"""统一运行上下文：所有前端、网关、后端、模块和支持库调用统一携带。

字段：请求id/任务id/项目id/用户id/会话id/模块id/能力id/包版本/契约版本/提供者。
要求：运行事件自动继承上下文；错误记录自动关联上下文；诊断中心可按
任意上下文查询；跨进程调用不丢失上下文；日志不写入敏感值。
"""

from __future__ import annotations

import json
import threading
import uuid
from dataclasses import dataclass, field
from typing import Any


@dataclass
class 运行上下文:
    """一次调用链的统一上下文。"""

    请求id: str = ""
    任务id: str = ""
    项目id: str = ""
    用户id: str = ""
    会话id: str = ""
    模块id: str = ""
    能力id: str = ""
    包版本: str = ""
    契约版本: str = ""
    提供者: str = ""
    父请求id: str = ""
    权限范围: list[str] = field(default_factory=list)
    来源地址: str = ""
    操作id: str = ""
    句柄: int | None = None

    def __post_init__(self) -> None:
        if not self.请求id:
            self.请求id = uuid.uuid4().hex[:16]

    def 继承(self, **覆盖字段: Any) -> "运行上下文":
        """派生子上下文（跨进程传递不丢失上下文）。"""
        字段表 = {
            "请求id": self.请求id, "任务id": self.任务id, "项目id": self.项目id,
            "用户id": self.用户id, "会话id": self.会话id, "模块id": self.模块id,
            "能力id": self.能力id, "包版本": self.包版本, "契约版本": self.契约版本,
            "提供者": self.提供者, "父请求id": self.请求id,
            "权限范围": list(self.权限范围), "来源地址": self.来源地址,
            "操作id": self.操作id, "句柄": self.句柄,
        }
        字段表.update(覆盖字段)
        return 运行上下文(**字段表)

    def 转字典(self) -> dict[str, Any]:
        return {
            "请求id": self.请求id, "任务id": self.任务id, "项目id": self.项目id,
            "用户id": self.用户id, "会话id": self.会话id, "模块id": self.模块id,
            "能力id": self.能力id, "包版本": self.包版本, "契约版本": self.契约版本,
            "提供者": self.提供者, "父请求id": self.父请求id,
            "权限范围": list(self.权限范围), "来源地址": self.来源地址,
            "操作id": self.操作id, "句柄": self.句柄,
        }

    def 事件字段(self) -> dict[str, Any]:
        """供运行事件继承（事件模型字段映射）。"""
        return {
            "追踪id": self.请求id, "项目id": self.项目id, "能力id": self.能力id,
            "模块id": self.模块id, "版本": self.包版本, "契约版本": self.契约版本,
            "提供者": self.提供者, "用户id": self.用户id,
            "会话id": self.会话id, "任务id": self.任务id,
            "来源地址": self.来源地址, "操作id": self.操作id, "句柄": self.句柄,
        }

    @classmethod
    def 从字典(cls, 数据: dict[str, Any]) -> "运行上下文":
        合法字段 = {字段 for 字段 in cls.__dataclass_fields__}
        字段表 = {键: 值 for 键, 值 in (数据 or {}).items() if 键 in 合法字段}
        权限范围 = 字段表.get("权限范围", [])
        if not isinstance(权限范围, list) or not all(isinstance(项, str) for 项 in 权限范围):
            字段表["权限范围"] = []
        return cls(**字段表)


class 上下文管理器:
    """当前线程的上下文栈（前端/网关/后端共享）。"""

    def __init__(self) -> None:
        self._线程状态 = threading.local()

    @property
    def 栈(self) -> list[运行上下文]:
        """每个请求线程独立持有上下文栈，避免并发请求串线。"""
        if not hasattr(self._线程状态, "栈"):
            self._线程状态.栈 = []
        return self._线程状态.栈

    def 进入(self, 上下文: 运行上下文) -> 运行上下文:
        self.栈.append(上下文)
        return 上下文

    def 当前(self) -> 运行上下文:
        return self.栈[-1] if self.栈 else 运行上下文()

    def 退出(self) -> None:
        if self.栈:
            self.栈.pop()

    def 序列化当前(self) -> str:
        """跨进程传递：上下文序列化（JSON 行）。"""
        return json.dumps(self.当前().转字典(), ensure_ascii=False)

    def 反序列化进入(self, 文本: str) -> 运行上下文:
        try:
            数据 = json.loads(文本)
        except json.JSONDecodeError:
            数据 = {}
        return self.进入(运行上下文.从字典(数据))


全局上下文管理器 = 上下文管理器()
