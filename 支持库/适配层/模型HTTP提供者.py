"""模型 HTTP Provider：统一承接 LLM、向量、重排的本地/云端兼容协议。"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

from 公共契约.基础类型.结果类型 import 结果

来源 = "模型HTTP提供者"


def _失败(错误码: str, 消息: str, *, 可重试: bool = False) -> 结果:
    return 结果.失败(错误码, 消息, 来源=来源, 可重试=可重试)


def _端点(配置: dict[str, Any], 后缀: str) -> str:
    地址 = str(配置.get("url") or "").strip().rstrip("/")
    if not 地址:
        return ""
    for 已有后缀 in ("/chat/completions", "/responses", "/embeddings", "/rerank"):
        if 地址.endswith(已有后缀):
            地址 = 地址[: -len(已有后缀)]
            break
    if not 地址.endswith("/v1"):
        地址 += "/v1"
    return 地址 + 后缀


def _请求(配置: dict[str, Any], 后缀: str, 载荷: dict[str, Any]) -> tuple[int, dict[str, Any] | None, str]:
    地址 = _端点(配置, 后缀)
    if not 地址:
        return 0, None, "未配置模型 HTTP 地址"
    请求头 = {"Content-Type": "application/json"}
    if 配置.get("api_key"):
        请求头["Authorization"] = f"Bearer {配置['api_key']}"
    请求 = urllib.request.Request(
        地址,
        data=json.dumps(载荷, ensure_ascii=False).encode("utf-8"),
        headers=请求头,
        method="POST",
    )
    try:
        开放器 = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with 开放器.open(请求, timeout=float(配置.get("请求超时秒") or 120)) as 响应:
            return 响应.status, json.loads(响应.read().decode("utf-8")), ""
    except urllib.error.HTTPError as 错误:
        return 错误.code, None, f"HTTP {错误.code}"
    except (urllib.error.URLError, TimeoutError, OSError) as 错误:
        return 0, None, str(错误)
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


def _文本(数据: dict[str, Any]) -> str:
    if isinstance(数据.get("output_text"), str):
        return 数据["output_text"]
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


def 调用对话(*, 配置: dict[str, Any], 消息列表: list, 系统提示词: str | None = None) -> 结果:
    if not isinstance(消息列表, list) or not 消息列表:
        return _失败("参数不合法", "消息列表必须是非空列表")
    载荷 = {"model": 配置.get("模型名", ""), "messages": _消息列表(消息列表, 系统提示词), "stream": False}
    状态码, 数据, 说明 = _请求(配置, "/chat/completions", 载荷)
    if 状态码 >= 400 or not 数据:
        return _错误响应(状态码, 说明)
    回复 = _文本(数据)
    if not 回复:
        return _失败("模型调用失败", "模型响应没有可用文本")
    return 结果.成功结果({"回复": 回复, "用量": 数据.get("usage") or {}})


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
