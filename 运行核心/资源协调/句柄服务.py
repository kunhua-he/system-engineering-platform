"""统一外部资源句柄服务：句柄只作查询键，不承载模块内部对象。"""

from __future__ import annotations

import threading
import time
import uuid
import json
import hashlib
from pathlib import Path
from typing import Any

from 公共契约.句柄体系 import (
    句柄, 句柄类型_资源, 句柄体系, 是合法句柄id, 状态_已失效,
)
from 公共契约.诊断.忽略记录 import 记录忽略
from 运行核心.权威状态 import 权威状态
from 公共契约.基础类型.逻辑类型 import 真, 假


class 资源句柄服务:
    """为网关提供登记、状态、续租和关闭；模块 CRUD 仍由模块自己负责。"""

    def __init__(self, 存储目录: Path | None = None, *, 默认超时秒: float = 1800) -> None:
        self.句柄体系 = 句柄体系()
        self.默认超时秒 = 默认超时秒
        # 账本落点经唯一解析器（禁止 cwd 依赖的裸相对 `工程缓存`）：制品进程 cwd 是制品目录，
        # 裸相对值会把句柄账本写进不可变制品；源码态回落 `<系统根>/工程缓存`（与旧值同义）。
        from 公共契约.运行时.运行缓存 import 解析运行缓存根

        self.权威状态 = 权威状态(
            存储目录 or 解析运行缓存根(Path(__file__).resolve().parents[2]) / "权威状态")
        # 启动恢复统计（现场口径：账本 有效行 8972 / 全量灌入 3.03s / 13.14MB）
        self.启动恢复统计: dict[str, Any] = {
            "恢复": 0, "格式不合法": 0, "无可用租约": 0, "已过期": 0}
        # 唤醒重判（审计 §9-B6）：内存句柄的 `元数据["租约截止"]` 是**睡下那一刻**的快照。
        # 合盖唤醒后账本里的租约已被 `权威状态.唤醒重判租约` 顺延，而内存快照没动 ——
        # 不刷新的话 `状态()` 会拿旧快照立刻把句柄判超时失效，把刚做的修正又抹掉
        # （这正是「沿用睡眠前的判定」）。故记下「唤醒序号」，每条被用到的句柄
        # **按需**刷新一次（懒加载：不遍历句柄表、开销随实际用量）。
        self._唤醒序号 = 0
        self._恢复账本句柄()

    def _恢复账本句柄(self) -> None:
        """启动时从 SQLite 恢复有效句柄；账本不完整时拒绝恢复（fail-closed）。

        只恢复「未回收且未过期」的句柄：过期句柄在所有入口（状态/续租）
        都已不可用（状态() 判超时即失效、续租() 拒绝复活），把它们灌进内存
        只白占内存与启动耗时。过期行仍留在账本供审计，由权威状态的
        清理器按保留窗口真删（回收过期资源行）。
        取数走 有效句柄与租约() 一次查询：逐行 读取租约 的 N+1 才是启动耗时主因
        （现场 8983 行 ≈ 2.99s），句柄与租约的配对口径与 读取租约 完全一致。

        唤醒重校准（审计 §9-B6，启动路径）：先按落盘的双时钟读数判「睡下之后才启动」
        的唤醒，凡属于睡眠窗口的租约先顺延回持有者手里，**再**做下面的逐行恢复 ——
        否则恢复路径会拿睡前的墙钟截止时间把整批租约判过期
        （打开机器就是「全部句柄超时」）。不构成唤醒（含：本机重启过、无基线）时零动作。
        """
        跨重启判定 = self.权威状态.检测跨重启唤醒()
        if 跨重启判定 is not None:
            self.启动恢复统计["唤醒重判"] = self.权威状态.唤醒重判租约(跨重启判定)
        现在 = time.time()
        for 记录 in self.权威状态.有效句柄与租约():
            原句柄id = 记录["句柄id"]
            账本句柄id = self._规范化句柄id(原句柄id)
            if 账本句柄id is None:
                # 历史测试/崩溃残留不得阻断新实例启动；该记录仍留在账本供审计。
                self.启动恢复统计["格式不合法"] += 1
                continue
            租约 = 记录.get("租约")
            if not 租约 or 租约["已回收"]:
                self.启动恢复统计["无可用租约"] += 1
                continue
            截止 = 租约.get("硬截止时间")
            if 截止 is None or float(截止) <= 现在:
                # 过期即不恢复：硬截止时间为 epoch 秒（写入方 创建 用
                # time.time()+默认超时秒），可直接与 time.time() 比较。
                self.启动恢复统计["已过期"] += 1
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
            self.启动恢复统计["恢复"] += 1

    def _加载句柄(self, 句柄id: str | int) -> Any | None:
        """按需从账本加载句柄，避免多个网关实例之间只看各自内存。"""
        self.唤醒重判()  # 唤醒检测挂在本就有的请求路径上；未检出唤醒时零动作
        对象 = self.句柄体系.查询句柄(句柄id)      # 唯一加锁读入口（禁止直接触碰 句柄表）
        if 对象 is not None:
            self._按需重判句柄(对象)
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
        # **收口（真竞态修）**：别名行只经 句柄体系.别名句柄() 持 `_锁` 写入——
        # 修前这里直接 `句柄体系.句柄表[句柄id] = 对象`（不经 `_锁`），与
        # `失效()` → `_淘汰失效句柄` 的锁内全表遍历并发时，遍历方抛
        # `RuntimeError: dictionary changed size during iteration`，
        # 把一次合法的句柄关闭/失效调用打成 500（200 轮并发探针 66 轮命中，修复后 0 轮）。
        if 句柄id != 对象.句柄id:
            self.句柄体系.别名句柄(句柄id, 对象)
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
    def _校验文本(值: Any, 字段: str, *, 可空: bool = 真) -> None:
        if not isinstance(值, str) or (not 可空 and not 值):
            raise ValueError(f"{字段}必须是文本型")

    # ---- 唤醒重判（审计 §9-B6） ----

    def 唤醒重判(self) -> dict[str, Any] | None:
        """热路径入口：检出（或尚未处理过）唤醒 → 账本租约重判 + 内存句柄快照重判。

        两件事必须在同一处触发，否则会互相打架：
        1. 账本侧：`权威状态.唤醒重判租约()` 把「睡眠期间才越过的截止时间」
           顺延回持有者手里（睡下前就已过期的维持原判）；
        2. 内存侧：本服务缓存的 `元数据["租约截止"]` 还是睡下那一刻的快照，
           不改就轮到 `状态()` 拿旧快照把句柄立刻判超时 —— 修正被自己抹掉。

        内存侧**懒刷新**（不在本方法里遍历句柄表）：本方法只推进 `_唤醒序号`，
        每条被用到的句柄在下一次 `_加载句柄` 时与自己的 `已重判唤醒序号` 比一次、
        按需从账本重新读一次截止时间。理由：句柄可有近万条，唤醒时全遍历是
        O(全表) 的无谓开销，而唤醒后真正会被用到的只有少数几条。

        未检出（且没有未处理的唤醒）→ 返回 None，**零动作**（正常路径只多两次取时钟
        与一次比较）。不新建线程、不新建巡检周期；挂在 `_加载句柄` 这条本来就有的
        请求路径上。
        """
        from 运行核心.时钟校准 import 取未处理唤醒

        判定 = 取未处理唤醒(self._唤醒序号)
        if 判定 is None:
            return None
        self._唤醒序号 = int(判定.序号)
        账本结果 = self.权威状态.唤醒重判租约(判定)
        return {"判定": 判定.转字典(), "账本": 账本结果}

    def _按需重判句柄(self, 对象: Any) -> None:
        """该句柄若落后于最近一次唤醒，就按账本重判一次（每句柄每代一次，幂等）。

        标记存在**句柄对象自己的元数据**里（`元数据["已重判唤醒序号"]`），不用服务的
        全局水位：句柄可有近万条，用一条全局水位就得在唤醒时遍历全表才能保证不漏，
        而唤醒后真正被用到的只有少数几条。
        """
        序号 = self._唤醒序号
        if not 序号 or 对象.元数据.get("已重判唤醒序号") == 序号:
            return
        对象.元数据["已重判唤醒序号"] = 序号
        租约id = 对象.元数据.get("租约id")
        if not 租约id:
            return
        租约 = self.权威状态.读取租约(对象.句柄id)
        if 租约 and str(租约.get("租约id") or "") == str(租约id):
            # 只重判「账本对同一租约的最新口径」：截止时间与心跳都取账本值，
            # 账本值已被 `唤醒重判租约` 顺延（睡眠窗口内的）；睡下前就已过期的
            # 账本值没被顺延，这里照抄后仍是过期 —— 与「不沿用睡眠前判定」同向。
            对象.元数据["租约截止"] = float(租约["硬截止时间"] or 0.0)
            对象.元数据["最后心跳"] = float(租约["最后心跳"] or 0.0)

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
        self._校验文本(句柄类型, "句柄类型", 可空=假)
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
        self._校验文本(资源id, "资源id", 可空=假)
        self._校验文本(项目id, "项目id")
        self._校验文本(所有者, "所有者")
        self._校验文本(句柄类型, "句柄类型", 可空=假)
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
        if 对象.项目id and 对象.项目id != 项目id:
            raise PermissionError("句柄所属项目不匹配")
        if 对象.所有者 and 对象.所有者 != 所有者:
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
            元数据={"受管状态": 真},
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


