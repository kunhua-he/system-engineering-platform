"""参数与返回校验：操作参数契约、能力参数契约、按契约过滤参数、结果类型合法性。

2026-09-19 从 `网关核心` 类按职责拆出。宿主提供 `后端核心`。"""

from __future__ import annotations

from __future__ import annotations
import time
import uuid
import copy
import difflib
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
from 运行核心.统一网关.协议.网关信封 import 网关请求
from 运行核心.统一网关.协议.参数别名表 import _应用参数别名

# 「最接近的契约参数」建议的相似度下限（difflib 口径，0~1）：低于它就不猜。
# 取 0.34 —— 实测 `路径` → `修改路径` 相似度 0.67，能点出真名；而 `路径` → `项目根`
# 这类无关名不会瞎点。**瞎点的建议比不给建议更坏**，故宁可留空。
近似名阈值 = 0.34


class 参数校验面:
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
            # 任务提交不在此表内：它的「参数」就是能力自身的入参，按能力契约校验
            # （见 _能力参数错误），与「调用能力」同一套规则。
            "任务查询": {"任务id"},
            "任务取消": {"任务id"},
            "热接入": set(),
        }
        允许字段 = 允许字段表.get(请求.操作)
        if 允许字段 is None:
            return ""
        参数 = 请求.参数
        # 协议兼容口径（哲学第 5 条 2 项）：**未知字段一律忽略**，只有「必填缺失」与「类型不符」才失败。
        # 旧行为是「未知字段即 400」，等于上游多传一个字段就整条调用失败，属兼容性硬点，已废止；
        # 以后协议只增不删不改名（改名须走别名表），保证旧调用方永不因新增字段而失败。
        值映射 = {
            "包详情": ("包id", 参数.get("包id")),
            "能力详情": ("能力id", 参数.get("能力id") or 请求.能力id or 请求.目标),
            "资源状态": ("句柄", 参数.get("句柄") or 请求.句柄),
            "资源续租": ("句柄", 参数.get("句柄") or 请求.句柄),
            "资源关闭": ("句柄", 参数.get("句柄") or 请求.句柄),
            "任务查询": ("任务id", 参数.get("任务id") or 请求.任务id),
            "任务取消": ("任务id", 参数.get("任务id") or 请求.任务id),
        }
        缺少字段 = [字段 for 操作, (字段, 值) in 值映射.items()
                  if 请求.操作 == 操作 and not 值]
        if 缺少字段:
            return f"参数不合法：操作 {请求.操作} 缺少必填字段 {', '.join(缺少字段)}"
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

    def _能力参数错误(self, 能力id: str, 参数: dict[str, Any]) -> str:
        """查注册表拿参数声明，委托唯一校验点 校验能力参数。"""
        注册表 = getattr(self.后端核心, "注册表", None)
        获取 = getattr(注册表, "获取", None)
        实现 = 获取(能力id) if callable(获取) else None
        if 实现 is None:
            return ""
        return 校验能力参数(能力id, getattr(实现, "参数", []), 参数)

    def _过滤能力参数(self, 能力id: str, 参数: dict[str, Any]) -> dict[str, Any]:
        """按能力契约剔除未知参数（协议兼容：未知字段一律忽略，不转给实现）。

        边界归一化放在网关做，实现永远看不到未知字段——否则上游多传一个字段
        会让实现收到 `TypeError`，等于把兼容性问题推给每个能力作者。
        """
        注册表 = getattr(self.后端核心, "注册表", None)
        获取 = getattr(注册表, "获取", None)
        实现 = 获取(能力id) if callable(获取) else None
        声明参数 = getattr(实现, "参数", None)
        if not isinstance(声明参数, list):
            return dict(参数)
        参数名 = {项.get("名称") if isinstance(项, dict) else 项 for 项 in 声明参数}
        已归一 = _应用参数别名(能力id, 参数)
        return {键: 值 for 键, 值 in 已归一.items() if 键 in 参数名}

    def _被忽略参数(self, 能力id: str, 参数: dict[str, Any]) -> list[dict[str, Any]]:
        """列出会被契约剔除的入参（只增回带，不改剔除行为，2026-09-21）。

        为什么要有它：未知字段一律忽略是刻意的协议兼容口径（哲学第 5 条 2 项），
        但「静默」让调用方分不清两种完全不同的情况 —— 「这个能力没这功能」与
        「我把参数名写错了」。实测踩过：给 `查询文件租约` 传 `路径`（真名 `修改路径`），
        条件被剔除后过滤器变成「取全部」⇒ 一次拿回 470KB 全表，还据此差点把平台
        判成缺陷。⇒ 剔除照旧，但**把「丢了哪些键、最接近的契约参数叫什么」说出来**。

        返回每条 `{参数名, 原因, 最接近的契约参数}`；没有忽略项时返回空列表。
        近似名用标准库 difflib 的字符相似度取（中文参数名按字符比，`路径` 对
        `修改路径` 相似度 0.67 ⇒ 能被点出来），低于阈值不猜、返回空列表。
        """
        注册表 = getattr(self.后端核心, "注册表", None)
        获取 = getattr(注册表, "获取", None)
        实现 = 获取(能力id) if callable(获取) else None
        声明参数 = getattr(实现, "参数", None)
        if not isinstance(声明参数, list):
            return []
        参数名 = [项.get("名称") if isinstance(项, dict) else 项 for 项 in 声明参数]
        参数名 = [名 for 名 in 参数名 if isinstance(名, str) and 名]
        if not 参数名:
            return []
        允许 = set(参数名)
        被忽略 = [键 for 键 in _应用参数别名(能力id, 参数) if 键 not in 允许]
        if not 被忽略:
            return []
        return [
            {
                "参数名": 键,
                "原因": "该能力契约里没有这个参数，已被网关剔除",
                "最接近的契约参数": difflib.get_close_matches(键, 参数名, n=3, cutoff=近似名阈值),
            }
            for 键 in 被忽略
        ]

    @staticmethod
    def _能力结果类型合法(结果对象: Any) -> bool:
        """能力返回必须是统一结果且关键字段类型固定，禁止真假值漂移。"""
        if not hasattr(结果对象, "成功") or not isinstance(结果对象.成功, bool):
            return 假
        for 字段 in ("错误码", "错误说明"):
            if not isinstance(getattr(结果对象, 字段, None), str):
                return 假
        return 真
