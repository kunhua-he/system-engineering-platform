"""口径读取：注册口径 / 契约口径 的 AST 静态读取

本模块是 `开发工具/契约编译/漂移检测.py` 的**内部搬家**产物（对外符号零变化）：
`漂移检测.py` 仍是契约漂移门禁的对外唯一门面，全部公开符号依然从那里导入；
本模块只承载实现，**不构成第二份判据**。原有文档串与注释一字未改。

依赖：`实现定位._系统根` 不涉及；仅 `公共契约.基础类型.逻辑类型`。
"""


from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any

from 公共契约.基础类型.逻辑类型 import 真, 假

# ---- 对外符号回托 ----
# 本块从 `漂移检测.py` 原地搬来时用到这些名；`漂移检测.<名>` 是全仓调用方与源码文本
# 依赖的对外面（多处注释与测试直接 grep `开发工具/契约编译/漂移检测.<符号>`），
# 故在此显式回托成模块级属性。仅 re-export，无任何语义改动。
真 = 真
假 = 假

class _未解析哨兵类型:
    """AST 静态求值的「不可判定」哨兵类型（与 None / 空串等合法值区分开）。"""


未解析哨兵 = _未解析哨兵类型()
"""不可静态判定的表达式的唯一哨兵值（单例，用 `is` 比较）。"""
def _静态字面量(节点: ast.AST, 绑定: dict[str, Any], 深度: int = 0) -> Any:
    """把 AST 表达式求值为字面量；不可静态判定的返回 未解析哨兵。

    绑定表里既可能是字面量，也可能是**赋值语句的 AST 节点**（注册表四元组里含
    函数引用，预先整体求值必然失败，所以赋值只登记节点、按需解引用）。
    """
    if 深度 > 8:
        return 未解析哨兵
    if isinstance(节点, ast.Constant):
        return 节点.value
    if isinstance(节点, ast.Name):
        if 节点.id not in 绑定:
            return 未解析哨兵
        值 = 绑定[节点.id]
        if isinstance(值, ast.AST):
            return _静态字面量(值, 绑定, 深度 + 1)
        return 值
    if isinstance(节点, (ast.List, ast.Tuple)):
        值表 = []
        for 元素 in 节点.elts:
            值 = _静态字面量(元素, 绑定, 深度 + 1)
            if 值 is 未解析哨兵:
                return 未解析哨兵
            值表.append(值)
        return tuple(值表) if isinstance(节点, ast.Tuple) else 值表
    if isinstance(节点, ast.Dict):
        字典: dict[Any, Any] = {}
        for 键节点, 值节点 in zip(节点.keys, 节点.values):
            if 键节点 is None:
                return 未解析哨兵
            键 = _静态字面量(键节点, 绑定, 深度 + 1)
            值 = _静态字面量(值节点, 绑定, 深度 + 1)
            if 键 is 未解析哨兵 or 值 is 未解析哨兵:
                return 未解析哨兵
            字典[键] = 值
        return 字典
    if isinstance(节点, ast.Subscript):
        # `返回表[能力id]` 形态：先解析容器（多为模块内字面量表），再按键取值。
        容器 = _静态字面量(节点.value, 绑定, 深度 + 1)
        if 容器 is 未解析哨兵 or not isinstance(容器, (dict, list, tuple)):
            return 未解析哨兵
        键 = _静态字面量(节点.slice, 绑定, 深度 + 1)
        if 键 is 未解析哨兵:
            return 未解析哨兵
        try:
            return 容器[键]
        except (KeyError, IndexError, TypeError):
            return 未解析哨兵
    return 未解析哨兵
def _参数项(项: dict[str, Any]) -> dict[str, Any]:
    """注册参数项归一：`名称`/`类型`必留，`默认值`/`必填`**写了才留**。

    「没写」与「写了 None」必须分开：前者是漏声明（本仓存量 152/69 条，见
    注册口径存量基线），后者是显式口径，参与硬比对。所以这里不能用 `.get` 拉平。
    """
    结果: dict[str, Any] = {"名称": str(项.get("名称", "")), "类型": str(项.get("类型") or "")}
    for 键 in ("默认值", "必填"):
        if 键 in 项:
            结果[键] = 项[键]
    return 结果
