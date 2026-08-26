"""路径安全原子能力实现（不对外暴露，只经包级中文入口调用）。

职责：路径穿越/越权校验（借鉴 OpenHands 路径安全围栏，保持原子）。
校验 相对路径 在 根目录 内：拒绝绝对路径、..、空、符号链接逃逸。
只做判定，不访问文件系统。
"""

from __future__ import annotations

import os

from 公共契约.基础类型.结果类型 import 结果


def 校验路径(根目录: str = None, 相对路径: str = None) -> 结果:
    """校验 相对路径 是否安全落在 根目录 内。返回 {通过, 绝对路径}。"""
    if not isinstance(根目录, str) or not 根目录.strip():
        return 结果.失败("参数不合法", "根目录必须是非空字符串", 来源="路径安全")
    if not isinstance(相对路径, str) or not 相对路径.strip():
        return 结果.失败("参数不合法", "相对路径必须是非空字符串", 来源="路径安全")
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
