"""代码解析支持库 · 语法索引原子能力（不对外暴露，只经包级中文入口调用）。

把调用方自持的 Python(ast) / TypeScript(tree-sitter) / Vue 语法遍历下沉为底座
原子能力：无状态、无副作用，一律返回统一结果，不抛异常（语法错误转稳定错误码）。

底座只回答「这段代码里有哪些语法事实」——导入、符号定义、调用、字符串常量、
字符串型类属性赋值；事实在调用方项目里意味着什么（跨模块判定、表名规范化、
能力边筛选、调用者归属）留在调用方。

遍历范围刻意为两套（与调用方现实现逐条对齐，不做「顺手修正」）：
- 符号只收集「模块级 + 类体直接子节点」；函数体内的嵌套定义不收集；
- 调用 / 类属性赋值深入函数体全量扫描（含嵌套函数体）+ 模块级顶层补扫。

Python 事实各带「序号」——同一文件内跨全部类目单调递增的事件序号。调用方按序号回放
才能复现原遍历的两处时序语义：调用目标是在「符号逐条入表」的过程中查找的（同文件
前向引用查不到），表边落账顺序也是调用与类属性交错产生的。TypeScript 事实无此依赖，
不产出序号。
"""

from __future__ import annotations

import ast
import re
import threading

from 公共契约.基础类型.结果类型 import 结果

# ── Python 语法事实 ────────────────────────────────────────────────────────

_有效语法集 = ("python", "typescript", "vue")

# ── TypeScript / Vue 正则降级（tree-sitter 不可用时的备胎，纯语法） ─────────

_正则_具名导入 = re.compile(
    r"""import\s*\{[^}]*\}\s*from\s*['"]([^'"]+)['"]""")
_正则_默认导入 = re.compile(
    r"""import\s+(\w+)\s+from\s*['"]([^'"]+)['"]""")
_正则_平台调用 = re.compile(
    r"""platform\s*\.\s*modules\s*\.\s*call\s*\(\s*['"]([\w-]+)['"]\s*,\s*['"]([\w-]+)['"]""")

# Vue 单文件组件：抽取 <script> 块
_正则_Vue脚本 = re.compile(r"""<script\b[^>]*>(.*?)</script>""", re.DOTALL)

# 惰性加载的 tree-sitter 解析器（线程安全双检锁）
_ts解析器 = None
_ts锁 = threading.Lock()


def _失败(错误码: str, 消息: str) -> 结果:
    return 结果.失败(错误码, 消息, 来源="语法索引")


def _空事实集() -> dict:
    return {
        "导入列表": [],
        "符号列表": [],
        "调用列表": [],
        "类属性列表": [],
        "字符串列表": [],
    }


# ══ Python ════════════════════════════════════════════════════════════════


