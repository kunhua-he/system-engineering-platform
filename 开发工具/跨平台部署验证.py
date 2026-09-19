#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""跨平台部署验证器：一键跑「换平台的正确顺序」并给出机器判定。

用途（换到 Windows / Linux 后第一条该跑的命令）：
    python3.14 -m 开发工具.跨平台部署验证

为什么需要它（设计哲学第 11 条：判定必须用数字；第 3.3 条：报错必须回填文档）：
    换平台不是「clone 下来就能跑」——本底座有三道**显式门禁**，按正确顺序拆掉才会通：

      第 1 道 依赖锁环境指纹（`强制校验` 规则 5）：锁里写死了 `Python/操作系统/CPU`，
              换平台不重建 → 装配被逐份拒绝（fail-closed，不是降级）。
              拆法：`重建依赖锁 --写入 --全部`（只刷 环境/生成时间，依赖集合原样保留）。
      第 2 道 平台准入（`平台适配.校验支持范围`）：只放行 macOS + arm64，
              五个入口一律退出码 1。**这是有意裁决**（不为未验收平台背书），
              不是缺陷；放开必须留真机证据。
      第 3 道 提供者环境（系统级环境依赖）：如 psycopg 需要系统 `libpq`，
              属「环境依赖必须本地具备」（第 2.2 条），不在锁里、pip 装不出来。

    本入口把这套顺序做成**一条命令 + 机器判定**，避免每次换机器都靠人记。

输出：中文分步报告 + 退出码。退出码 0 = 本平台已跑通到装配；非 0 = 卡在哪一步（见报告末）。
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

系统根 = Path(__file__).resolve().parents[1]
解释器 = sys.executable

#: 各步骤超时（秒）。换平台首跑要下载第三方闭包，给足余量；不是性能判据。
重建锁超时秒 = 900
自检超时秒 = 900


class 步骤结果:
    """一步的真实结果：名称 / 退出码 / 耗时 / 输出尾部。"""

    def __init__(self, 名称: str) -> None:
        self.名称 = 名称
        self.退出码 = -1
        self.耗时秒 = 0.0
        self.输出 = ""
        self.命令 = ""

    @property
    def 通过(self) -> bool:
        return self.退出码 == 0

    def 摘要行(self) -> str:
        if self.退出码 == -1:
            状态 = "未核验（命令没跑起来）"
        elif self.退出码 == 0:
            状态 = "通过"
        else:
            状态 = f"未通过（退出码 {self.退出码}）"
        return f"  {self.名称}：{状态}｜耗时 {self.耗时秒:.1f} 秒"


def _跑(名称: str, 命令: list[str], 超时秒: int) -> 步骤结果:
    """跑一条命令，中文环境变量注入 UTF-8（Windows 控制台默认 cp936 会炸中文）。"""
    结果 = 步骤结果(名称)
    结果.命令 = " ".join(命令)
    开始 = time.monotonic()
    环境 = {
        **os.environ,
        # 全中文输出在 Windows 默认码页下会 UnicodeEncodeError；统一 UTF-8 是
        # 跨平台的第一步（审计已登记：本仓 41 处 text=True 未显式 encoding）。
        "PYTHONUTF8": "1",
        "PYTHONIOENCODING": "utf-8",
        "PYTHONNOUSERSITE": "1",
    }
    环境.pop("PYTHONPATH", None)
    try:
        完成 = subprocess.run(
            命令, capture_output=True, text=True, timeout=超时秒,
            cwd=str(系统根), env=环境, encoding="utf-8", errors="replace",
        )
        结果.退出码 = 完成.returncode
        结果.输出 = ((完成.stdout or "") + (完成.stderr or "")).rstrip()
    except subprocess.TimeoutExpired:
        结果.输出 = f"超时（>{超时秒} 秒）"
    except Exception as 错误:
        结果.输出 = f"命令无法执行：{type(错误).__name__}: {错误}"
    结果.耗时秒 = time.monotonic() - 开始
    return 结果


def _尾部(文本: str, 行数: int = 12) -> str:
    行 = [行 for 行 in (文本 or "").splitlines() if 行.strip()]
    if not 行:
        return "（无输出）"
    return "\n".join("    " + 行 for 行 in 行[-行数:])


