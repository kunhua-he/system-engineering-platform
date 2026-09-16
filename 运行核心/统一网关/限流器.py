"""项目、用户、能力、任务、提供者五维限流与并发治理。"""

from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Any

错误码_限流 = "限流"

# 有界治理：空闲状态清理的调用间隔（每 N 次状态访问清一次，避免热路径开销）
清理间隔 = 256


@dataclass
class 限流状态:
    """一个维度键的频率与并发状态。"""

    维度: str
    键: str
    当前并发: int = 0
    窗口开始: float = 0.0
    窗口计数: int = 0
    拒绝数: int = 0
    上限: int = 0
    最后访问: float = 0.0

    def 转字典(self) -> dict[str, Any]:
        return {
            "维度": self.维度,
            "键": self.键,
            "当前并发": self.当前并发,
            "窗口计数": self.窗口计数,
            "拒绝数": self.拒绝数,
            "上限": self.上限,
        }


class 限流器:
    """所有检查在同一把锁内完成；任一维度失败时不占用其他维度。"""

    def __init__(
        self,
        *,
        最大并发请求: int = 50,
        最大任务数: int = 20,
        最大流式连接: int = 10,
        单项目频率: int = 500,
        单用户频率: int = 100,
        单能力频率: int = 200,
        单任务频率: int = 100,
        单提供者频率: int = 300,
        # 2026-09-16 华哥裁决：本地私有部署下按「相对安全」放宽。
        # 原 20 会让两个批量转码任务（16+4）正好占满、互相饿死；
        # 实测此时 CPU 仅 36%、磁盘 195MB/s，本机资源远未饱和。
        单维度并发: int = 40,
        窗口秒: float = 10.0,
        拒绝记录上限: int = 10000,
        状态空闲秒: float = 600.0,
    ) -> None:
        if min(最大并发请求, 最大任务数, 最大流式连接, 单维度并发) < 1:
            raise ValueError("并发上限必须大于零")
        if min(单项目频率, 单用户频率, 单能力频率, 单任务频率, 单提供者频率) < 1:
            raise ValueError("频率上限必须大于零")
        if 窗口秒 <= 0:
            raise ValueError("限流窗口必须大于零")
        if 拒绝记录上限 < 1:
            raise ValueError("拒绝记录上限必须大于零")
        if 状态空闲秒 <= 0:
            raise ValueError("状态空闲秒必须大于零")
        self.最大并发请求 = 最大并发请求
        self.最大任务数 = 最大任务数
        self.最大流式连接 = 最大流式连接
        self.单维度并发 = 单维度并发
        self.窗口秒 = 窗口秒
        self.频率上限表 = {
            "项目": 单项目频率,
            "用户": 单用户频率,
            "能力": 单能力频率,
            "任务": 单任务频率,
            "提供者": 单提供者频率,
        }
        self.拒绝记录上限 = 拒绝记录上限
        self.状态空闲秒 = 状态空闲秒
        self.锁 = threading.RLock()
        self.请求并发 = 0
        self.任务数 = 0
        self.流式连接数 = 0
        self.状态表: dict[tuple[str, str], 限流状态] = {}
        # 有界：拒绝记录只保留最近 N 条（deque maxlen），累计值另计，语义不丢
        self.拒绝记录: deque[dict[str, Any]] = deque(maxlen=拒绝记录上限)
        self.累计拒绝数 = 0
        self._清理计数 = 0

    def _维度表(
        self,
        *,
        项目id: str = "",
        用户id: str = "",
        能力id: str = "",
        任务id: str = "",
        提供者: str = "",
    ) -> list[tuple[str, str]]:
        return [(维度, 键) for 维度, 键 in (
            ("项目", 项目id), ("用户", 用户id), ("能力", 能力id),
            ("任务", 任务id), ("提供者", 提供者),
        ) if 键]

    def _状态(self, 维度: str, 键: str, 现在: float) -> 限流状态:
        标识 = (维度, 键)
        状态 = self.状态表.get(标识)
        if 状态 is None:
            状态 = 限流状态(维度=维度, 键=键, 窗口开始=现在, 上限=self.频率上限表[维度])
            self.状态表[标识] = 状态
        elif 现在 - 状态.窗口开始 >= self.窗口秒:
            状态.窗口开始 = 现在
            状态.窗口计数 = 0
        状态.最后访问 = 现在
        self._清理计数 += 1
        if self._清理计数 >= 清理间隔:
            self._清理计数 = 0
            self._清理空闲状态(现在)
        return 状态

    def _清理空闲状态(self, 现在: float) -> int:
        """有界：删除空闲超过 状态空闲秒 且当前无并发的维度状态（调用方必须已持锁）。

        只删"空闲且并发为 0"的条目，窗口（窗口秒）远小于空闲秒，不会放过频率限制。
        """
        过期 = [标识 for 标识, 状态 in self.状态表.items()
                if 状态.当前并发 <= 0 and 现在 - 状态.最后访问 > self.状态空闲秒]
        for 标识 in 过期:
            del self.状态表[标识]
        return len(过期)

    def _记录拒绝(self, 原因: str, 维度: str = "全局", 键: str = "") -> None:
        self.累计拒绝数 += 1
        self.拒绝记录.append({
            "时间": time.strftime("%Y-%m-%d %H:%M:%S"),
            "维度": 维度,
            "键": 键,
            "原因": 原因,
        })

    def 进入请求(
        self,
        *,
        项目id: str = "",
        用户id: str = "",
        能力id: str = "",
        任务id: str = "",
        提供者: str = "",
    ) -> tuple[bool, str]:
        维度表 = self._维度表(
            项目id=项目id, 用户id=用户id, 能力id=能力id,
            任务id=任务id, 提供者=提供者,
        )
        with self.锁:
            if self.请求并发 >= self.最大并发请求:
                原因 = f"并发请求数超过上限 {self.最大并发请求}"
                self._记录拒绝(原因)
                return False, f"{错误码_限流}: {原因}"
            现在 = time.monotonic()
            状态列表 = [self._状态(维度, 键, 现在) for 维度, 键 in 维度表]
            for 状态 in 状态列表:
                if 状态.当前并发 >= self.单维度并发:
                    状态.拒绝数 += 1
                    原因 = f"{状态.维度}并发超过上限"
                    self._记录拒绝(原因, 状态.维度, 状态.键)
                    return False, f"{错误码_限流}: {原因}"
                if 状态.窗口计数 >= 状态.上限:
                    状态.拒绝数 += 1
                    原因 = f"{状态.维度}调用频率超过上限"
                    self._记录拒绝(原因, 状态.维度, 状态.键)
                    return False, f"{错误码_限流}: {原因}"
            self.请求并发 += 1
            for 状态 in 状态列表:
                状态.当前并发 += 1
                状态.窗口计数 += 1
            return True, ""

    def 离开请求(
        self,
        *,
        项目id: str = "",
        用户id: str = "",
        能力id: str = "",
        任务id: str = "",
        提供者: str = "",
    ) -> None:
        with self.锁:
            self.请求并发 = max(0, self.请求并发 - 1)
            现在 = time.monotonic()
            for 维度, 键 in self._维度表(
                项目id=项目id, 用户id=用户id, 能力id=能力id,
                任务id=任务id, 提供者=提供者,
            ):
                状态 = self._状态(维度, 键, 现在)
                状态.当前并发 = max(0, 状态.当前并发 - 1)

    def 进入任务(self, *, 项目id: str = "", 用户id: str = "", 能力id: str = "",
                 任务id: str = "", 提供者: str = "") -> tuple[bool, str]:
        with self.锁:
            if self.任务数 >= self.最大任务数:
                原因 = f"任务数超过上限 {self.最大任务数}"
                self._记录拒绝(原因, "任务", 任务id)
                return False, f"{错误码_限流}: {原因}"
            self.任务数 += 1
            return True, ""

    def 离开任务(self) -> None:
        with self.锁:
            self.任务数 = max(0, self.任务数 - 1)

    def 进入流式(self, *, 项目id: str = "", 用户id: str = "", 能力id: str = "",
                 提供者: str = "") -> tuple[bool, str]:
        with self.锁:
            if self.流式连接数 >= self.最大流式连接:
                原因 = f"流式连接数超过上限 {self.最大流式连接}"
                self._记录拒绝(原因, "能力", 能力id)
                return False, f"{错误码_限流}: {原因}"
            self.流式连接数 += 1
            return True, ""

    def 离开流式(self) -> None:
        with self.锁:
            self.流式连接数 = max(0, self.流式连接数 - 1)

    def 状态快照(self) -> dict[str, Any]:
        with self.锁:
            return {
                "请求并发": self.请求并发,
                "任务数": self.任务数,
                "流式连接数": self.流式连接数,
                "拒绝总数": self.累计拒绝数,
                "拒绝记录保留": len(self.拒绝记录),
                "窗口秒": self.窗口秒,
                "五维状态": [状态.转字典() for 状态 in self.状态表.values()],
            }

    def 查询拒绝记录(self) -> list[dict[str, Any]]:
        with self.锁:
            return [dict(记录) for 记录 in self.拒绝记录]
