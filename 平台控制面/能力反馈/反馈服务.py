"""能力反馈登记、查询和状态迁移；唯一写入平台状态 SQLite。

机制（非空文本 / 大小上限 / 敏感脱敏 / 内容摘要）统一取自同目录 `反馈语义.py`，
本模块只保留**能力反馈自己的**字段、去重键与 8 态状态机；对外返回值与收敛前逐字一致。
"""
from __future__ import annotations

import hashlib
import json
import re
import time
import uuid
from pathlib import Path
from typing import Any, Callable

from 平台控制面.平台状态 import 平台状态
# 机制收口（第 1 条 3 项）：文本校验 / 敏感脱敏 / 摘要上限 / 内容摘要由 反馈语义.py 唯一实现。
from 平台控制面.能力反馈.反馈语义 import 文本, 文本上限, 摘要, 说明上限
from 平台控制面.能力反馈.反馈语义 import 内容摘要 as 计算内容摘要
from 公共契约.基础类型.逻辑类型 import 真, 假

状态表 = {
    "已登记": {"已确认", "重复反馈", "无法复现", "修复中"},
    "已确认": {"修复中", "无法复现", "重复反馈"},
    "修复中": {"待验证", "无法复现"},
    "待验证": {"已修复", "修复中"},
    "已修复": {"已关闭", "修复中"},
    "无法复现": {"已关闭", "修复中"},
    "重复反馈": {"已关闭"},
    "已关闭": set(),
}
优先级表 = {"普通", "高", "紧急"}
必填字段 = ("来源系统", "来源版本", "请求id", "能力id", "契约版本", "错误码", "错误说明")
契约格式 = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")


def _公开记录(记录: dict[str, Any]) -> dict[str, Any]:
    返回 = dict(记录)
    for 名称 in ("请求摘要", "响应摘要"):
        try:
            返回[名称] = json.loads(记录.get(名称) or "{}")
        except (TypeError, json.JSONDecodeError):
            返回[名称] = {}
    返回.pop("去重键", None)
    返回.pop("内容摘要", None)
    return 返回


