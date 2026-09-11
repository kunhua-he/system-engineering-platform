"""响应塑形原子能力：按路径选择、条目数与字节数裁剪结构化的工具响应。

迁移自 V3 响应塑形内核。为兼容不同调用方各自的 Agent 侧字段契约，
信封键（状态字段白名单）、元数据键与数据键全部参数化，底座内部不写死任何一方命名。
"""

from __future__ import annotations

import copy
import json
from typing import Any

from 公共契约.基础类型.结果类型 import 结果

来源标记 = "响应塑形"
默认信封键 = ["status_code", "状态", "success", "错误", "target"]
默认元数据键 = "response_meta"
默认数据键 = "data"


def _解析JSON大小(值: Any) -> int:
    """按统一序列化口径计算字节数（与调用方展示口径一致）。"""
    return len(json.dumps(值, ensure_ascii=False, indent=2).encode("utf-8"))


def _连接路径(基: str, 键: str) -> str:
    return f"{基}.{键}" if 基 else 键


def _查询路径(载荷: Any, 选择路径: str):
    """返回 (规范路径, 选中值, 警告)。"""
    片段列表 = [片段 for 片段 in 选择路径.split(".") if 片段]
    if not 片段列表:
        return None, None, "选择路径为空"

    当前 = 载荷
    已走路径: list[str] = []
    for 片段 in 片段列表:
        已走路径.append(片段)
        位置 = ".".join(已走路径)
        if isinstance(当前, dict):
            if 片段 not in 当前:
                return None, None, f"选择路径在 {位置} 处不存在"
            当前 = 当前[片段]
            continue
        if isinstance(当前, list):
            try:
                索引 = int(片段)
            except ValueError:
                return None, None, f"选择路径在 {位置} 处期望列表索引"
            if 索引 < 0 or 索引 >= len(当前):
                return None, None, f"选择路径在 {位置} 处索引越界"
            当前 = 当前[索引]
            continue
        return None, None, f"选择路径在 {位置} 处无法继续遍历标量"
    return ".".join(片段列表), 当前, None


def _已选中载荷(载荷: dict[str, Any], 选中值: Any, 信封键: list[str], 数据键: str) -> dict[str, Any]:
    """命中选择路径时，保留信封字段并把选中值放到数据键下。"""
    塑形: dict[str, Any] = {}
    for 键 in 信封键:
        if 键 in 载荷:
            塑形[键] = copy.deepcopy(载荷[键])
    内层 = 载荷.get(数据键)
    if isinstance(内层, dict):
        if "success" in 内层:
            塑形["upstream_success"] = 内层["success"]
        if "错误" in 内层:
            塑形["upstream_error"] = copy.deepcopy(内层["错误"])
    塑形[数据键] = copy.deepcopy(选中值)
    return 塑形


def _裁剪列表(值: Any, 最大条目数: int, 省略计数: dict[str, int],
              已选路径: str | None, 数据键: str, 路径: str = "") -> Any:
    if isinstance(值, list):
        省略数 = max(0, len(值) - 最大条目数)
        if 省略数:
            计数路径 = 已选路径 if 路径 == 数据键 and 已选路径 else (路径 or "$")
            省略计数[计数路径] = 省略数
        return [
            _裁剪列表(条目, 最大条目数, 省略计数, 已选路径, 数据键, _连接路径(路径, str(索引)))
            for 索引, 条目 in enumerate(值[:最大条目数])
        ]
    if isinstance(值, dict):
        return {
            键: _裁剪列表(条目, 最大条目数, 省略计数, 已选路径, 数据键, _连接路径(路径, 键))
            for 键, 条目 in 值.items()
        }
    return 值


