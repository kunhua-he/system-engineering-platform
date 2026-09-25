"""能力调用图审计：AST+调用图检视 模块库 包内全量源码，阻断原子旁路、越界导入、四者漂移与重复能力。
模块只经 获取能力调用器().调用能力 调支持库；禁止 from/import 支持库（调用器之外）、跨包实现目录、
第三方、运行核心实现；禁止 文件读写/网络/数据库/进程/临时目录/动态导入/格式解析 原子操作；
模块库不得直接使用网络/子进程模块（`模块库网络进程表`，第二调用腿收口）。

审计范围 = **包内全量 `.py`**（`实现/` + `工具/` + 包级 `__init__.py`），不再只扫 `实现/*.py`；
原先 `工具/` 下的整包文件整体逃逸（实测 2 个）。`__init__.py` 导自身包 `实现/` 是合法入口模式，
按权威函数 `运行核心/依赖防火墙.py::同包实现导入` 逐段判定豁免，跨包 `实现/` 直连照旧阻断
（E-g：豁免判据不本地复刻，只调该函数）。
"""

from __future__ import annotations

import ast
import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

系统根 = next(祖先 for 祖先 in Path(__file__).resolve().parents if (祖先 / "模块库").is_dir() and (祖先 / "测试中心").is_dir())
if str(系统根) not in sys.path:
    sys.path.insert(0, str(系统根))

# 第三方前缀表 与 运行核心/依赖防火墙.py **共用同一个 set 对象**，禁止在本文件重定义。
# 依赖方向核对：允许依赖表["开发工具"] 含 "运行核心"（开发工具 → 运行核心 合法），
# 反向（运行核心 → 开发工具）不在允许表内，故此处单向 import 不成环、不违反层向；
# 反向引用已实测：依赖防火墙.py 无任何 开发工具.* 导入。
# 同包 `实现/` 判定同理**不本地实现**，直接用权威函数（E-f/E-g：三处审计同一行只能一个结论）。
from 运行核心.依赖防火墙 import 第三方前缀表, 同包实现导入, 排除片段表  # noqa: E402 —— 须在 系统根 入 sys.path 之后

越界前缀表 = {"支持库": "支持库直连（只允许 获取能力调用器().调用能力）", "运行核心": "运行核心实现直连", "前端核心": "核心直连", "后端核心": "核心直连", "项目适配层": "项目适配层直连"}
原子库表 = {"socket": "网络", "requests": "网络", "urllib": "网络", "http.client": "网络", "sqlite3": "数据库", "subprocess": "进程", "multiprocessing": "进程", "tempfile": "临时目录"}

#: `原子库表` 的**精确豁免**：顶层名命中、但**具体子模块不构成旁路**的那些。
#:
#: `urllib.parse` 是**纯字符串处理**（百分号解码 / URL 拆分拼接）：不做任何 I/O、
#: 不建连接、不碰 socket —— 与同顶层名的 `urllib.request` 完全两回事。
#: 触发它的实例（2026-09-23 实测）：`模块库/开工编排/实现/开工编排.py:18` 为路径边界的
#: URL 解码归一化 `from urllib.parse import unquote`，被判「原子旁路-网络」，而该项门禁
#: 口径是「干净通过、存量 0、新增即红」⇒ **真阻断**（编译口定向测试因此判红）。
#: ★ 2026-09-24（批H-H2）：那处 `unquote` 已随「判据转调唯一节点」收口删除（自写 URL 解码
#:   是第二套口径）。**豁免不随之撤销** —— 它按精确子模块名生效、与具体调用点无关，
#:   全仓仍有 `运行核心/统一网关/本地网关.py` 等多处 `urllib.parse` 使用者（纯字符串处理，
#:   不做 I/O、不碰 socket）。撤销豁免会立刻把这些文件判红 = 假红。
#:
#: 定夺依据（先分清「假红改判据」与「真红改代码」）：全仓**没有** URL 解码能力
#: （`能力目录.搜索能力` 搜「URL 解码 / 百分号解码 / unquote」实测 0 条命中）
#: ⇒ 这不是「该走能力却绕开」，而是**判据按顶层名切分切得太粗**（归因在判据侧，② 架构错位）。
#: 故按**精确名**豁免，而**不动** `urllib` 顶层整体 —— `urllib.request`/`urllib.error`/
#: `urllib.response`/`urllib.robotparser` 仍照旧判「原子旁路-网络」。
原子库精确豁免 = frozenset({"urllib.parse"})


