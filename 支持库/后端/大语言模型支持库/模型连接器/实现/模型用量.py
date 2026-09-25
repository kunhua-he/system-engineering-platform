"""模型用量原子能力实现（不对外暴露，只经包级中文入口调用）。

职责：① 记录模型调用（打分燃料的入口）；② 汇总模型表现（把记录算成分数）。
存储：SQLite（本包专用库），路径 = 运行数据根 / `大语言模型支持库.模型用量.db`。
边界：**只记录与统计，不调用任何模型、不消耗任何 LLM 额度**。
      真正的模型调用由调用方完成后再把结果告诉本能力（华哥口径：记录的是「已发生的调用」）。

建连转调 `公共契约/运行时/数据库连接.py` 的写路径档 `打开可写`：连接按库路径缓存、
被模块级锁跨线程复用（`check_same_thread=False` 由具名档 `跨线程=True` 承担）。

全部能力返回统一结果（成功/值/错误码/错误说明）；参数非法返回 参数不合法。
"""

from __future__ import annotations

import atexit
import json
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

from 公共契约.基础类型.结果类型 import 结果
from 公共契约.运行时.运行缓存 import 解析运行数据根
from 公共契约.运行时.导入前缀 import 取系统根
from 公共契约.运行时.数据库连接 import 打开可写

默认库文件名 = "大语言模型支持库.模型用量.db"
默认最少样本数 = 3

# 权重默认（华哥口径：哪个模型适合做什么任务、性价比、效率最高）
默认权重 = {"成功率": 0.4, "效率": 0.2, "性价比": 0.3, "匹配度": 0.1}

降级记录表: list[str] = []  # 尽力清理/降级场景的异常记录（不阻断主流程）

_连接: sqlite3.Connection | None = None
_连接路径: Path | None = None
_连接锁 = threading.RLock()


def 默认数据库路径() -> Path:
    """本包专用库路径（与其他支持库库文件同放运行数据根）。"""
    return 解析运行数据根(取系统根(__file__)) / 默认库文件名


def _关闭连接() -> None:
    """进程退出时关闭内部 SQLite 连接，避免泄漏资源。"""
    global _连接, _连接路径
    with _连接锁:
        if _连接 is None:
            return
        try:
            _连接.close()
        finally:
            _连接 = None
            _连接路径 = None


atexit.register(_关闭连接)


def _失败(错误码: str, 消息: str) -> 结果:
    return 结果.失败(错误码, 消息, 来源="模型用量")


def _取连接(数据库路径: str | Path | None = None) -> sqlite3.Connection:
    global _连接, _连接路径
    目标 = Path(数据库路径) if 数据库路径 else 默认数据库路径()
    if _连接 is not None and _连接路径 == 目标:
        return _连接
    if _连接 is not None:
        try:
            _连接.close()
        except Exception as 错误:
            降级记录表.append(str(错误))
    目标.parent.mkdir(parents=True, exist_ok=True)
    # 转调 `公共契约/运行时/数据库连接.py`，原参数 timeout=10、check_same_thread=False → 写路径档
    # `打开可写(..., 跨线程=True)`（此处建表建索引，属初始化写路径）
    _连接 = 打开可写(str(目标), 10, 跨线程=True)
    _连接.execute(
        "CREATE TABLE IF NOT EXISTS 模型用量 ("
        " 记录id TEXT PRIMARY KEY, 模型 TEXT NOT NULL, 任务类型 TEXT NOT NULL,"
        " 成功 INTEGER NOT NULL, 耗时毫秒 REAL, 输入令牌 INTEGER, 输出令牌 INTEGER,"
        " 成本 REAL, 端点 TEXT, 备注 TEXT, 记录时间 TEXT NOT NULL)"
    )
    _连接.execute("CREATE INDEX IF NOT EXISTS 用量模型任务 ON 模型用量 (模型, 任务类型)")
    _连接.commit()
    _连接路径 = 目标
    return _连接


def _现在() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _整数(值, 名称: str):
    """选填整数的宽松校验：None 放行，其余必须是非负整数。返回 (值, 问题)。"""
    if 值 is None:
        return None, None
    if isinstance(值, bool) or not isinstance(值, int) or 值 < 0:
        return None, f"{名称} 必须是非负整数: {值!r}"
    return 值, None


