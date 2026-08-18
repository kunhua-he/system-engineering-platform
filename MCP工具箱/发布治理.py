"""发布治理工具集：发布门禁运行、发布证据读写、激活指针 CAS、依赖裁决。

供主协调接线；统一 结果 结构，错误码：门禁失败/无证据/陈旧令牌/指针缺失/裁决失败。
发布门禁真实调用 开发工具/发布门禁/运行发布门禁.py（子进程），不在本模块复制判断。
发布证据结构化追加 工程缓存/发布证据/{提交}.json（不入 git）。
激活指针 CAS：读 工程缓存/制品仓库/平台客户端环境/当前.json，旧令牌不匹配拒绝，
匹配则原子写新指针（版本+1、栅栏令牌+1）并记录证据。
依赖裁决复用 运行核心 发现器/选择器/解析器（传递闭包.py 同源组件），返回 裁决通过/缺口。
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from 运行核心.加载器.包发现.发现器 import 发现全部
from 运行核心.加载器.依赖解析.解析器 import 解析依赖
from 运行核心.加载器.提供者选择.选择器 import 选择全部提供者

系统根目录 = Path(__file__).resolve().parent.parent
if str(系统根目录) not in sys.path:
    sys.path.insert(0, str(系统根目录))

# ---- 错误码（统一） ----
门禁失败 = "门禁失败"
无证据 = "无证据"
陈旧令牌 = "陈旧令牌"
指针缺失 = "指针缺失"
裁决失败 = "裁决失败"
参数无效 = "参数无效"

_提交模式 = re.compile(r"^[0-9a-f]{40}$")

# ---- 默认路径（测试可注入临时目录） ----
验证历史路径 = 系统根目录 / "开发文档" / "项目证据" / "验证历史.jsonl"
发布证据目录 = 系统根目录 / "工程缓存" / "发布证据"
环境目录 = 系统根目录 / "工程缓存" / "制品仓库" / "平台客户端环境"
发布门禁脚本 = 系统根目录 / "开发工具" / "发布门禁" / "运行发布门禁.py"

# 激活指针字段名（与 平台控制面/包仓库/平台客户端制品.py 的指针契约一致）
摘要字段 = "摘要sha256"
制品目录字段 = "制品目录"
制品摘要字段 = "制品摘要"
版本字段 = "版本"
栅栏令牌字段 = "栅栏令牌"


@dataclass
class 结果:
    """统一结果：成功标记 + 错误码 + 消息 + 数据。"""

    成功: bool
    错误码: str = ""
    消息: str = ""
    数据: dict[str, Any] = field(default_factory=dict)


def _时间戳() -> str:
    """UTC 时间戳（与 验证历史.jsonl 格式一致）。"""
    return datetime.now(timezone.utc).isoformat()


def _原子写文本(路径: Path, 文本: str) -> None:
    """原子写：唯一临时文件 + fsync + 原子替换 + 目录 fsync。"""
    路径.parent.mkdir(parents=True, exist_ok=True)
    临时路径 = 路径.parent / f".{路径.name}.{uuid.uuid4().hex}.tmp"
    临时路径.write_text(文本, encoding="utf-8")
    with open(临时路径, "rb") as 句柄:
        os.fsync(句柄.fileno())
    os.replace(临时路径, 路径)
    目录句柄 = os.open(路径.parent, os.O_RDONLY)
    try:
        os.fsync(目录句柄)
    finally:
        os.close(目录句柄)


def 当前提交() -> str:
    """当前 git 提交（供切换激活指针记录证据用；无版本库时返回空串）。"""
    try:
        进程 = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=str(系统根目录),
            capture_output=True, text=True, timeout=10,
        )
        return 进程.stdout.strip() if 进程.returncode == 0 else ""
    except (OSError, subprocess.TimeoutExpired):
        return ""


# ---- 1. 发布门禁运行（真实调用 运行发布门禁.py，禁止复制简化判断） ----

def 运行发布门禁(包目录: str | Path | None = None, *, 超时秒: float = 600.0,
                命令列表: list[str] | None = None) -> 结果:
    """运行发布门禁（子进程调用 开发工具/发布门禁/运行发布门禁.py）。

    返回 发布状态/退出码/输出尾部；退出码非 0 时错误码为 门禁失败。
    命令列表 仅供测试桩注入轻量命令，验证返回码透传与输出解析；
    完整门禁执行由主协调阶段收口负责。
    """
    if 命令列表 is None:
        命令列表 = ["python3.14", str(发布门禁脚本)]
        if 包目录:
            命令列表 += ["--包目录", str(包目录)]
    try:
        进程 = subprocess.run(
            命令列表, cwd=str(系统根目录), capture_output=True, text=True,
            timeout=超时秒,
        )
    except (OSError, subprocess.TimeoutExpired) as 异常:
        return 结果(False, 门禁失败, f"发布门禁子进程异常: {异常}")
    输出 = (进程.stdout or "") + (进程.stderr or "")
    状态匹配 = re.findall(r"发布状态[:：]\s*(通过|失败|阻断)", 输出)
    发布状态 = 状态匹配[-1] if 状态匹配 else "未知"
    输出尾部 = "\n".join(输出.splitlines()[-40:])
    数据 = {"发布状态": 发布状态, "退出码": 进程.returncode, "输出尾部": 输出尾部}
    if 进程.returncode == 0:
        return 结果(True, 消息=f"发布门禁通过（发布状态: {发布状态}）", 数据=数据)
    return 结果(False, 门禁失败,
                f"发布门禁失败（退出码 {进程.returncode}，发布状态: {发布状态}）",
                数据=数据)


# ---- 2. 检查发布证据（读 验证历史.jsonl，无记录拒绝） ----

def 检查发布证据(提交: str, *, 证据路径: str | Path | None = None) -> 结果:
    """按提交查询 验证历史.jsonl 的成功验证记录（名称/退出码/指纹）。

    只认 退出码 == 0 且 提交 相符的记录；无成功记录 → 错误码 无证据 拒绝。
    """
    文件路径 = Path(证据路径) if 证据路径 else 验证历史路径
    if not 文件路径.is_file():
        return 结果(False, 无证据, f"验证历史不存在: {文件路径}")
    记录列表: list[dict[str, Any]] = []
    for 行 in 文件路径.read_text(encoding="utf-8").splitlines():
        try:
            记录 = json.loads(行)
        except json.JSONDecodeError:
            continue
        if 记录.get("提交") == 提交 and 记录.get("退出码") == 0:
            记录列表.append(记录)
    if not 记录列表:
        return 结果(False, 无证据,
                    f"提交 {提交[:12]} 无成功验证记录（无发布证据）")
    最新记录 = 记录列表[-1]
    数据 = {
        "名称": 最新记录.get("名称", ""),
        "退出码": 最新记录.get("退出码"),
        "指纹": 最新记录.get("工作区指纹", ""),
        "时间": 最新记录.get("时间", ""),
        "命令": 最新记录.get("命令", []),
        "记录数": len(记录列表),
    }
    return 结果(True,
               消息=f"提交 {提交[:12]} 有发布证据（{len(记录列表)} 条成功记录）",
               数据=数据)


# ---- 3. 生成发布证据（结构化追加 工程缓存/发布证据/{提交}.json，不入 git） ----

def 生成发布证据(提交: str, 名称: str, 退出码: int, 指纹: str, *,
                证据目录: str | Path | None = None) -> 结果:
    """结构化追加一条发布证据到 工程缓存/发布证据/{提交}.json，返回路径。

    文件结构: {"提交": ..., "条目": [{"名称", "退出码", "指纹", "时间"}, ...]}。
    工程缓存不入 git，发布证据不参与版本库。
    S7/C：提交必须是 40 位小写十六进制（防路径穿越文件名），否则参数无效拒绝。
    """
    if not _提交模式.fullmatch(提交):
        return 结果(False, 参数无效, f"提交必须是 40 位十六进制: {提交[:40]!r}")
    目录 = Path(证据目录) if 证据目录 else 发布证据目录
    文件路径 = 目录 / f"{提交}.json"
    条目表: list[dict[str, Any]] = []
    if 文件路径.is_file():
        try:
            现有 = json.loads(文件路径.read_text(encoding="utf-8"))
            if isinstance(现有, dict) and isinstance(现有.get("条目"), list):
                条目表 = 现有["条目"]
        except (json.JSONDecodeError, OSError) as 错误:
            return 结果(False, "证据写入失败", f"现有发布证据不可读: {错误}")
    条目表.append({"名称": 名称, "退出码": 退出码, "指纹": 指纹, "时间": _时间戳()})
    数据 = {"提交": 提交, "条目": 条目表}
    try:
        _原子写文本(文件路径, json.dumps(数据, ensure_ascii=False, indent=2) + "\n")
    except OSError as 错误:
        return 结果(False, "证据写入失败", f"发布证据写入失败: {错误}")
    return 结果(True, 消息=f"发布证据已追加: {文件路径}",
                数据={"路径": str(文件路径), "条目数": len(条目表)})


# ---- 4. 切换激活指针（CAS：旧令牌不匹配拒绝，匹配则原子写新指针并记录证据） ----

def 切换激活指针(目标摘要: str, 旧令牌: int, *,
                环境目录参数: str | Path | None = None,
                提交: str = "", 证据目录参数: str | Path | None = None) -> 结果:
    """CAS 切换激活指针：读 当前.json，旧令牌不匹配 → 陈旧令牌 拒绝。

    匹配则原子写新指针（版本+1、栅栏令牌+1），并把切换记录为发布证据。
    S7/C：显式提交必须是 40 位小写十六进制，否则参数无效拒绝（证据文件名防路径穿越）。
    """
    if 提交 and not _提交模式.fullmatch(提交):
        return 结果(False, 参数无效, f"提交必须是 40 位十六进制: {提交[:40]!r}")
    目录 = Path(环境目录参数) if 环境目录参数 else 环境目录
    指针文件 = 目录 / "当前.json"
    if not 指针文件.is_file():
        return 结果(False, 指针缺失, f"激活指针缺失: {指针文件}")
    try:
        指针 = json.loads(指针文件.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as 错误:
        return 结果(False, 指针缺失, f"激活指针不可读: {错误}")
    if not isinstance(指针, dict):
        return 结果(False, 指针缺失, "激活指针结构不合法")
    当前令牌 = int(指针.get(栅栏令牌字段, 0))
    if 当前令牌 != int(旧令牌):
        return 结果(False, 陈旧令牌,
                    f"陈旧令牌: 当前栅栏令牌为 {当前令牌}，收到 {旧令牌}")
    旧版本 = int(指针.get(版本字段, 1))
    新指针 = {
        摘要字段: str(目标摘要)[:16],
        制品目录字段: f"平台客户端-{str(目标摘要)[:16]}",
        制品摘要字段: str(目标摘要),
        版本字段: 旧版本 + 1,
        栅栏令牌字段: 当前令牌 + 1,
    }
    try:
        _原子写文本(指针文件, json.dumps(新指针, ensure_ascii=False))
    except OSError as 错误:
        return 结果(False, 指针缺失, f"激活指针写入失败: {错误}")
    证据提交 = 提交 or 当前提交()
    if 证据提交:
        生成发布证据(
            证据提交,
            f"激活指针切换: v{旧版本}→v{新指针[版本字段]}",
            0, str(目标摘要), 证据目录=证据目录参数,
        )
    return 结果(True,
               消息=f"激活指针已切换（令牌 {当前令牌}→{新指针[栅栏令牌字段]}）",
               数据={"新指针": 新指针, "指针文件": str(指针文件)})


# ---- 5. 依赖裁决（复用 发现器/选择器/解析器，返回 裁决通过/缺口） ----

def 校验依赖闭包(声明: Any, *, 系统根: str | Path | None = None) -> 结果:
    """校验单份包声明的依赖闭包：依赖能力在系统内均有提供者且版本满足。

    复用 发现全部/选择全部提供者/解析依赖（传递闭包.py 同源组件），
    缺口 = 缺失能力 + 版本冲突 + 循环，任一存在即 裁决失败。
    """
    根 = Path(系统根) if 系统根 else 系统根目录
    发现 = 发现全部(根 / "支持库", 根 / "模块库")
    if not 发现.成功:
        return 结果(False, 裁决失败,
                    "系统包发现失败: " + "；".join(发现.问题列表[:3]))
    系统提供者表 = 选择全部提供者(发现.声明列表)
    能力提供者 = {
        能力id: (选择.提供包id, 选择.提供版本)
        for 能力id, 选择 in 系统提供者表.items() if 选择.成功
    }
    解析 = 解析依赖([声明], 能力提供者)
    缺口 = 解析.缺失能力 + 解析.版本冲突 + 解析.循环
    if not 缺口:
        return 结果(True,
                   消息=f"{声明.包id} 依赖闭包裁决通过（{len(声明.依赖)} 项依赖）")
    return 结果(False, 裁决失败,
                f"{声明.包id} 依赖闭包有缺口: " + "；".join(缺口[:5]),
                数据={"缺口": 缺口})


def 依赖裁决(包id: str, *, 系统根: str | Path | None = None) -> 结果:
    """按包id 定位包声明并裁决其依赖闭包；系统内无此包声明 → 裁决失败。"""
    根 = Path(系统根) if 系统根 else 系统根目录
    发现 = 发现全部(根 / "支持库", 根 / "模块库")
    if not 发现.成功:
        return 结果(False, 裁决失败,
                    "系统包发现失败: " + "；".join(发现.问题列表[:3]))
    声明表 = {声明.包id: 声明 for 声明 in 发现.声明列表}
    目标声明 = 声明表.get(包id)
    if 目标声明 is None:
        return 结果(False, 裁决失败, f"系统内无包声明: {包id}")
    return 校验依赖闭包(目标声明, 系统根=根)
