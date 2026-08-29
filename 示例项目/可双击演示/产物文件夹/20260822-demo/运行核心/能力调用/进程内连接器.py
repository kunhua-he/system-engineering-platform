"""进程内连接器：模块跨边界调用的统一进程内通道。

与 HTTP连接器 共享同一调用接口（调用能力(能力id, 参数) -> dict），
但内部直接经 唯一能力调用服务 调用注册表实现，不走网络。

用途（统一口径）：
- 后端核心装配时注入模块：模块能力在后端核心进程内被网关调用时
  直通底层支持库能力，避免「模块内部连接器未装配 → 提供者不可用」。
- 外部独立进程使用模块：自行 设置HTTP连接器(HTTP连接器(...)) 指向远程网关。

返回结构固定：{成功, 值, 错误码, 错误说明, 句柄, 请求id, 耗时毫秒}，
与 HTTP连接器 对齐，模块的 _调用支持库 无需区分通道来源。
"""

from __future__ import annotations

import time
import uuid
from typing import Any

from 运行核心.能力调用.唯一能力调用 import 获取唯一调用服务


class 进程内连接器:
    """模块侧进程内调用门面（与 HTTP连接器 同接口）。"""

    def __init__(self, *, 默认超时秒: float = 10.0) -> None:
        self.默认超时秒 = 默认超时秒

    def 调用能力(self, 能力id: str, 参数: dict[str, Any] | None = None, *,
                 句柄: int | None = None, 项目id: str = "", 用户id: str = "",
                 超时秒: float | None = None, 契约版本: str = "",
                 请求id: str = "", 获取句柄: bool = True) -> dict[str, Any]:
        """按能力 id 经唯一能力调用服务直调注册表，返回统一 dict。"""
        开始 = time.monotonic()
        请求id = 请求id or uuid.uuid4().hex[:16]
        if not isinstance(能力id, str) or not 能力id.strip():
            return self._失败("参数不合法", "能力id 必须是非空文本", 请求id, 开始)
        if 参数 is not None and not isinstance(参数, dict):
            return self._失败("参数不合法", "参数必须是对象", 请求id, 开始)
        try:
            服务 = 获取唯一调用服务()
        except Exception as 错误:
            return self._失败("提供者不可用", f"唯一能力调用服务不可用: {错误}", 请求id, 开始)
        try:
            结果 = 服务.调用能力(
                能力id, 参数 or {}, 调用方="进程内连接器",
                项目id=项目id, 超时秒=超时秒 if 超时秒 is not None else self.默认超时秒,
                句柄=str(句柄) if 句柄 is not None else "",
            )
        except Exception as 错误:
            return self._失败("调用失败", f"{能力id} 调用异常: {错误}", 请求id, 开始)
        耗时毫秒 = round((time.monotonic() - 开始) * 1000, 3)
        if getattr(结果, "成功", False):
            return {
                "成功": True, "值": getattr(结果, "值", None),
                "错误码": "", "错误说明": "", "句柄": 句柄,
                "请求id": 请求id, "耗时毫秒": 耗时毫秒,
            }
        return {
            "成功": False, "值": None,
            "错误码": getattr(结果, "错误码", "调用失败") or "调用失败",
            "错误说明": getattr(结果, "错误说明", "") or "",
            "句柄": 句柄, "请求id": 请求id, "耗时毫秒": 耗时毫秒,
        }

    def 健康检查(self) -> bool:
        """进程内直通：唯一能力调用服务可用即视为健康。"""
        try:
            获取唯一调用服务()
            return True
        except Exception:
            return False

    @staticmethod
    def _失败(错误码: str, 错误说明: str, 请求id: str, 开始: float) -> dict[str, Any]:
        return {
            "成功": False, "值": None, "错误码": 错误码,
            "错误说明": 错误说明, "句柄": None, "请求id": 请求id,
            "耗时毫秒": round((time.monotonic() - 开始) * 1000, 3),
        }


__all__ = ["进程内连接器"]
