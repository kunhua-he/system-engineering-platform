"""正则表达式原子能力实现（不对外暴露，只经包级中文入口调用）。

职责：正则匹配/搜索/替换/分割/校验（参考易语言正则表达式支持库，保持原子）。
纯标准库 re，不做业务逻辑。
"""

from __future__ import annotations

import re

from 公共契约.基础类型.结果类型 import 结果


def _编译(表达式: str) -> re.Pattern | None:
    try:
        return re.compile(表达式)
    except re.error:
        return None


def 校验(表达式: str = None) -> 结果:
    """正则合法性校验。返回 {合法, 错误说明}。"""
    if not isinstance(表达式, str) or not 表达式.strip():
        return 结果.失败("参数不合法", "表达式必须是非空字符串", 来源="正则表达式")
    try:
        re.compile(表达式)
        return 结果.成功结果({"合法": True, "表达式": 表达式})
    except re.error as 错误:
        return 结果.成功结果({"合法": False, "表达式": 表达式, "错误说明": str(错误)})


def 匹配(表达式: str = None, 文本: str = None, 忽略大小写: bool = None) -> 结果:
    """正则匹配，返回所有命中。返回 {命中数, 命中列表}。"""
    if not isinstance(表达式, str) or not 表达式.strip():
        return 结果.失败("参数不合法", "表达式必须是非空字符串", 来源="正则表达式")
    if not isinstance(文本, str):
        return 结果.失败("参数不合法", "文本必须是非空字符串", 来源="正则表达式")
    标志 = re.IGNORECASE if 忽略大小写 else 0
    try:
        模式 = re.compile(表达式, 标志)
        命中列表 = [m.group(0) for m in 模式.finditer(文本)]
        return 结果.成功结果({"命中数": len(命中列表), "命中列表": 命中列表})
    except re.error as 错误:
        return 结果.失败("表达式不合法", str(错误), 来源="正则表达式")


def 搜索(表达式: str = None, 文本: str = None, 忽略大小写: bool = None) -> 结果:
    """正则搜索，返回首个命中（含分组）。返回 {找到, 命中, 分组}。"""
    if not isinstance(表达式, str) or not 表达式.strip():
        return 结果.失败("参数不合法", "表达式必须是非空字符串", 来源="正则表达式")
    if not isinstance(文本, str):
        return 结果.失败("参数不合法", "文本必须是非空字符串", 来源="正则表达式")
    标志 = re.IGNORECASE if 忽略大小写 else 0
    try:
        模式 = re.compile(表达式, 标志)
        m = 模式.search(文本)
        if m is None:
            return 结果.成功结果({"找到": False, "命中": None, "分组": []})
        return 结果.成功结果({"找到": True, "命中": m.group(0), "分组": list(m.groups())})
    except re.error as 错误:
        return 结果.失败("表达式不合法", str(错误), 来源="正则表达式")


def 替换(表达式: str = None, 文本: str = None, 替换为: str = None, 忽略大小写: bool = None) -> 结果:
    """正则替换。返回 {替换后文本, 替换次数}。"""
    if not isinstance(表达式, str) or not 表达式.strip():
        return 结果.失败("参数不合法", "表达式必须是非空字符串", 来源="正则表达式")
    if not isinstance(文本, str):
        return 结果.失败("参数不合法", "文本必须是非空字符串", 来源="正则表达式")
    if not isinstance(替换为, str):
        return 结果.失败("参数不合法", "替换为必须是非空字符串", 来源="正则表达式")
    标志 = re.IGNORECASE if 忽略大小写 else 0
    try:
        模式 = re.compile(表达式, 标志)
        新文本, 次数 = 模式.subn(替换为, 文本)
        return 结果.成功结果({"替换后文本": 新文本, "替换次数": 次数})
    except re.error as 错误:
        return 结果.失败("表达式不合法", str(错误), 来源="正则表达式")


def 分割(表达式: str = None, 文本: str = None, 忽略大小写: bool = None) -> 结果:
    """按正则分割。返回 {片段列表}。"""
    if not isinstance(表达式, str) or not 表达式.strip():
        return 结果.失败("参数不合法", "表达式必须是非空字符串", 来源="正则表达式")
    if not isinstance(文本, str):
        return 结果.失败("参数不合法", "文本必须是非空字符串", 来源="正则表达式")
    标志 = re.IGNORECASE if 忽略大小写 else 0
    try:
        模式 = re.compile(表达式, 标志)
        片段列表 = 模式.split(文本)
        return 结果.成功结果({"片段列表": 片段列表, "片段数": len(片段列表)})
    except re.error as 错误:
        return 结果.失败("表达式不合法", str(错误), 来源="正则表达式")
