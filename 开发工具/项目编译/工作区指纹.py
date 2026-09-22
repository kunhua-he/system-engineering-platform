"""唯一工作区字节指纹：供编译、HTML验证与发布门禁复用。

字段语义冻结为：HEAD + 暂存区差异字节 + 未暂存正式文件字节 +
未跟踪正式文件字节。排除项固定列出，不接受调用方临时扩展，避免不同入口
各算一套含义不同的“工作区摘要”。
"""
from __future__ import annotations
from 公共契约.基础类型.逻辑类型 import 真, 假

import fnmatch
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
    # `.tmp`：平台自己的**仓库内临时根**。`系统核心支持库.进程管理.执行命令` 以仓库根为
    # `工作目录` 时把临时文件落 `<工作目录>/.tmp`（`进程管理.py` 的
    # `临时目录 = _Path(工作目录) / ".tmp"`），现场残留全是门禁/测试的临时树
    # （`反向破坏_*` / `注册口径漂移测试_*` / `门禁_备份恢复_*` / `破坏任务_*` / `破坏路由_*` …）。
    # `.gitignore` 用 `*.tmp` 挡它（故 `git status` 看不见），但指纹的未跟踪腿**不用**
    # `--exclude-standard`（见 `计算工作区字节指纹` 内注释）⇒ 只认本表。
    # 实测 2026-09-23：不排除时 298 个临时树文件被算成「未跟踪正式文件」，
    # 工作区恒判「含未提交变更」、字节指纹随本机残留而变（假红）。
    ".tmp",
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
# 固定排除文件：按**基名**判定，支持 `fnmatch` 通配（无通配字符时即全等，语义不变）。
# 带通配的这批是 `.gitignore` 的**文件级**规则镜像 —— 此前只列目录，不认文件级规则，
# 于是 `.gitignore` 挡住、git status 看不见的本地残留（`*.db` / `*-wal` / `*.bak_*` /
# `zcode.json` 等）仍被 `git ls-files --others` 报出并被算成正式文件，导致工作区恒判
# 「含未提交变更」、字节指纹随本机残留而变。此处逐条镜像 `.gitignore`，仍是显式可审计表。
固定排除文件 = (
    ".DS_Store",
    "*.db",
    "*.db-wal",
    "*.db-shm",
    "*.sqlite3",
    "*.sqlite3-wal",
    "*.sqlite3-shm",
    "*-wal",
    "*-shm",
    "*.bak",
    "*.bak_*",
    "*.bak-*",
    "*.orig",
    "*~",
    ".env",
    "*.log",
    "*.tmp",
    ".测试值.*.tmp",
    "zcode.json",
    # `.zcodeignore`：**ZCode 客户端**的本地产物（文件头两段自带说明 ——
    # 「↑ 以上同步自 .gitignore」与「ZCode 默认排除规则」，由客户端生成/同步）。
    # 它**不在** `.gitignore` 里（`git status` 如实报 `?? .zcodeignore`），而指纹的未跟踪腿
    # **不用** `--exclude-standard`（.gitignore 不是指纹语义的一部分）⇒ 靠 `.gitignore`
    # 或客户端忽略规则都保不住工作区，必须进本表。
    # 实测 2026-09-23：不进本表时它被算成 1 个「未跟踪正式文件」，工作区恒判「含未提交变更」。
    ".zcodeignore",
)


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
    if not 规范:
        return 假
    基名 = Path(规范).name
    # `fnmatchcase`（区分大小写，与 git 的忽略口径一致）：无通配字符的模式即全等判定。
    if any(fnmatch.fnmatchcase(基名, 模式) for 模式 in 固定排除文件):
        return 假
    for 排除 in 固定排除目录:
        if "/" in 排除:
            if 规范 == 排除 or 规范.startswith(排除 + "/"):
                return 假
        elif 排除 in 规范.split("/"):
            return 假
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
        "工作区字节指纹": 哈希.hexdigest(),
        "工作区状态": "含未提交变更" if 有变更 else "干净",
        "语义": 指纹语义,
        "排除目录": list(固定排除目录),
        "暂存差异字节数": len(暂存差异),
        "未暂存正式文件数": 未暂存数,
        "未跟踪正式文件数": 未跟踪数,
    }


__all__ = ["计算工作区字节指纹", "指纹语义", "固定排除目录", "固定排除文件"]
