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
import hashlib
import os
import re
import subprocess
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from 运行核心.加载器.包发现.发现器 import 发现全部
from 运行核心.加载器.依赖解析.解析器 import 解析依赖
from 运行核心.加载器.提供者选择.选择器 import 选择全部提供者

系统根目录 = Path(__file__).resolve().parent.parent

# ---- 错误码（统一） ----
门禁失败 = "门禁失败"
无证据 = "无证据"
陈旧令牌 = "陈旧令牌"
指针缺失 = "指针缺失"
裁决失败 = "裁决失败"
参数无效 = "参数无效"
证据写入失败 = "证据写入失败"
正式发布证据类型 = "正式发布"
工作记录类型 = "工作记录"

_提交模式 = re.compile(r"^[0-9a-f]{40}$")
_制品摘要模式 = re.compile(r"^[0-9a-f]{32}$")
_指纹模式 = re.compile(r"^[0-9a-f]{64}$")

from .验证门禁 import 唯一发布命令

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


def 当前工作区指纹(工作根参数: str | Path | None = None) -> str:
    """按真实 git porcelain 状态计算工作区指纹，与 MCP 验证账本同算法。"""
    根 = Path(工作根参数) if 工作根参数 else 系统根目录
    try:
        进程 = subprocess.run(
            ["git", "status", "--porcelain=v1", "-z"], cwd=str(根),
            capture_output=True, text=True, timeout=10,
        )
        状态 = 进程.stdout if 进程.returncode == 0 else "无版本库"
    except (OSError, subprocess.TimeoutExpired):
        状态 = "无版本库"
    return hashlib.sha256(状态.encode("utf-8")).hexdigest()


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
    # 退出码只是进程层结果，不能覆盖发布门禁自己的状态。
    # 只有唯一明确的“通过”状态且退出码为 0 才能形成成功证据；
    # 无状态、失败或阻断一律失败，防止命令桩/异常输出制造假绿。
    if 进程.returncode == 0 and 发布状态 == "通过":
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


# ---- 3. 发布记录与专用正式发布证据 ----

def _正式证据问题(条目: dict[str, Any], 实际工作区指纹: str) -> str:
    if 条目.get("命令") != list(唯一发布命令):
        return "正式发布证据必须绑定唯一发布命令"
    if not _制品摘要模式.fullmatch(str(条目.get("制品摘要", ""))):
        return "正式发布证据缺少合法制品摘要"
    if 条目.get("状态") != "通过" or 条目.get("退出码") != 0:
        return "正式发布证据状态必须为通过且退出码为0"
    if 条目.get("工作区指纹") != 实际工作区指纹:
        return "正式发布证据工作区指纹不是当前真实指纹"
    if not _指纹模式.fullmatch(str(条目.get("来源指纹", ""))):
        return "正式发布证据缺少合法来源指纹"
    if not isinstance(条目.get("能力覆盖"), list) or not 条目["能力覆盖"]:
        return "正式发布证据能力覆盖不能为空"
    覆盖 = 条目.get("场景覆盖")
    if not isinstance(覆盖, dict):
        return "正式发布证据场景覆盖缺失"
    try:
        总数 = int(覆盖.get("总数", 0))
        通过数 = int(覆盖.get("通过数", -1))
        失败数 = int(覆盖.get("失败数", -1))
    except (TypeError, ValueError):
        return "正式发布证据场景覆盖字段不合法"
    if 总数 <= 0 or 通过数 != 总数 or 失败数 != 0:
        return "正式发布证据场景覆盖未全部通过"
    真实结果 = 条目.get("真实结果")
    if not isinstance(真实结果, dict) or 真实结果.get("成功") is not True:
        return "正式发布证据缺少成功的真实结果"
    return ""


