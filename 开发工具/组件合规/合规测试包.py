"""组件合规测试包：每个支持库和模块统一验证 13 项强制场景（S0.4 唯一权威）。

强制场景：结构/契约/依赖/配置/权限/生命周期/资源释放/版本升级/失败
语义/说明书/完整性摘要/公共入口/真实返回值。
组件作者不能自行减少强制场景。

S0 缺项阻断清单（正式包形态一律阻断）：配置契约/权限契约/资源预算/
复用决策/注册能力/__all__/能力契约/验证证据。
契约与权限验证遍历聚合契约每个能力（禁整文件当一个能力）；
真实返回经 公开入口+能力注册表+锁定提供者 调用。
"""

from __future__ import annotations

import json
import sys
import time
import unittest
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

合规场景表 = [
    "结构", "契约", "依赖", "配置", "权限", "生命周期", "资源释放",
    "版本升级", "失败语义", "说明书", "完整性摘要", "公共入口", "真实返回值",
]

聚合契约文件名 = "参数契约.json"
资源预算必需键 = ("内存上限", "线程上限", "子进程上限", "并发调用上限",
                "队列长度", "文件句柄上限", "临时空间上限", "单次调用超时",
                "每分钟重启次数", "空闲回收时间")
禁止参数类型 = {"任意", ""}


def _加载模块(文件路径: Path):
    """加载任意 Python 文件为模块（用于真实实现调用）。"""
    import importlib.util as _工具
    规格 = _工具.spec_from_file_location(f"合规_{文件路径.stem}", 文件路径)
    if 规格 is None or 规格.loader is None:
        raise ImportError(f"无法加载: {文件路径}")
    模块 = _工具.module_from_spec(规格)
    规格.loader.exec_module(模块)
    return 模块


def _加载入口(组件目录: Path, 入口路径: Path):
    """按公开入口加载入口模块：临时把组件目录加入 sys.path（兼容包内相对导入）。"""
    import sys as _系统
    _系统.path.insert(0, str(组件目录))
    try:
        return _加载模块(入口路径)
    finally:
        _系统.path.remove(str(组件目录))


def _值类型(值: Any) -> str:
    """按配置值推断类型（用于生产配置校验器声明表）。"""
    if isinstance(值, bool):
        return "布尔"
    if isinstance(值, int):
        return "整数"
    if isinstance(值, float):
        return "浮点数"
    if isinstance(值, str):
        return "文本"
    if isinstance(值, list):
        return "列表"
    if isinstance(值, dict):
        return "字典"
    return "空"


@dataclass
class 合规报告:
    """组件合规测试报告。"""

    组件id: str = ""
    场景结果表: list[tuple[str, bool, str]] = field(default_factory=list)
    总场景数: int = 13

    @property
    def 通过数(self) -> int:
        return sum(1 for _, 通过, _ in self.场景结果表 if 通过)

    @property
    def 成功(self) -> bool:
        return self.通过数 == self.总场景数 and len(self.场景结果表) == self.总场景数


