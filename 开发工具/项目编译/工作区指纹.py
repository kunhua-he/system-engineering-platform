"""唯一工作区字节指纹：供编译、HTML验证与发布门禁复用。

字段语义冻结为：HEAD + 暂存区差异字节 + 未暂存正式文件字节 +
未跟踪正式文件字节。排除项固定列出，不接受调用方临时扩展，避免不同入口
各算一套含义不同的“工作区摘要”。
"""
from __future__ import annotations

import hashlib
import os
import subprocess
from pathlib import Path
from typing import Any, Iterable

指纹语义 = "HEAD+暂存区差异字节+未暂存正式文件字节+未跟踪正式文件字节"
固定排除目录 = (
    ".git",
    "工程缓存",
    "开发文档/项目证据",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
    ".codegraph",
    ".hermes",
    ".venv",
    "venv",
    "node_modules",
)
固定排除文件 = (".DS_Store",)


def _执行(仓库根: Path, 参数: list[str]) -> bytes:
    try:
        结果 = subprocess.run(
            ["git", *参数], cwd=仓库根, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, timeout=30, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as 错误:
        raise ValueError(f"无法计算工作区字节指纹: {错误}") from 错误
    if 结果.returncode != 0:
        说明 = 结果.stderr.decode("utf-8", errors="replace").strip()
        raise ValueError(f"无法计算工作区字节指纹: git {' '.join(参数)}: {说明}")
    return 结果.stdout


def _路径表(原始: bytes) -> list[str]:
    return sorted({项.decode("utf-8", errors="surrogateescape") for 项 in 原始.split(b"\0") if 项})


def _是正式路径(相对路径: str) -> bool:
    规范 = 相对路径.replace("\\", "/").strip("/")
    if not 规范 or Path(规范).name in 固定排除文件:
        return False
    for 排除 in 固定排除目录:
        if "/" in 排除:
            if 规范 == 排除 or 规范.startswith(排除 + "/"):
                return False
        elif 排除 in 规范.split("/"):
            return False
    return not 规范.endswith((".pyc", ".pyo"))


def _加入正式文件字节(哈希: "hashlib._Hash", 仓库根: Path, 分类: bytes, 路径表: Iterable[str]) -> int:
    数量 = 0
    for 相对路径 in sorted(set(路径表)):
        if not _是正式路径(相对路径):
            continue
        文件 = 仓库根 / 相对路径
        路径字节 = 相对路径.encode("utf-8", errors="surrogateescape")
        if 文件.is_symlink():
            内容 = os.readlink(文件).encode("utf-8", errors="surrogateescape")
            类型 = b"symlink"
        elif 文件.is_file():
            内容 = 文件.read_bytes()
            类型 = b"file"
        else:
            内容 = b""
            类型 = b"deleted"
        哈希.update(分类 + b"\0" + 类型 + b"\0")
        哈希.update(len(路径字节).to_bytes(8, "big") + 路径字节)
        哈希.update(len(内容).to_bytes(8, "big") + 内容)
        数量 += 1
    return 数量


def 计算工作区字节指纹(仓库根: Path) -> dict[str, Any]:
    """按冻结语义计算当前 Git 工作区摘要；任何 Git 读取失败均阻断。"""
    根 = Path(仓库根).resolve()
    提交字节 = _执行(根, ["rev-parse", "HEAD"]).strip()
    if not 提交字节:
        raise ValueError("无法计算工作区字节指纹: HEAD 为空")

    暂存路径 = [路径 for 路径 in _路径表(_执行(根, ["diff", "--cached", "--name-only", "-z", "--"])) if _是正式路径(路径)]
    暂存差异 = bytearray()
    for 路径 in 暂存路径:
        暂存差异.extend(_执行(根, ["diff", "--cached", "--binary", "--no-ext-diff", "--no-color", "--", 路径]))

    未暂存路径 = _路径表(_执行(根, ["diff", "--name-only", "-z", "--"]))
    # 不使用 --exclude-standard：.gitignore 不是指纹语义的一部分；所有排除项
    # 必须只来自上方固定、显式、可审计的目录/文件表。
    未跟踪路径 = _路径表(_执行(根, ["ls-files", "--others", "-z", "--"]))

    哈希 = hashlib.sha256()
    哈希.update(b"HEAD\0" + len(提交字节).to_bytes(8, "big") + 提交字节)
    哈希.update(b"STAGED\0" + len(暂存差异).to_bytes(8, "big") + bytes(暂存差异))
    未暂存数 = _加入正式文件字节(哈希, 根, b"UNSTAGED", 未暂存路径)
    未跟踪数 = _加入正式文件字节(哈希, 根, b"UNTRACKED", 未跟踪路径)
    有变更 = bool(暂存差异 or 未暂存数 or 未跟踪数)
    return {
        "提交": 提交字节.decode("ascii", errors="replace"),
        "工作区摘要": 哈希.hexdigest(),
        "工作区状态": "含未提交变更" if 有变更 else "干净",
        "语义": 指纹语义,
        "排除目录": list(固定排除目录),
        "暂存差异字节数": len(暂存差异),
        "未暂存正式文件数": 未暂存数,
        "未跟踪正式文件数": 未跟踪数,
    }


__all__ = ["计算工作区字节指纹", "指纹语义", "固定排除目录", "固定排除文件"]
