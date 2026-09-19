"""Git 提供者受管执行层：参数列表执行、超时、进程组回收、输出上限。

全部 git 调用走 subprocess 参数列表（禁 shell=True / 禁字符串拼接）；
独立进程组（start_new_session）+ 超时 SIGTERM→SIGKILL 回收；
标准输出超限返回 超出限制；非零退出由调用方按语义映射错误码。
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from 公共契约.基础类型.结果类型 import 结果
from 公共契约.运行时 import 平台适配, 进程终止
from 公共契约.运行时.有界IO import 受限通信
from 支持库.适配层.Git提供者.实现.白名单 import 失败结果, 校验仓库路径, 校验超时

默认超时秒 = 60.0
最大输出字节 = 4 * 1024 * 1024


def _终止进程组(进程: subprocess.Popen, 宽限秒: float = 1.0) -> None:
    """进程组终止（终止→宽限→强杀→复查死透）：唯一实现在 公共契约.运行时.进程终止。

    平台差异（POSIX 按进程组 / Windows 按进程树）由收口层自己判定：本处不再持有
    平台判断、信号号或 killpg 调用，也不再自己 wait 收尾。
    """
    进程终止.强制结束子进程(进程, 宽限秒=宽限秒, 等待秒=宽限秒)


def 执行git(仓库路径: str, 参数列表: list[str], 超时秒: float = 默认超时秒) -> 结果:
    """受管执行 git：参数列表（禁 shell）、超时、进程组回收、输出上限。

    成功值：{退出码, 标准输出, 标准错误}；退出码非零不在此层判定语义，
    由能力层映射 命令失败/冲突/未提交修改 等稳定错误码。
    """
    校验 = 校验仓库路径(仓库路径) or 校验超时(超时秒)
    if 校验:
        return 校验
    仓库 = Path(仓库路径)
    if not (仓库 / ".git").exists() and not (仓库 / "HEAD").is_file():
        return 失败结果("仓库不存在", f"不是 git 仓库: {仓库路径}")
    try:
        进程 = subprocess.Popen(
            ["git", "-C", str(仓库)] + 参数列表,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            **平台适配.子进程组启动标志(),
        )
    except OSError as 错误:
        return 失败结果("提供者不可用", f"无法启动 git: {错误}", 可重试=True)
    try:
        标准输出, 标准错误, 已超时, 输出超限 = 受限通信(
            进程, 超时秒=超时秒, 输出上限字节=最大输出字节,
            终止回调=lambda: _终止进程组(进程),
        )
    finally:
        for 流 in (进程.stdin, 进程.stdout, 进程.stderr):
            if 流:
                try:
                    流.close()
                except (OSError, ValueError):
                    pass
    if 已超时:
        return 失败结果("超时", f"git 命令超过 {超时秒} 秒", 可重试=True)
    if 输出超限:
        return 失败结果("超出限制", f"git 输出超过上限 {最大输出字节} 字节")
    return 结果.成功结果({
        "退出码": 进程.returncode,
        "标准输出": 标准输出.decode("utf-8", errors="replace"),
        "标准错误": 标准错误.decode("utf-8", errors="replace"),
    })


def 命令结果(执行: 结果) -> 结果:
    """非零退出 → 命令失败（标准错误尾部摘要）；已失败或零退出原样通过。"""
    if not 执行.成功 or 执行.值["退出码"] == 0:
        return 执行
    错误 = 执行.值["标准错误"].strip() or 执行.值["标准输出"].strip()
    return 失败结果("命令失败", f"git 退出码 {执行.值['退出码']}: {错误[-300:]}")
