"""SQLite 数据库提供者：连接、查询、事务及底座运行态统一访问。"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from 公共契约.基础类型.结果类型 import 结果
from 公共契约.诊断.忽略记录 import 记录忽略

来源 = "SQLite数据库提供者"
错误码_参数不合法 = "参数不合法"
错误码_提供者不可用 = "提供者不可用"
错误码_连接失败 = "连接失败"
错误码_查询失败 = "查询失败"
错误码_事务失败 = "事务失败"


def 压缩数据库(数据库路径: str = None, 超时秒: float = 30) -> 结果:
    """压缩 SQLite 数据库文件并回收空闲页（VACUUM），返回压缩前后字节与释放量。

    为什么单列能力：VACUUM **不能在事务内执行**，而本库其余写能力都跑在显式事务里，
    调用方无法用它们完成压缩；"缺什么补什么"——缺的原子能力就补进对应的库。

    连接以**自动提交模式**（isolation_level=None）打开，只执行 VACUUM，不改业务数据。
    """
    路径 = _校验路径(数据库路径)
    if 路径 is None:
        return _失败(错误码_参数不合法, "数据库路径必须是非空文本")
    if (问题 := _校验超时(超时秒)):
        return _失败(错误码_参数不合法, 问题)
    文件 = Path(路径)
    if not 文件.is_file():
        return _失败(错误码_参数不合法, f"数据库文件不存在: {文件.name}")
    压缩前 = 文件.stat().st_size
    连接 = None
    try:
        连接 = sqlite3.connect(路径, timeout=float(超时秒), isolation_level=None)
        连接.execute("VACUUM")
    except sqlite3.Error as 错误:
        return _失败(错误码_事务失败, f"压缩失败: {错误}", 可重试=True)
    finally:
        if 连接 is not None:
            try:
                连接.close()
            except sqlite3.Error as 错误:
                记录忽略("SQLite数据库.压缩数据库.关闭连接", 错误)
    压缩后 = 文件.stat().st_size
    return 结果.成功结果({
        "数据库路径": 路径, "压缩前字节": 压缩前, "压缩后字节": 压缩后,
        "释放字节": max(压缩前 - 压缩后, 0),
    })


def _失败(错误码: str, 说明: str, *, 可重试: bool = False) -> 结果:
    return 结果.失败(错误码, 说明, 来源=来源, 可重试=可重试)


def _校验路径(数据库路径: Any) -> str | None:
    if not isinstance(数据库路径, str) or not 数据库路径.strip():
        return None
    return str(Path(数据库路径).expanduser())


def _校验超时(超时秒: Any) -> str | None:
    if not isinstance(超时秒, (int, float)) or isinstance(超时秒, bool) or 超时秒 <= 0:
        return "超时秒必须是正数"
    return None


def _打开(数据库路径: str, 超时秒: float) -> sqlite3.Connection:
    路径 = Path(数据库路径)
    路径.parent.mkdir(parents=True, exist_ok=True)
    连接对象 = sqlite3.connect(str(路径), timeout=float(超时秒))
    连接对象.execute("PRAGMA busy_timeout = 5000")
    连接对象.execute("PRAGMA journal_mode = WAL")
    连接对象.execute("PRAGMA synchronous = NORMAL")
    return 连接对象


def 连接(数据库路径: str, 超时秒: float = 10) -> 结果:
    """真实打开 SQLite 数据库并完成基础连接探针，随后关闭连接。"""
    路径 = _校验路径(数据库路径)
    if 路径 is None:
        return _失败(错误码_参数不合法, "数据库路径必须是非空文本")
    if (问题 := _校验超时(超时秒)):
        return _失败(错误码_参数不合法, 问题)
    连接对象 = None
    try:
        连接对象 = _打开(路径, float(超时秒))
        连接对象.execute("SELECT 1").fetchone()
        return 结果.成功结果({"已连接": True, "数据库路径": 路径})
    except sqlite3.Error as 错误:
        return _失败(错误码_连接失败, f"SQLite 数据库连接失败：{错误}", 可重试=True)
    finally:
        if 连接对象 is not None:
            连接对象.close()


def 查询(数据库路径: str, SQL: str, 参数: list | tuple | None = None,
         超时秒: float = 30) -> 结果:
    """执行只读查询，返回列名到值的行列表。"""
    路径 = _校验路径(数据库路径)
    if 路径 is None:
        return _失败(错误码_参数不合法, "数据库路径必须是非空文本")
    if not isinstance(SQL, str) or not SQL.strip():
        return _失败(错误码_参数不合法, "SQL 必须是非空文本")
    if 参数 is not None and not isinstance(参数, (list, tuple)):
        return _失败(错误码_参数不合法, "参数必须是列表或元组")
    if (问题 := _校验超时(超时秒)):
        return _失败(错误码_参数不合法, 问题)
    连接对象 = None
    try:
        连接对象 = _打开(路径, float(超时秒))
        游标 = 连接对象.execute(SQL, tuple(参数 or ()))
        列名表 = [描述[0] for 描述 in (游标.description or [])]
        行列表 = [dict(zip(列名表, 行)) for 行 in 游标.fetchall()]
        return 结果.成功结果({"行列表": 行列表})
    except sqlite3.Error as 错误:
        return _失败(错误码_查询失败, f"SQLite 查询失败：{错误}")
    finally:
        if 连接对象 is not None:
            连接对象.close()


def 事务执行(数据库路径: str, SQL列表: list, 超时秒: float = 30) -> 结果:
    """在一个真实事务内执行 SQL 列表；任一失败全部回滚。"""
    路径 = _校验路径(数据库路径)
    if 路径 is None:
        return _失败(错误码_参数不合法, "数据库路径必须是非空文本")
    if (问题 := _校验超时(超时秒)):
        return _失败(错误码_参数不合法, 问题)
    if not isinstance(SQL列表, list) or not SQL列表:
        return _失败(错误码_参数不合法, "SQL列表 必须是非空列表")
    if any(not isinstance(SQL, str) or not SQL.strip() for SQL in SQL列表):
        return _失败(错误码_参数不合法, "SQL列表 中每项必须是非空文本")
    连接对象 = None
    try:
        连接对象 = _打开(路径, float(超时秒))
        连接对象.execute("BEGIN IMMEDIATE")
        for SQL in SQL列表:
            连接对象.execute(SQL)
        连接对象.commit()
        return 结果.成功结果({"已提交": True, "执行数": len(SQL列表)})
    except sqlite3.Error as 错误:
        if 连接对象 is not None:
            连接对象.rollback()
        return _失败(错误码_事务失败, f"SQLite 事务失败，已回滚：{错误}")
    finally:
        if 连接对象 is not None:
            连接对象.close()


# 运行态表按真实文件字段保留专用列，完整原始记录同时写入 载荷 JSON 文本。
#
# 域清单只保留**有真实生产写入侧**的运行态（2026-09-15 审计删域；成因是对本字典 `全量遍历`
# 建表，`打开运行库即建表` 把没人写的域也一并建出来，表存在 ≠ 有人在写）：
# - `会话`：写入侧在 `大语言模型支持库.会话存储.db`（专用库）；
# - `检查点索引`：写入侧在 `检查点.db`（专用库）；
# - `缓存索引`：写入侧在 `大语言模型支持库.嵌入缓存.db`（专用库）；
# - `发布`：写入侧在平台控制面自己的权威状态库（`平台控制面/平台状态.py` 的 `发布` 表），同名双义。
# 保留 `灰度状态`：已接线（`运行核心/加载器/版本系统/灰度指标.py` 读写），0 行只是尚未发生灰度发布。
运行库表定义 = {
    "任务": {
        "字段": ["任务id", "能力id", "请求id", "项目id", "用户id", "进度", "错误码", "错误说明", "完成时间", "取消标记"],
        "索引": ["状态", "能力id", "请求id", "项目id", "创建时间"],
    },
    "作业": {
        "字段": ["作业id", "工具", "开工id", "错误码", "错误说明", "开始时间", "完成时间", "取消标记", "结果已截断"],
        "索引": ["状态", "工具", "开工id", "创建时间"],
    },
    "协作状态": {
        "字段": ["work_id", "任务", "角色", "worktree路径", "允许路径", "基线提交", "代码指纹", "parent_work_id", "子任务列表", "生命周期", "登记时间", "关闭原因", "收口结论", "关闭时间"],
        "索引": ["状态", "生命周期", "parent_work_id", "角色", "创建时间"],
    },
    "能力占用": {
        "字段": ["能力id", "提供包id", "开工id", "占用时间"],
        "索引": ["状态", "能力id", "提供包id", "开工id", "创建时间"],
    },
    "灰度观测": {
        "字段": ["时间", "能力id", "版本", "成功", "耗时毫秒", "超时"],
        "索引": ["能力id", "版本"],
    },
    "灰度状态": {
        "字段": ["灰度比例", "观察窗口秒", "触发回滚原因"],
        "索引": ["更新时间"],
    },
}
运行库主键字段 = {
    "任务": "任务id", "作业": "作业id", "协作状态": "work_id", "能力占用": "能力id",
    "灰度观测": "观测id", "灰度状态": "键",
}


def _现在() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _标识符(名称: str) -> str:
    return '"' + 名称.replace('"', '""') + '"'


def _创建运行库表(连接对象: sqlite3.Connection) -> None:
    """在已打开连接上幂等创建六个运行态域表及高频索引。

    只建 `运行库表定义` 里的域；删域后本函数**不会**删除已有库里的旧表（见模块注释与审计落点清单）。
    """
    公共字段 = [
        '"id" TEXT PRIMARY KEY', '"创建时间" TEXT NOT NULL',
        '"更新时间" TEXT NOT NULL', '"状态" TEXT NOT NULL',
        '"载荷" TEXT NOT NULL',
    ]
    for 域, 定义 in 运行库表定义.items():
        字段 = 公共字段[:]
        for 名称 in 定义["字段"]:
            # 数值型字段也要落真实数值类型：TEXT 列会让读到的 "0.25" 变成文本（实测踩坑）。
            类型 = "REAL" if 名称 in {"进度", "登记时间", "关闭时间", "灰度比例", "耗时毫秒",
                                     "观察窗口秒", "请求总数", "成功数", "失败数", "超时数"} else "TEXT"
            # 逻辑型字段必须落真正的整数 0/1：TEXT 存 "0"/"1" 会让 Python 端 `if "0"` 判成真，
            # 统计口径（成功/失败/超时、取消标记）会整体算错（实测踩坑 2026-09-15）。
            if 名称 in {"取消标记", "结果已截断", "成功", "超时"}:
                类型 = "INTEGER"
            字段.append(f"{_标识符(名称)} {类型}")
        连接对象.execute(
            f"CREATE TABLE IF NOT EXISTS {_标识符(域)} ({', '.join(字段)})")
        for 列名 in 定义["索引"]:
            索引名 = f"索引_{域}_{列名}"
            连接对象.execute(
                f"CREATE INDEX IF NOT EXISTS {_标识符(索引名)} "
                f"ON {_标识符(域)} ({_标识符(列名)})")


def 初始化运行数据库(数据库路径: str, 超时秒: float = 30) -> 结果:
    """创建底座运行库六个域表；重复初始化幂等。"""
    路径 = _校验路径(数据库路径)
    if 路径 is None:
        return _失败(错误码_参数不合法, "数据库路径必须是非空文本")
    if (问题 := _校验超时(超时秒)):
        return _失败(错误码_参数不合法, 问题)
    连接对象 = None
    try:
        连接对象 = _打开(路径, float(超时秒))
        连接对象.execute("BEGIN IMMEDIATE")
        _创建运行库表(连接对象)
        连接对象.commit()
        return 结果.成功结果({"数据库路径": 路径, "表清单": list(运行库表定义)})
    except sqlite3.Error as 错误:
        if 连接对象 is not None:
            连接对象.rollback()
        return _失败(错误码_事务失败, f"运行数据库初始化失败，已回滚：{错误}")
    finally:
        if 连接对象 is not None:
            连接对象.close()


def _运行库参数(数据库路径: str, 域: str, 超时秒: float) -> tuple[str | None, str | None]:
    路径 = _校验路径(数据库路径)
    if 路径 is None:
        return None, "数据库路径必须是非空文本"
    if 域 not in 运行库表定义:
        return None, f"域必须是：{'、'.join(运行库表定义)}"
    if (问题 := _校验超时(超时秒)):
        return None, 问题
    return 路径, None


def _载荷(记录: dict[str, Any]) -> str | None:
    try:
        return json.dumps(记录, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError):
        return None


# 正式运行库不得混入验收/测试标识行。为什么要在写入侧拦（2026-09-15 审计）：
# 一次性验收命令当时直接写了**正式库**（`灰度观测` 留了一行 `验收-灰度-1`），而
# `灰度指标.聚合()` 是「从库重算」，假行会污染任何按表统计的灰度结论，事后也无法与真实数据区分。
# 测试一律用 `tempfile` 临时库（见 `测试中心/运行核心/测试_灰度指标入库.py`）。
测试标识前缀 = ("验收-", "验收_", "测试-", "test-")
测试标识能力前缀 = ("验收", "测试.", "test.")


def _测试标识(记录id: str, 记录: dict[str, Any]) -> str | None:
    """命中验收/测试标识时返回命中的值，未命中返回 None。"""
    if 记录id.startswith(测试标识前缀):
        return 记录id
    能力id = 记录.get("能力id")
    if isinstance(能力id, str) and 能力id.startswith(测试标识能力前缀):
        return 能力id
    return None


def 写入运行态(数据库路径: str, 域: str, 记录: dict[str, Any], 超时秒: float = 30) -> 结果:
    """经唯一 SQLite 入口按域原子写入一条运行态记录，重复 id 采用更新语义。

    拒绝测试标识行（`验收-*` 等）：正式库只装真实运行态，见 `测试标识前缀` 注释。
    """
    路径, 问题 = _运行库参数(数据库路径, 域, 超时秒)
    if 问题:
        return _失败(错误码_参数不合法, 问题)
    if not isinstance(记录, dict):
        return _失败(错误码_参数不合法, "记录必须是字典")
    主键字段 = 运行库主键字段[域]
    记录id = 记录.get("id") or 记录.get(主键字段)
    if not isinstance(记录id, str) or not 记录id.strip():
        return _失败(错误码_参数不合法, f"记录必须提供非空 id 或 {主键字段}")
    if (命中 := _测试标识(记录id, 记录)):
        return _失败(错误码_参数不合法,
                    f"正式运行库不得写入验收/测试标识记录：{命中}"
                    f"（验收测试请用 tempfile 临时库）")
    载荷 = _载荷(记录)
    if 载荷 is None:
        return _失败(错误码_参数不合法, "记录必须可编码为 JSON")
    assert 路径 is not None
    现在 = _现在()
    值表: dict[str, Any] = {"id": 记录id, "创建时间": 记录.get("创建时间") or 现在,
                             "更新时间": 现在, "状态": 记录.get("状态") or "未开始", "载荷": 载荷}
    for 字段 in 运行库表定义[域]["字段"]:
        值表[字段] = 记录.get(字段)
    列表 = list(值表)
    占位 = ",".join("?" for _ in 列表)
    列名 = ",".join(_标识符(列) for 列 in 列表)
    更新 = ",".join(f"{_标识符(列)}=excluded.{_标识符(列)}" for 列 in 列表 if 列 != "id")
    连接对象 = None
    try:
        连接对象 = _打开(路径, float(超时秒))
        _创建运行库表(连接对象)
        连接对象.execute(
            f"INSERT INTO {_标识符(域)} ({列名}) VALUES ({占位}) "
            f"ON CONFLICT({_标识符('id')}) DO UPDATE SET {更新}",
            [值表[列] for 列 in 列表])
        连接对象.commit()
        return 结果.成功结果({"域": 域, "id": 记录id, "已写入": True, "更新时间": 现在})
    except sqlite3.Error as 错误:
        if 连接对象 is not None:
            连接对象.rollback()
        return _失败(错误码_事务失败, f"运行态写入失败，已回滚：{错误}")
    finally:
        if 连接对象 is not None:
            连接对象.close()


def 查询运行态(数据库路径: str, 域: str, 条件: dict[str, Any] | None = None,
             限制: int = 100, 超时秒: float = 30) -> 结果:
    """经唯一 SQLite 入口按域查询运行态；条件仅允许真实表列，避免拼接任意 SQL。"""
    路径, 问题 = _运行库参数(数据库路径, 域, 超时秒)
    if 问题:
        return _失败(错误码_参数不合法, 问题)
    if 条件 is not None and not isinstance(条件, dict):
        return _失败(错误码_参数不合法, "条件必须是字典")
    if isinstance(限制, bool) or not isinstance(限制, int) or not 1 <= 限制 <= 1000:
        return _失败(错误码_参数不合法, "限制必须是 1 到 1000 的整数")
    允许列 = {"id", "创建时间", "更新时间", "状态", "载荷", *运行库表定义[域]["字段"]}
    条件 = 条件 or {}
    if any(列 not in 允许列 for 列 in 条件):
        非法列 = next(列 for 列 in 条件 if 列 not in 允许列)
        return _失败(错误码_参数不合法, f"条件字段不支持：{非法列}")
    assert 路径 is not None
    where = " AND ".join(f"{_标识符(列)} = ?" for 列 in 条件) or "1=1"
    连接对象 = None
    try:
        连接对象 = _打开(路径, float(超时秒))
        _创建运行库表(连接对象)
        游标 = 连接对象.execute(
            f"SELECT * FROM {_标识符(域)} WHERE {where} ORDER BY {_标识符('更新时间')} DESC LIMIT ?",
            [*条件.values(), 限制])
        列名表 = [描述[0] for 描述 in (游标.description or [])]
        行列表 = [dict(zip(列名表, 行)) for 行 in 游标.fetchall()]
        return 结果.成功结果({"域": 域, "行列表": 行列表, "总数": len(行列表)})
    except sqlite3.Error as 错误:
        return _失败(错误码_查询失败, f"运行态查询失败：{错误}")
    finally:
        if 连接对象 is not None:
            连接对象.close()


def 关闭(数据库路径: str, 超时秒: float = 5) -> 结果:
    """关闭能力：连接每次调用结束即释放，返回真实关闭语义。"""
    路径 = _校验路径(数据库路径)
    if 路径 is None:
        return _失败(错误码_参数不合法, "数据库路径必须是非空文本")
    if (问题 := _校验超时(超时秒)):
        return _失败(错误码_参数不合法, 问题)
    return 结果.成功结果({"已关闭": True, "说明": "SQLite 连接随能力调用结束自动释放"})


__all__ = ["连接", "查询", "事务执行", "初始化运行数据库", "写入运行态", "查询运行态", "关闭"]
