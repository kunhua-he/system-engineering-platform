"""记忆支持库原子能力实现（不对外暴露，只经包级中文入口调用）。

职责：项目记忆的读写/搜索/管理（通用项目记忆能力，下沉底座）。
本质是链接 SQLite 数据库的原子能力，与 LLM 无归属关系；
向量生成调用大语言模型支持库（上游调用者）。
存储：SQLite 记忆库（唯一权威），不保留历史 Markdown 双份。

**项目维度**（v1.0.3 补齐）：每条记忆可归属一个「项目」，写入时标明、
查询时按项目过滤，做到一个库内各项目记忆互不串味。项目维度全程可选：
不传「项目」时行为与补齐前逐字一致（老调用方零影响）。

**仅关键词模式**：「搜索记忆」的 `仅关键词=true` 走纯 SQLite + 字符串匹配，
完全不调用大模型/向量 —— 「查某项目最近 N 条 / 搜关键词」这类结构化查询
不该付一次 LLM 调用的代价。
"""

from __future__ import annotations

import json
import re
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

from 公共契约.基础类型.结果类型 import 结果
from 公共契约.运行时.运行缓存 import 解析运行缓存根, 解析运行数据根

锁 = threading.Lock()
默认库路径 = 解析运行数据根(Path(__file__).resolve().parents[4]) / "记忆库.db"

项目记忆建表 = """
    CREATE TABLE IF NOT EXISTS 项目记忆(
      标识 TEXT PRIMARY KEY, 名称 TEXT NOT NULL, 记忆类型 TEXT NOT NULL,
      深度 TEXT NOT NULL, 状态 TEXT NOT NULL, 标签 TEXT NOT NULL,
      智能体 TEXT NOT NULL, 正文 TEXT NOT NULL, 创建时间 TEXT NOT NULL,
      更新时间 REAL NOT NULL, 项目 TEXT NOT NULL DEFAULT '');
"""

记忆向量建表 = """
    CREATE TABLE IF NOT EXISTS 记忆向量(
      标识 TEXT PRIMARY KEY, 向量 TEXT NOT NULL, 更新时间 REAL NOT NULL);
"""


def _迁移项目维度(连接: sqlite3.Connection) -> None:
    """老库自动迁移：给 项目记忆 补「项目」列并建（项目+更新时间）索引 —— 幂等。

    为什么不重建表：SQLite 的 `ALTER TABLE ... ADD COLUMN` 带默认值时只改元数据、
    不重写表，已存在的行该列自动取默认值空串（= 未归属项目），老数据零丢失、
    无需人工迁移。`ADD COLUMN` 不支持 IF NOT EXISTS，所以先用 PRAGMA 探列，
    已有该列就跳过；PRAGMA 是只读探测，重复执行安全（幂等）。
    """
    列名表 = {行[1] for 行 in 连接.execute("PRAGMA table_info(项目记忆)")}
    if "项目" not in 列名表:
        连接.execute("ALTER TABLE 项目记忆 ADD COLUMN 项目 TEXT NOT NULL DEFAULT ''")
    连接.execute(
        "CREATE INDEX IF NOT EXISTS 项目记忆_项目_时间 ON 项目记忆(项目, 更新时间 DESC)")


def _项目文本(项目: Any) -> str:
    """归一化「项目」入参：非文本或空白一律按「未指定项目」处理（空串）。"""
    return 项目.strip() if isinstance(项目, str) else ""


def _项目条件(项目文本: str) -> tuple[str, tuple]:
    """按项目过滤的 SQL 片段与绑定参数；未指定项目时不加条件（= 查全部，与旧版一致）。"""
    return (" WHERE 项目=?", (项目文本,)) if 项目文本 else ("", ())


