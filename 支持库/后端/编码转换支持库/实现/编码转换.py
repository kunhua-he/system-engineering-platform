"""编码转换原子能力实现（不对外暴露，只经包级中文入口调用）。

职责：字符编码转换（参考易语言汉字编码转换支持库，保持原子）。
UTF-8 / GBK / Unicode(UTF-16) 互转 + 编码检测。
只做编码转换，不做业务逻辑；纯标准库。
"""

from __future__ import annotations

from 公共契约.基础类型.结果类型 import 结果

_编码映射 = {"utf8": "utf-8", "utf-8": "utf-8", "gbk": "gbk", "gb2312": "gbk",
             "unicode": "utf-16", "utf16": "utf-16", "big5": "big5", "latin1": "latin-1"}


def _规范编码(编码: str) -> str:
    return _编码映射.get((编码 or "utf-8").lower().replace("_", "-"), (编码 or "utf-8"))


def 文本转字节(文本: str = None, 编码: str = None) -> 结果:
    """文本 → 字节序列。返回 {字节b64, 编码}。"""
    if not isinstance(文本, str):
        return 结果.失败("参数不合法", "文本必须是非空字符串", 来源="编码转换")
    目标编码 = _规范编码(编码)
    try:
        字节 = 文本.encode(目标编码)
    except (UnicodeEncodeError, LookupError) as 错误:
        return 结果.失败("编码失败", f"无法用 {目标编码} 编码文本: {错误}", 来源="编码转换")
    import base64
    return 结果.成功结果({"字节b64": base64.b64encode(字节).decode("ascii"), "编码": 目标编码, "字节数": len(字节)})


def 字节转文本(字节b64: str = None, 编码: str = None) -> 结果:
    """字节序列 → 文本。返回 {文本, 编码}。"""
    if not isinstance(字节b64, str) or not 字节b64.strip():
        return 结果.失败("参数不合法", "字节b64必须是非空字符串", 来源="编码转换")
    import base64
    try:
        字节 = base64.b64decode(字节b64)
    except Exception as 错误:
        return 结果.失败("参数不合法", f"字节b64解码失败: {错误}", 来源="编码转换")
    目标编码 = _规范编码(编码)
    try:
        文本 = 字节.decode(目标编码)
    except (UnicodeDecodeError, LookupError) as 错误:
        return 结果.失败("解码失败", f"无法用 {目标编码} 解码字节: {错误}", 来源="编码转换")
    return 结果.成功结果({"文本": 文本, "编码": 目标编码})


def 检测编码(字节b64: str = None) -> 结果:
    """检测字节序列编码（启发式）。返回 {编码, 置信度}。"""
    if not isinstance(字节b64, str) or not 字节b64.strip():
        return 结果.失败("参数不合法", "字节b64必须是非空字符串", 来源="编码转换")
    import base64
    try:
        字节 = base64.b64decode(字节b64)
    except Exception as 错误:
        return 结果.失败("参数不合法", f"字节b64解码失败: {错误}", 来源="编码转换")
    # UTF-8 严格校验
    try:
        字节.decode("utf-8")
        return 结果.成功结果({"编码": "utf-8", "置信度": "高"})
    except UnicodeDecodeError:
        pass
    # UTF-16 带 BOM
    if 字节[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return 结果.成功结果({"编码": "utf-16", "置信度": "高"})
    # GBK 试探
    try:
        字节.decode("gbk")
        return 结果.成功结果({"编码": "gbk", "置信度": "中"})
    except UnicodeDecodeError:
        pass
    return 结果.成功结果({"编码": "未知", "置信度": "低"})


def 转码(字节b64: str = None, 源编码: str = None, 目标编码: str = None) -> 结果:
    """字节从源编码转为目标编码。返回 {字节b64, 源编码, 目标编码}。"""
    if not isinstance(字节b64, str) or not 字节b64.strip():
        return 结果.失败("参数不合法", "字节b64必须是非空字符串", 来源="编码转换")
    import base64
    try:
        字节 = base64.b64decode(字节b64)
    except Exception as 错误:
        return 结果.失败("参数不合法", f"字节b64解码失败: {错误}", 来源="编码转换")
    源 = _规范编码(源编码)
    目标 = _规范编码(目标编码)
    try:
        文本 = 字节.decode(源)
        新字节 = 文本.encode(目标)
    except (UnicodeDecodeError, UnicodeEncodeError, LookupError) as 错误:
        return 结果.失败("转码失败", f"{源} → {目标}: {错误}", 来源="编码转换")
    return 结果.成功结果({"字节b64": base64.b64encode(新字节).decode("ascii"),
                            "源编码": 源, "目标编码": 目标})
