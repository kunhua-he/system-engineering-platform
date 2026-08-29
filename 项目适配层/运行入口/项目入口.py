"""项目公开入口：项目代码调用能力的唯一稳定入口。

调用流程：项目入口 → 项目适配层 → 模块公开能力 → 支持库公开能力
→ 返回统一结果。返回必须使用系统级统一结果结构（成功/值/错误/错误码/
说明），禁止返回第三方对象、内部类实例、文件句柄与不可序列化对象。
"""

from __future__ import annotations

from typing import Any

from 公共契约.基础类型.结果类型 import 结果
from 公共契约.能力契约.契约 import 能力注册表
from 项目适配层.能力适配.能力适配 import 能力映射


class 项目入口:
    """项目公开入口：持有一个已装配的能力注册表与能力映射。

    生命周期：可运行 → 已停止 → 已卸载。卸载后不能继续调用能力。
    """

    def __init__(self, 注册表: 能力注册表, 映射: 能力映射 | None = None,
                 连接器: Any | None = None) -> None:
        if 连接器 is None or not callable(getattr(连接器, "调用能力", None)):
            raise ValueError("项目入口必须装配 HTTP 连接器；禁止进程内直接调用能力")
        self.注册表 = 注册表
        self.映射 = 映射 or 能力映射()
        self.连接器 = 连接器
        self.状态 = "可运行"

    def 停止(self) -> None:
        """停止入口（幂等）：可运行 → 已停止。"""
        if self.状态 == "可运行":
            self.状态 = "已停止"

    def 卸载(self) -> None:
        """卸载入口（幂等）：必须先停止；可运行状态自动先停止。"""
        if self.状态 == "可运行":
            self.停止()
        if self.状态 == "已停止":
            self.状态 = "已卸载"
            self.注册表.清空()

    def 调用(self, 能力id: str, 参数: dict | None = None, **关键字参数) -> 结果:
        """按能力id（或能力名）调用能力，返回统一结果。"""
        if self.状态 == "已卸载":
            return 结果.失败("资源已卸载", f"项目入口已卸载，无法调用 {能力id}", 来源="项目入口")
        参数 = dict(参数 or {})
        参数.update(关键字参数)
        实际能力id = self.映射.解析(能力id) or 能力id
        try:
            响应 = self.连接器.调用能力(实际能力id, 参数)
            if not isinstance(响应, dict):
                return 结果.失败("返回结果不符合契约", "网关返回不是对象", 来源="项目入口")
            if 响应.get("成功"):
                return 结果.成功结果(响应.get("值"))
            return 结果.失败(响应.get("错误码") or "提供者不可用",
                           响应.get("错误说明") or "网关调用失败", 来源="项目入口")
        except Exception as 错误:
            return 结果.失败("提供者不可用", f"网关调用失败: {错误}", 来源="项目入口")

    def 已装配能力数(self) -> int:
        return len(self.注册表.能力id列表)

    def 可用能力id列表(self) -> list[str]:
        return list(self.注册表.能力id列表)