def _归属标识(项目文本: str, 基础标识: str) -> str:
    """带项目时给记忆标识加项目前缀（项目隔离的落点）。

    为什么必须动标识：`项目记忆` 的主键是 标识，`记忆向量` 也以 标识 为主键。
    若两个项目写入同名记忆（标识相同），`INSERT OR REPLACE` 会互相覆盖 ——
    那不是「独立记忆空间」，是同一行被两个项目抢。把项目编进标识后：
    同项目内同名仍幂等覆盖、跨项目同名互不相干、向量也各归各的。
    不传项目时标识逐字等于旧版 `生成标识(标题)`。
    """
    项目前缀 = 生成标识(项目文本) if 项目文本 else ""
    return f"{项目前缀}--{基础标识}" if 项目前缀 else 基础标识


def _关键词命中(查询: str, 记忆: dict) -> tuple[float, int]:
    """纯关键词打分：在 名称+正文+标签 上做大小写不敏感匹配，全程不碰向量/大模型。

    分数 = 命中的查询词种类数 / 查询词总数（0~1，与旧关键词兜底同口径）；
    另回传命中总次数，供同分时的稳定排序（命中度更密的在前）。
    """
    查询词 = {词 for 词 in re.split(r"\s+", 查询.lower()) if 词}
    原始标签 = 记忆.get("标签") or "[]"
    if isinstance(原始标签, str):
        try:
            标签项 = json.loads(原始标签)
        except Exception:
            标签项 = [原始标签]
    else:
        标签项 = 原始标签
    标签文本 = " ".join(str(项) for 项 in 标签项) if isinstance(标签项, list) else str(标签项)
    文本 = f"{记忆.get('名称', '')} {记忆.get('正文', '')} {标签文本}".lower()
    命中词数 = sum(1 for 词 in 查询词 if 词 in 文本)
    命中次数 = sum(文本.count(词) for 词 in 查询词)
    return 命中词数 / max(len(查询词), 1), 命中次数


def _连接(库路径: str = None) -> sqlite3.Connection:
    # 保留 sqlite3 直连、不收敛到唯一入口的技术必要：本库是记忆支持库**自有库**（记忆库.db），
    # 且写入需要参数绑定（正文是任意用户全文）；唯一入口的 事务执行 契约只有「SQL 文本列表、
    # 无参数绑定」，只把读改成走入口会留下两条执行腿（底座哲学第 1 条 2 项）→ 整模块保留待能力补齐。
    路径 = Path(库路径) if 库路径 else 默认库路径
    路径.parent.mkdir(parents=True, exist_ok=True)
    连接 = sqlite3.connect(路径)
    with 连接:
        连接.execute(项目记忆建表)
        连接.execute("CREATE INDEX IF NOT EXISTS 项目记忆_时间 ON 项目记忆(更新时间 DESC)")
        连接.execute(记忆向量建表)
        # 老库（缺 项目 列）在此自动补齐，新库走到这里已是 no-op。
        _迁移项目维度(连接)
    return 连接


def 生成标识(标题: str) -> str:
    标识 = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "-", 标题.strip().lower()).strip("-")
    return 标识 or "memory"


def _读取向量(库路径: str, 标识: str) -> list[float] | None:
    连接 = _连接(库路径)
    try:
        行 = 连接.execute("SELECT 向量 FROM 记忆向量 WHERE 标识=?", (标识,)).fetchone()
        if 行 and 行[0]:
            try:
                return json.loads(行[0])
            except Exception:
                return None
        return None
    finally:
        连接.close()


def _保存向量(库路径: str, 标识: str, 向量: list[float]) -> None:
    连接 = _连接(库路径)
    try:
        with 连接:
            连接.execute("INSERT OR REPLACE INTO 记忆向量(标识, 向量, 更新时间) VALUES (?,?,?)",
                         (标识, json.dumps(向量), time.time()))
    finally:
        连接.close()