def 生成发布证据(提交: str, 名称: str, 退出码: int, 指纹: str, *,
                证据目录: str | Path | None = None,
                证据类型: str = 工作记录类型,
                命令: list[str] | None = None,
                制品摘要: str = "", 来源指纹: str = "",
                能力覆盖: list[str] | None = None,
                场景覆盖: dict[str, Any] | None = None,
                真实结果: dict[str, Any] | None = None,
                状态: str = "", 核验工作区指纹: str = "") -> 结果:
    """写发布记录；只有完整的专用类型记录才是正式发布判定事实。"""
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
            return 结果(False, 证据写入失败, f"现有发布证据不可读: {错误}")
    条目: dict[str, Any] = {
        "类型": 证据类型, "名称": 名称, "退出码": 退出码,
        "指纹": 指纹, "工作区指纹": 指纹, "提交": 提交, "时间": _时间戳(),
    }
    if 证据类型 == 正式发布证据类型:
        条目.update({
            "命令": list(命令 or []), "制品摘要": 制品摘要,
            "来源指纹": 来源指纹, "能力覆盖": list(能力覆盖 or []),
            "场景覆盖": dict(场景覆盖 or {}), "真实结果": dict(真实结果 or {}),
            "状态": 状态,
        })
        预期工作区指纹 = 核验工作区指纹 or 当前工作区指纹()
        问题 = _正式证据问题(条目, 预期工作区指纹)
        if 问题:
            return 结果(False, 参数无效, 问题)
    条目表.append(条目)
    try:
        _原子写文本(
            文件路径,
            json.dumps({"提交": 提交, "条目": 条目表}, ensure_ascii=False, indent=2) + "\n",
        )
    except OSError as 错误:
        return 结果(False, 证据写入失败, f"发布证据写入失败: {错误}")
    return 结果(True, 消息=f"发布记录已追加: {文件路径}",
                数据={"路径": str(文件路径), "条目数": len(条目表), "类型": 证据类型})


