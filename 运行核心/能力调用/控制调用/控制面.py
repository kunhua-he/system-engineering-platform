"""控制面与调用面：分离安装/版本/配置/诊断/升级/回滚/发布 与 调用能力。

控制面故障不得拖垮已激活能力；调用面高负载不得阻止诊断和回滚。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

控制面操作表 = ("安装", "版本", "配置", "诊断", "升级", "回滚", "发布")
调用面操作表 = ("网关", "能力调用", "任务", "流式", "事件", "结果")


@dataclass
class 面状态:
    """控制面/调用面运行状态。"""

    名称: str
    健康: bool = True
    故障说明: str = ""
    操作计数: dict[str, int] = field(default_factory=dict)

    def 转字典(self) -> dict[str, Any]:
        return {"名称": self.名称, "健康": self.健康, "故障说明": self.故障说明,
                "操作计数": self.操作计数}


class 面分离器:
    """控制面/调用面分离：隔离故障与负载。"""

    def __init__(self) -> None:
        self.控制面 = 面状态("控制面")
        self.调用面 = 面状态("调用面")

    def 记录控制操作(self, 操作: str, 成功: bool = True) -> None:
        if 操作 not in 控制面操作表:
            raise ValueError(f"未知控制面操作: {操作}")
        self.控制面.操作计数[操作] = self.控制面.操作计数.get(操作, 0) + 1
        if not 成功:
            self.控制面.故障说明 = f"{操作} 失败（时间 {time.strftime('%H:%M:%S')}）"

    def 记录调用操作(self, 操作: str, 成功: bool = True) -> None:
        if 操作 not in 调用面操作表:
            raise ValueError(f"未知调用面操作: {操作}")
        self.调用面.操作计数[操作] = self.调用面.操作计数.get(操作, 0) + 1
        if not 成功:
            self.调用面.故障说明 = f"{操作} 失败"

    def 控制面故障(self, 说明: str) -> None:
        """控制面故障：不影响已激活能力（调用面保持健康）。"""
        self.控制面.健康 = False
        self.控制面.故障说明 = 说明

    def 调用面高负载(self) -> None:
        """调用面高负载：不阻止诊断和回滚（控制面保持健康）。"""
        self.调用面.健康 = True  # 高负载不等于故障
        self.调用面.故障说明 = "调用面高负载（控制面仍可诊断/回滚）"

    def 状态快照(self) -> dict[str, Any]:
        return {"控制面": self.控制面.转字典(), "调用面": self.调用面.转字典()}

    def 控制面可用(self) -> bool:
        return self.控制面.健康

    def 调用面可用(self) -> bool:
        return self.调用面.健康
