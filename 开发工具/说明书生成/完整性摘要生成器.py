"""为正式支持库与模块生成可重复的逐文件完整性摘要。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


摘要文件名 = "完整性摘要.json"
排除目录名 = {"__pycache__", "工程缓存"}
排除文件后缀 = {".pyc", ".pyo", ".log", ".tmp"}
排除文件名 = {摘要文件名, ".DS_Store"}


def 是否应当收录(文件: Path, 包目录: Path) -> bool:
    """判断文件是否属于正式、可发布的包内容。"""
    相对路径 = 文件.relative_to(包目录)
    if not 文件.is_file() or 文件.name in 排除文件名:
        return False
    if any(部分 in 排除目录名 for 部分 in 相对路径.parts):
        return False
    return 文件.suffix not in 排除文件后缀


def 计算文件摘要(文件: Path) -> str:
    """以分块方式计算文件的完整 SHA-256。"""
    摘要器 = hashlib.sha256()
    with 文件.open("rb") as 文件流:
        while 数据块 := 文件流.read(1024 * 1024):
            摘要器.update(数据块)
    return 摘要器.hexdigest()


def 生成单包摘要(包目录: Path) -> dict[str, object]:
    """读取包声明并生成路径有序、与时间无关的摘要数据。"""
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

    文件列表 = sorted(
        (文件 for 文件 in 包目录.rglob("*") if 是否应当收录(文件, 包目录)),
        key=lambda 文件: 文件.relative_to(包目录).as_posix(),
    )
    if not 文件列表:
        raise ValueError(f"包内没有可纳入摘要的正式文件: {包目录}")
    return {
        "包id": 包id,
        "版本": 版本,
        "摘要算法": "sha256",
        "文件清单": [
            {
                "路径": 文件.relative_to(包目录).as_posix(),
                "sha256": 计算文件摘要(文件),
            }
            for 文件 in 文件列表
        ],
    }


def 查找正式包(系统根: Path) -> list[Path]:
    """查找全部拥有包声明的正式支持库与模块（含尚无摘要的新包）。"""
    包目录集合: set[Path] = set()
    for 根目录名 in ("支持库", "模块库"):
        根目录 = 系统根 / 根目录名
        if not 根目录.is_dir():
            continue
        for 声明路径 in 根目录.rglob("包声明.json"):
            包目录 = 声明路径.parent
            包目录集合.add(包目录)
    return sorted(包目录集合, key=lambda 路径: 路径.relative_to(系统根).as_posix())


def 刷新全部摘要(系统根: Path) -> list[Path]:
    """刷新全部正式包摘要并返回写入路径。"""
    写入路径列表: list[Path] = []
    for 包目录 in 查找正式包(系统根):
        摘要路径 = 包目录 / 摘要文件名
        摘要文本 = json.dumps(生成单包摘要(包目录), ensure_ascii=False, indent=2) + "\n"
        摘要路径.write_text(摘要文本, encoding="utf-8")
        写入路径列表.append(摘要路径)
    if not 写入路径列表:
        raise RuntimeError("没有发现可刷新的正式支持库或模块")
    return 写入路径列表


def 主函数() -> int:
    系统根 = Path(__file__).resolve().parents[1]
    for _祖先 in 系统根.parents:
        if (_祖先 / "支持库").is_dir() and (_祖先 / "模块库").is_dir():
            系统根 = _祖先
            break
    写入路径列表 = 刷新全部摘要(系统根)
    for 路径 in 写入路径列表:
        print(f"已刷新: {路径.relative_to(系统根)}")
    print(f"共刷新 {len(写入路径列表)} 个正式包摘要")
    return 0


if __name__ == "__main__":
    raise SystemExit(主函数())
