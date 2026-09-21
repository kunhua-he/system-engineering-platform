"""运行依赖生命周期审计：依赖与生命周期审计命令行入口（发布门禁候选，只读）。

用法：
    python3.14 开发工具/依赖生命周期审计/运行依赖生命周期审计.py
    python3.14 开发工具/依赖生命周期审计/运行依赖生命周期审计.py --系统根 <平台根>
    python3.14 -m 开发工具.依赖生命周期审计.运行依赖生命周期审计

退出码：0 无违规；1 存在违规（打印违规清单）。
审计每个第三方支持库提供者的依赖锁/包声明/完整性摘要/健康探针/停止释放证据，
不修改被审计文件。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

本文件目录 = Path(__file__).resolve().parent
默认系统根 = 本文件目录.parents[1]  # 开发工具/依赖生命周期审计 → 平台根
# 直接以脚本方式运行时 sys.path[0] 为脚本目录，需把平台根插入顶层才能 import 中文包
if str(默认系统根) not in sys.path:
    sys.path.insert(0, str(默认系统根))

from 开发工具.依赖生命周期审计.审计核心 import 审计全部, 扫描根级平铺内部件

违规类别模板 = ("混装", "缺依赖锁", "缺完整性摘要", "缺健康探针", "缺停止入口", "释放策略不符", "摘要漂移")


def 汇总违规(结果列表) -> dict[str, int]:
    """按违规类别统计条数，供报告与门禁输出。"""
    统计 = {类别: 0 for 类别 in 违规类别模板}
    for 结果 in 结果列表:
        for 违规 in 结果.违规列表:
            for 类别 in 违规类别模板:
                if 违规.startswith(类别):
                    统计[类别] += 1
                    break
    return 统计


def 主入口(系统根: Path | None = None) -> int:
    """执行审计并打印报告；返回退出码（0 无违规 / 1 有违规）。"""
    系统根 = 系统根 or 默认系统根
    结果列表, 跳过列表 = 审计全部(系统根)
    平铺件说明 = 扫描根级平铺内部件(系统根)
    违规提供者数 = sum(1 for 结果 in 结果列表 if not 结果.是否通过)
    违规总数 = sum(len(结果.违规列表) for 结果 in 结果列表)
    print(f"依赖与生命周期审计（只读）")
    print(f"系统根: {系统根}")
    print(f"标准提供者 {len(结果列表)} 个（跳过 {len(跳过列表)} 个非标准目录）")
    for 说明 in 跳过列表:
        print(f"  跳过: {说明}")
    # #96（2026-09-21）：根级平铺 .py 内部件此前在审计输出里**完全不可见** ——
    # 它们无目录 ⇒ 依赖锁无落点，`*提供者` glob 也扫不到。本段只做可见性上报，
    # 判定口径仍在 `生成依赖分两段.py --校验` 一处。
    print(f"根级平铺内部件 {len(平铺件说明)} 个（无目录 ⇒ 依赖锁无落点；"
          f"判据在 开发工具/依赖派生/生成依赖分两段.py --校验）")
    for 说明 in 平铺件说明:
        print(f"  平铺件: {说明}")
    if 违规总数:
        print(f"违规清单（{违规提供者数} 个提供者，{违规总数} 条）：")
        for 结果 in 结果列表:
            if not 结果.是否通过:
                print(f"[{结果.提供者名}]")
                for 违规 in 结果.违规列表:
                    print(f"    - {违规}")
    else:
        print("全部通过：无违规")
    统计 = 汇总违规(结果列表)
    print("类别统计：" + "、".join(f"{类别} {数量}" for 类别, 数量 in 统计.items() if 数量))
    return 0 if 违规总数 == 0 else 1


if __name__ == "__main__":
    参数解析 = argparse.ArgumentParser(description="依赖与生命周期审计（只读）")
    参数解析.add_argument("--系统根", type=Path, default=None, help="平台根目录（默认自动推导）")
    参数 = 参数解析.parse_args()
    sys.exit(主入口(参数.系统根))
