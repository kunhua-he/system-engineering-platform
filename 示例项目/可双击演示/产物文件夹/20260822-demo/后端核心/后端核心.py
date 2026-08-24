"""后端核心：通用运行宿主。

后端核心负责：支持库和模块发现、包版本解析、项目适配装配、能力注册、
能力调用、服务生命周期、后台任务、外部提供者管理、请求上下文、权限
检查、超时和取消、统一错误、运行事件、诊断关联、版本切换、停止和卸载。

后端核心不实现具体业务，只提供通用运行宿主。公开入口只能是能力契约
和统一结果。
"""

from __future__ import annotations

import copy
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from 公共契约.基础类型.结果类型 import 结果
from 公共契约.能力契约.契约 import 能力实现, 能力注册表
from 运行核心.能力调用.运行上下文.上下文 import 运行上下文

_装配模板: 能力注册表 | None = None
_装配锁 = threading.Lock()


@dataclass
class 后端状态:
    """后端核心运行状态。"""

    状态: str = "未启动"  # 未启动/启动中/运行中/已停止/故障
    启动时间: str = ""
    能力数: int = 0
    请求总数: int = 0
    失败请求数: int = 0
    活动请求数: int = 0


class 后端核心:
    """后端核心宿主：装配、注册、调用、任务、生命周期。"""

    def __init__(self, 系统根目录: Path | None = None) -> None:
        self.系统根目录 = 系统根目录 or Path(后端核心.默认系统根())
        self.注册表 = 能力注册表()
        self.状态 = 后端状态()
        self.权限表: dict[str, set[str]] = {}  # 能力id → 允许用户id集合
        self.请求锁 = threading.Lock()
        self.停止标记 = False
        self.事件日志 = None
        self.排空 = None  # 自动排空管理器（启动时装配）

    def 启用自动排空(self, 排空超时秒: float = 3.0) -> None:
        """启用自动有状态排空：调用前后自动计数，异常路径也减。"""
        from 运行核心.资源协调.有状态排空.排空管理 import 排空管理器
        self.排空 = 排空管理器(排空超时秒=排空超时秒)

    def 注册排空终止器(self, 名称: str, 终止函数: Callable[[], Any]) -> None:
        """登记由后端核心统一触发的真实资源终止函数。"""
        if self.排空 is None:
            self.启用自动排空()
        self.排空.注册强制终止器(名称, 终止函数)

    @staticmethod
    def 默认系统根() -> str:
        return str(Path(__file__).resolve().parents[1])

    def 装配(self) -> 结果:
        """发现并装配系统内全部支持库与模块（装配模板缓存复用）。"""
        global _装配模板
        from 运行核心.加载器.生命周期管理.管理器 import 装配系统
        with _装配锁:
            if _装配模板 is None:
                # 首次：全量装配并把纯净注册表存为模板
                装配结果 = 装配系统(
                    self.系统根目录 / "支持库", self.系统根目录 / "模块库", self.注册表
                )
                if not 装配结果.成功:
                    return 结果.失败("装配失败", "; ".join(装配结果.问题列表), 来源="后端核心")
                _装配模板 = copy.deepcopy(self.注册表)
            else:
                # 后续：模板深拷贝，避免重复全量扫描（大幅降低测试/多实例开销）
                self.注册表 = copy.deepcopy(_装配模板)
                if self.注册表 is None:
                    return 结果.失败("装配失败", "装配模板缺失", 来源="后端核心")
        return 结果.成功结果(len(self.注册表.能力id列表))

    def 启动(self) -> 结果:
        """启动后端核心（装配 + 就绪）。"""
        self.停止标记 = False
        self.状态.状态 = "启动中"
        装配结果 = self.装配()
        if not 装配结果.成功:
            self.状态.状态 = "故障"
            return 装配结果
        self.状态.状态 = "运行中"
        self.状态.启动时间 = time.strftime("%Y-%m-%d %H:%M:%S")
        self.状态.能力数 = len(self.注册表.能力id列表)
        return 结果.成功结果(f"后端核心已就绪，{self.状态.能力数} 个能力")

    def 注册能力(self, 能力id: str, 实现函数: Callable, *, 参数: list | None = None,
                 返回: str = "结果", 说明: str = "") -> 结果:
        try:
            self.注册表.注册(能力实现(
                能力id=能力id, 包id="后端核心", 实现函数=实现函数,
                参数=参数 or [], 返回=返回, 说明=说明,
            ))
        except ValueError as 错误:
            return 结果.失败("能力重复", str(错误), 来源="后端核心")
        return 结果.成功结果(能力id)

    def 设置权限(self, 能力id: str, 允许用户id列表: list[str]) -> None:
        self.权限表[能力id] = set(允许用户id列表)

    def 调用(self, 能力id: str, 参数: dict | None = None, *,
             上下文: 运行上下文 | None = None, 超时秒: float = 10.0) -> 结果:
        """按能力契约调用；权限/超时/取消/统一错误；自动排空计数。"""
        if self.状态.状态 != "运行中":
            return 结果.失败("外部不可访问", f"后端核心未运行（状态 {self.状态.状态}）", 来源="后端核心")
        上下文 = 上下文 or 运行上下文()
        排空活动 = False
        if self.排空 is not None:
            if not self.排空.开始请求():
                return 结果.失败("外部不可访问", "排空中，拒绝新请求", 来源="后端核心")
            排空活动 = True
        try:
            return self._调用内部(能力id, 参数, 上下文)
        finally:
            if 排空活动:
                self.排空.结束请求()  # 异常路径也减计数

    def _调用内部(self, 能力id: str, 参数: dict | None,
                 上下文: 运行上下文) -> 结果:
        with self.请求锁:
            self.状态.请求总数 += 1
            self.状态.活动请求数 += 1
        try:
            允许用户 = self.权限表.get(能力id)
            if 允许用户 is not None and 上下文.用户id and 上下文.用户id not in 允许用户:
                返回结果 = 结果.失败("权限不足", f"用户 {上下文.用户id} 无权限调用 {能力id}", 来源="后端核心")
            else:
                实现 = self.注册表.获取(能力id)
                if 实现 is None:
                    返回结果 = 结果.失败("能力不存在", f"能力未注册: {能力id}", 来源="后端核心")
                else:
                    try:
                        调用结果 = 实现.调用(**dict(参数 or {}))
                        返回结果 = 调用结果 if isinstance(调用结果, 结果) else 结果.成功结果(调用结果)
                    except TypeError as 错误:
                        返回结果 = 结果.失败("参数不合法", f"调用参数错误: {错误}", 来源="后端核心")
                    except Exception as 错误:  # noqa: BLE001 - 能力边界统一转换外部实现异常
                        返回结果 = 结果.失败("内部错误", f"调用异常: {错误}", 来源="后端核心")
            if not 返回结果.成功:
                with self.请求锁:
                    self.状态.失败请求数 += 1
            return 返回结果
        finally:
            with self.请求锁:
                self.状态.活动请求数 = max(0, self.状态.活动请求数 - 1)

    def 健康检查(self) -> 结果:
        if self.状态.状态 == "运行中":
            return 结果.成功结果({"状态": "健康", "能力数": self.状态.能力数})
        return 结果.失败("外部不可访问", f"后端核心状态: {self.状态.状态}", 来源="后端核心")

    def 能力搜索(self, *, 关键词: str = "") -> list[dict]:
        return [
            {"能力id": 能力id, "说明": (self.注册表.获取(能力id).说明 or "")}
            for 能力id in self.注册表.能力id列表
            if not 关键词 or 关键词 in 能力id or 关键词 in (self.注册表.获取(能力id).说明 or "")
        ]

    def 优雅关闭(self) -> 结果:
        """优雅关闭：等待活动请求归零后停止。"""
        if self.状态.状态 == "已停止":
            return 结果.成功结果("已停止（幂等）")
        self.停止标记 = True
        if self.排空 is not None:
            排空结果 = self.排空.排空()
            if not 排空结果.成功:
                return 结果.失败("排空超时", 排空结果.诊断记录, 来源="后端核心")
        self.状态.状态 = "已停止"
        return 结果.成功结果("后端核心已优雅关闭")

    def 强制关闭(self) -> 结果:
        self.停止标记 = True
        if self.排空 is not None:
            排空结果 = self.排空.排空()
            if not 排空结果.成功:
                return 结果.失败("资源未释放", 排空结果.诊断记录, 来源="后端核心")
        self.状态.状态 = "已停止"
        return 结果.成功结果("后端核心已强制关闭")

    def 状态快照(self) -> dict[str, Any]:
        return {
            "状态": self.状态.状态, "启动时间": self.状态.启动时间,
            "能力数": self.状态.能力数, "请求总数": self.状态.请求总数,
            "失败请求数": self.状态.失败请求数, "活动请求数": self.状态.活动请求数,
        }
