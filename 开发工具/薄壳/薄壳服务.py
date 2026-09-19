"""系统工程平台 MCP 薄壳（stdio 传输，不监听任何端口）。

零业务语义：只做 MCP 协议翻译 + 转发唯一网关 40007（HTTP POST /网关/调用）。
暴露 3 个工具：capability_search（查询能力）/ capability_call（调用能力）/ tool_catalog（工具目录）。

直跑：`python3.14 开发工具/薄壳/薄壳服务.py`（stdio，由 MCP 客户端拉起）。
凭证：环境变量「系统库网关凭证」，只在转发请求头使用，不打印、不落盘。
"""

from __future__ import annotations
from 公共契约.基础类型.逻辑类型 import 真, 假

# 环境准入（必须在任何装配与第三方导入之前）：平台判定的唯一来源是
# `公共契约/运行时/平台适配`，本文件不自己写 sys.platform 判断。
import sys
from pathlib import Path

_薄壳目录 = Path(__file__).resolve().parent
if str(_薄壳目录) not in sys.path:
    sys.path.insert(0, str(_薄壳目录))

# 项目根入 sys.path：薄壳由 MCP 客户端按绝对路径拉起，脚本目录不是项目根。
_项目根 = _薄壳目录.parents[1]
if str(_项目根) not in sys.path:
    sys.path.insert(0, str(_项目根))

from 公共契约.运行时.平台适配 import 脚本入口准入

脚本入口准入("启动平台 MCP 薄壳")

import asyncio
import json
from pathlib import Path
from typing import Any

# MCP SDK 只经适配层提供者的包级中文入口使用：薄壳不直接依赖第三方 mcp 包。
from 支持库.适配层.MCP协议提供者 import (
    构造服务,
    构造初始化选项,
    构造文本内容,
    标准输入输出上下文,
)

from 工具清单 import 中文名到协议名, 三个工具定义, 构建工具目录, 搜索能力目标
from 网关转发 import 网关调用地址, 转发
from 待补能力清单 import 登记待补能力

服务 = 构造服务("系统工程平台_薄壳")
服务名 = "系统工程平台_薄壳"
服务版本 = "1.0.0"
# 网关表示「该能力没登记」的错误码/错误说明关键字（只做归一化，不改写业务语义）。
未注册标志 = ("能力不存在", "能力未注册")


def _包装(能力id: str, 结果: dict, 参数: dict) -> dict[str, Any]:
    """把网关返回统一成薄壳回执：保留 HTTP 状态码、信封关键字段与转发路径。"""
    信封 = 结果.get("信封") or {}
    数据: dict[str, Any] = {
        "HTTP状态码": 结果.get("HTTP状态码"),
        "转发": f"POST {网关调用地址}（操作=调用能力）",
        "能力id": 能力id,
        "成功": bool(信封.get("成功")),
        "错误码": str(信封.get("错误码", "") or 结果.get("错误码", "")),
        "错误说明": str(信封.get("错误说明", "") or 结果.get("错误说明", "")),
        "值": 信封.get("值"),
        "句柄": 信封.get("句柄"),
        "耗时毫秒": 信封.get("耗时毫秒"),
    }
    if not 信封:
        数据["成功"] = False
        数据["请检查"] = f"网关凭证来自环境变量，地址 {网关调用地址}"
    return 数据


def _项目根检查(参数: dict) -> tuple[bool, str]:
    """判断「这次调用是不是系统工程平台的」——不是就**不载入任何平台上下文**。

    华哥 2026-09-19 裁决：「如果是这个项目的就载入提示词；如果不是这个项目的，
    就直接不载入更多上下文就好了」「控制好最小体量的 token 限制」。

    判据只看一条：`项目根` 必须是**真实存在的目录**，且其下有本平台的锚文件
    （`AGENTS.md` **且** `开发文档/项目说明.md`）——两件都在才算本仓库，
    避免一个同名目录或随手传的路径把平台规则灌进无关会话。
    传空/不存在/缺锚文件 → 一律按「不是本项目」处理（fail-closed）。
    """
    传入 = str(参数.get("项目根", "") or "").strip()
    if not 传入:
        return 假, ("未传 项目根：本工具只服务系统工程平台仓库。"
                       "请传仓库绝对路径（含 AGENTS.md 与 开发文档/项目说明.md）后再调用；"
                       "非本仓库会话不要调用本工具，也不要据此载入平台上下文。")
    根 = Path(传入).expanduser()
    if not 根.is_dir():
        return 假, f"项目根不是目录：{传入}。本工具只服务系统工程平台仓库，已拒绝（未载入任何平台上下文）。"
    if not ((根 / "AGENTS.md").is_file() and (根 / "开发文档" / "项目说明.md").is_file()):
        return 假, (f"项目根缺少平台锚文件（AGENTS.md 与 开发文档/项目说明.md）：{根}。"
                       "本工具只服务系统工程平台仓库，已拒绝（未载入任何平台上下文）。")
    return 真, ""


