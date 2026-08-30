"""HTML 黑盒验证器：只经 HTTP 验证编译制品的包级真实场景。"""
from __future__ import annotations

import argparse
import copy
import hashlib
import ipaddress
import json
import os
import queue
import re
import shutil
import signal
import subprocess
import sys
import threading
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

系统根 = Path(__file__).resolve().parents[2]
if str(系统根) not in sys.path:
    sys.path.insert(0, str(系统根))

# P1-37：工作区指纹只消费编译控制面的单一实现，不在本验证器复制算法。
from 开发工具.项目编译.项目编译器 import _来源指纹 as _编译来源指纹

验证版本 = "3.0.0"
场景契约版本 = "验证场景/v1"
默认并发 = 8
默认超时秒 = 15
默认启动超时秒 = 20
固定端口 = 45080
请求上限字节 = 1024 * 1024
输出上限字节 = 64 * 1024
场景文件名 = "验证场景.json"
统一返回字段 = ("成功", "值", "错误码", "错误说明", "请求id", "耗时毫秒")
未指定 = object()


@dataclass
class 验证场景:
    """由正式包的验证场景引用声明的一次真实请求及其断言。"""

    场景id: str
    能力id: str
    方法: str = "POST"
    路径: str = "/网关/调用"
    参数: dict[str, Any] = field(default_factory=dict)
    预期状态码: int = 200
    预期成功: bool = True
    预期错误码: str = ""
    预期包含: str = ""
    预期值类型: str = ""
    预期关键值: dict[str, Any] = field(default_factory=dict)
    预期返回契约: dict[str, Any] = field(default_factory=dict)
    预期值: Any = None
    校验完整值: bool = False
    说明: str = ""
    制品摘要: str = ""
    步骤id: str = ""

    def 转字典(self) -> dict[str, Any]:
        预期: dict[str, Any] = {
            "成功": self.预期成功,
            "状态码": self.预期状态码,
        }
        if self.预期错误码:
            预期["错误码"] = self.预期错误码
        if self.预期包含:
            预期["包含"] = self.预期包含
        if self.预期值类型:
            预期["值类型"] = self.预期值类型
        if self.预期关键值:
            预期["关键值"] = self.预期关键值
        if self.预期返回契约:
            预期["返回契约"] = self.预期返回契约
        if self.校验完整值:
            预期["值"] = self.预期值
        return {
            "场景id": self.场景id,
            "能力id": self.能力id,
            "方法": self.方法,
            "路径": self.路径,
            "参数": self.参数,
            "预期": 预期,
            "说明": self.说明,
            "制品摘要": self.制品摘要,
        }

    @classmethod
    def 从字典(cls, 数据: dict[str, Any]) -> 验证场景:
        if not isinstance(数据, dict):
            raise ValueError("验证场景必须是对象")
        场景id = 数据.get("场景id")
        能力id = 数据.get("能力id")
        if not isinstance(场景id, str) or not 场景id.strip():
            raise ValueError("验证场景缺少场景id")
        if not isinstance(能力id, str) or not 能力id.strip():
            raise ValueError(f"验证场景 {场景id} 缺少能力id")
        方法 = 数据.get("方法", "POST")
        路径 = 数据.get("路径", "/网关/调用")
        参数 = 数据.get("参数", {})
        预期 = 数据.get("预期")
        if not isinstance(方法, str) or 方法.upper() not in {"GET", "POST"}:
            raise ValueError(f"验证场景 {场景id} 方法不合法")
        if not isinstance(路径, str) or not 路径.startswith("/"):
            raise ValueError(f"验证场景 {场景id} 路径不合法")
        if not isinstance(参数, dict):
            raise ValueError(f"验证场景 {场景id} 参数必须是对象")
        if not isinstance(预期, dict) or type(预期.get("成功")) is not bool:
            raise ValueError(f"验证场景 {场景id} 必须声明预期.成功布尔值")
        预期成功 = 预期["成功"]
        预期状态码 = 预期.get("状态码", 200 if 预期成功 else 0)
        if type(预期状态码) is not int or not 0 <= 预期状态码 <= 599:
            raise ValueError(f"验证场景 {场景id} 预期状态码不合法")
        错误码 = 预期.get("错误码", "")
        if not isinstance(错误码, str) or (not 预期成功 and not 错误码):
            raise ValueError(f"验证场景 {场景id} 负向场景必须声明错误码")
        关键值 = 预期.get("关键值", {})
        返回契约 = 预期.get("返回契约", {})
        if not isinstance(关键值, dict) or not isinstance(返回契约, dict):
            raise ValueError(f"验证场景 {场景id} 关键值/返回契约必须是对象")
        有业务断言 = any(("值" in 预期, bool(预期.get("值类型")), bool(关键值), bool(返回契约)))
        if 预期成功 and not 有业务断言:
            raise ValueError(f"验证场景 {场景id} 的真实成功场景缺少值/类型/关键值断言")
        return cls(
            场景id=场景id.strip(),
            能力id=能力id.strip(),
            方法=方法.upper(),
            路径=路径,
            参数=参数,
            预期状态码=预期状态码,
            预期成功=预期成功,
            预期错误码=错误码,
            预期包含=str(预期.get("包含", "")),
            预期值类型=str(预期.get("值类型", "")),
            预期关键值=关键值,
            预期返回契约=返回契约,
            预期值=预期.get("值"),
            校验完整值="值" in 预期,
            说明=str(数据.get("说明", "")),
            制品摘要=str(数据.get("制品摘要", "")),
        )


@dataclass
class 验证步骤:
    """一个严格绑定真实能力调用、预期状态和返回断言的有序步骤。"""

    步骤id: str
    能力id: str
    参数: dict[str, Any] = field(default_factory=dict)
    预期状态码: int = 200
    预期成功: bool = True
    预期错误码: str = ""
    预期包含: str = ""
    预期值类型: str = ""
    预期关键值: dict[str, Any] = field(default_factory=dict)
    预期返回契约: dict[str, Any] = field(default_factory=dict)
    预期值: Any = None
    校验完整值: bool = False
    制品摘要: str = ""

    def 转字典(self) -> dict[str, Any]:
        断言: dict[str, Any] = {}
        if self.预期错误码:
            断言["错误码"] = self.预期错误码
        if self.预期包含:
            断言["包含"] = self.预期包含
        if self.预期值类型:
            断言["值类型"] = self.预期值类型
        if self.预期关键值:
            断言["关键值"] = self.预期关键值
        if self.预期返回契约:
            断言.update(self.预期返回契约)
        if self.校验完整值:
            断言["值"] = self.预期值
        return {
            "步骤id": self.步骤id,
            "能力id": self.能力id,
            "参数": self.参数,
            "预期": {"成功": self.预期成功, "状态码": self.预期状态码, "返回断言": 断言},
        }

    @classmethod
    def 从字典(cls, 数据: Any, 场景id: str) -> 验证步骤:
        if not isinstance(数据, dict):
            raise ValueError(f"场景 {场景id} 的步骤必须是对象")
        多余 = set(数据) - {"步骤id", "能力id", "参数", "预期"}
        if 多余:
            raise ValueError(f"场景 {场景id} 步骤含未授权字段: {sorted(多余)}")
        步骤id = 数据.get("步骤id")
        能力id = 数据.get("能力id")
        参数 = 数据.get("参数", {})
        预期 = 数据.get("预期")
        if not isinstance(步骤id, str) or not 步骤id.strip():
            raise ValueError(f"场景 {场景id} 的步骤缺少步骤id")
        if not isinstance(能力id, str) or not 能力id.strip():
            raise ValueError(f"场景 {场景id} 步骤 {步骤id} 缺少真实能力id")
        if not isinstance(参数, dict):
            raise ValueError(f"场景 {场景id} 步骤 {步骤id} 参数必须是对象")
        if not isinstance(预期, dict) or set(预期) != {"成功", "状态码", "返回断言"}:
            raise ValueError(f"场景 {场景id} 步骤 {步骤id} 必须声明预期成功/状态码/返回断言")
        if type(预期["成功"]) is not bool:
            raise ValueError(f"场景 {场景id} 步骤 {步骤id} 预期成功必须是布尔值")
        if type(预期["状态码"]) is not int or not 100 <= 预期["状态码"] <= 599:
            raise ValueError(f"场景 {场景id} 步骤 {步骤id} 状态码不合法")
        断言 = 预期["返回断言"]
        if not isinstance(断言, dict) or not 断言:
            raise ValueError(f"场景 {场景id} 步骤 {步骤id} 返回断言不可为空")
        允许断言 = {"错误码", "包含", "值类型", "关键值", "必需字段", "字段类型", "值"}
        if set(断言) - 允许断言:
            raise ValueError(f"场景 {场景id} 步骤 {步骤id} 返回断言含未知字段")
        关键值 = 断言.get("关键值", {})
        必需字段 = 断言.get("必需字段", [])
        字段类型 = 断言.get("字段类型", {})
        if not isinstance(关键值, dict) or not isinstance(必需字段, list) or not isinstance(字段类型, dict):
            raise ValueError(f"场景 {场景id} 步骤 {步骤id} 返回断言结构不合法")
        错误码 = 断言.get("错误码", "")
        if not isinstance(错误码, str) or (not 预期["成功"] and not 错误码):
            raise ValueError(f"场景 {场景id} 步骤 {步骤id} 负向断言必须声明错误码")
        返回契约 = {}
        if "必需字段" in 断言:
            返回契约["必需字段"] = 必需字段
        if "字段类型" in 断言:
            返回契约["字段类型"] = 字段类型
        return cls(
            步骤id=步骤id.strip(), 能力id=能力id.strip(), 参数=copy.deepcopy(参数),
            预期状态码=预期["状态码"], 预期成功=预期["成功"], 预期错误码=错误码,
            预期包含=str(断言.get("包含", "")), 预期值类型=str(断言.get("值类型", "")),
            预期关键值=copy.deepcopy(关键值), 预期返回契约=返回契约,
            预期值=copy.deepcopy(断言.get("值")), 校验完整值="值" in 断言,
        )


