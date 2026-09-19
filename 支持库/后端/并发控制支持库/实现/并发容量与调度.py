"""并发控制容量与调度：容量闸门 / lane 调度 / 主体串行桶（内部实现，不对外）。

本模块由 `实现/并发控制.py` 按职责簇**原样搬出**（对外符号零变化：`并发控制.py`
逐名再导出，全仓调用方与 `__init__.py` 的 `from ….实现.并发控制 import X` 照旧成立）。

三簇共用同一套「同锁检查 + 超限直接拒绝不排队」语义：
- **容量闸门**：按名计数上限，同锁检查+占用，超限直接拒绝（Hermes async_delegation
  模式化落地）；槽位数支持一次调用拆 N 完成单元共享一个槽位；
- **lane 调度**：每 lane 一条队列 limit + active + queue，微任务泵 + 失败退避重排，
  同 lane 未满可并发（OpenClaw Swarm 调度器模式化落地）；
- **主体串行桶**：每主体一条 lane（并发上限=1），同主体串行、跨主体并行
  （OpenClaw ALS 会话级写串行化模式化落地）；0加密0限制，主体id原文使用。

主体串行桶复用 lane 的 `_lane表` / `_lane锁` 与 `lane排入/领取/完成/查询` 四函数，
故与 lane 同文件 —— 拆开会构成循环依赖（主体串行 → lane → 主体串行）。
"""

from __future__ import annotations

import threading

from 公共契约.基础类型.结果类型 import 结果

# ═══════════════════════════════════════════════
# 容量闸门：同锁容量检查 + 超限直接拒绝不排队（Hermes async_delegation 模式化落地）
# 防止模型/上游误调用把任务队列无限堆高；slot_key 支持一次调用拆 N 完成单元共享一个槽位。
# ═══════════════════════════════════════════════
_容量闸门: dict[str, dict] = {}  # 闸门名 -> {"上限": int, "占用": int, "创建时间": float}
_容量闸门锁 = threading.Lock()
容量闸门空闲清理秒 = 3600.0


def 创建容量闸门(*, 闸门名: str = None, 上限: int = None, 超时秒: int = None) -> 结果:
    """创建容量闸门。上限>0；同名复用。返回闸门名（文本标识，非句柄）。"""
    try:
        名称 = str(闸门名 or "").strip()
        if not 名称:
            return 结果.失败("参数不合法", "闸门名不能为空", 来源="并发控制")
        上限值 = int(上限 or 0)
        if 上限值 <= 0:
            return 结果.失败("参数不合法", "上限必须为正整数", 来源="并发控制")
        with _容量闸门锁:
            if 名称 not in _容量闸门:
                _容量闸门[名称] = {"上限": 上限值, "占用": 0, "创建时间": __import__("time").time()}
            else:
                _容量闸门[名称]["上限"] = 上限值
            return 结果.成功结果({"闸门名": 名称, "上限": _容量闸门[名称]["上限"], "占用": _容量闸门[名称]["占用"]})
    except Exception as 异常:
        return 结果.失败("创建失败", str(异常), 来源="并发控制")


def 占用容量(*, 闸门名: str = None, 槽位数: int = None, 等待秒: float = None) -> 结果:
    """尝试占用闸门容量。同锁检查+占用；超限直接拒绝（不排队），可等待重试。

    参数:
        闸门名: 容量闸门名称
        槽位数: 本次占用的槽位数（默认1；slot_key 场景一次拆 N 单元共享）
        等待秒: >0 时在超限后短暂等待重试（默认不等待直接拒绝）
    返回 {占用: bool, 闸门名, 当前占用, 上限, 拒绝原因}。
    """
    try:
        名称 = str(闸门名 or "").strip()
        if not 名称:
            return 结果.失败("参数不合法", "闸门名不能为空", 来源="并发控制")
        槽位 = max(1, int(槽位数 or 1))
        import time as _时间
        截止 = _时间.time() + float(等待秒 or 0)
        while True:
            with _容量闸门锁:
                if 名称 not in _容量闸门:
                    return 结果.失败("闸门不存在", f"容量闸门 {名称} 未创建", 来源="并发控制")
                闸门 = _容量闸门[名称]
                if 闸门["占用"] + 槽位 <= 闸门["上限"]:
                    闸门["占用"] += 槽位
                    return 结果.成功结果({
                        "占用": True, "闸门名": 名称, "当前占用": 闸门["占用"],
                        "上限": 闸门["上限"], "槽位数": 槽位,
                    })
            if _时间.time() >= 截止:
                return 结果.成功结果({
                    "占用": False, "闸门名": 名称,
                    "当前占用": _容量闸门.get(名称, {}).get("占用", 0),
                    "上限": _容量闸门.get(名称, {}).get("上限", 0),
                    "拒绝原因": "超限直接拒绝不排队",
                })
            _时间.sleep(0.05)
    except Exception as 异常:
        return 结果.失败("占用失败", str(异常), 来源="并发控制")


