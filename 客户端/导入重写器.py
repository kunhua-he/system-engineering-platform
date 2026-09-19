"""导入重写器：把顶层平台导入改写为 `平台客户端.` 前缀（构建平台客户端拆分件）。

2026-09-19 从 `客户端/构建平台客户端.py` 原样搬出（对外零变化）：类名、成员名、签名、
默认值、文档串与拆分前逐字一致；冻结基线 `/tmp/拆分基线/构建平台客户端.py`
（sha256 前16 = `a632e3398f121f5b`，对应提交 a5e9dcc1）。

**入口仍是 `客户端/构建平台客户端.py`**（本类按名回导到入口模块命名空间）。

职责边界：本类只做**语法层改写**（`ast.NodeTransformer`），改写规则的两张清单（`顶层包表` /
`客户端前缀`）由**构造参数**传入 —— 入口模块的 `复制并重写` 用入口模块自己的常量构造它
（那是 `mock.patch.multiple(构建模块, 顶层包表=…)` 的打补丁目标），故本模块不存第二份字面量。
`__future__` 不重写这一条是**有意**的（见 `_改写模块名`），不是漏网。
"""
from __future__ import annotations

import ast


class 导入重写器(ast.NodeTransformer):
    """把顶层平台导入改写为 平台客户端. 前缀（from/import 两种形态）。"""

    def __init__(self, 顶层包表: list[str], 前缀: str) -> None:
        self.顶层包表 = tuple(顶层包表)
        self.前缀 = 前缀
        self.改写数 = 0

    def _改写模块名(self, 模块名: str) -> str:
        if 模块名 == "__future__" or not 模块名:
            return 模块名
        顶层 = 模块名.split(".")[0]
        if 顶层 in self.顶层包表:
            self.改写数 += 1
            return f"{self.前缀}.{模块名}"
        return 模块名

    def visit_Import(self, 节点: ast.Import) -> ast.Import:
        for 别名 in 节点.names:
            别名.name = self._改写模块名(别名.name)
        return 节点

    def visit_ImportFrom(self, 节点: ast.ImportFrom) -> ast.ImportFrom:
        if 节点.module:
            节点.module = self._改写模块名(节点.module)
        return 节点
