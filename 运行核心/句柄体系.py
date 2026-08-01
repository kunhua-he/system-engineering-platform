"""运行核心句柄体系：统一资源协调的句柄状态机。

句柄类型：读取句柄/修改事务句柄/资源句柄/任务句柄/会话句柄。
规则：普通局部变量不创建系统句柄；只有共享可变状态、外部资源、
跨请求对象和长任务进入句柄体系。
句柄状态机：已创建 → 有效 → 已失效（过期/回收/释放）；回收证据保留。
过期句柄拒绝调用且不能自动复活；跨项目、跨所有者复用被拒绝。
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any

句柄类型_读取 = "读取句柄"
句柄类型_修改事务 = "修改事务句柄"
句柄类型_资源 = "资源句柄"
句柄类型_任务 = "任务句柄"
句柄类型_会话 = "会话句柄"

状态_已创建 = "已创建"
状态_有效 = "有效"
状态_已失效 = "已失效"

失效原因_过期 = "过期"
失效原因_回收 = "回收"
失效原因_释放 = "释放"
失效原因_超时 = "超时"


@dataclass
class 句柄:
    """一个系统句柄。"""

    句柄id: str = ""
    句柄类型: str = 句柄类型_资源
    资源id: str = ""
    项目id: str = ""
    所有者: str = ""
    状态: str = 状态_已创建
    创建时间: str = ""
    失效时间: str = ""
    失效原因: str = ""
    版本: str = ""  # 读取句柄锁定快照版本
    元数据: dict[str, Any] = field(default_factory=dict)

    def 转字典(self) -> dict[str, Any]:
        return {
            "句柄id": self.句柄id, "句柄类型": self.句柄类型, "资源id": self.资源id,
            "项目id": self.项目id, "所有者": self.所有者, "状态": self.状态,
            "创建时间": self.创建时间, "失效时间": self.失效时间,
            "失效原因": self.失效原因, "版本": self.版本,
        }


class 句柄体系:
    """句柄体系：创建/校验/失效/回收 + 回收证据。"""

    def __init__(self) -> None:
        self.句柄表: dict[str, 句柄] = {}
        self.回收证据表: list[dict[str, Any]] = []

    def 创建句柄(self, *, 句柄类型: str, 资源id: str, 项目id: str = "",
                所有者: str = "", 版本: str = "") -> 句柄:
        句柄对象 = 句柄(
            句柄id=uuid.uuid4().hex[:16], 句柄类型=句柄类型, 资源id=资源id,
            项目id=项目id, 所有者=所有者, 状态=状态_有效,
            创建时间=time.strftime("%Y-%m-%d %H:%M:%S"), 版本=版本,
        )
        self.句柄表[句柄对象.句柄id] = 句柄对象
        return 句柄对象

    def 校验(self, 句柄id: str, *, 项目id: str = "", 所有者: str = "") -> tuple[bool, str]:
        """校验句柄有效 + 权限与所有者匹配；跨项目/跨所有者拒绝。"""
        句柄对象 = self.句柄表.get(句柄id)
        if 句柄对象 is None:
            return False, f"句柄不存在: {句柄id}"
        if 句柄对象.状态 != 状态_有效:
            return False, f"句柄已失效（{句柄对象.失效原因}），不能自动复活"
        if 项目id and 句柄对象.项目id and 句柄对象.项目id != 项目id:
            return False, f"跨项目复用被拒绝: 句柄属 {句柄对象.项目id}，请求 {项目id}"
        if 所有者 and 句柄对象.所有者 and 句柄对象.所有者 != 所有者:
            return False, f"跨所有者复用被拒绝: 句柄属 {句柄对象.所有者}，请求 {所有者}"
        return True, "句柄有效"

    def 失效(self, 句柄id: str, 原因: str) -> tuple[bool, str]:
        """失效句柄；重复失效幂等；记录回收证据。"""
        句柄对象 = self.句柄表.get(句柄id)
        if 句柄对象 is None:
            return False, f"句柄不存在: {句柄id}"
        if 句柄对象.状态 == 状态_已失效:
            return True, "句柄已失效（幂等）"
        句柄对象.状态 = 状态_已失效
        句柄对象.失效时间 = time.strftime("%Y-%m-%d %H:%M:%S")
        句柄对象.失效原因 = 原因
        self.回收证据表.append({
            "句柄id": 句柄id, "资源id": 句柄对象.资源id, "类型": 句柄对象.句柄类型,
            "失效原因": 原因, "时间": 句柄对象.失效时间, "版本": 句柄对象.版本,
        })
        return True, f"句柄已失效（{原因}）"

    def 查询回收证据(self, *, 资源id: str = "") -> list[dict[str, Any]]:
        if 资源id:
            return [证据 for 证据 in self.回收证据表 if 证据["资源id"] == 资源id]
        return list(self.回收证据表)

    def 活跃句柄数(self) -> int:
        return sum(1 for 句柄对象 in self.句柄表.values() if 句柄对象.状态 == 状态_有效)

    def 状态快照(self) -> dict[str, Any]:
        return {
            "句柄总数": len(self.句柄表),
            "活跃句柄数": self.活跃句柄数(),
            "回收证据数": len(self.回收证据表),
        }
