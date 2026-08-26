"""能力适配：项目能力名与系统能力id的映射。

项目代码使用项目公开入口（能力名），适配层负责把能力名解析为系统
能力id；映射表来自项目声明，禁止扫描业务代码补全。
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class 能力映射:
    """能力名 → 系统能力id 的映射表。"""

    映射表: dict[str, str] = field(default_factory=dict)

    def 添加映射(self, 能力名: str, 系统能力id: str) -> None:
        """添加映射；同名能力名重复映射拒绝。"""
        if 能力名 in self.映射表:
            raise ValueError(f"能力名重复映射: {能力名}")
        self.映射表[能力名] = 系统能力id

    def 解析(self, 能力名: str) -> str | None:
        """能力名 → 系统能力id；未映射返回 None。"""
        return self.映射表.get(能力名)

    def 反向解析(self, 系统能力id: str) -> list[str]:
        """系统能力id → 能力名列表（一个系统能力可对应多个能力名）。"""
        return [名称 for 名称, 能力id in self.映射表.items() if 能力id == 系统能力id]


def 从项目声明构建映射(项目声明数据: dict, 声明列表) -> 能力映射:
    """从项目声明与系统包声明构建能力映射。

    映射规则：能力名 = 能力id 最后一段（如 文件系统支持库.文件操作.读取文件 → 读取文件）。
    模块能力短名优先（项目代码经模块调用能力）；支持库能力短名作为补充，
    仅在未被占用时添加。完整能力id 永远可直接调用。
    """
    映射 = 能力映射()
    绑定集合: set[str] = set()
    for 绑定 in 项目声明数据.get("支持库绑定", []):
        绑定集合.add(绑定["包id"])
    for 绑定 in 项目声明数据.get("模块绑定", []):
        绑定集合.add(绑定["包id"])

    模块声明 = [声明 for 声明 in 声明列表 if 声明.包id in 绑定集合 and 声明.类型 in ("模块", "基础模块", "功能模块")]
    支持库声明 = [声明 for 声明 in 声明列表 if 声明.包id in 绑定集合 and 声明.类型 == "支持库"]

    for 声明 in 模块声明:
        for 能力 in 声明.能力:
            短名 = 能力.能力id.split(".")[-1]
            try:
                映射.添加映射(短名, 能力.能力id)
            except ValueError:
                continue
    for 声明 in 支持库声明:
        for 能力 in 声明.能力:
            短名 = 能力.能力id.split(".")[-1]
            if 映射.解析(短名) is None:
                映射.添加映射(短名, 能力.能力id)
    return 映射
