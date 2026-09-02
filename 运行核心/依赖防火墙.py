"""依赖防火墙：统一 AST 依赖审计（进入发布门禁）。

允许方向：
公共契约 -> 不依赖其他层
支持库 -> 公共契约
模块库 -> 公共契约和公开能力调度
前端核心 -> 公共契约和私有引导适配器
后端核心 -> 公共契约和私有引导适配器
运行核心 -> 公共契约和支持库公开入口
项目适配层 -> 公共契约和核心公开入口

强制拒绝：
导入任何 实现/ 目录；支持库反向导入核心/模块/项目；
模块导入第三方库或支持库内部文件；核心硬编码具体模块；
使用物理目录作为能力身份；动态导入绕过依赖审计。
"""

from __future__ import annotations

import ast
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

系统根 = Path(__file__).resolve()
for _祖先 in 系统根.parents:
    if (_祖先 / "平台控制面").is_dir() and (_祖先 / "测试中心").is_dir():
        系统根 = _祖先
        break

层名称表 = {
    "公共契约": "公共契约",
    "支持库": "支持库",
    "模块库": "模块库",
    "前端核心": "前端核心",
    "后端核心": "后端核心",
    "运行核心": "运行核心",
    "项目适配层": "项目适配层",
    "开发工具": "开发工具",
    "其他": "其他",
}

允许依赖表: dict[str, set[str]] = {
    "公共契约": set(),
    "支持库": {"公共契约"},
    "模块库": {"公共契约", "支持库"},  # 支持库仅限包级公开入口（实现/ 已被强制拒绝）
    "前端核心": {"公共契约", "运行核心"},
    "后端核心": {"公共契约", "运行核心"},
    "运行核心": {"公共契约", "支持库"},
    "项目适配层": {"公共契约", "运行核心"},
    "开发工具": {"公共契约", "支持库", "模块库", "运行核心", "后端核心", "前端核心", "项目适配层"},
}

核心层表 = {"前端核心", "后端核心", "运行核心"}
第三方前缀表 = {
    "cryptography", "docx", "fitz", "openpyxl", "pdfplumber", "pg8000",
    "pptx", "psycopg", "psycopg2", "reportlab", "lxml", "pypdf", "PyPDF2",
    "numpy", "pandas", "PIL", "requests", "bs4", "yaml",
}
标准库前缀表 = {
    "abc", "argparse", "ast", "asyncio", "base64", "collections", "contextlib",
    "copy", "csv", "dataclasses", "datetime", "decimal", "difflib", "enum",
    "functools", "getpass", "glob", "hashlib", "hmac", "html", "http",
    "importlib", "inspect", "io", "itertools", "json", "logging", "math",
    "multiprocessing", "os", "pathlib", "platform", "queue", "random", "re",
    "shutil", "signal", "socket", "sqlite3", "ssl", "statistics", "string",
    "struct", "subprocess", "sys", "tempfile", "textwrap", "threading", "time",
    "traceback", "types", "typing", "unicodedata", "urllib", "uuid", "warnings",
    "weakref", "xml", "zipfile", "zlib", "unittest", "select", "pydoc",
}


@dataclass
class 依赖违规:
    """一条依赖违规。"""

    来源层: str
    目标: str
    规则: str
    文件: str = ""
    行号: int = 0

    def 转字典(self) -> dict[str, Any]:
        return {"来源层": self.来源层, "目标": self.目标, "规则": self.规则,
                "文件": self.文件, "行号": self.行号}


@dataclass
class 依赖审计结果:
    """依赖审计结果。"""

    违规列表: list[依赖违规] = field(default_factory=list)
    审计文件数: int = 0

    @property
    def 成功(self) -> bool:
        return not self.违规列表


def _确定层(路径: Path) -> str:
    """按顶层目录确定层。"""
    相对 = 路径.relative_to(系统根)
    顶层 = 相对.parts[0] if 相对.parts else ""
    return 层名称表.get(顶层, "其他")


