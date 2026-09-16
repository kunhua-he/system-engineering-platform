"""tree-sitter 适配提供者：第三方 tree-sitter / tree-sitter-typescript 的唯一边界封装。

只允许在本适配层 import tree_sitter / tree_sitter_typescript；上层支持库
（代码解析支持库.语法索引）不得直接依赖第三方。

本层只做一件事：把第三方语法树**翻成底座中性语法树**——节点种类与字段名一律中文，
第三方 grammar 的英文类型名（import_statement / member_expression …）与 Parser /
Language 对象只活在本文件内。哪些节点算「导入」「符号」「调用」「字符串」是业务语义，
由调用方在中性语法树上判定，本层不代替调用方做任何业务判断，也不猜调用方要什么。

中性节点（dict，可 JSON 化；结构与 能力定义.json 值结构一致）：

    {
      "种类": "导入语句",              # 中文种类；未登记的一律 "其他"
      "起始行": 2, "结束行": 2,        # 行号 1 起算（与第三方 start_point.row+1 同口径）
      "起始字节": 26, "结束字节": 50,  # utf-8 字节区间，供调用方按原字节切文本
      "字段": {"来源": 3},             # 中文字段名 → 子节点下标；同名字段取第一个
      "子节点": [节点, ...]            # 全部子节点，顺序与第三方 children 一致（含标点/关键字节点）
    }

「字段」表与第三方 child_by_field_name 同口径（取第一个带该字段的子节点）；未登记的字
段名不导出——第三方英文不出适配层，底座要用新字段时在这里登记中文字段名。
"""

from __future__ import annotations

import threading

# 第三方 grammar 节点类型 → 底座中文种类（只登记底座用到的种类，其余归 "其他"）
_种类表 = {
    "import_statement": "导入语句",
    "export_statement": "导出语句",
    "function_declaration": "函数声明",
    "function_expression": "函数表达式",
    "arrow_function": "箭头函数",
    "lexical_declaration": "词法声明",
    "variable_declarator": "变量声明符",
    "class_declaration": "类声明",
    "method_definition": "方法定义",
    "call_expression": "调用表达式",
    "string": "字符串字面量",
    "template_string": "模板字符串",
    "identifier": "标识符",
    "member_expression": "成员访问",
}

# 第三方 field 名 → 底座中文字段名（未登记的不导出，第三方英文不越界）
_字段表 = {
    "source": "来源",
    "name": "名称",
    "value": "值",
    "body": "正文",
    "function": "调用目标",
    "arguments": "实参",
    "object": "对象",
    "property": "属性",
}

# 底座语言名 → 第三方语言工厂名（同一发行包内，不额外引入第三方）
_语言工厂表 = {
    "typescript": "language_typescript",
    "tsx": "language_tsx",
}

# 解析器缓存：语言 → 第三方 Parser（构造昂贵，进程内复用；双检锁保证并发只构造一次）
_解析器缓存: dict[str, object] = {}
_缓存锁 = threading.Lock()


class TreeSitter解析错误(Exception):
    """第三方 tree-sitter 不可用或解析失败（本层如实抛出，降级与否由调用方决定）。"""


def _取依赖():
    """惰性导入第三方；未安装抛 TreeSitter解析错误（不静默降级）。"""
    try:
        import tree_sitter
        import tree_sitter_typescript
    except ImportError as 错误:
        raise TreeSitter解析错误(f"tree-sitter 未安装: {错误}") from 错误
    return tree_sitter, tree_sitter_typescript


def _取解析器(语言: str):
    """按语言取（并缓存）第三方解析器。"""
    if 语言 not in _语言工厂表:
        raise TreeSitter解析错误(f"不支持的语言: {语言!r}（支持 {'/'.join(_语言工厂表)}）")
    已缓存 = _解析器缓存.get(语言)
    if 已缓存 is not None:
        return 已缓存
    with _缓存锁:
        if _解析器缓存.get(语言) is None:
            tree_sitter, tree_sitter_typescript = _取依赖()
            工厂名 = _语言工厂表[语言]
            工厂 = getattr(tree_sitter_typescript, 工厂名, None)
            if 工厂 is None:
                raise TreeSitter解析错误(f"tree-sitter-typescript 缺少语言工厂: {工厂名}")
            _解析器缓存[语言] = tree_sitter.Parser(tree_sitter.Language(工厂()))
    return _解析器缓存[语言]


def _取原文(节点, 源码字节: bytes) -> str:
    """按第三方节点字节区间取原文本。"""
    return 源码字节[节点.start_byte:节点.end_byte].decode()


def _翻节点(节点, 源码字节: bytes) -> dict:
    """把一个第三方节点递归翻成中性节点。"""
    子节点表: list[dict] = []
    字段表: dict[str, int] = {}
    for 下标, 子节点 in enumerate(节点.children):
        中文字段名 = _字段表.get(节点.field_name_for_child(下标))
        if 中文字段名 is not None and 中文字段名 not in 字段表:
            字段表[中文字段名] = 下标
        子节点表.append(_翻节点(子节点, 源码字节))
    return {
        "种类": _种类表.get(节点.type, "其他"),
        "起始行": 节点.start_point[0] + 1,
        "结束行": 节点.end_point[0] + 1,
        "起始字节": 节点.start_byte,
        "结束字节": 节点.end_byte,
        "字段": 字段表,
        "子节点": 子节点表,
    }


def 解析语法树(代码文本: str, 语言: str = "typescript") -> dict:
    """把源码解析为中性语法树（根节点）；第三方不可用时抛 TreeSitter解析错误。

    语法错误不抛异常——第三方按错误恢复继续出树，错误区照常翻成中性节点。
    """
    if 语言 not in _语言工厂表:
        raise TreeSitter解析错误(f"不支持的语言: {语言!r}（支持 {'/'.join(_语言工厂表)}）")
    解析器 = _取解析器(语言)
    源码字节 = 代码文本.encode("utf-8")
    return _翻节点(解析器.parse(源码字节).root_node, 源码字节)


def 依赖版本() -> str:
    """读取 tree-sitter 版本（读不到返回空文本）。"""
    try:
        import tree_sitter
    except ImportError:
        return ""
    版本 = str(getattr(tree_sitter, "__version__", "") or "")
    if 版本:
        return 版本
    try:
        from importlib import metadata
        return metadata.version("tree-sitter")
    except Exception:
        return ""


def 检查可用性() -> dict:
    """探针：报告第三方依赖是否可导入及其版本；供健康检查与依赖审计使用。"""
    try:
        _取依赖()
    except TreeSitter解析错误 as 错误:
        return {"可用": False, "版本": "", "说明": str(错误)}
    try:
        解析器探针 = _取解析器("typescript")
    except TreeSitter解析错误 as 错误:
        return {"可用": False, "版本": 依赖版本(), "说明": str(错误)}
    return {
        "可用": 解析器探针 is not None,
        "版本": 依赖版本(),
        "说明": "tree-sitter 与 tree-sitter-typescript 可导入，typescript 解析器可构造",
    }


def 停止() -> None:
    """释放进程内缓存的第三方解析器（生命周期契约声明的停止入口）。

    解析器按语言在进程内复用，属跨调用保留的临时资源；停止时必须清空，
    避免长驻进程在卸载/重载提供者后继续持有第三方对象。
    """
    with _缓存锁:
        _解析器缓存.clear()
