"""HTML 验证结果和报告。"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class 验证结果:
    场景id: str
    能力id: str
    通过: bool = False
    状态码: int = 0
    返回: dict[str, Any] = field(default_factory=dict)
    耗时毫秒: float = 0
    失败原因: str = ""
    定位线索: str = ""
    步骤id: str = ""
    步骤类型: str = ""

    def 转字典(self) -> dict[str, Any]:
        return {
            "场景id": self.场景id, "能力id": self.能力id, "通过": self.通过,
            "状态码": self.状态码, "返回": self.返回, "耗时毫秒": self.耗时毫秒,
            "失败原因": self.失败原因, "定位线索": self.定位线索,
            "步骤id": self.步骤id, "步骤类型": self.步骤类型,
        }


@dataclass
class 验证报告:
    制品路径: str = ""
    制品摘要前: dict[str, Any] = field(default_factory=dict)
    制品摘要后: dict[str, Any] = field(default_factory=dict)
    场景总数: int = 0
    通过数: int = 0
    失败数: int = 0
    正向成功数: int = 0
    负向校验数: int = 0
    并发峰值: int = 0
    结果列表: list[验证结果] = field(default_factory=list)
    资源回收: dict[str, Any] = field(default_factory=dict)
    场景制品摘要: str = ""
    时间: str = ""
    证据绑定: dict[str, Any] = field(default_factory=dict)
    目标能力数: int = 0
    步骤总数: int = 0
    清理失败数: int = 0
    资源残留数: int = 0
    资源残留: list[str] = field(default_factory=list)
    目标能力全集: list[str] = field(default_factory=list)
    正向目标能力全集: list[str] = field(default_factory=list)
    实际成功目标能力全集: list[str] = field(default_factory=list)

    @property
    def 制品指纹(self) -> dict[str, Any]:
        return self.制品摘要前

    def 转字典(self) -> dict[str, Any]:
        数据 = {字段: getattr(self, 字段) for 字段 in (
            "制品路径", "制品摘要前", "制品摘要后", "场景总数", "通过数", "失败数",
            "正向成功数", "负向校验数", "并发峰值", "资源回收", "场景制品摘要", "时间",
            "证据绑定", "目标能力数", "步骤总数", "清理失败数", "资源残留数", "资源残留",
            "目标能力全集", "正向目标能力全集", "实际成功目标能力全集",
        )}
        数据["结果列表"] = [结果.转字典() for 结果 in self.结果列表]
        return 数据

    def 汇总(self) -> str:
        if self.场景总数 <= 0:
            return "阻断: 无任何有效验证场景（禁止零验证成功）"
        if self.失败数:
            return (f"失败: {self.失败数} 项未通过；目标能力 {self.目标能力数}，步骤 {self.步骤总数}，"
                    f"清理失败 {self.清理失败数}，资源残留 {self.资源残留数}")
        return (f"通过: 目标能力 {self.目标能力数}，步骤 {self.步骤总数}；"
                f"清理失败 {self.清理失败数}，资源残留 {self.资源残留数}")
