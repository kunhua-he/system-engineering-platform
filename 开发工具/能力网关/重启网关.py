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
    python3.14 开发工具/能力网关/重启网关.py --运行态同根  # 只判「运行态与构建链同根」（不重启、不落盘）
    python3.14 开发工具/能力网关/重启网关.py --看结果    # 读上次重启的结论
    python3.14 开发工具/能力网关/重启网关.py --前台      # 同步重启并等就绪（终端直跑用）
    python3.14 开发工具/能力网关/重启网关.py --重载配置后台  # 改了 plist 后必须用它（kickstart 不重读 plist）
    python3.14 开发工具/能力网关/重启网关.py --重载配置    # 同上，同步形态（终端直跑用）
    …均可加 `--超时 60`（就绪等待上限秒，默认 45）

**探活与重启都判「运行态同根」（债务 #219，2026-09-21）**：网关活着、能力数对、装配告警空
**都不代表**它的运行态与构建链同根 —— 实测出现过「健康 200／能力数 746／告警空」全绿、
而 `制品仓库`／`运行数据` 被解析到 `~/Library/Caches/…` 的静默分叉。故 `成功` 的定义是
**「活着 ∧ 同根」**，判据见 `判定同根`（两问：现在同根 + 下次重启还同根）。

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

from 公共契约.基础类型.逻辑类型 import 真, 假
from 公共契约.运行时 import 平台适配

网关地址 = "http://127.0.0.1:40007"
服务标签 = "com.huashi.gateway-40007"
plist路径 = Path.home() / "Library" / "LaunchAgents" / f"{服务标签}.plist"
凭证变量名 = "系统库网关凭证"
默认就绪超时秒 = 45.0
#: `重载配置` 的 `bootout → bootstrap` 重试（见 `重载配置` 内的 ★ 段：实测首次必 EIO）。
重载重试次数 = 3
重载重试间隔秒 = 2.0
#: 后台重启路径下，子进程动手前先等一拍（让父进程先把「已触发」送回去，见 重启() 注释）。
后台重启前延迟秒 = 0.8
结果文件 = Path(__file__).resolve().parents[2] / "工程缓存" / "网关重启结果.json"

#: 运行缓存根的环境变量名。**与 `公共契约/运行时/运行缓存.运行缓存环境变量` 同源同字面量** ——
#: 本脚本是**独立进程**（不 import 平台模块，见模块 docstring 的「脱离进程组」一节），
#: 故只留一个同名字面量并在此注明来源；改口径时两处必须同批改。
运行缓存变量名 = "系统底座_工程缓存根"
#: 经网关读「它自己解析出的制品根目录」的能力 —— 判据拿真值，不靠 ps/argv 猜运行模式。
制品布局能力 = "平台控制面.包仓库.查询制品布局"
#: 未完成事项 #219 处置栏点名的口径：稳定路径校验必须 `有效=true` 且激活路径落在构建链那棵树里。
稳定路径能力 = "平台控制面.包仓库.校验平台客户端稳定路径"


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
            return 真, 轮次, time.time() - 起点
        time.sleep(0.5)
    return 假, 轮次, time.time() - 起点


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


网关错误日志 = Path("/tmp/网关40007.err")


def 装配告警(最多条: int = 10) -> dict:
    """读网关启动日志里的装配告警：哪些包被跳过、为什么。

    为什么要有它（2026-09-21 实测踩到）：改能力时 `__init__.py` 参数名序与契约不一致，
    装配器 fail-closed 拒**整包**（`平台控制面.能力目录` 14 个能力一起消失），
    而 MCP 侧只看到「能力未注册」——真原因只在 `/tmp/网关40007.err` 的 `[装配告警]` 里。
    没有这个读数，能力凭空消失就只能靠人回终端 tail 日志发现（「调终端 = 能力缺失」的典型）。

    口径：只看日志**末尾 80 行**（日志会累积多次启动），故它代表「最近一次启动」的装配情况；
    刚跑完重启再调本项，结论就是本次装配。
    """
    if not 网关错误日志.is_file():
        return {"告警数": 0, "跳过包清单": [], "日志路径": str(网关错误日志), "日志存在": False}
    try:
        全部行 = 网关错误日志.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as 错误:
        return {"告警数": 0, "跳过包清单": [], "日志路径": str(网关错误日志),
                "日志存在": True, "读取问题": str(错误)}
    去重: dict = {}
    for 行 in 全部行[-80:]:
        行 = 行.strip()
        if not (行.startswith("[装配告警]") and "已跳过" in 行 and "｜" in 行):
            continue
        去重[行.split("已跳过", 1)[1].split("｜", 1)[0].strip()] = 行
    跳过包清单 = [去重[包名].split("已跳过", 1)[1].strip()
                   for 包名 in sorted(去重)][:最多条]
    return {"告警数": len(去重), "跳过包清单": 跳过包清单,
            "日志路径": str(网关错误日志), "日志存在": True,
            "提示": ("有包被跳过：包内全部能力都未注册，MCP 侧只会看到「能力不存在」。"
                     "常见原因是 __init__.py 参数名序与契约不一致、或包内导入报错。")
            if 去重 else ""}


