"""模型响应归一化：把 4 种协议（OpenAI / Anthropic / Gemini / 本地 llama-server）的
响应体与流式分块归一成平台统一形状。

**为什么单独成文件（2026-09-18 拆分）**：本段原属 `实现/模型连接器.py` 末尾，
自带完整边界（只依赖标准库 + 结果类型），与「句柄/连接/启动」三类职责无耦合。
拆出后该文件由 1667 行降到约 1440 行；**对外零变化** ——
`归一化对话响应` / `归一化流式分块` 仍在 `模型连接器.py` 里 re-export（见该文件尾部），
`__init__.py` 的导入路径不变。
"""

from __future__ import annotations

from typing import Any

from 公共契约.基础类型.结果类型 import 结果

# ── 模型响应归一化（迁移自 V3 网关适配器；支持 4 种协议） ──────────────

_流事件类型_令牌 = "令牌"
_流事件类型_思考中 = "思考中"
_流事件类型_完成 = "完成"
_流事件类型_错误 = "错误"
_流事件类型_工具调用 = "工具调用"


def _归一化用量(原始数据: dict):
    """提取用量：兼容 prompt_tokens/completion_tokens 与 input_tokens/output_tokens 两套命名。"""
    用量数据 = 原始数据.get("usage")
    if not isinstance(用量数据, dict):
        return None
    输入令牌 = 用量数据.get("prompt_tokens") or 用量数据.get("input_tokens") or 0
    输出令牌 = 用量数据.get("completion_tokens") or 用量数据.get("output_tokens") or 0
    if isinstance(输入令牌, bool) or isinstance(输出令牌, bool):
        return None
    if not isinstance(输入令牌, int) or not isinstance(输出令牌, int):
        return None
    if 输入令牌 <= 0 and 输出令牌 <= 0:
        return None
    return {"提示词令牌数": 输入令牌, "补全令牌数": 输出令牌, "总令牌数": 输入令牌 + 输出令牌}


def _归一化工具调用(消息: dict) -> list:
    """把 message.tool_calls 归一化：arguments 字符串 JSON 解析为对象。"""
    import json as _json
    结果 = []
    for 调用 in (消息 or {}).get("tool_calls") or []:
        if not isinstance(调用, dict):
            continue
        函数 = 调用.get("function") or {}
        参数 = 函数.get("arguments", {})
        if isinstance(参数, str):
            try:
                参数 = _json.loads(参数)
            except Exception:
                参数 = {}
        结果.append({"id": 调用.get("id", ""), "type": "function",
                     "function": {"name": 函数.get("name", ""), "arguments": 参数}})
    return 结果


