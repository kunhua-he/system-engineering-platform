"""SQLite 真实数据库提供者：真实连接/超时/事务/重连/释放。

契约接口（统一结果 {成功, 结果, 错误码, 消息}）：连接(库路径) 真实连接 +
PRAGMA busy_timeout；查询/执行(sql, 参数) 参数绑定 + 超时 interrupt 真实中断，
写语句独立自动提交；事务(fn) BEGIN + with 连接 原子提交/回滚；关闭() 释放句柄
后操作拒绝；连接失效自动重连。
"""
from __future__ import annotations

import contextlib
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor, TimeoutError as 并发超时
from pathlib import Path
from typing import Any, Callable

默认连接超时秒, 默认查询超时秒 = 5.0, 5.0


def _统一结果(成功, 结果=None, 错误码="", 消息=""):
    return {"成功": 成功, "结果": 结果, "错误码": 错误码, "消息": 消息}


class 数据库提供者:
    """SQLite 提供者：单连接复用 + 失效自动重连 + 真实超时/事务/释放。"""

    def __init__(self, 库路径: str | Path, 连接超时秒: float = 默认连接超时秒,
                查询超时秒: float = 默认查询超时秒) -> None:
        self.库路径 = str(库路径)
        self.连接超时秒, self.查询超时秒 = 连接超时秒, 查询超时秒
        self._连接: sqlite3.Connection | None = None
        self._已关闭 = False
        self._锁 = threading.RLock()
        self._执行器 = ThreadPoolExecutor(max_workers=1, thread_name_prefix="库查询")
        # 事务执行器独立于查询执行器：事务函数内部再走 _执行 提交查询时，
        # 若共用单线程执行器会形成嵌套死锁（事务函数占住线程等内部查询排队）
        self._事务执行器 = ThreadPoolExecutor(max_workers=1, thread_name_prefix="库事务")

    # ---- 内部：真实连接 / 失效自动重连 ----
    def _新建连接(self) -> sqlite3.Connection:
        连接 = sqlite3.connect(self.库路径, timeout=self.连接超时秒, check_same_thread=False)
        连接.isolation_level = ""
        连接.execute(f"PRAGMA busy_timeout={int(self.连接超时秒 * 1000)}")
        return 连接

    def _取连接(self) -> sqlite3.Connection:
        if self._已关闭:
            raise RuntimeError("数据库已关闭，句柄已释放")
        if self._连接 is None:
            self._连接 = self._新建连接()
        try:
            self._连接.execute("SELECT 1")
        except sqlite3.Error:
            self._连接 = self._新建连接()
        return self._连接

    # ---- 契约接口（全部返回统一结果结构） ----
    def 连接(self, 库路径: str | Path | None = None, 连接超时秒: float | None = None,
             查询超时秒: float | None = None):
        for 名称, 值 in (("库路径", 库路径), ("连接超时秒", 连接超时秒), ("查询超时秒", 查询超时秒)):
            if 值 is not None:
                setattr(self, 名称, str(值) if 名称 == "库路径" else 值)
        try:
            with self._锁:
                self._已关闭 = False
                self._连接 = self._新建连接()
            return _统一结果(True, 消息="数据库已连接")
        except sqlite3.Error as 错误:
            return _统一结果(False, 错误码="CONNECTION_FAILED", 消息=f"连接数据库失败: {错误}")

    def _执行(self, sql: str, 参数: tuple | list) -> sqlite3.Cursor:
        if not isinstance(参数, (tuple, list)):
            raise TypeError("参数必须是元组或列表")
        with self._锁:
            连接 = self._取连接()
            原先在事务 = 连接.in_transaction
            if self.查询超时秒 <= 0:
                游标 = 连接.execute(sql, 参数)
            else:
                未来 = self._执行器.submit(连接.execute, sql, 参数)
                try:
                    游标 = 未来.result(timeout=self.查询超时秒)
                except 并发超时:
                    with contextlib.suppress(sqlite3.Error):
                        连接.interrupt()
                    try:
                        with contextlib.suppress(Exception):
                            未来.result(timeout=self.查询超时秒)
                    except 并发超时:
                        # 二次超时：interrupt 未生效，连接可能已损坏，标记重建
                        self._连接 = None
                        raise TimeoutError(
                            f"查询超过 {self.查询超时秒} 秒，中断后仍未返回，连接将重建")
                    raise TimeoutError(f"查询超过 {self.查询超时秒} 秒，已真实中断")
            # 独立写语句自动提交；事务(fn) 内的写由 with 连接 统一提交/回滚
            if not 原先在事务 and 连接.in_transaction:
                连接.commit()
            return 游标

    def 查询(self, sql: str, 参数: tuple | list = ()):
        try:
            游标 = self._执行(sql, 参数)
            列名表 = [列[0] for 列 in (游标.description or ())]
            return _统一结果(True, 结果=[dict(zip(列名表, 行)) for 行 in 游标.fetchall()], 消息="查询成功")
        except Exception as 错误:
            return self._失败结果(错误)

    def 执行(self, sql: str, 参数: tuple | list = ()):
        try:
            游标 = self._执行(sql, 参数)
            return _统一结果(True, 结果={"影响行数": 游标.rowcount,
                                      "最后插入id": 游标.lastrowid}, 消息="执行成功")
        except Exception as 错误:
            return self._失败结果(错误)

    def 事务(self, 函数: Callable[[], Any]):
        try:
            with self._锁:
                连接 = self._取连接()
                连接.execute("BEGIN")
            with 连接:  # 提交/回滚由本线程统一执行（函数完成后）
                结果 = self._执行带超时(函数) if self.查询超时秒 > 0 else 函数()
            return _统一结果(True, 结果=结果, 消息="事务已提交")
        except Exception as 错误:
            return _统一结果(False, 错误码="TRANSACTION_FAILED", 消息=f"事务已回滚: {错误}")

    def _执行带超时(self, 函数: Callable[[], Any]) -> Any:
        """事务函数超时包装：独立事务执行器 + interrupt 真实中断兜底。

        BEGIN 后锁已释放，函数在独立事务执行器运行（不与查询执行器共用，
        防嵌套死锁）；函数内部的 _执行/查询 各自取锁，同一连接操作严格
        串行。超时后 interrupt 真实中断 SQL；二次超时标记连接需重建。
        """
        未来 = self._事务执行器.submit(函数)
        try:
            return 未来.result(timeout=self.查询超时秒)
        except 并发超时:
            with contextlib.suppress(sqlite3.Error):
                if self._连接 is not None:
                    self._连接.interrupt()
            try:
                with contextlib.suppress(Exception):
                    return 未来.result(timeout=self.查询超时秒)
            except 并发超时:
                # 二次超时：interrupt 未生效，连接可能已损坏，标记重建
                self._连接 = None
                raise TimeoutError(
                    f"事务函数超过 {self.查询超时秒} 秒，中断后仍未返回，连接将重建") from None
            raise TimeoutError(f"事务函数超过 {self.查询超时秒} 秒，已真实中断") from None

    def 关闭(self):
        with self._锁:
            self._已关闭 = True
            if self._连接 is not None:
                with contextlib.suppress(sqlite3.Error):
                    self._连接.close()
            self._连接 = None
            self._执行器.shutdown(wait=False)
            self._事务执行器.shutdown(wait=False)
        return _统一结果(True, 消息="数据库已关闭，句柄已释放")

    def _失败结果(self, 错误: Exception):
        if isinstance(错误, TimeoutError):
            return _统一结果(False, 错误码="QUERY_TIMEOUT", 消息=str(错误))
        if isinstance(错误, RuntimeError):
            return _统一结果(False, 错误码="DATABASE_CLOSED", 消息=str(错误))
        if isinstance(错误, sqlite3.OperationalError) and "locked" in str(错误):
            return _统一结果(False, 错误码="DATABASE_LOCKED", 消息=f"数据库被占用，busy_timeout 到期: {错误}")
        if isinstance(错误, sqlite3.Error):
            return _统一结果(False, 错误码="SQL_ERROR", 消息=f"SQL 执行失败: {错误}")
        return _统一结果(False, 错误码="PROVIDER_ERROR", 消息=str(错误))


def 创建数据库能力函数(库路径: str | Path) -> Callable[[dict[str, Any]], dict[str, Any]]:
    """工厂：返回可注册到 统一能力服务.注册提供者 的能力函数（统一契约）。"""
    提供者 = 数据库提供者(库路径)
    分发表 = {
        "连接": lambda 参数: 提供者.连接(),
        "查询": lambda 参数: 提供者.查询(参数.get("sql", ""), 参数.get("参数", ())),
        "执行": lambda 参数: 提供者.执行(参数.get("sql", ""), 参数.get("参数", ())),
        "事务": lambda 参数: 提供者.事务(参数.get("函数", lambda: None)),
        "关闭": lambda 参数: 提供者.关闭(),
    }

    def 能力函数(参数: dict[str, Any]) -> dict[str, Any]:
        操作 = 参数.get("操作", "")
        函数 = 分发表.get(操作)
        if 函数 is None:
            return _统一结果(False, 错误码="UNKNOWN_OPERATION", 消息=f"未知操作: {操作}")
        return 函数(参数)

    return 能力函数