@dataclass
class 多步骤验证场景:
    场景id: str
    包目录: Path
    前置步骤: list[验证步骤] = field(default_factory=list)
    目标步骤: list[验证步骤] = field(default_factory=list)
    清理步骤: list[验证步骤] = field(default_factory=list)

    @property
    def 步骤总数(self) -> int:
        return len(self.前置步骤) + len(self.目标步骤) + len(self.清理步骤)

    def 转字典(self, 制品目录: Path | None = None) -> dict[str, Any]:
        数据 = {
            "场景id": self.场景id,
            "前置步骤": [步骤.转字典() for 步骤 in self.前置步骤],
            "目标步骤": [步骤.转字典() for 步骤 in self.目标步骤],
            "清理步骤": [步骤.转字典() for 步骤 in self.清理步骤],
        }
        if 制品目录 is not None:
            数据["包相对目录"] = self.包目录.resolve().relative_to(制品目录.resolve()).as_posix()
        return 数据


@dataclass
class 验证场景束:
    场景列表: list[多步骤验证场景]
    目标能力全集: set[str]
    制品摘要: str

    @property
    def 步骤总数(self) -> int:
        return sum(场景.步骤总数 for 场景 in self.场景列表)

    def __len__(self) -> int:
        return sum(len(场景.目标步骤) for 场景 in self.场景列表)

    def __iter__(self):
        for 场景 in self.场景列表:
            yield from 场景.目标步骤

    def __getitem__(self, 索引: int) -> 验证步骤:
        return list(iter(self))[索引]


@dataclass
class 验证结果:
    场景id: str
    能力id: str
    通过: bool = False
    状态码: int = 0
    返回: dict[str, Any] = field(default_factory=dict)
    耗时毫秒: float = 0
    失败原因: str = ""
    定位线索: str = ""
    步骤id: str = ""
    步骤类型: str = ""

    def 转字典(self) -> dict[str, Any]:
        return {
            "场景id": self.场景id,
            "能力id": self.能力id,
            "通过": self.通过,
            "状态码": self.状态码,
            "返回": self.返回,
            "耗时毫秒": self.耗时毫秒,
            "失败原因": self.失败原因,
            "定位线索": self.定位线索,
            "步骤id": self.步骤id,
            "步骤类型": self.步骤类型,
        }


@dataclass
class 验证报告:
    制品路径: str = ""
    制品摘要前: dict[str, Any] = field(default_factory=dict)
    制品摘要后: dict[str, Any] = field(default_factory=dict)
    场景总数: int = 0
    通过数: int = 0
    失败数: int = 0
    正向成功数: int = 0
    负向校验数: int = 0
    并发峰值: int = 0
    结果列表: list[验证结果] = field(default_factory=list)
    资源回收: dict[str, Any] = field(default_factory=dict)
    场景制品摘要: str = ""
    时间: str = ""
    证据绑定: dict[str, Any] = field(default_factory=dict)
    目标能力数: int = 0
    步骤总数: int = 0
    清理失败数: int = 0
    资源残留数: int = 0
    资源残留: list[str] = field(default_factory=list)
    目标能力全集: list[str] = field(default_factory=list)
    正向目标能力全集: list[str] = field(default_factory=list)
    实际成功目标能力全集: list[str] = field(default_factory=list)

    @property
    def 制品指纹(self) -> dict[str, Any]:
        """兼容旧调用方；新证据以全文件摘要前后为准。"""
        return self.制品摘要前

    def 转字典(self) -> dict[str, Any]:
        return {
            "制品路径": self.制品路径,
            "制品摘要前": self.制品摘要前,
            "制品摘要后": self.制品摘要后,
            "场景总数": self.场景总数,
            "通过数": self.通过数,
            "失败数": self.失败数,
            "正向成功数": self.正向成功数,
            "负向校验数": self.负向校验数,
            "并发峰值": self.并发峰值,
            "结果列表": [结果.转字典() for 结果 in self.结果列表],
            "资源回收": self.资源回收,
            "场景制品摘要": self.场景制品摘要,
            "时间": self.时间,
            "证据绑定": self.证据绑定,
            "目标能力数": self.目标能力数,
            "步骤总数": self.步骤总数,
            "清理失败数": self.清理失败数,
            "资源残留数": self.资源残留数,
            "资源残留": self.资源残留,
            "目标能力全集": self.目标能力全集,
            "正向目标能力全集": self.正向目标能力全集,
            "实际成功目标能力全集": self.实际成功目标能力全集,
        }

    def 汇总(self) -> str:
        if self.场景总数 <= 0:
            return "阻断: 无任何有效验证场景（禁止零验证成功）"
        if self.失败数:
            return (f"失败: {self.失败数} 项未通过；目标能力 {self.目标能力数}，步骤 {self.步骤总数}，"
                    f"清理失败 {self.清理失败数}，资源残留 {self.资源残留数}")
        return (f"通过: 目标能力 {self.目标能力数}，步骤 {self.步骤总数}；"
                f"清理失败 {self.清理失败数}，资源残留 {self.资源残留数}")


def _工作区指纹(排除目录: Path | None = None) -> dict[str, str]:
    """复用项目编译控制面的唯一来源指纹实现。"""
    结果 = dict(_编译来源指纹(排除目录))
    结果["验证器版本"] = 验证版本
    结果["指纹实现"] = "开发工具.项目编译.项目编译器._来源指纹"
    return 结果


def _制品全文件摘要(制品目录: Path) -> dict[str, Any]:
    """摘要制品目录内全部普通文件，路径、类型和内容共同参与绑定。"""
    if not 制品目录.is_dir():
        raise ValueError(f"制品目录不存在: {制品目录}")
    文件清单: list[dict[str, Any]] = []
    汇总 = hashlib.sha256()
    for 文件 in sorted(制品目录.rglob("*"), key=lambda 路径: 路径.relative_to(制品目录).as_posix()):
        if not 文件.is_file():
            continue
        相对 = 文件.relative_to(制品目录).as_posix()
        内容摘要 = hashlib.sha256(文件.read_bytes()).hexdigest()
        项 = {"路径": 相对, "字节数": 文件.stat().st_size, "sha256": 内容摘要}
        文件清单.append(项)
        汇总.update(相对.encode("utf-8"))
        汇总.update(b"\0")
        汇总.update(str(项["字节数"]).encode("ascii"))
        汇总.update(b"\0")
        汇总.update(内容摘要.encode("ascii"))
        汇总.update(b"\0")
    return {
        "摘要算法": "sha256-全文件-v1",
        "文件数": len(文件清单),
        "文件清单": 文件清单,
        "制品摘要": 汇总.hexdigest(),
    }


def _找启动器(制品目录: Path) -> Path:
    候选 = [
        制品目录 / "运行入口" / "启动.py",
        制品目录 / "运行入口" / "独立HTML启动器.py",
        制品目录 / "运行入口" / "启动器.py",
    ]
    for 路径 in 候选:
        if 路径.is_file():
            return 路径
    入口目录 = 制品目录 / "运行入口"
    if 入口目录.is_dir():
        for 路径 in sorted(入口目录.rglob("*.py")):
            if "启动" in 路径.name or "入口" in 路径.name:
                return 路径
    raise FileNotFoundError(f"制品目录找不到启动器: {制品目录}")


