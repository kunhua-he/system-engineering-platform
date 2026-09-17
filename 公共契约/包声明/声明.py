"""包声明契约：包身份、版本、依赖与能力列表的统一声明。

一份包声明是支持库或模块的机器可读元信息（JSON），遵循易语言式工程
原则：永久包 id、版本、依赖要求、能力、说明属于声明，不靠导入源码猜测。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from 公共契约.基础类型.逻辑类型 import 真, 假

版本正则 = re.compile(r"^\d+\.\d+\.\d+$")

允许类型集合 = {"支持库", "模块", "基础模块", "功能模块"}
必填字段表 = ("包id", "名称", "类型", "版本", "能力")


@dataclass(frozen=True)
class 能力声明:
    """能力契约声明：能力 id、名称、参数、返回与说明。"""

    能力id: str
    名称: str = ""
    参数: list[dict[str, str]] = field(default_factory=list)
    返回: str = ""
    说明: str = ""

    def 转字典(self) -> dict[str, Any]:
        return {
            "能力id": self.能力id,
            "名称": self.名称,
            "参数": self.参数,
            "返回": self.返回,
            "说明": self.说明,
        }


@dataclass(frozen=True)
class 包声明:
    """一份支持库或模块的包声明。"""

    包id: str
    名称: str
    类型: str
    版本: str
    说明: str = ""
    入口: str = ""
    依赖: list[dict] = field(default_factory=list)
    能力: list[能力声明] = field(default_factory=list)
    配置项: list[dict] = field(default_factory=list)
    来源路径: str = ""
    已废弃: bool = 假
    内部层: bool = 假   # 第三方能力内部支持库：装配可用、网关 0 暴露
    #: 依赖类别：`第三方库`（代码级依赖，落适配层提供者）或 `环境依赖`（运行级依赖，独立进程/服务/
    #: 动态库/外部接口）。空串＝未声明（历史包）。**为什么进契约**：不进契约则 `转字典()` 会把它丢掉，
    #: 读包声明的消费方（包仓库/客户端）就拿不到该字段——决策记录 `0021` 要求它可被机器读取。
    依赖类别: str = ""

    def 转字典(self) -> dict[str, Any]:
        return {
            "包id": self.包id,
            "名称": self.名称,
            "类型": self.类型,
            "版本": self.版本,
            "说明": self.说明,
            "入口": self.入口,
            "依赖": self.依赖,
            "能力": [能力.转字典() for 能力 in self.能力],
            "来源路径": self.来源路径,
            "内部层": self.内部层,
            "依赖类别": self.依赖类别,
        }


def 校验版本(版本: str) -> None:
    """版本必须为 x.y.z 三段式。"""
    if not 版本正则.match(版本):
        raise ValueError(f"版本格式不合法（应为 x.y.z）: {版本}")


def 从字典构建(数据: dict[str, Any], *, 来源路径: str = "") -> 包声明:
    """从字典构建包声明并做结构校验。"""
    缺失 = [字段 for 字段 in 必填字段表 if 字段 not in 数据]
    if 缺失:
        raise ValueError(f"包声明缺少必填字段: {', '.join(缺失)}")
    类型 = str(数据["类型"])
    if 类型 not in 允许类型集合:
        raise ValueError(f"包类型不合法: {类型}，可选: {'/'.join(允许类型集合)}")
    版本 = str(数据["版本"])
    校验版本(版本)
    依赖 = 数据.get("依赖") or []
    if not isinstance(依赖, list):
        raise ValueError("依赖必须是列表")
    能力列表 = []
    for 条目 in 数据.get("能力") or []:
        if not isinstance(条目, dict) or not 条目.get("能力id"):
            raise ValueError("能力声明缺少 能力id")
        能力列表.append(
            能力声明(
                能力id=str(条目["能力id"]),
                名称=str(条目.get("名称", "")),
                参数=条目.get("参数") or [],
                返回=str(条目.get("返回", "")),
                说明=str(条目.get("说明", "")),
            )
        )
    return 包声明(
        包id=str(数据["包id"]),
        名称=str(数据["名称"]),
        类型=类型,
        版本=版本,
        说明=str(数据.get("说明", "")),
        入口=str(数据.get("入口", "")),
        依赖=依赖,
        能力=能力列表,
        配置项=数据.get("配置项") or [],
        来源路径=来源路径,
        已废弃=bool(数据.get("已废弃", 假)),
        内部层=bool(数据.get("内部层", 假)),
        依赖类别=str(数据.get("依赖类别", "") or ""),
    )


def 加载声明文件(路径: Path | str) -> 包声明:
    """从 JSON 文件加载并校验包声明。"""
    文件路径 = Path(路径)
    if not 文件路径.is_file():
        raise FileNotFoundError(f"包声明文件不存在: {文件路径}")
    try:
        数据 = json.loads(文件路径.read_text(encoding="utf-8"))
    except json.JSONDecodeError as 错误:
        raise ValueError(f"包声明不是合法 JSON: {文件路径} ({错误})") from 错误
    if not isinstance(数据, dict):
        raise ValueError(f"包声明必须是 JSON 对象: {文件路径}")
    return 从字典构建(数据, 来源路径=str(文件路径))


# ── 依赖锁契约（唯一判据，决策记录 `0033`）──────────────────────────────
#
# **为什么这条判据住公共契约**：它要同时被三层消费——装配层（`运行核心/环境管理器`，
# fail-closed 拒装）、生成层（`开发工具/重建依赖锁`、`组件规范支持库.支持库模板生成器`）、
# 门禁层（`开发工具/公开调用完整性门禁`）。此前它只实现在装配层，另两层只能各写一份
# 或干脆不判 → 生成器可以产出「注定装不上」的包而无人拦（2026-09-17 实测：本地装配
# 整包跳过、40007 热接入却成功，两条腿结论相反）。
# 判据是**纯 JSON 结构规则、零仓内依赖**，与包声明同域，故上移到本模块作唯一源；
# 装配层保留同名函数直接委托（调用点不变），不再各持一份。
依赖锁文件名 = "依赖锁.json"


def 检查依赖锁内容(提供者目录: Path | str) -> tuple[str, str]:
    """依赖锁内容检查（**唯一口径**）：返回 (错误码, 错误说明)，正常返回 ("", "")。

    判定规则（仓内铁口径）：

    1. **锁文件缺失 → 不在此判定**，返回 ``("", "")``。
       缺失正是「无第三方依赖」的**正确表达**——实测全仓：`支持库/后端` 78 包中
       62 包无锁，装配正常。
    2. 锁无法解析 / 顶层非对象 → ``依赖锁无效``。
    3. **包与直接依赖均为空 → ``依赖锁为空``**（空壳锁）。这种锁注定过不了装配：
       调用方须按 fail-closed 处理（装配期禁止装配提供者）。

    规则 3 是历史上踩过的坑：模板曾无条件造空壳锁，而装配期恰好拒它 → 模板产物
    必然被整包跳过。修法在表达侧（无第三方就不建锁）与门禁侧（把本条接到生成链），
    **不放宽判定**（放宽会让「无第三方」出现两种等价表达，违反 1.3 结果唯一即收口）。
    """
    锁文件 = Path(提供者目录) / 依赖锁文件名
    if not 锁文件.is_file():
        return "", ""
    try:
        锁 = json.loads(锁文件.read_text(encoding="utf-8"))
    except (OSError, ValueError) as 错误:
        return "依赖锁无效", f"依赖锁.json 无法解析（{错误}），禁止装配提供者"
    if not isinstance(锁, dict):
        return "依赖锁无效", "依赖锁.json 顶层必须是对象，禁止装配提供者"
    if not 锁.get("包") and not 锁.get("直接依赖"):
        return "依赖锁为空", "包与直接依赖均为空，禁止装配提供者"
    return "", ""
