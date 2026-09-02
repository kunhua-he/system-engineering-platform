"""统一网关控制面：协议转换、权限、五维限流、脱敏错误与安全审计。"""

from __future__ import annotations

import time
import uuid
import copy
import json
import base64
import threading
from dataclasses import dataclass, field
from typing import Any

from 运行核心.运行诊断.安全审计.安全审计 import 安全审计
from 运行核心.能力调用.运行上下文.上下文 import 运行上下文
from 运行核心.统一网关.安全边界 import 脱敏错误信息
from 运行核心.统一网关.限流器 import 限流器
from 公共契约.基础类型.数值类型 import 校验数值类型

允许操作表 = {
    "健康检查", "能力目录", "能力搜索", "包详情", "能力详情", "调用能力",
    "资源状态", "资源续租", "资源关闭", "任务提交",
    "任务查询", "任务取消", "版本查询", "激活版本查询", "诊断查询",
}

操作权限表 = {
    "健康检查": "查询", "能力目录": "查询", "能力搜索": "查询",
    "包详情": "查询", "能力详情": "查询", "资源状态": "查询",
    "资源续租": "调用", "资源关闭": "调用",
    "版本查询": "查询", "激活版本查询": "查询", "诊断查询": "查询",
    "调用能力": "调用", "任务提交": "任务", "任务查询": "任务",
    "任务取消": "任务",
}

公开错误说明表 = {
    "请求结构错误": "请求体不是合法 JSON 或缺少能力id",
    "参数不合法": "请求参数不符合接口契约（报具体参数名与期望）",
    "契约不存在": "能力契约未登记",
    "契约版本不兼容": "请求契约版本与已冻结契约不一致",
    "能力不存在": "请求的能力不存在",
    "提供者不可用": "提供者未启动或不可达",
    "句柄无效": "句柄不存在或格式错误",
    "句柄已过期": "句柄已超时/释放/回收，不能复活",
    "权限不足": "没有执行此操作的权限",
    "限流": "请求过于频繁，请稍后重试",
    "超时": "请求执行超时",
    "调用已取消": "调用已取消",
    "提供者崩溃": "提供者进程崩溃",
    "返回结果不符合契约": "返回结构或字段与契约不符",
    "资源释放失败": "句柄资源回收失败",
    "幂等键冲突": "同一请求id 携带不同参数",
    "版本冲突": "提供者或能力版本冲突",
    "内部错误": "服务内部错误",
}


def _是JSON值(值: Any) -> bool:
    try:
        json.dumps(值, ensure_ascii=False, allow_nan=False)
        return True
    except (TypeError, ValueError):
        return False