def _生成向量(文本: str) -> list[float] | None:
    """经统一能力调用器连接、生成并释放向量句柄。"""
    try:
        from 公共契约.能力契约.调用器 import 获取能力调用器
        调用器 = 获取能力调用器()
        连接结果 = 调用器.调用能力(
            "大语言模型支持库.模型连接器.连接向量模型", {}, 调用方="记忆支持库",
        )
        if not 连接结果.成功 or not isinstance(连接结果.值, dict):
            return None
        句柄 = 连接结果.值.get("句柄")
        if isinstance(句柄, bool) or not isinstance(句柄, int) or not 1 <= 句柄 <= 999999:
            return None
        向量: list[float] | None = None
        释放成功 = False
        try:
            生成结果 = 调用器.调用能力(
                "大语言模型支持库.模型连接器.生成嵌入",
                {"句柄": 句柄, "文本": 文本[:4000]},
                调用方="记忆支持库",
            )
            if 生成结果.成功 and isinstance(生成结果.值, dict):
                候选 = 生成结果.值.get("嵌入") or 生成结果.值.get("向量")
                if isinstance(候选, list) and 候选:
                    向量 = 候选
        finally:
            释放结果 = 调用器.调用能力(
                "大语言模型支持库.模型连接器.释放句柄",
                {"句柄": 句柄}, 调用方="记忆支持库",
            )
            释放成功 = bool(释放结果.成功)
        return 向量 if 释放成功 else None
    except Exception:
        return None


def 余弦相似度(左向量: list[float], 右向量: list[float]) -> float:
    点积 = sum(左值 * 右值 for 左值, 右值 in zip(左向量, 右向量, strict=False))
    左模长 = sum(值 * 值 for 值 in 左向量) ** 0.5
    右模长 = sum(值 * 值 for 值 in 右向量) ** 0.5
    return 点积 / (左模长 * 右模长) if 左模长 and 右模长 else 0.0


def 写入记忆(*, 名称: str = None, 正文: str = None, 记忆类型: str = None,
             深度: str = None, 标签: list = None, 智能体: str = None,
             状态: str = None, 标识: str = None, 项目: str = None,
             库路径: str = None) -> 结果:
    """写入一条记忆。返回 {标识, 名称, 状态}。

    参数:
        项目: 该记忆归属的项目（文本型，可空；空 = 未归属，与旧版逐字一致）。
            带项目时标识自动加项目前缀，跨项目同名记忆互不覆盖。
    """
    if not isinstance(名称, str) or not 名称.strip():
        return 结果.失败("参数不合法", "名称必须是非空字符串", 来源="记忆")
    if not isinstance(正文, str) or not 正文.strip():
        return 结果.失败("参数不合法", "正文必须是非空字符串", 来源="记忆")
    项目文本 = _项目文本(项目)
    记忆id = 标识 if isinstance(标识, str) and 标识.strip() else 生成标识(名称)
    记忆id = _归属标识(项目文本, 记忆id)
    连接 = _连接(库路径)
    try:
        with 连接:
            连接.execute(
                "INSERT OR REPLACE INTO 项目记忆(标识,名称,记忆类型,深度,状态,标签,智能体,正文,创建时间,更新时间,项目) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (记忆id, 名称, 记忆类型 or "参考", 深度 or "standard", 状态 or "已保存",
                 json.dumps(标签 or [], ensure_ascii=False), 智能体 or "",
                 正文, time.strftime("%Y-%m-%dT%H:%M:%S+08:00"), time.time(), 项目文本))
        # 尝试向量（失败静默，关键词兜底）
        向量 = _生成向量(f"{名称}\n{正文}")
        if 向量:
            _保存向量(库路径, 记忆id, 向量)
        return 结果.成功结果({"标识": 记忆id, "名称": 名称, "状态": "已保存"})
    except sqlite3.Error as 错误:
        return 结果.失败("存储失败", str(错误), 来源="记忆")
    finally:
        连接.close()


