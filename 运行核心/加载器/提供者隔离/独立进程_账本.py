"""独立进程账本：跨重启世代账本的唯一定义处（落账 / 销账 / 启动清扫）。

**为什么独立成文件**：这一簇是本子系统里**唯一碰 SQLite 与世代身份计数器**的部分，
被主文件的「启动落账 / 关闭销账」与外部三个公开入口共同依赖
（`运行核心/启动运行核心网关.py`：`清扫上一代常驻进程` / `当前网关世代id` /
`读取常驻进程账本`；`运行核心/运行环境管理器/提供者生命周期.py`：启动清扫）。
把**身份计数器（`_网关世代id`）与 sqlite 连接对象的唯一赋值处**收在同一个模块，
主文件不再持有第二张计数器、也不再自建第二条连接路径。

**为什么 `_账本连接` 是每次新建连接而不是共享一个对象**：跨线程/跨进程共用一个
`sqlite3.Connection` 会静默串事务；每次读写各开一条短连接、用完即关，
是本模块**拆分前就有的口径**，本次拆分一字未改（`WAL` + `synchronous=FULL`
就是账本要求的「写后落盘」，账本行必须扛得住网关被 kill -9）。

**`账本库路径` 不缓存**（函数内私有 local）：环境变量 `系统库运行库` 在测试里会被
临时改写（`测试中心/运行核心/测试_提供者生命周期.py` 用临时库路径），缓存即失效。

**`_定位系统根` 为什么从「主文件 + 用户不指定的非默认参数」升级为「无参」**：
原实现以 `独立进程.py` 的落点定位工程根，并用其返回值做「找不到祖先就退回自身」的
兜底。拆分后本模块仍以**主文件落点**为锚（`_主文件路径()` 惰性取主模块 `__file__`，
仅在运行期调用，不在导入期，故无引导期空模块窗口），兜底值因此与拆分前**逐字相同**。

**判据唯一事实源**：表名/列口径只在本模块定义一份（`常驻进程账本表名` / `账本列`），
读写与判活共用；主文件与 `平台控制面/平台状态/状态存储.py` 都不再各写一遍。
排空窗口/预算三个常量**不在本模块**（它们跟排空实现同处 `独立进程_管道读取面.py`，
一处定义，主文件经再导出拿到同一对象）。

**导入方向**：本文件只被 `独立进程.py` 与三个混入面模块级导入，
**不得反向导入**它们；`进程终止` / `解析运行数据根` 是闭环依赖（`公共契约.*`）。
"""

from __future__ import annotations

import os
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any

from 公共契约.运行时 import 进程终止
from 公共契约.运行时.运行缓存 import 解析运行数据根
from 公共契约.基础类型.逻辑类型 import 真, 假


def _主文件路径() -> Path:
    """主文件 `独立进程.py` 的落点（`_定位系统根` 的唯一锚点，拆分前后同一目录）。

    为什么惰性导入：本函数只在**运行期**被 `账本库路径()` 调用，那时主模块已执行完；
    写成模块级反向导入会让「主文件 → 本模块 → 主文件」在导入期成环。
    """
    from 运行核心.加载器.提供者隔离 import 独立进程 as _主模块

    return Path(_主模块.__file__)


# --------------------------------------------------------------------------- #
# 跨重启世代账本：常驻提供者进程落账 / 销账 / 启动清扫
# --------------------------------------------------------------------------- #

#: 底座运行库里本模块就地建的表（只读方按表名探测，缺表即视为无账本）
常驻进程账本表名 = "常驻提供者进程"
#: 底座运行库路径覆盖环境变量（与 运行核心/任务调度/任务系统.py 同一口径，避免第二套定位）
账本库环境变量 = "系统库运行库"
账本连接超时秒 = 10.0
#: 账本表列（读/写/判活共用一份，禁止两处各写一遍）
账本列 = ("网关世代id", "网关进程id", "提供者id", "组长进程id",
        "进程组号", "端口", "资源键", "启动时间", "启动时间戳")
