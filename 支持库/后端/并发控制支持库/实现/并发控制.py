"""并发控制原子能力实现（不对外暴露，只经包级中文入口调用）。

职责：线程池/互斥锁/信号量/并发限制（参考易语言多线程支持库，保持原子）。
句柄模式：创建锁/信号量/线程池返回句柄，状态机统一生命周期。
纯标准库 concurrent.futures / threading。
"""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from 公共契约.基础类型.结果类型 import 结果
from 公共契约.句柄体系 import 句柄体系, 句柄类型_资源

句柄系统 = 句柄体系()
资源表: dict[int, dict] = {}
锁 = threading.Lock()



降级记录表: list[str] = []  # 尽力清理/降级场景的异常记录（不阻断主流程），有界保留
降级记录上限 = 1000
线程池释放等待秒 = 5.0

def _记录降级(消息: Any) -> None:
    """有界记录降级/清理异常，避免无界增长。"""
    with 锁:
        降级记录表.append(str(消息))
        if len(降级记录表) > 降级记录上限:
            del 降级记录表[: len(降级记录表) - 降级记录上限]

def _句柄键(句柄: str | int) -> int:
    """资源表与公开网关统一使用整数句柄。"""
    return int(句柄)

def _创建(类型: str, 对象: object, 说明: str) -> 结果:
    with 锁:
        句柄 = 句柄系统.创建句柄(句柄类型=句柄类型_资源, 资源id=f"并发-{类型}", 所有者="")
        句柄键 = _句柄键(句柄.句柄id)
        资源表[句柄键] = {"类型": 类型, "对象": 对象, "状态": "有效"}
    return 结果.成功结果({"句柄": 句柄键, "类型": 类型, "说明": 说明})


def _取(句柄: str, 类型: str) -> tuple[object | None, str]:
    键 = _句柄键(句柄)
    try:
        状态机id = int(键)
    except ValueError:
        return None, f"句柄格式不合法: {句柄}"
    有效, 原因 = 句柄系统.校验(句柄id=状态机id)
    if not 有效:
        return None, 原因
    资源 = 资源表.get(键)
    if 资源 is None or 资源["类型"] != 类型:
        return None, f"{类型}句柄不存在"
    if 资源.get("状态", "有效") != "有效":
        return None, f"{类型}句柄正在释放或释放失败"
    return 资源["对象"], ""


def 创建互斥锁(超时秒: int = None) -> 结果:
    """创建互斥锁。返回句柄。"""
    return _创建("互斥锁", threading.Lock(), "互斥锁已创建；持句柄 获取锁/释放锁")


def 创建信号量(初始值: int = None, 超时秒: int = None) -> 结果:
    """创建信号量。返回句柄。"""
    值 = 初始值 if isinstance(初始值, int) and 初始值 > 0 else 1
    return _创建("信号量", threading.Semaphore(值), f"信号量已创建（初始 {值}）")


def 创建线程池(最大线程数: int = None, 超时秒: int = None) -> 结果:
    """创建线程池。返回句柄。"""
    数量 = 最大线程数 if isinstance(最大线程数, int) and 最大线程数 > 0 else 4
    try:
        池 = ThreadPoolExecutor(max_workers=数量)
    except Exception as 错误:
        return 结果.失败("创建失败", str(错误), 来源="并发控制")
    return _创建("线程池", 池, f"线程池已创建（最大 {数量} 线程）")


def 获取锁(句柄: str = None, 超时秒: float = None) -> 结果:
    """获取互斥锁。返回 {已获取}。"""
    对象, 原因 = _取(句柄, "互斥锁")
    if 对象 is None:
        return 结果.失败("句柄失效", 原因, 来源="并发控制")
    if 超时秒 is None:
        对象.acquire()
        return 结果.成功结果({"已获取": True})
    try:
        已获取 = 对象.acquire(timeout=超时秒)
        return 结果.成功结果({"已获取": bool(已获取)})
    except Exception as 错误:
        return 结果.失败("获取锁失败", str(错误), 来源="并发控制")


def 释放锁(句柄: str = None) -> 结果:
    """释放互斥锁。返回 {已释放}。"""
    对象, 原因 = _取(句柄, "互斥锁")
    if 对象 is None:
        return 结果.失败("句柄失效", 原因, 来源="并发控制")
    try:
        对象.release()
        return 结果.成功结果({"已释放": True})
    except RuntimeError as 错误:
        return 结果.失败("释放锁失败", str(错误), 来源="并发控制")


