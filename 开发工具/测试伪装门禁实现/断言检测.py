"""硬规则 3：负面断言的强度下限（必须能区分结构 ∨ 真实副作用 ∨ 量级守卫）。

判据来源：`落点清单_02_测试体系.md` 硬规则 3 原文。

**合规（满足任一即算强断言）**：

1. `结构`：可与**期望值比对**的断言——肯定型断言（`assertEqual`/`assertIn`/
   `assertRegex`/`assertCountEqual`/`assertSequenceEqual`…）且实参里出现具体
   字面量（`"失败:工具缺失"`、`3`）或结构字段名（`错误码`/`问题列表`/`详细信息`）。
   变体 `结构(异常类型)`：`assertRaises(ValueError)` 式点名**具体异常类**的断言
   ——它就是「错误码」的异常版本，能区分结构；`assertRaises(Exception)` 不算。
   （`落点清单` 的「单列为违规」清单里没有 `assertRaises`，故按此判；要更严只需
   把 `强度_结构异常` 从 `强强度` 移除。）
2. `副作用`：真实副作用判定——实参里出现 `is_file`/`is_dir`/`exists`/
   `read_text`/`rglob`… 等真实文件系统读取。
3. `量级`：计数量级守卫——`assertGreater/assertGreaterEqual/assertLess/
   assertLessEqual/assertAlmostEqual` 且含数值。

**恒真（无条件违规）**，两种形态：①`assertEqual(x, x)`／`assertNotEqual(x, x)`
（两侧同一表达式；原文称「全仓唯一真恒真断言在
`测试中心/平台控制面/测试_工作包11_消费者契约注册表.py:61`」——2026-09-18 实测有 **2** 处，
另一处在 `测试中心/公共契约/测试_数据类.py:58`）；②`assertTrue(True)` 式字面量断言。

**弱断言（单列违规，条件：用例名含负面关键词）**：反断言（`assertFalse`/
`assertNotEqual(值,"未知")`/`assertNotIn`）、桩计数（`assert_not_called`/
`assert_called_once`——「`assertNotCalled` 单独出现不算」即指此类）、
生产自填布尔（`assertTrue(结果.成功)`）、形状断言（`assertTrue(callable(x))`）。
负面关键词沿用清单原文：拒绝/失败/阻断/幂等/并发/超时/回滚/删除。

用例名不含负面关键词、但断言全是弱断言的，只进「观察」计数（不判违规），
避免把规则 3 扩成「全仓断言风格检查」。用例零断言同样只进观察。

本模块只读 AST：不导入被测模块、不执行用例、不打印。
"""
from __future__ import annotations
from 公共契约.基础类型.逻辑类型 import 真, 假

import ast
from dataclasses import dataclass

from . import 命名空间

规则3名称 = "规则3"
违规类型_恒真 = "规则3·恒真断言"
违规类型_强度 = "规则3·负面断言强度不足"

负面关键词 = ("拒绝", "失败", "阻断", "幂等", "并发", "超时", "回滚", "删除")

强度_结构 = "结构"
强度_结构异常 = "结构(异常类型)"
强度_副作用 = "副作用"
强度_量级 = "量级"
强度_反断言 = "反断言"
强度_桩计数 = "桩计数"
强度_生产布尔 = "生产布尔"
强度_形状 = "形状"
强度_其他 = "其他"

强强度 = (强度_结构, 强度_结构异常, 强度_副作用, 强度_量级)

弱强度 = (强度_反断言, 强度_桩计数, 强度_生产布尔, 强度_形状, 强度_其他)

肯定结构名 = frozenset({
    "assertEqual", "assertIn", "assertRegex", "assertCountEqual", "assertIs",
    "assertIsNot", "assertMultiLineEqual", "assertSequenceEqual", "assertDictEqual",
    "assertListEqual", "assertSetEqual", "assertTupleEqual",
})
异常断言名 = frozenset({
    "assertRaises", "assertRaisesRegex", "assertWarns", "assertWarnsRegex", "assertLogs",
})
通用异常名 = ("Exception", "BaseException", "ExceptionGroup", "BaseExceptionGroup")
否定结构名 = frozenset({
    "assertNotEqual", "assertNotIn", "assertNotRegex", "assertNotIsInstance",
    "assertFalse", "assertIsNone", "assertNotAlmostEqual",
})
量级名 = frozenset({
    "assertGreater", "assertGreaterEqual", "assertLess", "assertLessEqual",
    "assertAlmostEqual",
})
桩计数名 = frozenset({
    "assert_called", "assert_called_once", "assert_called_with",
    "assert_called_once_with", "assert_any_call", "assert_has_calls",
    "assert_not_called",
})
形状调用名 = frozenset({"callable", "hasattr", "getattr", "isinstance", "issubclass", "id", "type"})
真值常量 = (True, False, None)


@dataclass(frozen=True)
class 断言记录:
    行号: int
    名称: str
    文本: str
    强度: str
    恒真: bool


