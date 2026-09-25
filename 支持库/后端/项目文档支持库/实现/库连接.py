"""项目文档支持库 · 索引库连接层（进程内共用，不对外暴露）。

**为什么单独成文件**：`索引库.py` 与 `未命中词.py` 共用同一个 SQLite 库文件，
若两边互相 import 会形成循环（实测：`ImportError: cannot import name '_连接'
from partially initialized module`）。把「库路径解析 + 连接 + 建表」这三件事
抽到本文件后，依赖是单向的：

    索引库.py ──┐
                ├──> 库连接.py
    未命中词.py ─┘

**口径**：库文件位置 = `<运行数据根>/项目文档库.db`（经唯一解析器，
禁止裸拼 `工程缓存`）。检索口径与记忆支持库「仅关键词」同哲学：
**默认纯 SQLite + 字符串匹配，不调用大模型与向量**。

**落点口径（2026-09-25 收口）**：`库文件` 入参**只许指非受管面**（`工程缓存/` 豁免前缀
或仓库外）—— 受管面落点一律 fail-closed 拒绝，理由与取证见 `_库路径`。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from 公共契约.运行时.运行缓存 import 解析运行数据根
from 公共契约.运行时.导入前缀 import 取系统根
from 公共契约.运行时.写入授权 import 受管相对路径

系统根 = 取系统根(__file__)
默认库文件 = 解析运行数据根(系统根) / "项目文档库.db"

建表语句 = (
    """CREATE TABLE IF NOT EXISTS 项目登记(
       项目名 TEXT PRIMARY KEY, 项目根目录 TEXT NOT NULL, 文档根相对路径 TEXT NOT NULL,
       规范文件 TEXT NOT NULL, 登记时间 TEXT NOT NULL, 更新时间 REAL NOT NULL);""",
    """CREATE TABLE IF NOT EXISTS 文档索引(
       项目名 TEXT NOT NULL, 文档相对路径 TEXT NOT NULL, 标题 TEXT NOT NULL,
       文档类型 TEXT NOT NULL, 内容摘要 TEXT NOT NULL, 段数 INTEGER NOT NULL,
       字节数 INTEGER NOT NULL, 文件修改时间 REAL NOT NULL, 入库时间 REAL NOT NULL,
       PRIMARY KEY(项目名, 文档相对路径));""",
    """CREATE TABLE IF NOT EXISTS 块索引(
       块id INTEGER PRIMARY KEY AUTOINCREMENT, 项目名 TEXT NOT NULL, 文档相对路径 TEXT NOT NULL,
       起始行 INTEGER NOT NULL, 结束行 INTEGER NOT NULL, 块类型 TEXT NOT NULL, 块文本 TEXT NOT NULL);""",
    # 未命中词表：与其余三表同库（不新建库文件），随第一次使用惰性建齐
    """CREATE TABLE IF NOT EXISTS 未命中词(
       项目名 TEXT NOT NULL, 原始词 TEXT NOT NULL, 建议词 TEXT NOT NULL,
       命中次数 INTEGER NOT NULL DEFAULT 0, 登记时间 REAL NOT NULL, 更新时间 REAL NOT NULL,
       PRIMARY KEY(项目名, 原始词));""",
    "CREATE INDEX IF NOT EXISTS 文档索引_项目_时间 ON 文档索引(项目名, 入库时间 DESC);",
    "CREATE INDEX IF NOT EXISTS 块索引_项目_文档 ON 块索引(项目名, 文档相对路径);",
    "CREATE INDEX IF NOT EXISTS 未命中词_项目_命中 ON 未命中词(项目名, 命中次数 DESC);",
)


def _库路径(库文件: str) -> Path:
    """归一化库文件参数：留空取默认；给值必须是绝对路径（相对路径一律拒绝）+ **非受管面**。

    ★ 2026-09-25（写入凭证透传门禁 · 公开层红项收口，触发项 `建全仓索引`）：
    **受管面内的落点一律拒绝（fail-closed）**。

    ## 为什么不是「补一个 `开工ID` 透传到写腿」（而是收窄落点）
    本腿是 **SQLite 增量直写**（`sqlite3.connect` + `execute`，见 `_连接`），而平台唯一写入腿
    （`系统核心支持库.资源管理.原子写入` → `文件系统支持库.文件操作.写入文件`）只收**整值**
    —— 整库原子替换会毁掉这个**共享活库**（40007 常驻网关对
    `工程缓存/运行数据/项目文档库.db` 持有 123 个句柄、WAL 增量写；现场取证见
    `_自动关闭连接` 的 docstring）。⇒ 本腿**不可能**成为受管面的写腿，
    给它挂 `开工ID` 只会是「声明了但消费不了」的装饰性合规（正是门禁判据 C 在治的形态）。
    按单腿铁律（受管面写入只许走平台写腿）**收窄落点**：`库文件` 必须落在非受管面
    （`工程缓存/` 豁免前缀 或 仓库外）。

    ## 影响面
    默认值（`工程缓存/运行数据/项目文档库.db`）与全部调用方（测试一律用临时目录，
    见 `测试中心/支持库/测试_项目文档支持库.py`）都在非受管面 ⇒ 一处不改。
    受管落点此前是**静默直写**（不经写入授权），现在改成 fail-closed 拒绝
    —— 本包 11 条带 `库文件` 的能力（写入索引/登记项目/记踩坑/…）共用本入口，收在这里即全收。
    """
    if 库文件 is None or not str(库文件).strip():
        路径 = 默认库文件
    else:
        文本 = str(库文件).strip()
        if not Path(文本).is_absolute():
            raise ValueError(f"库文件必须是绝对路径: {文本}")
        路径 = Path(文本)
    受管, 相对, _理由 = 受管相对路径(str(路径))
    if 受管:
        raise ValueError(
            f"库文件不得落在仓库受管面内（{相对}）：本库是 SQLite 增量直写、不是平台写入腿，"
            f"按单腿铁律（受管面写入只许走平台写腿）不许写受管面。"
            f"请把 库文件 指到 工程缓存/ 或仓库外（留空即取 {默认库文件}）。")
    return 路径


class _自动关闭连接(sqlite3.Connection):
    """`with` 退出时**真关闭**的连接（标准库 `with sqlite3.connect()` 只提交事务、不关连接）。

    ## 为什么必须有它（2026-09-20 实测的真 bug，不是设计取舍）
    全仓 15 处都写成 `with _连接(库文件) as 连接:`，但 `with` 原生 sqlite3.Connection
    **只做事务提交/回滚，不释放文件句柄**（实测：`with c:` 之后 `c.execute('SELECT 1')`
    仍可用）。⇒ 每调用一次泄漏一个 FD，WAL 模式下每个连接还额外占 -wal / -shm。

    现场证据：40007 常驻网关对 `工程缓存/运行数据/项目文档库.db` 持有 **123 个句柄**，
    进程总 FD 342 撞上 `launchctl maxfiles=256` 后，所有库操作稳定失败
    `索引库不可用：unable to open database file`，同时 `审计/安全审计.jsonl`
    也报 `Too many open files` —— 而磁盘、权限、直连写入全部正常。

    修在**唯一连接入口**而非逐个调用点：调用点不改一个字，也不会出现
    「有的地方关了、有的没关」的第二条腿。
    """

    def __exit__(self, 异常类型, 异常, 回溯) -> bool:  # type: ignore[override]
        结果 = super().__exit__(异常类型, 异常, 回溯)
        self.close()          # 关键：标准库不做这一步
        return 结果


def _连接(库文件: str) -> sqlite3.Connection:
    """打开库并确保表齐（幂等）；父目录不存在则创建（运行数据根可能尚未建）。

    返回 `_自动关闭连接`：调用方照旧 `with _连接(...) as 连接:` 即自动回收句柄。
    """
    路径 = _库路径(库文件)
    路径.parent.mkdir(parents=True, exist_ok=True)
    连接 = sqlite3.connect(路径, timeout=10, factory=_自动关闭连接)
    连接.execute("PRAGMA journal_mode=WAL")
    连接.execute("PRAGMA busy_timeout=10000")
    for 语句 in 建表语句:
        连接.execute(语句)
    连接.commit()
    return 连接
