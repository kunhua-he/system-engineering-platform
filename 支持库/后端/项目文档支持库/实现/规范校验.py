"""项目文档支持库 · 规范校验原子能力（进程内实现，不对外暴露）。

判据来自**数据文件**（规范判据 JSON），不硬编在代码里：
规范改一句只改数据，判据与规范同源，不会漂移（哲学 5.1 / 4.4）。

判据文件结构（唯一真源：开发文档/规范/Markdown 文档体例规范.md）：

    {
      "判据版本": "1.0.0",
      "唯一真源": "开发文档/规范/Markdown 文档体例规范.md",
      "判据": [
        {"判据id": "单H1", "严重级": "阻断", "说明": "...",
         "类型": "行正则计数", "参数": {"模式": "^# ", "期望": 1, "跳过围栏": true}},
        ...
      ]
    }

已实现判据类型（类型 → 语义）：

| 类型 | 参数 | 语义 |
|---|---|---|
| 行正则计数 | 模式 / 期望 / 跳过围栏 | 命中行数必须等于期望 |
| 围栏配对 | 无 | 行首围栏数必须为偶数 |
| 头部包含 | 关键词 / 行数 | 前 N 行必须包含全部关键词 |
| 链接文字一致 | 无 | `[文字](目标)` 的文字须等于目标文件名 |
| 元信息取值域 | 键 / 取值域 / 行数 | 元信息行的值须以取值域之一开头（只认 `> ` 引用行且行首即键名） |
| 必填项 | 是否权威文档 | 权威文档才执行的判据（其余情况跳过） |
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from 公共契约.基础类型.结果类型 import 结果

围栏行模式 = re.compile(r"^\s*```")
链接模式 = re.compile(r"\[([^\]]*)\]\(([^)\s]+)\)")


def _读判据(判据文件: str) -> tuple[list[dict], str] | None:
    """读判据文件；不可读或结构不符返回 None（由调用方转明确失败）。"""
    路径 = Path(判据文件)
    if not 路径.is_file():
        return None
    try:
        数据 = json.loads(路径.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(数据, dict) or not isinstance(数据.get("判据"), list):
        return None
    return 数据["判据"], str(数据.get("唯一真源", ""))


def _行正则计数(正文: str, 参数: dict) -> list[int]:
    """返回未达标的命中行号；跳过围栏 为真时忽略代码块内的行。

    **期望** 是这条判据的核心：命中行数必须**等于**期望才算通过。
    不给 期望 时退化为「有命中即不通过」。
    """
    模式 = re.compile(str(参数.get("模式", "")))
    跳过围栏 = bool(参数.get("跳过围栏", False))
    命中: list[int] = []
    在围栏内 = False
    for 序号, 行 in enumerate(正文.split("\n"), start=1):
        if 围栏行模式.match(行):
            在围栏内 = not 在围栏内
            continue
        if 跳过围栏 and 在围栏内:
            continue
        if 模式.search(行):
            命中.append(序号)
    if "期望" not in 参数:
        return 命中
    期望 = int(参数.get("期望") or 0)
    if len(命中) == 期望:
        return []
    # 数量不对：有命中时报第一处命中行；一处不中时报第 1 行（缺项比多一项更需要定位起点）
    return 命中 or [1]


def _围栏配对(正文: str, 参数: dict) -> list[int]:
    """围栏数为奇数时，把最后一处未闭合的围栏行号报出来。"""
    围栏行号 = [i for i, 行 in enumerate(正文.split("\n"), start=1) if 围栏行模式.match(行)]
    return [] if len(围栏行号) % 2 == 0 else 围栏行号[-1:]


def _头部包含(正文: str, 参数: dict) -> list[int]:
    """前 N 行未覆盖到的关键词，按第一个关键词所在行报出。"""
    行数 = int(参数.get("行数", 5))
    头部 = "\n".join(正文.split("\n")[:行数])
    缺失 = [k for k in (参数.get("关键词") or []) if str(k) not in 头部]
    return [1] * len(缺失)


def _链接文字一致(正文: str, 参数: dict) -> list[int]:
    """链接文字不等于目标文件名时，报出该行行号（口径见体例规范第六节）。"""
    命中: list[int] = []
    for 序号, 行 in enumerate(正文.split("\n"), start=1):
        for 文字, 目标 in 链接模式.findall(行):
            if 目标.startswith(("http://", "https://", "#", "mailto:")):
                continue
            纯目标 = 目标.split("#")[0].lstrip("./")
            if not 纯目标:
                continue
            if 文字.strip() and 文字.strip() not in (纯目标, Path(纯目标).name):
                命中.append(序号)
    return 命中


def _元信息取值域(正文: str, 参数: dict) -> list[int]:
    """元信息三行的值必须落在取值域内（口径见体例规范第三/3.0 节）。

    参数：`键`（如「口径」）/ `取值域`（前缀列表，值须以其中之一开头）/ `行数`（前 N 行内找）。
    找不到该键所在行 → 报第 1 行（缺行与取值错都算不合规，不静默放过）。
    只认 `> ` 开头的引用行；正文里的同名词不算（防 3.0 节讲的那种「把口径当小标题写段子」被误判为合规）。
    """
    键 = str(参数.get("键", "")).strip()
    取值域 = [str(x) for x in (参数.get("取值域") or [])]
    if not 键 or not 取值域:
        return []
    行数 = int(参数.get("行数", 12))
    for 序号, 行 in enumerate(正文.split("\n")[:行数], start=1):
        if not 行.strip().startswith(">"):
            continue
        # 只认「行首（去引用符与加粗后）就是键名」的行 —— 否则「最后更新：…（按口径直接删除）」这类
        # 会把正文里的「口径」二字误判成元信息行（2026-09-20 实测踩坑）。
        归一行 = 行.lstrip(">").strip().lstrip("* ").strip()
        if not 归一行.startswith(键):
            continue
        值 = 归一行[len(键):]
        if "：" in 值 or ":" in 值:
            值 = 值.split("：", 1)[-1].split(":", 1)[-1]
        值 = 值.strip().lstrip("* ").strip()
        if not any(值.startswith(x) for x in 取值域):
            return [序号]
        return []
    return [1]


执行表 = {
    "行正则计数": _行正则计数,
    "围栏配对": _围栏配对,
    "头部包含": _头部包含,
    "链接文字一致": _链接文字一致,
    "元信息取值域": _元信息取值域,
}


def _跑一条(正文: str, 判据: dict, 是否权威文档: bool) -> dict | None:
    """跑单条判据；不通过返回违规范条目，通过返回 None。"""
    类型 = str(判据.get("类型", ""))
    if 判据.get("仅权威文档") and not 是否权威文档:
        return None
    执行 = 执行表.get(类型)
    if 执行 is None:
        return {
            "判据id": str(判据.get("判据id", "")), "严重级": str(判据.get("严重级", "建议")),
            "说明": f"未实现的判据类型 {类型}（判据文件与支持库版本不一致）", "行号": 0,
        }
    命中行 = 执行(正文, 判据.get("参数") or {})
    if not 命中行:
        return None
    return {
        "判据id": str(判据.get("判据id", "")),
        "严重级": str(判据.get("严重级", "建议")),
        "说明": str(判据.get("说明", "")),
        "行号": 命中行[0],
        "命中行数": len(命中行),
    }


def 校验规范(正文: str = None, 判据文件: str = None, 是否权威文档: bool = False) -> 结果:
    """按规范判据文件逐条校验文档正文。

    参数：正文 / 判据文件（绝对路径）/ 是否权威文档（真=执行仅权威文档的判据）
    返回：``{通过, 违规范条目, 条目数, 驳回项数, 唯一真源}``；判据文件不可读时**明确失败**，
    不假装通过（无判据的「通过」是假绿）。
    """
    if not isinstance(正文, str) or not 正文.strip():
        return 结果.失败("参数不合法", "正文必须是非空文本", 来源="项目文档支持库")
    if not isinstance(判据文件, str) or not 判据文件.strip():
        return 结果.失败("参数不合法", "判据文件必须是非空文本", 来源="项目文档支持库")
    读到 = _读判据(判据文件)
    if 读到 is None:
        return 结果.失败("判据文件不存在", f"判据文件不可读或结构不符: {判据文件}", 来源="项目文档支持库")
    判据列表, 唯一真源 = 读到

    条目 = [x for x in (_跑一条(正文, 判据, bool(是否权威文档)) for 判据 in 判据列表) if x]
    驳回项 = [x for x in 条目 if x["严重级"] == "阻断"]
    return 结果.成功结果({
        "通过": not 驳回项,
        "违规范条目": 条目,
        "条目数": len(条目),
        "驳回项数": len(驳回项),
        "唯一真源": 唯一真源,
    })