def 期望运行缓存根() -> Path:
    """构建链写入的那棵树：`<本仓>/工程缓存`（本脚本在 `开发工具/能力网关/` 下，上溯两级）。"""
    return (Path(__file__).resolve().parents[2] / "工程缓存").resolve()


def 判定同根(网关真值: dict, plist环境: dict, plist工作目录: str,
             *, 期望根: Path | None = None) -> dict:
    """**纯判据**（不碰真网关、可造正反向样本）：网关运行态与构建链是否同根。

    为什么必须有这条判据（债务 #219，2026-09-21 实测）：`公共契约/运行时/运行缓存.解析运行缓存根`
    对制品根名 `平台客户端` 走「制品稳定根」分支 ⇒ plist 不设 `系统底座_工程缓存根` 时，网关把
    `制品仓库`／`运行数据` 解析到 `~/Library/Caches/系统工程平台/运行缓存/`，而构建/安装链写的是
    源码树 `工程缓存` ⇒ **同一条链两个仓**。实测症状：`校验平台客户端稳定路径` 回
    `有效=false 缺少激活指针 当前.json（从未安装）`，而**同期「健康 200／能力数 746／装配告警空」
    全绿** —— 只看健康检查发现不了，故必须单列判据。

    `网关真值` 的两个读数都**经网关取**（不靠 ps/argv 猜运行模式）；两问都要，缺一即判红：

    ① `制品根目录`（`平台控制面.包仓库.查询制品布局`）= 网关**自己解析出的**运行缓存根下的制品仓库，
       必须 = `<期望根>/制品仓库`；
    ② `稳定路径有效`／`稳定路径激活路径`（`平台控制面.包仓库.校验平台客户端稳定路径`）——
       未完成事项 #219 处置栏点名的口径，且顺带把「激活路径落在哪棵树」也钉住。

    再加一问「**下次重启**还同根吗」（看 plist，与前两问互补）：plist 的 `WorkingDirectory`
    一旦落在制品仓库下（= 制品模式），就必须设 `系统底座_工程缓存根` = `<期望根>`。
    理由：`launchctl kickstart` 用的是已加载的作业定义、**不重读 plist**（AGENTS.md §4 实测）
    ⇒ 「现在同根」不等于「重启后同根」；源码树模式下这一条不要求（那种模式本来就落在
    `工程缓存`，无分叉可言）。
    """
    期望 = Path(期望根 or 期望运行缓存根()).resolve()
    期望制品仓库 = 期望 / "制品仓库"
    真值表 = dict(网关真值 or {})
    环境表 = dict(plist环境 or {})
    值 = str(环境表.get(运行缓存变量名) or "").strip()
    工作目录文本 = str(plist工作目录 or "").strip()
    制品模式 = False
    if 工作目录文本:
        try:
            制品模式 = Path(工作目录文本).resolve().is_relative_to(期望 / "制品仓库")
        except OSError:
            制品模式 = False
    制品根目录 = str(真值表.get("制品根目录") or "")
    稳定有效 = 真值表.get("稳定路径有效")
    激活路径 = str(真值表.get("稳定路径激活路径") or "")
    结论: dict = {"同根": False, "期望制品仓库": str(期望制品仓库),
                  "制品根目录": 制品根目录, "稳定路径有效": 稳定有效,
                  "稳定路径激活路径": 激活路径, "plist值": 值,
                  "plist工作目录": 工作目录文本, "制品模式": 制品模式, "说明": ""}
    if not 制品根目录:
        结论["说明"] = ("网关侧没有回出制品根目录（查询制品布局 未成功）—— "
                       "判据取不到即判红（fail-closed，不许当通过）")
        return 结论
    if Path(制品根目录).resolve() != 期望制品仓库:
        结论["说明"] = (f"网关侧制品根目录 = {制品根目录}，期望 {期望制品仓库}"
                       f" ⇒ 运行态与构建链分叉（债务 #219）")
        return 结论
    if 稳定有效 is not True:
        结论["说明"] = (f"网关侧「平台客户端稳定路径」校验未通过（有效={稳定有效}，"
                       f"激活路径={激活路径 or '<空>'}）⇒ 稳定根与构建链不同根（债务 #219）")
        return 结论
    if 激活路径 and not Path(激活路径).resolve().is_relative_to(期望制品仓库):
        结论["说明"] = (f"稳定路径的激活路径 = {激活路径} 不在 {期望制品仓库} 下"
                       f" ⇒ 运行态与构建链分叉（债务 #219）")
        return 结论
    if 制品模式 and 值 != str(期望):
        结论["说明"] = (f"plist 处于制品模式（WorkingDirectory 在制品仓库下）但 {运行缓存变量名}"
                       f" = {值 or '<未设>'}，期望 {期望} ⇒ **下次重启**就会分叉（债务 #219）")
        return 结论
    结论["同根"] = True
    结论["说明"] = f"网关运行态与构建链同根：{期望制品仓库}"
    return 结论


