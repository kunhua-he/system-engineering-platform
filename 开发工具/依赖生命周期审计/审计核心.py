"""依赖与生命周期审计核心：只读审计第三方支持库提供者（依赖锁独立版本声明/
完整性摘要重算比对/健康探针能力/停止释放入口），不写被审计文件、不 import 其实现。"""

from __future__ import annotations

import ast
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from 支持库.后端.组件规范支持库 import 生成完整性摘要

适配层目录名 = "支持库/适配层"
依赖锁文件名 = "依赖锁.json"
包声明文件名 = "包声明.json"
完整性摘要文件名 = "完整性摘要.json"
能力定义文件名 = "能力定义.json"
生命周期契约文件名 = "生命周期契约.json"
# 提供者现有公开能力中，“检查提供者/检查可用性”与“版本探针”都是
# 同一健康契约的合法中文命名；不能只认“探针/健康”两个词而误报。
探针关键词 = ("探针", "健康", "检查提供者", "检查可用性", "检查提供者版本")
停止关键词 = ("停止", "关闭", "释放", "终结", "终止")


@dataclass
class 提供者审计结果:
    提供者名: str
    目录: Path
    违规列表: list[str] = field(default_factory=list)

    @property
    def 是否通过(self) -> bool:
        return not self.违规列表


def 扫描提供者目录(系统根: Path) -> tuple[list[Path], list[str]]:
    """扫描 支持库/适配层/*提供者/；返回 (标准提供者目录, 跳过说明)。"""
    适配层 = 系统根 / 适配层目录名
    提供者列表: list[Path] = []
    跳过列表: list[str] = []
    if not 适配层.is_dir():
        return 提供者列表, 跳过列表
    for 目录 in sorted(适配层.glob("*提供者")):
        if not 目录.is_dir():
            continue
        if (目录 / 包声明文件名).is_file():
            提供者列表.append(目录)
        else:
            跳过列表.append(f"{目录.name}: 无 包声明.json，非标准第三方支持库提供者，跳过")
    return 提供者列表, 跳过列表


def 收集第三方名称(目录: Path, 声明: dict) -> tuple[set[str], list[str]]:
    """收集发行包归属，而非把同一发行包的命令/模块误判为混装。

    依赖锁条目可用 ``发行包`` 声明实际归属（例如 ffmpeg 与 ffprobe
    都属于 FFmpeg发行包）。旧条目没有该字段时退回名称，保持严格审计：
    未明确归属的不同名称仍然会被判为混装。
    """
    依赖锁路径 = 目录 / 依赖锁文件名
    if not 依赖锁路径.is_file():
        return set(), [f"缺依赖锁: {依赖锁文件名} 不存在，无独立版本声明"]
    try:
        数据 = json.loads(依赖锁路径.read_text(encoding="utf-8"))
        包列表 = 数据.get("包") or 数据.get("直接依赖") or []
    except (json.JSONDecodeError, OSError) as 错误:
        return set(), [f"依赖锁损坏: {错误}"]
    名称集合 = {
        str(条目.get("发行包") or 条目["名称"])
        if isinstance(条目, dict) else 条目
        for 条目 in (包列表 + (声明.get("依赖") or []))
        if (isinstance(条目, dict) and 条目.get("名称")) or isinstance(条目, str)
    }
    return 名称集合, []


def 检查依赖锁(目录: Path, 声明: dict) -> list[str]:
    """依赖锁.json 独立版本声明与混装检查（一个提供者只锁一个第三方）。"""
    名称集合, 违规列表 = 收集第三方名称(目录, 声明)
    if 违规列表:
        return 违规列表
    if not 名称集合:
        return ["依赖锁空: 未声明任何第三方包"]
    if len(名称集合) > 1:
        return [f"混装: 一个提供者声明多个第三方 {sorted(名称集合)}"]
    return []


def 检查完整性摘要(目录: Path, 声明: dict) -> list[str]:
    """完整性摘要.json 存在且与唯一生成器重算结果一致（检出漂移）。"""
    摘要路径 = 目录 / 完整性摘要文件名
    if not 摘要路径.is_file():
        return [f"缺完整性摘要: {完整性摘要文件名} 不存在"]
    包id = str(声明.get("包id") or 目录.name)
    版本 = str(声明.get("版本") or "1.0.0")
    try:
        磁盘摘要 = json.loads(摘要路径.read_text(encoding="utf-8"))
        重算摘要 = 生成完整性摘要(目录, 包id=包id, 版本=版本)
    except (json.JSONDecodeError, OSError, ValueError) as 错误:
        return [f"摘要漂移: 重算失败 {错误}"]
    if 磁盘摘要 == 重算摘要:
        return []
    磁盘条数 = len(磁盘摘要.get("文件清单", [])) if isinstance(磁盘摘要, dict) else -1
    重算条数 = len(重算摘要.get("文件清单", []))
    return [f"摘要漂移: 磁盘文件清单 {磁盘条数} 条 ≠ 唯一生成器重算 {重算条数} 条"
            f"（包id/版本/文件内容/清单不一致）"]