def _读取JSON严格(路径: Path, 名称: str) -> Any:
    try:
        return json.loads(路径.read_text(encoding="utf-8"))
    except FileNotFoundError as 错误:
        raise ValueError(f"缺少{名称}: {路径}") from 错误
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as 错误:
        raise ValueError(f"{名称}JSON不合法: {路径}: {错误}") from 错误


def _扫描公开能力(制品目录: Path) -> tuple[set[str], list[Path]]:
    """只消费统一正式包索引，再严格对账 owner 包的声明与能力契约。"""
    from 开发工具.项目编译.正式包索引 import 构建索引

    制品目录 = Path(制品目录)
    直接能力根 = any((制品目录 / 名称).is_dir() for 名称 in ("模块库", "支持库"))
    平台客户端根 = 制品目录 / "平台客户端"
    嵌套能力根 = any((平台客户端根 / 名称).is_dir() for 名称 in ("模块库", "支持库"))
    if 直接能力根 and 嵌套能力根:
        raise ValueError("制品同时存在顶层与平台客户端嵌套能力根，拒绝双事实源")
    扫描根 = 平台客户端根 if 嵌套能力根 else 制品目录
    索引 = 构建索引(扫描根)
    if 索引["能力冲突"]:
        raise ValueError(f"公开能力 owner 冲突: {索引['能力冲突']}")
    能力所有者: dict[str, str] = dict(索引["能力所有者"])
    if not 能力所有者:
        raise ValueError("制品无任何公开能力契约")
    全部包 = {**索引["支持库"], **索引["模块库"]}
    owner包id表 = sorted(set(能力所有者.values()))
    包目录表: list[Path] = []
    契约全集: set[str] = set()
    for 包id in owner包id表:
        if 包id.startswith("冲突:") or 包id not in 全部包:
            raise ValueError(f"公开能力 owner 不合法: {包id}")
        包目录, 声明 = 全部包[包id]
        包目录表.append(包目录)
        声明路径 = 包目录 / "包声明.json"
        if not isinstance(声明, dict) or not isinstance(声明.get("能力"), list):
            raise ValueError(f"包声明契约不合法: {声明路径}")
        本包声明: set[str] = set()
        for 条目 in 声明["能力"]:
            if not isinstance(条目, dict) or not isinstance(条目.get("能力id"), str) or not 条目["能力id"].strip():
                raise ValueError(f"包声明缺能力id: {声明路径}")
            能力id = 条目["能力id"].strip()
            if 能力id in 本包声明:
                raise ValueError(f"包内重复公开能力id: {能力id}")
            本包声明.add(能力id)
        owner能力 = {能力id for 能力id, owner in 能力所有者.items() if owner == 包id}
        if 本包声明 != owner能力:
            raise ValueError(
                f"包声明与统一 owner 索引差集: {包目录}; "
                f"仅声明={sorted(本包声明 - owner能力)} 仅owner={sorted(owner能力 - 本包声明)}"
            )
        契约路径 = 包目录 / "能力契约" / "参数契约.json"
        契约 = _读取JSON严格(契约路径, "能力契约")
        if not isinstance(契约, dict) or not isinstance(契约.get("能力契约"), list):
            raise ValueError(f"能力契约结构不合法: {契约路径}")
        本包契约: set[str] = set()
        for 条目 in 契约["能力契约"]:
            if not isinstance(条目, dict) or not isinstance(条目.get("能力id"), str) or not 条目["能力id"].strip():
                raise ValueError(f"能力契约缺能力id: {契约路径}")
            能力id = 条目["能力id"].strip()
            if 能力id in 本包契约 or 能力id in 契约全集:
                raise ValueError(f"重复能力契约id: {能力id}")
            本包契约.add(能力id)
            契约全集.add(能力id)
        if 本包声明 != 本包契约:
            raise ValueError(
                f"包声明与能力契约差集: {包目录}; "
                f"仅声明={sorted(本包声明 - 本包契约)} 仅契约={sorted(本包契约 - 本包声明)}"
            )
    公开能力 = set(能力所有者)
    if 公开能力 != 契约全集:
        raise ValueError("统一正式包索引与能力契约全集不一致")
    return 公开能力, 包目录表


def _解析场景引用(包目录: Path) -> list[tuple[dict[str, Any], Path]]:
    """读取唯一 v1 契约；旧的一请求一场景格式直接阻断。"""
    引用路径 = 包目录 / "验证场景引用.json"
    数据 = _读取JSON严格(引用路径, "验证场景引用")
    if not isinstance(数据, dict) or 数据.get("契约版本") != 场景契约版本:
        raise ValueError(f"验证场景引用契约版本不合法或为旧格式: {引用路径}")
    if set(数据) != {"契约版本", "验证场景引用"} or not isinstance(数据.get("验证场景引用"), list):
        raise ValueError(f"验证场景引用契约不合法: {引用路径}")
    原始列表 = 数据["验证场景引用"]
    if not 原始列表:
        raise ValueError(f"验证场景引用为空: {引用路径}")
    场景表: list[tuple[dict[str, Any], Path]] = []
    for 序号, 引用 in enumerate(原始列表):
        if not isinstance(引用, dict) or not ({"场景"} <= set(引用) or {"场景文件"} <= set(引用)):
            raise ValueError(f"无效或旧格式验证场景引用: {引用路径}#{序号}")
        if "场景" in 引用:
            if set(引用) != {"场景"} or not isinstance(引用["场景"], dict):
                raise ValueError(f"内联场景引用不合法: {引用路径}#{序号}")
            场景表.append((引用["场景"], 包目录))
            continue
        if set(引用) - {"场景文件", "场景id"}:
            raise ValueError(f"场景文件引用含未知字段: {引用路径}#{序号}")
        相对 = 引用.get("场景文件")
        if not isinstance(相对, str) or not 相对:
            raise ValueError(f"场景文件引用不合法: {引用路径}#{序号}")
        文件 = _安全合并路径(包目录, 相对, "场景文件")
        场景数据 = _读取JSON严格(文件, "验证场景")
        if (not isinstance(场景数据, dict) or 场景数据.get("契约版本") != 场景契约版本
                or set(场景数据) != {"契约版本", "验证场景"}
                or not isinstance(场景数据.get("验证场景"), list)):
            raise ValueError(f"验证场景文件契约不合法或为旧格式: {文件}")
        引用id = 引用.get("场景id")
        命中 = [项 for 项 in 场景数据["验证场景"]
              if isinstance(项, dict) and (not 引用id or 项.get("场景id") == 引用id)]
        if not 命中:
            raise ValueError(f"场景文件没有命中引用: {文件}#{引用id}")
        场景表.extend((项, 包目录) for 项 in 命中)
    return 场景表


def _安全合并路径(根: Path, 相对: str, 名称: str) -> Path:
    if not isinstance(相对, str) or not 相对 or Path(相对).is_absolute() or re.match(r"^[A-Za-z]:[\\/]", 相对):
        raise ValueError(f"{名称}路径不合法: {相对!r}")
    路径 = (根 / 相对).resolve()
    try:
        路径.relative_to(根.resolve())
    except ValueError as 错误:
        raise ValueError(f"{名称}越出包目录或受管目录: {相对}") from 错误
    return 路径


def _校验动态声明(值: Any, 场景id: str, 已出现步骤: set[str]) -> None:
    if isinstance(值, list):
        for 项 in 值:
            _校验动态声明(项, 场景id, 已出现步骤)
        return
    if not isinstance(值, dict):
        if isinstance(值, str) and (Path(值).is_absolute() or ".." in Path(值).parts
                                  or re.match(r"^[A-Za-z]:[\\/]", 值)):
            raise ValueError(f"场景 {场景id} 禁止静态绝对路径或路径逃逸")
        return
    if "$动态" not in 值:
        for 项 in 值.values():
            _校验动态声明(项, 场景id, 已出现步骤)
        return
    类型 = 值.get("$动态")
    允许字段 = {
        "制品根": {"$动态", "相对路径"},
        "受管临时目录": {"$动态", "相对路径"},
        "夹具文件复制": {"$动态", "来源", "目标"},
        "步骤返回": {"$动态", "步骤id", "JSON路径"},
    }
    if 类型 not in 允许字段 or set(值) != 允许字段[类型]:
        raise ValueError(f"场景 {场景id} 动态值声明不合法: {类型!r}")
    if 类型 == "步骤返回":
        if 值.get("步骤id") not in 已出现步骤 or not isinstance(值.get("JSON路径"), str):
            raise ValueError(f"场景 {场景id} 动态引用缺失或不是前序步骤: {值.get('步骤id')}")
    else:
        for 字段 in 允许字段[类型] - {"$动态"}:
            if not isinstance(值.get(字段), str) or not 值[字段]:
                raise ValueError(f"场景 {场景id} 动态路径字段不合法: {字段}")


