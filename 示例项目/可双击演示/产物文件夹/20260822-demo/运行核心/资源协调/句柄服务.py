"""统一外部资源句柄服务：句柄只作查询键，不承载模块内部对象。"""

from __future__ import annotations

import time
import uuid
import json
import hashlib
from pathlib import Path
from typing import Any

from 公共契约.句柄体系 import (
    句柄, 句柄类型_资源, 句柄体系, 是合法句柄id, 状态_已失效,
)
from 运行核心.权威状态 import 权威状态


class 资源句柄服务:
    """为网关提供登记、状态、续租和关闭；模块 CRUD 仍由模块自己负责。"""

    def __init__(self, 存储目录: Path | None = None, *, 默认超时秒: float = 1800) -> None:
        self.句柄体系 = 句柄体系()
        self.默认超时秒 = 默认超时秒
        self.权威状态 = 权威状态(存储目录 or Path("工程缓存") / "权威状态")
        self._恢复账本句柄()

    def _恢复账本句柄(self) -> None:
        """启动时从 SQLite 恢复有效句柄；账本不完整时拒绝恢复（fail-closed）。"""
        for 记录 in self.权威状态.全部句柄(仅有效=True):
            原句柄id = 记录["句柄id"]
            账本句柄id = self._规范化句柄id(原句柄id)
            if 账本句柄id is None:
                # 历史测试/崩溃残留不得阻断新实例启动；该记录仍留在账本供审计。
                continue
            租约 = self.权威状态.读取租约(原句柄id)
            if not 租约 or 租约["已回收"]:
                continue
            对象 = 句柄(
                句柄id=账本句柄id, 句柄类型=记录["句柄类型"],
                资源id=记录["资源id"], 项目id=记录["项目id"],
                所有者=记录["所有者"], 状态=记录["状态"],
                创建时间=记录["创建时间"], 失效时间=记录["失效时间"],
                失效原因=记录["失效原因"], 版本=记录["版本"],
                元数据={"租约截止": float(租约["硬截止时间"]),
                        "租约id": 租约["租约id"],
                        "最后心跳": float(租约["最后心跳"])},
            )
            self.句柄体系.恢复句柄(对象)

    def _加载句柄(self, 句柄id: str | int) -> Any | None:
        """按需从账本加载句柄，避免多个网关实例之间只看各自内存。"""
        对象 = self.句柄体系.句柄表.get(句柄id)
        if 对象 is not None:
            return 对象
        记录 = self.权威状态.读取句柄(句柄id)
        if not 记录:
            return None
        租约 = self.权威状态.读取租约(句柄id)
        元数据: dict[str, Any] = {}
        if 租约:
            元数据 = {"租约截止": float(租约["硬截止时间"]),
                      "租约id": 租约["租约id"],
                      "最后心跳": float(租约["最后心跳"])}
        账本句柄id = self._规范化句柄id(记录["句柄id"])
        if 账本句柄id is None:
            return None
        对象 = self.句柄体系.恢复句柄(句柄(
            句柄id=账本句柄id, 句柄类型=记录["句柄类型"],
            资源id=记录["资源id"], 项目id=记录["项目id"],
            所有者=记录["所有者"], 状态=记录["状态"],
            创建时间=记录["创建时间"], 失效时间=记录["失效时间"],
            失效原因=记录["失效原因"], 版本=记录["版本"], 元数据=元数据,
        ))
        # SQLite 的 TEXT 亲和性可能把历史整数读成字符串；保留请求键别名，
        # 使旧客户端和六位字符串客户端都命中同一个账本对象。
        if 句柄id != 对象.句柄id:
            self.句柄体系.句柄表[句柄id] = 对象
        return 对象

    @staticmethod
    def _规范化句柄id(句柄id: str | int) -> str | int | None:
        """恢复时把旧 SQLite 数字亲和性值规范为六位字符串。"""
        if isinstance(句柄id, str) and 句柄id.isascii() and 句柄id.isdecimal():
            return 句柄id.zfill(6)
        if isinstance(句柄id, int) and not isinstance(句柄id, bool) and 1 <= 句柄id <= 999999:
            return f"{句柄id:06d}"
        return None

    @staticmethod
    def _校验文本(值: Any, 字段: str, *, 可空: bool = True) -> None:
        if not isinstance(值, str) or (not 可空 and not 值):
            raise ValueError(f"{字段}必须是文本型")

    def 登记(self, 句柄id: str | int, *, 资源id: str = "", 项目id: str = "",
             所有者: str = "", 句柄类型: str = 句柄类型_资源,
             元数据: dict[str, Any] | None = None) -> dict[str, Any]:
        if isinstance(句柄id, bool) or not 是合法句柄id(句柄id):
            raise ValueError("句柄必须是六位数字字符串或合法句柄")
        if not 是合法句柄id(句柄id):
            raise ValueError("句柄格式不合法")
        self._校验文本(资源id, "资源id")
        self._校验文本(项目id, "项目id")
        self._校验文本(所有者, "所有者")
        self._校验文本(句柄类型, "句柄类型", 可空=False)
        if 元数据 is not None and not isinstance(元数据, dict):
            raise ValueError("元数据必须是字典型")
        已有 = self._加载句柄(句柄id)
        if 已有 is None:
            raise ValueError("句柄必须由状态机生成，不能自行登记伪造句柄")
        if 元数据:
            已有.元数据.update(元数据)
        return self._转公开(已有)

    def 创建(self, *, 资源id: str, 项目id: str = "", 所有者: str = "",
             句柄类型: str = 句柄类型_资源,
             元数据: dict[str, Any] | None = None) -> dict[str, Any]:
        """由状态机生成句柄，并在同一操作内写入权威生命周期账本。"""
        self._校验文本(资源id, "资源id", 可空=False)
        self._校验文本(项目id, "项目id")
        self._校验文本(所有者, "所有者")
        self._校验文本(句柄类型, "句柄类型", 可空=False)
        if 元数据 is not None and not isinstance(元数据, dict):
            raise ValueError("元数据必须是字典型")
        对象 = self.句柄体系.创建句柄(
            句柄类型=句柄类型, 资源id=资源id, 项目id=项目id, 所有者=所有者,
        )
        对象.元数据["租约截止"] = time.time() + self.默认超时秒
        对象.元数据["租约id"] = uuid.uuid4().hex[:16]
        if 元数据:
            对象.元数据.update(元数据)
        self.权威状态.保存句柄与租约(
            句柄id=对象.句柄id, 句柄类型=对象.句柄类型, 资源id=对象.资源id,
            项目id=对象.项目id, 所有者=对象.所有者, 状态=对象.状态,
            版本=对象.版本,
            租约id=对象.元数据["租约id"], 空闲超时秒=self.默认超时秒,
            硬截止时间=对象.元数据["租约截止"], 最后心跳=time.time(),
            进程身份键=self.权威状态.身份.身份键(),
        )
        return self._转公开(对象)

    def 状态(self, 句柄id: str | int, *, 项目id: str = "", 所有者: str = "") -> dict[str, Any] | None:
        对象 = self._加载句柄(句柄id)
        if 对象 is None:
            return None
        if 项目id and 对象.项目id and 对象.项目id != 项目id:
            raise PermissionError("句柄所属项目不匹配")
        if 所有者 and 对象.所有者 and 对象.所有者 != 所有者:
            raise PermissionError("句柄所属所有者不匹配")
        if 对象.状态 != "有效":
            return self._转公开(对象)
        截止 = float(对象.元数据.get("租约截止", 0) or 0)
        if 截止 and 截止 <= time.time():
            self._失效并记账(对象, "句柄超时")
        return self._转公开(对象)

    def 续租(self, 句柄id: str | int, *, 租约秒: float = 300,
             项目id: str = "", 所有者: str = "") -> dict[str, Any]:
        对象 = self._加载句柄(句柄id)
        if 对象 is None:
            raise KeyError("句柄不存在")
        通过, 消息 = self.句柄体系.校验(句柄id, 项目id=项目id, 所有者=所有者)
        if not 通过:
            raise PermissionError(消息)
        if isinstance(租约秒, bool) or not isinstance(租约秒, (int, float)) or not 0 < 租约秒 <= 86400:
            raise ValueError("租约秒必须在 1 到 86400 之间")
        现在 = time.time()
        原截止 = float(对象.元数据.get("租约截止", 0) or 0)
        if 原截止 and 原截止 <= 现在:
            self._失效并记账(对象, "句柄超时")
            raise PermissionError("句柄已过期，不能续租")
        租约id = 对象.元数据.get("租约id", "")
        新截止 = 现在 + float(租约秒)
        if not 租约id or not self.权威状态.续租租约(
                租约id, 硬截止时间=新截止, 最后心跳=现在, 当前时间=现在):
            self._加载句柄(句柄id)
            raise PermissionError("租约已失效，不能续租")
        对象.元数据["租约截止"] = 新截止
        对象.元数据["最后心跳"] = 现在
        return self._转公开(对象)

    def 关闭(self, 句柄id: str | int, *, 项目id: str = "", 所有者: str = "") -> dict[str, Any]:
        对象 = self._加载句柄(句柄id)
        if 对象 is None:
            raise KeyError("句柄不存在")
        通过, 消息 = self.句柄体系.校验(句柄id, 项目id=项目id, 所有者=所有者)
        if not 通过 and 对象.状态 != "已失效":
            raise PermissionError(消息)
        self._失效并记账(对象, "主动释放")
        return self._转公开(对象)

    def 关闭服务(self) -> None:
        """关闭句柄服务持有的权威状态连接；句柄账本保留供下次恢复。"""
        self.权威状态.关闭()

    def 创建受管状态(self, *, 资源id: str, 初始状态: dict[str, Any],
                  项目id: str = "", 所有者: str = "") -> dict[str, Any]:
        """创建句柄并把业务状态写入权威资源版本表。"""
        if not isinstance(初始状态, dict):
            raise ValueError("初始状态必须是字典型")
        公开句柄 = self.创建(
            资源id=资源id, 项目id=项目id, 所有者=所有者,
            元数据={"受管状态": True},
        )
        self.权威状态.初始化资源(资源id, dict(初始状态))
        return self._受管状态结果(公开句柄["句柄"], 项目id=项目id, 所有者=所有者)

    def 读取受管状态(self, 句柄id: str | int, *,
                  项目id: str = "", 所有者: str = "") -> dict[str, Any]:
        """按有效句柄读取权威业务状态。"""
        return self._受管状态结果(句柄id, 项目id=项目id, 所有者=所有者)

    def 更新受管状态(self, 句柄id: str | int, 新状态: dict[str, Any], *,
                  期望版本: str = "", 项目id: str = "", 所有者: str = "") -> dict[str, Any]:
        """按句柄对权威状态做带资源锁和版本条件的原子更新。"""
        if not isinstance(新状态, dict):
            raise ValueError("新状态必须是字典型")
        对象 = self._有效受管句柄(句柄id, 项目id=项目id, 所有者=所有者)
        当前 = self.权威状态.读取资源(对象.资源id)
        if 当前 is None:
            raise KeyError("受管状态不存在")
        版本 = str(期望版本 or 当前["版本"])
        事务id = uuid.uuid4().hex
        成功, 消息, 令牌 = self.权威状态.获取锁(
            对象.资源id, 操作id=事务id, 事务id=事务id,
            项目id=项目id, 所有者=所有者,
        )
        if not 成功:
            raise RuntimeError(f"受管状态加锁失败: {消息}")
        摘要 = hashlib.sha256(
            json.dumps(新状态, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()
        try:
            已提交, 提交消息 = self.权威状态.提交资源(
                资源id=对象.资源id, 期望版本=版本, 期望令牌=str(令牌),
                事务id=事务id, 项目id=项目id, 所有者=所有者,
                新值=dict(新状态), 新摘要=摘要,
            )
        finally:
            self.权威状态.释放锁(
                对象.资源id, 操作id=事务id, 事务id=事务id, 令牌=令牌)
        if not 已提交:
            raise RuntimeError(f"受管状态更新失败: {提交消息}")
        return self._受管状态结果(句柄id, 项目id=项目id, 所有者=所有者)

    def 释放受管状态(self, 句柄id: str | int, *,
                  项目id: str = "", 所有者: str = "") -> dict[str, Any]:
        """释放受管状态句柄；历史资源版本保留审计。"""
        return self.关闭(句柄id, 项目id=项目id, 所有者=所有者)

    def _有效受管句柄(self, 句柄id: str | int, *, 项目id: str, 所有者: str):
        对象 = self._加载句柄(句柄id)
        if 对象 is None:
            raise KeyError("句柄不存在")
        公开 = self.状态(句柄id, 项目id=项目id, 所有者=所有者)
        if 公开 is None or 公开["状态"] != "有效":
            raise PermissionError("句柄已过期")
        if not 对象.元数据.get("受管状态"):
            # 重启恢复后元数据不持久化，以资源版本存在作为权威补判。
            if self.权威状态.读取资源(对象.资源id) is None:
                raise PermissionError("句柄未绑定受管状态")
        return 对象

    def _受管状态结果(self, 句柄id: str | int, *, 项目id: str, 所有者: str) -> dict[str, Any]:
        对象 = self._有效受管句柄(句柄id, 项目id=项目id, 所有者=所有者)
        状态 = self.权威状态.读取资源(对象.资源id)
        if 状态 is None:
            raise KeyError("受管状态不存在")
        return {
            "句柄": 对象.句柄id, "资源id": 对象.资源id,
            "状态": 状态["值"], "版本": str(状态["版本"]),
        }

    def _失效并记账(self, 对象: Any, 原因: str) -> None:
        """内存状态与 SQLite 账本原子顺序收口；重复失效不重复制造错误。"""
        if 对象.状态 == "已失效":
            return
        成功, 消息 = self.句柄体系.失效(对象.句柄id, 原因)
        if not 成功:
            raise RuntimeError(f"资源未收敛：{消息}")
        self.权威状态.失效句柄并记录证据(
            句柄id=对象.句柄id, 资源id=对象.资源id, 类型=对象.句柄类型,
            原因=原因, 版本=对象.版本,
        )
        租约id = 对象.元数据.get("租约id", "")
        if 租约id:
            self.权威状态.回收租约(租约id, 原因)

    @staticmethod
    def _转公开(对象: Any) -> dict[str, Any]:
        return {
            "句柄": 对象.句柄id, "句柄类型": 对象.句柄类型,
            "资源id": 对象.资源id, "项目id": 对象.项目id,
            "所有者": 对象.所有者, "状态": 对象.状态,
            "版本": 对象.版本, "元数据": dict(对象.元数据),
        }


__all__ = ["资源句柄服务"]
