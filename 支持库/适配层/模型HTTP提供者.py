# ruff: noqa: N999
"""模型 HTTP Provider：统一承接 LLM、向量、重排的本地/云端兼容协议。"""

from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from typing import Any

from 公共契约.基础类型.结果类型 import 结果
from 公共契约.运行时.有界IO import 受限读取

来源 = "模型HTTP提供者"
默认协议 = "chat_completions"
# 与 大语言模型支持库.模型连接器.协议别名 同表：公开短值 chat/res/anthropic 与内部长值一一对应。
# 适配层与连接器是两个层，不能互相导入；此处镜像该表，并由
# 测试中心.支持库.测试_模型协议别名 断言两份取值一致，防止漂移。
协议别名表 = {
    "chat": "chat_completions",
    "chat_completions": "chat_completions",
    "res": "codex_responses",
    "codex_responses": "codex_responses",
    "anthropic": "anthropic_messages",
    "anthropic_messages": "anthropic_messages",
}
协议取值说明 = "协议必须是 chat_completions、codex_responses 或 anthropic_messages"
# anthropic Messages 协议：端点 /v1/messages、认证 x-api-key、版本头固定、max_tokens 必填。
# 工具名规范来自协议定义（^[a-zA-Z0-9_-]{1,64}$）；探针实测中文工具名会被上游拒为 502，
# 故在本层前置拒绝，不把非法工具名发给上游。
anthropic协议版本 = "2023-06-01"
anthropic默认最大令牌数 = 4096
anthropic工具名规范 = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")
anthropic完成原因表 = {
    "end_turn": "stop",
    "stop_sequence": "stop",
    "max_tokens": "length",
    "tool_use": "tool_calls",
    "pause_turn": "stop",
    "refusal": "stop",
}
响应上限字节 = 1024 * 1024
流式响应上限字节 = 1024 * 1024
流式事件上限字节 = 64 * 1024
流式事件数量上限 = 10000
流式读取块大小 = 4096


def _规范化协议(协议: Any) -> str | None:
    """把公开短协议别名统一为内部长协议；非法值返回 None。"""
    return 协议别名表.get(协议) if isinstance(协议, str) else None


def _失败(错误码: str, 消息: str, *, 可重试: bool = False,
        详情: dict[str, Any] | None = None) -> 结果:
    return 结果.失败(错误码, 消息, 来源=来源, 可重试=可重试, 详情=详情)


def 归一模型端点(配置: dict[str, Any], 后缀: str) -> str:
    """把配置里的 url 与目标后缀合成完整端点，两层共用同一套归一。

    归一规则：剥掉 url 里可能已写全的已知后缀、保证以 /v1 结尾、再拼目标后缀。
    连接器 `_HTTP调用模型` 与适配层调用路径都走这里，避免同一份配置在两层得到
    不同地址（历史上连接器只做 `基址 + 路径`，url 不带 /v1 时整条链路必失败）。
    """
    地址 = str(配置.get("url") or "").strip().rstrip("/")
    if not 地址:
        return ""
    for 已有后缀 in ("/chat/completions", "/responses", "/messages", "/embeddings", "/rerank"):
        if 地址.endswith(已有后缀):
            地址 = 地址[: -len(已有后缀)]
            break
    if not 地址.endswith("/v1"):
        地址 += "/v1"
    return 地址 + 后缀


def 检查不可发送请求头(请求头: dict[str, Any]) -> str:
    """返回第一个不可发送的请求头说明；全部可发送时返回空串。

    HTTP 头只能承载 latin-1 文本：api_key 或额外请求头里出现非 ASCII 字符时，
    出站会在 http.client 里抛 UnicodeEncodeError（历史上会逃逸或被笼统归为调用失败）。
    这里前置判定，把它变成可诊断的失败；连接器侧同一口径复用本函数。
    """
    for 键, 值 in 请求头.items():
        for 项 in (键, 值):
            try:
                str(项).encode("latin-1")
            except UnicodeEncodeError:
                return f"请求头 {键} 含非 ASCII 字符，无法作为 HTTP 头发送"
    return ""