@dataclass(frozen=True)
class 用例断言:
    相对路径: str
    类名: str
    方法名: str
    行号: int
    断言: tuple[断言记录, ...]
    助手: tuple[str, ...] = ()

    @property
    def 位置(self) -> str:
        return f"{self.类名}.{self.方法名}"


def _含字面量(节点: ast.AST) -> bool:
    for 子 in ast.walk(节点):
        if isinstance(子, ast.Constant) and 子.value not in 真值常量:
            return 真
    return 假


def _含结构字段(节点: ast.AST) -> bool:
    for 子 in ast.walk(节点):
        if isinstance(子, ast.Attribute) and 子.attr in 命名空间.结构字段名:
            return 真
        if isinstance(子, ast.Name) and 子.id in 命名空间.结构字段名:
            return 真
        if isinstance(子, ast.Subscript) and isinstance(子.slice, ast.Constant) \
                and 子.slice.value in 命名空间.结构字段名:
            return 真
    return 假


def _含副作用调用(节点: ast.AST) -> bool:
    for 子 in ast.walk(节点):
        if isinstance(子, ast.Call) and isinstance(子.func, ast.Attribute) \
                and 子.func.attr in 命名空间.副作用调用名:
            return 真
    return 假


def _含数值(节点: ast.AST) -> bool:
    for 子 in ast.walk(节点):
        if isinstance(子, ast.Constant) and isinstance(子.value, (int, float)) \
                and not isinstance(子.value, bool):
            return 真
    return 假


def _含形状调用(节点: ast.AST) -> bool:
    for 子 in ast.walk(节点):
        if isinstance(子, ast.Call):
            名 = ast.unparse(子.func).split(".")[-1]
            if 名 in 形状调用名:
                return 真
    return 假


def _是具体异常(节点: ast.AST | None) -> bool:
    """断言里点名的异常是**具体类**而不是通用 `Exception`。

    `assertRaises(ValueError)` 能区分结构（等于「错误码」的异常类型版本），
    `assertRaises(Exception)` 区分不出任何东西。`落点清单` 的「单列为违规」
    清单里没有 `assertRaises`，所以按本判据归入强断言；若后续要更严，把
    `强度_结构异常` 从 `强强度` 里移除即可（一处改动）。
    """
    if 节点 is None:
        return 假
    if isinstance(节点, ast.Tuple):
        return any(_是具体异常(元素) for 元素 in 节点.elts)
    if isinstance(节点, (ast.Name, ast.Attribute)):
        名 = ast.unparse(节点).split(".")[-1]
        return bool(名) and 名 not in 通用异常名
    return 假


def 分类断言(节点: ast.Call) -> tuple[str, str, bool]:
    """`(断言名, 强度, 是否恒真)`。"""
    名 = ast.unparse(节点.func).split(".")[-1]
    实参 = list(节点.args)
    恒真 = False
    if 名 in ("assertEqual", "assertNotEqual") and len(实参) >= 2:
        恒真 = ast.dump(实参[0]) == ast.dump(实参[1])
    if 名 in ("assertTrue", "assertFalse") and len(实参) == 1 and isinstance(实参[0], ast.Constant):
        恒真 = True
    if 名 in 桩计数名:
        return 名, 强度_桩计数, 恒真
    if 名 in ("assertTrue", "assertFalse", "assertIsNone", "assertIsNotNone", "assertIs"):
        目标 = 实参[0] if 实参 else None
        if 目标 is not None:
            if _含副作用调用(目标):
                return 名, 强度_副作用, 恒真
            if _含形状调用(目标) and not _含字面量(目标):
                return 名, 强度_形状, 恒真
            if _含字面量(目标) or _含结构字段(目标):
                return 名, 强度_结构, 恒真
            if isinstance(目标, ast.Name) and 目标.id in ("len",):
                return 名, 强度_其他, 恒真
        return 名, 强度_生产布尔, 恒真
    if 名 in 否定结构名:
        return 名, 强度_反断言, 恒真
    if 名 in 异常断言名:
        if _是具体异常(实参[0] if 实参 else None):
            return 名, 强度_结构异常, 恒真
        return 名, 强度_其他, 恒真
    if 名 in 量级名:
        if 实参 and _含数值(ast.Tuple(elts=list(实参))):
            return 名, 强度_量级, 恒真
        return 名, 强度_其他, 恒真
    if 名 in 肯定结构名:
        汇总 = ast.Tuple(elts=list(实参)) if 实参 else None
        if 汇总 is not None and (_含字面量(汇总) or _含结构字段(汇总) or _含副作用调用(汇总)):
            return 名, 强度_结构, 恒真
        return 名, 强度_其他, 恒真
    return 名, 强度_其他, 恒真


def _是断言(节点: ast.Call) -> bool:
    名 = ast.unparse(节点.func).split(".")[-1]
    return 名.startswith("assert")