def _注册参数表(节点: ast.AST, 绑定: dict[str, Any]) -> list[dict[str, Any]] | None:
    """注册 `参数=` 的四种实际写法 → [{名称,类型[,默认值,必填]}]；不全静态可判定时返回 None。

    写法：① [{名称,类型[,默认值,必填]}]；② [("名称","类型")]；③ ["名称", ...]（只有名）；
    ④ [{...} for 参数名, 类型 in 参数类型表]（列表推导 + 循环变量表）。
    写法 ②③ 天然只有名字，即「默认值/必填未声明」，由比对侧按漏声明分桶。
    """
    if isinstance(节点, ast.ListComp):
        return _列表推导参数表(节点, 绑定)
    值 = _静态字面量(节点, 绑定)
    if 值 is 未解析哨兵 or not isinstance(值, (list, tuple)):
        return None
    表: list[dict[str, Any]] = []
    for 项 in 值:
        if isinstance(项, dict) and "名称" in 项:
            表.append(_参数项(项))
        elif isinstance(项, str):
            表.append({"名称": 项, "类型": ""})
        elif isinstance(项, tuple) and len(项) == 2:
            表.append({"名称": str(项[0]), "类型": str(项[1])})
        else:
            return None
    return 表
def _列表推导参数表(节点: ast.ListComp, 绑定: dict[str, Any]) -> list[dict[str, Any]] | None:
    """`[{名称,类型[,默认值,必填]} for 参数名, 类型 in 参数类型表]` 形态（前端描述型包装用）。"""
    if len(节点.generators) != 1:
        return None
    生成器 = 节点.generators[0]
    序列 = _静态字面量(生成器.iter, 绑定)
    if 序列 is 未解析哨兵 or not isinstance(序列, (list, tuple)):
        return None
    if isinstance(生成器.target, ast.Tuple):
        目标名 = [元素.id for 元素 in 生成器.target.elts if isinstance(元素, ast.Name)]
    elif isinstance(生成器.target, ast.Name):
        目标名 = [生成器.target.id]
    else:
        return None
    if not 目标名:
        return None
    表: list[dict[str, Any]] = []
    for 元素 in 序列:
        子绑定 = dict(绑定)
        if isinstance(元素, (list, tuple)) and len(元素) == len(目标名):
            子绑定.update(dict(zip(目标名, 元素)))
        elif len(目标名) == 1:
            子绑定[目标名[0]] = 元素
        else:
            return None
        行 = _静态字面量(节点.elt, 子绑定)
        if isinstance(行, dict) and "名称" in 行:
            表.append(_参数项(行))
        elif isinstance(行, tuple) and len(行) == 2:
            表.append({"名称": str(行[0]), "类型": str(行[1])})
        else:
            return None
    return 表
def _收集注册调用(调用: ast.Call, 绑定: dict[str, Any], 表: dict[str, dict[str, Any]]) -> None:
    """从 注册表.注册(能力实现(...)) 调用里抽出注册口径。"""
    if isinstance(调用.func, ast.Name):
        函数名 = 调用.func.id
    elif isinstance(调用.func, ast.Attribute):
        函数名 = 调用.func.attr
    else:
        函数名 = ""
    关键字 = {关键字节点.arg: 关键字节点.value for 关键字节点 in 调用.keywords if 关键字节点.arg}
    if 函数名 == "注册":
        for 实参 in list(调用.args) + list(关键字.values()):
            if isinstance(实参, ast.Call):
                _收集注册调用(实参, 绑定, 表)
        return
    if 函数名 != "能力实现":
        return
    能力id = _静态字面量(关键字["能力id"], 绑定) if "能力id" in 关键字 else 未解析哨兵
    if not isinstance(能力id, str) or "." not in 能力id:
        return
    if "返回" not in 关键字:
        返回口径: str | None = ""      # 未传 返回 → 能力实现 默认空串，属真实空口径
    else:
        返回值 = _静态字面量(关键字["返回"], 绑定)
        返回口径 = 返回值 if isinstance(返回值, str) else None   # None=不可静态判定，跳过比对
    表[能力id] = {
        "返回": 返回口径,
        "参数": _注册参数表(关键字["参数"], 绑定) if "参数" in 关键字 else [],
    }
