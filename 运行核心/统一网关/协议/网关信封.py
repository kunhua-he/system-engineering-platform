"""网关信封：已完成 HTTP 边界校验的请求 / 待写出的响应（纯数据类）。

2026-09-19 从 `网关核心.py` 整块搬出（哲学 6.1）。原处再导出，
调用方（`本地网关.py` / `网关边界面.py` / 各测试）路径与符号名零改动。
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any
from 公共契约.基础类型.逻辑类型 import 真, 假


@dataclass
class 网关请求:
    """已完成 HTTP 边界校验的网关请求。"""

    操作: str = "调用能力"
    能力id: str = ""
    目标: str = ""
    参数: dict[str, Any] = field(default_factory=dict)
    句柄: int | None = None
    获取句柄: bool = 假
    项目id: str = ""
    用户id: str = ""
    会话id: str = ""
    任务id: str = ""
    提供者: str = ""
    权限范围: list[str] = field(default_factory=list)
    来源地址: str = ""
    请求id: str = ""
    # 2026-09-17 修复：原默认 10.0 秒会把所有耗时>10 秒的能力判「超时」，
    # 而这类调用（转码/转写/精校等）本就需数分钟。HTTP 边界会用网关配置的
    # 「请求超时秒」（1800）填充该字段，但实测存在未填充而落到本默认值的路径，
    # 导致长任务全部误判超时、且执行线程不可取消→ffmpeg 残留→媒体引擎被占满。
    # 默认值统一取与启动脚本一致的 1800 秒（30 分钟）。
    超时秒: float = 1800.0
    请求版本: str = ""

    def 转字典(self) -> dict[str, Any]:
        return {
            "操作": self.操作, "能力id": self.能力id, "目标": self.目标,
            "参数": self.参数, "句柄": self.句柄, "获取句柄": self.获取句柄,
            "项目id": self.项目id, "用户id": self.用户id,
            "会话id": self.会话id, "任务id": self.任务id,
            "提供者": self.提供者, "权限范围": list(self.权限范围),
            "来源地址": self.来源地址, "请求id": self.请求id,
            "超时秒": self.超时秒, "请求版本": self.请求版本,
        }


@dataclass
class 网关响应:
    """网关公开响应；内部异常原文永不进入该结构。"""

    请求id: str = ""
    操作: str = ""
    成功: bool = 真
    值: Any = None
    错误码: str = ""
    错误说明: str = ""
    # 能力侧的结构化错误明细（源：`结果.详情`，见 公共契约/基础类型/结果类型.py 的 详细信息）。
    # 只增字段（哲学第 5 条 2 项）：此前失败信封只有 错误码+错误说明，失败清单这类可定位
    # 信息被整块丢掉，调用方只能二分试（未完成事项 #203）。老调用方不受影响。
    详情: dict[str, Any] = field(default_factory=dict)
    句柄: int | None = None
    耗时毫秒: float = 0.0
    请求版本: str = ""
    当前版本: str = ""
    版本差异: str = ""

    def 转字典(self) -> dict[str, Any]:
        return {
            "请求id": self.请求id, "操作": self.操作, "成功": self.成功,
            "值": self.值, "错误码": self.错误码, "错误说明": self.错误说明,
            "详情": self.详情,
            "句柄": self.句柄,
            "耗时毫秒": round(self.耗时毫秒, 2),
            # 版本三项信息（哲学第 5 条 2 项，只增不改不删）：上游带版本请求时回报
            # 「请求版本 / 当前版本 / 差异原因」。版本号不一致**本身不失败**，
            # 只有强制参数（必填参数、类型、声明里的运算符约束）不满足才失败。
            "请求版本": self.请求版本,
            "当前版本": self.当前版本,
            "版本差异": self.版本差异,
        }
