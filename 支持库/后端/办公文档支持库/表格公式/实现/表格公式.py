"""办公文档支持库 · 表格公式原子能力（不对外暴露，只经包级中文入口调用）。

把 V3 自持的表格公式求值与 A1 单元格地址运算下沉为底座原子能力：
纯标准库、无状态、无副作用，一律返回统一结果，不抛异常。
"""

from __future__ import annotations

import ast
import operator
import re
from typing import Any

from 公共契约.基础类型.结果类型 import 结果

_允许运算符 = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}
_最大表达式长度 = 500
_最大节点数 = 100
_最大深度 = 10
_函数模式 = re.compile(r"^(SUM|AVERAGE|COUNT|MAX|MIN)\((.+)\)$", re.IGNORECASE)
_单元格模式 = re.compile(r"^([A-Z]+)(\d+)$")
_单元格引用模式 = re.compile(r"[A-Z]+\d+")
_空白模式 = re.compile(r"\s+")
_纯算式模式 = re.compile(r"^[0-9+\-*/().]+$")


def _失败(错误码: str, 消息: str) -> 结果:
    return 结果.失败(错误码, 消息, 来源="表格公式")


def 解析单元格地址(地址: str = None) -> 结果:
    """解析 A1 样式地址为行列：行 1 起、列 0 起；非法地址返回 0/0。"""
    if not isinstance(地址, str):
        return _失败("参数不合法", "地址必须是文本")
    匹配 = _单元格模式.match(地址.upper())
    if not 匹配:
        return 结果.成功结果({"行": 0, "列": 0})
    列号 = 0
    for 字符 in 匹配.group(1):
        列号 = 列号 * 26 + (ord(字符) - 64)
    return 结果.成功结果({"行": int(匹配.group(2)), "列": 列号 - 1})


def 格式化单元格地址(行: int = None, 列: int = None) -> 结果:
    """把（行 1 起、列 0 起）格式化为 A1 样式地址。"""
    for 值 in (行, 列):
        if isinstance(值, bool) or not isinstance(值, int):
            return _失败("参数不合法", "行与列必须是整数")
    列序号 = 列 + 1
    字母 = ""
    while 列序号 > 0:
        列序号 -= 1
        字母 = chr(65 + (列序号 % 26)) + 字母
        列序号 //= 26
    return 结果.成功结果({"地址": f"{字母}{行}"})


def 格式化列字母(列: int = None) -> 结果:
    """把列序号（0 起）格式化为列字母：0 → A、26 → AA。"""
    结果值 = 格式化单元格地址(1, 列)
    if not 结果值.成功:
        return 结果值
    return 结果.成功结果({"列字母": str(结果值.值["地址"]).rstrip("0123456789")})


def 列字母转索引(列字母: str = None) -> 结果:
    """把列字母转为列序号（0 起）：A → 0、AA → 26。"""
    if not isinstance(列字母, str):
        return _失败("参数不合法", "列字母必须是文本")
    索引 = 0
    for 字符 in 列字母.upper():
        索引 = 索引 * 26 + (ord(字符) - 64)
    return 结果.成功结果({"索引": 索引 - 1})


def 解析单元格范围(范围: str = None) -> 结果:
    """解析 'A1:B3' 为四角行列；非两段写法按单地址处理。"""
    if not isinstance(范围, str):
        return _失败("参数不合法", "范围必须是文本")
    分段 = 范围.split(":")
    if len(分段) != 2:
        左上 = 解析单元格地址(范围).值
        右下 = 左上
    else:
        左上 = 解析单元格地址(分段[0]).值
        右下 = 解析单元格地址(分段[1]).值
    return 结果.成功结果({
        "左上行": 左上["行"], "左上列": 左上["列"],
        "右下行": 右下["行"], "右下列": 右下["列"],
    })


def 展开单元格范围(范围: str = None) -> 结果:
    """把 'A1:C3' 展开为范围内全部单元格地址（先行后列）。"""
    范围值 = 解析单元格范围(范围)
    if not 范围值.成功:
        return 范围值
    四角 = 范围值.值
    地址列表 = [
        格式化单元格地址(行, 列).值["地址"]
        for 行 in range(四角["左上行"], 四角["右下行"] + 1)
        for 列 in range(四角["左上列"], 四角["右下列"] + 1)
    ]
    return 结果.成功结果({"地址列表": 地址列表})


def 批量格式化单元格地址(行列列表: list = None) -> 结果:
    """把 (行, 列) 列表批量格式化为 A1 地址，返回同序地址列表。

    逐项复用 格式化单元格地址，非法项与单次调用语义完全一致（不额外报错）。
    存在的意义：调用方常有「遍历整表逐格算地址」的循环，若逐格走网关会因
    单次约 1.5ms 且网关限流而不可用；批量一次调用把 N 次请求降为 1 次。
    """
    if not isinstance(行列列表, list):
        return _失败("参数不合法", "行列列表 必须是列表")
    地址列表 = []
    for 序号, 项 in enumerate(行列列表):
        if not isinstance(项, dict):
            return _失败("参数不合法", f"行列列表第 {序号} 项必须是字典")
        地址值 = 格式化单元格地址(项.get("行"), 项.get("列"))
        if not 地址值.成功:
            return 地址值
        地址列表.append(地址值.值["地址"])
    return 结果.成功结果({"地址列表": 地址列表})