def _归一化响应体(原始数据: dict, 包含思考: bool) -> dict:
    """把 4 种协议的原始响应归一化成统一结构。"""
    用量 = _归一化用量(原始数据)

    # ① codex_responses：object=response 或 output 是列表
    if 原始数据.get("object") == "response" or isinstance(原始数据.get("output"), list):
        内容片段, 思考片段 = [], []
        for 条目 in 原始数据.get("output") or []:
            if not isinstance(条目, dict):
                continue
            条目类型 = 条目.get("type")
            if 条目类型 == "reasoning" and 包含思考:
                for 摘要 in 条目.get("summary") or []:
                    if isinstance(摘要, dict) and 摘要.get("text"):
                        思考片段.append(str(摘要["text"]))
                continue
            if 条目类型 != "message":
                continue
            for 片段 in 条目.get("content") or []:
                if not isinstance(片段, dict):
                    continue
                if 片段.get("type") in {"output_text", "text"} and 片段.get("text") is not None:
                    内容片段.append(str(片段["text"]))
        结束原因 = "stop"
        if 原始数据.get("status") and 原始数据.get("status") != "completed":
            结束原因 = str(原始数据.get("status"))
        return {"内容": "\n".join(x for x in 内容片段 if x),
                "思考": "\n".join(x for x in 思考片段 if x),
                "工具调用": [], "结束原因": 结束原因, "用量": 用量}

    # ② anthropic：content[] 是块数组
    if isinstance(原始数据.get("content"), list) and not 原始数据.get("choices"):
        内容片段, 思考片段, 工具调用 = [], [], []
        for 块 in 原始数据.get("content") or []:
            if not isinstance(块, dict):
                continue
            块类型 = 块.get("type")
            if 块类型 == "text" and 块.get("text") is not None:
                内容片段.append(str(块["text"]))
            elif 块类型 == "thinking" and 包含思考 and 块.get("thinking"):
                思考片段.append(str(块["thinking"]))
            elif 块类型 == "tool_use":
                工具调用.append({"id": 块.get("id", ""), "type": "function",
                                 "function": {"name": 块.get("name", ""),
                                              "arguments": 块.get("input") or {}}})
        停止原因 = 原始数据.get("stop_reason") or "stop"
        return {"内容": "".join(内容片段),
                "思考": "\n".join(x for x in 思考片段 if x),
                "工具调用": 工具调用,
                "结束原因": "tool_calls" if 停止原因 == "tool_use" else "stop",
                "用量": 用量}

    # ③ ollama：message.content
    if isinstance(原始数据.get("message"), dict) and not 原始数据.get("choices"):
        消息 = 原始数据.get("message") or {}
        return {"内容": str(消息.get("content") or ""),
                "思考": str(消息.get("reasoning_content") or "") if 包含思考 else "",
                "工具调用": _归一化工具调用({"tool_calls": 消息.get("tool_calls")}),
                "结束原因": str(原始数据.get("done_reason") or "stop"), "用量": 用量}

    # ④ chat_completions：choices[0].message
    选项列表 = 原始数据.get("choices") or []
    选项 = 选项列表[0] if 选项列表 and isinstance(选项列表[0], dict) else {}
    消息 = 选项.get("message") or {}
    return {"内容": str(消息.get("content") or ""),
            "思考": str(消息.get("reasoning_content") or "") if 包含思考 else "",
            "工具调用": _归一化工具调用(消息),
            "结束原因": str(选项.get("finish_reason") or "stop"),
            "用量": 用量}


def 归一化对话响应(原始数据: dict = None, 包含思考: bool = False) -> 结果:
    """把模型原始响应归一化为统一结构。

    支持 4 种协议，按响应形状自动判别：
    - codex_responses（object=response 或 output 是列表）
    - anthropic（content[] 块数组）
    - ollama（message.content）
    - chat_completions（choices[0].message）

    返回 {内容, 思考, 工具调用, 结束原因, 用量}；纯计算、无状态。
    """
    if not isinstance(原始数据, dict):
        return _失败("参数不合法", "原始数据必须是字典型")
    if not isinstance(包含思考, bool):
        return _失败("参数不合法", "包含思考必须是逻辑型")
    try:
        return 结果.成功结果(_归一化响应体(原始数据, 包含思考))
    except Exception as 错误:
        return _失败("归一化失败", f"响应形状无法识别: {错误}")