class _Python事实收集器(ast.NodeVisitor):
    """遍历 Python AST，按类目产出有序语法事实。"""

    def __init__(self, 收集: dict):
        self.收集 = 收集
        self._当前类: str | None = None
        self._函数栈: list[str] = []
        self._事件序号 = 0

    def _追加(self, 类目: str, 条目: dict) -> dict:
        """按事件顺序登记一条事实（序号在同一文件内跨类目单调递增）。"""
        条目 = {"序号": self._事件序号, **条目}
        self._事件序号 += 1
        self.收集[类目].append(条目)
        return 条目

    def visit_Import(self, node: ast.Import) -> None:
        for 别名 in node.names:
            self._追加("导入列表", {
                "路径": 别名.name,
                "导入名": 别名.name,
                "行号": node.lineno,
            })
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.module is None:
            self.generic_visit(node)
            return
        for 别名 in node.names:
            self._追加("导入列表", {
                "路径": node.module,
                "导入名": f"{node.module}.{别名.name}",
                "行号": node.lineno,
            })
        self.generic_visit(node)

    def visit_FunctionDef(self, node) -> None:
        前缀 = f"{self._当前类}." if self._当前类 else ""
        完整名称 = f"{前缀}{node.name}"
        self._追加("符号列表", {
            "名称": 完整名称,
            "类别": "function",
            "行号": node.lineno,
            "结束行号": node.end_lineno or node.lineno,
        })
        self._函数栈.append(完整名称)
        for 子节点 in ast.walk(node):
            self._遍历表达式(子节点)
        self._函数栈.pop()

    def visit_AsyncFunctionDef(self, node) -> None:
        self.visit_FunctionDef(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._追加("符号列表", {
            "名称": node.name,
            "类别": "class",
            "行号": node.lineno,
            "结束行号": node.end_lineno or node.lineno,
        })
        for 子节点 in node.body:
            if isinstance(子节点, (ast.Assign, ast.AnnAssign)):
                self.处理分配(子节点)
        旧类 = self._当前类
        self._当前类 = node.name
        self.generic_visit(node)
        self._当前类 = 旧类

    def _遍历表达式(self, node: ast.AST) -> None:
        if isinstance(node, ast.Call):
            self.处理调用(node)
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            self.处理分配(node)

    def 处理调用(self, node: ast.Call) -> None:
        func_name = self.获取调用名称(node)
        if not func_name:
            return
        位置字符串 = []
        for 序号, 参数 in enumerate(node.args):
            if isinstance(参数, ast.Constant) and isinstance(参数.value, str):
                位置字符串.append({"序号": 序号, "值": 参数.value})
        关键字字符串 = []
        for 关键字 in node.keywords:
            值节点 = 关键字.value
            if isinstance(值节点, ast.Constant) and isinstance(值节点.value, str):
                关键字字符串.append({"名称": 关键字.arg, "值": 值节点.value})
        self._追加("调用列表", {
            "函数名": func_name,
            "行号": node.lineno if hasattr(node, "lineno") else 0,
            "位置字符串": 位置字符串,
            "关键字字符串": 关键字字符串,
            "所在函数": self._函数栈[-1] if self._函数栈 else None,
        })

    def 获取调用名称(self, node: ast.Call) -> str | None:
        if isinstance(node.func, ast.Name):
            return node.func.id
        if isinstance(node.func, ast.Attribute):
            片段: list[str] = []
            对象 = node.func
            while isinstance(对象, ast.Attribute):
                片段.append(对象.attr)
                对象 = 对象.value
            if isinstance(对象, ast.Name):
                片段.append(对象.id)
            片段.reverse()
            return ".".join(片段)
        return None

    def 处理分配(self, node) -> None:
        """提取字符串型类属性赋值（目标为简单名字）。"""
        值节点 = node.value
        if isinstance(值节点, ast.Call):
            self.处理调用(值节点)
            return
        if not isinstance(值节点, ast.Constant) or not isinstance(值节点.value, str):
            return
        目标列表 = node.targets if isinstance(node, ast.Assign) else [node.target]
        for 目标 in 目标列表:
            if isinstance(目标, ast.Name):
                self._追加("类属性列表", {
                    "名称": 目标.id,
                    "值": 值节点.value,
                    "行号": node.lineno if hasattr(node, "lineno") else 0,
                })


def _解析Python事实(代码文本: str) -> dict:
    """ast 解析 Python 源码，产出语法事实（不抛异常）。"""
    tree = ast.parse(代码文本)
    收集 = _空事实集()
    访问器 = _Python事实收集器(收集)
    访问器.visit(tree)
    # 模块级顶层表达式 / 赋值（不在任何函数 / 类体内）
    for 节点 in ast.iter_child_nodes(tree):
        if isinstance(节点, (ast.Expr, ast.Assign, ast.AnnAssign)):
            for 子节点 in ast.walk(节点):
                访问器._遍历表达式(子节点)
    return 收集


# ══ TypeScript / Vue ══════════════════════════════════════════════════════


def _确保TS解析器():
    """惰性初始化 tree-sitter TypeScript 解析器；不可用返回 None。"""
    global _ts解析器
    if _ts解析器 is not None:
        return _ts解析器
    with _ts锁:
        if _ts解析器 is not None:
            return _ts解析器
        try:
            import tree_sitter_typescript
            from tree_sitter import Language, Parser
        except ImportError:
            _ts解析器 = False
            return None
        try:
            语言 = Language(tree_sitter_typescript.language_typescript())
            _ts解析器 = Parser(语言)
        except Exception:
            _ts解析器 = False
            return None
    return _ts解析器


def _TS字符串值(节点, 源码: bytes) -> str:
    """提取 tree-sitter 字符串节点的内部值。"""
    文本 = 源码[节点.start_byte:节点.end_byte].decode()
    if len(文本) >= 2:
        if 文本[0] in ("'", '"') and 文本[-1] == 文本[0]:
            return 文本[1:-1]
        if 文本[0] == "`" and 文本[-1] == "`":
            return 文本[1:-1]
    return 文本


def _TS获取调用路径(节点, 源码: bytes) -> list[str] | None:
    """解析点号调用路径，如 platform.modules.call → ['platform','modules','call']。"""
    if 节点.type == "identifier":
        return [源码[节点.start_byte:节点.end_byte].decode()]
    if 节点.type == "member_expression":
        对象 = 节点.child_by_field_name("object")
        属性 = 节点.child_by_field_name("property")
        if 对象 and 属性:
            对象片段 = _TS获取调用路径(对象, 源码)
            属性名 = 源码[属性.start_byte:属性.end_byte].decode()
            if 对象片段:
                return 对象片段 + [属性名]
            return [属性名]
    return None


def _TS获取参数字符串(参数节点, 源码: bytes) -> list[str]:
    """从调用参数节点提取字符串字面量参数（含模板字符串）。"""
    结果列表: list[str] = []
    for 子节点 in 参数节点.children:
        if 子节点.type in ("string", "template_string"):
            值 = _TS字符串值(子节点, 源码)
            if 值:
                结果列表.append(值)
    return 结果列表


def _遍历TS类正文(正文节点, 源码: bytes, 类名: str, 收集: dict) -> None:
    """遍历类体内的方法定义（嵌套类递归，与调用方现实现一致）。"""
    for 子节点 in 正文节点.children:
        if 子节点.type == "method_definition":
            名称节点 = 子节点.child_by_field_name("name")
            if 名称节点:
                方法名 = 源码[名称节点.start_byte:名称节点.end_byte].decode()
                完整名称 = f"{类名}.{方法名}"
                收集["符号列表"].append({
                    "名称": 完整名称,
                    "类别": "method",
                    "行号": 名称节点.start_point[0] + 1,
                    "结束行号": 子节点.end_point[0] + 1,
                })
        for 孙节点 in 子节点.children:
            if 孙节点.type == "class_declaration":
                _遍历TS树(孙节点, 源码, 收集)


def _遍历TS树(节点, 源码: bytes, 收集: dict) -> None:
    """递归遍历 tree-sitter AST，收集导入 / 定义 / 调用 / 字符串事实。"""
    if 节点.type == "import_statement":
        来源子句 = 节点.child_by_field_name("source")
        if 来源子句 and 来源子句.type == "string":
            规格 = _TS字符串值(来源子句, 源码)
            if 规格:
                收集["导入列表"].append({
                    "路径": 规格,
                    "行号": 节点.start_point[0] + 1,
                    "类别": "import",
                })

    elif 节点.type == "export_statement":
        来源子句 = 节点.child_by_field_name("source")
        if 来源子句 and 来源子句.type == "string":
            规格 = _TS字符串值(来源子句, 源码)
            if 规格:
                收集["导入列表"].append({
                    "路径": 规格,
                    "行号": 节点.start_point[0] + 1,
                    "类别": "export-from",
                })

    elif 节点.type == "function_declaration":
        名称节点 = 节点.child_by_field_name("name")
        if 名称节点:
            名称 = 源码[名称节点.start_byte:名称节点.end_byte].decode()
            收集["符号列表"].append({
                "名称": 名称,
                "类别": "function",
                "行号": 名称节点.start_point[0] + 1,
                "结束行号": 节点.end_point[0] + 1,
            })

    elif 节点.type == "lexical_declaration":
        for 子节点 in 节点.children:
            if 子节点.type == "variable_declarator":
                名称节点 = 子节点.child_by_field_name("name")
                值节点 = 子节点.child_by_field_name("value")
                if (名称节点 and 值节点
                        and 值节点.type in ("arrow_function", "function_expression")):
                    名称 = 源码[名称节点.start_byte:名称节点.end_byte].decode()
                    收集["符号列表"].append({
                        "名称": 名称,
                        "类别": "function",
                        "行号": 名称节点.start_point[0] + 1,
                        "结束行号": 子节点.end_point[0] + 1,
                    })

    elif 节点.type == "class_declaration":
        名称节点 = 节点.child_by_field_name("name")
        类名 = ""
        if 名称节点:
            类名 = 源码[名称节点.start_byte:名称节点.end_byte].decode()
            收集["符号列表"].append({
                "名称": 类名,
                "类别": "class",
                "行号": 名称节点.start_point[0] + 1,
                "结束行号": 节点.end_point[0] + 1,
            })
        正文节点 = 节点.child_by_field_name("body")
        if 正文节点:
            _遍历TS类正文(正文节点, 源码, 类名, 收集)

    elif 节点.type == "call_expression":
        函数节点 = 节点.child_by_field_name("function")
        if 函数节点:
            片段 = _TS获取调用路径(函数节点, 源码)
            if 片段:
                参数字符串: list[str] = []
                参数节点 = 节点.child_by_field_name("arguments")
                if 参数节点:
                    参数字符串 = _TS获取参数字符串(参数节点, 源码)
                收集["调用列表"].append({
                    "函数名": ".".join(片段),
                    "行号": 节点.start_point[0] + 1,
                    "参数字符串": 参数字符串,
                })

    elif 节点.type == "string":
        值 = _TS字符串值(节点, 源码)
        if 值:
            收集["字符串列表"].append({
                "值": 值,
                "行号": 节点.start_point[0] + 1,
            })

    for 子节点 in 节点.children:
        _遍历TS树(子节点, 源码, 收集)


def _解析TS正则降级(源代码: str, 收集: dict) -> None:
    """tree-sitter 不可用时的最小正则解析（导入 + 平台调用）。"""
    for 匹配 in _正则_具名导入.finditer(源代码):
        收集["导入列表"].append({
            "路径": 匹配.group(1),
            "行号": 源代码[:匹配.start()].count("\n") + 1,
            "类别": "import",
        })
    for 匹配 in _正则_默认导入.finditer(源代码):
        收集["导入列表"].append({
            "路径": 匹配.group(2),
            "行号": 源代码[:匹配.start()].count("\n") + 1,
            "类别": "import",
        })
    for 匹配 in _正则_平台调用.finditer(源代码):
        收集["调用列表"].append({
            "函数名": "platform.modules.call",
            "行号": 源代码[:匹配.start()].count("\n") + 1,
            "参数字符串": [匹配.group(1), 匹配.group(2)],
        })


def _解析脚本来源(源代码: str, 收集: dict) -> str:
    """解析一段 TypeScript 源码，返回实际使用的解析器名。"""
    解析器 = _确保TS解析器()
    if not 解析器:
        _解析TS正则降级(源代码, 收集)
        return "正则降级"
    源码字节 = 源代码.encode("utf-8")
    树 = 解析器.parse(源码字节)
    _遍历TS树(树.root_node, 源码字节, 收集)
    return "tree-sitter"


def _解析脚本事实(代码文本: str, 语法集: str) -> dict:
    """解析 TypeScript / Vue 源码，产出语法事实（不抛异常）。"""
    收集 = _空事实集()
    if 语法集 == "vue":
        解析器名 = "tree-sitter"
        for 匹配 in _正则_Vue脚本.finditer(代码文本):
            # 每个 <script> 块独立从第 1 行编号（与调用方现实现一致）
            解析器名 = _解析脚本来源(匹配.group(1), 收集)
    else:
        解析器名 = _解析脚本来源(代码文本, 收集)
    收集.pop("类属性列表")
    收集["解析器"] = 解析器名
    return 收集


# ══ 对外能力 ══════════════════════════════════════════════════════════════


def 解析Python语法(代码文本: str) -> 结果:
    """把 Python 源码切成有序语法事实集。"""
    if not isinstance(代码文本, str):
        return _失败("参数不合法", "代码文本 必须是字符串")
    try:
        收集 = _解析Python事实(代码文本)
    except SyntaxError as 错误:
        return _失败("语法错误", f"{错误.msg} (行 {错误.lineno})")
    except Exception as 错误:
        return _失败("解析失败", f"{type(错误).__name__}: {错误}")
    return 结果.成功结果(收集)


def 解析脚本语法(代码文本: str, 语法集: str = "typescript") -> 结果:
    """把 TypeScript / Vue 源码切成有序语法事实集。"""
    if not isinstance(代码文本, str):
        return _失败("参数不合法", "代码文本 必须是字符串")
    if 语法集 not in ("typescript", "vue"):
        return _失败("参数不合法", f"语法集 必须是 typescript 或 vue，收到 {语法集!r}")
    try:
        收集 = _解析脚本事实(代码文本, 语法集)
    except Exception as 错误:
        return _失败("解析失败", f"{type(错误).__name__}: {错误}")
    return 结果.成功结果(收集)


def _解析一条(代码文本, 语法集) -> 结果:
    if 语法集 in (None, "", "python"):
        return 解析Python语法(代码文本)
    if 语法集 in ("typescript", "ts", "tsx"):
        return 解析脚本语法(代码文本, "typescript")
    if 语法集 == "vue":
        return 解析脚本语法(代码文本, "vue")
    return _失败("参数不合法", f"未知语法集: {语法集!r}")


def 批量解析语法(文件列表: list) -> 结果:
    """批量解析：按语法集分派，结果严格保序，单文件失败隔离。"""
    if not isinstance(文件列表, list):
        return _失败("参数不合法", "文件列表 必须是列表")
    结果列表: list[dict] = []
    失败列表: list[dict] = []
    for 序号, 条目 in enumerate(文件列表):
        if not isinstance(条目, dict):
            失败列表.append({
                "路径": "", "错误码": "参数不合法",
                "错误说明": f"第 {序号} 项不是字典",
            })
            continue
        路径 = 条目.get("路径") or ""
        单条 = _解析一条(条目.get("代码文本"), 条目.get("语法集"))
        if 单条.成功:
            结果列表.append({"路径": 路径, **单条.值})
        else:
            失败列表.append({
                "路径": 路径,
                "错误码": 单条.错误码,
                "错误说明": 单条.错误说明,
            })
    return 结果.成功结果({"结果列表": 结果列表, "失败列表": 失败列表})
