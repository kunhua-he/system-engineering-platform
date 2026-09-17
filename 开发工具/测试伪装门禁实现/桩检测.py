"""硬规则 1（禁 patch 被测对象自身 / 生产路径）与硬规则 2（一律 autospec）。

判据来源：`落点清单_02_测试体系.md` 第三节「问题 3：mock 假绿治理 —— 3 条可批量
落地的硬规则」的规则 1、规则 2。

规则 1 判据（本模块实现）：

1. AST 上收集全部 `mock.patch(...)` / `mock.patch.object(...)` / `patch(...)` 调用点，
   解析出**目标模块路径**：字符串目标取「去掉最后一段符号」的前缀，`patch.object`
   取宿主表达式的模块路径（`patch.object(模块.psycopg, "connect")` 前缀是
   `…实现.提供者`，属性链是 `psycopg`）。
2. 目标模块路径落在生产命名空间（见 `命名空间.生产根`）即命中；再分两级：
   `P1 被测模块本体`（与本文件 import 的生产模块精确相等 = patch 被测对象自身）、
   `P2 生产路径`（跨模块）。
3. 允许的例外只有两类，落地为两种豁免：
   - **`wraps=` 包住真实实现** → 自动豁免（规则 1 例外②）；
   - **依赖注入式替换** → 无法与「假桩」静态区分（两者都是传入一个值），所以
     不自动判例，只能经 `豁免清单.json` 按 `文件:行号` 人工登记（清单里写明理由）。
     同时每条违规带 `疑似依赖注入` 提示（`return_value=`/第 2 位置参数传真实对象
     引用，而非 `mock.Mock(...)`），方便一次性登记。
4. `patch.dict` 不针对生产对象（改的是映射内容），不参与规则 1。

规则 2 判据：任何 `patch`/`patch.object` 调用点缺 `autospec=True` 且缺 `spec=`/
`spec_set=` 即违规（`create_autospec` 生成的对象不在 patch 调用点上，另计）。
例外：`wraps=`（真实现 Spy，签名漂移会当场 `TypeError`，不是裸桩）与豁免清单。

本模块不导入被测模块、不执行用例、不打印；生产模块只被 `ast.parse` 读源码
（用于把符号分成「本体成员 / 依赖边界」，见 `命名空间.模块成员分类`）。
"""
from __future__ import annotations
from 公共契约.基础类型.逻辑类型 import 真, 假

import ast
from dataclasses import dataclass
from pathlib import Path

from . import 命名空间

桩形式_字符串目标 = "字符串目标"
桩形式_对象目标 = "对象目标"
桩形式_字典目标 = "字典目标"
桩形式_动态目标 = "动态目标"

规则1名称 = "规则1"
规则2名称 = "规则2"
违规类型_规则1本体 = "规则1·patch被测对象本体"
违规类型_规则1路径 = "规则1·patch生产路径"
违规类型_规则2 = "规则2·裸桩（缺 autospec=True/spec=）"


@dataclass(frozen=True)
class 桩调用点:
    """一个 patch 调用点的静态事实；判定结果由下游函数给出。"""

    相对路径: str
    行号: int
    形式: str
    调用文本: str
    目标: str
    模块路径: str
    符号链: str
    有autospec: bool
    有spec: bool
    有wraps: bool
    有显式new: bool
    真实对象替换: bool
    成员分类: str
    受测依据: str


def _调用名(节点: ast.AST) -> str:
    try:
        return ast.unparse(节点)
    except Exception:  # pragma: no cover
        return "<无法反解>"


def _是补丁基(节点: ast.AST) -> bool:
    """`mock.patch` 中的 `mock` 段（含 `unittest.mock`、别名 `m.patch`）。"""
    if isinstance(节点, ast.Attribute):
        return 节点.attr == "patch"
    if isinstance(节点, ast.Name):
        return 节点.id == "patch"
    return 假


def _补丁种类(节点: ast.AST, 导入表: dict[str, str]) -> str:
    """返回 `patch` / `object` / `dict` / `multiple` / `""`（不是补丁调用）。"""
    if isinstance(节点, ast.Name):
        路径 = 导入表.get(节点.id, "")
        if 节点.id == "patch" or 路径.endswith("mock.patch"):
            return "patch"
        if 节点.id == "patch" or 路径 == "unittest.mock.patch":
            return "patch"
        return ""
    if not isinstance(节点, ast.Attribute):
        return ""
    属性 = 节点.attr
    if 属性 == "patch":
        return "patch"
    if 属性 in ("object", "dict", "multiple") and _是补丁基(节点.value):
        return 属性
    return ""


