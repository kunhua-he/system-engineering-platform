"""模块合规验证：import 白名单、能力占用、包七要素三类校验。

模块开发门面：只读支持库公开能力 + 创建模块 + 模块合规验证；
模块禁止导入支持库实现目录/第三方/运行核心实现。

三类校验：
1. 导入白名单：AST 解析 模块库/<模块>/实现/*.py 的 import；
   允许 支持库.*（仅公开入口 __init__ 层，路径不得含 实现 或内部目录段）、
   公共契约.*、标准库；检出 支持库 内部目录导入、第三方、核心、白名单外导入。
2. 能力占用：读取 包声明.json 依赖列表，逐一核对 支持库 全包能力定义文件
   （能力定义.json 与支持库包声明.json 的能力清单）中存在提供者。
3. 包七要素：包声明.json/能力契约/说明/实现/完整性摘要/验证场景引用/__init__.py
   存在；完整性摘要用 开发工具/组件规范/完整性摘要.py 校验，漂移拒绝。

统一结果结构：{"成功": bool, "错误码": str, "违规列表": [...]}；
错误码：模块不存在 MODULE_NOT_FOUND / 导入违规 IMPORT_VIOLATION /
无提供者 NO_PROVIDER / 要素缺失 ELEMENT_MISSING / 摘要漂移 SUMMARY_DRIFT。
"""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path
from typing import Any, Iterator

# 支持库包内不允许被模块引用的内部目录段（只允许公开入口 __init__ 层）。
支持库内部目录段 = {"实现", "能力契约", "说明", "完整性摘要", "验证场景引用",
                "包声明", "默认配置", "能力数据", "__pycache__"}

# 已知第三方根模块（模块不得直接导入，第三方能力必须经支持库适配层提供）。
第三方根模块 = {
    "docx", "fitz", "openpyxl", "pdfplumber", "pptx", "reportlab",
    "cryptography", "PIL", "ffmpeg", "密码操作", "numpy", "pandas",
    "requests", "bs4", "lxml", "yaml", "sqlalchemy", "psycopg2",
    "psycopg", "pg8000", "torch", "whisper", "cv2", "matplotlib",
    "pydub", "moviepy", "selenium", "playwright", "chardet",
}

# 运行核心及其余平台核心目录（模块一律禁止导入）。
核心根目录名 = {"运行核心", "前端核心", "后端核心"}

标准库根模块 = frozenset(getattr(sys, "stdlib_module_names", set())) | {
    "__future__", "abc", "enum", "functools", "itertools", "operator",
}


