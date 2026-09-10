"""缓存目录准备、任务指纹与项目状态读写（断点续跑唯一依据）。

约定：任一阶段产物存在且任务指纹一致 → 该阶段可跳过；指纹不一致只重算受影响的下游。
本文件只负责路径、指纹与状态；不含任何转写/裁决逻辑。
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path

指纹文件名 = "任务指纹.json"
状态文件名 = "项目状态.json"
摘要分块字节 = 4 * 1024 * 1024


def 现在文本() -> str:
    """当前本地时间，ISO 格式到秒。"""
    return datetime.now().isoformat(timespec="seconds")


def 准备缓存(缓存目录: str) -> dict[str, Path]:
    """创建缓存目录骨架并返回命名路径表（键为阶段名）。"""
    根 = Path(缓存目录).expanduser().resolve()
    路径表 = {
        "根": 根,
        "元数据": 根 / "00_元数据",
        "音频": 根 / "01_音频",
        "分片": 根 / "02_分片",
        "分片转写": 根 / "03_分片转写",
        "复核": 根 / "06_复核",
        "证据包": 根 / "07_证据包",
        "裁决": 根 / "08_裁决",
        "合成": 根 / "09_合成",
        "质检": 根 / "10_质检",
    }
    for 名称, 路径 in 路径表.items():
        if 名称 == "根":
            continue
        路径.mkdir(parents=True, exist_ok=True)
    路径表["疑难清单"] = 根 / "04_疑难清单.json"
    路径表["复核区间"] = 根 / "05_复核区间.json"
    路径表["指纹"] = 路径表["元数据"] / 指纹文件名
    路径表["状态"] = 路径表["元数据"] / 状态文件名
    return 路径表


def 计算文件摘要(文件路径: str) -> str:
    """分块计算文件 sha256；失败返回空串（调用方按“未知摘要”处理）。"""
    摘要 = hashlib.sha256()
    try:
        with open(文件路径, "rb") as 句柄:
            while True:
                块 = 句柄.read(摘要分块字节)
                if not 块:
                    break
                摘要.update(块)
    except OSError:
        return ""
    return 摘要.hexdigest()


def 读JSON(路径: Path) -> dict | None:
    """读 JSON；不存在或损坏返回 None（不抛异常）。"""
    try:
        return json.loads(Path(路径).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def 写JSON(路径: Path, 数据: dict) -> bool:
    """写 JSON（utf-8、缩进 2）；成功返回 True。"""
    目标 = Path(路径)
    try:
        目标.parent.mkdir(parents=True, exist_ok=True)
        目标.write_text(json.dumps(数据, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except (OSError, TypeError):
        return False
    return True


def 读指纹(缓存: dict) -> dict | None:
    """读任务指纹；不存在返回 None。"""
    return 读JSON(缓存["指纹"])


def 写指纹(缓存: dict, 指纹: dict) -> bool:
    """写任务指纹。"""
    return 写JSON(缓存["指纹"], 指纹)


def 指纹一致(旧指纹: dict | None, 新指纹: dict) -> bool:
    """比较指纹关键字段：源文件摘要、大小、模式、分片秒数、附加术语、模型名。"""
    if not isinstance(旧指纹, dict):
        return False
    关键字段 = ("源文件摘要", "源文件大小字节", "模式", "分片秒数", "附加术语", "模型名")
    return all(旧指纹.get(字段) == 新指纹.get(字段) for 字段 in 关键字段)


def 写状态(缓存: dict, 状态: dict) -> bool:
    """写项目状态（追加更新时间）。"""
    内容 = dict(状态)
    内容["更新时间"] = 现在文本()
    return 写JSON(缓存["状态"], 内容)


def 读状态(缓存: dict) -> dict | None:
    """读项目状态；不存在返回 None。"""
    return 读JSON(缓存["状态"])


def 产物存在(缓存: dict, 键: str, 子项: str | None = None) -> bool:
    """判断某阶段产物是否已存在（子项为空时判目录非空）。"""
    路径 = 缓存.get(键)
    if 路径 is None:
        return False
    if 子项:
        return (Path(路径) / 子项).is_file()
    if Path(路径).is_file():
        return True
    try:
        return any(Path(路径).iterdir())
    except OSError:
        return False
