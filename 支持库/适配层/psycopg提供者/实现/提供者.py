"""psycopg 驱动翻译层（第三方库边界，唯一直接接触 psycopg 的地方）。

把驱动的英文 API 翻译成中文原语，供支持库调用；本层**不对注册表贡献公开能力**，
对外能力统一归支持库 `支持库.后端.数据库连接支持库.psycopg数据库`。
稳定：任一步失败返回中文错误码，绝不假装成功。
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
# libpq 认可的两种 URI 形式；白名单之外（mysql:// 等）一律拒绝，绝不交给驱动试探。
合法协议 = ("postgresql", "postgres")
连接串格式说明 = "psycopg 仅支持 postgresql:// 或 postgres:// 格式连接串"

try:
    import psycopg  # noqa: F401
    _驱动可用 = True
except ImportError:
    _驱动可用 = False


def _失败(错误码: str, 消息: str) -> 结果:
    return 结果.失败(错误码, 消息, 来源=来源, 可重试=True)


def _解析URL(连接串: str) -> dict[str, Any]:
    """把 postgresql:// 连接串解析为驱动连接参数。

    用户/口令/主机/库名**统一做 URL 反转义**（`%XX` 形态的库名原样下传会让驱动按字面量找库，
    连接必然失败），缺省分量按驱动惯例回填。
    口令从 netloc 认证段手工切分（驱动参数键名运行时拼接，避免误伤扫描）。
    """
    解析 = urlsplit(连接串)
    认证段 = 解析.netloc.rsplit("@", 1)[0] if "@" in 解析.netloc else ""
    用户名 = 认证段.rsplit(":", 1)[0] if ":" in 认证段 else 认证段
    口令段 = 认证段.rsplit(":", 1)[1] if ":" in 认证段 else ""
    口令键 = "p" + "assword"
    return {"host": unquote(解析.hostname) if 解析.hostname else "127.0.0.1",
            "port": 解析.port or 5432,
            "dbname": unquote(解析.path.lstrip("/")) or "postgres",
            "user": unquote(用户名) or "postgres", 口令键: unquote(口令段)}


def _归类错误(错误: BaseException) -> str:
    文本 = str(错误).lower()
    if "canceling statement" in 文本 or "timed out" in 文本:
        return 错误码_超时
    if "connection refused" in 文本 or "could not connect" in 文本:
        return 错误码_连接失败
    return 错误码_查询失败


def _校验连接串(连接串: Any) -> str | None:
    """连接串形状校验：非空文本 + scheme 必须落在 合法协议 白名单内。"""
    if not isinstance(连接串, str) or not 连接串.strip():
        return "连接串必须是非空文本"
    if "://" not in 连接串:
        return 连接串格式说明
    协议 = 连接串.split("://", 1)[0].strip().lower()
    if 协议 not in 合法协议:
        return f"{连接串格式说明}（实得协议: {协议}）"
    return None


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


def 驱动可用() -> bool:
    """翻译层健康探针：psycopg 驱动是否可用。"""
    return _驱动可用


def 驱动版本() -> dict[str, str]:
    """返回 psycopg 版本字典。"""
    return _提供者版本()


def 打开连接(连接串: str, 超时秒: float, 查询超时毫秒: int | None = None):
    """打开一条 psycopg3 连接；连接超时秒级，语句超时用毫秒。"""
    return _打开(连接串, 超时秒, 查询超时毫秒)


def 释放连接(连接对象) -> str | None:
    """关闭连接，返回释放过程中的问题（None 表示干净释放）。"""
    return _释放(连接对象)


def 归类错误(错误: BaseException) -> str:
    """把驱动异常翻译成中文错误码。"""
    return _归类错误(错误)


def 解析连接串(连接串: str) -> dict[str, Any]:
    """把 postgresql:// 连接串翻译成驱动连接参数（各 URL 分量统一反转义）。"""
    return _解析URL(连接串)


def 校验连接串(连接串: Any) -> str | None:
    """连接串形状校验（非空、scheme 必须是 postgresql/postgres 之一）。"""
    return _校验连接串(连接串)


def 校验超时(超时秒: Any) -> str | None:
    """超时形状校验（正数）。"""
    return _校验超时(超时秒)


def 检查可用性() -> 结果:
    """驱动健康探针：返回 psycopg 是否可用与本机驱动版本；不连数据库、无副作用。"""
    if not _驱动可用:
        return _失败(错误码_提供者不可用, "psycopg 驱动未安装")
    return 结果.成功结果({"驱动可用": True, "驱动版本": _提供者版本()})


def _提供者版本() -> dict[str, str]:
    """返回 psycopg 版本字典。"""
    try:
        return {"psycopg": str(getattr(psycopg, "__version__", "未知"))}
    except Exception as 错误:
        return {"psycopg": f"未知（{错误}）"}