class 能力反馈服务:
    """反馈事实服务；不执行反馈内容，不改变能力契约或 Provider 配置。"""

    def __init__(self, 存储目录: str, 能力存在: Callable[[str], bool], *,
                 状态: 平台状态 | None = None) -> None:
        self.状态 = 状态 or 平台状态(Path(存储目录), 项目id="平台控制面")
        self.能力存在 = 能力存在

    def 登记(self, 请求: dict[str, Any]) -> tuple[bool, str, dict[str, Any]]:
        try:
            if not isinstance(请求, dict):
                raise ValueError("请求必须是 JSON 对象")
            for 字段 in 必填字段:
                if 字段 not in 请求:
                    raise ValueError(f"缺少必填字段: {字段}")
            字段值 = {字段: 文本(请求[字段], 字段) for 字段 in 必填字段}
            if not 契约格式.fullmatch(字段值["契约版本"]):
                raise ValueError("契约版本必须是 主版本.次版本.修订版本")
            能力id = 字段值["能力id"]
            if not self.能力存在(能力id):
                return 假, "能力不存在", {}
            # 契约判据（平台控制面/能力反馈/能力契约/参数契约.json 的 请求 参数说明）：
            # 来源系统/来源版本/请求id/能力id/契约版本/错误码/错误说明 **必填**，
            # HTTP状态码 等五项 **可选**。可选字段缺省 != 值 0：缺省一律存 0 表示「未提供」，
            # **不做 100-599 区间校验**，只有调用方真的传了 HTTP状态码 才校验。
            # 反例（修复前实测 2026-09-16）：`请求.get("HTTP状态码", 0)` 把缺省当成 0 再判区间，
            # 于是契约允许的「最小反馈登记」必被判 参数不合法（200 != 400 黑盒红）。
            if "HTTP状态码" in 请求 and 请求["HTTP状态码"] is not None:
                状态码 = 请求["HTTP状态码"]
                if isinstance(状态码, bool) or not isinstance(状态码, int) or not 100 <= 状态码 <= 599:
                    raise ValueError("HTTP状态码必须是 100 到 599 的整数")
            else:
                状态码 = 0
            优先级 = 请求.get("优先级", "普通")
            if 优先级 not in 优先级表:
                raise ValueError("优先级必须是 普通、高、紧急")
            请求摘要 = 摘要(请求.get("请求摘要"), "请求摘要")
            响应摘要 = 摘要(请求.get("响应摘要"), "响应摘要")
            复现标识 = 请求.get("复现标识", "")
            if 复现标识 and (not isinstance(复现标识, str) or len(复现标识) > 文本上限):
                raise ValueError("复现标识超过长度上限")
            去重原文 = f"{字段值['来源系统']}\n{字段值['请求id']}\n{复现标识 or '请求'}"
            去重键 = hashlib.sha256(去重原文.encode("utf-8")).hexdigest()
            内容 = {**字段值, "HTTP状态码": 状态码, "请求摘要": 请求摘要,
                    "响应摘要": 响应摘要, "复现标识": 复现标识, "优先级": 优先级}
            内容摘要 = 计算内容摘要(内容)
            反馈id = uuid.uuid4().hex[:20]
            时间 = time.strftime("%Y-%m-%d %H:%M:%S")
            记录 = {"反馈id": 反馈id, "去重键": 去重键, **字段值,
                    "HTTP状态码": 状态码, "请求摘要": 请求摘要, "响应摘要": 响应摘要,
                    "复现标识": 复现标识, "优先级": 优先级, "状态": "已登记",
                    "创建时间": 时间, "更新时间": 时间, "处理者": "", "状态原因": "",
                    "关联提交": "", "验证证据": "", "发布制品": "", "内容摘要": 内容摘要}
            if self.状态.原子插入("能力反馈", 记录):
                return 真, "", {"反馈id": 反馈id, "状态": "已登记", "是否重复": 假}
            旧记录 = self.状态.查询记录("能力反馈", "去重键=?", (去重键,))
            if not 旧记录:
                return 假, "反馈写入失败", {}
            if 旧记录[0].get("内容摘要") != 内容摘要:
                return 假, "幂等键冲突", {"反馈id": 旧记录[0]["反馈id"]}
            return 真, "", {"反馈id": 旧记录[0]["反馈id"], "状态": 旧记录[0]["状态"], "是否重复": 真}
        except (OSError, TypeError, ValueError, KeyError, json.JSONDecodeError):
            return 假, "参数不合法", {}

    def 查询(self, 反馈id: str = "", 状态: str = "", 能力id: str = "", 限制: int = 50) -> tuple[bool, str, list[dict[str, Any]]]:
        if not isinstance(限制, int) or isinstance(限制, bool) or not 1 <= 限制 <= 100:
            return 假, "限制必须是 1 到 100 的整数", []
        条件, 参数 = [], []
        if 反馈id:
            条件.append("反馈id=?"); 参数.append(反馈id)
        if 状态:
            if 状态 not in 状态表: return 假, "状态不合法", []
            条件.append("状态=?"); 参数.append(状态)
        if 能力id:
            条件.append("能力id=?"); 参数.append(能力id)
        try:
            结果 = self.状态.查询记录("能力反馈", " AND ".join(条件) or "", tuple(参数))
            结果 = [_公开记录(项) for 项 in 结果[:限制]]
            return 真, "", 结果
        except (OSError, ValueError):
            return 假, "反馈查询失败", []

    def 迁移状态(self, 反馈id: str, 请求: dict[str, Any]) -> tuple[bool, str, dict[str, Any]]:
        try:
            if not isinstance(请求, dict):
                raise ValueError("请求必须是 JSON 对象")
            允许字段 = {"状态", "处理者", "原因", "关联提交", "验证证据", "发布制品"}
            未知字段 = sorted(set(请求) - 允许字段)
            if 未知字段:
                raise ValueError("状态请求包含未知字段: " + ", ".join(未知字段))
            目标 = 文本(请求.get("状态"), "状态")
            处理者 = 文本(请求.get("处理者"), "处理者")
            原因 = 文本(请求.get("原因"), "原因", 说明上限)
            if 目标 not in 状态表:
                raise ValueError("状态不合法")
            记录 = self.状态.读取记录("能力反馈", "反馈id", 反馈id)
            if not 记录:
                return 假, "反馈不存在", {}
            当前 = 记录["状态"]
            if 目标 not in 状态表.get(当前, set()):
                return 假, "状态迁移不允许", {"当前状态": 当前, "目标状态": 目标}
            字段 = {"处理者": 处理者, "状态原因": 原因,
                    "关联提交": 文本(请求.get("关联提交", ""), "关联提交") if 请求.get("关联提交") else "",
                    "验证证据": 文本(请求.get("验证证据", ""), "验证证据", 说明上限) if 请求.get("验证证据") else "",
                    "发布制品": 文本(请求.get("发布制品", ""), "发布制品", 说明上限) if 请求.get("发布制品") else "",
                    "状态": 目标, "更新时间": time.strftime("%Y-%m-%d %H:%M:%S")}
            if 目标 == "已修复" and (not 字段["验证证据"] or not 字段["发布制品"]):
                return 假, "已修复必须提供验证证据和发布制品", {}
            if not self.状态.条件更新("能力反馈", 字段, "反馈id=? AND 状态=?", (反馈id, 当前)):
                return 假, "状态版本冲突", {}
            self.状态.追加证据(类型="能力反馈状态", 主题=反馈id,
                              内容={"从": 当前, "到": 目标, "原因": 原因,
                                    "关联提交": 字段["关联提交"], "验证证据": 字段["验证证据"],
                                    "发布制品": 字段["发布制品"]}, 调用者=处理者, 结果=目标)
            return 真, "", {"反馈id": 反馈id, "状态": 目标, "处理者": 处理者}
        except (OSError, TypeError, ValueError, KeyError):
            return 假, "参数不合法", {}