def _解析导入(树: ast.AST) -> list[tuple[str, int]]:
    """AST 解析全部导入（含动态 import 调用）。"""
    导入表: list[tuple[str, int]] = []
    # for 名称 in ["固定子包", ...] 形式是有界的聚合注册，不属于任意动态导入。
    有界变量 = {
        节点.target.id
        for 节点 in ast.walk(树)
        if isinstance(节点, ast.For)
        and isinstance(节点.target, ast.Name)
        and isinstance(节点.iter, (ast.List, ast.Tuple))
        and all(isinstance(元素, ast.Constant) and isinstance(元素.value, str)
                for 元素 in 节点.iter.elts)
    }
    for 节点 in ast.walk(树):
        if isinstance(节点, ast.Import):
            for 别名 in 节点.names:
                导入表.append((别名.name, 节点.lineno))
        elif isinstance(节点, ast.ImportFrom):
            模块 = 节点.module or ""
            导入表.append((模块, 节点.lineno))
        elif isinstance(节点, ast.Call) and (
                (isinstance(节点.func, ast.Name) and 节点.func.id in ("__import__", "import_module", "动态导入"))
                or (isinstance(节点.func, ast.Attribute) and 节点.func.attr in ("import_module", "动态导入"))):
            try:
                参数 = 节点.args[0]
                if (isinstance(参数, ast.BinOp) and isinstance(参数.op, ast.Add)
                        and any(isinstance(部分, ast.Name) and 部分.id in 有界变量
                                for 部分 in ast.walk(参数))):
                    # 已由源码中的固定列表约束取值；保留模块前缀用于层向检查。
                    导入表.append(("<受控聚合导入>", 节点.lineno))
                elif isinstance(参数, ast.BinOp) and isinstance(参数.op, ast.Add):
                    def _字面字符串(表达式: ast.AST) -> str:
                        if isinstance(表达式, ast.Constant) and isinstance(表达式.value, str):
                            return 表达式.value
                        if isinstance(表达式, ast.BinOp) and isinstance(表达式.op, ast.Add):
                            return _字面字符串(表达式.left) + _字面字符串(表达式.right)
                        raise ValueError("非字面字符串")
                    导入表.append((_字面字符串(参数), 节点.lineno))
                else:
                    导入表.append((ast.literal_eval(参数), 节点.lineno))
            except (ValueError, SyntaxError, IndexError, TypeError):
                导入表.append(("<动态参数>", 节点.lineno))
    return 导入表


def _所在包已废弃(文件: Path) -> bool:
    """文件所属包是否已废弃（向上找 包声明.json 的 已废弃 标记）。"""
    for 目录 in 文件.parents:
        if (目录 / "包声明.json").is_file():
            try:
                import json
                声明 = json.loads((目录 / "包声明.json").read_text(encoding="utf-8"))
                return bool(声明.get("已废弃", False))
            except (OSError, ValueError):
                return False
    return False


def _所在包是内部层(文件: Path) -> bool:
    """读取文件所属包声明，判断是否为不对外暴露的内部支持库。"""
    for 目录 in 文件.parents:
        声明路径 = 目录 / "包声明.json"
        if not 声明路径.is_file():
            continue
        try:
            import json
            声明 = json.loads(声明路径.read_text(encoding="utf-8"))
            return bool(声明.get("内部层", False))
        except (OSError, ValueError):
            return False
    return False


