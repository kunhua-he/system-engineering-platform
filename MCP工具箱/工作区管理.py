"""为任务和子代理创建隔离 Git worktree，并提供合并与提交辅助。"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Any


def _标识(文本: str) -> str:
    结果 = str(文本).strip()
    if not 结果 or len(结果) > 60 or 结果.startswith("-"):
        raise ValueError("工作区标识无效")
    if not re.fullmatch(r"[A-Za-z0-9_\u4e00-\u9fff-]+", 结果):
        raise ValueError("工作区标识无效")
    return 结果


def _校验分支(分支: str) -> str:
    结果 = str(分支).strip()
    if not 结果 or len(结果) > 128 or 结果.startswith(("-", "/")):
        raise ValueError("分支名无效")
    if ".." in 结果 or 结果.endswith(("/", ".")) or "/." in 结果:
        raise ValueError("分支名无效")
    if not re.fullmatch(r"[A-Za-z0-9_\u4e00-\u9fff-]+(/[A-Za-z0-9_\u4e00-\u9fff-]+)*", 结果):
        raise ValueError("分支名无效")
    return 结果


def _运行(根目录: Path, 命令: list[str]) -> dict[str, Any]:
    结果 = subprocess.run(命令, cwd=根目录, capture_output=True, text=True, check=False)
    标准输出 = 结果.stdout or ""
    标准错误 = 结果.stderr or ""
    return {
        "退出码": 结果.returncode,
        "输出": 标准输出 + ("\n" + 标准错误 if 标准错误 else ""),
        "标准输出": 标准输出,
        "标准错误": 标准错误,
    }


def 创建工作区(项目根目录: Path, 工作区根目录: Path, *, 任务id: str,
            基线: str = "HEAD") -> dict[str, Any]:
    标识 = _标识(任务id)
    目标 = (工作区根目录 / 标识).resolve()
    if 项目根目录.resolve() == 目标 or 目标.exists():
        raise ValueError("工作区已存在或等于主工作区")
    工作区根目录.mkdir(parents=True, exist_ok=True)
    分支 = f"codex/任务-{标识}"
    结果 = _运行(项目根目录, ["git", "worktree", "add", "-b", 分支, str(目标), 基线])
    if 结果["退出码"] != 0:
        return {"成功": False, "错误码": "WORKSPACE_CREATE_FAILED", **结果}
    return {"成功": True, "任务id": 标识, "路径": str(目标), "分支": 分支, "基线": 基线}


def 查询工作区(项目根目录: Path, 工作区根目录: Path) -> dict[str, Any]:
    结果 = _运行(项目根目录, ["git", "worktree", "list", "--porcelain"])
    return {"成功": 结果["退出码"] == 0, "列表": 结果["输出"]}


def 关闭工作区(项目根目录: Path, 路径: str, *, 强制: bool = False) -> dict[str, Any]:
    目标 = Path(路径).resolve()
    if 目标 == 项目根目录.resolve() or not str(目标).startswith(str(项目根目录.parent.resolve())):
        raise ValueError("只能关闭项目旁路工作区")
    if not 强制:
        状态 = _运行(目标, ["git", "-c", "core.quotePath=false", "status", "--porcelain"])
        if 状态["退出码"] == 0:
            未提交修改列表 = [行.strip() for 行 in 状态["标准输出"].splitlines() if 行.strip()]
            if 未提交修改列表:
                return {
                    "成功": False,
                    "错误码": "WORKSPACE_DIRTY",
                    "未提交修改": 未提交修改列表,
                    "路径": str(目标),
                    "消息": "工作区存在未提交修改，拒绝关闭（可强制）",
                }
    命令 = ["git", "worktree", "remove"]
    if 强制:
        命令.append("--force")
    命令.append(str(目标))
    结果 = _运行(项目根目录, 命令)
    return {"成功": 结果["退出码"] == 0, "路径": str(目标), "已强制": 强制, **结果}


def 合并分支(项目根目录: Path, 目标分支: str, 来源分支: str, *,
          提交消息: str = "") -> dict[str, Any]:
    目标分支 = _校验分支(目标分支)
    来源分支 = _校验分支(来源分支)
    操作目录 = Path(项目根目录).resolve()
    切换 = _运行(操作目录, ["git", "switch", 目标分支])
    if 切换["退出码"] != 0:
        return {"成功": False, "错误码": "MERGE_SWITCH_FAILED", "目标分支": 目标分支,
                "来源分支": 来源分支, **切换}
    命令 = ["git", "merge"]
    if 提交消息.strip():
        命令.extend(["-m", 提交消息.strip()])
    else:
        命令.append("--no-edit")
    命令.append(来源分支)
    结果 = _运行(操作目录, 命令)
    冲突列表 = [行.strip() for 行 in 结果["输出"].splitlines() if "CONFLICT" in 行]
    return {
        "成功": 结果["退出码"] == 0,
        "目标分支": 目标分支,
        "来源分支": 来源分支,
        "冲突列表": 冲突列表,
        **结果,
    }


def 工作区提交(项目根目录: Path, 提交消息: str, *, 路径列表: list[str] | None = None) -> dict[str, Any]:
    消息 = str(提交消息).strip()
    if not 消息:
        raise ValueError("提交消息不能为空")
    操作目录 = Path(项目根目录).resolve()
    命令 = ["git", "add"]
    if 路径列表:
        for 路径 in 路径列表:
            if str(路径).startswith("-"):
                raise ValueError("提交路径无效")
        命令.extend(str(路径) for 路径 in 路径列表)
    else:
        命令.append("-A")
    添加结果 = _运行(操作目录, 命令)
    if 添加结果["退出码"] != 0:
        return {"成功": False, "错误码": "COMMIT_ADD_FAILED", **添加结果}
    提交结果 = _运行(操作目录, ["git", "commit", "-m", 消息])
    if 提交结果["退出码"] != 0:
        return {"成功": False, "错误码": "COMMIT_FAILED", **提交结果}
    摘要结果 = _运行(操作目录, ["git", "log", "-1", "--pretty=format:%h %s"])
    return {"成功": True, "提交摘要": 摘要结果["标准输出"].strip(), **提交结果}
