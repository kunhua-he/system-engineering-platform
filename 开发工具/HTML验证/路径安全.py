"""场景和动态路径安全边界。"""
from __future__ import annotations
import re
from pathlib import Path
from typing import Any


def _安全合并路径(根: Path, 相对: str, 名称: str) -> Path:
    if not isinstance(相对, str) or not 相对 or Path(相对).is_absolute() or re.match(r"^[A-Za-z]:[\\/]", 相对):
        raise ValueError(f"{名称}路径不合法: {相对!r}")
    路径 = (根 / 相对).resolve()
    try:
        路径.relative_to(根.resolve())
    except ValueError as 错误:
        raise ValueError(f"{名称}越出包目录或受管目录: {相对}") from 错误
    return 路径

def _校验动态声明(值: Any, 场景id: str, 已出现步骤: set[str]) -> None:
    if isinstance(值, list):
        for 项 in 值:
            _校验动态声明(项, 场景id, 已出现步骤)
        return
    if not isinstance(值, dict):
        if isinstance(值, str) and (Path(值).is_absolute() or ".." in Path(值).parts
                                  or re.match(r"^[A-Za-z]:[\\/]", 值)):
            raise ValueError(f"场景 {场景id} 禁止静态绝对路径或路径逃逸")
        return
    if "$动态" not in 值:
        for 项 in 值.values():
            _校验动态声明(项, 场景id, 已出现步骤)
        return
    类型 = 值.get("$动态")
    允许字段 = {
        "制品根": {"$动态", "相对路径"},
        "受管临时目录": {"$动态", "相对路径"},
        "受管临时路径": {"$动态", "相对路径"},
        "夹具文件复制": {"$动态", "来源", "目标"},
        "步骤返回": {"$动态", "步骤id", "JSON路径"},
    }
    if 类型 not in 允许字段 or set(值) != 允许字段[类型]:
        raise ValueError(f"场景 {场景id} 动态值声明不合法: {类型!r}")
    if 类型 == "步骤返回":
        if 值.get("步骤id") not in 已出现步骤 or not isinstance(值.get("JSON路径"), str):
            raise ValueError(f"场景 {场景id} 动态引用缺失或不是前序步骤: {值.get('步骤id')}")
    else:
        for 字段 in 允许字段[类型] - {"$动态"}:
            if not isinstance(值.get(字段), str) or not 值[字段]:
                raise ValueError(f"场景 {场景id} 动态路径字段不合法: {字段}")
