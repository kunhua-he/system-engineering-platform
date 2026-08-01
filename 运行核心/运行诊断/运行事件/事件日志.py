"""事件日志：JSONL 结构化日志写入与查询。

要求：日志支持 JSONL；失败信息不可丢失；密码/令牌/私钥脱敏；大文本
只保存摘要；日志写入失败不能破坏主调用，但必须产生降级告警。
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from 运行核心.运行诊断.运行事件.脱敏工具 import 脱敏事件字典


class 事件日志:
    """JSONL 事件日志：写入、查询、降级告警。"""

    def __init__(self, 日志目录: Path | None = None) -> None:
        默认目录 = Path(tempfile.gettempdir()) / "系统级支持库_日志"
        self.日志目录 = 日志目录 or Path(os.environ.get("系统库日志目录", str(默认目录)))
        self.日志目录.mkdir(parents=True, exist_ok=True)
        self.降级告警数 = 0
        self.当前文件 = self.日志目录 / "运行事件.jsonl"

    def 写入(self, 事件: Any) -> bool:
        """写入一条事件；失败产生降级告警但不抛出（不破坏主调用）。"""
        try:
            字典 = 脱敏事件字典(事件.转字典())
            with self.当前文件.open("a", encoding="utf-8") as 文件:
                文件.write(json.dumps(字典, ensure_ascii=False) + "\n")
            return True
        except OSError as 错误:
            self.降级告警数 += 1
            return False

    def 查询(
        self,
        *,
        事件类型: str = "",
        包id: str = "",
        能力id: str = "",
        成功: bool | None = None,
        错误码: str = "",
        追踪id: str = "",
        最近条数: int = 100,
    ) -> list[dict[str, Any]]:
        """按条件查询事件（按时间倒序取最近 N 条）。"""
        结果列表: list[dict[str, Any]] = []
        if not self.当前文件.is_file():
            return 结果列表
        for 行 in self.当前文件.read_text(encoding="utf-8").splitlines():
            try:
                条目 = json.loads(行)
            except json.JSONDecodeError:
                continue
            if 事件类型 and 条目.get("事件类型") != 事件类型:
                continue
            if 包id and 条目.get("包id") != 包id:
                continue
            if 能力id and 条目.get("能力id") != 能力id:
                continue
            if 成功 is not None and 条目.get("成功") is not 成功:
                continue
            if 错误码 and 条目.get("错误码") != 错误码:
                continue
            if 追踪id and 条目.get("追踪id") != 追踪id:
                continue
            结果列表.append(条目)
        return 结果列表[-最近条数:]

    def 聚合错误码(self, *, 最近条数: int = 500) -> dict[str, int]:
        """按错误码聚合失败事件数量。"""
        统计表: dict[str, int] = {}
        for 条目 in self.查询(成功=False, 最近条数=最近条数):
            错误码 = 条目.get("错误码") or "未知"
            统计表[错误码] = 统计表.get(错误码, 0) + 1
        return dict(sorted(统计表.items(), key=lambda 项: -项[1]))

    def 最近失败(self, 条数: int = 10) -> list[dict[str, Any]]:
        return self.查询(成功=False, 最近条数=条数)

    def 清空(self) -> None:
        """清空日志（仅测试/管理用）。"""
        try:
            self.当前文件.unlink(missing_ok=True)
        except OSError:
            pass