def 运行态同根(凭证: str) -> dict:
    """取真值跑 `判定同根`：经网关读它自己解析出的制品根与稳定路径，再读 plist 的环境与工作目录。"""
    制品根目录 = ""
    稳定有效 = None
    激活路径 = ""
    稳定错误 = ""
    码, 信封 = _发("/网关/调用",
                  {"操作": "调用能力", "能力id": 制品布局能力, "参数": {}}, 凭证)
    值 = ((信封.get("值") or {}) if isinstance(信封, dict) else {}) or {}
    制品根目录 = str(值.get("制品根目录") or "")
    稳定码, 稳定信封 = _发("/网关/调用",
                        {"操作": "调用能力", "能力id": 稳定路径能力, "参数": {}}, 凭证)
    稳定值 = ((稳定信封.get("值") or {}) if isinstance(稳定信封, dict) else {}) or {}
    稳定有效 = 稳定值.get("有效")
    激活路径 = str(稳定值.get("激活路径") or "")
    稳定错误 = str(稳定值.get("消息") or 稳定信封.get("错误说明") or "")
    真值 = {"制品根目录": 制品根目录, "稳定路径有效": 稳定有效, "稳定路径激活路径": 激活路径}
    try:
        配置 = plistlib.loads(plist路径.read_bytes()) if plist路径.is_file() else {}
        结论 = 判定同根(真值, dict(配置.get("EnvironmentVariables") or {}),
                       str(配置.get("WorkingDirectory") or ""))
    except (OSError, ValueError) as 错误:
        结论 = 判定同根(真值, {}, "")
        结论["说明"] = f"读 plist 失败（{错误}）：{结论['说明']}"
    结论["HTTP状态码"] = 码
    结论["稳定路径HTTP状态码"] = 稳定码
    if 稳定错误:
        结论["稳定路径消息"] = 稳定错误
    return 结论


def 探活(凭证: str) -> int:
    码, 信封 = _发("/网关/调用", {"操作": "健康检查", "能力id": "", "参数": {}}, 凭证)
    结果 = {"模式": "探活", "服务标签": 服务标签, "进程号": 进程号(),
            "健康检查HTTP状态码": 码, "网关活着": 码 in (200, 401, 403)}
    结果["能力数"] = ((信封.get("值") or {}) if isinstance(信封, dict) else {}).get("能力数")
    结果["装配告警"] = 装配告警()
    # 运行态同根（债务 #219）：网关活着 ≠ 它的运行态与构建链同根 —— 只看健康检查发现不了分叉。
    结果["运行态同根"] = 运行态同根(凭证)
    结果["成功"] = bool(结果["网关活着"] and 结果["运行态同根"]["同根"])
    if not 结果["成功"]:
        结果["错误说明"] = ("网关未响应（看 /tmp/网关40007.err）" if not 结果["网关活着"]
                          else f"网关活着但运行态与构建链不同根：{结果['运行态同根']['说明']}")
    _落结果(结果)
    return 0 if 结果["成功"] else 1