def 读取正式发布状态(*, 证据目录: str | Path | None = None,
                   提交: str = "", 工作区指纹: str = "") -> 结果:
    """只读专用正式发布证据，作为发布状态唯一事实源。"""
    目录 = Path(证据目录) if 证据目录 else 发布证据目录
    实际指纹 = 工作区指纹 or 当前工作区指纹()
    文件表 = [目录 / f"{提交}.json"] if 提交 else sorted(
        目录.glob("*.json"), key=lambda 项: 项.stat().st_mtime, reverse=True,
    ) if 目录.is_dir() else []
    候选表: list[dict[str, Any]] = []
    for 文件路径 in 文件表:
        if not 文件路径.is_file():
            continue
        try:
            数据 = json.loads(文件路径.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        for 条目 in reversed(数据.get("条目", [])) if isinstance(数据, dict) else []:
            if not isinstance(条目, dict) or 条目.get("类型") != 正式发布证据类型:
                continue
            if 提交 and 条目.get("提交") != 提交:
                continue
            if 条目.get("工作区指纹") != 实际指纹:
                continue
            if not _正式证据问题(条目, 实际指纹):
                候选表.append(条目)
    if not 候选表:
        return 结果(False, 无证据, "当前提交和工作区指纹没有正式发布通过证据")
    return 结果(True, 消息="正式发布状态：通过", 数据=dict(候选表[0]))


def 检查正式发布证据(提交: str, 制品摘要: str, 工作区指纹: str,
                 来源指纹: str, *, 证据目录: str | Path | None = None) -> 结果:
    """校验正式证据与本次待激活制品、提交、工作区和来源完全绑定。"""
    状态 = 读取正式发布状态(证据目录=证据目录, 提交=提交, 工作区指纹=工作区指纹)
    if not 状态.成功:
        return 状态
    if 状态.数据.get("制品摘要") != 制品摘要:
        return 结果(False, 无证据, "正式发布证据与待激活制品摘要不一致")
    if 状态.数据.get("来源指纹") != 来源指纹:
        return 结果(False, 无证据, "正式发布证据与制品来源指纹不一致")
    return 状态


# ---- 4. 激活前完整校验与 CAS 指针切换 ----

def _读取物料清单(制品目录: Path) -> tuple[dict[str, Any] | None, str]:
    清单路径 = 制品目录 / "物料清单.json"
    if not 清单路径.is_file():
        return None, "制品缺少物料清单.json"
    try:
        清单 = json.loads(清单路径.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as 错误:
        return None, f"物料清单不可读: {错误}"
    if not isinstance(清单, dict) or not isinstance(清单.get("文件清单"), dict) or not 清单["文件清单"]:
        return None, "物料清单缺少非空文件清单"
    for 相对路径, 摘要信息 in 清单["文件清单"].items():
        if not isinstance(摘要信息, dict) or not _指纹模式.fullmatch(str(摘要信息.get("sha256", ""))):
            return None, f"物料清单文件摘要不合法: {相对路径}"
        实际路径 = (制品目录 / str(相对路径)).resolve()
        if not str(实际路径).startswith(str(制品目录.resolve()) + "/"):
            return None, f"物料清单路径越界: {相对路径}"
        if not 实际路径.is_file():
            return None, f"物料清单中的正式文件不存在: {相对路径}"
    return 清单, ""


def _物料来源指纹(清单: dict[str, Any]) -> str:
    构建输入 = 清单.get("构建输入")
    if not isinstance(构建输入, dict):
        return ""
    for 键 in ("来源工作区指纹", "工作区指纹", "来源指纹"):
        值 = str(构建输入.get(键, ""))
        if _指纹模式.fullmatch(值):
            return 值
    return ""


def _校验制品签名与信任(制品摘要: str, *, 制品根目录参数: Path,
                  状态目录参数: Path, 环境目录参数: Path,
                  信任目录参数: Path) -> 结果:
    """复用正式包仓库校验签名、磁盘文件摘要和信任元数据。"""
    from 平台控制面.包仓库.平台客户端制品 import 平台客户端制品接入
    接入 = 平台客户端制品接入(
        状态目录=状态目录参数, 制品根目录=制品根目录参数,
        客户端制品目录=制品根目录参数 / "平台客户端制品",
        环境目录=环境目录参数, 信任目录=信任目录参数,
    )
    try:
        成功, 消息 = 接入.校验制品(制品摘要)
        return 结果(成功, "" if 成功 else 参数无效, 消息)
    finally:
        接入.关闭()


def _写激活准备证据(路径: Path, 条目: dict[str, Any]) -> 结果:
    """切换前持久化完整激活意图；失败时调用方绝不能改指针。"""
    旧文本 = ""
    if 路径.exists():
        try:
            旧文本 = 路径.read_text(encoding="utf-8")
        except OSError as 错误:
            return 结果(False, 证据写入失败, f"激活证据不可读: {错误}")
    try:
        _原子写文本(路径, 旧文本 + json.dumps(条目, ensure_ascii=False) + "\n")
    except OSError as 错误:
        return 结果(False, 证据写入失败, f"激活证据写入失败: {错误}")
    return 结果(True, 消息="激活准备证据已持久化", 数据={"路径": str(路径)})


def _CAS切换激活指针(指针文件: Path, 目标摘要: str, 旧令牌: int) -> 结果:
    """CAS 校验并构造新指针：读指针、校验令牌、构造新指针。

    指针缺失/不可读 → 指针缺失；令牌不匹配 → 陈旧令牌；
    匹配 → 返回新指针数据（版本+1、令牌+1）。
    不写文件，由调用方在证据落盘后原子写。
    成功时 data={"旧指针": 旧指针, "新指针": 新指针}。
    """
    if not 指针文件.is_file():
        return 结果(False, 指针缺失, f"激活指针缺失: {指针文件}")
    try:
        指针 = json.loads(指针文件.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as 错误:
        return 结果(False, 指针缺失, f"激活指针不可读: {错误}")
    if not isinstance(指针, dict):
        return 结果(False, 指针缺失, "激活指针结构不合法")
    try:
        当前令牌 = int(指针.get(栅栏令牌字段, 0))
        旧版本 = int(指针.get(版本字段, 1))
        请求令牌 = int(旧令牌)
    except (TypeError, ValueError):
        return 结果(False, 参数无效, "激活指针版本或栅栏令牌不合法")
    if 当前令牌 != 请求令牌:
        return 结果(False, 陈旧令牌,
                    f"陈旧令牌: 当前栅栏令牌为 {当前令牌}，收到 {旧令牌}")
    新指针 = {
        摘要字段: 目标摘要[:16],
        制品目录字段: f"平台客户端-{目标摘要[:16]}",
        制品摘要字段: 目标摘要,
        版本字段: 旧版本 + 1,
        栅栏令牌字段: 当前令牌 + 1,
    }
    return 结果(True, 消息=f"CAS 校验通过（令牌 {当前令牌}→{新指针[栅栏令牌字段]}）",
                数据={"旧指针": 指针, "新指针": 新指针})


def 切换激活指针(目标摘要: str, 旧令牌: int, *,
                环境目录参数: str | Path | None = None,
                提交: str = "", 证据目录参数: str | Path | None = None,
                制品根目录参数: str | Path | None = None,
                状态目录参数: str | Path | None = None,
                信任目录参数: str | Path | None = None,
                来源指纹: str = "", 工作区指纹: str = "",
                激活证据路径参数: str | Path | None = None) -> 结果:
    """全部制品、信任、正式证据和来源条件通过且证据先落盘后，才 CAS 切换。"""
    证据提交 = 提交 or 当前提交()
    if not _提交模式.fullmatch(证据提交):
        return 结果(False, 参数无效, f"提交必须是 40 位十六进制: {证据提交[:40]!r}")
    if not _制品摘要模式.fullmatch(str(目标摘要)):
        return 结果(False, 参数无效, f"制品摘要必须是 32 位小写十六进制: {目标摘要!r}")
    目录 = Path(环境目录参数) if 环境目录参数 else 环境目录
    制品根 = Path(制品根目录参数) if 制品根目录参数 else 目录.parent
    状态根 = Path(状态目录参数) if 状态目录参数 else 制品根 / "平台客户端状态"
    信任根 = Path(信任目录参数) if 信任目录参数 else 制品根 / "平台客户端信任"
    制品目录 = 制品根 / 目标摘要
    if not 制品目录.is_dir():
        return 结果(False, 参数无效, f"待激活制品不存在: {制品目录}")
    清单, 清单问题 = _读取物料清单(制品目录)
    if 清单 is None:
        return 结果(False, 参数无效, 清单问题)
    清单来源指纹 = _物料来源指纹(清单)
    if not 清单来源指纹:
        return 结果(False, 参数无效, "物料清单缺少合法来源工作区指纹")
    if 来源指纹 and 来源指纹 != 清单来源指纹:
        return 结果(False, 参数无效, "调用来源指纹与物料清单不一致")
    签名校验 = _校验制品签名与信任(
        目标摘要, 制品根目录参数=制品根, 状态目录参数=状态根,
        环境目录参数=目录, 信任目录参数=信任根,
    )
    if not 签名校验.成功:
        return 结果(False, 参数无效, f"制品签名或信任元数据校验失败: {签名校验.消息}")
    实际工作区指纹 = 当前工作区指纹()
    if 工作区指纹 and 工作区指纹 != 实际工作区指纹:
        return 结果(False, 参数无效, "调用工作区指纹不是当前真实工作区指纹")
    正式证据 = 检查正式发布证据(
        证据提交, 目标摘要, 实际工作区指纹, 清单来源指纹,
        证据目录=证据目录参数,
    )
    if not 正式证据.成功:
        return 正式证据
    指针文件 = 目录 / "当前.json"
    cas结果 = _CAS切换激活指针(指针文件, 目标摘要, 旧令牌)
    if not cas结果.成功:
        return cas结果
    旧指针 = cas结果.数据["旧指针"]
    新指针 = cas结果.数据["新指针"]
    激活证据路径 = Path(激活证据路径参数) if 激活证据路径参数 else (
        Path(证据目录参数) if 证据目录参数 else 发布证据目录
    ) / "激活证据.jsonl"
    准备证据 = _写激活准备证据(激活证据路径, {
        "类型": "激活准备", "状态": "已校验待切换", "提交": 证据提交,
        "制品摘要": 目标摘要, "来源指纹": 清单来源指纹,
        "工作区指纹": 实际工作区指纹, "旧指针": 旧指针, "新指针": 新指针,
        "时间": _时间戳(),
    })
    if not 准备证据.成功:
        return 准备证据
    try:
        _原子写文本(指针文件, json.dumps(新指针, ensure_ascii=False))
    except OSError as 错误:
        return 结果(False, 指针缺失, f"激活指针写入失败: {错误}")
    旧令牌号 = int(旧指针.get(栅栏令牌字段, 0))
    return 结果(True,
               消息=f"激活指针已切换（令牌 {旧令牌号}→{新指针[栅栏令牌字段]}）",
               数据={"新指针": 新指针, "指针文件": str(指针文件),
                    "激活证据": 准备证据.数据})


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