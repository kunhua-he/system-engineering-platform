"""未解释跳过检查（静态）：跳过没有理由即违规。

口径承自已退役的 `MCP工具箱/验证门禁.py::_检出未解释跳过`（该目录已收敛移除，
现由本模块自身实现该口径）——**存在跳过标记但
没有说明（skip 无原因）即失败**（`AGENTS.md:156`、`:283-284`）。本门禁不执行用例，
所以判定落在源码静态层：`skip` / `skipIf` / `skipUnless` / `skipTest` /
`SkipTest` 缺少理由实参，或理由实参是空/纯空白常量，即违规。

宽松边界（防误报，必须在文档里写明）：

- 理由若是非常量表达式（f-string、变量、函数返回），一律视为**已解释**——
  静态无法求值时不猜测，避免把「如实标注环境缺失」的正当跳过误判成违规；
- 理由为中文/英文常量只要非空白即视为已解释；
- 本模块不做「原因分支过宽」收紧（`开发文档/未完成事项.md` 已登记该待收紧项），
  沿用现口径。

本模块不打印、不退出。
"""
from __future__ import annotations
from 公共契约.基础类型.逻辑类型 import 真, 假

import ast

from . import 发现

跳过函数名 = frozenset({"skip", "skipIf", "skipUnless"})
需理由个数 = {"skip": 1, "skipIf": 2, "skipUnless": 2}
跳过方法名 = "skipTest"
跳过异常名 = "SkipTest"
理由关键字名 = frozenset({"reason", "理由"})


def _调用名(节点: ast.AST) -> str:
    if isinstance(节点, ast.Name):
        return 节点.id
    if isinstance(节点, ast.Attribute):
        return 节点.attr
    return ""


def _是空理由(节点: ast.AST | None) -> bool:
    """缺省、None 或纯空白字符串常量即「没有说明」；非常量表达式视为已解释。"""
    if 节点 is None:
        return 真
    if isinstance(节点, ast.Constant):
        if 节点.value is None:
            return 真
        if isinstance(节点.value, str):
            return not 节点.value.strip()
    return 假


def _位置理由问题(节点: ast.Call, 需个数: int) -> str:
    """返回违规细节；空字符串表示理由齐备或非常量（不猜测）。"""
    if len(节点.args) < 需个数:
        return f"缺理由实参（需 {需个数} 个实参，实际 {len(节点.args)} 个）"
    if _是空理由(节点.args[需个数 - 1]):
        return "理由实参为空或纯空白"
    return ""


def _关键字理由为空(节点: ast.Call) -> bool:
    return any(
        关键字.arg in 理由关键字名 and _是空理由(关键字.value)
        for 关键字 in 节点.keywords
    )


def 检查源码(源码: str, 相对路径: str) -> list[dict]:
    """AST 扫描单个测试文件，返回未解释跳过违规清单。"""
    违规: list[dict] = []
    try:
        树 = ast.parse(源码)
    except SyntaxError as 错误:
        return [{
            "类型": "未解释跳过", "文件": 相对路径, "行号": 错误.lineno,
            "细节": f"源码无法解析（导入阶段同样会失败）: {错误.msg}",
        }]
    for 节点 in ast.walk(树):
        if isinstance(节点, ast.Call):
            名字 = _调用名(节点.func)
            if 名字 in 跳过函数名:
                问题 = _位置理由问题(节点, 需理由个数[名字])
                if not 问题 and _关键字理由为空(节点):
                    问题 = "理由以关键字传入但为空"
            elif 名字 in (跳过方法名, 跳过异常名):
                问题 = _位置理由问题(节点, 1)
                if not 问题 and _关键字理由为空(节点):
                    问题 = "理由以关键字传入但为空"
            else:
                continue
            if 问题:
                违规.append({
                    "类型": "未解释跳过", "文件": 相对路径, "行号": 节点.lineno,
                    "细节": f"{名字}(): {问题}",
                })
        elif isinstance(节点, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            for 装饰器 in 节点.decorator_list:
                if isinstance(装饰器, (ast.Name, ast.Attribute)) and _调用名(装饰器) in 跳过函数名:
                    违规.append({
                        "类型": "未解释跳过", "文件": 相对路径,
                        "行号": getattr(装饰器, "lineno", 节点.lineno),
                        "细节": f"{_调用名(装饰器)} 作为裸装饰器使用，没有理由（导入期即 TypeError）",
                    })
    return sorted(违规, key=lambda 条: 条["行号"] or 0)


def 未解释跳过违规(资产列表: list[发现.测试资产]) -> list[dict]:
    """逐个静态扫描纳入可导入性的测试文件。"""
    违规: list[dict] = []
    for 资产 in 资产列表:
        if 资产.跳过原因:
            continue
        try:
            源码 = 资产.文件.read_text(encoding="utf-8")
        except OSError as 错误:
            违规.append({
                "类型": "未解释跳过", "文件": 资产.相对路径, "行号": None,
                "细节": f"源码读取失败: {错误}",
            })
            continue
        违规.extend(检查源码(源码, 资产.相对路径))
    return 违规
