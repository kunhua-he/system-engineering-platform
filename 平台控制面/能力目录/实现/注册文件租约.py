"""文件租约能力的注册装配：能力 id 表 + 契约条目只读（**参数声明不在这里**）。

参数声明的**唯一事实源**是 `能力契约/参数契约.json`，由 `__init__.py` 的 `注册能力`
把契约整条镜像成 `_参数契约表` 后按下标交给注册表；本文件只提供「读契约条目」给入口
取 `说明`/`版本` 这类非参数元数据。

历史（2026-09-18 清退）：本文件原先还导出 `注册参数(契约条目)`，在入口注册时按
名称/类型/必填 **重建**一份参数声明。那是同一件事的第二套实现（哲学 12.1），且重建
形态把 `默认值` 漏掉、AST 漂移检测也看不见（丢参缺陷的第三种变体）；入口改成整条
透传后它已无调用点，按「同一事两套实现即缺陷，旧实现直接删」清退。
"""
from __future__ import annotations

import json
from pathlib import Path

# 本面五条能力（顺序 = 注册顺序，与 能力定义.json 的能力列表同序）。
能力id表 = (
    "平台控制面.能力目录.申请文件租约",
    "平台控制面.能力目录.续租文件租约",
    "平台控制面.能力目录.释放文件租约",
    "平台控制面.能力目录.回收过期文件租约",
    "平台控制面.能力目录.查询文件租约",
)

契约相对路径 = Path("能力契约") / "参数契约.json"


def 读契约表(包目录: Path) -> dict[str, dict]:
    """读本包聚合参数契约，返回 `{能力id: 契约条目}`；读不成即空表（由门禁如实报缺）。"""
    路径 = 包目录 / 契约相对路径
    try:
        数据 = json.loads(路径.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return {}
    if not isinstance(数据, dict):
        return {}
    表: dict[str, dict] = {}
    for 条目 in 数据.get("能力契约") or []:
        if isinstance(条目, dict) and 条目.get("能力id"):
            表[str(条目["能力id"])] = 条目
    return 表