def 追加记忆(*, 标题: str = None, 细节: str = None, 记忆类型: str = None,
             项目: str = None, 库路径: str = None) -> 结果:
    """追加更新已有记忆（按标题找，找不到则新建）。返回 {标识, 已追加}。

    参数:
        项目: 在哪个项目的记忆空间里追加（文本型，可空）。带项目时记忆标识口径
            与 `写入记忆(项目=同值)` 完全一致，能命中文档前写入的同名记忆。
    """
    if not isinstance(标题, str) or not 标题.strip():
        return 结果.失败("参数不合法", "标题必须是非空字符串", 来源="记忆")
    项目文本 = _项目文本(项目)
    记忆id = _归属标识(项目文本, 生成标识(标题))
    连接 = _连接(库路径)
    try:
        行 = 连接.execute("SELECT 正文 FROM 项目记忆 WHERE 标识=?", (记忆id,)).fetchone()
        with 连接:
            if 行:
                新正文 = f"{行[0]}\n\n{细节}" if 细节 else 行[0]
                连接.execute("UPDATE 项目记忆 SET 正文=?, 更新时间=? WHERE 标识=?",
                             (新正文, time.time(), 记忆id))
                已追加 = True
            else:
                连接.execute(
                    "INSERT INTO 项目记忆(标识,名称,记忆类型,深度,状态,标签,智能体,正文,创建时间,更新时间,项目) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (记忆id, 标题, 记忆类型 or "参考", "standard", "已保存", "[]", "",
                     细节 or "", time.strftime("%Y-%m-%dT%H:%M:%S+08:00"), time.time(), 项目文本))
                已追加 = False
        return 结果.成功结果({"标识": 记忆id, "已追加": 已追加, "标题": 标题})
    except sqlite3.Error as 错误:
        return 结果.失败("存储失败", str(错误), 来源="记忆")
    finally:
        连接.close()


def 完成记忆(*, 标题: str = None, 库路径: str = None) -> 结果:
    """标记记忆完成。返回 {标识, 状态}。"""
    if not isinstance(标题, str) or not 标题.strip():
        return 结果.失败("参数不合法", "标题必须是非空字符串", 来源="记忆")
    记忆id = 生成标识(标题)
    连接 = _连接(库路径)
    try:
        with 连接:
            行 = 连接.execute("UPDATE 项目记忆 SET 状态='已完成', 更新时间=? WHERE 标识=?",
                              (time.time(), 记忆id))
        return 结果.成功结果({"标识": 记忆id, "状态": "已完成" if 行.rowcount else "未找到"})
    except sqlite3.Error as 错误:
        return 结果.失败("存储失败", str(错误), 来源="记忆")
    finally:
        连接.close()


def 删除记忆(*, 标识: str = None, 库路径: str = None) -> 结果:
    """删除记忆（含向量）。返回 {标识, 已删除}。"""
    if not isinstance(标识, str) or not 标识.strip():
        return 结果.失败("参数不合法", "标识必须是非空字符串", 来源="记忆")
    连接 = _连接(库路径)
    try:
        with 连接:
            行 = 连接.execute("DELETE FROM 项目记忆 WHERE 标识=?", (标识,))
            连接.execute("DELETE FROM 记忆向量 WHERE 标识=?", (标识,))
        return 结果.成功结果({"标识": 标识, "已删除": 行.rowcount > 0})
    except sqlite3.Error as 错误:
        return 结果.失败("存储失败", str(错误), 来源="记忆")
    finally:
        连接.close()


