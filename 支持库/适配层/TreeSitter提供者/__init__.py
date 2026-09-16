"""TreeSitter提供者 包级中文入口（第三方 tree-sitter 边界）。

调用者只从此入口导入，禁止深入 实现/ 目录。
公开能力（分组 代码语法）：
- 解析语法树 → 底座中性语法树（根节点）
- 检查可用性 → 依赖可用性探针
"""

from __future__ import annotations

from 支持库.适配层.TreeSitter提供者.实现.提供者 import 解析语法树
from 支持库.适配层.TreeSitter提供者.实现.提供者 import 检查可用性
from 支持库.适配层.TreeSitter提供者.实现.提供者 import TreeSitter解析错误
from 支持库.适配层.TreeSitter提供者.实现.提供者 import 停止

__all__ = ["解析语法树", "检查可用性", "TreeSitter解析错误", "停止", "注册能力"]

支持的语言集 = ("typescript", "tsx")


def 注册能力(注册表) -> None:
    """由支持库加载器调用，向能力注册表注册本提供者能力。"""
    from 公共契约.能力契约.契约 import 能力实现
    from 公共契约.基础类型.结果类型 import 结果

    def 解析语法树能力(代码文本: str, 语言: str = "typescript"):
        """能力边界：按契约返回结果型；依赖不可用/解析失败如实报错，不静默降级。"""
        if not isinstance(代码文本, str):
            return 结果.失败("参数不合法", "代码文本 必须是字符串", 来源="TreeSitter提供者")
        if 语言 not in 支持的语言集:
            return 结果.失败(
                "参数不合法", f"语言 必须是 {' 或 '.join(支持的语言集)}，收到 {语言!r}",
                来源="TreeSitter提供者")
        try:
            return 结果.成功结果(解析语法树(代码文本, 语言))
        except TreeSitter解析错误 as 错误:
            return 结果.失败("提供者不可用", f"tree-sitter 不可用: {错误}", 来源="TreeSitter提供者")
        except Exception as 错误:
            return 结果.失败(
                "解析失败", f"tree-sitter 解析异常: {type(错误).__name__}: {错误}",
                来源="TreeSitter提供者")

    def 检查可用性能力():
        """探针能力：依赖不可用时如实报告（不伪装可用）。"""
        try:
            return 结果.成功结果(检查可用性())
        except Exception as 错误:
            return 结果.失败("依赖不可用", f"tree-sitter 探针异常: {错误}", 来源="TreeSitter提供者")

    for 能力id, 函数, 参数表, 说明 in [
        ("适配层.TreeSitter提供者.解析语法树", 解析语法树能力,
         [{"名称": "代码文本", "类型": "文本型", "必填": True},
          {"名称": "语言", "类型": "文本型", "必填": False}],
         "把 TypeScript/TSX 源码解析为底座中性语法树（中文种类与中文字段名）"),
        ("适配层.TreeSitter提供者.检查可用性", 检查可用性能力,
         [], "探针：报告 tree-sitter 依赖可用性与版本"),
    ]:
        注册表.注册(
            能力实现(
                能力id=能力id,
                包id="支持库.适配层.TreeSitter提供者",
                实现函数=函数,
                参数=参数表,
                返回="结果",
                说明=说明,
            )
        )
