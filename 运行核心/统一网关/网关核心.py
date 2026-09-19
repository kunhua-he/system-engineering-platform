"""统一网关控制面：协议转换、权限、五维限流、脱敏错误与安全审计。

**本文件是宿主**（2026-09-19 按职责拆细，华哥裁决「能拆多细就多细，按职责拆，
不然后面还要拆，反复工作这个就很麻烦」）。职责已按块外置，本文件只留：
  ① 模块级协议数据与纯函数的**再导出**（调用方路径与符号名零改动）；
  ② `网关核心` 类的骨架 —— `__init__`（唯一的状态归属处）+ 两个装配 setter；
  ③ 四个职责混入类的装配（`class 网关核心(幂等记忆面, 参数校验面, 执行面, 请求处理面)`）。

外置的职责块（同目录）：
  `错误说明表.py`      348 码 → 文案（对外错误码文案唯一来源）
  `幂等存储.py`        幂等记录的 SQLite 落地
  `网关信封.py`        网关请求 / 网关响应（纯数据类）
  `调用点缺参判定.py`  操作不存在错误 + 调用点缺参判定
  `参数别名表.py`      能力参数别名表 + 参数别名归一
  `操作协议表.py`      允许操作表 + 操作权限表
  `幂等协议常量.py`    幂等库文件名 / 纯查询操作 / 幂等响应字段
  `网关幂等面.py`      幂等记忆（内存表 + 持久库）
  `网关参数校验面.py`  参数与返回校验
  `网关执行面.py`      操作分发与执行
  `网关处理面.py`      请求入口与响应装配

拆法保证**对外符号零变化**：所有搬走的名字在本文件 `from … import` 再导出，
`网关核心.公开错误说明表 is 错误说明表.公开错误说明表`（其余同理）。
"""

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
from 运行核心.统一网关.安全边界 import 脱敏错误信息
from 运行核心.统一网关.限流器 import 限流器
from 公共契约.版本规则.契约版本 import 契约版本
from 公共契约.运行时.运行缓存 import 解析运行数据根
from 公共契约.诊断.忽略记录 import 记录忽略
from 公共契约.基础类型.逻辑类型 import 真, 假

# ── 职责块装配（导入即再导出，调用方零改动）──────────────────────────────
from 运行核心.统一网关.错误说明表 import 公开错误说明表  # noqa: F401
from 运行核心.统一网关.幂等存储 import 幂等存储, 幂等默认保留秒  # noqa: F401
from 运行核心.统一网关.网关信封 import 网关请求, 网关响应  # noqa: F401
from 运行核心.统一网关.调用点缺参判定 import 操作不存在错误, _是调用点缺参错误  # noqa: F401
from 运行核心.统一网关.参数别名表 import 能力参数别名表, _应用参数别名  # noqa: F401
from 运行核心.统一网关.操作协议表 import 允许操作表, 操作权限表  # noqa: F401
from 运行核心.统一网关.幂等协议常量 import 幂等库文件名, 纯查询操作, 幂等响应字段  # noqa: F401
from 运行核心.统一网关.类型规格 import (  # noqa: F401 —— 2026-09-18 拆出时的再导出，本行原样保留
    类型短名映射, 类型匹配表, 数值类型名, _类型表自检, 校验能力参数,
)
from 运行核心.统一网关.网关幂等面 import 幂等记忆面
from 运行核心.统一网关.网关参数校验面 import 参数校验面
from 运行核心.统一网关.网关执行面 import 执行面
from 运行核心.统一网关.网关处理面 import 请求处理面


class 网关核心(幂等记忆面, 参数校验面, 执行面, 请求处理面):
    """所有调用共享同一限流器与审计器，业务能力仍由后端核心实现。

    按职责拆成四个混入类（MRO：幂等记忆面 → 参数校验面 → 执行面 → 请求处理面）；
    类内状态（后端核心/任务系统/限流器/审计/计数/幂等四件套）仍归本类 `__init__` 独占。
    """

    def __init__(self, 后端核心: Any = None, 任务系统: Any = None,
                 限流器实例: 限流器 | None = None,
                 审计实例: 安全审计 | None = None,
                 *,
                 幂等持久化: bool = 真,
                 幂等库路径: Path | str | None = None,
                 幂等保留秒: float = 幂等默认保留秒) -> None:
        self.后端核心 = 后端核心
        self.任务系统 = 任务系统
        self.限流器 = 限流器实例 or 限流器()
        self.审计 = 审计实例 or 安全审计()
        self.请求数 = 0
        self.失败数 = 0
        self._幂等表: dict[str, tuple[str, 网关响应]] = {}
        self._幂等进行中: dict[str, tuple[str, threading.Event]] = {}
        self._幂等锁 = threading.Lock()
        # 幂等持久化：**默认开**（进程重启不丢幂等判据，见文件顶部 B5 说明）。
        # 测试/演示实例显式关（`停用幂等持久化`），避免固定请求id 跨运行串味。
        self._幂等持久化 = bool(幂等持久化)
        self._幂等库路径 = Path(幂等库路径) if 幂等库路径 is not None else None
        self._幂等保留秒 = float(幂等保留秒)
        self._幂等存储: 幂等存储 | None = None

    def 设置后端(self, 后端核心: Any) -> None:
        self.后端核心 = 后端核心

    def 设置任务系统(self, 任务系统: Any) -> None:
        self.任务系统 = 任务系统