def 搜索记忆(*, 查询: str = None, 返回条数: int = None, 项目: str = None,
             仅关键词: bool = None, 库路径: str = None) -> 结果:
    """语义搜索记忆（向量相似度 + 关键词兜底）。返回 {数量, 记忆列表}。

    参数:
        项目: 只在该项目的记忆里搜（文本型，可空）。空 = 全部项目，与旧版逐字一致。
        仅关键词: 为真时**完全不调用大模型、不读不写向量**，只用关键词在
            `名称 + 正文 + 标签` 上做大小写不敏感匹配并按命中度排序。
            「某项目最近 N 条 / 搜关键词」这类结构化查询不该付一次 LLM 调用的代价。
    """
    if not isinstance(查询, str) or not 查询.strip():
        return 结果.失败("参数不合法", "查询必须是非空字符串", 来源="记忆")
    数量 = 返回条数 if isinstance(返回条数, int) and 返回条数 > 0 else 5
    项目文本 = _项目文本(项目)
    纯关键词 = bool(仅关键词)
    条件, 条件参数 = _项目条件(项目文本)
    连接 = _连接(库路径)
    try:
        游标 = 连接.execute(f"SELECT * FROM 项目记忆{条件}", 条件参数)
        列名 = [列[0] for 列 in 游标.description]
        行列表 = 游标.fetchall()
        if not 行列表:
            return 结果.成功结果({"数量": 0, "记忆列表": []})
        评分列表 = []
        if 纯关键词:
            # 纯关键词模式：零 LLM、零向量，只有 SQL 过滤 + 字符串匹配。
            for 行 in 行列表:
                记忆 = dict(zip(列名, 行))
                分数, 命中次数 = _关键词命中(查询, 记忆)
                评分列表.append((分数, 命中次数, float(记忆.get("更新时间") or 0.0), 记忆))
            评分列表.sort(key=lambda 项: (项[0], 项[1], 项[2]), reverse=True)
            评分列表 = [(项[0], 项[3]) for 项 in 评分列表]
        else:
            查询向量 = _生成向量(查询)
            查询词 = {词 for 词 in re.split(r"\s+", 查询.lower()) if 词}
            for 行 in 行列表:
                记忆 = dict(zip(列名, 行))
                标识 = str(记忆["标识"])
                记忆向量 = _读取向量(库路径, 标识)
                if 查询向量 and not 记忆向量:
                    记忆向量 = _生成向量(f"{记忆.get('名称','')}\n{记忆.get('正文','')}")
                    if 记忆向量:
                        _保存向量(库路径, 标识, 记忆向量)
                分数 = 0.0
                if 查询向量 and 记忆向量:
                    分数 = 余弦相似度(查询向量, 记忆向量)
                else:
                    文本 = f"{记忆.get('名称','')} {记忆.get('正文','')}".lower()
                    分数 = sum(1 for 词 in 查询词 if 词 in 文本) / max(len(查询词), 1)
                评分列表.append((分数, 记忆))
            评分列表.sort(key=lambda 项: 项[0], reverse=True)
        记忆列表 = []
        for 分数, 记忆 in 评分列表[:数量]:
            记忆["标签"] = json.loads(记忆.get("标签") or "[]")
            记忆["分数"] = round(分数, 4)
            记忆列表.append(记忆)
        return 结果.成功结果({"数量": len(记忆列表), "记忆列表": 记忆列表})
    except sqlite3.Error as 错误:
        return 结果.失败("查询失败", str(错误), 来源="记忆")
    finally:
        连接.close()


def 最近记忆(*, 数量: int = None, 项目: str = None, 库路径: str = None) -> 结果:
    """最近记忆列表。返回 {数量, 记忆列表}。

    参数:
        项目: 只看该项目的最近记忆（文本型，可空）。空 = 全部项目，与旧版逐字一致。
    """
    数量 = 数量 if isinstance(数量, int) and 数量 > 0 else 10
    条件, 条件参数 = _项目条件(_项目文本(项目))
    连接 = _连接(库路径)
    try:
        游标 = 连接.execute(
            f"SELECT * FROM 项目记忆{条件} ORDER BY 更新时间 DESC LIMIT ?",
            (*条件参数, 数量))
        列名 = [列[0] for 列 in 游标.description]
        行列表 = 游标.fetchall()
        记忆列表 = []
        for 行 in 行列表:
            记忆 = dict(zip(列名, 行))
            记忆["标签"] = json.loads(记忆.get("标签") or "[]")
            记忆列表.append(记忆)
        return 结果.成功结果({"数量": len(记忆列表), "记忆列表": 记忆列表})
    except sqlite3.Error as 错误:
        return 结果.失败("查询失败", str(错误), 来源="记忆")
    finally:
        连接.close()