def 收集用例(资产) -> list[用例断言]:
    """收集测试文件里每个 `def test_*` 的断言集合（含嵌套 with/subTest）。"""
    if not 资产.可用:
        return []
    结果: list[用例断言] = []

    def _遍历类(节点: ast.AST, 类名前缀: str) -> None:
        for 子 in ast.iter_child_nodes(节点):
            if isinstance(子, ast.ClassDef):
                _遍历类(子, 类名前缀 + 子.name + ".")
            elif isinstance(子, (ast.FunctionDef, ast.AsyncFunctionDef)) and 子.name.startswith("test"):
                记录: list[断言记录] = []
                助手: set[str] = set()
                for 内部 in ast.walk(子):
                    if isinstance(内部, ast.Call) and _是断言(内部):
                        名, 强度, 恒真 = 分类断言(内部)
                        try:
                            文本 = ast.unparse(内部)[:160]
                        except Exception:  # pragma: no cover
                            文本 = 名
                        记录.append(断言记录(行号=内部.lineno, 名称=名, 文本=文本,
                                             强度=强度, 恒真=恒真))
                    elif isinstance(内部, ast.Call) and isinstance(内部.func, ast.Attribute) \
                            and isinstance(内部.func.value, ast.Name) and 内部.func.value.id == "self":
                        助手名 = 内部.func.attr
                        if 助手名.startswith("_") or "断言" in 助手名 or "校验" in 助手名:
                            助手.add(f"self.{助手名}")
                记录.sort(key=lambda 条: 条.行号)
                结果.append(用例断言(
                    相对路径=资产.相对路径,
                    类名=类名前缀.rstrip("."),
                    方法名=子.name,
                    行号=子.lineno,
                    断言=tuple(记录),
                    助手=tuple(sorted(助手)),
                ))
            elif isinstance(子, (ast.FunctionDef, ast.AsyncFunctionDef)):
                pass

    _遍历类(资产.树, "")
    结果.sort(key=lambda 用例: (用例.相对路径, 用例.行号))
    return 结果


def 判定规则3(用例: 用例断言, 豁免表) -> tuple[list[dict], list[dict]]:
    """返回 `(违规列表, 观察列表)`。"""
    违规: list[dict] = []
    观察: list[dict] = []
    断言集 = 用例.断言
    if not 断言集:
        助手说明 = f"；疑似经断言助手 {'、'.join(用例.助手)}" if 用例.助手 else ""
        观察.append({
            "层级": "观察·用例无直接断言",
            "相对路径": 用例.相对路径, "行号": 用例.行号,
            "细节": f"{用例.位置} 不含任何 assert* 调用{助手说明}（未判定断言强度）",
        })
        return 违规, 观察
    恒真项 = [条 for 条 in 断言集 if 条.恒真]
    if 恒真项:
        理由 = 豁免表.查(规则3名称, 用例.相对路径, 用例.行号)
        if 理由:
            观察.append({
                "层级": "豁免·清单", "相对路径": 用例.相对路径, "行号": 用例.行号,
                "细节": f"{用例.位置} 恒真断言已豁免：{理由}",
            })
        else:
            违规.append({
                "层级": "违规", "类型": 违规类型_恒真,
                "相对路径": 用例.相对路径, "行号": 恒真项[0].行号,
                "细节": f"{用例.位置}：{'；'.join(条.文本 for 条 in 恒真项[:3])}",
                "建议": "把两侧换成「生产落盘/返回内容」与「期望值」的真实比对",
            })
    强项 = [条 for 条 in 断言集 if 条.强度 in 强强度]
    命中负面 = [词 for 词 in 负面关键词 if 词 in 用例.方法名]
    if not 强项 and 命中负面:
        理由 = 豁免表.查(规则3名称, 用例.相对路径, 用例.行号)
        if 理由:
            观察.append({
                "层级": "豁免·清单", "相对路径": 用例.相对路径, "行号": 用例.行号,
                "细节": f"{用例.位置} 强度不足已豁免：{理由}",
            })
        else:
            摘要 = "、".join(sorted({f"{条.强度}:{条.名称}" for 条 in 断言集}))
            违规.append({
                "层级": "违规", "类型": 违规类型_强度,
                "相对路径": 用例.相对路径, "行号": 用例.行号,
                "细节": (f"{用例.位置}（命中负面关键词 {命中负面}）：无强断言，"
                         f"现有断言 {摘要}"),
                "建议": ("补一条能区分结构的断言（错误码/问题列表内容/漂移字段名）、"
                         "真实副作用断言（文件/目录真实存在性）或量级守卫"
                         "（assertGreaterEqual(参与, 100)）"),
            })
    elif not 强项:
        观察.append({
            "层级": "观察·弱断言（用例名未含负面关键词）",
            "相对路径": 用例.相对路径, "行号": 用例.行号,
            "细节": f"{用例.位置}：断言全部为弱断言（{'、'.join(sorted({条.强度 for 条 in 断言集}))}）",
        })
    return 违规, 观察
