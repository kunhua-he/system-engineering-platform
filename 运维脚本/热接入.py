#!/usr/bin/env python3.14
"""一键热接入：让 40007 网关重新发现并增量装配「新增包 / 变更包」，不重启进程。

用法：
    python3.14 运维脚本/热接入.py            # 执行热接入并打印结果
    python3.14 运维脚本/热接入.py --查看      # 只看当前能力数与是否有待接入变更（不触发）

为什么用它：40007 是全机唯一执行网关，被 V3 后端、Agent 工具面等依赖。
直接重启会中断在途调用、打断句柄与租约。热接入只动变更包：
已装配包的运行态与句柄全部保留，实测单次约 0.2 秒。

依据：开发文档/决策记录/0008_能力更新走热接入不重启网关.md
"""
from __future__ import annotations

import sys
from pathlib import Path

# 环境准入（必须在任何装配与第三方导入之前）：平台判定的唯一来源是
# `公共契约/运行时/平台适配`，本文件不自己写 sys.platform 判断。
# 热接入依赖 LaunchAgent plist（macOS 专有）与 40007 网关，本机只支持 macOS arm64。
if str(Path(__file__).resolve().parents[1]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from 公共契约.运行时.平台适配 import 脚本入口准入

脚本入口准入("热接入（增量装配，不重启 40007 网关）")

import json
import time
import urllib.error
import urllib.request
from urllib.parse import quote

网关地址 = "http://127.0.0.1:40007"
# 凭证取用走唯一腿 `开发工具.薄壳.网关凭证`：回退顺序=("plist",) ——
# 现读现注入 launchd 里那份，不依赖调用方环境（本脚本的原有口径）。
from 开发工具.薄壳.网关凭证 import 凭证键 as 凭证变量名, 凭证缺失, 取网关凭证


def 读取凭证() -> str:
    """从 LaunchAgent 读取网关凭证（不打印明文）。"""
    try:
        凭证 = 取网关凭证(回退顺序=("plist",))
    except 凭证缺失 as 错误:
        raise SystemExit(str(错误)) from 错误
    if not 凭证:
        raise SystemExit(f"LaunchAgent 缺少环境变量 {凭证变量名}")
    return 凭证


def 调用(操作: str, 参数: dict | None = None, 超时秒: float = 180.0) -> dict:
    请求体 = {"操作": 操作}
    if 参数:
        请求体["参数"] = 参数
    return _发请求("/" + quote("网关/调用"), 请求体, 超时秒)


def 热接入(超时秒: float = 300.0) -> dict:
    """热接入走专用路径 POST /网关/热接入（空请求体），不是 /网关/调用 + 操作。

    网关对该路径固定注入 操作=热接入、参数={}，调用方不能伪造其他操作。
    """
    return _发请求("/" + quote("网关/热接入"), {}, 超时秒)


def _发请求(路径: str, 请求体: dict, 超时秒: float) -> dict:
    请求 = urllib.request.Request(
        网关地址 + 路径,
        data=json.dumps(请求体, ensure_ascii=False).encode("utf-8"),
        headers={
            "Content-Type": "application/json; charset=utf-8",
            "X-System-Credential": 读取凭证(),
        },
    )
    try:
        with urllib.request.urlopen(请求, timeout=超时秒) as 响应:
            return json.loads(响应.read().decode("utf-8"))
    except urllib.error.HTTPError as 错误:
        正文 = 错误.read().decode("utf-8", "replace")
        try:
            return json.loads(正文)
        except json.JSONDecodeError:
            raise SystemExit(f"网关返回 HTTP {错误.code}：{正文[:200]}")
    except urllib.error.URLError as 错误:
        raise SystemExit(f"连不上网关 {网关地址}：{错误.reason}")


def 当前能力数() -> int | str:
    健康 = 调用("健康检查", 超时秒=30)
    if not 健康.get("成功"):
        return f"未知（{健康.get('错误码') or '健康检查失败'}）"
    return (健康.get("值") or {}).get("能力数", "未知")


def 主(仅查看: bool) -> int:
    进程号 = _网关进程号()
    print(f"网关: {网关地址}   进程号: {进程号 or '未找到'}")
    print(f"当前能力数: {当前能力数()}")
    if 仅查看:
        print("（--查看 模式：未触发热接入）")
        return 0

    起点 = time.time()
    结果 = 热接入()
    耗时 = time.time() - 起点

    if not 结果.get("成功"):
        print(f"✗ 热接入失败（{耗时:.2f}s）：{结果.get('错误码')} {结果.get('错误说明')}")
        return 1

    值 = 结果.get("值") or {}
    新增, 变更, 卸载 = 值.get("新增包", 0), 值.get("变更包", 0), 值.get("卸载包", 0)
    print(f"✓ 热接入完成（{耗时:.2f}s）")
    print(f"  新增包 {新增} / 变更包 {变更} / 卸载包 {卸载} / 已注册能力数 {值.get('已注册能力数')}")
    for 名称, 列表键 in (("成功包", "成功包"), ("失败包", "失败包")):
        项目 = 值.get(列表键) or []
        if 项目:
            print(f"  {名称}:")
            for 项 in 项目:
                print(f"    · {项}")
    if 新增 == 0 and 变更 == 0 and 卸载 == 0:
        print("  （无待接入变更：代码与注册表一致）")
    print(f"  网关进程号: {_网关进程号() or '未找到'}   （热接入不重启进程）")
    return 0


def _网关进程号() -> str:
    import subprocess
    结果 = subprocess.run(
        ["bash", "-c", "pgrep -f '启动运行核心网关' | head -1"],
        capture_output=True, text=True,
    )
    return 结果.stdout.strip()


if __name__ == "__main__":
    raise SystemExit(主("--查看" in sys.argv))