def 批量解析单元格地址(地址列表: list = None) -> 结果:
    """把 A1 地址列表批量解析为行列列表，返回同序同长的结果列表。

    逐项复用 解析单元格地址，非法地址与单次调用语义完全一致（返回 0/0）。
    与 批量格式化单元格地址 配对：调用方遍历整表时，解析与格式化各 1 次调用。
    """
    if not isinstance(地址列表, list):
        return _失败("参数不合法", "地址列表 必须是列表")
    解析列表 = []
    for 序号, 地址 in enumerate(地址列表):
        if not isinstance(地址, str):
            return _失败("参数不合法", f"地址列表第 {序号} 项必须是文本")
        解析值 = 解析单元格地址(地址)
        if not 解析值.成功:
            return 解析值
        解析列表.append(解析值.值)
    return 结果.成功结果({"解析列表": 解析列表})


def _安全求值算术(表达式: str) -> float | int | None:
    """用 ast.parse 白名单求值代替 eval；越界或非法节点返回 None。"""
    if len(表达式) > _最大表达式长度:
        return None
    try:
        语法树 = ast.parse(表达式.strip(), mode="eval")
    except SyntaxError:
        return None

    节点计数 = 0

    def _检查(node: Any, 深度: int = 0) -> Any:
        nonlocal 节点计数
        if 深度 > _最大深度:
            raise ValueError("表达式嵌套过深")
        节点计数 += 1
        if 节点计数 > _最大节点数:
            raise ValueError("节点数过多")
        if isinstance(node, ast.Expression):
            return _检查(node.body, 深度)
        if isinstance(node, ast.Constant):
            if not isinstance(node.value, (int, float)):
                raise ValueError("非数值常量")
            return node.value
        if isinstance(node, ast.UnaryOp):
            运算 = _允许运算符.get(type(node.op))
            if 运算 is None:
                raise ValueError(f"不允许的一元运算符: {type(node.op).__name__}")
            return 运算(_检查(node.operand, 深度 + 1))
        if isinstance(node, ast.BinOp):
            运算 = _允许运算符.get(type(node.op))
            if 运算 is None:
                raise ValueError(f"不允许的二元运算符: {type(node.op).__name__}")
            return 运算(_检查(node.left, 深度 + 1), _检查(node.right, 深度 + 1))
        raise ValueError(f"不允许的节点类型: {type(node).__name__}")

    try:
        return _检查(语法树)
    except (ValueError, TypeError, ZeroDivisionError):
        return None


def _取数值列表(参数字符串: str, 单元格字典: dict) -> list | None:
    数值列表: list = []
    for 分段 in [项.strip() for 项 in 参数字符串.split(",")]:
        if ":" in 分段:
            分段表 = 分段.split(":")
            if len(分段表) != 2:
                return None
            左上 = 解析单元格地址(分段表[0]).值
            右下 = 解析单元格地址(分段表[1]).值
            for 行 in range(左上["行"], 右下["行"] + 1):
                for 列 in range(左上["列"], 右下["列"] + 1):
                    地址 = 格式化单元格地址(行, 列).值["地址"]
                    数值列表.append(_取数值(单元格字典.get(地址, "0")))
        else:
            数值列表.append(_取数值(单元格字典.get(分段, "0")))
    return 数值列表


def _取数值(值: Any) -> float:
    try:
        return float(值)
    except (ValueError, TypeError):
        return 0.0


def _执行函数(函数名: str, 参数字符串: str, 单元格字典: dict) -> str:
    数值列表 = _取数值列表(参数字符串, 单元格字典)
    if 数值列表 is None:
        return "#VALUE!"
    if 函数名 == "SUM":
        return str(sum(数值列表))
    if 函数名 == "AVERAGE":
        return str(sum(数值列表) / len(数值列表)) if 数值列表 else "#DIV/0!"
    if 函数名 == "COUNT":
        return str(len(数值列表))
    if 函数名 == "MAX":
        return str(max(数值列表)) if 数值列表 else "#VALUE!"
    if 函数名 == "MIN":
        return str(min(数值列表)) if 数值列表 else "#VALUE!"
    return "#NAME?"


def _安全算术(表达式: str, 单元格字典: dict) -> float | int | None:
    def _替换单元格(匹配: Any) -> str:
        地址 = 匹配.group(0)
        return str(单元格字典.get(地址, "0"))

    替换后 = _单元格引用模式.sub(_替换单元格, 表达式)
    替换后 = _空白模式.sub("", 替换后)
    if not _纯算式模式.match(替换后):
        return None
    return _安全求值算术(替换后)


def 求值公式(表达式: str = None, 单元格字典: dict = None) -> 结果:
    """对 Excel 公式求值：非 = 开头原样返回，其余按函数或四则运算求值。

    错误值沿用 Excel 语义：非法表达式 #VALUE!、空集平均 #DIV/0!、未知函数 #NAME?。
    """
    if not isinstance(表达式, str):
        return _失败("参数不合法", "表达式必须是文本")
    if 单元格字典 is None:
        单元格字典 = {}
    if not isinstance(单元格字典, dict):
        return _失败("参数不合法", "单元格字典必须是字典型")
    if not 表达式.startswith("="):
        return 结果.成功结果({"结果文本": 表达式})

    请求体 = 表达式[1:].strip()
    匹配 = _函数模式.match(请求体)
    if 匹配:
        return 结果.成功结果({
            "结果文本": _执行函数(匹配.group(1).upper(), 匹配.group(2), 单元格字典),
        })

    计算结果 = _安全算术(请求体, 单元格字典)
    if 计算结果 is not None and isinstance(计算结果, (int, float)):
        return 结果.成功结果({"结果文本": str(计算结果)})
    return 结果.成功结果({"结果文本": "#VALUE!"})