def _被原子库精确豁免(模块名: str) -> bool:
    """`urllib.parse` 及其子模块豁免；其余（含 `urllib.request`）不豁免。"""
    return any(模块名 == 条 or 模块名.startswith(条 + ".") for 条 in 原子库精确豁免)

# 模块库不得直接使用网络/子进程模块。与 原子库表 互补、无重叠：
# 原子库表 已覆盖 socket/urllib/requests/subprocess/multiprocessing（按顶层切分精确命中）；
# 此处补①其余网络/子进程发行包，②原子库表 的 "http.client" 条目因 `_检查导入` 只取顶层切分
# （顶层 = "http"）而**恒不命中**的历史漏判 —— 改为以顶层 "http" 覆盖 http.client / http.server。
模块库网络进程表 = {
    "http": "网络", "httpx": "网络", "aiohttp": "网络", "websockets": "网络", "socketserver": "网络",
    "ftplib": "网络", "smtplib": "网络", "poplib": "网络", "imaplib": "网络", "telnetlib": "网络",
    "xmlrpc": "网络", "pty": "子进程",
}
os原子表 = {"system": "进程", "popen": "进程", "kill": "进程", "open": "文件读写", "remove": "文件写", "unlink": "文件写", "rmdir": "文件写", "mkdir": "文件写", "makedirs": "文件写", "rename": "文件写", "replace": "文件写", "write": "文件写"}
Path原子表 = {"read_bytes": "文件读", "read_text": "文件读", "write_bytes": "文件写", "write_text": "文件写", "open": "文件读写", "unlink": "文件写", "mkdir": "文件写", "touch": "文件写", "rename": "文件写", "replace": "文件写", "rmdir": "文件写"}
动态导入名 = {"__import__", "import_module"}

@dataclass
class 审计违规:
    文件: str
    行号: int
    类型: str
    详情: str = ""

    @property
    def 文本(self) -> str:
        return f"{self.文件}:{self.行号}:{self.类型}"

@dataclass
class 审计报告:
    违规列表: list[审计违规] = field(default_factory=list)
    审计文件数: int = 0

    @property
    def 成功(self) -> bool:
        return not self.违规列表

def _导入表(树: ast.AST) -> list[tuple[str, int]]:
    """收集 import/from/动态导入（__import__/import_module 实参解析）。"""
    表 = []
    for 节点 in ast.walk(树):
        if isinstance(节点, ast.Import):
            表 += [(别名.name, 节点.lineno) for 别名 in 节点.names]
        elif isinstance(节点, ast.ImportFrom):
            表.append((节点.module or "", 节点.lineno))
        elif isinstance(节点, ast.Call) and isinstance(节点.func, ast.Name) and 节点.func.id in 动态导入名:
            try:
                表.append((str(ast.literal_eval(节点.args[0])), 节点.lineno))
            except (ValueError, SyntaxError, IndexError):
                表.append(("<动态参数>", 节点.lineno))
    return 表

def _路径链(节点) -> bool:
    return isinstance(节点, ast.Call) and (isinstance(节点.func, ast.Name) and 节点.func.id == "Path" or isinstance(节点.func, ast.Attribute) and 节点.func.attr == "Path")

