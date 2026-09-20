"""文档生成 · 类型登记：从「文档类型判据」数据文件读全部文档类型。

格式是**数据**，不是代码：`开发文档/规范/文档类型判据.json` 是《Markdown 文档体例规范》
里「每类文档一个格式」的数据侧投影。本模块只读它、不另写一份格式判据（哲学 1.2）。
新增一类文档 = 改数据文件一处，不改代码、不加文件。
"""

from __future__ import annotations

import json
from pathlib import Path

判据文件相对 = Path("开发文档/规范/文档类型判据.json")


class 类型定义缺失(Exception):
    """判据文件不可读或结构不符：严格报错，不假装没有类型。"""


def 读判据(项目根: Path) -> dict:
    路径 = 项目根 / 判据文件相对
    if not 路径.is_file():
        raise 类型定义缺失(f"文档类型判据文件不存在：{判据文件相对.as_posix()}")
    try:
        数据 = json.loads(路径.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as 错:
        raise 类型定义缺失(f"文档类型判据文件不可读或非法 JSON：{错}") from 错
    if not isinstance(数据, dict) or not isinstance(数据.get("文档类型"), list):
        raise 类型定义缺失("文档类型判据文件结构不符：缺少 文档类型 数组")
    return 数据


def 取类型表(项目根: Path) -> list[dict]:
    return 读判据(项目根)["文档类型"]


def 按名取(项目根: Path, 类型名: str) -> dict:
    表 = 取类型表(项目根)
    命中 = [x for x in 表 if str(x.get("类型", "")) == 类型名]
    if not 命中:
        raise 类型定义缺失(
            f"未知文档类型：{类型名}（已登记：{' / '.join(str(x.get('类型')) for x in 表)}）")
    return 命中[0]


def 按序号取(项目根: Path, 序号: int) -> dict:
    表 = 取类型表(项目根)
    命中 = [x for x in 表 if int(x.get("序号", -1)) == int(序号)]
    if not 命中:
        raise 类型定义缺失(
            f"未知文档类型序号：{序号}（已登记："
            + " / ".join(f"{x.get('序号')}={x.get('类型')}" for x in 表) + "）")
    return 命中[0]


def 命中类型(项目根: Path, 相对路径: str) -> dict | None:
    """按文件路径反查它属于哪类文档（顺序即优先级，越靠前越先匹配）。"""
    import fnmatch
    for 类型 in 取类型表(项目根):
        for 模式 in 类型.get("路径判据", []):
            模式文 = str(模式)
            if fnmatch.fnmatch(相对路径, 模式文):
                return 类型
            # 目录级模式 `a/b/*.md` 也匹配更深层
            if 模式文.endswith("/*.md") and 相对路径.startswith(模式文[:-len("*.md")]) \
                    and 相对路径.endswith(".md"):
                return 类型
    return None


def 枚举文件(项目根: Path, 类型: dict) -> list[Path]:
    """按类型定义枚举该类型下的现存文件（相对路径升序）。"""
    import fnmatch
    命中: list[Path] = []
    for 路径 in 项目根.rglob("*.md"):
        相对 = 路径.relative_to(项目根).as_posix()
        if any(相对.startswith(str(x)) for x in
               (".git/", "工程缓存/", "开发文档/参考资料/", "开发文档/归档/", "__pycache__/")):
            continue
        for 模式 in 类型.get("路径判据", []):
            模式文 = str(模式)
            if fnmatch.fnmatch(相对, 模式文) or (
                    模式文.endswith("/*.md") and 相对.startswith(模式文[:-len("*.md")])
                    and 相对.endswith(".md")):
                命中.append(路径)
                break
    return sorted(命中, key=lambda p: p.as_posix())
