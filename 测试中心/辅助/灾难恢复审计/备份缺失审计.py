"""工作包19 备份缺失攻击审计：备份缺关键文件必须明确失败（场景7）。"""
from __future__ import annotations

from pathlib import Path

from 平台控制面.备份恢复.备份契约 import 权威数据备份契约

from 审计环境 import 构造存储根, 构造权威状态库


def _最新快照(备份目录: Path) -> Path:
    return sorted(备份目录.glob("快照_*"))[-1]


class 备份缺失攻击审计:
    """对 备份契约 注入 源缺失/备份后删关键文件/清单丢失 三类缺失。"""

    def __init__(self, 临时根: Path) -> None:
        self.临时根 = Path(临时根)

    def 审计(self) -> dict:
        """场景7：备份缺关键文件 → 校验/恢复必须明确失败。"""
        缺陷表: list[str] = []
        目录a = self.临时根 / "存储根7a"
        目录a.mkdir(parents=True, exist_ok=True)
        构造权威状态库(目录a, "v1")  # 不建 项目锁.json 与 制品 目录 → 两类源缺失
        契约a = 权威数据备份契约(目录a)
        备份a = self.临时根 / "备份7a"
        契约a.执行备份(备份a)
        校验a, 原因a = 契约a.校验备份(备份a)
        恢复a = 契约a.恢复(备份a, self.临时根 / "目标7a")
        if 校验a:
            缺陷表.append("源缺失备份校验仍成功")
        if 恢复a["成功"]:
            缺陷表.append("源缺失备份恢复仍成功")
        if "缺失" not in 原因a:
            缺陷表.append(f"源缺失失败原因不明确: {原因a}")
        存储根b = 构造存储根(self.临时根 / "存储根7b", 版本标记="v1")
        契约b = 权威数据备份契约(存储根b)
        备份b = self.临时根 / "备份7b"
        契约b.执行备份(备份b)
        快照b = _最新快照(备份b)
        (快照b / "权威状态.db").unlink()
        校验b, 原因b = 契约b.校验备份(备份b)
        if 校验b:
            缺陷表.append("删除权威状态.db 后校验备份仍成功")
        try:
            恢复b = 契约b.恢复(备份b, self.临时根 / "目标7b")
            恢复b失败, 恢复b原因 = not 恢复b["成功"], [x["原因"] for x in 恢复b["结果"]]
        except FileNotFoundError as 错误:
            恢复b失败, 恢复b原因 = True, [str(错误)]
        if not 恢复b失败:
            缺陷表.append("删除权威状态.db 后恢复未失败")
        (快照b / "备份清单.json").unlink()
        try:
            契约b.校验备份(备份b)
            清单缺失被拒 = False
            清单缺失消息 = "校验备份未拒绝"
        except FileNotFoundError as 错误:
            清单缺失被拒 = True
            清单缺失消息 = str(错误)
        if not 清单缺失被拒:
            缺陷表.append(f"删除备份清单后未明确拒绝: {清单缺失消息}")
        return {"场景": "备份缺失", "防御有效": not 缺陷表, "缺陷": "；".join(缺陷表),
                "详情": {"源缺失校验": (校验a, 原因a), "源缺失恢复成功": 恢复a["成功"],
                         "删db校验": (校验b, 原因b), "删db恢复失败": 恢复b失败,
                         "删db恢复原因": 恢复b原因, "删清单拒绝": 清单缺失被拒,
                         "删清单消息": 清单缺失消息}}
