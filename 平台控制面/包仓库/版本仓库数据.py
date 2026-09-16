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
    """对目录内全部文件做内容寻址摘要（sha256 前 16 位）。

    口径与 `平台控制面/包仓库/平台客户端制品.py::计算目录摘要16` 对齐（同一算法）：

    - **相对路径 + 文件字节**一起进摘要。只混文件名时，两棵内容相同但**布局不同**
      的树会得到同一个摘要 —— 包可以被另一份换了目录结构的包顶替身份；
    - `__pycache__` 按**路径段**排除（`"__pycache__" in 文件.parts`）。它只可能是
      目录名，原先写 `文件.name != "__pycache__"` 是拿**文件名**比**目录名**、
      **永假**：包一旦被 import 生成 `.pyc`，目录摘要就变 → 对**未被篡改**的安装
      报「完整性摘要不一致」。本机遗留证据（2026-09-16）：同一个包
      `平台控制面.包仓库@1.0.0` 两次安装记录的摘要为
      `8f623935655b9ee7` / `f34c70247e70b046`，内容未变而摘要漂移，即此因。
    """
    哈希器 = hashlib.sha256()
    for 文件 in sorted(Path(目录).rglob("*")):
        if 文件.is_dir() or "__pycache__" in 文件.parts:
            continue
        哈希器.update(文件.relative_to(目录).as_posix().encode("utf-8"))
        哈希器.update(文件.read_bytes())
    return 哈希器.hexdigest()[:16]