def _平台三元组() -> dict[str, str]:
    import platform

    return {
        "Python": sys.version.split()[0],
        "操作系统": platform.system(),
        "CPU": platform.machine(),
        "解释器": 解释器,
    }


def 跑验证(*, 只报: bool = False, json输出: bool = False) -> int:
    开始 = time.monotonic()
    步骤表: list[步骤结果] = []
    三元组 = _平台三元组()

    if not json输出:
        print("═══ 跨平台部署验证 ═══")
        print(f"  仓库根：{系统根}")
        print(f"  当前环境：{三元组['操作系统']} / {三元组['CPU']} / Python {三元组['Python']}")
        print(f"  解释器：{三元组['解释器']}")
        print()

    def _报(结果: 步骤结果, *, 落表: bool = True) -> None:
        if 落表:
            步骤表.append(结果)
        if not json输出:
            print(结果.摘要行())
            print(f"    输出尾部：\n{_尾部(结果.输出)}")
            print()

    # ── 步骤 1：环境自检（换平台时正需要跑的自检工具，按设计**不接**平台准入）──
    # 首跑必然因第 3 项（依赖锁指纹）与第 8 项（装配）而失败——这正是要看的现状。
    if not json输出:
        print("── 步骤 1／3　环境自检（看清本平台现状，容忍失败）──")
    自检初 = _跑("① 环境自检（重建前现状）", [解释器, "-m", "开发工具.环境自检"], 自检超时秒)
    if not json输出:
        print(自检初.摘要行())
        print(f"    输出尾部：\n{_尾部(自检初.输出, 26)}")
        print()

    # ── 步骤 2：按当前平台重建依赖锁（唯一正确拆法，不许手改锁 JSON）──
    if not json输出:
        print("── 步骤 2／3　重建依赖锁（只刷环境指纹，依赖集合原样保留）──")
    if 只报:
        重建 = _跑("② 重建依赖锁（干跑，不写盘）", [解释器, "-m", "开发工具.重建依赖锁", "--全部"], 重建锁超时秒)
    else:
        重建 = _跑("② 重建依赖锁（按当前环境写盘）",
               [解释器, "-m", "开发工具.重建依赖锁", "--写入", "--全部"], 重建锁超时秒)
    _报(重建)

    # ── 步骤 3：装配冒烟（本机到底能不能跑的**唯一判据**）──
    if not json输出:
        print("── 步骤 3／3　环境自检复跑（含装配冒烟三断言）──")
    自检终 = _跑("③ 环境自检（含装配冒烟，最终判定）", [解释器, "-m", "开发工具.环境自检"], 自检超时秒)
    _报(自检终)

    # ── 结论 ──
    结论 = {
        "环境": 三元组,
        "步骤": [
            {"名称": 步.名称, "退出码": 步.退出码, "耗时秒": round(步.耗时秒, 1),
             "输出尾部": 步.输出[-2000:]}
            for 步 in 步骤表
        ],
        "总耗时秒": round(time.monotonic() - 开始, 1),
    }

    if json输出:
        print(json.dumps(结论, ensure_ascii=False, indent=1))
    else:
        print("═══ 结论 ═══")
        print(自检初.摘要行() + "　←　重建前现状（首跑必然暴露差异）")
        print(重建.摘要行())
        print(自检终.摘要行() + "　←　重建后判定（本命令的唯一判据）")
        print()

    if 自检终.通过:
        结论["判定"] = "本平台已跑通到装配"
        if not json输出:
            print("本平台已跑通：依赖锁与当前环境一致，装配冒烟通过（能力数 > 0、无跳过包）。")
            print("下一步：起常驻网关（README《部署》第 4 步），再按《当前支持矩阵》补真机证据。")
        else:
            print(json.dumps(结论, ensure_ascii=False, indent=1))
        return 0

    # 失败要**说清卡在哪一步**，不是丢一个退出码（第 3.1 条：把结论写成结论）。
    缺失清单: list[str] = []
    if "依赖锁" in 自检终.输出 and "不一致" in 自检终.输出:
        缺失清单.append("依赖锁仍与当前环境不一致——检查重建是否真的写盘（--写入 --全部）")
    if "不在支持范围内" in 自检终.输出:
        缺失清单.append("平台准入不放行（有意裁决，不是缺陷）——放开必须先留真机证据")
    if "被跳过" in 自检终.输出:
        缺失清单.append(
            "有包被装配跳过（单包级告警）：读上方「已跳过」点名的那一行，"
            "按其自述原因处置——常见两类：① 提供者环境起不来（系统库缺失，"
            "如 psycopg 需要 libpq；或在当前平台结构性不可用，如 mlx 是 Apple Silicon 专有）；"
            "② 第三方包未装上（pip 源不可达 / 代理未配置）"
        )
    if "提供者环境" in 自检终.输出 or "提供者不可用" in 自检终.输出:
        缺失清单.append(
            "提供者环境起不来：属「环境依赖必须本地具备」（第 2.2 条）。"
            "常见两类——① 系统库缺失（如 psycopg 需要 libpq）；"
            "② 该提供者在当前平台结构性不可用（如 mlx 是 Apple Silicon 专有）"
        )
    if "No space left on device" in 自检终.输出 or "ENOSPC" in 自检终.输出:
        缺失清单.append(
            "磁盘/临时目录空间不足：构建期第三方闭包可能有数百 MB，"
            "若 /tmp 是小容量内存盘，先 `export TMPDIR=<大盘目录>` 再重跑"
        )
    if not 缺失清单:
        缺失清单.append("见上方步骤 3 输出尾部定位")

    结论["判定"] = "本平台尚未跑通"
    结论["卡点"] = 缺失清单
    if not json输出:
        print("本平台尚未跑通，卡点如下（逐条对应设计哲学条款）：")
        for 序号, 条目 in enumerate(缺失清单, start=1):
            print(f"  {序号}. {条目}")
        print()
        print(f"完整结论：{'─' * 0}")
        print(json.dumps({"判定": 结论["判定"], "卡点": 缺失清单}, ensure_ascii=False, indent=1))
    else:
        print(json.dumps(结论, ensure_ascii=False, indent=1))
    return 1