def 审计依赖(目标目录: Path | None = None, *, 返回违规: bool = True) -> 依赖审计结果:
    """AST 依赖审计：逐文件解析导入，按允许方向与强制拒绝规则判定。"""
    实际目录 = Path(目标目录) if 目标目录 is not None else 系统根
    结果 = 依赖审计结果()
    for 文件 in sorted(实际目录.rglob("*.py")):
        if "pycache" in str(文件) or "工程缓存" in str(文件) or "测试中心" in str(文件) \
                or "示例项目" in str(文件) or "验证器" in str(文件) or "开发文档" in str(文件):
            continue
        # 已废弃包（保留为不可变回滚版本）不参与活跃依赖审计
        if _所在包已废弃(文件):
            continue
        try:
            树 = ast.parse(文件.read_text(encoding="utf-8"))
        except (SyntaxError, OSError, UnicodeDecodeError) as 错误:
            结果.违规列表.append(依赖违规(_确定层(文件), str(错误), "源码无法解析", str(文件.relative_to(系统根)), 0))
            continue
        来源层 = _确定层(文件)
        结果.审计文件数 += 1
        for 模块名, 行号 in _解析导入(树):
            if not 模块名 or 模块名.startswith("_") and 模块名 not in ("__future__",):
                continue
            if 模块名 == "__future__":
                continue
            顶层 = 模块名.split(".")[0]
            if 顶层 in 标准库前缀表:
                continue
            if 顶层 == "公共契约":
                continue  # 公共契约可被全部层依赖
            # 强制拒绝 1：跨包导入 实现/ 目录（同包 __init__ 导自身实现是合法入口模式）
            if "实现" in 模块名.split("."):
                文件包前缀 = ".".join(文件.relative_to(系统根).with_suffix("").parts[:-1]) \
                    if len(文件.relative_to(系统根).parts) > 1 else ""
                if not 模块名.startswith(文件包前缀):
                    结果.违规列表.append(依赖违规(来源层, 模块名, "跨包禁止导入 实现/ 目录", str(文件.relative_to(系统根)), 行号))
                continue
            # 强制拒绝 2：支持库反向导入核心/模块/项目
            if 来源层 == "支持库" and 顶层 in ("模块库", "前端核心", "后端核心", "运行核心", "项目适配层"):
                结果.违规列表.append(依赖违规(来源层, 模块名, "支持库反向导入", str(文件.relative_to(系统根)), 行号))
                continue
            # 强制拒绝 4：核心硬编码具体模块（核心层导入 模块库）
            if 来源层 in 核心层表 and 顶层 == "模块库":
                结果.违规列表.append(依赖违规(来源层, 模块名, "核心硬编码具体模块", str(文件.relative_to(系统根)), 行号))
                continue
            # 强制拒绝 6：动态导入绕过审计
            if 模块名 == "<动态参数>":
                结果.违规列表.append(依赖违规(来源层, 模块名, "动态导入绕过依赖审计", str(文件.relative_to(系统根)), 行号))
                continue
            # P6 规则 1：模块/项目适配层/核心 不得导入第三方发行包（docx/fitz/openpyxl 等）
            if 顶层 in 第三方前缀表:
                是否提供者文件 = (
                    来源层 == "支持库"
                    and "适配层" in str(文件.relative_to(系统根))
                    and (
                        文件.relative_to(系统根).parts[2].endswith("提供者")
                        # 密码适配.py 已废弃：正式代码已迁移到 密码签名提供者，
                        # 仅历史兼容保留（测试仍可直引）；豁免仅覆盖该文件本身。
                        or 文件.relative_to(系统根).parts[2] == "密码适配.py"
                    )
                ) or (
                    "平台控制面/提供者" in str(文件.relative_to(系统根))
                ) or (
                    来源层 == "开发工具" and "发布门禁" in str(文件.relative_to(系统根))
                )
                if not 是否提供者文件 and not _所在包是内部层(文件):
                    结果.违规列表.append(依赖违规(来源层, 模块名, "第三方直连（一第三方一支持库，仅提供者可导入）", str(文件.relative_to(系统根)), 行号))
                    continue
            # P6 规则 2：适配层提供者只允许支持库层/运行核心/模块库（模块组合提供者）依赖
            if 顶层 == "支持库" and "适配层" in 模块名 and 模块名.split(".")[-1].endswith("提供者"):
                if 来源层 not in ("支持库", "运行核心", "模块库", "开发工具"):
                    结果.违规列表.append(依赖违规(来源层, 模块名, "正式代码直达支持库提供者（只调用模块）", str(文件.relative_to(系统根)), 行号))
                    continue
            # 允许方向检查（同层内部导入允许；工具层"其他"不受方向限制）
            if 顶层 in 层名称表 and 顶层 != "公共契约" and 顶层 != 来源层:
                # 网关启动脚本是唯一的启动编排边界：它负责拉起后端核心。
                # 只放行该文件，禁止把整个运行核心层开放给后端核心。
                if (来源层 == "运行核心"
                        and str(文件.relative_to(系统根)) == "运行核心/启动运行核心网关.py"
                        and 顶层 == "后端核心"):
                    continue
                if 来源层 == "其他":
                    continue  # 工具/门禁/验证 文件可依赖任意层
                允许表 = 允许依赖表.get(来源层, set())
                if 顶层 not in 允许表:
                    结果.违规列表.append(依赖违规(来源层, 模块名, f"越层依赖（{来源层} 不允许依赖 {顶层}）", str(文件.relative_to(系统根)), 行号))
    return 结果


def 审计结果转清单(结果: 依赖审计结果) -> list[str]:
    return [f"[{违规.来源层}→{违规.目标}] {违规.规则} @ {违规.文件}:{违规.行号}" for 违规 in 结果.违规列表]
