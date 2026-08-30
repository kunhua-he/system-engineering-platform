"""SQLite 数据库提供者：有界连接池、事务隔离、超时中断与硬截止关闭。"""
from __future__ import annotations

import contextlib
import queue
import sqlite3
import threading
import time
import uuid
from concurrent.futures import Future, ThreadPoolExecutor, TimeoutError as 并发超时, wait
from pathlib import Path
from typing import Any, Callable

默认连接超时秒, 默认查询超时秒 = 5.0, 5.0
默认连接池大小, 默认关闭硬截止秒 = 4, 1.0
_资源锁表锁 = threading.Lock()
_资源锁表: dict[str, list[Any]] = {}


def _统一结果(成功, 结果=None, 错误码="", 消息=""):
    return {"成功": 成功, "结果": 结果, "错误码": 错误码, "消息": 消息}


def _资源键(库路径: str) -> str:
    return str(Path(库路径).expanduser().resolve())


def _取得写锁(键: str) -> threading.RLock:
    with _资源锁表锁:
        记录 = _资源锁表.setdefault(键, [threading.RLock(), 0])
        记录[1] += 1
        return 记录[0]


def _释放写锁(键: str) -> None:
    with _资源锁表锁:
        记录 = _资源锁表.get(键)
        if 记录 is None:
            return
        记录[1] -= 1
        if 记录[1] <= 0:
            del _资源锁表[键]


class _重连释放失败(RuntimeError):
    pass


