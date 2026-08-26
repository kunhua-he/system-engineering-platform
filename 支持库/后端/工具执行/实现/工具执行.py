"""工具执行原子能力实现（不对外暴露，只经包级中文入口调用）。

职责：工具调用的受理→执行→结果登记（借鉴 Codex dispatch_tool_call 两段式 + 失败标记）。
先登记执行记录（受理），再执行；执行异常不抛给调用方，统一返回 失败 + 错误标记。
只做工具调用编排，不执行业务逻辑。
"""

from __future__ import annotations

import threading
import time
import uuid

from 公共契约.基础类型.结果类型 import 结果

执行记录表: dict[str, dict] = {}
锁 = threading.Lock()


def 受理工具调用(工具名: str = None, 参数: dict = None, 超时秒: int = None) -> 结果:
    """受理工具调用，返回 执行id。后续可用 执行id 关联结果。"""
    if not isinstance(工具名, str) or not 工具名.strip():
        return 结果.失败("参数不合法", "工具名必须是非空字符串", 来源="工具执行")
    执行id = uuid.uuid4().hex[:16]
    with 锁:
        执行记录表[执行id] = {
            "执行id": 执行id, "工具名": 工具名, "参数": dict(参数 or {}),
            "状态": "已受理", "开始时间": time.strftime("%Y-%m-%d %H:%M:%S"),
            "超时秒": 超时秒 or 30, "结果": None, "错误": None,
        }
    return 结果.成功结果({"执行id": 执行id, "工具名": 工具名, "状态": "已受理"})


def 登记执行结果(执行id: str = None, 成功: bool = None, 结果值: dict = None, 错误: str = None) -> 结果:
    """登记执行结果（成功或失败，失败带错误标记）。"""
    if not isinstance(执行id, str) or not 执行id.strip():
        return 结果.失败("参数不合法", "执行id必须是非空字符串", 来源="工具执行")
    with 锁:
        记录 = 执行记录表.get(执行id)
        if 记录 is None:
            return 结果.失败("执行不存在", f"执行id {执行id} 未受理或已清理", 来源="工具执行")
        记录["状态"] = "成功" if 成功 else "失败"
        记录["结果"] = dict(结果值 or {})
        记录["错误"] = 错误 or (None if 成功 else "未知错误")
        记录["结束时间"] = time.strftime("%Y-%m-%d %H:%M:%S")
    return 结果.成功结果({"执行id": 执行id, "状态": 记录["状态"]})


def 查询执行结果(执行id: str = None) -> 结果:
    """查询执行结果。返回 {执行id, 状态, 结果, 错误}。"""
    if not isinstance(执行id, str) or not 执行id.strip():
        return 结果.失败("参数不合法", "执行id必须是非空字符串", 来源="工具执行")
    with 锁:
        记录 = 执行记录表.get(执行id)
    if 记录 is None:
        return 结果.失败("执行不存在", f"执行id {执行id} 不存在", 来源="工具执行")
    return 结果.成功结果({
        "执行id": 执行id, "工具名": 记录["工具名"], "状态": 记录["状态"],
        "结果": 记录["结果"], "错误": 记录["错误"],
        "开始时间": 记录["开始时间"], "结束时间": 记录.get("结束时间", ""),
    })


def 清理执行记录(执行id: str = None) -> 结果:
    """清理执行记录（幂等）。"""
    if not isinstance(执行id, str) or not 执行id.strip():
        return 结果.失败("参数不合法", "执行id必须是非空字符串", 来源="工具执行")
    with 锁:
        存在 = 执行记录表.pop(执行id, None)
    return 结果.成功结果({"执行id": 执行id, "已清理": 存在 is not None})
