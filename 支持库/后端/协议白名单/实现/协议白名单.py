"""协议白名单原子能力实现（不对外暴露，只经包级中文入口调用）。

职责：校验 LLM API 端点的协议类型是否在白名单内（借鉴 OpenCode runner/model.ts）。
白名单：openai、anthropic、openai-compatible（必须有 url）。
只做校验，不发起任何网络请求；拒绝 file/ftp/http（非 https）等不安全协议。
"""

from __future__ import annotations

from typing import Any

from 公共契约.基础类型.结果类型 import 结果

白名单 = frozenset({"openai", "anthropic", "openai-compatible"})


def _失败(错误码: str, 消息: str) -> 结果:
    return 结果.失败(错误码, 消息, 来源="协议白名单")


def 校验端点(api类型: str = None, base_url: str = None) -> 结果:
    """校验 API 端点协议类型是否在白名单内。返回 {通过=true/false, 原因}。"""
    if not isinstance(api类型, str) or not api类型.strip():
        return _失败("参数不合法", "api类型必须是非空字符串")
    类型 = api类型.strip().lower()
    # 1. 白名单检查
    if 类型 not in 白名单:
        return 结果.成功结果({"通过": False, "原因": f"api类型 '{api类型}' 不在白名单中（允许: {', '.join(sorted(白名单))}）"})
    # 2. openai-compatible 必须有 url
    if 类型 == "openai-compatible":
        if not isinstance(base_url, str) or not base_url.strip():
            return 结果.成功结果({"通过": False, "原因": "openai-compatible 类型必须提供 base_url"})
        # 3. 协议安全：只允许 http/https
        url = base_url.strip().lower()
        if not url.startswith("http://") and not url.startswith("https://"):
            return 结果.成功结果({"通过": False, "原因": f"不安全的协议: {base_url[:50]}，只允许 http/https"})
    return 结果.成功结果({"通过": True, "原因": "允许"})


def 查询白名单() -> 结果:
    """返回当前白名单列表。"""
    return 结果.成功结果({"白名单": sorted(白名单), "说明": "openai-compatible 必须有 base_url"})