def _查询能力(参数: dict) -> dict[str, Any]:
    """转发到唯一网关调用 搜索能力目标；未注册则报 能力未注册 并登记缺口。"""
    通过, 原因 = _项目根检查(参数)
    if not 通过:
        return {"成功": 假, "错误码": "非本平台项目根", "错误说明": 原因}
    关键词 = str(参数.get("关键词", "") or "").strip()
    if not 关键词:
        return {"成功": 假, "错误码": "参数不合法", "错误说明": "关键词必填"}
    try:
        限制 = int(参数.get("限制", 20))
    except (TypeError, ValueError):
        return {"成功": 假, "错误码": "参数不合法", "错误说明": "限制必须是整数"}
    结果 = 转发({"操作": "调用能力", "能力id": 搜索能力目标,
                "参数": {"关键词": 关键词, "限制": 限制}})
    数据 = _包装(搜索能力目标, 结果, 参数)
    未注册 = 数据["错误码"] in 未注册标志 or "能力未注册" in 数据["错误说明"]
    if not 数据["成功"] and 未注册:
        登记 = 登记待补能力(搜索能力目标, "capability_search", 数据["错误说明"])
        数据["错误码"] = "能力未注册"
        数据["错误说明"] = f"网关未注册能力 {搜索能力目标}；薄壳不自实现搜索逻辑"
        数据["待补能力清单"] = 登记
    return 数据


def _调用能力(参数: dict) -> dict[str, Any]:
    """薄壳主体：能力id + 参数 原样转发唯一网关（先校验项目根是本平台仓库）。"""
    通过, 原因 = _项目根检查(参数)
    if not 通过:
        return {"成功": 假, "错误码": "非本平台项目根", "错误说明": 原因}
    能力id = str(参数.get("能力id", "") or "").strip()
    if not 能力id:
        return {"成功": 假, "错误码": "参数不合法", "错误说明": "能力id必填"}
    入参 = 参数.get("参数")
    if 入参 is None:
        入参 = {}
    if not isinstance(入参, dict):
        return {"成功": 假, "错误码": "参数不合法", "错误说明": "参数必须是对象"}
    return _包装(能力id, 转发({"操作": "调用能力", "能力id": 能力id, "参数": 入参}), 参数)


def _工具目录(参数: dict) -> dict[str, Any]:
    return 构建工具目录()


分发表 = {
    "capability_search": _查询能力,
    "capability_call": _调用能力,
    "tool_catalog": _工具目录,
}


@服务.list_tools()
async def 工具列表() -> list:
    """薄壳只暴露 3 个工具，不按角色过滤、不注入业务工具。"""
    return list(三个工具定义)


@服务.call_tool()
async def 调用工具(名称: str, 参数: dict[str, Any]) -> list:
    协议名 = 中文名到协议名.get(str(名称), str(名称))
    处理 = 分发表.get(协议名)
    if 处理 is None:
        数据: dict[str, Any] = {"成功": 假, "错误码": "未知工具",
                              "错误说明": f"薄壳只有 3 个工具，未注册：{协议名}"}
    else:
        try:
            数据 = await asyncio.to_thread(处理, dict(参数 or {}))
        except Exception as 异常:  # 薄壳不吞异常细节以外的信息，凭证不入错误文本
            数据 = {"成功": 假, "错误码": "薄壳内部错误",
                    "错误说明": f"{type(异常).__name__}: {str(异常)[:200]}"}
    return [构造文本内容(json.dumps(数据, ensure_ascii=False, indent=2))]


async def 主程序() -> None:
    """stdio 传输：不绑定端口、不启 HTTP 服务。"""
    async with 标准输入输出上下文() as (读取流, 写入流):
        await 服务.run(读取流, 写入流, 构造初始化选项(服务名, 服务版本))


if __name__ == "__main__":
    asyncio.run(主程序())
