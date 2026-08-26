"""重排服务原子能力实现（不对外暴露，只经包级中文入口调用）。

职责：对检索候选文档按与查询的相关性重新排序。默认实现基于标准库
词法重叠 + 位置加权（无第三方依赖）；后续可插拔交叉编码器/重排模型
提供者（接口冻结，内核可升级）。

策略：默认 重叠得分 = 查询词命中数 + 命中位置前移加分；按得分降序重排。
边界：只做重排，不做检索、不调用模型；模型重排是提供者职责。
"""

from __future__ import annotations

import re
from typing import Any

from 公共契约.基础类型.结果类型 import 结果


def _失败(错误码: str, 消息: str) -> 结果:
    return 结果.失败(错误码, 消息, 来源="重排服务")


def _词集(文本: str) -> set[str]:
    """提取中文/英文词元（中文按字符二元组近似，英文按词）。"""
    if not isinstance(文本, str):
        return set()
    文本 = 文本.lower()
    英文词 = set(re.findall(r"[a-z0-9_]+", 文本))
    中文块 = re.sub(r"[a-z0-9_]+", " ", 文本)
    中文块 = re.sub(r"\s+", "", 中文块)
    中文二元组 = {中文块[i:i+2] for i in range(max(0, len(中文块)-1))}
    return 英文词 | 中文二元组


def _重叠得分(查询: str, 文档: str) -> float:
    查询词 = _词集(查询)
    文档词 = _词集(文档)
    if not 查询词:
        return 0.0
    命中 = 查询词 & 文档词
    if not 命中:
        return 0.0
    # 位置加权：文档靠前的命中加分
    位置分 = 0.0
    for 词 in 命中:
        idx = 文档.find(词)
        if idx >= 0:
            位置分 += 1.0 / (1.0 + idx / 100.0)
    return len(命中) + 位置分


def 重排(查询: str = None, 文档列表: list = None, 模型配置: dict = None, 顶部数量: int = None) -> 结果:
    """对候选文档按与查询的相关性重排。返回 {重排结果=[{文档, 得分, 原索引}]}。

    模型配置 预留：传入 {模型名, 提供者} 时未来走模型重排；当前忽略（标准库实现）。
    顶部数量 可选：限制返回条数（默认返回全部）。
    """
    if not isinstance(查询, str) or not 查询.strip():
        return _失败("参数不合法", "查询必须是非空字符串")
    if not isinstance(文档列表, list) or not 文档列表:
        return _失败("参数不合法", "文档列表必须是非空列表")
    try:
        带分 = []
        for 索引, 文档 in enumerate(文档列表):
            文本 = 文档 if isinstance(文档, str) else (文档.get("文本") or 文档.get("内容") or str(文档))
            得分 = _重叠得分(查询, 文本)
            带分.append({"文档": 文档, "得分": 得分, "原索引": 索引})
        带分.sort(key=lambda x: x["得分"], reverse=True)
        if 顶部数量 is not None:
            if not isinstance(顶部数量, int) or 顶部数量 <= 0:
                return _失败("参数不合法", "顶部数量必须是正整数")
            带分 = 带分[:顶部数量]
        return 结果.成功结果({"重排结果": 带分})
    except Exception as 错误:
        return _失败("重排失败", f"重排处理异常: {错误}")


def 检查可用性(模型配置: dict = None) -> 结果:
    """返回当前实现可用性。默认实现（标准库）始终可用；模型配置仅作声明。"""
    return 结果.成功结果({
        "可用": True,
        "实现": "标准库词法重排",
        "模型": (模型配置 or {}).get("模型名") or "无（标准库）",
        "提供者": (模型配置 or {}).get("提供者") or "内置",
    })
