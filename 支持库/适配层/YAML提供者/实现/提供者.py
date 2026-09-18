"""YAML 适配提供者：第三方 PyYAML 的唯一边界封装。

只允许在本适配层 import yaml；上层支持库（数据操作支持库）不得直接依赖第三方。
"""

from __future__ import annotations

from typing import Any

错误码_依赖不可用 = "依赖不可用"
来源 = "YAML提供者"

# —— 容忍式导入（2026-09-19 修，与 psycopg提供者 同口径）——
# 改前这里是**严格导入**（缺包即抛 ImportError），于是干净机器 / CI / 未装 PyYAML 的
# Windows、Linux 上本包在「入口装配」阶段直接抛错，被 `生命周期管理/管理器.py` 记成
# 「已跳过 …｜入口装配｜装配失败」，装配冒烟「无跳过包」断言随之失败。
# 本包是**纯 Python 库**，按 `运行核心/运行环境管理器/提供者生命周期.py` 的提供者隔离
# 边界（原生扩展与不可控全局状态第三方不得在主进程导入）允许主进程导入，故装配**不得**
# 因缺依赖被阻断：依赖缺失只在**调用时**以中文错误码体现，绝不静默降级、不假装成功。
_导入失败原因: str = ""
_yaml: Any = None
try:
    import yaml as _yaml
except Exception as _导入异常:  # 依赖缺失与版本不兼容都在此收口，原因留痕
    _导入失败原因 = f"{type(_导入异常).__name__}: {_导入异常}"


class YAML依赖不可用(RuntimeError):
    """PyYAML 不可导入时抛出的明确失败（中文错误码 依赖不可用 的承载异常）。"""


# 依赖可用时本名即第三方 `yaml.YAMLError`（既有类型口径逐字不变，调用方
# `except YAML解析错误` 原样成立）；不可用时退化为依赖缺失异常，两种环境下都可捕获。
YAML解析错误 = _yaml.YAMLError if _yaml is not None else YAML依赖不可用


def _确保可用() -> None:
    """依赖不可用时明确抛出 YAML依赖不可用（不静默降级、不返回空值冒充成功）。"""
    if _yaml is None:
        raise YAML依赖不可用(f"PyYAML 不可导入：{_导入失败原因}")


def 解析YAML(文本: str) -> Any:
    """把 YAML 文本解析为数据，解析失败抛 YAML解析错误；依赖缺失抛 YAML依赖不可用。"""
    _确保可用()
    return _yaml.safe_load(文本)


def 序列化YAML(数据: Any) -> str:
    """把数据序列化为 YAML 文本；依赖缺失抛 YAML依赖不可用。"""
    _确保可用()
    return _yaml.safe_dump(数据, allow_unicode=True, sort_keys=False)


def 依赖版本() -> str:
    """读取 PyYAML 版本（不可读取时返回空文本）。"""
    if _yaml is None:
        return ""
    return str(getattr(_yaml, "__version__", "") or "")


def 检查可用性() -> dict[str, Any]:
    """探针：PyYAML 是否可导入及版本；供健康检查与依赖审计使用。

    依赖缺失时**如实**返回 可用=假 与留痕的导入失败原因（不抛、不伪装可用），
    由能力层把 可用=假 翻成中文错误码 依赖不可用。
    """
    if _yaml is None:
        return {"可用": False, "版本": "", "说明": f"PyYAML 不可导入：{_导入失败原因}"}
    return {"可用": True, "版本": 依赖版本(), "说明": "PyYAML 可导入"}
