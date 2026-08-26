"""上下文压缩原子能力实现（不对外暴露，只经包级中文入口调用）。

职责：对话历史的 token 估算与压缩（借鉴 Claude Code compact + Codex auto_compact）。
额度原则：默认不限制；调用时可通过参数配置额度。
压缩策略：保留最近 N 条完整消息，更早消息合并为摘要。
数据源（华哥口径）：压缩从会话存储读历史（句柄 + 会话id），压完写回；
保留 消息列表 直传兜底（无会话存储时用）。
只做估算与压缩，不调用模型。
"""

from __future__ import annotations

from 公共契约.基础类型.结果类型 import 结果

默认压缩阈值 = 8000


def _从会话存储读取(句柄: str, 会话id: str) -> tuple[list | None, str]:
    """经会话存储读历史，返回 (消息列表, 错误)。不可用时返回 (None, 原因)。"""
    try:
        from 支持库.后端.大语言模型支持库.会话存储 import 读取历史
        r = 读取历史(句柄=句柄, 会话id=会话id)
        if not r.成功:
            return None, f"读取历史失败: {r.错误说明}"
        消息列表 = []
        for 消息 in r.值.get("消息列表", []):
            内容 = 消息.get("内容", {})
            正文 = 内容.get("正文", "") if isinstance(内容, dict) else str(内容)
            消息列表.append({"role": 消息.get("角色", "用户"), "content": 正文})
        return 消息列表, ""
    except Exception as e:
        return None, f"会话存储不可用: {e}"


def _估算文本token(文本: str) -> int:
    """中文约 1 token/字（保守 0.6），英文约 4 字符/token。"""
    if not 文本:
        return 0
    中文字数 = sum(1 for c in 文本 if ord(c) > 127)
    英文字符数 = len(文本) - 中文字数
    return int(中文字数 * 0.8 + 英文字符数 / 4) + 1


def 估算token数(文本: str = None) -> 结果:
    if not isinstance(文本, str):
        return 结果.失败("参数不合法", "文本必须是非空字符串", 来源="上下文压缩")
    return 结果.成功结果({"token数": _估算文本token(文本), "字符数": len(文本)})


def 估算消息token数(消息列表: list = None) -> 结果:
    if not isinstance(消息列表, list) or not 消息列表:
        return 结果.失败("参数不合法", "消息列表必须是非空列表", 来源="上下文压缩")
    总数 = 0
    for 消息 in 消息列表:
        if not isinstance(消息, dict):
            continue
        内容 = str(消息.get("content", ""))
        总数 += _估算文本token(内容) + 4
    return 结果.成功结果({"token数": 总数, "消息数": len(消息列表)})


def 压缩历史(消息列表: list = None, 压缩阈值: int = None,
             保留最近条数: int = None, 摘要长度上限: int = None, 摘要模式: str = None,
             句柄: str = None, 会话id: str = None) -> 结果:
    """压缩对话历史。数据源优先：传 句柄+会话id 从会话存储读取，否则用 消息列表 兜底。

    额度原则：压缩阈值/摘要长度上限 默认 None（内置 8000/不限制），调用方可配置。
    超限不是拒绝，是触发压缩的信号（由调用方决定是否压缩后重试）。
    返回 {已压缩, 压缩前token, 压缩后token, 消息列表, 摘要}。
    """
    # 从会话存储读取（华哥口径：句柄+会话id，不是请求包）
    if 句柄 and 会话id:
        消息列表, 错误 = _从会话存储读取(句柄, 会话id)
        if 消息列表 is None:
            return 结果.失败("读取历史失败", 错误, 来源="上下文压缩")
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
    # 摘要预算：早期内容必须显著压缩（默认压缩到早期 token 的 20%，可配上限）
    早期token = sum(_估算文本token(str(m.get("content", ""))) + 4 for m in 早期列表 if isinstance(m, dict))
    摘要预算 = 摘要长度上限 if isinstance(摘要长度上限, int) and 摘要长度上限 > 0 else max(200, int(早期token * 0.2))
    摘要文本 = "\n".join(
        f"{m.get('role', 'user')}: {m.get('content', '')}" for m in 早期列表 if isinstance(m, dict)
    )
    # 真正压缩：摘要必须显著小于早期原文
    摘要文本 = 摘要文本[:摘要预算]
    if len(摘要文本) >= 摘要预算:
        摘要文本 = 摘要文本 + "…"

    新消息列表 = [{"role": "system", "content": f"[历史摘要] {摘要文本}"}] + 保留列表 if 摘要文本 else list(保留列表)
    压缩后token = _估算文本token(摘要文本) + sum(_估算文本token(str(m.get("content", ""))) + 4 for m in 保留列表 if isinstance(m, dict))
    return 结果.成功结果({
        "已压缩": True, "压缩前token": 压缩前token, "压缩后token": 压缩后token,
        "消息列表": 新消息列表, "摘要": 摘要文本,
        "说明": f"超阈值 {阈值}，保留最近 {保留条数} 条，早期 {len(早期列表)} 条并入摘要",
    })


def 压缩会话(句柄: str = None, 会话id: str = None, 压缩阈值: int = None,
             保留最近条数: int = None, 摘要长度上限: int = None) -> 结果:
    """会话压缩一条龙：会话存储读历史 → 压缩 → 会话存储写回（带租约）。

    超阈值才压；未超返回原样（不写回）。写回后 压缩次数 递增。
    返回 {已压缩, 压缩前token, 压缩后token, 压缩次数, 说明}。
    """
    if not isinstance(句柄, str) or not 句柄.strip():
        return 结果.失败("参数不合法", "句柄必须是非空字符串", 来源="上下文压缩")
    if not isinstance(会话id, str) or not 会话id.strip():
        return 结果.失败("参数不合法", "会话id必须是非空字符串", 来源="上下文压缩")
    # 1. 从会话存储读
    消息列表, 错误 = _从会话存储读取(句柄, 会话id)
    if 消息列表 is None:
        return 结果.失败("读取历史失败", 错误, 来源="上下文压缩")
    # 2. 压缩
    压缩结果 = 压缩历史(消息列表=消息列表, 压缩阈值=压缩阈值,
                       保留最近条数=保留最近条数, 摘要长度上限=摘要长度上限)
    if not 压缩结果.成功:
        return 压缩结果
    值 = 压缩结果.值
    if not 值["已压缩"]:
        return 结果.成功结果({
            "已压缩": False, "压缩前token": 值["压缩前token"], "压缩后token": 值["压缩后token"],
            "压缩次数": None, "说明": 值.get("说明", "未超阈值，无需压缩"),
        })
    # 3. 写回会话存储（带租约防并发）
    try:
        from 支持库.后端.大语言模型支持库.会话存储 import 写入压缩结果
        写回 = 写入压缩结果(句柄=句柄, 会话id=会话id, 压缩后消息列表=值["消息列表"])
        if not 写回.成功:
            return 结果.失败("写回压缩结果失败", 写回.错误说明, 来源="上下文压缩")
        return 结果.成功结果({
            "已压缩": True, "压缩前token": 值["压缩前token"], "压缩后token": 值["压缩后token"],
            "压缩次数": 写回.值.get("压缩次数"), "说明": f"已压缩并写回，压缩次数 {写回.值.get('压缩次数')}",
        })
    except Exception as e:
        return 结果.失败("写回压缩结果失败", f"会话存储不可用: {e}", 来源="上下文压缩")