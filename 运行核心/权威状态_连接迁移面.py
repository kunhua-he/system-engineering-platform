"""连接迁移面：每线程连接管理 + 结构迁移器（初始化/迁移分离）。

**为什么独立成文件**（拆上帝文件 B1，2026-09-19）：本簇原住在
`运行核心/权威状态.py` 的 `权威状态` 类体内，是那个 1613 行文件里的一整块职责。
拆出只为让文件回到可维护尺寸，**对外零变化**：成员名、签名、默认值、正文
一个字符未改（搬动方式＝原样片段去 4 空格缩进），主类只改基类列表
（`class 权威状态(连接迁移面, 句柄租约面, 事务锁面, 资源与进程面, 可靠性面)`）。

连接池语义（每线程一条连接、死线程显式回收）与结构迁移序列表的唯一实现在本簇；
`_校验版本结构` / `_校验表存在` / `_校验列` 是**全仓结构校验的唯一事实源**
（`运行核心/运行状态监督/实现/只读状态库.py` 直接借一个未初始化实例调这三个方法），
搬动时一个字符未改。

**导入方向**：本文件只被 `运行核心/权威状态.py` 模块级导入，**不得反向导入**
`运行核心/权威状态.py`（会成环）；本文件从主文件取的模块级件（如 `版本元组` /
`锁所有权判据` / `是并发冲突`）一律走**函数内延迟导入**并当场转发，唯一实现恒在
主文件一处，方向恒为主文件 → 本文件。
"""

from __future__ import annotations

import contextlib
import json
import sqlite3
import threading
import time

from 公共契约.诊断.忽略记录 import 记录忽略
from 公共契约.基础类型.逻辑类型 import 真, 假
from 运行核心.sqlite错误码判据 import 迁移可重试主码


def 版本元组(版本: str) -> tuple[int, ...]:
    """版本字符串 → 比较元组（唯一实现在 `运行核心/权威状态.py`）。

    为什么是延迟取而不是模块级 `from … import 版本元组`：本文件被
    `运行核心/权威状态.py` 导入（它要拿本类当基类），模块级反向导入会成环；
    延迟导入在任何导入顺序下都成立，且不复制任何判据逻辑。
    """
    from 运行核心.权威状态 import 版本元组 as _唯一实现
    return _唯一实现(版本)


def sqlite主错误码(错误: BaseException) -> int:
    """取 sqlite 主错误码（唯一实现在 `运行核心/权威状态.py`）。

    为什么是延迟取而不是模块级 `from … import sqlite主错误码`：本文件被
    `运行核心/权威状态.py` 导入（它要拿本类当基类），模块级反向导入会成环；
    延迟导入在任何导入顺序下都成立，且不复制任何判据逻辑（本函数只有
    一行延迟导入 + 一行转发）。
    """
    from 运行核心.权威状态 import sqlite主错误码 as _唯一实现
    return _唯一实现(错误)