def 重启(凭证: str, 超时秒: float) -> int:
    # 后台触发时，父进程要把「已触发」的返回值送回去（经 执行命令 提供者 → 网关），
    # 而子进程一开始 kickstart 就会把这条链路掉。先等一拍，让父进程先答话再动手。
    time.sleep(后台重启前延迟秒)
    前进程 = 进程号()
    # ★ 重启前先清空错误日志：launchd 的 StandardErrorPath 是 append 模式，
    # 多次启动的 [装配告警] 会累积 ⇒ 不清空的话 `--探活` 会把历史告警当成本次装配
    # （实测：已删掉的包仍被报为「本次跳过」）。清空后本次装配的告警从 0 行开始。
    try:
        网关错误日志.write_text("", encoding="utf-8")
    except OSError:
        pass
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
    return _收尾(结果, 凭证, 超时秒)


def 重载配置(凭证: str, 超时秒: float) -> int:
    """**重载 plist 后**重启：`bootout` + `bootstrap`（kickstart 不重读 plist）。

    为什么必须有这条腿（2026-09-24 实测，批J）：
    `kickstart -k` 用的是 launchd **已加载的作业定义**，**不重读 plist**（本模块 docstring
    早就写明这一点，但只把它当成「判据边界」写进 `判定同根`，**没有给出口**）。
    实测代价：plist 补了 `SoftResourceLimits.NumberOfFiles = 65536`（2026-09-24 00:58），
    当天 03:30 重启后**进程真实软限仍是 256** —— 经 MCP `执行命令` 起子进程读
    `resource.getrlimit(RLIMIT_NOFILE)` 实测 `(256, …)`。于是「fd 耗尽」这类**配置级**
    修复永远只停在文件上，谁都不会发现（`判定同根` 只看运行缓存根，不看资源限额）。
    配置改了却没有一条腿把它读进去 = 与「源码改了没重建制品」同一类缺陷。

    做法：`bootout <域>/<标签>` 卸掉已加载定义，再 `bootstrap <域> <plist>` 按**盘上
    plist 现读**重新加载并启动（`RunAtLoad=真` ⇒ 随即拉起）。就绪等待、探活、能力数、
    装配告警、运行态同根与结论落盘**全部复用 `_收尾`**（一处实现，不复制一遍）。

    边界（如实）：`bootout` 非 0 不直接判死 —— 若作业本就没加载，它照样报错，
    此时 `bootstrap` 才是真判据；故 `bootout` 退出码只**记录**，成败由 `bootstrap` 定。
    """
    time.sleep(后台重启前延迟秒)
    前进程 = 进程号()
    try:
        网关错误日志.write_text("", encoding="utf-8")
    except OSError:
        pass
    域 = f"gui/{os.getuid()}"
    结果: dict = {"模式": "重载配置", "服务标签": 服务标签, "重启前进程号": 前进程,
                  "plist路径": str(plist路径)}
    卸载 = subprocess.run(["launchctl", "bootout", f"{域}/{服务标签}"],
                         capture_output=True, text=True, timeout=60)
    结果["bootout退出码"] = 卸载.returncode
    # ★ `bootout` 之后**不能立刻** `bootstrap`：实测（2026-09-24，本批首次用这条腿）
    # 第一次必得 `Bootstrap failed: 5: Input/output error`，隔一拍重试即成功 —— 是
    # launchd 卸载尚未落定的**竞态**，不是配置错（同一份 plist 紧接着 `bootstrap` 就成）。
    # 故按 `重载重试次数` 退避重试，并把**轮次**记进结论：判据要能区分「第一次就成」
    # 与「重试才成」，否则这个竞态会被当成偶发噪声，下一次仍要人工救场。
    装载 = None
    轮次 = 0
    for 轮次 in range(1, 重载重试次数 + 1):
        if 轮次 > 1:
            time.sleep(重载重试间隔秒)
        装载 = subprocess.run(["launchctl", "bootstrap", 域, str(plist路径)],
                             capture_output=True, text=True, timeout=60)
        if 装载.returncode == 0:
            break
    结果["bootstrap退出码"] = 装载.returncode
    结果["bootstrap轮次"] = 轮次
    if 装载.returncode != 0:
        结果["成功"] = False
        结果["错误说明"] = ("按盘上 plist 重新加载失败："
                          + (装载.stderr or 装载.stdout or "").strip()[:300])
        _落结果(结果)
        return 1
    return _收尾(结果, 凭证, 超时秒)


