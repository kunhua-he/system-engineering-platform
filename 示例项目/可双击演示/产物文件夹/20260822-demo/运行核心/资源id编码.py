"""资源 id 安全编码：拒绝路径逃逸，统一摘要映射。

拒绝：斜杠/上级目录/绝对路径/空值/跨目录逃逸。合法资源 id 使用
[一-龥\\w-] 字符集，其余一律经 sha256 摘要映射。
"""

from __future__ import annotations

import hashlib
import re

非法字符模式 = re.compile(r"[\\/]|\.\.|^\.|^$")
合法字符模式 = re.compile(r"^[一-龥\w-]+$")


def 校验资源id(资源id: str) -> tuple[bool, str]:
    """校验资源 id 合法性。"""
    if not isinstance(资源id, str) or not 资源id:
        return False, "资源 id 不能为空"
    if 资源id != 资源id.strip():
        return False, "资源 id 不能含首尾空白"
    if 非法字符模式.search(资源id):
        return False, f"资源 id 含非法字符（斜杠/上级目录/路径分隔）: {资源id}"
    if len(资源id) > 200:
        return False, "资源 id 过长"
    return True, "资源 id 合法"


def 安全资源id(资源id: str) -> str:
    """统一编码：合法字符原样，含非法字符时经 sha256 摘要映射。"""
    合法, _ = 校验资源id(资源id)
    if 合法 and 合法字符模式.match(资源id):
        return 资源id
    return f"摘要_{hashlib.sha256(资源id.encode('utf-8')).hexdigest()[:24]}"


def 拒绝跨目录逃逸(路径: str, 根目录: str) -> tuple[bool, str]:
    """路径逃逸拒绝：目标路径必须位于根目录内。"""
    from pathlib import Path
    try:
        目标 = Path(路径).resolve()
        根 = Path(根目录).resolve()
        目标.relative_to(根)
        return True, "路径安全"
    except (ValueError, OSError):
        return False, f"路径逃逸被拒绝: {路径}"
