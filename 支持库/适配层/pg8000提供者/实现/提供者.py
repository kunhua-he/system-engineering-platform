"""pg8000 数据库独立提供者：连接/查询/事务执行/关闭 四个原子能力。

一驱动一提供者一目录：本提供者只 import pg8000（纯 Python，主进程加载）。
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
来源 = "pg8000提供者"

try:
    import pg8000  # noqa: F401
    _驱动可用 = True
except ImportError:
    _驱动可用 = False


def _失败(错误码: str, 消息: str) -> 结果:
    return 结果.失败(错误码, 消息, 来源=来源, 可重试=True)


def _解析URL(连接串: str) -> dict[str, Any]:
    解析 = urlsplit(连接串)
    return {"host": 解析.hostname or "127.0.0.1", "port": 解析.port or 5432,
            "database": 解析.path.lstrip("/") or "postgres",
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
    return "pg8000 仅支持 postgresql:// 格式连接串" if "://" not in 连接串 else None


def _校验超时(超时秒: Any) -> str | None:
    if not isinstance(超时秒, (int, float)) or isinstance(超时秒, bool) or 超时秒 <= 0:
        return "超时秒必须是正数"
    return None


def _打开(连接串: str, 超时秒: float, 查询超时毫秒: int | None = None):
    连接 = pg8000.connect(**_解析URL(连接串), timeout=max(1.0, float(超时秒)))
    if 查询超时毫秒 is not None:
        游标 = 连接.cursor()
        try:
            游标.execute(f"SET statement_timeout = {查询超时毫秒}")
        finally:
            游标.close()
        连接.commit()
    return 连接


def _释放(连接对象) -> None:
    if 连接对象 is not None:
        try:
            连接对象.close()
        except Exception:
            pass


def 连接(连接串: str, 超时秒: float = 10) -> 结果:
    if (问题 := _校验连接串(连接串)) or (问题 := _校验超时(超时秒)):
        return _失败(错误码_参数不合法, 问题)
    if not _驱动可用:
        return _失败(错误码_提供者不可用, "pg8000 驱动未安装，提供者不可用")
    连接对象 = None
    try:
        连接对象 = _打开(连接串, 超时秒)
        return 结果.成功结果({"已连接": True})
    except Exception as 错误:
        return _失败(_归类错误(错误), f"连接失败：{错误}")
    finally:
        _释放(连接对象)


def 查询(连接串: str, SQL: str, 参数: list = [], 超时秒: float = 30) -> 结果:
    if (问题 := _校验连接串(连接串)) or (问题 := _校验超时(超时秒)):
        return _失败(错误码_参数不合法, 问题)
    if not isinstance(SQL, str) or not SQL.strip():
        return _失败(错误码_参数不合法, "SQL 必须是非空文本")
    if not isinstance(参数, (list, tuple)):
        return _失败(错误码_参数不合法, "参数必须是列表或元组")
    if not _驱动可用:
        return _失败(错误码_提供者不可用, "pg8000 驱动未安装，提供者不可用")
    连接对象 = None
    try:
        连接对象 = _打开(连接串, 超时秒, 查询超时毫秒=int(float(超时秒) * 1000))
        游标 = 连接对象.cursor()
        游标.execute(SQL, tuple(参数))
        行列表 = 游标.fetchall()
        列名表 = [描述[0] for 描述 in (游标.description or [])]
        游标.close()
        return 结果.成功结果({"行列表": [dict(zip(列名表, 行)) for 行 in 行列表]})
    except Exception as 错误:
        return _失败(_归类错误(错误), f"查询失败：{错误}")
    finally:
        _释放(连接对象)


def 事务执行(连接串: str, SQL列表: list, 超时秒: float = 30) -> 结果:
    if (问题 := _校验连接串(连接串)) or (问题 := _校验超时(超时秒)):
        return _失败(错误码_参数不合法, 问题)
    if not isinstance(SQL列表, list) or not SQL列表 or \
            any(not isinstance(条, str) or not 条.strip() for 条 in SQL列表):
        return _失败(错误码_参数不合法, "SQL列表 必须是非空文本列表")
    if not _驱动可用:
        return _失败(错误码_提供者不可用, "pg8000 驱动未安装，提供者不可用")
    连接对象 = None
    try:
        连接对象 = _打开(连接串, 超时秒, 查询超时毫秒=int(float(超时秒) * 1000))
        游标 = 连接对象.cursor()
        for 条 in SQL列表:
            游标.execute(条)
        游标.close()
        连接对象.commit()
        return 结果.成功结果({"已提交": True})
    except Exception as 错误:
        try:
            if 连接对象 is not None:
                连接对象.rollback()
        except Exception:
            pass
        return _失败(_归类错误(错误), f"事务执行失败，已回滚：{错误}")
    finally:
        _释放(连接对象)


def 关闭(连接串: str) -> 结果:
    if (问题 := _校验连接串(连接串)):
        return _失败(错误码_参数不合法, 问题)
    if not _驱动可用:
        return _失败(错误码_提供者不可用, "pg8000 驱动未安装，提供者不可用")
    连接对象 = None
    try:
        连接对象 = _打开(连接串, 3.0)
        return 结果.成功结果({"已关闭": True})
    except Exception as 错误:
        return _失败(_归类错误(错误), f"关闭失败：{错误}")
    finally:
        _释放(连接对象)
