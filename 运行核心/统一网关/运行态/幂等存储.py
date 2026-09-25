"""幂等存储：网关幂等记录的 SQLite 落地（跨进程重启不丢幂等判据）。

2026-09-19 从 `网关核心.py` 整块搬出（哲学 6.1：改动频率 × 读取成本）。
原处 `from 运行核心.统一网关.运行态.幂等存储 import 幂等存储, 幂等默认保留秒` 再导出，
对外符号零变化。

`幂等默认保留秒`（默认 TTL）随类一同搬来 —— 它是 `__init__` 的默认值，
在**类定义时**求值，留在原文件会让本模块 NameError。
"""
from __future__ import annotations
import sqlite3
import threading
import time
from pathlib import Path
from 公共契约.诊断.忽略记录 import 记录忽略
from 公共契约.基础类型.逻辑类型 import 真, 假
from 公共契约.运行时.数据库连接 import 打开


幂等默认保留秒 = 3600.0


class 幂等存储:
    """幂等记录的 SQLite 落地（跨进程重启不丢幂等判据）。

    就地建表，独立库文件，不改权威状态库（`平台控制面/平台状态/状态存储.py`）。
    每次操作开一条短连接：不做跨线程共享连接（SQLite 连接默认不许跨线程用），
    也就不需要额外锁；幂等库的读写量是「每个新请求id 一次」，短连接的代价可忽略。

    fail-soft：库打不开或读写失败一律当作「无持久记录」，只记忽略留痕。调用方
    （`网关核心`）据此回落纯内存幂等，不因幂等库故障拒服务。
    """

    建表语句 = (
        "CREATE TABLE IF NOT EXISTS 网关幂等记录 ("
        "请求id TEXT PRIMARY KEY, "
        "操作 TEXT NOT NULL, "
        "摘要 TEXT NOT NULL, "
        "响应 TEXT, "
        "写入时间 REAL NOT NULL, "
        "过期时间 REAL NOT NULL)"
    )
    # TTL 清理按 过期时间 扫，走索引避免全表扫。
    索引语句 = "CREATE INDEX IF NOT EXISTS 网关幂等记录_过期 ON 网关幂等记录(过期时间)"

    def __init__(self, 库路径: Path, *, 保留秒: float = 幂等默认保留秒) -> None:
        self.库路径 = Path(库路径)
        self.保留秒 = max(1.0, float(保留秒))
        self.读取失败数 = 0
        self.写入失败数 = 0
        self._已建表 = 假
        self._建表锁 = threading.Lock()

    def _连接(self) -> sqlite3.Connection:
        # 本处转调 `公共契约/运行时/数据库连接.py`：原 timeout=2.0 映射到档
        # 「打开(路径, 2.0)」——读路径，不建目录、不切 WAL，与原 sqlite3.connect 一致。
        return 打开(self.库路径, 2.0)

    def _确保表(self, 连接: sqlite3.Connection) -> None:
        if self._已建表:
            return
        with self._建表锁:
            if self._已建表:
                return
            连接.execute(self.建表语句)
            连接.execute(self.索引语句)
            连接.commit()
            self._已建表 = 真

    def 读取(self, 请求id: str) -> tuple[str, str | None] | None:
        """按请求id 取 (摘要, 响应JSON)；无记录 / 已过期 / 库不可用 → None。

        响应JSON 为 None 表示「操作已执行、但响应不可重放」（操作去重记录）。
        """
        现在 = time.time()
        try:
            self.库路径.parent.mkdir(parents=True, exist_ok=True)
            连接 = self._连接()
            try:
                self._确保表(连接)
                行 = 连接.execute(
                    "SELECT 摘要, 响应 FROM 网关幂等记录 WHERE 请求id = ? AND 过期时间 > ?",
                    (请求id, 现在),
                ).fetchone()
            finally:
                连接.close()
        except (sqlite3.Error, OSError) as 错误:
            self.读取失败数 += 1
            记录忽略("统一网关.幂等存储.读取", 错误)
            return None
        if 行 is None:
            return None
        return str(行[0]), (None if 行[1] is None else str(行[1]))

    def 写入(self, 请求id: str, 操作: str, 摘要: str, 响应JSON: str | None) -> None:
        """写一条幂等记录，并顺手清掉已过期行（TTL）。"""
        现在 = time.time()
        try:
            self.库路径.parent.mkdir(parents=True, exist_ok=True)
            连接 = self._连接()
            try:
                self._确保表(连接)
                连接.execute("DELETE FROM 网关幂等记录 WHERE 过期时间 <= ?", (现在,))
                连接.execute(
                    "INSERT INTO 网关幂等记录(请求id, 操作, 摘要, 响应, 写入时间, 过期时间)"
                    " VALUES(?, ?, ?, ?, ?, ?)"
                    " ON CONFLICT(请求id) DO UPDATE SET"
                    " 操作=excluded.操作, 摘要=excluded.摘要, 响应=excluded.响应,"
                    " 写入时间=excluded.写入时间, 过期时间=excluded.过期时间",
                    (请求id, 操作, 摘要, 响应JSON, 现在, 现在 + self.保留秒),
                )
                连接.commit()
            finally:
                连接.close()
        except (sqlite3.Error, OSError) as 错误:
            self.写入失败数 += 1
            记录忽略("统一网关.幂等存储.写入", 错误)