def _原子命中(节点) -> list[tuple[str, int, str]]:
    """扫描调用图：返回 (类型, 行号, 详情)；能力调用器调用放行。"""
    命中 = []
    for 调用 in ast.walk(节点):
        if not isinstance(调用, ast.Call):
            continue
        函数 = 调用.func
        if isinstance(函数, ast.Name):
            名称类型 = ("文件读写" if 函数.id == "open" else "动态导入" if 函数.id in 动态导入名 else None)
            if 名称类型:
                命中.append((名称类型, 调用.lineno, 函数.id))
        elif isinstance(函数, ast.Attribute) and 函数.attr != "调用能力":
            来源表 = os原子表 if isinstance(函数.value, ast.Name) and 函数.value.id == "os" else (Path原子表 if _路径链(函数.value) else None)
            if 来源表 and 函数.attr in 来源表:
                命中.append((来源表[函数.attr], 调用.lineno, 函数.attr))
            elif isinstance(函数.value, ast.Name) and 函数.value.id in 原子库表:
                命中.append((原子库表[函数.value.id], 调用.lineno, 函数.attr))
    return 命中

def _检查导入(文件: Path, 模块名: str, 行号: int, 报告: 审计报告) -> None:
    """按调用图判定导入：原子库/网络子进程禁令/跨包实现目录/第三方/越界 阻断，公共契约与标准库纯逻辑放行。

    同包 `实现/` 判定**不本地复刻**，一律调权威函数 `运行核心/依赖防火墙.py::同包实现导入`
    （E-g：本文件原有一份私有副本，且 docstring 写死「与 依赖防火墙.py:261-269 同口径」
    的陈旧行号 —— 三处审计各自实现就是 E-f 那种「同一行代码两个结论」的根因；
    私有副本已删除，只留权威函数一个出处）。
    """
    if not 模块名 or 模块名 == "__future__" or 模块名.split(".")[0] == "公共契约":
        return
    顶层 = 模块名.split(".")[0]
    类型 = (f"原子旁路-{原子库表[顶层]}" if 顶层 in 原子库表 and not _被原子库精确豁免(模块名) else
            f"模块库禁{模块库网络进程表[顶层]}模块" if 顶层 in 模块库网络进程表 else
            "实现目录直连" if "实现" in 模块名.split(".") and not 同包实现导入(文件, 模块名) else
            "第三方直连/格式解析原子实现" if 顶层 in 第三方前缀表 else
            越界前缀表.get(顶层))
    if 类型:
        报告.违规列表.append(审计违规(str(文件), 行号, 类型, 模块名))

def _模块级常量(树: ast.Module) -> dict[str, object]:
    """抽出模块级 `名字 = 字面量` 的常量绑定（能力id 常量折叠，路线 A）。

    判据工具原先只认两种 能力id 写法：字面量常量、`for 能力id, … in [...]` 列表首项。
    `模块库/文档生成/__init__.py:25` 的 `本模块能力id = "文档生成.生成文档"` 在 `:45`
    被当 能力id 用时就恒抽不到 → 注册集为空 → 报「漂移」**假红**。归因是**判据工具能力不足**
    （② 架构错位），不在被审包写法，故在审计器侧补常量折叠，而不是要求被审包改成字面量。

    判定规则：模块顶层语句顺序执行，**后写覆盖前写**（最后一次赋值为运行期真值）。
    只登记：**模块顶层**语句、**简单名目标**（`名字 = …`）、右值为**字面量**或**已绑定的
    模块级常量名**（单层别名传播）的绑定。以下一律**不登记**（不猜测、不冒充常量）：
    - 元组解包 / 下标 / 属性目标、函数/条件/循环等嵌套作用域里的赋值；
    - 右值为函数调用、下标、属性、拼接、跨模块引用等非常量表达式；
    - 引用“尚未绑定”的名字（正常 Python 会 NameError，静态不可定）。
    后写若是非常量表达式，前值的登记会被清掉 —— 折不出就走「无法静态确定」，不拿旧值蒙。
    """
    表: dict[str, object] = {}
    for 语句 in 树.body:
        if not isinstance(语句, ast.Assign):
            continue
        for 目标 in 语句.targets:
            if not isinstance(目标, ast.Name):
                continue
            表.pop(目标.id, None)  # 后写覆盖前写：先清掉旧绑定，再按本次右值决定是否重新登记
            if isinstance(语句.value, ast.Name):
                # 单层别名传播：`别名 = 本模块能力id`（只认已登记的模块级常量）。
                if 语句.value.id in 表:
                    表[目标.id] = 表[语句.value.id]
                continue
            try:
                表[目标.id] = ast.literal_eval(语句.value)
            except (ValueError, SyntaxError, TypeError):
                continue
    return 表


