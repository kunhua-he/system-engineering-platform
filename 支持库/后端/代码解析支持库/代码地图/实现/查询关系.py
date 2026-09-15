"""代码地图 · 查询关系：只读检索 edges 表，产出某节点的出边/入边事实。

底座只回答「这个节点连到谁 / 谁连到它」——`方向` 参数化出边/入边/双向，
关系种类可按 kinds 表收窄；不判调用链相关性、不拼源码、不做爆炸半径评分。
关系种类与方向取值均 fail-closed：不认识的值直接 `参数不合法`。
"""

from __future__ import annotations

import sqlite3

from 公共契约.基础类型.结果类型 import 结果
from 支持库.后端.代码解析支持库.代码地图.实现.参数口径 import (
    参数错误, 取枚举, 取整数, 取列表, 取文本, 模糊值,
)
from 支持库.后端.代码解析支持库.代码地图.实现.只读连接 import (
    关闭代码地图, 打开代码地图, 来源,
)
from 支持库.后端.代码解析支持库.代码地图.实现.查询节点 import _节点字典

方向表 = ("出边", "入边", "双向")
关系种类表 = ("contains", "calls", "imports", "instantiates", "references", "extends")
最大条数上限 = 500

对端列 = ("n.id AS 对方节点id, n.kind AS 对方种类, n.name AS 对方名称, "
         "n.file_path AS 对方文件路径, n.start_line AS 对方起始行")
节点列 = ("id AS 节点id, kind AS 种类, name AS 名称, qualified_name AS 限定名, "
         "file_path AS 文件路径, language AS 语言, start_line AS 起始行, "
         "end_line AS 结束行, is_exported AS 是否导出, signature AS 签名")


def 查询关系(*, 代码地图路径: str = "", 节点id: str = "", 节点名称: str = "",
             文件路径: str = "", 方向: str = "出边",
             关系种类: list | None = None, 最大条数: int = 100) -> 结果:
    """查某节点的出边/入边关系事实（必填参数在实现内校验：进程内调用与 HTTP 同口径）。"""
    try:
        取值 = 取文本("代码地图路径", 代码地图路径, 必填=True)
        起始id = 取文本("节点id", 节点id, 必填=False)
        起始名称 = 取文本("节点名称", 节点名称, 必填=False)
        路径限定 = 取文本("文件路径", 文件路径, 必填=False)
        取值方向 = 取枚举("方向", 方向, 允许值=方向表, 默认="出边")
        种类表 = 取列表("关系种类", 关系种类, 允许值=关系种类表)
        条数上限 = 取整数("最大条数", 最大条数, 默认=100, 最小=1, 最大=最大条数上限)
        if not 起始id and not 起始名称:
            raise 参数错误("缺少必填参数 节点id 与 节点名称 至少给一个")
    except 参数错误 as 错误:
        return 结果.失败(错误.错误码, 错误.说明, 来源=来源)
    连接结果 = 打开代码地图(取值)
    if not 连接结果.成功:
        return 连接结果
    连接 = 连接结果.值
    try:
        起始节点 = _定位节点(连接, 起始id, 起始名称, 路径限定)
        主体, 参数表 = _构造主体(起始节点["节点id"], 取值方向, 种类表)
        命中数 = 连接.execute(f"SELECT COUNT(*) FROM ({主体})", 参数表).fetchone()[0]
        行表 = 连接.execute(
            f"{主体} ORDER BY 对方文件路径, 对方起始行, 对方名称 LIMIT ?",
            参数表 + [条数上限],
        ).fetchall()
    except 参数错误 as 错误:
        return 结果.失败(错误.错误码, 错误.说明, 来源=来源)
    except sqlite3.Error as 错误:
        return 结果.失败("查询失败", f"代码地图查询关系失败: {错误}", 来源=来源)
    except Exception as 错误:  # 统一结果铁律：实现不外抛，真实原因原样回带
        return 结果.失败("查询失败", f"代码地图查询关系异常: {错误}", 来源=来源)
    finally:
        关闭代码地图(连接)
    return 结果.成功结果({
        "代码地图路径": 取值,
        "方向": 取值方向,
        "起始节点": 起始节点,
        "命中数": 命中数,
        "已截断": 命中数 > len(行表),
        "关系列表": [_节点字典(行) for 行 in 行表],
    })


def _定位节点(连接: sqlite3.Connection, 节点id: str, 节点名称: str,
              文件路径: str) -> dict:
    """定位起始节点：节点id 精确命中；否则按名称（可加文件路径）唯一命中。"""
    if 节点id:
        行 = 连接.execute(
            f"SELECT {节点列} FROM nodes WHERE id = ?", (节点id,)
        ).fetchone()
        if 行 is None:
            raise 参数错误(f"参数 节点id 指向的节点不存在: {节点id}")
        return _节点字典(行)
    if 文件路径:
        行表 = 连接.execute(
            f"SELECT {节点列} FROM nodes WHERE name = ? AND file_path LIKE ? ESCAPE '\\'",
            (节点名称, 模糊值(文件路径)),
        ).fetchall()
    else:
        行表 = 连接.execute(
            f"SELECT {节点列} FROM nodes WHERE name = ?", (节点名称,)
        ).fetchall()
    if not 行表:
        raise 参数错误(f"参数 节点名称 未命中任何节点: {节点名称}")
    if len(行表) > 1:
        候选 = "、".join(sorted(行["文件路径"] for 行 in 行表)[:5])
        raise 参数错误(f"参数 节点名称 命中 {len(行表)} 个节点（{候选}），"
                       "请改用 节点id 或补充 文件路径")
    return dict(行表[0])


def _构造主体(起始id: str, 方向: str, 种类表: list[str]) -> tuple[str, list]:
    """构造关系查询主体（含 方向 字面列；参数化，不做字符串拼接）。"""
    种类条件 = f" AND e.kind IN ({', '.join('?' * len(种类表))})" if 种类表 else ""
    出边段 = (f"SELECT '出边' AS 方向, e.kind AS 关系种类, e.line AS 行号, {对端列} "
             f"FROM edges e JOIN nodes n ON n.id = e.target "
             f"WHERE e.source = ?{种类条件}")
    入边段 = (f"SELECT '入边' AS 方向, e.kind AS 关系种类, e.line AS 行号, {对端列} "
             f"FROM edges e JOIN nodes n ON n.id = e.source "
             f"WHERE e.target = ?{种类条件}")
    if 方向 == "出边":
        return 出边段, [起始id] + 种类表
    if 方向 == "入边":
        return 入边段, [起始id] + 种类表
    return (f"{出边段} UNION ALL {入边段}",
            [起始id] + 种类表 + [起始id] + 种类表)
