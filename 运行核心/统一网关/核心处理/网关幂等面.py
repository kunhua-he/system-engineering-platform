"""幂等记忆：本进程内存表 + 持久库（跨重启不丢幂等判据）。

2026-09-19 从 `网关核心` 类按职责拆出（华哥：按职责拆、能拆多细就多细）。
宿主提供 `_幂等表/_幂等进行中/_幂等锁/_幂等持久化/_幂等库路径/_幂等保留秒/_幂等存储`。"""

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
from 运行核心.统一网关.运行态.幂等存储 import 幂等存储
from 运行核心.统一网关.协议.网关信封 import 网关请求, 网关响应
from 运行核心.统一网关.协议.幂等协议常量 import 幂等库文件名, 纯查询操作, 幂等响应字段


class 幂等记忆面:
    def _执行幂等请求(self, 请求: 网关请求, 响应: 网关响应) -> 网关响应:
        """同请求id串行执行一次并缓存结果；不同请求id不得被全局锁串行化。

        判据两层（B5）：本进程内存表优先（含「进行中」事件，同键并发只放行一次）；
        内存未命中且操作属**副作用类**时查持久库 —— 命中即**不执行**：可重放就返回
        缓存响应（响应去重），不可重放就明确回报冲突（操作去重）。
        """
        if not 请求.请求id:
            self._执行(请求, 响应)
            return 响应
        摘要 = self._请求摘要(请求)
        # 持久库预读放在锁外：库慢或不可用都不拖住其它请求；同键并发由内存表的
        # 「进行中」事件兜住（跨进程并发不在本层承诺内，见文件顶部 B5 说明）。
        持久记录 = self._读取持久幂等(请求)
        if 持久记录 is not None:
            return self._持久幂等结果(请求, 响应, 摘要, 持久记录)
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
            # 落库在锁外：SQLite 写不进只留忽略痕迹，不影响本次响应。
            self._写入持久幂等(请求, 摘要, 响应)
        return 响应

    def _读取持久幂等(self, 请求: 网关请求) -> tuple[str, str | None] | None:
        """副作用类操作才查持久库；纯查询与未启用持久化一律 None。"""
        if 请求.操作 in 纯查询操作:
            return None
        库 = self._幂等库()
        if 库 is None:
            return None
        return 库.读取(请求.请求id)

    def _写入持久幂等(self, 请求: 网关请求, 摘要: str, 响应: 网关响应) -> None:
        """执行成功后落库；响应不可重放时记「操作已执行」标记（响应JSON 为 NULL）。"""
        if 请求.操作 in 纯查询操作:
            return
        库 = self._幂等库()
        if 库 is None:
            return
        库.写入(请求.请求id, 请求.操作, 摘要, self._响应转JSON(响应))

    def _持久幂等结果(self, 请求: 网关请求, 响应: 网关响应, 摘要: str,
                      记录: tuple[str, str | None]) -> 网关响应:
        """持久记录命中 → 一律**不执行**，只回报结论（响应去重 / 操作去重）。"""
        记录摘要, 响应JSON = 记录
        if 记录摘要 != 摘要:
            self._设置失败(响应, "幂等键冲突")
            return 响应
        if 响应JSON is None:
            # 操作去重：副作用已执行过，但那次响应不可重放 → 绝不重复执行。
            self._设置失败(响应, "幂等键冲突")
            响应.错误说明 = (
                f"请求id {请求.请求id} 的操作已执行完成，其响应不可重放，"
                "拒绝重复执行；如需重做请换请求id")
            return 响应
        重放 = self._从JSON还原响应(响应JSON)
        if 重放 is None:
            self._设置失败(响应, "内部错误")
            return 响应
        return 重放

    def _从JSON还原响应(self, 响应JSON: str) -> 网关响应 | None:
        try:
            数据 = json.loads(响应JSON)
        except (TypeError, ValueError):
            return None
        if not isinstance(数据, dict):
            return None
        return 网关响应(**{键: 数据[键] for 键 in 幂等响应字段 if 键 in 数据})

    def _响应转JSON(self, 响应: 网关响应) -> str | None:
        """响应可重放 → 公开信封的 JSON 文本；不可承载（字节集等）→ None。"""
        try:
            return json.dumps(响应.转字典(), ensure_ascii=False, sort_keys=True,
                              allow_nan=False)
        except (TypeError, ValueError):
            return None

    def 停用幂等持久化(self) -> None:
        """幂等判据只留本进程内存：不落库、不跨重启、不读既有记录。

        测试/演示实例用（固定请求id 的用例不得被上一次运行的记录重放掉）。
        """
        self._幂等持久化 = 假
        self._幂等存储 = None

    def _幂等库(self) -> 幂等存储 | None:
        """惰性取持久库；未启用 / 路径解析失败 → None（回落纯内存）。"""
        if not self._幂等持久化:
            return None
        if self._幂等存储 is None:
            try:
                库路径 = self._幂等库路径 or (
                    解析运行数据根(Path(__file__).resolve().parents[2]) / 幂等库文件名)
            except (OSError, ValueError) as 错误:
                记录忽略("统一网关.幂等存储.解析库路径", 错误)
                return None
            self._幂等存储 = 幂等存储(库路径, 保留秒=self._幂等保留秒)
        return self._幂等存储