def 获取信号量(句柄: str = None, 超时秒: float = None) -> 结果:
    """获取信号量（计数减1；可设超时，超时返回未获取，不永久阻塞）。返回 {已获取}。"""
    对象, 原因 = _取(句柄, "信号量")
    if 对象 is None:
        return 结果.失败("句柄失效", 原因, 来源="并发控制")
    try:
        if 超时秒 is None:
            已获取 = 对象.acquire()
        else:
            已获取 = 对象.acquire(timeout=超时秒)
        return 结果.成功结果({"已获取": bool(已获取)})
    except Exception as 错误:
        return 结果.失败("获取信号量失败", str(错误), 来源="并发控制")


def 释放信号量(句柄: str = None) -> 结果:
    """释放信号量（计数加1）。返回 {已释放}。"""
    对象, 原因 = _取(句柄, "信号量")
    if 对象 is None:
        return 结果.失败("句柄失效", 原因, 来源="并发控制")
    对象.release()
    return 结果.成功结果({"已释放": True})


def 线程池执行(句柄: str = None, 任务列表: list = None, 超时秒: float = None) -> 结果:
    """线程池并发执行任务列表（每个任务 dict {函数, 参数}）。返回 {结果列表, 成功数, 失败数}。

    先批量 submit 全部合法任务再按原顺序收集 Future 结果，避免逐项
    submit().result() 把线程池退化成串行；超时/异常按任务收集失败。
    """
    池, 原因 = _取(句柄, "线程池")
    if 池 is None:
        return 结果.失败("句柄失效", 原因, 来源="并发控制")
    if not isinstance(任务列表, list) or not 任务列表:
        return 结果.失败("参数不合法", "任务列表必须是非空列表", 来源="并发控制")
    提交表: list[tuple[dict, object]] = []  # (原始任务, Future)
    for 任务 in 任务列表:
        if not isinstance(任务, dict):
            continue
        函数 = 任务.get("函数")
        参数 = 任务.get("参数") or {}
        if not callable(函数):
            continue
        try:
            未来 = 池.submit(函数, **参数)
            提交表.append((任务, 未来))
        except Exception as 错误:
            提交表.append((任务, 错误))
    结果列表 = []
    失败数 = 0
    for 任务, 未来 in 提交表:
        try:
            值 = 未来.result(timeout=超时秒)
            结果列表.append({"成功": True, "值": 值})
        except Exception as 错误:
            失败数 += 1
            结果列表.append({"成功": False, "错误": str(错误)})
    return 结果.成功结果({"结果列表": 结果列表, "成功数": len(结果列表) - 失败数, "失败数": 失败数})


def 释放句柄(句柄: str = None) -> 结果:
    """释放并发资源句柄（线程池有界等待，未收敛时保留账本）。"""
    if isinstance(句柄, bool) or not isinstance(句柄, int) or not 1 <= 句柄 <= 999999:
        return 结果.失败("参数不合法", "句柄必须是1到999999的整数", 来源="并发控制")
    键 = _句柄键(句柄)
    with 锁:
        资源 = 资源表.get(键)
        if 资源 and 资源["类型"] == "线程池":
            池 = 资源["对象"]
            if 资源.get("状态") == "释放中":
                return 结果.失败("资源释放中", "线程池已有释放请求，等待收敛后重试", 来源="并发控制")
            资源["状态"] = "释放中"
        else:
            池 = None
    if 池 is not None:
        完成 = threading.Event()

        def 关闭线程池() -> None:
            try:
                池.shutdown(wait=True, cancel_futures=True)
            except Exception as 错误:
                _记录降级(错误)
            finally:
                完成.set()

        threading.Thread(target=关闭线程池, daemon=True,
                         name=f"线程池释放-{句柄}").start()
        if not 完成.wait(线程池释放等待秒):
            with 锁:
                if 键 in 资源表:
                    资源表[键]["状态"] = "释放失败"
            return 结果.失败(
                "资源未收敛", "线程池结束请求已发出但未收敛，资源账本已保留供重试",
                来源="并发控制", 可重试=True,
                详情={"句柄": 句柄, "状态": "结束请求已发出但未收敛"})
        try:
            with 锁:
                资源表.pop(键, None)
                句柄系统.失效(int(键), "释放")
            return 结果.成功结果({"句柄": 句柄, "状态": "已结束并已释放", "已释放": True})
        except Exception as 错误:
            _记录降级(错误)
            return 结果.失败("资源未收敛", "线程池已结束但句柄收口失败，资源账本已保留供核对",
                            来源="并发控制", 可重试=True)
    with 锁:
        资源表.pop(键, None)
        try:
            句柄系统.失效(int(键), "释放")
        except ValueError:
            pass
    if 资源 is not None:
        return 结果.成功结果({"句柄": 句柄, "状态": "已结束并已释放", "已释放": True})
    return 结果.成功结果({"句柄": 句柄, "状态": "未找到且已幂等", "已释放": True})


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
