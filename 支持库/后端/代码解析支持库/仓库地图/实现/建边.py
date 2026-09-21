"""由节点索引建三类加权边：contains（文件→符号）、imports（文件→导入）、calls（调用者→被调符号）。

边权口径：同一 (起点, 终点, 关系种类) 三元组每出现一次 weight +1（引用次数即权重），
line 取首次出现的行号。三类边都**只连已存在的节点**：解析不到目标的调用直接丢弃，
不造幻影节点（幻影节点会把 PageRank 的质量引到不存在的符号上）。
"""

from __future__ import annotations

from 支持库.后端.代码解析支持库.仓库地图.实现.事实口径 import 取导入名, 取行号, 取末段


def 建边(文件表: list[dict], 事实索引: dict, 文件节点: dict,
         符号索引: dict, 导入索引: dict, 名称索引: dict) -> list[dict]:
    """按文件保序建边；返回按 (起点, 种类, 终点) 稳定排序的边表。"""
    边累计: dict[tuple[str, str, str], dict] = {}
    for 原文 in 文件表:
        相对 = 原文["相对路径"]
        事实 = 事实索引.get(相对)
        if 事实 is None:
            continue
        文件id = 文件节点[相对]
        for 符号 in 事实.get("符号列表") or []:
            节点id = 符号索引.get((相对, str(符号.get("名称") or "").strip()))
            if 节点id:
                加边(边累计, 文件id, 节点id, "contains", 取行号(符号))
        for 导入 in 事实.get("导入列表") or []:
            节点id = 导入索引.get((相对, 取导入名(导入)))
            if 节点id:
                加边(边累计, 文件id, 节点id, "imports", 取行号(导入))
        for 调用 in 事实.get("调用列表") or []:
            _连调用(边累计, 相对, 调用, 文件id, 符号索引, 导入索引, 名称索引)
    边表 = [{"source": 键[0], "target": 键[1], "kind": 键[2],
            "line": 值["line"], "weight": 值["weight"]}
           for 键, 值 in 边累计.items()]
    边表.sort(key=lambda 项: (项["source"], 项["kind"], 项["target"]))
    return 边表


def _连调用(边累计: dict, 相对: str, 调用: dict, 文件id: str,
           符号索引: dict, 导入索引: dict, 名称索引: dict) -> None:
    """连一条调用边：起点与终点都解析得到、且不自环时才落账。"""
    if not isinstance(调用, dict):
        return
    函数名 = str(调用.get("函数名") or "").strip()
    if not 函数名:
        return
    起点 = _调用起点(相对, 调用, 文件id, 符号索引)
    终点 = _解析目标(函数名, 相对, 符号索引, 导入索引, 名称索引)
    if 起点 and 终点 and 起点 != 终点:
        加边(边累计, 起点, 终点, "calls", 取行号(调用))


def _调用起点(相对: str, 调用: dict, 文件id: str, 符号索引: dict) -> str:
    """调用起点：命中外层函数则挂到该符号，否则挂到文件节点。"""
    所在函数 = str(调用.get("所在函数") or "").strip()
    if 所在函数:
        return 符号索引.get((相对, 所在函数)) or 文件id
    return 文件id


def _解析目标(函数名: str, 相对: str, 符号索引: dict, 导入索引: dict,
              名称索引: dict) -> str | None:
    """解析调用目标：同文件符号 → 同文件导入 → 全局同名符号（取首个），均无则 None。"""
    末段 = 取末段(函数名)
    for 候选 in (函数名, 末段):
        节点id = 符号索引.get((相对, 候选))
        if 节点id:
            return 节点id
    for 候选 in (函数名, 末段):
        节点id = 导入索引.get((相对, 候选))
        if 节点id:
            return 节点id
    候选表 = 名称索引.get(末段) or []
    return 候选表[0] if 候选表 else None


def 加边(边累计: dict, 起点: str, 终点: str, 种类: str, 行号: int) -> None:
    """累加加权边：同三元组重复出现则 weight+1，line 取最早行号。"""
    键 = (起点, 终点, 种类)
    项 = 边累计.get(键)
    if 项 is None:
        边累计[键] = {"line": 行号, "weight": 1.0}
        return
    项["weight"] += 1.0
    项["line"] = min(项["line"], 行号)
