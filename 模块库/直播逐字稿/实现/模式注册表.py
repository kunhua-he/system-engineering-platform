"""模式注册表读取：包内 模式数据/模式注册表.json 的唯一入口。

模式 = 排版模板 + 裁决提示词 + 质检规则 三件套；主流程共用，只有裁决、排版、质检附加项按模式分叉。
新增模式只改数据文件，不改代码。
"""

from __future__ import annotations

from pathlib import Path
from 公共契约.基础类型.逻辑类型 import 真, 假

来源 = "直播逐字稿"
模式数据路径 = Path(__file__).resolve().parent.parent / "模式数据" / "模式注册表.json"
_注册表缓存: dict | None = None


def _底座(能力id: str, 参数: dict):
    """经唯一能力调用服务调用底座原子能力；未装配或异常时返回 None。"""
    from 公共契约.能力契约.调用器 import 获取能力调用器
    try:
        return 获取能力调用器().调用能力(能力id, 参数, 调用方=来源)
    except Exception:
        return None


def _成功(结果对象) -> bool:
    return bool(结果对象 is not None and getattr(结果对象, "成功", 假))


def 读取模式注册表(强制重载: bool = 假) -> dict:
    """读取整张模式注册表；文件缺失或损坏时返回空注册表（不抛异常）。"""
    global _注册表缓存
    if _注册表缓存 is not None and not 强制重载:
        return _注册表缓存
    数据 = _读盘()
    if not isinstance(数据, dict) or not isinstance(数据.get("模式列表"), list):
        数据 = {"注册表版本": "", "模式列表": []}
    _注册表缓存 = 数据
    return 数据


def _读盘():
    """经底座读文件并解析为对象；任一步失败返回 None。"""
    读 = _底座("文件系统支持库.文件操作.读取文件",
              {"文件路径": str(模式数据路径), "最大字符": 0, "编码": "utf-8"})
    if not _成功(读):
        return None
    文本 = getattr(读, "值", None)
    if not isinstance(文本, str) or not 文本.strip():
        return None
    解析 = _底座("数据操作支持库.数据交换.反序列化JSON", {"文本": 文本})
    if not _成功(解析):
        return None
    return getattr(解析, "值", None)


def 模式列表() -> list[dict]:
    """返回全部模式条目（保持注册表顺序）。"""
    return [条目 for 条目 in 读取模式注册表().get("模式列表", []) if isinstance(条目, dict)]


def 取模式(编号: int) -> dict | None:
    """按模式号取条目；不存在返回 None。"""
    for 条目 in 模式列表():
        try:
            当前 = int(str(条目.get("模式") or "").strip())
        except (TypeError, ValueError):
            continue
        if 当前 == 编号:
            return 条目
    return None


def 模式编号集合() -> list[int]:
    """返回注册表内全部合法模式号（升序）。"""
    编号表: list[int] = []
    for 条目 in 模式列表():
        try:
            编号表.append(int(str(条目.get("模式") or "").strip()))
        except (TypeError, ValueError):
            continue
    return sorted(编号表)


def 模式摘要(编号: int) -> str:
    """返回 “编号 名称” 形式的展示名（缺条目时只给编号）。"""
    条目 = 取模式(编号)
    if not 条目:
        return str(编号)
    return f"{编号} {str(条目.get('名称') or '').strip()}".strip()


def 模式显示名(编号: int) -> str:
    """返回模式中文名（缺条目时为空串）。"""
    条目 = 取模式(编号)
    return str((条目 or {}).get("名称") or "").strip()


def 取裁决提示词(编号: int) -> str:
    """返回该模式的裁决提示词（缺条目为空串，由调用方决定是否失败）。"""
    条目 = 取模式(编号)
    return str((条目 or {}).get("裁决提示词") or "").strip()


def 取前置提示词(编号: int) -> str:
    """返回该模式的两阶段「前置精校」提示词。

    条目里 前置模式 指向另一个模式时，用那个模式的裁决提示词先做一遍逐句精校，
    再按本模式提示词做总结/改写——避免"直接从原始识别总结"把词改错（同音替换）。
    """
    条目 = 取模式(编号) or {}
    前置模式号 = 条目.get("前置模式")
    if 前置模式号 is None:
        return ""
    try:
        return 取裁决提示词(int(str(前置模式号).strip()))
    except (TypeError, ValueError):
        return ""


def 取质检规则(编号: int) -> dict:
    条目 = 取模式(编号) or {}
    规则 = 条目.get("质检规则")
    默认 = {"最小长度比": 0.7, "最小数字保留率": 0.85, "关键数字全保留": 假, "禁止删减": 假}
    if not isinstance(规则, dict):
        return 默认
    return {**默认, **规则}
