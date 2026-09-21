"""语义索引主实现：建代码索引 / 查代码块。

两个能力共用同一份库文件口径（`_解析库文件`），避免「建到 A、查到 B」；
切块、嵌入、打分三个子过程各在 `实现/切块.py`、`实现/嵌入.py`、`实现/索引库.py`，
本文件只做编排与参数校验。

**边界（硬口径）**：语义索引只做召回补充。返回的 文件路径/起始行/结束行 是
可回查的定位，不是内容；调用方必须回 `读取文件` 按行区间取真实内容，
**不得以向量相似度当事实**。
"""
from __future__ import annotations

import time
from datetime import datetime
from fnmatch import fnmatch
from pathlib import Path

from 公共契约.基础类型.结果类型 import 结果
from 公共契约.运行时.运行缓存 import 解析运行缓存根

from 支持库.后端.代码解析支持库.语义索引.实现.嵌入 import (
    取句柄, 嵌入一条, 嵌入查询, 释放句柄,
)
from 支持库.后端.代码解析支持库.语义索引.实现.切块 import 收集代码块
from 支持库.后端.代码解析支持库.语义索引.实现.索引库 import (
    余弦相似度, 打开库, 关键词分数, 清空索引, 截取片段, 块总数, 综合分数,
    写块批, 读全部块,
)

来源 = "语义索引"
平台根 = Path(__file__).resolve().parents[5]
默认嵌入模型名 = "bge-m3"


def _解析库文件(索引根: str, 库文件: str) -> str:
    """统一库文件口径：显式优先，否则 工程缓存/语义索引/<目录名>.db。"""
    if isinstance(库文件, str) and 库文件.strip():
        return str(Path(库文件).expanduser().resolve())
    目录名 = Path(索引根).expanduser().resolve().name or "索引"
    return str(解析运行缓存根(平台根) / "语义索引" / f"{目录名}.db")


def 建代码索引(索引根=None, 库文件="", 嵌入模型名=默认嵌入模型名,
               排除目录=None, 批大小=32) -> 结果:
    """切块 → 生成嵌入 → 落 SQLite（块文本 + 向量 + 文件路径 + 起止行）。"""
    if not isinstance(索引根, str) or not 索引根.strip():
        return 结果.失败("参数不合法", "索引根必须是非空文本", 来源=来源)
    根 = Path(索引根).expanduser().resolve()
    if not 根.is_dir():
        return 结果.失败("目录不存在", f"索引根不是目录: {根}", 来源=来源)
    if not isinstance(嵌入模型名, str) or not 嵌入模型名.strip():
        return 结果.失败("参数不合法", "嵌入模型名必须是非空文本", 来源=来源)
    if 排除目录 is not None and not isinstance(排除目录, list):
        return 结果.失败("参数不合法", "排除目录必须是列表型或空值", 来源=来源)
    if isinstance(批大小, bool) or not isinstance(批大小, int) or 批大小 < 1:
        return 结果.失败("参数不合法", "批大小必须是正整数", 来源=来源)

    起点 = time.time()
    收集 = 收集代码块(str(根), 排除目录)
    块列表, 跳过清单 = 收集["块列表"], list(收集["跳过清单"])
    if not 块列表:
        return 结果.成功结果({"块数": 0, "文件数": 收集["文件数"], "命中缓存数": 0,
                             "新算数": 0, "耗时秒": round(time.time() - 起点, 3),
                             "跳过清单": 跳过清单})

    句柄, 说明 = 取句柄(嵌入模型名)
    if 句柄 is None:
        return 结果.失败("嵌入不可用", 说明, 来源=来源, 可重试=True)
    记录列表: list[dict] = []
    命中缓存数 = 新算数 = 0
    嵌入错误 = ""
    try:
        for 块 in 块列表:
            单条 = 嵌入一条(句柄, 嵌入模型名, 块["块文本"][:4000])
            if 单条["错误说明"]:
                跳过清单.append({"文件路径": 块["文件路径"], "原因": 单条["错误说明"]})
                嵌入错误 = 嵌入错误 or 单条["错误说明"]
                continue
            命中缓存数 += 1 if 单条["命中缓存"] else 0
            新算数 += 0 if 单条["命中缓存"] else 1
            记录列表.append({**块, "块摘要": 截取片段(块["块文本"]), "向量": 单条["向量"],
                           "模型名": 嵌入模型名})
    finally:
        释放句柄(句柄)
    if not 记录列表:
        return 结果.失败("嵌入不可用", f"全部块嵌入失败：{嵌入错误 or '未产生任何向量'}",
                        来源=来源, 可重试=True)

    库文件路径 = _解析库文件(str(根), 库文件)
    try:
        连接 = 打开库(库文件路径)
    except Exception as 错误:
        return 结果.失败("索引写入失败", f"打不开索引库 {库文件路径}: {错误}", 来源=来源)
    try:
        清空索引(连接)
        写入时间 = datetime.now().isoformat(timespec="seconds")
        for 起点序 in range(0, len(记录列表), 批大小):
            写块批(连接, 记录列表[起点序:起点序 + 批大小], 写入时间)
        块数 = 块总数(连接)
    except Exception as 错误:
        return 结果.失败("索引写入失败", f"写入索引库失败: {错误}", 来源=来源)
    finally:
        连接.close()
    return 结果.成功结果({"块数": 块数, "文件数": 收集["文件数"], "命中缓存数": 命中缓存数,
                         "新算数": 新算数, "耗时秒": round(time.time() - 起点, 3),
                         "跳过清单": 跳过清单, "库文件": 库文件路径})


