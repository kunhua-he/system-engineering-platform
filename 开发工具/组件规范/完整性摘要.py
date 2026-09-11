"""完整性摘要唯一生成器与校验器：文件清单 sha256 格式为唯一权威。

正式包 完整性摘要.json 只允许一种格式：
{
  "包id": ...,
  "版本": ...,
  "摘要算法": "sha256",
  "文件清单": [{"路径": ..., "sha256": ...}, ...]
}
生成时排除 完整性摘要.json 自身与 __pycache__ 缓存，保证可重复生成。
旧"能力数/能力清单"格式或缺失 文件清单 的输入一律校验失败（拒绝漂移）。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Iterable

摘要文件名 = "完整性摘要.json"
排除目录名 = {"__pycache__", "工程缓存"}
排除文件后缀 = {".pyc", ".pyo"}
排除文件名 = {摘要文件名, ".DS_Store"}


def 是否应当收录(文件: Path, 包目录: Path) -> bool:
    """文件是否属于正式包内容（排除摘要自身与缓存）。"""
    if not 文件.is_file() or 文件.name in 排除文件名:
        return False
    相对路径 = 文件.relative_to(包目录)
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


def 生成完整性摘要(包目录: Path, *, 包id: str, 版本: str) -> dict[str, Any]:
    """生成文件清单格式完整性摘要（路径有序、与时间无关）。"""
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


def 校验完整性摘要(包目录: Path) -> tuple[bool, list[str]]:
    """校验包目录 完整性摘要.json 与真实文件闭合。

    拒绝：缺摘要/非 JSON/缺 文件清单 或为空（旧"能力数"格式）/
    摘要算法不合法/包id或版本与声明不一致/路径越界/清单文件不存在/
    文件摘要不一致/清单不闭合（未登记或多余）。
    """
    问题列表: list[str] = []
    摘要路径 = 包目录 / 摘要文件名
    if not 摘要路径.is_file():
        return False, ["缺少 完整性摘要.json"]
    try:
        摘要 = json.loads(摘要路径.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as 错误:
        return False, [f"摘要不可读: {错误}"]
    文件清单 = 摘要.get("文件清单")
    if not isinstance(文件清单, list) or not 文件清单:
        return False, ["文件清单缺失或为空（旧'能力数'格式或空清单；文件清单为唯一权威格式）"]
    if 摘要.get("摘要算法") not in (None, "sha256"):
        return False, [f"摘要算法不合法: {摘要.get('摘要算法')}"]
    声明路径 = 包目录 / "包声明.json"
    if 声明路径.is_file():
        try:
            声明 = json.loads(声明路径.read_text(encoding="utf-8"))
            if 摘要.get("包id") != 声明.get("包id") or 摘要.get("版本") != 声明.get("版本"):
                return False, ["摘要中的包id或版本与包声明不一致"]
        except (json.JSONDecodeError, OSError):
            return False, ["包声明.json 不可读"]
    声明路径集合: set[str] = set()
    包目录解析 = 包目录.resolve()
    for 条目 in 文件清单:
        if not isinstance(条目, dict):
            return False, ["文件清单条目必须包含路径和sha256"]
        相对路径 = str(条目.get("路径", ""))
        期望摘要 = str(条目.get("sha256", "")).lower()
        if not 相对路径 or len(期望摘要) < 16:
            return False, [f"文件清单条目不完整: {相对路径 or '缺少路径'}"]
        文件 = (包目录 / 相对路径).resolve()
        try:
            文件.relative_to(包目录解析)
        except ValueError:
            return False, [f"文件路径越界: {相对路径}"]
        if not 文件.is_file():
            return False, [f"清单文件不存在: {相对路径}"]
        实际摘要 = hashlib.sha256(文件.read_bytes()).hexdigest()
        if not 实际摘要.startswith(期望摘要):
            return False, [f"文件摘要不一致: {相对路径}"]
        声明路径集合.add(Path(相对路径).as_posix())
    实际路径集合 = {
        文件.relative_to(包目录).as_posix()
        for 文件 in 包目录.rglob("*")
        if 文件.is_file() and 是否应当收录(文件, 包目录)
    }
    缺少清单 = sorted(实际路径集合 - 声明路径集合)
    多余清单 = sorted(声明路径集合 - 实际路径集合)
    if 缺少清单 or 多余清单:
        return False, [f"清单不闭合: 未登记{缺少清单[:3]} 多余{多余清单[:3]}"]
    return True, []


def 扫描正式包(系统根: Path) -> list[Path]:
    """查找全部拥有包声明的正式支持库与模块包目录。"""
    包目录集合: set[Path] = set()
    for 根目录名 in ("支持库", "模块库"):
        根目录 = 系统根 / 根目录名
        if not 根目录.is_dir():
            continue
        for 声明路径 in 根目录.rglob("包声明.json"):
            包目录集合.add(声明路径.parent)
    return sorted(包目录集合, key=lambda 路径: 路径.relative_to(系统根).as_posix())


def 迁移旧格式摘要(系统根: Path, 排除路径: Iterable[Path] = ()) -> list[Path]:
    """扫描全仓正式包，旧格式（缺/空 文件清单）或内容漂移用唯一生成器重算。

    排除路径内的包不参与重算，供并发写盘期间避让。
    返回重算写入的摘要路径列表。
    """
    排除集 = {Path(路径).resolve() for 路径 in 排除路径}
    重算列表: list[Path] = []
    for 包目录 in 扫描正式包(系统根):
        if 包目录.resolve() in 排除集:
            continue
        通过, _ = 校验完整性摘要(包目录)
        if 通过:
            continue
        声明路径 = 包目录 / "包声明.json"
        try:
            声明 = json.loads(声明路径.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            声明 = {}
        摘要 = 生成完整性摘要(
            包目录,
            包id=声明.get("包id", 包目录.name),
            版本=声明.get("版本", "1.0.0"),
        )
        摘要路径 = 包目录 / 摘要文件名
        摘要路径.write_text(
            json.dumps(摘要, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        重算列表.append(摘要路径)
    return 重算列表
