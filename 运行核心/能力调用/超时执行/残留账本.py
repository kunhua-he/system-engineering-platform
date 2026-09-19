"""残留账本：超时后仍在运行的执行单元记录 + 两个进程级诊断快照。

源：`运行核心/能力调用/超时执行.py`（20260919 拆分，开工-20260919-225500-e4a1）。
"""

from __future__ import annotations

from 运行核心.能力调用.超时执行.形态判定 import 默认执行形态

from dataclasses import dataclass
from dataclasses import field
from typing import Any
from 公共契约.基础类型.逻辑类型 import 真, 假
import threading
import time

@dataclass
class 残留执行:
    """一次超时后仍在运行（或刚结束）的执行单元。"""

    序号: int
    能力id: str
    包id: str
    请求id: str
    线程名: str
    超时秒: float
    开始时刻: float
    执行形态: str = 默认执行形态
    可取消: bool = 假
    完成事件: threading.Event = field(default_factory=threading.Event)

    def 仍在运行(self) -> bool:
        return not self.完成事件.is_set()

    def 已运行秒(self) -> float:
        return max(0.0, time.monotonic() - self.开始时刻)

    def 转字典(self) -> dict[str, Any]:
        return {
            "序号": self.序号,
            "能力id": self.能力id,
            "包id": self.包id,
            "请求id": self.请求id,
            "线程名": self.线程名,
            "执行形态": self.执行形态,
            "可取消": self.可取消,
            "超时秒": self.超时秒,
            "已运行秒": round(self.已运行秒(), 3),
            "仍在运行": self.仍在运行(),
        }


def 残留账本快照() -> dict[str, Any]:
    """进程级残留执行账本快照（诊断用：超时后到底还有多少东西在跑）。"""
    from 运行核心.能力调用.超时执行.执行器_核心 import 执行器
    return 执行器.状态快照()


def 线程准入快照() -> dict[str, Any]:
    """进程级执行线程准入快照（诊断用：线程侧上限、占用、满载拒绝留痕）。"""
    from 运行核心.能力调用.超时执行.执行器_核心 import 执行器
    全量 = 执行器.状态快照()
    return {键: 值 for 键, 值 in 全量.items()
            if 键 in ("全局执行线程上限", "每能力执行线程上限", "全局执行线程占用",
                      "准入后端", "准入降级说明", "累计准入拒绝数", "准入释放失败数",
                      "准入拒绝明细", "每能力占用明细", "已登记能力闸门数",
                      "走兜底闸门次数")}
