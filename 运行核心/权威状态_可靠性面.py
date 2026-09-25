"""可靠性面：回收证据 / 引用计数 / WAL 检查点 / 备份 / 关闭 / 只读校验 / 损坏恢复。

**为什么独立成文件**（拆上帝文件 B1，2026-09-19）：本簇原住在
`运行核心/权威状态.py` 的 `权威状态` 类体内，是那个 1613 行文件里的一整块职责。
拆出只为让文件回到可维护尺寸，**对外零变化**：成员名、签名、默认值、正文
一个字符未改（搬动方式＝原样片段去 4 空格缩进），主类只改基类列表
（`class 权威状态(连接迁移面, 句柄租约面, 事务锁面, 资源与进程面, 可靠性面)`）。

`_校验目标库` / `_判定同一库` 只在 `损坏恢复` 的校验段被调用，故与 损坏恢复 同簇。

**导入方向**：本文件只被 `运行核心/权威状态.py` 模块级导入，**不得反向导入**
`运行核心/权威状态.py`（会成环）；本文件从主文件取的模块级件（如 `版本元组` /
`锁所有权判据` / `是并发冲突`）一律走**函数内延迟导入**并当场转发，唯一实现恒在
主文件一处，方向恒为主文件 → 本文件。
"""

from __future__ import annotations

import os
import shutil
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from 公共契约.诊断.忽略记录 import 记录忽略
from 公共契约.基础类型.逻辑类型 import 真, 假
from 公共契约.运行时.数据库连接 import 打开只读
from 公共契约.运行时.数据库URI import 连接真实库路径