def _请求(配置: dict[str, Any], 后缀: str, 载荷: dict[str, Any],
         附加请求头: dict[str, Any] | None = None, *,
         协议: str = "chat_completions") -> tuple[int, dict[str, Any] | None, str]:
    地址 = 归一模型端点(配置, 后缀)
    if not 地址:
        return 0, None, "未配置模型 HTTP 地址"
    请求头 = {"Content-Type": "application/json"}
    if 配置.get("api_key"):
        if 协议 == "anthropic_messages":
            # anthropic 按协议规范走 x-api-key + 版本头（探针实测 Bearer 亦可通过，
            # 但规范认证是 x-api-key，故只发规范头，不双发两套认证）。
            请求头["x-api-key"] = str(配置["api_key"])
            请求头["anthropic-version"] = anthropic协议版本
        else:
            请求头["Authorization"] = f"Bearer {配置['api_key']}"
    if isinstance(配置.get("额外请求头"), dict):
        请求头.update(配置["额外请求头"])
    if isinstance(附加请求头, dict):
        请求头.update(附加请求头)
    非法头 = 检查不可发送请求头(请求头)
    if 非法头:
        return 400, None, 非法头
    请求 = urllib.request.Request(
        地址,
        data=json.dumps(载荷, ensure_ascii=False).encode("utf-8"),
        headers=请求头,
        method="POST",
    )
    try:
        开放器 = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with 开放器.open(请求, timeout=float(配置.get("请求超时秒") or 600)) as 响应:
            正文, 超限 = 受限读取(响应, 响应上限字节)
            if 超限:
                return 响应.status, None, f"响应超过读取上限 {响应上限字节} 字节"
            return 响应.status, json.loads(正文.decode("utf-8")), ""
    except urllib.error.HTTPError as 错误:
        try:
            return 错误.code, None, f"HTTP {错误.code}"
        finally:
            错误.close()
    except (urllib.error.URLError, TimeoutError, OSError) as 错误:
        return 0, None, str(错误)
    except UnicodeEncodeError as 错误:
        # 兜底：任何遗漏在请求头/URL 里的非 latin-1 字符都不得逃逸到调用方。
        return 400, None, f"出站请求含无法编码的字符：{错误}"
    except (json.JSONDecodeError, UnicodeDecodeError) as 错误:
        return 200, None, f"响应不是有效 JSON：{错误}"


def _错误响应(状态码: int, 说明: str) -> 结果:
    if 状态码 == 0:
        return _失败("提供者不可用", f"模型 HTTP Provider 不可用：{说明}", 可重试=True)
    if 状态码 in (408, 504):
        return _失败("超时", f"模型 HTTP 请求超时：{说明}", 可重试=True)
    if 状态码 == 429:
        return _失败("请求限流", f"模型 HTTP 请求被限流：{说明}", 可重试=True)
    if 状态码 in (401, 403):
        return _失败("认证失败", f"模型 HTTP 认证失败：{说明}")
    if 状态码 == 404:
        return _失败("端点不存在", f"模型 HTTP 端点不存在：{说明}")
    return _失败("模型调用失败", f"模型 HTTP 返回 {状态码 or '未知状态'}：{说明}", 可重试=状态码 >= 500)


def _消息列表(消息: list[dict[str, Any]], 系统提示词: str | None) -> list[dict[str, Any]]:
    结果列表 = []
    if 系统提示词:
        结果列表.append({"role": "system", "content": 系统提示词})
    for 项 in 消息:
        角色 = str(项.get("role") or 项.get("角色") or "user")
        内容 = 项.get("content", 项.get("内容处理", 项.get("内容", "")))
        结果列表.append({"role": 角色, "content": 内容})
    return 结果列表


def _anthropic工具列表(工具列表: list) -> tuple[list[dict[str, Any]], str]:
    """把工具声明转成 anthropic 形态：{name, description, input_schema}。

    兼容两种入参形态：OpenAI 形态（type=function + function.{name,parameters}）
    与 anthropic 原生形态（直接含 input_schema）。工具名按协议规范前置校验，
    非法名（如中文名）在本层拒绝，不把必然被上游拒绝的请求发出去。
    """
    结果列表: list[dict[str, Any]] = []
    for 项 in 工具列表:
        if not isinstance(项, dict):
            return [], "工具列表每一项都必须是字典型"
        函数 = 项.get("function") if isinstance(项.get("function"), dict) else None
        名称 = str((函数 or 项).get("name") or "")
        说明 = (函数 or 项).get("description")
        参数 = (函数 or 项).get("parameters") or 项.get("input_schema") or {"type": "object", "properties": {}}
        if not anthropic工具名规范.match(名称):
            return [], f"anthropic 协议的工具名必须匹配 {anthropic工具名规范.pattern}，收到：{名称!r}"
        条目: dict[str, Any] = {"name": 名称, "input_schema": 参数 if isinstance(参数, dict) else {}}
        if isinstance(说明, str) and 说明:
            条目["description"] = 说明
        结果列表.append(条目)
    return 结果列表, ""


