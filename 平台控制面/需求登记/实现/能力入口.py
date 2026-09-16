"""需求登记包的实现层：需求治理面写读动作的唯一执行入口（能力实现）。

本模块是 `平台控制面.需求登记` 正式包的能力实现层，包级中文入口
（同包 `__init__.py`）的 `注册能力(注册表)` 从这里取实现函数。

分工：
- `需求服务.py`：需求快照/确认状态/装配计划/工作包的**需求语义唯一实现**
  （本次包化只把原平铺文件 `平台控制面/需求登记.py` 逐字迁入，类名与全部
  既有方法不变，仅补一个只读 `查询需求`，不产生第二套实现）；
- 本模块：把需求服务的公开动作包成**统一结果契约**的能力实现，
  负责能力边界上的参数校验、存储目录缺省与统一结果归一。

为什么要有这一层（第 2 条 1 项分层与归属固定）：
- 需求事实属**平台控制面证据域**（`平台状态.需求表` 唯一写入口）；
- 调用方（`统一入口`、`能力反馈` 包、开发工具门禁与视图、网关）**不得 import 实现**，
  只能经唯一能力调用入口按能力 id 调用，实现与本层之间由包级中文入口隔离；
- 存储目录由调用方按部署配置传入（缺省取工程缓存下的平台控制面目录，与
  `平台控制面.平台状态` / `平台控制面.能力反馈` 同口径），本层不硬编码任何调用方的缓存根。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from 平台控制面.需求登记.需求服务 import 需求登记
from 平台控制面.需求登记.需求错误码 import 稳定错误码映射

默认存储目录 = "工程缓存/平台控制面"
来源名称 = "需求登记"

# 落工作包=true 时，`工作包表` 每一项必须给齐的字段（与 需求服务.保存工作包 的入参一一对应）。
工作包必需键 = ("波次", "说明", "输入快照", "允许修改路径", "能力占用", "资源预算", "验收命令")

# 存储目录 → 需求服务（同目录复用同一实例，避免每次调用重建状态库连接）。
_服务表: dict[str, 需求登记] = {}


def _取服务(存储目录: str) -> 需求登记:
    """按存储目录取需求服务；目录为空即抛错（由能力实现转 参数不合法）。"""
    目录 = str(存储目录 or 默认存储目录).strip()
    if not 目录:
        raise ValueError("存储目录不能为空")
    服务 = _服务表.get(目录)
    if 服务 is None:
        from 平台控制面.平台状态.状态存储 import 平台状态

        服务 = 需求登记(平台状态(Path(目录), 项目id="平台控制面"))
        _服务表[目录] = 服务
    return 服务


def _取服务或失败(存储目录: str) -> tuple[Any, Any]:
    """取需求服务；参数类不可用返回 (None, 失败结果)，其余异常交给调用方按域错误码处理。"""
    from 公共契约.基础类型.结果类型 import 结果

    try:
        return _取服务(存储目录), None
    except (TypeError, ValueError, OSError) as 错误:
        return None, 结果.失败("参数不合法", f"存储目录不合法：{错误}", 来源=来源名称)


def 登记需求(目标: str, 非目标: str = "", 输入: dict[str, Any] | None = None,
            输出: dict[str, Any] | None = None, 权限: dict[str, Any] | None = None,
            调用者: str = "", 角色: str = "", 存储目录: str = "") -> Any:
    """登记一条需求（不可变快照的唯一写入口，变化生成新版本、不覆盖旧快照）。"""
    from 公共契约.基础类型.结果类型 import 结果

    if not isinstance(目标, str) or not 目标.strip():
        return 结果.失败("参数不合法", "目标必须是非空文本", 来源=来源名称)
    for 名称, 值 in (("非目标", 非目标), ("调用者", 调用者), ("角色", 角色)):
        if not isinstance(值, str):
            return 结果.失败("参数不合法", f"{名称} 必须是文本", 来源=来源名称)
    for 名称, 值 in (("输入", 输入), ("输出", 输出), ("权限", 权限)):
        if 值 is not None and not isinstance(值, dict):
            return 结果.失败("参数不合法", f"{名称} 必须是 JSON 对象", 来源=来源名称)
    服务, 失败 = _取服务或失败(存储目录)
    if 服务 is None:
        return 失败
    try:
        快照 = 服务.登记需求(目标=目标, 非目标=非目标, 输入=输入, 输出=输出, 权限=权限,
                            调用者=调用者, 角色=角色)
    except sqlite3.Error as 错误:
        return 结果.失败("需求登记失败", f"需求快照写入失败：{错误}", 来源=来源名称)
    except (TypeError, ValueError) as 错误:
        return 结果.失败("参数不合法", f"需求快照参数不合法：{错误}", 来源=来源名称)
    return 结果.成功结果(快照)


def 确认需求(需求id: str, 调用者: str = "", 角色: str = "", 存储目录: str = "") -> Any:
    """确认一条需求快照；未确认前正式开发与发布门禁必须失败（幂等：重复确认返回已确认）。"""
    from 公共契约.基础类型.结果类型 import 结果

    if not isinstance(需求id, str) or not 需求id.strip():
        return 结果.失败("需求id不能为空",
                        "需求id不能为空（平台稳定码 REQUIREMENT_REQUIRED：空需求id一律阻断）",
                        来源=来源名称, 详情={"稳定错误码": "REQUIREMENT_REQUIRED"})
    for 名称, 值 in (("调用者", 调用者), ("角色", 角色)):
        if not isinstance(值, str):
            return 结果.失败("参数不合法", f"{名称} 必须是文本", 来源=来源名称)
    服务, 失败 = _取服务或失败(存储目录)
    if 服务 is None:
        return 失败
    try:
        成功, 消息 = 服务.确认需求(需求id=需求id, 调用者=调用者, 角色=角色)
    except sqlite3.Error as 错误:
        # 写入失败即「确认状态没落上」→ 按未确认 fail-safe 阻断（稳定码与拆表前同码）。
        return 结果.失败("需求未确认", f"需求确认写入失败：{错误}", 来源=来源名称,
                        详情={"稳定错误码": "REQUIREMENT_UNCONFIRMED", "需求id": 需求id})
    if not 成功:
        return 结果.失败("需求不存在", f"{消息}（平台稳定码 REQUIREMENT_NOT_FOUND："
                        "需求快照查不到，不能确认）",
                        来源=来源名称,
                        详情={"稳定错误码": "REQUIREMENT_NOT_FOUND", "需求id": 需求id})
    return 结果.成功结果({"需求id": 需求id, "是否已确认": True, "消息": 消息})


def 查询需求(需求id: str = "", 限制: int = 50, 包含工作包: bool = False,
            存储目录: str = "") -> Any:
    """查询需求（只读）：给 需求id 单查确认状态，留空按创建顺序列表，可带该需求的工作包。"""
    from 公共契约.基础类型.结果类型 import 结果

    if 需求id is None or not isinstance(需求id, str):
        return 结果.失败("参数不合法", "需求id 必须是文本（留空表示列表查询）", 来源=来源名称)
    if not isinstance(限制, int) or isinstance(限制, bool) or not 1 <= 限制 <= 1000:
        return 结果.失败("参数不合法", "限制必须是 1 到 1000 的整数", 来源=来源名称)
    if not isinstance(包含工作包, bool):
        return 结果.失败("参数不合法", "包含工作包 必须是布尔", 来源=来源名称)
    服务, 失败 = _取服务或失败(存储目录)
    if 服务 is None:
        return 失败
    标识 = 需求id.strip()
    try:
        需求表 = 服务.查询需求(标识)[:限制]
        工作包表 = 服务.查询工作包(标识)[:限制] if 包含工作包 else []
    except sqlite3.Error as 错误:
        return 结果.失败("需求查询失败", f"需求查询失败：{错误}", 来源=来源名称)
    单条 = 需求表[0] if (标识 and 需求表) else None
    return 结果.成功结果({
        "需求表": 需求表,
        "数量": len(需求表),
        "需求": 单条,
        "是否命中": 单条 is not None,
        "是否已确认": bool(单条 and 单条.get("确认状态") == "已确认"),
        "工作包表": 工作包表,
    })


def 需求已确认(需求id: str, 存储目录: str = "") -> Any:
    """只读判定需求是否已确认（闸门口径与 确认需求 逐字一致，幂等、无副作用）。"""
    from 公共契约.基础类型.结果类型 import 结果

    if not isinstance(需求id, str) or not 需求id.strip():
        return 结果.失败("需求id不能为空",
                        "需求id不能为空（平台稳定码 REQUIREMENT_REQUIRED：空需求id一律阻断）",
                        来源=来源名称, 详情={"稳定错误码": "REQUIREMENT_REQUIRED"})
    服务, 失败 = _取服务或失败(存储目录)
    if 服务 is None:
        return 失败
    读取失败 = False
    try:
        记录表 = 服务.查询需求(需求id.strip())
    except sqlite3.Error:
        # 闸门 fail-safe：读不到一律按「未确认」阻断（与 确认需求 的 sqlite 分支同口径），
        # 绝不在读取失败时假装已确认。
        读取失败 = True
        记录表 = []
    命中 = 记录表[0] if 记录表 else None
    if 命中 is None and not 读取失败:
        # 干净读、无记录 → 目标快照查不到（稳定码 REQUIREMENT_NOT_FOUND，
        # 与 统一入口.py:184 的「需求不存在」逐字同词）。
        return 结果.失败("需求不存在",
                        f"{需求id} 查不到需求快照（平台稳定码 REQUIREMENT_NOT_FOUND："
                        "不存在一律阻断开发与发布放行）",
                        来源=来源名称,
                        详情={"稳定错误码": "REQUIREMENT_NOT_FOUND", "需求id": 需求id})
    if 读取失败 or (命中.get("确认状态") if 命中 else "") != "已确认":
        # 需求存在但未确认（或读取失败 fail-safe）→ 稳定码 REQUIREMENT_UNCONFIRMED，
        # 与 统一入口.py:186/235/389 的「需求未确认」逐字同词。
        return 结果.失败("需求未确认",
                        f"{需求id} 未确认（平台稳定码 REQUIREMENT_UNCONFIRMED："
                        "未确认一律阻断开发与发布放行）",
                        来源=来源名称,
                        详情={"稳定错误码": "REQUIREMENT_UNCONFIRMED", "需求id": 需求id})
    return 结果.成功结果({"需求id": 需求id, "是否已确认": True, "消息": "需求已确认"})


def 保存工作包(需求id: str, 波次: int, 说明: str, 输入快照: dict[str, Any],
              允许修改路径: list[str], 能力占用: list[str], 资源预算: dict[str, Any],
              验收命令: str, 存储目录: str = "") -> Any:
    """把一条工作包落 平台状态.工作包 表（唯一写入口仍是 需求服务.保存工作包）。"""
    from 公共契约.基础类型.结果类型 import 结果

    if not isinstance(需求id, str) or not 需求id.strip():
        return 结果.失败("需求id不能为空",
                        "需求id不能为空（平台稳定码 REQUIREMENT_REQUIRED：空需求id一律阻断）",
                        来源=来源名称, 详情={"稳定错误码": "REQUIREMENT_REQUIRED"})
    if not isinstance(波次, int) or isinstance(波次, bool):
        return 结果.失败("参数不合法", "波次 必须是整数", 来源=来源名称)
    for 名称, 值 in (("说明", 说明), ("验收命令", 验收命令)):
        if not isinstance(值, str):
            return 结果.失败("参数不合法", f"{名称} 必须是文本", 来源=来源名称)
    for 名称, 值 in (("输入快照", 输入快照), ("资源预算", 资源预算)):
        if not isinstance(值, dict):
            return 结果.失败("参数不合法", f"{名称} 必须是 JSON 对象", 来源=来源名称)
    for 名称, 值 in (("允许修改路径", 允许修改路径), ("能力占用", 能力占用)):
        if not isinstance(值, list):
            return 结果.失败("参数不合法", f"{名称} 必须是列表", 来源=来源名称)
    服务, 失败 = _取服务或失败(存储目录)
    if 服务 is None:
        return 失败
    try:
        记录 = 服务.保存工作包(需求id=需求id, 波次=波次, 说明=说明, 输入快照=输入快照,
                             允许修改路径=允许修改路径, 能力占用=能力占用,
                             资源预算=资源预算, 验收命令=验收命令)
    except sqlite3.Error as 错误:
        return 结果.失败("工作包登记失败", f"工作包写入失败：{错误}", 来源=来源名称)
    except (TypeError, ValueError) as 错误:
        return 结果.失败("参数不合法", f"工作包参数不合法：{错误}", 来源=来源名称)
    return 结果.成功结果({键: 记录[键] for 键 in ("工作包id", "需求id", "波次", "说明", "状态")})


def 查询工作包(需求id: str = "", 限制: int = 50, 存储目录: str = "") -> Any:
    """查询工作包（只读）：给 需求id 过滤，留空列全部，按 限制 截断。"""
    from 公共契约.基础类型.结果类型 import 结果

    if 需求id is None or not isinstance(需求id, str):
        return 结果.失败("参数不合法", "需求id 必须是文本（留空表示列全部）", 来源=来源名称)
    if not isinstance(限制, int) or isinstance(限制, bool) or not 1 <= 限制 <= 1000:
        return 结果.失败("参数不合法", "限制必须是 1 到 1000 的整数", 来源=来源名称)
    服务, 失败 = _取服务或失败(存储目录)
    if 服务 is None:
        return 失败
    try:
        工作包表 = 服务.查询工作包(需求id.strip())[:限制]
    except sqlite3.Error as 错误:
        return 结果.失败("需求查询失败", f"工作包查询失败：{错误}", 来源=来源名称)
    return 结果.成功结果({"工作包表": 工作包表, "数量": len(工作包表)})


def 登记装配计划(需求id: str, 能力搜索结果: list[Any] | None = None,
                工作包表: list[Any] | None = None, 落工作包: bool = False,
                存储目录: str = "") -> Any:
    """生成并落盘装配计划（依赖 DAG + 并行波次）；可选同时把工作包逐项落盘。"""
    from 公共契约.基础类型.结果类型 import 结果

    if not isinstance(需求id, str) or not 需求id.strip():
        return 结果.失败("需求id不能为空",
                        "需求id不能为空（平台稳定码 REQUIREMENT_REQUIRED：空需求id一律阻断）",
                        来源=来源名称, 详情={"稳定错误码": "REQUIREMENT_REQUIRED"})
    候选 = [] if 能力搜索结果 is None else 能力搜索结果
    包表 = [] if 工作包表 is None else 工作包表
    if not isinstance(候选, list):
        return 结果.失败("参数不合法", "能力搜索结果 必须是列表", 来源=来源名称)
    if not isinstance(包表, list):
        return 结果.失败("参数不合法", "工作包表 必须是列表", 来源=来源名称)
    if not isinstance(落工作包, bool):
        return 结果.失败("参数不合法", "落工作包 必须是布尔", 来源=来源名称)
    # 工作包表项形状先校验（收敛前该入参直接抛 AttributeError：能力边界改为稳定错误码）：
    # 装配计划的波次表按 工作包id 生成，逐项必须是带 工作包id 的对象。
    for 序号, 包 in enumerate(包表):
        if not isinstance(包, dict):
            return 结果.失败("参数不合法", f"工作包表第 {序号 + 1} 项必须是 JSON 对象",
                            来源=来源名称)
        if not str(包.get("工作包id", "")).strip():
            return 结果.失败("参数不合法",
                            f"工作包表第 {序号 + 1} 项缺少 工作包id（装配计划按它生成波次表）",
                            来源=来源名称)
        if "波次" in 包 and (not isinstance(包["波次"], int) or isinstance(包["波次"], bool)):
            return 结果.失败("参数不合法", f"工作包表第 {序号 + 1} 项的 波次 必须是整数",
                            来源=来源名称)
        if "能力占用" in 包 and not isinstance(包["能力占用"], list):
            return 结果.失败("参数不合法", f"工作包表第 {序号 + 1} 项的 能力占用 必须是列表",
                            来源=来源名称)
    if 落工作包:
        # 先把全部工作包的形状校验完，再动任何写（避免"计划已落、工作包半落"）。
        for 序号, 包 in enumerate(包表):
            if not isinstance(包, dict):
                return 结果.失败("参数不合法", f"工作包表第 {序号 + 1} 项必须是 JSON 对象",
                                来源=来源名称)
            缺 = [键 for 键 in 工作包必需键 if 键 not in 包]
            if 缺:
                return 结果.失败("参数不合法",
                                f"工作包表第 {序号 + 1} 项缺少字段 {缺}"
                                "（落工作包=true 时每项必须给齐 波次/说明/输入快照/"
                                "允许修改路径/能力占用/资源预算/验收命令）",
                                来源=来源名称)
    服务, 失败 = _取服务或失败(存储目录)
    if 服务 is None:
        return 失败
    try:
        计划 = 服务.生成装配计划(需求id=需求id, 能力搜索结果=候选, 工作包表=包表)
    except ValueError as 错误:
        return 结果.失败("装配计划生成失败", str(错误), 来源=来源名称)
    except sqlite3.Error as 错误:
        return 结果.失败("装配计划生成失败", f"装配计划落盘失败：{错误}", 来源=来源名称)
    已落工作包数 = 0
    if 落工作包:
        try:
            for 包 in 包表:
                服务.保存工作包(需求id=需求id, 波次=int(包["波次"]), 说明=str(包["说明"]),
                              输入快照=dict(包["输入快照"]), 允许修改路径=list(包["允许修改路径"]),
                              能力占用=list(包["能力占用"]), 资源预算=dict(包["资源预算"]),
                              验收命令=str(包["验收命令"]))
                已落工作包数 += 1
        except (sqlite3.Error, TypeError, ValueError) as 错误:
            return 结果.失败("工作包登记失败", f"装配计划已落盘、工作包落盘失败：{错误}",
                            来源=来源名称)
    return 结果.成功结果({"装配计划": 计划, "波次数": len(计划.get("波次", {})),
                        "已落工作包数": 已落工作包数})