def _扫描注册语句(语句列表: list[ast.stmt], 绑定: dict[str, Any],
                表: dict[str, dict[str, Any]]) -> None:
    """按语句顺序维护名字绑定（赋值只登记节点），逐条抽出注册口径。

    `for 能力id, 函数, 参数表[, 返回类型|说明] in 表名:` 是仓库主流写法，且
    循环变量名各不相同（返回类型 / 返回 / 说明 / 参数名 / 参数类型表），所以必须
    按**位置绑定循环变量名**再解引用，不能假定第 4 项就是返回。
    """
    for 语句 in 语句列表:
        if isinstance(语句, ast.Assign) and len(语句.targets) == 1 \
                and isinstance(语句.targets[0], ast.Name):
            绑定[语句.targets[0].id] = 语句.value
        elif isinstance(语句, ast.For):
            序列节点: ast.AST = 语句.iter
            if isinstance(序列节点, ast.Name) and 序列节点.id in 绑定 \
                    and isinstance(绑定[序列节点.id], ast.AST):
                序列节点 = 绑定[序列节点.id]
            if isinstance(语句.target, ast.Tuple):
                目标名 = [元素.id for 元素 in 语句.target.elts
                         if isinstance(元素, ast.Name)]
            elif isinstance(语句.target, ast.Name):
                目标名 = [语句.target.id]
            else:
                目标名 = []
            元素表 = 序列节点.elts if isinstance(序列节点, ast.List) else None
            if 元素表 is None or len(目标名) < 2 or not 元素表:
                _扫描注册语句(语句.body, 绑定, 表)
                continue
            for 元素 in 元素表:
                子绑定 = dict(绑定)
                if isinstance(元素, ast.Tuple) and len(元素.elts) == len(目标名):
                    for 名, 值节点 in zip(目标名, 元素.elts):
                        子绑定[名] = 值节点
                elif isinstance(元素, ast.Dict):
                    for 键节点, 值节点 in zip(元素.keys, 元素.values):
                        键 = _静态字面量(键节点, 绑定) if 键节点 is not None else None
                        if isinstance(键, str):
                            子绑定[键] = 值节点
                _扫描注册语句(语句.body, 子绑定, 表)
        elif isinstance(语句, ast.If):
            _扫描注册语句(语句.body, dict(绑定), 表)
            _扫描注册语句(语句.orelse, dict(绑定), 表)
        elif isinstance(语句, ast.Expr) and isinstance(语句.value, ast.Call):
            _收集注册调用(语句.value, 绑定, 表)
#: 静态可求值的常量导入源：模块路径 → {模块内名: 常量值}。
#:
#: **为什么必须补这一层（2026-09-18 实测踩坑）**：正式代码的布尔位一律写中文
#: `真`／`假`（真源 `公共契约/基础类型/逻辑类型.py`：「两者在 Python 里是同一个对象」），
#: 而 `注册能力` 是真源 `逻辑类型` 的**导入方**——`from 公共契约.基础类型.逻辑类型 import 真, 假`
#: 是模块级 import。但本读取器的绑定表原先**只收赋值语句、不收 import**（`_扫描注册语句`
#: 从空字典起步），于是 `真`／`假` 全落「未解析哨兵」，参数表整块解析失败：
#: 实测 `模块库/开工编排/__init__.py` 迁成 `真/假` 后 4/4 能力「参数口径未解析」，
#: 改回裸布尔立刻恢复 —— 即「用中文口径」与「被门禁看见」原先**不可兼得**。
#: 把「已知常量模块的导入名」纳入种子绑定，两件事才同时成立。
#:
#: 只收**值被冻结在真源里**的常量，且**只在文件真的 import 了才绑**（见 `_导入常量绑定`）：
#: 文件没 import 却用 `真` 是 NameError 级真缺陷，必须继续落「未解析」，不许被这里掩盖。
_常量导入源: dict[str, dict[str, Any]] = {
    "公共契约.基础类型.逻辑类型": {"真": 真, "假": 假},
}
def 常量种子绑定() -> dict[str, Any]:
    """`_常量导入源` 展平后的「名字 → 常量值」种子绑定。

    给**只解析 `注册能力` 函数体**的调用方复用：它们拿到的是 `inspect.getsource(注册能力)`
    的函数体 AST，模块级 import 不在那棵树里，`真`／`假` 会落「未解析」。
    与 `_导入常量绑定` 的差别：这里不要求文件里出现 import 语句（调用方已确认源码
    上下文就是该模块本体）；生产路径一律用 `_导入常量绑定`，不用本函数。
    两份「名字 → 值」不会漂移：都从 `_常量导入源` 这一个字典派生。
    """
    种子: dict[str, Any] = {}
    for 常量表 in _常量导入源.values():
        种子.update(常量表)
    return 种子
