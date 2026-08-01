"""租约管理：心跳续租、空闲超时、硬截止时间与自动回收。

停止心跳后自动回收；进程崩溃后租约/锁/临时目录/资源全部释放（由
回收器扫描超时租约并清理）。
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from 运行核心.句柄体系 import 句柄体系, 失效原因_超时


@dataclass
class 租约:
    """一份资源租约。"""

    租约id: str = ""
    资源id: str = ""
    项目id: str = ""
    所有者: str = ""
    句柄id: str = ""
    空闲超时秒: float = 10.0
    硬截止时间: float = 0.0
    最后心跳: float = 0.0
    已回收: bool = False

    def 转字典(self) -> dict[str, Any]:
        return {
            "租约id": self.租约id, "资源id": self.资源id, "项目id": self.项目id,
            "所有者": self.所有者, "句柄id": self.句柄id,
            "空闲超时秒": self.空闲超时秒, "硬截止时间": self.硬截止时间,
            "最后心跳": self.最后心跳, "已回收": self.已回收,
        }


class 租约管理器:
    """租约管理器：创建/心跳续租/过期回收。"""

    def __init__(self, 句柄体系: 句柄体系 | None = None) -> None:
        from 运行核心.句柄体系 import 句柄体系 as _句柄体系
        self.句柄体系 = 句柄体系 or _句柄体系()
        self.租约表: dict[str, 租约] = {}

    def 创建租约(self, *, 资源id: str, 项目id: str = "", 所有者: str = "",
                空闲超时秒: float = 10.0, 硬截止秒: float = 60.0,
                句柄id: str = "") -> 租约:
        """创建租约并绑定句柄；租约默认活跃（心跳即刻）。"""
        租约对象 = 租约(
            租约id=uuid.uuid4().hex[:16], 资源id=资源id, 项目id=项目id,
            所有者=所有者, 句柄id=句柄id, 空闲超时秒=空闲超时秒,
            硬截止时间=time.monotonic() + 硬截止秒,
            最后心跳=time.monotonic(),
        )
        self.租约表[租约对象.租约id] = 租约对象
        return 租约对象

    def 心跳(self, 租约id: str) -> tuple[bool, str]:
        """心跳续租：重置最后心跳；停止心跳后自动回收。"""
        租约对象 = self.租约表.get(租约id)
        if 租约对象 is None:
            return False, f"租约不存在: {租约id}"
        if 租约对象.已回收:
            return False, "租约已回收，不能复活"
        if time.monotonic() > 租约对象.硬截止时间:
            self.回收(租约id, 原因="硬截止时间到达")
            return False, "租约硬截止时间到达，已回收"
        租约对象.最后心跳 = time.monotonic()
        return True, "心跳续租成功"

    def 回收(self, 租约id: str, 原因: str = "") -> tuple[bool, str]:
        """回收租约：绑定句柄一并失效；幂等。"""
        租约对象 = self.租约表.get(租约id)
        if 租约对象 is None:
            return False, f"租约不存在: {租约id}"
        if 租约对象.已回收:
            return True, "租约已回收（幂等）"
        租约对象.已回收 = True
        if 租约对象.句柄id:
            self.句柄体系.失效(租约对象.句柄id, 原因 or 失效原因_超时)
        return True, f"租约已回收（{原因 or '主动回收'}）"

    def 扫描过期(self, 现在时间: float | None = None) -> list[str]:
        """扫描空闲超时/硬截止过期的租约并自动回收。"""
        现在时间 = 现在时间 or time.monotonic()
        回收列表 = []
        for 租约id, 租约对象 in list(self.租约表.items()):
            if 租约对象.已回收:
                continue
            空闲超时 = (现在时间 - 租约对象.最后心跳) > 租约对象.空闲超时秒
            硬截止 = 现在时间 > 租约对象.硬截止时间
            if 空闲超时 or 硬截止:
                self.回收(租约id, 原因="空闲超时" if 空闲超时 else "硬截止时间到达")
                回收列表.append(租约id)
        return 回收列表

    def 清理全部(self) -> None:
        """进程崩溃后清理：全部租约回收（句柄失效 + 资源释放由调用方）。"""
        for 租约id in list(self.租约表.keys()):
            self.回收(租约id, 原因="进程崩溃清理")
        self.租约表.clear()

    def 查询(self, 租约id: str) -> 租约 | None:
        return self.租约表.get(租约id)

    def 活跃租约数(self) -> int:
        return sum(1 for 租约对象 in self.租约表.values() if not 租约对象.已回收)