def _anthropic消息(消息列表: list, 系统提示词: str | None) -> list[dict[str, Any]]:
    """构造 anthropic messages：只保留 user/assistant，system 由调用方放顶层。"""
    结果列表: list[dict[str, Any]] = []
    for 项 in 消息列表:
        角色 = str(项.get("role") or 项.get("角色") or "user")
        if 角色 == "system":
            # anthropic 不接受 messages 里的 system 角色；调用方负责顶层 system。
            continue
        内容 = 项.get("content", 项.get("内容处理", 项.get("内容", "")))
        结果列表.append({"role": 角色, "content": 内容})
    return 结果列表


def 构造anthropic载荷(配置: dict[str, Any], 消息列表: list, 系统提示词: str | None, *,
                 流式: bool, 温度: float | None, 最大令牌数: int | None,
                 工具: list | None, 响应格式: dict | None) -> tuple[dict[str, Any] | None, str]:
    """按 anthropic Messages 协议构造出站载荷；返回 (载荷, 错误说明)。

    这是 anthropic 载荷的唯一实现：适配层两条调用路径（流式/非流式）与连接器
    `_HTTP调用模型` 都复用它，避免同一协议映射在多处各写一套而漂移。
    """
    if 响应格式:
        # anthropic 无 response_format 语义；静默丢弃会让调用方误以为生效。
        return None, "anthropic 协议不支持 响应格式，请改用 chat_completions 或 codex_responses"
    工具表, 工具错误 = _anthropic工具列表(工具 or [])
    if 工具错误:
        return None, 工具错误
    载荷: dict[str, Any] = {
        "model": 配置.get("模型名", ""),
        # max_tokens 在 anthropic 是必填项；未指定时用协议默认值，保证请求合法。
        "max_tokens": 最大令牌数 if 最大令牌数 is not None else anthropic默认最大令牌数,
        "messages": _anthropic消息(消息列表, 系统提示词),
    }
    if 系统提示词:
        载荷["system"] = 系统提示词
    if 温度 is not None:
        载荷["temperature"] = 温度
    if 工具表:
        载荷["tools"] = 工具表
    if 流式:
        载荷["stream"] = True
    return 载荷, ""


def _文本(数据: dict[str, Any]) -> str:
    if isinstance(数据.get("output_text"), str):
        return 数据["output_text"]
    # anthropic Messages：顶层 content[] 块数组，文本块是 {type:text,text}
    块列表 = 数据.get("content")
    if isinstance(块列表, list) and not 数据.get("choices"):
        return "".join(
            str(块.get("text", "")) for 块 in 块列表
            if isinstance(块, dict) and 块.get("type") == "text"
        )
    选择 = (数据.get("choices") or [{}])[0]
    消息 = 选择.get("message") or 选择.get("delta") or {}
    内容 = 消息.get("content", "")
    if isinstance(内容, list):
        内容 = "".join(str(项.get("text", "")) for 项 in 内容 if isinstance(项, dict))
    if 内容:
        return str(内容)
    for 输出 in 数据.get("output") or []:
        for 项 in 输出.get("content") or []:
            if isinstance(项, dict) and 项.get("text"):
                return str(项["text"])
    return ""




def _流式错误(错误码: str, 错误说明: str, *, 可重试: bool = False,
           **详情: Any) -> dict[str, Any]:
    事件: dict[str, Any] = {
        "类型": "错误", "错误码": 错误码, "错误说明": 错误说明,
        "可重试": 可重试,
    }
    事件.update(详情)
    return 事件


def _流式完成(完成原因: str, 用量: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "类型": "完成", "文本": "", "完成原因": 完成原因,
        "用量": 用量 if isinstance(用量, dict) else {},
    }


def _流式读取超时(响应: Any, 秒: float) -> None:
    """把本次读取的 socket 空闲超时收紧到总截止时间，尽量避免阻塞超出预算。"""
    try:
        套接字 = 响应.fp.raw._sock
        套接字.settimeout(max(0.001, 秒))
    except (AttributeError, OSError):
        # urllib 的底层对象在不同 Python 版本可能没有公开 socket 路径；
        # opener.open 的 timeout 仍提供空闲读取上限。
        pass


