"""流式推理原子能力实现（不对外暴露，只经包级中文入口调用）。

职责：流式推理请求的提交→事件消费→关闭（借鉴 Codex 增量推理 + Claude 流式协议）。
流式 = 按事件队列消费（增量/完成/错误），事件由真实 Provider 注册后填充。
只做流式编排，不实现模型调用；调用器未注册时返回 提供者不可用。
"""

from __future__ import annotations

import json
import threading
import time
import uuid
from typing import Any, Callable

from 公共契约.基础类型.结果类型 import 结果

流表: dict[str, dict] = {}       # 流id → 流信息
提供者表: dict[str, Callable] = {}  # 流式提供者
锁 = threading.Lock()


def 提交流式请求(模型连接句柄: int | None = None, 消息列表: list = None, 系统提示词: str = None) -> 结果:
    """提交流式推理请求，返回 流id（句柄时效内可消费事件）。"""
    if isinstance(模型连接句柄, bool) or not isinstance(模型连接句柄, int) or not 1 <= 模型连接句柄 <= 999999:
        return 结果.失败("参数不合法", "模型连接句柄必须是1到999999的整数", 来源="流式推理")
    if not isinstance(消息列表, list) or not 消息列表:
        return 结果.失败("参数不合法", "消息列表必须是非空列表", 来源="流式推理")
    流id = uuid.uuid4().hex[:16]
    with 锁:
        流表[流id] = {
            "流id": 流id, "句柄": 模型连接句柄, "消息列表": list(消息列表),
            "系统提示词": 系统提示词, "状态": "运行中", "事件队列": [],
            "创建时间": time.strftime("%Y-%m-%d %H:%M:%S"),
            "最后消费时间": time.time(),
        }
    return 结果.成功结果({"流id": 流id, "状态": "运行中", "说明": "使用 消费事件 获取增量/完成/错误事件"})


def 消费事件(流id: str = None, 批次大小: int = None) -> 结果:
    """消费流式事件（增量/完成/错误）。返回 {事件列表, 更多}。"""
    if not isinstance(流id, str) or not 流id.strip():
        return 结果.失败("参数不合法", "流id必须是非空字符串", 来源="流式推理")
    with 锁:
        流 = 流表.get(流id)
        if 流 is None:
            return 结果.失败("流不存在", f"流id {流id} 不存在或已关闭", 来源="流式推理")
        流["最后消费时间"] = time.time()
        批次 = 流["事件队列"][:批次大小 or 10]
        流["事件队列"] = 流["事件队列"][批次大小 or 10:]
        更多 = len(流["事件队列"]) > 0 or 流["状态"] == "运行中"
    return 结果.成功结果({"事件列表": 批次, "更多": 更多, "流状态": 流["状态"]})


def 关闭流(流id: str = None) -> 结果:
    """关闭流（幂等）。"""
    if not isinstance(流id, str) or not 流id.strip():
        return 结果.失败("参数不合法", "流id必须是非空字符串", 来源="流式推理")
    with 锁:
        流 = 流表.pop(流id, None)
        if 流:
            流["状态"] = "已关闭"
    return 结果.成功结果({"流id": 流id, "已关闭": 流 is not None, "说明": "幂等"})


def 推送事件(流id: str, 事件类型: str, 数据: dict) -> bool:
    """向流推送事件（由适配层 Provider 调用）。事件类型 ∈ 增量/完成/错误。"""
    with 锁:
        流 = 流表.get(流id)
        if 流 is None:
            return False
        流["事件队列"].append({"类型": 事件类型, "数据": dict(数据), "时间": time.strftime("%H:%M:%S.%f")[:-3]})
        if 事件类型 in ("完成", "错误"):
            流["状态"] = "已完成" if 事件类型 == "完成" else "错误"
    return True


def 注册流提供者(提供者名: str, 调用函数: Callable) -> None:
    """注册流式提供者（由适配层 Provider 调用）。"""
    提供者表[提供者名] = 调用函数



# ═══════════════════════════════════════════════
# SSE 事件名协议：Coze SSE 三件套模式化落地
# 事件帧格式化（ack/增量/完成/错误 + [DONE]）、X-Accel-Buffering 头建议。
# 0加密0限制：数据原文透传，脱敏由业务端自理。
# ═══════════════════════════════════════════════
_SSE事件名 = ("ack", "增量", "完成", "错误")
SSE缓冲头 = {"X-Accel-Buffering": "no", "Cache-Control": "no-cache", "Content-Type": "text/event-stream; charset=utf-8"}


def 格式化事件帧(*, 事件名: str = None, 数据: dict = None, 序号: int = None,
                 带缓冲头: bool = None) -> 结果:
    """格式化 SSE 事件帧。返回 {帧文本, 响应头, 是否结束, 序号}。

    事件名 ∈ ack/增量/完成/错误；完成帧后自动附 [DONE]（OpenClaw 约定）。
    带缓冲头=True 时返回 SSE 标准响应头（含 X-Accel-Buffering: no 穿透反代缓冲）。
    """
    try:
        名称 = str(事件名 or "").strip()
        if 名称 not in _SSE事件名:
            return 结果.失败("参数不合法",
                             f"事件名必须是 {'/'.join(_SSE事件名)}: {名称}", 来源="流式推理")
        if 数据 is None:
            数据 = {}
        if not isinstance(数据, dict):
            return 结果.失败("参数不合法", "数据必须是字典型", 来源="流式推理")
        序号值 = int(序号 or 0)
        数据体 = json.dumps(数据, ensure_ascii=False)
        帧 = f"event: {名称}\nid: {序号值}\ndata: {数据体}\n\n"
        是否结束 = 名称 == "完成"
        if 是否结束:
            帧 += "data: [DONE]\n\n"
        return 结果.成功结果({
            "帧文本": 帧,
            "响应头": dict(SSE缓冲头) if 带缓冲头 is not False else {},
            "是否结束": 是否结束,
            "序号": 序号值,
        })
    except Exception as 异常:
        return 结果.失败("格式化失败", str(异常), 来源="流式推理")
