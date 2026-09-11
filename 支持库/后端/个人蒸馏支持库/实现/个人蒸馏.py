"""个人蒸馏网关支持库：唯一外部客户端与事实投影格式化。

调用者只能经 40007 网关调用能力；本实现直接发 HTTP 请求外部个人蒸馏服务
（默认 http://127.0.0.1:8898），只依赖 Python 标准库。
"""

from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any


class 个人蒸馏不可用(RuntimeError):
    """外部个人蒸馏网关不可用或返回不符合契约。"""


def 当前时间() -> datetime:
    return datetime.now(timezone.utc)


def _地址() -> str:
    return os.environ.get("V3个人蒸馏地址", "http://127.0.0.1:8898").rstrip("/")


def 构建上下文请求参数(*, 主体标识: str, 岗位标识: str, 场景: str | None, as_of: datetime, known_at: datetime) -> dict[str, str]:
    if not 主体标识.strip() or not 岗位标识.strip():
        raise ValueError("主体标识和岗位标识不能为空")
    参数 = {
        "主体标识": 主体标识,
        "岗位标识": 岗位标识,
        "场景": 场景 or "",
        "as_of": as_of.isoformat(),
        "known_at": known_at.isoformat(),
    }
    return {键: 值 for 键, 值 in 参数.items() if 值 != ""}


def _校验上下文(上下文: Any) -> dict[str, Any]:
    if not isinstance(上下文, dict):
        raise 个人蒸馏不可用("个人蒸馏返回不是对象")
    缺失 = [字段 for 字段 in ("主体标识", "岗位标识") if 字段 not in 上下文]
    if 缺失:
        raise 个人蒸馏不可用(f"个人蒸馏返回缺少字段：{', '.join(缺失)}")
    if "条目" in 上下文 and not isinstance(上下文["条目"], list):
        raise 个人蒸馏不可用("个人蒸馏投影条目不是列表")
    for 字段 in ("正式事实", "归纳观察"):
        if 字段 in 上下文 and not isinstance(上下文[字段], list):
            raise 个人蒸馏不可用(f"个人蒸馏{字段}字段不是列表")
    return 上下文


def 查询上下文(主体标识: str, 岗位标识: str, 场景: str | None, as_of: datetime, known_at: datetime) -> dict[str, Any]:
    参数 = 构建上下文请求参数(主体标识=主体标识, 岗位标识=岗位标识, 场景=场景, as_of=as_of, known_at=known_at)
    查询串 = urllib.parse.urlencode(参数)
    # 路径含中文，必须单独编码；urlencode 只处理 query 不处理 path
    接口路径 = urllib.parse.quote("/接口/v1/人格/当前")
    url = f"{_地址()}{接口路径}?{查询串}"
    try:
        with urllib.request.urlopen(url, timeout=8) as resp:
            状态码 = resp.status
            响应文本 = resp.read().decode("utf-8")
    except Exception as 错误:
        raise 个人蒸馏不可用(f"请求外部个人蒸馏失败: {错误}")
    if 状态码 != 200:
        raise 个人蒸馏不可用(f"HTTP {状态码}")
    try:
        上下文 = json.loads(响应文本)
    except json.JSONDecodeError as 错误:
        raise 个人蒸馏不可用(f"个人蒸馏返回不是合法 JSON: {错误}")
    return _校验上下文(上下文)


def 格式化可注入上下文(上下文: dict[str, Any]) -> str:
    """只输出稳定、已确认条目和证据边界。"""
    if not isinstance(上下文, dict):
        return ""
    稳定事实 = [
        项 for 项 in 上下文.get("正式事实", [])
        if isinstance(项, dict) and 项.get("状态") == "有效" and 项.get("可用于稳定判断") is True
    ]
    稳定观察 = [
        项 for 项 in 上下文.get("归纳观察", [])
        if isinstance(项, dict) and 项.get("层级") == "稳定" and 项.get("待确认") is False
    ]
    稳定投影 = [
        项 for 项 in 上下文.get("条目", [])
        if isinstance(项, dict) and 项.get("认识阶段") == "已建立" and 项.get("待确认") is False
    ]
    行 = ["## 外部个人蒸馏已确认事实", f"主体：{上下文.get('主体标识', '')}", f"岗位：{上下文.get('岗位标识', '')}"]
    if 稳定事实:
        行.append("### 正式事实")
        行.extend(f"- {项.get('谓词', '事实')}：{项.get('客体', '')}" for 项 in 稳定事实)
    if 稳定观察:
        行.append("### 稳定观察")
        行.extend(f"- {项.get('结论', '')}" for 项 in 稳定观察)
    if 稳定投影:
        行.append("### 已确认人格事实")
        行.extend(f"- {项.get('维度', '')}：{项.get('结论', '')}" for 项 in 稳定投影)
    for 标题, 字段 in (("### 证据边界", "证据边界"), ("### 禁止推断", "禁止推断")):
        值列表 = [str(项) for 项 in 上下文.get(字段, []) if str(项).strip()]
        if 值列表:
            行.append(标题)
            行.extend(f"- {项}" for 项 in 值列表)
    return "\n".join(行)
