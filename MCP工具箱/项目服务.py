"""系统工程平台专属 MCP：项目身份、代码地图、记忆和验证证据。"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from mcp.server import Server
from mcp.server.models import InitializationOptions
from mcp.server.stdio import stdio_server
from mcp.types import ServerCapabilities, TextContent, Tool

try:
    from MCP工具箱.公开能力 import 搜索公开能力, 读取公开能力
    from MCP工具箱.使用反馈 import 写入反馈, 查询反馈状态, 读取反馈列表
    from MCP工具箱.角色权限 import (
        代码地图范围, 读取当前角色, 角色说明, 可用工具, 校验工具权限,
        校验验证命令, 获取角色指南,
    )
except ModuleNotFoundError:
    from 公开能力 import 搜索公开能力, 读取公开能力
    from 使用反馈 import 写入反馈, 查询反馈状态, 读取反馈列表
    from 角色权限 import (
        代码地图范围, 读取当前角色, 角色说明, 可用工具, 校验工具权限,
        校验验证命令, 获取角色指南,
    )

项目根目录 = Path(__file__).resolve().parent.parent
记忆目录 = 项目根目录 / "开发文档" / "项目记忆"
证据路径 = 项目根目录 / "开发文档" / "项目证据" / "验证历史.jsonl"
反馈路径 = 项目根目录 / "开发文档" / "项目证据" / "MCP使用反馈.jsonl"
服务 = Server("system_engineering_toolkit")
当前角色 = 读取当前角色()
当前实例 = {
    "调用者": "system_engineering_caller",
    "支持库开发者": "system_engineering_support_library_developer",
    "模块开发者": "system_engineering_module_developer",
    "核心开发者": "system_engineering_core_developer",
    "项目开发者": "system_engineering_project_developer",
    "平台构建开发者": "system_engineering_platform_build_developer",
    "平台维护者": "system_engineering_toolkit",
    "发布者": "system_engineering_publisher",
}[当前角色]
当前任务名称 = ""
当前开工id = ""


def _执行(
    命令: list[str], 超时秒数: int = 30, 输出上限: int = 12000,
) -> dict[str, Any]:
    try:
        结果 = subprocess.run(
            命令, cwd=项目根目录, capture_output=True, text=True,
            timeout=超时秒数, check=False,
        )
        return {
            "退出码": 结果.returncode,
            "标准输出": 结果.stdout[-输出上限:],
            "标准错误": 结果.stderr[-4000:],
        }
    except (OSError, subprocess.TimeoutExpired) as 异常:
        return {"退出码": 124, "标准输出": "", "标准错误": str(异常)}


def _代码指纹() -> tuple[str, str]:
    提交结果 = _执行(["git", "rev-parse", "HEAD"])
    状态结果 = _执行(["git", "status", "--porcelain=v1", "-z"])
    提交 = 提交结果["标准输出"].strip() if 提交结果["退出码"] == 0 else ""
    状态 = 状态结果["标准输出"] if 状态结果["退出码"] == 0 else "无版本库"
    return 提交, hashlib.sha256(状态.encode("utf-8")).hexdigest()


def _读取成功记录(数量: int = 3) -> list[dict[str, Any]]:
    if not 证据路径.is_file():
        return []
    记录列表: list[dict[str, Any]] = []
    for 行 in reversed(证据路径.read_text(encoding="utf-8").splitlines()):
        try:
            记录 = json.loads(行)
        except json.JSONDecodeError:
            continue
        if 记录.get("退出码") == 0:
            记录列表.append(记录)
        if len(记录列表) >= max(1, min(数量, 3)):
            break
    return 记录列表


def _代码地图状态() -> dict[str, Any]:
    if not (项目根目录 / ".codegraph").is_dir():
        return {"可用": False, "状态": "未初始化"}
    结果 = _执行(["codegraph", "status", str(项目根目录)], 45)
    return {
        "可用": 结果["退出码"] == 0,
        "状态": "可用" if 结果["退出码"] == 0 else "需同步",
        "详情": (结果["标准输出"] or 结果["标准错误"])[-2500:],
    }


def _开工上下文(任务: str, 历史数量: int) -> dict[str, Any]:
    global 当前任务名称, 当前开工id
    if not 当前开工id or 任务 != 当前任务名称:
        当前任务名称 = 任务
        当前开工id = uuid.uuid4().hex[:16]
    提交, 工作区指纹 = _代码指纹()
    历史 = _读取成功记录(历史数量)
    匹配数 = sum(
        记录.get("提交") == 提交 and 记录.get("工作区指纹") == 工作区指纹
        for 记录 in 历史
    )
    地图 = _代码地图状态()
    分数 = 20 + (30 if 地图["可用"] else 0) + min(50, 匹配数 * 25)
    return {
        "项目": {
            "名称": "系统工程平台", "根目录": str(项目根目录),
            "MCP实例": 当前实例, "角色门面": 当前角色,
            "任务": 任务, "开工id": 当前开工id,
        },
        "代码地图": 地图,
        "证据可信度": {
            "分数": 分数,
            "等级": "已验证" if 分数 >= 75 else "部分可信" if 分数 >= 40 else "需建立证据",
            "依据": "项目规则20 + 可用代码地图30 + 当前代码指纹匹配成功记录最多50",
            "提交": 提交, "工作区指纹": 工作区指纹, "匹配成功记录数": 匹配数,
        },
        "最近成功验证": 历史,
        "固定流程": [
            "先调用项目开工上下文", "再用代码地图探索定位符号和调用链",
            "只在地图未覆盖时直接读取文件", "代码指纹变化后只复验受影响范围",
            "收工前提交 MCP 使用反馈，再执行成功验证并记录证据",
        ],
        "探索策略": {
            "顺序": ["项目身份与角色", "能力摘要", "代码地图符号与调用链", "完整契约", "历史成功证据"],
            "默认返回": "高相关摘要，不隐藏参数、返回、错误码、权限、资源限制、版本和副作用",
            "禁止": ["一次加载全部源码", "一次加载全部说明书", "重复探索未变化的代码指纹"],
            "展开条件": "确认能力或定位目标后，按能力id、文件或符号展开完整信息",
        },
        "验证策略": {
            "工作包": "连续完成同一工作包后，只验证受影响测试；无共享资源的测试并行",
            "合并波次": "工作包合并后只验证受影响阶段；不得重复运行相同测试",
            "阶段收口": "全部工作包合并后由主协调者执行一次常规全量",
            "慢速层": "源码、依赖、环境指纹一致且证据未过期时复用；变化或故障回归才强制执行",
            "禁止": "每改一个文件就跑全量，或用缓存冒充受影响测试真实通过",
        },
        "反馈门禁": {
            "必须提交": True, "工具": "mcp_feedback",
            "字段": ["总结", "不满意", "多余", "缺失", "升级建议"],
            "说明": "无问题也要明确填写“无”；未反馈不得记录成功验证证据。",
        },
    }


def _搜索记忆(查询: str, 数量: int) -> list[dict[str, Any]]:
    查询词 = [词.lower() for 词 in 查询.split() if 词]
    结果列表: list[tuple[int, Path, str]] = []
    if not 记忆目录.is_dir():
        return []
    for 路径 in 记忆目录.glob("*.md"):
        if 路径.name.startswith("_"):
            continue
        文本 = 路径.read_text(encoding="utf-8", errors="replace")
        分数 = sum(词 in 文本.lower() for 词 in 查询词)
        if 分数:
            结果列表.append((分数, 路径, 文本))
    结果列表.sort(key=lambda 条目: (条目[0], 条目[1].stat().st_mtime), reverse=True)
    return [
        {"路径": str(路径.relative_to(项目根目录)), "分数": 分数, "摘要": 文本[:1200]}
        for 分数, 路径, 文本 in 结果列表[: max(1, min(数量, 10))]
    ]


def _写入记忆(标题: str, 正文: str, 标签: list[str]) -> dict[str, Any]:
    安全名 = "".join(字符 if 字符.isalnum() or 字符 in "-_" else "-" for 字符 in 标题).strip("-")
    if not 安全名:
        raise ValueError("标题不能为空")
    记忆目录.mkdir(parents=True, exist_ok=True)
    路径 = 记忆目录 / f"{安全名}.md"
    内容 = f"---\n名称: {标题}\n标签: [{', '.join(标签)}]\n创建时间: {datetime.now(timezone.utc).isoformat()}\n---\n\n{正文.strip()}\n"
    临时路径 = 路径.with_suffix(".md.tmp")
    临时路径.write_text(内容, encoding="utf-8")
    临时路径.replace(路径)
    return {"成功": True, "路径": str(路径.relative_to(项目根目录))}


def _运行验证(名称: str, 命令: list[str], 超时秒数: int) -> dict[str, Any]:
    if not 名称.strip() or not 命令 or any(not isinstance(项, str) or not 项 for 项 in 命令):
        raise ValueError("名称和命令数组不能为空")
    结果 = _执行(命令, max(1, min(超时秒数, 3600)))
    提交, 工作区指纹 = _代码指纹()
    记录 = {
        "名称": 名称, "命令": 命令, "退出码": 结果["退出码"],
        "时间": datetime.now(timezone.utc).isoformat(), "提交": 提交,
        "工作区指纹": 工作区指纹, "输出末尾": 结果["标准输出"][-2000:],
        "错误末尾": 结果["标准错误"][-1000:],
    }
    if 结果["退出码"] == 0:
        证据路径.parent.mkdir(parents=True, exist_ok=True)
        with 证据路径.open("a", encoding="utf-8") as 文件:
            文件.write(json.dumps(记录, ensure_ascii=False) + "\n")
    return 记录


def _过滤代码地图输出(原文: str, 范围表: list[str]) -> str:
    """仅保留允许目录的源码块，丢弃跨范围调用链和源码。"""
    匹配表 = list(re.finditer(
        r"(?m)^\*\*\x60([^\x60]+)\x60\*\*.*$", 原文,
    ))
    保留表: list[str] = []
    for 序号, 匹配 in enumerate(匹配表):
        路径 = 匹配.group(1).removeprefix("./")
        if not any(路径 == 范围 or 路径.startswith(f"{范围}/") for 范围 in 范围表):
            continue
        结束 = 匹配表[序号 + 1].start() if 序号 + 1 < len(匹配表) else len(原文)
        保留表.append(原文[匹配.start():结束].rstrip())
    if not 保留表:
        return "当前角色范围内没有匹配源码。"
    return "**角色范围内源码**\n\n" + "\n\n".join(保留表)


def _按角色探索代码(查询: str) -> dict[str, Any]:
    范围表 = 代码地图范围(当前角色)
    if not 范围表:
        raise PermissionError(f"角色 {当前角色} 没有源码查询权限")
    结果 = _执行(
        ["codegraph", "explore", 查询, "--max-files", "20"],
        60, 200000,
    )
    return {
        "退出码": 结果["退出码"],
        "标准输出": _过滤代码地图输出(结果["标准输出"], 范围表)[-48000:],
        "标准错误": 结果["标准错误"][-4000:],
        "查询范围": 范围表,
    }


def _验证计划(修改路径: list[str], 级别: str = "工作包") -> dict[str, Any]:
    """按修改范围给出定向验证建议；只规划，不执行测试。"""
    测试表 = {
        "项目适配层": "测试中心/项目适配",
        "运行核心/运行环境": "测试中心/运行核心",
        "运行核心": "测试中心/运行核心",
        "平台控制面/包仓库": "测试中心/平台控制面",
        "客户端": "测试中心/客户端",
        "支持库": "测试中心/支持库",
        "模块库": "测试中心/模块库",
        "MCP工具箱": "测试中心/MCP工具箱",
    }
    影响阶段: set[str] = set()
    for 路径 in 修改路径:
        规范路径 = str(路径).replace("\\", "/").lstrip("./")
        for 前缀, 测试目录 in 测试表.items():
            if 规范路径 == 前缀 or 规范路径.startswith(f"{前缀}/"):
                影响阶段.add(测试目录)
    目录列表 = sorted(影响阶段)
    测试命令 = []
    for 目录 in 目录列表:
        测试文件 = sorted(
            (项目根目录 / 目录).rglob("测试_*.py")
            if (项目根目录 / 目录).is_dir() else []
        )
        if 测试文件:
            测试命令.append(
                ["python3.14", "测试中心/运行测试.py", "--测试文件", *[
                    str(文件.relative_to(项目根目录)) for 文件 in 测试文件
                ], "--并行数", "0"]
            )
    if 级别 == "阶段收口":
        测试命令 = [["python3.14", "测试中心/运行测试.py"]]
    elif 级别 == "正式发布":
        测试命令 = [
            ["python3.14", "测试中心/运行测试.py", "--范围", "全部"],
            ["python3.14", "开发工具/发布门禁/运行发布门禁.py"],
        ]
    return {
        "修改路径": 修改路径,
        "验证级别": 级别,
        "受影响测试目录": 目录列表,
        "并行建议": "不同测试目录可并行；共享数据库、端口、发布指针和外部应用必须串行。",
        "建议命令": 测试命令,
        "是否需要全量": 级别 in {"阶段收口", "正式发布"},
        "说明": "本工具只生成计划，不执行验证；执行后必须用 verify_and_record 记录证据。",
    }


@服务.list_tools()
async def 工具列表() -> list[Tool]:
    工具定义 = [
        Tool(name="project_context", description="项目开工上下文：身份、代码地图、证据可信度和最近成功验证。", inputSchema={"type": "object", "properties": {"task": {"type": "string"}, "history_limit": {"type": "integer", "minimum": 1, "maximum": 3}}}),
        Tool(name="role_profile", description="返回当前 MCP 角色、可用工具及其边界。", inputSchema={"type": "object", "properties": {}}),
        Tool(name="capability_search", description="高相关只读搜索公开能力；默认返回最多5个候选，不加载实现。确认能力后再用能力id读取完整契约。", inputSchema={"type": "object", "properties": {"keyword": {"type": "string"}, "limit": {"type": "integer", "minimum": 1, "maximum": 10, "default": 5}}}),
        Tool(name="capability_read", description="只读查看一个公开能力的名称、说明、所属包和类型。", inputSchema={"type": "object", "properties": {"capability_id": {"type": "string"}}, "required": ["capability_id"]}),
        Tool(name="mcp_feedback", description="提交本次 MCP 使用反馈；成功验证入账前强制执行。", inputSchema={"type": "object", "properties": {"summary": {"type": "string"}, "dissatisfaction": {"type": "string"}, "redundant": {"type": "string"}, "missing": {"type": "string"}, "upgrade_suggestion": {"type": "string"}}, "required": ["summary", "dissatisfaction", "redundant", "missing", "upgrade_suggestion"]}),
        Tool(name="feedback_status", description="查看本次开工标识是否已提交 MCP 使用反馈。", inputSchema={"type": "object", "properties": {}}),
        Tool(name="feedback_review", description="维护者按开工id或任务读取MCP反馈与升级候选。", inputSchema={"type": "object", "properties": {"work_id": {"type": "string"}, "task": {"type": "string"}, "limit": {"type": "integer"}}}),
        Tool(name="support_library_development_guide", description="支持库开发专属流程与边界。", inputSchema={"type": "object", "properties": {}}),
        Tool(name="module_development_guide", description="模块开发专属流程与边界。", inputSchema={"type": "object", "properties": {}}),
        Tool(name="core_development_guide", description="核心开发专属流程与边界。", inputSchema={"type": "object", "properties": {}}),
        Tool(name="project_development_guide", description="项目适配开发专属流程与边界。", inputSchema={"type": "object", "properties": {}}),
        Tool(name="platform_build_development_guide", description="平台构建开发专属流程与边界。", inputSchema={"type": "object", "properties": {}}),
        Tool(name="platform_maintenance_guide", description="平台维护专属流程与边界。", inputSchema={"type": "object", "properties": {}}),
        Tool(name="release_guide", description="发布者专属审核、激活和回滚流程。", inputSchema={"type": "object", "properties": {}}),
        Tool(name="codegraph_explore", description="在系统工程平台自己的代码地图中探索符号、源码和调用链。", inputSchema={"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}),
        Tool(name="memory_search", description="搜索系统工程平台自己的项目记忆。", inputSchema={"type": "object", "properties": {"query": {"type": "string"}, "limit": {"type": "integer"}}, "required": ["query"]}),
        Tool(name="memory_write", description="写入系统工程平台自己的长期项目记忆。", inputSchema={"type": "object", "properties": {"title": {"type": "string"}, "body": {"type": "string"}, "labels": {"type": "array", "items": {"type": "string"}}}, "required": ["title", "body"]}),
        Tool(name="verify_and_record", description="不经 shell 运行验证；仅退出码为0时记入最近成功证据。", inputSchema={"type": "object", "properties": {"name": {"type": "string"}, "command": {"type": "array", "items": {"type": "string"}}, "timeout_seconds": {"type": "integer"}}, "required": ["name", "command"]}),
        Tool(name="verification_plan", description="按修改路径生成定向验证计划；只规划不执行，避免每次重复跑全量。", inputSchema={"type": "object", "properties": {"modified_paths": {"type": "array", "items": {"type": "string"}}, "level": {"type": "string", "enum": ["工作包", "合并波次", "阶段收口", "正式发布"], "default": "工作包"}}, "required": ["modified_paths"]}),
    ]
    return [工具 for 工具 in 工具定义 if 工具.name in 可用工具(当前角色)]


@服务.call_tool()
async def 调用工具(名称: str, 参数: dict[str, Any]) -> list[TextContent]:
    校验工具权限(当前角色, 名称)
    if 名称 == "project_context":
        数据 = _开工上下文(str(参数.get("task", "")), int(参数.get("history_limit", 3)))
    elif 名称 == "role_profile":
        数据 = 角色说明(当前角色)
    elif 名称 == "capability_search":
        数据 = 搜索公开能力(
            项目根目录, str(参数.get("keyword", "")), int(参数.get("limit", 5)),
        )
    elif 名称 == "capability_read":
        数据 = 读取公开能力(项目根目录, str(参数["capability_id"]))
        if 数据 is None:
            数据 = {"成功": False, "错误码": "CAPABILITY_NOT_FOUND", "消息": "公开能力不存在"}
    elif 名称 == "mcp_feedback":
        数据 = 写入反馈(
            反馈路径, 开工id=当前开工id, 任务=当前任务名称, 角色=当前角色,
            总结=str(参数["summary"]), 不满意=str(参数["dissatisfaction"]),
            多余=str(参数["redundant"]), 缺失=str(参数["missing"]),
            升级建议=str(参数["upgrade_suggestion"]),
        )
    elif 名称 == "feedback_status":
        数据 = 查询反馈状态(反馈路径, 当前开工id)
    elif 名称 == "feedback_review":
        数据 = 读取反馈列表(
            反馈路径, 开工id=str(参数.get("work_id", "")),
            任务=str(参数.get("task", "")), 数量=int(参数.get("limit", 20)),
        )
    elif 名称 in {
        "support_library_development_guide", "module_development_guide",
        "core_development_guide", "platform_maintenance_guide", "release_guide",
        "project_development_guide", "platform_build_development_guide",
    }:
        数据 = 获取角色指南(当前角色)
    elif 名称 == "codegraph_explore":
        数据 = _按角色探索代码(str(参数["query"]))
    elif 名称 == "memory_search":
        数据 = _搜索记忆(str(参数["query"]), int(参数.get("limit", 5)))
    elif 名称 == "memory_write":
        数据 = _写入记忆(str(参数["title"]), str(参数["body"]), list(参数.get("labels", [])))
    elif 名称 == "verification_plan":
        数据 = _验证计划(list(参数.get("modified_paths", [])), str(参数.get("level", "工作包")))
    elif 名称 == "verify_and_record":
        if not 查询反馈状态(反馈路径, 当前开工id)["已反馈"]:
            raise PermissionError("本次任务尚未提交 MCP 使用反馈，不能记录成功验证证据")
        校验验证命令(当前角色, list(参数["command"]))
        数据 = _运行验证(str(参数["name"]), list(参数["command"]), int(参数.get("timeout_seconds", 300)))
    else:
        raise ValueError(f"未知工具：{名称}")
    return [TextContent(type="text", text=json.dumps(数据, ensure_ascii=False, indent=2))]


async def 主程序() -> None:
    async with stdio_server() as (读取流, 写入流):
        await 服务.run(
            读取流, 写入流,
            InitializationOptions(
                server_name="system_engineering_toolkit", server_version="1.0.0",
                capabilities=ServerCapabilities(tools={}),
            ),
        )


if __name__ == "__main__":
    asyncio.run(主程序())
