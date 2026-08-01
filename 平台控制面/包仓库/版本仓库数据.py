"""版本仓库数据：安装记录与目录摘要（版本目录仓库共用数据定义）。"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

仓库结构表 = ["包声明.json", "能力契约", "实现", "配置声明", "权限声明"]


@dataclass
class 安装记录:
    """一条安装记录。"""

    记录id: str
    包id: str
    版本: str
    契约版本: str
    完整性摘要: str
    安装路径: str
    时间: str
    来源: str = "本地目录"

    def 转字典(self) -> dict[str, Any]:
        return {
            "记录id": self.记录id, "包id": self.包id, "版本": self.版本,
            "契约版本": self.契约版本, "完整性摘要": self.完整性摘要,
            "安装路径": self.安装路径, "时间": self.时间, "来源": self.来源,
        }


def 计算目录摘要(目录: Path) -> str:
    """对目录内全部文件做内容寻址摘要（sha256 前 16 位）。"""
    哈希器 = hashlib.sha256()
    for 文件 in sorted(目录.rglob("*")):
        if 文件.is_file() and 文件.name != "__pycache__":
            哈希器.update(文件.name.encode("utf-8"))
            哈希器.update(文件.read_bytes())
    return 哈希器.hexdigest()[:16]
