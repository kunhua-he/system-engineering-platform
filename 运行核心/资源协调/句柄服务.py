"""统一外部资源句柄服务：句柄只作查询键，不承载模块内部对象。"""

from __future__ import annotations

import time
from typing import Any

from 公共契约.句柄体系 import 句柄类型_资源, 句柄体系, 是合法句柄id


class 资源句柄服务:
    """为网关提供登记、状态、续租和关闭；模块 CRUD 仍由模块自己负责。"""

    def __init__(self) -> None:
        self.句柄体系 = 句柄体系()

    def 登记(self, 句柄id: str, *, 资源id: str = "", 项目id: str = "",
             所有者: str = "", 句柄类型: str = 句柄类型_资源,
             元数据: dict[str, Any] | None = None) -> dict[str, Any]:
        if not isinstance(句柄id, str) or not 句柄id.strip():
            raise ValueError("句柄不能为空")
        if not 是合法句柄id(句柄id):
            raise ValueError("句柄必须是六位数字")
        已有 = self.句柄体系.句柄表.get(句柄id)
        if 已有 is None:
            已有 = self.句柄体系.创建句柄(
                句柄类型=句柄类型, 资源id=资源id, 项目id=项目id, 所有者=所有者,
            )
            临时句柄id = 已有.句柄id
            已有.句柄id = 句柄id
            self.句柄体系.句柄表.pop(临时句柄id, None)
            self.句柄体系.句柄表[句柄id] = 已有
        if 元数据:
            已有.元数据.update(元数据)
        return self._转公开(已有)

    def 状态(self, 句柄id: str, *, 项目id: str = "", 所有者: str = "") -> dict[str, Any] | None:
        对象 = self.句柄体系.句柄表.get(句柄id)
        if 对象 is None:
            return None
        通过, _ = self.句柄体系.校验(句柄id, 项目id=项目id, 所有者=所有者)
        if not 通过:
            raise PermissionError("句柄所属项目或所有者不匹配")
        截止 = float(对象.元数据.get("租约截止", 0) or 0)
        if 截止 and 截止 <= time.time():
            self.句柄体系.失效(句柄id, "租约过期")
        return self._转公开(对象)

    def 续租(self, 句柄id: str, *, 租约秒: float = 300,
             项目id: str = "", 所有者: str = "") -> dict[str, Any]:
        对象 = self.句柄体系.句柄表.get(句柄id)
        if 对象 is None:
            raise KeyError("句柄不存在")
        通过, 消息 = self.句柄体系.校验(句柄id, 项目id=项目id, 所有者=所有者)
        if not 通过:
            raise PermissionError(消息)
        if isinstance(租约秒, bool) or not isinstance(租约秒, (int, float)) or not 0 < 租约秒 <= 86400:
            raise ValueError("租约秒必须在 1 到 86400 之间")
        对象.元数据["租约截止"] = time.time() + float(租约秒)
        return self._转公开(对象)

    def 关闭(self, 句柄id: str, *, 项目id: str = "", 所有者: str = "") -> dict[str, Any]:
        对象 = self.句柄体系.句柄表.get(句柄id)
        if 对象 is None:
            raise KeyError("句柄不存在")
        通过, 消息 = self.句柄体系.校验(句柄id, 项目id=项目id, 所有者=所有者)
        if not 通过 and 对象.状态 != "已失效":
            raise PermissionError(消息)
        self.句柄体系.失效(句柄id, "主动关闭")
        return self._转公开(对象)

    @staticmethod
    def _转公开(对象: Any) -> dict[str, Any]:
        return {
            "句柄": 对象.句柄id, "句柄类型": 对象.句柄类型,
            "资源id": 对象.资源id, "项目id": 对象.项目id,
            "所有者": 对象.所有者, "状态": 对象.状态,
            "版本": 对象.版本, "元数据": dict(对象.元数据),
        }


__all__ = ["资源句柄服务"]
