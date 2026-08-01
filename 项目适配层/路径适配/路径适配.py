"""路径适配：项目目录路径的唯一解析来源。

项目路径规则：项目根目录 + 标准子目录名（项目代码/项目模块/项目配置/
项目资源/测试/运行入口）。整个适配层只保留这一处路径解析实现。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

标准子目录表 = ["项目代码", "项目模块", "项目配置", "项目资源", "测试", "运行入口"]


@dataclass
class 项目路径:
    """项目标准路径集合。"""

    根目录: Path

    @property
    def 项目代码(self) -> Path:
        return self.根目录 / "项目代码"

    @property
    def 项目模块(self) -> Path:
        return self.根目录 / "项目模块"

    @property
    def 项目配置(self) -> Path:
        return self.根目录 / "项目配置"

    @property
    def 项目资源(self) -> Path:
        return self.根目录 / "项目资源"

    @property
    def 测试(self) -> Path:
        return self.根目录 / "测试"

    @property
    def 运行入口(self) -> Path:
        return self.根目录 / "运行入口"

    @property
    def 项目声明文件(self) -> Path:
        return self.根目录 / "项目声明.json"

    @property
    def 依赖锁定文件(self) -> Path:
        return self.根目录 / "依赖锁定.json"

    def 校验完整(self) -> list[str]:
        """校验标准子目录齐全；返回缺失目录列表。"""
        缺失 = [名称 for 名称 in 标准子目录表 if not (self.根目录 / 名称).is_dir()]
        return 缺失
