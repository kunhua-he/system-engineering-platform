"""Git 提供者变更命令：提交（add+commit）、回滚（revert）、挑拣合入（cherry-pick）。

变更类最小原子命令。提交路径必须落在仓库目录内（路径越界拒绝）；
回滚/挑拣合入 提交哈希白名单（7-40 位十六进制），冲突自动 --abort
恢复干净状态（非零退出且含 conflict 标记时才判定冲突，不吞异常）。
"""

from __future__ import annotations

from pathlib import Path

from 公共契约.基础类型.结果类型 import 结果
from 支持库.适配层.Git提供者.实现.白名单 import (
    失败结果, 校验仓库路径, 校验提交哈希, 校验提交消息, 校验路径在仓库内, 校验超时,
)
from 支持库.适配层.Git提供者.实现.受管执行 import 默认超时秒, 执行git, 命令结果


def 提交(仓库路径: str, 路径列表: list[str], 消息: str,
        超时秒: float = 默认超时秒) -> 结果:
    """git add 指定路径 + git commit 原子提交（路径越界拒绝）。"""
    校验 = 校验仓库路径(仓库路径) or 校验提交消息(消息) or 校验超时(超时秒)
    if 校验:
        return 校验
    if not isinstance(路径列表, list) or not 路径列表:
        return 失败结果("参数不合法", "路径列表必须为非空列表")
    相对列表: list[str] = []
    for 路径 in 路径列表:
        校验 = 校验路径在仓库内(仓库路径, 路径)
        if 校验:
            return 校验
        相对列表.append(str(Path(路径).resolve().relative_to(Path(仓库路径).resolve())))
    执行列表: list[结果] = []
    for 参数 in (["add", "--"] + 相对列表, ["commit", "-m", 消息], ["rev-parse", "HEAD"]):
        执行 = 命令结果(执行git(仓库路径, 参数, 超时秒))
        if not 执行.成功:
            return 执行
        执行列表.append(执行)
    return 结果.成功结果({
        "提交": 执行列表[2].值["标准输出"].strip(), "消息": 消息, "路径列表": 相对列表,
    })


def _撤销式命令(仓库路径: str, 子命令: str, 操作名: str, 提交哈希: str,
               超时秒: float) -> 结果:
    """回滚/挑拣合入共用：哈希白名单 → 执行 → 冲突自动中止恢复。"""
    校验 = 校验仓库路径(仓库路径) or 校验提交哈希(提交哈希) or 校验超时(超时秒)
    if 校验:
        return 校验
    参数 = [子命令, 提交哈希]
    if 子命令 == "revert":
        参数.insert(1, "--no-edit")
    执行 = 执行git(仓库路径, 参数, 超时秒)
    if not 执行.成功:
        return 执行
    if 执行.值["退出码"] == 0:
        完成 = 命令结果(执行git(仓库路径, ["rev-parse", "HEAD"], 超时秒))
        if 完成.成功:
            return 结果.成功结果({
                操作名: 提交哈希, "新提交": 完成.值["标准输出"].strip(),
            })
        return 完成
    输出 = (执行.值["标准输出"] + 执行.值["标准错误"]).lower()
    if "conflict" not in 输出:
        return 命令结果(执行)
    中止 = 命令结果(执行git(仓库路径, [子命令, "--abort"], 超时秒))
    return 失败结果("冲突", f"{操作名} 发生冲突，已自动中止", 详情={
        "中止成功": 中止.成功, "git输出": 执行.值["标准错误"].strip()[-300:],
    })


def 回滚(仓库路径: str, 提交哈希: str, 超时秒: float = 默认超时秒) -> 结果:
    """git revert --no-edit 撤销指定提交；冲突自动中止。"""
    return _撤销式命令(仓库路径, "revert", "回滚", 提交哈希, 超时秒)


def 挑拣合入(仓库路径: str, 提交哈希: str, 超时秒: float = 默认超时秒) -> 结果:
    """git cherry-pick 挑拣指定提交到当前分支；冲突自动中止。"""
    return _撤销式命令(仓库路径, "cherry-pick", "挑拣合入", 提交哈希, 超时秒)
