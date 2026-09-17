"""项目文档支持库 · 项目登记原子能力（进程内实现，不对外暴露）。

登记表存「项目名 → 项目根 / 文档根 / 规范文件」。本层只做写读与幂等，
**不校验目录是否真实存在**（那是模块层的边界校验：支持库只提供原子动作）。
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from typing import Any

from 公共契约.基础类型.结果类型 import 结果
from 支持库.后端.项目文档支持库.实现.索引库 import _连接, _库路径


def 登记项目(项目名: str = None, 项目根目录: str = None, 文档根相对路径: str = "开发文档",
            规范文件: str = "", 库文件: str = None) -> 结果:
    """把一个项目写进登记表，同项目名覆盖更新（幂等）。

    参数：项目名 / 项目根目录 / 文档根相对路径 / 规范文件 / 库文件
    返回：``{项目名, 项目根目录, 文档根相对路径, 规范文件, 是否新增}``
    """
    if not isinstance(项目名, str) or not 项目名.strip():
        return 结果.失败("参数不合法", "项目名必须是非空文本", 来源="项目文档支持库")
    if not isinstance(项目根目录, str) or not 项目根目录.strip():
        return 结果.失败("参数不合法", "项目根目录必须是非空文本", 来源="项目文档支持库")
    文档根 = str(文档根相对路径 or "开发文档").strip() or "开发文档"
    try:
        import time
        with _连接(库文件) as 连接:
            已存在 = 连接.execute("SELECT 1 FROM 项目登记 WHERE 项目名=?", (项目名,)).fetchone()
            连接.execute(
                """INSERT OR REPLACE INTO 项目登记
                   (项目名,项目根目录,文档根相对路径,规范文件,登记时间,更新时间)
                   VALUES(?,?,?,?,COALESCE((SELECT 登记时间 FROM 项目登记 WHERE 项目名=?), ?),?)""",
                (项目名, 项目根目录.strip(), 文档根, str(规范文件 or "").strip(),
                 项目名, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), time.time()))
            连接.commit()
        return 结果.成功结果({
            "项目名": 项目名, "项目根目录": 项目根目录.strip(), "文档根相对路径": 文档根,
            "规范文件": str(规范文件 or "").strip(), "是否新增": 已存在 is None,
        })
    except ValueError as 错误:
        return 结果.失败("参数不合法", str(错误), 来源="项目文档支持库")
    except sqlite3.Error as 错误:
        return 结果.失败("索引库不可用", f"登记失败: {错误}", 来源="项目文档支持库")


def 查询项目(项目名: str = "", 库文件: str = None) -> 结果:
    """查询已登记项目：给项目名单查，留空列出全部（按登记时间）。

    参数：项目名（留空列出全部）/ 库文件
    返回：``{项目表, 数量}``；给名查不到时 ``项目表`` 为空数组且 ``数量`` 为 0。
    """
    名称 = str(项目名 or "").strip()
    try:
        with _连接(库文件) as 连接:
            if 名称:
                行表 = 连接.execute(
                    """SELECT 项目名,项目根目录,文档根相对路径,规范文件,登记时间
                       FROM 项目登记 WHERE 项目名=?""", (名称,)).fetchall()
            else:
                行表 = 连接.execute(
                    """SELECT 项目名,项目根目录,文档根相对路径,规范文件,登记时间
                       FROM 项目登记 ORDER BY 更新时间 DESC""").fetchall()
    except ValueError as 错误:
        return 结果.失败("参数不合法", str(错误), 来源="项目文档支持库")
    except sqlite3.Error as 错误:
        return 结果.失败("索引库不可用", f"查询失败: {错误}", 来源="项目文档支持库")

    项目表 = [{"项目名": r[0], "项目根目录": r[1], "文档根相对路径": r[2],
              "规范文件": r[3], "登记时间": r[4]} for r in 行表]
    return 结果.成功结果({"项目表": 项目表, "数量": len(项目表), "库文件": str(_库路径(库文件))})
