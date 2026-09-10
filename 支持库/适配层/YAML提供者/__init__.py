"""YAML 提供者包级中文入口（第三方 PyYAML 边界）。

调用者只从此入口导入，禁止深入 实现/ 目录。
公开能力（分组 数据交换）：
- 解析YAML → 解析后的数据
- 序列化YAML → YAML 文本
"""

from __future__ import annotations

from 支持库.适配层.YAML提供者.实现.提供者 import 解析YAML
from 支持库.适配层.YAML提供者.实现.提供者 import 序列化YAML
from 支持库.适配层.YAML提供者.实现.提供者 import YAML解析错误

__all__ = ["解析YAML", "序列化YAML", "YAML解析错误", "注册能力"]


def 注册能力(注册表) -> None:
    """由支持库加载器调用，向能力注册表注册本提供者能力。"""
    from 公共契约.能力契约.契约 import 能力实现

    for 能力id, 函数, 参数表, 说明 in [
        ("适配层.YAML提供者.解析YAML", 解析YAML,
         [{"名称": "文本", "类型": "文本型", "必填": True}], "把 YAML 文本解析为数据"),
        ("适配层.YAML提供者.序列化YAML", 序列化YAML,
         [{"名称": "数据", "类型": "JSON值型", "必填": True}], "把数据序列化为 YAML 文本"),
    ]:
        注册表.注册(
            能力实现(
                能力id=能力id,
                包id="支持库.适配层.YAML提供者",
                实现函数=函数,
                参数=参数表,
                返回="结果",
                说明=说明,
            )
        )
