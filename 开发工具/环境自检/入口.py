"""命令行入口：人读输出 / JSON 输出 / 退出码口径。

退出码：0 没有任何【不支持】项（可以有【警告】项）；1 存在【不支持】项；2 自检自身
无法开始（定不到仓库根）。本模块只做输出与退出码归并，不含判据。"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import sys
import time
from collections import Counter
from pathlib import Path

import platform as 平台模块

from 公共契约.运行时 import 平台适配

from 开发工具.环境自检.基础 import (
    结论_不支持, 结论_通过, 结论_警告, 进度前缀, 自检项, _准备导入路径)
from 开发工具.环境自检.编排 import _行宽, 跑全部自检


def 打印文本(项表: list[自检项], 根: Path, 详细: bool) -> None:
    统计 = Counter(项.结论 for 项 in 项表)
    print(f"{进度前缀} 仓库根 {根}")
    print(f"{进度前缀} 解释器 {sys.executable}（Python "
          f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}）"
          f"｜时间 {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{进度前缀} 共 {len(项表)} 项：通过 {统计[结论_通过]}｜警告 {统计[结论_警告]}"
          f"｜不支持 {统计[结论_不支持]}")
    print()
    for 项 in 项表:
        print(f"  {_行宽(项.序号, 6)}{_行宽(项.名称, 32)}{_行宽('【' + 项.结论 + '】', 10)}"
              f"{项.说明}")
        if 详细 or 项.结论 != 结论_通过:
            if 项.为什么:
                print(f"        ↳ 为什么：{项.为什么}")
            if 项.影响:
                print(f"        ↳ 影响：{项.影响}")
    print()
    不支持项 = [项 for 项 in 项表 if 项.结论 == 结论_不支持]
    警告项 = [项 for 项 in 项表 if 项.结论 == 结论_警告]
    if 警告项:
        print(f"{进度前缀} 警告（不阻断）：")
        for 项 in 警告项:
            print(f"  - {项.序号} {项.名称}：{项.说明}")
    if 不支持项:
        print(f"{进度前缀} 不支持项（必须解决，否则跑不起来／跑不全）：")
        for 项 in 不支持项:
            print(f"  - {项.序号} {项.名称}：{项.说明}")
            if 项.影响:
                print(f"      影响：{项.影响}")
        print()
        print(f"{进度前缀} 结论：本机还缺 {len(不支持项)} 项能力，见上（每项都写了影响范围）。")
        print(f"{进度前缀} 退出码 1")
        return
    print(f"{进度前缀} 结论：没有【不支持】项，本机可以跑。"
          f"（警告 {len(警告项)} 项只影响对应能力，不是缺陷）")
    print(f"{进度前缀} 退出码 0")


def 主(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python3.14 -m 开发工具.环境自检",
        description="环境自检：一跑就知道本机能不能跑、缺什么（有不支持项即非零退出）")
    parser.add_argument("--json", action="store_true", help="以 JSON 输出（便于机器判读）")
    parser.add_argument("--详细", action="store_true",
                        help="连【通过】项也打印『为什么需要它』与详情")
    参数 = parser.parse_args(argv)

    try:
        根 = _准备导入路径()
    except Exception as 错误:  # noqa: BLE001
        print(f"{进度前缀} 无法开始：{type(错误).__name__}: {错误}", file=sys.stderr)
        return 2

    被抑制输出 = ""
    if 参数.json:
        # 装配/忽略记录可能往 stdout 打日志；JSON 模式必须保证 stdout 只有一份合法 JSON
        缓冲 = io.StringIO()
        with contextlib.redirect_stdout(缓冲):
            项表 = 跑全部自检()
        被抑制输出 = 缓冲.getvalue()[:4000]
    else:
        项表 = 跑全部自检()

    统计 = Counter(项.结论 for 项 in 项表)
    退出码 = 1 if 统计[结论_不支持] else 0
    if 参数.json:
        载荷 = {
            "仓库根": str(根),
            "解释器": {"路径": sys.executable, "版本": 平台模块.python_version()},
            "平台": {"sys.platform": 平台适配.原始平台标志(),
                   "系统": 平台适配.本机系统名(),
                   "架构": 平台适配.当前架构()},
            "结论统计": {"通过": 统计[结论_通过], "警告": 统计[结论_警告],
                     "不支持": 统计[结论_不支持]},
            "有不支持项": 退出码 != 0,
            "退出码": 退出码,
            "自检项": [项.转字典() for 项 in 项表],
        }
        if 被抑制输出:
            载荷["被抑制输出"] = 被抑制输出
        print(json.dumps(载荷, ensure_ascii=False, indent=2))
    else:
        打印文本(项表, 根, 详细=bool(参数.详细))
    return 退出码