def _流式事件内容(数据: dict[str, Any], 协议: str) -> tuple[str, str | None, dict[str, Any]]:
    """提取单个已解码 SSE JSON 的文本、完成原因和用量。"""
    if isinstance(数据.get("error"), dict):
        错误 = 数据["error"]
        raise ValueError(f"上游错误：{错误.get('message') or 错误}")  # noqa: TRY004
    类型 = 数据.get("type")
    if 协议 == "anthropic_messages":
        # anthropic SSE：事件名在 data.type 上（event: 行由读取层忽略）。
        # 文本增量在 content_block_delta.delta.text；完成原因在 message_delta.delta.stop_reason；
        # message_stop 是终态；message_start/content_block_start/content_block_stop/ping 是结构事件。
        if 类型 == "error":
            错误 = 数据.get("error") or {}
            raise ValueError(f"上游错误：{错误.get('message') or 错误 or 'anthropic 流式错误'}")
        if 类型 == "content_block_delta":
            增量对象 = 数据.get("delta") or {}
            if not isinstance(增量对象, dict):
                raise TypeError("anthropic 流式 delta 必须是对象")
            增量类型 = 增量对象.get("type")
            if 增量类型 == "text_delta":
                文本 = 增量对象.get("text", "")
                if not isinstance(文本, str):
                    raise TypeError("anthropic text_delta.text 必须是字符串")
                return 文本, None, {}
            # thinking_delta / input_json_delta 等不产生可见文本增量，跳过。
            return "", None, {}
        if 类型 == "message_delta":
            增量对象 = 数据.get("delta") or {}
            原始原因 = 增量对象.get("stop_reason") if isinstance(增量对象, dict) else None
            用量 = 数据.get("usage") if isinstance(数据.get("usage"), dict) else {}
            原因 = anthropic完成原因表.get(str(原始原因)) if 原始原因 else None
            return "", 原因, 用量 or {}
        if 类型 == "message_stop":
            return "", "stop", {}
        if 类型 in {"message_start", "content_block_start", "content_block_stop", "ping"}:
            return "", None, {}
        raise LookupError(f"未知 anthropic SSE 事件类型：{类型!r}")
    if 协议 == "codex_responses":
        if 类型 == "response.error":
            错误 = 数据.get("error") or {}
            raise ValueError(f"上游错误：{错误.get('message') or 错误}")
        if 类型 in {
            "response.created",
            "response.in_progress",
            "response.output_item.added",
            "response.content_part.added",
            "response.output_text.done",
            "response.content_part.done",
            "response.output_item.done",
        }:
            # Responses 生命周期事件只表示状态推进，不产生文本增量；
            # 必须跳过而不是误判为畸形，终态仍由 response.completed 处理。
            return "", None, {}
        if 类型 in {"response.failed", "response.incomplete"}:
            响应 = 数据.get("response") or {}
            错误 = 响应.get("error") if isinstance(响应, dict) else None
            raise ValueError(f"上游错误：{(错误 or {}).get('message') or 类型}")
        if 类型 == "response.output_text.delta":
            增量 = 数据.get("delta", "")
            if not isinstance(增量, str):
                raise TypeError("Responses 增量 delta 必须是字符串")
            return 增量, None, {}
        if 类型 == "response.completed":
            回复 = 数据.get("response") or {}
            用量 = 回复.get("usage") if isinstance(回复, dict) else {}
            return "", "completed", 用量 if isinstance(用量, dict) else {}
        raise LookupError(f"未知 Responses SSE 事件类型：{类型!r}")

    选择列表 = 数据.get("choices")
    if not isinstance(选择列表, list) or not 选择列表 or not isinstance(选择列表[0], dict):
        raise LookupError("Chat SSE 缺少 choices")
    选择 = 选择列表[0]
    完成原因 = 选择.get("finish_reason")
    增量对象 = 选择.get("delta") or 选择.get("message") or {}
    if not isinstance(增量对象, dict):
        raise TypeError("Chat SSE 的 delta/message 必须是对象")
    增量 = 增量对象.get("content", "")
    if isinstance(增量, list):
        增量 = "".join(
            str(项.get("text", "")) for 项 in 增量 if isinstance(项, dict)
        )
    if not isinstance(增量, str):
        raise TypeError("Chat SSE 的 content 必须是字符串或内容列表")
    用量 = 数据.get("usage")
    return 增量, 完成原因 if isinstance(完成原因, str) and 完成原因 else None, 用量 if isinstance(用量, dict) else {}


