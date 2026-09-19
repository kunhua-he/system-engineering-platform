"""唯一聚合契约解析器：契约编译器/能力搜索器/说明书生成器共用的唯一解析入口。

S0 唯一聚合格式：{契约版本, 能力契约:[{能力id,版本,说明,参数,返回,错误码,调用示例}]}。
本模块是唯一的契约解析实现：禁止各自解析与兼容双写；类型"任意"由本解析器
统一拒绝（严格模式）或归一为"未约束"（读取模式），搜索与说明书只消费本模块输出。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from 公共契约.基础类型.类型表 import 正式类型表

任意类型 = "任意"
未约束类型 = "未约束"


def 读取原始(来源: Path | str | dict) -> dict[str, Any] | None:
    """读取聚合契约 JSON（文件/文本/字典）；非法或非对象返回 None。"""
    if isinstance(来源, dict):
        return 来源
    try:
        文本 = 来源.read_text(encoding="utf-8") if isinstance(来源, Path) else 来源
        数据 = json.loads(文本)
    except (OSError, json.JSONDecodeError):
        return None
    return 数据 if isinstance(数据, dict) else None


#: 必填参数在示例里的占位值（按正式类型名给；搜到即可照抄改）。
#: 为什么需要：原实现只取「默认值非 None」的参数，**无默认值的必填参数一律不进示例** ⇒
#: 生成的示例结构上必然跑不通（实测 491/713 个能力的示例缺必填，照抄即报「缺少必填参数」）。
示例占位值: dict[str, Any] = {
    "文本型": "<必填>",
    "整数型": 0,
    "长整数型": 0,
    "双精度数型": 0.0,
    "单精度数型": 0.0,
    "逻辑型": False,
    "列表型": [],
    "字典型": {},
    "JSON值型": {},
    "字节型": "<字节>",
    "字节集型": "<字节集>",
    "日期时间型": "<日期时间>",
    "句柄型": "<句柄：由产生它的能力返回>",
    "资源引用型": "<资源引用>",
    "空值型": None,
    "结果型": {},
    "任意": "<必填>",
    "未约束": "<必填>",
}


def 示例值(参数: dict) -> Any:
    """取一个参数在调用示例里的值：有默认值用默认值，必填无默认值给类型占位值。

    不可填的可选参数（无默认值、非必填）不进示例 —— 可选参数缺失本就合法，
    填上去反而把示例变复杂（省 token 口径：示例只写到「能跑」为止）。
    """
    默认 = 参数.get("默认值")
    if 默认 is not None:
        return 默认
    if not 参数.get("必填", True):
        return None
    return 示例占位值.get(str(参数.get("类型", "")), "<必填>")


def 生成调用示例(能力id: str, 参数表: list[dict]) -> dict:
    """由参数默认值生成可执行调用示例（必填而无默认值的参数给类型占位值）。

    **「可执行」的判据是「照抄不报缺少必填参数」**，不是「参数对象非空」——
    原实现只收默认值非 None 的参数，导致必填参数整体缺失、示例必然跑不通（见 示例值 注释）。
    """
    示例参数: dict[str, Any] = {}
    for 参数 in 参数表:
        值 = 示例值(参数)
        if 值 is not None:
            示例参数[参数["名称"]] = 值
    return {"能力id": 能力id, "参数": 示例参数}


def 校验能力条目(条目: dict[str, Any], *, 严格: bool = False) -> list[str]:
    """校验一条能力契约；严格模式按 S0 全量（说明/错误码非空/调用示例/类型门禁）。"""
    问题列表 = []
    能力id = 条目.get("能力id", "")
    if not 能力id:
        问题列表.append("缺少 能力id")
    if not 条目.get("版本"):
        问题列表.append(f"能力 {能力id or '?'}: 缺少 版本")
    参数表 = 条目.get("参数")
    if not isinstance(参数表, list):
        问题列表.append(f"能力 {能力id or '?'}: 缺少 参数 列表")
    else:
        for 参数 in 参数表:
            名称 = 参数.get("名称", "")
            if not 名称:
                问题列表.append(f"能力 {能力id or '?'}: 存在缺少 名称 的参数")
                continue
            类型 = 参数.get("类型", "")
            if not 类型:
                问题列表.append(f"能力 {能力id or '?'}: 参数 {名称} 缺少 类型")
            elif 类型 == 任意类型:
                if 严格:
                    问题列表.append(f"能力 {能力id or '?'}: 参数 {名称} 类型为 任意（禁止）")
            elif 严格 and 类型 not in 正式类型表:
                问题列表.append(f"能力 {能力id or '?'}: 参数 {名称} 类型 {类型} 不在正式类型表")
    if not 条目.get("返回"):
        问题列表.append(f"能力 {能力id or '?'}: 缺少 返回")
    if "错误码" not in 条目:
        问题列表.append(f"能力 {能力id or '?'}: 缺少 错误码")
    elif 严格 and (not isinstance(条目["错误码"], list) or not 条目["错误码"]):
        问题列表.append(f"能力 {能力id or '?'}: 错误码 必须为非空列表")
    if 严格:
        if not 条目.get("说明"):
            问题列表.append(f"能力 {能力id or '?'}: 缺少 说明")
        if not 条目.get("调用示例"):
            问题列表.append(f"能力 {能力id or '?'}: 缺少 调用示例")
    return 问题列表


def 标准化条目(条目: dict[str, Any]) -> dict[str, Any]:
    """归一化一条能力条目：参数补默认字段；任意类型归一为未约束；缺调用示例生成。"""
    能力id = str(条目.get("能力id", ""))
    参数表 = []
    for 参数 in 条目.get("参数", []):
        if not isinstance(参数, dict) or not 参数.get("名称"):
            continue
        类型 = 参数.get("类型", "")
        参数表.append({
            "名称": 参数["名称"],
            "类型": 未约束类型 if 类型 == 任意类型 else 类型,
            "必填": 参数.get("必填", True),
            "默认值": 参数.get("默认值"),
            "说明": 参数.get("说明", ""),
        })
    调用示例 = 条目.get("调用示例")
    if not isinstance(调用示例, dict):
        调用示例 = 生成调用示例(能力id, 参数表)
    错误码 = 条目.get("错误码", [])
    return {
        "能力id": 能力id,
        "版本": 条目.get("版本", ""),
        "说明": 条目.get("说明", ""),
        "参数": 参数表,
        "返回": 条目.get("返回", ""),
        "错误码": 错误码 if isinstance(错误码, list) else [],
        "调用示例": 调用示例,
        "行为": 条目.get("行为", {}),
        "提供者": 条目.get("提供者", {}),
    }


def 解析聚合契约(来源: Any, *, 严格: bool = False) -> tuple[dict, list[str]]:
    """解析并归一化聚合契约；返回 (标准数据, 问题列表)。"""
    原始 = 读取原始(来源)
    if 原始 is None:
        return {"契约版本": "", "能力契约": []}, ["聚合契约 JSON 非法或缺失"]
    问题列表 = []
    契约版本 = 原始.get("契约版本")
    if 严格 and not 契约版本:
        问题列表.append("缺少 契约版本")
    能力契约 = 原始.get("能力契约")
    if not isinstance(能力契约, list):
        问题列表.append("能力契约 必须是列表")
        return {"契约版本": 契约版本 or "", "能力契约": []}, 问题列表
    if 严格 and not 能力契约:
        问题列表.append("能力契约 不能为空列表")
    条目表 = []
    for 条目 in 能力契约:
        if not isinstance(条目, dict):
            问题列表.append("能力契约 存在非对象条目")
            continue
        问题列表.extend(校验能力条目(条目, 严格=严格))
        if 条目.get("能力id"):
            条目表.append(标准化条目(条目))
    return {"契约版本": 契约版本 or "", "能力契约": 条目表}, 问题列表


def 提取能力表(聚合数据: dict[str, Any]) -> list[dict[str, Any]]:
    """从聚合契约数据提取能力条目表。"""
    if not isinstance(聚合数据, dict):
        return []
    return 聚合数据.get("能力契约", [])
