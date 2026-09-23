"""路径安全原子能力实现（不对外暴露，只经包级中文入口调用）。

职责：路径穿越/越权校验（借鉴 OpenHands 路径安全围栏，保持原子）。
校验 相对路径 在 根目录 内：拒绝绝对路径、..、空、符号链接逃逸。
只做判定，不访问文件系统。

★ 2026-09-23（未完成事项 §四「路径边界有 5 份实现、口径互不一致」）：判据前先 `unquote`（**只解一次**）—— 此前
`..%2fetc` / `%2e%2e/x` / `a/..%2f/b` 三种 URL 编码穿越**全放行**（字面量里没有 `..` 段、
`os.path.isabs` 也不认）。二次解码本身是漏洞，故只对原始入参解一次。
"""

from __future__ import annotations

import os
from urllib.parse import unquote

from 公共契约.基础类型.结果类型 import 结果


def 校验路径(根目录: str = None, 相对路径: str = None) -> 结果:
    """校验 相对路径 是否安全落在 根目录 内。返回 {通过, 绝对路径}。"""
    if not isinstance(根目录, str) or not 根目录.strip():
        return 结果.失败("参数不合法", "根目录必须是非空字符串", 来源="路径安全")
    if not isinstance(相对路径, str) or not 相对路径.strip():
        return 结果.失败("参数不合法", "相对路径必须是非空字符串", 来源="路径安全")
    # URL 解码归一化（未完成事项 §四「路径边界有 5 份实现、口径互不一致」，2026-09-23）：**所有判据之前**先 unquote，且只解一次。
    # 为什么必须在判据之前：`..%2fetc` / `%2e%2e/x` / `a/..%2f/b` 字面既不含 `..` 段、
    # `os.path.isabs` 也不认，会被整段当成普通目录名放行；而消费方拿到的是**解码后**的
    # 路径 ⇒ 编码穿越可整体绕过本能力。
    # 为什么只解一次：对**已解码结果**再解一次会让 `%252e%252e` 这类双重编码钻过去
    # （二次解码本身就是漏洞），故此处只对原始入参调用一次 unquote。
    相对路径 = unquote(相对路径)
    根 = os.path.abspath(os.path.expanduser(根目录))
    if os.path.isabs(相对路径):
        return 结果.成功结果({"通过": False, "原因": "相对路径不能是绝对路径", "绝对路径": ""})
    if ".." in 相对路径.split(os.sep) or ".." in 相对路径.split("/"):
        return 结果.成功结果({"通过": False, "原因": "相对路径不能包含 .. 目录跳转", "绝对路径": ""})
    if 相对路径 in (".", "./"):
        return 结果.成功结果({"通过": False, "原因": "相对路径不能是当前目录", "绝对路径": ""})
    绝对路径 = os.path.normpath(os.path.join(根, 相对路径))
    # 防符号链接逃逸：解析后必须仍在根内
    try:
        真实根 = os.path.realpath(根)
        真实路径 = os.path.realpath(绝对路径)
    except OSError:
        return 结果.失败("路径解析失败", "realpath 解析异常", 来源="路径安全")
    if not (真实路径 == 真实根 or 真实路径.startswith(真实根 + os.sep)):
        return 结果.成功结果({"通过": False, "原因": "路径越出根目录（符号链接逃逸）", "绝对路径": ""})
    return 结果.成功结果({"通过": True, "原因": "允许", "绝对路径": 绝对路径})


def 校验文件名(文件名: str = None) -> 结果:
    """校验文件名安全：非空、不含路径分隔符、不含 .. 、不以 . 开头（防隐藏文件）。"""
    if not isinstance(文件名, str) or not 文件名.strip():
        return 结果.失败("参数不合法", "文件名必须是非空字符串", 来源="路径安全")
    if "/" in 文件名 or "\\" in 文件名:
        return 结果.成功结果({"通过": False, "原因": "文件名不能包含路径分隔符", "安全文件名": ""})
    if 文件名 in (".", "..") or 文件名.startswith("."):
        return 结果.成功结果({"通过": False, "原因": "文件名不能是 . / .. 或以点开头", "安全文件名": ""})
    return 结果.成功结果({"通过": True, "原因": "允许", "安全文件名": 文件名})

def 显示相对路径(目标路径: str = None, 基准目录: str = None, 备选基准: str = None) -> 结果:
    """把绝对路径显示为相对某基准目录的字符串（用于日志/UI 展示）。

    依次尝试 基准目录 → 备选基准，都不在则原样返回绝对路径。
    不抛异常：任何异常都回退为原样返回，保证展示路径永不中断调用方。
    """
    from pathlib import Path as _Path

    if not isinstance(目标路径, str) or not 目标路径.strip():
        return 结果.失败("参数不合法", "目标路径必须是非空字符串", 来源="路径安全")
    路径 = _Path(目标路径)
    for 候选 in (基准目录, 备选基准):
        if isinstance(候选, str) and 候选.strip():
            try:
                return 结果.成功结果({"显示路径": str(路径.relative_to(_Path(候选))), "相对": True})
            except ValueError:
                continue
    return 结果.成功结果({"显示路径": str(路径), "相对": False})