class 连接迁移面:
    def _连接(self) -> sqlite3.Connection:
        """返回当前线程的独立连接；连接回收只能在显式维护点执行。"""
        线程id = threading.get_ident()
        当前线程 = threading.current_thread()
        with self._连接锁:
            原线程 = self._连接线程表.get(线程id)
            if 原线程 is not None and 原线程 is not 当前线程:
                # 操作系统可复用已退出线程的 id；此时旧连接已无调用者。
                self._连接表[线程id].close()
                del self._连接表[线程id]
                del self._连接线程表[线程id]
            if 线程id not in self._连接表:
                连接 = sqlite3.connect(
                    str(self.数据库路径), timeout=10, check_same_thread=False)
                # busy_timeout 必须先于 WAL/写操作设置，否则并发下 PRAGMA 立即 locked
                连接.execute("PRAGMA busy_timeout=5000")  # 写竞争自动等待（WAL）
                连接.execute("PRAGMA journal_mode=WAL")
                连接.execute("PRAGMA synchronous=NORMAL")
                self._连接表[线程id] = 连接
                self._连接线程表[线程id] = 当前线程
            return self._连接表[线程id]


    @contextlib.contextmanager
    def _事务(self, 连接: sqlite3.Connection | None = None):
        """交出「本次写入用的事务边界」；已在事务中则**复用**，不嵌套、不提前提交。

        A1 根因：嵌套调用 `回收租约()` / `失效句柄()` 原先各自 `self._连接()` 并
        `with 连接`——内层退出即提交**外层**事务，外层原子性被破坏（已实证：外层
        中途抛异常后内层改动仍落盘：锁已删、租约已回收、句柄已失效、证据已写，
        而外层事务仍标「进行中」）。三种情形各有出口：

        - 传 `连接`（本文件内部调用点，如 `清理死亡进程资源`）：复用同一连接，
          提交/回滚由最外层 `with 连接` 统一决定；
        - 不传且当前线程连接**已在事务中**（外层已写过、正处在 `with 连接:` 里）：
          同样只交出连接、不提交也不结束事务——把「内层提前提交外层」这个隐蔽
          破坏兜死。外层没写过任何东西时连接尚未进入事务，内层按自身事务收口，
          此时外层也没有可被破坏的写入；
        - 不传且无活动事务（普通公开调用）：按普通事务起止，与原先行为一致。
        """
        连接 = self._连接() if 连接 is None else 连接
        if 连接.in_transaction:
            yield 连接  # 已在事务中：复用，提交/回滚交给最外层
            return
        with 连接:
            yield 连接


    def _清理死连接(self) -> None:
        """显式回收已结束线程的连接；普通读取路径不得调用本方法。"""
        with self._连接锁:
            for 线程id, 线程 in list(self._连接线程表.items()):
                if not 线程.is_alive():
                    self._连接表[线程id].close()
                    del self._连接表[线程id]
                    del self._连接线程表[线程id]


    def 释放当前线程连接(self) -> None:
        """关闭并移除当前线程的缓存连接（供长驻后台维护线程在两次任务之间让出连接）。

        长驻线程（如账本周期维护）若一直持有线程级连接，会让 关闭() 的
        「仍有工作线程正在使用权威状态」判据在退出时误报。维护线程每轮收尾
        调用本方法，退出路径只剩正在执行的那一次，不阻塞正常关闭。
        """
        线程id = threading.get_ident()
        with self._连接锁:
            连接 = self._连接表.pop(线程id, None)
            self._连接线程表.pop(线程id, None)
        if 连接 is None:
            return
        try:
            连接.close()
        except sqlite3.Error as 错误:  # 允许忽略，但留痕（哲学第 3 条 2 项）
            记录忽略('权威状态.释放当前线程连接', 错误)


    def _初始化(self) -> None:
        """打开数据库并执行结构迁移；数据库损坏时自动从备份恢复后再初始化。"""
        with self._本地锁:
            try:
                # 迁移脚本包含历史 DDL；旧版本 SQLite 的 executescript 可能在
                # 并发进程间短暂暴露中间 schema。对可恢复的 schema 竞态重试，
                # 其它迁移错误仍立即失败，避免吞掉真实损坏。
                # P1-6（2026-09-18 硬化）：可恢复性判 **sqlite 错误码**（原始异常由
                # `_迁移结构` 挂在 `__cause__` 上），禁止解析 sqlite 英文消息文本。
                for 次数 in range(4):
                    try:
                        self._迁移结构()
                        break
                    except RuntimeError as 错误:
                        原因 = 错误.__cause__
                        可恢复 = (isinstance(原因, sqlite3.OperationalError)
                                  and sqlite主错误码(原因) in 迁移可重试主码)
                        if not 可恢复 or 次数 == 3:
                            raise
                        time.sleep(0.05 * (次数 + 1))
            except sqlite3.DatabaseError:
                # 数据库损坏：自动恢复（损坏恢复内部重新校验结构后再允许运行）
                成功, 消息 = self.损坏恢复()
                if not 成功:
                    raise RuntimeError(
                        f"权威状态数据库损坏且自动恢复失败: {消息}")
                self._迁移结构()
            self._注册进程()


    def _迁移结构(self) -> None:
        """结构迁移主入口：BEGIN IMMEDIATE 串行化 + 固定迁移序列表。

        支持：全新空库、真实旧库升级、中断迁移恢复、假升级错误历史补列、
        重复迁移幂等、多进程并发迁移。
        """
        连接 = self._连接()
        with 连接:
            # 串行化：并发迁移只允许一个进程执行，其余等待后看到新版本跳过
            连接.execute("BEGIN IMMEDIATE")
            try:
                # 元信息表是版本记录的载体，任何迁移前必须存在（幂等）
                连接.execute("CREATE TABLE IF NOT EXISTS 元信息(键 TEXT PRIMARY KEY, 值 TEXT)")
                行 = 连接.execute("SELECT 值 FROM 元信息 WHERE 键='结构版本'").fetchone()
                当前版本 = 行[0] if 行 else "0.0.0"
                目标版本 = self.目标版本
                目标元组 = 版本元组(目标版本)
                # 假升级检测：元信息已写高版本但列缺失（错误历史状态）→ 重新执行到目标
                需要补列 = 当前版本 == 目标版本 and not self._校验当前结构(连接)
                if 需要补列:
                    当前版本 = "0.0.0"  # 按序重放，幂等 ALTER 补齐缺失列
                for 目标, 函数名 in self.迁移序列表:
                    目标_元组 = 版本元组(目标)
                    if 版本元组(当前版本) < 目标_元组:
                        try:
                            getattr(self, 函数名)(连接)
                            self._校验版本结构(连接, 目标)
                        except Exception as 错误:
                            # 迁移失败：回滚部分迁移 + 保留旧版本 + 写持久失败证据
                            # （证据必须单独提交，禁止随回滚丢失——任务信三.3）
                            连接.rollback()
                            连接.execute(
                                "INSERT OR REPLACE INTO 元信息(键, 值) VALUES('迁移失败', ?)",
                                (json.dumps({"版本": 当前版本, "目标": 目标,
                                             "错误": str(错误), "时间": time.strftime("%Y-%m-%d %H:%M:%S")},
                                            ensure_ascii=False),))
                            连接.commit()
                            raise RuntimeError(
                                f"结构迁移失败 {当前版本}→{目标}: {错误}（已回滚，版本保持 {当前版本}）"
                            ) from 错误
                        连接.execute("INSERT OR REPLACE INTO 元信息(键, 值) VALUES('结构版本', ?)", (目标,))
                # for 循环后兜底：版本匹配但结构不完整的错误历史状态无法修复时失败。
                # 原判据 `版本元组(状态结构版本) < 版本元组("1.0.0")` 拿模块常量
                # 状态结构版本("1.2.0") 与 "1.0.0" 比，恒为 (1,2,0)<(1,0,0)=False，
                # 整个兜底是死分支——假升级重放迁移后结构仍不完整也会被静默放行。
                # 按原意改为「重放后复验结构」：仍不完整即说明现有迁移序列表修不好它。
                if 需要补列 and not self._校验当前结构(连接):
                    raise RuntimeError(
                        f"结构校验失败: 元信息版本已是 {目标版本} 但表结构不完整，"
                        f"按序重放迁移后仍未补齐")
                连接.execute("DELETE FROM 元信息 WHERE 键='迁移失败'")
            except Exception:
                连接.rollback()
                raise


    def _校验当前结构(self, 连接: sqlite3.Connection) -> bool:
        """当前版本完整结构校验（列齐全才认为版本真实）。"""
        try:
            self._校验版本结构(连接, self.目标版本)
            return 真
        except RuntimeError:
            return 假


    def _校验版本结构(self, 连接: sqlite3.Connection, 版本: str) -> None:
        """按 校验规则表 校验指定版本要求的表、列与完整性；不满足抛 RuntimeError。

        规则表按版本号升序执行所有 <= 目标版本的规则，子类可扩展规则表。
        """
        目标元组 = 版本元组(版本)
        for 规则版本 in sorted(self.校验规则表, key=版本元组):
            if 版本元组(规则版本) > 目标元组:
                continue
            规则 = self.校验规则表[规则版本]
            for 表 in 规则.get("表", []):
                self._校验表存在(连接, 表)
            for 表, 列 in 规则.get("列", []):
                self._校验列(连接, 表, 列)
        # 完整性检查必须读取返回值并判断 ok
        结果 = 连接.execute("PRAGMA integrity_check").fetchone()
        if not 结果 or 结果[0] != "ok":
            raise RuntimeError(f"数据库完整性检查失败: {结果}")


    def _校验表存在(self, 连接: sqlite3.Connection, 表: str) -> None:
        行 = 连接.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (表,)).fetchone()
        if 行 is None:
            raise RuntimeError(f"缺少必需表: {表}")


    def _校验列(self, 连接: sqlite3.Connection, 表: str, 列: str) -> None:
        列表 = {行[1] for 行 in 连接.execute(f"PRAGMA table_info({表})").fetchall()}
        if 列 not in 列表:
            raise RuntimeError(f"缺少必需列: {表}.{列}")


    def _迁移到100(self, 连接: sqlite3.Connection) -> None:
        """1.0.0：建全部基础表（无栅栏列；对旧库 CREATE IF NOT EXISTS 幂等）。"""
        连接.executescript("""
            CREATE TABLE IF NOT EXISTS 元信息(键 TEXT PRIMARY KEY, 值 TEXT);
            CREATE TABLE IF NOT EXISTS 句柄(
                句柄id TEXT PRIMARY KEY, 句柄类型 TEXT, 资源id TEXT,
                项目id TEXT, 所有者 TEXT, 状态 TEXT, 版本 TEXT,
                创建时间 TEXT, 失效时间 TEXT, 失效原因 TEXT);
            CREATE TABLE IF NOT EXISTS 租约(
                租约id TEXT PRIMARY KEY, 资源id TEXT, 项目id TEXT, 所有者 TEXT,
                句柄id TEXT, 空闲超时秒 REAL, 硬截止时间 REAL, 最后心跳 REAL,
                已回收 INTEGER);
            CREATE TABLE IF NOT EXISTS 资源版本(
                资源id TEXT PRIMARY KEY, 版本 TEXT, 值 TEXT, 摘要 TEXT,
                更新时间 TEXT);
            CREATE TABLE IF NOT EXISTS 事务(
                事务id TEXT PRIMARY KEY, 资源id TEXT, 句柄id TEXT, 基础版本 TEXT,
                状态 TEXT, 结果 TEXT, 新版本 TEXT, 创建时间 TEXT, 提交时间 TEXT);
            CREATE TABLE IF NOT EXISTS 锁(
                资源id TEXT PRIMARY KEY, 持有者 TEXT, 锁时间 TEXT);
            CREATE TABLE IF NOT EXISTS 进程(
                身份键 TEXT PRIMARY KEY, 进程id INTEGER, 启动指纹 TEXT,
                项目id TEXT, 所有者 TEXT, 实例id TEXT, 最后心跳 REAL);
            CREATE TABLE IF NOT EXISTS 回收证据(
                证据id TEXT PRIMARY KEY, 句柄id TEXT, 资源id TEXT, 类型 TEXT,
                失效原因 TEXT, 时间 TEXT, 版本 TEXT);
            CREATE TABLE IF NOT EXISTS 引用计数(
                引用键 TEXT PRIMARY KEY, 包id TEXT, 版本 TEXT, 计数 INTEGER);
        """)


    def _迁移到110(self, 连接: sqlite3.Connection) -> None:
        """1.1.0：资源版本/事务 增加栅栏令牌列（幂等：只补缺失列，明确识别重复列）。"""
        self._补列(连接, "资源版本", "栅栏令牌", "INTEGER DEFAULT 0")
        self._补列(连接, "事务", "基础令牌", "TEXT DEFAULT '0'")


    def _迁移到120(self, 连接: sqlite3.Connection) -> None:
        """1.2.0：结构化锁表 + 租约/句柄/事务 增加进程身份键列 + 旧锁数据迁移。"""
        for 表, 列, 定义 in (("租约", "进程身份键", "TEXT DEFAULT ''"),
                          ("句柄", "进程身份键", "TEXT DEFAULT ''"),
                          ("事务", "进程身份键", "TEXT DEFAULT ''")):
            self._补列(连接, 表, 列, 定义)
        # 锁表重建为结构化（保留旧数据，不删除）
        结构化锁列 = ("操作id", "事务id", "进程身份键", "项目id", "所有者",
                      "栅栏令牌", "获取时间", "租约截止")
        锁列 = {行[1] for 行 in 连接.execute("PRAGMA table_info(锁)").fetchall()}
        if "持有者" in 锁列:
            # 旧布局（持有者拼接字符串）才整表重建；不能用「缺 操作id」判定，
            # 半结构化表也缺 操作id，走重建会因 锁旧表 无 持有者 列而报错。
            连接.execute("ALTER TABLE 锁 RENAME TO 锁旧表")
            连接.executescript("""
                -- 租约截止：> 0 表示该锁带租约（过期即可被 CAS 抢占，见 获取锁 P2-7）；
                --           = 0 表示无租约，只有进程死亡清理能回收该锁。
                CREATE TABLE 锁(
                    资源id TEXT PRIMARY KEY, 操作id TEXT DEFAULT '',
                    事务id TEXT DEFAULT '', 进程身份键 TEXT DEFAULT '',
                    项目id TEXT DEFAULT '', 所有者 TEXT DEFAULT '',
                    栅栏令牌 INTEGER DEFAULT 0, 获取时间 REAL DEFAULT 0,
                    租约截止 REAL DEFAULT 0);
                INSERT INTO 锁(资源id, 操作id, 事务id, 进程身份键, 获取时间)
                    SELECT 资源id,
                           CASE WHEN 持有者 LIKE '事务_%' THEN ''
                                WHEN 持有者 LIKE '%:%' THEN
                                     SUBSTR(持有者, 1, INSTR(持有者, ':') - 1)
                                ELSE 持有者 END,
                           CASE WHEN 持有者 LIKE '事务_%' THEN
                                     SUBSTR(持有者, 7) ELSE '' END,
                           CASE WHEN 持有者 LIKE '%:%' THEN
                                     SUBSTR(持有者, INSTR(持有者, ':') + 1) ELSE '' END,
                           CAST(0 AS REAL) FROM 锁旧表;
                DROP TABLE 锁旧表;
            """)
        else:
            # 结构化布局：逐列补回缺失列（假升级 / 手工删列的错误历史状态）。
            # 原判据只认 操作id 一列，缺 进程身份键 等列时整段跳过 → 假升级状态
            # 永远修不好，只会在 _校验版本结构 处直接抛错（见 _迁移结构 的
            # 「假升级错误历史补列」承诺）。半结构化表不能走整表重建：重建的
            # INSERT 要读 锁旧表.持有者，而它没有该列。
            锁列定义 = {"操作id": "TEXT DEFAULT ''", "事务id": "TEXT DEFAULT ''",
                        "进程身份键": "TEXT DEFAULT ''", "项目id": "TEXT DEFAULT ''",
                        "所有者": "TEXT DEFAULT ''", "栅栏令牌": "INTEGER DEFAULT 0",
                        "获取时间": "REAL DEFAULT 0", "租约截止": "REAL DEFAULT 0"}
            for 列 in 结构化锁列:
                self._补列(连接, "锁", 列, 锁列定义[列])


    def _补列(self, 连接: sqlite3.Connection, 表: str, 列: str, 定义: str) -> None:
        """幂等补列：只有明确识别为重复列（duplicate column）才继续。"""
        列表 = {行[1] for 行 in 连接.execute(f"PRAGMA table_info({表})").fetchall()}
        if 列 in 列表:
            return
        连接.execute(f"ALTER TABLE {表} ADD COLUMN {列} {定义}")


    def _注册进程(self) -> None:
        连接 = self._连接()
        with 连接:
            连接.execute(
                "INSERT OR REPLACE INTO 进程(身份键, 进程id, 启动指纹, 项目id, 所有者, 实例id, 最后心跳) "
                "VALUES(?, ?, ?, ?, ?, ?, ?)",
                (self.身份.身份键(), self.身份.进程id, self.身份.启动指纹,
                 self.身份.项目id, self.身份.所有者, self.身份.实例id, self.身份.最后心跳))


    def 刷新心跳(self) -> None:
        """当前进程心跳（进程存活判定依据）。"""
        from 运行核心.进程身份 import 心跳
        心跳(self.身份)
        连接 = self._连接()
        with 连接:
            连接.execute("UPDATE 进程 SET 最后心跳=? WHERE 身份键=?",
                         (self.身份.最后心跳, self.身份.身份键()))
