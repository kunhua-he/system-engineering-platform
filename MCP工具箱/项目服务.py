"""系统工程平台专属 MCP：项目身份、代码地图、记忆和验证证据。"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import subprocess
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from mcp.server import Server
from mcp.server.models import InitializationOptions
from mcp.server.stdio import stdio_server
from mcp.types import ServerCapabilities, TextContent, Tool

from 公共契约.运行时.有界IO import (
    默认JSONL读取上限字节, 默认JSONL读取上限记录, 读取JSONL,
)
from .工具名映射 import 中文名到协议名, 协议名到中文名
from .公开能力 import 搜索公开能力, 读取公开能力
from .使用反馈 import 写入反馈, 查询反馈状态, 读取反馈列表
from .临时上下文 import 写入临时上下文, 读取临时上下文, 清理临时上下文, 清理过期上下文, 核对修改范围
from .任务观测 import 任务开始, 工具事件, 任务结束, 查询任务, 阶段记录, 生成效率报告
from .工作区管理 import 创建工作区, 查询工作区, 关闭工作区, 合并分支, 工作区提交
from .测试资源 import 登记资源, 清理资源
from .支持库协作 import 登记需求, 复用搜索, 登记能力占用
from .模块合规 import 校验模块合规
from .核心治理 import 创建核心快照, 查询核心快照, 兼容性检查, 回滚门禁
from .发布治理 import (
    运行发布门禁, 检查发布证据, 生成发布证据, 切换激活指针, 依赖裁决,
    读取正式发布状态, 正式发布证据类型,
)
from .协作状态 import 登记任务, 查询协作状态, 收口登记, 计算代码指纹
from .文件租约 import (
    申请文件租约, 续租文件租约, 释放文件租约, 释放工作包文件租约,
    回收过期文件租约, 查询文件占用,
)
from .验证门禁 import (
    校验验证命令 as 校验验证命令受控, 判定验证结果, 反馈门禁,
    正式发布命令表, 唯一发布命令, 判定正式发布结果,
)
from .角色权限 import 获取角色指南, 网关实例名, 网关角色名, 网关说明
from .热重载 import 扫描并重载工具模块

项目根目录 = Path(__file__).resolve().parent.parent
记忆目录 = 项目根目录 / "开发文档" / "项目记忆"
证据路径 = 项目根目录 / "开发文档" / "项目证据" / "验证历史.jsonl"
反馈路径 = 项目根目录 / "开发文档" / "项目证据" / "MCP使用反馈.jsonl"
临时上下文目录 = 项目根目录 / "工程缓存" / "MCP临时上下文"
观测路径 = 项目根目录 / "工程缓存" / "MCP任务观测" / "事件.jsonl"
工程缓存目录 = 项目根目录 / "工程缓存"
工作区根目录 = 项目根目录 / "工程缓存" / "任务工作区"
测试资源清单目录 = 项目根目录 / "工程缓存" / "测试资源清单"
协作状态目录 = 项目根目录 / "工程缓存" / "协作状态"
平台控制面目录 = 项目根目录 / "工程缓存" / "平台控制面"
服务 = Server("system_engineering_toolkit")
# 单网关（无角色）模式：8766 单一对外网关，不再读取角色环境变量。
当前任务名称 = ""
当前开工id = ""


def _保留输出(文本: str, 上限: int) -> str:
    """保留输出首尾，避免错误/零测试标记位于截断中段而被判定器漏掉。"""
    文本 = str(文本 or "")
    上限 = max(2000, int(上限))
    if len(文本) <= 上限:
        return 文本
    首部 = 上限 // 2
    尾部 = 上限 - 首部
    return 文本[:首部] + "\n...[输出中段已省略]...\n" + 文本[-尾部:]


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
            "标准输出": _保留输出(结果.stdout, 输出上限),
            "标准错误": _保留输出(结果.stderr, 4000),
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
    全部记录, _ = 读取JSONL(
        证据路径, 最大字节数=默认JSONL读取上限字节,
        最大记录数=默认JSONL读取上限记录,
    )
    记录列表 = [记录 for 记录 in reversed(全部记录) if 记录.get("退出码") == 0]
    return 记录列表[: max(1, min(数量, 3))]


def _代码地图状态() -> dict[str, Any]:
    if not (项目根目录 / ".codegraph").is_dir():
        return {"可用": False, "状态": "未初始化"}
    结果 = _执行(["codegraph", "status", str(项目根目录)], 45)
    return {
        "可用": 结果["退出码"] == 0,
        "状态": "可用" if 结果["退出码"] == 0 else "需同步",
        "详情": (结果["标准输出"] or 结果["标准错误"])[-2500:],
    }


def _工作区快照() -> dict[str, Any]:
    分支 = _执行(["git", "branch", "--show-current"])
    状态 = _执行(["git", "-c", "core.quotePath=false", "status", "--short"])
    工作树 = _执行(["git", "worktree", "list", "--porcelain"])
    脏文件 = [行 for 行 in 状态["标准输出"].splitlines() if 行.strip()]
    return {"当前分支": 分支["标准输出"].strip(), "脏文件数": len(脏文件),
            "脏文件": 脏文件[:100], "工作树": 工作树["标准输出"].strip(),
            "提示": "并行工作包必须使用独立worktree；同阶段共享文件发生变化时重新读取后再编辑。"}


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
            "MCP实例": 网关实例名, "角色门面": "单网关（无角色）",
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
        "工作区快照": _工作区快照(),
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


def _运行验证(名称: str, 命令: list[str], 超时秒数: int, *, 开工id: str = "") -> dict[str, Any]:
    if not 名称.strip() or not 命令 or any(not isinstance(项, str) or not 项 for 项 in 命令):
        raise ValueError("名称和命令数组不能为空")
    结果 = _执行(命令, max(1, min(超时秒数, 3600)))
    提交, 工作区指纹 = _代码指纹()
    # 同时写两种指纹：`工作区指纹` 是 sha256(git status)（发布证据路径用），
    # `指纹` 是 `计算代码指纹` 的目录内容摘要前 16 位——收口登记（delivery_closeout）
    # 读的正是后者。此前只写前者，两者取值域不同导致收口恒报「证据指纹不匹配」。
    内容指纹结果 = 计算代码指纹(项目根目录)
    记录 = {
        "名称": 名称, "命令": 命令, "退出码": 结果["退出码"], "开工id": 开工id,
        "时间": datetime.now(timezone.utc).isoformat(), "提交": 提交,
        "工作区指纹": 工作区指纹, "输出末尾": 结果["标准输出"][-2000:],
        "错误末尾": 结果["标准错误"][-1000:],
        "指纹": str(内容指纹结果.get("指纹", "")) if 内容指纹结果.get("成功") else "",
    }
    # 退出码为 0 只代表进程正常结束，不能证明测试真的通过；统一判定器
    # 还会拒绝零测试、导入失败、未解释跳过和门禁失败。只有两者同时成立
    # 才能写入可复用的成功验证证据，避免账本被“正常退出但实际失败”污染。
    判定器 = 判定正式发布结果 if tuple(命令) == 唯一发布命令 else 判定验证结果
    判定 = 判定器(
        int(结果["退出码"]),
        str(结果.get("标准输出", "")),
        str(结果.get("标准错误", "")),
    )
    记录["判定"] = 判定
    if 结果["退出码"] == 0 and 判定.get("成功") is True:
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
        return "查询范围内没有匹配源码。"
    return "**查询范围内源码**\n\n" + "\n\n".join(保留表)


def _有效开工id(候选: object) -> str:
    """只允许当前开工id或已登记子任务（临时上下文存在或协作状态已登记）。"""
    开工id = str(候选 or 当前开工id)
    if not 开工id:
        raise PermissionError("尚未建立开工上下文")
    if 开工id == 当前开工id:
        return 开工id
    if 读取临时上下文(临时上下文目录, 开工id).get("成功"):
        return 开工id
    if (协作状态目录 / f"{开工id}.json").is_file():
        return 开工id
    raise PermissionError("只能操作当前任务或已登记子任务")


# 单网关模式代码地图探索范围：全部正式目录（无角色过滤）。
全部目录表 = [
    "公共契约", "平台控制面", "启动监督器", "运行核心", "前端核心", "后端核心",
    "支持库", "模块库", "项目适配层", "开发工具", "测试中心", "示例项目",
]


def _探索代码(查询: str) -> dict[str, Any]:
    """网关直通探索代码地图：单网关模式不设角色范围限制。"""
    结果 = _执行(
        ["codegraph", "explore", 查询, "--max-files", "20"],
        60, 200000,
    )
    return {
        "退出码": 结果["退出码"],
        "标准输出": 结果["标准输出"][-48000:],
        "标准错误": 结果["标准错误"][-4000:],
        "查询范围": list(全部目录表),
    }


def _验证计划(修改路径: list[str], 级别: str = "工作包", *, 制品: str = "") -> dict[str, Any]:
    """按修改范围给出定向验证建议；正式发布命令与白名单、证据同源。"""
    目录表 = {
        "项目适配层": "测试中心/项目适配",
        "运行核心/运行环境": "测试中心/运行核心",
        "运行核心": "测试中心/运行核心",
        "平台控制面/包仓库": "测试中心/平台控制面",
        "客户端": "测试中心/客户端",
        "支持库": "测试中心/支持库",
        "模块库": "测试中心/模块库",
        "MCP工具箱": "测试中心/MCP工具箱",
    }
    精确测试关键词 = {
        "强制校验": "测试_强制校验.py",
        "传递闭包": "测试_项目锁传递闭包.py",
        "平台客户端制品": "测试_平台客户端制品接入.py",
        "唯一能力调用": "测试_唯一能力调用.py",
        "项目服务": "测试_项目服务.py",
    }
    影响阶段: set[str] = set()
    精确测试: set[Path] = set()
    for 路径 in 修改路径:
        规范路径 = str(路径).replace("\\", "/").lstrip("./")
        for 关键词, 测试名 in 精确测试关键词.items():
            if 关键词 in 规范路径:
                精确测试.update(测试中心路径 for 测试中心路径 in [
                    项目根目录 / "测试中心" / 测试名,
                    项目根目录 / "测试中心" / "运行核心" / 测试名,
                    项目根目录 / "测试中心" / "项目适配" / 测试名,
                    项目根目录 / "测试中心" / "平台控制面" / 测试名,
                    项目根目录 / "测试中心" / "MCP工具箱" / 测试名,
                ] if 测试中心路径.is_file())
        for 前缀, 测试目录 in 目录表.items():
            if 规范路径 == 前缀 or 规范路径.startswith(f"{前缀}/"):
                影响阶段.add(测试目录)
    目录列表 = sorted(影响阶段)
    测试命令 = []

    def 精确模块命令(文件: Path) -> list[str]:
        相对 = 文件.relative_to(项目根目录).with_suffix("")
        if any(not 段.isidentifier() for 段 in 相对.parts):
            raise ValueError(f"测试路径不能转换为精确模块: {相对}")
        return ["python3.14", "-m", ".".join(相对.parts)]

    if 精确测试:
        测试命令.extend(精确模块命令(文件) for 文件 in sorted(精确测试))
    else:
        for 目录 in 目录列表:
            测试文件 = sorted(
                (项目根目录 / 目录).rglob("测试_*.py")
                if (项目根目录 / 目录).is_dir() else []
            )
            if not 测试文件:
                continue
            测试命令.extend(精确模块命令(文件) for 文件 in 测试文件)
    if 级别 == "阶段收口":
        测试命令 = [正式发布命令表(制品)[0]] if 制品 else []
    elif 级别 == "正式发布":
        测试命令 = 正式发布命令表(制品)
    return {
        "修改路径": 修改路径,
        "验证级别": 级别,
        "受影响测试目录": 目录列表,
        "并行建议": "不同测试目录可并行；共享数据库、端口、发布指针和外部应用必须串行。",
        "建议命令": 测试命令,
        "是否需要全量": 级别 == "正式发布",
        "说明": ("阶段收口缺少编译制品，拒绝生成验证命令。" if 级别 == "阶段收口" and not 制品
                 else "本工具只生成计划，不执行验证；执行后必须用 verify_and_record 记录证据。"),
    }


def _统一开发入口(
    任务: str, 修改路径: list[str], 级别: str, 历史数量: int, 制品: str = "",
) -> dict[str, Any]:
    """一次返回开工上下文和验证计划，避免Agent重复调用元工具。"""
    上下文 = _开工上下文(任务, 历史数量)
    清理过期上下文(临时上下文目录)
    任务开始(观测路径, 任务id=上下文["项目"]["开工id"],
            开工id=上下文["项目"]["开工id"], 角色=网关角色名)
    计划 = _验证计划(修改路径, 级别, 制品=制品)
    return {
        "开工上下文": 上下文,
        "验证计划": 计划,
        "下一步": [
            "按网关直通使用代码地图定位",
            "连续完成同一工作包，不逐文件跑全量",
            "工作包完成后按验证计划并行执行",
            "收工前提交MCP反馈，再记录成功证据",
        ],
    }


# 全量工具定义（唯一权威）：精简注入只过滤此表，工具目录(tool_catalog) 按此表发现。
_工具定义列表 = [
    Tool(name="project_context", description="项目开工上下文：身份、代码地图、证据可信度和最近成功验证。", inputSchema={"type": "object", "properties": {"task": {"type": "string"}, "history_limit": {"type": "integer", "minimum": 1, "maximum": 3}}}),
        Tool(name="role_profile", description="返回当前 MCP 角色、可用工具及其边界。", inputSchema={"type": "object", "properties": {}}),
        Tool(name="capability_search", description="高相关只读搜索公开能力；默认返回最多5个候选，不加载实现。确认能力后再用能力id读取完整契约。", inputSchema={"type": "object", "properties": {"keyword": {"type": "string"}, "limit": {"type": "integer", "minimum": 1, "maximum": 10, "default": 5}}}),
        Tool(name="capability_read", description="只读查看一个公开能力的名称、说明、所属包和类型。", inputSchema={"type": "object", "properties": {"capability_id": {"type": "string"}}, "required": ["capability_id"]}),
        Tool(name="mcp_feedback", description="提交当前任务或有效子任务的MCP反馈；成功验证入账前强制执行。", inputSchema={"type": "object", "properties": {"work_id": {"type": "string"}, "summary": {"type": "string"}, "dissatisfaction": {"type": "string"}, "redundant": {"type": "string"}, "missing": {"type": "string"}, "upgrade_suggestion": {"type": "string"}}, "required": ["summary", "dissatisfaction", "redundant", "missing", "upgrade_suggestion"]}),
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
        Tool(name="verify_and_record", description="不经shell运行受控验证；唯一发布入口还会生成专用正式发布证据。", inputSchema={"type": "object", "properties": {"work_id": {"type": "string"}, "name": {"type": "string"}, "command": {"type": "array", "items": {"type": "string"}}, "timeout_seconds": {"type": "integer"}, "artifact_digest": {"type": "string"}, "source_fingerprint": {"type": "string"}, "capability_coverage": {"type": "array", "items": {"type": "string"}}, "scenario_coverage": {"type": "object"}, "real_result": {"type": "object"}}, "required": ["name", "command"]}),
        Tool(name="verification_plan", description="按修改路径生成验证计划；正式发布仅含受控HTML和唯一发布入口。", inputSchema={"type": "object", "properties": {"modified_paths": {"type": "array", "items": {"type": "string"}}, "level": {"type": "string", "enum": ["工作包", "合并波次", "阶段收口", "正式发布"], "default": "工作包"}, "artifact": {"type": "string"}}, "required": ["modified_paths"]}),
        Tool(name="development_start", description="开发统一开工入口：一次返回项目上下文、代码地图状态、可信证据和受影响测试计划。", inputSchema={"type": "object", "properties": {"task": {"type": "string"}, "modified_paths": {"type": "array", "items": {"type": "string"}}, "level": {"type": "string", "enum": ["工作包", "合并波次", "阶段收口", "正式发布"], "default": "工作包"}, "artifact": {"type": "string"}, "history_limit": {"type": "integer", "minimum": 1, "maximum": 3, "default": 3}}, "required": ["task"]}),
        Tool(name="temporary_context", description="读取、写入、核对或清理子任务临时上下文。", inputSchema={"type": "object", "properties": {"operation": {"type": "string", "enum": ["写入", "读取", "核对范围", "清理"]}, "work_id": {"type": "string"}, "parent_task": {"type": "string"}, "role": {"type": "string"}, "allowed_paths": {"type": "array", "items": {"type": "string"}}, "actual_paths": {"type": "array", "items": {"type": "string"}}, "memory_queries": {"type": "array", "items": {"type": "string"}}, "confirmed_facts": {"type": "array", "items": {"type": "string"}}, "verification_commands": {"type": "array", "items": {"type": "array", "items": {"type": "string"}}}, "ttl_seconds": {"type": "integer"}}, "required": ["operation", "work_id"]}),
        Tool(name="task_observation", description="被动记录任务、阶段与工具耗时，并生成效率报告；不记录提示词或源码。", inputSchema={"type": "object", "properties": {"operation": {"type": "string", "enum": ["开始", "结束", "查询", "阶段开始", "阶段结束", "报告"]}, "task_id": {"type": "string"}, "work_id": {"type": "string"}, "parent_task_id": {"type": "string"}, "success": {"type": "boolean"}, "error_code": {"type": "string"}, "child_count": {"type": "integer"}, "phase": {"type": "string", "enum": ["探索", "开发", "子代理", "测试", "等待", "合并", "收口"]}, "phase_id": {"type": "string"}, "note": {"type": "string"}}, "required": ["operation", "task_id"]}),
        Tool(name="workspace", description="创建、查询、提交、合并和关闭隔离Git worktree。", inputSchema={"type": "object", "properties": {"operation": {"type": "string", "enum": ["创建", "查询", "提交", "合并", "关闭"]}, "task_id": {"type": "string"}, "path": {"type": "string"}, "base": {"type": "string"}, "target_branch": {"type": "string"}, "source_branch": {"type": "string"}, "message": {"type": "string"}, "paths": {"type": "array", "items": {"type": "string"}}, "force": {"type": "boolean"}}, "required": ["operation"]}),
        Tool(name="test_resource", description="按开工id登记或清理测试临时资源；只允许清理临时根目录内且未标记保留的资源。", inputSchema={"type": "object", "properties": {"work_id": {"type": "string"}, "operation": {"type": "string", "enum": ["登记", "清理"]}, "resource_path": {"type": "string"}, "temp_root": {"type": "string"}, "resource_type": {"type": "string"}, "keep": {"type": "boolean"}}, "required": ["operation", "temp_root"]}),
        Tool(name="register_requirement", description="登记需求：登记平台能力需求快照（能力id/说明/来源任务）。", inputSchema={"type": "object", "properties": {"能力id": {"type": "string"}, "说明": {"type": "string"}, "来源任务": {"type": "string"}, "work_id": {"type": "string"}}, "required": ["能力id", "说明"]}),
        Tool(name="reuse_search", description="复用搜索：扫描既有支持库能力，返回可复用候选或标记无现成。", inputSchema={"type": "object", "properties": {"关键词": {"type": "string"}, "limit": {"type": "integer"}}, "required": ["关键词"]}),
        Tool(name="claim_capability", description="登记能力占用：登记某能力由某提供包占用；异包重复占用冲突拒绝。", inputSchema={"type": "object", "properties": {"能力id": {"type": "string"}, "提供包id": {"type": "string"}, "开工id": {"type": "string"}}, "required": ["能力id", "提供包id"]}),
        Tool(name="validate_module_compliance", description="校验模块合规：模块合规验证：权威 13 项组件合规 + 模块专属边界审计（支持库/提供者物理导入、直接I/O、tempfile、subprocess、socket、数据库、动态import 等）。", inputSchema={"type": "object", "properties": {"模块名": {"type": "string"}}, "required": ["模块名"]}),
        Tool(name="generate_module_template", description="生成模块模板：唯一模块模板生成器：按 模块名/类型(基础模块|功能模块)/能力清单/依赖能力清单 生成 聚合契约+包声明+经调用器实现骨架+对称入口+完整性摘要。", inputSchema={"type": "object", "properties": {"模块名": {"type": "string"}, "类型": {"type": "string", "enum": ["基础模块", "功能模块"]}, "能力清单": {"type": "array", "items": {"type": "object"}}, "依赖能力清单": {"type": "array", "items": {"type": "object"}}}, "required": ["模块名", "能力清单"]}),
        Tool(name="create_core_snapshot", description="创建核心快照：创建核心快照（运行核心+公共契约清单与摘要，入工程缓存）。", inputSchema={"type": "object", "properties": {"说明": {"type": "string"}}}),
        Tool(name="query_core_snapshot", description="查询核心快照：列出核心快照（时间/摘要/文件数）。", inputSchema={"type": "object", "properties": {}}),
        Tool(name="compatibility_check", description="兼容性检查：对比当前与快照的兼容性：漂移与资源预算（行数上限）。", inputSchema={"type": "object", "properties": {"快照标识": {"type": "string"}}, "required": ["快照标识"]}),
        Tool(name="rollback_gate", description="回滚门禁：校验快照完整性并原子切换激活指针回滚（不覆盖源码）。", inputSchema={"type": "object", "properties": {"快照标识": {"type": "string"}, "执行回滚": {"type": "boolean"}}, "required": ["快照标识"]}),
        Tool(name="run_release_gate", description="运行发布门禁：真实运行平台发布门禁（运行发布门禁.py）。", inputSchema={"type": "object", "properties": {"包目录": {"type": "string"}}}),
        Tool(name="check_release_evidence", description="只读正式发布唯一事实源，返回制品、覆盖、真实结果、提交和工作区指纹。", inputSchema={"type": "object", "properties": {"提交": {"type": "string"}, "工作区指纹": {"type": "string"}}}),
        Tool(name="generate_release_evidence", description="禁止独立伪造正式发布证据；必须改用 verify_and_record 真实执行唯一发布命令。", inputSchema={"type": "object", "properties": {"提交": {"type": "string"}, "名称": {"type": "string"}, "退出码": {"type": "integer"}, "指纹": {"type": "string"}, "制品摘要": {"type": "string"}, "来源指纹": {"type": "string"}, "能力覆盖": {"type": "array", "items": {"type": "string"}}, "场景覆盖": {"type": "object"}, "真实结果": {"type": "object"}, "状态": {"type": "string"}}, "required": ["提交", "名称", "退出码", "指纹", "制品摘要", "来源指纹", "能力覆盖", "场景覆盖", "真实结果", "状态"]}),
        Tool(name="switch_active_pointer", description="完成制品、清单、签名、信任、正式证据和来源校验后 CAS 切换。", inputSchema={"type": "object", "properties": {"目标摘要": {"type": "string"}, "旧令牌": {"type": "string"}, "提交": {"type": "string"}, "来源指纹": {"type": "string"}, "工作区指纹": {"type": "string"}}, "required": ["目标摘要", "旧令牌", "提交", "来源指纹"]}),
        Tool(name="dependency_arbitration", description="依赖裁决：校验包声明依赖闭包（缺项/多余/版本漂移/循环）。", inputSchema={"type": "object", "properties": {"包id": {"type": "string"}}, "required": ["包id"]}),
        Tool(name="register_task", description="登记任务：登记主/子任务协作状态（parent/child 映射）。", inputSchema={"type": "object", "properties": {"work_id": {"type": "string"}, "任务": {"type": "string"}, "角色": {"type": "string"}, "worktree路径": {"type": "string"}, "允许路径": {"type": "array", "items": {"type": "string"}}, "基线提交": {"type": "string"}, "parent_work_id": {"type": "string"}}, "required": ["work_id", "任务"]}),
        Tool(name="collaboration_status", description="协作状态：按开工id或任务查询协作状态（子任务/反馈/证据/阻断标记）。", inputSchema={"type": "object", "properties": {"work_id": {"type": "string"}, "任务": {"type": "string"}}}),
        Tool(name="delivery_closeout", description="收口登记：delivery_closeout：收口登记五件套与结论；未反馈或证据不匹配阻断。", inputSchema={"type": "object", "properties": {"work_id": {"type": "string"}, "五件套路径": {"type": "string"}, "结论": {"type": "string"}}, "required": ["work_id"]}),
        Tool(name="file_lease", description="文件占用租约：多会话同仓开发时按文件原子互斥认领（复用平台控制面占用租约，不建新表）。开工自动申请、收口自动释放；本工具做查询、续租、手动释放与过期回收。", inputSchema={"type": "object", "properties": {"operation": {"type": "string", "enum": ["查询", "续租", "释放", "回收过期"]}, "paths": {"type": "array", "items": {"type": "string"}}, "lease_ids": {"type": "array", "items": {"type": "string"}}, "evidence": {"type": "string"}}, "required": ["operation"]}),
        Tool(name="validate_verification_command", description="校验验证命令：受控模块验证命令白名单校验（仅允许 unittest 模块入口，禁 shell/逃逸/无限超时）。", inputSchema={"type": "object", "properties": {"命令": {"type": "array", "items": {"type": "string"}}}, "required": ["命令"]}),
        Tool(name="judge_verification_result", description="判定验证结果：判定验证退出码/输出：收集错误/零测试/未解释跳过检出。", inputSchema={"type": "object", "properties": {"退出码": {"type": "integer"}, "标准输出": {"type": "string"}}, "required": ["退出码", "标准输出"]}),
    Tool(name="tool_catalog", description="工具目录：按 分类/关键词 返回全量工具清单（中文名+协议名+描述+分类+当前实例可调用性），用于发现未直接注入的工具。", inputSchema={"type": "object", "properties": {"分类": {"type": "string"}, "关键词": {"type": "string"}}}),
    Tool(name="reload_tool_modules", description="热重载工具模块：比对 MCP工具箱 下工具源码时间戳，重载变化的模块；改工具实现后免重启进程即时生效（新增/删除工具与参数表变更仍需重启）。", inputSchema={"type": "object", "properties": {}}),
]


@服务.list_tools()
async def 工具列表() -> list[Tool]:
    # 单网关模式：全部工具直通注入，不按角色过滤。
    return list(_工具定义列表)


# 工具目录分类：按 14 个模块域划分，覆盖全部全量工具。
_工具分类表 = {
    "基础": ["project_context", "role_profile", "mcp_feedback", "feedback_status",
             "feedback_review", "tool_catalog", "reload_tool_modules"],
    "公开能力": ["capability_search", "capability_read"],
    "开发": ["codegraph_explore", "support_library_development_guide",
             "module_development_guide", "core_development_guide",
             "project_development_guide", "platform_build_development_guide",
             "platform_maintenance_guide", "release_guide"],
    "支持库": ["register_requirement", "reuse_search", "claim_capability"],
    "模块": ["validate_module_compliance", "generate_module_template"],
    "核心": ["create_core_snapshot", "query_core_snapshot", "compatibility_check", "rollback_gate"],
    "发布": ["run_release_gate", "check_release_evidence", "generate_release_evidence", "switch_active_pointer", "dependency_arbitration"],
    "协作": ["register_task", "collaboration_status", "delivery_closeout", "file_lease"],
    "记忆": ["memory_search", "memory_write"],
    "验证": ["verify_and_record", "verification_plan", "validate_verification_command", "judge_verification_result"],
    "工作区": ["workspace", "development_start"],
    "临时上下文": ["temporary_context"],
    "任务观测": ["task_observation"],
    "测试资源": ["test_resource"],
}


def _结果转字典(结果: Any) -> dict[str, Any]:
    """发布治理.结果 dataclass → 可 JSON 序列化字典（S6：json.dumps 无法序列化 dataclass）。"""
    return {
        "成功": 结果.成功,
        "错误码": 结果.错误码,
        "消息": 结果.消息,
        "数据": 结果.数据,
    }


def _工具目录(分类: str = "", 关键词: str = "") -> dict[str, Any]:
    """只读返回工具清单（中文名+协议名+描述），不加载实现、不触碰项目资源。"""
    定义表 = {工具.name: 工具 for 工具 in _工具定义列表}
    可调用集 = set(定义表)  # 单网关模式：全部工具对网关调用者开放
    条目表: list[dict[str, Any]] = []
    已覆盖: set[str] = set()
    for 分类名, 工具名表 in _工具分类表.items():
        if 分类 and 分类 != 分类名:
            continue
        for 工具名 in 工具名表:
            if 工具名 not in 定义表:
                continue
            定义 = 定义表[工具名]
            if 关键词 and 关键词 not in 工具名 and 关键词 not in 定义.description:
                continue
            条目表.append({
                "中文名": 协议名到中文名.get(工具名, 工具名), "协议名": 工具名, "描述": 定义.description,
                "分类": 分类名, "当前实例可调用": 工具名 in 可调用集,
            })
            已覆盖.add(工具名)
    # 未分类归属的工具兜底列出（通常为空；保证全量清单完整）
    if not 分类 and not 关键词:
        for 工具名 in sorted(set(定义表) - 已覆盖):
            定义 = 定义表[工具名]
            条目表.append({
                "中文名": 协议名到中文名.get(工具名, 工具名), "协议名": 工具名, "描述": 定义.description,
                "分类": "未分类", "当前实例可调用": 工具名 in 可调用集,
            })
    return {
        "分类": 分类 or "全部",
        "关键词": 关键词,
        "条目数": len(条目表),
        "当前实例": 网关实例名,
        "当前实例可用工具数": len(可调用集),
        "工具清单": 条目表,
        "提示": "单网关模式：全部工具对网关调用者开放；未知工具名与越界路径仍默认拒绝。",
    }


@服务.call_tool()
async def 调用工具(名称: str, 参数: dict[str, Any]) -> list[TextContent]:
    # 改 MCP工具箱 下工具代码后免重启：入口按源码时间戳增量重载（详见 热重载.py）。
    本次重载 = 扫描并重载工具模块(Path(__file__).parent, globals(), {Path(__file__).name})
    # 兼容：调用方可能用中文名，统一归一化为英文协议名再分发。
    名称 = 中文名到协议名.get(名称, 名称)
    if 名称 == "tool_catalog":
        # 工具目录是只读发现工具：不触碰项目资源，直接返回全量清单。
        数据 = _工具目录(str(参数.get("分类", "")), str(参数.get("关键词", "")))
        工具事件(观测路径, 任务id=str(参数.get("task_id") or 当前开工id),
                开工id=当前开工id, 工具=名称, 开始单调=time.monotonic())
        return [TextContent(type="text", text=json.dumps(数据, ensure_ascii=False, indent=2))]
    观测开始 = time.monotonic()
    观测任务id = str(参数.get("task_id") or 当前开工id)
    事件开工id = 当前开工id
    if 名称 in {"mcp_feedback", "task_observation", "test_resource", "verify_and_record"}:
        事件开工id = _有效开工id(参数.get("work_id"))
    try:
        if 名称 == "project_context":
            数据 = _开工上下文(str(参数.get("task", "")), int(参数.get("history_limit", 3)))
        elif 名称 == "reload_tool_modules":
            数据 = {
                "成功": True,
                "本次重载模块": 本次重载,
                "重载数量": len(本次重载),
                "说明": "已即时生效，无需重启" if 本次重载 else "无变化（源码未改动）",
            }
        elif 名称 == "role_profile":
            数据 = {
                **网关说明(),
                "可用工具": sorted(定义.name for 定义 in _工具定义列表),
                "可用工具数": len(_工具定义列表),
            }
        elif 名称 == "capability_search":
            数据 = 搜索公开能力(
                项目根目录, str(参数.get("keyword", "")), int(参数.get("limit", 5)),
            )
        elif 名称 == "capability_read":
            数据 = 读取公开能力(项目根目录, str(参数["capability_id"]))
            if 数据 is None:
                数据 = {"成功": False, "错误码": "CAPABILITY_NOT_FOUND", "消息": "公开能力不存在"}
        elif 名称 == "mcp_feedback":
            反馈开工id = str(参数.get("work_id") or 当前开工id)
            if not 反馈开工id:
                raise PermissionError("尚未建立开工上下文")
            数据 = 写入反馈(
                反馈路径, 开工id=反馈开工id, 任务=当前任务名称, 角色=网关角色名,
                总结=str(参数["summary"]), 不满意=str(参数["dissatisfaction"]),
                多余=str(参数["redundant"]), 缺失=str(参数["missing"]),
                升级建议=str(参数["upgrade_suggestion"]),
            )
        elif 名称 == "feedback_status":
            数据 = 查询反馈状态(反馈路径, 当前开工id)
        elif 名称 == "feedback_review":
            # 审阅只能针对当前任务或已登记子任务；空 work_id 不得退化为全量读取。
            审阅开工id = _有效开工id(参数.get("work_id"))
            数据 = 读取反馈列表(
                反馈路径, 开工id=审阅开工id,
                任务=str(参数.get("task", "")), 数量=int(参数.get("limit", 20)),
            )
        elif 名称 in {
            "support_library_development_guide", "module_development_guide",
            "core_development_guide", "platform_maintenance_guide", "release_guide",
            "project_development_guide", "platform_build_development_guide",
        }:
            # 单网关模式：指南工具统一返回网关说明。
            数据 = 获取角色指南(名称)
        elif 名称 == "codegraph_explore":
            数据 = _探索代码(str(参数["query"]))
        elif 名称 == "memory_search":
            数据 = _搜索记忆(str(参数["query"]), int(参数.get("limit", 5)))
        elif 名称 == "memory_write":
            数据 = _写入记忆(str(参数["title"]), str(参数["body"]), list(参数.get("labels", [])))
        elif 名称 == "verification_plan":
            修改路径 = list(参数.get("modified_paths", []))
            数据 = _验证计划(
                修改路径, str(参数.get("level", "工作包")),
                制品=str(参数.get("artifact", "")),
            )
        elif 名称 == "development_start":
            修改路径 = list(参数.get("modified_paths", []))
            数据 = _统一开发入口(
                str(参数.get("task", "")), 修改路径,
                str(参数.get("level", "工作包")), int(参数.get("history_limit", 3)),
                str(参数.get("artifact", "")),
            )
            # 文件级占用：拿到"修改路径"后先批量申请文件租约，冲突在开工那一刻暴露。
            租约结果 = 申请文件租约(
                平台控制面目录, 修改路径, 所有者=当前开工id,
                任务=str(参数.get("task", "")),
            )
            if 修改路径 and not 租约结果.get("成功"):
                数据 = {
                    "成功": False, "错误码": 租约结果.get("错误码"),
                    "消息": f"开工被拒：{租约结果.get('消息', '')}",
                    "冲突文件": 租约结果.get("文件路径"),
                    "占用者": 租约结果.get("占用者"),
                    "占用开始时间": 租约结果.get("占用开始时间"),
                    "已回滚": 租约结果.get("已回滚", []),
                    "处置": "换不重叠的工作包，或写进旁路清单待下一批；不许硬闯。",
                }
            else:
                数据["文件租约"] = 租约结果
        elif 名称 == "temporary_context":
            操作 = str(参数["operation"])
            开工id = str(参数["work_id"])
            if 操作 == "写入":
                # 只允许当前开工id或已登记子任务（与 mcp_feedback/verify_and_record 同路径），
                # 防止伪造任意子任务身份。
                try:
                    有效id = _有效开工id(开工id)
                except PermissionError as 错误:
                    数据 = {"成功": False, "错误码": "未授权", "错误说明": str(错误)}
                else:
                    数据 = 写入临时上下文(
                        临时上下文目录, 开工id=有效id,
                        父任务=str(参数.get("parent_task", 当前任务名称)),
                        角色=str(参数.get("role", 网关角色名)),
                        允许目录=list(参数.get("allowed_paths", [])),
                        记忆查询=list(参数.get("memory_queries", [])),
                        事实=list(参数.get("confirmed_facts", [])),
                        验证计划=list(参数.get("verification_commands", [])),
                        有效秒数=int(参数.get("ttl_seconds", 7200)),
                    )
            elif 操作 == "读取":
                数据 = 读取临时上下文(临时上下文目录, 开工id)
            elif 操作 == "清理":
                数据 = 清理临时上下文(临时上下文目录, 开工id)
            elif 操作 == "核对范围":
                数据 = 核对修改范围(临时上下文目录, 开工id, list(参数.get("actual_paths", [])))
            else:
                raise ValueError("临时上下文操作必须是写入、读取、核对范围或清理")
        elif 名称 == "task_observation":
            操作 = str(参数["operation"])
            任务id = str(参数["task_id"])
            观测开工id = _有效开工id(参数.get("work_id"))
            if 操作 == "开始":
                数据 = 任务开始(观测路径, 任务id=任务id, 开工id=观测开工id,
                               角色=网关角色名, 父任务id=str(参数.get("parent_task_id", "")),
                               子代理数=int(参数.get("child_count", 0)))
            elif 操作 == "结束":
                数据 = 任务结束(观测路径, 任务id=任务id, 开工id=观测开工id,
                               成功=bool(参数.get("success", True)), 错误码=str(参数.get("error_code", "")))
            elif 操作 == "查询":
                数据 = 查询任务(观测路径, 任务id, 观测开工id)
            elif 操作 in {"阶段开始", "阶段结束"}:
                数据 = 阶段记录(观测路径, 任务id=任务id,
                             开工id=观测开工id,
                             阶段=str(参数["phase"]), 状态=操作.removeprefix("阶段"),
                             阶段id=str(参数.get("phase_id", "")),
                             说明=str(参数.get("note", "")))
            elif 操作 == "报告":
                数据 = 生成效率报告(观测路径, 任务id)
            else:
                raise ValueError("任务观测操作必须是开始、结束、查询、阶段开始、阶段结束或报告")
        elif 名称 == "workspace":
            操作 = str(参数["operation"])
            if 操作 == "创建":
                数据 = 创建工作区(项目根目录, 工作区根目录, 任务id=str(参数["task_id"]), 基线=str(参数.get("base", "HEAD")))
            elif 操作 == "查询":
                数据 = 查询工作区(项目根目录, 工作区根目录)
            elif 操作 == "关闭":
                数据 = 关闭工作区(项目根目录, str(参数["path"]), 强制=bool(参数.get("force", False)),
                                work_id=str(参数.get("work_id", 当前开工id)))
            elif 操作 == "提交":
                数据 = 工作区提交(Path(str(参数["path"])), str(参数["message"]), 路径列表=list(参数.get("paths", [])) or None)
            elif 操作 == "合并":
                数据 = 合并分支(Path(str(参数["path"])), str(参数["target_branch"]), str(参数["source_branch"]), 提交消息=str(参数.get("message", "")))
            else:
                raise ValueError("工作区操作必须是创建、查询、提交、合并或关闭")
        elif 名称 == "test_resource":
            操作 = str(参数["operation"])
            资源开工id = _有效开工id(参数.get("work_id"))
            # S2：临时根固定为 工程缓存/测试临时/，不接受调用者任意参数。
            临时根 = (项目根目录 / "工程缓存" / "测试临时").resolve()
            清单 = 测试资源清单目录 / f"{资源开工id or '未开工'}.jsonl"
            if 操作 == "登记":
                数据 = 登记资源(清单, 资源路径=str(参数["resource_path"]), 临时根目录=临时根,
                               资源类型=str(参数.get("resource_type", "文件")), 保留=bool(参数.get("keep", False)),
                               work_id=str(参数.get("work_id", 当前开工id)))
            elif 操作 == "清理":
                数据 = 清理资源(清单, 临时根目录=临时根)
            else:
                raise ValueError("测试资源操作必须是登记或清理")
        elif 名称 == "register_requirement":
            需求开工id = _有效开工id(参数.get("work_id"))
            数据 = 登记需求(工程缓存目录, 能力id=str(参数["能力id"]), 说明=str(参数["说明"]),
                          来源任务=str(参数.get("来源任务", 当前任务名称)), work_id=需求开工id)
        elif 名称 == "reuse_search":
            数据 = 复用搜索(项目根目录, str(参数["关键词"]))
        elif 名称 == "claim_capability":
            占用开工id = _有效开工id(参数.get("开工id"))
            数据 = 登记能力占用(工程缓存目录, 能力id=str(参数["能力id"]),
                              提供包id=str(参数["提供包id"]), 开工id=占用开工id)
        elif 名称 == "validate_module_compliance":
            数据 = 校验模块合规(项目根目录, str(参数["模块名"]))
        elif 名称 == "generate_module_template":
            from 开发工具.组件规范.模块模板生成器 import 生成模块模板
            结果 = 生成模块模板(
                模块名=str(参数["模块名"]), 类型=str(参数.get("类型", "基础模块")),
                能力清单=参数.get("能力清单", []), 依赖能力清单=参数.get("依赖能力清单", []),
            )
            if 结果.成功:
                数据 = {"成功": True, **结果.值}
            else:
                数据 = {"成功": False, "错误码": 结果.错误码, "说明": 结果.错误说明}
        elif 名称 == "create_core_snapshot":
            数据 = 创建核心快照(项目根目录, 说明=str(参数.get("说明", "")))
        elif 名称 == "query_core_snapshot":
            数据 = 查询核心快照(项目根目录)
        elif 名称 == "compatibility_check":
            数据 = 兼容性检查(str(参数["快照标识"]), 项目根目录)
        elif 名称 == "rollback_gate":
            数据 = 回滚门禁(str(参数["快照标识"]), 项目根目录, 执行回滚=bool(参数.get("执行回滚", False)))
        elif 名称 == "run_release_gate":
            数据 = _结果转字典(运行发布门禁(str(参数.get("包目录", "")) or None))
        elif 名称 == "check_release_evidence":
            数据 = _结果转字典(读取正式发布状态(
                提交=str(参数.get("提交", "")),
                工作区指纹=str(参数.get("工作区指纹", "")),
            ))
        elif 名称 == "generate_release_evidence":
            数据 = {
                "成功": False, "错误码": "命令拒绝",
                "错误说明": "正式发布证据只能由 verify_and_record 真实执行唯一发布命令后生成",
            }
        elif 名称 == "switch_active_pointer":
            数据 = _结果转字典(切换激活指针(
                str(参数["目标摘要"]), int(参数["旧令牌"]),
                提交=str(参数["提交"]), 来源指纹=str(参数["来源指纹"]),
                工作区指纹=str(参数.get("工作区指纹", "")),
            ))
        elif 名称 == "dependency_arbitration":
            数据 = _结果转字典(依赖裁决(str(参数["包id"])))
        elif 名称 == "register_task":
            数据 = 登记任务(str(参数["work_id"]), 任务=str(参数["任务"]), 角色=str(参数.get("角色", 网关角色名)),
                           worktree路径=str(参数.get("worktree路径", "")), 允许路径=list(参数.get("允许路径", [])),
                           基线提交=str(参数.get("基线提交", "")), parent_work_id=str(参数.get("parent_work_id", "")))
        elif 名称 == "collaboration_status":
            协作开工id = _有效开工id(参数.get("work_id"))
            数据 = 查询协作状态(协作开工id, 任务=str(参数.get("任务", "")))
        elif 名称 == "delivery_closeout":
            收口开工id = _有效开工id(参数.get("work_id"))
            数据 = 收口登记(收口开工id, 五件套路径=str(参数.get("五件套路径", "")), 结论=str(参数.get("结论", "")))
            if 数据.get("成功"):
                # 收口后自动释放本工作包持有的全部文件租约，不留残锁。
                数据["文件租约释放"] = 释放工作包文件租约(
                    平台控制面目录, 收口开工id,
                    证据=f"收口：{str(参数.get('结论', '')).strip()}",
                )
        elif 名称 == "file_lease":
            操作 = str(参数["operation"])
            路径表 = list(参数.get("paths", []))
            租约id表 = [str(项) for 项 in 参数.get("lease_ids", [])]
            证据 = str(参数.get("evidence", ""))
            if 操作 == "查询":
                数据 = 查询文件占用(平台控制面目录, 路径表 or None)
            elif 操作 == "续租":
                数据 = 续租文件租约(平台控制面目录, 租约id表)
            elif 操作 == "释放":
                数据 = 释放文件租约(平台控制面目录, 租约id表, 证据=证据)
            elif 操作 == "回收过期":
                数据 = 回收过期文件租约(平台控制面目录)
            else:
                raise ValueError("文件租约操作必须是查询、续租、释放或回收过期")
        elif 名称 == "validate_verification_command":
            数据 = 校验验证命令受控(list(参数["命令"]))
        elif 名称 == "judge_verification_result":
            数据 = 判定验证结果(int(参数["退出码"]), str(参数["标准输出"]))
        elif 名称 == "verify_and_record":
            证据开工id = str(参数.get("work_id") or 当前开工id)
            if not 证据开工id:
                raise PermissionError("尚未建立开工上下文")
            if not 查询反馈状态(反馈路径, 证据开工id)["已反馈"]:
                raise PermissionError("本次任务尚未提交 MCP 使用反馈，不能记录成功验证证据")
            命令 = list(参数["command"])
            校验 = 校验验证命令受控(命令)
            if not 校验["成功"]:
                raise PermissionError(f"验证命令拒绝: {校验['错误码']}: {校验.get('消息', '')}")
            数据 = _运行验证(
                str(参数["name"]), 命令, int(参数.get("timeout_seconds", 300)),
                开工id=证据开工id,
            )
            判定 = dict(数据.get("判定", {}))
            if tuple(命令) == 唯一发布命令 and 判定.get("成功") is True:
                发布证据结果 = 生成发布证据(
                    str(数据.get("提交", "")), str(参数["name"]),
                    int(数据.get("退出码", -1)), str(数据.get("工作区指纹", "")),
                    证据类型=正式发布证据类型, 命令=命令,
                    制品摘要=str(参数.get("artifact_digest", "")),
                    来源指纹=str(参数.get("source_fingerprint", "")),
                    能力覆盖=list(参数.get("capability_coverage", [])),
                    场景覆盖=dict(参数.get("scenario_coverage", {})),
                    真实结果=dict(参数.get("real_result", {})), 状态="通过",
                    核验工作区指纹=str(数据.get("工作区指纹", "")),
                )
                数据["发布证据"] = _结果转字典(发布证据结果)
                if not 发布证据结果.成功:
                    数据["判定"] = {
                        "成功": False, "错误码": 发布证据结果.错误码,
                        "消息": 发布证据结果.消息,
                    }
            elif not 判定.get("成功"):
                数据["判定"] = 判定
        else:
            raise ValueError(f"未知工具：{名称}")
    except (KeyError, ValueError, TypeError) as 异常:
        数据 = {"成功": False, "错误码": "参数无效", "错误说明": str(异常)}
    工具事件(观测路径, 任务id=观测任务id, 开工id=事件开工id, 工具=名称, 开始单调=观测开始)
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


async def 主程序HTTP(端口: int = 8766) -> None:
    """以 Streamable HTTP 协议提供 MCP 服务（opencode remote 接入）。"""
    from 公共契约.运行时.端口策略 import 校验应用监听端口
    校验应用监听端口(端口)
    from starlette.applications import Starlette
    from starlette.routing import Route
    import uvicorn
    from mcp.server.streamable_http_manager import StreamableHTTPSessionManager

    会话管理 = StreamableHTTPSessionManager(app=服务, event_store=None, stateless=False)

    class _流式HTTP应用:
        """类实例端点：Starlette 将其识别为 ASGI 应用（全 HTTP 方法放行）。"""

        async def __call__(self, 作用域: object, 接收: object, 发送: object) -> None:
            await 会话管理.handle_request(作用域, 接收, 发送)  # type: ignore[arg-type]

    应用 = Starlette(
        routes=[Route("/mcp/", endpoint=_流式HTTP应用())],
        lifespan=lambda 应用对象: 会话管理.run(),
    )
    配置 = uvicorn.Config(应用, host="127.0.0.1", port=端口, log_level="info")
    服务器 = uvicorn.Server(配置)
    await 服务器.serve()


if __name__ == "__main__":
    import argparse

    解析器 = argparse.ArgumentParser(description="系统工程平台 MCP 服务")
    解析器.add_argument("--http", action="store_true", help="以 HTTP(Streamable) 协议提供服务")
    解析器.add_argument("--端口", type=int, default=8766, help="HTTP 服务端口")
    参数 = 解析器.parse_args()
    if 参数.http:
        asyncio.run(主程序HTTP(端口=参数.端口))
    else:
        asyncio.run(主程序())
