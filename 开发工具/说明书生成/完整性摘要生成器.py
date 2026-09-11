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

from 开发工具.组件规范.完整性摘要 import (
    生成完整性摘要,
    扫描正式包,
    摘要文件名,
)


def 生成单包摘要(包目录: Path) -> dict[str, object]:
    """读取包声明并委托唯一生成器生成路径有序、与时间无关的摘要数据。"""
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
    return 生成完整性摘要(包目录, 包id=包id, 版本=版本)


def 查找正式包(系统根目录: Path) -> list[Path]:
    """查找全部拥有包声明的正式支持库与模块（含尚无摘要的新包）。"""
    return 扫描正式包(系统根目录)


def 刷新全部摘要(系统根目录: Path) -> list[Path]:
    """刷新全部正式包摘要并返回写入路径。"""
    写入路径列表: list[Path] = []
    for 包目录 in 查找正式包(系统根目录):
        摘要路径 = 包目录 / 摘要文件名
        摘要文本 = json.dumps(生成单包摘要(包目录), ensure_ascii=False, indent=2) + "\n"
        摘要路径.write_text(摘要文本, encoding="utf-8")
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
