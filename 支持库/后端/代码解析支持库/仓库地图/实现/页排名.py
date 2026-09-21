"""PageRank：优先 networkx（本机实测 3.6.1 可用），不可用时退化为等价的幂迭代实现。

为什么要自带退化实现：networkx 是**第三方**依赖，平台支持库不应因它缺失而整条能力不可用；
退化实现与 networkx 同口径（衰减系数 0.85、权重归一、悬挂节点质量均摊），
只保证「排名可用」，不保证与 networkx 逐位相同（已在返回口径中声明）。
"""

from __future__ import annotations

衰减系数 = 0.85
最大迭代 = 100
收敛阈值 = 1e-8


def 页排名(节点id表: list[str], 边表: list[tuple[str, str, float]],
         个性化: dict[str, float] | None = None) -> dict[str, float]:
    """加权有向图 PageRank；返回 {节点id: 得分}，得分总和为 1。"""
    if not 节点id表:
        return {}
    try:
        return _用networkx(节点id表, 边表, 个性化)
    except Exception:  # 第三方不可用/内部异常一律降级：排名能力不能因此整条消失
        return _幂迭代(节点id表, 边表, 个性化)


def _用networkx(节点id表: list[str], 边表: list[tuple[str, str, float]],
              个性化: dict[str, float] | None) -> dict[str, float]:
    import networkx as 图库

    图 = 图库.DiGraph()
    图.add_nodes_from(节点id表)
    for 起点, 终点, 权重 in 边表:
        if 起点 in 图 and 终点 in 图:
            图.add_edge(起点, 终点, weight=float(权重) if 权重 and 权重 > 0 else 1.0)
    向量 = _归一化(节点id表, 个性化) if 个性化 else None
    return dict(图库.pagerank(图, alpha=衰减系数, personalization=向量, weight="weight"))


def _幂迭代(节点id表: list[str], 边表: list[tuple[str, str, float]],
           个性化: dict[str, float] | None) -> dict[str, float]:
    """自带幂迭代：与 networkx 同口径的加权 PageRank。"""
    出边: dict[str, list[tuple[str, float]]] = {节点: [] for 节点 in 节点id表}
    for 起点, 终点, 权重 in 边表:
        if 起点 in 出边 and 终点 in 出边:
            出边[起点].append((终点, float(权重) if 权重 and 权重 > 0 else 1.0))
    总数 = len(节点id表)
    个人 = _归一化(节点id表, 个性化)
    得分 = dict(个人)
    for _ in range(最大迭代):
        新分 = {节点: (1.0 - 衰减系数) * 个人[节点] for 节点 in 节点id表}
        悬挂 = sum(得分[节点] for 节点 in 节点id表 if not 出边[节点])
        分摊 = 衰减系数 * 悬挂 / 总数
        for 节点 in 节点id表:
            新分[节点] += 分摊
            邻接 = 出边[节点]
            if not 邻接:
                continue
            总权 = sum(权 for _, 权 in 邻接) or 1.0
            for 终点, 权 in 邻接:
                新分[终点] += 衰减系数 * 得分[节点] * 权 / 总权
        偏差 = sum(abs(新分[节点] - 得分[节点]) for 节点 in 节点id表)
        得分 = 新分
        if 偏差 < 收敛阈值:
            break
    return 得分


def _归一化(节点id表: list[str], 个性化: dict[str, float] | None) -> dict[str, float]:
    """个性化向量归一化；无个性化则退化为均匀分布（不偏向任何节点）。"""
    if not 个性化:
        均匀 = 1.0 / len(节点id表)
        return {节点: 均匀 for 节点 in 节点id表}
    权重 = {节点: float(个性化.get(节点, 1.0)) for 节点 in 节点id表}
    总权 = sum(权重.values()) or float(len(节点id表))
    return {节点: 值 / 总权 for 节点, 值 in 权重.items()}