def _解析流式响应(响应: Any, 协议: str, *, 响应上限: int,
               事件上限: int, 事件数量上限: int, 超时时间: float) -> Iterator[dict[str, Any]]:
    """按 SSE 行和事件边界读取上游，不把整个响应当作 JSON。"""
    缓冲 = bytearray()
    数据行: list[bytes] = []
    总字节数 = 0
    事件字节数 = 0
    事件数量 = 0
    已完成 = False
    完成原因 = "stop"
    截止时间 = time.monotonic() + 超时时间

    def 错误(错误码: str, 说明: str, **详情: Any) -> dict[str, Any]:
        return _流式错误(错误码, 说明, **详情)

    def 处理事件() -> tuple[list[dict[str, Any]], bool]:
        nonlocal 数据行, 事件字节数, 事件数量, 已完成, 完成原因
        if not 数据行:
            事件字节数 = 0
            return [], False
        事件数量 += 1
        文本数据 = b"\n".join(数据行)
        数据行 = []
        事件字节数 = 0
        if 事件数量 > 事件数量上限:
            return [错误("事件数量超限", f"SSE 事件数量超过上限 {事件数量上限}",
                         上限数量=事件数量上限)], True
        try:
            文本 = 文本数据.decode("utf-8")
        except UnicodeDecodeError as 异常:
            return [错误("事件格式错误", f"SSE 数据不是 UTF-8：{异常}",
                         异常类型=type(异常).__name__)], True
        if 文本.strip() == "[DONE]":
            if 已完成:
                return [], False
            已完成 = True
            return [_流式完成(完成原因)], True
        try:
            数据 = json.loads(文本)
            if not isinstance(数据, dict):
                raise TypeError("SSE data 必须是 JSON 对象")
            增量, 原因, 用量 = _流式事件内容(数据, 协议)
        except ValueError as 异常:
            说明 = str(异常)
            if 说明.startswith("上游错误："):
                return [错误("上游错误", 说明.removeprefix("上游错误："),
                             异常类型=type(异常).__name__)], True
            return [错误("事件格式错误", f"SSE JSON 无效：{说明}",
                         异常类型=type(异常).__name__)], True
        except (TypeError, LookupError, json.JSONDecodeError) as 异常:
            return [错误("事件格式错误", f"SSE 事件结构无效：{异常}",
                         异常类型=type(异常).__name__)], True
        结果: list[dict[str, Any]] = []
        if 增量:
            结果.append({"类型": "增量", "文本": 增量})
        if 原因 is not None:
            已完成 = True
            完成原因 = 原因
            结果.append(_流式完成(原因, 用量))
        elif 数据.get("type") == "response.completed":
            已完成 = True
            结果.append(_流式完成("completed", 用量))
        return 结果, bool(结果 and 已完成)

    while True:
        剩余时间 = 截止时间 - time.monotonic()
        if 剩余时间 <= 0:
            yield 错误("超时", f"上游 SSE 读取超过 {超时时间:g} 秒", 可重试=True)
            return
        _流式读取超时(响应, 剩余时间)
        try:
            块 = 响应.read(流式读取块大小)
        except TimeoutError as 异常:
            yield 错误("超时", f"上游 SSE 读取超时：{异常 or '读取超时'}",
                       可重试=True, 异常类型=type(异常).__name__)
            return
        except (OSError, urllib.error.URLError) as 异常:
            yield 错误("上游断开", f"上游 SSE 读取中断：{异常}",
                       可重试=True, 异常类型=type(异常).__name__)
            return
        if not 块:
            break
        总字节数 += len(块)
        if 总字节数 > 响应上限:
            yield 错误("响应超限", f"SSE 响应超过读取上限 {响应上限} 字节",
                       上限字节=响应上限)
            return
        缓冲.extend(块)
        while b"\n" in 缓冲:
            行, _, 剩余 = 缓冲.partition(b"\n")
            缓冲 = bytearray(剩余)
            if 行.endswith(b"\r"):
                行 = 行[:-1]
            if not 行:
                事件, 终止 = 处理事件()
                yield from 事件
                if 终止:
                    return
                continue
            if 行.startswith(b":"):
                continue
            if 行.startswith(b"data:"):
                内容 = 行[5:]
                if 内容.startswith(b" "):
                    内容 = 内容[1:]
                事件字节数 += len(内容)
                if 事件字节数 > 事件上限:
                    yield 错误("事件超限", f"单个 SSE 事件超过上限 {事件上限} 字节",
                               上限字节=事件上限)
                    return
                数据行.append(bytes(内容))
                continue
            if 行.startswith((b"event:", b"id:", b"retry:")):
                continue
            yield 错误("事件格式错误", "SSE 含有无法识别的字段",
                       字段=行[:64].decode("ascii", errors="replace"))
            return
    if 缓冲.strip() or 数据行:
        if 缓冲.strip():
            yield 错误("事件格式错误", "SSE 响应以未结束的事件行结尾")
            return
        事件, 终止 = 处理事件()
        yield from 事件
        if 终止:
            return
    if not 已完成:
        yield 错误("上游断开", "上游 SSE 在完成事件前断开", 可重试=True)