def 全量验收放行(目标: str) -> tuple[bool, str]:
    """全量验收授权判定：默认拒绝，须经华哥授权后放行（哲学 11.2，2026-09-19 华哥裁决）。

    唯一授权腿 ＝ `系统核心支持库.权限审批`（规则表「全量验收」默认 `询问`＝不放行）。
    **本函数是跨平台部署验证的入口闸门**；发布门禁用的是同一腿的自己的那份薄壳，
    两边都只读「权限审批.校验动作」，不各自造令牌后门（哲学 1.3 结果唯一即收口）。
    """
    try:
        from 支持库.后端.系统核心支持库.权限审批 import 校验动作
    except ImportError as 错误:  # fail-closed
        return False, (f"全量验收被拒绝：取不到授权判定腿（{错误}）。按哲学 11.2，默认不跑全量。")
    判定 = 校验动作("全量验收", 目标)
    if not 判定.成功:
        return False, f"全量验收被拒绝：授权判定失败（{判定.错误码}：{判定.错误说明}）。按哲学 11.2，默认不跑全量。"
    值 = 判定.值 if isinstance(判定.值, dict) else {}
    if 值.get("通过") is True:
        return True, f"全量验收已授权（策略={值.get('策略')}）：开始 {目标}。"
    return False, (
        f"全量验收被拒绝（策略={值.get('策略')}：{值.get('原因')}）。\n"
        "按哲学 11.2（2026-09-19 华哥裁决）：全量只在大版本发布或走审计流程时跑，\n"
        "默认无授权禁止跑全量 —— 要跑需华哥明确授权。\n"
        "日常开发请走静态编译：python3.14 -m 开发工具.开发编译口.编译口 --变更"
    )


def 主函数() -> int:
    解析 = argparse.ArgumentParser(
        prog="python3.14 -m 开发工具.跨平台部署验证",
        description="跨平台部署验证：环境自检 → 重建依赖锁 → 装配冒烟，一条命令给机器判定。",
    )
    解析.add_argument("--只报", action="store_true", help="只干跑重建（不写盘），用于先看差异")
    解析.add_argument("--json", action="store_true", help="以 JSON 输出（便于机器/CICD 判读）")
    参数 = 解析.parse_args()
    放行, 闸门说明 = 全量验收放行("跨平台部署验证")
    if not 放行:
        print(闸门说明)
        return 1
    return 跑验证(只报=参数.只报, json输出=参数.json)


if __name__ == "__main__":
    raise SystemExit(主函数())
