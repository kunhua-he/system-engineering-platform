"""原子能力实现（不对外暴露，只经包级中文入口调用）。

全部公开能力返回统一结果（成功/值/错误/错误码）；参数缺失返回 参数不合法，
序列化/解析异常转换为稳定错误码，不吞异常、不以成功形状伪装失败。
"""

from __future__ import annotations

import csv
import io
import json
from typing import Any

from 公共契约.基础类型.结果类型 import 结果


def _成功(值: Any = None) -> 结果:
    return 结果.成功结果(值)


def _失败(错误码: str, 消息: str) -> 结果:
    return 结果.失败(错误码, 消息, 来源="数据交换")


def 序列化JSON(数据: Any = None) -> 结果:
    """把字典或列表数据序列化为 JSON 文本（ensure_ascii=False，缩进 2）。"""
    if 数据 is None:
        return _失败("参数不合法", "数据不能为空")
    try:
        return _成功(json.dumps(数据, ensure_ascii=False, indent=2))
    except (TypeError, ValueError) as 错误:
        return _失败("序列化失败", f"JSON 序列化失败: {错误}")


def 反序列化JSON(文本: str = None) -> 结果:
    """把 JSON 文本解析为字典或列表。"""
    if 文本 is None or not isinstance(文本, str):
        return _失败("参数不合法", "文本必须为非空字符串")
    try:
        return _成功(json.loads(文本))
    except (json.JSONDecodeError, TypeError) as 错误:
        return _失败("反序列化失败", f"JSON 解析失败: {错误}")


def 序列化CSV(行列表: list = None) -> 结果:
    """把行列表序列化为 CSV 文本。"""
    if 行列表 is None:
        return _失败("参数不合法", "行列表不能为空")
    if not isinstance(行列表, list):
        return _失败("参数不合法", "行列表必须是列表")
    try:
        缓冲区 = io.StringIO()
        写入器 = csv.writer(缓冲区)
        写入器.writerows(行列表)
        return _成功(缓冲区.getvalue())
    except (csv.Error, TypeError, ValueError) as 错误:
        return _失败("序列化失败", f"CSV 序列化失败: {错误}")


def 反序列化CSV(文本: str = None, 分隔符: str = "", 严格模式: bool = False) -> 结果:
    """把 CSV 文本解析为行列表。

    分隔符：留空按逗号解析；支持 , \\t ; | 等单字符分隔符。
    严格模式：开启后畸形 CSV（未闭合引号等）返回 反序列化失败，而不是静默吞掉。
    """
    if 文本 is None or not isinstance(文本, str):
        return _失败("参数不合法", "文本必须为非空字符串")
    实际分隔符 = 分隔符 if isinstance(分隔符, str) and 分隔符 else ","
    if len(实际分隔符) != 1:
        return _失败("参数不合法", "分隔符必须是单个字符")
    try:
        读取器 = csv.reader(io.StringIO(文本), delimiter=实际分隔符, strict=bool(严格模式))
        return _成功([行 for 行 in 读取器])
    except (csv.Error, TypeError) as 错误:
        return _失败("反序列化失败", f"CSV 解析失败: {错误}")


def 解析YAML(文本: str = None):
    """把 YAML 文本解析为数据（经适配层 YAML提供者）。"""
    try:
        from 支持库.适配层.YAML提供者.实现.提供者 import 解析YAML as _解析YAML
        from 支持库.适配层.YAML提供者.实现.提供者 import YAML解析错误
    except ImportError as e:
        return _失败("解析失败", f"PyYAML 不可用: {e}")
    if 文本 is None:
        return _失败("参数不合法", "文本 不能为空")
    if not isinstance(文本, str):
        return _失败("参数不合法", "文本 必须是文本")
    try:
        return _成功(_解析YAML(文本))
    except YAML解析错误 as e:
        return _失败("解析失败", f"YAML 解析失败: {e}")
    except Exception as e:
        return _失败("解析失败", f"YAML 解析异常: {e}")


def 序列化YAML(数据: Any = None):
    """把数据序列化为 YAML 文本（经适配层 YAML提供者）。"""
    try:
        from 支持库.适配层.YAML提供者.实现.提供者 import 序列化YAML as _序列化YAML
    except ImportError as e:
        return _失败("序列化失败", f"PyYAML 不可用: {e}")
    try:
        return _成功(_序列化YAML(数据))
    except Exception as e:
        return _失败("序列化失败", f"YAML 序列化异常: {e}")

def 深合并(基础: dict = None, 覆盖: dict = None) -> 结果:
    """递归合并两个字典（深合并）。

    规则：同键且两边都是字典时递归合并；否则用「覆盖」的值替换。
    返回全新对象，不修改入参。
    """
    if not isinstance(基础, dict):
        return 结果.失败("参数不合法", "基础必须是字典型", 来源="数据交换")
    if not isinstance(覆盖, dict):
        return 结果.失败("参数不合法", "覆盖必须是字典型", 来源="数据交换")

    def _合并(左: dict, 右: dict) -> dict:
        结果字典 = {}
        for 键, 值 in 左.items():
            结果字典[键] = _合并(值, {}) if isinstance(值, dict) else 值
        for 键, 值 in 右.items():
            if isinstance(值, dict) and isinstance(结果字典.get(键), dict):
                结果字典[键] = _合并(结果字典[键], 值)
            elif isinstance(值, dict):
                结果字典[键] = _合并({}, 值)
            else:
                结果字典[键] = 值
        return 结果字典

    合并后 = _合并(基础, 覆盖)
    return 结果.成功结果({"合并结果": 合并后, "键数": len(合并后)})
