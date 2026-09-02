"""多步骤验证场景和场景束。"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

from 开发工具.HTML验证.单步场景 import 验证步骤


@dataclass
class 多步骤验证场景:
    场景id: str
    包目录: Path
    前置步骤: list[验证步骤] = field(default_factory=list)
    目标步骤: list[验证步骤] = field(default_factory=list)
    清理步骤: list[验证步骤] = field(default_factory=list)

    @property
    def 步骤总数(self) -> int:
        return len(self.前置步骤) + len(self.目标步骤) + len(self.清理步骤)

    def 转字典(self, 制品目录: Path | None = None) -> dict[str, Any]:
        数据 = {
            "场景id": self.场景id,
            "前置步骤": [步骤.转字典() for 步骤 in self.前置步骤],
            "目标步骤": [步骤.转字典() for 步骤 in self.目标步骤],
            "清理步骤": [步骤.转字典() for 步骤 in self.清理步骤],
        }
        if 制品目录 is not None:
            数据["包相对目录"] = self.包目录.resolve().relative_to(制品目录.resolve()).as_posix()
        return 数据


@dataclass
class 验证场景束:
    场景列表: list[多步骤验证场景]
    目标能力全集: set[str]
    制品摘要: str

    @property
    def 步骤总数(self) -> int:
        return sum(场景.步骤总数 for 场景 in self.场景列表)

    def __len__(self) -> int:
        return sum(len(场景.目标步骤) for 场景 in self.场景列表)

    def __iter__(self) -> Iterator[验证步骤]:
        for 场景 in self.场景列表:
            yield from 场景.目标步骤

    def __getitem__(self, 索引: int) -> 验证步骤:
        return list(iter(self))[索引]
