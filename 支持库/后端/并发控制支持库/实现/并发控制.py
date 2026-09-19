"""并发控制原子能力实现（不对外暴露，只经包级中文入口调用）。

职责：线程池/互斥锁/信号量/并发限制（参考易语言多线程支持库，保持原子）。
句柄模式：创建锁/信号量/线程池返回句柄，状态机统一生命周期。
纯标准库 concurrent.futures / threading。

**本文件是 `支持库.后端.并发控制支持库.实现` 的对外唯一实现面**：包级中文入口
`__init__.py` 与全仓调用方都按 `实现.并发控制 import X` 取符号，故拆分后本文件
逐名再导出（见下方「对外符号回托」），import 路径与公开契约零变化。
"""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from 公共契约.基础类型.结果类型 import 结果

# ---- 对外符号回托（拆分后逐名再导出：import 路径与公开契约零变化） ----
#
# 本文件原先 1016 行 / 全部顶层能力函数与模块级常量按职责簇搬进了同目录四个新模块，
# 但**对外名字一个不改、值一个不改**：下面五组 from-import 合起来就是搬家前的完整
# 公开面，因此 `from 支持库.后端.并发控制支持库.实现.并发控制 import X` 与
# `并发控制.X`（含包级 `__init__.py` 的 39 条逐名导入）两种用法都照旧成立。
#
# 搬家落点（每个文件职责见其头部文档串）：
#   并发句柄核心.py    → 句柄系统 / 资源表 / 锁 + _句柄键 / _创建 / _取（共享底座）
#   并发容量与调度.py  → 容量闸门 / lane 调度 / 主体串行桶（9 名 + 6 项簇内状态）
#   并发事件与管道.py  → 事件总线 / 流管道（10 名 + 6 项簇内状态）
#   并发组与任务收口.py → 并发组 / 结构化任务结果（7 名 + 3 项簇内状态）
#
# 留在这里的是**句柄原语本体**：互斥锁 / 信号量 / 线程池的创建与持句柄操作、
# 释放句柄（含线程池有界等待与资源账本保留），以及降级账本 `_记录降级`
# —— 它们与调用方直接持有的句柄语义绑在一起，必须在对外入口这一处看得见。
from 支持库.后端.并发控制支持库.实现.并发句柄核心 import (
    句柄系统,
    资源表,
    锁,
    _句柄键,
    _创建,
    _取,
)
from 支持库.后端.并发控制支持库.实现.并发容量与调度 import (
    容量闸门空闲清理秒,
    创建容量闸门,
    占用容量,
    释放容量,
    查询容量闸门,
    lane空闲清理秒,
    创建lane,
    lane排入,
    lane领取,
    lane完成,
    lane查询,
    登记主体桶,
    主体串行排入,
    主体串行领取,
    主体串行完成,
    主体串行查询,
    _容量闸门,
    _容量闸门锁,
    _lane表,
    _lane锁,
    _主体桶表,
)
from 支持库.后端.并发控制支持库.实现.并发事件与管道 import (
    创建事件总线,
    订阅事件,
    取消订阅,
    发布通知,
    发布决策,
    查询事件总线,
    创建流管道,
    管道写入,
    管道读取,
    查询流管道,
    _事件总线表,
    _事件总线锁,
    _流管道表,
    _流管道锁,
)
from 支持库.后端.并发控制支持库.实现.并发组与任务收口 import (
    创建并发组,
    组内提交,
    组内领取,
    组内完成,
    组内等待,
    查询并发组,
    结构化任务结果,
    _并发组表,
    _并发组锁,
)




降级记录表: list[str] = []  # 尽力清理/降级场景的异常记录（不阻断主流程），有界保留
降级记录上限 = 1000
线程池释放等待秒 = 5.0

def _记录降级(消息: Any) -> None:
    """有界记录降级/清理异常，避免无界增长。"""
    with 锁:
        降级记录表.append(str(消息))
        if len(降级记录表) > 降级记录上限:
            del 降级记录表[: len(降级记录表) - 降级记录上限]

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


def 获取锁(句柄: int = None, 超时秒: float = None) -> 结果:
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


def 释放锁(句柄: int = None) -> 结果:
    """释放互斥锁。返回 {已释放}。"""
    对象, 原因 = _取(句柄, "互斥锁")
    if 对象 is None:
        return 结果.失败("句柄失效", 原因, 来源="并发控制")
    try:
        对象.release()
        return 结果.成功结果({"已释放": True})
    except RuntimeError as 错误:
        return 结果.失败("释放锁失败", str(错误), 来源="并发控制")


def 获取信号量(句柄: int = None, 超时秒: float = None) -> 结果:
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


def 释放信号量(句柄: int = None) -> 结果:
    """释放信号量（计数加1）。返回 {已释放}。"""
    对象, 原因 = _取(句柄, "信号量")
    if 对象 is None:
        return 结果.失败("句柄失效", 原因, 来源="并发控制")
    对象.release()
    return 结果.成功结果({"已释放": True})


def 线程池执行(句柄: int = None, 任务列表: list = None, 超时秒: float = None) -> 结果:
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


def 释放句柄(句柄: int = None) -> 结果:
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
