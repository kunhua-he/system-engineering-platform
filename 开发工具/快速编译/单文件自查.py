"""单文件自查：改完一个文件，立刻确认它还能编译（并行期的第一道自检）。

**为什么必须有它（2026-09-18 实测教训，哲学 14.3「反复犯错的开发要补底层」）**：
并行维修期有 30+ 路同时改同一仓库。某一路拆分 `网关核心.py` 时把中间态（class 体被搬空、
语法错）留在磁盘上，导致：
- 另一路跑 `测试_冷启动反向门禁` → **11 个用例红**，全因 `import 网关核心` 失败；
- 父会话复跑同一条测试 → 误判「刚提交的改动把仓库跑红了」，白查一轮。

**根因不是谁不小心，是流程缺一轻量自检**：`py_compile` 一行命令，但没人把它固定成动作。
本工具就是那个动作——**改完立刻跑一次**，代价不到 1 秒。

用法：
    python3.14 开发工具/快速编译/单文件自查.py 运行核心/统一网关/网关核心.py
    python3.14 开发工具/快速编译/单文件自查.py --全仓 --只近期 30      # 扫全仓（只报近期改过的）
    python3.14 开发工具/快速编译/单文件自查.py --改过   # 只查 git 工作树里已改动的 .py

退出码：0 全部可编译；1 有不可编译文件（逐条打印错误位置与原因）。
"""

from __future__ import annotations

import argparse
import ast
import subprocess
import sys
import time
from pathlib import Path

from 公共契约.基础类型.逻辑类型 import 真, 假
from 公共契约.正式根 import 遍历源码
from 公共契约.运行时.平台适配 import 解析路径

# 边界项（批G L3 类2，**保留**）：本工具自己的仓根（`解析路径` 不覆盖「按本文件推
# 仓根」这一档，它只给 显式根/环境变量/cwd 三级兜底）；拼根本身已改调 `解析路径`。
系统根 = Path(__file__).resolve().parents[2]
git = "/Library/Developer/CommandLineTools/usr/bin/git"

#: 扫描/自查的排除名单已收口到唯一事实源 `公共契约/正式根.py::生成式目录表`
#: （此前本文件自持一份 frozenset，含 `归档`/`参考资料` 却漏 `.venv` 等，与另外 7 处互不相同）。


def 查一个(相对路径: str) -> tuple[bool, str]:
    """查单个文件能否编译；返回 (是否通过, 说明)。"""
    # 空值：唯一节点对空文本**原样返回**，故显式补 `.` —— 与改前 `系统根 / ""` 逐字等价。
    路径 = 解析路径(相对路径 or ".", 系统根)
    if not 路径.is_file():
        return 假, f"文件不存在: {相对路径}"
    try:
        ast.parse(路径.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError) as 错误:
        行号 = getattr(错误, "lineno", "?")
        文本 = getattr(错误, "text", "") or ""
        return 假, f"{相对路径}:{行号} {type(错误).__name__}: {错误.msg if hasattr(错误,'msg') else 错误}\n      {文本.strip()[:110]}"
    except OSError as 错误:
        return 假, f"{相对路径}: 读取失败 {错误}"
    return 真, f"{相对路径}: OK"


def _工作树改动的py() -> list[str]:
    """git 工作树里已改动/新增的 .py（排 __pycache__）。"""
    结果 = subprocess.run([git, "status", "--porcelain"], cwd=系统根, capture_output=True, text=True)
    表: list[str] = []
    for 行 in 结果.stdout.splitlines():
        状态, _, 路径 = 行[:2], 行[2:3], 行[3:].strip().strip('"')
        if not 路径.endswith(".py") or "__pycache__" in 路径:
            continue
        if 状态.strip().startswith("D"):
            continue  # 已删除的不查
        表.append(路径)
    return 表


def _全仓(只近期分钟: int) -> list[str]:
    表: list[str] = []
    现在 = time.time()
    # 进目录即剪枝（`正式根.遍历源码`）：此前 `系统根.rglob("*.py")` 会把 9.3G `工程缓存`
    # 全枚举一遍再按路径跳过（实测全仓 31 万条 / 167 秒，其中 97.5% 是生成式）。
    # 跳过名单唯一事实源＝`公共契约/正式根.py::生成式目录表`；本文件不再自持一份。
    for 路径 in 遍历源码(系统根):
        if 只近期分钟 and (现在 - 路径.stat().st_mtime) / 60 > 只近期分钟:
            continue
        表.append(str(路径.relative_to(系统根)))
    return 表


def 主函数(argv: list[str] | None = None) -> int:
    解析 = argparse.ArgumentParser(description="改完立刻自查：文件还能不能编译")
    解析.add_argument("文件", nargs="*", help="要查的仓库相对路径（可多个）")
    解析.add_argument("--改过", action="store_true", help="只查 git 工作树里改动的 .py")
    解析.add_argument("--全仓", action="store_true", help="扫全仓 .py")
    解析.add_argument("--只近期", type=int, default=0, metavar="分钟",
                      help="配合 --全仓：只查该时间内改过的（0=不限）")
    参 = 解析.parse_args(argv)

    if 参.改过:
        目标 = _工作树改动的py()
    elif 参.全仓:
        目标 = _全仓(参.只近期)
    else:
        目标 = 参.文件
    if not 目标:
        print("没有要查的文件（给路径，或用 --改过 / --全仓）")
        return 0

    坏: list[str] = []
    for 项 in 目标:
        通过, 说明 = 查一个(项)
        if not 通过:
            坏.append(说明)
    if 坏:
        print(f"❌ {len(坏)}/{len(目标)} 个文件不可编译（并行期请立刻修回可编译状态）:")
        for 说明 in 坏:
            print("  " + 说明)
        return 1
    print(f"✅ {len(目标)} 个文件全部可编译")
    return 0


if __name__ == "__main__":
    raise SystemExit(主函数())
