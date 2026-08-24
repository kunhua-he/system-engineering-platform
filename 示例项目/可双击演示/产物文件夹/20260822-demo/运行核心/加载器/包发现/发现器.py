"""包发现器：统一扫描支持库与模块库，读取声明并检查唯一性。

检查项：包 id 唯一、能力 id 唯一、包声明合法。加载器不执行未通过
校验的包；发现阶段只读文件系统与声明，不加载任何实现。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from 公共契约.包声明.声明 import 包声明, 加载声明文件

声明文件名 = "包声明.json"


@dataclass
class 发现结果:
    """发现结果：包声明列表与唯一性/合法性问题。"""

    声明列表: list[包声明] = field(default_factory=list)
    问题列表: list[str] = field(default_factory=list)

    @property
    def 成功(self) -> bool:
        return not self.问题列表


def 扫描目录(根目录: Path, 包类型: str) -> list[包声明]:
    """递归扫描根目录下全部同类型包声明（跳过 _ 开头的目录）。

    模块类别（基础模块/功能模块/模块）统一按 包类型="模块" 识别（S0.2）。
    """
    声明列表: list[包声明] = []
    模块类别集合 = {"模块", "基础模块", "功能模块"} if 包类型 == "模块" else {包类型}
    if not 根目录.is_dir():
        return 声明列表
    for 声明路径 in sorted(根目录.rglob(声明文件名)):
        if any(部分.startswith("_") for 部分 in 声明路径.parts):
            continue
        声明 = 加载声明文件(声明路径)
        if 声明.类型 in 模块类别集合:
            声明列表.append(声明)
    return 声明列表


def 发现全部(
    支持库根目录: Path,
    模块根目录: Path,
) -> 发现结果:
    """发现全部支持库与模块，检查包 id 与能力 id 唯一性。"""
    结果 = 发现结果()
    声明列表 = 扫描目录(支持库根目录, "支持库") + 扫描目录(模块根目录, "模块")
    结果.声明列表 = sorted(声明列表, key=lambda 声明: 声明.包id)

    包id出现: dict[str, int] = {}
    能力id出现: dict[str, int] = {}
    for 声明 in 声明列表:
        包id出现[声明.包id] = 包id出现.get(声明.包id, 0) + 1
        # 适配层仅是受管实现，不是公开能力 owner；已废弃包也不注册能力。
        if getattr(声明, "已废弃", False) or 声明.包id.startswith("支持库.适配层."):
            continue
        for 能力 in 声明.能力:
            能力id出现[能力.能力id] = 能力id出现.get(能力.能力id, 0) + 1
    for 包id, 次数 in 包id出现.items():
        if 次数 > 1:
            结果.问题列表.append(f"包 id 重复: {包id} 出现 {次数} 次")
    for 能力id, 次数 in 能力id出现.items():
        if 次数 > 1:
            结果.问题列表.append(f"能力 id 重复: {能力id} 出现 {次数} 次")
    return 结果
