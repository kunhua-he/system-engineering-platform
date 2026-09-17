"""代码解析器公共基类。

收敛 5 个解析器（通用/HTML/JS/PHP/Python）共享的解析逻辑：
切块规则加载与重载、文本解码、文件样本读取、来源引用与块构造、
python AST 切块、正则切块、HTML 切块、字节/文件解析统一入口。

子类需覆盖：
- 模块键：解析器标识（如 code-html-parser）
- 支持扩展名：允许的文件扩展名集合
- 规则文件路径：本模块目录下的 `切块规则.json` 路径
可选覆盖（专属差异）：
- 标题标签集合 / 段落标签集合 / 跳过标签集合：HTML 提取的标签差异
"""
from __future__ import annotations

import ast
import json
import re
from html.parser import HTMLParser
from pathlib import Path
from typing import ClassVar


class 代码解析错误(ValueError):
    """代码文件解析失败。"""


class _Html提取器(HTMLParser):
    """HTML 可见文本 / script / style / 标题提取器。

    标签集合由 解析器基类 的子类通过构造参数传入，支持各解析器专属差异。
    """

    def __init__(
        self,
        标题标签集合: set[str] | None = None,
        段落标签集合: set[str] | None = None,
        跳过标签集合: set[str] | None = None,
    ) -> None:
        super().__init__(convert_charrefs=True)
        self.blocks_raw: list[tuple[str, str, int]] = []
        self._capture_tag: str | None = None
        self._buf: list[str] = []
        self._start_line = 1
        self._visible_buf: list[str] = []
        self._visible_start = 1
        self._skip_depth = 0
        self._标题标签集合 = 标题标签集合 or {"h1", "h2", "h3", "h4", "h5", "h6"}
        self._段落标签集合 = 段落标签集合 or {"p", "li", "td", "th", "div", "section", "article"}
        self._跳过标签集合 = 跳过标签集合 or {"noscript"}

    def handle_starttag(self, tag: str, _attrs) -> None:
        标签 = tag.lower()
        if 标签 in {"script", "style"}:
            self._收束可见段()
            self._capture_tag = 标签
            self._buf = []
            self._start_line = self.getpos()[0]
            return
        if 标签 in self._跳过标签集合:
            self._skip_depth += 1
        if 标签 in self._标题标签集合:
            self._收束可见段()
            self._capture_tag = "heading"
            self._buf = []
            self._start_line = self.getpos()[0]
        elif 标签 in self._段落标签集合:
            if self._capture_tag is None:
                self._visible_start = self.getpos()[0]

    def handle_endtag(self, tag: str) -> None:
        标签 = tag.lower()
        if self._capture_tag in {"script", "style"} and 标签 == self._capture_tag:
            文本 = "".join(self._buf).strip()
            if 文本:
                self.blocks_raw.append(("code", 文本, self._start_line))
            self._capture_tag = None
            self._buf = []
            return
        if self._capture_tag == "heading" and 标签 in self._标题标签集合:
            文本 = "".join(self._buf).strip()
            if 文本:
                self.blocks_raw.append(("heading", 文本, self._start_line))
            self._capture_tag = None
            self._buf = []
            return
        if 标签 in self._段落标签集合:
            self._收束可见段()

    def handle_data(self, data: str) -> None:
        if self._capture_tag in {"script", "style", "heading"}:
            self._buf.append(data)
            return
        if data.strip():
            if not self._visible_buf:
                self._visible_start = self.getpos()[0]
            self._visible_buf.append(data)

    def _收束可见段(self) -> None:
        文本 = "".join(self._visible_buf).strip()
        if 文本:
            self.blocks_raw.append(("paragraph", re.sub(r"\s+", " ", 文本), self._visible_start))
        self._visible_buf = []


