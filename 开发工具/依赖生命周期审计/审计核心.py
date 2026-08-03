"""依赖与生命周期审计核心：只读审计第三方支持库提供者（依赖锁独立版本声明/
完整性摘要重算比对/健康探针能力/停止释放入口），不写被审计文件、不 import 其实现。"""

from __future__ import annotations

import ast
import json
from dataclasses import dataclass, field
from pathlib import Path

from 开发工具.组件规范.完整性摘要 import 生成完整性摘要

适配层目录名 = "支持库/适配层"
依赖锁文件名 = "依赖锁.json"
包声明文件名 = "包声明.json"
完整性摘要文件名 = "完整性摘要.json"
能力定义文件名 = "能力定义.json"
探针关键词 = ("探针", "健康")
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
    """从 依赖锁.json 与 包声明.依赖 收集第三方名称；返回 (名称集合, 违规)。"""
    依赖锁路径 = 目录 / 依赖锁文件名
    if not 依赖锁路径.is_file():
        return set(), [f"缺依赖锁: {依赖锁文件名} 不存在，无独立版本声明"]
    try:
        数据 = json.loads(依赖锁路径.read_text(encoding="utf-8"))
        包列表 = 数据.get("包") or 数据.get("直接依赖") or []
    except (json.JSONDecodeError, OSError) as 错误:
        return set(), [f"依赖锁损坏: {错误}"]
    名称集合 = {
        str(条目["名称"]) if isinstance(条目, dict) else 条目
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
    """健康探针能力存在性：能力定义.json 含 探针/健康 能力。"""
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
    return ["缺健康探针: 能力定义.json 未声明 探针/健康 能力"]


def 检查停止入口(目录: Path) -> list[str]:
    """停止与资源释放证据：实现/ 下 AST 找到 停止/关闭/释放/终结/终止 函数。"""
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
    return ["缺停止入口: 实现/ 下无 停止/关闭/释放/终结/终止 函数（无资源释放证据）"]


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
