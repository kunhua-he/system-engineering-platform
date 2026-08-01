"""PostgreSQL 真实数据库提供者（提供者适配层）。

职责：真实连接/连接超时/查询超时/事务回滚/断开重连/关闭释放；
无驱动/无连接串/连接失败一律明确返回宿主不可用（HOST_UNAVAILABLE）。
驱动：psycopg2 → psycopg → pg8000；psql 仅如实上报。
"""
from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass, field
from typing import Any

错误码_宿主不可用 = "HOST_UNAVAILABLE"
错误码_超时 = "超时"
错误码_内部错误 = "内部错误"
驱动模块表 = ("psycopg2", "psycopg", "pg8000")

def _探测驱动() -> dict[str, bool]:
    """如实检测驱动：模块真实导入 + psql 命令探活，绝不猜测。

    使用静态导入（try/except 捕获 ImportError），不动态导入（依赖防火墙禁止）。
    """
    try:
        import psycopg2  # noqa: F401
        psycopg2可用 = True
    except ImportError:
        psycopg2可用 = False
    try:
        import psycopg  # noqa: F401
        psycopg可用 = True
    except ImportError:
        psycopg可用 = False
    try:
        import pg8000  # noqa: F401
        pg8000可用 = True
    except ImportError:
        pg8000可用 = False
    结果 = {"psycopg2": psycopg2可用, "psycopg": psycopg可用,
            "pg8000": pg8000可用, "psql命令行": False}
    try:
        subprocess.run(["psql", "--version"], capture_output=True, timeout=3)
        结果["psql命令行"] = True
    except Exception:
        pass
    return 结果


def _归类错误(错误: BaseException) -> str:
    文本 = str(错误)
    if "canceling statement" in 文本 or "timeout" in 文本.lower():
        return 错误码_超时
    if "connection refused" in 文本 or "could not connect" in 文本:
        return 错误码_宿主不可用
    return 错误码_内部错误


def _解析URL(连接串: str) -> dict:
    from urllib.parse import unquote, urlsplit
    if "://" not in 连接串:
        raise ValueError("pg8000 仅支持 postgresql:// 连接串")
    解析 = urlsplit(连接串)
    return {"host": 解析.hostname or "127.0.0.1", "port": 解析.port or 5432,
            "database": 解析.path.lstrip("/") or "postgres",
            "user": unquote(解析.username or "postgres"),
            "password": unquote(解析.password or "")}


@dataclass
class 提供结果:
    成功: bool
    值: Any = None
    错误码: str = ""
    错误说明: str = ""
    详情: dict[str, Any] = field(default_factory=dict)


class PostgreSQL提供者:
    def __init__(self, 连接串: str | None = None, 连接超时秒: float = 3.0,
                 查询超时秒: float = 5.0):
        连接串 = 连接串 if 连接串 is not None else os.environ.get("PG_DSN", "")
        self.连接串 = 连接串 or ""
        self.连接超时秒 = max(1.0, 连接超时秒)
        self.查询超时秒 = max(0.5, 查询超时秒)
        self.驱动表 = _探测驱动()
        self.驱动名 = next((名 for 名 in 驱动模块表 if self.驱动表.get(名)), "")
        self.连接 = None

    def 检测(self) -> 提供结果:
        if not self.驱动名 or not self.连接串:
            return 提供结果(False, 错误码=错误码_宿主不可用,
                            错误说明="未检测到可用驱动或未提供连接串（PG_DSN 未设置），当前宿主不可用",
                            详情={"驱动表": self.驱动表})
        连接结果 = self.打开连接()
        if not 连接结果.成功:
            return 提供结果(False, 错误码=错误码_宿主不可用,
                            错误说明=f"真实连接失败，宿主不可用：{连接结果.错误说明}",
                            详情={"驱动表": self.驱动表, "驱动": self.驱动名})
        return 提供结果(True, 值={"驱动": self.驱动名, "驱动表": self.驱动表})

    def 打开连接(self) -> 提供结果:
        if not self.驱动名 or not self.连接串:
            return 提供结果(False, 错误码=错误码_宿主不可用, 错误说明="无可用驱动或无连接串，宿主不可用")
        try:
            if self.驱动名 == "psycopg2":
                import psycopg2
                连接 = psycopg2.connect(self.连接串, connect_timeout=int(self.连接超时秒))
            elif self.驱动名 == "psycopg":
                import psycopg
                连接 = psycopg.connect(self.连接串, connect_timeout=int(self.连接超时秒))
            else:
                import pg8000
                连接 = pg8000.connect(**_解析URL(self.连接串), timeout=self.连接超时秒)
        except Exception as 错误:
            return 提供结果(False, 错误码=_归类错误(错误),
                            错误说明=f"连接失败：{错误}", 详情={"驱动": self.驱动名})
        self.关闭()
        self.连接 = 连接
        if not (结果 := self._设置查询超时()).成功:
            self.关闭()
        return 结果

    def _设置查询超时(self) -> 提供结果:
        try:
            with self.连接.cursor() as 游标:
                游标.execute(f"SET statement_timeout = {int(self.查询超时秒 * 1000)}")
            self.连接.commit()
            return 提供结果(True, 值=self.驱动名)
        except Exception as 错误:
            return 提供结果(False, 错误码=_归类错误(错误), 错误说明=str(错误))

    def _运行(self, sql: str, 参数: tuple, 取行: bool) -> 提供结果:
        if self.连接 is None:
            return 提供结果(False, 错误码=错误码_宿主不可用, 错误说明="提供者未连接或已关闭，宿主不可用")
        try:
            with self.连接.cursor() as 游标:
                游标.execute(sql, 参数)
                值 = 游标.fetchall() if 取行 else 游标.rowcount
            return 提供结果(True, 值=值)
        except Exception as 错误:
            return 提供结果(False, 错误码=_归类错误(错误), 错误说明=str(错误))

    def 查询(self, sql: str, 参数: tuple = ()) -> 提供结果:
        return self._运行(sql, 参数, 取行=True)

    def 执行(self, sql: str, 参数: tuple = ()) -> 提供结果:
        return self._运行(sql, 参数, 取行=False)

    def _结束事务(self, 动作: str) -> 提供结果:
        if self.连接 is None:
            return 提供结果(False, 错误码=错误码_宿主不可用, 错误说明=f"未连接，无法{动作}")
        try:
            getattr(self.连接, 动作)()
            return 提供结果(True)
        except Exception as 错误:
            return 提供结果(False, 错误码=_归类错误(错误), 错误说明=str(错误))

    def 提交(self) -> 提供结果:
        return self._结束事务("commit")

    def 回滚(self) -> 提供结果:
        return self._结束事务("rollback")

    def 关闭(self) -> 提供结果:
        if self.连接 is None:
            return 提供结果(True, 错误说明="已处于关闭状态")
        try:
            self.连接.close()
            return 提供结果(True)
        except Exception as 错误:
            return 提供结果(False, 错误码=错误码_内部错误, 错误说明=str(错误))
        finally:
            self.连接 = None

    def 重连(self) -> 提供结果:
        关闭结果 = self.关闭()
        if not 关闭结果.成功:
            return 关闭结果
        return self.打开连接()
