"""开工id父子映射与协作状态：登记任务、聚合查询、收口登记与代码指纹计算。

数据源：
- 协作状态：工程缓存/协作状态/{work_id}.json（本模块）
- 临时上下文：工程缓存/MCP临时上下文/{work_id}.json（临时上下文.py）
- 反馈：开发文档/项目证据/MCP使用反馈.jsonl
- 验证证据：开发文档/项目证据/验证历史.jsonl
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from pathlib import Path
from typing import Any

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

_开工id模式 = re.compile(r"^[0-9a-fA-F]{16}$")
_排除片段表 = ("pycache", "工程缓存", "测试中心缓存", ".git", "完整性摘要.json")


def _校验开工id(work_id: str) -> str:
    """校验并规范化 16 位十六进制开工id。"""
    文本 = str(work_id).strip()
    if not _开工id模式.fullmatch(文本):
        raise ValueError("work_id 必须为 16 位十六进制")
    return 文本.lower()


def _记录路径(状态目录: Path, work_id: str) -> Path:
    return 状态目录 / f"{work_id}.json"


def _原子写入(路径: Path, 记录: dict[str, Any]) -> None:
    路径.parent.mkdir(parents=True, exist_ok=True)
    临时路径 = 路径.with_suffix(".json.tmp")
    临时路径.write_text(json.dumps(记录, ensure_ascii=False, indent=2), encoding="utf-8")
    临时路径.replace(路径)


def 计算代码指纹(目录: Path) -> dict[str, Any]:
    """目录内容摘要（sha256 前 16 位），复用运行测试.py 目录摘要语义：排除缓存目录。"""
    根 = Path(目录)
    if not 根.is_dir():
        return {"成功": False, "错误码": 错误_登记失败, "消息": "目录不存在，无法计算代码指纹"}
    摘要器 = hashlib.sha256()
    for 文件 in sorted(根.rglob("*")):
        if not 文件.is_file():
            continue
        相对 = 文件.relative_to(根)
        if any(片段 in 段 for 片段 in _排除片段表 for 段 in 相对.parts):
            continue  # 只按相对路径段名（子串）排除缓存，避免 TMPDIR 前缀误匹配
        摘要器.update(str(相对).encode("utf-8"))
        摘要器.update(文件.read_bytes())
    return {"成功": True, "指纹": 摘要器.hexdigest()[:16]}


def 登记任务(
    work_id: str, *, 任务: str, 角色: str, worktree路径: str,
    允许路径: list[str], 基线提交: str, parent_work_id: str = "",
    子任务列表: list[str] | None = None, 代码指纹: str = "",
    状态目录: Path | None = None,
) -> dict[str, Any]:
    """登记任务（父或子）：写入工程缓存/协作状态/{work_id}.json。

    子任务登记时自动追加到父任务的子任务列表；父任务可预声明子任务列表。
    """
    try:
        规范化id = _校验开工id(work_id)
        规范化父id = _校验开工id(parent_work_id) if parent_work_id else ""
        子id表 = [_校验开工id(项) for 项 in (子任务列表 or [])]
    except ValueError:
        return {"成功": False, "错误码": 错误_work_id非法, "消息": "work_id 必须为 16 位十六进制"}
    状态目录 = 状态目录 or 默认状态目录
    if not str(任务).strip() or not str(角色).strip():
        return {"成功": False, "错误码": 错误_登记失败, "消息": "任务和角色不能为空"}
    路径 = _记录路径(状态目录, 规范化id)
    if 路径.is_file():
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
        父路径 = _记录路径(状态目录, 规范化父id)
        if not 父路径.is_file():
            return {"成功": False, "错误码": 错误_登记失败, "消息": f"父任务 {规范化父id} 未登记"}
        父记录 = json.loads(父路径.read_text(encoding="utf-8"))
        父子表 = list(父记录.get("子任务列表", []))
        if 规范化id not in 父子表:
            父子表.append(规范化id)
        父记录["子任务列表"] = 父子表
        _原子写入(父路径, 父记录)
    _原子写入(路径, 记录)
    return {"成功": True, "work_id": 规范化id, "parent_work_id": 规范化父id, "生命周期": "创建"}


def _读取记录(状态目录: Path, work_id: str) -> dict[str, Any] | None:
    路径 = _记录路径(状态目录, work_id)
    if not 路径.is_file():
        return None
    try:
        return json.loads(路径.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _读取反馈状态(反馈文件: Path, work_id: str) -> str:
    if not 反馈文件.is_file():
        return "未反馈"
    for 行 in reversed(反馈文件.read_text(encoding="utf-8").splitlines()):
        try:
            记录 = json.loads(行)
        except json.JSONDecodeError:
            continue
        if 记录.get("开工id") == work_id:
            return "已反馈"
    return "未反馈"


def _读取验证证据(验证历史文件: Path, work_id: str) -> list[dict[str, Any]]:
    if not 验证历史文件.is_file():
        return []
    证据表: list[dict[str, Any]] = []
    for 行 in 验证历史文件.read_text(encoding="utf-8").splitlines():
        try:
            记录 = json.loads(行)
        except json.JSONDecodeError:
            continue
        if 记录.get("开工id") != work_id:
            continue
        证据表.append({
            "名称": 记录.get("名称", ""), "退出码": 记录.get("退出码"),
            "提交": 记录.get("提交", ""), "指纹": 记录.get("工作区指纹", ""),
            "时间": 记录.get("时间", ""),
        })
    return 证据表


def _聚合一条(
    状态目录: Path, work_id: str, 反馈文件: Path, 验证历史文件: Path, 临时上下文目录: Path,
) -> dict[str, Any] | None:
    """聚合单个任务：任务信息 + 子任务 + 反馈 + 验证证据 + 生命周期 + 阻断标记。"""
    记录 = _读取记录(状态目录, work_id)
    if 记录 is None:
        return None
    子任务列表 = [str(项) for 项 in 记录.get("子任务列表", [])]
    子任务状态 = {
        子id: ("已登记" if _记录路径(状态目录, 子id).is_file() else "未登记")
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
) -> dict[str, Any]:
    """按开工id或任务关键词聚合查询协作状态。"""
    状态目录 = 状态目录 or 默认状态目录
    反馈文件 = 反馈文件 or 默认反馈文件
    验证历史文件 = 验证历史文件 or 默认验证历史文件
    临时上下文目录 = 临时上下文目录 or 默认临时上下文目录
    if work_id:
        try:
            规范化id = _校验开工id(work_id)
        except ValueError:
            return {"成功": False, "错误码": 错误_work_id非法, "消息": "work_id 必须为 16 位十六进制"}
        聚合 = _聚合一条(状态目录, 规范化id, 反馈文件, 验证历史文件, 临时上下文目录)
        if 聚合 is None:
            return {"成功": False, "错误码": 错误_任务不存在, "work_id": 规范化id,
                    "阻断标记": ["未登记"], "消息": f"{规范化id} 未登记"}
        return {"成功": True, "查询方式": "work_id", "数量": 1, "结果列表": [聚合]}
    if 任务关键词:
        关键词 = str(任务关键词).strip()
        if not 关键词:
            return {"成功": False, "错误码": 错误_work_id非法, "消息": "查询条件为空"}
        结果列表: list[dict[str, Any]] = []
        if 状态目录.is_dir():
            for 路径 in sorted(状态目录.glob("*.json")):
                记录 = _读取记录(状态目录, 路径.stem)
                if 记录 is None:
                    continue
                if 关键词.lower() in str(记录.get("任务", "")).lower():
                    聚合 = _聚合一条(状态目录, 路径.stem, 反馈文件, 验证历史文件, 临时上下文目录)
                    if 聚合 is not None:
                        结果列表.append(聚合)
        if not 结果列表:
            return {"成功": False, "错误码": 错误_任务不存在, "消息": f"未找到任务包含关键词：{关键词}"}
        return {"成功": True, "查询方式": "任务关键词", "数量": len(结果列表), "结果列表": 结果列表}
    return {"成功": False, "错误码": 错误_work_id非法, "消息": "必须提供 work_id 或任务关键词"}


def 收口登记(
    work_id: str, *, 五件套路径: str, 结论: str,
    状态目录: Path | None = None, 反馈文件: Path | None = None,
    验证历史文件: Path | None = None,
) -> dict[str, Any]:
    """收口登记（delivery_closeout）：生命周期置为完成，写入五件套路径与结论。

    校验：未提交 MCP 反馈阻断拒绝；存在验证证据且指纹与当前代码不一致时阻断。
    """
    try:
        规范化id = _校验开工id(work_id)
    except ValueError:
        return {"成功": False, "错误码": 错误_work_id非法, "消息": "work_id 必须为 16 位十六进制"}
    状态目录 = 状态目录 or 默认状态目录
    反馈文件 = 反馈文件 or 默认反馈文件
    验证历史文件 = 验证历史文件 or 默认验证历史文件
    if not str(五件套路径).strip() or not str(结论).strip():
        return {"成功": False, "错误码": 错误_登记失败, "消息": "五件套路径和结论不能为空"}
    记录 = _读取记录(状态目录, 规范化id)
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
    _原子写入(_记录路径(状态目录, 规范化id), 记录)
    return {"成功": True, "work_id": 规范化id, "生命周期": "完成",
            "五件套路径": 记录["五件套路径"], "收口结论": 记录["收口结论"]}
