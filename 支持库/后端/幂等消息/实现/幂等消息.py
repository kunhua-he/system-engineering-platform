"""幂等消息原子能力实现（不对外暴露，只经包级中文入口调用）。

职责：生成会话消息的幂等 id（借鉴 OpenCode SessionInput.admit 两段式语义）。
幂等 id = sha256(会话id | 内容摘要 | 前缀) 截断，同一会话同一内容永远得到同一 id；
配合调用方的唯一约束即可实现「重复提交返回同一记录」。
只生成 id，不落库；落库与去重是调用方/业务层职责。
"""

from __future__ import annotations

import hashlib
import re
from typing import Any

from 公共契约.基础类型.结果类型 import 结果


def _失败(错误码: str, 消息: str) -> 结果:
    return 结果.失败(错误码, 消息, 来源="幂等消息")


def 生成id(会话id: str = None, 内容: str = None, 前缀: str = None) -> 结果:
    """生成幂等 id。同一 会话id+内容 永远得到同一 id。返回 {幂等id}。"""
    if not isinstance(会话id, str) or not 会话id.strip():
        return _失败("参数不合法", "会话id必须是非空字符串")
    if not isinstance(内容, str) or not 内容.strip():
        return _失败("参数不合法", "内容必须是非空字符串")
    摘要源 = f"{会话id.strip()}|{内容.strip()}"
    摘要 = hashlib.sha256(摘要源.encode("utf-8")).hexdigest()
    if isinstance(前缀, str) and 前缀.strip():
        前缀 = re.sub(r"[^a-zA-Z0-9_-]", "", 前缀.strip())[:16]
        id值 = f"{前缀}-{摘要[:24]}" if 前缀 else 摘要[:24]
    else:
        id值 = 摘要[:24]
    return 结果.成功结果({"幂等id": id值, "算法": "sha256(会话id|内容) 截断"})


def 校验id(幂等id: str = None) -> 结果:
    """校验幂等 id 格式（长度 24 或 前缀-24）。返回 {有效=true/false}。"""
    if not isinstance(幂等id, str) or not 幂等id.strip():
        return 结果.成功结果({"有效": False, "原因": "幂等id为空"})
    id值 = 幂等id.strip()
    合法 = bool(re.fullmatch(r"[a-zA-Z0-9_-]{1,16}-[a-f0-9]{24}|[a-f0-9]{24}", id值))
    return 结果.成功结果({"有效": 合法, "原因": "格式合法" if 合法 else "格式非法"})