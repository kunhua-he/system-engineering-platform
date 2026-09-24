"""内容检索原子能力：按正则表达式搜索目录内文件内容。

优先使用 ripgrep（rg），不可用时回退系统 grep；两者输出统一解析为
{文件, 行号, 文本} 列表。默认排除常见噪声目录（可用 排除列表 覆盖）。
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any

from 公共契约.基础类型.结果类型 import 结果
from 公共契约.运行时.平台适配 import 解析路径

默认排除列表 = (
    ".git", ".venv", "venv", "node_modules", "__pycache__", "工程缓存",
    "dist", "build", ".pytest_cache", ".mypy_cache",
)
默认最大匹配数 = 30
硬上限匹配数 = 200


def _解析结果行(文本: str, 根目录: Path, 上限: int) -> list[dict[str, Any]]:
    """解析 `文件:行号:内容`（命中行）与 `文件-行号-内容`（上下文行）为匹配列表。

    上下文行是 rg ``-C`` 的产物：rg 用 ``:`` 分隔命中行、用 ``-`` 分隔上下文行。
    两种行**同列在 匹配列表 里**，用 ``是否命中`` 区分。

    为什么必须分两条正则（2026-09-21 实测）：上下文行整行**不含 ``:``**，
    只按 ``文件:行号:内容`` 解析会把上下文行全部丢掉——这正是「``上下文`` 参数
    声明了却没出口」的根因（rg 确实执行了 ``-C``，但结果被解析器吃掉）。
    ``上限`` **只数命中行**：上下文行不占额度，否则 上下文=3 会把可回命中数压到 1/7。
    """
    import re as _re

    命中模式 = _re.compile(r"^(.*?):(\d+):(.*)$")
    上下文模式 = _re.compile(r"^(.*?)-(\d+)-(.*)$")
    匹配列表: list[dict[str, Any]] = []
    命中数 = 0
    for 原始行 in 文本.splitlines():
        if not 原始行.strip() or 原始行.startswith("--"):
            continue
        命中 = 命中模式.match(原始行)
        是否命中 = True
        if 命中 is None:
            命中 = 上下文模式.match(原始行)
            是否命中 = False
        if 命中 is None:
            continue
        文件部分, 行号, 内容 = 命中.group(1), 命中.group(2), 命中.group(3)
        if 是否命中:
            if 命中数 >= 上限:
                break
            命中数 += 1
        try:
            # 「相对 → 绝对」转调全平台唯一那条解析腿，生效根取本函数收到的 `根目录`
            # （调用方给的搜索根）—— 本函数不自带 `is_absolute()` 拼根分支。
            相对 = str(Path(解析路径(文件部分, 根目录)).resolve().relative_to(根目录))
        except ValueError:
            相对 = 文件部分
        匹配列表.append({"文件": 相对, "行号": int(行号), "文本": 内容, "是否命中": 是否命中})
    return 匹配列表


def _紧凑行(条: dict[str, Any]) -> str:
    """匹配列表的一项 → 紧凑一行文本（`紧凑返回=真` 专用）。

    形如 ``文件:行号:文本``（命中行）或 ``文件-行号-文本``（上下文行）—— 与 rg ``-C``
    的既有约定**逐字同形**（`_解析结果行` 正是按这个约定区分两种行的），故
    **命中信息一个不少**：文件 / 行号 / 内容 / 命中与上下文 四项全在，只是不再逐项
    重复那四个键名（实测 16 命中：2,635 → 1,312 字符，降 50.2%；读数与口径见
    `开发文档/分析/批R单据_R15_批量取证_20260924.md`）。
    """
    分隔 = ":" if 条.get("是否命中") else "-"
    return f"{条['文件']}{分隔}{条['行号']}{分隔}{条['文本']}"


def 正则搜索(
    根目录: str | None = None,
    模式: str | None = None,
    路径: str = "",
    文件模式: str = "",
    最大匹配数: int | None = None,
    上下文: int = 0,
    忽略大小写: bool = False,
    排除列表: list | None = None,
    紧凑返回: bool = False,
) -> 结果:
    """按正则表达式搜索目录内文件内容。

    引擎：优先 ripgrep（rg），缺失时回退 grep。返回
    {引擎, 搜索根, 匹配列表[{文件, 行号, 文本, 是否命中}], 匹配数, 上下文数, 已达上限, 命令}。
    排除列表 不传时用 默认排除列表（噪声目录）；传空列表表示不排除任何目录。
    上下文 大于 0 时，命中行的前后各 上下文 行一并回在 匹配列表 里（是否命中=假），
    上限只数命中行。

    **路径口径与「不静默」（2026-09-24 批R·R-26）**：`根目录` 与 `路径` 都走
    全平台唯一那条解析腿（`根目录` 改前自成一条腿），**绝对路径与项目根相对路径都收**；
    目录不存在 ⇒ 明确报 `目录不存在`（说明里带解析后的绝对路径与相对写法示例）。
    另新增恒在键 `搜索根绝对路径`：**如实回带实际搜索的绝对目录** ——
    改前只回 `搜索根`（相对 根目录 的写法，路径省略时恒为 `.`），0 命中时调用方
    无从核对「到底搜了哪」，只能去翻 `命令`（紧凑档还没有它）。这是 R-23 单据 §7.3
    「静默 0 命中」的真形态：0 命中本身可读（`匹配数=0`），**不可读的是搜索落点**。

    **紧凑返回（2026-09-24 批R R-15 只增开关，默认 假）**：真 时去掉 `命令` 回显
    （实测占 27%）并把 `匹配列表` 压成 `命中行`（每条 ``文件:行号:文本`` /
    ``文件-行号-文本``，信息一个不少）；**不传（默认 假）时返回与改前逐字节一致**。
    """
    if not isinstance(根目录, str) or not 根目录.strip():
        return 结果.失败("参数不合法", "根目录必须是非空字符串", 来源="内容检索")
    if not isinstance(模式, str) or not 模式:
        return 结果.失败("参数不合法", "模式（正则表达式）不能为空", 来源="内容检索")
    if not isinstance(忽略大小写, bool):
        return 结果.失败("参数不合法", "忽略大小写必须是逻辑型", 来源="内容检索")
    if not isinstance(紧凑返回, bool):
        return 结果.失败("参数不合法", "紧凑返回必须是逻辑型", 来源="内容检索")

    # ★ 2026-09-24 批R·R-26：`根目录` 改走**全平台唯一那条解析腿**（改前是
    #   `Path(根目录).resolve()` —— 自成一条腿：只认进程 cwd、不认「锁定的项目根」，
    #   与 `路径` 的解析口径不一致）。绝对与相对**都收**（华哥 2026-09-22 裁决：
    #   「无论输入绝对路径，还是相对路径，只要文件存在，就可以使用的兼容性才对」；
    #   调用账实测：`根目录` 传绝对的 698 次、传相对的 66 次 ⇒ 只收相对会是回归）。
    #   **本函数不做自写路径判定**（唯一腿是 `系统核心支持库.路径安全.校验路径`，哲学 1.2）。
    根 = Path(解析路径(根目录.strip())).resolve()
    if not 根.is_dir():
        return 结果.失败(
            "目录不存在",
            f"根目录不存在: {根}（绝对路径与项目根相对路径都收；"
            f"相对写法示例：根目录='模块库/开工编排'）",
            来源="内容检索")

    搜索根 = 根
    if isinstance(路径, str) and 路径.strip():
        候选 = Path(解析路径(路径.strip(), 根)).resolve()
        if not 候选.is_dir():
            return 结果.失败("目录不存在", f"搜索路径不存在: {候选}", 来源="内容检索")
        搜索根 = 候选

    上限 = max(1, min(int(最大匹配数) if isinstance(最大匹配数, int) and not isinstance(最大匹配数, bool)
                     else 默认最大匹配数, 硬上限匹配数))
    上下文数 = max(0, min(int(上下文) if isinstance(上下文, int) and not isinstance(上下文, bool) else 0, 3))
    排除项 = tuple(排除列表) if isinstance(排除列表, list) else 默认排除列表

    rg = shutil.which("rg")
    if rg:
        命令 = [rg, "--line-number", "--with-filename", "--no-heading", "--color", "never",
                "--max-count", str(上限)]
        if 忽略大小写:
            命令.append("-i")
        if 上下文数:
            命令.extend(["-C", str(上下文数)])
        for 项 in 排除项:
            命令.extend(["--glob", f"!{项}"])
            命令.extend(["--glob", f"!**/{项}/**"])
        if isinstance(文件模式, str) and 文件模式:
            命令.extend(["--glob", 文件模式])
        命令.extend(["--", 模式, str(搜索根)])
        引擎 = "rg"
    else:
        命令 = ["grep", "-R", "-n", "-I"]
        if 忽略大小写:
            命令.append("-i")
        for 项 in 排除项:
            命令.append(f"--exclude-dir={Path(项).name}")
            命令.append(f"--exclude={Path(项).name}")
        if isinstance(文件模式, str) and 文件模式:
            命令.append(f"--include={文件模式}")
        命令.extend(["--", 模式, str(搜索根)])
        引擎 = "grep"

    try:
        进程 = subprocess.run(命令, capture_output=True, cwd=str(根), timeout=60)
    except subprocess.TimeoutExpired:
        return 结果.失败("超时", "内容检索超过 60 秒", 来源="内容检索")
    except OSError as 错误:
        return 结果.失败("执行失败", f"检索命令无法执行: {错误}", 来源="内容检索")

    输出 = (进程.stdout or b"").decode("utf-8", errors="replace")
    if 进程.returncode not in (0, 1):      # rg/grep 无匹配时返回 1，属正常
        错误文本 = (进程.stderr or b"").decode("utf-8", errors="replace")[:300]
        return 结果.失败("检索失败", f"{引擎} 返回 {进程.returncode}: {错误文本}", 来源="内容检索")

    匹配列表 = _解析结果行(输出, 根, 上限)
    命中数 = sum(1 for 条 in 匹配列表 if 条.get("是否命中"))
    try:
        搜索根显示 = str(搜索根.relative_to(根)) or "."
    except ValueError:
        搜索根显示 = str(搜索根)
    if 紧凑返回:
        return 结果.成功结果({
            "引擎": 引擎,
            "搜索根": 搜索根显示,
            "搜索根绝对路径": str(搜索根),
            "命中行": [_紧凑行(条) for 条 in 匹配列表],
            "匹配数": 命中数,
            "上下文数": 上下文数,
            "已达上限": 命中数 >= 上限,
        })
    return 结果.成功结果({
        "引擎": 引擎,
        "搜索根": 搜索根显示,
        "搜索根绝对路径": str(搜索根),
        "匹配列表": 匹配列表,
        "匹配数": 命中数,
        "上下文数": 上下文数,
        "已达上限": 命中数 >= 上限,
        "命令": 命令,
    })