def 摘要值(值: Any, 最大字节: int) -> Any:
    """把超限值压成带预览的摘要结构。"""
    if isinstance(值, str):
        return {
            "_truncated": True,
            "类型": "str",
            "bytes_before": _解析JSON大小(值),
            "预览": 值[: max(0, min(len(值), 最大字节 // 4))],
        }
    if isinstance(值, list):
        return {
            "_truncated": True,
            "类型": "list",
            "original_length": len(值),
            "预览": [摘要值(条目, 最大字节 // 2) for 条目 in 值[:3]],
        }
    if isinstance(值, dict):
        预览: dict[str, Any] = {}
        for 键, 条目 in list(值.items())[:8]:
            if isinstance(条目, (str, int, float, bool)) or 条目 is None:
                预览[键] = 条目
            else:
                预览[键] = 摘要值(条目, 最大字节 // 2)
        return {
            "_truncated": True,
            "类型": "dict",
            "keys": list(值.keys())[:20],
            "预览": 预览,
            "bytes_before": _解析JSON大小(值),
        }
    return 值


def _裁剪到最大字节(载荷: dict[str, Any], 最大字节: int, 元数据键: str, 数据键: str) -> dict[str, Any]:
    if _解析JSON大小(载荷) <= 最大字节:
        return 载荷

    塑形 = copy.deepcopy(载荷)
    元数据 = 塑形.setdefault(元数据键, {})
    元数据["truncated"] = True
    元数据["max_bytes"] = 最大字节
    元数据["bytes_before"] = _解析JSON大小(载荷)
    塑形[数据键] = 摘要值(塑形.get(数据键), 最大字节)
    if _解析JSON大小(塑形) <= 最大字节:
        return 塑形

    塑形[数据键] = {
        "_truncated": True,
        "类型": type(载荷.get(数据键)).__name__,
        "bytes_before": _解析JSON大小(载荷.get(数据键)),
    }
    if _解析JSON大小(塑形) <= 最大字节:
        return 塑形

    元数据["warnings"] = [*元数据.get("warnings", []), f"最小响应仍超过 {最大字节} 字节"]
    return 塑形


def 裁剪响应(
    载荷: dict,
    选择路径: str = "",
    最大条目数: int | None = None,
    最大字节数: int | None = None,
    信封键: list | None = None,
    元数据键: str | None = None,
    数据键: str | None = None,
) -> 结果:
    """按路径 / 条目数 / 字节数裁剪结构化响应。

    无任何限制参数时原样返回（不做塑形、不加元数据）。
    返回 {塑形结果, 已塑形, 已截断, 选择路径, 省略计数, 警告列表}。
    """
    if not isinstance(载荷, dict):
        return 结果.失败("参数不合法", "载荷必须是字典型", 来源=来源标记)
    if 选择路径 is None or not isinstance(选择路径, str):
        return 结果.失败("参数不合法", "选择路径必须是字符串", 来源=来源标记)
    for 名称, 值 in (("最大条目数", 最大条目数), ("最大字节数", 最大字节数)):
        if 值 is not None and (isinstance(值, bool) or not isinstance(值, int)):
            return 结果.失败("参数不合法", f"{名称}必须是整数型", 来源=来源标记)
    最终信封键 = list(信封键) if isinstance(信封键, list) else list(默认信封键)
    最终元数据键 = 元数据键 if isinstance(元数据键, str) and 元数据键 else 默认元数据键
    最终数据键 = 数据键 if isinstance(数据键, str) and 数据键 else 默认数据键

    选择路径 = 选择路径.strip()
    if not 选择路径 and 最大条目数 is None and 最大字节数 is None:
        return 结果.成功结果({
            "塑形结果": 载荷, "已塑形": False, "已截断": False,
            "选择路径": None, "省略计数": {}, "警告列表": [],
        })

    警告列表: list[str] = []
    省略计数: dict[str, int] = {}
    命中路径: str | None = None
    塑形 = copy.deepcopy(载荷)

    if 选择路径:
        规范路径, 选中值, 警告 = _查询路径(载荷, 选择路径)
        if 警告:
            警告列表.append(警告)
        else:
            命中路径 = 规范路径
            塑形 = _已选中载荷(载荷, 选中值, 最终信封键, 最终数据键)

    if 最大条目数 is not None:
        塑形 = _裁剪列表(塑形, max(0, 最大条目数), 省略计数, 命中路径, 最终数据键)

    元数据 = {
        "truncated": bool(省略计数),
        "selected_path": 命中路径,
        "omitted_counts": 省略计数,
    }
    if 警告列表:
        元数据["warnings"] = 警告列表
    塑形[最终元数据键] = 元数据

    if 最大字节数 is not None:
        塑形 = _裁剪到最大字节(塑形, max(0, 最大字节数), 最终元数据键, 最终数据键)

    return 结果.成功结果({
        "塑形结果": 塑形,
        "已塑形": True,
        "已截断": bool(省略计数) or bool((塑形.get(最终元数据键) or {}).get("truncated")),
        "选择路径": 命中路径,
        "省略计数": 省略计数,
        "警告列表": 警告列表,
    })