def _解析多步骤场景(原始: Any, 包目录: Path, 制品摘要: str) -> 多步骤验证场景:
    if not isinstance(原始, dict):
        raise ValueError("验证场景必须是对象")
    if set(原始) != {"场景id", "前置步骤", "目标步骤", "清理步骤"}:
        raise ValueError("验证场景字段不完整或为旧格式")
    场景id = 原始.get("场景id")
    if not isinstance(场景id, str) or not 场景id.strip():
        raise ValueError("验证场景缺少场景id")
    for 阶段 in ("前置步骤", "目标步骤", "清理步骤"):
        if not isinstance(原始[阶段], list):
            raise ValueError(f"场景 {场景id} 的{阶段}必须是列表")
    if not 原始["目标步骤"]:
        raise ValueError(f"场景 {场景id} 必须至少有一个目标步骤")
    已出现: set[str] = set()
    分段: dict[str, list[验证步骤]] = {}
    for 阶段 in ("前置步骤", "目标步骤", "清理步骤"):
        步骤表: list[验证步骤] = []
        for 步骤原始 in 原始[阶段]:
            步骤 = 验证步骤.从字典(步骤原始, 场景id)
            if 步骤.步骤id in 已出现:
                raise ValueError(f"场景 {场景id} 重复步骤id: {步骤.步骤id}")
            _校验动态声明(步骤.参数, 场景id, 已出现)
            步骤.制品摘要 = 制品摘要
            步骤表.append(步骤)
            已出现.add(步骤.步骤id)
        分段[阶段] = 步骤表
    return 多步骤验证场景(
        场景id.strip(), 包目录.resolve(), 分段["前置步骤"], 分段["目标步骤"], 分段["清理步骤"],
    )


def _校验场景全集(
    公开能力: set[str], 场景原始表: list[tuple[dict[str, Any], Path]], 制品摘要: str,
) -> 验证场景束:
    if not 场景原始表:
        raise ValueError("无任何有效验证场景")
    场景列表: list[多步骤验证场景] = []
    场景id集合: set[str] = set()
    全步骤能力: set[str] = set()
    for 原始, 包目录 in 场景原始表:
        场景 = _解析多步骤场景(原始, 包目录, 制品摘要)
        if 场景.场景id in 场景id集合:
            raise ValueError(f"重复场景id: {场景.场景id}")
        场景id集合.add(场景.场景id)
        场景列表.append(场景)
        全步骤能力.update(步骤.能力id for 阶段 in (场景.前置步骤, 场景.目标步骤, 场景.清理步骤) for 步骤 in 阶段)
    未公开 = 全步骤能力 - 公开能力
    if 未公开:
        raise ValueError(f"步骤绑定了非正式公开能力: {sorted(未公开)}")
    正向目标能力 = {
        步骤.能力id for 场景 in 场景列表 for 步骤 in 场景.目标步骤 if 步骤.预期成功
    }
    if 正向目标能力 != 公开能力:
        raise ValueError(
            "正式公开能力全集 != 正向目标步骤能力全集: "
            f"缺目标={sorted(公开能力 - 正向目标能力)} 多目标={sorted(正向目标能力 - 公开能力)}"
        )
    return 验证场景束(场景列表, set(公开能力), 制品摘要)


def _扫描能力契约(制品目录: Path) -> list[dict[str, Any]]:
    """兼容查询入口：返回严格校验后的公开能力 id。"""
    能力, _ = _扫描公开能力(制品目录)
    return [{"能力id": 能力id} for 能力id in sorted(能力)]


def _加载场景(制品目录: Path, 场景路径: Path | None) -> 验证场景束:
    公开能力, 包目录表 = _扫描公开能力(制品目录)
    摘要 = _制品全文件摘要(制品目录)["制品摘要"]
    if 场景路径 is None:
        原始表 = [条目 for 包目录 in 包目录表 for 条目 in _解析场景引用(包目录)]
    else:
        束 = _读取JSON严格(场景路径, "外部验证场景束")
        if not isinstance(束, dict) or 束.get("来源") != "包级验证场景引用":
            raise ValueError("外部场景束来源必须是包级验证场景引用")
        if 束.get("制品摘要") != 摘要:
            raise ValueError(f"外部场景束制品摘要不匹配: {束.get('制品摘要')} != {摘要}")
        if 束.get("契约版本") != 场景契约版本 or not isinstance(束.get("验证场景"), list):
            raise ValueError("外部场景束契约版本不合法或为旧格式")
        原始表 = []
        for 原始 in 束["验证场景"]:
            if not isinstance(原始, dict) or not isinstance(原始.get("包相对目录"), str):
                raise ValueError("外部场景束缺包相对目录")
            包目录 = _安全合并路径(制品目录, 原始["包相对目录"], "包相对目录")
            场景数据 = {键: 值 for 键, 值 in 原始.items() if 键 != "包相对目录"}
            原始表.append((场景数据, 包目录))
    return _校验场景全集(公开能力, 原始表, 摘要)


def _扫描制品能力(制品目录: Path) -> list[dict[str, Any]]:
    场景束 = _加载场景(制品目录, None)
    return [场景.转字典(制品目录) for 场景 in 场景束.场景列表]


def _校验直连地址(地址: str) -> str:
    if not isinstance(地址, str) or not 地址:
        raise ValueError("直连地址不能为空")
    try:
        拆分 = urllib.parse.urlsplit(地址)
        主机 = 拆分.hostname
        端口 = 拆分.port
    except ValueError as 错误:
        raise ValueError(f"直连地址不合法: {地址}") from 错误
    if 拆分.scheme != "http" or not 主机 or 端口 is None:
        raise ValueError("直连地址必须是带显式端口的 HTTP 回环 URL")
    try:
        if not ipaddress.ip_address(主机).is_loopback:
            raise ValueError("直连地址必须使用 IP 回环地址")
    except ValueError as 错误:
        raise ValueError("直连地址必须使用 IP 回环地址，不能使用主机名") from 错误
    if 拆分.username or 拆分.password or 拆分.path not in {"", "/"} or 拆分.query or 拆分.fragment:
        raise ValueError("直连地址不得包含凭据、业务路径、查询或片段")
    return 地址.rstrip("/")


def _检查端口可用(端口: int) -> tuple[bool, str]:
    import socket
    测试 = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        测试.bind(("127.0.0.1", 端口))
        return True, ""
    except OSError as 错误:
        return False, f"端口 {端口} 已被占用: {错误}"
    finally:
        测试.close()


class _有界输出:
    def __init__(self, 上限字节: int) -> None:
        self.上限 = max(128, int(上限字节))
        self.内容 = bytearray()
        self.锁 = threading.Lock()

    def 追加(self, 数据: bytes) -> None:
        with self.锁:
            self.内容.extend(数据)
            if len(self.内容) > self.上限:
                del self.内容[:len(self.内容) - self.上限]

    def 文本(self) -> str:
        with self.锁:
            return bytes(self.内容).decode("utf-8", errors="replace")


def _读取管道(管道: Any, 缓冲: _有界输出, 事件: queue.Queue[None]) -> None:
    try:
        while True:
            数据 = os.read(管道.fileno(), 4096)
            if not 数据:
                break
            缓冲.追加(数据)
            try:
                事件.put_nowait(None)
            except queue.Full:
                pass
    except (OSError, ValueError):
        pass


def _进程组活跃(进程组id: int) -> bool:
    if os.name != "posix":
        return False
    try:
        结果 = subprocess.run(
            ["ps", "-axo", "pgid=,stat="], capture_output=True, text=True, timeout=2, check=False,
        )
        for 行 in 结果.stdout.splitlines():
            部分 = 行.strip().split(None, 1)
            if len(部分) == 2 and int(部分[0]) == 进程组id and not 部分[1].startswith("Z"):
                return True
        return False
    except (OSError, ValueError, subprocess.TimeoutExpired):
        try:
            os.killpg(进程组id, 0)
            return True
        except (ProcessLookupError, PermissionError):
            return False


