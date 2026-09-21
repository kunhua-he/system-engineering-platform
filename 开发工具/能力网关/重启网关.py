#!/usr/bin/env python3.14
"""重启 40007 唯一网关：触发即返回 + 就绪轮询 + 结构化结论（**一次调用拿到结论**）。

为什么要有这个落点（2026-09-21，开工-20260921-064256-6fc0）：
`决策记录 0008` 要求「改完能力走热接入、不重启」。但实测（未完成事项 #195）
**热接入并不重载已导入模块**：它报「成功包」之后旧代码仍在跑，二次调用就报
「无待接入变更」，变更记录被消费、重试也刷不出来 —— 此时**只有重启能生效**。
而此前「重启」这条腿**没有任何落点**：Agent 只能回终端手写 `launchctl kickstart`
+ `curl` 轮询循环（本会话实测连写 3 次，每次都要猜轮询次数与退避），正是
「每次调一次终端，都可以理解成是能力的缺失」。本脚本把「重启 + 等就绪」收成一条命令。

★ 为什么默认要**脱离进程组**跑（2026-09-21 实测踩到）：
本脚本经 MCP `执行命令` 调用时，它自己的父进程链是 网关 → 执行命令提供者 → 本脚本，
而平台收尾是**按进程组**整组回收的。同步重启会把网关连同本脚本一起杀掉，
调用方只能拿到 `网关不可达`（实测就是如此，重启成功了但拿不到结论）。
故默认路径 `start_new_session=True` 起一个脱离进程组的子进程去 kickstart + 轮询，
结果写 `工程缓存/网关重启结果.json`，父进程立即返回。
这**不是绕过资源回收**：子进程有界（最多等 `--超时` 秒即退），结果落盘可查。

用法（经 MCP `系统核心支持库.进程管理.执行命令` 调用，不必手写循环）：
    python3.14 开发工具/能力网关/重启网关.py            # 触发重启，立即返回（结果写文件）
    python3.14 开发工具/能力网关/重启网关.py --探活      # 只探活，同步返回（不重启）
    python3.14 开发工具/能力网关/重启网关.py --看结果    # 读上次重启的结论
    python3.14 开发工具/能力网关/重启网关.py --前台      # 同步重启并等就绪（终端直跑用）
    …均可加 `--超时 60`（就绪等待上限秒，默认 45）

凭证从 40007 的 launchd plist 现读现注入，**不打印、不落盘**（与薄壳同一口径）。

**安全警示（决策记录 0008 原话）**：重启会中断在途调用、打断句柄与租约，
并牵连依赖 40007 的其他进程。故只在「热接入确实没生效」或「网关无响应」时用，
**不要**当成改完能力的默认动作；能用热接入就先用热接入。
"""

from __future__ import annotations

import json
import os
import plistlib
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import quote

网关地址 = "http://127.0.0.1:40007"
服务标签 = "com.huashi.gateway-40007"
plist路径 = Path.home() / "Library" / "LaunchAgents" / f"{服务标签}.plist"
凭证变量名 = "系统库网关凭证"
默认就绪超时秒 = 45.0
#: 后台重启路径下，子进程动手前先等一拍（让父进程先把「已触发」送回去，见 重启() 注释）。
后台重启前延迟秒 = 0.8
结果文件 = Path(__file__).resolve().parents[2] / "工程缓存" / "网关重启结果.json"


def 读取凭证() -> str:
    if not plist路径.is_file():
        raise SystemExit(f"找不到 LaunchAgent：{plist路径}")
    配置 = plistlib.loads(plist路径.read_bytes())
    return str((配置.get("EnvironmentVariables") or {}).get(凭证变量名) or "")