#: 启动清扫整组回收的复查等待上限（强杀后等整组消失的总时长）
清扫等待秒 = 2.0



_网关世代id: str | None = None


def 当前网关世代id() -> str:
    """本进程（网关世代）的唯一世代 id：进程号 + 纳秒时间 + 随机数，进程内只算一次。

    为什么按进程算而不是按调用算：世代 = 「一次网关进程生命周期」，同一次网关里
    所有常驻提供者必须记同一个世代 id，清扫时才能一眼分出「本世代 / 上一代」。
    """
    global _网关世代id
    if _网关世代id is None:
        _网关世代id = f"{os.getpid()}-{time.time_ns():x}-{uuid.uuid4().hex[:8]}"
    return _网关世代id


def _定位系统根() -> Path:
    """定位工程根（同时含 `支持库` 与 `模块库` 的最近祖先；找不到时退回本文件路径）。"""
    候选 = _主文件路径().resolve()
    for _祖先 in 候选.parents:
        if (_祖先 / "支持库").is_dir() and (_祖先 / "模块库").is_dir():
            return _祖先
    return 候选


def 账本库路径() -> Path:
    """世代账本所在的底座运行库路径：环境变量覆盖优先，否则经唯一解析器落运行数据根。"""
    显式 = str(os.environ.get(账本库环境变量, "") or "").strip()
    if 显式:
        return Path(显式).expanduser()
    return 解析运行数据根(_定位系统根()) / "底座运行.db"


def _账本连接(库路径: Path) -> sqlite3.Connection:
    """打开底座运行库连接（WAL；本模块只在建表与读写账本时用它）。

    ``synchronous=FULL``：WAL 模式下每次提交都对 WAL 做 fsync —— 这就是账本要求的
    「写后落盘」；账本行必须扛得住网关被 kill -9（正是它要解决的场景）。
    """
    连接 = sqlite3.connect(str(库路径), timeout=账本连接超时秒)
    连接.execute("PRAGMA journal_mode=WAL")
    连接.execute("PRAGMA synchronous=FULL")
    return 连接


def _建账本表(连接: sqlite3.Connection) -> None:
    """就地建表（幂等）。

    为什么不写进 `平台控制面/平台状态/状态存储.py` 的建表序列：该文件由并行任务在改，
    本模块只在**自己的库里**加一张自己的表，不动别人的迁移序列。
    主键取 (网关世代id, 提供者id)：不同世代的行可以并存，上一代的行在被确认回收前
    必须留着（否则孤儿失去观测对象）；同世代重复启动同一提供者则覆盖为新进程号。
    """
    连接.executescript(
        f"CREATE TABLE IF NOT EXISTS {常驻进程账本表名}("
        "网关世代id TEXT NOT NULL, 网关进程id INTEGER NOT NULL, 提供者id TEXT NOT NULL,"
        "组长进程id INTEGER NOT NULL, 进程组号 INTEGER, 端口 INTEGER,"
        "资源键 TEXT NOT NULL DEFAULT '', 启动时间 TEXT NOT NULL, 启动时间戳 REAL NOT NULL,"
        "PRIMARY KEY(网关世代id, 提供者id));"
    )


def 读取常驻进程账本() -> list[dict[str, Any]]:
    """读全部账本行（最新在后）；库不存在或无本表时返回空表（读路径不建库、不建表）。"""
    库路径 = 账本库路径()
    if not 库路径.is_file():
        return []
    连接 = _账本连接(库路径)
    try:
        表存在 = 连接.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (常驻进程账本表名,)).fetchone()
        if not 表存在:
            return []
        行表 = 连接.execute(
            f"SELECT {', '.join(账本列)} FROM {常驻进程账本表名} ORDER BY 启动时间戳").fetchall()
    finally:
        连接.close()
    return [dict(zip(账本列, 行)) for 行 in 行表]


