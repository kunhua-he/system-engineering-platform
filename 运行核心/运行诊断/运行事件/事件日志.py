"""事件日志：JSONL 结构化日志写入与查询（有界：轮转 + 尾部分片读）。

要求：日志支持 JSONL；失败信息不可丢失；密码/令牌/私钥脱敏；大文本
只保存摘要；日志写入失败不能破坏主调用，但必须产生降级告警。

有界承诺（与实现一致）：写入走 `公共契约.运行时.有界IO.追加JSONL`
（达上限轮转有限份分片），查询走 `有界IO.读取JSONL` 尾部分片倒读，
内存与耗时不再随日志总量线性增长。
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
from pathlib import Path
from typing import Any

from 公共契约.运行时.有界IO import (
    默认JSONL读取上限字节, 默认JSONL读取上限记录, 默认JSONL文件上限字节,
    追加JSONL, 读取JSONL,
)
from 运行核心.运行诊断.运行事件.脱敏工具 import 脱敏事件字典
from 公共契约.基础类型.逻辑类型 import 真, 假


class 事件日志:
    """JSONL 事件日志：有界写入（轮转）、尾部分片读、降级告警。"""

    def __init__(
        self,
        日志目录: Path | None = None,
        *,
        最大文件字节数: int = 默认JSONL文件上限字节,
        轮转数量: int = 2,
    ) -> None:
        默认目录 = Path(tempfile.gettempdir()) / "系统级支持库_日志"
        self.日志目录 = 日志目录 or Path(os.environ.get("系统库日志目录", str(默认目录)))
        self.日志目录.mkdir(parents=True, exist_ok=True)
        self.降级告警数 = 0
        self.当前文件 = self.日志目录 / "运行事件.jsonl"
        # 有界写入上界：单文件字节上限与保留的轮转分片数（分片总数 = 轮转数量）。
        self.最大文件字节数 = max(1024, int(最大文件字节数))
        self.轮转数量 = max(1, int(轮转数量))
        self.锁 = threading.Lock()

    def 写入(self, 事件: Any) -> bool:
        """写入一条事件；失败产生降级告警但不抛出（不破坏主调用）。

        有界：改由 `有界IO.追加JSONL` 落盘，文件达 `最大文件字节数`
        时轮转，最多保留 `轮转数量` 份分片。
        """
        try:
            字典 = 脱敏事件字典(事件.转字典())
            with self.锁:
                追加JSONL(
                    self.当前文件, 字典,
                    最大文件字节数=self.最大文件字节数,
                    轮转数量=self.轮转数量,
                    强制落盘=假,
                )
            return 真
        except OSError:
            self.降级告警数 += 1
            return 假

    def 分片路径表(self) -> list[Path]:
        """从新到旧返回日志分片：当前文件、`.1`、`.2` …（供有界分片读）。"""
        分片表 = [self.当前文件]
        for 序号 in range(1, self.轮转数量 + 1):
            候选 = self.当前文件.with_name(f"{self.当前文件.name}.{序号}")
            if not 候选.is_file():
                break
            分片表.append(候选)
        return 分片表

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
        最大扫描记录数: int = 默认JSONL读取上限记录,
    ) -> list[dict[str, Any]]:
        """按条件查询事件（按时间倒序取最近 N 条；尾部分片有界读）。

        从最新分片起有界倒读，命中数达到 `最近条数` 即停止，只多读
        `最大扫描记录数` 量级；不再整文件 `read_text` 进内存。
        """
        需要 = max(1, int(最近条数))
        扫描上限 = max(需要, int(最大扫描记录数))
        命中: list[dict[str, Any]] = []
        for 分片 in self.分片路径表():  # 从新到旧
            记录列表, _ = 读取JSONL(
                分片,
                最大字节数=默认JSONL读取上限字节,
                最大记录数=扫描上限,
            )
            本片命中: list[dict[str, Any]] = []
            for 条目 in 记录列表:
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
                本片命中.append(条目)
            命中 = 本片命中 + 命中  # 更旧的分片排在前面，维持时间升序
            if len(命中) >= 需要:
                break
        return 命中[-需要:]

    def 聚合错误码(self, *, 最近条数: int = 500) -> dict[str, int]:
        """按错误码聚合失败事件数量。"""
        统计表: dict[str, int] = {}
        for 条目 in self.查询(成功=假, 最近条数=最近条数):
            错误码 = 条目.get("错误码") or "未知"
            统计表[错误码] = 统计表.get(错误码, 0) + 1
        return dict(sorted(统计表.items(), key=lambda 项: -项[1]))

    def 最近失败(self, 条数: int = 10) -> list[dict[str, Any]]:
        return self.查询(成功=假, 最近条数=条数)

    def 清空(self) -> None:
        """清空日志及其轮转分片（仅测试/管理用）。"""
        with self.锁:
            for 分片 in self.分片路径表():
                try:
                    分片.unlink(missing_ok=True)
                except OSError:
                    pass
