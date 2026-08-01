"""能力目录：组件/能力/契约/资源/提供者/所有者/成熟度/替代能力/复用裁决。

实现契约指纹、复用决策强制、能力占用租约（心跳/过期/释放证据）、
维护者裁决（复用/合并/允许并存/拒绝）；相同契约指纹直接阻断重复实现，
高度重叠进入待裁决；Agent 中断后占用自动过期。
"""
from __future__ import annotations

import hashlib
import json
import time
import uuid
from typing import Any


def 契约指纹(契约: dict[str, Any]) -> str:
    """契约指纹：参数/返回/错误码/副作用/资源类型/宿主/权限 → sha256。"""
    关键字段 = {
        "能力id": 契约.get("能力id", ""), "名称": 契约.get("名称", ""),
        "参数": 契约.get("参数", []), "返回": 契约.get("返回", {}),
        "错误码": 契约.get("错误码", []), "副作用": 契约.get("副作用", ""),
        "资源类型": 契约.get("资源类型", ""), "宿主": 契约.get("宿主", ""),
        "权限": 契约.get("权限", ""),
    }
    正文 = json.dumps(关键字段, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(正文.encode("utf-8")).hexdigest()[:16]


class 能力目录:
    """能力目录服务（唯一写入口：平台状态.能力条目/占用租约）。"""

    def __init__(self, 状态) -> None:
        self.状态 = 状态

    def 登记能力(self, *, 能力id: str, 契约: dict[str, Any], 组件: str, 领域: str,
                成熟度: str = "实验", 所有者: str = "", 提供者: str = "",
                资源: dict[str, Any] | None = None) -> tuple[bool, str]:
        """登记能力；相同契约指纹直接阻断重复实现。"""
        指纹 = 契约指纹(契约)
        已有 = self.状态.查询记录("能力条目", "契约指纹=?", (指纹,))
        if 已有 and 已有[0]["能力id"] != 能力id:
            return False, f"相同契约指纹已存在: {已有[0]['能力id']}（必须复用或声明新提供者）"
        self.状态.写入记录("能力条目", {
            "能力id": 能力id, "契约指纹": 指纹, "组件": 组件, "领域": 领域,
            "成熟度": 成熟度, "所有者": 所有者, "替代能力": "", "复用裁决": "",
            "裁决状态": "已登记", "提供者": 提供者,
            "资源": json.dumps(资源 or {}, ensure_ascii=False), "版本": "1",
        })
        return True, "能力已登记"

    def 搜索能力(self, 关键词: str = "", 限制: int = 20) -> list[dict[str, Any]]:
        结果表 = []
        for 记录 in self.状态.查询记录("能力条目"):
            if 关键词 and 关键词 not in 记录["能力id"] and 关键词 not in 记录["组件"]:
                continue
            结果表.append({键: 记录[键] for 键 in
                          ("能力id", "组件", "领域", "成熟度", "所有者", "裁决状态")})
            if len(结果表) >= 限制:
                break
        return 结果表

    def 待裁决(self) -> list[dict[str, Any]]:
        return [记录 for 记录 in self.状态.查询记录("能力条目")
                if 记录["裁决状态"] == "待裁决"]

    def 裁决(self, *, 能力id: str, 决定: str, 替代能力: str = "",
             维护者: str = "") -> tuple[bool, str]:
        """维护者裁决：复用/合并/允许并存/拒绝；裁决写入能力目录供后续继承。"""
        if 决定 not in ("复用", "合并", "允许并存", "拒绝"):
            return False, f"未知裁决: {决定}"
        更新 = {"复用裁决": 决定, "裁决状态": "已裁决"}
        if 替代能力:
            更新["替代能力"] = 替代能力
        self.状态.条件更新("能力条目", 更新, "能力id=?", (能力id,))
        self.状态.追加证据(类型="能力目录", 主题=能力id, 内容={"裁决": 决定, "替代": 替代能力},
                          调用者=维护者, 角色="平台维护者", 结果="裁决")
        return True, f"裁决完成: {决定}"

    # ---- 能力占用租约 ----
    def 申请占用(self, *, 能力id: str, 领域: str, 契约指纹: str, 任务: str,
                所有者: str, 心跳秒: float = 60.0) -> tuple[bool, str, str]:
        """申请能力占用；唯一部分索引（活跃租约同能力唯一）原子保证互斥。"""
        租约id = uuid.uuid4().hex[:16]
        成功 = self.状态.原子插入("占用租约", {
            "租约id": 租约id, "能力id": 能力id, "领域": 领域, "契约指纹": 契约指纹,
            "任务": 任务, "所有者": 所有者, "心跳": time.time(),
            "过期时间": time.time() + 心跳秒 * 10, "释放证据": "", "状态": "活跃",
        })
        if not 成功:
            活跃 = [租约 for 租约 in self.状态.查询记录("占用租约", "状态='活跃' AND 能力id=?", (能力id,))]
            占用者 = 活跃[0]["所有者"] if 活跃 else "未知"
            return False, f"能力已被占用: {占用者}", ""
        return True, "占用成功", 租约id

    def 续租(self, 租约id: str) -> bool:
        记录 = self.状态.读取记录("占用租约", "租约id", 租约id)
        if 记录 is None or 记录["状态"] != "活跃":
            return False
        return self.状态.条件更新("占用租约", {"心跳": time.time()},
                                  "租约id=? AND 状态='活跃'", (租约id,))

    def 释放占用(self, 租约id: str, 证据: str = "") -> bool:
        return self.状态.条件更新("占用租约", {"状态": "已释放", "释放证据": 证据},
                                  "租约id=? AND 状态='活跃'", (租约id,))

    def 回收过期占用(self, 心跳超时秒: float = 300.0) -> list[str]:
        """Agent 中断后占用自动过期（心跳停止）；幂等。"""
        过期列表 = []
        截止 = time.time() - 心跳超时秒
        for 租约 in self.状态.查询记录("占用租约", "状态='活跃' AND 心跳 <= ?", (截止,)):
            self.状态.条件更新("占用租约", {"状态": "已过期"},
                              "租约id=? AND 状态='活跃'", (租约["租约id"],))
            过期列表.append(租约["租约id"])
        return 过期列表
