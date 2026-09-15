"""测试资产发现：`测试中心/**/测试_*.py` 的唯一发现口径。

发现口径与 `开发工具/测试体系门禁实现/发现.py` 同源（`AGENTS.md:161/185`：
测试统一放 `测试中心/`），用 `rglob("测试_*.py")` 而不是 `unittest discover`
（discover 的 `VALID_MODULE_NAME` 只认 ASCII 标识符，加载不了中文测试文件名，
且 `AGENTS.md:138` 明确禁用 discover）。

本模块只读文件与解析 AST：**不导入任何被测模块、不执行任何用例、不打印**。
规则 1/2/3 的判据全部是「源码结构」判定（patch 目标字符串、patch kwargs、
断言实参），AST 足以覆盖；一旦为了判定去导入被测模块，门禁自身就变成了
「跑测试」，既与 `AGENTS.md:138` 冲突，也超出哲学第 12 条 1 项允许的只读轻检范围。

解析失败（读取失败/语法错误）不静默丢弃：带 `语法错误` 单独报出，由主文件
升级为违规（fail-closed）。
"""
from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

测试文件名模式 = "测试_*.py"
测试中心目录名 = "测试中心"


@dataclass(frozen=True)
class 测试资产:
    """一个测试文件的发现结果；`语法错误` 非空表示未进入三条规则扫描。"""

    文件: Path
    相对路径: str
    源码: str
    树: ast.Module | None = None
    语法错误: str = ""

    @property
    def 可用(self) -> bool:
        return self.语法错误 == "" and self.树 is not None


def _是可忽略目录(名字: str) -> bool:
    """隐藏目录与字节码缓存不属于测试资产。"""
    return 名字.startswith(".") or 名字 == "__pycache__"


def 发现测试文件(根: Path) -> list[测试资产]:
    """发现 `根/测试中心` 下全部 `测试_*.py`，按相对路径排序。

    测试中心目录不存在时返回空列表；「一个文件都没有」由调用方判定为环境
    或结构问题（本门禁只关心 mock 与断言伪装，零测试由 `测试体系门禁` 负责）。
    """
    测试中心 = 根 / 测试中心目录名
    if not 测试中心.is_dir():
        return []
    资产列表: list[测试资产] = []
    for 文件 in sorted(测试中心.rglob(测试文件名模式)):
        相对 = 文件.relative_to(根)
        if any(_是可忽略目录(片段) for 片段 in 相对.parts):
            continue
        try:
            源码 = 文件.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as 错误:
            资产列表.append(测试资产(
                文件=文件, 相对路径=相对.as_posix(), 源码="",
                语法错误=f"读取失败：{type(错误).__name__}: {错误}",
            ))
            continue
        try:
            树 = ast.parse(源码)
        except SyntaxError as 错误:
            资产列表.append(测试资产(
                文件=文件, 相对路径=相对.as_posix(), 源码=源码,
                语法错误=f"语法错误：第 {错误.lineno} 行 {错误.msg}",
            ))
            continue
        资产列表.append(测试资产(
            文件=文件, 相对路径=相对.as_posix(), 源码=源码, 树=树,
        ))
    return 资产列表
