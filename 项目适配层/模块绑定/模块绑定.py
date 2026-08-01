"""模块绑定：校验并绑定模块到项目。

模块只能经公开支持库能力运行；绑定校验：模块存在、版本满足、
模块依赖的支持库能力全部存在且版本满足、无依赖循环。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from 公共契约.版本规则.比较 import 满足约束
from 运行核心.加载器.包发现.发现器 import 发现全部


@dataclass
class 绑定结果:
    """一次模块绑定的结果。"""

    模块id: str
    成功: bool = False
    绑定版本: str = ""
    问题列表: list[str] = field(default_factory=list)


def 校验绑定(模块id: str, 版本约束: str, 系统根目录: Path) -> 绑定结果:
    """校验模块能否绑定到项目（不修改任何状态）。"""
    结果 = 绑定结果(模块id=模块id)
    发现 = 发现全部(系统根目录 / "支持库", 系统根目录 / "模块库")
    支持库声明 = [声明 for 声明 in 发现.声明列表 if 声明.类型 == "支持库"]
    模块声明列表 = [声明 for 声明 in 发现.声明列表 if 声明.类型 == "模块"]

    # 1. 模块是否存在
    匹配列表 = [声明 for 声明 in 模块声明列表 if 声明.包id == 模块id]
    if not 匹配列表:
        结果.问题列表.append(f"模块不存在: {模块id}")
        return 结果
    声明 = 匹配列表[0]

    # 2. 版本是否满足
    if 版本约束 and not 满足约束(声明.版本, 版本约束):
        结果.问题列表.append(f"版本不满足: {模块id}@{声明.版本} 不满足 {版本约束}")
        return 结果

    # 3. 模块依赖的支持库能力必须存在且版本满足
    支持库能力表 = {
        能力.能力id: (条目.包id, 条目.版本)
        for 条目 in 支持库声明 for 能力 in 条目.能力
    }
    for 依赖 in 声明.依赖:
        能力id = 依赖.get("能力", "")
        版本约束值 = 依赖.get("版本", "")
        if 能力id not in 支持库能力表:
            结果.问题列表.append(f"模块依赖的支持库能力不存在: {模块id} 依赖 {能力id}")
            return 结果
        if 版本约束值:
            提供版本 = 支持库能力表[能力id][1]
            if not 满足约束(提供版本, 版本约束值):
                结果.问题列表.append(f"模块依赖版本不满足: {能力id}@{提供版本} 不满足 {版本约束值}")
                return 结果

    # 4. 模块间依赖循环
    依赖图: dict[str, set[str]] = {}
    for 条目 in 模块声明列表:
        依赖图[条目.包id] = {
            依赖.get("能力", "").split(".")[0] for 依赖 in 条目.依赖 if 依赖.get("能力")
        }
    已访问: set[str] = set()
    在路径: set[str] = set()

    def 检测循环(包id: str) -> bool:
        if 包id in 在路径:
            return True
        if 包id in 已访问:
            return False
        已访问.add(包id)
        在路径.add(包id)
        for 依赖包 in 依赖图.get(包id, set()):
            if 依赖包 in 依赖图 and 检测循环(依赖包):
                return True
        在路径.remove(包id)
        return False

    for 包id in 依赖图:
        if 检测循环(包id):
            结果.问题列表.append(f"模块存在依赖循环: {模块id}")
            return 结果

    结果.成功 = True
    结果.绑定版本 = 声明.版本
    return 结果
