"""迁移互斥编排器：真实 sqlite 写锁（BEGIN IMMEDIATE）+ 元信息状态位，治理并发双迁移。

两个真实进程同时迁移同一存储时只允许一个推进；另一个等待后复用结果或明确冲突；
不产生双写与半状态；迁移中途失败整体回滚到迁移前状态。"""
from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any

忙碌超时毫秒 = 3000


class 迁移互斥编排器:
    数据库文件名 = "迁移状态.db"
    步骤延迟秒 = 0.0
    迁移步骤表 = [("步骤1_建表", "_步骤1_建表"), ("步骤2_写入记录", "_步骤2_写入记录"),
                   ("步骤3_追加列", "_步骤3_追加列")]

    def __init__(self, 存储目录: str | Path) -> None:
        self.存储目录 = Path(存储目录)
        self.存储目录.mkdir(parents=True, exist_ok=True)
        self._连接: sqlite3.Connection | None = None

    def _打开(self) -> sqlite3.Connection:
        if self._连接 is None:
            self._连接 = sqlite3.connect(
                str(self.存储目录 / self.数据库文件名),
                timeout=忙碌超时毫秒 / 1000)
            self._连接.execute(f"PRAGMA busy_timeout = {忙碌超时毫秒}")
        return self._连接

    def 执行迁移(self, 迁移任务id: str) -> tuple[str, str]:
        """并发互斥迁移主流程；返回 (结果, 状态)：推进/复用/冲突/失败。"""
        连接 = self._打开()
        记录 = self._读状态(连接)
        if 记录 and 记录.get("状态") == "迁移中" and 记录.get("任务id") != 迁移任务id:
            return "冲突", "冲突"  # 他人迁移中：明确冲突，不并发推进
        if 记录 and 记录.get("状态") == "已完成" and self._结构就位(连接):
            return "复用", "已完成"  # 已完成：直接复用结果
        try:
            连接.execute("BEGIN IMMEDIATE")  # 真实数据库级排他写锁
        except sqlite3.OperationalError as 错误:
            if "locked" not in str(错误):
                raise
            连接.rollback()
            return "冲突", "冲突"  # 写锁等待超时：明确冲突
        记录 = self._读状态(连接)
        if 记录 is None or 记录.get("状态") == "失败":
            return self._抢占并迁移(连接, 迁移任务id)
        if 记录.get("状态") == "已完成":
            if not self._结构就位(连接):
                return self._抢占并迁移(连接, 迁移任务id)
            连接.rollback()
            return "复用", "已完成"  # 等锁后确认已完成：复用结果
        if 记录.get("任务id") != 迁移任务id:
            连接.rollback()
            return "冲突", "冲突"  # 锁内兜底：他人迁移中残留
        连接.rollback()
        return self._中断残留(连接, 迁移任务id)

    def _抢占并迁移(self, 连接, 迁移任务id: str) -> tuple[str, str]:
        连接.execute("CREATE TABLE IF NOT EXISTS 元信息(键 TEXT PRIMARY KEY, 值 TEXT)")
        self._写状态(连接, {"状态": "迁移中", "任务id": 迁移任务id, "开始时间": self._时间戳()})
        连接.execute("INSERT OR REPLACE INTO 元信息(键, 值) VALUES('迁移执行次数', ?)",
                     (str(self._次数(连接) + 1),))
        return self._推进或失败(连接, 迁移任务id)

    def _中断残留(self, 连接, 迁移任务id: str) -> tuple[str, str]:
        if self._结构就位(连接):
            self._写状态(连接, {"状态": "已完成", "任务id": 迁移任务id, "完成时间": self._时间戳()})
            连接.commit()
            return "复用", "已完成"
        连接.execute("INSERT OR REPLACE INTO 元信息(键, 值) VALUES('迁移执行次数', ?)",
                     (str(self._次数(连接) + 1),))
        return self._推进或失败(连接, 迁移任务id)

    def _推进或失败(self, 连接, 迁移任务id: str) -> tuple[str, str]:
        try:
            self._执行迁移步骤(连接)
        except Exception as 错误:
            连接.rollback()  # 整体回滚到迁移前（半状态防护）
            连接.execute("CREATE TABLE IF NOT EXISTS 元信息(键 TEXT PRIMARY KEY, 值 TEXT)")
            self._写状态(连接, {"状态": "失败", "任务id": 迁移任务id,
                               "错误": str(错误), "时间": self._时间戳()})
            连接.commit()  # 失败记录单独提交，不随回滚丢失
            return "失败", "失败"
        self._写状态(连接, {"状态": "已完成", "任务id": 迁移任务id, "完成时间": self._时间戳()})
        连接.commit()
        return "推进", "已完成"

    def _执行迁移步骤(self, 连接) -> None:
        for 步骤名, 方法名 in self.迁移步骤表:
            连接.execute("INSERT OR REPLACE INTO 元信息(键, 值) VALUES('迁移进度', ?)", (步骤名,))
            getattr(self, 方法名)(连接)
            if self.步骤延迟秒:
                time.sleep(self.步骤延迟秒)

    def _步骤1_建表(self, 连接) -> None:
        连接.execute("CREATE TABLE IF NOT EXISTS 迁移目标表(id TEXT PRIMARY KEY, 名称 TEXT, 版本 TEXT)")

    def _步骤2_写入记录(self, 连接) -> None:
        连接.execute("INSERT OR REPLACE INTO 迁移目标表(id, 名称, 版本) VALUES('版本1', '迁移验证记录', '1.0')")

    def _步骤3_追加列(self, 连接) -> None:
        列集合 = {行[1] for 行 in 连接.execute("PRAGMA table_info(迁移目标表)").fetchall()}
        if "扩展列" not in 列集合:
            连接.execute("ALTER TABLE 迁移目标表 ADD COLUMN 扩展列 TEXT")

    def _结构就位(self, 连接) -> bool:
        """迁移后结构校验：表存在、列齐全、记录存在，才算真实完成。"""
        try:
            表行 = 连接.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='迁移目标表'").fetchone()
            if 表行 is None:
                return False
            列集合 = {行[1] for 行 in 连接.execute("PRAGMA table_info(迁移目标表)").fetchall()}
            记录 = 连接.execute("SELECT 名称 FROM 迁移目标表 WHERE id='版本1'").fetchone()
            return {"id", "名称", "版本", "扩展列"} <= 列集合 and 记录 is not None
        except sqlite3.DatabaseError:
            return False

    def _写状态(self, 连接, 记录: dict[str, Any]) -> None:
        连接.execute("INSERT OR REPLACE INTO 元信息(键, 值) VALUES('迁移状态', ?)",
                     (json.dumps(记录, ensure_ascii=False),))

    def _读状态(self, 连接) -> dict[str, Any] | None:
        try:
            行 = 连接.execute("SELECT 值 FROM 元信息 WHERE 键='迁移状态'").fetchone()
        except sqlite3.OperationalError:
            return None
        try:
            return json.loads(行[0]) if 行 else None
        except (ValueError, TypeError):
            return {"状态": "未知"}

    def _次数(self, 连接) -> int:
        行 = 连接.execute("SELECT 值 FROM 元信息 WHERE 键='迁移执行次数'").fetchone()
        try:
            return int(行[0]) if 行 else 0
        except (ValueError, TypeError):
            return 0

    def _时间戳(self) -> str:
        return time.strftime("%Y-%m-%d %H:%M:%S")

    def 查询迁移状态(self) -> str:
        记录 = self._读状态(self._打开())
        return 记录.get("状态", "未开始") if 记录 else "未开始"

    def 清理(self) -> None:
        if self._连接 is not None:
            try:
                if self._连接.in_transaction:
                    self._连接.rollback()
            except sqlite3.Error:
                pass
            self._连接.close()
            self._连接 = None
