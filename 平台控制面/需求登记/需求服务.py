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
from 公共契约.基础类型.逻辑类型 import 真, 假


class 需求不存在错误(ValueError):
    """未登记需求 id 触达需求写动作时的唯一阻断信号（`生成装配计划` 抛它）。

    为什么单独一个类型（2026-09-17 修「需求确认闸门可绕过」）：能力实现层必须把它映射成
    中文域错误码 `需求不存在`，不能与 `装配计划生成失败`（同为 ValueError）混一条 ——
    混了以后「需求压根没登记」和「计划本身不合法」共用一个错误码，闸门与调用方都无法分辨。
    """


def 取登记快照(记录: Any) -> dict[str, Any] | None:
    """从需求行里取 `登记需求` 写入的不可变快照；取不到即返回 None。

    判据只有一条：`登记需求` **真的写过**这条需求的快照。行存在、`确认状态=已确认`
    都不算数 —— 修前 `生成装配计划` 直接 `写入记录("需求", …)`（底层 INSERT OR REPLACE）
    能平白建出一行，于是「需求已确认」这条权威事实不再唯一来自 `登记需求`。
    本函数是该事实的唯一判定点：全包凡问「这条需求算不算登记过」，一律问它。
    """
    if not isinstance(记录, dict):
        return None
    原文 = 记录.get("快照")
    if not isinstance(原文, str) or not 原文.strip():
        return None
    try:
        快照 = json.loads(原文)
    except (ValueError, TypeError):
        return None
    if not isinstance(快照, dict) or not str(快照.get("需求id") or "").strip():
        return None
    if str(快照.get("需求id")) != str(记录.get("需求id")):
        return None
    return 快照


def 已登记且已确认(记录: Any) -> bool:
    """需求行是否「已登记（有 `登记需求` 写的快照）且已确认」——两个条件必须同时成立。"""
    return bool(取登记快照(记录) is not None and 记录.get("确认状态") == "已确认")


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
        """确认需求快照；未确认前正式开发/发布门禁必须失败。

        闸门两条（2026-09-17 修「需求确认闸门可绕过」）：行必须存在，且 `登记需求` 写的
        **快照必须非空**。修前只查「记录存在」，于是任何平白建出的行（见 `生成装配计划`
        修前的 INSERT OR REPLACE）都能被确认 ——「需求已确认」这条权威事实就不再唯一来自
        `登记需求`。老库里已经这么被确认过的脏行（有确认状态、无快照）在本口径下一律不认。
        """
        记录 = self.状态.读取记录("需求", "需求id", 需求id)
        if 记录 is None:
            return 假, f"需求不存在: {需求id}"
        if 取登记快照(记录) is None:
            return 假, f"需求不存在: {需求id}（该行没有 登记需求 写入的需求快照，不能确认）"
        if 记录["确认状态"] == "已确认":
            return 真, "需求已确认（幂等）"
        self.状态.条件更新("需求", {"确认状态": "已确认", "状态": "已确认"},
                          "需求id=?", (需求id,))
        self.状态.追加证据(类型="需求", 主题=需求id, 内容={"确认": 真},
                          调用者=调用者, 角色=角色, 结果="确认")
        return 真, "需求已确认"

    def 需求已确认(self, 需求id: str) -> bool:
        """只读判定：登记过（有快照）且已确认才算 true（脏行一律不认，见 `取登记快照`）。"""
        记录 = self.状态.读取记录("需求", "需求id", 需求id)
        return 已登记且已确认(记录)

    def 生成装配计划(self, *, 需求id: str, 能力搜索结果: list[dict[str, Any]],
                    工作包表: list[dict[str, Any]]) -> dict[str, Any]:
        """生成装配计划：依赖 DAG + 并行波次 + 工作包（波次内互不占用相同能力）。

        写库前必须先读需求行（2026-09-17 修「未登记需求可被顺手建行」）：本方法只用
        `条件更新`/`读取记录`，不建行；需求不存在即抛 `需求不存在错误`，
        调用方映射成中文域错误码 `需求不存在`。
        """
        if 取登记快照(self.状态.读取记录("需求", "需求id", 需求id)) is None:
            raise 需求不存在错误(
                f"需求不存在: {需求id}（未登记需求一律不得生成装配计划，写库前先读记录、不建行）")
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

    def 查询需求(self, 需求id: str = "") -> list[dict[str, Any]]:
        """查询需求记录（只读，包化时补的唯一读动作）。

        给 `需求id` 单查（未命中返回空列表，不伪造记录）；留空按创建顺序列出全部。
        本方法只是把 `self.状态.读取记录/查询记录` 的原有两个调用收在服务里，
        不新增任何需求语义，也不改既有方法的行为。
        """
        if 需求id:
            记录 = self.状态.读取记录("需求", "需求id", 需求id)
            return [记录] if 记录 is not None else []
        return self.状态.查询记录("需求")