class 资源账本维护循环:
    """权威状态账本的周期维护：自身心跳 → 判死回收 → 过期真删 → 让出连接。

    背景（落点清单_05 R2）：句柄/租约/进程三表只增不删（现场 18 天
    9130/9166/3633 行），而已有的回收器 `清理死亡进程资源` /
    `扫描过期租约` 生产调用方为 0（仅在发布门禁里被调用过）。本类给
    它们真实的生产调用方，并让「判死 → 终态 → 按保留窗口真删」在长驻
    网关里周期推进。

    两个必须的自我保护：
    - 每轮先 `刷新心跳`：判死判据含「心跳过期即视为失联」，不刷新自身
      心跳会把仍在运行的自己判成死亡进程，进而回收自己创建的有效句柄；
    - 每轮收尾 `释放当前线程连接`：长驻线程若一直持有线程级连接，会让
      `权威状态.关闭()` 的「仍有工作线程正在使用权威状态」判据误报。
    """

    def __init__(self, 状态账本: Any, *, 间隔秒: float = 300.0,
                 心跳超时秒: float = 15.0, 保留窗口秒: float | None = None) -> None:
        if not 间隔秒 or float(间隔秒) <= 0:
            raise ValueError("间隔秒必须大于 0")
        self.状态账本 = 状态账本
        self.间隔秒 = float(间隔秒)
        self.心跳超时秒 = float(心跳超时秒)
        self.保留窗口秒 = 保留窗口秒
        self.清扫次数 = 0
        self.最近清扫: list[str] = []
        self.最近错误 = ""
        self._停止事件 = threading.Event()
        self._清扫锁 = threading.Lock()
        self._线程: threading.Thread | None = None

    def 清扫一次(self) -> list[str]:
        """一轮清扫：刷新心跳 → 判死回收（末尾含真删）→ 扫过期租约 → 再真删新终态行。"""
        with self._清扫锁:
            try:
                self.状态账本.刷新心跳()
            except Exception as 错误:  # 允许忽略，但留痕（哲学第 3 条 2 项）
                记录忽略('资源账本维护循环.刷新心跳', 错误)
            清理列表 = list(self.状态账本.清理死亡进程资源(
                心跳超时秒=self.心跳超时秒, 保留窗口秒=self.保留窗口秒))
            清理列表.extend(self.状态账本.扫描过期租约())
            # 扫描过期租约 刚把一批租约/句柄改成终态，同轮补一次真删。
            清理列表.extend(self.状态账本.回收过期资源行(保留窗口秒=self.保留窗口秒))
            self.清扫次数 += 1
            self.最近清扫 = 清理列表[-20:]
            return 清理列表

    def _循环(self) -> None:
        while not self._停止事件.is_set():
            try:
                self.清扫一次()
            except Exception as 错误:  # 维护失败不得中断网关，但必须留痕
                self.最近错误 = str(错误)
                记录忽略('资源账本维护循环.清扫', 错误)
            finally:
                try:
                    self.状态账本.释放当前线程连接()
                except Exception as 错误:  # 允许忽略，但留痕（哲学第 3 条 2 项）
                    记录忽略('资源账本维护循环.释放连接', 错误)
            self._停止事件.wait(self.间隔秒)

    def 启动(self) -> None:
        """启动后台维护线程（幂等）；首轮清扫立即执行，不阻塞调用方返回。"""
        if self._线程 is not None and self._线程.is_alive():
            return
        self._停止事件.clear()
        self._线程 = threading.Thread(target=self._循环, name="权威状态账本维护", daemon=True)
        self._线程.start()

    def 停止(self, 超时秒: float = 5.0) -> None:
        """停止维护线程并等它退出（幂等）；退出路径必须先停线程再关数据库连接。"""
        self._停止事件.set()
        线程 = self._线程
        self._线程 = None
        if 线程 is not None and 线程.is_alive() and 线程 is not threading.current_thread():
            线程.join(超时秒)

    def 状态快照(self) -> dict[str, Any]:
        return {"运行中": bool(self._线程 and self._线程.is_alive()),
                "间隔秒": self.间隔秒, "心跳超时秒": self.心跳超时秒,
                "保留窗口秒": self.保留窗口秒, "清扫次数": self.清扫次数,
                "最近清扫条数": len(self.最近清扫), "最近错误": self.最近错误}


__all__ = ["资源句柄服务", "资源账本维护循环"]