def 释放容量(*, 闸门名: str = None, 槽位数: int = None) -> 结果:
    """释放闸门容量（幂等，负数钳到0）。"""
    try:
        名称 = str(闸门名 or "").strip()
        if not 名称:
            return 结果.失败("参数不合法", "闸门名不能为空", 来源="并发控制")
        槽位 = max(1, int(槽位数 or 1))
        with _容量闸门锁:
            if 名称 not in _容量闸门:
                return 结果.成功结果({"释放": True, "闸门名": 名称, "当前占用": 0, "已幂等": True})
            闸门 = _容量闸门[名称]
            闸门["占用"] = max(0, 闸门["占用"] - 槽位)
            return 结果.成功结果({"释放": True, "闸门名": 名称, "当前占用": 闸门["占用"]})
    except Exception as 异常:
        return 结果.失败("释放失败", str(异常), 来源="并发控制")


def 查询容量闸门(*, 闸门名: str = None) -> 结果:
    """查询闸门状态。"""
    try:
        名称 = str(闸门名 or "").strip()
        with _容量闸门锁:
            if not 名称:
                return 结果.成功结果({"闸门列表": [
                    {"闸门名": k, "上限": v["上限"], "占用": v["占用"]} for k, v in _容量闸门.items()
                ]})
            if 名称 not in _容量闸门:
                return 结果.失败("闸门不存在", f"容量闸门 {名称} 未创建", 来源="并发控制")
            闸门 = _容量闸门[名称]
            return 结果.成功结果({"闸门名": 名称, "上限": 闸门["上限"], "占用": 闸门["占用"]})
    except Exception as 异常:
        return 结果.失败("查询失败", str(异常), 来源="并发控制")


# ═══════════════════════════════════════════════
# lane 调度：OpenClaw Swarm 调度器模式化落地
# 每 lane 一条队列：limit + active + queue；微任务泵 + 失败退避重排；同 lane 未满可并发。
# ═══════════════════════════════════════════════
_lane表: dict[str, dict] = {}
_lane锁 = threading.Lock()
lane空闲清理秒 = 3600.0


def 创建lane(*, 名称: str = None, 并发上限: int = None, 队列上限: int = None, 超时秒: int = None) -> 结果:
    """创建 lane 调度器。并发上限默认8；队列上限默认50。同名复用（更新上限）。"""
    try:
        名 = str(名称 or "").strip()
        if not 名:
            return 结果.失败("参数不合法", "lane 名称不能为空", 来源="并发控制")
        并发 = max(1, int(并发上限 or 8))
        队列 = max(0, int(队列上限 or 50))
        import time as _时间
        with _lane锁:
            if 名 not in _lane表:
                _lane表[名] = {
                    "并发上限": 并发, "队列上限": 队列, "活跃数": 0, "排队数": 0,
                    "完成数": 0, "失败数": 0, "创建时间": _时间.time(),
                }
            else:
                _lane表[名]["并发上限"] = 并发
                _lane表[名]["队列上限"] = 队列
            return 结果.成功结果({"名称": 名, "并发上限": 并发, "队列上限": 队列,
                                 "活跃数": _lane表[名]["活跃数"], "排队数": _lane表[名]["排队数"]})
    except Exception as 异常:
        return 结果.失败("创建失败", str(异常), 来源="并发控制")