def _回收进程组(进程: subprocess.Popen[Any] | None) -> dict[str, Any]:
    if 进程 is None:
        return {"已回收": True, "模式": "直连", "进程组残留": False}
    进程组id: int | None = None
    if os.name == "posix":
        try:
            进程组id = os.getpgid(进程.pid)
        except ProcessLookupError:
            pass
    if 进程.poll() is None or (进程组id is not None and _进程组活跃(进程组id)):
        try:
            if 进程组id is not None:
                os.killpg(进程组id, signal.SIGTERM)
            else:
                进程.terminate()
        except ProcessLookupError:
            pass
        截止 = time.monotonic() + 2
        while time.monotonic() < 截止:
            if 进程.poll() is not None and (进程组id is None or not _进程组活跃(进程组id)):
                break
            time.sleep(0.03)
        if 进程.poll() is None or (进程组id is not None and _进程组活跃(进程组id)):
            try:
                if 进程组id is not None:
                    os.killpg(进程组id, signal.SIGKILL)
                else:
                    进程.kill()
            except ProcessLookupError:
                pass
    try:
        进程.wait(timeout=2)
    except subprocess.TimeoutExpired:
        try:
            进程.kill()
        except ProcessLookupError:
            pass
        try:
            进程.wait(timeout=2)
        except subprocess.TimeoutExpired:
            pass
    残留 = bool(进程组id is not None and _进程组活跃(进程组id))
    for 管道 in (进程.stdin, 进程.stdout, 进程.stderr):
        if 管道 is not None and not 管道.closed:
            try:
                管道.close()
            except (OSError, ValueError):
                pass
    return {
        "已回收": 进程.poll() is not None and not 残留,
        "模式": "独立进程组" if 进程组id is not None else "单进程",
        "pid": 进程.pid,
        "进程组id": 进程组id,
        "退出码": 进程.poll(),
        "进程组残留": 残留,
    }


def _启动制品(
    启动器: Path,
    制品目录: Path,
    端口: int,
    启动超时秒: float = 默认启动超时秒,
    上限字节: int = 输出上限字节,
) -> tuple[subprocess.Popen[Any], int, dict[str, str]]:
    进程 = subprocess.Popen(
        [sys.executable, "-u", str(启动器), "--端口", str(端口), "--不自动打开"],
        cwd=str(制品目录),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=os.name == "posix",
    )
    标准输出 = _有界输出(上限字节)
    标准错误 = _有界输出(上限字节)
    事件: queue.Queue[None] = queue.Queue(maxsize=1)
    线程表 = [
        threading.Thread(target=_读取管道, args=(进程.stdout, 标准输出, 事件), daemon=True),
        threading.Thread(target=_读取管道, args=(进程.stderr, 标准错误, 事件), daemon=True),
    ]
    for 线程 in 线程表:
        线程.start()
    截止 = time.monotonic() + max(0.05, 启动超时秒)
    try:
        while time.monotonic() < 截止:
            文本 = 标准输出.文本()
            匹配 = re.search(r"127\.0\.0\.1:(\d+)", 文本)
            if 匹配 and ("已启动" in 文本 or "启动" in 文本):
                return 进程, int(匹配.group(1)), {"stdout": 文本, "stderr": 标准错误.文本()}
            if 进程.poll() is not None:
                raise RuntimeError(
                    f"制品启动失败(退出码={进程.returncode}): stdout={文本!r} stderr={标准错误.文本()!r}"
                )
            try:
                事件.get(timeout=min(0.05, max(0.001, 截止 - time.monotonic())))
            except queue.Empty:
                pass
        raise RuntimeError(
            f"制品启动超时({启动超时秒}s): stdout={标准输出.文本()!r} stderr={标准错误.文本()!r}"
        )
    except BaseException:
        _回收进程组(进程)
        raise


