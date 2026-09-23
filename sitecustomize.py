"""仓库级 `sitecustomize`：**本项目目录内跑起来的 Python 进程必须经 MCP**，否则拒绝。

## 这是什么（华哥 2026-09-23 裁决的机器落点）

> 「运行本项目的代码的时候，除了 mcp 可以运行以外，终端直接禁止运行……给 mcp 加上
>  一个识别符号。当运行的时候，本地文件都要对账。这个都是毫秒级的。反正快。然后
>  **没对上账直接报错**。返回错误提示词。**请使用***来运行**。类似于这样子的形式。」
>
> 「其实我更趋向于**直接给 python 做上这个目录的限制**。**如果没对上账的直接拒绝**。
>  这个反而感觉轻量化一些。」

`sitecustomize` 是 CPython 解释器**启动时自动加载**的钩子（`site` 模块的
`execsitecustomize`）。放在仓库根、且仓库根命中解释器的模块搜索路径时，本项目目录内
跑起来的一切 `python3.14 …` 都会先经过本模块：对账不过就**打印替代命令并以退出码 1
拒绝启动**，绝不静默继续。

## 判据（三层，穷尽）

1. **本进程是不是在本项目目录内跑**：`Path.cwd()` 在仓库根下，**或** `sys.argv[0]`
   解析出的脚本路径在仓库根下 ⇒ 算「在本项目内」。两处都不命中 ⇒ **不拦**
   （用户机器上还有别的项目，在别处跑本项目不该误伤）。
2. 在本项目内 ⇒ 调 `公共契约.运行时.平台适配.MCP身份准入()`：
   · 带识别符号 `系统库网关凭证`（MCP 腿经 40007 网关注入）⇒ 放行；
   · 或设了修 MCP 白名单 `系统平台_修MCP自身` ⇒ 放行（「修 mcp 可以用终端」的口子）；
   · 两者都没有 ⇒ 取 `对账MCP身份()` 的说明（**拒绝文本的唯一来源**，本模块不另写
     一份替代命令）打印到 stderr 并退出码 1。
3. 判据自己取不到（导入 `平台适配` 失败等）⇒ **fail-closed**：打印诊断并退出码 1
   （不许因为「判据自己坏了」而变成静默放行 —— 那正是华哥要堵的「静默继续」）。

## 局限（**如实标注：这是轻量层，不是唯一防线**）

下面每一条都实测过（2026-09-23，本机 Python 3.14.4，命令均可照抄复跑）。
**任一条都能绕过本层**，故**不许把「本模块写好了」说成「终端跑不起来了」**：

· **只有 `PYTHONPATH` 命中本目录才加载**（实测）：
      cd <仓库根> && python3.14 -c "print(1)"            # cwd=仓库根，**不加载**
      cd <仓库根> && python3.14 -m json.tool </dev/null   # **不加载**
      cd <仓库根> && python3.14 某脚本.py                 # **不加载**
      cd <仓库根> && PYTHONPATH=<仓库根> python3.14 -c "print(1)"   # **加载**
  根因：`sys.path[0]`（cwd / 脚本目录）是在 `site` 初始化**之后**才插入的，
  `sitecustomize` 查找时还看不见它。而本仓《通用纪律》恰恰要求「跑项目命令前先
  unset PYTHONPATH」⇒ **默认的终端腿根本不经过本层**，它靠的是写入腿那层
  （`支持库/后端/文件系统支持库/**` 的落盘对账）。
· **`-S` / `-E` 跳过 site 初始化** ⇒ 本模块根本不加载（实测）：
      cd <仓库根> && PYTHONPATH=<仓库根> python3.14 -S -c "print('S ran')"  # 输出 S ran，退出码 0
· **临时清空 / 前置改写 `PYTHONPATH`**（`env -u PYTHONPATH …`、`PYTHONPATH= …`）⇒ 同第 1 条。
· **不用 Python 直接落盘**（`echo > 文件`、`sed -i`、`git checkout`、agent 自带的
  文件编辑工具、`dd`）⇒ 根本不经过 Python，本层与写入腿都管不到。
· **设了修 MCP 白名单**（`系统平台_修MCP自身`）⇒ 按设计放行（那是正式口子，不是绕过）。

⇒ 本层拦的是「在本项目目录里、带着本项目 `PYTHONPATH`、没带识别符号的 `python3.14` 直跑」，
与华哥「终端直接禁止运行」的意图对齐；再往上「整仓文件系统只读 + 原子写」是更强的
下一层（本仓写入腿已改原子写为其铺路），**不在本轮**。

## 一个必须处理的副作用：本文件会**遮蔽**标准库的同名文件

`PYTHONPATH` 排在标准库之前，故本文件一旦加载就遮蔽了标准库目录里那份
`sitecustomize.py`。实测（2026-09-23）：Homebrew 的 Python 3.14 自带一份
`sitecustomize.py`，它做 sys.path 手术（把 `/Library/Python/3.14/site-packages`
挪到末尾、把 `Cellar` 前缀改写成 `opt` 短前缀、`site.addsitedir('/opt/homebrew/
lib/python3.14/site-packages')`）。**遮蔽它会让第三方包不可导入** —— 实测
`PYTHONPATH=<仓库根> 系统库网关凭证=x python3.14 -c "import psycopg"` 报
`ModuleNotFoundError: No module named 'psycopg'`（`import docx` 同），
而不带 `PYTHONPATH` 时两个都 `ok`。故本模块**先按路径把被遮蔽的那份执行掉**，
再做自己的对账（见 `_执行被遮蔽的标准库sitecustomize()`）—— 实测修复后
`import psycopg` / `import docx` 均恢复 `ok`。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

#: 本文件所在的目录就是仓库根（本文件按约定只住在仓库根）。
仓库根 = Path(__file__).resolve().parent


def _执行被遮蔽的标准库sitecustomize() -> None:
    """把**被本文件遮蔽的**标准库 `sitecustomize.py` 先按路径执行一遍。

    为什么必须做（2026-09-23 实测）：`PYTHONPATH` 排在标准库之前，本文件一旦加载就遮蔽
    标准库目录里那份同名文件。Homebrew 的 Python 3.14 自带一份，它做 sys.path 手术
    （`/Library/.../site-packages` 挪末尾、`Cellar` 前缀改写、`site.addsitedir`）。
    遮蔽它的后果实测：`PYTHONPATH=<仓库根> python3.14 -c "import psycopg"` ⇒
    `ModuleNotFoundError`（`import docx` 同），不设 `PYTHONPATH` 时两个都 `ok`。

    失败一律吞掉（best-effort）：标准库没有这份文件、或它不是 Python 源、或它自己抛错，
    都**不许**反噬 —— 它只是「恢复本该发生的副作用」，不是本层判据的一部分。
    """
    import importlib.util
    import sysconfig

    try:
        标准库目录 = str(sysconfig.get_paths().get("stdlib") or "")
        if not 标准库目录:
            return
        候选 = Path(标准库目录) / "sitecustomize.py"
        if not 候选.is_file() or 候选.resolve() == Path(__file__).resolve():
            return
        规格 = importlib.util.spec_from_file_location(
            "_被遮蔽的标准库sitecustomize", str(候选))
        if 规格 is None or 规格.loader is None:
            return
        模块 = importlib.util.module_from_spec(规格)
        规格.loader.exec_module(模块)
    except Exception:
        # 故意吞：这是恢复副作用，不是判据。真正判据在下面，照做。
        pass


def _在仓库根下(路径文本: str) -> bool:
    """路径（可能为空 / 不存在 / 非法）解析后是否落在仓库根之下。

    解析失败一律返回 ``假``（不抛）：本函数只回答「是不是在本项目内」，
    拿不准就当不在 —— 在别处误伤的代价比漏拦大得多（用户机器上还有别的项目）。
    """
    if not 路径文本:
        return False
    # 边界项（批G L3 类1，**保留**）：本判据**必须**不依赖平台。它回答的正是
    # 「要不要加载平台」——`在本项目内跑()` 为真时下方才 import `MCP身份准入`，
    # 导入失败走 fail-closed 拒绝启动。若本判据改调唯一腿，平台一缺件它就先崩/先
    # 返回假 ⇒ 整层守卫退化成**静默放行**（本文件「局限」一节最忌的那种）。
    # 另：唯一腿把 `~` 展开成家目录、并给相对值加一层「环境变量 系统平台_项目根」
    # 优先级，与「就按进程 cwd 判在不在本仓」不是同一件事（后者才是本判据的语义）。
    try:
        候选 = Path(路径文本)
        if not 候选.is_absolute():
            候选 = Path.cwd() / 候选
        候选 = 候选.resolve()
    except (OSError, ValueError):
        return False
    return 候选 == 仓库根 or 仓库根 in 候选.parents


def 在本项目内跑() -> bool:
    """本进程是否「在本项目目录内跑」：cwd 在仓库根下，或所跑脚本在仓库根下。"""
    try:
        if _在仓库根下(str(Path.cwd())):
            return True
    except OSError:
        pass
    return _在仓库根下(sys.argv[0] if sys.argv else "")


def _拒绝(说明: str) -> None:
    """打印拒绝说明并以退出码 1 结束进程。

    为什么用 ``os._exit(1)`` 而不是 ``sys.exit(1)``（2026-09-23 实测）：``sys.exit(1)``
    抛出的 ``SystemExit`` 会从 ``site.execsitecustomize`` 逸出，解释器打一整屏
    ``Fatal Python error: init_import_site`` 回溯 —— 退出码同样是 1（**不是静默继续**，
    这一点已实测确认），但那份回溯会盖住我们这句唯一线索。``os._exit(1)`` 只留我们自己
    flush 过的那句，退出码一致，故取它。
    """
    sys.stderr.write(说明.rstrip("\n") + "\n")
    sys.stderr.flush()
    os._exit(1)


# 无条件先恢复被遮蔽的标准库同名文件的副作用（否则第三方包会不可导入）。
# **不能放进下面的 if 里**：本文件只要被加载就遮蔽了它，与「本进程在不在本项目内」无关
# —— 在别处跑（cwd 不在本项目）时不恢复，就是拿本项目去误伤别人的项目。
_执行被遮蔽的标准库sitecustomize()


if 在本项目内跑():
    try:
        from 公共契约.运行时.平台适配 import MCP身份准入

        通过, 说明 = MCP身份准入()
    except Exception as 错误:  # 判据自己坏了 —— fail-closed，不许静默放行
        _拒绝(
            "启动被拒绝：本项目的代码只能经 MCP 运行，但身份判据不可用"
            f"（{type(错误).__name__}: {错误}）。\n"
            "请使用：\n"
            '  capability_call(能力id="自修复工具.静态编译", '
            '参数={"类型": 1, "模块ID": "<你改的库或模块>"})\n'
            "（若你确实在修 MCP 自身：设环境变量 "
            "`系统平台_修MCP自身` 后重跑。）"
        )
    if not 通过:
        _拒绝(说明)