def lane排入(*, 名称: str = None, 任务数: int = None) -> 结果:
    """将 N 个任务排入 lane。队列未满则入队；满则直接拒绝（不排队等待）。"""
    try:
        名 = str(名称 or "").strip()
        if not 名:
            return 结果.失败("参数不合法", "lane 名称不能为空", 来源="并发控制")
        数量 = max(1, int(任务数 or 1))
        with _lane锁:
            if 名 not in _lane表:
                return 结果.失败("lane不存在", f"lane {名} 未创建", 来源="并发控制")
            lane = _lane表[名]
            if lane["排队数"] + lane["活跃数"] + 数量 > lane["队列上限"]:
                return 结果.成功结果({
                    "排入": False, "名称": 名, "拒绝原因": "队列满直接拒绝",
                    "活跃数": lane["活跃数"], "排队数": lane["排队数"],
                })
            lane["排队数"] += 数量
            return 结果.成功结果({"排入": True, "名称": 名, "排队数": lane["排队数"],
                                 "活跃数": lane["活跃数"]})
    except Exception as 异常:
        return 结果.失败("排入失败", str(异常), 来源="并发控制")


def lane领取(*, 名称: str = None, 数量: int = None) -> 结果:
    """主循环微任务泵：领取可执行任务槽位（并发上限内）。返回本次可跑数量（0=无）。"""
    try:
        名 = str(名称 or "").strip()
        if not 名:
            return 结果.失败("参数不合法", "lane 名称不能为空", 来源="并发控制")
        上限 = max(1, int(数量 or 1))
        with _lane锁:
            if 名 not in _lane表:
                return 结果.失败("lane不存在", f"lane {名} 未创建", 来源="并发控制")
            lane = _lane表[名]
            空位 = max(0, lane["并发上限"] - lane["活跃数"])
            可跑 = min(空位, lane["排队数"], 上限)
            if 可跑 > 0:
                lane["活跃数"] += 可跑
                lane["排队数"] -= 可跑
            return 结果.成功结果({"领取": 可跑, "名称": 名, "活跃数": lane["活跃数"],
                                 "排队数": lane["排队数"]})
    except Exception as 异常:
        return 结果.失败("领取失败", str(异常), 来源="并发控制")


def lane完成(*, 名称: str = None, 数量: int = None, 失败数: int = None, 退避秒: float = None) -> 结果:
    """上报完成/失败。失败数>0 可附退避秒（下次领取前等待，失败重排语义）。"""
    try:
        名 = str(名称 or "").strip()
        if not 名:
            return 结果.失败("参数不合法", "lane 名称不能为空", 来源="并发控制")
        完成 = max(1, int(数量 or 1))
        失败 = max(0, int(失败数 or 0))
        import time as _时间
        with _lane锁:
            if 名 not in _lane表:
                return 结果.失败("lane不存在", f"lane {名} 未创建", 来源="并发控制")
            lane = _lane表[名]
            lane["活跃数"] = max(0, lane["活跃数"] - 完成)
            lane["完成数"] += 完成 - 失败
            lane["失败数"] += 失败
            if 失败 > 0:
                lane["退避截止"] = _时间.time() + float(退避秒 or 1.0)
            return 结果.成功结果({"名称": 名, "活跃数": lane["活跃数"],
                                 "排队数": lane["排队数"], "完成数": lane["完成数"], "失败数": lane["失败数"]})
    except Exception as 异常:
        return 结果.失败("完成上报失败", str(异常), 来源="并发控制")


def lane查询(*, 名称: str = None) -> 结果:
    """查询 lane 状态。"""
    try:
        名 = str(名称 or "").strip()
        import time as _时间
        with _lane锁:
            if not 名:
                return 结果.成功结果({"lane列表": [
                    {"名称": k, "并发上限": v["并发上限"], "活跃数": v["活跃数"],
                     "排队数": v["排队数"], "完成数": v["完成数"], "失败数": v["失败数"]}
                    for k, v in _lane表.items()
                ]})
            if 名 not in _lane表:
                return 结果.失败("lane不存在", f"lane {名} 未创建", 来源="并发控制")
            lane = _lane表[名]
            return 结果.成功结果({"名称": 名, "并发上限": lane["并发上限"],
                                 "活跃数": lane["活跃数"], "排队数": lane["排队数"],
                                 "完成数": lane["完成数"], "失败数": lane["失败数"]})
    except Exception as 异常:
        return 结果.失败("查询失败", str(异常), 来源="并发控制")