def _常量串(节点: ast.expr, 常量表: dict[str, object]) -> str | None:
    """把表达式折成常量字符串；折不出返回 None（**不猜**）。

    只认两种可静态确定的形态：字符串字面量、已登记的模块级常量名（值须为 str）。
    函数调用/下标/属性/拼接/跨模块引用一律返回 None，交由调用方如实记「无法静态确定」。
    """
    if isinstance(节点, ast.Constant):
        return 节点.value if isinstance(节点.value, str) else None
    if isinstance(节点, ast.Name):
        值 = 常量表.get(节点.id)
        return 值 if isinstance(值, str) else None
    return None


def _循环表(节点: ast.expr, 常量表: dict[str, object]) -> tuple[set[str], list[tuple[int, str]]]:
    """把 `for 能力id, … in [ (...), ... ]` 的列表折成 能力id 集 + 无法确定清单。

    每个元素的首项逐个走 `_常量串`（故列表里也能吃到模块级常量折叠）；折不出的元素
    按行号如实记进未定清单，**不静默丢**——漏一条就是漂移核对少一条，等于放行。
    """
    能力id集: set[str] = set()
    未定: list[tuple[int, str]] = []
    if not isinstance(节点, ast.List):
        return 能力id集, 未定
    for 元素 in 节点.elts:
        首项 = 元素.elts[0] if isinstance(元素, (ast.Tuple, ast.List)) and 元素.elts else None
        折 = _常量串(首项, 常量表) if 首项 is not None else None
        if 折 is None:
            未定.append((元素.lineno, ast.unparse(首项) if 首项 is not None else "<空元素>"))
        else:
            能力id集.add(折)
    return 能力id集, 未定


