"""激活指针：`当前.json` 的**唯一 schema**（同一件事只有一种表达）。

为什么单独成文件（2026-09-18 现场两个同名文件的收口）：

现场有两份都叫 `当前.json` 的激活指针，**同名不同 schema**：

| 文件 | 键集 |
|---|---|
| `工程缓存/制品仓库/平台客户端制品/当前.json` | `摘要sha256`、`路径` |
| `工程缓存/制品仓库/平台客户端环境/当前.json` | `摘要sha256`、`制品目录`、`制品摘要`、`版本`、`栅栏令牌` |

两份文件承载的是**同一个概念**（「现在生效的是哪个制品」），却各写一套键 ——
这是「同一件事两种表达」（哲学 1.3）的教科书形态：读的人必须按文件名猜 schema，
写的人各写各的。

本模块是收口落点，**不新增第三套**：

- **唯一 schema = `指针键表`**（取现场更完整的一套：环境指针那套，它多带
  `制品摘要`/`版本`/`栅栏令牌`，是发布管理 CAS 诊断要用的字段）；
- **唯一写入点 = `写激活指针`**：任何 `当前.json` 落盘都只写 `指针键表` 里的键，
  不夹带第二套表达；
- **兼容读取 = `归一激活指针`**：历史写法 `路径`（= 制品目录）在**读取侧**归一为
  `制品目录`，正文里不再出现第二个键名。历史文件不必改写即可被同一套 schema 读懂，
  因此不需要「先迁移才能读」的窗口期，也就不需要第三套 schema 过渡。

`路径` 只作为**历史兼容键**存在于读取侧（`兼容路径键`）。改写历史文件属可选迁移
（见 `写激活指针` 的调用方），不是读通的前提。
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

# 唯一 schema：任何 `当前.json` 的正文都只有这五个键（顺序即落盘顺序）。
指针键表 = ("摘要sha256", "制品目录", "制品摘要", "版本", "栅栏令牌")
# 历史兼容键（**只在读取侧**）：旧写法把「制品目录」叫 `路径`。
兼容路径键 = "路径"
指针文件名 = "当前.json"


def 归一激活指针(原始: dict[str, Any] | None) -> dict[str, Any]:
    """任意形态的指针正文 → 唯一 schema 的字典（**读侧收口**，不做任何写入）。

    归一规则：
    - `制品目录` 取 `制品目录`，缺失时回落历史键 `路径`（两者是同一件事的两个写法）；
    - 缺失/不可解析的字段按类型补零值（`""` / `0`），不丢键——调用方拿到的字典
      **键集恒定**，不必再判「有哪个键」；
    - 额外键（历史残留）不进返回：schema 之外的东西不参与语义。
    """
    原始 = 原始 or {}
    制品目录 = 原始.get("制品目录") or 原始.get(兼容路径键) or ""
    try:
        版本 = int(原始.get("版本") or 0)
    except (TypeError, ValueError):
        版本 = 0
    try:
        栅栏令牌 = int(原始.get("栅栏令牌") or 0)
    except (TypeError, ValueError):
        栅栏令牌 = 0
    return {
        "摘要sha256": str(原始.get("摘要sha256") or ""),
        "制品目录": str(制品目录),
        "制品摘要": str(原始.get("制品摘要") or ""),
        "版本": 版本,
        "栅栏令牌": 栅栏令牌,
    }


def 读取激活指针(路径: Path | str) -> dict[str, Any] | None:
    """读一份激活指针并归一到唯一 schema；文件不存在返回 None。

    只读：不创建目录、不写任何文件。JSON 不可读时**抛出**（`OSError` /
    `json.JSONDecodeError`）——「读不成」与「没有」是两件事，调用方分别处理，
    不在这里静默压成同一个 None。
    """
    路径 = Path(路径)
    if not 路径.is_file():
        return None
    return 归一激活指针(json.loads(路径.read_text(encoding="utf-8")))


def 写激活指针(路径: Path | str, 指针: dict[str, Any], *,
               保留额外键: bool = False) -> None:
    """按唯一 schema 原子写指针（临时文件 → fsync → `os.replace` → 目录 fsync）。

    **唯一落盘点**：入库/安装/重建/重置/回收规范化全部走这里，不得各写各的
    `json.dumps`（那正是两份 schema 能各活一半的原因）。

    `保留额外键=False`（缺省）时只落 `指针键表` 的键：写出来的文件必然是同一种
    表达。历史兼容键 `路径` 属 schema 之外，因此**不会**被写出——需要让历史读法
    继续可用的调用方，请用 `保留额外键=True` 显式说明原因（缺省不留后门）。
    """
    路径 = Path(路径)
    归一 = 归一激活指针(指针)
    正文: dict[str, Any] = {}
    if 保留额外键:
        for 键, 值 in (指针 or {}).items():
            if 键 not in 指针键表:
                正文[键] = 值
    for 键 in 指针键表:
        正文[键] = 归一[键]
    路径.parent.mkdir(parents=True, exist_ok=True)
    临时路径 = 路径.with_name(f".{路径.name}.tmp")
    临时路径.write_text(json.dumps(正文, ensure_ascii=False), encoding="utf-8")
    with open(临时路径, "rb") as 句柄:
        os.fsync(句柄.fileno())
    os.replace(临时路径, 路径)
    目录句柄 = os.open(路径.parent, os.O_RDONLY)
    try:
        os.fsync(目录句柄)
    finally:
        os.close(目录句柄)


def 指针形态(路径: Path | str) -> dict[str, Any]:
    """诊断一份指针文件的形态（只读）：它用的是统一 schema 还是历史写法。

    返回 `{存在, 可读, 原始键, 统一键, 历史写法, 归一键集, 已统一}`。
    历史写法 = 正文里出现了 `兼容路径键`；`已统一` = 正文键集恰好等于 `指针键表`。
    **不评判、不修改**：调用方（回收能力/门禁）据此决定要不要迁移。
    """
    路径 = Path(路径)
    结论: dict[str, Any] = {
        "存在": 路径.is_file(), "可读": False,
        "原始键": [], "统一键": list(指针键表), "历史写法": False,
        "归一键集": [], "已统一": False,
    }
    if not 结论["存在"]:
        return 结论
    try:
        原始 = json.loads(路径.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return 结论
    if not isinstance(原始, dict):
        return 结论
    归一 = 归一激活指针(原始)
    结论.update({
        "可读": True,
        "原始键": sorted(原始.keys()),
        "历史写法": 兼容路径键 in 原始,
        "归一键集": sorted(归一.keys()),
        "已统一": sorted(原始.keys()) == sorted(指针键表),
    })
    return 结论


__all__ = [
    "指针键表", "兼容路径键", "指针文件名",
    "归一激活指针", "读取激活指针", "写激活指针", "指针形态",
]
