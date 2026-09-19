"""薄壳工具清单：3 个薄壳工具的协议名、中文名、描述、入参与转发目标（唯一元数据来源）。

协议名保持 ASCII（SEP-986：Tool.name 仅允许 [A-Za-z0-9_.-]+），中文名写进 description。
薄壳零业务语义：这里只声明「转发哪个操作、哪个能力」，不写任何业务规则、不读业务数据。
"""

from __future__ import annotations

from typing import Any

import sys as _sys
from pathlib import Path as _Path

_项目根 = _Path(__file__).resolve().parents[2]
if str(_项目根) not in _sys.path:
    _sys.path.insert(0, str(_项目根))

from 支持库.适配层.MCP协议提供者 import 构造工具定义


# 唯一转发目标：网关操作名（与 开发文档/网关调用最小示例.md 一致）。
调用能力操作 = "调用能力"
# 查询能力薄壳要求转发的登记能力 id；该能力未注册时薄壳只报错并登记，不自实现搜索。
# 能力 id 是「不带头部包根前缀」的形式（真实注册表口径，已实测：注册表 能力id列表 里是
# `能力目录.搜索能力`；写 `模块库.能力目录.搜索能力` 会被网关判 404 能力未注册）。
搜索能力目标 = "能力目录.搜索能力"

三个工具定义: tuple = (
    构造工具定义(
        "capability_search",
        (
            "查询能力：经唯一网关查平台已注册能力。"
            "**前提**：本工具只服务系统工程平台仓库（传参 项目根 必须是平台绝对路径）；"
            "不是本仓库的会话不要调用，也不要据此载入任何平台上下文。"
        ),
        {
            "type": "object",
            "properties": {
                "关键词": {"type": "string", "description": "搜索关键词，例如 读取文件"},
                "限制": {"type": "integer", "description": "返回上限，默认 20"},
                "项目根": {"type": "string", "description": "系统工程平台仓库绝对路径；非本仓库不要调用"},
            },
            "required": ["关键词", "项目根"],
        },
    ),
    构造工具定义(
        "capability_call",
        (
            "调用能力：入参「能力id」+「参数」+「项目根」，经唯一网关转发执行。"
            "**前提**：本工具只服务系统工程平台仓库（传参 项目根 必须是平台绝对路径）；"
            "不是本仓库的会话不要调用。"
            "在本仓库做任务时，**开工第一步必须调能力 id「开工编排.开工准备」**"
            "（入参 项目根=仓库绝对路径、任务、修改路径），它返回开工 ID 与本次任务的全部规则；"
            "按返回值里的 开工ID 向 GitHub 提交。规则正文以该返回为唯一送达点，本文不复述。"
        ),
        {
            "type": "object",
            "properties": {
                "能力id": {"type": "string", "description": "能力 id，例如 开工编排.开工准备"},
                "参数": {"type": "object", "description": "能力入参对象，原样转发给网关"},
                "项目根": {"type": "string", "description": "系统工程平台仓库绝对路径；非本仓库不要调用"},
            },
            "required": ["能力id", "项目根"],
        },
    ),
    构造工具定义(
        "tool_catalog",
        (
            "工具目录：返回薄壳当前暴露的工具清单（协议名/中文名/入参/转发目标）。"
            "只读元数据，不扫描仓库、不转发网关。"
        ),
        {"type": "object", "properties": {}},
    ),
)

中文名到协议名 = {
    "查询能力": "capability_search",
    "调用能力": "capability_call",
    "工具目录": "tool_catalog",
}
协议名到中文名 = {协议名: 中文名 for 中文名, 协议名 in 中文名到协议名.items()}


def 构建工具目录() -> dict[str, Any]:
    """薄壳自身工具清单（只读元数据，不触碰仓库其它文件）。"""
    清单 = [
        {
            "协议名": 工具.name,
            "中文名": 协议名到中文名.get(工具.name, 工具.name),
            "入参": 工具.inputSchema,
            "描述": 工具.description,
            "转发目标": {
                "capability_search": f"{调用能力操作} → {搜索能力目标}",
                "capability_call": f"{调用能力操作} → 入参指定能力id",
                "tool_catalog": "不转发（薄壳本地元数据）",
            }.get(工具.name, ""),
        }
        for 工具 in 三个工具定义
    ]
    return {
        "成功": True,
        "错误码": "",
        "错误说明": "",
        "薄壳工具数": len(清单),
        "工具": 清单,
        "传输": "stdio（不监听任何端口）",
        "唯一转发通道": "HTTP POST http://127.0.0.1:40007/网关/调用",
    }
