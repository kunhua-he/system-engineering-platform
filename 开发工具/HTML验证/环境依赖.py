"""本机环境依赖注入：HTML 验证链与发布门禁**共用的唯一实现**。

哲学第 1 条 1 项：模型文件、外部应用这类**环境依赖**由运行环境提供，不进场景
静态路径。场景只声明「读哪个环境变量」（`{"$动态": "环境变量", "名称": X}`），
取值由运行环境负责（见同目录 `动态值.py`：取值缺失即明确失败，不静默跳过）。

本模块就是「运行环境」在这台机器上的唯一声明点与读取点：

1. 取值顺序：① 当前进程环境；② 本机 40007 网关 launchd 配置
   （`~/Library/LaunchAgents/com.huashi.gateway-40007.plist` 的
   `EnvironmentVariables`）——本机的提供者环境依赖就是在那里声明的。
2. 取不到**不注入、不伪造**：相关场景会以「环境依赖未就绪：环境变量 X 未设置或
   为空」明确失败，不会被静默跳过。

**为什么要共用一份**：`开发工具/发布门禁/运行发布门禁.py` 原先只把这些变量注入
到自己拉起的 HTML 验证**子进程**（`环境覆盖={**缓存环境, **环境依赖注入()}`），
而 `开发文档/主开发文档.md` 记载的全量验收入口是直接跑
`python3.14 -m 开发工具.HTML验证.验证器`——子进程这条线注入、直接跑这条线不注入。
实测后果（2026-09-16 HTML 黑盒，并发 32）：`直播逐字稿.全自动精校正向` 恒定以
`步骤执行异常: ValueError: 环境依赖未就绪：环境变量 MLXWhisper提供者_模型路径
未设置或为空` 变红——不是能力缺陷、也不是场景缺陷，而是**验证链自己没把场景已
声明依赖的运行环境补上**。现在由验证器自己注入，两条线同源同结果。
"""
from __future__ import annotations

import os
import plistlib
from pathlib import Path
from typing import Any, Mapping, MutableMapping

#: 本机声明的环境依赖变量（提供者侧环境依赖；新增变量只在这里加一份）。
环境依赖变量表 = ("MLXWhisper提供者_模型路径", "MLXWhisper提供者_模型名",
                "系统工程平台_决策模型权重目录")

#: 本机声明这些环境依赖的载体：40007 常驻网关的 launchd 配置。
网关配置路径 = Path.home() / "Library" / "LaunchAgents" / "com.huashi.gateway-40007.plist"

#: 最近一次注入过程中遇到的问题（读取失败必须留痕，不静默）。
环境依赖注入问题: list[str] = []


def 读取本机声明(配置路径: Path | None = None) -> dict[str, str]:
    """读本机 launchd 配置里声明的环境变量；文件缺失或不可解析一律返回空字典并留痕。"""
    路径 = Path(配置路径) if 配置路径 is not None else 网关配置路径
    if not 路径.is_file():
        环境依赖注入问题.append(f"缺少 launchd 配置，无法取环境依赖: {路径}")
        return {}
    try:
        环境 = plistlib.loads(路径.read_bytes()).get("EnvironmentVariables", {})
    except (OSError, ValueError, plistlib.InvalidFileException) as 错误:
        环境依赖注入问题.append(f"读取 launchd 环境失败: {错误}")
        return {}
    if not isinstance(环境, dict):
        环境依赖注入问题.append(f"launchd 配置的 EnvironmentVariables 不是字典: {路径}")
        return {}
    return {str(键): str(值) for 键, 值 in 环境.items() if isinstance(值, (str, int, float))}


def 环境依赖注入(配置路径: Path | None = None) -> dict[str, str]:
    """返回可注入的环境依赖变量：① 当前进程环境，② 本机 launchd 声明（只补缺）。"""
    注入 = {名称: os.environ[名称] for 名称 in 环境依赖变量表 if os.environ.get(名称)}
    缺失 = [名称 for 名称 in 环境依赖变量表 if 名称 not in 注入]
    if not 缺失:
        return 注入
    本机声明 = 读取本机声明(配置路径)
    for 名称 in 缺失:
        if 本机声明.get(名称):
            注入[名称] = 本机声明[名称]
    return 注入


def 应用环境依赖(
    环境: MutableMapping[str, str] | None = None, 配置路径: Path | None = None,
) -> tuple[list[str], list[str]]:
    """把缺失的环境依赖补进进程环境（只补空、绝不覆盖调用方已设的值）。

    返回 `(本次注入的变量名, 仍未就绪的变量名)`。调用方应把两个名字表都打印出来：
    注入要可见，「仍未就绪」更要可见——否则调用方会把环境问题当成能力红。
    """
    目标: MutableMapping[str, str] = os.environ if 环境 is None else 环境
    注入 = 环境依赖注入(配置路径)
    已注入: list[str] = []
    for 名称 in 环境依赖变量表:
        取值 = 注入.get(名称) or ""
        if not 取值 or 目标.get(名称):
            continue
        目标[名称] = 取值
        已注入.append(名称)
    未就绪 = [名称 for 名称 in 环境依赖变量表 if not (目标.get(名称) or "").strip()]
    return 已注入, 未就绪


def 报告环境依赖(目标: Any = None) -> None:
    """注入并打印一行结论（验证链入口调用；注入与未就绪都看得见）。"""
    已注入, 未就绪 = 应用环境依赖(目标)
    if 已注入:
        print("[环境依赖] 已按场景声明注入（取值：外层进程环境 / 本机 40007 网关 launchd 配置）: "
              + ", ".join(已注入))
    if 未就绪:
        print("[环境依赖] 仍未就绪: " + ", ".join(未就绪)
              + "（声明该依赖的场景将明确失败，不会被静默跳过）")


__all__ = [
    "环境依赖变量表",
    "网关配置路径",
    "环境依赖注入问题",
    "读取本机声明",
    "环境依赖注入",
    "应用环境依赖",
    "报告环境依赖",
]
