"""由语法事实集建节点：文件/类/函数/方法/导入五类节点，边交给 建边。

节点列名与 代码地图 的 nodes 表逐字对齐；本文件只负责「有哪些节点、叫什么、在哪一行」，
不负责连边（连边是 建边.py 的职责）。
"""

from __future__ import annotations

from 支持库.后端.代码解析支持库.仓库地图.实现.事实口径 import (
    类别表, 取导入名, 取行号, 取末段,
)
from 支持库.后端.代码解析支持库.仓库地图.实现.建边 import 建边
from 支持库.后端.代码解析支持库.仓库地图.实现.签名抽取 import 取签名


def 建图(文件表: list[dict], 事实表: list[dict]) -> tuple[list[dict], list[dict]]:
    """按文件保序建节点与边；返回 (节点表, 边表)。"""
    节点表: list[dict] = []
    名称索引: dict[str, list[str]] = {}
    文件节点: dict[str, str] = {}
    符号索引: dict[tuple[str, str], str] = {}
    导入索引: dict[tuple[str, str], str] = {}
    事实索引 = {事实["相对路径"]: 事实 for 事实 in 事实表}
    for 事实 in 事实表:
        相对 = 事实["相对路径"]
        文件id = f"file:{相对}"
        文件节点[相对] = 文件id
        节点表.append(节点字典(文件id, "file", 相对, 相对, 相对, 事实["语言"],
                           1, max(len(事实["代码行表"]), 1), 0, "", ""))
        _建导入节点(节点表, 名称索引, 导入索引, 事实)
        _建符号节点(节点表, 名称索引, 符号索引, 事实)
    边表 = 建边(文件表, 事实索引, 文件节点, 符号索引, 导入索引, 名称索引)
    return 节点表, 边表


def 节点字典(节点id: str, 种类: str, 名称: str, 限定名: str, 相对路径: str, 语言: str,
            起始行: int, 结束行: int, 是否导出: int, 签名: str, 文档: str) -> dict:
    """节点字典：列名与 代码地图 的 nodes 表逐字对齐。"""
    return {"id": 节点id, "kind": 种类, "name": 名称, "qualified_name": 限定名,
            "file_path": 相对路径, "language": 语言, "start_line": 起始行,
            "end_line": 结束行, "is_exported": 是否导出, "signature": 签名,
            "docstring": 文档}


def _建导入节点(节点表: list[dict], 名称索引: dict, 导入索引: dict, 事实: dict) -> None:
    """建导入节点（同一文件内同名导入只建一个，行号取首次出现）。"""
    相对 = 事实["相对路径"]
    for 导入 in 事实.get("导入列表") or []:
        if not isinstance(导入, dict):
            continue
        名 = 取导入名(导入)
        if not 名 or (相对, 名) in 导入索引:
            continue
        行号 = 取行号(导入)
        节点id = f"import:{相对}:{名}"
        导入索引[(相对, 名)] = 节点id
        节点表.append(节点字典(节点id, "import", 名, f"{相对}:{名}", 相对, 事实["语言"],
                           行号, 行号, 0, f"import {名}", ""))
        名称索引.setdefault(取末段(名), []).append(节点id)


def _建符号节点(节点表: list[dict], 名称索引: dict, 符号索引: dict, 事实: dict) -> None:
    """建符号节点；Python 类内函数（名称带点且类别为 function）归一到 method。"""
    相对 = 事实["相对路径"]
    行表 = 事实["代码行表"]
    for 符号 in 事实.get("符号列表") or []:
        if not isinstance(符号, dict):
            continue
        名 = str(符号.get("名称") or "").strip()
        if not 名 or (相对, 名) in 符号索引:
            continue
        类别 = 类别表.get(str(符号.get("类别") or ""), "function")
        if 类别 == "function" and "." in 名:
            类别 = "method"
        起始行 = 取行号(符号)
        结束行 = max(取行号(符号, "结束行号"), 起始行)
        节点id = f"symbol:{相对}:{名}"
        符号索引[(相对, 名)] = 节点id
        节点表.append(节点字典(节点id, 类别, 名, f"{相对}:{名}", 相对, 事实["语言"],
                           起始行, 结束行, 1, 取签名(行表, 起始行, 类别, 名), ""))
        名称索引.setdefault(取末段(名), []).append(节点id)