def 流式调用对话(*, 配置: dict[str, Any], 消息列表: list,
             系统提示词: str | None = None,
             温度: float | None = None, 最大令牌数: int | None = None,
             工具: list | None = None, 响应格式: dict | None = None,
             附加请求头: dict[str, Any] | None = None) -> Iterator[dict[str, Any]]:
    """读取模型 Provider SSE；调用方必须消费或显式 close 返回的有限迭代器。

    生成参数 `温度/最大令牌数/工具/响应格式` 与 `调用对话` 同一套校验与协议映射表，
    不传则载荷里不出现对应键（与迁移前行为逐字节一致）。
    """
    if not isinstance(消息列表, list) or not 消息列表:
        return iter((_流式错误("参数不合法", "消息列表必须是非空列表"),))
    if 温度 is not None and (isinstance(温度, bool) or not isinstance(温度, (int, float))):
        return iter((_流式错误("参数不合法", "温度必须是数值"),))
    if 最大令牌数 is not None and (isinstance(最大令牌数, bool) or not isinstance(最大令牌数, int)):
        return iter((_流式错误("参数不合法", "最大令牌数必须是整数"),))
    if 工具 is not None and not isinstance(工具, list):
        return iter((_流式错误("参数不合法", "工具必须是列表"),))
    if 响应格式 is not None and not isinstance(响应格式, dict):
        return iter((_流式错误("参数不合法", "响应格式必须是字典型"),))
    协议 = _规范化协议(配置.get("协议", 默认协议))
    if 协议 is None:
        return iter((_流式错误("参数不合法", 协议取值说明),))
    try:
        超时时间 = float(配置.get("请求超时秒") or 120)
        响应上限 = int(配置.get("流式响应上限字节") or 流式响应上限字节)
        事件上限 = int(配置.get("流式事件上限字节") or 流式事件上限字节)
        数量上限 = int(配置.get("流式事件数量上限") or 流式事件数量上限)
    except (TypeError, ValueError):
        return iter((_流式错误("参数不合法", "流式超时和响应上限必须是正数"),))
    if 超时时间 <= 0 or 响应上限 <= 0 or 事件上限 <= 0 or 数量上限 <= 0:
        return iter((_流式错误("参数不合法", "流式超时和响应上限必须是正数"),))
    if 协议 == "anthropic_messages":
        地址 = 归一模型端点(配置, "/messages")
    elif 协议 == "codex_responses":
        地址 = 归一模型端点(配置, "/responses")
    else:
        地址 = 归一模型端点(配置, "/chat/completions")
    if not 地址:
        return iter((_流式错误("提供者不可用", "未配置模型 HTTP 地址", 可重试=True),))
    if 协议 == "anthropic_messages":
        载荷, 载荷错误 = 构造anthropic载荷(
            配置, 消息列表, 系统提示词, 流式=True,
            温度=温度, 最大令牌数=最大令牌数, 工具=工具, 响应格式=响应格式,
        )
        if 载荷错误 or 载荷 is None:
            return iter((_流式错误("参数不合法", 载荷错误 or "参数不合法"),))
    else:
        消息 = _消息列表(消息列表, 系统提示词)
        if 协议 == "codex_responses":
            载荷 = {"model": 配置.get("模型名", ""), "input": 消息, "stream": True}
            令牌键 = "max_output_tokens"
            if 响应格式:
                载荷["text"] = {"format": 响应格式}
        else:
            # chat 协议流式默认不回传 usage；显式索取，用量追踪才有数（与迁移前 V3 实现一致）。
            # codex/responses 协议自带用量，不加此键。
            载荷 = {"model": 配置.get("模型名", ""), "messages": 消息, "stream": True,
                    "stream_options": {"include_usage": True}}
            令牌键 = "max_tokens"
            if 响应格式:
                载荷["response_format"] = 响应格式
        # 生成参数按 `调用对话` 同一张映射表落地；None/空即不写入，保证不传时载荷不变。
        if 温度 is not None:
            载荷["temperature"] = 温度
        if 最大令牌数 is not None:
            载荷[令牌键] = 最大令牌数
        if 工具:
            载荷["tools"] = 工具
    请求头 = {"Content-Type": "application/json", "Accept": "text/event-stream"}
    if 配置.get("api_key"):
        if 协议 == "anthropic_messages":
            请求头["x-api-key"] = str(配置["api_key"])
            请求头["anthropic-version"] = anthropic协议版本
        else:
            请求头["Authorization"] = f"Bearer {配置['api_key']}"
    if isinstance(配置.get("额外请求头"), dict):
        请求头.update(配置["额外请求头"])
    if isinstance(附加请求头, dict):
        请求头.update(附加请求头)
    请求 = urllib.request.Request(
        地址, data=json.dumps(载荷, ensure_ascii=False).encode("utf-8"),
        headers=请求头, method="POST",
    )

    def 读取() -> Iterator[dict[str, Any]]:
        try:
            开放器 = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            with 开放器.open(请求, timeout=超时时间) as 响应:
                if 响应.status >= 400:
                    yield _流式错误(
                        "上游错误", f"模型 HTTP 返回 {响应.status}",
                        状态码=响应.status, 可重试=响应.status >= 500,
                    )
                    return
                yield from _解析流式响应(
                    响应, 协议, 响应上限=响应上限, 事件上限=事件上限,
                    事件数量上限=数量上限, 超时时间=超时时间,
                )
        except urllib.error.HTTPError as 异常:
            异常.close()
            yield _流式错误(
                "认证失败" if 异常.code in (401, 403) else "上游错误",
                f"模型 HTTP 返回 {异常.code}", 状态码=异常.code,
                可重试=异常.code >= 500, 异常类型=type(异常).__name__,
            )
        except TimeoutError as 异常:
            yield _流式错误("超时", f"模型 HTTP 请求超时：{异常 or '请求超时'}",
                           可重试=True, 异常类型=type(异常).__name__)
        except (urllib.error.URLError, OSError) as 异常:
            yield _流式错误("提供者不可用", f"模型 HTTP Provider 不可用：{异常}",
                           可重试=True, 异常类型=type(异常).__name__)

    return 读取()


