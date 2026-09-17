"""平台控制面权威状态存储的对外能力实现（能力边界层）。

本模块是 `平台控制面.平台状态` 正式包的能力实现层：把 `状态存储.平台状态`
（`运行核心.权威状态` 子类，结构 1.4.0）的六服务通用读写与证据账本动作
包成**统一结果契约**的公开能力。

分工：
- `状态存储.py`：权威状态存储本体（连接管理 / 迁移 / 表结构，唯一事实源）。
- 本模块：能力边界参数校验、存储实例按目录缓存、统一结果归一。

为什么要有这一层（第 2 条 1 项分层与归属固定）：
- 权威事实属平台控制面证据域，写入口只有本包；
- 调用方（开发工具门禁、运行核心、网关）**不得 import 实现**，只能经
  唯一能力调用入口按能力 id 调用，包级中文入口（`__init__.py`）负责隔离。
- 存储目录由调用方按部署配置传入（缺省取工程缓存下的平台控制面目录），
  本层不硬编码任何调用方的缓存根。
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from 平台控制面.平台状态.状态存储 import 平台状态
from 公共契约.基础类型.逻辑类型 import 真, 假
from 公共契约.运行时.运行缓存 import 解析运行缓存根

# 存储目录缺省值：经唯一解析器取运行态存储根（源码态 = `<系统根>/工程缓存/平台控制面`，
# 与旧的裸相对值同义；制品态 = 平台受管缓存）。裸相对路径在制品态会把运行态写进制品。
默认存储目录 = str(解析运行缓存根(Path(__file__).resolve().parents[3]) / "平台控制面")
来源名称 = "平台状态"

# 存储实例 → 按 (目录, 项目id) 复用，避免每次调用重建状态库连接。
_状态表: dict[tuple[str, str, str], 平台状态] = {}


def _取状态(存储目录: str, 项目id: str, 所有者: str = ""):
    """按存储目录取平台状态实例；目录为空即明确失败（不隐式兜底）。"""
    from 公共契约.基础类型.结果类型 import 结果

    目录 = str(存储目录 or 默认存储目录).strip()
    if not 目录:
        return None, 结果.失败("参数不合法", "存储目录不能为空", 来源=来源名称)
    键 = (目录, str(项目id), str(所有者))
    状态 = _状态表.get(键)
    if 状态 is not None:
        return 状态, None
    try:
        状态 = 平台状态(目录, 项目id=str(项目id), 所有者=str(所有者))
    except (OSError, ValueError, sqlite3.Error) as 错误:
        return None, 结果.失败("存储目录不可用", f"无法打开平台权威状态库：{错误}",
                              来源=来源名称)
    _状态表[键] = 状态
    return 状态, None


def 读取记录(存储目录: str = "", 表: str = "", 主键列: str = "", 主键值: str = "",
            项目id: str = "") -> Any:
    """读取一条平台权威状态记录（只读）；未命中返回 是否命中=False，不伪造记录。"""
    from 公共契约.基础类型.结果类型 import 结果

    if not 表 or not 主键列 or str(主键值) == "":
        return 结果.失败("参数不合法", "表/主键列/主键值必须给齐", 来源=来源名称)
    状态, 失败 = _取状态(存储目录, 项目id)
    if 状态 is None:
        return 失败
    try:
        记录 = 状态.读取记录(表, 主键列, str(主键值))
    except sqlite3.Error as 错误:
        return 结果.失败("读取记录失败", f"读取 {表} 失败：{错误}", 来源=来源名称)
    if 记录 is None:
        return 结果.成功结果({"记录": None, "是否命中": 假})
    return 结果.成功结果({"记录": 记录, "是否命中": 真})


def 查询记录(存储目录: str = "", 表: str = "", 条件: str = "", 参数: list | None = None,
            限制: int = 200, 项目id: str = "") -> Any:
    """查询平台权威状态记录（只读）；条件留空表示按限制全表取。"""
    from 公共契约.基础类型.结果类型 import 结果

    if not 表:
        return 结果.失败("参数不合法", "表不能为空", 来源=来源名称)
    if not isinstance(限制, int) or isinstance(限制, bool) or not 1 <= 限制 <= 1000:
        return 结果.失败("参数不合法", "限制必须是 1 到 1000 的整数", 来源=来源名称)
    占位符 = tuple(参数) if isinstance(参数, (list, tuple)) else ()
    if not 条件 and 占位符:
        return 结果.失败("参数不合法", "条件为空时不允许携带参数占位符", 来源=来源名称)
    状态, 失败 = _取状态(存储目录, 项目id)
    if 状态 is None:
        return 失败
    try:
        记录表 = 状态.查询记录(表, 条件, 占位符)
    except sqlite3.Error as 错误:
        return 结果.失败("查询记录失败", f"查询 {表} 失败：{错误}", 来源=来源名称)
    结果表 = 记录表[:限制]
    return 结果.成功结果({"记录表": 结果表, "数量": len(结果表)})


def 写入记录(存储目录: str = "", 表: str = "", 记录: dict | None = None,
            主键: str = "id", 项目id: str = "") -> Any:
    """写入一条平台权威状态记录；同主键按字段合并更新（不丢既有字段）。"""
    from 公共契约.基础类型.结果类型 import 结果

    if not 表 or not isinstance(记录, dict) or not 记录:
        return 结果.失败("参数不合法", "表与记录字典必须给齐，记录不能为空", 来源=来源名称)
    if not 主键 or 主键 not in 记录:
        return 结果.失败("参数不合法", f"记录必须包含主键字段 {主键}", 来源=来源名称)
    状态, 失败 = _取状态(存储目录, 项目id)
    if 状态 is None:
        return 失败
    try:
        状态.写入记录(表, 记录, 主键)
        写回 = 状态.读取记录(表, 主键, str(记录[主键]))
    except sqlite3.Error as 错误:
        return 结果.失败("写入记录失败", f"写入 {表} 失败：{错误}", 来源=来源名称)
    return 结果.成功结果({"记录": 写回})


def 追加证据(存储目录: str = "", 类型: str = "", 主题: str = "", 内容: dict | None = None,
            操作id: str = "", 调用者: str = "", 角色: str = "", 结果: str = "",
            错误码: str = "") -> Any:
    """向平台证据账本追加一条证据（仅追加，旧证据不可覆盖）。"""
    from 公共契约.基础类型.结果类型 import 结果 as 结果类型

    if not 类型 or not 主题 or not isinstance(内容, dict):
        return 结果类型.失败("参数不合法", "类型/主题/内容必须给齐，内容必须是 JSON 对象",
                            来源=来源名称)
    状态, 失败 = _取状态(存储目录, "")
    if 状态 is None:
        return 失败
    try:
        证据id = 状态.追加证据(类型=类型, 主题=主题, 内容=内容, 操作id=操作id,
                            调用者=调用者, 角色=角色, 结果=结果, 错误码=错误码)
        证据表 = 状态.查询证据(主题=主题, 类型=类型, 限制=10)
    except sqlite3.Error as 错误:
        return 结果类型.失败("写入记录失败", f"追加证据失败：{错误}", 来源=来源名称)
    命中 = next((证据 for 证据 in 证据表 if 证据["证据id"] == 证据id), None)
    return 结果类型.成功结果({"证据id": 证据id, "哈希": (命中 or {}).get("哈希", "")})


def 查询证据(存储目录: str = "", 主题: str = "", 类型: str = "", 限制: int = 50,
            项目id: str = "") -> Any:
    """查询平台证据账本（只读）；空过滤条件表示不限。"""
    from 公共契约.基础类型.结果类型 import 结果

    if not isinstance(限制, int) or isinstance(限制, bool) or not 1 <= 限制 <= 500:
        return 结果.失败("参数不合法", "限制必须是 1 到 500 的整数", 来源=来源名称)
    状态, 失败 = _取状态(存储目录, 项目id)
    if 状态 is None:
        return 失败
    try:
        证据表 = 状态.查询证据(主题=主题, 类型=类型, 限制=限制)
    except sqlite3.Error as 错误:
        return 结果.失败("查询证据失败", f"查询证据失败：{错误}", 来源=来源名称)
    return 结果.成功结果({"证据表": 证据表, "数量": len(证据表)})
