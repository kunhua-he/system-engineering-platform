"""公共句柄契约与唯一状态机实现。"""
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
    句柄id: str = ""
    句柄类型: str = 句柄类型_资源
    资源id: str = ""
    项目id: str = ""
    所有者: str = ""
    状态: str = 状态_已创建
    创建时间: str = ""
    失效时间: str = ""
    失效原因: str = ""
    版本: str = ""
    元数据: dict[str, Any] = field(default_factory=dict)

    def 转字典(self) -> dict[str, Any]:
        return {"句柄id": self.句柄id, "句柄类型": self.句柄类型, "资源id": self.资源id,
                "项目id": self.项目id, "所有者": self.所有者, "状态": self.状态,
                "创建时间": self.创建时间, "失效时间": self.失效时间,
                "失效原因": self.失效原因, "版本": self.版本}

class 句柄体系:
    def __init__(self) -> None:
        self.句柄表: dict[str, 句柄] = {}
        self.回收证据表: list[dict[str, Any]] = []

    def 创建句柄(self, *, 句柄类型: str, 资源id: str, 项目id: str = "", 所有者: str = "", 版本: str = "") -> 句柄:
        对象 = 句柄(uuid.uuid4().hex[:16], 句柄类型, 资源id, 项目id, 所有者, 状态_有效, time.strftime("%Y-%m-%d %H:%M:%S"), 版本=版本)
        self.句柄表[对象.句柄id] = 对象
        return 对象

    def 校验(self, 句柄id: str, *, 项目id: str = "", 所有者: str = "") -> tuple[bool, str]:
        对象 = self.句柄表.get(句柄id)
        if 对象 is None: return False, f"句柄不存在: {句柄id}"
        if 对象.状态 != 状态_有效: return False, f"句柄已失效（{对象.失效原因}），不能自动复活"
        if 项目id and 对象.项目id and 对象.项目id != 项目id: return False, f"跨项目复用被拒绝: 句柄属 {对象.项目id}，请求 {项目id}"
        if 所有者 and 对象.所有者 and 对象.所有者 != 所有者: return False, f"跨所有者复用被拒绝: 句柄属 {对象.所有者}，请求 {所有者}"
        return True, "句柄有效"

    def 失效(self, 句柄id: str, 原因: str) -> tuple[bool, str]:
        对象 = self.句柄表.get(句柄id)
        if 对象 is None: return False, f"句柄不存在: {句柄id}"
        if 对象.状态 == 状态_已失效: return True, "句柄已失效（幂等）"
        对象.状态 = 状态_已失效; 对象.失效时间 = time.strftime("%Y-%m-%d %H:%M:%S"); 对象.失效原因 = 原因
        self.回收证据表.append({"句柄id": 句柄id, "资源id": 对象.资源id, "类型": 对象.句柄类型, "失效原因": 原因, "时间": 对象.失效时间, "版本": 对象.版本})
        return True, f"句柄已失效（{原因}）"

    def 查询回收证据(self, *, 资源id: str = "") -> list[dict[str, Any]]:
        return [x for x in self.回收证据表 if not 资源id or x["资源id"] == 资源id]

    def 活跃句柄数(self) -> int:
        return sum(x.状态 == 状态_有效 for x in self.句柄表.values())

    def 状态快照(self) -> dict[str, Any]:
        return {"句柄总数": len(self.句柄表), "活跃句柄数": self.活跃句柄数(), "回收证据数": len(self.回收证据表)}

__all__ = ["句柄", "句柄体系", "句柄类型_读取", "句柄类型_修改事务", "句柄类型_资源", "句柄类型_任务", "句柄类型_会话", "状态_已创建", "状态_有效", "状态_已失效", "失效原因_过期", "失效原因_回收", "失效原因_释放", "失效原因_超时"]
