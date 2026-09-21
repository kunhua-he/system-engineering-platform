"""实现定位：实现文件定位与 AST 静态助手

本模块是 `开发工具/契约编译/漂移检测.py` 的**内部搬家**产物（对外符号零变化）：
`漂移检测.py` 仍是契约漂移门禁的对外唯一门面，全部公开符号依然从那里导入；
本模块只承载实现，**不构成第二份判据**。原有文档串与注释一字未改。

依赖：仅 `公共契约.基础类型.逻辑类型`。
"""


from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

from 公共契约.基础类型.逻辑类型 import 真, 假

# ---- 对外符号回托 ----
# 本块从 `漂移检测.py` 原地搬来时用到这些名；`漂移检测.<名>` 是全仓调用方与源码文本
# 依赖的对外面（多处注释与测试直接 grep `开发工具/契约编译/漂移检测.<符号>`），
# 故在此显式回托成模块级属性。仅 re-export，无任何语义改动。
真 = 真
假 = 假

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
        return 假
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
    # 兜底候选：文件里出现的所有「点分模块名」字符串（含 `唯一实现名 = "…"` 这类绑定）。
    #
    # ★ 2026-09-22 加宽（实测 47 条能力被误报为「转调目标未解析」）：本仓现行转调写法是
    #   `唯一实现名 = 取根前缀(__name__) + "支持库.适配层.X.实现.Y"` —— 根前缀在制品里才不同、
    #   必须运行时求值，所以那一段是 BinOp 而不是字符串常量。只收「绑定到 Name 的常量」时，
    #   拼接写法整批落到「未解析出静态模块名」；但**字面量那一段**本身就能定位到文件。
    #   故同时收「加法表达式两侧的模块名形字符串常量」。多收的候选由「能定位到文件且
    #   目标里定义了该函数」的下游判据自然筛掉，不会拿无关字符串冒充已解析。
    for 值 in list(绑定.values()):
        if _疑似模块名字符串(值):
            候选.append(值)
    for 节点 in ast.walk(树):
        if not (isinstance(节点, ast.BinOp) and isinstance(节点.op, ast.Add)):
            continue
        for 侧 in (节点.left, 节点.right):
            if isinstance(侧, ast.Constant) and _疑似模块名字符串(侧.value):
                候选.append(侧.value)
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
