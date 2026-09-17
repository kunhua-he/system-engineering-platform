"""漂移检测：契约与实现/产物的漂移拒绝。

全面漂移检测 实际执行：声明能力但没有实现（按实现目录内文件名匹配）、
参数顺序/类型漂移、返回结构漂移、错误码漂移（该两项需调用方传入 实现文件；
未传入且按 实现目录/{能力id末段}.py 猜不中时，显式登记「未执行」而非静默
通过——本仓实现文件是「一包一文件」，猜路径命中率实测为 0）、说明书与入口
不一致、契约破坏但未升级主版本。

**判据的两处口径修正（2026-09-18，实战 126 条缺口里 72 条是判据误判）**：

1. **入口定位**（`定位对外入口`）：对外实现 = `__init__.py` 的 `注册能力` 登记
   `实现函数` 指向的那份，依次按「包入口本文件（`_包装*` 闭包）→ 包入口导入目标 →
   实现目录索引（对外优先、`子进程*` 垫底）→ 转调跟随」定位，**绝不**「按文件名字典序
   取第一个同名函数」。原判据抓到的是子进程内部实现（`解码图像(字节b64)`）、
   `实现/` 里的内部同名方法、或别名/转调形态下的不存在函数 —— 实测 32 条正确实现
   被判「参数顺序漂移」、16 条被判「声明无实现」。
2. **参数名序**（`检测参数漂移`）：按「**契约必填参数的相对顺序**在入口签名里做
   **子序列匹配**」判。契约只登记对外参数面，实现签名里带默认值的可选参数
   （`项目id: str = ""`）是平台允许的实现自由度：入口是契约超集时**判对不判错**，
   多出的参数进 `只报列表`（`检测参数超出`），不进缺口计数；只有必填项**缺失**或
   相对顺序**颠倒**才判「参数顺序漂移」。原判据按参数表严格相等判，实测 56 条假红。
3. **同一根因只计一条**：声明无实现 / 转调目标未解析 命中时，不再连带报
   「入口文件缺失」「实现文件未定位」。转调跟不到目标时单独报「转调目标未解析」，
   与「真无实现」分开表述（判不出 ≠ 判绿，也不许混为一谈）。

其余检测器（检测实现无声明 / 检测生成文件被改 / 检测完整性摘要格式 /
检测能力定义漂移 / 检测注册口径漂移）供调用方按场景单独选用，不并入
全面漂移检测——检测实现无声明 见其文档串（函数级粒度无法区分能力入口与内部
辅助函数）；注册口径 见 检测注册口径漂移（按包整包比对，且必须先按
契约.归一注册口径 归一口径，否则约 300 条「注册 `结果` / 契约 `结果型`」的
写法噪声会把真问题淹掉）。

注册口径的判据含四类（详见 比对注册口径明细）：返回口径、参数名序、参数类型，
以及 **2026-09-17 新增的参数默认值 / 必填**。前三条是「写法漂移」，后两条才是
会让**合法调用被拒**或**对外公布的默认值与真实行为不符**的口径裂缝——加它们之前
「注册写 必填=True 而契约与实现都是可选」「注册默认值 0 而契约 45080」这类问题
全仓无人拦（提交 adf38428 修的三必填一默认值即此类）。默认值/必填的**漏声明**
是存量（注册侧普遍只写 名称+类型），故必须按 *注册口径存量基线.json* 分治：
基线命中=存量（只报）；基线外=新增（判红）；无基线时一律按存量只报，不判红。
"""

from __future__ import annotations

import ast
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from 公共契约.基础类型.逻辑类型 import 真, 假
from 公共契约.基础类型.类型表 import 正式类型表
from 公共契约.能力契约.契约 import 归一注册口径

生成标记 = "本文件由契约编译器自动生成，禁止手工修改"

顶层目录名 = ("支持库", "模块库", "技能库")
"""系统根下的顶层目录名：点分模块名首段 → 文件路径的解析起点。"""

内部实现文件名前缀 = ("子进程",)
"""`子进程*` 是**子进程内**的实现（协议侧），不是对外契约的对应物。

实测形态：`图像解码`/`Pillow提供者`/`PyMuPDF提供者`/`转写`/`MLXWhisper提供者` 的实现目录里
既有 `提供者.py`（对外实现，签名与契约一致）又有 `子进程解析.py`（子进程内协议实现，
签名是 `解码图像(字节b64)` 这类内部形态）。判据若按文件名字典序取第一个定义同名函数的
文件，就会抓错这份内部实现并把 32 条正确实现判成「参数顺序漂移」。对外实现的正确定位
键是**注册映射**（`__init__.py` 的 `注册能力` → `实现函数`），不是文件名。
"""


class _未解析哨兵类型:
    """AST 静态求值的「不可判定」哨兵类型（与 None / 空串等合法值区分开）。"""


未解析哨兵 = _未解析哨兵类型()
"""不可静态判定的表达式的唯一哨兵值（单例，用 `is` 比较）。"""


@dataclass
class 漂移结果:
    """一次漂移检测结果。

    `问题列表` = 判红项（进缺口计数/基线）；`只报列表` = **只报不判**的度量项
    （如「入口多出契约未登记的可选参数」——平台允许的实现自由度，判红会把正确实现
    判成缺陷，但默默丢掉又丢失了「契约与实现对不齐」的事实）。
    """

    问题列表: list[str] = field(default_factory=list)
    只报列表: list[str] = field(default_factory=list)

    @property
    def 成功(self) -> bool:
        return not self.问题列表


def 主版本号(版本: str) -> int:
    """提取主版本号（1.0.0 → 1）。"""
    try:
        return int(str(版本).split(".")[0])
    except (ValueError, AttributeError):
        return 0


def _实现候选代价(文件: Path) -> int:
    """同名函数出现在多个文件里时「谁更对外」的代价（越小越对外）。

    子进程内实现排最后：它是协议侧产物，签名是内部形态（`字节b64`），拿它比对
    对外契约必然假报漂移（见 `内部实现文件名前缀` 的说明）。
    """
    名 = 文件.stem
    包名 = 文件.parent.parent.name if 文件.parent.name == "实现" else 文件.parent.name
    if 名.startswith(内部实现文件名前缀):
        return 30
    if 名 == 包名:
        return 0
    if 名 == "提供者":
        return 1
    return 10


