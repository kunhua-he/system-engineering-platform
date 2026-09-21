"""薄壳唯一转发通道：HTTP POST http://127.0.0.1:40007/网关/调用。

薄壳不监听任何端口，只作为客户端调用唯一网关（40007），没有第二条转发路径。
凭证只从环境变量「系统库网关凭证」读取：缺失时明确失败「网关凭证缺失」；
凭证不写入日志、返回值、文件与异常文本，只在 Authorization 请求头里使用。
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
网关请求地址 = 网关基地址 + urllib.parse.quote(网关路径, safe="/")
凭证环境变量 = "系统库网关凭证"
默认超时秒 = 120.0
#: 本值是薄壳**自己的生命周期上限**：它既作为 urlopen 超时，又作为 `调用方超时秒`
#: 声明给网关（见 `转发`）。两者必须同源——分开写会让「薄壳等 120、却告诉网关
#: 它可以跑 1800」重新出现，那正是 2026-09-21 内存被打爆的形态。


def 读取凭证() -> str:
    """只从环境变量取凭证；本函数返回值只允许进请求头，禁止打印或落盘。"""
    return os.environ.get(凭证环境变量, "").strip()


def 转发(请求体: dict) -> dict:
    """把请求体发到唯一网关，返回 {HTTP状态码, 信封, 错误码, 错误说明}。

    不重试、不做业务判断；网关不可达与响应非 JSON 都如实上报。

    **唯一一处改写：注入 `调用方超时秒`（2026-09-21 华哥裁决）**。
    薄壳自己最多等 `默认超时秒`（120 秒），据「下级生命周期不得超过上级」把这个
    上限告诉网关，网关据此把本次执行的超时**压到不超过它**。
    为什么必须有（当日实测）：MCP 客户端 120 秒就断连，而网关允许本次执行跑到
    1800 秒 —— 调用方走了、网关还在替它干活，线程与子进程都不回收，是 2026-09-21
    内存被打爆的导火索。调用方已显式给 `调用方超时秒` 时**以调用方为准**（不覆盖）。
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
    数据 = json.dumps(载荷, ensure_ascii=False).encode("utf-8")
    请求 = urllib.request.Request(
        网关请求地址,
        data=数据,
        method="POST",
        headers={
            "Content-Type": "application/json; charset=utf-8",
            "Authorization": f"Bearer {凭证}",
            "X-Request-ID": uuid.uuid4().hex[:16],
        },
    )
    try:
        with urllib.request.urlopen(请求, timeout=默认超时秒) as 响应:
            状态码, 原文 = int(响应.status), 响应.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as 错误:
        # 网关 401/404/500 等带响应体，仍按统一信封解析，不吞掉状态码。
        状态码, 原文 = int(错误.code), 错误.read().decode("utf-8", "replace")
    except TimeoutError:
        return {"HTTP状态码": None, "信封": None, "错误码": "网关超时",
                "错误说明": f"转发唯一网关超时（{默认超时秒} 秒）"}
    except (urllib.error.URLError, OSError) as 错误:
        return {"HTTP状态码": None, "信封": None, "错误码": "网关不可达",
                "错误说明": f"无法连接唯一网关 {网关调用地址}（{type(错误).__name__}）"}
    try:
        信封 = json.loads(原文)
    except json.JSONDecodeError:
        return {"HTTP状态码": 状态码, "信封": None, "错误码": "网关响应非JSON",
                "错误说明": 原文[:200]}
    if not isinstance(信封, dict):
        return {"HTTP状态码": 状态码, "信封": None, "错误码": "网关响应非对象",
                "错误说明": 原文[:200]}
    return {"HTTP状态码": 状态码, "信封": 信封, "错误码": "", "错误说明": ""}