def _登记常驻进程(记录: dict[str, Any]) -> None:
    """原子写一行账本（BEGIN IMMEDIATE + 提交即 fsync）；异常向上抛，由调用方留痕。"""
    库路径 = 账本库路径()
    库路径.parent.mkdir(parents=True, exist_ok=True)
    连接 = _账本连接(库路径)
    try:
        _建账本表(连接)
        连接.execute("BEGIN IMMEDIATE")
        连接.execute(
            f"INSERT OR REPLACE INTO {常驻进程账本表名}({', '.join(账本列)}) "
            f"VALUES ({', '.join('?' * len(账本列))})",
            tuple(记录.get(列) for 列 in 账本列))
        连接.commit()
    except sqlite3.Error:
        连接.rollback()
        raise
    finally:
        连接.close()


def _注销常驻进程(网关世代id: str, 提供者id: str) -> None:
    """删掉一行账本（确认整组收敛后才调用）；库/表不存在即视为无账可销。"""
    库路径 = 账本库路径()
    if not 库路径.is_file():
        return
    连接 = _账本连接(库路径)
    try:
        if not 连接.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                (常驻进程账本表名,)).fetchone():
            return
        连接.execute("BEGIN IMMEDIATE")
        连接.execute(
            f"DELETE FROM {常驻进程账本表名} WHERE 网关世代id=? AND 提供者id=?",
            (网关世代id, 提供者id))
        连接.commit()
    except sqlite3.Error:
        连接.rollback()
        raise
    finally:
        连接.close()


def _账本记录存活(组长进程id: int, 进程组号: int | None) -> bool:
    """账本记录对应的整组是否仍存活（组长或同组子孙任一活着即为真）。

    先按组长进程号探活（跨平台）；组长已被回收时再按**组号**探活 —— `setsid` 保证
    组号 == 组长进程号，这是「组长退出、同组子孙仍在」唯一能表达的判据。
    """
    if 组长进程id <= 0:
        return 假
    if 进程终止.进程存活(组长进程id):
        return 真
    if 进程组号 is not None and 进程组号 == 组长进程id:
        return 进程终止.按组号探活(进程组号)
    return 假


def _回收账本行(行: dict[str, Any], *, 等待秒: float,
            宽限秒: float | None = None) -> tuple[bool, str]:
    """回收一条「非本世代」账本记录对应的整组；确认收敛才销行。返回（是否已回收, 说明）。

    `宽限秒` 缺省 `None` ⇒ **一字不改地沿用收口层默认**（`进程终止.终止宽限秒` = 1.0）；
    只有调用方显式传入才透传（C2-①：常驻提供者可持在途长调用，转码/转写可达分钟级，
    1 秒宽限会把它们腰斩、整批重跑。长宽限是**调用方的选择**，不能靠改默认强加给所有调用方）。
    """
    提供者id = str(行.get("提供者id") or "")
    世代 = str(行.get("网关世代id") or "")
    组长进程id = 行.get("组长进程id")
    组长进程id = int(组长进程id) if isinstance(组长进程id, int) and not isinstance(组长进程id, bool) else 0
    组号 = 行.get("进程组号")
    组号 = int(组号) if isinstance(组号, int) and not isinstance(组号, bool) else None
    if 组长进程id <= 0:
        _注销常驻进程(世代, 提供者id)
        return 真, "记录无合法组长进程号，脏行已销"
    if not _账本记录存活(组长进程id, 组号):
        _注销常驻进程(世代, 提供者id)
        return 真, f"整组已不存在（组长 {组长进程id}），销行"
    # 仍活：整组回收走收口层既有能力（终止 → 宽限 → 强杀 → 复查；失败由收口层留痕）
    if 宽限秒 is None:
        进程终止.强制结束子进程(组长进程id)
    else:
        进程终止.强制结束子进程(组长进程id, 宽限秒=宽限秒)
    if 组号 is not None and 组号 == 组长进程id and 进程终止.按组号探活(组号):
        # 组长已被回收但同组子孙仍在（组号 == 组长进程号）→ 按组号补一次强杀
        进程终止.按组号终止(组号, 信号="强杀")
    截止 = time.monotonic() + max(0.0, 等待秒)
    while _账本记录存活(组长进程id, 组号) and time.monotonic() < 截止:
        time.sleep(0.05)
    if _账本记录存活(组长进程id, 组号):
        return 假, f"整组仍未收敛（组长 {组长进程id}），保留账本行待下一世代再收"
    _注销常驻进程(世代, 提供者id)
    return 真, f"整组已回收（组长 {组长进程id}），销行"


