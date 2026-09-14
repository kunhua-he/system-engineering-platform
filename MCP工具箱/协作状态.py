"""开工id父子映射与协作状态：登记任务、聚合查询、收口登记与代码指纹计算。

数据源：
- 协作状态：**底座运行库** `工程缓存/运行数据/底座运行.db` 的 `协作状态` 域（本模块；
  经唯一 SQLite 支持库访问）；旧 `工程缓存/协作状态/{work_id}.json` 只做只读兼容 +
  库里缺的按 work_id 一次性补齐，不再写文件（华哥 2026-09-15 定盘：运行态一律入库、不搞双写）。
- 临时上下文：工程缓存/MCP临时上下文/{work_id}.json（临时上下文.py）
- 反馈：开发文档/项目证据/MCP使用反馈.jsonl
- 验证证据：开发文档/项目证据/验证历史.jsonl
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

from 公共契约.运行时.有界IO import (
    默认JSONL读取上限字节, 默认JSONL读取上限记录, 读取JSONL,
)
from MCP工具箱.临时上下文 import 读取临时上下文

系统根 = Path(__file__).resolve().parents[1]
默认状态目录 = 系统根 / "工程缓存" / "协作状态"
默认反馈文件 = 系统根 / "开发文档" / "项目证据" / "MCP使用反馈.jsonl"
默认验证历史文件 = 系统根 / "开发文档" / "项目证据" / "验证历史.jsonl"
默认临时上下文目录 = 系统根 / "工程缓存" / "MCP临时上下文"

错误_work_id非法 = "WORK_ID_INVALID"
错误_任务不存在 = "TASK_NOT_FOUND"
错误_未反馈阻断 = "FEEDBACK_BLOCKED"
错误_证据不匹配 = "EVIDENCE_MISMATCH"
错误_登记失败 = "REGISTRATION_FAILED"

# 最近一次运行库访问失败：失败必须可见（模块级字段 + stderr），不许静默吞异常。
同步错误 = ""

_开工id模式 = re.compile(r"^[0-9a-fA-F]{16}$")
_排除片段表 = ("__pycache__", "工程缓存", "测试中心缓存", ".git", "完整性摘要.json", "项目证据", "临时文件")


def 默认运行库路径() -> str:
    """底座运行库路径（运行态唯一落点；可用 `系统库运行库` 环境变量覆盖）。"""
    环境 = os.environ.get("系统库运行库", "").strip()
    if 环境:
        return 环境
    return str(系统根 / "工程缓存" / "运行数据" / "底座运行.db")


def _校验开工id(work_id: str) -> str:
    """校验并规范化 16 位十六进制开工id。"""
    文本 = str(work_id).strip()
    if not _开工id模式.fullmatch(文本):
        raise ValueError("work_id 必须为 16 位十六进制")
    return 文本.lower()


def _记同步错误(说明: str) -> None:
    """记录运行库访问失败：写模块级 `同步错误` 并落 stderr（不静默）。"""
    global 同步错误
    同步错误 = 说明
    print(f"协作状态-运行库同步失败：{说明}", file=sys.stderr)


def _运行库调用(能力id: str, 参数: dict[str, Any]) -> Any:
    """经唯一调用入口访问底座运行库；不可用时记入 `同步错误` 并返回 None。"""
    try:
        # 注册惰性装配钩子：MCP 管理端进程不经加载器装配，缺这步会恒「未装配」。
        import 运行核心.能力调用.唯一能力调用  # noqa: F401

        from 公共契约.能力契约.调用器 import 获取能力调用器

        return 获取能力调用器().调用能力(能力id, 参数)
    except Exception as 错误:  # noqa: BLE001 —— 运行库不可用必须可见，见 同步错误
        _记同步错误(f"运行库不可用：{错误}")
        return None


def _读运行库(运行库路径: str) -> dict[str, dict[str, Any]] | None:
    """从运行库读回全部协作状态记录；库不可用或为空时返回 None（交给旧文件回退）。"""
    结果对象 = _运行库调用(
        "数据库连接支持库.SQLite数据库.查询运行态",
        {"数据库路径": 运行库路径, "域": "协作状态", "限制": 1000, "超时秒": 10.0},
    )
    if 结果对象 is None or not 结果对象.成功:
        return None
    值 = 结果对象.值 if isinstance(结果对象.值, dict) else {}
    行列表 = 值.get("行列表") or []
    if not 行列表:
        return None
    记录表: dict[str, dict[str, Any]] = {}
    for 行 in 行列表:
        if not isinstance(行, dict):
            continue
        载荷 = 行.get("载荷")
        try:
            记录 = json.loads(载荷) if isinstance(载荷, str) and 载荷 else {}
        except json.JSONDecodeError:
            continue
        if not isinstance(记录, dict) or not 记录:
            continue
        键 = str(记录.get("work_id") or 行.get("id") or "").lower()
        if 键:
            记录表[键] = _还原清单字段(记录)
    return 记录表 or None


def _读旧文件(状态目录: Path) -> dict[str, dict[str, Any]]:
    """迁移期只读兼容：读旧 `{work_id}.json`（首次读到时一次性搬入运行库，此后只读）。"""
    记录表: dict[str, dict[str, Any]] = {}
    if not 状态目录.is_dir():
        return 记录表
    for 路径 in sorted(状态目录.glob("*.json")):
        try:
            记录 = json.loads(路径.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(记录, dict) and 记录:
            记录表[路径.stem.lower()] = 记录
    return 记录表


_清单列字段 = ("允许路径", "子任务列表")  # 库表这两列是 TEXT：列表按 JSON 文本落列


def _库视图(记录: dict[str, Any]) -> dict[str, Any]:
    """落库视图：库表列只收 TEXT/REAL，列表类字段转 JSON 文本（读回时还原）。

    运行库 `协作状态` 表的 `允许路径`/`子任务列表` 是 TEXT 列，直接塞 list 会被
    SQLite 拒绑（表结构属支持库，本批不动）；故此处按 JSON 文本落列，`_读运行库`
    一律还原回列表——对外契约仍是列表，读回一致。
    """
    视图 = dict(记录)
    for 键 in _清单列字段:
        if isinstance(视图.get(键), (list, dict)):
            视图[键] = json.dumps(视图[键], ensure_ascii=False)
    视图["状态"] = str(视图.get("生命周期") or 视图.get("状态") or "创建")
    return 视图


def _还原清单字段(记录: dict[str, Any]) -> dict[str, Any]:
    """把落库时转成 JSON 文本的列表字段还原为列表（对外契约一致）。"""
    for 键 in _清单列字段:
        值 = 记录.get(键)
        if isinstance(值, str):
            try:
                记录[键] = json.loads(值)
            except json.JSONDecodeError:
                continue
    return 记录


def _写运行库(运行库路径: str, 记录: dict[str, Any]) -> bool:
    """把一条协作状态记录写进运行库（主键 work_id）；失败记入 `同步错误` 并返回 False。"""
    结果对象 = _运行库调用(
        "数据库连接支持库.SQLite数据库.写入运行态",
        {"数据库路径": 运行库路径, "域": "协作状态",
         "记录": _库视图(记录), "超时秒": 10.0},
    )
    if 结果对象 is None or not 结果对象.成功:
        说明 = getattr(结果对象, "错误说明", "") or "运行库不可用"
        _记同步错误(f"协作状态落库失败（work_id {记录.get('work_id', '')}）：{说明}")
        return False
    return True


def 协作状态记录表(*, 状态目录: Path | None = None, 运行库路径: str | None = None,
              一次性搬迁: bool = True) -> dict[str, dict[str, Any]]:
    """协作状态记录表：**库优先**；库空回退旧文件；旧文件里库里没有的记录按 work_id 缺页补齐。

    返回 {work_id: 记录}（work_id 一律小写）。旧文件只读、不删、不覆盖库记录；
    补齐只在库里确实缺该 work_id 时发生（幂等，不双写）。
    """
    状态目录 = Path(状态目录) if 状态目录 else 默认状态目录
    库路径 = str(运行库路径) if 运行库路径 else 默认运行库路径()
    记录表 = _读运行库(库路径)
    旧记录表 = _读旧文件(状态目录) if 一次性搬迁 else {}
    缺失 = {键: 记录 for 键, 记录 in 旧记录表.items()
            if 记录表 is None or 键 not in 记录表}
    for 记录 in 缺失.values():
        _写运行库(库路径, 记录)
    if 记录表 is None:
        return dict(旧记录表)
    记录表.update(缺失)
    return 记录表


def 搬迁旧文件(*, 状态目录: Path | None = None, 运行库路径: str | None = None) -> dict[str, Any]:
    """首次搬迁入口：把旧 `{work_id}.json` 一次性搬入运行库；旧文件保留不删。"""
    状态目录 = Path(状态目录) if 状态目录 else 默认状态目录
    库路径 = str(运行库路径) if 运行库路径 else 默认运行库路径()
    旧记录表 = _读旧文件(状态目录)
    已搬 = 0
    for 记录 in 旧记录表.values():
        if _写运行库(库路径, 记录):
            已搬 += 1
    return {"成功": 已搬 == len(旧记录表), "旧文件数": len(旧记录表), "已搬迁": 已搬,
            "运行库路径": 库路径, "同步错误": 同步错误}


def 计算代码指纹(目录: Path) -> dict[str, Any]:
    """目录内容摘要（sha256 前 16 位），排除工程缓存目录，与当前模块验证证据保持一致。"""
    根 = Path(目录)
    if not 根.is_dir():
        return {"成功": False, "错误码": 错误_登记失败, "消息": "目录不存在，无法计算代码指纹"}
    摘要器 = hashlib.sha256()
    for 文件 in sorted(根.rglob("*")):
        if not 文件.is_file():
            continue
        相对 = 文件.relative_to(根)
        if any(段 in _排除片段表 for 段 in 相对.parts):
            # 按路径段名精确排除缓存/证据目录。子串匹配会把 开发工具/工程缓存回收.py、
            # 支持库/适配层/Tesseract提供者/实现/临时文件.py 这类真源码一并跳过，
            # 导致这些文件改了内容指纹也不变，收口比对与证据复用被误判为"已验证"。
            continue
        摘要器.update(str(相对).encode("utf-8"))
        摘要器.update(文件.read_bytes())
    return {"成功": True, "指纹": 摘要器.hexdigest()[:16]}


def 登记任务(
    work_id: str, *, 任务: str, 角色: str, worktree路径: str,
    允许路径: list[str], 基线提交: str, parent_work_id: str = "",
    子任务列表: list[str] | None = None, 代码指纹: str = "",
    状态目录: Path | None = None, 运行库路径: str | None = None,
) -> dict[str, Any]:
    """登记任务（父或子）：写入底座运行库 `协作状态` 域（主键 work_id）。

    子任务登记时自动追加到父任务的子任务列表；父任务可预声明子任务列表。
    旧 `工程缓存/协作状态/{work_id}.json` 仅供只读兼容，不再写。
    """
    try:
        规范化id = _校验开工id(work_id)
        规范化父id = _校验开工id(parent_work_id) if parent_work_id else ""
        子id表 = [_校验开工id(项) for 项 in (子任务列表 or [])]
    except ValueError:
        return {"成功": False, "错误码": 错误_work_id非法, "消息": "work_id 必须为 16 位十六进制"}
    状态目录 = 状态目录 or 默认状态目录
    库路径 = str(运行库路径) if 运行库路径 else 默认运行库路径()
    if not str(任务).strip() or not str(角色).strip():
        return {"成功": False, "错误码": 错误_登记失败, "消息": "任务和角色不能为空"}
    已登记表 = 协作状态记录表(状态目录=状态目录, 运行库路径=库路径)
    if 规范化id in 已登记表:
        return {"成功": False, "错误码": 错误_登记失败, "消息": f"{规范化id} 已登记，禁止重复登记"}
    指纹 = str(代码指纹).strip()
    if not 指纹:
        指纹结果 = 计算代码指纹(worktree路径)
        指纹 = str(指纹结果.get("指纹", "")) if 指纹结果.get("成功") else ""
    记录: dict[str, Any] = {
        "work_id": 规范化id, "任务": str(任务).strip(), "角色": str(角色).strip(),
        "worktree路径": str(worktree路径), "允许路径": [str(项) for 项 in 允许路径],
        "基线提交": str(基线提交), "代码指纹": 指纹,
        "parent_work_id": 规范化父id, "子任务列表": 子id表,
        "生命周期": "创建", "登记时间": time.time(),
    }
    if 规范化父id:
        父记录 = 已登记表.get(规范化父id)
        if 父记录 is None:
            return {"成功": False, "错误码": 错误_登记失败, "消息": f"父任务 {规范化父id} 未登记"}
        父子表 = list(父记录.get("子任务列表", []))
        if 规范化id not in 父子表:
            父子表.append(规范化id)
        父记录["子任务列表"] = 父子表
        if not _写运行库(库路径, 父记录):
            return {"成功": False, "错误码": 错误_登记失败,
                    "消息": f"父任务 {规范化父id} 子任务列表落库失败", "同步错误": 同步错误}
    if not _写运行库(库路径, 记录):
        return {"成功": False, "错误码": 错误_登记失败,
                "消息": f"{规范化id} 协作状态落库失败", "同步错误": 同步错误}
    return {"成功": True, "work_id": 规范化id, "parent_work_id": 规范化父id, "生命周期": "创建"}


def _读取记录(状态目录: Path, work_id: str, *,
             运行库路径: str | None = None) -> dict[str, Any] | None:
    记录表 = 协作状态记录表(状态目录=状态目录, 运行库路径=运行库路径)
    return 记录表.get(str(work_id).strip().lower())


def 已登记(work_id: str, *, 状态目录: Path | None = None,
         运行库路径: str | None = None) -> bool:
    """该开工id是否已登记：先查运行库，库空再查旧文件（与 查询协作状态 同口径）。"""
    文本 = str(work_id).strip().lower()
    if not _开工id模式.fullmatch(文本):
        return False
    return 文本 in 协作状态记录表(状态目录=状态目录, 运行库路径=运行库路径)


def _读取反馈状态(反馈文件: Path, work_id: str) -> str:
    记录列表, _ = 读取JSONL(
        反馈文件, 最大字节数=默认JSONL读取上限字节,
        最大记录数=默认JSONL读取上限记录,
    )
    for 记录 in reversed(记录列表):
        if 记录.get("开工id") == work_id:
            return "已反馈"
    return "未反馈"


def _读取验证证据(验证历史文件: Path, work_id: str) -> list[dict[str, Any]]:
    记录列表, _ = 读取JSONL(
        验证历史文件, 最大字节数=默认JSONL读取上限字节,
        最大记录数=默认JSONL读取上限记录,
    )
    证据表: list[dict[str, Any]] = []
    for 记录 in 记录列表:
        if 记录.get("开工id") != work_id:
            continue
        证据表.append({
            "名称": 记录.get("名称", ""), "退出码": 记录.get("退出码"),
            "提交": 记录.get("提交", ""),
            # 优先取目录内容摘要 `指纹`（与 `计算代码指纹` 同口径）；旧证据只有
            # `工作区指纹`（sha256(git status)，取值域不同）时才回退，保持兼容。
            "指纹": 记录.get("指纹") or 记录.get("工作区指纹", ""),
            "时间": 记录.get("时间", ""),
        })
    return 证据表


def _聚合一条(
    记录: dict[str, Any], work_id: str, 已登记表: dict[str, dict[str, Any]],
    反馈文件: Path, 验证历史文件: Path, 临时上下文目录: Path,
) -> dict[str, Any] | None:
    """聚合单个任务：任务信息 + 子任务 + 反馈 + 验证证据 + 生命周期 + 阻断标记。"""
    if not 记录:
        return None
    子任务列表 = [str(项) for 项 in 记录.get("子任务列表", [])]
    子任务状态 = {
        子id: ("已登记" if 子id.strip().lower() in 已登记表 else "未登记")
        for 子id in 子任务列表
    }
    反馈状态 = _读取反馈状态(反馈文件, work_id)
    验证证据 = _读取验证证据(验证历史文件, work_id)
    指纹结果 = 计算代码指纹(记录.get("worktree路径", ""))
    当前指纹 = str(指纹结果.get("指纹", "")) if 指纹结果.get("成功") else ""
    阻断标记: list[str] = []
    if 反馈状态 == "未反馈":
        阻断标记.append("未反馈")
    if 验证证据 and str(验证证据[-1].get("指纹", "")) != 当前指纹:
        阻断标记.append("证据指纹不匹配")
    if any(状态 == "未登记" for 状态 in 子任务状态.values()):
        阻断标记.append("子代理未登记")
    临时上下文 = 读取临时上下文(临时上下文目录, work_id)
    临时上下文 = 临时上下文 if 临时上下文.get("成功") else None
    生命周期 = str(记录.get("生命周期", "创建"))
    if 生命周期 not in ("完成", "关闭"):
        生命周期 = "进行" if 反馈状态 == "已反馈" else "创建"
    return {
        "work_id": work_id, "任务": 记录.get("任务", ""), "角色": 记录.get("角色", ""),
        "父任务": 记录.get("parent_work_id", ""), "worktree路径": 记录.get("worktree路径", ""),
        "允许路径": 记录.get("允许路径", []), "基线提交": 记录.get("基线提交", ""),
        "代码指纹": 记录.get("代码指纹", ""), "子任务列表": 子任务列表,
        "子任务状态": 子任务状态, "反馈状态": 反馈状态, "验证证据": 验证证据,
        "临时上下文": 临时上下文, "生命周期": 生命周期, "阻断标记": 阻断标记,
    }


def 查询协作状态(
    work_id: str = "", 任务关键词: str = "", *,
    状态目录: Path | None = None, 反馈文件: Path | None = None,
    验证历史文件: Path | None = None, 临时上下文目录: Path | None = None,
    运行库路径: str | None = None,
) -> dict[str, Any]:
    """按开工id或任务关键词聚合查询协作状态（记录取自运行库，库空回退旧文件）。"""
    状态目录 = 状态目录 or 默认状态目录
    反馈文件 = 反馈文件 or 默认反馈文件
    验证历史文件 = 验证历史文件 or 默认验证历史文件
    临时上下文目录 = 临时上下文目录 or 默认临时上下文目录
    记录表 = 协作状态记录表(状态目录=状态目录, 运行库路径=运行库路径)
    if work_id:
        try:
            规范化id = _校验开工id(work_id)
        except ValueError:
            return {"成功": False, "错误码": 错误_work_id非法, "消息": "work_id 必须为 16 位十六进制"}
        聚合 = _聚合一条(记录表.get(规范化id, {}), 规范化id, 记录表,
                        反馈文件, 验证历史文件, 临时上下文目录)
        if 聚合 is None:
            return {"成功": False, "错误码": 错误_任务不存在, "work_id": 规范化id,
                    "阻断标记": ["未登记"], "消息": f"{规范化id} 未登记"}
        return {"成功": True, "查询方式": "work_id", "数量": 1, "结果列表": [聚合]}
    if 任务关键词:
        关键词 = str(任务关键词).strip()
        if not 关键词:
            return {"成功": False, "错误码": 错误_work_id非法, "消息": "查询条件为空"}
        结果列表: list[dict[str, Any]] = []
        for 键, 记录 in sorted(记录表.items()):
            if 关键词.lower() in str(记录.get("任务", "")).lower():
                聚合 = _聚合一条(记录, 键, 记录表, 反馈文件, 验证历史文件, 临时上下文目录)
                if 聚合 is not None:
                    结果列表.append(聚合)
        if not 结果列表:
            return {"成功": False, "错误码": 错误_任务不存在, "消息": f"未找到任务包含关键词：{关键词}"}
        return {"成功": True, "查询方式": "任务关键词", "数量": len(结果列表), "结果列表": 结果列表}
    return {"成功": False, "错误码": 错误_work_id非法, "消息": "必须提供 work_id 或任务关键词"}


def 收口登记(
    work_id: str, *, 五件套路径: str, 结论: str,
    状态目录: Path | None = None, 反馈文件: Path | None = None,
    验证历史文件: Path | None = None, 运行库路径: str | None = None,
) -> dict[str, Any]:
    """收口登记（delivery_closeout）：生命周期置为完成，写入五件套路径与结论。

    校验：未提交 MCP 反馈阻断拒绝；存在验证证据且指纹与当前代码不一致时阻断。
    落点是底座运行库 `协作状态` 域（不再写旧 `{work_id}.json`）。
    """
    try:
        规范化id = _校验开工id(work_id)
    except ValueError:
        return {"成功": False, "错误码": 错误_work_id非法, "消息": "work_id 必须为 16 位十六进制"}
    状态目录 = 状态目录 or 默认状态目录
    库路径 = str(运行库路径) if 运行库路径 else 默认运行库路径()
    反馈文件 = 反馈文件 or 默认反馈文件
    验证历史文件 = 验证历史文件 or 默认验证历史文件
    if not str(五件套路径).strip() or not str(结论).strip():
        return {"成功": False, "错误码": 错误_登记失败, "消息": "五件套路径和结论不能为空"}
    记录 = _读取记录(状态目录, 规范化id, 运行库路径=库路径)
    if 记录 is None:
        return {"成功": False, "错误码": 错误_任务不存在, "work_id": 规范化id,
                "阻断标记": ["未登记"], "消息": f"{规范化id} 未登记，无法收口"}
    if _读取反馈状态(反馈文件, 规范化id) != "已反馈":
        return {"成功": False, "错误码": 错误_未反馈阻断, "work_id": 规范化id,
                "阻断标记": ["未反馈"], "消息": "未提交 MCP 反馈，阻断收口"}
    验证证据 = _读取验证证据(验证历史文件, 规范化id)
    指纹结果 = 计算代码指纹(记录.get("worktree路径", ""))
    当前指纹 = str(指纹结果.get("指纹", "")) if 指纹结果.get("成功") else ""
    if 验证证据 and str(验证证据[-1].get("指纹", "")) != 当前指纹:
        return {"成功": False, "错误码": 错误_证据不匹配, "work_id": 规范化id,
                "阻断标记": ["证据指纹不匹配"], "消息": "验证证据指纹与当前代码指纹不匹配，阻断收口"}
    记录["生命周期"] = "完成"
    记录["五件套路径"] = str(五件套路径).strip()
    记录["收口结论"] = str(结论).strip()
    记录["收口时间"] = time.time()
    if not _写运行库(库路径, 记录):
        return {"成功": False, "错误码": 错误_登记失败, "work_id": 规范化id,
                "消息": f"{规范化id} 收口落库失败", "同步错误": 同步错误}
    return {"成功": True, "work_id": 规范化id, "生命周期": "完成",
            "五件套路径": 记录["五件套路径"], "收口结论": 记录["收口结论"]}
