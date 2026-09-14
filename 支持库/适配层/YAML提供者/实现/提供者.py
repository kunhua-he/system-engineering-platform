"""YAML 适配提供者：第三方 PyYAML 的唯一边界封装。

只允许在本适配层 import yaml；上层支持库（数据操作支持库）不得直接依赖第三方。
"""

from __future__ import annotations

from typing import Any

try:
    import yaml as _yaml
except ImportError as _错误:  # pragma: no cover
    raise ImportError(
        "PyYAML 未安装：请通过 pip 安装 pyyaml（本机 pip 源已配 127.0.0.1:4780 代理）"
    ) from _错误


YAML解析错误 = _yaml.YAMLError


def 解析YAML(文本: str) -> Any:
    """把 YAML 文本解析为数据，解析失败抛 YAML解析错误。"""
    return _yaml.safe_load(文本)


def 序列化YAML(数据: Any) -> str:
    """把数据序列化为 YAML 文本。"""
    return _yaml.safe_dump(数据, allow_unicode=True, sort_keys=False)


def 依赖版本() -> str:
    """读取 PyYAML 版本（不可读取时返回空文本）。"""
    return str(getattr(_yaml, "__version__", "") or "")


def 检查可用性() -> dict[str, Any]:
    """探针：PyYAML 是否可导入及版本；供健康检查与依赖审计使用。"""
    return {"可用": True, "版本": 依赖版本(), "说明": "PyYAML 可导入"}