def 检查健康探针(目录: Path) -> list[str]:
    """健康探针能力存在性：能力定义或生命周期契约必须可审计。"""
    能力路径 = 目录 / 能力定义文件名
    if not 能力路径.is_file():
        return [f"缺健康探针: {能力定义文件名} 不存在，无法声明探针能力"]
    try:
        数据 = json.loads(能力路径.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as 错误:
        return [f"缺健康探针: 能力定义损坏 {错误}"]
    for 能力 in 数据.get("能力列表") or []:
        if not isinstance(能力, dict):
            continue
        名称文本 = f"{能力.get('能力id', '')} {能力.get('中文名称', '')}"
        if any(词 in 名称文本 for 词 in 探针关键词):
            return []
    契约路径 = 目录 / 生命周期契约文件名
    if 契约路径.is_file():
        try:
            契约 = json.loads(契约路径.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as 错误:
            return [f"缺健康探针: 生命周期契约损坏 {错误}"]
        探针 = 契约.get("健康探针")
        入口 = str(探针.get("入口") or "") if isinstance(探针, dict) else ""
        入口路径 = 入口.split(":", 1)[0].strip()
        入口存在 = bool(入口路径) and (目录 / 入口路径).is_file()
        身份一致 = 契约.get("提供者id") in {
            str(目录.name),
            f"支持库.适配层.{目录.name}",
        }
        if (isinstance(探针, dict) and 探针.get("方式")
                and 探针.get("成功条件") and 探针.get("失败码")
                and 入口存在 and 身份一致):
            return []
    return ["缺健康探针: 能力定义.json 未声明探针且生命周期契约无效"]


def _停止入口真实存在(目录: Path, 停止入口文本: str) -> bool:
    """契约里的「停止入口」必须指向实现里**真实存在**的函数。

    为什么要这一步：光有「停止入口」这个字段可能是空话（契约写了、实现里没有）。
    本函数从文本里抓出函数名（形如 ``实现/进程管理.py 的 终止进程组()``），
    再到 ``实现/**/*.py`` 的 AST 里核对确实存在同名函数。
    """
    实现目录 = 目录 / "实现"
    if not 实现目录.is_dir():
        return False
    候选 = re.findall(r"([A-Za-z_\u4e00-\u9fff][A-Za-z0-9_\u4e00-\u9fff]{1,40})\s*\(\)", 停止入口文本)
    if not 候选:
        候选 = re.findall(r"[A-Za-z_][A-Za-z0-9_]{2,40}", 停止入口文本)
    if not 候选:
        return False
    实际函数名: set[str] = set()
    for 文件 in 实现目录.rglob("*.py"):
        try:
            树 = ast.parse(文件.read_text(encoding="utf-8"))
        except (SyntaxError, OSError):
            continue
        for 节点 in ast.walk(树):
            if isinstance(节点, (ast.FunctionDef, ast.AsyncFunctionDef)):
                实际函数名.add(节点.name)
    return any(名 in 实际函数名 for 名 in 候选)


def 检查停止入口(目录: Path) -> list[str]:
    """停止与资源释放证据：实现函数或生命周期契约必须明确释放语义。"""
    实现目录 = 目录 / "实现"
    if not 实现目录.is_dir():
        return ["缺停止入口: 实现/ 目录不存在"]
    for 文件 in 实现目录.glob("*.py"):
        try:
            树 = ast.parse(文件.read_text(encoding="utf-8"))
        except (SyntaxError, OSError):
            continue
        for 节点 in ast.walk(树):
            if isinstance(节点, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if any(词 in 节点.name for 词 in 停止关键词):
                    return []
    契约路径 = 目录 / 生命周期契约文件名
    if 契约路径.is_file():
        try:
            契约 = json.loads(契约路径.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            契约 = {}
        身份一致 = 契约.get("提供者id") in {
            str(目录.name),
            f"支持库.适配层.{目录.name}",
        }
        # 主判据（2026-09-16 收紧）：契约必须**显式声明停止入口**，且该入口**真实存在**。
        # 旧判据只认「资源模型 == 调用内临时资源」这个精确字符串，写别的合法措辞会被误判成缺入口；
        # 而"契约写了停止入口但实现里没有"这类名不副实又拦不住 —— 故改为按停止入口字段 + AST 核对。
        停止入口 = str(契约.get("停止入口") or "")
        if 身份一致 and len(停止入口) >= 6 and _停止入口真实存在(目录, 停止入口):
            return []
        # 兼容路径：契约没有停止入口字段，但资源模型自述为"调用内临时资源"且释放策略明确
        资源模型 = 契约.get("资源模型")
        释放策略 = 契约.get("释放策略")
        释放文本 = str(释放策略 or "")
        释放证据词 = ("finally", "关闭", "释放", "终止", "回收", "无跨调用状态")
        if (资源模型 == "调用内临时资源" and 身份一致
                and any(词 in 释放文本 for 词 in 释放证据词)
                and len(释放文本) >= 12):
            return []
    return ["缺停止入口: 实现/ 下无停止函数，且契约未声明可核对的停止入口"]


def 审计单个提供者(目录: Path) -> 提供者审计结果:
    """审计一个标准提供者目录，返回违规清单。"""
    结果 = 提供者审计结果(提供者名=目录.name, 目录=目录)
    声明路径 = 目录 / 包声明文件名
    try:
        声明 = json.loads(声明路径.read_text(encoding="utf-8")) if 声明路径.is_file() else {}
    except (json.JSONDecodeError, OSError) as 错误:
        结果.违规列表.append(f"包声明损坏: {错误}")
        声明 = {}
    if not 声明:
        结果.违规列表.append("包声明缺失: 包声明.json 不存在或为空")
        return 结果
    结果.违规列表.extend(检查依赖锁(目录, 声明))
    结果.违规列表.extend(检查完整性摘要(目录, 声明))
    结果.违规列表.extend(检查健康探针(目录))
    结果.违规列表.extend(检查停止入口(目录))
    return 结果


def 审计全部(系统根: Path) -> tuple[list[提供者审计结果], list[str]]:
    """审计全部标准提供者目录；返回 (结果列表, 跳过说明列表)。"""
    提供者列表, 跳过列表 = 扫描提供者目录(系统根)
    return [审计单个提供者(目录) for 目录 in 提供者列表], 跳过列表
