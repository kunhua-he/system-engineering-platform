"""能力调用图审计：AST+调用图检视 模块库 实现，阻断原子旁路、越界导入、四者漂移与重复能力。
模块只经 获取能力调用器().调用能力 调支持库；禁止 from/import 支持库（调用器之外）、实现目录、
第三方、运行核心实现；禁止 文件读写/网络/数据库/进程/临时目录/动态导入/格式解析 原子操作。
"""

from __future__ import annotations

import ast
import json
from dataclasses import dataclass, field
from pathlib import Path

系统根 = next(祖先 for 祖先 in Path(__file__).resolve().parents if (祖先 / "模块库").is_dir() and (祖先 / "测试中心").is_dir())
越界前缀表 = {"支持库": "支持库直连（只允许 获取能力调用器().调用能力）", "运行核心": "运行核心实现直连", "前端核心": "核心直连", "后端核心": "核心直连", "项目适配层": "项目适配层直连"}
第三方前缀表 = {"cryptography", "docx", "fitz", "openpyxl", "pdfplumber", "pg8000", "pptx", "psycopg", "psycopg2", "reportlab", "lxml", "pypdf", "PyPDF2", "numpy", "pandas", "PIL", "requests", "bs4", "yaml"}
原子库表 = {"socket": "网络", "requests": "网络", "urllib": "网络", "http.client": "网络", "sqlite3": "数据库", "subprocess": "进程", "multiprocessing": "进程", "tempfile": "临时目录"}
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
    """按调用图判定导入：越界/第三方/实现目录/原子库 阻断，公共契约与标准库纯逻辑放行。"""
    if not 模块名 or 模块名 == "__future__" or 模块名.split(".")[0] == "公共契约":
        return
    顶层 = 模块名.split(".")[0]
    类型 = (f"原子旁路-{原子库表[顶层]}" if 顶层 in 原子库表 else
            "实现目录直连" if "实现" in 模块名.split(".") else
            "第三方直连/格式解析原子实现" if 顶层 in 第三方前缀表 else
            越界前缀表.get(顶层))
    if 类型:
        报告.违规列表.append(审计违规(str(文件), 行号, 类型, 模块名))

def _入口能力(包目录: Path) -> tuple[set[str], set[str]]:
    """AST 提取 __init__.py 的 注册能力id 集与 __all__ 函数名集（含循环注册）。"""
    注册集, 导出集, 循环映射 = set(), set(), {}
    try:
        树 = ast.parse((包目录 / "__init__.py").read_text(encoding="utf-8"))
    except (OSError, SyntaxError):
        return 注册集, 导出集
    for 节点 in ast.walk(树):
        if isinstance(节点, ast.Assign) and any(isinstance(目标, ast.Name) and 目标.id == "__all__" for 目标 in 节点.targets):
            导出集 = {元素.value for 元素 in 节点.value.elts if isinstance(元素, ast.Constant) and 元素.value not in {"注册能力", "设置HTTP连接器"}}
        elif isinstance(节点, ast.For) and isinstance(节点.iter, ast.List) and 节点.target:
            目标 = 节点.target
            变量名 = 目标.id if isinstance(目标, ast.Name) else (目标.elts[0].id if isinstance(目标, ast.Tuple) and 目标.elts and isinstance(目标.elts[0], ast.Name) else None)
            if 变量名:
                循环映射[变量名] = [元素.elts[0].value for 元素 in 节点.iter.elts if isinstance(元素, ast.Tuple) and 元素.elts and isinstance(元素.elts[0], ast.Constant)]
        elif isinstance(节点, ast.Call) and isinstance(节点.func, ast.Attribute) and 节点.func.attr == "注册" and 节点.args and isinstance(节点.args[0], ast.Call):
            for 关键字 in 节点.args[0].keywords:
                if 关键字.arg == "能力id":
                    if isinstance(关键字.value, ast.Constant):
                        注册集.add(关键字.value.value)
                    elif isinstance(关键字.value, ast.Name) and 关键字.value.id in 循环映射:
                        注册集.update(循环映射[关键字.value.id])
    return 注册集, 导出集

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
    注册集, 导出集 = _入口能力(包目录)
    前缀 = f"{包目录.name}."
    if 声明集 != 注册集 or 声明集 != 契约集 or 导出集 != {名.removeprefix(前缀) for 名 in 注册集}:
        报告.违规列表.append(审计违规(f"{包目录.name}/__init__.py", 0, "漂移",
                                        f"声明:{sorted(声明集)} 契约:{sorted(契约集)} 注册:{sorted(注册集)} __all__:{sorted(导出集)}"))

def 审计模块库(目标目录: Path | None = None) -> 审计报告:
    """AST+调用图审计 模块库：实现文件原子旁路/越界导入 + 每包四者漂移 + 重复能力。"""
    实际目录 = Path(目标目录) if 目标目录 is not None else 系统根 / "模块库"
    报告 = 审计报告()
    if not 实际目录.is_dir():
        return 报告
    显示根 = 系统根 if 实际目录 == 系统根 / "模块库" else 实际目录.parent
    for 实现文件 in sorted(实际目录.rglob("实现/*.py")):
        if "pycache" in str(实现文件):
            continue
        报告.审计文件数 += 1
        try:
            树 = ast.parse(实现文件.read_text(encoding="utf-8"))
        except (OSError, SyntaxError):
            报告.违规列表.append(审计违规(str(实现文件.relative_to(显示根)), 0, "解析失败", ""))
            continue
        相对 = 实现文件.relative_to(显示根)
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
