"""目录遍历 + 切块：只调 `代码解析支持库.按规则切块`，不重写切块算法。

为什么用 `按规则切块` 而不是 `解析代码文件`：后者无条件加载规则 JSON 文件，
而全仓当前**没有任何 `切块规则.json`**（实测 find 零命中），传不存在的路径必失败；
`按规则切块` 直接收 规则 字典，正是为这种「规则由调用方提供」的场景设计的。

边界：本文件只负责「找到文件 → 切出块 → 带上真实行号」，不生成嵌入、不落库。
单文件失败不中断整轮（隔离进跳过清单），因为一个语法错文件不该废掉整仓索引。
"""
from __future__ import annotations

from pathlib import Path

默认排除目录 = (".git", "__pycache__", ".venv", "venv", "node_modules", "dist", "build",
                ".pytest_cache", ".mypy_cache", ".ruff_cache", ".codegraph",
                "工程缓存", "工程制品", "运行数据")

扩展名到格式 = {".py": "python", ".ts": "typescript", ".tsx": "typescript",
                ".js": "javascript", ".jsx": "javascript", ".mjs": "javascript",
                ".vue": "vue"}

Python规则 = {
    "language": "python", "split_mode": "python_ast", "extensions": ["py"],
    "max_bytes": 1048576,
    "unit_patterns": ["^def ", "^class ", "^async def "],
    "line_comment": ["#"], "block_comment": [], "preserve_indent": True,
    "indent_based_body": True, "module_docstring_as_heading": True,
    "emit_docstring_paragraph": True,
}

脚本规则 = {
    "language": "typescript", "split_mode": "regex",
    "extensions": ["ts", "tsx", "js", "jsx", "vue"], "max_bytes": 1048576,
    "unit_patterns": [r"^\s*(export\s+)?(async\s+)?function\s",
                      r"^\s*(export\s+)?(abstract\s+)?class\s",
                      r"^\s*(export\s+)?(const|let|var)\s+\w+\s*=\s*(async\s*)?\(",
                      r"^\s*<script"],
    "line_comment": ["//"], "block_comment": [{"启动": "/*", "end": "*/"}],
    "preserve_indent": True, "blank_line_split": False,
}

读取编码链 = ("utf-8-sig", "utf-8", "gb18030", "gbk")


def 取规则(文件格式: str) -> dict:
    return Python规则 if 文件格式 == "python" else 脚本规则


def 遍历代码文件(索引根: str, 排除目录: list | None = None) -> list[Path]:
    """递归收集待索引代码文件（路径排序稳定，同输入同顺序）。"""
    根 = Path(索引根).expanduser().resolve()
    排除集 = set(默认排除目录 if not 排除目录 else [str(项) for 项 in 排除目录])
    文件列表: list[Path] = []
    for 路径 in sorted(根.rglob("*")):
        if not 路径.is_file():
            continue
        if 路径.suffix.lower() not in 扩展名到格式:
            continue
        相对 = 路径.relative_to(根)
        if any(片段 in 排除集 for 片段 in 相对.parts[:-1]):
            continue
        文件列表.append(路径)
    return 文件列表


def 读文本(路径: Path) -> str | None:
    """多编码回退读取（与平台解析器同一条编码链），读不出返回 None。"""
    try:
        原始字节 = 路径.read_bytes()
    except OSError:
        return None
    for 编码 in 读取编码链:
        try:
            return 原始字节.decode(编码)
        except (UnicodeDecodeError, LookupError):
            continue
    return None


def _调用能力(能力id: str, 参数: dict):
    from 公共契约.能力契约.调用器 import 获取能力调用器
    return 获取能力调用器().调用能力(能力id, 参数, 调用方="语义索引")


def 切单文件(路径: Path, 文件id: int, 文件格式: str) -> tuple[list[dict], str]:
    """切一个文件；返回（块记录列表, 错误说明）；错误说明非空即该文件失败。"""
    文本 = 读文本(路径)
    if 文本 is None:
        return [], "文件无法按已知编码解码"
    调用结果 = _调用能力("代码解析支持库.按规则切块",
                     {"内容": 文本, "文件id": 文件id, "文件格式": 文件格式,
                      "规则": 取规则(文件格式)})
    if not 调用结果.成功:
        return [], f"{调用结果.错误码}: {调用结果.错误说明}"
    块列表 = 调用结果.值
    if not isinstance(块列表, list):
        return [], "切块返回不是块列表"
    记录列表: list[dict] = []
    for 块 in 块列表:
        if not isinstance(块, dict):
            continue
        块文本 = str(块.get("文本") or "").strip()
        引用 = 块.get("source_ref") if isinstance(块.get("source_ref"), dict) else {}
        if not 块文本:
            continue
        起始行 = int(引用.get("line_start") or 1)
        结束行 = int(引用.get("line_end") or 起始行)
        记录列表.append({"文件路径": str(路径), "起始行": 起始行, "结束行": 结束行,
                       "块类型": str(块.get("类型") or "code"), "块文本": 块文本})
    return 记录列表, ""


def 收集代码块(索引根: str, 排除目录: list | None = None) -> dict:
    """遍历并切块：返回 {块列表, 文件数, 跳过清单}；单文件失败只进跳过清单。"""
    文件列表 = 遍历代码文件(索引根, 排除目录)
    块列表: list[dict] = []
    跳过清单: list[dict] = []
    成功文件数 = 0
    for 序号, 路径 in enumerate(文件列表, start=1):
        文件格式 = 扩展名到格式[路径.suffix.lower()]
        try:
            记录列表, 错误说明 = 切单文件(路径, 序号, 文件格式)
        except Exception as 错误:  # 单文件异常不废掉整仓
            记录列表, 错误说明 = [], f"{type(错误).__name__}: {错误}"
        if 错误说明:
            跳过清单.append({"文件路径": str(路径), "原因": 错误说明})
            continue
        成功文件数 += 1
        块列表.extend(记录列表)
    return {"块列表": 块列表, "文件数": 成功文件数, "跳过清单": 跳过清单}


__all__ = ["默认排除目录", "扩展名到格式", "遍历代码文件", "读文本", "切单文件",
           "收集代码块", "取规则"]