def _数(值, 名称: str):
    """选填数值的宽松校验：None 放行，其余必须是非负数字。返回 (值, 问题)。"""
    if 值 is None:
        return None, None
    if isinstance(值, bool) or not isinstance(值, (int, float)) or 值 < 0:
        return None, f"{名称} 必须是非负数字: {值!r}"
    return float(值), None


def 记录模型调用(
    模型=None, 成功=None, 任务类型=None, 耗时毫秒=None,
    输入令牌=None, 输出令牌=None, 成本=None, 端点=None, 备注=None,
    记录id=None, 数据库路径=None,
) -> 结果:
    """记录一条模型调用（打分燃料的入口）。

    ★ 本能力**不消耗任何 LLM 额度** —— 它记录的是「已经发生过的调用」，
    模型调用由调用方自己完成后再把结果告诉本能力。

    参数:
        模型: 文本型，必填
        成功: 逻辑型，必填
        任务类型: 文本型，选填（如 策划/日常/清洗/看图/生图）
        耗时毫秒/输入令牌/输出令牌/成本: 选填，非负
        端点/备注: 文本型，选填
        记录id: 文本型，选填（不给则自动生成；同 id 重复写为更新语义）
        数据库路径: 文本型，选填（默认本包专用库）

    返回: 已记录（逻辑型）、记录id（文本型）、累计条数（整数型）
    """
    if not isinstance(模型, str) or not 模型.strip():
        return _失败("参数不合法", f"模型 必须是非空字符串: {模型!r}")
    if not isinstance(成功, bool):
        return _失败("参数不合法", f"成功 必须是逻辑型（真/假）: {成功!r}")
    for 值, 名称 in ((任务类型, "任务类型"), (端点, "端点"), (备注, "备注"), (记录id, "记录id")):
        if 值 is not None and (not isinstance(值, str)):
            return _失败("参数不合法", f"{名称} 必须是字符串: {值!r}")
    耗时净, 问题 = _整数(耗时毫秒, "耗时毫秒")
    if 问题:
        return _失败("参数不合法", 问题)
    成本净, 问题 = _数(成本, "成本")
    if 问题:
        return _失败("参数不合法", 问题)
    输入净, 问题 = _整数(输入令牌, "输入令牌")
    if 问题:
        return _失败("参数不合法", 问题)
    输出净, 问题 = _整数(输出令牌, "输出令牌")
    if 问题:
        return _失败("参数不合法", 问题)

    净记录id = 记录id.strip() if isinstance(记录id, str) and 记录id.strip() else uuid.uuid4().hex
    try:
        with _连接锁:
            连接 = _取连接(数据库路径)
            连接.execute(
                "INSERT INTO 模型用量"
                " (记录id, 模型, 任务类型, 成功, 耗时毫秒, 输入令牌, 输出令牌, 成本, 端点, 备注, 记录时间)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?)"
                " ON CONFLICT(记录id) DO UPDATE SET 模型=excluded.模型, 任务类型=excluded.任务类型,"
                " 成功=excluded.成功, 耗时毫秒=excluded.耗时毫秒, 输入令牌=excluded.输入令牌,"
                " 输出令牌=excluded.输出令牌, 成本=excluded.成本, 端点=excluded.端点,"
                " 备注=excluded.备注, 记录时间=excluded.记录时间",
                (净记录id, 模型.strip(), (任务类型 or "未分类").strip(), 1 if 成功 else 0,
                 耗时净, 输入净, 输出净, 成本净,
                 (端点 or "").strip(), (备注 or "").strip(), _现在()),
            )
            连接.commit()
            累计 = 连接.execute("SELECT COUNT(*) FROM 模型用量").fetchone()[0]
        return 结果.成功结果({"已记录": True, "记录id": 净记录id, "累计条数": int(累计)})
    except sqlite3.Error as 错误:
        return _失败("写入失败", f"记录模型调用失败: {错误}")


