"""sqlite 错误码机器判据常量：迁移可重试主码 / 并发冲突主码 / 主码掩码。

**为什么独立成文件**（拆上帝文件 B1，2026-09-19）：`连接迁移面` 的 `_初始化`
要用 `迁移可重试主码`，而它住在 `运行核心/权威状态.py` 的模块级；若从混入类模块
反向 import 主文件会成环。故把**纯常量**下沉成本文件（叶子，不 import 任何本仓模块），
混入类模块与主文件都可单向依赖它。

**值的一致性怎么保证**：本文件三行常量由拆分脚本从 `运行核心/权威状态.py` 的
拆分前基线**逐字提取**（按整行文本精确匹配，匹配不到即失败），主文件里同名的三行
一字未改 —— 两份取值因此逐字节同源；判据逻辑（`sqlite主错误码` / `是并发冲突`）
仍唯一住在主文件，本文件一个函数都没有。
"""

from __future__ import annotations

import sqlite3

sqlite主码掩码 = 0xFF
并发冲突主码 = frozenset({sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED})
迁移可重试主码 = frozenset({sqlite3.SQLITE_ERROR, sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED})