class 数据库提供者:
    """每个 SQL 工作单元独占池连接；同库写事务按资源键排队。"""

    def __init__(self, 库路径: str | Path, 连接超时秒: float = 默认连接超时秒,
                 查询超时秒: float = 默认查询超时秒, *,
                 连接池大小: int = 默认连接池大小,
                 关闭硬截止秒: float = 默认关闭硬截止秒) -> None:
        if 连接池大小 < 1:
            raise ValueError("连接池大小必须大于零")
        self.库路径 = str(库路径)
        self.连接超时秒, self.查询超时秒 = 连接超时秒, 查询超时秒
        self.连接池大小, self.关闭硬截止秒 = 连接池大小, max(0.01, 关闭硬截止秒)
        self._连接: Any = None  # 保留首连接兼容诊断与真实断连注入
        self._连接表: list[Any] = []
        self._空闲连接: queue.LifoQueue[Any] = queue.LifoQueue(maxsize=连接池大小)
        self._连接锁, self._状态锁 = threading.RLock(), threading.RLock()
        self._任务锁 = threading.Lock()
        self._任务账本: dict[str, dict[str, Any]] = {}
        self._线程上下文 = threading.local()
        self._已关闭, self._执行器已关闭 = False, False
        self._执行器 = self._新执行器()
        self._任务槽 = threading.BoundedSemaphore(连接池大小 * 4)
        self._写资源键 = _资源键(self.库路径)
        self._写锁: threading.RLock | None = _取得写锁(self._写资源键)

    def _新执行器(self) -> ThreadPoolExecutor:
        return ThreadPoolExecutor(max_workers=self.连接池大小,
                                  thread_name_prefix="SQLite工作单元")

    def _新建连接(self) -> sqlite3.Connection:
        连接 = sqlite3.connect(self.库路径, timeout=self.连接超时秒,
                             check_same_thread=False)
        连接.isolation_level = ""
        连接.execute(f"PRAGMA busy_timeout={int(self.连接超时秒 * 1000)}")
        return 连接

    def _确保可提交(self) -> None:
        with self._状态锁:
            if self._已关闭:
                raise RuntimeError("数据库已关闭，句柄已释放")

    def _释放单连接(self, 连接: Any) -> None:
        错误表 = []
        try:
            if 连接.in_transaction:
                连接.rollback()
        except sqlite3.ProgrammingError as 错误:
            if "closed" not in str(错误).lower():
                错误表.append(f"回滚失败: {错误}")
        except Exception as 错误:
            错误表.append(f"回滚失败: {错误}")
        try:
            连接.close()
        except Exception as 错误:
            错误表.append(f"关闭失败: {错误}")
        if 错误表:
            raise _重连释放失败("；".join(错误表))

    def _释放全部连接(self) -> None:
        with self._连接锁:
            连接表 = ([] if self._连接 is None else [self._连接]) + [
                项 for 项 in self._连接表 if 项 is not self._连接]
            for 连接 in 连接表:
                self._释放单连接(连接)
            self._连接表.clear()
            self._空闲连接 = queue.LifoQueue(maxsize=self.连接池大小)
            self._连接 = None

    def _登记新连接(self) -> Any:
        连接 = self._新建连接()
        self._连接表.append(连接)
        if self._连接 is None:
            self._连接 = 连接
        return 连接

    def _替换失效连接(self, 旧连接: Any) -> Any:
        self._释放单连接(旧连接)
        with contextlib.suppress(ValueError):
            self._连接表.remove(旧连接)
        新连接 = self._登记新连接()
        if self._连接 is 旧连接:
            self._连接 = 新连接
        return 新连接

    def _借连接(self) -> Any:
        self._确保可提交()
        截止 = time.monotonic() + max(self.连接超时秒, 0.01)
        while True:
            with self._连接锁:
                try:
                    连接 = self._空闲连接.get_nowait()
                except queue.Empty:
                    if len(self._连接表) < self.连接池大小:
                        连接 = self._登记新连接()
                    else:
                        连接 = None
            if 连接 is None:
                剩余 = 截止 - time.monotonic()
                if 剩余 <= 0:
                    raise TimeoutError("等待数据库连接池超时")
                try:
                    连接 = self._空闲连接.get(timeout=剩余)
                except queue.Empty as 错误:
                    raise TimeoutError("等待数据库连接池超时") from 错误
            try:
                连接.execute("SELECT 1")
                return 连接
            except sqlite3.Error:
                with self._连接锁:
                    return self._替换失效连接(连接)

    def _还连接(self, 连接: Any) -> None:
        with self._连接锁:
            if self._已关闭 or 连接 not in self._连接表:
                with contextlib.suppress(Exception):
                    self._释放单连接(连接)
                return
            with contextlib.suppress(queue.Full):
                self._空闲连接.put_nowait(连接)

    def 连接(self, 库路径: str | Path | None = None, 连接超时秒: float | None = None,
             查询超时秒: float | None = None):
        with self._状态锁:
            新路径 = str(库路径) if 库路径 is not None else self.库路径
            try:
                if self._任务账本 and any(
                        not 项["未来"].done() for 项 in self._任务账本.values()):
                    return _统一结果(False, 错误码="RESOURCE_BUSY",
                                     消息="仍有数据库任务运行，不能替换连接")
                if self._连接 is not None or self._连接表:
                    self._释放全部连接()
                if 连接超时秒 is not None:
                    self.连接超时秒 = 连接超时秒
                if 查询超时秒 is not None:
                    self.查询超时秒 = 查询超时秒
                新资源键 = _资源键(新路径)
                if 新资源键 != self._写资源键:
                    if self._写锁 is not None:
                        _释放写锁(self._写资源键)
                    self._写资源键 = 新资源键
                    self._写锁 = _取得写锁(self._写资源键)
                elif self._写锁 is None:
                    self._写锁 = _取得写锁(self._写资源键)
                self.库路径 = 新路径
                if self._执行器已关闭:
                    self._执行器 = self._新执行器()
                    self._任务槽 = threading.BoundedSemaphore(self.连接池大小 * 4)
                    self._执行器已关闭 = False
                self._已关闭 = False
                with self._连接锁:
                    连接 = self._登记新连接()
                    self._空闲连接.put_nowait(连接)
                return _统一结果(True, 消息="数据库已连接")
            except _重连释放失败 as 错误:
                return _统一结果(False, 错误码="RECONNECT_RELEASE_FAILED",
                                 消息=f"旧连接释放失败，拒绝重连: {错误}")
            except sqlite3.Error as 错误:
                return _统一结果(False, 错误码="CONNECTION_FAILED",
                                 消息=f"连接数据库失败: {错误}")

    def _设置任务连接(self, 连接: Any | None) -> None:
        任务id = getattr(self._线程上下文, "任务id", "")
        if not 任务id:
            return
        with self._任务锁:
            if 任务id in self._任务账本:
                self._任务账本[任务id]["连接"] = 连接

    def _运行任务(self, 名称: str, 函数: Callable[[], Any]) -> Any:
        self._确保可提交()
        if not self._任务槽.acquire(timeout=max(self.连接超时秒, 0.01)):
            raise TimeoutError("数据库任务队列已满")
        任务id = uuid.uuid4().hex
        开始门 = threading.Event()

        def 包装():
            开始门.wait()
            self._线程上下文.任务id = 任务id
            try:
                return 函数()
            finally:
                self._线程上下文.任务id = ""

        try:
            未来 = self._执行器.submit(包装)
        except Exception:
            self._任务槽.release()
            raise RuntimeError("数据库已关闭，执行器拒绝新任务") from None
        with self._任务锁:
            self._任务账本[任务id] = {
                "名称": 名称, "状态": "运行中", "连接": None,
                "未来": 未来, "开始时间": time.monotonic(), "保留": False}
            # 账本有界：只裁掉已完成旧项，运行中/未收敛项绝不丢失。
            if len(self._任务账本) > 256:
                for 旧id, 旧记录 in sorted(
                        self._任务账本.items(), key=lambda 项: 项[1]["开始时间"]):
                    if 旧记录["未来"].done() and 旧id != 任务id:
                        del self._任务账本[旧id]
                    if len(self._任务账本) <= 256:
                        break
        开始门.set()

        def 完成(完成未来: Future):
            self._任务槽.release()
            with self._任务锁:
                记录 = self._任务账本.get(任务id)
                if 记录 is None:
                    return
                记录["状态"] = "已完成"
                if not 记录["保留"]:
                    del self._任务账本[任务id]
        未来.add_done_callback(完成)
        if self.查询超时秒 <= 0:
            return 未来.result()
        try:
            return 未来.result(timeout=self.查询超时秒)
        except 并发超时:
            with self._任务锁:
                记录 = self._任务账本.get(任务id)
                if 记录 is not None:
                    记录["状态"], 记录["保留"] = "请求中断", True
                    连接 = 记录["连接"]
                else:
                    连接 = None
            未来.cancel()
            if 连接 is not None:
                with contextlib.suppress(sqlite3.Error):
                    连接.interrupt()
            try:
                未来.result(timeout=min(max(self.查询超时秒, 0.05), 0.5))
            except Exception:
                pass
            if not 未来.done():
                with self._任务锁:
                    if 任务id in self._任务账本:
                        self._任务账本[任务id]["状态"] = "中断后未收敛"
            raise TimeoutError(f"{名称}超过 {self.查询超时秒} 秒，已请求中断") from None

    def _事务内连接(self) -> Any | None:
        return getattr(self._线程上下文, "事务连接", None)

    def _读工作(self, sql: str, 参数: tuple | list) -> list[dict[str, Any]]:
        事务连接 = self._事务内连接()
        连接 = 事务连接 or self._借连接()
        self._设置任务连接(连接)
        try:
            游标 = 连接.execute(sql, 参数)
            列名表 = [列[0] for 列 in (游标.description or ())]
            return [dict(zip(列名表, 行)) for 行 in 游标.fetchall()]
        finally:
            self._设置任务连接(None)
            if 事务连接 is None:
                self._还连接(连接)

    def _带写锁查询工作(self, sql: str, 参数: tuple | list) -> list[dict[str, Any]]:
        """查询接口收到写 SQL 时也按写资源键排队并独立提交。"""
        if self._事务内连接() is not None:
            return self._读工作(sql, 参数)
        if self._写锁 is None:
            raise RuntimeError("数据库已关闭，写资源锁已释放")
        with self._写锁:
            连接 = self._借连接()
            self._设置任务连接(连接)
            try:
                游标 = 连接.execute(sql, 参数)
                列名表 = [列[0] for 列 in (游标.description or ())]
                结果 = [dict(zip(列名表, 行)) for 行 in 游标.fetchall()]
                if 连接.in_transaction:
                    连接.commit()
                return 结果
            except Exception:
                with contextlib.suppress(sqlite3.Error):
                    连接.rollback()
                raise
            finally:
                self._设置任务连接(None)
                self._还连接(连接)

    @staticmethod
    def _是只读SQL(sql: str) -> bool:
        首词 = sql.lstrip().split(None, 1)[0].upper() if sql.strip() else ""
        return 首词 in {"SELECT", "PRAGMA", "EXPLAIN", "WITH"}

    def _写工作(self, sql: str, 参数: tuple | list) -> dict[str, Any]:
        事务连接 = self._事务内连接()
        if 事务连接 is not None:
            游标 = 事务连接.execute(sql, 参数)
            return {"影响行数": 游标.rowcount, "最后插入id": 游标.lastrowid}
        if self._写锁 is None:
            raise RuntimeError("数据库已关闭，写资源锁已释放")
        with self._写锁:
            连接 = self._借连接()
            self._设置任务连接(连接)
            try:
                游标 = 连接.execute(sql, 参数)
                if 连接.in_transaction:
                    连接.commit()
                return {"影响行数": 游标.rowcount, "最后插入id": 游标.lastrowid}
            except Exception:
                with contextlib.suppress(sqlite3.Error):
                    连接.rollback()
                raise
            finally:
                self._设置任务连接(None)
                self._还连接(连接)

    @staticmethod
    def _检查参数(参数: tuple | list) -> None:
        if not isinstance(参数, (tuple, list)):
            raise TypeError("参数必须是元组或列表")

    def 查询(self, sql: str, 参数: tuple | list = ()):
        try:
            self._检查参数(参数)
            工作函数 = self._读工作 if self._是只读SQL(sql) else self._带写锁查询工作
            函数 = lambda: 工作函数(sql, 参数)
            结果 = 函数() if self._事务内连接() is not None else self._运行任务("查询", 函数)
            return _统一结果(True, 结果=结果, 消息="查询成功")
        except Exception as 错误:
            return self._失败结果(错误)

    def 执行(self, sql: str, 参数: tuple | list = ()):
        try:
            self._检查参数(参数)
            函数 = lambda: self._写工作(sql, 参数)
            结果 = 函数() if self._事务内连接() is not None else self._运行任务("执行", 函数)
            return _统一结果(True, 结果=结果, 消息="执行成功")
        except Exception as 错误:
            return self._失败结果(错误)

    def 事务(self, 函数: Callable[[], Any]):
        def 工作():
            if self._写锁 is None:
                raise RuntimeError("数据库已关闭，写资源锁已释放")
            with self._写锁:
                连接 = self._借连接()
                self._设置任务连接(连接)
                self._线程上下文.事务连接 = 连接
                try:
                    连接.execute("BEGIN")
                    结果 = 函数()
                    连接.commit()
                    return 结果
                except Exception:
                    with contextlib.suppress(sqlite3.Error):
                        连接.rollback()
                    raise
                finally:
                    self._线程上下文.事务连接 = None
                    self._设置任务连接(None)
                    self._还连接(连接)
        try:
            return _统一结果(True, 结果=self._运行任务("事务", 工作), 消息="事务已提交")
        except Exception as 错误:
            return _统一结果(False, 错误码="TRANSACTION_FAILED", 消息=f"事务已回滚: {错误}")

    def _执行带超时(self, 函数: Callable[[], Any]) -> Any:
        return self._运行任务("事务", 函数)

    def 关闭(self):
        with self._状态锁:
            self._已关闭 = True
            with self._任务锁:
                记录表 = list(self._任务账本.values())
                for 记录 in 记录表:
                    记录["保留"] = True
            for 记录 in 记录表:
                记录["未来"].cancel()
                连接 = 记录.get("连接")
                if 连接 is not None:
                    with contextlib.suppress(sqlite3.Error):
                        连接.interrupt()
            if not self._执行器已关闭:
                self._执行器.shutdown(wait=False, cancel_futures=True)
                self._执行器已关闭 = True
        未完成 = [记录["未来"] for 记录 in 记录表 if not 记录["未来"].done()]
        if 未完成:
            _, 未收敛 = wait(未完成, timeout=self.关闭硬截止秒)
        else:
            未收敛 = set()
        释放错误 = ""
        try:
            self._释放全部连接()
        except _重连释放失败 as 错误:
            释放错误 = str(错误)
        if 未收敛:
            for 记录 in 记录表:
                if not 记录["未来"].done():
                    记录["状态"] = "关闭截止后未收敛"
            return _统一结果(False, 错误码="RESOURCE_NOT_CONVERGED",
                             消息=f"关闭硬截止 {self.关闭硬截止秒} 秒到期，"
                                f"仍有 {len(未收敛)} 个任务未收敛，账本已保留")
        if 释放错误:
            return _统一结果(False, 错误码="RELEASE_FAILED",
                             消息=f"数据库关闭时资源释放失败: {释放错误}")
        if self._写锁 is not None:
            _释放写锁(self._写资源键)
            self._写锁 = None
        return _统一结果(True, 消息="数据库已关闭，句柄已释放")

    def _失败结果(self, 错误: Exception):
        if isinstance(错误, _重连释放失败):
            return _统一结果(False, 错误码="RECONNECT_RELEASE_FAILED", 消息=str(错误))
        if isinstance(错误, TimeoutError):
            return _统一结果(False, 错误码="QUERY_TIMEOUT", 消息=str(错误))
        if isinstance(错误, RuntimeError):
            return _统一结果(False, 错误码="DATABASE_CLOSED", 消息=str(错误))
        if isinstance(错误, sqlite3.OperationalError) and "locked" in str(错误):
            return _统一结果(False, 错误码="DATABASE_LOCKED",
                             消息=f"数据库被占用，busy_timeout 到期: {错误}")
        if isinstance(错误, sqlite3.Error):
            return _统一结果(False, 错误码="SQL_ERROR", 消息=f"SQL 执行失败: {错误}")
        return _统一结果(False, 错误码="PROVIDER_ERROR", 消息=str(错误))


def 创建数据库能力函数(库路径: str | Path) -> Callable[[dict[str, Any]], dict[str, Any]]:
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
