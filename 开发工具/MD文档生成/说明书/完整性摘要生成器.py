"""为正式支持库与模块生成可重复的逐文件完整性摘要（委托唯一生成器）。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# 项目根入 sys.path 必须在任何项目内导入之前（直接执行时项目根不在 path）。
系统根 = Path(__file__).resolve()
for _祖先 in 系统根.parents:
    if (_祖先 / "支持库").is_dir() and (_祖先 / "模块库").is_dir():
        系统根 = _祖先
        break
if str(系统根) not in sys.path:
    sys.path.insert(0, str(系统根))

from 支持库.后端.组件规范支持库 import (
    生成完整性摘要,
    扫描正式包,
    摘要文件名,
)
# 生成器落盘的**唯一腿**（2026-09-23「生成器开窗」）：原子写 + 留写入凭据，
# 见 `开发工具/MD文档生成/机器印记.py` 同一处说明。本层不再各自 `write_text`。
from 支持库.后端.文件系统支持库.文件操作 import 写入文件


def 生成单包摘要(包目录: Path) -> dict[str, object]:
    """读取包声明并委托唯一生成器生成路径有序、与时间无关的摘要数据。"""
    包id, 版本 = _包标识(包目录)
    return 生成完整性摘要(包目录, 包id=包id, 版本=版本)


def _包标识(包目录: Path) -> tuple[str, str]:
    """读 包声明.json 取（包id, 版本）：缺文件/缺字段一律抛错（fail-closed，不猜）。

    `生成单包摘要` 与 `刷新全部摘要` 共用本函数取**同一对标识** —— 两处各读一遍
    就是同一判据的第二条腿（哲学 1.2）。
    """
    声明路径 = 包目录 / "包声明.json"
    if not 声明路径.is_file():
        raise FileNotFoundError(f"缺少包声明: {声明路径}")
    声明 = json.loads(声明路径.read_text(encoding="utf-8"))
    包id = 声明.get("包id")
    版本 = 声明.get("版本")
    if not isinstance(包id, str) or not 包id:
        raise ValueError(f"包声明缺少包id: {声明路径}")
    if not isinstance(版本, str) or not 版本:
        raise ValueError(f"包声明缺少版本: {声明路径}")
    return 包id, 版本


def _包标识宽容(包目录: Path) -> tuple[str, str]:
    """同 `_包标识`，但包声明不可读/缺字段时回落目录名与 `1.0.0`（**不抛错**）。

    取舍与 `开发工具.全量重算摘要.全量重算` 逐字同源（包id → 提供者id → 目录名；
    版本 → `1.0.0`）：两条腿刷同一份文件时不得产生两种字节。
    """
    声明路径 = 包目录 / "包声明.json"
    try:
        声明 = (json.loads(声明路径.read_text(encoding="utf-8"))
               if 声明路径.is_file() else {})
    except (json.JSONDecodeError, OSError, UnicodeDecodeError):
        声明 = {}
    return (str(声明.get("包id") or 声明.get("提供者id") or 包目录.name),
            str(声明.get("版本") or "1.0.0"))


def 刷新登记该文件的摘要(目标文件: Path) -> list[str]:
    """重算**所有登记了该文件**的完整性摘要（目标所在包 + 登记了它的祖先聚合包）。

    为什么必须含祖先（`开发工具/全量重算摘要` 模块 docstring 的同一条教训）：聚合父包的
    `完整性摘要.json` 也登记子包里的文件 —— 实测 `支持库/后端/文件系统支持库` 的清单里有
    `内容检索/包声明.json` 等子包件；全仓 42 份人工类说明书同时被祖先登记。只刷「目标所在包」
    会把祖先摘要留成过期 ⇒ `摘要闭合` 仍红。

    扫描面仍是**定点**的（从目标文件所在目录起逐级向上，不 `rglob` 全仓），故可放在
    「写实体后同轮刷摘要」处按需调用（全仓重算属明令禁止的全量动作）。返回已重写的摘要
    路径（posix）；没有登记该文件的摘要一律不碰（返回空表 = 该文件不在任何摘要清单里）。
    """
    from 开发工具.全量重算摘要 import 完整性摘要文本

    目标 = 目标文件.resolve()
    已重算: list[str] = []
    目录 = 目标.parent
    while True:
        摘要路径 = 目录 / 摘要文件名
        if 摘要路径.is_file():
            try:
                相对 = 目标.relative_to(目录).as_posix()
            except ValueError:
                相对 = ""
            try:
                数据 = json.loads(摘要路径.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError, UnicodeDecodeError):
                数据 = None
            清单 = 数据.get("文件清单") if isinstance(数据, dict) else None
            登记了 = isinstance(清单, list) and any(
                isinstance(条目, dict) and str(条目.get("路径")) == 相对 for 条目 in 清单)
            if 登记了:
                包id, 版本 = _包标识宽容(目录)
                写入文件(str(摘要路径),
                      完整性摘要文本(目录, 包id=包id, 版本=版本)).确保成功()
                已重算.append(摘要路径.as_posix())
        if 目录 == 目录.parent:
            break
        目录 = 目录.parent
    return 已重算


def 查找正式包(系统根目录: Path) -> list[Path]:
    """查找全部拥有包声明的正式支持库与模块（含尚无摘要的新包）。"""
    return 扫描正式包(系统根目录)


def 刷新全部摘要(系统根目录: Path) -> list[Path]:
    """刷新全部正式包摘要并返回写入路径。"""
    写入路径列表: list[Path] = []
    # 文本一律取自**唯一权威**（`开发工具.全量重算摘要.完整性摘要文本`），本层不再自写
    # `json.dumps` 公式（2026-09-24 批O O-5）。
    from 开发工具.全量重算摘要 import 完整性摘要文本

    for 包目录 in 查找正式包(系统根目录):
        摘要路径 = 包目录 / 摘要文件名
        包id, 版本 = _包标识(包目录)
        写入文件(str(摘要路径),
              完整性摘要文本(包目录, 包id=包id, 版本=版本)).确保成功()
        写入路径列表.append(摘要路径)
    if not 写入路径列表:
        raise RuntimeError("没有发现可刷新的正式支持库或模块")
    return 写入路径列表


def 主函数() -> int:
    根目录 = 系统根
    写入路径列表 = 刷新全部摘要(根目录)
    for 路径 in 写入路径列表:
        print(f"已刷新: {路径.relative_to(根目录)}")
    print(f"共刷新 {len(写入路径列表)} 个正式包摘要")
    return 0


if __name__ == "__main__":
    raise SystemExit(主函数())
