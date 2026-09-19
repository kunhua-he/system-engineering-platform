"""请求入口与响应装配：计时、权限、错误码收口、审计、限流与响应写出。

2026-09-19 从 `网关核心` 类按职责拆出。宿主提供 `限流器/审计/后端核心`。"""

from __future__ import annotations

from __future__ import annotations
import time
import uuid
import copy
import json
import base64
import sqlite3
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from 运行核心.运行诊断.安全审计.安全审计 import 安全审计
from 运行核心.能力调用.运行上下文.上下文 import 运行上下文
from 运行核心.统一网关.安全.安全边界 import 脱敏错误信息
from 运行核心.统一网关.安全.限流器 import 限流器
from 公共契约.版本规则.契约版本 import 契约版本
from 公共契约.运行时.运行缓存 import 解析运行数据根
from 公共契约.诊断.忽略记录 import 记录忽略
from 公共契约.基础类型.逻辑类型 import 真, 假
from 运行核心.统一网关.协议.类型规格 import (
    类型短名映射, 类型匹配表, 数值类型名, _类型表自检, 校验能力参数,
)
from 运行核心.统一网关.协议.网关信封 import 网关请求, 网关响应
from 运行核心.统一网关.协议.操作协议表 import 允许操作表, 操作权限表
from 运行核心.统一网关.协议.调用点缺参判定 import 操作不存在错误


class 请求处理面:
    def 处理(self, 请求: 网关请求) -> 网关响应:
        开始 = time.monotonic()
        请求id = 请求.请求id or uuid.uuid4().hex[:16]
        响应 = 网关响应(请求id=请求id, 操作=请求.操作)
        # 版本三项信息（哲学第 5 条 2 项）：回报「请求版本 / 当前版本 / 差异原因」；
        # 版本号不一致本身不失败，只有强制参数不满足才失败。
        响应.请求版本 = 请求.请求版本
        响应.当前版本 = 契约版本
        if 请求.请求版本 and 请求.请求版本 != 契约版本:
            响应.版本差异 = (
                f"请求版本 {请求.请求版本} 与当前契约版本 {契约版本} 不一致；"
                "无强制约束，按兼容放行（只有强制参数不满足才失败）"
            )
        已进入限流 = 假
        审计失败原因 = ""
        被限流 = 假
        权限拒绝 = 假
        try:
            if 请求.操作 not in 允许操作表:
                raise 操作不存在错误("未知操作")
            if not self._权限通过(请求):
                权限拒绝 = 真
                raise PermissionError("权限范围不足")
            通过, _ = self.限流器.进入请求(
                项目id=请求.项目id, 用户id=请求.用户id, 能力id=请求.能力id,
                任务id=请求.任务id, 提供者=请求.提供者,
            )
            if not 通过:
                被限流 = 真
                self._设置失败(响应, "限流")
            else:
                已进入限流 = 真
                响应 = self._执行幂等请求(请求, 响应)
        except 操作不存在错误:
            self._设置失败(响应, "操作不存在")
        # 异常分支 → 公开码收口：这里出现的每个码都必须在 公开错误说明表 与
        # 本地网关.公开错误码状态映射 中同时登记（批次0-3 同步纪律）。
        # KeyError 兜底=能力 id 未注册（能力 id 不存在时才是真实语义，业务分支
        # 应各自先判空，见 F-04）；FileNotFoundError=文件不存在（原先落在两张表外，
        # 已随批次0-3 登记为公开码，不再回落「请求处理失败」+500）。
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

    def _权限通过(self, 请求: 网关请求) -> bool:
        """进程内兼容调用可不带范围；HTTP 安全层会注入可信范围。"""
        if not 请求.权限范围:
            return 真
        需要权限 = 操作权限表.get(请求.操作, "")
        return not 需要权限 or 需要权限 in 请求.权限范围 or "全部" in 请求.权限范围

    def _设置失败(self, 响应: 网关响应, 错误码: str) -> None:
        响应.成功 = 假
        响应.值 = None
        响应.错误码 = 错误码
        响应.错误说明 = 公开错误说明表.get(错误码, "请求处理失败")

    def _设置后端字典结果(self, 响应: 网关响应, 值: Any) -> None:
        """后端字典的兼容口径（哲学第 5 条 2 项）：信封**只增不改不删，缺键补默认**。

        旧行为是「缺任一必填键即判 502 返回结果不符合契约」——实现少写一个键就整条链路失败，
        属兼容性硬点，已废止。现在的判定分三类：
        - **缺 `成功` 键且未声明 `错误码`/`错误说明`**：视为**业务值**，按成功返回该字典
          （实现返回裸业务字典是合法用法，不该被判违约）；
        - **声明了 `错误码`/`错误说明` 但没写 `成功`**：视为实现声明的失败，取其错误码（缺则 `内部错误`）；
        - **键存在但类型不符**（`成功` 不是真正逻辑型、`错误码`/`错误说明` 不是文本）：仍判契约违约——
          类型漂移必须拦（第 3 条 2 项：失败必须明确），这条不能放宽。
        """
        if not isinstance(值, dict):
            响应.值 = 值
            return
        if "成功" not in 值:
            if "错误码" in 值 or "错误说明" in 值:
                self._设置失败(响应, str(值.get("错误码") or "内部错误"))
                响应.错误说明 = 脱敏错误信息(str(值.get("错误说明", "")))
                return
            响应.值 = 值
            return
        成功 = 值.get("成功")
        if (not isinstance(成功, bool)
                or not isinstance(值.get("错误码", ""), str)
                or not isinstance(值.get("错误说明", ""), str)):
            self._设置失败(响应, "返回结果不符合契约")
            return
        if not 成功:
            self._设置失败(响应, 值.get("错误码") or "内部错误")
            响应.错误说明 = 脱敏错误信息(值.get("错误说明", ""))
            return
        响应.值 = 值.get("值")

# ── 跨文件依赖（拆分后补齐，2026-09-19；原是同一模块内的兄弟名字）──
from 运行核心.统一网关.协议.错误说明表 import 公开错误说明表
