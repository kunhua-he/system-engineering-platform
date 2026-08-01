"""统一网关控制面：协议转换、权限、五维限流、脱敏错误与安全审计。"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from 运行核心.运行诊断.安全审计.安全审计 import 安全审计
from 运行核心.能力调用.运行上下文.上下文 import 运行上下文
from 运行核心.统一网关.安全边界 import 脱敏错误信息
from 运行核心.统一网关.限流器 import 限流器

允许操作表 = {
    "健康检查", "能力搜索", "能力详情", "调用能力", "任务提交",
    "任务查询", "任务取消", "版本查询", "激活版本查询", "诊断查询",
}

操作权限表 = {
    "健康检查": "查询", "能力搜索": "查询", "能力详情": "查询",
    "版本查询": "查询", "激活版本查询": "查询", "诊断查询": "查询",
    "调用能力": "调用", "任务提交": "任务", "任务查询": "任务",
    "任务取消": "任务",
}

公开错误说明表 = {
    "能力不存在": "请求的能力不存在",
    "权限不足": "没有执行此操作的权限",
    "限流": "请求过于频繁，请稍后重试",
    "参数不合法": "请求参数不符合接口契约",
    "外部不可访问": "后端服务暂时不可用",
    "版本不兼容": "请求版本与当前能力不兼容",
    "超时": "请求执行超时",
    "内部错误": "服务内部错误",
}


@dataclass
class 网关请求:
    """已完成 HTTP 边界校验的网关请求。"""

    操作: str = "调用能力"
    能力id: str = ""
    参数: dict[str, Any] = field(default_factory=dict)
    项目id: str = ""
    用户id: str = ""
    会话id: str = ""
    任务id: str = ""
    提供者: str = ""
    权限范围: list[str] = field(default_factory=list)
    来源地址: str = ""
    请求id: str = ""
    超时秒: float = 10.0

    def 转字典(self) -> dict[str, Any]:
        return {
            "操作": self.操作, "能力id": self.能力id, "参数": self.参数,
            "项目id": self.项目id, "用户id": self.用户id,
            "会话id": self.会话id, "任务id": self.任务id,
            "提供者": self.提供者, "权限范围": list(self.权限范围),
            "来源地址": self.来源地址, "请求id": self.请求id,
            "超时秒": self.超时秒,
        }


@dataclass
class 网关响应:
    """网关公开响应；内部异常原文永不进入该结构。"""

    请求id: str = ""
    操作: str = ""
    成功: bool = True
    值: Any = None
    错误码: str = ""
    错误说明: str = ""
    耗时毫秒: float = 0.0

    def 转字典(self) -> dict[str, Any]:
        return {
            "请求id": self.请求id, "操作": self.操作, "成功": self.成功,
            "值": self.值, "错误码": self.错误码, "错误说明": self.错误说明,
            "耗时毫秒": round(self.耗时毫秒, 2),
        }


class 网关核心:
    """所有调用共享同一限流器与审计器，业务能力仍由后端核心实现。"""

    def __init__(self, 后端核心: Any = None, 任务系统: Any = None,
                 版本查询: Any = None, 限流器实例: 限流器 | None = None,
                 审计实例: 安全审计 | None = None) -> None:
        self.后端核心 = 后端核心
        self.任务系统 = 任务系统
        self.版本查询 = 版本查询
        self.限流器 = 限流器实例 or 限流器()
        self.审计 = 审计实例 or 安全审计()
        self.请求数 = 0
        self.失败数 = 0

    def 设置后端(self, 后端核心: Any) -> None:
        self.后端核心 = 后端核心

    def 设置任务系统(self, 任务系统: Any) -> None:
        self.任务系统 = 任务系统

    def _权限通过(self, 请求: 网关请求) -> bool:
        """进程内兼容调用可不带范围；HTTP 安全层会注入可信范围。"""
        if not 请求.权限范围:
            return True
        需要权限 = 操作权限表.get(请求.操作, "")
        return not 需要权限 or 需要权限 in 请求.权限范围 or "全部" in 请求.权限范围

    def _设置失败(self, 响应: 网关响应, 错误码: str) -> None:
        响应.成功 = False
        响应.值 = None
        响应.错误码 = 错误码
        响应.错误说明 = 公开错误说明表.get(错误码, "请求处理失败")

    def _执行(self, 请求: 网关请求, 响应: 网关响应) -> None:
        if self.后端核心 is None:
            raise ConnectionError("后端核心未接入")
        if 请求.操作 == "健康检查":
            结果对象 = self.后端核心.健康检查()
            if not 结果对象.成功:
                self._设置失败(响应, 结果对象.错误码 or "外部不可访问")
            else:
                响应.值 = 结果对象.值
        elif 请求.操作 == "能力搜索":
            响应.值 = self.后端核心.能力搜索(关键词=请求.参数.get("关键词", ""))
        elif 请求.操作 == "能力详情":
            能力id = 请求.参数.get("能力id", 请求.能力id)
            if not 能力id:
                raise ValueError("缺少能力id")
            实现 = self.后端核心.注册表.获取(能力id)
            if 实现 is None:
                raise KeyError(能力id)
            响应.值 = {"能力id": 实现.能力id, "包id": 实现.包id,
                        "参数": 实现.参数, "返回": 实现.返回, "说明": 实现.说明}
        elif 请求.操作 == "调用能力":
            if not 请求.能力id:
                raise ValueError("缺少能力id")
            结果对象 = self.后端核心.调用(
                请求.能力id, 请求.参数,
                上下文=运行上下文(
                    请求id=响应.请求id, 项目id=请求.项目id, 用户id=请求.用户id,
                    会话id=请求.会话id, 任务id=请求.任务id, 能力id=请求.能力id,
                    提供者=请求.提供者, 权限范围=list(请求.权限范围),
                    来源地址=请求.来源地址,
                ),
                超时秒=请求.超时秒,
            )
            if 结果对象.成功:
                响应.值 = 结果对象.值
            else:
                self._设置失败(响应, 结果对象.错误码 or "内部错误")
        elif 请求.操作 == "任务提交":
            if self.任务系统 is None:
                raise ConnectionError("任务系统未接入")
            任务对象 = self.任务系统.提交(
                能力id=请求.能力id, 参数=请求.参数,
                请求id=响应.请求id, 项目id=请求.项目id, 用户id=请求.用户id,
            )
            响应.值 = {"任务id": 任务对象.任务id, "状态": 任务对象.状态}
        elif 请求.操作 == "任务查询":
            if self.任务系统 is None:
                raise ConnectionError("任务系统未接入")
            任务id = 请求.参数.get("任务id", 请求.任务id)
            if not 任务id:
                raise ValueError("缺少任务id")
            任务对象 = self.任务系统.查询(任务id)
            if 任务对象 is None:
                raise KeyError(任务id)
            响应.值 = 任务对象.转字典()
        elif 请求.操作 == "任务取消":
            if self.任务系统 is None:
                raise ConnectionError("任务系统未接入")
            任务id = 请求.参数.get("任务id", 请求.任务id)
            if not 任务id:
                raise ValueError("缺少任务id")
            成功, 消息 = self.任务系统.取消(任务id)
            响应.值 = {"成功": 成功, "消息": 脱敏错误信息(str(消息))}
        elif 请求.操作 in ("版本查询", "诊断查询", "激活版本查询"):
            if self.版本查询 is None:
                raise ConnectionError("查询服务未接入")
            查询结果 = self.版本查询(请求.参数)
            if 请求.操作 == "激活版本查询":
                查询结果 = {"能力id": 请求.参数.get("能力id", ""),
                            "激活版本": 查询结果.get("激活版本") if isinstance(查询结果, dict) else None}
            响应.值 = 查询结果

    def 处理(self, 请求: 网关请求) -> 网关响应:
        开始 = time.monotonic()
        请求id = 请求.请求id or uuid.uuid4().hex[:16]
        响应 = 网关响应(请求id=请求id, 操作=请求.操作)
        已进入限流 = False
        审计失败原因 = ""
        被限流 = False
        权限拒绝 = False
        try:
            if 请求.操作 not in 允许操作表:
                raise ValueError("未知操作")
            if not self._权限通过(请求):
                权限拒绝 = True
                raise PermissionError("权限范围不足")
            通过, _ = self.限流器.进入请求(
                项目id=请求.项目id, 用户id=请求.用户id, 能力id=请求.能力id,
                任务id=请求.任务id, 提供者=请求.提供者,
            )
            if not 通过:
                被限流 = True
                self._设置失败(响应, "限流")
            else:
                已进入限流 = True
                self._执行(请求, 响应)
        except KeyError:
            self._设置失败(响应, "能力不存在")
        except PermissionError:
            self._设置失败(响应, "权限不足")
        except ValueError:
            self._设置失败(响应, "参数不合法")
        except (ConnectionError, TimeoutError):
            self._设置失败(响应, "外部不可访问")
        except Exception as 错误:
            self._设置失败(响应, "内部错误")
            审计失败原因 = f"未处理异常类型: {type(错误).__name__}"
        finally:
            if 已进入限流:
                self.限流器.离开请求(
                    项目id=请求.项目id, 用户id=请求.用户id, 能力id=请求.能力id,
                    任务id=请求.任务id, 提供者=请求.提供者,
                )
            响应.耗时毫秒 = (time.monotonic() - 开始) * 1000
            self.请求数 += 1
            if not 响应.成功:
                self.失败数 += 1
            self.审计.记录(
                操作=请求.操作, 用户id=请求.用户id, 项目id=请求.项目id,
                能力id=请求.能力id, 请求id=请求id, 任务id=请求.任务id,
                会话id=请求.会话id, 提供者=请求.提供者,
                权限范围=请求.权限范围, 来源地址=请求.来源地址,
                成功=响应.成功, 错误码=响应.错误码,
                失败原因=审计失败原因 or 响应.错误说明,
                被限流=被限流, 权限拒绝=权限拒绝,
                耗时毫秒=响应.耗时毫秒,
            )
        return 响应
