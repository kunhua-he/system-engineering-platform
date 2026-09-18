"""模型端点探针：按「目的」探测一个模型端点是否可用、走哪种协议。

**目的（华哥口径 2026-09-18）**：用户只要输入 url 和 key 就行 —— 缺的参数自动补齐。
    第一步：获取模型（调用方没给 → 向端点取模型清单；给了 → 跳过）
    第二步：拿模型试协议（调用方给了协议 → 只打这一个；没给 → 三种按序打，命中即停）
    返回：有一个成功 → 报成功 + 另两个的失败原因；三个全失败 → 报三个失败原因

**为什么单独成文件**：本能力自带完整边界（只依赖标准库 + 结果类型），
与「句柄/连接/启动」三类职责无耦合，照 `实现/响应归一化.py` 的拆分先例。

**三个实测钉死的坑（2026-09-18 现场实测）**：
1. 第一步「取模型」**必须用 GET**：llama-server 对 `POST /v1/models` 返回 404
   （它的 POST 走 chat 路由），写错第一步就整个失败。
2. **状态码判不出协议**：llama-server 是「宽容服务器」，`/chat/completions`、
   `/responses`、`/messages` 全回 200 —— 必须看**响应体特征字段**。
3. **`/models` 通 ≠ 该端点能聊**：实测 8328 的 `/v1/models` 返回 `grok-4.5`，
   但 `/v1/chat/completions` 是 404，真正能聊的在 `/hermes-chat/v1/chat/completions`。
   ⇒ 两步结果必须分开如实报，不能因第一步成功就宣布可用；**不猜根路径**。

零第三方依赖：只用标准库 `json` / `urllib` / `time`。
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import Any

from 公共契约.基础类型.逻辑类型 import 假, 真
from 公共契约.基础类型.结果类型 import 结果

# ── 协议定义（路径 + 请求体 + 鉴权头 + 响应体特征）────────────────────
# ★ 特征函数是「唯一可靠判据」—— 状态码会被宽容服务器骗过（见文件头坑二）。
协议定义表: dict[str, dict[str, Any]] = {
    "chat_completions": {
        "路径": "/chat/completions",
        "请求体": lambda 模型名: {
            "model": 模型名,
            "messages": [{"role": "user", "content": 探针内容}],
            "max_tokens": 探针最大令牌,
        },
        "鉴权头": lambda 密钥: {"Authorization": f"Bearer {密钥}"},
        "特征": lambda 响应体: isinstance(响应体, dict) and "choices" in 响应体,
        "特征说明": "有 choices[]",
    },
    "codex_responses": {
        "路径": "/responses",
        "请求体": lambda 模型名: {
            "model": 模型名,
            "input": 探针内容,
            "max_output_tokens": 探针最大令牌,
        },
        "鉴权头": lambda 密钥: {"Authorization": f"Bearer {密钥}"},
        "特征": lambda 响应体: isinstance(响应体, dict)
        and "output" in 响应体
        and "choices" not in 响应体,
        "特征说明": "有 output[] 且无 choices[]",
    },
    "anthropic_messages": {
        "路径": "/messages",
        "请求体": lambda 模型名: {
            "model": 模型名,
            "max_tokens": 探针最大令牌,
            "messages": [{"role": "user", "content": 探针内容}],
        },
        "鉴权头": lambda 密钥: {
            "x-api-key": 密钥,
            "anthropic-version": "2023-06-01",
        },
        "特征": lambda 响应体: isinstance(响应体, dict)
        and "content" in 响应体
        and "type" in 响应体,
        "特征说明": "有 content 且 type",
    },
}

默认超时秒 = 15
取模型超时秒 = 10
探针内容 = "hi"          # 华哥口径：「只要打个 hi 看看有没有返回」
探针最大令牌 = 8          # 成本极低
允许协议名 = frozenset(协议定义表)
协议取值说明 = "协议必须是 chat_completions、codex_responses 或 anthropic_messages"


def _失败(错误码: str, 说明: str, **额外: Any) -> 结果:
    return 结果.失败(错误码, 说明, 来源="模型连接器", **额外)


def _规范基址(url: str) -> str:
    """去掉尾部斜杠；不改动路径结构（★ 不猜根路径，见文件头坑三）。"""
    return url.strip().rstrip("/")


def _校验url(url: Any) -> str | None:
    """校验 url 是 http/https 绝对地址；不合法返回 None。"""
    if not isinstance(url, str) or not url.strip():
        return None
    净 = url.strip()
    if not (净.startswith("http://") or 净.startswith("https://")):
        return None
    主机部分 = 净.split("//", 1)[-1].split("/", 1)[0]
    return 净 if 主机部分 else None


def _发请求(
    地址: str,
    方法: str,
    请求体: dict | None,
    鉴权头: dict,
    超时秒: float,
) -> tuple[int | None, dict | None, str | None, str | None]:
    """发一次 HTTP 请求。

    返回 (状态码, 解析后的响应体, 连接层异常说明, 解析异常说明)。
    网络失败一律不抛异常，转成说明文本返回 —— 探针不该因目标不通而自身崩掉。
    """
    数据 = json.dumps(请求体).encode("utf-8") if 请求体 is not None else None
    请求 = urllib.request.Request(
        地址,
        data=数据,
        headers={"Content-Type": "application/json", **鉴权头},
        method=方法,
    )
    try:
        with urllib.request.urlopen(请求, timeout=超时秒) as 响应:
            原文 = 响应.read().decode("utf-8", "replace")
            状态码 = int(响应.status)
    except urllib.error.HTTPError as 异常:
        try:
            原文 = 异常.read().decode("utf-8", "replace")
        except Exception:
            原文 = ""
        状态码 = int(异常.code)
    except Exception as 异常:
        名称 = type(异常).__name__
        说明 = str(异常)[:160]
        return None, None, f"{名称}: {说明}", None
    try:
        return 状态码, json.loads(原文), None, None
    except Exception:
        return 状态码, None, None, "响应体不是合法 JSON"


def _取模型清单(基址: str, 密钥: str, 超时秒: float) -> tuple[list[str], list[str]]:
    """第一步：向端点取模型清单。

    ★ 必须用 GET（文件头坑一）。
    返回 (模型名列表, 诊断列表)。失败不中断流程，只在诊断里如实记录。
    """
    诊断: list[str] = []
    地址 = f"{基址}/models"
    状态码, 响应体, 连接异常, 解析异常 = _发请求(
        地址, "GET", None, {"Authorization": f"Bearer {密钥}"}, 超时秒
    )
    if 连接异常:
        诊断.append(f"取模型清单失败：连接失败（{连接异常}）")
        return [], 诊断
    if 状态码 != 200:
        诊断.append(f"取模型清单失败：HTTP {状态码}")
        return [], 诊断
    if 解析异常 or not isinstance(响应体, dict):
        诊断.append(f"取模型清单失败：{解析异常 or '响应体不是对象'}")
        return [], 诊断
    条目 = 响应体.get("data") or 响应体.get("models") or []
    if not isinstance(条目, list):
        诊断.append("取模型清单失败：清单字段不是列表")
        return [], 诊断
    模型名表: list[str] = []
    for 项 in 条目:
        if isinstance(项, dict):
            名 = 项.get("id") or 项.get("name") or 项.get("model")
            if isinstance(名, str) and 名.strip():
                模型名表.append(名.strip())
    if not 模型名表:
        诊断.append("取模型清单成功，但清单为空")
    else:
        诊断.append(f"自动取到模型：{模型名表}")
    return 模型名表, 诊断


def _判单项(
    协议名: str, 状态码: int | None, 响应体: dict | None,
    连接异常: str | None, 解析异常: str | None,
) -> tuple[bool, str]:
    """判定单次探测是否命中该协议。返回 (是否可用, 判据说明)。"""
    定义 = 协议定义表[协议名]
    if 连接异常:
        return 假, f"连接失败：{连接异常}"
    if 状态码 in (401, 403):
        return 假, f"鉴权失败（HTTP {状态码}）"
    if 状态码 == 404:
        return 假, "路径不存在（HTTP 404）"
    if 状态码 != 200:
        return 假, f"HTTP {状态码}"
    if 解析异常:
        return 假, f"200 但{解析异常}（可能不是模型端点）"
    if 定义["特征"](响应体):
        return 真, f"响应体特征命中（{定义['特征说明']}）"
    顶层键 = list(响应体.keys())[:6] if isinstance(响应体, dict) else []
    return 假, f"200 但响应体无该协议特征（顶层键 {顶层键}，可能不是模型端点）"


def _试一个协议(
    基址: str, 密钥: str, 模型名: str, 协议名: str, 超时秒: float
) -> dict[str, Any]:
    """对单个协议打一次探针，返回该协议的明细项。"""
    定义 = 协议定义表[协议名]
    路径 = 定义["路径"]
    开始 = time.perf_counter()
    状态码, 响应体, 连接异常, 解析异常 = _发请求(
        f"{基址}{路径}",
        "POST",
        定义["请求体"](模型名),
        定义["鉴权头"](密钥),
        超时秒,
    )
    耗时毫秒 = round((time.perf_counter() - 开始) * 1000, 3)
    可用, 判据 = _判单项(协议名, 状态码, 响应体, 连接异常, 解析异常)
    明细: dict[str, Any] = {
        "协议": 协议名,
        "请求路径": f"{基址}{路径}",
        "状态码": 状态码,
        "可用": 可用,
        "判据": 判据,
        "响应毫秒": 耗时毫秒,
    }
    if 可用 and isinstance(响应体, dict):
        回带模型 = 响应体.get("model")
        if isinstance(回带模型, str) and 回带模型.strip():
            明细["回带模型"] = 回带模型.strip()
    return 明细


def 探测模型端点(
    url: Any = None,
    api_key: Any = None,
    模型: Any = None,
    协议: Any = None,
    超时秒: Any = None,
) -> 结果:
    """探测一个模型端点：取模型 → 试协议 → 回报结果。

    参数:
        url: 端点地址（必填），如 http://127.0.0.1:11434/v1
        api_key: 密钥（选填；缺省用 "123" 占位，本地服务常不校验）
        模型: 模型名（选填；缺省自动向端点取）
        协议: 协议（选填；缺省自动依次试三种，命中即停）
             取值 chat_completions / codex_responses / anthropic_messages
        超时秒: 单次请求超时秒（选填，默认 15）

    返回（值结构）:
        可用: 逻辑型 —— 是否有任一协议命中
        命中协议: 文本型 —— 命中的协议名；全失败时为「都不通」
        模型: 文本型 —— 实际使用的模型名
        模型清单: 列表型 —— 第一步取到的全量模型名
        响应毫秒: 双精度数型 —— 命中那次请求的耗时（全失败时为 None）
        逐项结果: 列表型 —— 每个协议的 协议/请求路径/状态码/可用/判据/响应毫秒
        诊断: 列表型 —— 如「自动取到模型：[…]」
    """
    净url = _校验url(url)
    if 净url is None:
        return _失败("参数不合法", f"url 必须是 http/https 绝对地址: {url!r}")
    基址 = _规范基址(净url)
    密钥 = api_key.strip() if isinstance(api_key, str) and api_key.strip() else "123"
    # ★ HTTP 头只允许 latin-1（RFC 7230）：非 ASCII 密钥会被 urllib 抛 UnicodeEncodeError，
    #   那是编码错误不是网络故障，必须在参数校验阶段就明确拒绝（实测坑，2026-09-18）。
    try:
        密钥.encode("latin-1")
    except UnicodeEncodeError:
        return _失败("参数不合法",
                    f"api_key 含非 ASCII 字符（HTTP 头只允许 latin-1）：{api_key!r}。"
                    "若密钥确含非 ASCII，请改用网关或适配层转发，本能力不支持放进请求头。")

    指定协议: Any = None
    if 协议 is not None:
        候选 = 协议.strip() if isinstance(协议, str) else ""
        if 候选 not in 允许协议名:
            return _失败("参数不合法", f"{协议取值说明}: {协议!r}")
        指定协议 = 候选

    try:
        超时数值 = float(超时秒) if 超时秒 is not None else 默认超时秒
    except (TypeError, ValueError):
        return _失败("参数不合法", f"超时秒必须是数字: {超时秒!r}")
    if 超时数值 <= 0:
        return _失败("参数不合法", f"超时秒必须大于 0: {超时数值}")
    诊断: list[str] = []

    # ── 第一步：获取模型 ──────────────────────────────────
    模型清单: list[str] = []
    实际模型 = 模型.strip() if isinstance(模型, str) and 模型.strip() else ""
    if not 实际模型:
        模型清单, 取模型诊断 = _取模型清单(基址, 密钥, min(超时数值, float(取模型超时秒)))
        诊断.extend(取模型诊断)
        if 模型清单:
            实际模型 = 模型清单[0]
        else:
            实际模型 = "unknown"
            诊断.append("未取到模型清单，用占位名继续探协议")

    # ── 第二步：试协议（命中即停）────────────────────────
    逐项结果: list[dict[str, Any]] = []
    待试 = [指定协议] if 指定协议 else list(协议定义表.keys())
    for 协议名 in 待试:
        明细 = _试一个协议(基址, 密钥, 实际模型, 协议名, 超时数值)
        逐项结果.append(明细)
        if 明细["可用"]:
            break

    命中 = next((项 for 项 in 逐项结果 if 项["可用"]), None)
    return 结果.成功结果(
        {
            "可用": 真 if 命中 else 假,
            "命中协议": 命中["协议"] if 命中 else "都不通",
            "模型": 实际模型,
            "模型清单": 模型清单,
            "响应毫秒": 命中["响应毫秒"] if 命中 else None,
            "逐项结果": 逐项结果,
            "诊断": 诊断,
        }
    )


__all__ = ["探测模型端点"]
