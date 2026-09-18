"""项目文档支持库 · 坑条目写入侧（喂料端，进程内实现，不对外暴露）。

两个动作：
- `建坑索引`：把「踩坑条目」**数据文件**灌进坑条目表（批量喂料）；
- `记踩坑`：把刚踩的**一个**坑结构化落盘（单条，状态机入口）。

判据来自数据文件（与 `校验规范` / `校验集合判据` 同口径）：条目是数据，
改一条只改数据，不需要改代码、不需要重编译。

条目文件结构（唯一真源见 `开发文档/规范/踩坑条目.json`）：

    {"条目版本": "1.0.0", "唯一真源说明": "…",
     "条目": [{"场景id": "…", "症状": "…", "根因": "…",
               "判据": "…", "原文位置": "…", "状态": "草稿"}]}
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from 公共契约.基础类型.结果类型 import 结果
from 支持库.后端.项目文档支持库.实现.索引库 import _连接
from 支持库.后端.项目文档支持库.实现.坑条目表 import (
    五键, 条目id, 校验五键, 状态表, 确保表,
)

_列 = ("条目id", "项目名", "场景id", "症状", "根因", "判据", "原文位置", "状态",
       "命中次数", "首次命中时间", "最近命中时间", "创建时间", "更新时间")


def _文本校验(值, 名: str) -> str:
    return "" if isinstance(值, str) and 值.strip() else f"{名}必须是非空文本"


def 建坑索引(项目名: str = "", 条目文件: str = "", 是否重建: bool = False,
            库文件: str = "") -> 结果:
    """把「踩坑条目」数据文件灌进坑条目表（批量喂料）。

    参数：项目名 / 条目文件（绝对路径）/ 是否重建（真＝先清该项目旧条目）/ 库文件
    返回：``{项目名, 条目数, 写入, 删除}``
    """
    for 值, 名 in ((项目名, "项目名"), (条目文件, "条目文件")):
        if 说明 := _文本校验(值, 名):
            return 结果.失败("参数不合法", 说明, 来源="项目文档支持库")
    路径 = Path(条目文件.strip())
    if not 路径.is_absolute():
        return 结果.失败("参数不合法", "条目文件必须是绝对路径", 来源="项目文档支持库")
    if not 路径.is_file():
        return 结果.失败("判据文件不存在", f"条目文件不可读: {路径}", 来源="项目文档支持库")
    try:
        数据 = json.loads(路径.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as 错误:
        return 结果.失败("文档不可读", f"条目文件解析失败: {错误}", 来源="项目文档支持库")
    条目列表 = 数据.get("条目") if isinstance(数据, dict) else None
    if not isinstance(条目列表, list):
        return 结果.失败("参数不合法", "条目文件缺少「条目」列表", 来源="项目文档支持库")

    待写 = []
    for 序, 条目 in enumerate(条目列表, 1):
        if not isinstance(条目, dict):
            return 结果.失败("参数不合法", f"第 {序} 条不是对象", 来源="项目文档支持库")
        if 说明 := 校验五键(条目, 序):
            return 结果.失败("参数不合法", 说明, 来源="项目文档支持库")
        状态 = str(条目.get("状态") or "草稿").strip()
        if 状态 not in 状态表:
            return 结果.失败("参数不合法",
                           f"第 {序} 条状态非法: {状态}（合法值 {'/'.join(状态表)}）",
                           来源="项目文档支持库")
        待写.append((条目id(项目名, 条目["场景id"], 条目["症状"]), 项目名,
                    *[str(条目[键]).strip() for 键 in 五键], 状态))

    现在 = time.time()
    try:
        with _连接(库文件) as 连接:
            确保表(连接)
            删除 = 0
            if 是否重建:
                删除 = 连接.execute("DELETE FROM 坑条目 WHERE 项目名=?", (项目名,)).rowcount
            for 记录 in 待写:
                连接.execute(
                    f"""INSERT INTO 坑条目({','.join(_列)})
                        VALUES(?,?,?,?,?,?,?,?,0,0,0,?,?)
                        ON CONFLICT(条目id) DO UPDATE SET
                          场景id=excluded.场景id, 根因=excluded.根因, 判据=excluded.判据,
                          原文位置=excluded.原文位置, 状态=excluded.状态,
                          更新时间=excluded.更新时间""",
                    (*记录, 现在, 现在))
            连接.commit()
    except Exception as 错误:
        return 结果.失败("索引库不可用", f"灌条目失败: {错误}", 来源="项目文档支持库")
    return 结果.成功结果({"项目名": 项目名, "条目数": len(待写),
                        "写入": len(待写), "删除": 删除})


def 记踩坑(项目名: str = "", 场景id: str = "", 症状: str = "", 根因: str = "",
          判据: str = "", 原文位置: str = "", 库文件: str = "") -> 结果:
    """把刚踩的一个坑结构化落盘（单条，状态机入口；五键齐全才收）。

    新记的条目落在 `草稿` 态；被检索命中后由 `查开工上下文` 推进状态。
    参数：项目名 / 场景id / 症状 / 根因 / 判据 / 原文位置 / 库文件
    返回：``{条目id, 状态, 是否新增}``
    """
    if 说明 := _文本校验(项目名, "项目名"):
        return 结果.失败("参数不合法", 说明, 来源="项目文档支持库")
    条目 = {"场景id": 场景id, "症状": 症状, "根因": 根因, "判据": 判据, "原文位置": 原文位置}
    if 说明 := 校验五键(条目):
        return 结果.失败("参数不合法", 说明, 来源="项目文档支持库")
    主键 = 条目id(项目名, 场景id, 症状)
    现在 = time.time()
    try:
        with _连接(库文件) as 连接:
            确保表(连接)
            已存在 = 连接.execute("SELECT 1 FROM 坑条目 WHERE 条目id=?", (主键,)).fetchone()
            连接.execute(
                f"""INSERT INTO 坑条目({','.join(_列)})
                    VALUES(?,?,?,?,?,?,?,'草稿',0,0,0,?,?)
                    ON CONFLICT(条目id) DO UPDATE SET
                      根因=excluded.根因, 判据=excluded.判据,
                      原文位置=excluded.原文位置, 更新时间=excluded.更新时间""",
                (主键, 项目名, *[str(条目[键]).strip() for 键 in 五键], 现在, 现在))
            连接.commit()
    except Exception as 错误:
        return 结果.失败("索引库不可用", f"记踩坑失败: {错误}", 来源="项目文档支持库")
    return 结果.成功结果({"条目id": 主键, "状态": "草稿", "是否新增": not bool(已存在)})
