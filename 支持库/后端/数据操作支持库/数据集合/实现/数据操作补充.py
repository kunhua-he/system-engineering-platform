"""数据操作补充原子能力实现。

职责：列表去重/倒序/分片、字典合并、文本截取/去首尾/重复（补充常用场景）。
纯标准库，不做业务逻辑。
"""

from __future__ import annotations

from 公共契约.基础类型.结果类型 import 结果


def 列表去重(列表: list = None) -> 结果:
    """列表去重（保持原顺序）。返回 {结果列表, 数量}。"""
    if not isinstance(列表, list):
        return 结果.失败("参数不合法", "列表必须是列表", 来源="数据操作")
    结果列表 = []
    seen = set()
    for 项 in 列表:
        try:
            if 项 in seen:
                continue
            seen.add(项)
            结果列表.append(项)
        except TypeError:
            结果列表.append(项)
    return 结果.成功结果({"结果列表": 结果列表, "数量": len(结果列表)})


def 列表倒序(列表: list = None) -> 结果:
    """列表倒序。返回 {结果列表}。"""
    if not isinstance(列表, list):
        return 结果.失败("参数不合法", "列表必须是列表", 来源="数据操作")
    return 结果.成功结果({"结果列表": list(reversed(列表))})


def 列表分片(列表: list = None, 起始: int = None, 结束: int = None) -> 结果:
    """列表分片。返回 {结果列表}。"""
    if not isinstance(列表, list):
        return 结果.失败("参数不合法", "列表必须是列表", 来源="数据操作")
    起 = 起始 if isinstance(起始, int) else 0
    止 = 结束 if isinstance(结束, int) else len(列表)
    return 结果.成功结果({"结果列表": 列表[起:止]})


def 字典合并(字典列表: list = None) -> 结果:
    """合并多个字典（后者覆盖前者）。返回 {结果字典}。"""
    if not isinstance(字典列表, list):
        return 结果.失败("参数不合法", "字典列表必须是列表", 来源="数据操作")
    结果字典 = {}
    for 字典 in 字典列表:
        if not isinstance(字典, dict):
            return 结果.失败("参数不合法", "字典列表元素必须是字典", 来源="数据操作")
        结果字典.update(字典)
    return 结果.成功结果({"结果字典": 结果字典, "键数量": len(结果字典)})


def 文本截取(文本: str = None, 起始: int = None, 长度: int = None) -> 结果:
    """文本截取。返回 {结果文本}。"""
    if not isinstance(文本, str):
        return 结果.失败("参数不合法", "文本必须是字符串", 来源="数据操作")
    起 = 起始 if isinstance(起始, int) else 0
    长 = 长度 if isinstance(长度, int) and 长度 > 0 else len(文本) - 起
    return 结果.成功结果({"结果文本": 文本[起:起 + 长]})


def 文本去首尾(文本: str = None, 字符集: str = None) -> 结果:
    """去除文本首尾指定字符（默认空白）。返回 {结果文本}。"""
    if not isinstance(文本, str):
        return 结果.失败("参数不合法", "文本必须是字符串", 来源="数据操作")
    字符 = 字符集 if isinstance(字符集, str) and 字符集 else None
    return 结果.成功结果({"结果文本": 文本.strip(字符) if 字符 else 文本.strip()})


def 文本重复(文本: str = None, 次数: int = None) -> 结果:
    """文本重复 N 次。返回 {结果文本}。"""
    if not isinstance(文本, str):
        return 结果.失败("参数不合法", "文本必须是字符串", 来源="数据操作")
    次 = 次数 if isinstance(次数, int) and 次数 > 0 else 1
    return 结果.成功结果({"结果文本": 文本 * 次})