class 解析器基类:
    """代码解析器公共基类：切块 / 解码 / 来源引用 / 整段切分等公共逻辑。"""

    架构版本 = "内容-ir/v1"
    模块键 = "解析器基类"
    支持扩展名: ClassVar[set[str]] = set()
    规则文件路径: Path | None = None
    默认最大字节数 = 1024 * 1024
    标题标签集合: ClassVar[set[str]] = {"h1", "h2", "h3", "h4", "h5", "h6"}
    段落标签集合: ClassVar[set[str]] = {"p", "li", "td", "th", "div", "section", "article"}
    跳过标签集合: ClassVar[set[str]] = {"noscript"}

    def __init__(self, 规则文件路径: Path | str | None = None) -> None:
        # 允许无规则路径构造：按规则切块 等能力直接接收 规则 参数，无需规则文件。
        # 真正依赖规则文件的入口（加载切块规则）在使用时自行校验。
        if 规则文件路径 is not None:
            self.规则文件路径 = Path(规则文件路径)
        self._规则缓存: dict | None = None
        self._规则修改时间: float | None = None

    # ---------- 切块规则加载与重载 ----------

    def 加载切块规则(self, 强制重载: bool = False) -> dict:
        """读切块规则；默认按 mtime 缓存，强制重载=True 强制重载。"""
        if self.规则文件路径 is None:
            raise 代码解析错误("未配置切块规则文件路径")
        if not self.规则文件路径.exists():
            raise 代码解析错误(f"缺少切块规则: {self.规则文件路径}")
        修改时间 = self.规则文件路径.stat().st_mtime
        if (
            not 强制重载
            and self._规则缓存 is not None
            and self._规则修改时间 is not None
            and 修改时间 == self._规则修改时间
        ):
            return self._规则缓存
        try:
            数据 = json.loads(self.规则文件路径.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            # 坏文件不覆盖已有好缓存
            if self._规则缓存 is not None and not 强制重载:
                return self._规则缓存
            raise 代码解析错误(f"切块规则 JSON 无效: {exc}") from exc
        if not isinstance(数据, dict):
            raise 代码解析错误("切块规则必须是 JSON 对象")
        self._规则缓存 = 数据
        self._规则修改时间 = 修改时间
        return 数据

    def 重载切块规则(self) -> dict:
        """显式热加载：强制读盘并返回规则摘要（供 reload_rules capability）。"""
        规则列表 = self.加载切块规则(强制重载=True)
        单元模式列表 = 规则列表.get("unit_patterns") or []
        return {
            "ok": True,
            "module": self.模块键,
            "rules_path": str(self.规则文件路径),
            "rules_name": self.规则文件路径.name,
            "mtime": self._规则修改时间,
            "language": 规则列表.get("language"),
            "split_mode": 规则列表.get("split_mode"),
            "extensions": 规则列表.get("extensions") or sorted(self.支持扩展名),
            "unit_patterns_count": len(单元模式列表) if isinstance(单元模式列表, list) else 0,
            "max_bytes": int(规则列表.get("max_bytes", self.默认最大字节数)),
        }

    # ---------- 文本解码与样本读取 ----------

    @staticmethod
    def 解码文本(原始字节: bytes) -> tuple[str, str]:
        for 编码 in ("utf-8-sig", "utf-8", "gb18030", "gbk", "gb2312"):
            try:
                return 原始字节.decode(编码), 编码
            except (UnicodeDecodeError, LookupError):
                continue
        return 原始字节.decode("latin-1"), "latin-1"

    @staticmethod
    def 读文件样本(路径: Path, 最大字节数: int) -> tuple[bytes, dict[str, object]]:
        文件大小 = 路径.stat().st_size
        with 路径.open("rb") as 文件句柄:
            原始字节 = 文件句柄.read(最大字节数 + 4 if 文件大小 > 最大字节数 else 最大字节数)
        return 原始字节, {
            "original_size": 文件大小,
            "parsed_bytes": len(原始字节),
            "max_bytes": 最大字节数,
            "truncated": 文件大小 > len(原始字节),
        }

    # ---------- 来源引用与块构造 ----------

    def _来源引用(
        self,
        文件id: int,
        文件格式: str,
        起始行: int | None,
        结束行: int | None = None,
        章节: str = "body",
    ) -> dict[str, object]:
        return {
            "file_id": 文件id,
            "格式化": 文件格式,
            "章节": 章节,
            "line_start": 起始行,
            "line_end": 结束行 if 结束行 is not None else 起始行,
            "module": self.模块键,
        }

    @staticmethod
    def 构建块(块类型: str, 文本: str, 来源引用: dict[str, object]) -> dict[str, object]:
        return {
            "类型": 块类型,
            "文本": 文本,
            "页码": None,
            "资源引用": None,
            "source_ref": 来源引用,
        }

    @staticmethod
    def _统计行数上限(文本: str, 索引: int) -> int:
        if 索引 <= 0:
            return 1
        return 文本.count("\n", 0, 索引) + 1

    # ---------- python AST 切块 ----------

    def 切python(self, 内容: str, 文件id: int, 文件格式: str, 规则: dict) -> list[dict[str, object]]:
        块列表: list[dict[str, object]] = []
        try:
            语法树 = ast.parse(内容)
        except SyntaxError:
            return self.切正则(内容, 文件id, 文件格式, 规则)

        # 模块 docstring → heading
        模块文档 = ast.get_docstring(语法树)
        if 模块文档 and 规则.get("module_docstring_as_heading", True):
            结束行 = 1
            if 语法树.body:
                首个节点 = 语法树.body[0]
                结束行 = getattr(首个节点, "end_lineno", getattr(首个节点, "lineno", 1)) or 1
            块列表.append(self.构建块("heading", 模块文档.strip(), self._来源引用(文件id, 文件格式, 1, 结束行, "heading")))

        代码行列表 = 内容.splitlines()
        for 节点 in 语法树.body:
            if isinstance(节点, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                起始 = getattr(节点, "lineno", 1) or 1
                结束 = getattr(节点, "end_lineno", 起始) or 起始
                # 尽量包含装饰器
                if getattr(节点, "decorator_list", None):
                    起始 = min(起始, min(d.lineno for d in 节点.decorator_list if getattr(d, "lineno", None)))
                片段 = "\n".join(代码行列表[起始 - 1:结束])
                if 片段.strip():
                    块列表.append(self.构建块("code", 片段, self._来源引用(文件id, 文件格式, 起始, 结束, "code")))
                节点文档 = ast.get_docstring(节点)
                if 节点文档 and 规则.get("emit_docstring_paragraph", True):
                    块列表.append(self.构建块("paragraph", 节点文档.strip(), self._来源引用(文件id, 文件格式, 起始, 结束, "docstring")))
            elif isinstance(节点, ast.Expr) and isinstance(getattr(节点, "value", None), ast.Constant):
                # 已作为模块 docstring 处理
                continue
            elif isinstance(节点, (ast.Assign, ast.AnnAssign, ast.Import, ast.ImportFrom)):
                起始 = getattr(节点, "lineno", 1) or 1
                结束 = getattr(节点, "end_lineno", 起始) or 起始
                片段 = "\n".join(代码行列表[起始 - 1:结束])
                if 片段.strip():
                    # 顶层 import/常量并入 code
                    块列表.append(self.构建块("code", 片段, self._来源引用(文件id, 文件格式, 起始, 结束, "toplevel")))

        if not 块列表:
            return self.切正则(内容, 文件id, 文件格式, 规则)
        return self._合并相邻code(块列表)

    def _合并相邻code(self, 块列表: list[dict[str, object]]) -> list[dict[str, object]]:
        if not 块列表:
            return 块列表
        合并结果: list[dict[str, object]] = []
        for 当前块 in 块列表:
            if (
                合并结果
                and 当前块["类型"] == "code"
                and 合并结果[-1]["类型"] == "code"
                and 合并结果[-1]["source_ref"].get("章节") == "toplevel"
                and 当前块["source_ref"].get("章节") == "toplevel"
            ):
                前一块 = 合并结果[-1]
                前一块["文本"] = f"{前一块['文本']}\n{当前块['文本']}"
                前一块引用 = dict(前一块["source_ref"])
                前一块引用["line_end"] = 当前块["source_ref"].get("line_end")
                前一块["source_ref"] = 前一块引用
                continue
            合并结果.append(当前块)
        return 合并结果

    # ---------- 正则切块 ----------

    def 切正则(self, 内容: str, 文件id: int, 文件格式: str, 规则: dict) -> list[dict[str, object]]:
        行列表 = 内容.replace("\r\n", "\n").replace("\r", "\n").splitlines()
        单元模式列表 = [re.compile(p) for p in 规则.get("unit_patterns", [])]
        行注释标记 = tuple(规则.get("line_comment", []))
        块注释列表 = 规则.get("block_comment", [])
        保留缩进 = bool(规则.get("preserve_indent", True))
        基于缩进 = bool(规则.get("indent_based_body", False))
        基于大括号 = bool(规则.get("brace_based_body", False))
        按空行切 = bool(规则.get("blank_line_split", False))

        块列表: list[dict[str, object]] = []
        注释缓冲: list[str] = []
        注释起始行: int | None = None
        当前行号 = 0
        总行数 = len(行列表)

        def 刷新注释(结束行: int) -> None:
            nonlocal 注释缓冲, 注释起始行
            if not 注释缓冲:
                return
            文本 = "\n".join(注释缓冲).strip()
            if 文本:
                块列表.append(self.构建块("paragraph", 文本, self._来源引用(文件id, 文件格式, 注释起始行, 结束行, "comment")))
            注释缓冲 = []
            注释起始行 = None

        def 是否单元起始(行: str) -> bool:
            处理行 = 行 if 保留缩进 else 行.lstrip()
            return any(p.search(处理行) for p in 单元模式列表)

        def 行缩进量(行: str) -> int:
            return len(行) - len(行.lstrip(" \t"))

        # 文件头：跳过 shebang / php 开标签，收集前置注释作为 heading
        while 当前行号 < 总行数:
            去除空白 = 行列表[当前行号].strip()
            if not 去除空白:
                当前行号 += 1
                continue
            if 去除空白.startswith("#!") or 去除空白 in {"<?php", "<?", "<?="}:
                当前行号 += 1
                continue
            if any(去除空白.startswith(c) for c in 行注释标记):
                if 注释起始行 is None:
                    注释起始行 = 当前行号 + 1
                注释缓冲.append(去除空白)
                当前行号 += 1
                continue
            命中块注释 = False
            for 块注释 in 块注释列表:
                开始标记 = 块注释.get("启动", "")
                结束标记 = 块注释.get("end", "")
                if 开始标记 and 开始标记 in 行列表[当前行号]:
                    命中块注释 = True
                    if 注释起始行 is None:
                        注释起始行 = 当前行号 + 1
                    注释缓冲.append(去除空白)
                    if 结束标记 and 结束标记 in 行列表[当前行号][行列表[当前行号].find(开始标记) + len(开始标记):]:
                        当前行号 += 1
                        break
                    当前行号 += 1
                    while 当前行号 < 总行数:
                        注释缓冲.append(行列表[当前行号].strip())
                        if 结束标记 and 结束标记 in 行列表[当前行号]:
                            当前行号 += 1
                            break
                        当前行号 += 1
                    break
            if 命中块注释:
                continue
            break
        if 注释缓冲:
            原始文本 = "\n".join(x for x in 注释缓冲 if x).strip()
            清理后 = []
            for 行 in 原始文本.splitlines():
                行2 = 行.strip()
                for c in 行注释标记:
                    if 行2.startswith(c):
                        行2 = 行2[len(c):].strip()
                        break
                if 行2.startswith("/*") or 行2.startswith("/**"):
                    行2 = 行2.lstrip("/*").strip()
                if 行2.endswith("*/"):
                    行2 = 行2[:-2].strip()
                if 行2.startswith("*"):
                    行2 = 行2[1:].strip()
                if 行2:
                    清理后.append(行2)
            最终文本 = "\n".join(清理后).strip() or 原始文本
            if 最终文本:
                块列表.append(self.构建块("heading", 最终文本, self._来源引用(文件id, 文件格式, 注释起始行, 当前行号, "heading")))
            注释缓冲 = []
            注释起始行 = None

        在块注释中 = False
        块注释结束标记 = ""
        while 当前行号 < 总行数:
            当前行 = 行列表[当前行号]
            去除空白 = 当前行.strip()

            # 块注释
            if not 在块注释中:
                for 块注释 in 块注释列表:
                    开始标记 = 块注释.get("启动", "")
                    结束标记 = 块注释.get("end", "")
                    if 开始标记 and 开始标记 in 当前行:
                        在块注释中 = True
                        块注释结束标记 = 结束标记
                        if 注释起始行 is None:
                            注释起始行 = 当前行号 + 1
                        注释缓冲.append(去除空白)
                        if 结束标记 and 结束标记 in 当前行[当前行.find(开始标记) + len(开始标记):]:
                            在块注释中 = False
                            刷新注释(当前行号 + 1)
                        当前行号 += 1
                        break
                else:
                    pass
                if 在块注释中 and 注释缓冲 and 注释缓冲[-1] == 去除空白:
                    # 已消费本行
                    continue
            else:
                if 注释起始行 is None:
                    注释起始行 = 当前行号 + 1
                注释缓冲.append(去除空白)
                if 块注释结束标记 and 块注释结束标记 in 当前行:
                    在块注释中 = False
                    刷新注释(当前行号 + 1)
                当前行号 += 1
                continue

            if any(去除空白.startswith(c) for c in 行注释标记):
                if 注释起始行 is None:
                    注释起始行 = 当前行号 + 1
                注释缓冲.append(去除空白)
                当前行号 += 1
                continue
            else:
                刷新注释(当前行号)

            if not 去除空白:
                当前行号 += 1
                continue

            if 单元模式列表 and 是否单元起始(当前行):
                起始 = 当前行号 + 1
                结束 = 当前行号
                if 基于缩进:
                    基准缩进 = 行缩进量(当前行)
                    j = 当前行号 + 1
                    while j < 总行数:
                        下一行 = 行列表[j]
                        if not 下一行.strip():
                            j += 1
                            continue
                        if 行缩进量(下一行) > 基准缩进:
                            j += 1
                            continue
                        # 装饰器后的 def 已在 起始；同级结束
                        if 是否单元起始(下一行) or 行缩进量(下一行) <= 基准缩进:
                            break
                        j += 1
                    结束 = j
                elif 基于大括号:
                    括号深度 = 当前行.count("{") - 当前行.count("}")
                    j = 当前行号 + 1
                    while j < 总行数 and 括号深度 > 0:
                        括号深度 += 行列表[j].count("{") - 行列表[j].count("}")
                        j += 1
                    # 若没有大括号，退化为单行/直到空行
                    if 括号深度 == 0 and "{" not in 当前行:
                        j = 当前行号 + 1
                        while j < 总行数 and 行列表[j].strip() and not 是否单元起始(行列表[j]):
                            j += 1
                    结束 = max(j, 当前行号 + 1)
                else:
                    j = 当前行号 + 1
                    while j < 总行数 and 行列表[j].strip() and not 是否单元起始(行列表[j]):
                        j += 1
                    结束 = j
                片段行列表 = 行列表[当前行号:结束]
                片段 = "\n".join(片段行列表)
                if not 保留缩进:
                    片段 = "\n".join(x.lstrip() for x in 片段行列表)
                if 片段.strip():
                    块列表.append(self.构建块("code", 片段.rstrip(), self._来源引用(文件id, 文件格式, 起始, 结束, "code")))
                当前行号 = 结束
                continue

            if 按空行切:
                起始 = 当前行号 + 1
                j = 当前行号
                分块内容: list[str] = []
                while j < 总行数 and 行列表[j].strip():
                    if 单元模式列表 and 是否单元起始(行列表[j]) and 分块内容:
                        break
                    分块内容.append(行列表[j])
                    j += 1
                文本 = "\n".join(分块内容).rstrip()
                if 文本:
                    块列表.append(self.构建块("code", 文本, self._来源引用(文件id, 文件格式, 起始, j, "code")))
                当前行号 = j
                continue

            # 默认：逐非空行聚合到下一空行
            起始 = 当前行号 + 1
            j = 当前行号
            分块内容 = []
            while j < 总行数 and 行列表[j].strip():
                if 单元模式列表 and 是否单元起始(行列表[j]) and 分块内容:
                    break
                分块内容.append(行列表[j])
                j += 1
            文本 = "\n".join(分块内容).rstrip()
            if 文本:
                块列表.append(self.构建块("code", 文本, self._来源引用(文件id, 文件格式, 起始, j, "code")))
            当前行号 = j

        刷新注释(总行数)
        if not 块列表:
            请求体 = 内容.strip() or "(empty code file)"
            块列表.append(self.构建块(
                "code" if 内容.strip() else "paragraph",
                请求体,
                {**self._来源引用(文件id, 文件格式, 1 if 内容.strip() else None, max(总行数, 1) if 内容.strip() else None, "body"), **({"empty": True} if not 内容.strip() else {})},
            ))
        return 块列表

    # ---------- HTML 切块 ----------

    def 切html(self, 内容: str, 文件id: int, 文件格式: str, 规则: dict) -> list[dict[str, object]]:
        解析器实例 = _Html提取器(self.标题标签集合, self.段落标签集合, self.跳过标签集合)
        try:
            解析器实例.feed(内容)
            解析器实例.close()
        except Exception:
            return self.切正则(内容, 文件id, 文件格式, 规则)
        解析器实例._收束可见段()
        块列表: list[dict[str, object]] = []
        for 种类, 文本, 起始 in 解析器实例.blocks_raw:
            结束 = 起始 + max(文本.count("\n"), 0)
            块列表.append(self.构建块(种类, 文本, self._来源引用(文件id, 文件格式, 起始, 结束, 种类)))
        if not 块列表:
            return self.切正则(内容, 文件id, 文件格式, 规则)
        return 块列表

    # ---------- 按规则选择切块模式 ----------

    def 按规则切块(self, 内容: str, 文件id: int, 文件格式: str, 规则: dict) -> list[dict[str, object]]:
        切分模式 = str(规则.get("split_mode", "regex"))
        if 切分模式 == "python_ast":
            return self.切python(内容, 文件id, 文件格式, 规则)
        if 切分模式 == "html":
            return self.切html(内容, 文件id, 文件格式, 规则)
        return self.切正则(内容, 文件id, 文件格式, 规则)

    # ---------- 对外解析入口 ----------

    def 解析代码字节(
        self,
        文件id: int,
        原始字节: bytes,
        扩展名: str,
        元数据: dict[str, object] | None = None,
        规则: dict | None = None,
    ) -> dict[str, object]:
        标准化扩展名 = 扩展名.lower().lstrip(".")
        if 标准化扩展名 not in self.支持扩展名:
            raise 代码解析错误(f"Unsupported 格式化 '{标准化扩展名}'")
        规则列表 = 规则 if isinstance(规则, dict) else self.加载切块规则()
        内容, 编码 = self.解码文本(原始字节)
        内容 = 内容.replace("\r\n", "\n").replace("\r", "\n")
        块列表 = self.按规则切块(内容, 文件id, 标准化扩展名, 规则列表)
        结果元数据 = dict(元数据 or {})
        结果元数据.update({
            "encoding": 编码,
            "parser": self.模块键,
            "格式化": 标准化扩展名,
            "language": 规则列表.get("language", 标准化扩展名),
            "rules_path": str(self.规则文件路径.name) if self.规则文件路径 else "",
            "block_count": len(块列表),
        })
        return {
            "schema_version": self.架构版本,
            "content_type": "code",
            "标题": f"{标准化扩展名} code",
            "source_file_id": 文件id,
            "source_module": self.模块键,
            "parser": self.模块键,
            "source": {
                "module": self.模块键,
                "file_id": 文件id,
                "文件名": None,
                "mime_type": None,
                "格式化": 标准化扩展名,
            },
            "file_id": 文件id,
            "格式化": 标准化扩展名,
            "块列表": 块列表,
            "资源列表": [],
            "元数据": 结果元数据,
            "warnings": [],
        }

    def 解析代码文件(self, 文件id: int, 路径: Path | str, 扩展名: str) -> dict[str, object]:
        规则列表 = self.加载切块规则()
        最大字节数 = int(规则列表.get("max_bytes", self.默认最大字节数))
        完整路径 = Path(路径)
        原始字节, 元数据 = self.读文件样本(完整路径, 最大字节数=最大字节数)
        结果 = self.解析代码字节(文件id, 原始字节, 扩展名, 元数据=元数据, 规则=规则列表)
        结果["标题"] = 完整路径.name
        结果["source"]["文件名"] = 完整路径.name
        结果["元数据"]["文件名"] = 完整路径.name
        return 结果

def 扫描类属性(
    目录: str,
    属性名: str,
    递归: bool = True,
    排除关键字: list | None = None,
    最大文件数: int = 5000,
) -> 结果:
    """AST 扫描 Python 文件中「类属性 = 字符串常量」赋值，产出去重值清单。

    典型用途：扫描 ORM 数据模型的 __tablename__、扫描配置类常量等。
    只读能力：语法错误的文件跳过并计数，不中断整体扫描。
    返回 {属性名, 值列表, 文件映射, 扫描文件数, 跳过文件数}。
    """
    from pathlib import Path as _Path

    from 公共契约.基础类型.结果类型 import 结果

    if not isinstance(目录, str) or not 目录.strip():
        return 结果.失败("参数不合法", "目录必须是非空字符串", 来源="代码解析")
    if not isinstance(属性名, str) or not 属性名.strip():
        return 结果.失败("参数不合法", "属性名必须是非空字符串", 来源="代码解析")
    if not isinstance(递归, bool):
        return 结果.失败("参数不合法", "递归必须是逻辑型", 来源="代码解析")
    if not (排除关键字 is None or isinstance(排除关键字, list)):
        return 结果.失败("参数不合法", "排除关键字必须是列表型", 来源="代码解析")

    根 = _Path(目录).expanduser()
    if not 根.is_dir():
        return 结果.失败("目录不存在", f"目录不存在: {根}", 来源="代码解析")
    根 = 根.resolve()

    排除项 = tuple(str(项) for 项 in 排除关键字) if 排除关键字 else ("测试",)
    上限 = max(1, int(最大文件数)) if isinstance(最大文件数, int) and not isinstance(最大文件数, bool) else 5000

    匹配文件 = 根.rglob("*.py") if 递归 else 根.glob("*.py")
    值列表: list[str] = []
    文件映射: dict[str, list[str]] = {}
    扫描文件数 = 0
    跳过文件数 = 0

    for 文件 in sorted(匹配文件):
        if 扫描文件数 >= 上限:
            break
        名称 = str(文件.relative_to(根))
        if any(关键词 in 文件.name or 关键词 in 名称 for 关键词 in 排除项):
            continue
        try:
            源码 = 文件.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            跳过文件数 += 1
            continue
        扫描文件数 += 1
        try:
            语法树 = ast.parse(源码)
        except SyntaxError:
            跳过文件数 += 1
            continue
        本文件值: list[str] = []
        for 节点 in ast.walk(语法树):
            if not isinstance(节点, ast.Assign) or len(节点.targets) != 1:
                continue
            目标 = 节点.targets[0]
            if isinstance(目标, ast.Name) and 目标.id == 属性名:
                if isinstance(节点.value, ast.Constant) and isinstance(节点.value.value, str):
                    值 = 节点.value.value.strip()
                    if 值:
                        if 值 not in 值列表:
                            值列表.append(值)
                        if 值 not in 本文件值:
                            本文件值.append(值)
        if 本文件值:
            文件映射[名称] = 本文件值

    return 结果.成功结果({
        "属性名": 属性名,
        "值列表": 值列表,
        "文件映射": 文件映射,
        "扫描文件数": 扫描文件数,
        "跳过文件数": 跳过文件数,
    })