def _归一化响应(数据: dict[str, Any]) -> dict[str, Any]:
    """复用连接器公开的响应归一化（延迟导入避免环形依赖）；失败返回空结构。"""
    try:
        from 支持库.后端.大语言模型支持库.模型连接器 import 归一化对话响应

        归一结果 = 归一化对话响应(数据, True)
    except Exception:
        return {}
    值 = getattr(归一结果, "值", None)
    return 值 if isinstance(值, dict) else {}


def 调用对话(*, 配置: dict[str, Any], 消息列表: list,
           系统提示词: str | None = None, 流式输出: bool = False,
           温度: float | None = None, 最大令牌数: int | None = None,
           工具: list | None = None, 响应格式: dict | None = None,
           附加请求头: dict[str, Any] | None = None) -> 结果:
    """与连接器 `_HTTP调用模型` 同一协议契约：生成参数按协议映射，响应统一归一化。"""
    if not isinstance(消息列表, list) or not 消息列表:
        return _失败("参数不合法", "消息列表必须是非空列表")
    if 流式输出 is True:
        return _失败(
            "流式能力未装配",
            "流式输出已请求，但40007网关尚未装配模型SSE传输，待补网关流；未伪造完成结果",
            详情={"流式输出": True, "协议": 配置.get("协议", "chat_completions"), "网关": "40007"},
        )
    if not isinstance(流式输出, bool):
        return _失败("参数不合法", "流式输出必须是逻辑型")
    if 温度 is not None and (isinstance(温度, bool) or not isinstance(温度, (int, float))):
        return _失败("参数不合法", "温度必须是数值")
    if 最大令牌数 is not None and (isinstance(最大令牌数, bool) or not isinstance(最大令牌数, int)):
        return _失败("参数不合法", "最大令牌数必须是整数")
    if 工具 is not None and not isinstance(工具, list):
        return _失败("参数不合法", "工具必须是列表")
    if 响应格式 is not None and not isinstance(响应格式, dict):
        return _失败("参数不合法", "响应格式必须是字典型")
    协议 = _规范化协议(配置.get("协议", 默认协议))
    if 协议 is None:
        return _失败("参数不合法", 协议取值说明)
    if 协议 == "anthropic_messages":
        路径 = "/messages"
        载荷, 载荷错误 = 构造anthropic载荷(
            配置, 消息列表, 系统提示词, 流式=False,
            温度=温度, 最大令牌数=最大令牌数, 工具=工具, 响应格式=响应格式,
        )
        if 载荷错误 or 载荷 is None:
            return _失败("参数不合法", 载荷错误 or "参数不合法")
    else:
        消息 = _消息列表(消息列表, 系统提示词)
        if 协议 == "codex_responses":
            路径, 载荷 = "/responses", {"model": 配置.get("模型名", ""), "input": 消息, "stream": False}
            令牌键 = "max_output_tokens"
            if 响应格式:
                载荷["text"] = {"format": 响应格式}
        else:
            路径, 载荷 = "/chat/completions", {"model": 配置.get("模型名", ""), "messages": 消息, "stream": False}
            令牌键 = "max_tokens"
            if 响应格式:
                载荷["response_format"] = 响应格式
        if 温度 is not None:
            载荷["temperature"] = 温度
        if 最大令牌数 is not None:
            载荷[令牌键] = 最大令牌数
        if 工具:
            载荷["tools"] = 工具
    状态码, 数据, 说明 = _请求(配置, 路径, 载荷, 附加请求头, 协议=协议)
    if 状态码 >= 400 or not 数据:
        return _错误响应(状态码, 说明)
    归一 = _归一化响应(数据)
    回复 = str(归一.get("内容") or _文本(数据) or "")
    if not 回复 and not 归一.get("工具调用"):
        return _失败("模型调用失败", "模型响应既没有可用文本也没有工具调用")
    return 结果.成功结果({
        "回复": 回复, "用量": 数据.get("usage") or {},
        "内容": 归一.get("内容", ""), "思考": 归一.get("思考", ""),
        "工具调用": 归一.get("工具调用", []),
        "结束原因": str(归一.get("结束原因") or "stop"),
    })