def _导入常量绑定(树: ast.AST, 绑定: dict[str, Any]) -> None:
    """把「已知常量模块」的导入名绑进绑定表；非白名单模块一概不解析。

    不做通用 import 解析（那要先定位并读被导入模块，等于把「零依赖静态解析」换成
    一个依赖解析器）；这里只认 `_常量导入源` 列出的**值已冻结**的模块。别名形态
    （`import 真 as 是`）按 asname 绑定，与 `_静态字面量` 的 `ast.Name` 分支对齐。
    """
    for 节点 in ast.walk(树):
        if not isinstance(节点, ast.ImportFrom) or 节点.level or not 节点.module:
            continue
        常量表 = _常量导入源.get(节点.module)
        if not 常量表:
            continue
        for 别名 in 节点.names:
            if 别名.name in 常量表:
                绑定[别名.asname or 别名.name] = 常量表[别名.name]
def 读取注册口径(入口文件: Path) -> dict[str, dict[str, Any]]:
    """AST 抽取包入口 `注册能力` 的真实注册口径：能力id → {返回, 参数}。

    只静态解析，不导入实现模块（零副作用、零依赖）。仓库实测的三种数据流都覆盖：
    ① 四元组表 `("能力id", 函数, [参数表], "返回")`（循环变量名各异）；
    ② 三元组表 + 函数体内 `能力实现(..., 返回="结果")`；
    ③ inline `能力实现(能力id="…", 参数=[…], 返回="…")`。
    参数项里的 `默认值`/`必填` **只在注册侧真的写了键时才有该键**（写了才留，
    没写=漏声明，见 比对注册口径明细）。
    解析不出的（动态拼装）能力不进返回表，由 全仓注册口径统计 如实登记「未解析」。
    """
    if not 入口文件.is_file():
        return {}
    try:
        树 = ast.parse(入口文件.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError, OSError):
        return {}
    种子: dict[str, Any] = {}
    _导入常量绑定(树, 种子)
    表: dict[str, dict[str, Any]] = {}
    注册函数表 = [节点 for 节点 in ast.walk(树)
                if isinstance(节点, (ast.FunctionDef, ast.AsyncFunctionDef))
                and 节点.name == "注册能力"]
    if 注册函数表:
        for 函数 in 注册函数表:
            _扫描注册语句(函数.body, dict(种子), 表)
    else:
        _扫描注册语句(树.body, dict(种子), 表)
    return 表
def 读取契约口径(契约文件: Path) -> dict[str, dict[str, Any]]:
    """读 `能力契约/参数契约.json` → 能力id → {返回, 参数:[{名称,类型,默认值,必填}]}。

    契约侧 返回 有两种写法：`{"类型": "结果型", ...}` 与纯文本串（结构描述），
    两者都归一成「口径名」再比对。

    参数项保留 `默认值`/`必填`（本检测的新判据）：`必填` 缺失按契约惯例视作 True；
    `默认值` **只在契约真的写了键时保留**，以便与注册侧的「写了 null」区分开。
    """
    if not 契约文件.is_file():
        return {}
    try:
        数据 = json.loads(契约文件.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    表: dict[str, dict[str, Any]] = {}
    for 条目 in 数据.get("能力契约") or []:
        if not isinstance(条目, dict) or not 条目.get("能力id"):
            continue
        返回 = 条目.get("返回")
        返回口径 = str(返回.get("类型", "")) if isinstance(返回, dict) else str(返回 or "")
        参数列表: list[dict[str, Any]] = []
        for 项 in 条目.get("参数") or []:
            if not isinstance(项, dict):
                continue
            参数: dict[str, Any] = {"名称": str(项.get("名称", "")), "类型": str(项.get("类型") or ""),
                                  "必填": bool(项.get("必填", True))}
            if "默认值" in 项:
                参数["默认值"] = 项["默认值"]
            参数列表.append(参数)
        表[str(条目["能力id"])] = {"返回": 返回口径, "参数": 参数列表}
    return 表