def _发送请求(地址: str, 场景: 验证场景, 超时秒: float) -> tuple[int, dict[str, Any], float]:
    开始 = time.monotonic()
    拆分 = urllib.parse.urlsplit(地址)
    基址 = f"{拆分.scheme}://{拆分.netloc}"
    路径 = 场景.路径 if 场景.路径.startswith("/") else "/" + 场景.路径
    目标 = 基址 + urllib.parse.quote(路径, safe="/:@._-")
    if 场景.方法 == "GET":
        请求 = urllib.request.Request(目标, method="GET")
    else:
        请求体 = {"能力id": 场景.能力id, "参数": 场景.参数}
        请求 = urllib.request.Request(
            目标,
            data=json.dumps(请求体, ensure_ascii=False).encode("utf-8"),
            method="POST",
            headers={"Content-Type": "application/json"},
        )
    try:
        with urllib.request.urlopen(请求, timeout=超时秒) as 响应:
            正文 = 响应.read(请求上限字节 + 1)
            if len(正文) > 请求上限字节:
                return 响应.status, {"成功": False, "错误码": "返回过大", "错误说明": "响应超过读取上限"}, (time.monotonic() - 开始) * 1000
            try:
                数据 = json.loads(正文.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                数据 = {"成功": False, "错误码": "返回非JSON", "错误说明": 正文[:200].decode("utf-8", errors="replace")}
            return 响应.status, 数据, (time.monotonic() - 开始) * 1000
    except urllib.error.HTTPError as 错误:
        try:
            正文 = 错误.read(请求上限字节 + 1)
            try:
                数据 = json.loads(正文[:请求上限字节].decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                数据 = {"成功": False, "错误码": "返回非JSON", "错误说明": 正文[:200].decode("utf-8", errors="replace")}
            return 错误.code, 数据, (time.monotonic() - 开始) * 1000
        finally:
            错误.close()
    except (urllib.error.URLError, TimeoutError, OSError) as 错误:
        return 502, {"成功": False, "错误码": "网关断开", "错误说明": str(错误)}, (time.monotonic() - 开始) * 1000


def _类型匹配(值: Any, 类型名: str) -> bool:
    映射 = {
        "字典型": lambda 项: isinstance(项, dict),
        "对象型": lambda 项: isinstance(项, dict),
        "列表型": lambda 项: isinstance(项, list),
        "文本型": lambda 项: isinstance(项, str),
        "字符串型": lambda 项: isinstance(项, str),
        "整数型": lambda 项: type(项) is int,
        "数值型": lambda 项: type(项) in {int, float},
        "浮点型": lambda 项: type(项) is float,
        "逻辑型": lambda 项: type(项) is bool,
        "布尔型": lambda 项: type(项) is bool,
        "空值型": lambda 项: 项 is None,
    }
    判断 = 映射.get(类型名)
    return bool(判断 and 判断(值))


def _取路径(值: Any, 路径: str) -> Any:
    当前 = 值
    if 路径 in {"", "$"}:
        return 当前
    for 段 in 路径.removeprefix("$.").split("."):
        if isinstance(当前, dict) and 段 in 当前:
            当前 = 当前[段]
        elif isinstance(当前, list) and 段.isdigit() and int(段) < len(当前):
            当前 = 当前[int(段)]
        else:
            return 未指定
    return 当前


def _校验统一返回(返回: Any) -> tuple[bool, str]:
    if not isinstance(返回, dict):
        return False, "返回必须是JSON对象"
    缺失 = [字段 for 字段 in 统一返回字段 if 字段 not in 返回]
    if 缺失:
        return False, f"统一返回缺字段: {缺失}"
    if type(返回["成功"]) is not bool:
        return False, "成功必须是真正布尔型"
    if "可重试" in 返回 and type(返回["可重试"]) is not bool:
        return False, "可重试存在时必须是真正布尔型"
    if not isinstance(返回["错误码"], str) or not isinstance(返回["错误说明"], str):
        return False, "错误码/错误说明必须是文本型"
    if not isinstance(返回["请求id"], str) or not 返回["请求id"]:
        return False, "请求id必须是非空文本"
    if type(返回["耗时毫秒"]) not in {int, float} or 返回["耗时毫秒"] < 0:
        return False, "耗时毫秒必须是非负数值"
    if 返回["成功"]:
        if 返回["值"] is None:
            return False, "成功结果的值不可为空"
        if 返回["错误码"] or 返回["错误说明"]:
            return False, "成功结果与错误字段互斥"
    else:
        if 返回["值"] is not None:
            return False, "错误结果的值必须为空"
        if not 返回["错误码"] or not 返回["错误说明"]:
            return False, "错误结果必须包含错误码和错误说明"
    return True, ""


def _判定(场景: 验证场景, 状态码: int, 返回: dict[str, Any]) -> tuple[bool, str, str]:
    合法, 原因 = _校验统一返回(返回)
    if not 合法:
        return False, 原因, "返回契约"
    if 场景.预期状态码 and 状态码 != 场景.预期状态码:
        return False, f"状态码 {状态码} != 预期 {场景.预期状态码}", "路由" if 状态码 in {404, 405} else "网关"
    if 返回["成功"] is not 场景.预期成功:
        return False, f"成功={返回['成功']} != 预期 {场景.预期成功}", "能力"
    if not 场景.预期成功:
        if 返回["错误码"] != 场景.预期错误码:
            return False, f"错误码 {返回['错误码']!r} != 预期 {场景.预期错误码!r}", "能力"
        return True, "", ""
    值 = 返回["值"]
    if 场景.预期值类型 and not _类型匹配(值, 场景.预期值类型):
        return False, f"值类型不符合 {场景.预期值类型}", "值"
    for 路径, 预期值 in 场景.预期关键值.items():
        实际 = _取路径(值, str(路径))
        if 实际 is 未指定 or 实际值不等于预期(实际, 预期值):
            return False, f"关键值 {路径}={实际!r} != {预期值!r}", "值"
    契约 = 场景.预期返回契约
    必需字段 = 契约.get("必需字段", []) if isinstance(契约, dict) else []
    字段类型 = 契约.get("字段类型", {}) if isinstance(契约, dict) else {}
    if not isinstance(必需字段, list) or not isinstance(字段类型, dict):
        return False, "返回契约的必需字段/字段类型格式不合法", "返回契约"
    for 路径 in 必需字段:
        if _取路径(值, str(路径)) is 未指定:
            return False, f"返回值缺少必需字段: {路径}", "返回契约"
    for 路径, 类型名 in 字段类型.items():
        实际 = _取路径(值, str(路径))
        if 实际 is 未指定 or not isinstance(类型名, str) or not _类型匹配(实际, 类型名):
            return False, f"返回字段 {路径} 类型不符合 {类型名}", "返回契约"
    if 场景.校验完整值 and 实际值不等于预期(值, 场景.预期值):
        return False, f"完整值 {值!r} != 预期 {场景.预期值!r}", "值"
    if 场景.预期包含 and 场景.预期包含 not in json.dumps(返回, ensure_ascii=False):
        return False, f"返回未包含预期子串: {场景.预期包含}", "值"
    return True, "", ""


def 实际值不等于预期(实际: Any, 预期: Any) -> bool:
    """严格比较，避免 bool 与 0/1 被 Python 相等语义混淆。"""
    return type(实际) is not type(预期) or 实际 != 预期


def 验证单个(地址: str, 场景: 验证场景, 超时秒: float = 默认超时秒) -> 验证结果:
    结果 = 验证结果(场景id=场景.场景id, 能力id=场景.能力id)
    try:
        状态码, 返回, 耗时 = _发送请求(地址, 场景, 超时秒)
        结果.状态码 = 状态码
        结果.返回 = 返回
        结果.耗时毫秒 = 耗时
        结果.通过, 结果.失败原因, 结果.定位线索 = _判定(场景, 状态码, 返回)
    except BaseException as 错误:
        结果.失败原因 = f"验证任务异常: {type(错误).__name__}: {错误}"
        结果.定位线索 = "验证器"
    return 结果


def _展开动态值(
    值: Any, *, 制品目录: Path, 包目录: Path, 临时目录: Path,
    步骤返回表: dict[str, dict[str, Any]],
) -> Any:
    """只展开冻结的四类动态值；文件写入只能落受管临时目录。"""
    if isinstance(值, list):
        return [_展开动态值(项, 制品目录=制品目录, 包目录=包目录,
                           临时目录=临时目录, 步骤返回表=步骤返回表) for 项 in 值]
    if not isinstance(值, dict):
        return 值
    if "$动态" not in 值:
        return {键: _展开动态值(项, 制品目录=制品目录, 包目录=包目录,
                              临时目录=临时目录, 步骤返回表=步骤返回表)
                for 键, 项 in 值.items()}
    类型 = 值["$动态"]
    if 类型 == "制品根":
        return str(_安全合并路径(制品目录, 值["相对路径"], "制品动态路径"))
    if 类型 == "受管临时目录":
        路径 = _安全合并路径(临时目录, 值["相对路径"], "临时动态路径")
        路径.mkdir(parents=True, exist_ok=True)
        return str(路径)
    if 类型 == "夹具文件复制":
        来源 = _安全合并路径(包目录, 值["来源"], "夹具来源")
        if not 来源.is_file():
            raise ValueError(f"夹具文件不存在: {来源}")
        目标 = _安全合并路径(临时目录, 值["目标"], "夹具目标")
        目标.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(来源, 目标)
        return str(目标)
    if 类型 == "步骤返回":
        步骤id = 值["步骤id"]
        if 步骤id not in 步骤返回表:
            raise ValueError(f"动态引用缺失: {步骤id}")
        结果值 = _取路径(步骤返回表[步骤id], 值["JSON路径"])
        if 结果值 is 未指定:
            raise ValueError(f"动态JSON路径不存在: {步骤id} {值['JSON路径']}")
        return copy.deepcopy(结果值)
    raise ValueError(f"未知动态值类型: {类型}")


def _执行场景束(
    制品目录: Path, 场景束: 验证场景束, 地址: str, *, 超时秒: float = 默认超时秒,
) -> 验证报告:
    """按场景执行前置→目标并finally清理；每个能力步骤只经正式HTTP通道。"""
    制品目录 = Path(制品目录).resolve()
    报告 = 验证报告(
        制品路径=str(制品目录), 场景总数=len(场景束),
        目标能力数=len(场景束.目标能力全集), 步骤总数=场景束.步骤总数,
        目标能力全集=sorted(场景束.目标能力全集), 场景制品摘要=场景束.制品摘要,
    )
    报告.制品摘要前 = _制品全文件摘要(制品目录)
    实际成功目标: set[str] = set()

    def 执行步骤(场景: 多步骤验证场景, 步骤: 验证步骤, 步骤类型: str,
                 临时根: Path, 返回表: dict[str, dict[str, Any]]) -> 验证结果:
        结果 = 验证结果(场景.场景id, 步骤.能力id, 步骤id=步骤.步骤id, 步骤类型=步骤类型)
        try:
            参数 = _展开动态值(
                步骤.参数, 制品目录=制品目录, 包目录=场景.包目录,
                临时目录=临时根, 步骤返回表=返回表,
            )
            请求场景 = 验证场景(
                场景id=f"{场景.场景id}.{步骤.步骤id}", 能力id=步骤.能力id,
                参数=参数, 预期状态码=步骤.预期状态码, 预期成功=步骤.预期成功,
                预期错误码=步骤.预期错误码, 预期包含=步骤.预期包含,
                预期值类型=步骤.预期值类型, 预期关键值=步骤.预期关键值,
                预期返回契约=步骤.预期返回契约, 预期值=步骤.预期值,
                校验完整值=步骤.校验完整值, 制品摘要=场景束.制品摘要,
                步骤id=步骤.步骤id,
            )
            状态码, 返回, 耗时 = _发送请求(地址, 请求场景, 超时秒)
            返回表[步骤.步骤id] = copy.deepcopy(返回)
            结果.状态码, 结果.返回, 结果.耗时毫秒 = 状态码, 返回, 耗时
            结果.通过, 结果.失败原因, 结果.定位线索 = _判定(请求场景, 状态码, 返回)
        except BaseException as 错误:
            结果.失败原因 = f"步骤执行异常: {type(错误).__name__}: {错误}"
            结果.定位线索 = "场景执行器"
        return 结果

    for 场景 in 场景束.场景列表:
        临时对象 = tempfile.TemporaryDirectory(prefix="HTML黑盒场景_")
        临时根 = Path(临时对象.name).resolve()
        返回表: dict[str, dict[str, Any]] = {}
        前置通过 = True
        try:
            for 步骤 in 场景.前置步骤:
                结果 = 执行步骤(场景, 步骤, "前置", 临时根, 返回表)
                报告.结果列表.append(结果)
                if not 结果.通过:
                    前置通过 = False
                    break
            if 前置通过:
                for 步骤 in 场景.目标步骤:
                    结果 = 执行步骤(场景, 步骤, "目标", 临时根, 返回表)
                    报告.结果列表.append(结果)
                    if 结果.通过 and 步骤.预期成功:
                        实际成功目标.add(步骤.能力id)
        finally:
            for 步骤 in 场景.清理步骤:
                结果 = 执行步骤(场景, 步骤, "清理", 临时根, 返回表)
                报告.结果列表.append(结果)
                if not 结果.通过:
                    报告.清理失败数 += 1
            临时对象.cleanup()
            if 临时根.exists():
                报告.资源残留.append(str(临时根))
    报告.资源残留数 = len(报告.资源残留)
    报告.实际成功目标能力全集 = sorted(实际成功目标)
    报告.正向目标能力全集 = sorted(场景束.目标能力全集)
    报告.通过数 = sum(结果.通过 for 结果 in 报告.结果列表)
    报告.失败数 = sum(not 结果.通过 for 结果 in 报告.结果列表)
    报告.正向成功数 = sum(
        结果.通过 and 结果.步骤类型 == "目标" for 结果 in 报告.结果列表
    )
    报告.负向校验数 = sum(
        结果.通过 and 结果.步骤类型 != "目标" for 结果 in 报告.结果列表
    )
    if 实际成功目标 != 场景束.目标能力全集:
        报告.结果列表.append(验证结果(
            "场景.实际覆盖", "", False,
            失败原因=f"实际成功目标能力全集不一致: 缺少={sorted(场景束.目标能力全集 - 实际成功目标)}",
            定位线索="覆盖对账",
        ))
        报告.失败数 += 1
    if 报告.资源残留数:
        报告.失败数 += 报告.资源残留数
    报告.制品摘要后 = _制品全文件摘要(制品目录)
    _校验制品前后绑定(报告)
    return 报告


def _校验制品前后绑定(报告: 验证报告) -> None:
    前 = 报告.制品摘要前.get("制品摘要")
    后 = 报告.制品摘要后.get("制品摘要")
    if (not 前 or not 后 or 前 != 后) and not any(
        结果.场景id == "制品.摘要绑定" for 结果 in 报告.结果列表
    ):
        报告.结果列表.append(验证结果(
            场景id="制品.摘要绑定",
            能力id="",
            通过=False,
            失败原因=f"制品全文件摘要前后不一致: {前} != {后}",
            定位线索="制品绑定",
        ))
        报告.失败数 += 1


def 验证全部(
    制品目录: Path,
    场景列表: list[验证场景] | 验证场景束,
    并发: int = 默认并发,
    超时秒: float = 默认超时秒,
    端口: int = 固定端口,
    自动打开: bool = False,
    直连地址: str = "",
    进程接收: Any = None,
) -> tuple[验证报告, int | None, Any]:
    del 自动打开
    if not 场景列表:
        raise ValueError("无任何有效验证场景")
    if type(并发) is not int or 并发 < 1:
        raise ValueError("并发必须是正整数")
    报告 = 验证报告(制品路径=str(制品目录), 场景总数=len(场景列表))
    报告.制品摘要前 = _制品全文件摘要(制品目录)
    当前摘要 = 报告.制品摘要前["制品摘要"]
    场景摘要集合 = ({场景列表.制品摘要} if isinstance(场景列表, 验证场景束)
                  else {场景.制品摘要 for 场景 in 场景列表})
    if 场景摘要集合 != {当前摘要}:
        报告.失败数 = 1
        报告.结果列表.append(验证结果(
            "场景.制品绑定", "", False, 0,
            失败原因=f"场景制品摘要未绑定当前制品: {sorted(场景摘要集合)} != {当前摘要}",
            定位线索="制品绑定",
        ))
        报告.制品摘要后 = _制品全文件摘要(制品目录)
        return 报告, None, None
    报告.场景制品摘要 = 当前摘要
    进程: subprocess.Popen[Any] | None = None
    实际端口: int | None = None
    if 直连地址:
        地址 = _校验直连地址(直连地址)
    else:
        启动器 = _找启动器(制品目录)
        可用, 消息 = _检查端口可用(端口)
        if not 可用:
            报告.失败数 = 1
            报告.结果列表.append(验证结果("制品启动", "", False, 0, 失败原因=消息, 定位线索="端口"))
            return 报告, None, None
        try:
            进程, 实际端口, _ = _启动制品(启动器, 制品目录, 端口)
            if 进程接收 is not None:
                进程接收(进程)
        except BaseException as 错误:
            报告.失败数 = 1
            报告.结果列表.append(验证结果(
                "制品启动", "", False, 0,
                失败原因=f"制品启动异常: {type(错误).__name__}: {错误}", 定位线索="编译",
            ))
            报告.资源回收 = {"已回收": True, "原因": "启动助手已回收"}
            return 报告, None, None
        地址 = f"http://127.0.0.1:{实际端口}"
    健康 = 验证场景(
        场景id="制品.健康", 能力id="制品.健康", 方法="GET", 路径="/",
        预期状态码=200, 预期成功=True, 预期值类型="字典型",
    )
    状态码, _, 耗时 = _发送请求(地址, 健康, 超时秒)
    if 状态码 != 200:
        报告.失败数 = 1
        报告.结果列表.append(验证结果(
            "制品.健康", "", False, 状态码, 耗时毫秒=耗时,
            失败原因=f"制品健康检查状态码 {状态码} != 200", 定位线索="编译",
        ))
        if 直连地址:
            报告.制品摘要后 = _制品全文件摘要(制品目录)
            _校验制品前后绑定(报告)
        return 报告, 实际端口, 进程

    if isinstance(场景列表, 验证场景束):
        场景报告 = _执行场景束(制品目录, 场景列表, 地址, 超时秒=超时秒)
        场景报告.并发峰值 = 1
        if 直连地址:
            场景报告.资源回收 = {"已回收": True, "模式": "直连"}
        return 场景报告, 实际端口, 进程

    活跃 = 0
    峰值 = 0
    锁 = threading.Lock()

    def 运行(场景: 验证场景) -> 验证结果:
        nonlocal 活跃, 峰值
        with 锁:
            活跃 += 1
            峰值 = max(峰值, 活跃)
        try:
            return 验证单个(地址, 场景, 超时秒)
        except BaseException as 错误:
            return 验证结果(
                场景.场景id, 场景.能力id, False, 0,
                失败原因=f"验证任务异常: {type(错误).__name__}: {错误}", 定位线索="验证器",
            )
        finally:
            with 锁:
                活跃 -= 1

    结果表: list[验证结果] = []
    with ThreadPoolExecutor(max_workers=min(并发, len(场景列表)), thread_name_prefix="HTML验证") as 执行器:
        任务表 = {执行器.submit(运行, 场景): 场景 for 场景 in 场景列表}
        for 任务 in as_completed(任务表):
            场景 = 任务表[任务]
            try:
                结果表.append(任务.result())
            except BaseException as 错误:
                结果表.append(验证结果(
                    场景.场景id, 场景.能力id, False, 0,
                    失败原因=f"验证任务异常: {type(错误).__name__}: {错误}", 定位线索="验证器",
                ))
    结果表.sort(key=lambda 结果: 结果.场景id)
    报告.结果列表.extend(结果表)
    报告.通过数 = sum(结果.通过 for 结果 in 结果表)
    报告.失败数 += len(结果表) - 报告.通过数
    报告.正向成功数 = sum(结果.通过 and 场景.预期成功 for 结果 in 结果表 for 场景 in 场景列表 if 场景.场景id == 结果.场景id)
    报告.负向校验数 = sum(结果.通过 and not 场景.预期成功 for 结果 in 结果表 for 场景 in 场景列表 if 场景.场景id == 结果.场景id)
    报告.并发峰值 = 峰值
    if 直连地址:
        报告.资源回收 = {"已回收": True, "模式": "直连"}
        报告.制品摘要后 = _制品全文件摘要(制品目录)
        _校验制品前后绑定(报告)
    return 报告, 实际端口, 进程


def _证据根目录(制品目录: Path) -> Path:
    del 制品目录
    return 系统根 / "工程缓存" / "HTML验证证据"


def 保存证据(报告: 验证报告, 制品目录: Path, 输出目录: Path | None = None) -> Path:
    if not 报告.制品摘要前:
        报告.制品摘要前 = _制品全文件摘要(制品目录)
    if not 报告.制品摘要后:
        报告.制品摘要后 = _制品全文件摘要(制品目录)
    制品摘要 = 报告.制品摘要前.get("制品摘要", "未知制品")
    报告.时间 = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    报告.证据绑定 = {
        "制品摘要": 制品摘要,
        "制品摘要前": 报告.制品摘要前.get("制品摘要", ""),
        "制品摘要后": 报告.制品摘要后.get("制品摘要", ""),
        "场景制品摘要": 报告.场景制品摘要,
        "工作区指纹": _工作区指纹(),
    }
    输出根 = (输出目录 or _证据根目录(制品目录)) / 制品摘要
    输出根.mkdir(parents=True, exist_ok=True)
    for _ in range(10):
        名称 = f"验证证据_{time.time_ns()}_{uuid.uuid4().hex[:12]}.json"
        路径 = 输出根 / 名称
        try:
            with 路径.open("x", encoding="utf-8") as 文件:
                json.dump(报告.转字典(), 文件, ensure_ascii=False, indent=2)
                文件.write("\n")
            return 路径
        except FileExistsError:
            continue
    raise FileExistsError("无法生成唯一证据文件名")


def 生成场景文件(制品目录: Path, 输出: Path | None = None) -> Path:
    场景束 = _加载场景(制品目录, None)
    摘要 = _制品全文件摘要(制品目录)["制品摘要"]
    输出路径 = 输出 or (_证据根目录(制品目录) / 摘要 / 场景文件名)
    输出路径.parent.mkdir(parents=True, exist_ok=True)
    数据 = {
        "来源": "包级验证场景引用",
        "契约版本": 场景契约版本,
        "制品摘要": 摘要,
        "验证场景": [场景.转字典(制品目录) for 场景 in 场景束.场景列表],
    }
    输出路径.write_text(json.dumps(数据, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 输出路径


def 服务模式(制品地址: str, 服务端口: int = 45081, 制品目录: Path | None = None) -> int:
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    制品地址 = _校验直连地址(制品地址)
    页面字节 = (Path(__file__).resolve().parent / "验证页.html").read_bytes()
    场景字节 = json.dumps({"来源": "包级验证场景引用", "验证场景": []}, ensure_ascii=False).encode()
    场景束: 验证场景束 | None = None
    if 制品目录 is not None:
        场景束 = _加载场景(制品目录, None)
        场景路径 = 生成场景文件(制品目录)
        场景字节 = 场景路径.read_bytes()
    执行锁 = threading.Lock()
    CSP = "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"

    class 处理器(BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            del format, args

        def _公共头(self) -> None:
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", CSP)

        def do_GET(self) -> None:
            解码路径 = urllib.parse.unquote(self.path)
            if 解码路径 in {"/", "/验证页.html"}:
                self.send_response(200)
                self._公共头()
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(页面字节)))
                self.end_headers()
                self.wfile.write(页面字节)
                return
            if 解码路径 == "/验证场景.json":
                self.send_response(200)
                self._公共头()
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(场景字节)))
                self.end_headers()
                self.wfile.write(场景字节)
                return
            if 解码路径 == "/代理/":
                self._转发("GET", 制品地址 + "/")
                return
            self.send_error(404)

        def do_POST(self) -> None:
            解码路径 = urllib.parse.unquote(self.path)
            if 解码路径 == "/执行验证":
                if 制品目录 is None or 场景束 is None:
                    self.send_error(409, "服务未绑定制品场景")
                    return
                with 执行锁:
                    报告 = _执行场景束(制品目录, 场景束, 制品地址)
                返回 = json.dumps(报告.转字典(), ensure_ascii=False).encode("utf-8")
                self.send_response(200 if 报告.失败数 == 0 else 409)
                self._公共头()
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(返回)))
                self.end_headers()
                self.wfile.write(返回)
                return
            self.send_error(404)

        def _转发(self, 方法: str, 目标: str, 正文: bytes = b"") -> None:
            拆分 = urllib.parse.urlsplit(目标)
            编码目标 = f"{拆分.scheme}://{拆分.netloc}{urllib.parse.quote(拆分.path, safe='/:@._-')}"
            try:
                请求 = urllib.request.Request(
                    编码目标, data=正文 or None, method=方法,
                    headers={"Content-Type": "application/json"},
                )
                with urllib.request.urlopen(请求, timeout=默认超时秒) as 响应:
                    状态码, 返回 = 响应.status, 响应.read(请求上限字节)
            except urllib.error.HTTPError as 错误:
                状态码, 返回 = 错误.code, 错误.read(请求上限字节)
            except (urllib.error.URLError, TimeoutError, OSError) as 错误:
                状态码 = 502
                返回 = json.dumps({
                    "成功": False, "值": None, "错误码": "网关断开", "错误说明": str(错误),
                    "可重试": True, "请求id": uuid.uuid4().hex, "耗时毫秒": 0,
                }, ensure_ascii=False).encode()
            self.send_response(状态码)
            self._公共头()
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(返回)))
            self.end_headers()
            self.wfile.write(返回)

    服务 = ThreadingHTTPServer(("127.0.0.1", 服务端口), 处理器)
    print(f"验证页已启动: http://127.0.0.1:{服务.server_port}/ （代理到 {制品地址}）")
    try:
        服务.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        服务.shutdown()
        服务.server_close()
    return 0


