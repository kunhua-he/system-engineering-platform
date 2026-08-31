"""为任务和子代理创建隔离 Git worktree，并提供合并与提交辅助。

关闭工作区前自动联动清理：释放 ps 匹配工作区路径的残留子进程、
调用 测试资源.清理资源 清理登记资源（未标记保留）；清理失败必须写结构化证据到
工程缓存/清理失败证据/{work_id}.json 并返回 清理失败（非零语义）。
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import time
from pathlib import Path
from typing import Any

from .测试资源 import 清理资源, 终止进程防残留, 写清理失败证据


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


def 关闭工作区(项目根目录: Path, 路径: str, *, 强制: bool = False,
              work_id: str = "") -> dict[str, Any]:
    目标 = Path(路径).resolve()
    项目根文本 = f"{str(项目根目录.resolve())}{os.sep}"
    if 目标 == 项目根目录.resolve() or not str(目标).startswith(项目根文本):
        raise ValueError("只能关闭项目内工作区（工程缓存/任务工作区 下）")
    if not 强制:
        状态 = _运行(目标, ["git", "-c", "core.quotePath=false", "status", "--porcelain"])
        if 状态["退出码"] == 0:
            已登记路径 = _已登记路径表(项目根目录, 目标, work_id)
            未提交修改列表 = [
                行.strip() for 行 in 状态["标准输出"].splitlines()
                if 行.strip() and not _命中已登记路径(目标, 行, 已登记路径)
            ]
            if 未提交修改列表:
                return {
                    "成功": False,
                    "错误码": "WORKSPACE_DIRTY",
                    "未提交修改": 未提交修改列表,
                    "路径": str(目标),
                    "消息": "工作区存在未提交修改，拒绝关闭（可强制）",
                }
    # 关闭前资源联动清理：残留子进程释放 + 登记资源清理；失败必须留证据并拒绝关闭
    清理结果 = _清理关闭前资源(项目根目录, 目标, work_id)
    if not 清理结果["成功"]:
        return {
            "成功": False,
            "错误码": "WORKSPACE_CLEANUP_FAILED",
            "路径": str(目标),
            "消息": "工作区资源清理失败，拒绝关闭",
            "失败表": 清理结果["失败表"],
            "证据路径": 清理结果["证据路径"],
            "清理数": 清理结果["清理数"],
            "保留数": 清理结果["保留数"],
        }
    命令 = ["git", "worktree", "remove"]
    if 强制:
        命令.append("--force")
    命令.append(str(目标))
    结果 = _运行(项目根目录, 命令)
    if 结果["退出码"] != 0 and int(清理结果["清理数"]) > 0:
        # 清理删除工作区内登记文件导致目录变脏：资源已清理，强制移除
        结果 = _运行(项目根目录, ["git", "worktree", "remove", "--force", str(目标)])
    return {
        "成功": 结果["退出码"] == 0, "路径": str(目标), "已强制": 强制,
        "清理数": 清理结果["清理数"], "保留数": 清理结果["保留数"],
        "失败表": 清理结果["失败表"], "证据路径": 清理结果["证据路径"],
        **结果,
    }


def _工程缓存目录(项目根目录: Path) -> Path:
    return (项目根目录 / "工程缓存").resolve()


def _资源清单目录(项目根目录: Path) -> Path:
    return _工程缓存目录(项目根目录) / "测试资源清单"


def _清理失败证据目录(项目根目录: Path) -> Path:
    return _工程缓存目录(项目根目录) / "清理失败证据"


def _定位资源清单(项目根目录: Path, 工作区路径: Path, work_id: str) -> Path | None:
    """按 work_id 或工作区路径匹配定位资源清单；无清单返回 None。"""
    清单目录 = _资源清单目录(项目根目录)
    if not 清单目录.is_dir():
        return None
    候选表 = [清单目录 / f"{work_id}.jsonl"] if work_id else sorted(清单目录.glob("*.jsonl"))
    工作区文本 = str(工作区路径)
    for 候选 in 候选表:
        if not 候选.is_file():
            continue
        for 行 in 候选.read_text(encoding="utf-8").splitlines():
            try:
                记录 = json.loads(行)
            except json.JSONDecodeError:
                continue
            if 记录.get("work_id") == work_id:
                return 候选
            资源路径 = str(记录.get("路径", ""))
            if 资源路径.startswith(f"{工作区文本}{os.sep}") or 资源路径 == 工作区文本:
                return 候选
    return None


def _已登记路径表(项目根目录: Path, 工作区路径: Path, work_id: str) -> set[str]:
    """已登记文件/目录资源路径集合（resolve 后），脏检查排除明确授权清理的资源。"""
    清单路径 = _定位资源清单(项目根目录, 工作区路径, work_id)
    if 清单路径 is None:
        return set()
    路径表: set[str] = set()
    for 行 in 清单路径.read_text(encoding="utf-8").splitlines():
        try:
            记录 = json.loads(行)
        except json.JSONDecodeError:
            continue
        if 记录.get("类型") in ("文件", "目录") and 记录.get("路径"):
            路径表.add(str(Path(str(记录["路径"])).resolve()))
    return 路径表


def _命中已登记路径(工作区路径: Path, 行: str, 已登记路径: set[str]) -> bool:
    """porcelain 状态行是否对应已登记资源路径（这些资源将被清理，不阻断关闭）。"""
    if not 已登记路径:
        return False
    路径文本 = 行.strip()
    if not 路径文本:
        return False
    if 路径文本.startswith("??"):
        路径文本 = 路径文本[2:].strip()
    elif len(路径文本) >= 3:
        路径文本 = 路径文本[3:].strip()
    if " -> " in 路径文本:
        路径文本 = 路径文本.rsplit(" -> ", 1)[-1]
    if 路径文本.startswith('"'):
        try:
            路径文本 = json.loads(路径文本)
        except json.JSONDecodeError:
            pass
    if not 路径文本:
        return False
    return str((工作区路径 / 路径文本).resolve()) in 已登记路径


def _解析运行秒数(etime文本: str) -> float:
    """解析 ps etime 列（秒 / MM:SS / HH:MM:SS / D-HH:MM:SS）为秒数。"""
    文本 = etime文本.strip()
    if not 文本:
        return 0.0
    if "-" in 文本:
        天数, 时间部分 = 文本.split("-", 1)
        return float(天数) * 86400 + _解析运行秒数(时间部分)
    段 = 文本.split(":")
    try:
        if len(段) == 1:
            return float(段[0])
        if len(段) == 2:
            return float(段[0]) * 60 + float(段[1])
        if len(段) == 3:
            return float(段[0]) * 3600 + float(段[1]) * 60 + float(段[2])
    except ValueError:
        return 0.0
    return 0.0


def _释放工作区残留进程(工作区路径: Path) -> list[dict[str, str]]:
    """ps 匹配工作区路径的残留子进程 → 终止；无法释放项进失败表。

    S2 收紧：只匹配 argv0 含工作区路径、且进程启动时间晚于工作区创建时间的进程；
    排除自身与网关进程（项目服务.py），防止误杀无关进程。
    """
    失败表: list[dict[str, str]] = []
    try:
        结果 = subprocess.run(
            ["ps", "-axo", "pid=,etime=,command="], capture_output=True, text=True, check=False,
        )
    except OSError as 错误:
        return [{"路径/标识": "ps", "类型": "子进程",
                 "原因": f"无法执行 ps 检查残留进程：{type(错误).__name__}: {错误}"}]
    if 结果.returncode != 0:
        return [{"路径/标识": "ps", "类型": "子进程",
                 "原因": f"ps 检查残留进程退出码 {结果.returncode}"}]
    自身pid = os.getpid()
    工作区文本 = str(工作区路径.resolve())
    try:
        创建时间 = 工作区路径.stat().st_ctime  # 工作区目录创建时间
    except OSError:
        创建时间 = 0.0
    当前时间 = time.time()
    for 行 in 结果.stdout.splitlines():
        字段 = 行.split(None, 2)
        if len(字段) < 3:
            continue
        if not 字段[0].isdigit():
            continue
        pid = int(字段[0])
        if pid == 自身pid:
            continue
        命令 = 字段[2]
        # 命令行必须含工作区路径（进程以工作区内文件/目录身份启动）；
        # macOS ps 的 command 列不保证显示自定义 argv[0]，按完整命令行匹配
        if 工作区文本 not in 命令:
            continue
        # 排除网关进程自身（命令行含 项目服务.py 的 Python 服务）
        if "项目服务.py" in 命令:
            continue
        try:
            运行秒数 = _解析运行秒数(字段[1])
        except ValueError:
            continue
        启动时间 = 当前时间 - 运行秒数
        # ps 的 etime 只按整秒显示，且目录 ctime 与进程启动存在时钟
        # 舍入差；允许 2 秒观测误差，同时仍排除明显早于工作区的历史进程。
        if 启动时间 < 创建时间 - 2.0:
            continue
        try:
            终止进程防残留(pid)
        except OSError as 错误:
            失败表.append({"路径/标识": f"子进程:{pid}", "类型": "子进程",
                         "原因": f"{type(错误).__name__}: {错误}"})
    return 失败表


def _清理关闭前资源(项目根目录: Path, 工作区路径: Path, work_id: str) -> dict[str, Any]:
    """关闭前：释放残留子进程并清理登记资源；失败写结构化证据并返回失败。"""
    失败表: list[dict[str, str]] = _释放工作区残留进程(工作区路径)
    清单路径 = _定位资源清单(项目根目录, 工作区路径, work_id)
    清理数 = 0
    保留数 = 0
    证据路径 = ""
    if 清单路径 is not None:
        清理结果 = 清理资源(
            清单路径, 临时根目录=工作区路径,
            证据目录=_清理失败证据目录(项目根目录), work_id=work_id or "",
        )
        清理数 = int(清理结果.get("清理数", 0) or 0)
        保留数 = int(清理结果.get("保留数", 0) or 0)
        证据路径 = str(清理结果.get("证据路径", "") or "")
        失败表.extend(清理结果.get("失败表", []) or [])
    if 失败表:
        if not 证据路径:
            证据路径 = str(写清理失败证据(
                _清理失败证据目录(项目根目录), work_id or "未开工", str(工作区路径), 失败表,
            ))
        return {"成功": False, "清理数": 清理数, "保留数": 保留数,
                "失败表": 失败表, "证据路径": 证据路径}
    return {"成功": True, "清理数": 清理数, "保留数": 保留数,
            "失败表": 失败表, "证据路径": 证据路径}


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