def _常量文本(节点: ast.AST) -> str | None:
    if isinstance(节点, ast.Constant) and isinstance(节点.value, str):
        return 节点.value
    return None


def _显式new(节点: ast.Call) -> bool:
    """是否显式传了替换对象（第 2 位置参数 / `new=` / `new_callable=`）。"""
    if len(节点.args) > 1:
        return 真
    return any(键.arg in ("new", "new_callable") for 键 in 节点.keywords if 键.arg)


def _真实对象替换(节点: ast.Call, 形式: str) -> bool:
    """替换值是不是「真实对象引用」（依赖注入的形态证据，不是判例依据）。

    `patch("…", 假venv)`、`patch("…", return_value=假调用器())` 属于真实对象；
    `return_value=mock.Mock()`/`lambda …` 属于造桩。仅作提示，不参与豁免判定。
    """
    值节点: ast.AST | None = None
    if 形式 == 桩形式_对象目标:
        if len(节点.args) > 2:
            值节点 = 节点.args[2]
    elif 形式 == 桩形式_字符串目标 and len(节点.args) > 1:
        值节点 = 节点.args[1]
    if 值节点 is None:
        for 键 in 节点.keywords:
            if 键.arg in ("new", "new_callable"):
                值节点 = 键.value
                break
    if 值节点 is None:
        return 假
    if isinstance(值节点, ast.Call):
        名 = _调用名(值节点.func)
        return not (名.endswith("Mock") or 名.endswith("MagicMock") or 名 in ("mock",))
    if isinstance(值节点, ast.Lambda):
        return 假
    return isinstance(值节点, (ast.Name, ast.Attribute))


def 收集桩调用点(资产, 根: Path) -> list[桩调用点]:
    """收集一个测试文件里的全部 patch 调用点（纯静态，不导入被测模块）。"""
    if not 资产.可用:
        return []
    树 = 资产.树
    导入表 = 命名空间.收集导入表(树)
    受测导入 = 命名空间.受测模块集合(树)
    调用点列表: list[桩调用点] = []
    for 节点 in ast.walk(树):
        if not isinstance(节点, ast.Call):
            continue
        种类 = _补丁种类(节点.func, 导入表)
        if not 种类:
            continue
        kwargs = {键.arg: 键.value for 键 in 节点.keywords if 键.arg}
        有autospec = "autospec" in kwargs
        有spec = "spec" in kwargs or "spec_set" in kwargs
        有wraps = "wraps" in kwargs
        有显式new = _显式new(节点)
        目标 = ""
        模块路径 = ""
        符号链 = ""
        形式 = 桩形式_动态目标
        if 种类 == "dict":
            形式 = 桩形式_字典目标
            目标 = _调用名(节点)
        elif 种类 == "multiple":
            形式 = 桩形式_动态目标
            目标 = _调用名(节点)
        elif not 节点.args:
            形式 = 桩形式_动态目标
            目标 = _调用名(节点)
        elif 种类 == "patch":
            文本 = _常量文本(节点.args[0])
            if 文本 is None:
                形式 = 桩形式_动态目标
                目标 = _调用名(节点.args[0])
            else:
                形式 = 桩形式_字符串目标
                目标 = 文本
                模块路径, 符号链 = 命名空间.解析字符串目标(文本)
        else:  # patch.object
            宿主模块, 属性链 = 命名空间.解析宿主(节点.args[0], 导入表)
            属性名 = _常量文本(节点.args[1]) if len(节点.args) > 1 else None
            if 宿主模块:
                形式 = 桩形式_对象目标
                模块路径 = 宿主模块
                符号链 = f"{属性链}.{属性名 or '<动态属性名>'}" if 属性链 else (属性名 or "<动态属性名>")
                目标 = f"{宿主模块}.{符号链}"
            else:
                形式 = 桩形式_动态目标
                目标 = f"{_调用名(节点.args[0])}.{属性名 or '<动态属性名>'}"
        首符号 = 符号链.split(".")[0] if 符号链 else ""
        成员分类 = ""
        if 模块路径 and 命名空间.是生产命名空间(模块路径) and 首符号:
            成员分类 = 命名空间.模块成员分类(根, 模块路径, 首符号)
        依据 = ""
        if 模块路径 in 受测导入:
            依据 = "；".join(sorted(set(受测导入[模块路径]))[:2])
        调用点列表.append(桩调用点(
            相对路径=资产.相对路径,
            行号=节点.lineno,
            形式=形式,
            调用文本=_调用名(节点)[:160],
            目标=目标 or _调用名(节点)[:160],
            模块路径=模块路径,
            符号链=符号链,
            有autospec=有autospec,
            有spec=有spec,
            有wraps=有wraps,
            有显式new=有显式new,
            真实对象替换=_真实对象替换(节点, 形式),
            成员分类=成员分类,
            受测依据=依据,
        ))
    return 调用点列表


