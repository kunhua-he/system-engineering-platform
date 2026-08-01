"""psycopg 数据库独立提供者：连接/查询/事务执行/关闭 四个原子能力。

一驱动一提供者一目录：本提供者只 import psycopg（纯 Python，主进程加载）。
每次调用自包含连接生命周期，无持久连接状态；驱动缺失明确返回 提供者不可用；
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
来源 = "psycopg提供者"

try:
    import psycopg  # noqa: F401
    _驱动可用 = True
except ImportError:
    _驱动可用 = False


def _失败(错误码: str, 消息: str) -> 结果:
    return 结果.失败(错误码, 消息, 来源=来源, 可重试=True)


def _解析URL(连接串: str) -> dict[str, Any]:
    解析 = urlsplit(连接串)
    return {"host": 解析.hostname or "127.0.0.1", "port": 解析.port or 5432,
            "dbname": 解析.path.lstrip("/") or "postgres",
            "user": unquote(解析.username or "postgres"),
            "password": unquote(解析.password or "")}


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
    return "psycopg 仅支持 postgresql:// 格式连接串" if "://" not in 连接串 else None


def _校验超时(超时秒: Any) -> str | None:
    if not isinstance(超时秒, (int, float)) or isinstance(超时秒, bool) or 超时秒 <= 0:
        return "超时秒必须是正数"
    return None


def _打开(连接串: str, 超时秒: float, 查询超时毫秒: int | None = None):
    """psycopg3 连接：connect_timeout 秒级；查询超时用 statement_timeout。"""
    连接 = psycopg.connect(
        **_解析URL(连接串), connect_timeout=max(1.0, float(超时秒))
    )
    if 查询超时毫秒 is not None:
        with 连接.cursor() as 游标:
            游标.execute(f"SET statement_timeout = {查询超时毫秒}")
        连接.commit()
    return 连接


def 连接(连接串: str, 超时秒: float = 10) -> 结果:
    """连接测试：成功返回 {已连接: true}。"""
    if not _驱动可用:
        return _失败(错误码_提供者不可用, "psycopg 未安装（提供者不可用）")
    参数问题 = _校验连接串(连接串)
    if 参数问题:
        return _失败(错误码_参数不合法, 参数问题)
    超时问题 = _校验超时(超时秒)
    if 超时问题:
        return _失败(错误码_参数不合法, 超时问题)
    try:
        连接对象 = _打开(连接串, 超时秒)
        连接对象.close()
        return 结果.成功结果({"已连接": True})
    except Exception as 错误:
        return _失败(_归类错误(错误), f"连接失败: {错误}")


def 查询(连接串: str, SQL: str, 参数: list | None = None, 超时秒: float = 30) -> 结果:
    """查询：返回 {行列表: [{列名: 值}...]}。"""
    if not _驱动可用:
        return _失败(错误码_提供者不可用, "psycopg 未安装（提供者不可用）")
    参数问题 = _校验连接串(连接串)
    if 参数问题:
        return _失败(错误码_参数不合法, 参数问题)
    if not isinstance(SQL, str) or not SQL.strip():
        return _失败(错误码_参数不合法, "SQL 必须是非空文本")
    try:
        连接对象 = _打开(连接串, 10, 查询超时毫秒=int(超时秒 * 1000))
        with 连接对象.cursor() as 游标:
            游标.execute(SQL, 参数 or [])
            列名 = [描述[0] for 描述 in 游标.description] if 游标.description else []
            行列表 = [dict(zip(列名, 行)) for 行 in 游标.fetchall()]
        连接对象.close()
        return 结果.成功结果({"行列表": 行列表})
    except Exception as 错误:
        return _失败(_归类错误(错误), f"查询失败: {错误}")


def 事务执行(连接串: str, SQL列表: list, 超时秒: float = 30) -> 结果:
    """事务执行：全部成功提交；任一失败回滚。"""
    if not _驱动可用:
        return _失败(错误码_提供者不可用, "psycopg 未安装（提供者不可用）")
    参数问题 = _校验连接串(连接串)
    if 参数问题:
        return _失败(错误码_参数不合法, 参数问题)
    if not isinstance(SQL列表, list) or not SQL列表:
        return _失败(错误码_参数不合法, "SQL列表 必须是非空列表")
    try:
        连接对象 = _打开(连接串, 10, 查询超时毫秒=int(超时秒 * 1000))
        try:
            with 连接对象.cursor() as 游标:
                for SQL in SQL列表:
                    游标.execute(SQL)
            连接对象.commit()
        except Exception:
            连接对象.rollback()
            raise
        finally:
            连接对象.close()
        return 结果.成功结果({"已提交": True})
    except Exception as 错误:
        return _失败(_归类错误(错误), f"事务失败: {错误}")


def 关闭(连接串: str, 超时秒: float = 5) -> 结果:
    """关闭：无持久连接，本提供者每次调用自包含连接，关闭为空操作。"""
    return 结果.成功结果({"已关闭": True})