def 清扫上一代常驻进程(*, 等待秒: float = 清扫等待秒,
                宽限秒: float | None = None) -> dict[str, Any]:
    """启动时扫一遍世代账本：回收「非本世代且归属网关已消失」的常驻进程整组。

    判据是**归属 + 世代**，不是端口号：
    - 记录世代 == 本世代 → 是本次网关自己的账，交给生命周期管理（不动）；
    - 记录归属网关进程仍活着（且不是本进程）→ 是**另一个仍在运行的网关**的合法财产，跳过
      —— 这也是并发测试/多网关并存时不被误杀的关键；
    - 记录归属网关进程已消失（kill -9 / 异常退出，内存里的 PID 表随之蒸发）→ 孤儿，整组回收。

    只回收「确认整组消失」的行；没收敛的行**保留**，留给下一世代再收（不静默销账）。
    `等待秒` 是强杀后等整组消失的上限。
    返回信封：`{成功, 本世代, 账本行数, 已回收, 未回收, 跳过, 错误说明}`。
    """
    本世代 = 当前网关世代id()
    结果: dict[str, Any] = {
        "成功": 真, "本世代": 本世代, "账本行数": 0,
        "已回收": [], "未回收": [], "跳过": [], "错误说明": "",
    }
    try:
        行表 = 读取常驻进程账本()
    except Exception as 错误:  # noqa: BLE001 —— 账本不可用必须可见（进错误说明），不静默
        结果["成功"] = 假
        结果["错误说明"] = f"世代账本不可读: {type(错误).__name__}: {错误}"
        return 结果
    结果["账本行数"] = len(行表)
    for 行 in 行表:
        提供者id = str(行.get("提供者id") or "")
        if str(行.get("网关世代id") or "") == 本世代:
            continue
        归属进程id = 行.get("网关进程id")
        归属进程id = int(归属进程id) if isinstance(归属进程id, int) and not isinstance(归属进程id, bool) else 0
        if 归属进程id != os.getpid() and 进程终止.进程存活(归属进程id):
            结果["跳过"].append({
                "提供者id": 提供者id, "网关世代id": 行.get("网关世代id"),
                "组长进程id": 行.get("组长进程id"),
                "原因": f"归属网关进程 {归属进程id} 仍在运行（不是孤儿）",
            })
            continue
        try:
            已回收, 说明 = _回收账本行(行, 等待秒=等待秒, 宽限秒=宽限秒)
        except Exception as 错误:  # noqa: BLE001 —— 回收失败必须可见，不静默
            已回收, 说明 = 假, f"回收异常 {type(错误).__name__}: {错误}"
        项 = {"提供者id": 提供者id, "网关世代id": 行.get("网关世代id"),
             "组长进程id": 行.get("组长进程id"), "说明": 说明}
        if 已回收:
            结果["已回收"].append(项)
        else:
            结果["未回收"].append(项)
            结果["成功"] = 假
    if 结果["未回收"]:
        结果["错误说明"] = f"{len(结果['未回收'])} 条上一代常驻进程未收敛（账本行保留）"
    return 结果
