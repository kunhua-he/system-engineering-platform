"""派活前核验：这条待办是否已经被修好了？（防止重复派活白耗子代理）。

**为什么需要它（2026-09-18 主会话实测教训）**：
主会话按 `未完成事项.md` 条目批量派了 12 路，其中 **6 路开工后发现「缺陷早已在批A
（提交 `97ca5792`）修完」**——子代理正确地停下并改做独立复核，但整批仍白耗约 30 分钟。
根因不是条目没写清楚，是**派活流程缺一步「先核验该条是否已闭合」**。按哲学 14.3
（反复犯错的开发要补底层），补的是流程里那个缺口，不是再叮嘱一次。

**它怎么判**：对指定文件查 git 历史——最近几次改动、以及按关键词（`-S` 代码增删 +
`--grep` 提交信息）命中的提交。有命中 ⇒ 很可能已修，**改派「独立复核 + 反向验证」**。

用法：
    python3.14 开发工具/派活前核验.py --文件 运行核心/权威状态.py --关键词 A1 原子性
    python3.14 开发工具/派活前核验.py --多条 未完成事项.md
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

# 系统根必须在取正式类型名**之前**算好并插入 sys.path —— 否则全新解释器
# 下 `from 公共契约...` 会 ModuleNotFoundError（本工具的调用方常年在仓库外跑）。
系统根 = Path(__file__).resolve().parents[1]
if str(系统根) not in sys.path:
    sys.path.insert(0, str(系统根))

from 公共契约.基础类型.逻辑类型 import 真, 假

git = "/Library/Developer/CommandLineTools/usr/bin/git"


def 跑(参数: list[str]) -> str:
    """跑一条 git 命令；失败返回空串（不抛，核验工具本身不该阻断流程）。"""
    try:
        结果 = subprocess.run([git, *参数], cwd=系统根, capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return 结果.stdout.strip()


def 查文件(文件: str, 关键词: list[str]) -> dict:
    """对一个文件：最近提交 + 关键词命中的提交。"""
    最近 = 跑(["log", "--oneline", "-5", "--date=short", "--format=%h %ad %s", "--", 文件])
    命中: list[tuple[str, str]] = []
    for 词 in 关键词:
        段 = 跑(["log", "--oneline", "-3", f"-S{词}", "--", 文件]) or 跑(["log", "--oneline", "-3", f"--grep={词}", "--", 文件])
        if 段:
            命中.append((词, 段))
    return {"最近提交": 最近, "关键词命中": 命中}


def _打印(文件: str, 果: dict) -> bool:
    print(f"=== {文件} ===")
    print("最近 5 次改动：")
    print("  " + (果["最近提交"].replace("\n", "\n  ") if 果["最近提交"] else "（无提交记录）"))
    if 果["关键词命中"]:
        print("关键词命中（**先读这些提交，再决定派不派活**）：")
        for 词, 段 in 果["关键词命中"]:
            print(f"  [{词}] " + 段.replace("\n", "\n        "))
        return 真
    print("关键词无命中（该缺陷可能尚未修，可派活）")
    return 假


def 主函数(argv: list[str] | None = None) -> int:
    解析 = argparse.ArgumentParser(description="派活前核验：这条待办是否已经修好")
    解析.add_argument("--文件", default="", help="待修文件的仓库相对路径")
    解析.add_argument("--关键词", nargs="*", default=[], help="缺陷关键词（如 A1 原子性）")
    参 = 解析.parse_args(argv)
    if not 参.文件:
        print("必须给 --文件 <仓库相对路径>")
        return 2
    if not (系统根 / 参.文件).exists():
        print(f"⚠️ 该路径在主干不存在：{参.文件}")
        print("   → 可能已被搬走或删除。**先确认归属再派活**（别让子代理去全盘搜）。")
        return 2
    有命中 = _打印(参.文件, 查文件(参.文件, 参.关键词))
    print()
    if 有命中:
        print("判据：**很可能已经修好了** —— 不要再派「修」，改派「独立复核 + 反向验证」。")
    else:
        print("判据：无命中 —— 可按原样派「修」，但派前请把上面「最近改动」看一眼，防同类。")
    return 0


if __name__ == "__main__":
    raise SystemExit(主函数())
