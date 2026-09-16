"""提供者注册表与统一结果：注册 → 授权 → 资源监督 → 真实执行 → 证据。

统一结果结构 {成功, 结果, 错误码, 消息, 可重试}；
调用必须经资源监督有界执行（信号量/超时/释放），真实结果或稳定错误码，
证据账本追加调用记录；未注册能力 / 提供者异常 / 超时全部真实失败。
"""
from __future__ import annotations

import uuid
from typing import Any, Callable

from 平台控制面.资源监督 import 资源监督器


class 注册表:
    """提供者注册表：注册真实实现，统一调用入口。"""

    def __init__(self, 状态, 监督器: 资源监督器 | None = None) -> None:
        self.状态 = 状态
        self.监督器 = 监督器 or 资源监督器(状态)
        self._提供者表: dict[str, tuple[Callable, dict[str, Any]]] = {}

    def 注册(self, *, 能力id: str, 调用函数: Callable,
            预算: dict[str, Any]) -> tuple[bool, str]:
        """注册提供者：校验预算并建立有界执行单元。"""
        if not callable(调用函数):
            return False, "调用函数必须是可调用对象"
        有效, 消息 = self.监督器.校验预算声明(预算)
        if not 有效:
            return False, 消息
        单元id = f"单元_{能力id}"
        if 单元id not in self.监督器._池表:
            self.监督器.注册执行单元(单元id=单元id, 预算=预算)
        self._提供者表[能力id] = (调用函数, 预算)
        self.状态.追加证据(类型="提供者", 主题=能力id, 内容={"注册": True},
                          调用者="注册表", 角色="平台维护者", 结果="注册")
        return True, f"提供者已注册: {能力id}"

    def 已注册(self, 能力id: str) -> bool:
        return 能力id in self._提供者表

    def 调用(self, *, 能力id: str, 参数: dict[str, Any] | None = None,
             超时秒: float = 0) -> dict[str, Any]:
        """统一调用：资源监督有界执行 → 真实结果或稳定错误码 → 证据。"""
        提供者 = self._提供者表.get(能力id)
        if 提供者 is None:
            return {"成功": False, "结果": None, "错误码": "能力不存在",
                    "消息": f"能力未注册: {能力id}", "可重试": False}
        函数, 预算 = 提供者
        超时 = 超时秒 or float(预算.get("单次调用超时", 5))

        def 执行() -> Any:
            if 参数:
                return 函数(**参数)
            return 函数()

        成功, 消息, 结果 = self.监督器.提交任务(
            f"单元_{能力id}", 执行, 超时秒=超时)
        证据结果 = "成功" if 成功 else "失败"
        错误码 = "" if 成功 else ("CALL_TIMEOUT" if "超时" in 消息 else "CALL_FAILED")
        self.状态.追加证据(类型="调用", 主题=能力id, 内容={"参数": 参数, "消息": 消息},
                          调用者="注册表", 角色="调用Agent",
                          结果=证据结果, 错误码=错误码)
        if not 成功:
            return {"成功": False, "结果": None, "错误码": 错误码,
                    "消息": 消息, "可重试": "超时" not in 消息}
        return {"成功": True, "结果": 结果, "错误码": "", "消息": "调用完成",
                "可重试": False}

    def 卸载(self, 能力id: str) -> bool:
        """卸载提供者并优雅停止其执行单元。"""
        if 能力id not in self._提供者表:
            return False
        del self._提供者表[能力id]
        self.监督器.优雅停止(f"单元_{能力id}")
        return True
