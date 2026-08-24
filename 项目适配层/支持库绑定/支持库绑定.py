"""支持库绑定：校验并绑定支持库到项目。

六项校验：包存在、版本满足、能力存在、多提供者、依赖循环、宿主冲突。
绑定只读包声明，不加载支持库实现。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from 公共契约.包声明 import 包声明
from 公共契约.版本规则.比较 import 满足约束
from 运行核心.加载器.包发现.发现器 import 发现全部
from 运行核心.加载器.提供者选择.选择器 import 选择提供者


@dataclass
class 绑定结果:
    """一次支持库绑定的结果。"""

    支持库id: str
    成功: bool = False
    绑定版本: str = ""
    问题列表: list[str] = field(default_factory=list)


def 校验绑定(支持库id: str, 版本约束: str, 支持库根目录: Path) -> 绑定结果:
    """校验支持库能否绑定到项目（不修改任何状态）。"""
    结果 = 绑定结果(支持库id=支持库id)
    发现 = 发现全部(支持库根目录, Path("不存在的模块目录"))
    声明列表 = [声明 for 声明 in 发现.声明列表 if 声明.类型 == "支持库"]

    # 1. 包是否存在
    匹配列表 = [声明 for 声明 in 声明列表 if 声明.包id == 支持库id]
    if not 匹配列表:
        结果.问题列表.append(f"支持库不存在: {支持库id}")
        return 结果
    声明 = 匹配列表[0]

    # 2. 版本是否满足
    if 版本约束 and not 满足约束(声明.版本, 版本约束):
        结果.问题列表.append(f"版本不满足: {支持库id}@{声明.版本} 不满足 {版本约束}")
        return 结果

    # 3. 能力是否存在（支持库必须至少提供一项能力）
    if not 声明.能力:
        结果.问题列表.append(f"支持库未声明任何能力: {支持库id}")
        return 结果

    # 4. 多提供者冲突（支持库id 唯一，能力不应被多个包重复提供）
    for 能力 in 声明.能力:
        选择 = 选择提供者(能力.能力id, 声明列表)
        if 选择.冲突列表:
            结果.问题列表.append(f"能力 {能力.能力id} 多提供者冲突: {' / '.join(选择.冲突列表)}")
            return 结果

    # 5. 依赖循环（支持库之间不得循环依赖）
    依赖图: dict[str, set[str]] = {}
    for 条目 in 声明列表:
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
            结果.问题列表.append(f"支持库存在依赖循环: {支持库id}")
            return 结果

    # 6. 宿主冲突（同名能力不得跨越正式支持库宿主重复声明；废弃包与
    # 适配层 Provider 不参与）。Provider 只是公开 owner 的内部实现，
    # 不能因实现声明同一能力而被算作第二个宿主。
    能力id出现: dict[str, int] = {}
    for 条目 in 声明列表:
        if (getattr(条目, "已废弃", False)
                or 条目.包id.startswith("支持库.适配层.")):
            continue
        for 能力 in 条目.能力:
            能力id出现[能力.能力id] = 能力id出现.get(能力.能力id, 0) + 1
    for 能力id, 次数 in 能力id出现.items():
        if 次数 > 1:
            结果.问题列表.append(f"能力 {能力id} 被 {次数} 个宿主声明（宿主冲突）")
            return 结果

    结果.成功 = True
    结果.绑定版本 = 声明.版本
    return 结果