def _读取记录(数据库路径: str | None = None, 任务类型: str | None = None) -> list[dict]:
    """读全部（或指定任务类型的）用量记录。"""
    with _连接锁:
        连接 = _取连接(数据库路径)
        if 任务类型:
            行列表 = 连接.execute(
                "SELECT 模型, 任务类型, 成功, 耗时毫秒, 输入令牌, 输出令牌, 成本 FROM 模型用量"
                " WHERE 任务类型 = ?", (任务类型,)).fetchall()
        else:
            行列表 = 连接.execute(
                "SELECT 模型, 任务类型, 成功, 耗时毫秒, 输入令牌, 输出令牌, 成本 FROM 模型用量").fetchall()
    记录 = []
    for 行 in 行列表:
        记录.append({
            "模型": 行[0], "任务类型": 行[1], "成功": bool(行[2]),
            "耗时毫秒": 行[3], "输入令牌": 行[4], "输出令牌": 行[5], "成本": 行[6],
        })
    return 记录


def _中位数(数值列表: list[float]) -> float:
    """中位数（基准值用，避免极端值带偏）。空表返回 0。"""
    有效 = sorted(数值列表)
    if not 有效:
        return 0.0
    中 = len(有效) // 2
    if len(有效) % 2:
        return float(有效[中])
    return (有效[中 - 1] + 有效[中]) / 2.0


def 汇总模型表现(候选清单=None, 任务类型=None, 最少样本数=None, 数据库路径=None) -> 结果:
    """把用量记录汇总成可比较的表现指标（纯统计，**不消耗任何额度**）。

    参数:
        候选清单: 列表型，必填（由调用方给，底座不存模型台账）
        任务类型: 文本型，选填；不给则汇总全部记录
        最少样本数: 整数型，选填，默认 3
        数据库路径: 文本型，选填

    返回: 汇总（列表型：模型/样本数/成功率/平均耗时毫秒/平均令牌/平均成本/是否样本充足）
          数据条数（整数型）、说明（文本型）
    """
    if not isinstance(候选清单, list) or not 候选清单:
        return _失败("参数不合法", f"候选清单 必须是非空列表: {候选清单!r}")
    for 项 in 候选清单:
        if not isinstance(项, str) or not 项.strip():
            return _失败("参数不合法", f"候选清单 每项必须是非空字符串: {项!r}")
    if 任务类型 is not None and (not isinstance(任务类型, str)):
        return _失败("参数不合法", f"任务类型 必须是字符串: {任务类型!r}")
    样本门槛 = 默认最少样本数 if 最少样本数 is None else 最少样本数
    if isinstance(样本门槛, bool) or not isinstance(样本门槛, int) or 样本门槛 < 1:
        return _失败("参数不合法", f"最少样本数 必须是正整数: {最少样本数!r}")

    try:
        记录 = _读取记录(数据库路径, (任务类型 or "").strip() or None)
    except sqlite3.Error as 错误:
        return _失败("读取失败", f"读取用量记录失败: {错误}")

    汇总 = []
    for 模型 in 候选清单:
        名 = 模型.strip()
        该模型 = [条 for 条 in 记录 if 条["模型"] == 名]
        条数 = len(该模型)
        成功数 = sum(1 for 条 in 该模型 if 条["成功"])
        耗时表 = [条["耗时毫秒"] for 条 in 该模型 if 条["耗时毫秒"] is not None]
        令牌表 = [(条["输入令牌"] or 0) + (条["输出令牌"] or 0) for 条 in 该模型]
        成本表 = [条["成本"] for 条 in 该模型 if 条["成本"] is not None]
        汇总.append({
            "模型": 名,
            "样本数": 条数,
            "成功率": round(成功数 / 条数, 6) if 条数 else None,
            "平均耗时毫秒": round(sum(耗时表) / len(耗时表), 3) if 耗时表 else None,
            "平均令牌": round(sum(令牌表) / 条数, 3) if 条数 else None,
            "平均成本": round(sum(成本表) / len(成本表), 6) if 成本表 else None,
            "是否样本充足": 条数 >= 样本门槛,
        })
    说明 = (f"共 {len(记录)} 条记录（任务类型={'全部' if not 任务类型 else 任务类型}）；"
            f"样本门槛 {样本门槛} 条；样本不足者不给分，仅如实标注。")
    return 结果.成功结果({"汇总": 汇总, "数据条数": len(记录), "说明": 说明})
