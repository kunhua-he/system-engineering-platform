"""记忆支持库原子能力实现（不对外暴露，只经包级中文入口调用）。

职责：项目记忆的读写/搜索/管理（通用项目记忆能力，下沉底座）。
本质是链接 SQLite 数据库的原子能力，与 LLM 无归属关系；
向量生成调用大语言模型支持库（上游调用者）。
存储：SQLite 记忆库（唯一权威），不保留历史 Markdown 双份。
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


def _连接(库路径: str = None) -> sqlite3.Connection:
    路径 = Path(库路径) if 库路径 else 默认库路径
    路径.parent.mkdir(parents=True, exist_ok=True)
    连接 = sqlite3.connect(路径)
    with 连接:
        连接.execute("""
            CREATE TABLE IF NOT EXISTS 项目记忆(
              标识 TEXT PRIMARY KEY, 名称 TEXT NOT NULL, 记忆类型 TEXT NOT NULL,
              深度 TEXT NOT NULL, 状态 TEXT NOT NULL, 标签 TEXT NOT NULL,
              智能体 TEXT NOT NULL, 正文 TEXT NOT NULL, 创建时间 TEXT NOT NULL,
              更新时间 REAL NOT NULL);
        """)
        连接.execute("CREATE INDEX IF NOT EXISTS 项目记忆_时间 ON 项目记忆(更新时间 DESC)")
        连接.execute("""
            CREATE TABLE IF NOT EXISTS 记忆向量(
              标识 TEXT PRIMARY KEY, 向量 TEXT NOT NULL, 更新时间 REAL NOT NULL);
        """)
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
             状态: str = None, 标识: str = None, 库路径: str = None) -> 结果:
    """写入一条记忆。返回 {标识, 名称, 状态}。"""
    if not isinstance(名称, str) or not 名称.strip():
        return 结果.失败("参数不合法", "名称必须是非空字符串", 来源="记忆")
    if not isinstance(正文, str) or not 正文.strip():
        return 结果.失败("参数不合法", "正文必须是非空字符串", 来源="记忆")
    记忆id = 标识 if isinstance(标识, str) and 标识.strip() else 生成标识(名称)
    连接 = _连接(库路径)
    try:
        with 连接:
            连接.execute(
                "INSERT OR REPLACE INTO 项目记忆(标识,名称,记忆类型,深度,状态,标签,智能体,正文,创建时间,更新时间) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (记忆id, 名称, 记忆类型 or "参考", 深度 or "standard", 状态 or "已保存",
                  json.dumps(标签 or [], ensure_ascii=False), 智能体 or "",
                  正文, time.strftime("%Y-%m-%dT%H:%M:%S+08:00"), time.time()))
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
             库路径: str = None) -> 结果:
    """追加更新已有记忆（按标题找，找不到则新建）。返回 {标识, 已追加}。"""
    if not isinstance(标题, str) or not 标题.strip():
        return 结果.失败("参数不合法", "标题必须是非空字符串", 来源="记忆")
    记忆id = 生成标识(标题)
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
                    "INSERT INTO 项目记忆(标识,名称,记忆类型,深度,状态,标签,智能体,正文,创建时间,更新时间) VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (记忆id, 标题, 记忆类型 or "参考", "standard", "已保存", "[]", "",
                     细节 or "", time.strftime("%Y-%m-%dT%H:%M:%S+08:00"), time.time()))
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


def 搜索记忆(*, 查询: str = None, 返回条数: int = None, 库路径: str = None) -> 结果:
    """语义搜索记忆（向量相似度 + 关键词兜底）。返回 {数量, 记忆列表}。"""
    if not isinstance(查询, str) or not 查询.strip():
        return 结果.失败("参数不合法", "查询必须是非空字符串", 来源="记忆")
    数量 = 返回条数 if isinstance(返回条数, int) and 返回条数 > 0 else 5
    连接 = _连接(库路径)
    try:
        行列表 = 连接.execute("SELECT * FROM 项目记忆").fetchall()
        if not 行列表:
            return 结果.成功结果({"数量": 0, "记忆列表": []})
        列名 = [c[0] for c in 连接.execute("SELECT * FROM 项目记忆").description]
        查询向量 = _生成向量(查询)
        查询词 = {词 for 词 in re.split(r"\s+", 查询.lower()) if 词}
        评分列表 = []
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


def 最近记忆(*, 数量: int = None, 库路径: str = None) -> 结果:
    """最近记忆列表。返回 {数量, 记忆列表}。"""
    数量 = 数量 if isinstance(数量, int) and 数量 > 0 else 10
    连接 = _连接(库路径)
    try:
        行列表 = 连接.execute("SELECT * FROM 项目记忆 ORDER BY 更新时间 DESC LIMIT ?", (数量,)).fetchall()
        列名 = [c[0] for c in 连接.execute("SELECT * FROM 项目记忆").description]
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


def 列出记忆(*, 库路径: str = None) -> 结果:
    """列出全部记忆。返回 {数量, 记忆列表}。"""
    连接 = _连接(库路径)
    try:
        行列表 = 连接.execute("SELECT * FROM 项目记忆 ORDER BY 更新时间 DESC").fetchall()
        列名 = [c[0] for c in 连接.execute("SELECT * FROM 项目记忆").description]
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
