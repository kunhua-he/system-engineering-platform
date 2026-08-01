"""脱敏工具：日志与诊断输出前的敏感信息脱敏。

规则：密码/令牌/私钥/密钥 等敏感参数值替换为 已脱敏；大文本只保留
摘要（前 100 字符 + 长度标记）；错误说明中的疑似密钥片段替换。
"""

from __future__ import annotations

import re
from typing import Any

from 支持库.适配层.脱敏模式 import 密钥片段模式

敏感关键词表 = ("密码", "口令", "令牌", "私钥", "密钥", "token", "secret", "password", "private_key")
摘要长度 = 100


def 脱敏文本(文本: str) -> str:
    """替换文本中的疑似密钥片段；大文本只保留摘要。"""
    if not 文本:
        return 文本
    文本 = 密钥片段模式.sub("已脱敏", 文本)
    if len(文本) > 摘要长度:
        return f"{文本[:摘要长度]}…（全文{len(文本)}字符，已截断）"
    return 文本


def 脱敏值(值: Any, 名称: str = "") -> Any:
    """按配置名或值特征脱敏单个值。"""
    if isinstance(值, str):
        是敏感名 = any(关键词 in 名称.lower() for 关键词 in 敏感关键词表)
        if 是敏感名:
            return "已脱敏"
        if 密钥片段模式.search(值):
            return 脱敏文本(值)
        if len(值) > 摘要长度:
            return f"{值[:摘要长度]}…（全文{len(值)}字符，已截断）"
        return 值
    if isinstance(值, dict):
        return {键: 脱敏值(子值, 键) for 键, 子值 in 值.items()}
    if isinstance(值, (list, tuple)):
        return [脱敏值(子值, 名称) for 子值 in 值]
    return 值


def 脱敏事件字典(事件字典: dict[str, Any]) -> dict[str, Any]:
    """对事件字典做整条脱敏（错误说明/依赖摘要等文本字段）。"""
    输出 = dict(事件字典)
    for 字段 in ("错误说明", "操作名称", "依赖摘要", "配置来源"):
        if isinstance(输出.get(字段), str):
            输出[字段] = 脱敏文本(输出[字段])
    return 输出
