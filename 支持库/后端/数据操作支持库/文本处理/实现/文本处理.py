"""原子能力实现（不对外暴露，只经包级中文入口调用）。

全部公开能力返回统一结果（成功/值/错误/错误码）；参数缺失或类型非法
返回 参数不合法，不抛出异常、不以成功形状伪装失败。
"""

from __future__ import annotations

from typing import Any

from 公共契约.基础类型.结果类型 import 结果


def _成功(值: Any = None) -> 结果:
    return 结果.成功结果(值)


def _失败(错误码: str, 消息: str) -> 结果:
    return 结果.失败(错误码, 消息, 来源="文本处理")


def 分割文本(文本: str = None, 分隔符: str = None) -> 结果:
    """按分隔符分割文本，返回片段列表。"""
    if not isinstance(文本, str):
        return _失败("参数不合法", "文本必须为字符串")
    if not isinstance(分隔符, str):
        return _失败("参数不合法", "分隔符必须为字符串")
    return _成功(文本.split(分隔符))


def 合并文本(片段列表: list = None, 分隔符: str = None) -> 结果:
    """用分隔符连接片段列表。"""
    if not isinstance(片段列表, list):
        return _失败("参数不合法", "片段列表必须是列表")
    if not isinstance(分隔符, str):
        return _失败("参数不合法", "分隔符必须为字符串")
    return _成功(分隔符.join(str(片段) for 片段 in 片段列表))


def 替换文本(文本: str = None, 旧文本: str = None, 新文本: str = None) -> 结果:
    """把文本中所有旧文本替换为新文本。"""
    if not isinstance(文本, str):
        return _失败("参数不合法", "文本必须为字符串")
    if not isinstance(旧文本, str) or 旧文本 == "":
        return _失败("参数不合法", "旧文本不能为空")
    if not isinstance(新文本, str):
        return _失败("参数不合法", "新文本必须为字符串")
    return _成功(文本.replace(旧文本, 新文本))


def 查找文本(文本: str = None, 目标: str = None) -> 结果:
    """返回目标在文本中的首个位置（未找到返回 -1）。"""
    if not isinstance(文本, str):
        return _失败("参数不合法", "文本必须为字符串")
    if not isinstance(目标, str):
        return _失败("参数不合法", "目标必须为字符串")
    return _成功(文本.find(目标))


def 去空白(文本: str = None) -> 结果:
    """去除文本首尾空白。"""
    if not isinstance(文本, str):
        return _失败("参数不合法", "文本必须为字符串")
    return _成功(文本.strip())


def 转大写(文本: str = None) -> 结果:
    """把文本转为大写。"""
    if not isinstance(文本, str):
        return _失败("参数不合法", "文本必须为字符串")
    return _成功(文本.upper())


def 转小写(文本: str = None) -> 结果:
    """把文本转为小写。"""
    if not isinstance(文本, str):
        return _失败("参数不合法", "文本必须为字符串")
    return _成功(文本.lower())


def 统计长度(文本: str = None) -> 结果:
    """统计文本字符长度。"""
    if not isinstance(文本, str):
        return _失败("参数不合法", "文本必须为字符串")
    return _成功(len(文本))


def 按行分割(文本: str = None) -> 结果:
    """按换行符分割文本为行列表。"""
    if not isinstance(文本, str):
        return _失败("参数不合法", "文本必须为字符串")
    return _成功(文本.splitlines())

def 解析区间(文本: str = None, 模式: str = "集合") -> 结果:
    """解析 "1-5,7,10" 形式的页码/行号区间文本。

    模式="集合"：支持多段（逗号分隔）与范围（起-止），
                返回 {数值列表(去重升序), 数量, 是否有效}；无法解析出任何数值时 是否有效=False。
    模式="范围"：仅接受单个 "起-止" 或单值，返回 {起始, 结束, 是否有效}。
    空文本：集合模式返回空集（是否有效=True）；范围模式返回 是否有效=False。
    """
    if 文本 is not None and not isinstance(文本, str):
        return 结果.失败("参数不合法", "文本必须是文本型", 来源="文本处理")
    if 模式 not in ("集合", "范围"):
        return 结果.失败("参数不合法", "模式必须是 集合 或 范围", 来源="文本处理")

    原文 = (文本 or "").strip()
    if 模式 == "范围":
        if not 原文:
            return 结果.成功结果({"起始": None, "结束": None, "是否有效": False})
        if "-" in 原文:
            起, 止 = 原文.split("-", 1)
            try:
                return 结果.成功结果({"起始": int(起), "结束": int(止), "是否有效": True})
            except ValueError:
                return 结果.成功结果({"起始": None, "结束": None, "是否有效": False})
        try:
            值 = int(原文)
            return 结果.成功结果({"起始": 值, "结束": 值, "是否有效": True})
        except ValueError:
            return 结果.成功结果({"起始": None, "结束": None, "是否有效": False})

    集合: set[int] = set()
    for 段 in 原文.split(","):
        段 = 段.strip()
        if not 段:
            continue
        if "-" in 段:
            起, 止 = 段.split("-", 1)
            try:
                集合.update(range(int(起), int(止) + 1))
            except ValueError:
                continue
        else:
            try:
                集合.add(int(段))
            except ValueError:
                continue
    数值列表 = sorted(集合)
    return 结果.成功结果({"数值列表": 数值列表, "数量": len(数值列表), "是否有效": bool(数值列表) or not 原文})