def _实现函数索引(实现目录: Path) -> dict[str, tuple[Path, ast.AST]]:
    """实现目录内 **函数名 → (文件, 函数节点)**（AST 静态索引，零副作用）。

    为什么必须有它：本仓实现文件普遍是「一包一文件」（`实现/包名.py` 内含该包全部
    能力），能力id 末段几乎**不等于文件名**。任何按文件名猜实现的判据在本仓命中率
    实测为 0 —— 要么全仓假红（按「文件名含能力名」判声明无实现），要么永久空跑
    （`检测返回漂移` 收到不存在的路径直接返回 None）。唯一可靠的定位键是**函数名**：
    注册入口 `能力实现(实现函数=函数名)` 与能力id 末段同名是编译器生成口径
    （`能力定义编译器.生成注册入口` 逐条 `from … import {能力id末段}`）。

    同名函数跨文件时按**对外优先**取（`_实现候选代价`）：文件名==包名 > `提供者.py` >
    其他 → `子进程*` 垫底。原实现按 `sorted(rglob)` 取**第一个**，实测抓到了
    `子进程解析.py` 那份内部实现。定位对外实现的**首选**键仍是注册映射
    （见 `定位对外入口`），本索引只是它的兜底。
    """
    表: dict[str, tuple[Path, ast.AST]] = {}
    代价表: dict[str, tuple[int, str]] = {}
    if not 实现目录.is_dir():
        return 表
    for 文件 in sorted(实现目录.rglob("*.py")):
        if "__pycache__" in 文件.parts:
            continue
        try:
            树 = ast.parse(文件.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError, OSError):
            continue
        for 节点 in ast.walk(树):
            if not isinstance(节点, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            代价 = (_实现候选代价(文件), str(文件))
            if 节点.name not in 表 or 代价 < 代价表[节点.name]:
                表[节点.name] = (文件, 节点)
                代价表[节点.name] = 代价
    return 表


def _定位实现文件(契约: dict[str, Any], 实现目录: Path,
                 实现索引: dict[str, tuple[Path, ast.AST]] | None = None) -> Path | None:
    """按「能力id 末段 == 函数名」定位实现文件；定位不到返回 None（不臆造路径）。

    **它只是兜底**：权威定位走 `定位对外入口`（注册映射 → 包入口导入目标 →
    实现目录索引 → 转调跟随）。调用方不知道包目录时才用本函数。
    """
    能力名 = 契约.get("能力id", "").split(".")[-1]
    if not 能力名:
        return None
    索引 = 实现索引 if 实现索引 is not None else _实现函数索引(实现目录)
    命中 = 索引.get(能力名)
    return 命中[0] if 命中 else None


def _系统根(包目录: Path) -> Path | None:
    """从包目录回溯系统根：**包相对路径的首段是 支持库/模块库/技能库** 的那个祖先。

    判定不能用「祖先目录名 ∈ 顶层目录名」，也不能用「祖先下有同名子目录」：本仓存在
    与顶层目录同名的包（`技能库/后端/技能库`），后者会把 `技能库/后端` 误当系统根。
    取**最外层**的合格祖先（真根），保证 `A.B.C → A/B/C.py` 的模块名解析起点正确。
    """
    命中: Path | None = None
    for 祖先 in (包目录, *包目录.parents):
        try:
            段列表 = 包目录.relative_to(祖先).parts
        except ValueError:
            continue
        if len(段列表) >= 2 and 段列表[0] in 顶层目录名:
            命中 = 祖先
    return 命中


def _模块名到文件(模块名: str, 系统根: Path | None) -> Path | None:
    """点分模块名 → 文件（`A.B.C` → `系统根/A/B/C.py`，包取 `__init__.py`）。

    只解析**本仓顶层名开头**的绝对模块名（`支持库`/`模块库`/`技能库`）；
    解析不到就返回 None（不臆造路径）。
    """
    if not 模块名 or 系统根 is None:
        return None
    段列表 = [段 for 段 in str(模块名).split(".") if 段]
    if len(段列表) < 2 or 段列表[0] not in 顶层目录名:
        return None
    候选 = 系统根.joinpath(*段列表).with_suffix(".py")
    if 候选.is_file():
        return 候选
    包入口 = 系统根.joinpath(*段列表) / "__init__.py"
    return 包入口 if 包入口.is_file() else None


def _文件模块名(文件: Path, 系统根: Path | None) -> str | None:
    """文件路径 → 点分模块名（`…/实现/PDF文本表格.py` → `….实现.PDF文本表格`）。"""
    if 系统根 is None:
        return None
    try:
        相对 = 文件.resolve().relative_to(系统根.resolve())
    except (ValueError, OSError):
        return None
    段列表 = list(相对.parts)
    if 段列表 and 段列表[-1] == "__init__.py":
        段列表 = 段列表[:-1]
    elif 段列表 and 段列表[-1].endswith(".py"):
        段列表[-1] = 段列表[-1][:-3]
    return ".".join(段列表) if 段列表 else None


def _文件内函数名集(文件: Path) -> set[str]:
    """文件内全部函数名（含嵌套闭包与方法）。解析失败返回空集。"""
    try:
        树 = ast.parse(文件.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError, OSError):
        return set()
    return {节点.name for 节点 in ast.walk(树)
            if isinstance(节点, (ast.FunctionDef, ast.AsyncFunctionDef))}


def _文件内定义(文件: Path, 函数名: str) -> bool:
    """文件里是否定义了该函数（AST 判定，不导入模块 = 零副作用）。"""
    return bool(函数名) and 函数名 in _文件内函数名集(文件)


def _包入口导入表(包目录: Path) -> dict[str, tuple[str, str]]:
    """包 `__init__.py` 的导入表：本地名 → (模块名, 模块内原名)。

    `from 支持库.…实现.提供者 import 解码图像` → `{"解码图像": ("支持库.…实现.提供者", "解码图像")}`。
    注册入口的 `实现函数=函数` 用的就是这张表里的**本地名**，所以「注册函数名 → 文件」
    必须经它解析，不能按文件名猜。
    """
    入口 = 包目录 / "__init__.py"
    if not 入口.is_file():
        return {}
    try:
        树 = ast.parse(入口.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError, OSError):
        return {}
    表: dict[str, tuple[str, str]] = {}
    for 节点 in ast.walk(树):
        if isinstance(节点, ast.ImportFrom) and 节点.module and not 节点.level:
            for 别名 in 节点.names:
                表.setdefault(别名.asname or 别名.name, (节点.module, 别名.name))
        elif isinstance(节点, ast.Import):
            for 别名 in 节点.names:
                if 别名.asname:
                    表.setdefault(别名.asname, (别名.name, ""))
    return 表


def _关键字字面量(调用: ast.Call, 键: str) -> str | None:
    """取调用里某关键字参数的字符串字面量（非字面量返回 None）。"""
    for 关键字 in 调用.keywords:
        if 关键字.arg == 键 and isinstance(关键字.value, ast.Constant) \
                and isinstance(关键字.value.value, str):
            return 关键字.value.value
    return None


def _关键字名(调用: ast.Call, 键: str) -> str | None:
    """取调用里某关键字参数引用的变量名（`实现函数=解析PDF` → `解析PDF`）。"""
    for 关键字 in 调用.keywords:
        if 关键字.arg == 键 and isinstance(关键字.value, ast.Name):
            return 关键字.value.id
    return None


def 包入口映射(包目录: Path | None) -> dict[str, dict[str, str]]:
    """包 `__init__.py` 里 `注册能力` 登记的 能力id → 实现函数名（**权威映射**）。

    为什么必须用它：`能力id 末段 == 实现函数名` 只是编译器的**多数**口径，本仓有两类
    合法例外，按末段猜名字必然假报「声明无实现 / 参数漂移」：
      ① **别名**：`文档转换支持库.PDF隔离提供者.解析PDF` 的实现函数是 `解析PDF隔离`；
         `内部.文字文档.解析` → `解析文字文档`；`技能库.技能索引.生成索引` → `生成技能索引`；
         `转写支持库.转写.检查可用性` → `检查转写可用性`；`系统核心支持库.资源管理.资源短锁`
         → `执行资源短锁`。
      ② **包装闭包**：`代码解析支持库.*` 的实现函数是 `注册能力` 内的 `_包装*`
         （**对外签名在那里**；`实现/代码解析.py` 里的同名方法是内部形态，参数面不同）。
    解析不出的（动态拼装，如 `实现函数=globals()[能力["能力id"].split(".")[-1]]`）不进返回表，
    由调用方按「能力id 末段」回退。
    """
    表: dict[str, dict[str, str]] = {}
    if 包目录 is None:
        return 表
    入口 = 包目录 / "__init__.py"
    if not 入口.is_file():
        return 表
    try:
        树 = ast.parse(入口.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError, OSError):
        return 表
    for 节点 in ast.walk(树):
        if isinstance(节点, ast.Call) and isinstance(节点.func, ast.Name) \
                and 节点.func.id == "能力实现":
            能力id = _关键字字面量(节点, "能力id")
            函数 = _关键字名(节点, "实现函数")
            if 能力id and 函数:
                表.setdefault(能力id, {"函数名": 函数, "来源": "注册表"})
        elif isinstance(节点, (ast.Tuple, ast.List)) and len(节点.elts) >= 2:
            # `for 能力id, 函数, 参数表, 说明 in [("能力id", 实现函数, …), …]` 的表格项
            首位, 次位 = 节点.elts[0], 节点.elts[1]
            if isinstance(首位, ast.Constant) and isinstance(首位.value, str) \
                    and "." in 首位.value and isinstance(次位, ast.Name):
                表.setdefault(首位.value, {"函数名": 次位.id, "来源": "注册表"})
    return 表


def _是sys模块下标(节点: ast.AST) -> ast.Subscript | None:
    """`sys.modules[...]` 形态的下标节点（不是则 None）。"""
    if (isinstance(节点, ast.Subscript)
            and isinstance(节点.value, ast.Attribute) and 节点.value.attr == "modules"
            and isinstance(节点.value.value, ast.Name) and 节点.value.value.id == "sys"):
        return 节点
    return None


def _下标键(节点: ast.AST, 绑定: dict[str, str]) -> str | None:
    """取 `sys.modules[…]` 的键：`__name__` 哨兵 / 字符串常量 / 已绑定的字符串变量。"""
    if isinstance(节点, ast.Constant) and isinstance(节点.value, str):
        return 节点.value
    if isinstance(节点, ast.Name):
        return "__name__" if 节点.id == "__name__" else 绑定.get(节点.id)
    return None


def _疑似模块名字符串(值: Any) -> bool:
    """是否是「点分模块名」形状的字符串（每段都是合法标识符，至少两段）。"""
    if not isinstance(值, str) or "." not in 值:
        return False
    return all(段.isidentifier() for 段 in 值.split("."))


def 模块替换标记(文件: Path) -> dict[str, Any] | None:
    """识别 **D-2 结构债收口**的「转调」形态：模块对象被替换成唯一实现。

    形态（实测两例：`文档转换支持库/PDF文本表格/实现/PDF文本表格.py`、
    `文档转换支持库/PDF隔离提供者/实现/子进程解析.py`）：
    ```python
    唯一实现名 = "支持库.适配层.pdfplumber提供者.实现.PDF文本表格"
    if 唯一实现名 not in sys.modules:      # 兜底：按文件路径显式载入
        … sys.modules[唯一实现名] = _模块 …
    sys.modules[__name__] = sys.modules[唯一实现名]
    ```
    这类文件里当然没有 `def 解析PDF`（函数在适配层那份里），判据按 AST 找函数名必然
    报「声明无实现」。返回 `{"自替换": bool, "候选模块": [...] }`；文件里没有
    `sys.modules[…] =` 赋值时返回 None（= 不是转调文件，不许当转调放行）。
    """
    try:
        树 = ast.parse(文件.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError, OSError):
        return None
    本模块名 = _文件模块名(文件, _系统根(文件))
    绑定: dict[str, str] = {}
    for 节点 in ast.walk(树):
        if isinstance(节点, ast.Assign) and len(节点.targets) == 1 \
                and isinstance(节点.targets[0], ast.Name) \
                and isinstance(节点.value, ast.Constant) \
                and isinstance(节点.value.value, str):
            绑定[节点.targets[0].id] = 节点.value.value
    自替换 = False
    命中替换赋值 = False
    候选: list[str] = []
    for 节点 in ast.walk(树):
        if not isinstance(节点, ast.Assign):
            continue
        目标 = [项 for 项 in 节点.targets if _是sys模块下标(项) is not None]
        if not 目标:
            continue
        命中替换赋值 = True
        键 = _下标键(目标[0].slice, 绑定)
        if 键 == "__name__" or (本模块名 is not None and 键 == 本模块名):
            自替换 = True
        取值 = 节点.value
        取值下标 = _是sys模块下标(取值)
        if 取值下标 is not None:
            名 = _下标键(取值下标.slice, 绑定)
            if 名:
                候选.append(名)
        elif isinstance(取值, ast.Name) and 取值.id in 绑定:
            候选.append(绑定[取值.id])
    if not 命中替换赋值:
        return None
    # 兜底候选：文件里出现的所有「点分模块名」字符串（含 `唯一实现名 = "…"` 这类绑定）
    for 值 in list(绑定.values()):
        if _疑似模块名字符串(值):
            候选.append(值)
    去重候选 = [名 for 名 in dict.fromkeys(候选) if _疑似模块名字符串(名)]
    return {"自替换": 自替换, "候选模块": 去重候选}


def _跟随转调(文件: Path, 函数名: str, 系统根: Path | None) -> tuple[Path | None, str]:
    """跟随「模块对象替换」到被替换模块去定位函数。

    返回 `(目标文件, 说明)`：
      · 跟到了 → 目标文件非 None；
      · 是转调但**跟不到**（目标模块名非静态/文件不存在/目标里也没有该函数）→
        目标文件 None + 非空说明（调用方据此报「转调目标未解析」，与「真无实现」分开）；
      · 根本不是转调 → `(None, "")`。
    """
    标记 = 模块替换标记(文件)
    if 标记 is None:
        return None, ""
    if not 标记.get("自替换"):
        # 有 sys.modules 改写但不是「替换本模块」（如主进程注释里的契约注入）→ 不当转调
        return None, ""
    候选 = list(标记.get("候选模块") or [])
    for 名 in 候选:
        目标 = _模块名到文件(名, 系统根)
        if 目标 is not None and _文件内定义(目标, 函数名):
            return 目标, f"转调跟随 {文件} → {名}（该模块对象替换的唯一实现）"
    已解析文件 = [str(_模块名到文件(名, 系统根)) for 名 in 候选]
    return None, (f"转调文件 {文件} 把本模块对象替换为唯一实现，但跟随不到目标"
                f"（候选模块 {候选 or '（未解析出静态模块名）'}；"
                f"可解析到文件 {[项 for 项 in 已解析文件 if 项 != 'None'] or '无'}；"
                f"目标里也未定义函数 {函数名}）")


@dataclass
class 对外入口定位:
    """一次「能力 → 对外实现函数所在文件」的定位结果。"""

    文件: Path | None = None
    函数名: str = ""
    来源: str = ""
    状态: str = "未定位"        # 已定位 / 转调未解析 / 未定位
    详情: str = ""


def 定位对外入口(契约: dict[str, Any], *, 实现目录: Path,
                 包目录: Path | None = None,
                 实现索引: dict[str, tuple[Path, ast.AST]] | None = None,
                 系统根: Path | None = None) -> 对外入口定位:
    """定位能力的**对外实现**（注册映射优先，绝不「按文件名猜第一个同名函数」）。

    定位顺序（每一档都要「文件里真的有那个函数」才算命中）：
      ① **注册映射**：`__init__.py` 的 `注册能力` 登记 `能力id → 实现函数`（别名/包装闭包靠它）；
      ② **包入口本文件**：包装函数写在 `__init__.py` 里（`_包装解析代码文件`）；
      ③ **包入口导入目标**：`from 支持库.…实现.提供者 import 检查转写可用性` → 该文件；
      ④ **实现目录索引**：同名函数（对外优先，`子进程*` 垫底）；
      ⑤ **转调跟随**：命中文件里没有该函数、但它把本模块对象替换成唯一实现时，
         跟到被替换模块（D-2 收口形态）；跟不到 → 状态 `转调未解析`（与「真无实现」分开）。
    """
    能力id = str(契约.get("能力id") or "")
    能力名 = 能力id.split(".")[-1]
    if 实现索引 is None:
        实现索引 = _实现函数索引(实现目录)
    根 = 系统根 if 系统根 is not None else (_系统根(包目录) if 包目录 is not None else None)
    if not 能力id:
        return 对外入口定位(函数名=能力名, 来源="无能力id", 状态="未定位",
                          详情="契约缺少 能力id")
    登记 = 包入口映射(包目录).get(能力id) or {}
    函数名 = str(登记.get("函数名") or 能力名)
    来源 = str(登记.get("来源") or "能力名回退")
    # 候选条目 = (文件, 出处, **在该文件里应当找到的函数名**)。第三项必须跟着候选走：
    # 注册表里的 `实现函数` 是 `__init__` 里的**本地名**（可能是别名，如
    # `from …实现.组件规范支持库 import 生成完整性摘要 as 生成完整性摘要能力`），
    # 被导入模块里定义的是**原名**。
    候选: list[tuple[Path, str, str]] = []
    if 包目录 is not None:
        入口 = 包目录 / "__init__.py"
        if 入口.is_file() and _文件内定义(入口, 函数名):
            候选.append((入口, "包入口本文件", 函数名))
        导入表 = _包入口导入表(包目录)
        for 查名 in dict.fromkeys((函数名, 能力名)):
            条目 = 导入表.get(查名)
            if not 条目:
                continue
            目标 = _模块名到文件(条目[0], 根)
            if 目标 is not None:
                候选.append((目标, f"包入口导入 {条目[0]}", 条目[1] or 能力名))
                break
    命中 = 实现索引.get(函数名)
    if 命中:
        候选.append((命中[0], "实现目录索引", 函数名))
    命中能力名 = 实现索引.get(能力名)
    if 命中能力名 and 命中能力名[0] != (命中[0] if 命中 else None):
        候选.append((命中能力名[0], "实现目录索引（能力id 末段）", 能力名))
    for 文件, 出处, 核对名 in 候选:
        if 文件.is_file() and _文件内定义(文件, 核对名):
            return 对外入口定位(文件=文件, 函数名=核对名, 来源=出处, 状态="已定位",
                              详情=f"{出处}: {文件}（函数 {核对名}）")
    for 文件, 出处, 核对名 in 候选:
        if not 文件.is_file():
            continue
        目标, 说明 = _跟随转调(文件, 核对名, 根)
        if 目标 is not None:
            return 对外入口定位(文件=目标, 函数名=核对名, 来源=f"转调跟随（{出处}）",
                              状态="已定位", 详情=说明)
        if 说明:
            return 对外入口定位(文件=None, 函数名=核对名, 来源=出处,
                              状态="转调未解析", 详情=说明)
    return 对外入口定位(文件=None, 函数名=函数名, 来源=来源, 状态="未定位",
                      详情=f"{实现目录} 下未找到函数 {函数名}")


def 检测声明无实现(契约: dict[str, Any], 实现目录: Path,
                   实现索引: dict[str, tuple[Path, ast.AST]] | None = None) -> str | None:
    """契约声明了能力但实现目录无对应实现（按**函数名**匹配，不按文件名）。

    原实现按「文件名含能力名」判，在本仓（一包一文件）实测：108 包 570 条全红、
    真缺口 0 条 —— 这是判据错误，不是被测缺陷（哲学 9.x：判据错误不得说成被测
    缺陷）。改为按函数名索引后，真缺口才如实报出。

    **它只认「能力id 末段 == 函数名」这一档**，故会把两类**合法**形态误报：
    ① 别名（`…PDF隔离提供者.解析PDF` 的实现函数是 `解析PDF隔离`）；
    ② 转调（`…PDF文本表格.实现/PDF文本表格.py` 用 `sys.modules[__name__] = 唯一实现`
       把模块对象换掉，文件里当然没有 `def 解析PDF`）。
    `全面漂移检测` 已改走 **`定位对外入口`**（注册映射 + 转调跟随）再判，不再直接调本
    函数；本函数保留给「拿不到包目录」的调用方（如反向破坏验证的临时夹具）。
    """
    能力id = 契约.get("能力id", "")
    if not 能力id:
        return None
    if 实现索引 is None:
        实现索引 = _实现函数索引(实现目录)
    能力名 = 能力id.split(".")[-1]
    if 能力名 in 实现索引:
        return None
    return f"声明能力但无实现: {能力id}（{实现目录} 下未找到函数 {能力名}）"


def _取能力函数定义(树: ast.AST, 函数名: str, *,
                   允许唯一函数回退: bool = False
                   ) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
    """按**函数名**取函数定义（AST，含嵌套闭包）。

    `允许唯一函数回退`：只在「文件里只有一个函数」时用它（生成入口/夹具即此形态）。
    多函数文件里找不到同名函数 = 本能力无可比对签名，**不拿别人的签名顶替**（那是错归属）。
    """
    函数表 = [节点 for 节点 in ast.walk(树)
            if isinstance(节点, (ast.FunctionDef, ast.AsyncFunctionDef))]
    命中 = next((节点 for 节点 in 函数表 if 节点.name == 函数名), None) if 函数名 else None
    if 命中 is not None:
        return 命中
    if 允许唯一函数回退 and len(函数表) == 1:
        return 函数表[0]
    return None


def _签名参数(函数定义: ast.FunctionDef | ast.AsyncFunctionDef) -> tuple[list[str], set[str]]:
    """函数签名 → (参数名序, 带默认值的参数名集合)。

    参数名序 = 位置参数（`posonlyargs + args`）紧接关键字专用参数（`kwonlyargs`）——
    全 kw-only 的能力入口（`def 启动桌面窗口(*, 标题=…)`）必须认。`self`/`cls`/`无参数`
    是平台占位形态，剔除。
    """
    位置 = list(函数定义.args.posonlyargs) + list(函数定义.args.args)
    默认数 = len(函数定义.args.defaults)
    有默认 = {参数.arg for 参数 in 位置[len(位置) - 默认数:]} if 默认数 else set()
    有默认 |= {参数.arg for 参数, 默认 in zip(函数定义.args.kwonlyargs,
                                           函数定义.args.kw_defaults)
             if 默认 is not None}
    参数名序 = [参数.arg for 参数 in 位置 + list(函数定义.args.kwonlyargs)
             if 参数.arg not in ("无参数", "self", "cls")]
    return 参数名序, 有默认


def _必填名序问题(必填: list[str], 入口参数: list[str]) -> tuple[list[str], list[str]]:
    """必填参数在入口签名里的**子序列**问题：返回 (缺失的必填项, 顺序颠倒的说明)。

    只比必填项的相对顺序：入口签名里带默认值的可选参数是平台允许的实现自由度，
    它们插在哪里都不算漂移（契约只登记对外必填面）。
    """
    位置表: dict[str, int] = {}
    for 序号, 名 in enumerate(入口参数):
        位置表.setdefault(名, 序号)
    缺失 = [名 for 名 in 必填 if 名 not in 位置表]
    顺序错: list[str] = []
    上一位 = -1
    上一个名 = ""
    for 名 in 必填:
        if 名 not in 位置表:
            continue
        位 = 位置表[名]
        if 位 < 上一位:
            顺序错.append(f"{名} 应在 {上一个名} 前")
            continue
        上一位 = 位
        上一个名 = 名
    return 缺失, 顺序错


def 检测参数漂移(契约: dict[str, Any], 入口文件: Path, *,
                函数名: str | None = None) -> str | None:
    """契约参数与入口签名的**名序**一致性（ast 解析函数签名；名序过了再比类型）。

    **名序判据（2026-09-18 修正）**：按「**契约必填参数的相对顺序**在入口签名里做
    **子序列匹配**」判，不再按「入口参数表 == 契约参数表」严格相等判：
      · 必填项按序全部命中（入口多出带默认值的可选参数）= **不漂移**（多出的只报不判，
        见 `检测参数超出`）。本仓契约只登记必填面，实现签名里带默认值的可选参数
        （`项目id: str = ""`）是平台允许的实现自由度——原严格相等判据实测把 56 条
        正确实现判成「参数顺序漂移」；
      · 必填项在入口里**缺失**或相对顺序**颠倒** = 漂移，且报清楚缺了哪些 / 哪两个颠倒。
    `函数名`：入口文件里**对外函数**的名字。给了就用它（注册映射给的实现函数名可能与
    能力id 末段不同：别名 / `__init__` 里的 `_包装*` 闭包），不给才按能力id 末段取。
    形参名序 = 位置参数（`posonlyargs + args`）紧接关键字专用参数（`kwonlyargs`）——
    全 kw-only 的能力入口（`def 启动桌面窗口(*, 标题=…)`，本仓实测 65 条）必须认它。
    """
    if not 入口文件.is_file():
        return f"入口文件缺失: {入口文件}"
    try:
        树 = ast.parse(入口文件.read_text(encoding="utf-8"))
    except SyntaxError as 错误:
        return f"入口文件语法错误: {错误}"
    参数表 = 契约.get("参数", [])
    契约参数 = [参数["名称"] for 参数 in 参数表]
    契约必填 = [参数["名称"] for 参数 in 参数表 if 参数.get("必填", True)]
    # **必须按函数名取函数，不能取「文件里第一个函数」**：本仓一包一文件，文件里
    # 通常先放私有辅助函数（`_失败`/`_校验`）→ 取首个函数等于拿别人的签名比对，
    # 实测把 107 条真·参数名序差异里的 51 条变成了错归属的假红。
    查名 = 函数名 or str(契约.get("能力id", "")).split(".")[-1]
    函数定义 = _取能力函数定义(树, 查名, 允许唯一函数回退=True)
    if 函数定义 is None:
        # 找不到同名函数 = 本能力无可比对签名（不拿别人的签名顶替）；「函数根本不存在」
        # 由同批的 声明无实现 / 转调目标未解析 / 实现文件未定位 如实报出。
        return None
    入口参数, _ = _签名参数(函数定义)
    缺失, 顺序错 = _必填名序问题(契约必填, 入口参数)
    if 缺失 or 顺序错:
        明细 = []
        if 缺失:
            明细.append(f"必填参数缺失 {缺失}")
        if 顺序错:
            明细.append("必填参数顺序颠倒 " + "；".join(顺序错))
        return (f"参数顺序漂移: 契约 {契约参数} ≠ 入口 {入口参数}"
                f"（{'；'.join(明细)}）")
    # 名序通过再看类型（**必须保留在同一个入口里**：反向破坏门禁的「参数类型修改」
    # 场景正是靠 检测参数漂移 对类型差异报红来证明判据不恒真；把类型检查只放到
    # 检测参数类型漂移 会让该场景变成恒真）。类型判据本体只有一处实现，见下。
    return 检测参数类型漂移(契约, 入口文件, 函数名=函数名)


def 检测参数超出(契约: dict[str, Any], 入口文件: Path, *,
                函数名: str | None = None) -> list[str]:
    """**只报不判**：入口签名里契约未登记的额外参数（实现自带的带默认值参数）。

    契约只登记对外必填面，实现多带的参数是平台允许的实现自由度，**判红等于把正确实现
    判成缺陷**（这正是原 56 条误判的形态之一）；但也不许默默丢掉——它是「契约与实现
    参数面对不齐」的度量，进 `全面漂移扫描` 的 `只报列表`，不进缺口计数。
    额外参数里**没有默认值**的那些要单独点名：那种形态会改变对外可用的必填面，值得复核。
    """
    if not 入口文件.is_file():
        return []
    try:
        树 = ast.parse(入口文件.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError, OSError):
        return []
    查名 = 函数名 or str(契约.get("能力id", "")).split(".")[-1]
    函数定义 = _取能力函数定义(树, 查名)
    if 函数定义 is None:
        return []
    入口参数, 有默认 = _签名参数(函数定义)
    契约参数集 = {str(参数.get("名称", "")) for 参数 in 契约.get("参数", [])}
    额外 = [名 for 名 in 入口参数 if 名 not in 契约参数集]
    if not 额外:
        return []
    行 = f"入口多出契约未登记的参数 {额外}（契约只登记对外参数面，实现多带默认值参数属实现自由度，只报不判）"
    无默认 = [名 for 名 in 额外 if 名 not in 有默认]
    if 无默认:
        行 += f"；其中 {无默认} 无默认值（会改变对外必填面，值得复核）"
    return [行]


def 检测实现无声明(实现目录: Path, 契约列表: list[dict]) -> list[str]:
    """实现文件中的函数没有对应契约声明。

    **不要并入 全面漂移检测**：本实现按「实现目录下每个公开函数名 == 某能力id
    的末段」判定，而真实支持库的实现模块普遍带内部辅助函数（测得的样本：
    100 个含实现目录的包中 54 个包共报出 237 条，如 余弦相似度/主循环/
    校验OOXML安全/加载提供者，全是合法内部函数）。函数级粒度无法区分
    「能力入口」与「辅助函数」，直接启用等于给正式包制造大面积假红。
    要真做这项，必须按注册映射（__init__ 的 注册能力）反查能力入口。
    """
    问题列表 = []
    声明能力表 = {契约.get("能力id", "").split(".")[-1] for 契约 in 契约列表}
    for 文件 in 实现目录.rglob("*.py"):
        if "pycache" in str(文件):
            continue
        内容 = 文件.read_text(encoding="utf-8")
        for 匹配 in re.finditer(r"^def ([一-龥\w]+)\(", 内容, re.MULTILINE):
            函数名 = 匹配.group(1)
            if 函数名.startswith("_"):
                continue
            if 函数名 not in 声明能力表:
                问题列表.append(f"有实现但无声明: {文件.name} 中的 {函数名}")
    return 问题列表


def _注解可比形状(注解: str) -> str:
    """把入口注解归一成可比的窄形状，消除三类**判据读法不全造成的假红**：

    ① `X | None` / `Optional[X]` —— 契约「必填=False」的可选参数，实现按 Python 惯例
       写 `字典型 | None`；契约类型名本身不含 ` | None`，两者比对必然全红（实测
       `技能库.受控执行.运行技能包` 的 `字典型` vs `dict | None`）。
    ② `Any` / `object` —— 实现明确声明「不做静态约束」（校验器类能力普遍如此，如
       `前端契约校验.校验页面定义` 的 `页面定义: Any`）。「不约束」不等于「类型写错」，
       比不出差异就不报（判不出 ≠ 判红）。
    ③ 前后空白与内部多余空格（`dict[str, Any]` 这类带参数化注解保持原样可比）。
    """
    形状 = " ".join(str(注解).split())
    if 形状.startswith("Optional[") and 形状.endswith("]"):
        形状 = 形状[len("Optional["):-1]
    if 形状.endswith("| None"):
        形状 = 形状[:-len("| None")].strip()
    if 形状.startswith("None |"):
        形状 = 形状[len("None |"):].strip()
    return 形状


def 检测参数类型漂移(契约: dict[str, Any], 入口文件: Path, *,
                    函数名: str | None = None) -> str | None:
    """参数**类型**漂移（与 检测参数漂移 分开：名序与类型是两类缺口，分别计数）。

    归一后仍不一致才报：见 `_注解可比形状`（`Any` 视为未约束、可选参数剥 `| None`）。
    `函数名`：对外函数名（注册映射给的实现函数名可能与能力id 末段不同）；不给按末段取。
    """
    if not 入口文件.is_file():
        return None
    try:
        树 = ast.parse(入口文件.read_text(encoding="utf-8"))
    except SyntaxError:
        return None
    查名 = 函数名 or str(契约.get("能力id", "")).split(".")[-1]
    函数定义 = _取能力函数定义(树, 查名)
    if 函数定义 is None:
        return None
    类型映射 = {"文本型": "str", "整数型": "int", "长整数型": "int",
              "逻辑型": "bool", "列表型": "list", "字典型": "dict",
              "字节集型": "bytes", "双精度数型": "float",
              "单精度数型": "float"}
    注解表: dict[str, str] = {}
    for 参数 in list(函数定义.args.posonlyargs) + list(函数定义.args.args) \
            + list(函数定义.args.kwonlyargs):
        if 参数.annotation is None:
            continue
        try:
            注解表[参数.arg] = ast.unparse(参数.annotation)
        except TypeError:
            continue
    for 参数 in 契约.get("参数", []):
        名称 = 参数["名称"]
        期望注解 = 类型映射.get(参数.get("类型", ""), "")
        实际注解 = 注解表.get(名称)
        if not 期望注解 or 实际注解 is None:
            continue
        形状 = _注解可比形状(实际注解)
        if not 形状 or 形状 in ("Any", "object"):
            continue        # 实现声明「不做静态约束」：比不出差异，不判红
        if 期望注解 != 形状:
            return f"参数类型漂移: {名称} 契约类型 {参数.get('类型', '')} ≠ 入口注解 {实际注解}"
    return None


def 检测返回漂移(契约: dict[str, Any], 实现文件: Path) -> str | None:
    """返回结构漂移：实现返回值与契约 返回 字段不一致（ast 分析返回路径）。"""
    if not 实现文件.is_file():
        return None
    try:
        树 = ast.parse(实现文件.read_text(encoding="utf-8"))
    except SyntaxError:
        return None
    返回类型 = 契约.get("返回", "普通返回")
    能力名 = 契约.get("能力id", "").split(".")[-1]
    函数定义 = next((节点 for 节点 in ast.walk(树)
                    if isinstance(节点, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and 节点.name == 能力名), None)
    if 函数定义 is None:
        return None
    # 返回路径分析：yield = 生成器（流式）；任务提交调用 = 任务句柄
    yield节点 = any(isinstance(节点, ast.Yield) for 节点 in ast.walk(函数定义))
    return节点 = any(isinstance(节点, ast.Return) for 节点 in ast.walk(函数定义))
    调用名表 = {节点.func.id for 节点 in ast.walk(函数定义)
                if isinstance(节点, ast.Call) and isinstance(节点.func, ast.Name)}
    异常处理 = any(isinstance(节点, ast.Try) for 节点 in ast.walk(函数定义))
    if 返回类型 == "任务句柄返回" and not (调用名表 & {"提交", "提交任务"}):
        return f"返回结构漂移: 契约声明任务句柄返回但实现未提交任务"
    if 返回类型 == "流式返回" and not yield节点:
        return f"返回结构漂移: 契约声明流式返回但实现无 yield 生成器"
    if 返回类型 == "普通返回" and not return节点:
        return f"返回结构漂移: 契约声明普通返回但实现无 return"
    if 返回类型 == "事件返回" and not (yield节点 or 调用名表 & {"追加事件", "emit"}):
        return f"返回结构漂移: 契约声明事件返回但实现无事件产出"
    if 契约.get("失败语义", "") == "异常上报" and not 异常处理:
        return f"失败语义漂移: 契约声明异常上报但实现无 try/except"
    return None


def 检测错误码漂移(契约: dict[str, Any], 实现文件: Path) -> list[str]:
    """错误码漂移：实现引用的错误码不在契约声明中。

    **作用域口径（2026-09-18 修正）**：只扫**该能力自己的函数段**，不扫整份文件。
    本仓实现是「一包一文件」（一个 `实现/xxx.py` 里放该包全部能力），扫整份文件等于
    把同包其它能力的码全算到本能力头上 —— 实测 `大语言模型支持库/模型连接器` 一个包
    就报出 110 条这种**错归属**的假红（真问题 0 条）。定位不到该能力的函数时返回空表
    （无法归属），由 `全面漂移检测` 按「实现文件未定位」如实登记「未执行」，本函数
    不臆造归属、也不静默通过。
    """
    问题列表 = []
    if not 实现文件.is_file():
        return 问题列表
    内容 = 实现文件.read_text(encoding="utf-8")
    声明错误码 = set(契约.get("错误码", []))
    能力名 = 契约.get("能力id", "").split(".")[-1]
    函数段 = None
    if 能力名:
        try:
            树 = ast.parse(内容)
        except SyntaxError:
            return 问题列表
        节点 = next((节点 for 节点 in ast.walk(树)
                    if isinstance(节点, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and 节点.name == 能力名), None)
        if 节点 is None:
            return 问题列表
        行表 = 内容.splitlines()
        函数段 = "\n".join(行表[节点.lineno - 1: 节点.end_lineno])
    if 函数段 is None:
        return 问题列表
    for 错误码 in re.findall(r'"(参数不合法|能力不存在|权限不足|外部不可访问|超时|内部错误|契约不兼容|资源泄漏)"', 函数段):
        if 错误码 not in 声明错误码:
            问题列表.append(f"错误码漂移: 实现引用 {错误码} 但契约未声明（{实现文件.name}）")
    return 问题列表


def 检测说明书一致(契约: dict[str, Any], 说明书文件: Path) -> str | None:
    """说明书与入口不一致：说明书缺参数/错误码/版本。"""
    if not 说明书文件.is_file():
        return f"说明书缺失: {说明书文件}"
    内容 = 说明书文件.read_text(encoding="utf-8")
    if 契约.get("版本") and 契约["版本"] not in 内容:
        return f"说明书与契约不一致: 缺少版本 {契约['版本']}"
    for 参数 in 契约.get("参数", []):
        if 参数["名称"] not in 内容:
            return f"说明书与入口不一致: 缺少参数 {参数['名称']}"
    for 错误码 in 契约.get("错误码", [])[:3]:
        if 错误码 not in 内容:
            return f"说明书与入口不一致: 缺少错误码 {错误码}"
    return None


def 检测契约升级(旧契约: dict, 新契约: dict) -> str | None:
    """契约破坏但未升级主版本（只对真破坏变更要求升主版本）。"""
    旧主版 = 主版本号(旧契约.get("版本", "0.0.0"))
    新主版 = 主版本号(新契约.get("版本", "0.0.0"))
    破坏原因 = 检测破坏(旧契约, 新契约)
    if 破坏原因 and 新主版 <= 旧主版:
        return f"契约破坏但未升级主版本: {破坏原因}（{旧契约.get('版本')} → {新契约.get('版本')}）"
    return None


def 检测非破坏变更(旧契约: dict, 新契约: dict) -> list[str]:
    """兼容变更清单（非破坏，不需升主版本），供调用方记录。"""
    变更: list[str] = []
    旧参数 = {参数["名称"]: 参数 for 参数 in 旧契约.get("参数", [])}
    新参数 = {参数["名称"]: 参数 for 参数 in 新契约.get("参数", [])}
    for 名称, 参数 in 旧参数.items():
        if 名称 in 新参数 and 参数.get("必填", True) and not 新参数[名称].get("必填", True):
            变更.append(f"必填参数改为可选（非破坏）: {名称}")
    for 名称, 参数 in 新参数.items():
        if 名称 not in 旧参数 and not 参数.get("必填", True):
            变更.append(f"增加参数（非破坏）: {名称}")
    for 错误码 in sorted(set(新契约.get("错误码", [])) - set(旧契约.get("错误码", []))):
        变更.append(f"新增错误码（非破坏）: {错误码}")
    return 变更


def 检测破坏(旧契约: dict, 新契约: dict) -> str | None:
    """检测破坏性变更（非破坏变更不算破坏，见 检测非破坏变更）。

    判据与唯一权威 `运行核心/加载器/版本系统/契约兼容.检查契约兼容` 同口径：
    删除参数、可选参数改为必填、新增必填参数、返回结构变更、删除错误码 才是破坏；
    「必填参数改为可选」「增加可选参数」是非破坏变更。

    原实现把「必填参数改为可选（非破坏）」「增加参数（非破坏）」也当破坏返回，并把
    非破坏变更 return 得比后续检查更早 → 两类错误同时存在：①非破坏变更被上层
    `检测契约升级` 当破坏处理，要求升主版本（假报破坏）；②其后的「返回结构变更」
    「删除错误码」等真破坏被提前 return 掩盖（真破坏漏报）。现按真破坏判据逐项检查、
    中途不因非破坏变更短路。
    """
    旧参数 = {参数["名称"]: 参数 for 参数 in 旧契约.get("参数", [])}
    新参数 = {参数["名称"]: 参数 for 参数 in 新契约.get("参数", [])}
    for 名称, 参数 in 旧参数.items():
        if 名称 not in 新参数:
            return f"删除参数: {名称}"
        if not 参数.get("必填", True) and 新参数[名称].get("必填", True):
            return f"可选参数改为必填: {名称}"
    for 名称, 参数 in 新参数.items():
        if 名称 not in 旧参数 and 参数.get("必填", True):
            return f"新增必填参数: {名称}"
    旧返回 = 旧契约.get("返回", "普通返回")
    新返回 = 新契约.get("返回", "普通返回")
    if 旧返回 != 新返回:
        return f"返回结构变更: {旧返回} → {新返回}"
    旧错误码 = set(旧契约.get("错误码", []))
    新错误码 = set(新契约.get("错误码", []))
    for 错误码 in 旧错误码 - 新错误码:
        return f"删除错误码: {错误码}"
    return None


def 检测生成文件被改(产物目录: Path) -> list[str]:
    """生成文件被手工修改：缺少生成标记的文件报告。"""
    问题列表 = []
    for 文件 in 产物目录.rglob("*"):
        if 文件.suffix in (".py", ".js", ".md") and 文件.is_file():
            内容 = 文件.read_text(encoding="utf-8")
            if 生成标记 not in 内容 and 文件.name not in ("能力搜索数据.json", "Agent查询数据.json"):
                问题列表.append(f"生成文件被手工修改: {文件.name}（缺少生成标记）")
    return 问题列表


def 检测完整性摘要格式(包目录: Path) -> list[str]:
    """完整性摘要.json 必须为文件清单格式（拒绝旧'能力数'格式/缺文件清单）。"""
    问题列表 = []
    摘要路径 = 包目录 / "完整性摘要.json"
    if not 摘要路径.is_file():
        return 问题列表
    try:
        摘要数据 = json.loads(摘要路径.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return [f"完整性摘要.json 不是合法 JSON: {摘要路径}"]
    文件清单 = 摘要数据.get("文件清单")
    if not isinstance(文件清单, list) or not 文件清单:
        问题列表.append(f"完整性摘要.json 非文件清单格式（缺文件清单或为空）: {摘要路径}")
    if 摘要数据.get("摘要算法", "sha256") != "sha256":
        问题列表.append(f"完整性摘要.json 摘要算法不合法: {摘要数据.get('摘要算法')}")
    return 问题列表


def 检测能力定义漂移(包目录: Path) -> list[str]:
    """能力定义 → 生成物一致性：从能力定义重编译并与现有生成物对比。

    拒绝：能力定义缺失行为字段；生成物被手工篡改；生成物与能力定义不一致；
    有生成物但无能力定义（应重新编译）；有包声明但无能力定义。
    """
    import sys
    from pathlib import Path as 路径

    问题列表 = []
    定义文件 = 包目录 / "能力定义.json"
    if not 定义文件.is_file():
        # 无能力定义：若包声明存在则必须提示迁移
        声明文件 = 包目录 / "包声明.json"
        if 声明文件.is_file():
            问题列表.append(f"存在包声明但无能力定义（需迁移到唯一事实源）: {包目录}")
        return 问题列表
    # 完整性摘要必须为文件清单格式（拒绝旧'能力数'格式漂移）
    问题列表.extend(检测完整性摘要格式(包目录))
    # 加入平台根以导入编译器
    平台根 = str(包目录.resolve().parents[1])
    if 平台根 not in sys.path:
        sys.path.insert(0, 平台根)
    from 开发工具.契约编译.能力定义编译器 import (
        生成Agent数据, 生成包声明, 生成能力契约, 生成注册入口,
        生成搜索数据, 读取能力定义, 校验能力定义,
    )
    from 开发工具.契约编译.聚合契约解析 import 读取原始
    try:
        定义 = 读取能力定义(定义文件)
    except json.JSONDecodeError as 错误:
        问题列表.append(f"能力定义 JSON 解析失败: {定义文件}：{错误}")
        return 问题列表
    结构问题 = 校验能力定义(定义)
    问题列表.extend(f"能力定义结构: {问题}" for 问题 in 结构问题)
    if 结构问题:
        return 问题列表
    声明文件 = 包目录 / "包声明.json"
    依赖 = []
    包id = ""
    包名称 = ""
    包类型 = "支持库"
    实现模块 = ""
    if 声明文件.is_file():
        try:
            声明 = json.loads(声明文件.read_text(encoding="utf-8"))
            包id = 声明.get("包id", "")
            包名称 = 声明.get("名称", "")
            包类型 = 声明.get("类型", "支持库")
            依赖 = 声明.get("依赖", [])
        except json.JSONDecodeError:
            问题列表.append(f"包声明 JSON 解析失败: {声明文件}")
    # 与生成物对比（重编译 → 摘要一致）
    # 口径必须与编译器一致（哲学第 1 条 3 项：一个事实源）：编译器是**非破坏性**生成——
    # 它按既有契约保留手写 `中文名称`/`名称`/自定义键、手写 `调用示例`，契约版本恒等于契约事实源。
    # 因此这里必须把**既有契约**传进去再比对；否则凡有手写保留键的包都会被误报成「需重新编译」。
    契约文件 = 包目录 / "能力契约" / "参数契约.json"
    期望契约 = json.loads(生成能力契约(定义, 读取原始(契约文件) if 契约文件.is_file() else None))
    if 契约文件.is_file():
        实际契约 = 读取原始(契约文件)
        if 实际契约 is None:
            问题列表.append(f"能力契约 JSON 解析失败: {契约文件}")
        elif 实际契约 != 期望契约:
            问题列表.append(f"能力契约与能力定义不一致（需重新编译）: {包目录}")
    else:
        问题列表.append(f"能力契约缺失（需重新编译）: {契约文件}")
    # 注册入口含生成标记（或手写入口含 注册能力 → 合法）
    入口文件 = 包目录 / "__init__.py"
    if 入口文件.is_file():
        内容 = 入口文件.read_text(encoding="utf-8")
        if 生成标记 not in 内容 and "def 注册能力" not in 内容:
            问题列表.append(f"注册入口未由编译器生成（缺少生成标记且无注册能力）: {入口文件}")
    else:
        问题列表.append(f"注册入口缺失: {入口文件}")
    return 问题列表


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
    表: dict[str, dict[str, Any]] = {}
    注册函数表 = [节点 for 节点 in ast.walk(树)
                if isinstance(节点, (ast.FunctionDef, ast.AsyncFunctionDef))
                and 节点.name == "注册能力"]
    if 注册函数表:
        for 函数 in 注册函数表:
            _扫描注册语句(函数.body, {}, 表)
    else:
        _扫描注册语句(树.body, {}, 表)
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


@dataclass
class 口径比对结果:
    """一次「注册口径 ↔ 契约口径」比对的分桶结果（判红／存量只报／度量分开）。

    `问题列表` 是**判红口径**（调用方计分、门禁据它红/绿）；`存量漏声明列表` 与
    `基线过期列表` 只报不计分；`实现默认值` 类的度量不走本结构（见
    检测实现默认值差异，只报不计分不判红）。
    """

    既有问题列表: list[str] = field(default_factory=list)
    默认值硬不一致列表: list[str] = field(default_factory=list)
    必填硬不一致列表: list[str] = field(default_factory=list)
    新增漏声明列表: list[str] = field(default_factory=list)
    存量漏声明列表: list[str] = field(default_factory=list)
    基线过期列表: list[str] = field(default_factory=list)
    漏声明键集: set[str] = field(default_factory=set)
    声明计数: dict[str, int] = field(default_factory=dict)
    基线生效: bool = False

    @property
    def 硬问题列表(self) -> list[str]:
        """既有判据 + 默认值/必填硬不一致（不受基线影响）。"""
        return self.既有问题列表 + self.默认值硬不一致列表 + self.必填硬不一致列表

    @property
    def 问题列表(self) -> list[str]:
        """判红口径 = 硬问题 + 基线外新增漏声明。"""
        return self.硬问题列表 + self.新增漏声明列表


def _默认值等价(左: Any, 右: Any) -> bool:
    """默认值比较：数值口径等价即可（60 == 60.0），但 bool 不与 0/1 混同。

    JSON 里 `false` 与 `0` 是两回事（`false` 是逻辑型默认值、`0` 是整数型默认值），
    Python 的 `False == 0` 会把它们判等，所以这里显式分开。
    """
    if isinstance(左, bool) or isinstance(右, bool):
        return isinstance(左, bool) and isinstance(右, bool) and 左 == 右
    return 左 == 右


def _记漏声明(结果: 口径比对结果, 基线键集: set[str] | None, 维度: str,
             能力id: str, 参数名: str, 行: str) -> None:
    """漏声明分桶：基线命中=存量（只报）；基线外=新增（判红）；无基线=一律存量。"""
    键 = f"{维度}|{能力id}#{参数名}"
    结果.漏声明键集.add(键)
    结果.声明计数[维度] = 结果.声明计数.get(维度, 0) + 1
    if 基线键集 is not None and 键 not in 基线键集:
        结果.新增漏声明列表.append(行)
    else:
        结果.存量漏声明列表.append(行)


def 比对注册口径明细(契约表: dict[str, dict[str, Any]],
                     注册表: dict[str, dict[str, Any]],
                     基线键集: set[str] | None = None) -> 口径比对结果:
    """逐条比对注册口径与契约口径并**分桶**（与 契约.校验声明一致 同口径）。

    - 返回：两边经 `契约.归一注册口径` 归一后比较（注册 `结果` ≡ 契约 `结果型`）；
      不归一的话全仓首报约 300 条纯写法噪声，会把真问题淹掉。
    - 参数：① 参数名序；② 参数类型——**只比对两侧都是正式类型名**的项
      （历史短名 布尔/文本/字典/数值 属批次4「注册元数据-类型名非正式」治理范围，
      不是本检测的口径漂移，混进来会造出第二套清单）。
    - 参数**默认值/必填（2026-09-17 新增判据）**：
      · 双侧都声明且不等 → **硬不一致**（判红）。实例：契约/实现 45080 而注册 0
        （`浏览器宿主.启动网页服务.端口`），对外公布的默认值与真实行为不符；
        注册写 `必填=True` 而契约与实现皆可选，会把**合法调用**判「参数不合法」拒掉。
      · 注册侧缺声明而契约有值（默认值非 None／必填=True）→ **漏声明**，按
        *注册口径存量基线.json* 分治：基线命中=存量（只报）；基线外=新增（判红）；
        基线键集为 None（无基线/基线不可读）时一律按存量只报——判不出新增就不判红，
        仅由 `基线生效=False` 如实暴露「新增判据未生效」。
      · 存量实测（2026-09-17，包×能力×参数 条目数）：默认值漏声明 **152**
        必填漏声明 **69**（注册侧已声明 667/1142，故不是「全部漏」）；硬不一致 0/0。
        另有「注册参数表整体未解析」（AST 静态解析不出）137 条同口径项不计入漏声明。
    - 基线过期：基线里登记、本次已不再复现的键单列（提示收缩，不判红）。
    只在两侧都解析出的能力上比对；未解析的能力由调用方按覆盖率如实登记。
    """
    结果 = 口径比对结果(基线生效=基线键集 is not None)
    for 能力id, 契约项 in sorted(契约表.items()):
        注册项 = 注册表.get(能力id)
        if 注册项 is None:
            continue
        注册返回 = 注册项.get("返回")
        契约返回 = str(契约项.get("返回", ""))
        # 返回口径解析不出（动态拼装）时跳过，不伪造「空返回」的假红。
        if 注册返回 is not None and 归一注册口径(str(注册返回)) != 归一注册口径(契约返回):
            结果.既有问题列表.append(f"{能力id}: 注册返回 {注册返回} ≠ 契约返回 {契约返回}")
        注册参数 = 注册项.get("参数")
        if 注册参数 is None:
            continue
        注册名 = [项["名称"] for 项 in 注册参数]
        契约名 = [项["名称"] for 项 in 契约项.get("参数", [])]
        if 注册名 and 契约名 and 注册名 != 契约名:
            结果.既有问题列表.append(f"{能力id}: 注册参数名序 {注册名} ≠ 契约参数名序 {契约名}")
        契约类型 = {项["名称"]: 项["类型"] for 项 in 契约项.get("参数", [])}
        for 项 in 注册参数:
            类型 = str(项.get("类型", ""))
            期望 = str(契约类型.get(项["名称"], ""))
            if 类型 in 正式类型表 and 期望 in 正式类型表 and 类型 != 期望:
                结果.既有问题列表.append(
                    f"{能力id}: 注册参数 {项['名称']} 类型 {类型} ≠ 契约类型 {期望}"
                )
        # 新判据：默认值 / 必填。只在两侧都声明同一参数名时比对，缺声明按漏声明分桶。
        契约按名 = {项["名称"]: 项 for 项 in 契约项.get("参数", [])}
        for 项 in 注册参数:
            名称 = 项["名称"]
            契约参数 = 契约按名.get(名称)
            if 契约参数 is None:
                continue
            if "默认值" in 项:
                结果.声明计数["默认值已声明"] = 结果.声明计数.get("默认值已声明", 0) + 1
                if 项["默认值"] is 未解析哨兵:
                    结果.声明计数["默认值不可静态判定"] = 结果.声明计数.get("默认值不可静态判定", 0) + 1
                elif "默认值" not in 契约参数:
                    结果.默认值硬不一致列表.append(
                        f"{能力id}: 注册参数 {名称} 声明默认值 {项['默认值']!r} 但契约未声明默认值")
                elif not _默认值等价(项["默认值"], 契约参数["默认值"]):
                    结果.默认值硬不一致列表.append(
                        f"{能力id}: 注册参数 {名称} 默认值 {项['默认值']!r}"
                        f" ≠ 契约默认值 {契约参数['默认值']!r}")
            elif 契约参数.get("默认值") is not None:
                _记漏声明(结果, 基线键集, "默认值漏声明", 能力id, 名称,
                          f"{能力id}: 注册参数 {名称} 未声明默认值"
                          f"（契约默认值 {契约参数.get('默认值')!r}）")
            if "必填" in 项:
                结果.声明计数["必填已声明"] = 结果.声明计数.get("必填已声明", 0) + 1
                if 项["必填"] is 未解析哨兵:
                    结果.声明计数["必填不可静态判定"] = 结果.声明计数.get("必填不可静态判定", 0) + 1
                elif bool(项["必填"]) != bool(契约参数.get("必填", True)):
                    结果.必填硬不一致列表.append(
                        f"{能力id}: 注册参数 {名称} 必填 {bool(项['必填'])}"
                        f" ≠ 契约必填 {bool(契约参数.get('必填', True))}")
            elif 契约参数.get("必填", True):
                _记漏声明(结果, 基线键集, "必填漏声明", 能力id, 名称,
                          f"{能力id}: 注册参数 {名称} 未声明必填（契约必填=True）")
    if 基线键集 is not None:
        结果.基线过期列表 = sorted(基线键集 - 结果.漏声明键集)
    return 结果


def 比对注册口径(契约表: dict[str, dict[str, Any]],
                注册表: dict[str, dict[str, Any]],
                基线键集: set[str] | None = None) -> list[str]:
    """比对注册口径并返回**判红清单**（既有判据 + 默认值/必填硬不一致 + 新增漏声明）。

    分桶明细见 比对注册口径明细；不传 `基线键集` 时新判据的漏声明全部只报，
    本函数只返回「硬」的那部分，调用方不需要基线也不会被 221 条存量漏声明打红。
    """
    return 比对注册口径明细(契约表, 注册表, 基线键集).问题列表


def 检测注册口径漂移明细(包目录: Path,
                        基线键集: set[str] | None = None) -> 口径比对结果:
    """「注册口径」子检测的**分桶明细**：包入口注册表 ↔ `能力契约/参数契约.json`。

    与 检测注册口径漂移 同口径，只是把判红/存量/影响面分开返回，便于调用方照实分级。
    """
    return 比对注册口径明细(读取契约口径(包目录 / "能力契约" / "参数契约.json"),
                          读取注册口径(包目录 / "__init__.py"), 基线键集)


def 检测注册口径漂移(包目录: Path, 基线键集: set[str] | None = None) -> list[str]:
    """「注册口径」子检测：包入口注册表 ↔ `能力契约/参数契约.json` 的**判红**不一致清单。

    落点清单_03 重要-10：`契约.校验声明一致` 曾零生产调用点，注册口径漂移长期
    无人发现；本检测是它的**编译期**落点（运行期落点见批次0-4 接线说明）。
    判据含返回口径/参数名序/参数类型（写法漂移）与参数默认值/必填（口径裂缝）；
    漏声明类需存量基线才判得出「新增」，传 `基线键集` 启用，不传则一并只报。
    """
    结果 = 检测注册口径漂移明细(包目录, 基线键集)
    问题列表 = 结果.问题列表
    if not 问题列表:
        return []
    相对路径 = 包目录.name
    return [f"{相对路径}: {问题}" for 问题 in 问题列表]


def 读取实现形参默认值(实现目录: Path) -> dict[str, dict[str, Any]]:
    """静态读 实现目录 下各模块函数的形参默认值：函数名 → {形参名: 默认值}。

    只做 AST 静态求值（复用 `_静态字面量`）：取不到字面量的登记 未解析哨兵，
    比对侧跳过、不伪造差异。同名函数取首个命中（本仓实现是「一包一文件」）。
    """
    表: dict[str, dict[str, Any]] = {}
    if not 实现目录.is_dir():
        return 表
    for 文件 in sorted(实现目录.rglob("*.py")):
        if "__pycache__" in 文件.parts:
            continue
        try:
            树 = ast.parse(文件.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError, OSError):
            continue
        for 节点 in ast.walk(树):
            if not isinstance(节点, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if 节点.name in 表:
                continue
            位置参数 = list(节点.args.posonlyargs) + list(节点.args.args)
            默认节点表 = list(节点.args.defaults)
            形参默认: dict[str, Any] = {}
            for 形参, 默认节点 in zip(位置参数[len(位置参数) - len(默认节点表):], 默认节点表):
                形参默认[形参.arg] = _静态字面量(默认节点, {})
            for 形参, 默认节点 in zip(节点.args.kwonlyargs, 节点.args.kw_defaults):
                if 默认节点 is not None:
                    形参默认[形参.arg] = _静态字面量(默认节点, {})
            表[节点.name] = 形参默认
    return 表


def 检测实现默认值差异(契约表: dict[str, dict[str, Any]],
                      实现目录: Path) -> dict[str, Any]:
    """「契约默认值 vs 实现形参默认值」差异——**只报、不计分、不判红**。

    为什么要单列且不判红：注册口径对齐的是「注册元数据」，而对外真实公布的默认值还
    取决于实现形参。实测（2026-09-17，全仓 116 包）差异 **130 条**，其中「契约声明
    null（必填/无默认）而实现给了默认值」12 条、其中「契约 null vs 实现 ``''``」8 条；
    另有「实现无默认但契约有默认」43 条与「实现默认值不可静态判定」100 条。
    量级大且部分是历史约定（如 `输出路径=None` 表示写临时文件），所以先只报作
    **影响面**登记，由治理批次逐包收口后再决定是否升格。
    双侧都有默认值才比；实现未给默认值的不算差异（另计 实现无默认但契约有默认）。
    """
    实现表 = 读取实现形参默认值(实现目录)
    差异列表: list[str] = []
    计数 = {"差异数": 0, "契约null数": 0, "契约null实现空串数": 0,
            "实现无默认但契约有默认": 0, "不可静态判定数": 0}
    for 能力id, 契约项 in sorted(契约表.items()):
        形参默认 = 实现表.get(能力id.split(".")[-1])
        if 形参默认 is None:
            continue
        for 参数 in 契约项.get("参数", []):
            名称 = 参数["名称"]
            if 名称 not in 形参默认:
                if 参数.get("默认值") is not None:
                    计数["实现无默认但契约有默认"] += 1
                continue
            实现值 = 形参默认[名称]
            if 实现值 is 未解析哨兵:
                计数["不可静态判定数"] += 1
                continue
            契约值 = 参数.get("默认值")
            if _默认值等价(实现值, 契约值):
                continue
            计数["差异数"] += 1
            if 契约值 is None:
                计数["契约null数"] += 1
                if 实现值 == "":
                    计数["契约null实现空串数"] += 1
            差异列表.append(
                f"{能力id}.{名称}: 契约默认值 {契约值!r} vs 实现形参默认值 {实现值!r}")
    return {"差异列表": 差异列表, "计数": 计数}


存量基线文件名 = "注册口径存量基线.json"
存量基线版本 = 1
漏声明维度表 = ("默认值漏声明", "必填漏声明")


def 默认存量基线路径() -> Path:
    """基线文件位置：本模块同目录（`开发工具/契约编译/注册口径存量基线.json`）。

    基线是**判据的组成部分**（不是被检测对象的产物），所以跟着代码走，不跟着系统根走：
    这样对任意系统根（含临时验证根）都能用同一份判据，且搬动代码不会悄悄失去豁免。
    """
    return Path(__file__).resolve().with_name(存量基线文件名)


def 读取存量基线(基线文件: Path) -> dict[str, Any]:
    """读存量基线；缺失/非 JSON/结构不对 → 返回 {}（调用方据此降级为「只报」）。"""
    if not 基线文件.is_file():
        return {}
    try:
        数据 = json.loads(基线文件.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(数据, dict) or not isinstance(数据.get("维度"), dict):
        return {}
    return 数据


def 存量基线键集(基线数据: dict[str, Any], 包相对路径: str) -> set[str]:
    """取某包的基线键集（`维度|能力id#参数名`）；该包不在基线里 → 空集（全判新增）。"""
    维度表 = (基线数据 or {}).get("维度") or {}
    键集: set[str] = set()
    for 维度名 in 漏声明维度表:
        for 条目键 in (维度表.get(维度名, {}) or {}).get(包相对路径, []) or []:
            键集.add(f"{维度名}|{条目键}")
    return 键集


def 写入存量基线(基线文件: Path, 基线数据: dict[str, Any]) -> None:
    """写盘：缩进 2 + 结尾换行（与仓库其它 JSON 产物一致，便于 git diff 人工裁决）。"""
    基线文件.parent.mkdir(parents=True, exist_ok=True)
    基线文件.write_text(json.dumps(基线数据, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def 生成存量基线(系统根: Path) -> dict[str, Any]:
    """按当前仓库实测**重建**基线（仅用于首次初始化；日常只允许 收缩存量基线）。

    只登记「漏声明」两个维度：默认值/必填**硬不一致**实测存量 0，故不设豁免——
    一旦出现就应直接判红，登记进基线等于给自己发免死牌。
    """
    汇总 = _全仓注册口径扫描(系统根, None, 含实现默认值=False)
    维度: dict[str, dict[str, list[str]]] = {名: {} for 名 in 漏声明维度表}
    for 包相对路径, 键集 in sorted(汇总["漏声明键表"].items()):
        for 键 in sorted(键集):
            维度名, _, 条目键 = 键.partition("|")
            if 维度名 in 维度:
                维度[维度名].setdefault(包相对路径, []).append(条目键)
    return {
        "版本": 存量基线版本,
        "说明": ("注册口径存量基线（只减不增）：基线命中=存量（只报）；基线外=新增（判红）；"
                 "无基线时新判据整批降级为只报。默认值/必填**硬不一致不设基线**（实测存量 0）。"),
        "生成口径": "包×能力×参数 条目数；条目键 = 能力id#参数名",
        "条目数": {名: sum(len(列表) for 列表 in 维度[名].values()) for 名 in 漏声明维度表},
        "维度": 维度,
    }


def 收缩存量基线(系统根: Path, 基线文件: Path, *, 写盘: bool = False) -> dict[str, Any]:
    """基线**只减不增**：删掉已消解的项，并**拒绝**把新出现的不一致纳入基线。

    返回 {新基线, 已删除, 拒绝纳入, 写盘}。`拒绝纳入` 非空即说明仓库里出现了新的
    漏声明（那本该判红）——不能靠「重建基线」一键洗白，要洗白必须先在源码里改对。
    """
    旧 = 读取存量基线(基线文件)
    汇总 = _全仓注册口径扫描(系统根, None, 含实现默认值=False)
    实测 = {包: set(键集) for 包, 键集 in 汇总["漏声明键表"].items()}
    旧维度 = (旧 or {}).get("维度", {}) or {}
    新维度: dict[str, dict[str, list[str]]] = {名: {} for 名 in 漏声明维度表}
    已删除: list[str] = []
    for 维度名 in 漏声明维度表:
        for 包相对路径, 条目列表 in sorted((旧维度.get(维度名, {}) or {}).items()):
            实测键 = 实测.get(包相对路径, set())
            for 键 in 条目列表:
                if f"{维度名}|{键}" in 实测键:
                    新维度[维度名].setdefault(包相对路径, []).append(键)
                else:
                    已删除.append(f"{包相对路径}: {维度名} {键}")
    旧键全 = {f"{包}|{维度名}|{条目键}" for 维度名 in 漏声明维度表
             for 包, 列表 in (旧维度.get(维度名, {}) or {}).items() for 条目键 in 列表}
    实测键全 = {f"{包}|{键}" for 包, 键集 in 实测.items() for 键 in 键集}
    基线包数 = len({包 for 维度名 in 漏声明维度表
                 for 包 in (旧维度.get(维度名, {}) or {})})
    # 防呆：基线覆盖的是「全仓」，对局部树（包数少于基线登记的包数）不许写盘——
    # 否则对某个局部系统根跑一次收缩，就会把「本根里没有的包」整片判成已消解而删光基线。
    拒绝写盘 = ""
    if 写盘 and 汇总["包数"] < 基线包数:
        拒绝写盘 = (f"系统根只扫到 {汇总['包数']} 个包 < 基线登记的 {基线包数} 个包，"
                  "疑似局部树：拒绝写盘（仅返回收缩结果供人工核对）")
    新基线 = {
        "版本": 存量基线版本,
        "说明": 旧.get("说明", "") if 旧 else "注册口径存量基线（只减不增）",
        "生成口径": 旧.get("生成口径", "包×能力×参数 条目数；条目键 = 能力id#参数名") if 旧 else
                    "包×能力×参数 条目数；条目键 = 能力id#参数名",
        "条目数": {名: sum(len(列表) for 列表 in 新维度[名].values()) for 名 in 漏声明维度表},
        "维度": 新维度,
    }
    if 写盘 and not 拒绝写盘:
        写入存量基线(基线文件, 新基线)
    return {"新基线": 新基线, "已删除": sorted(已删除),
            "拒绝纳入": sorted(实测键全 - 旧键全),
            "拒绝写盘": 拒绝写盘, "写盘": bool(写盘 and not 拒绝写盘)}


def _全仓注册口径扫描(系统根: Path, 基线数据: dict[str, Any] | None, *,
                     含实现默认值: bool = True) -> dict[str, Any]:
    """**唯一**全仓扫描实现：遍历 支持库/模块库/技能库 下全部 参数契约.json，逐包分桶。

    全仓注册口径统计 / 生成存量基线 / 收缩存量基线 共用本函数，避免出现第二套口径。
    `基线数据=None` 表示无基线（新判据的漏声明一律进存量桶，如实反映「判不出新增」）。
    """
    汇总: dict[str, Any] = {
        "包数": 0, "契约能力数": 0, "已解析注册数": 0, "未解析注册数": 0,
        "返回未解析数": 0, "参数未解析数": 0,
        "既有问题列表": [], "默认值硬不一致列表": [], "必填硬不一致列表": [],
        "新增漏声明列表": [], "存量漏声明列表": [], "基线过期列表": [],
        "实现默认值差异列表": [], "实现默认值计数": {},
        "漏声明键表": {}, "声明计数": {},
    }
    for 顶层 in ("支持库", "模块库", "技能库"):
        根目录 = 系统根 / 顶层
        if not 根目录.is_dir():
            continue
        for 契约文件 in sorted(根目录.glob("**/能力契约/参数契约.json")):
            包目录 = 契约文件.parent.parent
            契约表 = 读取契约口径(契约文件)
            注册表 = 读取注册口径(包目录 / "__init__.py")
            包相对路径 = (str(包目录.relative_to(系统根)) if 包目录.is_relative_to(系统根)
                        else str(包目录))
            基线键集 = 存量基线键集(基线数据, 包相对路径) if 基线数据 else None
            结果 = 比对注册口径明细(契约表, 注册表, 基线键集)
            汇总["包数"] += 1
            汇总["契约能力数"] += len(契约表)
            for 能力id in 契约表:
                注册项 = 注册表.get(能力id)
                if 注册项 is None:
                    汇总["未解析注册数"] += 1
                    continue
                汇总["已解析注册数"] += 1
                if 注册项.get("返回") is None:
                    汇总["返回未解析数"] += 1
                if 注册项.get("参数") is None:
                    汇总["参数未解析数"] += 1
            for 键 in ("既有问题列表", "默认值硬不一致列表", "必填硬不一致列表",
                       "新增漏声明列表", "存量漏声明列表", "基线过期列表"):
                汇总[键].extend(f"{包相对路径}: {行}" for 行 in getattr(结果, 键))
            汇总["漏声明键表"][包相对路径] = set(结果.漏声明键集)
            for 键, 值 in 结果.声明计数.items():
                汇总["声明计数"][键] = 汇总["声明计数"].get(键, 0) + 值
            if 含实现默认值:
                实现结果 = 检测实现默认值差异(契约表, 包目录 / "实现")
                汇总["实现默认值差异列表"].extend(
                    f"{包相对路径}: {行}" for 行 in 实现结果["差异列表"])
                for 键, 值 in 实现结果["计数"].items():
                    汇总["实现默认值计数"][键] = 汇总["实现默认值计数"].get(键, 0) + 值
    return 汇总


def 全仓注册口径统计(系统根: Path, *, 基线文件: Path | None = None) -> dict[str, Any]:
    """全仓注册口径检测（只读）：遍历 支持库/模块库/技能库 下全部 参数契约.json。

    返回（键按用途分组，都不省略）：
      · 覆盖率：包数 / 契约能力数 / 已解析注册数 / 未解析注册数 / 返回未解析数 /
        参数未解析数 —— 三个「未解析」如实暴露 AST 静态解析覆盖率，不假装 100%。
      · **判红（计分）**：`问题列表` = `硬问题列表` + `新增漏声明列表`。
      · **只报（不计分）**：`存量漏声明列表`（基线命中的漏声明）、`基线过期列表`、
        `实现默认值差异列表`（影响面，先只报不判红）。
      · 计数：`*_数` 系列，便于门禁文案直接引用。
      · 基线：{路径, 生效, 版本, 条目数, 过期项数}；基线缺失/非法时 `生效=False`，
        新判据的漏声明整批降级为「只报」——既不静默判绿（计数照样报出来），
        也不把 221 条存量漏声明一次打红。
    """
    路径 = 基线文件 if 基线文件 is not None else 默认存量基线路径()
    基线数据 = 读取存量基线(路径)
    汇总 = _全仓注册口径扫描(系统根, 基线数据 or None)
    问题列表 = 汇总["既有问题列表"] + 汇总["默认值硬不一致列表"] + 汇总["必填硬不一致列表"] \
        + 汇总["新增漏声明列表"]
    return {
        "包数": 汇总["包数"],
        "契约能力数": 汇总["契约能力数"],
        "已解析注册数": 汇总["已解析注册数"],
        "未解析注册数": 汇总["未解析注册数"],
        "返回未解析数": 汇总["返回未解析数"],
        "参数未解析数": 汇总["参数未解析数"],
        "问题列表": 问题列表,
        "硬问题列表": 汇总["既有问题列表"] + 汇总["默认值硬不一致列表"] + 汇总["必填硬不一致列表"],
        "既有问题列表": 汇总["既有问题列表"],
        "默认值硬不一致列表": 汇总["默认值硬不一致列表"],
        "必填硬不一致列表": 汇总["必填硬不一致列表"],
        "新增漏声明列表": 汇总["新增漏声明列表"],
        "存量漏声明列表": 汇总["存量漏声明列表"],
        "基线过期列表": 汇总["基线过期列表"],
        "默认值硬不一致数": len(汇总["默认值硬不一致列表"]),
        "必填硬不一致数": len(汇总["必填硬不一致列表"]),
        "默认值漏声明数": 汇总["声明计数"].get("默认值漏声明", 0),
        "必填漏声明数": 汇总["声明计数"].get("必填漏声明", 0),
        "新增漏声明数": len(汇总["新增漏声明列表"]),
        "存量漏声明数": len(汇总["存量漏声明列表"]),
        "默认值已声明数": 汇总["声明计数"].get("默认值已声明", 0),
        "必填已声明数": 汇总["声明计数"].get("必填已声明", 0),
        "新维度不可静态判定数": (汇总["声明计数"].get("默认值不可静态判定", 0)
                          + 汇总["声明计数"].get("必填不可静态判定", 0)),
        "实现默认值差异列表": 汇总["实现默认值差异列表"],
        "实现默认值差异数": 汇总["实现默认值计数"].get("差异数", 0),
        "实现默认值_契约null数": 汇总["实现默认值计数"].get("契约null数", 0),
        "实现默认值_契约null实现空串数": 汇总["实现默认值计数"].get("契约null实现空串数", 0),
        "实现默认值_实现无默认数": 汇总["实现默认值计数"].get("实现无默认但契约有默认", 0),
        "实现默认值_不可静态判定数": 汇总["实现默认值计数"].get("不可静态判定数", 0),
        "基线": {
            "路径": str(路径),
            "生效": bool(基线数据),
            "版本": 基线数据.get("版本", 0),
            "条目数": 基线数据.get("条目数", {}),
            "过期项数": len(汇总["基线过期列表"]),
        },
    }


def 全仓注册口径检测(系统根: Path, *, 基线文件: Path | None = None) -> list[str]:
    """全仓注册口径漂移的**判红**清单（只读；拦还是只报由调用方决定）。"""
    return 全仓注册口径统计(系统根, 基线文件=基线文件)["问题列表"]


def 入口() -> int:
    """命令行入口（基线运维 + 现状报告，均为只读，除非显式 --写盘）：

        python3.14 -m 开发工具.契约编译.漂移检测 --报告
        python3.14 -m 开发工具.契约编译.漂移检测 --生成基线 --写盘   # 仅首次初始化
        python3.14 -m 开发工具.契约编译.漂移检测 --收缩基线 --写盘   # 只减不增；有新增则拒绝
    """
    参数 = sys.argv[1:]
    系统根 = Path(__file__).resolve().parents[2]
    基线文件 = 默认存量基线路径()
    if "--生成基线" in 参数:
        基线 = 生成存量基线(系统根)
        print(f"实测存量：默认值漏声明 {基线['条目数'].get('默认值漏声明')} 条 / "
              f"必填漏声明 {基线['条目数'].get('必填漏声明')} 条")
        if "--写盘" in 参数:
            写入存量基线(基线文件, 基线)
            print(f"已写入 {基线文件}")
        else:
            print("（未写盘；加 --写盘 才落盘）")
        return 0
    if "--收缩基线" in 参数:
        收缩 = 收缩存量基线(系统根, 基线文件, 写盘="--写盘" in 参数)
        print(f"已删除（已消解）: {len(收缩['已删除'])} 条")
        for 行 in 收缩["已删除"][:10]:
            print("  ", 行)
        print(f"拒绝纳入（新出现的不一致，必须先改源码）: {len(收缩['拒绝纳入'])} 条")
        for 行 in 收缩["拒绝纳入"][:10]:
            print("  ", 行)
        if 收缩["拒绝写盘"]:
            print(f"拒绝写盘: {收缩['拒绝写盘']}")
        print(f"写盘={收缩['写盘']}")
        return 0 if not 收缩["拒绝纳入"] else 1
    统计 = 全仓注册口径统计(系统根, 基线文件=基线文件)
    print(f"包数 {统计['包数']}；契约能力 {统计['契约能力数']}；已解析注册 {统计['已解析注册数']}"
          f"（未解析注册 {统计['未解析注册数']}／返回口径未解析 {统计['返回未解析数']}／"
          f"参数口径未解析 {统计['参数未解析数']}）")
    print(f"基线 {统计['基线']['路径']} 生效={统计['基线']['生效']}"
          f" 条目数={统计['基线']['条目数']} 过期项={统计['基线']['过期项数']}")
    print(f"判红 {len(统计['问题列表'])} 条（默认值硬 {统计['默认值硬不一致数']}／"
          f"必填硬 {统计['必填硬不一致数']}／新增漏声明 {统计['新增漏声明数']}）")
    for 行 in 统计["问题列表"][:10]:
        print("  [判红]", 行)
    print(f"只报 存量漏声明 {统计['存量漏声明数']} 条（默认值 {统计['默认值漏声明数']}／"
          f"必填 {统计['必填漏声明数']}）；实现默认值差异 {统计['实现默认值差异数']} 条"
          f"（契约null {统计['实现默认值_契约null数']}／其中实现空串 "
          f"{统计['实现默认值_契约null实现空串数']}）")
    return 0 if not 统计["问题列表"] else 1


def 全面漂移检测(*, 契约: dict[str, Any], 实现目录: Path,
                  入口文件: Path, 说明书文件: Path,
                  旧契约: dict[str, Any] | None = None,
                  实现文件: Path | None = None,
                  实现索引: dict[str, tuple[Path, ast.AST]] | None = None,
                  包目录: Path | None = None) -> 漂移结果:
    """执行全部漂移检测。

    **入口定位（2026-09-18 修正）**：给了 `包目录` 时，一律以 `定位对外入口` 的结果为
    权威入口——注册映射（`注册能力` 登记的 `实现函数`，含别名与 `__init__` 里的
    `_包装*` 闭包）→ 包入口导入目标 → 实现目录索引（对外优先，`子进程*` 垫底）→
    转调跟随。原实现按「能力id 末段 == 函数名」在**文件名字典序**里取第一个命中，
    实测把正确实现判成缺陷：抓到子进程内部实现（`子进程解析.py` 的 `解码图像(字节b64)`）、
    抓到 `实现/` 里的内部同名方法（`解析代码文件` 的类方法是内部形态）、抓错别名（
    `解析PDF` 的实现函数是 `解析PDF隔离`），三类合计 32 条。

    实现文件：返回结构漂移与错误码漂移都要读「实现该能力的那个 .py」；按权威入口定位，
    定位不到就如实登记「未执行」而不是当成「无漂移」。

    **同一根因只计一条**：声明无实现 / 转调目标未解析 命中时，不再连带报
    「入口文件缺失」「实现文件未定位」（那是同一根因的三种说法，原实现把它们各计一条，
    把一条缺陷放大成三条）。
    """
    结果 = 漂移结果()
    if 实现索引 is None:
        实现索引 = _实现函数索引(实现目录)
    能力id = str(契约.get("能力id") or "")
    能力名 = 能力id.split(".")[-1]
    定位 = (定位对外入口(契约, 实现目录=实现目录, 包目录=包目录, 实现索引=实现索引)
            if 包目录 is not None else None)
    # 1. 声明能力但没有实现 / 转调目标未解析（同一根因只计一条）
    实现缺口: str | None = None
    if 定位 is not None:
        if 定位.状态 == "转调未解析":
            实现缺口 = f"转调目标未解析: {能力id}（{定位.详情}）"
        elif 定位.文件 is None:
            实现缺口 = (f"声明能力但无实现: {能力id}"
                       f"（{实现目录} 下未找到函数 {定位.函数名 or 能力名}）")
    else:
        实现缺口 = 检测声明无实现(契约, 实现目录, 实现索引)
    if 实现缺口:
        结果.问题列表.append(实现缺口)
    权威入口 = 定位.文件 if 定位 is not None else None
    if 权威入口 is not None and not 权威入口.is_file():
        权威入口 = None
    查名 = (定位.函数名 if 定位 is not None and 定位.函数名 else None)
    定位文件 = 权威入口 or 实现文件
    if 定位文件 is None and 实现目录.is_dir():
        定位文件 = _定位实现文件(契约, 实现目录, 实现索引)
    # 2. 参数顺序漂移 + 参数类型漂移（权威入口文件、同一函数，分别计两类缺口）
    参数入口 = 权威入口
    if 参数入口 is None and 入口文件.is_file():
        参数入口 = 入口文件
    if 参数入口 is None and 定位文件 is not None and 定位文件.is_file():
        参数入口 = 定位文件
    if 参数入口 is None:
        # 只报「实现未定位」一条：参数顺序/类型漂移与返回结构/错误码漂移都依赖同一份
        # 实现文件，未定位时它们是**同一个根因**；实现缺口已报就不再重复计一条。
        if not 实现缺口:
            结果.问题列表.append(
                f"实现文件未定位，参数顺序/类型、返回结构/错误码漂移均未执行: "
                f"{能力id or '（无能力id）'}"
                f"（{实现目录} 下无函数 {能力名 or '（无能力名）'}）"
            )
        说明书问题_仅缺文件 = 检测说明书一致(契约, 说明书文件)
        if 说明书问题_仅缺文件:
            结果.问题列表.append(说明书问题_仅缺文件)
        if 旧契约 is not None:
            升级问题_仅缺文件 = 检测契约升级(旧契约, 契约)
            if 升级问题_仅缺文件:
                结果.问题列表.append(升级问题_仅缺文件)
        return 结果
    # 一次调用覆盖名序与类型两类缺口（`检测参数漂移` 内含类型判据，见其文档串）：
    # 同一能力不重复计两类 —— 名序错了，逐参数类型比对已无意义（那是同一根因）。
    参数漂移 = 检测参数漂移(契约, 参数入口, 函数名=查名)
    if 参数漂移:
        结果.问题列表.append(参数漂移)
    else:
        # 只报不判：入口多出的契约未登记参数（实现自带的带默认值参数 = 平台允许的
        # 实现自由度）。判红会把正确实现判成缺陷，默默丢掉又丢失了「契约与实现对不齐」。
        结果.只报列表.extend(f"{能力id}: {行}"
                          for 行 in 检测参数超出(契约, 参数入口, 函数名=查名))
    # 3./4. 返回结构漂移 + 错误码漂移（都需要真实实现文件）
    # 原实现按 实现目录/{能力id末段}.py 拼接后直接传给两个检测器：路径不存在时
    # 检测返回漂移 返回 None、检测错误码漂移 返回 []，二者都不产生任何问题，
    # 即「找不到实现文件」被静默当成「无漂移」。而本仓实现文件普遍是「一包一文件」
    # （实现/包名.py 内含该包全部能力，如 支持库/前端/桌面宿主/实现/桌面宿主.py），
    # 能力id 末段几乎不与文件名相同——全仓 549 条能力实测两项检测命中 0，属永久空跑。
    # 现按权威入口（注册映射定位）取实现文件；仍定位不到时已在上方如实登记「未执行」。
    if 定位文件 is not None and 定位文件.is_file():
        返回漂移 = 检测返回漂移(契约, 定位文件)
        if 返回漂移:
            结果.问题列表.append(返回漂移)
        结果.问题列表.extend(检测错误码漂移(契约, 定位文件))
    # 5. 说明书与入口不一致
    说明书问题 = 检测说明书一致(契约, 说明书文件)
    if 说明书问题:
        结果.问题列表.append(说明书问题)
    # 6. 契约破坏但未升级主版本
    if 旧契约 is not None:
        升级问题 = 检测契约升级(旧契约, 契约)
        if 升级问题:
            结果.问题列表.append(升级问题)
    return 结果


def 全面漂移存量基线文件名() -> str:
    """全面漂移存量基线文件名（与本模块同目录）。"""
    return "全面漂移存量基线.json"


def 全面漂移默认存量基线路径() -> Path:
    """基线文件位置：本模块同目录（判据的组成部分，跟着代码走，不跟着系统根走）。"""
    return Path(__file__).resolve().with_name(全面漂移存量基线文件名())


def 全面漂移扫描(系统根: Path, *,
                基线文件: Path | None = None) -> dict[str, Any]:
    """全仓逐能力跑 `全面漂移检测`，按「包×缺口类型」分桶并消费存量基线（只读）。

    为什么要整仓跑而不是「逐包跑 `检测能力定义漂移` 就够」：`检测能力定义漂移` 只比
    「能力定义 ↔ 派生物」，**不看实现、不看说明书**——实现缺函数、参数名序漂移、
    错误码未声明、说明书缺参数/版本，它一条都拦不住。`全面漂移检测` 才是覆盖
    「契约 ↔ 实现 ↔ 说明书」三方的检测器，接线前它零调用方（第 24 项）。

    分桶与豁免口径与 `公开调用完整性门禁` 完全同形（键 = `包相对路径|缺口类型`，
    基线只减不增，基线读不成 → 全部算新增即 fail-closed），不造第二套豁免机制。

    返回：{`能力数`,`包数`,`问题列表`（判红=基线外新增）,`存量列表`,`收敛列表`,
    `缺口计数`,`定位失败数`,`只报列表`（只报不判的参数超出口径）,`基线`}。
    """
    路径 = 基线文件 if 基线文件 is not None else 全面漂移默认存量基线路径()
    基线 = 读取全面漂移基线(路径)
    条目列表: list[dict] = []
    只报列表: list[dict] = []
    包数 = 能力数 = 0
    for 顶层 in ("支持库", "模块库", "技能库"):
        根目录 = 系统根 / 顶层
        if not 根目录.is_dir():
            continue
        for 契约文件 in sorted(根目录.glob("**/能力契约/参数契约.json")):
            包目录 = 契约文件.parent.parent
            包相对路径 = (str(包目录.relative_to(系统根)) if 包目录.is_relative_to(系统根)
                        else str(包目录))
            try:
                契约条目表 = (json.loads(契约文件.read_text(encoding="utf-8"))
                          .get("能力契约") or [])
            except (OSError, json.JSONDecodeError):
                契约条目表 = []
            包数 += 1
            实现目录 = 包目录 / "实现"
            实现索引 = _实现函数索引(实现目录)
            说明书文件 = 包目录 / "说明" / "使用说明.md"
            for 契约 in 契约条目表:
                能力id = 契约.get("能力id") or ""
                if not 能力id:
                    continue
                能力数 += 1
                定位文件 = _定位实现文件(契约, 实现目录, 实现索引)
                结果 = 全面漂移检测(
                    契约=契约, 实现目录=实现目录,
                    入口文件=定位文件 or (实现目录 / f"{能力id.split('.')[-1]}.py"),
                    说明书文件=说明书文件, 实现文件=定位文件, 实现索引=实现索引,
                    包目录=包目录)
                for 问题 in 结果.问题列表:
                    条目列表.append({
                        "包": 包相对路径, "包id": str(契约.get("包id") or 包目录.name),
                        "能力id": 能力id, "缺口类型": _漂移缺口类型(问题), "详情": 问题,
                    })
                for 行 in 结果.只报列表:
                    只报列表.append({
                        "包": 包相对路径, "能力id": 能力id, "详情": 行,
                    })
    新增, 存量, 收敛 = _应用全面漂移基线(条目列表, 基线)
    缺口计数: dict[str, int] = {}
    for 条 in 条目列表:
        缺口计数[条["缺口类型"]] = 缺口计数.get(条["缺口类型"], 0) + 1
    return {
        "包数": 包数, "能力数": 能力数,
        "问题列表": 新增, "存量列表": 存量, "收敛列表": 收敛,
        "缺口计数": dict(sorted(缺口计数.items(), key=lambda 项: -项[1])),
        "定位失败数": 缺口计数.get("实现文件未定位（返回结构/错误码未执行）", 0),
        "只报列表": 只报列表, "只报计数": len(只报列表),
        "基线": {"路径": str(路径), "生效": 基线 is not None,
                "版本": (基线 or {}).get("版本", 0),
                "条目数": (基线 or {}).get("条目", {})},
    }


def 全面漂移检测门禁(系统根: Path, *,
                    基线文件: Path | None = None) -> tuple[bool, str]:
    """发布门禁用的「全面漂移」判据：**基线外新增必须阻断，基线内存量只报**。

    与 `注册口径新增判据` 同一分治口径（存量冻结 + 新增即红），不把已有的存量
    一次打成永久红。基线缺失/非法时降级为「全部算新增」（fail-closed）——判不出
    新增就不静默放过，也**不**静默判绿。
    """
    统计 = 全面漂移扫描(系统根, 基线文件=基线文件)
    新增数 = len(统计["问题列表"])
    台账 = (f"能力 {统计['能力数']}／包 {统计['包数']}；"
          f"缺口合计 {sum(统计['缺口计数'].values())} 条"
          f"（{_缺口摘要(统计['缺口计数'])}）；"
          f"存量豁免 {len(统计['存量列表'])} 条；"
          f"基线生效={统计['基线']['生效']}")
    if 新增数 == 0:
        return 真, f"无基线外新增（{台账}）"
    样例 = "；".join(f"{条['包']}|{条['缺口类型']}|{条['能力id']}: {条['详情'][:80]}"
                   for 条 in 统计["问题列表"][:5])
    return False, f"基线外新增 {新增数} 条（{台账}）：{样例}"


def _漂移缺口类型(问题: str) -> str:
    """按问题文案归到稳定的缺口类型桶（桶键进基线，必须稳定）。"""
    for 前缀, 名 in (
        ("声明能力但无实现", "声明无实现"),
        ("转调目标未解析", "转调目标未解析"),
        ("参数顺序漂移", "参数顺序漂移"),
        ("参数类型漂移", "参数类型漂移"),
        ("入口文件缺失", "入口文件缺失"),
        ("入口文件语法错误", "入口文件语法错误"),
        ("入口文件未找到函数定义", "入口无函数定义"),
        ("返回结构漂移", "返回结构漂移"),
        ("失败语义漂移", "失败语义漂移"),
        ("错误码漂移", "错误码漂移"),
        ("说明书缺失", "说明书缺失"),
        ("说明书与契约不一致", "说明书版本不一致"),
        ("说明书与入口不一致", "说明书缺参数/错误码"),
        ("契约破坏但未升级主版本", "契约破坏未升主版本"),
        ("实现文件未定位", "实现文件未定位（返回结构/错误码未执行）"),
    ):
        if 问题.startswith(前缀):
            return 名
    return "其他"


def _缺口摘要(缺口计数: dict[str, int]) -> str:
    """缺口计数 → 一行摘要（门禁详情文案用）。"""
    if not 缺口计数:
        return "无"
    return "／".join(f"{名} {数}" for 名, 数 in 缺口计数.items())


def _应用全面漂移基线(条目列表: list[dict],
                   基线: dict[str, Any] | None) -> tuple[list[dict], list[dict], list[dict]]:
    """按「包×缺口类型」消费存量基线，返回 (新增, 存量, 收敛)；基线为 None → 全算新增。"""
    上限表: dict[str, int] = ((基线 or {}).get("条目") or {}) if isinstance(基线, dict) else {}
    桶: dict[str, list[dict]] = {}
    for 条 in 条目列表:
        桶.setdefault(f"{条['包']}|{条['缺口类型']}", []).append(条)
    新增: list[dict] = []
    存量: list[dict] = []
    收敛: list[dict] = []
    for 键 in sorted(set(桶) | set(上限表)):
        条们 = 桶.get(键, [])
        上限 = int(上限表.get(键, 0) or 0)
        if len(条们) > 上限:
            新增.extend(条们[上限:])
        存量.extend(条们[:上限])
        if len(条们) < 上限:
            收敛.append({"桶": 键, "当前": len(条们), "基线": 上限})
    return 新增, 存量, 收敛


def 读取全面漂移基线(路径: Path | None) -> dict[str, Any] | None:
    """读 `{版本, 条目: {包|缺口类型: 允许条数}}`；读不成返回 None（= 不豁免任何条目）。"""
    if 路径 is None or not Path(路径).is_file():
        return None
    try:
        数据 = json.loads(Path(路径).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    if not isinstance(数据, dict) or not isinstance(数据.get("条目"), dict):
        return None
    return 数据


def 写入全面漂移基线(基线文件: Path, 基线数据: dict[str, Any]) -> None:
    """写盘：缩进 2 + 结尾换行（与仓库其它 JSON 产物一致，便于 git diff 人工裁决）。"""
    基线文件.parent.mkdir(parents=True, exist_ok=True)
    基线文件.write_text(json.dumps(基线数据, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")


def 生成全面漂移基线(系统根: Path) -> dict[str, Any]:
    """按当前仓库实测**重建**基线（仅首次初始化；日常只允许收缩，见 `全面漂移检测门禁`）。"""
    条目列表: list[dict] = []
    包数 = 能力数 = 0
    for 顶层 in ("支持库", "模块库", "技能库"):
        根目录 = 系统根 / 顶层
        if not 根目录.is_dir():
            continue
        for 契约文件 in sorted(根目录.glob("**/能力契约/参数契约.json")):
            包目录 = 契约文件.parent.parent
            包相对路径 = (str(包目录.relative_to(系统根)) if 包目录.is_relative_to(系统根)
                        else str(包目录))
            try:
                契约条目表 = (json.loads(契约文件.read_text(encoding="utf-8"))
                          .get("能力契约") or [])
            except (OSError, json.JSONDecodeError):
                契约条目表 = []
            包数 += 1
            实现目录 = 包目录 / "实现"
            实现索引 = _实现函数索引(实现目录)
            说明书文件 = 包目录 / "说明" / "使用说明.md"
            for 契约 in 契约条目表:
                能力id = 契约.get("能力id") or ""
                if not 能力id:
                    continue
                能力数 += 1
                定位文件 = _定位实现文件(契约, 实现目录, 实现索引)
                结果 = 全面漂移检测(
                    契约=契约, 实现目录=实现目录,
                    入口文件=定位文件 or (实现目录 / f"{能力id.split('.')[-1]}.py"),
                    说明书文件=说明书文件, 实现文件=定位文件, 实现索引=实现索引,
                    包目录=包目录)
                for 问题 in 结果.问题列表:
                    条目列表.append({"包": 包相对路径, "缺口类型": _漂移缺口类型(问题)})
    条目: dict[str, int] = {}
    for 条 in 条目列表:
        键 = f"{条['包']}|{条['缺口类型']}"
        条目[键] = 条目.get(键, 0) + 1
    return {
        "版本": 1,
        "口径": ("全仓逐能力跑 `全面漂移检测`（契约↔实现↔说明书三方），"
               "按「包相对路径|缺口类型」分桶计数；检测器为 python3.14 现场实跑。"),
        "说明": ("全面漂移存量基线（只减不增）：基线命中=存量（只报）；基线外=新增（判红）；"
               "基线读不成 → 全部算新增（fail-closed）。"),
        "包数": 包数, "能力数": 能力数,
        "条目": dict(sorted(条目.items())),
    }


if __name__ == "__main__":
    raise SystemExit(入口())