def _记录流程异常(报告: 验证报告, 错误: BaseException) -> None:
    报告.失败数 += 1
    报告.结果列表.append(验证结果(
        场景id="验证流程",
        能力id="",
        通过=False,
        失败原因=f"验证流程异常: {type(错误).__name__}: {错误}",
        定位线索="验证器",
    ))


def 主函数(参数: argparse.Namespace) -> int:
    制品目录 = Path(参数.制品).resolve()
    if not 制品目录.is_dir():
        print(f"阻断: 制品目录不存在: {制品目录}")
        return 2
    if 参数.服务:
        try:
            return 服务模式(参数.直连地址 or f"http://127.0.0.1:{参数.端口}", 参数.服务, 制品目录)
        except BaseException as 错误:
            print(f"阻断: 服务模式启动失败: {错误}")
            return 2
    if 参数.只生成场景:
        try:
            路径 = 生成场景文件(制品目录, Path(参数.场景) if 参数.场景 else None)
            print(f"验证场景已生成: {路径}")
            return 0
        except BaseException as 错误:
            print(f"阻断: 场景生成失败: {错误}")
            return 2

    报告 = 验证报告(制品路径=str(制品目录))
    进程: subprocess.Popen[Any] | None = None
    证据路径: Path | None = None
    def 接收进程(新进程: subprocess.Popen[Any]) -> None:
        nonlocal 进程
        进程 = 新进程

    try:
        报告.制品摘要前 = _制品全文件摘要(制品目录)
        场景列表 = _加载场景(制品目录, Path(参数.场景) if 参数.场景 else None)
        print(f"加载 {len(场景列表)} 个包级验证场景")
        报告, _, 进程 = 验证全部(
            制品目录, 场景列表, 并发=参数.并发, 超时秒=参数.超时秒,
            端口=参数.端口, 直连地址=参数.直连地址, 进程接收=接收进程,
        )
    except BaseException as 错误:
        _记录流程异常(报告, 错误)
    finally:
        try:
            回收 = _回收进程组(进程)
            报告.资源回收 = 回收
            if not 回收.get("已回收"):
                报告.失败数 += 1
                报告.结果列表.append(验证结果(
                    "资源回收", "", False, 0, 失败原因=f"进程组回收失败: {回收}", 定位线索="资源回收",
                ))
        except BaseException as 错误:
            _记录流程异常(报告, 错误)
        try:
            报告.制品摘要后 = _制品全文件摘要(制品目录)
            _校验制品前后绑定(报告)
        except BaseException as 错误:
            _记录流程异常(报告, 错误)
        try:
            证据路径 = 保存证据(报告, 制品目录)
        except BaseException as 错误:
            报告.失败数 += 1
            print(f"阻断: 失败证据写入失败: {错误}")
    print(报告.汇总())
    if 证据路径:
        print(f"证据: {证据路径}")
    for 结果 in 报告.结果列表:
        if not 结果.通过:
            print(f"  ✗ [{结果.场景id}] {结果.失败原因}（{结果.定位线索}）")
    return 0 if 报告.场景总数 > 0 and 报告.失败数 == 0 and 报告.正向成功数 > 0 else 1


if __name__ == "__main__":
    解析器 = argparse.ArgumentParser(description="HTML 黑盒验证器：只验证包级真实场景")
    解析器.add_argument("--制品", required=True, help="编译产物目录")
    解析器.add_argument("--场景", default="", help="由包级引用生成且绑定制品摘要的场景束")
    解析器.add_argument("--并发", type=int, default=默认并发)
    解析器.add_argument("--超时秒", type=float, default=默认超时秒)
    解析器.add_argument("--端口", type=int, default=固定端口)
    解析器.add_argument("--直连地址", default="", help="严格 IP 回环 HTTP 地址，带显式端口")
    解析器.add_argument("--服务", type=int, default=0)
    解析器.add_argument("--只生成场景", action="store_true")
    raise SystemExit(主函数(解析器.parse_args()))
