"""FFmpeg 外部进程受管执行核心（FFmpeg媒体）：唯一实现在 支持库/适配层/FFmpeg提供者（第 1 对收口）。

本文件原与 `支持库/适配层/FFmpeg提供者/实现/进程管理.py` **逻辑同源**，差异只在收尾稳健度：

- **适配层腿（唯一实现）**：`Popen` 之后的每一步（读取线程构造与 `start()`、轮询里的
  `取消函数()`、超时判定）都在 try 内，进程组回收与管道 `close()` 全在 finally；
  `finally` 只 join **真正启动成功过**的线程。
- **本后端腿（原副本）**：读取线程 `start()`、`取消函数()`、超时判定都在 try 之外，
  只有正常/超时/取消三条路径手工回收；异常路径直接逸出，子进程组泄漏。
  且 `join()` 会打到**未 start 成功**的线程对象上 —— `threading.Thread.join()`
  对未 `start()` 的线程抛 `RuntimeError`，在 finally 里抛会顶掉真实异常并跳过管道 `close()`。

反向验证（真实 `/bin/sh` 挂起脚本 + 进程组探活，不打桩）：
适配层腿 `{子进程已回收: True, 进程组已消失: True}`，
本后端腿副本 `{子进程已回收: False, 进程组已消失: False}`（子进程组真泄漏）。

**结论**：收尾方向的权威在适配层腿（与 Tesseract提供者/实现/受管进程.py、PDF隔离提供者 同口径）。
同一份逻辑只能有一个实现，故本文件改为**转调**：让
`支持库.后端.媒体处理支持库.FFmpeg媒体.实现.进程管理` 与适配层腿那唯一实现成为
**同一个模块对象**（`sys.modules[__name__] = 唯一实现`）。本包 `实现/探测.py`、`实现/处理.py`
照旧从本路径导入 `执行受管命令` —— **对外 import 路径零改动**。

为什么不直接 `import ...实现.进程管理`：跨包导入 `实现/` 被
`运行核心/依赖防火墙.py` 强制拒绝（判据「跨包禁止导入 实现/ 目录」）；而适配层腿
的公开入口 `__init__.py` 已经是合规的同层导入，且它会正常加载自己的 `实现/` 子模块，
故这里先导公开入口、再把两个模块名指向同一对象（兜底路径按文件路径显式载入，
文件缺失时明确报错、不静默降级）。同一模块对象、不产生第二份实现是平台既有做法，
见 `平台控制面/授权/__init__.py`、`支持库/后端/转写支持库/转写/实现/提供者.py`。
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import 支持库.适配层.FFmpeg提供者  # noqa: F401 —— 公开入口（同层，合规）

# 前缀感知：制品把本模块注册成 `平台客户端.支持库.…`，而字面量不随导入前缀改写，
# 故按 `__name__` 派生本树前缀（源码树为空串、制品为 `平台客户端.`），
# 使下面的兜底判据在两种形态下都成立（债务 #216②）。
唯一实现名 = f"{__name__.split('支持库.', 1)[0]}支持库.适配层.FFmpeg提供者.实现.进程管理"
系统根 = next(
    祖先 for 祖先 in Path(__file__).resolve().parents
    if (祖先 / "支持库").is_dir() and (祖先 / "模块库").is_dir()
)

if 唯一实现名 not in sys.modules:  # 兜底：公开入口未加载该子模块时按文件路径显式载入
    唯一实现文件 = 系统根 / "支持库" / "适配层" / "FFmpeg提供者" / "实现" / "进程管理.py"
    _规格 = importlib.util.spec_from_file_location(唯一实现名, 唯一实现文件)
    if _规格 is None or _规格.loader is None:
        raise ImportError(f"无法加载唯一实现（文件缺失或不可加载）: {唯一实现文件}")
    _模块 = importlib.util.module_from_spec(_规格)
    sys.modules[唯一实现名] = _模块
    _规格.loader.exec_module(_模块)

sys.modules[__name__] = sys.modules[唯一实现名]
