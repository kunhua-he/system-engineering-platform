#!/usr/bin/env python3.14
"""工具模块热重载：改 MCP工具箱 下工具代码后，免重启进程即时生效。

为什么需要它：8765/8766 管理端启动时，把全部工具实现一次性顶层导入（`from .协作状态 import 收口登记`
这一串），之后改源码不重启就不生效 —— 平台所有管理端改动都被"必须重启"卡住。本模块在
每次工具调用入口比对一次源码时间戳，只重载变化的同包工具模块；服务对象与会话保持存活，
MCP 连接不断。与网关侧的 `运维脚本/热接入.py`（增量装配、不重启进程）同源同精神。

刻意不做的边界：
- 不重载入口 `项目服务.py` 与自身：工具的新增 / 删除 / 参数表变更仍需重启。
- 不重载 `公共契约` / `运行核心` / `平台控制面` 等其他包：改那些仍需重启。
- 重载失败不抛错、不降级：保留旧实现，源码修好后的下一次变更自动重试。

依据：开发文档/多会话并行开发规约.md、
     开发文档/决策记录/0008_能力更新走热接入不重启网关.md
"""

from __future__ import annotations

import ast
import importlib
import sys
import threading
from pathlib import Path

# 模块名 → 上次成功重载时的源码纳秒时间戳；失败不更新，故坏源码不会永久卡死后续重载。
_快照: dict[str, int] = {}
# 后台作业线程与事件循环会并发进入本模块，重载同一模块与回填全局必须串行。
_重载锁 = threading.RLock()


def 依赖顺序(模块根: Path) -> list[str]:
    """按「被依赖者在前」返回同包模块名顺序。

    只认 `from .X import ...` 这一种同包依赖形式（本项目内部依赖全部是这种写法）。
    拓扑序是必需的：若先重载依赖方、后重载被依赖方，依赖方拿到的仍是旧的被依赖对象。
    """
    依赖表: dict[str, set[str]] = {}
    for 路径 in sorted(模块根.glob("*.py")):
        if 路径.name == "__init__.py":
            continue
        名 = 路径.stem
        依赖: set[str] = set()
        try:
            树 = ast.parse(路径.read_text(encoding="utf-8"))
        except (OSError, SyntaxError):
            依赖表[名] = 依赖
            continue
        for 节点 in ast.walk(树):
            if isinstance(节点, ast.ImportFrom) and 节点.level == 1 and 节点.module:
                依赖.add(节点.module)
        依赖表[名] = {项 for 项 in 依赖 if (模块根 / f"{项}.py").is_file()}

    结果: list[str] = []
    已完成: set[str] = set()
    进行中: set[str] = set()

    def _访问(名: str) -> None:
        if 名 in 已完成 or 名 in 进行中:
            return
        进行中.add(名)
        for 依赖 in sorted(依赖表.get(名, ())):
            if 依赖 in 依赖表:
                _访问(依赖)
        进行中.discard(名)
        已完成.add(名)
        结果.append(名)

    for 名 in sorted(依赖表):
        _访问(名)
    return 结果


def 扫描并重载工具模块(
    模块根: Path,
    目标全局: dict,
    排除: set[str] | None = None,
) -> list[str]:
    """串行包装：后台作业线程与事件循环会并发调用，重载与回填必须互斥。"""
    with _重载锁:
        return _扫描并重载已加锁(模块根, 目标全局, 排除)


def _扫描并重载已加锁(
    模块根: Path,
    目标全局: dict,
    排除: set[str] | None = None,
) -> list[str]:
    """比对源码时间戳，重载变化的同包模块，并把其自有定义回填到 `目标全局`。

    返回本次**实际重载成功**的模块名。首次调用只记录基线，返回空列表。
    重载失败的模块不更新快照，下一次调用会自动重试（源码修好即自愈）。
    """
    包名 = 目标全局.get("__package__") or 模块根.name
    排除集 = set(排除 or ()) | {"__init__", "热重载"}
    顺序 = [名 for 名 in 依赖顺序(模块根) if 名 not in 排除集]

    待重载: list[tuple[str, int]] = []
    for 名 in 顺序:
        try:
            时间 = (模块根 / f"{名}.py").stat().st_mtime_ns
        except OSError:
            continue
        旧时间 = _快照.get(名)
        if 旧时间 is None:
            _快照[名] = 时间  # 首次只记基线
            continue
        if 旧时间 != 时间:
            待重载.append((名, 时间))

    if not 待重载:
        return []

    importlib.invalidate_caches()
    已重载: list[str] = []
    for 名, 时间 in 待重载:
        全名 = f"{包名}.{名}"
        if 全名 not in sys.modules:
            _快照[名] = 时间
            continue
        try:
            模块 = importlib.reload(sys.modules[全名])
        except Exception:
            continue  # 源码暂时坏了：保留旧实现，不打断本次调用，快照不更新以便重试
        _快照[名] = 时间
        已重载.append(名)
        _回填(模块, 全名, 目标全局)
    return 已重载


def _回填(模块: object, 全名: str, 目标全局: dict) -> None:
    """把模块**自己定义**的函数 / 类回填到目标模块全局。

    只回填 `__module__` 指向本模块的对象：避免把模块内部 import 进来的同名符号
    （如 pathlib.Path、json）误覆盖到入口模块的同名全局上。
    """
    for 名, 对象 in vars(模块).items():
        if 名.startswith("_") or 名 not in 目标全局:
            continue
        if getattr(对象, "__module__", None) != 全名:
            continue
        目标全局[名] = 对象
