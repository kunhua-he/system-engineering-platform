"""薄壳唯一转发通道：HTTP POST http://127.0.0.1:40007/网关/调用。

薄壳不监听任何端口，只作为客户端调用唯一网关（40007），没有第二条转发路径。
凭证只从环境变量「系统库网关凭证」读取：缺失时明确失败「网关凭证缺失」；
凭证不写入日志、返回值、文件与异常文本，只在 Authorization 请求头里使用。

**本文件同时是全平台唯一一条网关 HTTP 腿**（2026-09-22 #85 收口）：
`发送()` 是唯一的 HTTP 收发实现（任意路径 / 方法 / 基地址 / 凭证 / 超时），
`转发()` 是它的薄壳专用薄包装（POST /网关/调用 + 注入 `调用方超时秒` + 凭证 fail-closed）。
开发工具里其它要打网关的脚本一律 `from 开发工具.薄壳.网关转发 import 发送`，
**不得再自建 urllib / http.client 客户端** —— 同一件事只留一条腿（哲学 1.2）。
为什么统一件落在这里、而不是能力 `网络通信支持库.请求.发送请求`：本文件的使用方全是
**网关的客户端**（MCP 薄壳在平台进程之外、HTML 黑盒回归、消费者侧队列、性能基准的进程内
网关），它们手里没有（也不该有）平台的能力调用器；能力腿要在**装配进平台进程之后**才可用，
两者不是同一条腿的两种写法。
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
import uuid

网关基地址 = "http://127.0.0.1:40007"
网关路径 = "/网关/调用"
网关调用地址 = 网关基地址 + 网关路径
# http.client 只接受 ASCII 请求行：路径必须百分号编码（网关侧统一 unquote 回中文路径）。
# safe 里带 "%" 是为了让**已经编码过**的路径（如 "/%E5%81%A5%E5%BA%B7"）原样通过、
# 不被二次编码（现场：开发工具/性能基准/基准场景.py 传的就是已编码路径）。
网关请求地址 = 网关基地址 + urllib.parse.quote(网关路径, safe="/%")
凭证环境变量 = "系统库网关凭证"
默认超时秒 = 120.0
#: 本值是薄壳**自己的生命周期上限**：它既作为 urlopen 超时，又作为 `调用方超时秒`
#: 声明给网关（见 `转发`）。两者必须同源——分开写会让「薄壳等 120、却告诉网关
#: 它可以跑 1800」重新出现，那正是 2026-09-21 内存被打爆的形态。


def 读取凭证() -> str:
    """只从环境变量取凭证；本函数返回值只允许进请求头，禁止打印或落盘。"""
    return os.environ.get(凭证环境变量, "").strip()


def _请求地址(路径: str, 基地址: str) -> str:
    """把「中文网关路径」或「已编码路径 / 完整 URL」折成可发的 ASCII 地址。"""
    if 路径.startswith(("http://", "https://")):
        return 路径
    return 基地址.rstrip("/") + "/" + urllib.parse.quote(路径.lstrip("/"), safe="/%")


def _显示地址(路径: str, 基地址: str) -> str:
    """错误说明里给人看的地址：完整 URL 原样、中文路径不编码（可读，不改语义）。"""
    if 路径.startswith(("http://", "https://")):
        return 路径
    return 基地址.rstrip("/") + "/" + 路径.lstrip("/")


def 发送(路径: str, 请求体: dict | None = None, *, 方法: str = "POST",
         基地址: str = 网关基地址, 凭证: str | None = None,
         超时秒: float = 默认超时秒,
         附加头: dict[str, str] | None = None) -> dict:
    """对网关发一次 HTTP 请求，返回 {HTTP状态码, 信封, 错误码, 错误说明}。

    **全平台唯一一条 HTTP 腿**：薄壳与开发工具脚本共用本函数，谁都不再自建
    urllib / http.client 客户端。不重试、不做业务判断；网关不可达与响应非 JSON
    都如实上报（`HTTP状态码` 为 None + 明确错误码），绝不吞掉 HTTP 状态码。

    - `路径`：中文网关路径（如 `网关/调用`）自动百分号编码（HTTP 请求行只接受
      ASCII）；已是完整 URL（`http://…`）或已编码的 ASCII 路径原样使用。
    - `基地址`：默认本机 40007；`路径` 传完整 URL 时本参数被忽略。
    - `凭证`：`None` = 从环境变量「系统库网关凭证」读；空串 = **不带** Authorization
      头（只给免凭证的测试网关用，如性能基准的进程内回环网关）；其余原样进请求头。
      「凭证缺失即不转发」的 fail-closed 由薄壳入口 `转发()` 负责（见该函数）。
    - `附加头`：额外请求头（如 `X-请求-id`）；**Authorization 一律以本函数的 `凭证`
      为准** —— 附加头里的同名键被丢弃，避免出现第二个凭证来源。
    """
    凭证 = 读取凭证() if 凭证 is None else str(凭证).strip()
    头 = {键: 值 for 键, 值 in (附加头 or {}).items() if 键.lower() != "authorization"}
    头["Content-Type"] = "application/json; charset=utf-8"
    if 凭证:
        头["Authorization"] = f"Bearer {凭证}"
    数据 = None if 请求体 is None else json.dumps(请求体, ensure_ascii=False).encode("utf-8")
    请求 = urllib.request.Request(
        _请求地址(路径, 基地址), data=数据, method=方法, headers=头)
    try:
        with urllib.request.urlopen(请求, timeout=float(超时秒)) as 响应:
            状态码, 原文 = int(响应.status), 响应.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as 错误:
        # 网关 401/404/500 等带响应体，仍按统一信封解析，不吞掉状态码。
        状态码, 原文 = int(错误.code), 错误.read().decode("utf-8", "replace")
    except TimeoutError:
        return {"HTTP状态码": None, "信封": None, "错误码": "网关超时",
                "错误说明": f"转发唯一网关超时（{超时秒} 秒）"}
    except (urllib.error.URLError, OSError) as 错误:
        return {"HTTP状态码": None, "信封": None, "错误码": "网关不可达",
                "错误说明": f"无法连接唯一网关 {_显示地址(路径, 基地址)}"
                            f"（{type(错误).__name__}）"}
    try:
        信封 = json.loads(原文)
    except json.JSONDecodeError:
        return {"HTTP状态码": 状态码, "信封": None, "错误码": "网关响应非JSON",
                "错误说明": 原文[:200]}
    if not isinstance(信封, dict):
        return {"HTTP状态码": 状态码, "信封": None, "错误码": "网关响应非对象",
                "错误说明": 原文[:200]}
    return {"HTTP状态码": 状态码, "信封": 信封, "错误码": "", "错误说明": ""}


def 转发(请求体: dict) -> dict:
    """把请求体发到唯一网关，返回 {HTTP状态码, 信封, 错误码, 错误说明}。

    不重试、不做业务判断；网关不可达与响应非 JSON 都如实上报。

    **唯一一处改写：注入 `调用方超时秒`（2026-09-21 华哥裁决）**。
    薄壳自己最多等 `默认超时秒`（120 秒），据「下级生命周期不得超过上级」把这个
    上限告诉网关，网关据此把本次执行的超时**压到不超过它**。
    为什么必须有（当日实测）：MCP 客户端 120 秒就断连，而网关允许本次执行跑到
    1800 秒 —— 调用方走了、网关还在替它干活，线程与子进程都不回收，是 2026-09-21
    内存被打爆的导火索。调用方已显式给 `调用方超时秒` 时**以调用方为准**（不覆盖）。

    收发实现走 `发送()`（全平台唯一一条 HTTP 腿）；凭证缺失的 fail-closed 留在这里：
    薄壳是受控接入面，凭证缺失时必须**明确失败且不发起转发**。
    """
    载荷 = dict(请求体)
    载荷.setdefault("调用方超时秒", 默认超时秒)
    凭证 = 读取凭证()
    if not 凭证:
        return {
            "HTTP状态码": None,
            "信封": None,
            "错误码": "网关凭证缺失",
            "错误说明": f"环境变量 {凭证环境变量} 未设置或为空，薄壳不发起转发",
        }
    return 发送(网关路径, 载荷, 方法="POST", 凭证=凭证, 超时秒=默认超时秒,
                附加头={"X-Request-ID": uuid.uuid4().hex[:16]})