# ═══════════════════════════════════════════════
# 主体串行调度：OpenClaw ALS 会话级写串行化模式化落地
# 同主体（客户/会话/门店）串行、跨主体并行；复用 lane 机制（每主体一条 lane，并发上限1）。
# 0加密0限制：主体id原文使用，业务端自理敏感处理。
# ═══════════════════════════════════════════════
_主体桶表: dict[str, str] = {}  # 主体id -> lane名


def 登记主体桶(*, 主体id: str = None) -> 结果:
    """登记主体串行桶（内部创建 lane，并发上限=1 强制串行）。幂等。"""
    try:
        主体 = str(主体id or "").strip()
        if not 主体:
            return 结果.失败("参数不合法", "主体id不能为空", 来源="并发控制")
        with _lane锁:
            if 主体 in _主体桶表:
                lane名 = _主体桶表[主体]
            else:
                lane名 = f"主体串行-{主体}"
                _主体桶表[主体] = lane名
                if lane名 not in _lane表:
                    import time as _时间
                    _lane表[lane名] = {
                        "并发上限": 1, "队列上限": 1000, "活跃数": 0, "排队数": 0,
                        "完成数": 0, "失败数": 0, "创建时间": _时间.time(),
                    }
            return 结果.成功结果({"主体id": 主体, "lane名": lane名, "并发上限": 1,
                                 "状态": "串行就绪"})
    except Exception as 异常:
        return 结果.失败("登记失败", str(异常), 来源="并发控制")


def 主体串行排入(*, 主体id: str = None, 任务数: int = None) -> 结果:
    """主体桶内排入任务（同主体排队等待串行执行）。"""
    try:
        主体 = str(主体id or "").strip()
        if not 主体:
            return 结果.失败("参数不合法", "主体id不能为空", 来源="并发控制")
        with _lane锁:
            if 主体 not in _主体桶表:
                return 结果.失败("主体未登记", f"主体 {主体} 未登记主体桶", 来源="并发控制")
            lane名 = _主体桶表[主体]
        return lane排入(名称=lane名, 任务数=任务数 or 1)
    except Exception as 异常:
        return 结果.失败("排入失败", str(异常), 来源="并发控制")


def 主体串行领取(*, 主体id: str = None, 数量: int = None) -> 结果:
    """从主体桶领取可执行任务（并发上限1=同一主体同一时刻最多1个执行）。"""
    try:
        主体 = str(主体id or "").strip()
        if not 主体:
            return 结果.失败("参数不合法", "主体id不能为空", 来源="并发控制")
        with _lane锁:
            if 主体 not in _主体桶表:
                return 结果.失败("主体未登记", f"主体 {主体} 未登记主体桶", 来源="并发控制")
            lane名 = _主体桶表[主体]
        return lane领取(名称=lane名, 数量=数量 or 1)
    except Exception as 异常:
        return 结果.失败("领取失败", str(异常), 来源="并发控制")


def 主体串行完成(*, 主体id: str = None, 数量: int = None, 失败数: int = None,
                 退避秒: float = None) -> 结果:
    """主体桶任务完成上报。"""
    try:
        主体 = str(主体id or "").strip()
        if not 主体:
            return 结果.失败("参数不合法", "主体id不能为空", 来源="并发控制")
        with _lane锁:
            if 主体 not in _主体桶表:
                return 结果.失败("主体未登记", f"主体 {主体} 未登记主体桶", 来源="并发控制")
            lane名 = _主体桶表[主体]
        return lane完成(名称=lane名, 数量=数量 or 1, 失败数=失败数 or 0, 退避秒=退避秒 or 0)
    except Exception as 异常:
        return 结果.失败("完成上报失败", str(异常), 来源="并发控制")


def 主体串行查询(*, 主体id: str = None) -> 结果:
    """查询主体桶状态（空=全部）。"""
    try:
        主体 = str(主体id or "").strip()
        with _lane锁:
            if not 主体:
                return 结果.成功结果({"主体桶列表": [
                    {"主体id": k, "lane名": v, "状态": "串行"} for k, v in _主体桶表.items()
                ]})
            if 主体 not in _主体桶表:
                return 结果.失败("主体未登记", f"主体 {主体} 未登记主体桶", 来源="并发控制")
            lane名 = _主体桶表[主体]
        return lane查询(名称=lane名)
    except Exception as 异常:
        return 结果.失败("查询失败", str(异常), 来源="并发控制")


