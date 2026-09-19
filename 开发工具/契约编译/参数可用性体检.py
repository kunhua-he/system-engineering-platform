"""参数可用性体检（只报告口径）：让「搜到即会用」。

华哥 2026-09-20 口述「搜到即会用、不再反复探索」。本入口检查三类参数缺陷：

1. **必填参数说明无信息量**：说明为空，或与参数名完全相同（如 `{"名称":"消息列表",
   "说明":"消息列表"}`）——使用者只能靠猜形状。
2. **句柄类参数缺产地能力**：说明里只说「网关返回的句柄」，不说**哪个能力**产生它——
   使用者拿到句柄参数也不知道该先调哪个能力。
3. **产地写了但指向不存在的能力**（2026-09-20 新增）：判据 2 只查「写没写」，
   `由 某个不存在的能力 返回` 照样能过——那等于没有指引。本判据把产地名拿全仓能力
   名库解析一遍，解析不到即判红（歧义同名不判红，那是「宁缺勿假」的合法结果）。

**为什么是「只报告」而不是阻断**（存量冻结原则）：本判据上线时存量违规 **215 条**
（131 说明问题 + 84 句柄产地，全仓 2118 个参数），直接阻断会把开发循环打死。
存量按基线治理、只减不增；新增违规由调用方按基线比对拦。

用法：`python3.14 -m 开发工具.契约编译.参数可用性体检 [--只报]`
退出码：0 = 无违规；1 = 有违规（`--只报` 时仍退出 1，由调用方按角色决定是否阻断）。
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

系统根 = Path(__file__).resolve()
for _祖先 in 系统根.parents:
    if (_祖先 / "支持库").is_dir() and (_祖先 / "模块库").is_dir():
        系统根 = _祖先
        break
if str(系统根) not in sys.path:
    sys.path.insert(0, str(系统根))

from 公共契约.基础类型.逻辑类型 import 真, 假
from 开发工具.契约编译.聚合契约解析 import 检查参数可用性

#: 存量基线（2026-09-20）：**已清零**。当日一次性补录完 198 条存量
#: （说明空 29 + 说明等于参数名 102 + 句柄缺产地 67），全仓 2118 个参数现 0 违规。
#: 基线归零 ⇒ 此后任何一处违规即判红（判据由「只报告」实质转为硬要求）。
存量基线 = 0

#: 产地句式与并列切分（与 `模块库/能力目录/实现/能力索引.py` 同口径）。
#: 为什么在这里各自实现一份而不是 import 模块库：本入口属 `开发工具/契约编译/`，
#: 让「契约编译判据」反向依赖「模块库实现」会把依赖方向倒过来（契约编译在模块库
#: 之下）。两边判据都从同一份 `说明` 文本派生，口径由本节注释与两条测试共同锁死。
产地句式 = re.compile(r"由\s*([^（）。；\n]{1,80}?)\s*返回")
产地名分隔符句式 = re.compile(r"\s*[/、和及]\s*")
无产地句式 = re.compile(r"调用方提供|无产地|不由任何能力")


def 建全仓能力名库(契约文件表: list[Path]) -> tuple[set[str], dict[str, int]]:
    """扫一遍已收集的契约文件，返回（全限定能力id 集, 末段名 → 出现次数）。"""
    全id集: set[str] = set()
    名计数: dict[str, int] = {}
    for 文件 in 契约文件表:
        try:
            数据 = json.loads(文件.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for 条目 in 数据.get("能力契约") or []:
            if not isinstance(条目, dict) or not 条目.get("能力id"):
                continue
            能力id = str(条目["能力id"])
            全id集.add(能力id)
            名 = 能力id.rsplit(".", 1)[-1]
            名计数[名] = 名计数.get(名, 0) + 1
    return 全id集, 名计数


def 产地可解析(产地名: str, 本能力id: str, 全id集: set[str],
              名计数: dict[str, int]) -> bool:
    """产地名能否解析成全仓真实能力 id（与 能力索引.解析产地 同三级判据）。

    歧义（末段名对应多条能力）**算通过**：那不证明写错了，只证明不够精确——
    真判红会逼作者瞎猜一个，属「宁缺勿假」的反面。
    """
    净 = 产地名.strip().strip("的").strip()
    if not 净:
        return 假
    if "." in 净:
        return 净 in 全id集
    同包 = f"{本能力id.rsplit('.', 1)[0]}.{净}"
    if 同包 in 全id集:
        return 真
    return 名计数.get(净, 0) >= 1


def 检查产地可解析(契约文件表: list[Path]) -> list[str]:
    """判据 3：句柄参数的产地名必须能解析到真实能力。"""
    全id集, 名计数 = 建全仓能力名库(契约文件表)
    问题表: list[str] = []
    for 文件 in 契约文件表:
        try:
            数据 = json.loads(文件.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for 条目 in 数据.get("能力契约") or []:
            if not isinstance(条目, dict) or not 条目.get("能力id"):
                continue
            能力id = str(条目["能力id"])
            for 参数 in 条目.get("参数") or []:
                if not isinstance(参数, dict):
                    continue
                名或型 = f"{参数.get('名称', '')}{参数.get('类型', '')}"
                if "句柄" not in 名或型:
                    continue
                说明 = str(参数.get("说明", "") or "")
                if 无产地句式.search(说明):
                    continue
                名表 = [段.strip().strip("的").strip()
                       for 匹配 in 产地句式.finditer(说明)
                       for 段 in 产地名分隔符句式.split(匹配.group(1))
                       if 段.strip().strip("的").strip()]
                if any(not 产地可解析(名, 能力id, 全id集, 名计数) for 名 in 名表):
                    坏 = [名 for 名 in 名表
                         if not 产地可解析(名, 能力id, 全id集, 名计数)]
                    问题表.append(
                        f"能力 {能力id}: 句柄参数 {参数.get('名称', '?')} 的产地 "
                        f"{'、'.join(坏)} 解析不到真实能力"
                        "（写明全限定能力 id，或改成「由调用方提供」）")
    return 问题表


def 体检(项目根: Path | None = None) -> tuple[list[str], int, int]:
    """扫全部包的聚合契约，返回（问题列表, 参数总数, 违规数）。"""
    根 = 项目根 or 系统根
    契约文件表 = [文件 for 文件 in sorted(根.rglob("能力契约/参数契约.json"))
              if "工程缓存" not in 文件.as_posix()]
    问题表: list[str] = []
    参数总数 = 0
    for 契约文件 in 契约文件表:
        try:
            数据 = json.loads(契约文件.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        问题, 数 = 检查参数可用性(数据)
        相对 = 契约文件.relative_to(根).as_posix()
        问题表.extend(f"{相对}: {项}" for 项 in 问题)
        参数总数 += 数
    问题表.extend(f"产地可解析: {项}" for 项 in 检查产地可解析(契约文件表))
    return 问题表, 参数总数, len(问题表)


def 主函数() -> int:
    问题表, 参数总数, 违规数 = 体检()
    for 问题 in 问题表[:40]:
        print(f"  [违规] {问题}")
    if 违规数 > 40:
        print(f"  …（另有 {违规数 - 40} 条，见完整清单请去掉本口截断）")
    print(f"参数可用性体检：扫描参数 {参数总数} 个，违规 {违规数} 条；存量基线 {存量基线}")
    if 违规数 > 存量基线:
        print(f"⇒ 新增违规 {违规数 - 存量基线} 条（超出基线，判红）")
        return 1
    print("⇒ 未超存量基线（存量冻结，只减不增）")
    return 0


if __name__ == "__main__":
    raise SystemExit(主函数())