def _归一化分块体(分块: dict, 包含思考: bool):
    """把流式单块归一化成统一事件；结构事件返回 None（跳过）。"""
    类型 = 分块.get("type")

    # ① codex_responses 流式：response.* 事件
    if isinstance(类型, str) and 类型.startswith("response."):
        if 类型 == "response.output_text.delta":
            增量 = 分块.get("delta")
            return {"类型": _流事件类型_令牌, "内容": str(增量), "工具调用": [], "用量": None} if 增量 else None
        if 类型 == "response.reasoning_summary_text.delta":
            if 包含思考 and 分块.get("delta"):
                return {"类型": _流事件类型_思考中, "内容": str(分块["delta"]), "工具调用": [], "用量": None}
            return None
        if 类型 == "response.completed":
            响应 = 分块.get("response") or {}
            return {"类型": _流事件类型_完成, "内容": "", "工具调用": [],
                    "用量": _归一化用量(响应) or _归一化用量(分块)}
        if 类型 in {"response.failed", "response.incomplete"}:
            响应 = 分块.get("response") or {}
            错误 = 响应.get("error") or 分块.get("error") or 类型
            return {"类型": _流事件类型_错误, "内容": str(错误), "工具调用": [], "用量": None}
        return None

    # ② anthropic 流式：content_block_delta / message_delta / message_stop / error
    if 类型 in {"content_block_delta", "message_delta", "message_stop", "message_start",
                "content_block_start", "content_block_stop", "ping", "error"}:
        if 类型 == "content_block_delta":
            增量 = 分块.get("delta") or {}
            增量类型 = 增量.get("type")
            if 增量类型 == "text_delta" and 增量.get("text"):
                return {"类型": _流事件类型_令牌, "内容": str(增量["text"]), "工具调用": [], "用量": None}
            if 增量类型 == "thinking_delta" and 包含思考 and 增量.get("thinking"):
                return {"类型": _流事件类型_思考中, "内容": str(增量["thinking"]), "工具调用": [], "用量": None}
            return None
        if 类型 in {"message_delta", "message_stop"}:
            return {"类型": _流事件类型_完成, "内容": "", "工具调用": [], "用量": _归一化用量(分块)}
        if 类型 == "error":
            错误 = 分块.get("error") or {}
            return {"类型": _流事件类型_错误,
                    "内容": str(错误.get("message") or 错误 or "anthropic 流式错误"),
                    "工具调用": [], "用量": None}
        return None

    # ③ ollama 流式
    if 分块.get("done") and not 分块.get("choices"):
        return {"类型": _流事件类型_完成, "内容": "", "工具调用": [], "用量": _归一化用量(分块)}
    if isinstance(分块.get("message"), dict) and not 分块.get("choices"):
        消息 = 分块.get("message") or {}
        工具调用 = _归一化工具调用({"tool_calls": 消息.get("tool_calls")})
        if 工具调用:
            return {"类型": _流事件类型_工具调用, "内容": "", "工具调用": 工具调用, "用量": None}
        思考 = 消息.get("reasoning_content") or ""
        if 包含思考 and 思考:
            return {"类型": _流事件类型_思考中, "内容": str(思考), "工具调用": [], "用量": None}
        if 消息.get("content"):
            return {"类型": _流事件类型_令牌, "内容": str(消息["content"]), "工具调用": [], "用量": None}
        return None

    # ④ chat_completions 流式
    选项列表 = 分块.get("choices") or []
    选项 = 选项列表[0] if 选项列表 and isinstance(选项列表[0], dict) else {}
    增量 = 选项.get("delta") or {}
    if 增量.get("tool_calls"):
        return None
    if 选项.get("finish_reason"):
        return {"类型": _流事件类型_完成, "内容": "", "工具调用": [], "用量": _归一化用量(分块)}
    思考 = 增量.get("reasoning_content") or ""
    if 包含思考 and 思考:
        return {"类型": _流事件类型_思考中, "内容": str(思考), "工具调用": [], "用量": None}
    if 增量.get("content"):
        return {"类型": _流事件类型_令牌, "内容": str(增量["content"]), "工具调用": [], "用量": None}
    return None


def 归一化流式分块(分块: dict = None, 包含思考: bool = False) -> 结果:
    """把模型流式单块归一化为统一事件。

    返回 {类型, 内容, 工具调用, 用量}；结构事件（心跳/开始/结束标记等）
    归一化为 {"类型": "跳过"}，调用方应丢弃。纯计算、无状态。
    """
    if not isinstance(分块, dict):
        return _失败("参数不合法", "分块必须是字典型")
    if not isinstance(包含思考, bool):
        return _失败("参数不合法", "包含思考必须是逻辑型")
    try:
        事件 = _归一化分块体(分块, 包含思考)
    except Exception as 错误:
        return _失败("归一化失败", f"分块形状无法识别: {错误}")
    if 事件 is None:
        return 结果.成功结果({"类型": "跳过", "内容": "", "工具调用": [], "用量": None})
    return 结果.成功结果(事件)