def _收尾(结果: dict, 凭证: str, 超时秒: float) -> int:
    """重启/重载共用收尾：等就绪 → 探活 → 能力数 → 装配告警 → 运行态同根 → 落盘。

    **一处实现**（哲学 1.2）：`重启` 与 `重载配置` 只差「怎么把进程换掉」那一步，
    换完之后的判据与结论形状逐字相同，故不各写一遍。
    """
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
    结果["装配告警"] = 装配告警()
    结果["运行态同根"] = 运行态同根(凭证)
    结果["成功"] = bool(结果["能力数"] and 结果["运行态同根"]["同根"])
    if not 结果["成功"]:
        if not 结果["能力数"]:
            结果["错误说明"] = "网关在听但 健康检查 未回能力数，需人工看一眼"
        else:
            结果["错误说明"] = f"网关起来了但运行态与构建链不同根：{结果['运行态同根']['说明']}"
    _落结果(结果)
    return 0 if 结果["成功"] else 1


def 触发后台重启(argv: list[str], 前台参数: str = "--前台") -> int:
    """脱离进程组起子进程做重启 + 轮询，父进程立即返回（见模块 docstring 的 ★ 段）。

    `前台参数` 决定子进程走哪条腿：`--前台`（kickstart）或 `--重载配置`（bootout+bootstrap）。
    两条腿共用本函数，故**脱离进程组的姿势只有一处实现**。
    """
    if 结果文件.exists():
        结果文件.unlink()
    子参数 = [sys.executable, str(Path(__file__).resolve()), 前台参数]
    if _取值(argv, "--超时"):
        子参数 += ["--超时", _取值(argv, "--超时")]
    with open(os.devnull, "wb") as 空:
        subprocess.Popen(子参数, stdout=空, stderr=空, stdin=空,
                         **平台适配.子进程组启动标志(), cwd=str(结果文件.parents[1]))
    print(json.dumps({
        "模式": "触发后台重启", "服务标签": 服务标签, "重启前进程号": 进程号(),
        "成功": 真, "已触发": 真, "结果文件": str(结果文件),
        "提示": "重启会掐断本次调用所在进程组，故结论写文件；"
                "等 1~3 秒再跑 `--看结果` 或 `--探活` 取结论",
    }, ensure_ascii=False))
    return 0


def 看结果() -> int:
    if not 结果文件.is_file():
        print(json.dumps({"成功": 假, "错误说明": f"还没有结果文件：{结果文件}"}, ensure_ascii=False))
        return 1
    print(结果文件.read_text(encoding="utf-8"))
    return 0


if __name__ == "__main__":
    参 = sys.argv[1:]
    if "--看结果" in 参:
        raise SystemExit(看结果())
    凭 = 读取凭证()
    if not 凭:
        print(json.dumps({"成功": 假, "错误说明": f"plist 里取不到 {凭证变量名}"}, ensure_ascii=False))
        raise SystemExit(2)
    if "--运行态同根" in 参:
        # 只读探针：不落盘（区别于 --探活 会写 网关重启结果.json），退出码 0/1 即结论。
        结论 = 运行态同根(凭)
        print(json.dumps(结论, ensure_ascii=False))
        raise SystemExit(0 if 结论["同根"] else 1)
    if "--探活" in 参:
        raise SystemExit(探活(凭))
    if "--前台" in 参:
        raise SystemExit(重启(凭, _超时秒(参)))
    if "--重载配置" in 参:
        # 同步重载（终端直跑用）；经 MCP 调时用下面的后台形态，否则网关换进程会掐断调用链
        raise SystemExit(重载配置(凭, _超时秒(参)))
    if "--重载配置后台" in 参:
        raise SystemExit(触发后台重启(参, "--重载配置"))
    raise SystemExit(触发后台重启(参))
