"""公开能力目录：只读取声明，不导入实现。

搜索结果每条覆盖 10 字段：能力id/中文名称/说明/参数(含必填标记)/返回结构/
错误码/版本/提供者/调用示例/验证状态。数据只来自 JSON 声明
（能力定义.json/能力契约/能力数据/包声明.json/验证场景引用.json/验证历史.jsonl），
全程不 import 任何支持库实现；字段缺失时如实标注（"无"/"未声明"），不伪造。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from 开发工具.项目编译.正式包索引 import 构建索引

搜索字段表 = (
    "能力id", "中文名称", "说明", "参数", "返回结构", "错误码",
    "版本", "提供者", "调用示例", "验证状态",
)


def _读取声明(路径: Path) -> dict[str, Any] | None:
    try:
        数据 = json.loads(路径.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return 数据 if isinstance(数据, dict) else None


def _读取列表(路径: Path) -> list[Any]:
    try:
        数据 = json.loads(路径.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return 数据 if isinstance(数据, list) else []


def _按能力id索引(数据: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    """把 能力定义.json 的能力列表 / 参数契约.json 的能力契约 按能力id 建索引。"""
    表: dict[str, dict[str, Any]] = {}
    for 键 in ("能力列表", "能力契约"):
        for 条目 in (数据 or {}).get(键, []):
            if isinstance(条目, dict) and 条目.get("能力id"):
                表[str(条目["能力id"])] = 条目
    return 表


def _包辅助数据(包目录: Path) -> dict[str, Any]:
    """按包目录聚合只读声明（能力定义/参数契约/搜索数据/验证场景）。"""
    return {
        "能力定义": _按能力id索引(_读取声明(包目录 / "能力定义.json")),
        "参数契约": _按能力id索引(_读取声明(包目录 / "能力契约" / "参数契约.json")),
        "搜索数据": {
            str(条目["能力id"]): 条目
            for 条目 in _读取列表(包目录 / "能力数据" / "能力搜索数据.json")
            if isinstance(条目, dict) and 条目.get("能力id")
        },
        "验证场景": _读取声明(包目录 / "验证场景引用.json"),
    }


def _规范参数(参数表: Any) -> list[dict[str, Any]]:
    """参数统一为 {名称, 必填, ...}；来源未声明必填时如实标注"未声明"。"""
    if not isinstance(参数表, list):
        return []
    结果: list[dict[str, Any]] = []
    for 参数 in 参数表:
        if isinstance(参数, str) and 参数:
            结果.append({"名称": 参数, "必填": "未声明"})
            continue
        if not isinstance(参数, dict) or not 参数.get("名称"):
            continue
        项: dict[str, Any] = {"名称": str(参数["名称"]), "必填": 参数.get("必填", "未声明")}
        for 键 in ("类型", "默认值", "说明"):
            if 键 in 参数:
                项[键] = 参数[键]
        结果.append(项)
    return 结果


def _读取验证历史(项目根: Path) -> list[dict[str, Any]]:
    路径 = 项目根 / "开发文档" / "项目证据" / "验证历史.jsonl"
    if not 路径.exists():
        return []
    结果: list[dict[str, Any]] = []
    for 行 in 路径.read_text(encoding="utf-8").splitlines():
        行 = 行.strip()
        if not 行:
            continue
        try:
            记录 = json.loads(行)
        except json.JSONDecodeError:
            continue
        if isinstance(记录, dict):
            结果.append(记录)
    return 结果


def _验证状态(包id: str, 验证场景: dict[str, Any] | None,
               验证历史表: list[dict[str, Any]]) -> str:
    段: list[str] = []
    段.append("有验证场景引用" if isinstance(验证场景, dict) else "无验证场景引用")
    有成功记录 = bool(包id) and any(
        记录.get("退出码") == 0 and 包id in json.dumps(记录, ensure_ascii=False)
        for 记录 in 验证历史表
    )
    段.append("有验证成功记录" if 有成功记录 else "无验证成功记录")
    return "；".join(段)


def _能力记录(声明: dict[str, Any], 包目录: Path,
              包辅助: dict[str, Any],
              验证历史表: list[dict[str, Any]]) -> list[dict[str, Any]]:
    包id = str(声明.get("包id", ""))
    包名 = str(声明.get("中文名称", 声明.get("名称", "")))
    类型 = str(声明.get("类型", ""))
    说明 = str(声明.get("说明", ""))
    包版本 = str(声明.get("版本", ""))
    记录表: list[dict[str, Any]] = []
    for 能力 in 声明.get("提供能力", 声明.get("能力", [])):
        if isinstance(能力, dict):
            能力id = str(能力.get("能力id", ""))
            名称 = str(能力.get("中文名称", 能力.get("名称", 能力id)))
            能力说明 = str(能力.get("说明", 说明))
            参数表 = 能力.get("参数", [])
            返回 = 能力.get("返回", "")
            错误码 = 能力.get("错误码", [])
        else:
            能力id = str(能力)
            名称 = 能力id.rsplit(".", 1)[-1]
            能力说明 = 说明
            参数表, 返回, 错误码 = [], "", []
        if not 能力id:
            continue
        定义 = 包辅助["能力定义"].get(能力id)
        契约 = 包辅助["参数契约"].get(能力id)
        搜索 = 包辅助["搜索数据"].get(能力id)
        来源优先 = [来源 for 来源 in (契约, 定义, 能力) if isinstance(来源, dict)]
        合并返回 = 返回
        for 来源 in 来源优先:
            if 来源.get("返回"):
                合并返回 = 来源["返回"]
                break
        合并错误码 = 错误码
        for 来源 in 来源优先:
            if 来源.get("错误码"):
                合并错误码 = 来源["错误码"]
                break
        参数来源 = 参数表
        for 来源 in 来源优先:
            if isinstance(来源.get("参数"), list):
                参数来源 = 来源["参数"]
                break
        版本 = "无"
        if 定义 and 定义.get("版本"):
            版本 = str(定义["版本"])
        elif 包版本:
            版本 = 包版本
        提供者 = "无"
        if 定义 and isinstance(定义.get("提供者"), dict) and 定义["提供者"].get("默认"):
            提供者 = str(定义["提供者"]["默认"])
        elif 包id:
            提供者 = 包id
        调用示例 = "无"
        if 搜索 and 搜索.get("示例"):
            调用示例 = 搜索["示例"]
        返回结构 = 合并返回 if 合并返回 else "无"
        记录表.append({
            "能力id": 能力id, "中文名称": 名称, "说明": 能力说明,
            "参数": _规范参数(参数来源 if isinstance(参数来源, list) else []),
            "返回结构": 返回结构,
            "错误码": 合并错误码 if 合并错误码 else "无",
            "版本": 版本, "提供者": 提供者, "调用示例": 调用示例,
            "验证状态": _验证状态(包id, 包辅助["验证场景"], 验证历史表),
            "包id": 包id, "包名称": 包名, "类型": 类型, "返回": 返回结构,
        })
    return 记录表


def _全部能力(项目根: Path) -> list[dict[str, Any]]:
    验证历史表 = _读取验证历史(项目根)
    结果: list[dict[str, Any]] = []
    索引 = 构建索引(项目根)
    # 公开目录只读取正式支持库/模块库；Provider 仅供依赖闭包使用，模板已由索引排除。
    for 包目录, 声明 in [*索引["支持库"].values(), *索引["模块库"].values()]:
        包id = str(声明.get("包id", ""))
        if 包id.startswith("支持库.适配层."):
            continue
        # 聚合父包无能力定义.json，能力由子包声明（与正式包索引的 owner 规则一致）；
        # 跳过父包，避免父包无错误码/参数的聚合视图遮蔽子包的完整契约。
        if not (包目录 / "能力定义.json").is_file():
            continue
        包辅助 = _包辅助数据(包目录)
        结果.extend(_能力记录(声明, 包目录, 包辅助, 验证历史表))
    return sorted(结果, key=lambda 项: (项["能力id"], 项["包id"]))


def 搜索公开能力(项目根: Path, 关键词: str, 限制: int = 20) -> list[dict[str, Any]]:
    """按公开声明检索能力，不加载实现源码；每条结果含 10 字段。"""
    关键词 = 关键词.strip().lower()
    候选 = _全部能力(项目根)
    if not 关键词:
        return 候选[: max(1, min(限制, 100))]
    return [
        项 for 项 in 候选
        if 关键词 in json.dumps(项, ensure_ascii=False).lower()
    ][: max(1, min(限制, 100))]


def 读取公开能力(项目根: Path, 能力id: str) -> dict[str, Any] | None:
    for 记录 in _全部能力(项目根):
        if 记录["能力id"] == 能力id:
            return 记录
    return None
