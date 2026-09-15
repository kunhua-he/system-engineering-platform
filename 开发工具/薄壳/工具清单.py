"""薄壳工具清单：3 个薄壳工具的协议名、中文名、描述、入参与转发目标（唯一元数据来源）。

协议名保持 ASCII（SEP-986：Tool.name 仅允许 [A-Za-z0-9_.-]+），中文名写进 description。
薄壳零业务语义：这里只声明「转发哪个操作、哪个能力」，不写任何业务规则、不读业务数据。
"""

from __future__ import annotations

from typing import Any

from mcp.types import Tool

# 唯一转发目标：网关操作名（与 开发文档/网关调用最小示例.md 一致）。
调用能力操作 = "调用能力"
# 查询能力薄壳要求转发的登记能力 id；该能力未注册时薄壳只报错并登记，不自实现搜索。
# 能力 id 是「不带头部包根前缀」的形式（真实注册表口径，已实测：注册表 能力id列表 里是
# `能力目录.搜索能力`；写 `模块库.能力目录.搜索能力` 会被网关判 404 能力未注册）。
搜索能力目标 = "能力目录.搜索能力"

三个工具定义: tuple[Tool, ...] = (
    Tool(
        name="capability_search",
        description=(
            "查询能力（薄壳工具）：经唯一网关查询平台已注册能力。"
            f"只转发网关操作「{调用能力操作}」到能力 id「{搜索能力目标}」，"
            "薄壳不实现任何搜索逻辑；该能力未注册时明确返回 能力未注册 并登记待补能力清单。"
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "关键词": {"type": "string", "description": "搜索关键词，例如 读取文件"},
                "限制": {"type": "integer", "description": "返回上限，默认 20"},
            },
            "required": ["关键词"],
        },
    ),
    Tool(
        name="capability_call",
        description=(
            "调用能力（薄壳主体）：入参「能力id」+「参数」，"
            f"经唯一网关 HTTP POST /网关/调用（操作={调用能力操作}）转发执行。"
            "薄壳不解析业务参数、不做业务判断、不落业务数据，只回传网关信封。"
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "能力id": {"type": "string", "description": "能力 id，例如 技能库.技能索引.扫描技能包"},
                "参数": {"type": "object", "description": "能力入参对象，原样转发给网关"},
            },
            "required": ["能力id"],
        },
    ),
    Tool(
        name="tool_catalog",
        description=(
            "工具目录（薄壳工具）：返回薄壳自身当前暴露的工具清单"
            "（协议名/中文名/入参/转发目标）。只读元数据，不扫描仓库、不转发网关。"
        ),
        inputSchema={"type": "object", "properties": {}},
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
