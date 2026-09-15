"""包发现器：统一扫描支持库与模块库，读取声明并检查唯一性。

检查项：包 id 唯一、能力 id 唯一、包声明合法。加载器不执行未通过
校验的包；发现阶段只读文件系统与声明，不加载任何实现。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from 公共契约.包声明.声明 import 包声明, 加载声明文件
from 公共契约.正式根 import 枚举正式根

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
        # 适配层 Provider 也必须进入内部提供者选择和装配表；后续
        # 能力计数/公开 owner 会按 支持库.适配层. 前缀过滤，不对外暴露。
        # 功能域分组 v2：跳过聚合支持库内部的子域包声明（子域只是目录分组，不是独立包）
        # 6 大聚合库的子域跳过；第三方支持库的子域是独立子库，保留
        if 包类型 == "支持库":
            相对部分 = 声明路径.relative_to(根目录).parts
            聚合库名表 = {"系统核心支持库", "大语言模型支持库", "办公文档支持库",
                        "文件系统支持库", "数据操作支持库", "网络通信支持库"}
            # 形如 后端/<聚合库>/<子域>/包声明.json（4 部分，聚合库在列表内）→ 跳过
            if (len(相对部分) >= 3 and 相对部分[1] in 聚合库名表
                    and not (声明路径.parent / "能力定义.json").is_file()):
                continue
        声明 = 加载声明文件(声明路径)
        if 声明.类型 in 模块类别集合:
            声明列表.append(声明)
    return 声明列表


def 发现全部(
    支持库根目录: Path,
    模块根目录: Path,
    技能库根目录: Path | None = None,
    额外根目录表: list | None = None,
) -> 发现结果:
    """发现全部正式包，检查包 id 与能力 id 唯一性（**声明式根**）。

    正式根清单的唯一事实源是 `公共契约.正式根.正式根名表`（支持库/模块库/
    技能库/平台控制面/运行核心）：除显式传入的三根外，其余存在且含包声明的
    正式根**自动纳入**，不再靠调用方逐个传参。硬编码根列表本身就是特例绕过
    ——治理类能力面（`平台控制面`、`运行核心`）会因此装不进装配表。

    技能库根目录仍是可选兼容参数（技能库包的类型是「支持库」，单独成根只是
    让它在目录上与支持库/模块库平级）；同一根不会重复扫描。该参数为 None 时，
    技能库若存在则由声明式清单自动纳入，行为与原来一致。
    """
    结果 = 发现结果()
    声明列表: list = []
    已扫根集合: set = set()

    def 扫(根目录, 类型: str) -> None:
        路径 = Path(根目录)
        try:
            键 = 路径.resolve()
        except OSError:
            键 = 路径
        if 键 in 已扫根集合:
            return
        已扫根集合.add(键)
        声明列表.extend(扫描目录(路径, 类型))

    扫(支持库根目录, "支持库")
    if 技能库根目录 is not None:
        扫(技能库根目录, "支持库")
    if 额外根目录表 is None:
        try:
            系统根 = Path(支持库根目录).resolve().parent
            额外根目录表 = 枚举正式根(系统根)
        except Exception:
            额外根目录表 = []
    for 根目录, 类型 in 额外根目录表 or ():
        扫(根目录, 类型)
    扫(模块根目录, "模块")
    结果.声明列表 = sorted(声明列表, key=lambda 声明: 声明.包id)

    包id出现: dict[str, int] = {}
    # 能力重复是声明层约束：适配层声明也必须参与计数，避免重复声明
    # 被后续提供者选择器误报为“多提供者冲突”。适配层仍不会成为公开
    # owner；公开能力注册/选择继续由后续层按其边界过滤。
    能力id出现: dict[str, int] = {}
    for 声明 in 声明列表:
        包id出现[声明.包id] = 包id出现.get(声明.包id, 0) + 1
        # 已废弃包不参与当前声明唯一性；适配层参与重复检测，但不作为
        # 公开能力 owner（公开 owner 边界由提供者选择/注册层维护）。
        if getattr(声明, "已废弃", False):
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
