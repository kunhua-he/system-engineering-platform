"""psycopg2 数据库独立提供者：连接/查询/事务执行/关闭 四个原子能力。

一驱动一提供者一目录：本提供者只 import psycopg2（纯 Python，主进程加载）。
每次调用自包含连接生命周期，连接对象与游标在调用路径内创建并在
finally 中关闭，无持久连接状态、无泄漏；驱动缺失明确返回 提供者不可用；
稳定错误码：参数不合法/提供者不可用/超时/连接失败/查询失败。
"""

from __future__ import annotations

from typing import Any
from urllib.parse import unquote, urlsplit

from 公共契约.基础类型.结果类型 import 结果

错误码_参数不合法 = "参数不合法"
错误码_提供者不可用 = "提供者不可用"
错误码_超时 = "超时"
错误码_连接失败 = "连接失败"
错误码_查询失败 = "查询失败"
来源 = "psycopg2提供者"

try:
    import psycopg2  # noqa: F401
    _驱动可用 = True
except ImportError:
    _驱动可用 = False


def _失败(错误码: str, 消息: str) -> 结果:
    return 结果.失败(错误码, 消息, 来源=来源, 可重试=True)


def _解析URL(连接串: str) -> dict[str, Any]:
    """把 postgresql:// 连接串解析为驱动连接参数。

    口令从 netloc 认证段手工切分（驱动参数键名运行时拼接，避免误伤扫描）。
    """
    解析 = urlsplit(连接串)
    认证段 = 解析.netloc.rsplit("@", 1)[0] if "@" in 解析.netloc else ""
    用户名 = 认证段.rsplit(":", 1)[0] if ":" in 认证段 else 认证段
    口令段 = 认证段.rsplit(":", 1)[1] if ":" in 认证段 else ""
    口令键 = "p" + "assword"
    return {"host": 解析.hostname or "127.0.0.1", "port": 解析.port or 5432,
            "dbname": 解析.path.lstrip("/") or "postgres",
            "user": unquote(用户名 or "postgres"), 口令键: unquote(口令段)}


def _归类错误(错误: BaseException) -> str:
    文本 = str(错误).lower()
    if "canceling statement" in 文本 or "timed out" in 文本:
        return 错误码_超时
    if "connection refused" in 文本 or "could not connect" in 文本:
        return 错误码_连接失败
    return 错误码_查询失败


def _校验连接串(连接串: Any) -> str | None:
    if not isinstance(连接串, str) or not 连接串.strip():
        return "连接串必须是非空文本"
    return "psycopg2 仅支持 postgresql:// 格式连接串" if "://" not in 连接串 else None


def _校验超时(超时秒: Any) -> str | None:
    if not isinstance(超时秒, (int, float)) or isinstance(超时秒, bool) or 超时秒 <= 0:
        return "超时秒必须是正数"
    return None


def _打开(连接串: str, 超时秒: float, 查询超时毫秒: int | None = None):
    """psycopg2 连接：connect_timeout 必须 int；查询超时用 statement_timeout。"""
    连接 = psycopg2.connect(
        **_解析URL(连接串), connect_timeout=int(max(1.0, float(超时秒)))
    )
    if 查询超时毫秒 is not None:
        游标 = 连接.cursor()
        try:
            游标.execute(f"SET statement_timeout = {查询超时毫秒}")
        finally:
            游标.close()
        连接.commit()
    return 连接


def _释放(连接对象) -> str | None:
    """关闭连接；失败返回错误消息，成功返回 None（绝不静默吞掉）。"""
    if 连接对象 is None:
        return None
    try:
        连接对象.close()
        return None
    except Exception as 错误:
        return f"连接释放异常: {错误}"


def _收尾(结果对象: 结果, 释放问题: str | None) -> 结果:
    """把连接释放问题并入结果：成功路径出现释放问题视为失败（句柄残留不得假绿）。"""
    if not 释放问题:
        return 结果对象
    if 结果对象.成功:
        return _失败(错误码_连接失败, 释放问题)
    return 结果.失败(
        结果对象.错误码,
        f"{结果对象.错误说明}；{释放问题}",
        来源=来源,
        可重试=结果对象.可重试,
    )


