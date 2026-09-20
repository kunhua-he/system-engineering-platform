"""Git 提供者参数白名单：分支名/路径/提交哈希/消息 结构化校验。

安全目标：拒绝含 空格/换行/;|&`$ 等 shell 元字符的输入；路径必须为
绝对路径且解析后落在仓库目录内（路径越界拒绝）；分支名与起始点只允许
字母数字 _ . / - 组合；提交哈希只允许 7-40 位十六进制。
"""

from __future__ import annotations

import re
from pathlib import Path

from 公共契约.基础类型.结果类型 import 结果

来源 = "Git提供者"
# 分支名/起始点：允许中文等可打印字符，仅拒绝 空白 与 shell 元字符
# （;|&`$"'\\ 与 C0 控制字符），git 自身规则（..、尾斜杠等）由 git 校验
分支名模式 = re.compile(r"^[^ \t\n\r\v\f;|&`$\"'\\\x00-\x1f]+$")
哈希模式 = re.compile(r"^[0-9a-fA-F]{7,40}$")
禁止元字符 = " \n\t\r;|&`$\"'\\"


def 失败结果(错误码: str, 消息: str, *, 可重试: bool = False,
             详情: dict | None = None) -> 结果:
    """统一失败结果（白名单与执行层共用）。"""
    return 结果.失败(错误码, 消息, 来源=来源, 可重试=可重试, 详情=详情 or {})


def 校验仓库路径(仓库路径: object) -> 结果 | None:
    """仓库路径必须是非空文本且指向真实目录。"""
    if not isinstance(仓库路径, str) or not 仓库路径.strip():
        return 失败结果("参数不合法", "仓库路径必须是非空文本")
    if not Path(仓库路径).is_dir():
        return 失败结果("仓库不存在", f"仓库目录不存在: {仓库路径}")
    return None


def 校验分支名(分支名: object) -> 结果 | None:
    """分支名白名单：禁 空白 与 shell 元字符（中文等可打印字符放行）。"""
    if not isinstance(分支名, str) or not 分支名.strip():
        return 失败结果("参数不合法", "分支名必须为非空文本")
    if 分支名.startswith("-") or not 分支名模式.fullmatch(分支名):
        return 失败结果("参数不合法", f"分支名含禁止字符: {分支名!r}")
    return None


def 校验远端名(远端: object) -> 结果 | None:
    """远端名白名单：非空、不以 `-` 开头、无 空白 与 shell 元字符。

    缺省（None 或空文本）放行 —— 由能力层填默认远端 `origin`。
    为什么单独一条而不复用 `校验分支名`：远端名会**直接出现在 git 参数位**，
    `-` 开头的名字会被 git 当**选项**解析（如 `--upload-pack=…` 可挂任意命令），
    这是参数注入面，必须显式拒绝（`校验分支名` 也拒 `-` 开头，但报错文案是
    「分支名…」，用在远端上会误导排查）。
    """
    if 远端 is None or (isinstance(远端, str) and not 远端.strip()):
        return None
    if not isinstance(远端, str):
        return 失败结果("参数不合法", "远端名必须是文本")
    if 远端.startswith("-") or not 分支名模式.fullmatch(远端):
        return 失败结果("参数不合法", f"远端名含禁止字符或以 - 开头: {远端!r}")
    return None


def 校验起始点(起始点: object) -> 结果 | None:
    """起始点：提交哈希 或 白名单分支名（worktree add 的 <commit-ish>）。"""
    if not isinstance(起始点, str) or not 起始点.strip():
        return 失败结果("参数不合法", "起始点必须为非空文本")
    if 哈希模式.fullmatch(起始点):
        return None
    return 校验分支名(起始点)


def 校验提交哈希(提交哈希: object) -> 结果 | None:
    """提交哈希白名单：7-40 位十六进制。"""
    if not isinstance(提交哈希, str) or not 哈希模式.fullmatch(提交哈希 or ""):
        return 失败结果("参数不合法", "提交哈希必须是 7-40 位十六进制")
    return None


def 校验路径文本(候选路径: object) -> 结果 | None:
    """路径白名单：绝对路径且不含 空格/换行/;|&`$ 等元字符。"""
    if not isinstance(候选路径, str) or not 候选路径.strip():
        return 失败结果("参数不合法", "路径必须为非空文本")
    if not 候选路径.startswith("/"):
        return 失败结果("参数不合法", "路径必须为绝对路径")
    if any(字符 in 候选路径 for 字符 in 禁止元字符):
        return 失败结果("参数不合法", "路径含禁止元字符（空格/换行/;|&`$ 等）")
    return None


def 校验路径在仓库内(仓库路径: str, 候选路径: str) -> 结果 | None:
    """路径必须解析后落在仓库目录内（路径越界拒绝）。"""
    错误 = 校验路径文本(候选路径)
    if 错误:
        return 错误
    try:
        Path(候选路径).resolve().relative_to(Path(仓库路径).resolve())
    except ValueError:
        return 失败结果("路径越界", f"路径不在仓库内: {候选路径}")
    return None


def 校验提交消息(消息: object) -> 结果 | None:
    """提交消息：非空文本，**允许多行**，禁回车与 NUL。

    为什么放开换行（2026-09-21）：本仓的提交约定是「首行 `开工ID + 一句话`，下面跟
    为什么 / 逐条改动 / 验证证据」的多行说明，而本能力原先只收单行 —— 于是收工只能退回
    终端 `git commit -F <信息文件>`（本轮实测：连着两轮收工都这么干）。命令是按
    「可执行文件 + 参数」直启（不经 shell），argv 里的换行没有任何注入面，
    原先那条限制挡住的不是风险而是**平台自己的提交约定**。

    仍拒 `\\r` 与 `\\x00`：前者会让 git 把消息按 CRLF 拆出多余空行，后者是 argv 的
    截断字符（execve 层面直接报错），两者都不是「多行」而是畸形输入。
    """
    if not isinstance(消息, str) or not 消息.strip():
        return 失败结果("参数不合法", "提交消息必须为非空文本")
    if any(字符 in 消息 for 字符 in "\r\x00"):
        return 失败结果("参数不合法", "提交消息禁止回车与控制字符（换行可用）")
    return None


def 校验逻辑值(值: object, 名称: str = "开关") -> 结果 | None:
    """逻辑型参数必须是真布尔（不接受 0/1/\"true\" 等替代）。"""
    if type(值) is not bool:
        return 失败结果("参数不合法", f"{名称}必须是逻辑值（真/假）")
    return None


def 校验超时(超时秒: object) -> 结果 | None:
    """超时秒必须是正数。"""
    if not isinstance(超时秒, (int, float)) or isinstance(超时秒, bool) or 超时秒 <= 0:
        return 失败结果("参数不合法", "超时秒必须是正数")
    return None
