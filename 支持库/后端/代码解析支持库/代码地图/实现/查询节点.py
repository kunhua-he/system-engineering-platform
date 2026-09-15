"""代码地图 · 查询节点：只读检索 nodes 表，产出结构化符号事实。

底座只回答「代码地图里有哪些节点满足条件」——名称/限定名/路径/全文四类匹配
经 `模式` 参数化，种类/文件/语言做收窄；不渲染文本、不读源码、不判相关性。
命中为空是**成功结果**（`节点列表` 为空、`命中数` 为 0），不是错误。
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

模式表 = ("名称子串", "名称精确", "限定名子串", "路径子串", "全文")
节点种类表 = ("class", "function", "method", "variable", "import", "file")
最大条数上限 = 500

节点选择列 = ("id AS 节点id, kind AS 种类, name AS 名称, qualified_name AS 限定名, "
              "file_path AS 文件路径, language AS 语言, start_line AS 起始行, "
              "end_line AS 结束行, is_exported AS 是否导出, signature AS 签名")


def 查询节点(*, 代码地图路径: str = "", 关键词: str = "", 模式: str = "名称子串",
             节点种类: list | None = None, 文件路径: str = "",
             语言: str = "", 最大条数: int = 50) -> 结果:
    """按模式检索代码地图节点（必填参数在实现内校验：进程内调用与 HTTP 同口径）。"""
    try:
        取值 = 取文本("代码地图路径", 代码地图路径, 必填=True)
        匹配词 = 取文本("关键词", 关键词, 必填=True)
        匹配模式 = 取枚举("模式", 模式, 允许值=模式表, 默认="名称子串")
        种类表 = 取列表("节点种类", 节点种类, 允许值=节点种类表)
        路径过滤 = 取文本("文件路径", 文件路径, 必填=False)
        语言过滤 = 取文本("语言", 语言, 必填=False)
        条数上限 = 取整数("最大条数", 最大条数, 默认=50, 最小=1, 最大=最大条数上限)
    except 参数错误 as 错误:
        return 结果.失败(错误.错误码, 错误.说明, 来源=来源)
    连接结果 = 打开代码地图(取值)
    if not 连接结果.成功:
        return 连接结果
    连接 = 连接结果.值
    条件, 参数表 = _构造条件(匹配模式, 匹配词, 种类表, 路径过滤, 语言过滤)
    主体 = f"FROM nodes WHERE {条件}"
    try:
        命中数 = 连接.execute(f"SELECT COUNT(*) {主体}", 参数表).fetchone()[0]
        行表 = 连接.execute(
            f"SELECT {节点选择列} {主体} ORDER BY file_path, start_line, name LIMIT ?",
            参数表 + [条数上限],
        ).fetchall()
    except sqlite3.Error as 错误:
        return 结果.失败("查询失败", f"代码地图查询节点失败: {错误}", 来源=来源)
    except Exception as 错误:  # 统一结果铁律：实现不外抛，真实原因原样回带
        return 结果.失败("查询失败", f"代码地图查询节点异常: {错误}", 来源=来源)
    finally:
        关闭代码地图(连接)
    return 结果.成功结果({
        "代码地图路径": 取值,
        "模式": 匹配模式,
        "命中数": 命中数,
        "已截断": 命中数 > len(行表),
        "节点列表": [_节点字典(行) for 行 in 行表],
    })


def _节点字典(行) -> dict:
    """SQLite 行 → 节点字典：`是否导出` 归一到真布尔。

    契约语义是逻辑型，而 SQLite 存的是 0/1 整数——不归一就会出现
    `是否导出=0` 与断言 `false` 不符（HTML 黑盒实测：代码地图两能力正向链）。
    """
    项 = dict(行)
    if "是否导出" in 项:
        项["是否导出"] = bool(项["是否导出"])
    return 项


def _构造条件(模式: str, 匹配词: str, 种类表: list[str],
              路径过滤: str, 语言过滤: str) -> tuple[str, list]:
    """构造 WHERE 子句与参数表（参数化，不做字符串拼接）。"""
    模糊 = 模糊值(匹配词)
    if 模式 == "名称精确":
        条件, 参数表 = "name = ?", [匹配词]
    elif 模式 == "限定名子串":
        条件, 参数表 = "qualified_name LIKE ? ESCAPE '\\'", [模糊]
    elif 模式 == "路径子串":
        条件, 参数表 = "file_path LIKE ? ESCAPE '\\'", [模糊]
    elif 模式 == "全文":
        条件 = ("(name LIKE ? ESCAPE '\\' OR qualified_name LIKE ? ESCAPE '\\' "
                "OR docstring LIKE ? ESCAPE '\\' OR signature LIKE ? ESCAPE '\\')")
        参数表 = [模糊, 模糊, 模糊, 模糊]
    else:
        条件, 参数表 = "name LIKE ? ESCAPE '\\'", [模糊]
    if 种类表:
        条件 += f" AND kind IN ({', '.join('?' * len(种类表))})"
        参数表 += 种类表
    if 路径过滤:
        条件 += " AND file_path LIKE ? ESCAPE '\\'"
        参数表.append(模糊值(路径过滤))
    if 语言过滤:
        条件 += " AND language = ?"
        参数表.append(语言过滤)
    return 条件, 参数表