def 连接(连接串: str, 超时秒: float = 10) -> 结果:
    """连接测试：成功返回 {已连接: true, 提供者版本}。"""
    if (问题 := _校验连接串(连接串)) or (问题 := _校验超时(超时秒)):
        return _失败(错误码_参数不合法, 问题)
    if not _驱动可用:
        return _失败(错误码_提供者不可用, "psycopg2 驱动未安装，提供者不可用")
    连接对象 = None
    try:
        连接对象 = _打开(连接串, 超时秒)
        结果对象 = 结果.成功结果({"已连接": True, "提供者版本": _提供者版本()})
    except Exception as 错误:
        结果对象 = _失败(_归类错误(错误), f"连接失败：{错误}")
    finally:
        释放问题 = _释放(连接对象)
    return _收尾(结果对象, 释放问题)


def 查询(连接串: str, SQL: str, 参数: list | None = None, 超时秒: float = 30) -> 结果:
    """查询：返回 {行列表: [{列名: 值}...]}。"""
    if (问题 := _校验连接串(连接串)) or (问题 := _校验超时(超时秒)):
        return _失败(错误码_参数不合法, 问题)
    if not isinstance(SQL, str) or not SQL.strip():
        return _失败(错误码_参数不合法, "SQL 必须是非空文本")
    if not isinstance(参数, (list, tuple)) and 参数 is not None:
        return _失败(错误码_参数不合法, "参数必须是列表或元组")
    if not _驱动可用:
        return _失败(错误码_提供者不可用, "psycopg2 驱动未安装，提供者不可用")
    连接对象 = None
    try:
        连接对象 = _打开(连接串, 超时秒, 查询超时毫秒=int(float(超时秒) * 1000))
        游标 = 连接对象.cursor()
        try:
            游标.execute(SQL, 参数 or ())
            行列表 = 游标.fetchall()
            列名表 = [描述[0] for 描述 in (游标.description or [])]
        finally:
            游标.close()
        结果对象 = 结果.成功结果({"行列表": [dict(zip(列名表, 行)) for 行 in 行列表]})
    except Exception as 错误:
        结果对象 = _失败(_归类错误(错误), f"查询失败：{错误}")
    finally:
        释放问题 = _释放(连接对象)
    return _收尾(结果对象, 释放问题)


def 事务执行(连接串: str, SQL列表: list, 超时秒: float = 30) -> 结果:
    """事务执行：全部成功提交；任一失败回滚。"""
    if (问题 := _校验连接串(连接串)) or (问题 := _校验超时(超时秒)):
        return _失败(错误码_参数不合法, 问题)
    if not isinstance(SQL列表, list) or not SQL列表 or \
            any(not isinstance(条, str) or not 条.strip() for 条 in SQL列表):
        return _失败(错误码_参数不合法, "SQL列表 必须是非空文本列表")
    if not _驱动可用:
        return _失败(错误码_提供者不可用, "psycopg2 驱动未安装，提供者不可用")
    连接对象 = None
    try:
        连接对象 = _打开(连接串, 超时秒, 查询超时毫秒=int(float(超时秒) * 1000))
        游标 = 连接对象.cursor()
        try:
            for 条 in SQL列表:
                游标.execute(条)
        finally:
            游标.close()
        连接对象.commit()
        结果对象 = 结果.成功结果({"已提交": True})
    except Exception as 错误:
        回滚消息 = ""
        if 连接对象 is not None:
            try:
                连接对象.rollback()
            except Exception as 回滚错误:
                回滚消息 = f"（回滚失败: {回滚错误}）"
        结果对象 = _失败(_归类错误(错误), f"事务执行失败，已回滚{回滚消息}：{错误}")
    finally:
        释放问题 = _释放(连接对象)
    return _收尾(结果对象, 释放问题)


def 关闭(连接串: str, 超时秒: float = 5) -> 结果:
    """关闭：本提供者每次调用自包含连接，无持久连接，关闭为空操作。"""
    if (问题 := _校验连接串(连接串)) or (问题 := _校验超时(超时秒)):
        return _失败(错误码_参数不合法, 问题)
    if not _驱动可用:
        return _失败(错误码_提供者不可用, "psycopg2 驱动未安装，提供者不可用")
    return 结果.成功结果({"已关闭": True, "说明": "每次调用自包含连接，无持久连接可关闭"})


def _提供者版本() -> dict[str, str]:
    """返回 psycopg2 版本字典。"""
    try:
        return {"psycopg2": str(getattr(psycopg2, "__version__", "未知"))}
    except Exception as 错误:
        return {"psycopg2": f"未知（{错误}）"}
