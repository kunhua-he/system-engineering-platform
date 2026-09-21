"""MCP 协议适配提供者：第三方 mcp SDK 的唯一边界封装。

只允许在本文件 import mcp；薄壳（开发工具/薄壳/薄壳服务.py）与其它调用方
一律经包级中文入口使用本提供者，不得直接依赖第三方。

分工：
- 探针（检查可用性）注册为能力，供健康检查与依赖审计；
- 服务端侧：构造服务/构造初始化选项/构造工具定义/构造文本内容/构造工具结果/标准输入输出上下文；
- 客户端侧：构造标准输入输出参数/标准输入输出客户端/构造客户端会话（自测客户端用）；
  以上返回的都是第三方对象（不可契约化），只作为包级入口导出的翻译函数。
"""

from __future__ import annotations

from typing import Any

# 依赖导入失败原因：模块级记录，工厂函数据此抛 MCP依赖不可用，不静默降级。
_导入失败原因: str = ""
try:
    import importlib.metadata as _元数据
    from mcp.server import Server as _服务类
    from mcp.server.models import InitializationOptions as _初始化选项类
    from mcp.server.stdio import stdio_server as _标准输入输出函数
    from mcp.types import ServerCapabilities as _服务能力类
    from mcp.types import TextContent as _文本内容类
    from mcp import ClientSession as _客户端会话类
    from mcp import StdioServerParameters as _标准输入输出参数类
    from mcp.client.stdio import stdio_client as _标准输入输出客户端函数
    from mcp.types import Tool as _工具类
    from mcp.types import CallToolResult as _工具结果类
except Exception as _导入异常:  # 依赖缺失与版本不兼容都在此收口，原因留痕
    _导入失败原因 = f"{type(_导入异常).__name__}: {_导入异常}"


class MCP依赖不可用(RuntimeError):
    """mcp SDK 不可导入时抛出的明确失败（不静默降级）。"""


def _确保可用() -> None:
    """依赖不可用时明确抛出 MCP依赖不可用。"""
    if _导入失败原因:
        raise MCP依赖不可用(f"mcp SDK 不可导入：{_导入失败原因}")


def 依赖版本() -> str:
    """读取 mcp SDK 版本（不可读取时返回空文本）。"""
    try:
        return str(_元数据.version("mcp"))
    except Exception:  # 元数据缺失只影响版本展示，不影响可用性判定
        return ""


def 检查可用性() -> dict[str, Any]:
    """探针：mcp SDK 是否可导入及版本；供健康检查与依赖审计使用。"""
    if _导入失败原因:
        return {"可用": False, "版本": "", "说明": f"mcp SDK 不可导入：{_导入失败原因}"}
    版本 = 依赖版本()
    return {"可用": True, "版本": 版本, "说明": f"mcp SDK 可导入，版本 {版本 or '未知'}"}


def 构造服务(名称: str):
    """构造 mcp 服务对象（第三方对象，不契约化，故不作为能力注册）。"""
    _确保可用()
    return _服务类(名称)


def 构造初始化选项(服务名: str, 服务版本: str):
    """构造初始化选项；能力集固定为 tools（薄壳只暴露工具，不收资源与提示）。"""
    _确保可用()
    return _初始化选项类(
        server_name=服务名,
        server_version=服务版本,
        capabilities=_服务能力类(tools={}),
    )


def 构造工具定义(名称: str, 说明: str, 参数结构: dict):
    """构造 mcp 工具定义（工具协议名保持 ASCII，中文名写进说明）。"""
    _确保可用()
    return _工具类(name=名称, description=说明, inputSchema=参数结构)


def 构造文本内容(文本: str):
    """构造 mcp 文本内容（工具回执统一走 text 类型）。"""
    _确保可用()
    return _文本内容类(type="text", text=文本)


def 构造工具结果(文本: str, *, 失败: bool = False):
    """构造 mcp 工具结果，并**如实置 `isError`**（SEP-1303：输入校验失败必须走 Tool Execution Error）。

    为什么必须补这个函数（2026-09-21 批 2 · L10 实测）：薄壳此前只回 `list[TextContent]`，
    而 mcp SDK 对「返回 list」的正常路径**固定 `isError=False`**
    （`server/lowlevel/server.py`：`CallToolResult(..., isError=False)`），
    只有 inputSchema 校验失败与 handler 抛异常才置 True ⇒ **业务失败（含 `参数不合法`）
    一律回成 `isError=False`**，客户端与模型都**看不见失败**，于是反复重试同一错误。

    返回 `CallToolResult` 对象而非 list：SDK 对 `isinstance(results, CallToolResult)` 的路径
    **原样返回、不再包装**，故 `isError` 能透到客户端。
    """
    _确保可用()
    return _工具结果类(content=[_文本内容类(type="text", text=文本)], isError=bool(失败))


def 标准输入输出上下文():
    """返回 mcp 标准输入输出传输的上下文管理器（stdio，不监听任何端口）。"""
    _确保可用()
    return _标准输入输出函数()


def 构造标准输入输出参数(*, 命令: str, 参数表: list[str], 环境: dict, 工作目录: str):
    """构造客户端侧 stdio 启动参数（第三方对象，不契约化）。"""
    _确保可用()
    return _标准输入输出参数类(
        command=命令, args=[str(项) for 项 in 参数表], env=dict(环境), cwd=str(工作目录),
    )


def 标准输入输出客户端(参数):
    """返回客户端侧 stdio 传输的上下文管理器（第三方对象，不契约化）。"""
    _确保可用()
    return _标准输入输出客户端函数(参数)


def 构造客户端会话(读取流, 写入流):
    """构造客户端会话对象（第三方对象，不契约化）。"""
    _确保可用()
    return _客户端会话类(读取流, 写入流)
