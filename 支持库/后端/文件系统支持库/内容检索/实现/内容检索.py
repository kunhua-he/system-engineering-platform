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

默认排除列表 = (
    ".git", ".venv", "venv", "node_modules", "__pycache__", "工程缓存",
    "dist", "build", ".pytest_cache", ".mypy_cache",
)
默认最大匹配数 = 30
硬上限匹配数 = 200


def _解析结果行(文本: str, 根目录: Path, 上限: int) -> list[dict[str, Any]]:
    """解析 `文件:行号:内容` 形式的输出为匹配列表。"""
    import re as _re

    模式 = _re.compile(r"^(.*?):(\d+)[:-](.*)$")
    匹配列表: list[dict[str, Any]] = []
    for 原始行 in 文本.splitlines():
        if not 原始行.strip() or 原始行.startswith("--"):
            continue
        命中 = 模式.match(原始行)
        if not 命中:
            continue
        文件部分, 行号, 内容 = 命中.group(1), 命中.group(2), 命中.group(3)
        路径 = Path(文件部分)
        try:
            相对 = str(路径.resolve().relative_to(根目录)) if 路径.is_absolute() \
                else str((根目录 / 路径).resolve().relative_to(根目录))
        except ValueError:
            相对 = 文件部分
        匹配列表.append({"文件": 相对, "行号": int(行号), "文本": 内容})
        if len(匹配列表) >= 上限:
            break
    return 匹配列表


def 正则搜索(
    根目录: str | None = None,
    模式: str | None = None,
    路径: str = "",
    文件模式: str = "",
    最大匹配数: int | None = None,
    上下文: int = 0,
    忽略大小写: bool = False,
    排除列表: list | None = None,
) -> 结果:
    """按正则表达式搜索目录内文件内容。

    引擎：优先 ripgrep（rg），缺失时回退 grep。返回
    {引擎, 搜索根, 匹配列表[{文件, 行号, 文本}], 匹配数, 已达上限, 命令}。
    排除列表 不传时用 默认排除列表（噪声目录）；传空列表表示不排除任何目录。
    """
    if not isinstance(根目录, str) or not 根目录.strip():
        return 结果.失败("参数不合法", "根目录必须是非空字符串", 来源="内容检索")
    if not isinstance(模式, str) or not 模式:
        return 结果.失败("参数不合法", "模式（正则表达式）不能为空", 来源="内容检索")
    if not isinstance(忽略大小写, bool):
        return 结果.失败("参数不合法", "忽略大小写必须是逻辑型", 来源="内容检索")

    根 = Path(根目录).resolve()
    if not 根.is_dir():
        return 结果.失败("目录不存在", f"根目录不存在: {根}", 来源="内容检索")

    搜索根 = 根
    if isinstance(路径, str) and 路径.strip():
        候选 = (根 / 路径.strip()).resolve()
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
    try:
        搜索根显示 = str(搜索根.relative_to(根)) or "."
    except ValueError:
        搜索根显示 = str(搜索根)
    return 结果.成功结果({
        "引擎": 引擎,
        "搜索根": 搜索根显示,
        "匹配列表": 匹配列表,
        "匹配数": len(匹配列表),
        "已达上限": len(匹配列表) >= 上限,
        "命令": 命令,
    })
