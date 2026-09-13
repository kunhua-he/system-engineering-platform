"""删除守卫原子能力实现（不对外暴露，只经包级中文入口调用）。

职责：危险删除操作的三重保护（借鉴 TencentDB-Agent-Memory 删除守卫）：
1. 删除比例上限：目标表待删行占比 > 上限（默认 80%）→ 拒绝；
2. 空过滤条件：无条件/空过滤 → 拒绝；
3. 保护资产表：声明为资产/不可清空的表 → 拒绝。
只做检查判定，不执行任何删除；实际删除由调用方执行。
"""

from __future__ import annotations

from typing import Any

from 公共契约.基础类型.结果类型 import 结果

默认比例上限 = 0.8
默认保护表 = frozenset({"资产", "资产表", "用户", "角色", "权限", "凭证", "密钥", "订单", "交易"})


def _失败(错误码: str, 消息: str) -> 结果:
    return 结果.失败(错误码, 消息, 来源="删除守卫")


def 检查删除(目标表: str = None, 删除比例: float = None, 过滤条件: str = None,
              比例上限: float = None, 保护表: list = None) -> 结果:
    """检查一次删除操作是否安全。返回 {通过=true/false, 原因}。"""
    if not isinstance(目标表, str) or not 目标表.strip():
        return _失败("参数不合法", "目标表必须是非空字符串")
    上限 = 比例上限 if isinstance(比例上限, (int, float)) and 比例上限 > 0 else 默认比例上限
    保护 = frozenset(保护表) if isinstance(保护表, list) else 默认保护表
    # 1. 保护表检查
    if 目标表 in 保护:
        return 结果.成功结果({"通过": False, "原因": f"{目标表} 是受保护表，禁止删除"})
    # 2. 空过滤条件检查
    if not isinstance(过滤条件, str) or not 过滤条件.strip():
        return 结果.成功结果({"通过": False, "原因": "删除必须带过滤条件，拒绝无条件删除"})
    # 3. 删除比例检查（未知即拒绝：拿不到占比就无法证明没超上限，
    #    默认放行会让「占比>上限→拒绝」这重保护形同虚设，与 docstring 承诺不符）
    if isinstance(删除比例, bool) or not isinstance(删除比例, (int, float)):
        return 结果.成功结果({"通过": False, "原因": "删除比例未知，无法判定是否超上限，拒绝"})
    if 删除比例 > 上限:
        return 结果.成功结果({"通过": False, "原因": f"删除比例 {删除比例:.0%} 超过上限 {上限:.0%}，拒绝"})
    return 结果.成功结果({"通过": True, "原因": "允许"})


def 检查清空(目标表: str = None, 保护表: list = None) -> 结果:
    """检查清空整表操作。返回 {通过=true/false, 原因}。"""
    if not isinstance(目标表, str) or not 目标表.strip():
        return _失败("参数不合法", "目标表必须是非空字符串")
    保护 = frozenset(保护表) if isinstance(保护表, list) else 默认保护表
    if 目标表 in 保护:
        return 结果.成功结果({"通过": False, "原因": f"{目标表} 是受保护表，禁止清空"})
    return 结果.成功结果({"通过": True, "原因": "允许清空（非保护表）"})
