"""文件租约能力的注册装配：注册参数逐条读 `能力契约/参数契约.json`（唯一事实源）。

为什么不在这里再写一份参数表：契约驱动流程里 `能力契约/参数契约.json` 是本包参数的
**唯一事实源**；`__init__.py` 的 `注册能力` 只负责把它读成注册结构。手写第二份类型
（哪怕当下"看起来一样"）就是第二套口径的起点——契约改了、注册没改，网关校验与
能力声明立刻分叉（第 5 条 1 项：契约唯一）。
"""
from __future__ import annotations

import json
from pathlib import Path
from 公共契约.基础类型.逻辑类型 import 真, 假

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


def 注册参数(契约条目: dict) -> list[dict]:
    """把契约条目的 `参数` 装配成注册结构（只取 名称/类型/必填，不新增第二份类型）。"""
    参数表: list[dict] = []
    for 参数 in 契约条目.get("参数") or []:
        if not isinstance(参数, dict) or not 参数.get("名称"):
            continue
        参数表.append({"名称": 参数["名称"], "类型": 参数.get("类型"),
                     "必填": 参数.get("必填") is 真})
    return 参数表