def _入口能力(包目录: Path) -> tuple[set[str], set[str], list[tuple[int, str]]]:
    """AST 提取 __init__.py 的 注册能力id 集、__all__ 函数名集、**无法静态确定**清单。

    注册 能力id 实参的静态取值支持三态（全部纯 AST，不导入被审包、不执行任何代码）：
      ① 字符串字面量；
      ② for 列表循环变量（`for 能力id, … in [("id", …)]`）——逐元素折首项；
      ③ **模块级常量**（`本模块能力id = "…"`，含一层别名传播）——常量折叠，本处新支持。
    三态之外的实参（函数调用、下标、属性、拼接、跨模块引用、循环表里折不出的首项）
    **不静默丢弃**：记进 无法确定 清单，由 `_审计包` 如实报「能力id 无法静态确定」。
    抽不到 ≠ 通过（13.1）：宁可显式报「判不了」，也不让漂移核对静默变绿。
    """
    注册集, 导出集, 循环映射 = set(), set(), {}
    无法确定: list[tuple[int, str]] = []
    try:
        树 = ast.parse((包目录 / "__init__.py").read_text(encoding="utf-8"))
    except (OSError, SyntaxError):
        return 注册集, 导出集, 无法确定
    常量表 = _模块级常量(树)
    for 节点 in ast.walk(树):
        if isinstance(节点, ast.Assign) and any(isinstance(目标, ast.Name) and 目标.id == "__all__" for 目标 in 节点.targets):
            导出集 = {元素.value for 元素 in 节点.value.elts if isinstance(元素, ast.Constant) and 元素.value not in {"注册能力", "设置HTTP连接器"}}
        elif isinstance(节点, ast.For) and isinstance(节点.iter, ast.List) and 节点.target:
            目标 = 节点.target
            变量名 = 目标.id if isinstance(目标, ast.Name) else (目标.elts[0].id if isinstance(目标, ast.Tuple) and 目标.elts and isinstance(目标.elts[0], ast.Name) else None)
            if 变量名:
                循环映射[变量名] = _循环表(节点.iter, 常量表)
        elif isinstance(节点, ast.Call) and isinstance(节点.func, ast.Attribute) and 节点.func.attr == "注册" and 节点.args and isinstance(节点.args[0], ast.Call):
            for 关键字 in 节点.args[0].keywords:
                if 关键字.arg == "能力id":
                    值 = 关键字.value
                    if isinstance(值, ast.Name) and 值.id in 循环映射:
                        # 循环变量优先于同名模块常量：循环体内该名字已被重新绑定。
                        循环集, 循环未定 = 循环映射[值.id]
                        注册集.update(循环集)
                        无法确定 += 循环未定
                        continue
                    折 = _常量串(值, 常量表)
                    if 折 is None:
                        表达式 = 值.id if isinstance(值, ast.Name) else ast.unparse(值)
                        无法确定.append((getattr(值, "lineno", 节点.lineno), 表达式))
                    else:
                        注册集.add(折)
    return 注册集, 导出集, 无法确定

def _导出名(能力id: str, 包名: str) -> str:
    """能力id → 该包 __all__ 里的函数名。

    兼容两种命名形态：`文档生成.生成文档`（模块库自命名）与
    `办公文档支持库.文档生成.生成文档`（带支持库包名前缀）。原先只用
    `removeprefix(f"{包名}.")`，第二种形态剥不掉前缀 → `__all__` 恒不等于注册集，
    会让 `模块库/文档生成` 这类包永久判漂移。
    """
    带包名 = f".{包名}."
    if 带包名 in 能力id:
        return 能力id.rsplit(带包名, 1)[1]
    return 能力id.removeprefix(f"{包名}.")


def _审计包(包目录: Path, 报告: 审计报告) -> None:
    """四者漂移：包声明/能力契约/注册能力/__all__ 能力集一致。"""
    声明集, 契约集 = set(), set()
    for 路径, 键, 是声明 in ((包目录 / "包声明.json", "能力", True),
                          (包目录 / "能力契约" / "参数契约.json", "能力契约", False)):
        try:
            集 = {项["能力id"] for 项 in json.loads(路径.read_text(encoding="utf-8")).get(键, [])}
        except (OSError, ValueError, TypeError):
            报告.违规列表.append(审计违规(f"{包目录.name}/{路径.name}", 0, "漂移", f"{路径.name}缺失或不可解析"))
        else:
            (声明集 if 是声明 else 契约集).update(集)
    注册集, 导出集, 无法确定 = _入口能力(包目录)
    # 13.1：抽不到 ≠ 放行。能力id 实参无法静态确定（常量折叠也定不了）时，
    # 注册集天然不全 —— 此时**不能**因为「集合看起来相等」就判通过，必须如实报
    # 「无法静态确定」并连同漂移一起红，避免判据工具的能力不足被静默吸收成绿灯。
    for 行号, 表达式 in 无法确定:
        报告.违规列表.append(审计违规(f"{包目录.name}/__init__.py", 行号, "漂移",
                                        f"能力id 实参 {表达式} 无法静态确定（模块级常量折叠未命中）"))
    if 声明集 != 注册集 or 声明集 != 契约集 or 导出集 != {_导出名(名, 包目录.name) for 名 in 注册集}:
        报告.违规列表.append(审计违规(f"{包目录.name}/__init__.py", 0, "漂移",
                                        f"声明:{sorted(声明集)} 契约:{sorted(契约集)} 注册:{sorted(注册集)} __all__:{sorted(导出集)}"))

