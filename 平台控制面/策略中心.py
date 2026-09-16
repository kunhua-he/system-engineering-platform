"""策略中心：统一判定依赖、权限、资源、兼容、复用、签名和发布策略。

只返回结构化决定（允许/拒绝 + 理由 + 证据），策略判定与执行分离。
"""
from __future__ import annotations

import time
import uuid
from typing import Any


class 策略中心:
    """策略中心服务（唯一写入口：平台状态.策略表）。"""

    def __init__(self, 状态) -> None:
        self.状态 = 状态

    def 判定(self, *, 类型: str, 主题: str, 请求: dict[str, Any]) -> dict[str, Any]:
        """统一判定入口；返回结构化决定 {允许, 理由, 证据id}。"""
        决定 = self._执行判定(类型, 主题, 请求)
        证据id = self.状态.追加证据(
            类型="策略", 主题=f"{类型}:{主题}",
            内容={"请求": 请求, "决定": 决定},
            调用者=请求.get("调用者", ""), 角色=请求.get("角色", ""),
            结果="允许" if 决定["允许"] else "拒绝",
            错误码="" if 决定["允许"] else 决定.get("错误码", ""))
        决定["证据id"] = 证据id
        return 决定

    def _执行判定(self, 类型: str, 主题: str, 请求: dict[str, Any]) -> dict[str, Any]:
        """按策略类型执行判定（可被测试扩展）。"""
        if 类型 == "复用":
            return self._复用判定(主题, 请求)
        if 类型 == "依赖":
            return self._依赖判定(主题, 请求)
        if 类型 == "签名":
            return self._签名判定(主题, 请求)
        if 类型 == "发布":
            return self._发布判定(主题, 请求)
        if 类型 == "资源":
            return self._资源判定(主题, 请求)
        return {"允许": True, "理由": f"无 {类型} 策略约束"}

    def _复用判定(self, 能力id: str, 请求: dict[str, Any]) -> dict[str, Any]:
        记录 = self.状态.读取记录("能力条目", "能力id", 能力id)
        if 记录 is None:
            return {"允许": True, "理由": "能力不存在，允许新增"}
        if 记录["裁决状态"] == "待裁决":
            return {"允许": False, "理由": "疑似重叠能力未裁决，禁止发布", "错误码": "待裁决"}
        if 记录["复用裁决"] == "拒绝":
            return {"允许": False, "理由": f"维护者裁决拒绝: {记录['复用裁决']}", "错误码": "复用被拒"}
        if 记录["复用裁决"] in ("复用", "合并", "允许并存"):
            return {"允许": True, "理由": f"复用裁决: {记录['复用裁决']}"}
        return {"允许": True, "理由": "已登记能力"}

    def _依赖判定(self, 包id: str, 请求: dict[str, Any]) -> dict[str, Any]:
        依赖 = 请求.get("依赖", [])
        声明 = {依赖项["能力id"] for 依赖项 in 依赖}
        已存在 = {记录["能力id"] for 记录 in self.状态.查询记录("能力条目")}
        缺失 = 声明 - 已存在
        if 缺失:
            return {"允许": False, "理由": f"依赖能力未登记: {缺失}", "错误码": "依赖缺失"}
        return {"允许": True, "理由": "依赖全部已登记"}

    def _签名判定(self, 包id: str, 请求: dict[str, Any]) -> dict[str, Any]:
        if not 请求.get("已签名"):
            return {"允许": False, "理由": "未签名包禁止安装/激活", "错误码": "未签名"}
        if 请求.get("签名失效"):
            return {"允许": False, "理由": "签名失效（内容/权限/预算变化）", "错误码": "签名失效"}
        发布者 = 请求.get("签名者", "")
        信任 = self.状态.读取记录("信任", "发布者", 发布者)
        if 信任 is None or 信任["状态"] != "有效":
            return {"允许": False, "理由": f"发布者不在信任目录: {发布者}", "错误码": "发布者不受信"}
        return {"允许": True, "理由": f"签名有效，发布者受信: {发布者}"}

    def _发布判定(self, 包id: str, 请求: dict[str, Any]) -> dict[str, Any]:
        需求id = 请求.get("需求id", "")
        if 需求id:
            需求 = self.状态.读取记录("需求", "需求id", 需求id)
            if 需求 is None or 需求["确认状态"] != "已确认":
                return {"允许": False, "理由": "需求未确认，禁止发布", "错误码": "需求未确认"}
        候选 = 请求.get("候选版本", "")
        已有 = [记录 for 记录 in self.状态.查询记录("发布", "包id=?", (包id,))
                if 记录["期望版本"] == 候选 and 记录["状态"] in ("激活", "灰度")]
        if 已有:
            return {"允许": False, "理由": f"候选版本已发布: {候选}", "错误码": "版本已存在"}
        return {"允许": True, "理由": "发布条件满足"}

    def _资源判定(self, 包id: str, 请求: dict[str, Any]) -> dict[str, Any]:
        预算 = 请求.get("资源预算", {})
        缺失 = [键 for 键 in ("内存上限", "线程上限", "子进程上限", "并发调用上限",
                             "队列长度", "单次调用超时") if 键 not in 预算]
        if 缺失:
            return {"允许": False, "理由": f"资源预算缺少必需项: {缺失}", "错误码": "预算不完整"}
        return {"允许": True, "理由": "资源预算完整"}
