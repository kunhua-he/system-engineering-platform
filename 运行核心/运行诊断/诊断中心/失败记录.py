"""失败记录：失败证据的持久化与维修状态流转。

状态：待诊断 → 已定位 → 修复中 → 待回归 → 已修复 → 已关闭；
可跳过状态：已忽略（必须填写原因与有效期，不能永久隐藏失败）。
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from 公共契约.基础类型.逻辑类型 import 真, 假

状态_待诊断 = "待诊断"
状态_已定位 = "已定位"
状态_修复中 = "修复中"
状态_待回归 = "待回归"
状态_已修复 = "已修复"
状态_已关闭 = "已关闭"
状态_已忽略 = "已忽略"

允许流转表 = {
    状态_待诊断: {状态_已定位, 状态_已忽略, 状态_已关闭},
    状态_已定位: {状态_修复中, 状态_已忽略, 状态_已关闭},
    状态_修复中: {状态_待回归, 状态_已忽略, 状态_已关闭},
    状态_待回归: {状态_已修复, 状态_已忽略, 状态_已关闭},
    状态_已修复: {状态_已关闭},
    状态_已关闭: set(),
    状态_已忽略: {状态_已定位, 状态_修复中, 状态_待回归, 状态_已关闭},
}


@dataclass
class 失败记录:
    """一条失败记录（含诊断定位与维修状态）。"""

    记录id: str
    追踪id: str
    时间: str
    包id: str
    模块id: str = ""
    能力id: str = ""
    版本: str = ""
    错误码: str = ""
    错误说明: str = ""
    阶段: str = ""  # 失败发生在哪个阶段（发现/校验/锁定/装配/运行/停止/卸载）
    提供者: str = ""
    是否可重试: bool = 假
    归类: str = ""  # 契约漂移/配置问题/提供者问题/资源释放问题/未知
    状态: str = 状态_待诊断
    关联验证场景: str = ""
    复现输入: str = ""
    忽略原因: str = ""
    忽略有效期: str = ""
    详情: dict[str, Any] = field(default_factory=dict)

    def 转字典(self) -> dict[str, Any]:
        return {
            "记录id": self.记录id, "追踪id": self.追踪id, "时间": self.时间,
            "包id": self.包id, "模块id": self.模块id, "能力id": self.能力id,
            "版本": self.版本, "错误码": self.错误码, "错误说明": self.错误说明,
            "阶段": self.阶段, "提供者": self.提供者, "是否可重试": self.是否可重试,
            "归类": self.归类, "状态": self.状态, "关联验证场景": self.关联验证场景,
            "复现输入": self.复现输入, "忽略原因": self.忽略原因,
            "忽略有效期": self.忽略有效期, "详情": self.详情,
        }


class 失败记录库:
    """失败记录库：存储、状态流转、查询。"""

    def __init__(self, 存储目录: Path | None = None) -> None:
        self.存储目录 = 存储目录 or Path(失败记录库.默认存储目录())
        self.存储目录.mkdir(parents=True, exist_ok=True)
        self.记录表: dict[str, 失败记录] = {}
        self.加载()

    @staticmethod
    def 默认存储目录() -> str:
        import os, tempfile
        return os.environ.get("系统库诊断目录", str(Path(tempfile.gettempdir()) / "系统级支持库_诊断"))

    def 加载(self) -> None:
        文件 = self.存储目录 / "失败记录.jsonl"
        if not 文件.is_file():
            return
        for 行 in 文件.read_text(encoding="utf-8").splitlines():
            try:
                数据 = json.loads(行)
                记录 = 失败记录(**{k: v for k, v in 数据.items() if k in 失败记录.__dataclass_fields__})
                记录.详情 = 数据.get("详情", {})
                self.记录表[记录.记录id] = 记录
            except (json.JSONDecodeError, TypeError):
                continue

    def 保存(self) -> None:
        文件 = self.存储目录 / "失败记录.jsonl"
        with 文件.open("w", encoding="utf-8") as 输出:
            for 记录 in self.记录表.values():
                输出.write(json.dumps(记录.转字典(), ensure_ascii=False) + "\n")

    def 登记失败(self, *, 追踪id: str, 包id: str, 错误码: str, 错误说明: str,
                 模块id: str = "", 能力id: str = "", 版本: str = "", 阶段: str = "",
                 提供者: str = "", 是否可重试: bool = 假, 归类: str = "",
                 关联验证场景: str = "", 复现输入: str = "") -> 失败记录:
        记录 = 失败记录(
            记录id=uuid.uuid4().hex[:16], 追踪id=追踪id,
            时间=time.strftime("%Y-%m-%d %H:%M:%S"),
            包id=包id, 模块id=模块id, 能力id=能力id, 版本=版本,
            错误码=错误码, 错误说明=错误说明, 阶段=阶段, 提供者=提供者,
            是否可重试=是否可重试, 归类=归类,
            关联验证场景=关联验证场景, 复现输入=复现输入,
        )
        self.记录表[记录.记录id] = 记录
        self.保存()
        return 记录

    def 流转状态(self, 记录id: str, 目标状态: str, *, 忽略原因: str = "", 忽略有效期: str = "") -> tuple[bool, str]:
        """状态流转；已忽略必须填写原因与有效期。"""
        记录 = self.记录表.get(记录id)
        if 记录 is None:
            return 假, f"记录不存在: {记录id}"
        if 目标状态 not in 允许流转表.get(记录.状态, set()):
            return 假, f"不允许从 {记录.状态} 流转到 {目标状态}"
        if 目标状态 == 状态_已忽略:
            if not 忽略原因:
                return 假, "已忽略必须填写忽略原因"
            if not 忽略有效期:
                return 假, "已忽略必须填写忽略有效期（不能永久隐藏失败）"
            记录.忽略原因 = 忽略原因
            记录.忽略有效期 = 忽略有效期
        记录.状态 = 目标状态
        self.保存()
        return 真, ""

    def 查询(self, *, 包id: str = "", 模块id: str = "", 能力id: str = "",
             版本: str = "", 错误码: str = "", 追踪id: str = "", 状态: str = "",
             归类: str = "") -> list[失败记录]:
        结果列表 = []
        for 记录 in self.记录表.values():
            if 包id and 记录.包id != 包id:
                continue
            if 模块id and 记录.模块id != 模块id:
                continue
            if 能力id and 记录.能力id != 能力id:
                continue
            if 版本 and 记录.版本 != 版本:
                continue
            if 错误码 and 记录.错误码 != 错误码:
                continue
            if 追踪id and 记录.追踪id != 追踪id:
                continue
            if 状态 and 记录.状态 != 状态:
                continue
            if 归类 and 记录.归类 != 归类:
                continue
            结果列表.append(记录)
        return 结果列表

    def 最近失败(self, 条数: int = 10) -> list[失败记录]:
        return list(self.记录表.values())[-条数:]

    def 同类失败统计(self, *, 包id: str = "", 错误码: str = "") -> dict[str, int]:
        统计表: dict[str, int] = {}
        for 记录 in self.查询(包id=包id, 错误码=错误码):
            键 = f"{记录.包id}@{记录.错误码}"
            统计表[键] = 统计表.get(键, 0) + 1
        return dict(sorted(统计表.items(), key=lambda 项: -项[1]))
