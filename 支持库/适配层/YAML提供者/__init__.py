"""YAML 提供者包级中文入口（第三方 PyYAML 边界）。

调用者只从此入口导入，禁止深入 实现/ 目录。
公开能力（分组 数据交换）：
- 解析YAML → 解析后的数据
- 序列化YAML → YAML 文本
"""

from __future__ import annotations

from 公共契约.基础类型.逻辑类型 import 真, 假

from 支持库.适配层.YAML提供者.实现.提供者 import 解析YAML
from 支持库.适配层.YAML提供者.实现.提供者 import 序列化YAML
from 支持库.适配层.YAML提供者.实现.提供者 import 检查可用性
from 支持库.适配层.YAML提供者.实现.提供者 import YAML解析错误

__all__ = ["解析YAML", "序列化YAML", "检查可用性", "YAML解析错误", "注册能力"]


def 注册能力(注册表) -> None:
    """由支持库加载器调用，向能力注册表注册本提供者能力。"""
    from 公共契约.能力契约.契约 import 能力实现
    from 公共契约.基础类型.结果类型 import 结果

    def 解析YAML能力(文本: str):
        """能力边界：按契约返回结果型；裸 dict 会被统一结果契约判违约，故在此收口。"""
        try:
            return 结果.成功结果(解析YAML(文本))
        except YAML解析错误 as 错误:
            return 结果.失败("解析失败", f"YAML 解析失败: {错误}", 来源="YAML提供者")
        except Exception as 错误:
            return 结果.失败("解析失败", f"YAML 解析异常: {错误}", 来源="YAML提供者")

    def 序列化YAML能力(数据):
        try:
            return 结果.成功结果(序列化YAML(数据))
        except Exception as 错误:
            return 结果.失败("序列化失败", f"YAML 序列化异常: {错误}", 来源="YAML提供者")

    def 检查可用性能力():
        """探针能力：依赖不可用时明确失败（不静默降级）。"""
        try:
            return 结果.成功结果(检查可用性())
        except Exception as 错误:
            return 结果.失败("依赖不可用", f"PyYAML 不可用: {错误}", 来源="YAML提供者")

    for 能力id, 函数, 参数表, 说明 in [
        ("适配层.YAML提供者.解析YAML", 解析YAML能力,
         [{"名称": "文本", "类型": "文本型", "必填": 真}], "把 YAML 文本解析为数据"),
        ("适配层.YAML提供者.序列化YAML", 序列化YAML能力,
         [{"名称": "数据", "类型": "JSON值型", "必填": 真}], "把数据序列化为 YAML 文本"),
        ("适配层.YAML提供者.检查可用性", 检查可用性能力,
         [], "探针：报告 PyYAML 依赖可用性与版本"),
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
