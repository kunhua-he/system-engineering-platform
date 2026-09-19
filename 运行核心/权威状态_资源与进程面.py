"""资源与进程面：资源版本与 CAS 提交、令牌签发、心跳时基、进程账本与保留窗口清理。

**为什么独立成文件**（拆上帝文件 B1，2026-09-19）：本簇原住在
`运行核心/权威状态.py` 的 `权威状态` 类体内，是那个 1613 行文件里的一整块职责。
拆出只为让文件回到可维护尺寸，**对外零变化**：成员名、签名、默认值、正文
一个字符未改（搬动方式＝原样片段去 4 空格缩进），主类只改基类列表
（`class 权威状态(连接迁移面, 句柄租约面, 事务锁面, 资源与进程面, 可靠性面)`）。

`_签发新令牌` 与 `_提交资源单事务` 都与「资源版本行」直接耦合（都在同一 SQL 事务里
读写 `资源版本.栅栏令牌`），故与 提交资源 同簇；时基三件套（`_时基换算`/`_心跳到单调`/
`_单调截止`）是本簇内 `清理死亡进程资源` / `回收过期资源行` 与 `存活的进程身份表` 的
唯一收敛点，不得分到别处。

**导入方向**：本文件只被 `运行核心/权威状态.py` 模块级导入，**不得反向导入**
`运行核心/权威状态.py`（会成环）；本文件从主文件取的模块级件（如 `版本元组` /
`锁所有权判据` / `是并发冲突`）一律走**函数内延迟导入**并当场转发，唯一实现恒在
主文件一处，方向恒为主文件 → 本文件。
"""

from __future__ import annotations

import json
import sqlite3
import time
from typing import Any

from 公共契约.基础类型.逻辑类型 import 真, 假


def 是并发冲突(错误: BaseException) -> bool:
    """并发冲突判定（唯一实现在 `运行核心/权威状态.py`）。

    为什么是延迟取而不是模块级 `from … import 是并发冲突`：本文件被
    `运行核心/权威状态.py` 导入（它要拿本类当基类），模块级反向导入会成环；
    延迟导入在任何导入顺序下都成立，且不复制任何判据逻辑。
    """
    from 运行核心.权威状态 import 是并发冲突 as _唯一实现
    return _唯一实现(错误)