#: 审计剪枝目录表 —— **与 `运行核心/依赖防火墙.py::排除片段表` 必须同口径**。
#: 为什么必须排除：`工程缓存/` 下是**编译产物与制品仓库的副本**（实测 119376 个 `.py`，
#: 占全仓 99.7%），审计扫进去会把「产物副本」当源码判违规 —— 2026-09-18 实测：传 `Path(".")`
#: 时扫出 118511 文件 / 234312 违规 / 耗时 593.6 秒，且 `公共契约/句柄体系.py` 这类**真源码**
#: 的违规被 23 万条噪声淹没＝审计等于空转。`测试中心`／`示例项目`／`开发文档` 同理不是产品源码。
#: 按「目录名精确相等」剪枝，**不用子串命中**：`"pycache" in str(路径)` 会连带剪掉文件名
#: 含该子串的真实源码文件（同 `依赖防火墙.排除片段表` 的语义修正）。
# 审计剪枝目录表**不本地复刻**：唯一事实源 = `运行核心/依赖防火墙.py::排除片段表`
# （逐元素、同序相同；依赖方向 开发工具 → 运行核心 合法）。
审计剪枝目录表 = 排除片段表


def _收集源码(根: Path) -> list[Path]:
    """递归收集**包内全量** `.py`，进目录即剪枝 `审计剪枝目录表`（与 `依赖防火墙` 同口径）。

    剪枝必须用「目录名精确相等」而不是子串命中，理由见 `审计剪枝目录表` 上方注释。
    """
    收集: list[Path] = []
    for 当前根, 子目录名表, 文件名表 in os.walk(根):
        子目录名表[:] = [名 for 名 in 子目录名表 if 名 not in 审计剪枝目录表]
        收集 += [Path(当前根) / 名 for 名 in 文件名表
                 if 名.endswith(".py") and 名 not in 审计剪枝目录表]
    return sorted(收集)


def 审计模块库(目标目录: Path | None = None) -> 审计报告:
    """AST+调用图审计 模块库 包内全量 `.py`：原子旁路/网络子进程禁令/越界导入 + 每包四者漂移 + 重复能力。"""
    实际目录 = Path(目标目录) if 目标目录 is not None else 系统根 / "模块库"
    报告 = 审计报告()
    if not 实际目录.is_dir():
        return 报告
    显示根 = 系统根 if 实际目录 == 系统根 / "模块库" else 实际目录.parent
    for 源码文件 in _收集源码(实际目录):
        报告.审计文件数 += 1
        try:
            树 = ast.parse(源码文件.read_text(encoding="utf-8"))
        except (OSError, SyntaxError):
            报告.违规列表.append(审计违规(str(源码文件.relative_to(显示根)), 0, "解析失败", ""))
            continue
        相对 = 源码文件.relative_to(显示根)
        for 模块名, 行号 in _导入表(树):
            _检查导入(相对, 模块名, 行号, 报告)
        for 类型, 行号, 详情 in _原子命中(树):
            报告.违规列表.append(审计违规(str(相对), 行号, f"原子旁路-{类型}", 详情))
        for 函数 in (节点 for 节点 in ast.walk(树) if isinstance(节点, (ast.FunctionDef, ast.AsyncFunctionDef)) and _原子命中(节点)):
            报告.违规列表.append(审计违规(str(相对), 函数.lineno, "重复能力", f"函数 {函数.name} 内复制支持库原子实现"))
    for 包目录 in sorted(实际目录.iterdir()):
        if 包目录.is_dir() and (包目录 / "实现").is_dir():
            _审计包(包目录, 报告)
    return 报告