@dataclass
class 网关请求:
    """已完成 HTTP 边界校验的网关请求。"""

    操作: str = "调用能力"
    能力id: str = ""
    目标: str = ""
    参数: dict[str, Any] = field(default_factory=dict)
    句柄: int | None = None
    获取句柄: bool = False
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
            "操作": self.操作, "能力id": self.能力id, "目标": self.目标,
            "参数": self.参数, "句柄": self.句柄, "获取句柄": self.获取句柄,
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
    句柄: int | None = None
    耗时毫秒: float = 0.0

    def 转字典(self) -> dict[str, Any]:
        return {
            "请求id": self.请求id, "操作": self.操作, "成功": self.成功,
            "值": self.值, "错误码": self.错误码, "错误说明": self.错误说明,
            "句柄": self.句柄,
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
        self._幂等表: dict[str, tuple[str, 网关响应]] = {}
        self._幂等进行中: dict[str, tuple[str, threading.Event]] = {}
        self._幂等锁 = threading.Lock()

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

    def _设置后端字典结果(self, 响应: 网关响应, 值: Any) -> None:
        """后端字典必须完整满足统一结果契约，禁止缺字段字典伪装成功。"""
        if not isinstance(值, dict):
            响应.值 = 值
            return
        必填字段 = {"成功", "值", "错误码", "错误说明"}
        if not 必填字段.issubset(值):
            self._设置失败(响应, "返回结果不符合契约")
            return
        成功 = 值.get("成功")
        if (not isinstance(成功, bool)
                or not isinstance(值.get("错误码"), str)
                or not isinstance(值.get("错误说明"), str)):
            self._设置失败(响应, "返回结果不符合契约")
            return
        if not 成功:
            self._设置失败(响应, 值["错误码"] or "内部错误")
            响应.错误说明 = 脱敏错误信息(值["错误说明"])
            return
        响应.值 = 值["值"]

    @staticmethod
    def _能力结果类型合法(结果对象: Any) -> bool:
        """能力返回必须是统一结果且关键字段类型固定，禁止真假值漂移。"""
        if not hasattr(结果对象, "成功") or not isinstance(结果对象.成功, bool):
            return False
        for 字段 in ("错误码", "错误说明"):
            if not isinstance(getattr(结果对象, 字段, None), str):
                return False
        return True

    def _能力参数错误(self, 能力id: str, 参数: dict[str, Any]) -> str:
        """按已注册能力契约校验参数名、必填项和冻结的数值类型。"""
        注册表 = getattr(self.后端核心, "注册表", None)
        获取 = getattr(注册表, "获取", None)
        实现 = 获取(能力id) if callable(获取) else None
        if 实现 is None:
            return ""
        声明参数 = getattr(实现, "参数", [])
        if not isinstance(声明参数, list):
            return f"参数不合法：能力 {能力id} 的参数契约不是列表"
        参数名 = {
            项.get("名称") if isinstance(项, dict) else 项
            for 项 in 声明参数
        }
        未知参数 = sorted(set(参数) - 参数名)
        if 未知参数:
            return f"参数不合法：能力 {能力id} 收到未知参数 {', '.join(map(str, 未知参数))}"
        for 项 in 声明参数:
            if not isinstance(项, dict):
                continue
            名称 = 项.get("名称")
            if 项.get("必填") is True and 名称 not in 参数:
                return f"参数不合法：能力 {能力id} 缺少必填参数 {名称}"
            if 名称 not in 参数:
                continue
            类型值 = 项.get("类型")
            类型 = 类型值 if isinstance(类型值, str) else ""
            # 旧包声明仍可能携带历史短名；先在边界归一化并执行严格
            # 校验，避免未知类型直接落入“未校验”分支形成假绿。
            类型 = {
                "文本": "文本型", "整数": "整数型", "长整数": "长整数型",
                "单精度数": "单精度数型", "双精度数": "双精度数型",
                "浮点数": "双精度数型", "逻辑": "逻辑型", "布尔": "逻辑型",
                "列表": "列表型", "字典": "字典型", "映射": "字典型",
            }.get(类型, 类型)
            类型匹配 = {
                "逻辑型": lambda 值: isinstance(值, bool),
                "文本型": lambda 值: isinstance(值, str),
                "列表型": lambda 值: isinstance(值, list),
                "字典型": lambda 值: isinstance(值, dict),
                "JSON值型": _是JSON值,
            }.get(类型)
            if 类型 in ("整数型", "长整数型", "单精度数型", "双精度数型"):
                try:
                    合法 = 校验数值类型(参数[名称], 类型)
                except (TypeError, ValueError):
                    合法 = False
                if not 合法:
                    return f"参数不合法：能力 {能力id} 的参数 {名称} 必须是 {类型}"
            elif 类型匹配 is not None and not 类型匹配(参数[名称]):
                return f"参数不合法：能力 {能力id} 的参数 {名称} 必须是 {类型}"
        return ""

    @staticmethod
    def _操作参数错误(请求: 网关请求) -> str:
        """校验网关查询操作的数值/文本参数，禁止静默回退。"""
        允许字段表 = {
            "能力目录": {"关键词", "偏移", "限制"},
            "能力搜索": {"关键词", "限制"},
            "包详情": {"包id"},
            "能力详情": {"能力id"},
            "资源状态": {"句柄"},
            "资源续租": {"句柄", "租约秒"},
            "资源关闭": {"句柄"},
            "任务提交": set(),
            "任务查询": {"任务id"},
            "任务取消": {"任务id"},
            "版本查询": set(),
            "诊断查询": set(),
            "激活版本查询": {"能力id"},
        }
        允许字段 = 允许字段表.get(请求.操作)
        if 允许字段 is None:
            return ""
        参数 = 请求.参数
        未知字段 = sorted(set(参数) - 允许字段)
        if 未知字段:
            return f"参数不合法：操作 {请求.操作} 不支持字段 {', '.join(map(str, 未知字段))}"
        if "关键词" in 参数 and not isinstance(参数["关键词"], str):
            return "参数不合法：关键词必须是文本型"
        for 字段 in ("包id", "能力id", "句柄", "任务id"):
            if 字段 in 参数 and not isinstance(参数[字段], (str, int)):
                return f"参数不合法：{字段}必须是文本型或句柄型"
        if "句柄" in 参数 and (
                isinstance(参数["句柄"], bool)
                or not isinstance(参数["句柄"], (str, int))
                or (isinstance(参数["句柄"], int) and not 1 <= 参数["句柄"] <= 999999)):
            return "参数不合法：句柄必须是有效句柄"
        if "限制" in 参数 and (
            isinstance(参数["限制"], bool) or not isinstance(参数["限制"], int)
            or 参数["限制"] < 1
        ):
            return "参数不合法：限制必须是大于等于 1 的整数型"
        if 请求.操作 == "能力目录" and "偏移" in 参数 and (
            isinstance(参数["偏移"], bool) or not isinstance(参数["偏移"], int)
            or 参数["偏移"] < 0
        ):
            return "参数不合法：偏移必须是大于等于 0 的整数型"
        return ""

    @staticmethod
    def _请求摘要(请求: 网关请求) -> str:
        """对请求语义做稳定摘要；请求id本身不参与摘要。"""
        内容 = {
            "操作": 请求.操作, "能力id": 请求.能力id, "目标": 请求.目标,
            "参数": 请求.参数, "句柄": 请求.句柄, "获取句柄": 请求.获取句柄,
            "项目id": 请求.项目id, "用户id": 请求.用户id,
            "会话id": 请求.会话id, "任务id": 请求.任务id,
            "提供者": 请求.提供者, "超时秒": 请求.超时秒,
        }
        def _JSON默认值(值: Any):
            if isinstance(值, (bytes, bytearray, memoryview)):
                return {
                    "类型": "字节集型",
                    "base64": base64.b64encode(bytes(值)).decode("ascii"),
                }
            raise TypeError(f"请求参数包含不可摘要类型: {type(值).__name__}")
        return json.dumps(
            内容, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
            allow_nan=False, default=_JSON默认值,
        )

    def _执行幂等请求(self, 请求: 网关请求, 响应: 网关响应) -> 网关响应:
        """同请求id串行执行一次并缓存结果；不同请求id不得被全局锁串行化。"""
        if not 请求.请求id:
            self._执行(请求, 响应)
            return 响应
        摘要 = self._请求摘要(请求)
        while True:
            with self._幂等锁:
                已有 = self._幂等表.get(请求.请求id)
                if 已有 is not None:
                    if 已有[0] != 摘要:
                        self._设置失败(响应, "幂等键冲突")
                        return 响应
                    return copy.deepcopy(已有[1])
                进行中 = self._幂等进行中.get(请求.请求id)
                if 进行中 is None:
                    完成事件 = threading.Event()
                    self._幂等进行中[请求.请求id] = (摘要, 完成事件)
                    break
                if 进行中[0] != 摘要:
                    self._设置失败(响应, "幂等键冲突")
                    return 响应
                完成事件 = 进行中[1]
            # 只有同一幂等键等待；其它请求已经在锁外并行执行。
            if not 完成事件.wait(timeout=max(0.1, 请求.超时秒)):
                self._设置失败(响应, "超时")
                return 响应
        try:
            self._执行(请求, 响应)
        except BaseException:
            # 异常场景不缓存部分响应；错误码映射由外层 处理 统一完成。
            with self._幂等锁:
                self._幂等进行中.pop(请求.请求id, None)
                while len(self._幂等表) > 500:
                    self._幂等表.pop(next(iter(self._幂等表)))
                完成事件.set()
            raise
        else:
            with self._幂等锁:
                self._幂等表[请求.请求id] = (摘要, copy.deepcopy(响应))
                self._幂等进行中.pop(请求.请求id, None)
                while len(self._幂等表) > 500:
                    self._幂等表.pop(next(iter(self._幂等表)))
                完成事件.set()
        return 响应

    def _执行(self, 请求: 网关请求, 响应: 网关响应) -> None:
        if self.后端核心 is None:
            raise ConnectionError("后端核心未接入")
        操作参数错误 = self._操作参数错误(请求)
        if 操作参数错误:
            self._设置失败(响应, "参数不合法")
            响应.错误说明 = 操作参数错误
            return
        if 请求.操作 == "健康检查":
            结果对象 = self.后端核心.健康检查()
            if not 结果对象.成功:
                self._设置失败(响应, 结果对象.错误码 or "外部不可访问")
            else:
                响应.值 = 结果对象.值
        elif 请求.操作 == "能力目录":
            响应.值 = self.后端核心.能力目录(
                关键词=请求.参数.get("关键词", ""),
                偏移=请求.参数.get("偏移", 0),
                限制=请求.参数.get("限制", 20),
            )
        elif 请求.操作 == "能力搜索":
            响应.值 = self.后端核心.能力搜索(
                关键词=请求.参数.get("关键词", ""),
                限制=请求.参数.get("限制", 20),
            )
        elif 请求.操作 == "包详情":
            包id = 请求.参数.get("包id", "")
            if not 包id:
                raise ValueError("缺少包id")
            详情 = self.后端核心.包详情(包id)
            if 详情 is None:
                raise KeyError(包id)
            响应.值 = 详情
        elif 请求.操作 == "能力详情":
            能力id = 请求.参数.get("能力id", 请求.能力id)
            if not 能力id:
                raise ValueError("缺少能力id")
            详情 = self.后端核心.能力详情(能力id)
            if 详情 is None:
                raise KeyError(能力id)
            响应.值 = 详情
        elif 请求.操作 == "资源状态":
            句柄 = 请求.句柄 or str(请求.参数.get("句柄", ""))
            if not 句柄:
                raise ValueError("缺少句柄")
            状态 = self.后端核心.资源状态(句柄, 项目id=请求.项目id, 所有者=请求.用户id)
            if 状态 is None:
                raise KeyError(句柄)
            响应.值 = 状态
        elif 请求.操作 == "资源续租":
            句柄 = 请求.句柄 or str(请求.参数.get("句柄", ""))
            if not 句柄:
                raise ValueError("缺少句柄")
            响应.值 = self.后端核心.资源续租(
                句柄, 租约秒=请求.参数.get("租约秒", 300),
                项目id=请求.项目id, 所有者=请求.用户id,
            )
        elif 请求.操作 == "资源关闭":
            句柄 = 请求.句柄 or str(请求.参数.get("句柄", ""))
            if not 句柄:
                raise ValueError("缺少句柄")
            响应.值 = self.后端核心.资源关闭(
                句柄, 项目id=请求.项目id, 所有者=请求.用户id,
            )
        elif 请求.操作 == "调用能力":
            能力id = 请求.能力id or 请求.目标
            if not 能力id:
                raise ValueError("缺少能力id")
            参数错误 = self._能力参数错误(能力id, 请求.参数)
            if 参数错误:
                self._设置失败(响应, "参数不合法")
                响应.错误说明 = 参数错误
                return
            if 请求.句柄 is not None:
                状态 = self.后端核心.资源状态(
                    请求.句柄, 项目id=请求.项目id, 所有者=请求.用户id,
                )
                if 状态 is None:
                    self._设置失败(响应, "句柄无效")
                    return
                if 状态.get("状态") != "有效":
                    self._设置失败(响应, "句柄已过期")
                    return
                if 状态.get("元数据", {}).get("能力id") not in ("", 能力id):
                    self._设置失败(响应, "句柄无效")
                    return
            结果对象 = self.后端核心.调用(
                能力id, 请求.参数,
                上下文=运行上下文(
                    请求id=响应.请求id, 项目id=请求.项目id, 用户id=请求.用户id,
                    会话id=请求.会话id, 任务id=请求.任务id, 能力id=能力id,
                    提供者=请求.提供者, 权限范围=list(请求.权限范围),
                    来源地址=请求.来源地址,
                    句柄=请求.句柄,
                ),
                超时秒=请求.超时秒,
            )
            if not self._能力结果类型合法(结果对象):
                self._设置失败(响应, "返回结果不符合契约")
                响应.错误说明 = "能力返回结构不符合契约（成功、错误码、错误说明类型错误）"
            elif 结果对象.成功:
                响应.值 = 结果对象.值
                if 请求.句柄 is not None:
                    响应.句柄 = 请求.句柄
                elif 请求.获取句柄:
                    新句柄 = self.后端核心.资源句柄服务.创建(
                        资源id=能力id, 项目id=请求.项目id, 所有者=请求.用户id,
                        元数据={"能力id": 能力id},
                    )
                    响应.句柄 = 新句柄["句柄"]
            else:
                self._设置失败(响应, 结果对象.错误码 or "内部错误")
                if 结果对象.错误说明:
                    响应.错误说明 = 脱敏错误信息(结果对象.错误说明)
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
            任务对象 = self.任务系统.查询(任务id, 项目id=请求.项目id, 用户id=请求.用户id)
            if 任务对象 is None:
                raise KeyError(任务id)
            响应.值 = 任务对象.转字典()
        elif 请求.操作 == "任务取消":
            if self.任务系统 is None:
                raise ConnectionError("任务系统未接入")
            任务id = 请求.参数.get("任务id", 请求.任务id)
            if not 任务id:
                raise ValueError("缺少任务id")
            成功, 消息 = self.任务系统.取消(任务id, 项目id=请求.项目id, 用户id=请求.用户id)
            self._设置后端字典结果(
                响应, {
                    "成功": 成功, "值": str(消息) if 成功 else None,
                    "错误码": "" if 成功 else "调用已取消",
                    "错误说明": "" if 成功 else 脱敏错误信息(str(消息)),
                },
            )
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
                响应 = self._执行幂等请求(请求, 响应)
        except KeyError:
            self._设置失败(响应, "能力不存在")
        except PermissionError:
            self._设置失败(响应, "权限不足")
        except FileNotFoundError:
            self._设置失败(响应, "文件不存在")
        except ValueError:
            self._设置失败(响应, "参数不合法")
        except (ConnectionError, TimeoutError):
            self._设置失败(响应, "提供者不可用")
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
                能力id=请求.能力id or 请求.目标, 请求id=请求id, 任务id=请求.任务id,
                会话id=请求.会话id, 提供者=请求.提供者,
                权限范围=请求.权限范围, 来源地址=请求.来源地址,
                成功=响应.成功, 错误码=响应.错误码,
                失败原因=审计失败原因 or 响应.错误说明,
                被限流=被限流, 权限拒绝=权限拒绝,
                耗时毫秒=响应.耗时毫秒,
            )
        return 响应
