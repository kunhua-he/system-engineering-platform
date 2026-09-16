"""需求登记：不可变需求快照、验收契约、装配计划、工作包、变更影响与确认状态。

需求规划入口：输入用户目标 → 固定输出 需求快照.json/验收契约.json/
装配计划.json/工作包/*.json；搜索现有能力、生成依赖 DAG 与并行波次；
未确认需求时正式开发与发布门禁必须失败；需求变化生成新版本不覆盖旧快照。
"""
from __future__ import annotations

import json
import time
import uuid
from typing import Any


class 需求登记:
    """需求登记服务（唯一写入口：平台状态.需求表）。"""

    def __init__(self, 状态) -> None:
        self.状态 = 状态

    def 登记需求(self, *, 目标: str, 非目标: str = "", 输入: dict[str, Any] | None = None,
                输出: dict[str, Any] | None = None, 权限: dict[str, Any] | None = None,
                调用者: str = "", 角色: str = "") -> dict[str, Any]:
        """创建需求快照（不可变，变化生成新版本）。"""
        需求id = uuid.uuid4().hex[:16]
        版本 = "1"
        快照 = {"需求id": 需求id, "版本": 版本, "目标": 目标, "非目标": 非目标,
                "输入": 输入 or {}, "输出": 输出 or {}, "权限": 权限 or {},
                "验收结果": [], "创建时间": time.strftime("%Y-%m-%d %H:%M:%S")}
        self.状态.写入记录("需求", {
            "需求id": 需求id, "版本": 版本, "状态": "待确认", "快照": json.dumps(快照, ensure_ascii=False),
            "验收契约": "{}", "装配计划": "{}", "变更影响": "{}", "确认状态": "未确认",
            "创建时间": 快照["创建时间"],
        })
        self.状态.追加证据(类型="需求", 主题=需求id, 内容=快照, 操作id=需求id,
                          调用者=调用者, 角色=角色, 结果="登记")
        return 快照

    def 确认需求(self, *, 需求id: str, 调用者: str = "", 角色: str = "") -> tuple[bool, str]:
        """确认需求快照；未确认前正式开发/发布门禁必须失败。"""
        记录 = self.状态.读取记录("需求", "需求id", 需求id)
        if 记录 is None:
            return False, f"需求不存在: {需求id}"
        if 记录["确认状态"] == "已确认":
            return True, "需求已确认（幂等）"
        self.状态.条件更新("需求", {"确认状态": "已确认", "状态": "已确认"},
                          "需求id=?", (需求id,))
        self.状态.追加证据(类型="需求", 主题=需求id, 内容={"确认": True},
                          调用者=调用者, 角色=角色, 结果="确认")
        return True, "需求已确认"

    def 需求已确认(self, 需求id: str) -> bool:
        记录 = self.状态.读取记录("需求", "需求id", 需求id)
        return bool(记录 and 记录["确认状态"] == "已确认")

    def 生成装配计划(self, *, 需求id: str, 能力搜索结果: list[dict[str, Any]],
                    工作包表: list[dict[str, Any]]) -> dict[str, Any]:
        """生成装配计划：依赖 DAG + 并行波次 + 工作包（波次内互不占用相同能力）。"""
        波次表: dict[int, list[str]] = {}
        已占用: set[str] = set()
        for 包 in 工作包表:
            波次 = 包.get("波次", 1)
            占用 = 包.get("能力占用", [])
            冲突 = [能力 for 能力 in 占用 if 能力 in 已占用]
            if 冲突 and 波次 == 1:
                raise ValueError(f"波次1内部能力占用冲突: {冲突}")
            已占用.update(占用)
            波次表.setdefault(波次, []).append(包["工作包id"])
        计划 = {
            "需求id": 需求id, "能力搜索结果": 能力搜索结果,
            "波次": {str(波次): 列表 for 波次, 列表 in sorted(波次表.items())},
            "工作包表": 工作包表, "生成时间": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        self.状态.写入记录("需求", {"需求id": 需求id, "装配计划": json.dumps(计划, ensure_ascii=False)},
                          "需求id")
        return 计划

    def 保存工作包(self, *, 需求id: str, 波次: int, 说明: str,
                 输入快照: dict[str, Any], 允许修改路径: list[str],
                 能力占用: list[str], 资源预算: dict[str, Any],
                 验收命令: str) -> dict[str, Any]:
        工作包id = uuid.uuid4().hex[:16]
        记录 = {"工作包id": 工作包id, "需求id": 需求id, "波次": 波次, "说明": 说明,
                "输入快照": json.dumps(输入快照, ensure_ascii=False),
                "允许修改路径": json.dumps(允许修改路径, ensure_ascii=False),
                "能力占用": json.dumps(能力占用, ensure_ascii=False),
                "资源预算": json.dumps(资源预算, ensure_ascii=False),
                "验收命令": 验收命令, "状态": "待执行"}
        self.状态.写入记录("工作包", 记录)
        return 记录

    def 查询工作包(self, 需求id: str = "") -> list[dict[str, Any]]:
        if 需求id:
            return self.状态.查询记录("工作包", "需求id=?", (需求id,))
        return self.状态.查询记录("工作包")