class 可靠性面:
    def 记录回收证据(self, *, 句柄id: int, 资源id: str, 类型: str, 原因: str, 版本: str) -> None:
        连接 = self._连接()
        with 连接:
            连接.execute(
                "INSERT INTO 回收证据(证据id, 句柄id, 资源id, 类型, 失效原因, 时间, 版本) "
                "VALUES(?, ?, ?, ?, ?, ?, ?)",
                (uuid.uuid4().hex[:16], 句柄id, 资源id, 类型, 原因,
                 time.strftime("%Y-%m-%d %H:%M:%S"), 版本))


    def 查询回收证据(self, 资源id: str = "") -> list[dict[str, Any]]:
        连接 = self._连接()
        条件 = "WHERE 资源id=?" if 资源id else ""
        参数 = (资源id,) if 资源id else ()
        结果表 = []
        for 行 in 连接.execute(
                f"SELECT 句柄id, 资源id, 类型, 失效原因, 时间, 版本 FROM 回收证据 {条件}", 参数):
            结果表.append({"句柄id": 行[0], "资源id": 行[1], "类型": 行[2],
                          "失效原因": 行[3], "时间": 行[4], "版本": 行[5]})
        return 结果表


    def 增加引用(self, *, 包id: str, 版本: str) -> None:
        连接 = self._连接()
        with 连接:
            引用键 = f"{包id}@{版本}"
            连接.execute(
                "INSERT INTO 引用计数(引用键, 包id, 版本, 计数) VALUES(?, ?, ?, 1) "
                "ON CONFLICT(引用键) DO UPDATE SET 计数=计数+1",
                (引用键, 包id, 版本))


    def 减少引用(self, *, 包id: str, 版本: str) -> int:
        连接 = self._连接()
        with 连接:
            引用键 = f"{包id}@{版本}"
            连接.execute(
                "UPDATE 引用计数 SET 计数=MAX(0, 计数-1) WHERE 引用键=?", (引用键,))
            行 = 连接.execute("SELECT 计数 FROM 引用计数 WHERE 引用键=?", (引用键,)).fetchone()
            return 行[0] if 行 else 0


    def 引用数(self, *, 包id: str, 版本: str) -> int:
        连接 = self._连接()
        行 = 连接.execute("SELECT 计数 FROM 引用计数 WHERE 引用键=?", (f"{包id}@{版本}",)).fetchone()
        return 行[0] if 行 else 0


    def WAL检查点(self, 模式: str = "TRUNCATE") -> None:
        """WAL 检查点（TRUNCATE 合并回主库并清空 WAL 日志）；先提交活跃写入。"""
        for 连接 in list(self._连接表.values()):
            try:
                连接.commit()
            except sqlite3.OperationalError:
                pass
            try:
                连接.execute(f"PRAGMA wal_checkpoint({模式})")
            except sqlite3.OperationalError:
                pass


    def 备份(self, 目标路径: Path) -> bool:
        """原子备份数据库（含 WAL 日志）。"""
        try:
            self.WAL检查点("TRUNCATE")
            目标路径 = Path(目标路径)
            目标路径.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(self.数据库路径, 目标路径)
            return 目标路径.is_file()
        except (OSError, sqlite3.OperationalError):
            return 假


    def 关闭(self) -> None:
        """在没有其他活跃调用线程时关闭全部连接。"""
        当前线程 = threading.current_thread()
        with self._连接锁:
            活跃工作线程 = [
                线程 for 线程 in self._连接线程表.values()
                if 线程 is not 当前线程 and 线程.is_alive()
            ]
        if 活跃工作线程:
            raise RuntimeError("仍有工作线程正在使用权威状态，拒绝关闭数据库")
        self._清理死连接()
        self.WAL检查点("TRUNCATE")
        with self._连接锁:
            for 连接 in list(self._连接表.values()):
                try:
                    连接.close()
                except sqlite3.OperationalError:
                    pass
            self._连接表.clear()
            self._连接线程表.clear()


    def __del__(self) -> None:
        """对象异常离开生命周期时尽力关闭连接，避免解释器回收时报资源泄漏。"""
        try:
            连接表 = getattr(self, "_连接表", {})
            for 连接 in list(连接表.values()):
                try:
                    连接.close()
                except Exception as 错误:  # 允许忽略，但留痕（哲学第 3 条 2 项）
                    记录忽略('权威状态.__del__', 错误)
            连接表.clear()
            getattr(self, "_连接线程表", {}).clear()
        except Exception as 错误:  # 允许忽略，但留痕（哲学第 3 条 2 项）
            记录忽略('权威状态.__del__', 错误)


    def _校验目标库(self, 连接: sqlite3.Connection) -> None:
        """只读校验连接必须真的开在 `self.数据库路径` 上；否则抛 sqlite3.DatabaseError。

        为什么单列一条判据（P2-13③）：`PRAGMA integrity_check` 对**任何**容器的空库
        都返回 `ok`（含 SQLite 现场新建的空文件），拿它单独判完整性会**掩盖真实损坏**
        —— 只要连接开到别处（另一个库、截断出来的空库），它就恒过。

        两级判据，先精后宽（都是为了「既不放过错误库、也不冤枉正确库」，因为判红的
        后果是走备份覆盖 ⇒ 假红会拿旧备份盖掉好库）：
        1. `os.path.samefile` 比 **inode + 设备号**：同一文件的不同写法（软链接、
           `/var` 与 `/private/var`、`..` 段）全判等，这是「是不是同一个文件」的精确答案；
        2. 任一侧不存在时降级比**规范化路径双向包含**（`abspath`/`realpath` 各一份，
           任一命中即算等）。

        路径判据里禁止出现 `#`/`?` 这类**拼进 URI 就会被改写语义**的字符（哲学第 2 条 2 项）：
        这里的比对全在文件系统路径层做，URI 编码只发生在 `只读库URI()` 一处。
        """
        目标 = str(self.数据库路径)
        自报 = 连接真实库路径(连接)
        if 自报 and self._判定同一库(目标, 自报):
            return
        # 用 sqlite3.DatabaseError 而不是 RuntimeError：本方法专为「损坏恢复」的
        # 校验段服务，语义就是「这个连接不可信 ⇒ 当作数据库不可用」，
        # 复用既有的损坏→备份恢复分支，不新增未处理异常类型。
        raise sqlite3.DatabaseError(
            f"只读校验连接未开在目标库: 目标={os.path.realpath(目标)} "
            f"实际={os.path.realpath(自报) if 自报 else '（空）'}")


    @staticmethod
    def _判定同一库(目标: str, 自报: str) -> bool:
        """两个路径是否指向同一个库文件（同 inode 优先，路径双向包含兜底）。"""
        try:
            if os.path.samefile(目标, 自报):
                return 真
        except OSError:
            pass  # 任一侧不存在（如截断出来又没建成的前缀）→ 降级比路径
        for 规约 in (os.path.abspath, os.path.realpath):
            规约目标, 规约自报 = 规约(目标), 规约(自报)
            if 规约目标 in 规约自报 or 规约自报 in 规约目标:
                return 真
        return 假


    def 校验结构(self) -> tuple[bool, str]:
        """结构校验：版本一致 + 必需列齐全 + integrity_check 返回 ok。"""
        try:
            连接 = self._连接()
            with 连接:
                self._校验版本结构(连接, self.目标版本)
                行 = 连接.execute("SELECT 值 FROM 元信息 WHERE 键='结构版本'").fetchone()
                if not 行 or 行[0] != self.目标版本:
                    return 假, f"结构版本不一致: {行[0] if 行 else '无'}"
            return 真, "结构完整"
        except Exception as 错误:
            return 假, str(错误)


    def 损坏恢复(self, 备份目录: Path | None = None) -> tuple[bool, str]:
        """数据库损坏恢复：integrity_check 返回 ok 才认为完整；损坏则从最新备份恢复。

        恢复后重新校验 结构版本/必需列/完整性，再允许继续运行。

        判据顺序（P2-13③，2026-09-18 收口）：① 只读连接必须真开在目标库上
        （`_校验目标库`，先拆「连到空库」这种掩盖）→ ② 才看 `integrity_check`。
        顺序不能反：空库的完整性检查恒返回 `ok`，先看它就等于给假绿开门
        （类 docstring 第 1 条）。
        """
        try:
            # 本处转调 `公共契约/运行时/数据库连接.py`：原
            # sqlite3.connect(只读库URI(self.数据库路径), uri=True) 且未显式传 timeout
            # 映射到档「打开只读(路径)」——默认超时 5.0 = stdlib 默认，行为不变；
            # uri=True 与只读 URI 由 打开只读 经 数据库URI 唯一口径自带。
            校验连接 = 打开只读(self.数据库路径)
            try:
                self._校验目标库(校验连接)
                结果 = 校验连接.execute("PRAGMA integrity_check").fetchone()
            finally:
                # 库损坏时 integrity_check 先抛 sqlite3.DatabaseError，原写法
                # 的 close() 在异常路径永不执行 ⇒ 「越需要恢复越漏连接」。
                # close 必须在 finally 里，只读校验连接不得泄漏。
                校验连接.close()
            if 结果 and 结果[0] == "ok":
                return 真, "数据库完整"
            raise sqlite3.DatabaseError(f"完整性检查: {结果}")
        except sqlite3.DatabaseError:
            pass
        备份目录 = Path(备份目录 or (self.存储目录 / "备份"))
        if not 备份目录.is_dir():
            return 假, "数据库损坏且无可用备份"
        for 备份文件 in sorted(备份目录.glob("*.db"), reverse=True):
            try:
                shutil.copy(备份文件, self.数据库路径)
                for 连接 in list(self._连接表.values()):
                    try:
                        连接.close()
                    except sqlite3.Error:
                        pass
                self._连接表.clear()
                self._连接线程表.clear()
                # 恢复后重新校验结构
                成功, 消息 = self.校验结构()
                if not 成功:
                    return 假, f"备份恢复后结构校验失败: {消息}"
                return 真, f"已从备份恢复: {备份文件.name}"
            except (OSError, sqlite3.OperationalError):
                continue
        return 假, "数据库损坏且所有备份恢复失败"