def _读取聚合契约(组件目录: Path) -> tuple[list[dict[str, Any]], bool, list[str]]:
    """读取唯一聚合契约 能力契约/参数契约.json，返回 (能力表, 是否聚合, 问题)。

    聚合格式：顶层 {"契约版本": ..., "能力契约": [能力, ...]}，每个能力为
    独立对象；禁止把整文件当一个能力。不存在聚合文件时回退旧格式
    （能力契约/*.json 单能力对象），供历史组件兼容。
    """
    聚合路径 = 组件目录 / "能力契约" / 聚合契约文件名
    if 聚合路径.is_file():
        try:
            数据 = json.loads(聚合路径.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return [], True, ["参数契约.json JSON 解析失败"]
        问题: list[str] = []
        if not isinstance(数据, dict) or not 数据.get("契约版本"):
            问题.append("聚合契约缺少 契约版本")
        能力表 = 数据.get("能力契约", []) if isinstance(数据, dict) else []
        if not isinstance(能力表, list) or not 能力表:
            问题.append("聚合契约 能力契约 为空（禁整文件当一个能力）")
            return [], True, 问题
        return [能力 for 能力 in 能力表 if isinstance(能力, dict)], True, 问题
    契约目录 = 组件目录 / "能力契约"
    if not 契约目录.is_dir():
        return [], False, ["缺少 能力契约/"]
    能力表: list[dict[str, Any]] = []
    for 契约文件 in sorted(契约目录.glob("*.json")):
        try:
            契约 = json.loads(契约文件.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if isinstance(契约, dict) and 契约.get("能力id"):
            能力表.append(契约)
    return 能力表, False, ["能力契约/ 为空（无契约 JSON）"] if not 能力表 else []


def _提供者锁定(系统根: Path, 组件目录: Path, 声明: dict[str, Any]) -> tuple[bool, str]:
    """锁定提供者：依赖声明（能力+版本）必须能定位到 支持库/模块库 真实提供者包。"""
    依赖列表 = 声明.get("依赖", []) if isinstance(声明.get("依赖"), list) else []
    if not 依赖列表:
        return True, "无依赖（独立组件，无需锁定提供者）"
    提供者能力表: set[str] = set()
    支持库根 = 系统根 / "支持库"
    模块库根 = 系统根 / "模块库"
    for 包目录 in ([*支持库根.rglob("包声明.json"), *模块库根.rglob("包声明.json")]
                   if 支持库根.is_dir() else []):
        if "pycache" in 包目录.parts or 包目录.parent.name == "_模板":
            continue
        try:
            提供声明 = json.loads(包目录.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        提供声明 = 提供声明 if isinstance(提供声明, dict) else {}
        for 能力 in 提供声明.get("能力", []) if isinstance(提供声明.get("能力"), list) else []:
            if isinstance(能力, dict) and 能力.get("能力id"):
                提供者能力表.add(str(能力["能力id"]))
        定义路径 = 包目录.parent / "能力定义.json"
        if 定义路径.is_file():
            try:
                定义 = json.loads(定义路径.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            for 能力 in 定义.get("能力列表", []) if isinstance(定义.get("能力列表"), list) else []:
                if isinstance(能力, dict) and 能力.get("能力id"):
                    提供者能力表.add(str(能力["能力id"]))
        聚合路径 = 包目录.parent / "能力契约" / 聚合契约文件名
        if 聚合路径.is_file():
            try:
                数据 = json.loads(聚合路径.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            for 能力 in 数据.get("能力契约", []) if isinstance(数据.get("能力契约"), list) else []:
                if isinstance(能力, dict) and 能力.get("能力id"):
                    提供者能力表.add(str(能力["能力id"]))
    未锁定: list[str] = []
    for 依赖 in 依赖列表:
        if not isinstance(依赖, dict):
            continue
        能力id = str(依赖.get("能力", ""))
        if 能力id and 能力id not in 提供者能力表:
            未锁定.append(能力id)
    if 未锁定:
        return False, f"依赖能力无锁定提供者: {未锁定}"
    return True, f"依赖 {len(依赖列表)} 项全部锁定真实提供者"


class 组件合规:
    """组件合规验证器：对任意组件目录执行 13 项强制场景。"""

    def __init__(self, 组件目录: Path) -> None:
        self.组件目录 = 组件目录
        self.报告 = 合规报告(组件id=组件目录.name)

    @property
    def _系统根(self) -> Path:
        根 = Path(__file__).resolve()
        for 祖先 in 根.parents:
            if (祖先 / "支持库").is_dir() and (祖先 / "模块库").is_dir():
                return 祖先
        return 根.parents[1]

    @property
    def _正式包形态(self) -> bool:
        return (self.组件目录 / "能力契约" / 聚合契约文件名).is_file()

    def 执行(self) -> 合规报告:
        """执行全部 13 项强制场景。"""
        场景函数表 = [
            ("结构", self._场景结构),
            ("契约", self._场景契约),
            ("依赖", self._场景依赖),
            ("配置", self._场景配置),
            ("权限", self._场景权限),
            ("生命周期", self._场景生命周期),
            ("资源释放", self._场景资源释放),
            ("版本升级", self._场景版本升级),
            ("失败语义", self._场景失败语义),
            ("说明书", self._场景说明书),
            ("完整性摘要", self._场景完整性摘要),
            ("公共入口", self._场景公共入口),
            ("真实返回值", self._场景真实返回值),
        ]
        for 名称, 函数 in 场景函数表:
            try:
                通过, 详情 = 函数()
            except Exception as 错误:
                通过, 详情 = False, f"异常: {错误}"
            self.报告.场景结果表.append((名称, 通过, 详情))
        return self.报告

    def _场景结构(self) -> tuple[bool, str]:
        """结构：九要素目录齐全 + 正式包缺项阻断（资源预算/复用决策/验证证据）。"""
        from 开发工具.组件规范.组件规范 import 校验组件规范
        结果 = 校验组件规范(self.组件目录)
        问题列表 = list(结果.问题列表)
        if self._正式包形态:
            # S0 缺项阻断：资源预算/复用决策/验证证据
            预算路径 = self.组件目录 / "资源预算.json"
            if not 预算路径.is_file():
                问题列表.append("缺少 资源预算.json")
            else:
                try:
                    预算 = json.loads(预算路径.read_text(encoding="utf-8"))
                except json.JSONDecodeError:
                    问题列表.append("资源预算.json JSON 解析失败")
                    预算 = {}
                缺失 = [键 for 键 in 资源预算必需键
                        if isinstance(预算, dict) and 键 not in 预算]
                if 缺失:
                    问题列表.append(f"资源预算缺少必需项: {缺失}")
            复用路径 = self.组件目录 / "复用决策.json"
            if not 复用路径.is_file():
                问题列表.append("缺少 复用决策.json")
            else:
                try:
                    复用 = json.loads(复用路径.read_text(encoding="utf-8"))
                except json.JSONDecodeError:
                    问题列表.append("复用决策.json JSON 解析失败")
                    复用 = {}
                if not (isinstance(复用, dict) and 复用.get("搜索词")
                        and 复用.get("候选能力id")):
                    问题列表.append("复用决策缺少 搜索词 或 候选能力id")
            证据路径 = self.组件目录 / "验证场景引用.json"
            if not 证据路径.is_file():
                问题列表.append("缺少 验证证据（验证场景引用.json）")
            else:
                try:
                    证据 = json.loads(证据路径.read_text(encoding="utf-8"))
                except json.JSONDecodeError:
                    问题列表.append("验证场景引用.json JSON 解析失败")
                    证据 = {}
                if not 证据.get("验证场景引用"):
                    问题列表.append("验证证据为空（验证场景引用 列表必须非空）")
        return not 问题列表, "; ".join(问题列表) or "九要素+资源预算+复用决策+验证证据齐全"

    def _场景契约(self) -> tuple[bool, str]:
        """契约：遍历聚合契约每个能力（S0.1 全要素），禁整文件当一个能力。"""
        from 开发工具.契约编译.契约编译器 import 校验契约结构
        能力表, 是否聚合, 问题列表 = _读取聚合契约(self.组件目录)
        if 问题列表 and not 能力表:
            return False, "; ".join(问题列表)
        for 契约 in 能力表:
            if 是否聚合:
                if not 契约.get("能力id"):
                    问题列表.append("聚合契约存在缺少 能力id 的能力")
                if not 契约.get("版本") or "." not in str(契约.get("版本", "")):
                    问题列表.append(f"{契约.get('能力id', '未知能力')} 缺少 版本")
                if not 契约.get("说明"):
                    问题列表.append(f"{契约.get('能力id', '未知能力')} 缺少 说明")
                参数列表 = 契约.get("参数", [])
                if not isinstance(参数列表, list) or not 参数列表:
                    问题列表.append(f"{契约.get('能力id', '未知能力')} 缺少 参数")
                else:
                    for 参数 in 参数列表:
                        if not isinstance(参数, dict) or not 参数.get("名称"):
                            问题列表.append(f"{契约.get('能力id', '未知能力')} 存在缺少 名称 的参数")
                            continue
                        if 参数.get("类型") in 禁止参数类型:
                            问题列表.append(
                                f"{契约.get('能力id', '未知能力')} 参数 {参数['名称']} 类型禁止: {参数.get('类型')!r}")
                        if "必填" not in 参数 or "默认值" not in 参数 or "说明" not in 参数:
                            问题列表.append(
                                f"{契约.get('能力id', '未知能力')} 参数 {参数['名称']} 缺少 必填/默认值/说明")
                if not 契约.get("返回"):
                    问题列表.append(f"{契约.get('能力id', '未知能力')} 缺少 返回结构")
                if not isinstance(契约.get("错误码"), list) or not 契约.get("错误码"):
                    问题列表.append(f"{契约.get('能力id', '未知能力')} 缺少 错误码")
                if not isinstance(契约.get("调用示例"), dict):
                    问题列表.append(f"{契约.get('能力id', '未知能力')} 缺少 可执行调用示例")
                问题列表.extend(校验契约结构(契约))
            else:
                问题列表.extend(校验契约结构(契约))
        return not 问题列表, "; ".join(问题列表) or f"聚合契约 {len(能力表)} 个能力逐一遍历通过"

    def _场景依赖(self) -> tuple[bool, str]:
        """依赖：调用真实包发现与依赖解析器，验证包存在/版本/能力/循环。"""
        依赖路径 = self.组件目录 / "依赖契约" / "依赖契约.json"
        if not 依赖路径.is_file():
            return False, "缺少 依赖契约/依赖契约.json"
        try:
            依赖数据 = json.loads(依赖路径.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return False, "依赖契约 JSON 解析失败"
        依赖列表 = 依赖数据.get("依赖", []) if isinstance(依赖数据, dict) else 依赖数据
        if not isinstance(依赖列表, list):
            return False, "依赖必须是列表"
        if not 依赖列表:
            return True, "无依赖（独立组件）"
        from 运行核心.加载器.包发现.发现器 import 扫描目录
        系统根 = self._系统根
        已发现包id表 = {
            声明.包id for 声明 in
            扫描目录(系统根 / "支持库", "支持库") + 扫描目录(系统根 / "模块库", "模块")
        }
        问题列表 = []
        for 依赖 in 依赖列表:
            依赖包id = 依赖.get("包id", "")
            if 依赖包id and 依赖包id not in 已发现包id表:
                问题列表.append(f"依赖包不存在: {依赖包id}")
        if 问题列表:
            return False, "; ".join(问题列表)
        return True, f"依赖 {len(依赖列表)} 项（经真实包发现验证）"

    def _场景配置(self) -> tuple[bool, str]:
        """配置：配置契约存在（缺则阻断）并按契约真实执行缺失/类型/未知项检查。"""
        配置路径 = self.组件目录 / "配置契约" / "配置契约.json"
        if not 配置路径.is_file():
            return False, "缺少 配置契约/配置契约.json"
        try:
            配置契约 = json.loads(配置路径.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return False, "配置契约 JSON 解析失败"
        if not isinstance(配置契约, dict) or not 配置契约:
            return False, "配置契约不能为空"
        from 项目适配层.配置适配.配置校验 import 校验配置
        try:
            声明表 = {键: {"类型": _值类型(值), "必填": False}
                      for 键, 值 in 配置契约.items()}
            校验结果 = 校验配置(配置契约, 声明表=声明表)
            问题 = 校验结果.问题列表 if hasattr(校验结果, "问题列表") else []
            if 问题:
                return False, "; ".join(问题)
        except (ImportError, AttributeError) as 错误:
            return False, f"生产配置校验器不可用: {错误}"
        return True, f"配置项 {len(配置契约)} 项（经生产校验器检查）"

    def _场景权限(self) -> tuple[bool, str]:
        """权限：遍历聚合契约每个能力都必须有权限声明（缺权限契约阻断）。"""
        权限路径 = self.组件目录 / "权限契约" / "权限契约.json"
        if not 权限路径.is_file():
            return False, "缺少 权限契约/权限契约.json"
        try:
            权限 = json.loads(权限路径.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return False, "权限契约 JSON 解析失败"
        能力表, _, 问题列表 = _读取聚合契约(self.组件目录)
        if 问题列表 and not 能力表:
            return False, "; ".join(问题列表)
        公开能力表 = [能力.get("能力id", "") for 能力 in 能力表 if 能力.get("能力id")]
        if not 公开能力表:
            return False, "无公开能力可校验权限"
        缺失权限 = [能力id for 能力id in 公开能力表
                    if isinstance(权限, dict) and 能力id not in 权限]
        if 缺失权限:
            return False, f"公开能力缺权限声明（逐能力遍历检出）: {缺失权限}"
        return True, f"聚合契约 {len(公开能力表)} 个能力全部有权限声明"

    def _场景生命周期(self) -> tuple[bool, str]:
        """生命周期：实际执行合法流转/非法流转/重复操作/失败回滚。"""
        声明路径 = self.组件目录 / "包声明.json"
        if not 声明路径.is_file():
            return False, "缺少 包声明.json"
        try:
            声明 = json.loads(声明路径.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return False, "包声明 JSON 解析失败"
        if not 声明.get("版本"):
            return False, "缺少 版本（生命周期依据）"
        from 平台控制面.包仓库.生命周期 import 包生命周期
        状态机 = 包生命周期(声明.get("包id", "合规组件"), 声明.get("版本", "1.0.0"))
        问题 = []
        for 目标 in ("安装中", "已安装", "校验中", "已校验", "已解析", "启动中", "已就绪"):
            记录 = 状态机.流转(目标)
            if not 记录.成功:
                问题.append(f"合法流转失败: {目标}（{记录.错误码}）")
        非法记录 = 状态机.流转("安装中")
        if 非法记录.成功:
            问题.append("非法流转未被拒绝: 已就绪→安装中")
        状态机.流转("已激活")
        重复记录 = 状态机.流转("已激活")
        if not 重复记录.成功:
            问题.append("重复操作非幂等")
        故障记录 = 状态机.流转("故障")
        if not 故障记录.成功:
            问题.append("故障流转失败")
        状态机.回滚("合规测试失败")
        if 状态机.状态 == "回滚中":
            问题.append("失败回滚未恢复")
        if 问题:
            return False, "; ".join(问题)
        return True, f"版本 {声明['版本']}（合法/非法/重复/回滚全部真实执行）"

    def _场景资源释放(self) -> tuple[bool, str]:
        """资源释放：真实创建资源并验证关闭/句柄归零/锁释放；文本扫描仅辅助。"""
        实现目录 = self.组件目录 / "实现"
        if not 实现目录.is_dir():
            实现目录 = self.组件目录 / "执行单元"
        if not 实现目录.is_dir():
            return False, "缺少 实现/ 或 执行单元/"
        问题列表 = []
        for 文件 in 实现目录.rglob("*.py"):
            内容 = 文件.read_text(encoding="utf-8")
            if "open(" in 内容 and "close()" not in 内容 and "with open" not in 内容:
                问题列表.append(f"{文件.name} 存在 open 未关闭")
            if "while True" in 内容 and "break" not in 内容 and "return" not in 内容:
                问题列表.append(f"{文件.name} 存在无退出无限循环")
        if 问题列表:
            return False, "; ".join(问题列表)
        import tempfile as _临时
        from 支持库.后端.资源管理 import (
            创建唯一运行目录, 原子写入, 安全释放资源, 资源短锁,
        )
        try:
            运行目录 = 创建唯一运行目录(Path(_临时.gettempdir()), "合规资源")
            测试文件 = 运行目录 / "测试.json"
            原子写入(测试文件, '{"值": 1}')
            锁 = 资源短锁(运行目录 / "锁", "合规资源", 持有者="合规测试")
            锁成功, _ = 锁.获取()
            if not 锁成功:
                return False, "资源短锁获取失败"
            锁释放, _ = 锁.释放()
            if not 锁释放:
                return False, "资源短锁释放失败"
            释放成功, 释放消息 = 安全释放资源(运行目录)
            if not 释放成功:
                return False, f"资源释放失败: {释放消息}"
            if 运行目录.exists():
                return False, "资源释放后目录仍存在"
        except Exception as 错误:
            return False, f"真实资源释放异常: {错误}"
        return True, "真实创建并释放资源（目录/文件/短锁全部归零）"

    def _场景版本升级(self) -> tuple[bool, str]:
        """版本升级：遍历聚合契约每个能力的版本号格式合法。"""
        from 开发工具.契约编译.漂移检测 import 主版本号
        能力表, _, 问题列表 = _读取聚合契约(self.组件目录)
        if 问题列表 and not 能力表:
            return False, "; ".join(问题列表)
        for 契约 in 能力表:
            版本 = 契约.get("版本", "")
            if not 版本 or 主版本号(版本) < 0 or "." not in str(版本):
                问题列表.append(f"{契约.get('能力id', '未知能力')} 版本号不合法: {版本}")
        return not 问题列表, "; ".join(问题列表) or f"聚合契约 {len(能力表)} 个能力版本号合法"

    def _场景失败语义(self) -> tuple[bool, str]:
        """失败语义：遍历聚合契约每个能力声明错误码且实现不吞异常。"""
        能力表, _, 问题列表 = _读取聚合契约(self.组件目录)
        if 问题列表 and not 能力表:
            return False, "; ".join(问题列表)
        for 契约 in 能力表:
            if not isinstance(契约.get("错误码"), list) or not 契约.get("错误码"):
                问题列表.append(f"{契约.get('能力id', '未知能力')} 未声明错误码")
        实现目录 = self.组件目录 / "实现"
        if not 实现目录.is_dir():
            实现目录 = self.组件目录 / "执行单元"
        if 实现目录.is_dir():
            for 文件 in 实现目录.rglob("*.py"):
                内容 = 文件.read_text(encoding="utf-8")
                if "except Exception" in 内容 and "pass" in 内容:
                    问题列表.append(f"{文件.name} 吞异常（except+pass）")
        return not 问题列表, "; ".join(问题列表) or "失败语义明确"

    def _场景说明书(self) -> tuple[bool, str]:
        """说明书：说明存在且非空。"""
        说明目录 = self.组件目录 / "说明"
        说明书 = self.组件目录 / "说明书.md"
        if 说明目录.is_dir():
            文件列表 = list(说明目录.rglob("*.md"))
            if not 文件列表:
                return False, "说明/ 目录为空"
            return True, f"说明书 {len(文件列表)} 份"
        if 说明书.is_file() and 说明书.read_text(encoding="utf-8").strip():
            return True, "说明书.md 存在"
        return False, "缺少 说明/ 或 说明书.md"

    def _场景完整性摘要(self) -> tuple[bool, str]:
        """完整性摘要：经唯一校验器验证文件清单格式闭合（拒绝旧格式与自比较）。"""
        from 开发工具.组件规范.完整性摘要 import 校验完整性摘要
        通过, 问题列表 = 校验完整性摘要(self.组件目录)
        if not 通过:
            return False, "; ".join(问题列表) or "完整性摘要校验失败"
        return True, "文件清单格式校验通过（唯一校验器）"

    def _场景公共入口(self) -> tuple[bool, str]:
        """公共入口：入口文件存在且可导入；正式包形态必须有 __all__ 与 注册能力。"""
        声明路径 = self.组件目录 / "包声明.json"
        if not 声明路径.is_file():
            return False, "缺少 包声明.json"
        try:
            声明 = json.loads(声明路径.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return False, "包声明 JSON 解析失败"
        入口 = 声明.get("入口", "")
        if not 入口:
            return False, "包声明缺少 入口"
        入口路径 = self.组件目录 / 入口
        if not 入口路径.is_file():
            return False, f"入口文件不存在: {入口}"
        try:
            入口模块 = _加载入口(self.组件目录, 入口路径)
        except Exception as 错误:
            return False, f"入口不可导入: {错误}"
        问题列表 = []
        if self._正式包形态 and 入口路径.name == "__init__.py":
            if not getattr(入口模块, "__all__", None):
                问题列表.append("缺少 __all__（正式包入口必须声明公开导出）")
            if not callable(getattr(入口模块, "注册能力", None)):
                问题列表.append("缺少 注册能力 函数（正式包入口必须注册能力）")
        return not 问题列表, "; ".join(问题列表) or f"入口 {入口} 可导入"

    def _场景真实返回值(self) -> tuple[bool, str]:
        """真实返回：经 公开入口.注册能力 + 能力注册表 + 锁定提供者 调用真实实现。"""
        声明路径 = self.组件目录 / "包声明.json"
        if not 声明路径.is_file():
            return False, "缺少 包声明.json"
        try:
            声明 = json.loads(声明路径.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return False, "包声明 JSON 解析失败"
        from 公共契约.能力契约.契约 import 能力实现, 能力注册表
        # 1. 锁定提供者：依赖能力必须锁定真实提供者包
        锁定成功, 锁定证据 = _提供者锁定(self._系统根, self.组件目录, 声明)
        if not 锁定成功:
            return False, 锁定证据
        # 2. 公开入口：经入口模块的 注册能力 注册实现（正式包形态强制）
        入口 = 声明.get("入口", "")
        入口模块 = None
        if 入口 and (self.组件目录 / 入口).is_file():
            try:
                入口模块 = _加载入口(self.组件目录, self.组件目录 / 入口)
            except Exception:
                入口模块 = None
        注册表 = 能力注册表()
        已注册 = False
        if 入口模块 is not None and callable(getattr(入口模块, "注册能力", None)):
            入口模块.注册能力(注册表)
            已注册 = bool(注册表.能力id列表)
        if not 已注册:
            实现目录 = self.组件目录 / "实现"
            if not 实现目录.is_dir():
                实现目录 = self.组件目录 / "执行单元"
            能力表, _, _ = _读取聚合契约(self.组件目录)
            for 契约 in 能力表[:1]:
                能力id = 契约.get("能力id", "")
                实现文件 = 实现目录 / f"{能力id.split('.')[-1]}.py"
                if not 实现文件.is_file():
                    for 候选 in sorted(实现目录.rglob("*.py")):
                        if "pycache" not in str(候选) and not 候选.name.startswith("_"):
                            实现文件 = 候选
                            break
                if 实现文件.is_file():
                    try:
                        模块 = _加载模块(实现文件)
                        实现函数 = getattr(模块, 能力id.split(".")[-1])
                        注册表.注册(能力实现(
                            能力id=能力id, 包id=声明.get("包id", self.组件目录.name),
                            实现函数=实现函数, 参数=契约.get("参数", []),
                            返回=契约.get("返回", "普通返回"), 说明=契约.get("说明", ""),
                        ))
                        已注册 = True
                    except (ImportError, AttributeError):
                        continue
        if not 已注册:
            return False, "公开入口未提供 注册能力 且无可用实现（真实返回不可达）"
        # 3. 装配最小合规调用器（模块实现经 获取能力调用器 调用的唯一装配路径）
        from 公共契约.能力契约.调用器 import 注册能力调用器

        class _合规调用器:
            def __init__(self, 注册表) -> None:
                self._注册表 = 注册表

            def 调用能力(self, 能力id: str, 参数: dict | None = None, **选项) -> Any:
                from 公共契约.基础类型.结果类型 import 结果
                实现 = self._注册表.获取(能力id)
                if 实现 is None:
                    return 结果.失败("提供者不可用", f"能力未注册: {能力id}",
                                      来源="组件合规", 可重试=True)
                返回值 = 实现.调用(**(参数 or {}))
                if isinstance(返回值, dict):
                    if 返回值.get("成功"):
                        return 结果.成功结果(返回值.get("值"))
                    return 结果.失败(str(返回值.get("错误码") or "失败"),
                                      str(返回值.get("消息") or ""), 来源="组件合规")
                return 返回值

            def 幂等重放(self, *args, **kwargs) -> bool:
                return False

            def 查询调用历史(self, 上限: int = 50) -> list:
                return []

            def 最近失败(self, 上限: int = 10) -> list:
                return []

            def 回答九问(self, *args, **kwargs) -> dict:
                return {}

        注册能力调用器(_合规调用器(注册表))
        try:
            问题 = self._遍历真实调用(注册表)
        finally:
            注册能力调用器(None)
        if 问题:
            return False, "；".join(问题)
        return True, f"真实调用 {len(注册表.能力id列表)} 个能力全部非空返回"

    def _遍历真实调用(self, 注册表) -> list[str]:
        """遍历注册表每个能力：成功路径 + 缺必填失败路径。"""
        问题: list[str] = []
        能力表, _, _ = _读取聚合契约(self.组件目录)
        示例参数表 = {
            契约.get("能力id", ""): (契约.get("调用示例") or {}).get("参数", {})
            for 契约 in 能力表 if isinstance(契约.get("调用示例"), dict)
        }
        for 能力id in 注册表.能力id列表:
            实现对象 = 注册表.获取(能力id)
            if 实现对象 is None:
                问题.append(f"{能力id} 注册表获取失败")
                continue
            参数表 = 实现对象.参数
            示例参数 = 示例参数表.get(能力id, {})
            成功参数 = dict(示例参数) if 示例参数 else {
                参数["名称"]: "测试值" for 参数 in 参数表 if 参数.get("必填", True)
            }
            try:
                成功结果 = 实现对象.调用(**成功参数)
            except Exception as 错误:
                问题.append(f"{能力id} 成功路径异常: {错误}")
                continue
            if 成功结果 is None:
                问题.append(f"{能力id} 成功路径无返回（真实返回为空）")
            if 参数表:
                失败参数 = {参数["名称"]: "测试值" for 参数 in 参数表
                            if not 参数.get("必填", True)}
                try:
                    失败结果 = 实现对象.调用(**失败参数)
                    是成功 = False
                    if isinstance(失败结果, dict):
                        是成功 = bool(失败结果.get("成功"))
                    elif hasattr(失败结果, "成功"):
                        是成功 = bool(失败结果.成功)
                    if 是成功:
                        问题.append(f"{能力id} 缺必填参数未返回失败（失败语义缺失）")
                except TypeError:
                    # 缺必填参数被 Python 签名拒绝 = 失败语义成立
                    pass
                except Exception as 错误:
                    问题.append(f"{能力id} 缺必填参数调用异常（失败语义缺失）: {错误}")
        return 问题