class 资源与进程面:
    def 读取资源(self, 资源id: str) -> dict[str, Any] | None:
        连接 = self._连接()
        行 = 连接.execute(
            "SELECT 资源id, 版本, 值, 摘要, 更新时间, 栅栏令牌 FROM 资源版本 WHERE 资源id=?",
            (资源id,)).fetchone()
        if 行 is None:
            return None
        return {"资源id": 行[0], "版本": 行[1], "值": json.loads(行[2]), "摘要": 行[3],
                "更新时间": 行[4], "栅栏令牌": 行[5]}


    def 全部资源版本(self) -> list[dict[str, Any]]:
        """全部资源当前版本（崩溃恢复重建快照用）。"""
        连接 = self._连接()
        结果表 = []
        for 行 in 连接.execute(
                "SELECT 资源id, 版本, 值, 摘要, 更新时间, 栅栏令牌 FROM 资源版本"):
            结果表.append({"资源id": 行[0], "版本": 行[1], "值": json.loads(行[2]), "摘要": 行[3],
                          "更新时间": 行[4], "栅栏令牌": 行[5]})
        return 结果表


    def 初始化资源(self, 资源id: str, 初始值: Any = None) -> None:
        连接 = self._连接()
        with 连接:
            连接.execute(
                "INSERT OR IGNORE INTO 资源版本(资源id, 版本, 值, 摘要, 更新时间, 栅栏令牌) "
                "VALUES(?, '0', ?, '', '', 0)",
                (资源id, json.dumps(初始值, ensure_ascii=False)))


    def 提交资源(self, *, 资源id: str, 期望版本: str, 期望令牌: str,
                 事务id: str = "", 进程身份键: str = "",
                 项目id: str = "", 所有者: str = "",
                 新值: Any, 新摘要: str) -> tuple[bool, str]:
        """原子 CAS 提交：同一事务内校验 锁所有权 + 版本 + 令牌，条件更新。

        拒绝：版本不匹配、旧栅栏令牌、锁不属于该事务/进程、项目或所有者不匹配。
        写入使用单条条件 UPDATE（WHERE 资源id AND 版本 AND 栅栏令牌），无 SELECT 后无条件 UPDATE 竞态。

        并发冲突（P2-8）：写事务撞上其它进程/线程（sqlite 主码 BUSY/LOCKED，含
        SQLITE_BUSY_SNAPSHOT）时返回 `(假, "并发冲突: …可原样重试")`——**可重试**语义，
        不再冒泡成「内部错误」。判据是 sqlite 错误码，不是文案。
        """
        进程身份键 = 进程身份键 or self.身份.身份键()
        连接 = self._连接()
        try:
            return self._提交资源单事务(
                连接=连接, 资源id=资源id, 期望版本=期望版本, 期望令牌=期望令牌,
                事务id=事务id, 进程身份键=进程身份键, 项目id=项目id,
                所有者=所有者, 新值=新值, 新摘要=新摘要)
        except sqlite3.OperationalError as 错误:
            if not 是并发冲突(错误):
                raise
            # P2-8（2026-09-18 硬化）：WAL 下「先读后写」的写事务后到者会撞
            # SQLITE_BUSY / SQLITE_BUSY_SNAPSHOT（busy handler 对快照冲突不自动
            # 重试）。这是**并发冲突（可重试）**，不是内部错误——归成明确失败交回
            # 调用方重试，禁止冒泡成「内部错误」丢掉可重试语义。
            # 判据是 sqlite 错误码（`是并发冲突`），不是文案。
            名称 = getattr(错误, "sqlite_errorname", "") or "并发写冲突"
            return 假, (f"并发冲突: 资源 {资源id} 的写事务与其它进程/线程重叠（{名称}），"
                        f"本次未提交，可原样重试")


    def _提交资源单事务(self, *, 连接: sqlite3.Connection, 资源id: str,
                        期望版本: str, 期望令牌: str, 事务id: str,
                        进程身份键: str, 项目id: str, 所有者: str,
                        新值: Any, 新摘要: str) -> tuple[bool, str]:
        """提交的读校验 + 条件更新（事务边界与并发冲突归类由 `提交资源` 统一负责）。"""
        with 连接:
            锁行 = 连接.execute(
                "SELECT 事务id, 进程身份键, 项目id, 所有者, 栅栏令牌 FROM 锁 WHERE 资源id=?",
                (资源id,)).fetchone()
            if 锁行 is None:
                return 假, "锁不存在: 提交必须持有资源锁"
            if 锁行[0] and 锁行[0] != 事务id:
                return 假, f"锁所有权不匹配: 锁属事务 {锁行[0]}，请求 {事务id}"
            if 锁行[1] and 锁行[1] != 进程身份键:
                return 假, f"锁所有权不匹配: 锁属进程 {锁行[1]}，请求 {进程身份键}"
            if 锁行[2] and 锁行[2] != 项目id:
                return 假, f"跨项目提交被拒绝: 锁属 {锁行[2]}，请求 {项目id}"
            if 锁行[3] and 锁行[3] != 所有者:
                return 假, f"跨所有者提交被拒绝: 锁属 {锁行[3]}，请求 {所有者}"
            资源行 = 连接.execute(
                "SELECT 版本, 栅栏令牌 FROM 资源版本 WHERE 资源id=?", (资源id,)).fetchone()
            if 资源行 is None:
                return 假, "资源不存在"
            if str(资源行[0]) != str(期望版本):
                return 假, f"版本冲突: 期望 {期望版本}，当前 {资源行[0]}"
            if str(资源行[1]) != str(期望令牌) or str(锁行[4]) != str(期望令牌):
                return 假, "旧令牌提交: 栅栏令牌已变化，提交被拒绝"
            try:
                版本号文本 = str(资源行[0])
                当前版本号 = int(版本号文本)
            except (TypeError, ValueError):
                # A3：版本是外部可写的账本字段（迁移库/手工写入/异常数据都可能是
                # 「v2」或 NULL），int() 不得让异常穿透错误边界——异常文本会直接
                # 漏给调用方。版本域失败统一用已登记中文码「版本冲突」
                # （网关 公开错误说明表 已登记，本地网关 公开错误码状态映射 → 409）。
                当前版本号 = None
            if 当前版本号 is None:
                return 假, (f"版本冲突: 资源 {资源id} 当前版本 {资源行[0]!r} "
                               f"不是十进制数字，无法递增新版本，提交被拒绝")
            新版本 = str(当前版本号 + 1)
            游标 = 连接.execute(
                "UPDATE 资源版本 SET 版本=?, 值=?, 摘要=?, 更新时间=? "
                "WHERE 资源id=? AND 版本=? AND 栅栏令牌=?",
                (新版本, json.dumps(新值, ensure_ascii=False), 新摘要,
                 time.strftime("%Y-%m-%d %H:%M:%S"), 资源id, 期望版本, 期望令牌))
            if 游标.rowcount != 1:
                return 假, "并发提交冲突"
            return 真, 新版本


    def _签发新令牌(self, 连接: sqlite3.Connection, 资源id: str) -> int:
        """锁授予的令牌签发（新授锁与租约抢占共用，禁止各写一套）：同事务内递增并回写。

        签发后永不回退：被抢占/已释放的旧令牌再也通不过 `提交资源`/`续期锁`/
        `释放锁` 的令牌判据。
        """
        连接.execute("UPDATE 资源版本 SET 栅栏令牌=栅栏令牌+1 WHERE 资源id=?", (资源id,))
        新令牌 = 连接.execute(
            "SELECT 栅栏令牌 FROM 资源版本 WHERE 资源id=?", (资源id,)).fetchone()[0]
        连接.execute("UPDATE 锁 SET 栅栏令牌=? WHERE 资源id=?", (新令牌, 资源id))
        return 新令牌


    @property
    def _时基换算(self) -> float:
        """墙钟 epoch 秒 → 本进程单调秒 的**一次性常量**（进程生命周期内不变）。

        本进程（源码/制品任一形态）从没写过墙钟心跳，历史行的墙钟值必然
        **早于**本进程启动，故用「进程启动那一刻的双时钟偏差」换算，误差 = 启动耗时（毫秒级），
        对 15 秒量级的心跳超时判据无影响。取一次即缓存：热路径不再重复取时钟。
        """
        缓存 = getattr(self, "_时基换算缓存", None)
        if 缓存 is None:
            缓存 = time.time() - time.monotonic()
            self._时基换算缓存 = 缓存
        return 缓存


    def _心跳到单调(self, 心跳值: Any) -> float:
        """把某一行的 `最后心跳` 统一到**单调时基**（同一列两种时基的收敛点）。

        为什么必须收敛：本列自 §9-B6 起改为单调口径（经过时间量，睡眠期间不走），
        而历史行存的是 epoch 秒。两种时基混在同一列，两个方向都会错：
        - 拿单调 `截止` 比墙钟值（≈1.7e9 ≫ ≈6e5）→ 恒真 → **死进程永久显示存活**；
        - 拿墙钟 `截止` 比单调值 → 恒假 → **活进程被批量判死**（那正是本轮要修的误杀）。
        判据：值 > 1e8 即视为墙钟量（epoch，2026 年 ≈1.79e9；任何单调时钟都不可能到 1e8 秒
        ≈ 3.2 年开机时长），换算到单调；否则按已是单调值原样返回。
        """
        try:
            值 = float(心跳值 or 0.0)
        except (TypeError, ValueError):
            return 0.0
        return 值 - self._时基换算 if 值 > 1e8 else 值


    def _单调截止(self, 心跳超时秒: float) -> float:
        """心跳新鲜判据的截止点（**单调时基**）：比它新才算活着。"""
        return time.monotonic() - float(心跳超时秒)


    def 存活的进程身份表(self, 心跳超时秒: float = 15.0) -> list[dict[str, Any]]:
        """存活进程（心跳新鲜）；pid 复用不误认（指纹参与身份键）。"""
        连接 = self._连接()
        结果表 = []
        # 比较口径：全部经 `_心跳到单调` 收敛后与本进程单调时钟比，绝不直接把列与
        # 时间戳混算（见 `_心跳到单调` 的两种错法）。候选集先按最宽的墙钟/单调
        # 两界取全，再由 Python 侧收敛复判 —— 保证不漏行、不误判。
        上界 = max(time.time(), time.monotonic()) + 1.0
        for 行 in 连接.execute("SELECT * FROM 进程 WHERE 最后心跳 > ?", (0.0,)):
            心跳 = self._心跳到单调(行[6])
            if 心跳 <= 0 or 心跳 > 上界:
                continue
            if 心跳 <= self._单调截止(心跳超时秒):
                continue
            结果表.append({
                "身份键": 行[0], "进程id": 行[1], "启动指纹": 行[2], "项目id": 行[3],
                "所有者": 行[4], "实例id": 行[5], "最后心跳": 心跳,
            })
        return 结果表


    def 清理死亡进程资源(self, *, 项目id: str = "", 所有者: str = "",
                          心跳超时秒: float = 15.0,
                          保留窗口秒: float | None = None) -> list[str]:
        """结构化精确回收：按进程身份键回收 锁/租约/未完成事务/句柄。

        系统进程已不存在时立即回收；进程仍存在但心跳过期时按失联回收。
        只处理项目/所有者匹配的资源；活跃进程锁不被误删；
        清理重复执行幂等。
        末尾按保留窗口真删 句柄/租约/进程 三类终态历史行
        （见 回收过期资源行），使账本「只增不删」变为「有界即正确」。
        自身进程身份键永不判死：清理器不得回收正在运行的调用方资源。

        本轮顺带收割「已结束线程的缓存连接」：网关是「每连接一线程」，
        每条连接线程用完就退出，而 `_清理死连接` 原先唯一调用点在 `关闭()`，
        进程长驻期间那些连接会一直挂在 `_连接表` 上（tid 复用只能兜住一部分）。
        收口点选在这里，是因为本方法就是 `资源账本维护循环` 每轮的判死回收动作
        ——零新增线程、零新增周期，拿现成的显式维护点。
        """
        from 运行核心.进程身份 import 系统进程存在

        # 收割已结束线程的缓存连接（显式维护点；`_连接()` 读取路径不收割）
        self._清理死连接()
        连接 = self._连接()
        截止 = self._单调截止(心跳超时秒)
        自身身份键 = self.身份.身份键()
        清理列表 = []
        条件表: list[str] = []
        参数表: list[Any] = []
        if 项目id:
            条件表.append("项目id = ?")
            参数表.append(项目id)
        if 所有者:
            条件表.append("所有者 = ?")
            参数表.append(所有者)
        条件 = " AND ".join(条件表) if 条件表 else "1=1"
        候选进程表 = 连接.execute(
            f"SELECT 身份键, 进程id, 最后心跳 FROM 进程 WHERE {条件}", 参数表).fetchall()
        # 心跳判据全在**单调时基**上做（`_心跳到单调` 收敛历史墙钟行）：
        # 墙钟口径下合盖睡眠会让所有行集体显得「心跳过期」（审计 §9-B6 的误杀根因），
        # 单调口径下睡眠不动 → 只有真失联的行才过期；PID 探活仍是并列的兜底判据。
        死亡进程表 = [
            (身份键, 进程id)
            for 身份键, 进程id, 最后心跳 in 候选进程表
            if 身份键 != 自身身份键
            and (self._心跳到单调(最后心跳) <= 截止 or not 系统进程存在(int(进程id)))
        ]
        with 连接:
            for 身份键, 进程id in 死亡进程表:
                锁行 = 连接.execute("SELECT 资源id FROM 锁 WHERE 进程身份键=?", (身份键,)).fetchall()
                for (资源id,) in 锁行:
                    连接.execute("DELETE FROM 锁 WHERE 资源id=? AND 进程身份键=?", (资源id, 身份键))
                    清理列表.append(f"锁: {资源id}（死亡进程 {进程id}）")
                租约行 = 连接.execute(
                    "SELECT 租约id FROM 租约 WHERE 进程身份键=? AND 已回收=0", (身份键,)).fetchall()
                for (租约id,) in 租约行:
                    # 传入外层连接：内层不得自带 `with 连接`，否则内层退出即提交
                    # 外层事务，本方法整体原子性失效（A1）。
                    self.回收租约(租约id, "所属进程死亡", 连接=连接)
                    清理列表.append(f"租约: {租约id}（死亡进程 {进程id}）")
                事务行 = 连接.execute(
                    "SELECT 事务id FROM 事务 WHERE 进程身份键=? AND 状态='进行中'", (身份键,)).fetchall()
                for (事务id,) in 事务行:
                    连接.execute("UPDATE 事务 SET 状态='失败', 结果='进程死亡回滚' WHERE 事务id=?", (事务id,))
                    清理列表.append(f"事务: {事务id}（死亡进程 {进程id}）")
                句柄行 = 连接.execute(
                    "SELECT 句柄id FROM 句柄 WHERE 进程身份键=? AND 状态='有效'", (身份键,)).fetchall()
                for (句柄id,) in 句柄行:
                    # 同上：复用外层连接，句柄失效随外层事务一起提交或回滚。
                    self.失效句柄(句柄id, "所属进程死亡", 连接=连接)
                    清理列表.append(f"句柄: {句柄id}（死亡进程 {进程id}）")
        # 真删放在标记事务之外：标记先落地，真删失败下一轮重试，不做半嵌套事务。
        清理列表.extend(self.回收过期资源行(保留窗口秒=保留窗口秒))
        return 清理列表


    def _保留窗口(self, 保留窗口秒: float | None) -> float:
        """解析本次调用的保留窗口：入参 > 类属性 `保留窗口秒`；NaN/无穷按「永不真删」处理。"""
        窗口 = self.保留窗口秒 if 保留窗口秒 is None else float(保留窗口秒)
        if 窗口 != 窗口 or 窗口 == float("inf"):  # NaN / 无穷：保持只增语义，不真删
            return float("inf")
        if 窗口 < 0:
            raise ValueError("保留窗口秒不得为负")
        return float(窗口)


    def 回收过期资源行(self, *, 保留窗口秒: float | None = None) -> list[str]:
        """按保留窗口真删 句柄/租约/进程 三类历史行（只删已终态且够老的行）。

        为什么需要：判死清理（清理死亡进程资源）对 租约/句柄 只改状态、对 进程 只读不写，
        锁表是唯一真删；不改终态为删除 ⇒ 三表只增不删（现场 18 天 9130/9166/3633 行）。
        行级判据（三类各自与 清理死亡进程资源 的判死判据配对）：
        - 句柄：`状态='已失效'` 且 `失效时间` < 保留截止（失效时间为本地时间文本，
          定宽零填充，可直接字典序比较）；历史行没有 失效时间 时用 创建时间 兜底，
          两者都缺则视为不可判定、继续保留；
        - 租约：`已回收=1` 且 `最后心跳` < 保留截止（epoch 秒，NULL 视为远古）；
        - 进程：`最后心跳` < 保留截止 且 身份键不再被 锁 表引用 且 不是自身身份键
          （残留引用保护：仍有锁的行说明清理链未走完，留给下一轮）。
        单事务提交，逐条返回删除说明；幂等（重复调用第二次返回空）。
        """
        窗口 = self._保留窗口(保留窗口秒)
        if 窗口 == float("inf"):
            return []
        现在 = time.time()
        截止时间 = 现在 - 窗口
        截止文本 = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(截止时间))
        连接 = self._连接()
        删除列表: list[str] = []
        with 连接:
            # 句柄：失效时间缺失的历史行（旧版本只改状态不写时间）用 创建时间 兜底，
            # 两边都缺（'' 或 NULL）的行视为不可判定，继续保留（审计优先于清空）。
            游标 = 连接.execute(
                "DELETE FROM 句柄 WHERE 状态='已失效' "
                "AND COALESCE(NULLIF(失效时间, ''), NULLIF(创建时间, '')) IS NOT NULL "
                "AND COALESCE(NULLIF(失效时间, ''), NULLIF(创建时间, '')) < ?",
                (截止文本,))
            if 游标.rowcount:
                删除列表.append(f"句柄: 真删 {游标.rowcount} 行（失效早于 {截止文本}）")
            游标 = 连接.execute(
                "DELETE FROM 租约 WHERE 已回收=1 AND COALESCE(最后心跳, 0) < ?", (截止时间,))
            if 游标.rowcount:
                删除列表.append(f"租约: 真删 {游标.rowcount} 行（心跳早于 {截止时间:.0f}）")
            # 进程：`最后心跳` 自 §9-B6 起是**单调**口径（`进程身份.心跳` 写
            # `time.monotonic()`），历史行却是墙钟 epoch 秒。真删判据必须按行收敛到
            # 同一时基（`_心跳到单调`）：不收敛的话，`截止时间`（墙钟 epoch ≈1.79e9）
            # 对**任何**单调值（≈6e5）都恒真 → 每一轮清扫都把**全部活进程行真删**
            # （本轮实测复现：写入一条心跳为当前 monotonic 的行，一轮即被删）。
            # 与 存活的进程身份表/清理死亡进程资源 用同一个 `_心跳到单调` 收敛点。
            时基换算 = self._时基换算
            游标 = 连接.execute(
                "DELETE FROM 进程 WHERE 身份键 <> ? "
                "AND 身份键 NOT IN (SELECT 进程身份键 FROM 锁) "
                "AND (CASE WHEN COALESCE(最后心跳, 0) > 1e8 "
                "          THEN COALESCE(最后心跳, 0) - ? "
                "          ELSE COALESCE(最后心跳, 0) END) < ?",
                (self.身份.身份键(), 时基换算, self._单调截止(窗口)))
            if 游标.rowcount:
                删除列表.append(
                    f"进程: 真删 {游标.rowcount} 行（心跳早于单调 {self._单调截止(窗口):.0f}）")
        return 删除列表


    def 状态快照(self) -> dict[str, Any]:
        连接 = self._连接()
        return {
            "结构版本": self.目标版本,
            "句柄": self.活跃句柄数(),
            "租约": 连接.execute("SELECT COUNT(*) FROM 租约 WHERE 已回收=0").fetchone()[0],
            "资源": 连接.execute("SELECT COUNT(*) FROM 资源版本").fetchone()[0],
            "进行中事务": len(self.进行中事务()),
            "存活进程": len(self.存活的进程身份表()),
            "引用计数": 连接.execute("SELECT COUNT(*) FROM 引用计数 WHERE 计数 > 0").fetchone()[0],
            "锁": 连接.execute("SELECT COUNT(*) FROM 锁").fetchone()[0],
        }
