"""reportlab 提供者包级中文入口（主进程直接加载 reportlab）。

调用者只从此入口导入，禁止深入 实现/ 目录。
公开能力：PDF生成.生成PDF（标题/段落列表/表格列表 → 生成产物字典）。
reportlab 为纯 Python 库，主进程 import，不启用子进程隔离。
"""

from __future__ import annotations

from 支持库.适配层.reportlab提供者.实现.生成PDF import 生成PDF

__all__ = ["生成PDF"]


def 注册能力(注册表) -> None:
    """由支持库加载器调用，向能力注册表注册本库能力。"""
    from 公共契约.能力契约.契约 import 能力实现

    注册表.注册(
        能力实现(
            能力id="PDF生成.生成PDF",
            包id="支持库.适配层.reportlab提供者",
            实现函数=生成PDF,
            参数=[{"名称": "参数", "类型": "对象"}],
            返回="结果",
            说明="按内容参数字典（标题/段落列表/表格列表）生成 PDF，返回生成产物字典",
        )
    )
