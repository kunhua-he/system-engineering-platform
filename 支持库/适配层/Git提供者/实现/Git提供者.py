"""Git 提供者主实现：检查提供者、worktree 创建/查询/关闭、当前状态、获取当前提交哈希。

最小原子命令集（一个第三方 git 一个提供者）。参数经白名单校验
（实现/白名单.py），git 调用走受管执行（实现/受管执行.py：参数
列表、超时、进程组回收、输出上限）；关闭工作区非强制。
"""

from __future__ import annotations

from pathlib import Path

from 公共契约.基础类型.结果类型 import 结果
from 支持库.适配层.Git提供者.实现.白名单 import (
    失败结果, 授权拒绝, 校验分支名, 校验仓库路径, 校验起始点, 校验逻辑值, 校验路径文本,
    校验超时,
)
from 支持库.适配层.Git提供者.实现.受管执行 import 默认超时秒, 执行git, 命令结果


def _顺序执行(仓库路径: str, 命令列表: list[list[str]], 超时秒: float) -> 结果:
    """依次执行 git 命令；任一失败即返回失败结果，成功返回全部执行结果。"""
    执行列表 = []
    for 参数 in 命令列表:
        执行 = 命令结果(执行git(仓库路径, 参数, 超时秒))
        if not 执行.成功:
            return 执行
        执行列表.append(执行)
    return 结果.成功结果({"执行列表": 执行列表})


def 检查提供者(超时秒: float = 15) -> 结果:
    """git --version 真实探针：{git, 版本} 或 提供者不可用。

    探针腿唯一（2026-09-24 批R·R-3 合并）：外部命令版本探针一律经
    `系统探针.检查系统工具`（独立进程组 / 超时强杀 / 退出码分类 / 版本提取），
    本件不再自持 `subprocess.run` 探针；版本取该节点提取出的版本号，
    与 环境指纹 / 健康监督 的版本口径一致。
    """
    校验 = 校验超时(超时秒)
    if 校验:
        return 校验
    from 支持库.适配层.系统探针 import 检查系统工具
    探针 = 检查系统工具("git", ["git"], 超时秒=float(超时秒))
    if not 探针.成功:
        return 失败结果("提供者不可用",
                        f"git 探针失败（{探针.错误码}）: {探针.诊断}", 可重试=True)
    return 结果.成功结果({"git": "可用", "版本": 探针.版本})


def 创建工作区(仓库路径: str, 新路径: str, 分支名: str | None = None,
             起始点: str | None = None, 开工ID: str = None,
             超时秒: float = 默认超时秒) -> 结果:
    """git worktree add [-b 分支名] 路径 [起始点]：新建独立工作区。

    `开工ID`（写入凭证，**只做形态归一，不自行判拒**）：worktree add 会在 `新路径`
    落一整棵工作树，若 `新路径` 落在仓库受管面内，必须被一条 `所有者 == 开工ID` 的
    活跃写租约覆盖 —— 判据唯一在 `公共契约/运行时/写入授权.校验写入授权`（本腿逐条
    转调 `白名单.授权拒绝`）。`新路径` 在仓库外/`工程缓存/`/临时目录时该判据恒通过。
    """
    校验 = 校验仓库路径(仓库路径) or 校验路径文本(新路径) or 校验超时(超时秒)
    if 校验:
        return 校验
    if 分支名 is not None:
        校验 = 校验分支名(分支名)
    if 校验 is None and 起始点 is not None:
        校验 = 校验起始点(起始点)
    if 校验:
        return 校验
    if Path(新路径).exists():
        return 失败结果("参数不合法", f"目标路径已存在: {新路径}")
    校验 = 授权拒绝([新路径], 开工ID)
    if 校验:
        return 校验
    参数 = ["worktree", "add"]
    if 分支名:
        参数 += ["-b", 分支名]
    参数 += [新路径] + ([起始点] if 起始点 else [])
    执行 = 命令结果(执行git(仓库路径, 参数, 超时秒))
    if not 执行.成功:
        return 执行
    if not Path(新路径).is_dir():
        return 失败结果("命令失败", "worktree add 未产出工作区目录")
    return 结果.成功结果({"路径": 新路径, "分支": 分支名 or "由路径命名"})


