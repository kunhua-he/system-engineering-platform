"""仓库地图 · 取仓库地图：Personalized PageRank 排名 + token 预算二分渲染。

两个关键做法（对齐 aider repo map）：

1. **锚点即个性化向量**：锚点命中的节点权重放大，PageRank 质量向它周边集中；
   无锚点 = 均匀分布（全局排名，不偏向）。
2. **预算用二分找最大可容纳前缀**，不是截断字符串：排名后的符号与文件头展平成
   有序渲染单元，二分「能容纳多少个完整单元」——收录的每一行都是完整的。
   粒度取**符号**而非文件：按文件二分时，排名第一的文件放不下就整张地图空掉
   （实测 200 token 预算下收录文件数=0），按符号二分才能给出可用的头几条。
"""

from __future__ import annotations

from 公共契约.基础类型.结果类型 import 结果
from 支持库.后端.代码解析支持库.仓库地图.实现.参数口径 import (
    参数错误, 取整数, 取文本, 取文本列表,
)
from 支持库.后端.代码解析支持库.仓库地图.实现.地图渲染 import (
    估算token, 展开单元, 渲染, 统计,
)
from 支持库.后端.代码解析支持库.仓库地图.实现.图库 import (
    关闭, 只读打开, 读边, 读节点, 落点, 来源,
)
from 支持库.后端.代码解析支持库.仓库地图.实现.页排名 import 页排名

token预算上限 = 200000
符号种类 = ("class", "function", "method")
锚点放大倍数 = 10.0


def 取仓库地图(*, 仓库根: str = "", 锚点: list | None = None,
               token预算: int = 4096, 库文件: str = "") -> 结果:
    """按 Personalized PageRank 排名 + token 预算二分渲染紧凑地图。"""
    try:
        根 = 取文本("仓库根", 仓库根, 必填=True)
        锚点表 = 取文本列表("锚点", 锚点)
        预算 = 取整数("token预算", token预算, 默认=4096, 最小=1, 最大=token预算上限)
        落点参数 = 取文本("库文件", 库文件, 必填=False)
    except 参数错误 as 错误:
        return 结果.失败(错误.错误码, 错误.说明, 来源=来源)
    连接结果 = 只读打开(落点(根, 落点参数))
    if not 连接结果.成功:
        return 连接结果
    连接 = 连接结果.值
    try:
        节点表 = 读节点(连接)
        边表 = 读边(连接)
    except Exception as 错误:  # 统一结果铁律：实现不外抛，真实原因原样回带
        return 结果.失败("查询失败", f"仓库地图读取失败: {错误}", 来源=来源)
    finally:
        关闭(连接)
    if not 节点表:
        return 结果.失败("查询失败", "仓库地图库内没有任何节点，请先调用 建符号图", 来源=来源)
    单元表 = 展开单元(_排文件(节点表, 边表, 锚点表))
    收录数, 地图文本 = _二分收录(单元表, 预算)
    收录文件数, 收录符号数 = 统计(单元表[:收录数])
    return 结果.成功结果({
        "地图文本": 地图文本,
        "收录文件数": 收录文件数,
        "收录符号数": 收录符号数,
        "预算": 预算,
        "已用预算": 估算token(地图文本),
        "是否截断": 收录数 < len(单元表),
    })


def _排文件(节点表: list[dict], 边表: list[dict], 锚点表: list[str]) -> list[dict]:
    """按 PageRank 得分把节点得分汇到文件上，文件块按 (-得分, 路径) 稳定排序。"""
    节点id表 = [str(节点["id"]) for 节点 in 节点表]
    加权边表 = [(str(边["source"]), str(边["target"]), float(边.get("weight") or 1.0))
              for 边 in 边表]
    得分表 = 页排名(节点id表, 加权边表, _个性化(节点表, 锚点表))
    文件得分: dict[str, float] = {}
    文件符号: dict[str, list[dict]] = {}
    for 节点 in 节点表:
        路径 = str(节点.get("file_path") or "")
        文件得分[路径] = 文件得分.get(路径, 0.0) + 得分表.get(str(节点["id"]), 0.0)
        if str(节点.get("kind") or "") in 符号种类:
            文件符号.setdefault(路径, []).append(节点)
    文件块表 = [{"路径": 路径, "得分": 文件得分[路径],
               "符号列表": _符号视图(文件符号.get(路径, []))} for 路径 in 文件得分]
    文件块表.sort(key=lambda 块: (-块["得分"], 块["路径"]))
    return 文件块表


def _符号视图(节点列表: list[dict]) -> list[dict]:
    """符号视图：只带渲染需要的四要素，按 起始行、名称 稳定排序。"""
    视图 = [{"类别": str(节点.get("kind") or ""),
            "名称": str(节点.get("name") or ""),
            "签名": str(节点.get("signature") or ""),
            "起始行": int(节点.get("start_line") or 0)} for 节点 in 节点列表]
    视图.sort(key=lambda 项: (项["起始行"], 项["名称"]))
    return 视图


def _个性化(节点表: list[dict], 锚点表: list[str]) -> dict[str, float] | None:
    """锚点作个性化向量：命中节点放大，其余为 1；无锚点（或全未命中）返回 None = 均匀分布。"""
    if not 锚点表:
        return None
    向量 = {str(节点["id"]): 1.0 for 节点 in 节点表}
    命中数 = 0
    for 节点 in 节点表:
        for 锚点 in 锚点表:
            if _命中(节点, 锚点):
                向量[str(节点["id"])] = 锚点放大倍数
                命中数 += 1
                break
    return 向量 if 命中数 else None


def _命中(节点: dict, 锚点: str) -> bool:
    """锚点命中判据：名称/路径/限定名精确相等，或路径后缀命中（锚点可给相对路径）。"""
    路径 = str(节点.get("file_path") or "")
    名称 = str(节点.get("name") or "")
    限定名 = str(节点.get("qualified_name") or "")
    return (锚点 == 名称 or 锚点 == 路径 or 锚点 == 限定名
            or 路径.endswith("/" + 锚点))


def _二分收录(单元表: list[dict], 预算: int) -> tuple[int, str]:
    """二分找「最大可容纳单元数」；返回 (收录单元数, 地图文本)。

    不是截断字符串：先按排名取前 N 个**完整单元**整体渲染，再二分 N 的最大可行值。
    估算 token 随 N 单调不减，二分成立；全程最多 log2(单元数) 次渲染。
    """
    全量文本 = 渲染(单元表)
    if 估算token(全量文本) <= 预算:
        return len(单元表), 全量文本
    低, 高 = 0, len(单元表) - 1
    while 低 < 高:
        中 = (低 + 高 + 1) // 2
        if 估算token(渲染(单元表[:中])) <= 预算:
            低 = 中
        else:
            高 = 中 - 1
    return 低, 渲染(单元表[:低])