def 判定规则1(点: 桩调用点, 豁免表) -> dict | None:
    """返回违规/观察条目；不适用返回 None。"""
    if 点.形式 == 桩形式_字典目标:
        return None
    if not 点.模块路径:
        return {"层级": "观察·无法解析目标", "依据": f"目标不是生产模块路径：{点.目标}"}
    if not 命名空间.是生产命名空间(点.模块路径):
        if 命名空间.是范围外命名空间(点.模块路径):
            return {"层级": "观察·范围外命名空间", "依据": f"{点.模块路径} 不在硬规则 1 的生产根内"}
        return None
    if 点.有wraps:
        return {"层级": "豁免·wraps 包住真实实现", "依据": "规则 1 例外②：wraps= 保留真实实现"}
    理由 = 豁免表.查(规则1名称, 点.相对路径, 点.行号)
    if 理由:
        return {"层级": "豁免·清单", "依据": f"豁免清单：{理由}"}
    层级 = "P1 被测模块本体" if 点.受测依据 else "P2 生产路径"
    类型 = 违规类型_规则1本体 if 层级 == "P1 被测模块本体" else 违规类型_规则1路径
    子类型 = f"{层级}·{点.成员分类 or '未知成员'}"
    提示 = "；疑似依赖注入（替换值是真实对象引用，可登记豁免）" if 点.真实对象替换 else ""
    依据 = 点.受测依据 or "非本文件 import 的模块（跨模块生产路径）"
    建议 = (
        "改法：① 不 patch，改用真实依赖或真实副作用断言；② 必须替换时加 `wraps=` 包住真实实现；"
        "③ 确属依赖注入式替换 → 在 `开发工具/测试伪装门禁实现/豁免清单.json` 登记 `文件:行号` 与理由"
    )
    return {
        "层级": 层级,
        "子类型": 子类型,
        "类型": 类型,
        "细节": f"{点.形式} 目标={点.目标}；模块={点.模块路径 or '未解析'}；成员={点.成员分类 or '未判定'}；依据={依据}{提示}",
        "建议": 建议,
    }


def 判定规则2(点: 桩调用点, 豁免表) -> dict | None:
    """返回违规/合规/豁免条目；不适用返回 None。"""
    if 点.形式 == 桩形式_字典目标:
        return {"层级": "不适用·patch.dict", "依据": "patch.dict 改映射内容，无签名可校"}
    if 点.有autospec or 点.有spec:
        return {"层级": "合规·已有签名校验", "依据": "autospec=True / spec="}
    if 点.有wraps:
        return {"层级": "豁免·wraps 真实现 Spy", "依据": "wraps= 调真实实现，签名漂移会当场 TypeError"}
    理由 = 豁免表.查(规则2名称, 点.相对路径, 点.行号)
    if 理由:
        return {"层级": "豁免·清单", "依据": f"豁免清单：{理由}"}
    return {
        "层级": "违规",
        "类型": 违规类型_规则2,
        "细节": f"{点.形式} 目标={点.目标}；调用={点.调用文本}",
        "建议": (
            "改法：`mock.patch(\"…\", autospec=True, return_value=…)` 或 "
            "`mock.patch.object(模块, \"名\", autospec=True)`；存量按批次清零，"
            "基线豁免请在豁免清单登记（文件+行号，行号 null 表示整文件）"
        ),
    }


def 收集自动规格数(资产) -> int:
    """`create_autospec(...)` 调用数（合规形态的另一种写法，单独计数）。"""
    if not 资产.可用:
        return 0
    计数 = 0
    for 节点 in ast.walk(资产.树):
        if isinstance(节点, ast.Call):
            名 = _调用名(节点.func)
            if 名 == "create_autospec" or 名.endswith(".create_autospec"):
                计数 += 1
    return 计数