def _命中模式(文件路径: str, 文件模式: str) -> bool:
    if not 文件模式.strip():
        return True
    return fnmatch(文件路径, 文件模式) or fnmatch(Path(文件路径).name, 文件模式)


def 查代码块(索引根=None, 查询=None, 库文件="", 顶部数量=10, 文件模式="",
           最小分数=0.0) -> 结果:
    """向量召回 topN + 关键词/符号精排（召回宽、精排严）。"""
    if not isinstance(索引根, str) or not 索引根.strip():
        return 结果.失败("参数不合法", "索引根必须是非空文本", 来源=来源)
    if not isinstance(查询, str) or not 查询.strip():
        return 结果.失败("参数不合法", "查询必须是非空文本", 来源=来源)
    if isinstance(顶部数量, bool) or not isinstance(顶部数量, int) or 顶部数量 < 1:
        return 结果.失败("参数不合法", "顶部数量必须是正整数", 来源=来源)
    if not isinstance(文件模式, str):
        return 结果.失败("参数不合法", "文件模式必须是文本型", 来源=来源)
    if isinstance(最小分数, bool) or not isinstance(最小分数, (int, float)):
        return 结果.失败("参数不合法", "最小分数必须是数值", 来源=来源)
    库文件路径 = _解析库文件(索引根, 库文件)
    if not Path(库文件路径).is_file():
        return 结果.失败("索引不存在", f"索引库不存在（先调 建代码索引）: {库文件路径}", 来源=来源)
    try:
        连接 = 打开库(库文件路径)
        全部块 = 读全部块(连接)
    except Exception as 错误:
        return 结果.失败("索引读取失败", f"读索引库失败: {错误}", 来源=来源)
    finally:
        try:
            连接.close()
        except Exception:
            pass

    候选块 = [块 for 块 in 全部块 if _命中模式(块["文件路径"], 文件模式)]
    查询向量, 嵌入说明 = 嵌入查询(默认嵌入模型名, 查询)
    打分列表 = []
    for 块 in 候选块:
        向量分数 = 余弦相似度(查询向量, 块["向量"]) if 查询向量 else 0.0
        词分数 = 关键词分数(查询, 块["块文本"])
        分数 = 综合分数(向量分数, 词分数)
        if 分数 < float(最小分数):
            continue
        打分列表.append({"文件路径": 块["文件路径"], "起始行": 块["起始行"], "结束行": 块["结束行"],
                       "块类型": 块["块类型"], "分数": round(分数, 6),
                       "向量分数": round(向量分数, 6), "关键词分数": round(词分数, 6),
                       "片段": 块["块摘要"]})
    打分列表.sort(key=lambda 项: (-项["分数"], 项["文件路径"], 项["起始行"]))
    命中列表 = 打分列表[:顶部数量]
    if not 查询向量 and 嵌入说明:
        命中列表 = [{**项, "向量分数": 0.0} for 项 in 命中列表]
    return 结果.成功结果({"候选列表": 命中列表, "命中数": len(命中列表), "召回数": len(候选块)})


__all__ = ["建代码索引", "查代码块"]
