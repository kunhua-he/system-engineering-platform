"""配置适配：项目配置的读写与校验。

项目配置/ 目录存放项目自身配置（JSON）；适配层只做读写与结构校验，
不解释业务配置含义。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class 配置结果:
    """一次配置读写的结果。"""

    成功: bool = False
    配置: dict = field(default_factory=dict)
    问题列表: list[str] = field(default_factory=list)


def 读取配置(项目根目录: Path, 配置名: str = "项目配置.json") -> 配置结果:
    """读取项目配置；文件缺失或 JSON 不合法返回失败。"""
    结果 = 配置结果()
    配置路径 = 项目根目录 / "项目配置" / 配置名
    if not 配置路径.is_file():
        结果.问题列表.append(f"配置不存在: {配置路径}")
        return 结果
    try:
        结果.配置 = json.loads(配置路径.read_text(encoding="utf-8"))
        结果.成功 = True
    except (json.JSONDecodeError, OSError) as 错误:
        结果.问题列表.append(f"配置读取失败: {错误}")
    return 结果


def 写入配置(项目根目录: Path, 配置: dict, 配置名: str = "项目配置.json") -> 配置结果:
    """写入项目配置（原子写盘）；非字典配置拒绝。"""
    结果 = 配置结果()
    if not isinstance(配置, dict):
        结果.问题列表.append("配置必须是字典")
        return 结果
    配置目录 = 项目根目录 / "项目配置"
    配置目录.mkdir(parents=True, exist_ok=True)
    配置路径 = 配置目录 / 配置名
    临时路径 = 配置路径.with_suffix(".tmp")
    try:
        临时路径.write_text(json.dumps(配置, ensure_ascii=False, indent=2), encoding="utf-8")
        临时路径.replace(配置路径)
        结果.成功 = True
        结果.配置 = 配置
    except OSError as 错误:
        结果.问题列表.append(f"配置写入失败: {错误}")
    return 结果