def _发(路径: str, 请求体: dict | None, 凭证: str, 超时秒: float = 20.0) -> tuple[int, dict]:
    """向网关发一次请求；返回 (HTTP状态码, 信封)。连不上时状态码为 0。"""
    数据 = None if 请求体 is None else json.dumps(请求体, ensure_ascii=False).encode("utf-8")
    # 请求行只能是 ASCII：中文路径必须百分号编码（实测漏了这步直接
    # `UnicodeEncodeError: 'ascii' codec can't encode`，与薄壳同一条坑）
    请求 = urllib.request.Request(
        网关地址 + "/" + quote(路径.lstrip("/")),
        data=数据,
        method="POST" if 数据 is not None else "GET",
        headers={"Content-Type": "application/json; charset=utf-8",
                 "Authorization": f"Bearer {凭证}"},
    )
    try:
        with urllib.request.urlopen(请求, timeout=超时秒) as 响应:
            return int(响应.status), json.loads(响应.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as 错误:
        # 401/403 也说明进程活着；带体的错误仍按信封解析
        try:
            return int(错误.code), json.loads(错误.read().decode("utf-8", "replace"))
        except (json.JSONDecodeError, ValueError):
            return int(错误.code), {}
    except (urllib.error.URLError, OSError, TimeoutError):
        return 0, {}


def 进程号() -> int | None:
    """取网关进程号：直接问 launchd，不靠 pgrep 猜命令行。"""
    完成 = subprocess.run(
        ["launchctl", "print", f"gui/{os.getuid()}/{服务标签}"],
        capture_output=True, text=True, timeout=30)
    for 行 in (完成.stdout or "").splitlines():
        行 = 行.strip()
        if 行.startswith("pid = "):
            try:
                return int(行.split("=", 1)[1].strip())
            except ValueError:
                return None
    return None


def 就绪等待(凭证: str, 上限秒: float) -> tuple[bool, int, float]:
    """轮询到「进程真的在听」为止。返回 (是否就绪, 轮次, 耗时秒)。"""
    起点 = time.time()
    轮次 = 0
    while time.time() - 起点 < 上限秒:
        轮次 += 1
        码, _ = _发("/健康", None, 凭证, 超时秒=3.0)
        if 码 in (200, 401, 403):
            return True, 轮次, time.time() - 起点
        time.sleep(0.5)
    return False, 轮次, time.time() - 起点


def _取值(argv: list[str], 开关: str) -> str:
    位 = argv.index(开关) if 开关 in argv else -1
    return argv[位 + 1] if 0 <= 位 < len(argv) - 1 else ""


def _超时秒(argv: list[str]) -> float:
    原文 = _取值(argv, "--超时")
    if not 原文:
        return 默认就绪超时秒
    try:
        return float(原文)
    except ValueError:
        raise SystemExit("--超时 必须是数字")


def _落结果(结果: dict) -> None:
    """结果落盘：重启会把调用方一起带走，故结论只能经文件交付。"""
    结果["完成时间"] = time.strftime("%Y-%m-%d %H:%M:%S")
    try:
        结果文件.parent.mkdir(parents=True, exist_ok=True)
        结果文件.write_text(json.dumps(结果, ensure_ascii=False, indent=1), encoding="utf-8")
    except OSError as 错误:
        结果["结果落盘失败"] = str(错误)
    print(json.dumps(结果, ensure_ascii=False))


def 探活(凭证: str) -> int:
    码, 信封 = _发("/网关/调用", {"操作": "健康检查", "能力id": "", "参数": {}}, 凭证)
    结果 = {"模式": "探活", "服务标签": 服务标签, "进程号": 进程号(),
            "健康检查HTTP状态码": 码, "网关活着": 码 in (200, 401, 403)}
    结果["能力数"] = ((信封.get("值") or {}) if isinstance(信封, dict) else {}).get("能力数")
    结果["成功"] = bool(结果["网关活着"])
    if not 结果["成功"]:
        结果["错误说明"] = "网关未响应（看 /tmp/网关40007.err）"
    _落结果(结果)
    return 0 if 结果["成功"] else 1


def 重启(凭证: str, 超时秒: float) -> int:
    # 后台触发时，父进程要把「已触发」的返回值送回去（经 执行命令 提供者 → 网关），
    # 而子进程一开始 kickstart 就会把这条链路掉。先等一拍，让父进程先答话再动手。
    time.sleep(后台重启前延迟秒)
    前进程 = 进程号()
    完成 = subprocess.run(
        ["launchctl", "kickstart", "-k", f"gui/{os.getuid()}/{服务标签}"],
        capture_output=True, text=True, timeout=60)
    结果: dict = {"模式": "重启", "服务标签": 服务标签, "重启前进程号": 前进程,
                  "kickstart退出码": 完成.returncode}
    if 完成.returncode != 0:
        结果["成功"] = False
        结果["错误说明"] = (完成.stderr or 完成.stdout or "").strip()[:300]
        _落结果(结果)
        return 1
    就绪, 轮次, 耗时 = 就绪等待(凭证, 超时秒)
    结果.update({"就绪": 就绪, "就绪轮次": 轮次, "就绪耗时秒": round(耗时, 2),
                 "重启后进程号": 进程号()})
    if not 就绪:
        结果["成功"] = False
        结果["错误说明"] = f"等待 {超时秒} 秒仍未就绪（看 /tmp/网关40007.err）"
        _落结果(结果)
        return 1
    码, 信封 = _发("/网关/调用", {"操作": "健康检查", "能力id": "", "参数": {}}, 凭证)
    结果["健康检查HTTP状态码"] = 码
    结果["能力数"] = ((信封.get("值") or {}) if isinstance(信封, dict) else {}).get("能力数")
    结果["成功"] = bool(结果["能力数"])
    if not 结果["成功"]:
        结果["错误说明"] = "网关在听但 健康检查 未回能力数，需人工看一眼"
    _落结果(结果)
    return 0 if 结果["成功"] else 1


def 触发后台重启(argv: list[str]) -> int:
    """脱离进程组起子进程做重启 + 轮询，父进程立即返回（见模块 docstring 的 ★ 段）。"""
    if 结果文件.exists():
        结果文件.unlink()
    子参数 = [sys.executable, str(Path(__file__).resolve()), "--前台"]
    if _取值(argv, "--超时"):
        子参数 += ["--超时", _取值(argv, "--超时")]
    with open(os.devnull, "wb") as 空:
        subprocess.Popen(子参数, stdout=空, stderr=空, stdin=空,
                         start_new_session=True, cwd=str(结果文件.parents[1]))
    print(json.dumps({
        "模式": "触发后台重启", "服务标签": 服务标签, "重启前进程号": 进程号(),
        "成功": True, "已触发": True, "结果文件": str(结果文件),
        "提示": "重启会掐断本次调用所在进程组，故结论写文件；"
                "等 1~3 秒再跑 `--看结果` 或 `--探活` 取结论",
    }, ensure_ascii=False))
    return 0


def 看结果() -> int:
    if not 结果文件.is_file():
        print(json.dumps({"成功": False, "错误说明": f"还没有结果文件：{结果文件}"}, ensure_ascii=False))
        return 1
    print(结果文件.read_text(encoding="utf-8"))
    return 0


if __name__ == "__main__":
    参 = sys.argv[1:]
    if "--看结果" in 参:
        raise SystemExit(看结果())
    凭 = 读取凭证()
    if not 凭:
        print(json.dumps({"成功": False, "错误说明": f"plist 里取不到 {凭证变量名}"}, ensure_ascii=False))
        raise SystemExit(2)
    if "--探活" in 参:
        raise SystemExit(探活(凭))
    if "--前台" in 参:
        raise SystemExit(重启(凭, _超时秒(参)))
    raise SystemExit(触发后台重启(参))
