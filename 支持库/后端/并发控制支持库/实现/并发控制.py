"""并发控制原子能力实现（不对外暴露，只经包级中文入口调用）。

职责：线程池/互斥锁/信号量/并发限制（参考易语言多线程支持库，保持原子）。
句柄模式：创建锁/信号量/线程池返回句柄，状态机统一生命周期。
纯标准库 concurrent.futures / threading。
"""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor

from 公共契约.基础类型.结果类型 import 结果
from 公共契约.句柄体系 import 句柄体系, 句柄类型_资源

句柄系统 = 句柄体系()
资源表: dict[str, dict] = {}
锁 = threading.Lock()


def _创建(类型: str, 对象: object, 说明: str) -> 结果:
    with 锁:
        句柄 = 句柄系统.创建句柄(句柄类型=句柄类型_资源, 资源id=f"并发-{类型}", 所有者="")
        资源表[句柄.句柄id] = {"类型": 类型, "对象": 对象}
    return 结果.成功结果({"句柄": 句柄.句柄id, "类型": 类型, "说明": 说明})


def _取(句柄: str, 类型: str) -> tuple[object | None, str]:
    有效, 原因 = 句柄系统.校验(句柄id=句柄)
    if not 有效:
        return None, 原因
    资源 = 资源表.get(句柄)
    if 资源 is None or 资源["类型"] != 类型:
        return None, f"{类型}句柄不存在"
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


def 获取信号量(句柄: str = None) -> 结果:
    """获取信号量（计数减1，可能阻塞）。返回 {已获取}。"""
    对象, 原因 = _取(句柄, "信号量")
    if 对象 is None:
        return 结果.失败("句柄失效", 原因, 来源="并发控制")
    对象.acquire()
    return 结果.成功结果({"已获取": True})


def 释放信号量(句柄: str = None) -> 结果:
    """释放信号量（计数加1）。返回 {已释放}。"""
    对象, 原因 = _取(句柄, "信号量")
    if 对象 is None:
        return 结果.失败("句柄失效", 原因, 来源="并发控制")
    对象.release()
    return 结果.成功结果({"已释放": True})


def 线程池执行(句柄: str = None, 任务列表: list = None, 超时秒: float = None) -> 结果:
    """线程池并发执行任务列表（每个任务 dict {函数, 参数}）。返回 {结果列表, 成功数, 失败数}。"""
    池, 原因 = _取(句柄, "线程池")
    if 池 is None:
        return 结果.失败("句柄失效", 原因, 来源="并发控制")
    if not isinstance(任务列表, list) or not 任务列表:
        return 结果.失败("参数不合法", "任务列表必须是非空列表", 来源="并发控制")
    结果列表 = []
    失败数 = 0
    for 任务 in 任务列表:
        if not isinstance(任务, dict):
            continue
        函数 = 任务.get("函数")
        参数 = 任务.get("参数") or {}
        if not callable(函数):
            continue
        try:
            值 = 池.submit(函数, **参数).result(timeout=超时秒)
            结果列表.append({"成功": True, "值": 值})
        except Exception as 错误:
            失败数 += 1
            结果列表.append({"成功": False, "错误": str(错误)})
    return 结果.成功结果({"结果列表": 结果列表, "成功数": len(结果列表) - 失败数, "失败数": 失败数})


def 释放句柄(句柄: str = None) -> 结果:
    """释放并发资源句柄（幂等，线程池关闭）。"""
    with 锁:
        资源 = 资源表.pop(句柄, None)
        if 资源 and 资源["类型"] == "线程池":
            try:
                资源["对象"].shutdown(wait=False)
            except Exception:
                pass
        句柄系统.失效(句柄, "释放")
    return 结果.成功结果({"句柄": 句柄, "已释放": True})
