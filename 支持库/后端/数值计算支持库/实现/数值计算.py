"""数值计算原子能力实现（不对外暴露，只经包级中文入口调用）。

职责：常用数值计算（参考易语言数值计算支持库，保持原子）。
四舍五入/取整/绝对值/最大/最小/随机数/求和/平均值。
只做数值计算，不做业务逻辑；纯标准库。
"""

from __future__ import annotations

import math
import random
from decimal import Decimal, ROUND_HALF_UP

from 公共契约.基础类型.结果类型 import 结果


def 四舍五入(数值: float = None, 小数位: int = None) -> 结果:
    """四舍五入到指定小数位。返回 {结果}。"""
    if not isinstance(数值, (int, float)) or isinstance(数值, bool):
        return 结果.失败("参数不合法", "数值必须是数字", 来源="数值计算")
    位 = 小数位 if isinstance(小数位, int) else 0
    try:
        d = Decimal(str(数值)).quantize(Decimal(1).scaleb(-位), rounding=ROUND_HALF_UP)
        return 结果.成功结果({"结果": float(d), "小数位": 位})
    except Exception as 错误:
        return 结果.失败("计算失败", str(错误), 来源="数值计算")


def 取整(数值: float = None, 方式: str = None) -> 结果:
    """取整。方式：向下/向上/四舍五入。返回 {结果}。"""
    if not isinstance(数值, (int, float)) or isinstance(数值, bool):
        return 结果.失败("参数不合法", "数值必须是数字", 来源="数值计算")
    模式 = (方式 or "四舍五入").strip()
    if 模式 == "向下":
        结果值 = math.floor(数值)
    elif 模式 == "向上":
        结果值 = math.ceil(数值)
    elif 模式 == "四舍五入":
        结果值 = round(数值)
    else:
        return 结果.失败("参数不合法", f"取整方式必须是 向下/向上/四舍五入: {方式}", 来源="数值计算")
    return 结果.成功结果({"结果": 结果值, "方式": 模式})


def 绝对值(数值: float = None) -> 结果:
    """绝对值。返回 {结果}。"""
    if not isinstance(数值, (int, float)) or isinstance(数值, bool):
        return 结果.失败("参数不合法", "数值必须是数字", 来源="数值计算")
    return 结果.成功结果({"结果": abs(数值)})


def 最大值(数值列表: list = None) -> 结果:
    """列表最大值。返回 {结果, 索引}。"""
    if not isinstance(数值列表, list) or not 数值列表:
        return 结果.失败("参数不合法", "数值列表必须是非空列表", 来源="数值计算")
    if not all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in 数值列表):
        return 结果.失败("参数不合法", "数值列表必须全部是数字", 来源="数值计算")
    最大值 = max(数值列表)
    return 结果.成功结果({"结果": 最大值, "索引": 数值列表.index(最大值)})


def 最小值(数值列表: list = None) -> 结果:
    """列表最小值。返回 {结果, 索引}。"""
    if not isinstance(数值列表, list) or not 数值列表:
        return 结果.失败("参数不合法", "数值列表必须是非空列表", 来源="数值计算")
    if not all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in 数值列表):
        return 结果.失败("参数不合法", "数值列表必须全部是数字", 来源="数值计算")
    最小值 = min(数值列表)
    return 结果.成功结果({"结果": 最小值, "索引": 数值列表.index(最小值)})


def 随机数(下限: int = None, 上限: int = None) -> 结果:
    """随机整数。返回 {结果}。"""
    低 = 下限 if isinstance(下限, int) else 0
    高 = 上限 if isinstance(上限, int) else 100
    if 低 > 高:
        return 结果.失败("参数不合法", "下限不能大于上限", 来源="数值计算")
    return 结果.成功结果({"结果": random.randint(低, 高)})


def 求和(数值列表: list = None) -> 结果:
    """列表求和。返回 {结果}。"""
    if not isinstance(数值列表, list) or not 数值列表:
        return 结果.失败("参数不合法", "数值列表必须是非空列表", 来源="数值计算")
    if not all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in 数值列表):
        return 结果.失败("参数不合法", "数值列表必须全部是数字", 来源="数值计算")
    return 结果.成功结果({"结果": sum(数值列表)})


def 平均值(数值列表: list = None) -> 结果:
    """列表平均值。返回 {结果}。"""
    if not isinstance(数值列表, list) or not 数值列表:
        return 结果.失败("参数不合法", "数值列表必须是非空列表", 来源="数值计算")
    if not all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in 数值列表):
        return 结果.失败("参数不合法", "数值列表必须全部是数字", 来源="数值计算")
    return 结果.成功结果({"结果": sum(数值列表) / len(数值列表)})

def 分位数(数值列表: list = None, 百分位: float = None, 小数位: int = 3) -> 结果:
    """计算百分位数（线性插值法，保证单调：P50 ≤ P95 ≤ P99 ≤ max）。

    与"取序号法"（round((n-1)*pct)）不同，本实现按标准线性插值：
    位置 = (n-1) * pct，在相邻两值间按小数部分插值。小样本/重复值/奇偶/单样本均可。
    百分位取值 0~1（如 0.95 表示 P95）。
    """
    if not isinstance(数值列表, list):
        return 结果.失败("参数不合法", "数值列表必须是列表型", 来源="数值计算")
    if not isinstance(百分位, (int, float)) or isinstance(百分位, bool):
        return 结果.失败("参数不合法", "百分位必须是数值", 来源="数值计算")
    if not 0 <= float(百分位) <= 1:
        return 结果.失败("参数不合法", "百分位必须在 0 到 1 之间", 来源="数值计算")
    数值 = [float(值) for 值 in 数值列表 if isinstance(值, (int, float)) and not isinstance(值, bool)]
    if not 数值:
        return 结果.成功结果({"分位数值": None, "样本数": 0, "百分位": float(百分位)})

    排序 = sorted(数值)
    n = len(排序)
    if n == 1:
        值 = 排序[0]
    else:
        位置 = (n - 1) * float(百分位)
        下 = int(位置)
        上 = min(n - 1, 下 + 1)
        比例 = 位置 - 下
        值 = 排序[下] + (排序[上] - 排序[下]) * 比例
    位数 = int(小数位) if isinstance(小数位, int) and not isinstance(小数位, bool) else 3
    return 结果.成功结果({
        "分位数值": round(值, 位数), "样本数": n, "百分位": float(百分位),
        "最小值": round(排序[0], 位数), "中位数": round(排序[(n - 1) // 2], 位数), "最大值": round(排序[-1], 位数),
    })