def 列出记忆(*, 项目: str = None, 库路径: str = None) -> 结果:
    """列出全部记忆。返回 {数量, 记忆列表}。

    参数:
        项目: 只列该项目的记忆（文本型，可空）。空 = 列出全部，与旧版逐字一致。
    """
    条件, 条件参数 = _项目条件(_项目文本(项目))
    连接 = _连接(库路径)
    try:
        游标 = 连接.execute(
            f"SELECT * FROM 项目记忆{条件} ORDER BY 更新时间 DESC", 条件参数)
        列名 = [列[0] for 列 in 游标.description]
        行列表 = 游标.fetchall()
        记忆列表 = []
        for 行 in 行列表:
            记忆 = dict(zip(列名, 行))
            记忆["标签"] = json.loads(记忆.get("标签") or "[]")
            记忆列表.append(记忆)
        return 结果.成功结果({"数量": len(记忆列表), "记忆列表": 记忆列表})
    except sqlite3.Error as 错误:
        return 结果.失败("查询失败", str(错误), 来源="记忆")
    finally:
        连接.close()


def 解析配置回退链(*, 目标类型: str, 目标标识: str, 层级: str = None,
                    配置表: list = None) -> 结果:
    """按 精确→团队→实例 三级回退解析配置（TencentDB mps 模式化落地）。

    参数:
        目标类型: 配置归属类型，如 agent / team / instance（文本型）
        目标标识: 目标实体的标识（如 agent 名或 id）
        层级: 配置层级过滤（如 L1/L2/L3），可空
        配置表: 配置候选列表 [{目标类型, 目标标识, 层级, 配置}]，按优先级从高到低

    回退链：精确(目标类型+目标标识+层级) → 同类型泛化(目标类型+层级，目标标识为通配) → 全局(层级)
    返回 {匹配目标, 配置, 回退路径}。
    """
    try:
        目标类型 = str(目标类型 or "").strip()
        目标标识 = str(目标标识 or "").strip()
        if not 目标类型 or not 目标标识:
            return 结果.失败("参数不合法", "目标类型和目标标识不能为空", 来源="记忆")
        候选列表 = list(配置表 or [])
        if not 候选列表:
            return 结果.失败("参数不合法", "配置表不能为空", 来源="记忆")
        # 校验配置表格式
        for 项 in 候选列表:
            if not isinstance(项, dict) or "配置" not in 项:
                return 结果.失败("参数不合法", "配置表每项必须含 配置 字段", 来源="记忆")

        def _匹配(项: dict) -> bool:
            if 项.get("目标类型") != 目标类型:
                return False
            if 层级 and 项.get("层级") and 项["层级"] != 层级:
                return False
            return True

        回退路径 = []
        # ① 精确匹配：目标类型+目标标识（+层级）
        for 项 in 候选列表:
            if _匹配(项) and 项.get("目标标识") == 目标标识:
                回退路径.append("精确")
                return 结果.成功结果({
                    "匹配目标": 项.get("目标标识"),
                    "配置": 项.get("配置"),
                    "回退路径": 回退路径,
                })
        # ② 泛化匹配：目标类型+层级，目标标识为通配（如 "*" / 空）
        for 项 in 候选列表:
            if _匹配(项) and (项.get("目标标识") in ("", "*", None)):
                回退路径.append("泛化")
                return 结果.成功结果({
                    "匹配目标": "*",
                    "配置": 项.get("配置"),
                    "回退路径": 回退路径,
                })
        # ③ 全局：仅层级匹配
        for 项 in 候选列表:
            if 项.get("目标类型") == 目标类型 and (层级 is None or 项.get("层级") == 层级):
                回退路径.append("全局")
                return 结果.成功结果({
                    "匹配目标": "全局",
                    "配置": 项.get("配置"),
                    "回退路径": 回退路径,
                })
        return 结果.成功结果({
            "匹配目标": None,
            "配置": None,
            "回退路径": 回退路径,
        })
    except Exception as 异常:
        return 结果.失败("解析失败", str(异常), 来源="记忆")
