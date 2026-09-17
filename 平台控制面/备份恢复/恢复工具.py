"""工作包10 恢复编排器专用工具：文件收集、摘要计算、目录清空与复制核对。"""
from __future__ import annotations

import hashlib
import shutil
from pathlib import Path
from 公共契约.基础类型.逻辑类型 import 真, 假


def 计算摘要(文件: Path) -> str:
    """真实读取磁盘字节重算 sha256。"""
    return hashlib.sha256(文件.read_bytes()).hexdigest()


def 内容寻址名(文件名: str) -> bool:
    """去扩展名后为 64 位小写十六进制，即视为内容寻址名。"""
    return len(文件名) == 64 and all(字符 in "0123456789abcdef" for 字符 in 文件名)


def 收集文件(目录: Path, 排除缓存: bool = 假) -> dict[str, str]:
    """返回目录内全部文件 {相对路径: sha256}；可选排除缓存目录。"""
    结果: dict[str, str] = {}
    for 文件 in 目录.rglob("*"):
        if 文件.is_file() and not (排除缓存 and "__pycache__" in 文件.parts):
            结果[文件.relative_to(目录).as_posix()] = 计算摘要(文件)
    return 结果


def 清空目录(目录: Path) -> None:
    """清空并重建目标目录；重复恢复先清后建，不残留中间状态。"""
    if 目录.exists():
        for 项 in 目录.iterdir():
            shutil.rmtree(项) if 项.is_dir() else 项.unlink()
    else:
        目录.mkdir(parents=True)


def 复制核对(来源: Path, 目标: Path) -> bool:
    """真实复制文件并核对源与目标摘要一致。"""
    目标.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(来源, 目标)
    return 计算摘要(来源) == 计算摘要(目标)
