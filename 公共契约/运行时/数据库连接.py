"""SQLite **连接创建**的唯一腿：三档具名入口 + 具名参数档，全平台只此一处 `sqlite3.connect`。

## 为什么住 `公共契约/运行时/`（不是重复造件）
依赖防火墙 `允许依赖表` 里 `公共契约 -> []`、`支持库 -> ["公共契约"]`、
`运行核心 -> ["公共契约","支持库"]`、`平台控制面 -> ["公共契约","支持库","运行核心"]`、
`开发工具 -> ["公共契约",…]` —— **`公共契约` 是唯一能被上述全部层导入的层**，
而本腿的调用方横跨 公共契约 / 支持库 / 运行核心 / 平台控制面 / 开发工具 五层，
故「连接创建」这个跨层共用原语只能落在这里。完整论证（各层可依赖集合、代价实测、
为什么不能住高层、为什么不能复用 `实现/` 下的件）见同目录 `数据库URI.py` 的模块 docstring
—— 那是同一论证的**唯一出处**，本文件不复述；与同层 `平台适配.py` / `有界IO.py` 一致：
都是「跨层共用的底层原语」。

## 与 `数据库URI.py` 的分工（**不是两条腿**）
- `数据库URI.py`：只负责**构造**只读 file URI 字符串（百分号编码 + 参数常量），不碰连接；
- 本文件：只负责**创建**连接（三档参数语义），只读档**转调** `数据库URI` 的构造口径。
即「URI 构造」与「连接创建」是**同一条只读腿的两个相邻环节**：本文件 `打开只读` 必然经过
`只读库URI` / `只读库URI实参`，全仓不存在第二种只读 URI 拼法。

## 三档语义
- `打开(路径, 超时秒, *, 只读=False, …)`：**读路径**。不建目录、不切 WAL、不设 PRAGMA
  （除非调用方显式给具名档 `忙等待毫秒` / `同步模式` / `日志模式`）。
- `打开可写(路径, 超时秒, …)`：**写路径 / 初始化路径**。先 `mkdir(parents=True, exist_ok=True)`，
  再走读路径参数，最后 `PRAGMA journal_mode=WAL`。
- `打开只读(路径, *, 不可变=False, …)`：**只读路径**。经 `只读库URI`（活动库）或
  `只读库URI实参`（外部索引，`immutable=1`）构造 URI，`uri=True`；不建目录、不设 PRAGMA。

### 为什么读路径不建目录、不切 WAL（论证搬自 `SQLite数据库.提供者._打开`）
- `路径.parent.mkdir(...)`：读一个不存在的目录下的库，本来就该报「打不开」；
  替调用方把目录建出来，等于**读动作改了文件系统**。
- `PRAGMA journal_mode = WAL`：这是**写进库文件头**的库级设置，切换本身是隐式写事务，
  还会生成 `-wal`/`-shm` 两个文件；而 WAL 库由文件头自动识别，**读并不需要先切模式**。
  需要「建目录 + 切 WAL」的写入腿 / 初始化腿请用 `打开可写`。

### 参数档（具名，禁止调用方再手写 `sqlite3.connect` 参数字面量）
- `自动提交=True` → `isolation_level=None`（VACUUM / `BEGIN EXCLUSIVE` 探针这类
  「自己管事务边界」的连接）；
- `跨线程=True` → `check_same_thread=False`（连接在模块级锁内跨线程复用）；
- `连接工厂=类` → `factory=类`（如项目文档库「`with` 退出真关闭」的连接子类）；
- `忙等待毫秒=N` → `PRAGMA busy_timeout = N`；
- `同步模式="NORMAL"` → `PRAGMA synchronous = NORMAL`；
- `日志模式="WAL"` → `PRAGMA journal_mode = WAL`。

PRAGMA 应用顺序恒为 **忙等待 → 同步模式 → 日志模式**。历史实现里
`SQLite数据库.提供者._打开可写` 是「忙等待→同步→WAL」、
`运行核心/权威状态_连接迁移面._连接` 是「忙等待→WAL→同步」；两种顺序**行为等价**
——`PRAGMA synchronous` 是**连接级**设置，`journal_mode` 切换不会重置它，
唯一有硬约束的是「忙等待必须最先」（`journal_mode=WAL` 要拿写锁，先设忙等待才不会
在并发下立即报 locked，见 `运行核心/权威状态_连接迁移面._连接` 的现场注释）。
本腿统一取前者为准。

## 默认超时（实测后定档，不写死成与现网不同）
`默认超时秒 = 5.0` = **`sqlite3.connect` 标准库默认值**。全仓实测：显式传超时的调用点
各有其值（2.0/3.0/5.0/10/15/30 都有，故不存在「现网唯一默认」），而**未显式传超时**的
调用点（`记忆支持库.记忆._连接`、`备份恢复演练核对.破坏恢复副本`、`备份恢复校验函数`、
`控制面对账.只读激活指针`、`权威状态_可靠性面.损坏恢复`、`模型路由` 的参考库分支）
在 `sqlite3.connect` 下**实际就是 5.0** —— 默认档取 5.0，这些点逐字等价、零语义漂移。
其余调用点的现行值一律由调用方**显式传入**，本文件不替它们改档。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from 公共契约.运行时.数据库URI import 只读库URI, 只读库URI实参

#: `sqlite3.connect` 标准库默认超时（秒）；默认档取它，保证「未显式传」的调用点行为不变。
默认超时秒 = 5.0

#: `PRAGMA synchronous` 允许值（连接级；白名单同时挡住拼接注入）。
同步模式允许值 = frozenset({"OFF", "NORMAL", "FULL", "EXTRA"})
#: `PRAGMA journal_mode` 允许值（库级；白名单同时挡住拼接注入）。
日志模式允许值 = frozenset({"DELETE", "TRUNCATE", "PERSIST", "MEMORY", "WAL", "OFF"})


def _连接实参(超时秒, 自动提交: bool, 跨线程: bool, 连接工厂) -> dict:
    """装配 `sqlite3.connect` 关键字实参（三档共用，避免各写一遍）。"""
    实参: dict = {"timeout": float(超时秒)}
    if 自动提交:
        实参["isolation_level"] = None
    if 跨线程:
        实参["check_same_thread"] = False
    if 连接工厂 is not None:
        实参["factory"] = 连接工厂
    return 实参


def _设PRAGMA(连接对象, 忙等待毫秒, 同步模式, 日志模式) -> None:
    """按固定顺序应用具名 PRAGMA 档：忙等待 → 同步模式 → 日志模式（顺序理由见模块 docstring）。"""
    if 忙等待毫秒 is not None:
        连接对象.execute(f"PRAGMA busy_timeout = {int(忙等待毫秒)}")
    if 同步模式 is not None:
        取值 = str(同步模式).upper()
        if 取值 not in 同步模式允许值:
            raise ValueError(f"同步模式不在允许值内: {同步模式}")
        连接对象.execute(f"PRAGMA synchronous = {取值}")
    if 日志模式 is not None:
        取值 = str(日志模式).upper()
        if 取值 not in 日志模式允许值:
            raise ValueError(f"日志模式不在允许值内: {日志模式}")
        连接对象.execute(f"PRAGMA journal_mode = {取值}")


def 打开(路径, 超时秒=默认超时秒, *, 只读: bool = False, 不可变: bool = False,
        自动提交: bool = False, 跨线程: bool = False, 连接工厂=None,
        忙等待毫秒=None, 同步模式=None, 日志模式=None) -> sqlite3.Connection:
    """**读路径**打开连接：不建目录、不切 WAL；具名档按需加 PRAGMA。

    `只读=True`（或 `不可变=True`）时**转调** `打开只读`（同一只读腿，不在此另拼 URI）；
    此时不得再给 PRAGMA 具名档（库级设置写不了只读连接），给了即 `ValueError`（fail-closed，
    不做静默忽略——静默忽略会让调用方以为 WAL 已切而实际没有）。
    """
    if 只读 or 不可变:
        if 忙等待毫秒 is not None or 同步模式 is not None or 日志模式 is not None:
            raise ValueError("只读打开不得同时给 PRAGMA 具名档（库级设置写不了只读连接）")
        return 打开只读(路径, 超时秒=超时秒, 不可变=不可变,
                       自动提交=自动提交, 跨线程=跨线程, 连接工厂=连接工厂)
    连接对象 = sqlite3.connect(
        str(Path(路径)), **_连接实参(超时秒, 自动提交, 跨线程, 连接工厂))
    _设PRAGMA(连接对象, 忙等待毫秒, 同步模式, 日志模式)
    return 连接对象


def 打开可写(路径, 超时秒=默认超时秒, *, 自动提交: bool = False, 跨线程: bool = False,
            连接工厂=None, 忙等待毫秒=None, 同步模式=None) -> sqlite3.Connection:
    """**写路径 / 初始化路径**打开连接：先建父目录，再走读路径参数，最后切 WAL。

    WAL 是库级持久设置（写进文件头、长期生效），写腿依赖它拿到「读写不互斥」的并发语义；
    已生效时 `PRAGMA journal_mode` 直接返回原模式、不重复写文件头，故每次写前重申是幂等的。
    """
    目标 = Path(路径)
    目标.parent.mkdir(parents=True, exist_ok=True)
    return 打开(目标, 超时秒, 自动提交=自动提交, 跨线程=跨线程, 连接工厂=连接工厂,
                忙等待毫秒=忙等待毫秒, 同步模式=同步模式, 日志模式="WAL")


def 打开只读(路径, *, 超时秒=默认超时秒, 不可变: bool = False,
            自动提交: bool = False, 跨线程: bool = False,
            连接工厂=None) -> sqlite3.Connection:
    """**只读路径**打开连接：URI 构造走 `数据库URI.py`（唯一口径），`uri=True`。

    `不可变=False`（默认）→ `只读库URI`（`mode=ro`）：目标是**活动库**（权威状态等
    WAL 活库）。**不要**默认加 `immutable=1` —— 该选项断言「文件不会变」，正在追加的 WAL
    在 immutable 连接下读不到（会把活跃内容误判成缺失）。
    `不可变=True` → `只读库URI实参`（`mode=ro&immutable=1`）：目标是**别人的只读外部索引**
    （连 `mode=ro` 都会在其目录留下 `-shm`/`-wal` side 文件），前提是该库连接期间不被追加。

    不建目录、不设 PRAGMA：只读连接不该改文件系统，也设不了库级设置。
    """
    URI = 只读库URI实参(路径) if 不可变 else 只读库URI(路径)
    实参 = _连接实参(超时秒, 自动提交, 跨线程, 连接工厂)
    实参["uri"] = True
    return sqlite3.connect(URI, **实参)


__all__ = ["默认超时秒", "打开", "打开可写", "打开只读"]