def 查询工作区(仓库路径: str, 超时秒: float = 默认超时秒) -> 结果:
    """git worktree list --porcelain：{工作区列表: [{路径, 分支, 提交}]}。"""
    执行 = 命令结果(执行git(仓库路径, ["worktree", "list", "--porcelain"], 超时秒))
    if not 执行.成功:
        return 执行
    字段映射 = {"worktree": "路径", "branch": "分支", "HEAD": "提交"}
    清单: list[dict] = []
    当前: dict = {}
    for 行 in 执行.值["标准输出"].splitlines():
        if not 行.strip():
            if 当前:
                清单.append(当前)
                当前 = {}
            continue
        字段, _, 值 = 行.partition(" ")
        if 字段 == "detached":
            当前["分离头"] = True
        elif 字段 in 字段映射:
            当前[字段映射[字段]] = (
                值.removeprefix("refs/heads/") if 字段 == "branch" else 值)
    if 当前:
        清单.append(当前)
    return 结果.成功结果({"工作区列表": 清单})


def 关闭工作区(仓库路径: str, 目标路径: str, 强制: bool = False,
             开工ID: str = None, 超时秒: float = 默认超时秒) -> 结果:
    """git worktree remove 关闭工作区；强制=假 时存在未提交修改一律 未提交修改 拒绝。

    强制=真 → `git worktree remove --force`（丢弃未提交修改，调用方须显式选择）；
    强制=假 → 先查未提交修改，存在即拒绝（默认口径不变）。
    值：{已关闭, 强制}。

    `开工ID`（写入凭证，**只做形态归一，不自行判拒**）：worktree remove 会**删除
    `目标路径` 整棵工作树**，若它落在仓库受管面内，必须被一条 `所有者 == 开工ID` 的
    活跃写租约覆盖 —— 判据唯一在 `公共契约/运行时/写入授权.校验写入授权`（本腿逐条
    转调 `白名单.授权拒绝`）。`目标路径` 在仓库外/`工程缓存/`/临时目录时恒通过。
    """
    校验 = (校验仓库路径(仓库路径) or 校验路径文本(目标路径)
            or 校验逻辑值(强制, "强制") or 校验超时(超时秒))
    if 校验:
        return 校验
    校验 = 授权拒绝([目标路径], 开工ID)
    if 校验:
        return 校验
    if not 强制:
        状态 = 命令结果(执行git(目标路径, ["status", "--porcelain"], 超时秒))
        if not 状态.成功:
            return 状态
        if 状态.值["标准输出"].strip():
            return 失败结果("未提交修改", f"工作区存在未提交修改: {目标路径}")
    参数 = ["worktree", "remove"] + (["--force"] if 强制 else []) + [目标路径]
    执行 = 命令结果(执行git(仓库路径, 参数, 超时秒))
    if not 执行.成功:
        return 执行
    if Path(目标路径).exists():
        return 失败结果("命令失败", "worktree remove 后目录仍存在")
    return 结果.成功结果({"已关闭": 目标路径, "强制": 强制})


def 当前状态(仓库路径: str, 超时秒: float = 默认超时秒) -> 结果:
    """status/log 摘要：{分支, 未提交修改, 最近提交}。"""
    执行 = _顺序执行(仓库路径, [
        ["rev-parse", "--abbrev-ref", "HEAD"],
        ["status", "--porcelain"],
        ["log", "--oneline", "-10"],
    ], 超时秒)
    if not 执行.成功:
        return 执行
    分支, 状态, 日志 = 执行.值["执行列表"]
    return 结果.成功结果({
        "分支": 分支.值["标准输出"].strip(),
        "未提交修改": [行 for 行 in 状态.值["标准输出"].splitlines() if 行.strip()],
        "最近提交": [行 for 行 in 日志.值["标准输出"].splitlines() if 行.strip()],
    })


def 获取当前提交哈希(仓库路径: str, 超时秒: float = 默认超时秒) -> 结果:
    """git rev-parse HEAD + rev-parse --abbrev-ref HEAD：{提交哈希, 分支}。

    正常分支返回分支名；detached HEAD 时分支为 HEAD。非仓库目录统一
    映射为 命令失败（错误码契约不暴露 仓库不存在）。
    """
    校验 = 校验超时(超时秒)
    if 校验:
        return 校验
    if not isinstance(仓库路径, str) or not 仓库路径.strip():
        return 失败结果("参数不合法", "仓库路径必须是非空文本")
    执行 = _顺序执行(仓库路径, [
        ["rev-parse", "HEAD"],
        ["rev-parse", "--abbrev-ref", "HEAD"],
    ], 超时秒)
    if not 执行.成功:
        if 执行.错误码 == "仓库不存在":
            return 失败结果("命令失败", f"不是 git 仓库: {仓库路径}")
        return 执行
    哈希执行, 分支执行 = 执行.值["执行列表"]
    return 结果.成功结果({
        "提交哈希": 哈希执行.值["标准输出"].strip(),
        "分支": 分支执行.值["标准输出"].strip() or "HEAD",
    })
