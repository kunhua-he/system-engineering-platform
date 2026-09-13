"""安全审计：统一审计记录（JSONL 持久化）。

至少记录：谁调用/调用了什么/调用哪个版本/什么时候调用/是否成功/
为什么失败/是否被限流/是否触发权限拒绝/是否触发回滚/是否访问敏感配置。
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from 公共契约.运行时.有界IO import (
    默认JSONL文件上限字节, 默认JSONL读取上限字节, 默认JSONL读取上限记录,
    追加JSONL, 读取JSONL,
)
from 运行核心.运行诊断.运行事件.脱敏工具 import 脱敏值


class 安全审计:
    """安全审计：追加式 JSONL 审计日志。"""

    def __init__(self, 存储目录: Path | None = None) -> None:
        self.存储目录 = 存储目录 or Path(安全审计.默认存储目录())
        self.存储目录.mkdir(parents=True, exist_ok=True)
        self.审计文件 = self.存储目录 / "安全审计.jsonl"
        self.锁 = threading.Lock()

    @staticmethod
    def 默认存储目录() -> str:
        import os, tempfile
        return os.environ.get("系统库审计目录", str(Path(tempfile.gettempdir()) / "系统级支持库_审计"))

    def 记录(self, *, 操作: str, 用户id: str = "", 项目id: str = "",
             能力id: str = "", 版本: str = "", 请求id: str = "",
             成功: bool = True, 失败原因: str = "", 被限流: bool = False,
             权限拒绝: bool = False, 触发回滚: bool = False,
             访问敏感配置: bool = False, 来源地址: str = "",
             模块id: str = "", 任务id: str = "", 会话id: str = "",
             契约版本: str = "", 提供者: str = "", 错误码: str = "",
             权限范围: list[str] | None = None, 耗时毫秒: float = 0.0,
             操作id: str = "") -> str:
        """写一条审计记录；返回审计id。"""
        审计id = uuid.uuid4().hex[:16]
        记录 = {
            "审计id": 审计id,
            "时间": time.strftime("%Y-%m-%d %H:%M:%S"),
            "操作": 操作, "用户id": 用户id, "项目id": 项目id,
            "模块id": 模块id, "能力id": 能力id, "版本": 版本,
            "契约版本": 契约版本, "提供者": 提供者,
            "请求id": 请求id, "任务id": 任务id, "会话id": 会话id,
            "操作id": 操作id, "来源地址": 来源地址,
            "权限范围": list(权限范围 or []), "耗时毫秒": round(耗时毫秒, 2),
            "成功": 成功, "错误码": 错误码, "失败原因": 失败原因,
            "被限流": 被限流, "权限拒绝": 权限拒绝,
            "触发回滚": 触发回滚, "访问敏感配置": 访问敏感配置,
        }
        记录 = 脱敏值(记录)
        try:
            with self.锁:
                追加JSONL(
                    self.审计文件, 记录,
                    最大文件字节数=默认JSONL文件上限字节,
                    强制落盘=True,
                )
        except OSError as 错误:
            # 审计落盘失败必须留痕：调用方（统一网关）丢弃返回值，
            # 静默返回 "" 会让安全审计链路无声断掉，事后无从发现。
            # 返回值语义不变，仍以空审计id 表示失败。
            print(f"[安全审计] 审计记录落盘失败: {错误}", file=sys.stderr)
            return ""
        return 审计id

    def 查询(self, *, 用户id: str = "", 能力id: str = "", 操作: str = "",
             成功: bool | None = None, 限流: bool | None = None,
             权限拒绝: bool | None = None, 回滚: bool | None = None,
             敏感配置: bool | None = None, 项目id: str = "",
             请求id: str = "", 任务id: str = "", 错误码: str = "",
             最大记录数: int = 默认JSONL读取上限记录) -> list[dict[str, Any]]:
        """按任意维度查询最近有界审计记录。"""
        结果列表 = []
        记录列表, _ = 读取JSONL(
            self.审计文件, 最大字节数=默认JSONL读取上限字节,
            最大记录数=默认JSONL读取上限记录,
        )
        for 记录 in 记录列表:
            if 用户id and 记录.get("用户id") != 用户id:
                continue
            if 能力id and 记录.get("能力id") != 能力id:
                continue
            if 操作 and 记录.get("操作") != 操作:
                continue
            if 项目id and 记录.get("项目id") != 项目id:
                continue
            if 请求id and 记录.get("请求id") != 请求id:
                continue
            if 任务id and 记录.get("任务id") != 任务id:
                continue
            if 错误码 and 记录.get("错误码") != 错误码:
                continue
            if 成功 is not None and 记录.get("成功") != 成功:
                continue
            if 限流 is not None and 记录.get("被限流") != 限流:
                continue
            if 权限拒绝 is not None and 记录.get("权限拒绝") != 权限拒绝:
                continue
            if 回滚 is not None and 记录.get("触发回滚") != 回滚:
                continue
            if 敏感配置 is not None and 记录.get("访问敏感配置") != 敏感配置:
                continue
            结果列表.append(记录)
        return 结果列表[-max(1, int(最大记录数)):]

    def 统计(self) -> dict[str, int]:
        全部 = self.查询()
        return {
            "总记录数": len(全部),
            "成功数": sum(1 for 记录 in 全部 if 记录["成功"]),
            "失败数": sum(1 for 记录 in 全部 if not 记录["成功"]),
            "被限流数": sum(1 for 记录 in 全部 if 记录["被限流"]),
            "权限拒绝数": sum(1 for 记录 in 全部 if 记录["权限拒绝"]),
            "触发回滚数": sum(1 for 记录 in 全部 if 记录["触发回滚"]),
            "敏感配置访问数": sum(1 for 记录 in 全部 if 记录["访问敏感配置"]),
        }
