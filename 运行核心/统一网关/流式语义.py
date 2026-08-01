"""流式语义：能力契约的流式/事件/句柄返回类型与流式调用管理。

能力契约明确：普通返回/流式返回/事件返回/任务句柄返回/资源句柄返回。
流式调用支持：首个事件/中间事件/完成事件/失败事件/取消/超时/客户端
断开/提供者崩溃。客户端断开后必须释放对应任务和资源。
"""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable

返回类型_普通 = "普通返回"
返回类型_流式 = "流式返回"
返回类型_事件 = "事件返回"
返回类型_任务句柄 = "任务句柄返回"
返回类型_资源句柄 = "资源句柄返回"

事件_首个 = "首个事件"
事件_中间 = "中间事件"
事件_完成 = "完成事件"
事件_失败 = "失败事件"
事件_取消 = "取消事件"


@dataclass
class 流事件:
    """一条流式事件。"""

    事件类型: str
    数据: Any = None
    序号: int = 0
    时间: str = ""

    def 转字典(self) -> dict[str, Any]:
        return {"事件类型": self.事件类型, "数据": self.数据, "序号": self.序号}


@dataclass
class 流式调用:
    """一次流式调用（事件队列 + 状态）。"""

    调用id: str = ""
    能力id: str = ""
    状态: str = "进行中"  # 进行中/已完成/已失败/已取消/已断开
    事件列表: list[流事件] = field(default_factory=list)
    序号: int = 0
    断开: bool = False
    错误码: str = ""
    错误说明: str = ""
    _条件: threading.Condition = field(
        default_factory=lambda: threading.Condition(threading.RLock()), repr=False
    )

    def 追加事件(self, 事件类型: str, 数据: Any = None) -> 流事件:
        with self._条件:
            if self.状态 != "进行中" and 事件类型 not in (事件_完成, 事件_失败, 事件_取消):
                return 流事件(事件类型=事件类型, 数据=数据, 序号=-1)
            事件 = 流事件(事件类型=事件类型, 数据=数据, 序号=self.序号,
                        时间=time.strftime("%H:%M:%S"))
            self.序号 += 1
            self.事件列表.append(事件)
            self._条件.notify_all()
            return 事件

    def 完成(self, 数据: Any = None) -> None:
        with self._条件:
            if self.状态 != "进行中":
                return
            self.状态 = "已完成"
            self.追加事件(事件_完成, 数据)

    def 失败(self, 错误码: str, 错误说明: str) -> None:
        with self._条件:
            if self.状态 != "进行中":
                return
            self.错误码 = 错误码
            self.错误说明 = 错误说明
            self.状态 = "已失败"
            self.追加事件(事件_失败, {"错误码": 错误码, "错误说明": 错误说明})

    def 取消(self) -> None:
        with self._条件:
            if self.状态 != "进行中":
                return
            self.状态 = "已取消"
            self.追加事件(事件_取消)

    def 断开清理(self) -> None:
        """客户端断开：释放任务和资源，不得继续无限执行。"""
        with self._条件:
            if self.状态 == "已断开":
                return
            self.断开 = True
            self.状态 = "已断开"
            self.事件列表.clear()
            self._条件.notify_all()

    def 等待新事件(self, 已读序号: int, 超时秒: float = 0.25) -> list[流事件]:
        """等待并返回尚未消费的事件，不等待整条流完成。"""
        with self._条件:
            if len(self.事件列表) <= 已读序号 and self.状态 == "进行中":
                self._条件.wait(timeout=max(0.0, 超时秒))
            return list(self.事件列表[已读序号:])

    def 全部事件(self) -> list[dict]:
        return [事件.转字典() for 事件 in self.事件列表]


class 流式管理器:
    """流式调用管理：创建、执行生成器、取消、断开清理。"""

    def __init__(self) -> None:
        self.调用表: dict[str, 流式调用] = {}

    def 开始(self, 能力id: str, 事件生成函数: Callable, *, 最大事件数: int = 10000) -> 流式调用:
        """开始一次流式调用（生成函数逐事件产出）。

        最大事件数保护：防止无限生成器卡死消费端；超限自动断开。
        """
        调用 = 流式调用(调用id=uuid.uuid4().hex[:16], 能力id=能力id)
        self.调用表[调用.调用id] = 调用
        try:
            生成器 = 事件生成函数()
            调用.追加事件(事件_首个, {"能力id": 能力id, "调用id": 调用.调用id})
            for 数据 in 生成器:
                if 调用.断开:
                    调用.取消()
                    return 调用
                if 调用.序号 >= 最大事件数:
                    调用.失败("超时", f"事件数超过上限 {最大事件数}，已断开")
                    return 调用
                调用.追加事件(事件_中间, 数据)
            if 调用.状态 == "进行中":
                调用.完成()
        except Exception as 错误:
            调用.失败("内部错误", str(错误))
        return 调用

    def 查询(self, 调用id: str) -> 流式调用 | None:
        return self.调用表.get(调用id)

    def 取消(self, 调用id: str) -> bool:
        调用 = self.调用表.get(调用id)
        if 调用 is None or 调用.状态 not in ("进行中",):
            return False
        调用.取消()
        return True

    def 断开(self, 调用id: str) -> None:
        调用 = self.调用表.get(调用id)
        if 调用 is not None:
            调用.断开清理()
            self.调用表.pop(调用id, None)  # 释放引用
