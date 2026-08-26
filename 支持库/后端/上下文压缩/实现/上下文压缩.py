"""上下文压缩原子能力实现（不对外暴露，只经包级中文入口调用）。

职责：对话历史的 token 估算与压缩（借鉴 Claude Code compact + Codex auto_compact）。
额度原则（华哥口径）：默认不限制；调用时可通过参数配置额度。
- 压缩阈值：默认 None（内置默认 8000 token），调用方可配置。
- 摘要长度上限：默认 None（不限制），调用方可配置。
压缩策略：保留最近 N 条完整消息，更早消息合并为摘要。
只做估算与压缩，不调用模型；摘要生成由调用方/提供者完成。
"""

from __future__ import annotations

from typing import Any

from 公共契约.基础类型.结果类型 import 结果

默认压缩阈值 = 8000   # token


def _估算文本token(文本: str) -> int:
    """中文约 1 token/字（保守 0.6），英文约 4 字符/token。"""
    if not 文本:
        return 0
    # 简单估算：中文按 1 字 ≈ 1 token，英文按 4 字符 ≈ 1 token
    中文字数 = sum(1 for c in 文本 if ord(c) > 127)
    英文字符数 = len(文本) - 中文字数
    return int(中文字数 * 0.8 + 英文字符数 / 4) + 1


def 估算token数(文本: str = None) -> 结果:
    """估算文本 token 数。返回 {token数, 字符数}。"""
    if not isinstance(文本, str):
        return 结果.失败("参数不合法", "文本必须是非空字符串", 来源="上下文压缩")
    return 结果.成功结果({"token数": _估算文本token(文本), "字符数": len(文本)})


def 估算消息token数(消息列表: list = None) -> 结果:
    """估算消息列表 token 数（含角色开销）。返回 {token数, 消息数}。"""
    if not isinstance(消息列表, list) or not 消息列表:
        return 结果.失败("参数不合法", "消息列表必须是非空列表", 来源="上下文压缩")
    总数 = 0
    for 消息 in 消息列表:
        if not isinstance(消息, dict):
            continue
        内容 = str(消息.get("content", ""))
        总数 += _估算文本token(内容) + 4  # 角色/格式开销
    return 结果.成功结果({"token数": 总数, "消息数": len(消息列表)})


def 压缩历史(消息列表: list = None, 压缩阈值: int = None,
             保留最近条数: int = None, 摘要长度上限: int = None, 摘要模式: str = None) -> 结果:
    """压缩对话历史：超阈值时，保留最近 N 条完整，更早消息合并为摘要。

    额度原则：压缩阈值 默认 None（内置 8000）；摘要长度上限 默认 None（不限制）。
    返回 {已压缩, 压缩前token, 压缩后token, 消息列表, 摘要}。
    """
    if not isinstance(消息列表, list) or not 消息列表:
        return 结果.失败("参数不合法", "消息列表必须是非空列表", 来源="上下文压缩")
    阈值 = 压缩阈值 if isinstance(压缩阈值, int) and 压缩阈值 > 0 else 默认压缩阈值
    保留条数 = 保留最近条数 if isinstance(保留最近条数, int) and 保留最近条数 > 0 else 10
    模式 = (摘要模式 or "拼接").strip()
    if 模式 not in ("拼接", "截断"):
        return 结果.失败("参数不合法", f"摘要模式必须是 拼接/截断: {摘要模式}", 来源="上下文压缩")

    压缩前token = sum(_估算文本token(str(m.get("content", ""))) + 4 for m in 消息列表 if isinstance(m, dict))
    if 压缩前token <= 阈值:
        return 结果.成功结果({
            "已压缩": False, "压缩前token": 压缩前token, "压缩后token": 压缩前token,
            "消息列表": 消息列表, "摘要": "", "说明": f"未超阈值 {阈值}，无需压缩",
        })

    保留列表 = 消息列表[-保留条数:]
    早期列表 = 消息列表[:-保留条数]
    # 合并摘要：角色:内容 拼接
    摘要文本 = "\n".join(
        f"{m.get('role', 'user')}: {m.get('content', '')}" for m in 早期列表 if isinstance(m, dict)
    )
    if 摘要长度上限 is not None and isinstance(摘要长度上限, int) and 摘要长度上限 > 0:
        if 模式 == "截断":
            摘要文本 = 摘要文本[:摘要长度上限] + ("…" if len(摘要文本) > 摘要长度上限 else "")
        else:
            # 拼接模式：按 token 上限截断
            if _估算文本token(摘要文本) > 摘要长度上限:
                摘要文本 = 摘要文本[:摘要长度上限 * 2]  # 粗略字符截断
                摘要文本 = 摘要文本[:摘要长度上限 * 2] + "…"

    新消息列表 = [{"role": "system", "content": f"[历史摘要] {摘要文本}"}] + 保留列表 if 摘要文本 else list(保留列表)
    压缩后token = _估算文本token(摘要文本) + sum(_估算文本token(str(m.get("content", ""))) + 4 for m in 保留列表 if isinstance(m, dict))
    return 结果.成功结果({
        "已压缩": True, "压缩前token": 压缩前token, "压缩后token": 压缩后token,
        "消息列表": 新消息列表, "摘要": 摘要文本,
        "说明": f"超阈值 {阈值}，保留最近 {保留条数} 条，早期 {len(早期列表)} 条并入摘要",
    })
