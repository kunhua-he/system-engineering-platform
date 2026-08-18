"""核心开发工具集：核心快照 / 查询 / 兼容性检查（资源预算）/ 回滚门禁。

复用 平台控制面/核心快照.py 的算法组件与语义：
- 文件摘要 sha256 与聚合摘要（支持库.适配层.内容摘要）与核心快照.py 相同；
- 路径安全（平台控制面.包仓库.规范化相对路径）与核心快照.py 相同；
- 完整性校验语义同 核心快照管理.校验快照：磁盘重算文件摘要与清单记录比对。

快照根目录：工程缓存/核心快照/{时间戳}/，含 清单.json、摘要.json 与
运行核心+公共契约 的不可变文件副本（回滚切换旧制品，不恢复源码分支）。
激活指针：工程缓存/核心快照/当前.json；执行回滚只切换该元数据，不覆盖源码。

错误码：快照不存在 / 快照损坏 / 漂移 / 超限 / 回滚失败 / 参数无效；
成功时错误码为空字符串。
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

系统根 = Path(__file__).resolve().parents[1]
if str(系统根) not in sys.path:
    sys.path.insert(0, str(系统根))

from 平台控制面.包仓库 import 规范化相对路径
from 支持库.适配层 import 内容摘要

行数上限 = 160
快照范围 = ("运行核心", "公共契约")
清单文件名 = "清单.json"
摘要文件名 = "摘要.json"
激活指针文件名 = "当前.json"
排除目录名表 = {"__pycache__"}


def 核心快照根目录(项目根目录: Path) -> Path:
    """快照根：项目根/工程缓存/核心快照（与核心快照.py 默认一致）。"""
    return Path(项目根目录) / "工程缓存" / "核心快照"


def 解析快照路径(快照标识: str | Path, 项目根目录: Path,
               快照根目录: Path | None = None) -> Path:
    """快照标识：单个时间戳名或快照根下相对路径（拒绝绝对路径与 .. 段，防路径穿越）。

    解析结果必须是快照根下的路径；不满足时抛 ValueError（调用方转 参数无效）。
    """
    原始 = Path(快照标识)
    快照根 = Path(快照根目录) if 快照根目录 else 核心快照根目录(项目根目录)
    快照根 = 快照根.resolve()
    if 原始.is_absolute():
        raise ValueError(f"快照标识不允许绝对路径: {快照标识}")
    if ".." in 原始.parts:
        raise ValueError(f"快照标识不允许 .. 段: {快照标识}")
    候选 = 快照根 / 原始
    解析结果 = 候选.resolve()
    if 解析结果 != 快照根 and not str(解析结果).startswith(f"{快照根}{os.sep}"):
        raise ValueError(f"快照标识越界快照根: {快照标识}")
    return 解析结果


def _收集当前文件表(项目根目录: Path) -> dict[str, str]:
    """收集 运行核心+公共契约 全部正式文件的相对路径与 sha256 摘要。"""
    文件表: dict[str, str] = {}
    for 范围名 in 快照范围:
        目录 = Path(项目根目录) / 范围名
        if not 目录.is_dir():
            raise OSError(f"范围目录不存在: {范围名}")
        for 文件 in sorted(目录.rglob("*")):
            if not 文件.is_file():
                continue
            if any(段 in 排除目录名表 for 段 in 文件.parts):
                continue
            相对路径 = 规范化相对路径(文件.relative_to(项目根目录).as_posix())
            文件表[相对路径] = hashlib.sha256(文件.read_bytes()).hexdigest()
    return 文件表


def _聚合摘要(范围: list[str], 文件表: dict[str, str]) -> str:
    """聚合摘要：范围 + 全部文件摘要（与核心快照.py 摘要语义一致）。"""
    return 内容摘要(json.dumps(
        {"范围": 范围, "文件表": 文件表},
        ensure_ascii=False, sort_keys=True).encode("utf-8"))


def _统计行数(文件: Path) -> int:
    """正式文件行数（资源预算审计用）。"""
    return len(文件.read_text(encoding="utf-8").splitlines())


def _写激活指针CAS(激活指针路径: Path, 快照路径: Path, 清单: dict[str, Any],
                 期望旧文本: str) -> str:
    """CAS 写激活指针：写入前复核原文件文本仍为 期望旧文本，否则返回 陈旧令牌 错误码。"""
    当前文本 = ""
    try:
        if 激活指针路径.is_file():
            当前文本 = 激活指针路径.read_text(encoding="utf-8")
    except OSError as 错误:
        return f"激活指针复核失败: {错误}"
    if 当前文本 != 期望旧文本:
        return "陈旧令牌: 激活指针已被其他方切换，回滚被拒绝"
    数据 = {
        "激活快照": str(快照路径),
        "时间戳": 清单.get("时间戳", 快照路径.name),
        "摘要": 清单["摘要"],
        "文件数": 清单["文件数"],
        "时间": datetime.now().isoformat(timespec="seconds"),
        "说明": "激活指针切换：仅元数据，未覆盖源码",
    }
    try:
        激活指针路径.parent.mkdir(parents=True, exist_ok=True)
        临时路径 = 激活指针路径.parent / f".{激活指针路径.name}.{hashlib.sha256(str(datetime.now().timestamp()).encode()).hexdigest()[:8]}.tmp"
        临时路径.write_text(json.dumps(数据, ensure_ascii=False, indent=2), encoding="utf-8")
        临时路径.replace(激活指针路径)
    except OSError as 错误:
        return f"激活指针切换失败: {错误}"
    return ""


def _校验快照完整性(快照路径: Path) -> tuple[bool, str, dict[str, Any]]:
    """校验快照完整性：磁盘文件摘要与清单记录比对 + 聚合摘要比对。"""
    清单路径 = 快照路径 / 清单文件名
    if not 清单路径.is_file():
        return False, "快照缺少清单.json", {}
    try:
        清单 = json.loads(清单路径.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as 错误:
        return False, f"快照清单损坏: {错误}", {}
    if not isinstance(清单, dict) or not isinstance(清单.get("文件表"), dict) \
            or not isinstance(清单.get("摘要"), str):
        return False, "快照清单字段缺失", {}
    磁盘文件表: dict[str, str] = {}
    for 文件 in sorted(快照路径.rglob("*")):
        if not 文件.is_file():
            continue
        相对 = 文件.relative_to(快照路径).as_posix()
        if 相对 in (清单文件名, 摘要文件名):
            continue
        if any(段 in 排除目录名表 for 段 in 文件.parts):
            continue
        磁盘文件表[相对] = hashlib.sha256(文件.read_bytes()).hexdigest()
    if 磁盘文件表 != 清单["文件表"]:
        return False, "快照内容被篡改（磁盘文件摘要与清单不符）", 清单
    范围 = [str(项) for 项 in 清单.get("范围", list(快照范围))]
    if _聚合摘要(范围, 磁盘文件表) != 清单["摘要"]:
        return False, "快照内容被篡改（聚合摘要与清单不符）", 清单
    return True, "快照完整", 清单


def 创建核心快照(项目根目录: Path, *, 说明: str = "",
               快照根目录: Path | None = None) -> dict[str, Any]:
    """创建核心快照：复制 运行核心+公共契约 到 快照根/{时间戳}/，写清单与摘要。"""
    项目根 = Path(项目根目录)
    快照根 = (Path(快照根目录) if 快照根目录
             else 核心快照根目录(项目根)).resolve()
    try:
        文件表 = _收集当前文件表(项目根)
    except OSError as 错误:
        return {"成功": False, "错误码": "参数无效", "消息": f"收集核心文件失败: {错误}"}
    if not 文件表:
        return {"成功": False, "错误码": "参数无效", "消息": "运行核心与公共契约无正式文件"}
    时间戳 = datetime.now().strftime("%Y%m%d-%H%M%S-%f")[:-3]
    快照路径 = 快照根 / 时间戳
    序号 = 2
    while 快照路径.exists():
        快照路径 = 快照根 / f"{时间戳}-{序号}"
        序号 += 1
    摘要 = _聚合摘要(list(快照范围), 文件表)
    清单 = {
        "类型": "核心快照",
        "时间戳": 快照路径.name,
        "说明": 说明,
        "范围": list(快照范围),
        "摘要": 摘要,
        "文件数": len(文件表),
        "文件表": 文件表,
        "创建时间": datetime.now().isoformat(timespec="seconds"),
    }
    try:
        快照路径.mkdir(parents=True, exist_ok=True)
        for 相对路径 in 文件表:
            来源 = 项目根 / 相对路径
            目标 = 快照路径 / 相对路径
            目标.parent.mkdir(parents=True, exist_ok=True)
            目标.write_bytes(来源.read_bytes())
        (快照路径 / 清单文件名).write_text(
            json.dumps(清单, ensure_ascii=False, indent=2), encoding="utf-8")
        (快照路径 / 摘要文件名).write_text(
            json.dumps({"摘要": 摘要}, ensure_ascii=False), encoding="utf-8")
    except OSError as 错误:
        return {"成功": False, "错误码": "参数无效",
                "消息": f"快照写入失败: {错误}", "快照路径": str(快照路径)}
    return {"成功": True, "错误码": "", "快照路径": str(快照路径),
            "时间戳": 快照路径.name, "摘要": 摘要, "文件数": len(文件表),
            "说明": 说明, "消息": "核心快照已创建（不可变制品）"}


def 查询核心快照(项目根目录: Path, *, 快照根目录: Path | None = None) -> dict[str, Any]:
    """查询核心快照：列出快照（时间戳/摘要/文件数/说明）。"""
    快照根 = (Path(快照根目录) if 快照根目录
             else 核心快照根目录(项目根目录)).resolve()
    列表: list[dict[str, Any]] = []
    if 快照根.is_dir():
        for 目录 in sorted(快照根.iterdir()):
            if not 目录.is_dir():
                continue
            清单路径 = 目录 / 清单文件名
            if not 清单路径.is_file():
                continue
            try:
                清单 = json.loads(清单路径.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            if not isinstance(清单, dict) or "摘要" not in 清单:
                continue
            列表.append({
                "快照路径": str(目录),
                "时间戳": 清单.get("时间戳", 目录.name),
                "摘要": 清单.get("摘要", ""),
                "文件数": 清单.get("文件数", len(清单.get("文件表", {}))),
                "说明": 清单.get("说明", ""),
            })
    return {"成功": True, "错误码": "", "快照列表": 列表, "数量": len(列表)}


def 兼容性检查(快照标识: str | Path, 项目根目录: Path, *,
            快照根目录: Path | None = None) -> dict[str, Any]:
    """兼容性检查：对比当前 运行核心/公共契约 与快照，检出漂移与资源预算超限。"""
    项目根 = Path(项目根目录)
    try:
        快照路径 = 解析快照路径(快照标识, 项目根, 快照根目录)
    except ValueError as 错误:
        return {"成功": False, "错误码": "参数无效", "可检查": False,
                "消息": str(错误), "快照路径": str(快照标识)}
    if not 快照路径.is_dir():
        return {"成功": False, "错误码": "快照不存在", "可检查": False,
                "消息": f"快照目录不存在: {快照路径}", "快照路径": str(快照路径)}
    有效, 消息, 清单 = _校验快照完整性(快照路径)
    if not 有效:
        return {"成功": False, "错误码": "快照损坏", "可检查": False,
                "消息": 消息, "快照路径": str(快照路径)}
    try:
        当前文件表 = _收集当前文件表(项目根)
    except OSError as 错误:
        return {"成功": False, "错误码": "参数无效", "可检查": False,
                "消息": f"收集当前核心文件失败: {错误}", "快照路径": str(快照路径)}
    快照文件表 = 清单["文件表"]
    差异列表: list[dict[str, str]] = []
    新增路径表: list[str] = []
    for 相对路径 in sorted(set(快照文件表) | set(当前文件表)):
        快照摘要 = 快照文件表.get(相对路径)
        当前摘要 = 当前文件表.get(相对路径)
        if 当前摘要 is None:
            差异列表.append({"路径": 相对路径, "类型": "删除",
                             "快照摘要": 快照摘要, "当前摘要": ""})
        elif 快照摘要 is None:
            差异列表.append({"路径": 相对路径, "类型": "新增",
                             "快照摘要": "", "当前摘要": 当前摘要})
            新增路径表.append(相对路径)
        elif 快照摘要 != 当前摘要:
            差异列表.append({"路径": 相对路径, "类型": "修改",
                             "快照摘要": 快照摘要, "当前摘要": 当前摘要})
    # 资源预算：新增正式文件单文件行数审计（≤160 行）
    超限列表: list[dict[str, Any]] = []
    for 相对路径 in 新增路径表:
        行数 = _统计行数(项目根 / 相对路径)
        if 行数 > 行数上限:
            超限列表.append({"路径": 相对路径, "行数": 行数, "上限": 行数上限})
    问题列表 = []
    if 差异列表:
        问题列表.append("漂移")
    if 超限列表:
        问题列表.append("超限")
    if 问题列表:
        错误码 = "超限" if "超限" in 问题列表 else "漂移"
        return {"成功": False, "错误码": 错误码, "可检查": True,
                "消息": f"存在{'、'.join(问题列表)}",
                "快照路径": str(快照路径), "差异列表": 差异列表,
                "超限列表": 超限列表, "问题列表": 问题列表,
                "漂移数": len(差异列表), "超限数": len(超限列表)}
    return {"成功": True, "错误码": "", "可检查": True,
            "消息": "无漂移且资源预算合规", "快照路径": str(快照路径),
            "差异列表": [], "超限列表": [], "问题列表": [],
            "漂移数": 0, "超限数": 0}


def 回滚门禁(快照标识: str | Path, 项目根目录: Path, *, 执行回滚: bool = False,
          快照根目录: Path | None = None) -> dict[str, Any]:
    """回滚门禁：校验快照完整性；执行回滚仅切换激活指针（当前.json），不覆盖源码。"""
    项目根 = Path(项目根目录)
    try:
        快照路径 = 解析快照路径(快照标识, 项目根, 快照根目录)
    except ValueError as 错误:
        return {"成功": False, "错误码": "参数无效", "可回滚": False,
                "消息": str(错误), "快照路径": str(快照标识)}
    if not 快照路径.is_dir():
        return {"成功": False, "错误码": "快照不存在", "可回滚": False,
                "消息": f"快照目录不存在: {快照路径}", "快照路径": str(快照路径)}
    有效, 消息, 清单 = _校验快照完整性(快照路径)
    if not 有效:
        return {"成功": False, "错误码": "快照损坏", "可回滚": False,
                "消息": 消息, "快照路径": str(快照路径)}
    快照根 = Path(快照根目录) if 快照根目录 else 核心快照根目录(项目根)
    激活指针路径 = 快照根 / 激活指针文件名
    当前激活 = ""
    期望旧文本 = ""
    if 激活指针路径.is_file():
        try:
            期望旧文本 = 激活指针路径.read_text(encoding="utf-8")
            当前激活 = json.loads(期望旧文本).get("激活快照", "")
        except (json.JSONDecodeError, OSError):
            期望旧文本 = ""
            当前激活 = ""
    基础 = {"成功": True, "错误码": "", "可回滚": True,
            "消息": "快照完整，可回滚", "快照路径": str(快照路径),
            "摘要": 清单["摘要"], "文件数": 清单["文件数"],
            "当前激活": 当前激活}
    if not 执行回滚:
        return 基础
    cas错误 = _写激活指针CAS(激活指针路径, 快照路径, 清单, 期望旧文本)
    if cas错误:
        return {"成功": False, "错误码": "陈旧令牌", "可回滚": True,
                "消息": cas错误, "快照路径": str(快照路径),
                "摘要": 清单["摘要"], "文件数": 清单["文件数"],
                "当前激活": 当前激活}
    return {"成功": True, "错误码": "", "可回滚": True, "已执行回滚": True,
            "消息": "已切换激活指针（当前.json），未覆盖源码；"
                    "回滚切换不可变旧制品，不恢复源码分支",
            "快照路径": str(快照路径), "激活快照": str(快照路径),
            "摘要": 清单["摘要"], "文件数": 清单["文件数"],
            "当前激活": str(快照路径)}


__all__ = ["创建核心快照", "查询核心快照", "兼容性检查", "回滚门禁", "行数上限"]