def 调用嵌入(*, 配置: dict[str, Any], 文本: str) -> 结果:
    if not isinstance(文本, str) or not 文本.strip():
        return _失败("参数不合法", "文本必须是非空字符串")
    状态码, 数据, 说明 = _请求(配置, "/embeddings", {"model": 配置.get("模型名", ""), "input": [文本]})
    if 状态码 >= 400 or not 数据:
        return _错误响应(状态码, 说明)
    数据列表 = 数据.get("data") or []
    向量 = 数据列表[0].get("embedding") if 数据列表 and isinstance(数据列表[0], dict) else None
    if not isinstance(向量, list) or not 向量:
        return _失败("模型调用失败", "嵌入响应没有有效向量")
    return 结果.成功结果({"向量": 向量, "维度": len(向量)})


def 调用重排(*, 配置: dict[str, Any], 查询: str, 文档列表: list) -> 结果:
    if not isinstance(查询, str) or not 查询.strip() or not isinstance(文档列表, list) or not 文档列表:
        return _失败("参数不合法", "查询必须非空且文档列表必须是非空列表")
    载荷 = {"model": 配置.get("模型名", ""), "query": 查询, "documents": 文档列表}
    状态码, 数据, 说明 = _请求(配置, "/rerank", 载荷)
    if 状态码 >= 400 or not 数据:
        return _错误响应(状态码, 说明)
    结果列表 = 数据.get("results") or 数据.get("data") or []
    return 结果.成功结果({"重排结果": 结果列表})


def 注册模型HTTP提供者() -> None:
    """把同一 HTTP Provider 注册到三类模型的本地/云端路径。"""
    from 支持库.后端.大语言模型支持库.模型连接器 import 注册调用器

    for 连接类型, 调用函数 in (("LLM", 调用对话), ("向量", 调用嵌入), ("重排", 调用重排)):
        注册调用器(连接类型, "本地", 调用函数)
        注册调用器(连接类型, "云端", 调用函数)