def _读取声明(路径: Path) -> dict[str, Any]:
    """读取 JSON 声明；不可读或非对象返回空字典。"""
    try:
        数据 = json.loads(路径.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return 数据 if isinstance(数据, dict) else {}


def _结果(违规列表: list[dict[str, Any]], 错误码: str = "") -> dict[str, Any]:
    """统一结果结构：成功/错误码/违规列表。"""
    return {"成功": not 违规列表, "错误码": 错误码, "违规列表": 违规列表}


def _定位模块目录(项目根: Path, 模块名: str) -> Path | None:
    """定位 模块库/<模块名> 目录；兼容 模块库. 前缀。"""
    模块名 = 模块名.strip().removeprefix("模块库.").strip("/")
    if not 模块名 or 模块名 in ("", "."):
        return None
    模块目录 = 项目根 / "模块库" / 模块名
    if not 模块目录.is_dir():
        return None
    return 模块目录


def _解析导入(源码路径: Path) -> Iterator[dict[str, Any]]:
    """AST 解析单个实现文件的 import 语句，产出 行/模块。"""
    try:
        树 = ast.parse(源码路径.read_text(encoding="utf-8"))
    except (OSError, SyntaxError, UnicodeDecodeError):
        return
    for 节点 in ast.walk(树):
        if isinstance(节点, ast.Import):
            for 别名 in 节点.names:
                yield {"行": 节点.lineno, "模块": str(别名.name)}
        elif isinstance(节点, ast.ImportFrom):
            if 节点.level:
                yield {"行": 节点.lineno, "模块": "." * 节点.level + (节点.module or "")}
            elif 节点.module:
                yield {"行": 节点.lineno, "模块": str(节点.module)}


def _分类导入(导入模块: str) -> dict[str, str] | None:
    """按白名单分类单个导入；返回违规 {类别} 或 None（放行）。

    允许：标准库、公共契约.*、支持库.*（仅公开入口 __init__ 层）。
    检出：支持库内部目录（含 *.实现*）、第三方、核心、白名单外、相对导入。
    """
    模块 = 导入模块.strip()
    if not 模块:
        return None
    根 = 模块.split(".")[0]
    if 根 in 标准库根模块 or 模块.startswith("__future__"):
        return None
    if 模块 == "公共契约" or 模块.startswith("公共契约."):
        return None
    if 根 == "支持库":
        if 模块 == "支持库":
            return None
        路径段 = 模块.split(".")
        内部段 = [段 for 段 in 路径段[1:] if 段 in 支持库内部目录段]
        if 内部段:
            return {"类别": "实现目录导入", "内部段": 内部段[0]}
        return None
    if 根 in 核心根目录名:
        return {"类别": "核心导入"}
    if 根 in 第三方根模块:
        return {"类别": "第三方导入"}
    if 模块.startswith("."):
        return {"类别": "相对导入"}
    return {"类别": "白名单外导入"}


def 校验导入白名单(项目根: Path, 模块名: str) -> dict[str, Any]:
    """校验 模块库/<模块>/实现/*.py 的 import 白名单合规。

    违规项：{"文件": 相对路径, "行": 行号, "模块": 导入模块名, "类别": 类别}。
    """
    模块目录 = _定位模块目录(项目根, 模块名)
    if 模块目录 is None:
        return _结果([{"文件": "模块库/" + 模块名.strip("模块库.").strip("/"),
                       "行": 0, "模块": 模块名, "类别": "模块不存在"}],
                      "MODULE_NOT_FOUND")
    违规列表: list[dict[str, Any]] = []
    实现目录 = 模块目录 / "实现"
    if 实现目录.is_dir():
        for 源码路径 in sorted(实现目录.glob("*.py")):
            相对路径 = 源码路径.relative_to(项目根).as_posix()
            for 导入 in _解析导入(源码路径):
                分类 = _分类导入(导入["模块"])
                if 分类 is None:
                    continue
                违规列表.append({
                    "文件": 相对路径,
                    "行": int(导入["行"]),
                    "模块": 导入["模块"],
                    "类别": 分类["类别"],
                })
    return _结果(违规列表, "IMPORT_VIOLATION" if 违规列表 else "")


def _收集支持库能力(项目根: Path) -> set[str]:
    """收集 支持库 全包能力定义（能力定义.json + 支持库包声明.json 能力清单）。"""
    能力集合: set[str] = set()
    支持库根 = 项目根 / "支持库"
    if not 支持库根.is_dir():
        return 能力集合
    for 定义路径 in 支持库根.rglob("能力定义.json"):
        定义 = _读取声明(定义路径)
        能力列表 = 定义.get("能力列表", 定义.get("能力定义", []))
        for 能力 in 能力列表 if isinstance(能力列表, list) else []:
            if isinstance(能力, dict) and 能力.get("能力id"):
                能力集合.add(str(能力["能力id"]))
    for 声明路径 in 支持库根.rglob("包声明.json"):
        声明 = _读取声明(声明路径)
        for 能力 in 声明.get("能力", []) if isinstance(声明.get("能力", []), list) else []:
            if isinstance(能力, dict) and 能力.get("能力id"):
                能力集合.add(str(能力["能力id"]))
    return 能力集合


def 校验能力占用(项目根: Path, 模块名: str) -> dict[str, Any]:
    """校验模块声明依赖在 支持库 全包能力定义中存在提供者。

    违规项：{"文件": "包声明.json", "行": 0, "模块": 能力id, "类别": "无提供者"}。
    """
    模块目录 = _定位模块目录(项目根, 模块名)
    if 模块目录 is None:
        return _结果([{"文件": "模块库/" + 模块名.strip("模块库.").strip("/"),
                       "行": 0, "模块": 模块名, "类别": "模块不存在"}],
                      "MODULE_NOT_FOUND")
    声明 = _读取声明(模块目录 / "包声明.json")
    依赖列表 = 声明.get("依赖", [])
    提供者能力 = _收集支持库能力(项目根)
    违规列表: list[dict[str, Any]] = []
    for 依赖 in 依赖列表 if isinstance(依赖列表, list) else []:
        if not isinstance(依赖, dict):
            continue
        能力id = str(依赖.get("能力", ""))
        if 能力id and 能力id not in 提供者能力:
            违规列表.append({
                "文件": "模块库/" + 模块名.strip("模块库.").strip("/") + "/包声明.json",
                "行": 0, "模块": 能力id, "类别": "无提供者",
            })
    return _结果(违规列表, "NO_PROVIDER" if 违规列表 else "")


包七要素名称 = ("包声明.json", "能力契约", "说明", "实现", "完整性摘要.json",
            "验证场景引用.json", "__init__.py")


def _要素缺失违规(模块目录: Path, 要素: str) -> dict[str, Any]:
    return {"文件": 模块目录.as_posix() + "/" + 要素, "行": 0,
            "模块": 模块目录.name, "类别": "要素缺失", "要素": 要素}


def 校验包七要素(项目根: Path, 模块名: str) -> dict[str, Any]:
    """校验模块包七要素存在，并用 开发工具/组件规范/完整性摘要.py 校验摘要。

    违规项类别：要素缺失（缺文件/目录/内容）/ 摘要漂移（完整性摘要不闭合）。
    """
    模块目录 = _定位模块目录(项目根, 模块名)
    if 模块目录 is None:
        return _结果([{"文件": "模块库/" + 模块名.strip("模块库.").strip("/"),
                       "行": 0, "模块": 模块名, "类别": "模块不存在"}],
                      "MODULE_NOT_FOUND")
    违规列表: list[dict[str, Any]] = []
    if not (模块目录 / "包声明.json").is_file():
        违规列表.append(_要素缺失违规(模块目录, "包声明.json"))
    elif not _读取声明(模块目录 / "包声明.json"):
        违规列表.append({"文件": (模块目录 / "包声明.json").as_posix(), "行": 0,
                       "模块": 模块目录.name, "类别": "要素缺失", "要素": "包声明.json",
                       "说明": "包声明.json 不可读或非对象"})
    能力契约目录 = 模块目录 / "能力契约"
    if not 能力契约目录.is_dir() or not (能力契约目录 / "参数契约.json").is_file():
        违规列表.append(_要素缺失违规(模块目录, "能力契约"))
    说明目录 = 模块目录 / "说明"
    if not 说明目录.is_dir() or not any(说明目录.iterdir()):
        违规列表.append(_要素缺失违规(模块目录, "说明"))
    实现目录 = 模块目录 / "实现"
    if not 实现目录.is_dir() or not any(实现目录.glob("*.py")):
        违规列表.append(_要素缺失违规(模块目录, "实现"))
    for 要素 in ("完整性摘要.json", "验证场景引用.json", "__init__.py"):
        if not (模块目录 / 要素).is_file():
            违规列表.append(_要素缺失违规(模块目录, 要素))
    if not (模块目录 / "完整性摘要.json").is_file():
        return _结果(违规列表, "ELEMENT_MISSING" if 违规列表 else "")
    from 开发工具.组件规范.完整性摘要 import 校验完整性摘要
    摘要通过, 摘要问题 = 校验完整性摘要(模块目录)
    if not 摘要通过:
        for 问题 in 摘要问题:
            违规列表.append({
                "文件": (模块目录 / "完整性摘要.json").as_posix(),
                "行": 0, "模块": 模块目录.name, "类别": "摘要漂移", "说明": str(问题),
            })
    if any(项["类别"] == "摘要漂移" for 项 in 违规列表):
        return _结果(违规列表, "SUMMARY_DRIFT")
    return _结果(违规列表, "ELEMENT_MISSING" if 违规列表 else "")


def 校验模块合规(项目根: Path, 模块名: str) -> dict[str, Any]:
    """统一入口：合并导入白名单、能力占用、包七要素三类校验结果。

    成功 = 三类均无违规；错误码取首个违规错误码，均无违规时为空串。
    """
    模块目录 = _定位模块目录(项目根, 模块名)
    if 模块目录 is None:
        return _结果([{"文件": "模块库/" + 模块名.strip("模块库.").strip("/"),
                       "行": 0, "模块": 模块名, "类别": "模块不存在"}],
                      "MODULE_NOT_FOUND")
    导入结果 = 校验导入白名单(项目根, 模块名)
    占用结果 = 校验能力占用(项目根, 模块名)
    要素结果 = 校验包七要素(项目根, 模块名)
    违规列表 = (
        导入结果.get("违规列表", [])
        + 占用结果.get("违规列表", [])
        + 要素结果.get("违规列表", [])
    )
    if not 违规列表:
        return _结果([])
    for 错误码 in ("MODULE_NOT_FOUND", "IMPORT_VIOLATION", "NO_PROVIDER",
                   "ELEMENT_MISSING", "SUMMARY_DRIFT"):
        if 错误码 in (导入结果.get("错误码"), 占用结果.get("错误码"),
                     要素结果.get("错误码")):
            return _结果(违规列表, 错误码)
    return _结果(违规列表)
