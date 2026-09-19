"""提供者环境旧版本回收：只留「现用摘要」，其余哈希目录都是旧版本。

## 为什么需要它（2026-09-18 实测，华哥明确「能加速而且不影响的直接就做」）

实测：`工程缓存/提供者运行环境` 占到 **7.6GB**，其中大量是**同一提供者的多个历史环境**——
实测 20 个提供者留了 2–5 个哈希版本，而**每个提供者只有 1 个现用**（其余全是依赖锁变化
后留下的旧环境）。清掉后 `工程缓存` 由 9.8GB → 5.0GB，全仓 `grep -r` 由 15.62 秒 → 9.35 秒。

## 判据（用平台自己的算法，不另立一套）

`运行核心/运行环境管理器/环境管理器.计算环境摘要(依赖锁, 提供者id)` 就是环境的唯一命名依据：

    环境目录 = 提供者运行环境/<提供者id>/<环境摘要>/

所以本脚本**当场调它**算出现用摘要，凡不等于该摘要的同级目录即旧版本，可删。
缺环境时平台会自动重建（`确保环境`），因此删旧版本**不影响任何在跑的东西**。

## 边界（保守优先，宁可少删）

- **只删**「现用摘要确实在磁盘上」的提供者的旧版本；算不出/找不到对应提供者的**一律跳过并打印**。
  （若现用摘要不在磁盘，说明该提供者环境尚未生成，此时所有既有版本来源不明，不动。）
- `缓存证据.jsonl` 等文件一律不碰；只处理目录层。
- 默认**只报不删**，必须显式 `--执行`。

## 用法

    python3.14 开发工具/提供者环境回收.py --试运行    # 只打印清单（缺省行为）
    python3.14 开发工具/提供者环境回收.py --执行      # 真删旧版本
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

系统根 = Path(__file__).resolve().parents[1]
if str(系统根) not in sys.path:
    sys.path.insert(0, str(系统根))

from 运行核心.运行环境管理器.环境管理器 import 计算环境摘要, 读取依赖锁  # noqa: E402
from 公共契约.运行时.平台适配 import 清只读后删除树  # noqa: E402
from 公共契约.基础类型.逻辑类型 import 真  # noqa: E402

环境根相对 = Path("工程缓存") / "提供者运行环境"


def 目录大小兆(路径: Path) -> float:
    """目录占用（MB）。"""
    总 = 0
    for 子 in 路径.rglob("*"):
        try:
            if 子.is_file() and not 子.is_symlink():
                总 += 子.stat().st_size
        except OSError:
            continue
    return 总 / 1024 / 1024


def 找提供者目录(提供者id: str) -> Path | None:
    """在全仓找同名提供者目录（判据：它自己带 `依赖锁.json`）。找不到即返回 None。"""
    for 命中 in 系统根.rglob(提供者id):
        if 命中.is_dir() and (命中 / "依赖锁.json").is_file():
            return 命中
    return None


def 回收(执行: bool) -> int:
    环境根 = 系统根 / 环境根相对
    if not 环境根.is_dir():
        print(f"无此目录：{环境根}")
        return 0
    可释放 = 0.0
    删表: list[tuple[str, str, float]] = []
    留表: list[tuple[str, str]] = []
    跳过: list[str] = []

    for 提供者目录 in sorted(环境根.iterdir()):
        if not 提供者目录.is_dir():
            continue
        版本表 = sorted(x for x in 提供者目录.iterdir() if x.is_dir())
        if not 版本表:
            continue
        真身 = 找提供者目录(提供者目录.name)
        if 真身 is None:
            跳过.append(f"{提供者目录.name}（仓库里找不到带 依赖锁.json 的同名提供者）")
            continue
        现用 = 计算环境摘要(读取依赖锁(真身), 提供者目录.name)
        if not any(版本.name == 现用 for 版本 in 版本表):
            跳过.append(f"{提供者目录.name}（现用摘要 {现用} 不在磁盘：环境尚未生成，"
                      f"{len(版本表)} 个版本来源不明，全部保留）")
            continue
        留表.append((提供者目录.name, 现用))
        for 版本 in 版本表:
            if 版本.name == 现用:
                continue
            大小 = 目录大小兆(版本)
            删表.append((f"{提供者目录.name}/{版本.name}", 现用, 大小))
            可释放 += 大小
            if 执行:
                 # 唯一实现：清只读/补父目录写位后再删（旧环境版本目录可为只读）
                清只读后删除树(版本, 忽略失败=真)

    print(f"现用版本（保留）{len(留表)} 个：")
    for 名, 摘要 in 留表:
        print(f"  保留  {名}/{摘要}")
    print(f"\n旧版本（{'已删' if 执行 else '待删'}）{len(删表)} 个：")
    for 名, 现用, 大小 in sorted(删表, key=lambda x: -x[2]):
        print(f"  {'删  ' if 执行 else '待删'}  {名}（现用 {现用}）  {大小:.1f} MB")
    if 跳过:
        print(f"\n保守跳过 {len(跳过)} 个（来源不明，宁可少删）：")
        for 项 in 跳过:
            print(f"  跳过  {项}")
    print(f"\n{'已释放' if 执行 else '可释放'} {可释放:.1f} MB（{可释放 / 1024:.2f} GB）")
    if not 执行:
        print("【只报不删】加 --执行 才真删。")
        # **退出码口径（2026-09-20 补，待办 #65）**：原实现无论扫出什么都没做都 `return 0`
        # ⇒ 调用方永远读不到「这轮到底干了什么」。口径：
        #   0 = 扫干净且旧版本已清；1 = 有「来源不明、保守跳过」的目录（真发现问题）；
        #   2 = 未做任何动作（只报不删）—— 「没做」不是「做好了」。
        return 2
    if 跳过:
        return 1
    return 0


def 主函数(argv: list[str] | None = None) -> int:
    解析 = argparse.ArgumentParser(description="提供者环境回收：只留现用摘要，清旧版本")
    解析.add_argument("--执行", action="store_true", help="真删（缺省只报不删）")
    解析.add_argument("--试运行", action="store_true", help="显式只报不删（与缺省同义）")
    参 = 解析.parse_args(argv)
    return 回收(执行=bool(参.执行))


if __name__ == "__main__":
    raise SystemExit(主函数())
