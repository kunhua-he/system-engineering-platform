"""持久化灰度指标：JSONL 落盘、进程重启恢复、阈值自动回滚。

持久化：能力id/版本/请求总数/成功数/失败数/超时数/平均耗时/最大耗时/
当前灰度比例/观察窗口/触发回滚原因。
指标写入失败不能破坏主调用；指标文件损坏必须可检测。
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

阈值_失败率上限 = 0.05
阈值_超时率上限 = 0.10


@dataclass
class 灰度指标:
    """灰度观察指标（聚合视图）。"""

    能力id: str = ""
    版本: str = ""
    请求总数: int = 0
    成功数: int = 0
    失败数: int = 0
    超时数: int = 0
    平均耗时毫秒: float = 0.0
    最大耗时毫秒: float = 0.0
    当前灰度比例: float = 1.0
    观察窗口秒: int = 300
    触发回滚原因: str = ""

    def 失败率(self) -> float:
        return self.失败数 / self.请求总数 if self.请求总数 else 0.0

    def 超时率(self) -> float:
        return self.超时数 / self.请求总数 if self.请求总数 else 0.0

    def 转字典(self) -> dict[str, Any]:
        return {
            "能力id": self.能力id, "版本": self.版本, "请求总数": self.请求总数,
            "成功数": self.成功数, "失败数": self.失败数, "超时数": self.超时数,
            "平均耗时毫秒": round(self.平均耗时毫秒, 2), "最大耗时毫秒": self.最大耗时毫秒,
            "当前灰度比例": self.当前灰度比例, "观察窗口秒": self.观察窗口秒,
            "触发回滚原因": self.触发回滚原因, "失败率": round(self.失败率(), 4),
            "超时率": round(self.超时率(), 4),
        }


class 灰度指标库:
    """灰度指标持久化：每次观测一行 JSONL；聚合时重算。"""

    def __init__(self, 存储目录: Path | None = None) -> None:
        self.存储目录 = 存储目录 or Path(灰度指标库.默认存储目录())
        self.存储目录.mkdir(parents=True, exist_ok=True)
        self.指标文件 = self.存储目录 / "灰度指标.jsonl"
        self.状态文件 = self.存储目录 / "灰度状态.json"
        self.写入失败计数 = 0
        self.状态表: dict[str, dict[str, Any]] = {}
        self.恢复()

    @staticmethod
    def 默认存储目录() -> str:
        import os, tempfile
        return os.environ.get("系统库灰度目录", str(Path(tempfile.gettempdir()) / "系统级支持库_灰度"))

    def 恢复(self) -> None:
        """进程重启后恢复已有状态（文件损坏必须可检测）。"""
        if self.状态文件.is_file():
            try:
                self.状态表 = json.loads(self.状态文件.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                self.状态表 = {"损坏警告": "灰度状态.json 损坏，已重置"}
                self.保存状态()

    def 保存状态(self) -> None:
        try:
            self.状态文件.write_text(json.dumps(self.状态表, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError:
            self.写入失败计数 += 1  # 不破坏主调用

    def 设置灰度比例(self, 能力id: str, 版本: str, 比例: float) -> None:
        键 = f"{能力id}@{版本}"
        self.状态表.setdefault(键, {})["当前灰度比例"] = 比例
        self.状态表[键]["观察窗口秒"] = 300
        self.保存状态()

    def 观测(self, *, 能力id: str, 版本: str, 成功: bool, 耗时毫秒: float = 0.0,
             超时: bool = False) -> list[str]:
        """记录一次观测；返回超阈值问题列表（空=正常）。"""
        键 = f"{能力id}@{版本}"
        行 = {
            "时间": time.strftime("%Y-%m-%d %H:%M:%S"), "能力id": 能力id,
            "版本": 版本, "成功": 成功, "耗时毫秒": round(耗时毫秒, 2), "超时": 超时,
        }
        try:
            with self.指标文件.open("a", encoding="utf-8") as 文件:
                文件.write(json.dumps(行, ensure_ascii=False) + "\n")
        except OSError:
            self.写入失败计数 += 1
            return []
        指标 = self.聚合(能力id=能力id, 版本=版本)
        if 键 in self.状态表:
            指标.当前灰度比例 = self.状态表[键].get("当前灰度比例", 1.0)
        return self.超阈值问题(指标)

    def 聚合(self, *, 能力id: str = "", 版本: str = "") -> 灰度指标:
        """聚合指定能力@版本的指标（重算，不依赖内存）。"""
        指标 = 灰度指标(能力id=能力id, 版本=版本)
        if not self.指标文件.is_file():
            return 指标
        for 行 in self.指标文件.read_text(encoding="utf-8").splitlines():
            try:
                条目 = json.loads(行)
            except json.JSONDecodeError:
                continue
            if 能力id and 条目.get("能力id") != 能力id:
                continue
            if 版本 and 条目.get("版本") != 版本:
                continue
            指标.请求总数 += 1
            if 条目.get("成功"):
                指标.成功数 += 1
                耗时 = float(条目.get("耗时毫秒", 0))
                指标.平均耗时毫秒 = (指标.平均耗时毫秒 * (指标.成功数 - 1) + 耗时) / 指标.成功数
                指标.最大耗时毫秒 = max(指标.最大耗时毫秒, 耗时)
            else:
                指标.失败数 += 1
            if 条目.get("超时"):
                指标.超时数 += 1
        return 指标

    def 超阈值问题(self, 指标: 灰度指标) -> list[str]:
        问题列表 = []
        if 指标.请求总数 >= 5:  # 样本量门槛
            if 指标.失败率() > 阈值_失败率上限:
                问题列表.append(f"失败率 {指标.失败率():.2%} 超过上限 {阈值_失败率上限:.0%}")
            if 指标.超时率() > 阈值_超时率上限:
                问题列表.append(f"超时率 {指标.超时率():.2%} 超过上限 {阈值_超时率上限:.0%}")
        return 问题列表

    def 全部指标(self) -> list[灰度指标]:
        键集合 = set()
        if self.指标文件.is_file():
            for 行 in self.指标文件.read_text(encoding="utf-8").splitlines():
                try:
                    条目 = json.loads(行)
                    键集合.add((条目.get("能力id", ""), 条目.get("版本", "")))
                except json.JSONDecodeError:
                    continue
        return [self.聚合(能力id=能力id, 版本=版本) for 能力id, 版本 in sorted(键集合)]

    def 触发回滚(self, 能力id: str, 版本: str, 原因: str) -> None:
        键 = f"{能力id}@{版本}"
        self.状态表.setdefault(键, {})["触发回滚原因"] = 原因
        self.保存状态()
