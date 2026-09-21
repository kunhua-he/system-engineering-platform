"""目录树原子能力实现（不对外暴露，只经包级中文入口调用）。

职责：一次调用返回多层目录树（深度 / 名称过滤 / 条数预算）。
纯标准库、纯只读：不写盘、不建目录、不改任何文件。

口径（与 能力定义.json 逐字对齐）：
- 深度语义：`最大深度=1` 只列树根的直接子项；`0` = 不限深度。
- 统计口径：节点数 = 目录数 + 文件数，**不含树根自身**（树根只出现在 树文本 首行）。
- 名称模式：只作用于文件条目（glob），目录骨架始终保留（同 tree -P 的口径）；空串 = 不过滤。
- 条数上限：按深度优先前序收录，超限**如实截断并回报**（已截断/截断处），不静默。
- 排序稳定：同层按名称升序（目录与文件混排），保证同输入同输出。
"""

from __future__ import annotations

import fnmatch
import os
import pathlib

from 公共契约.基础类型.逻辑类型 import 真, 假
from 公共契约.基础类型.结果类型 import 结果

# 平台默认排除目录：调用方传 排除目录 非空时以调用方清单为准（整表替换，不是叠加）。
默认排除目录 = (".git", "__pycache__", "工程缓存", "node_modules", ".venv", "dist", "build")
默认最大深度 = 3
默认条数上限 = 500


def _列直接条目(目录: pathlib.Path, 排除集: frozenset) -> list:
    """列出目录下的直接条目（已排除 排除集 中的目录），同层按名称升序。

    软链接一律按文件处理（`is_dir(follow_symlinks=False)`）：既避免环，
    也保证同一输入两次调用结果逐字一致。目录读不动（权限等）时返回空表 ——
    该目录节点仍会出现在树里，只是不带子项，不编造也不报假成功。
    """
    条目表 = []
    try:
        with os.scandir(目录) as 迭代器:
            for 条目 in 迭代器:
                是目录 = 条目.is_dir(follow_symlinks=False)
                if 是目录 and 条目.name in 排除集:
                    continue
                条目表.append({"名称": 条目.name, "是目录": 是目录, "路径": 条目.path})
    except OSError:
        return []
    条目表.sort(key=lambda 项: 项["名称"])
    return 条目表


def _取大小(路径: str) -> int:
    """取文件字节数；取不到（软链失效/权限）时回 0，不把整次调用拖挂。"""
    try:
        return os.path.getsize(路径)
    except OSError:
        return 0


def 目录树(目录路径: str = None, 最大深度: int = 默认最大深度, 包含文件: bool = 真,
           名称模式: str = "", 排除目录: list = None, 条数上限: int = 默认条数上限,
           含大小: bool = 假) -> 结果:
    """一次调用返回整棵树。返回 {树文本, 节点数, 目录数, 文件数, 已截断, 截断处}。

    为什么要有它（2026-09-21）：`列出目录` 只看一层，多层的现状要靠 N 次调用
    一层一层拼，调用方每拼一层就多付一轮往返；`搜索文件` 给的是绝对路径平铺列表，
    看不出层级。缺「一次拿到整棵树的形状 + 深度可控 + 条数有预算」这一条，调用方
    就只能退回 `find` / `tree` 拼 shell，那正是「终端能做的、能力面里没有」的缺口。

    只读：不写盘、不建目录、不改任何文件；条数超限如实截断并回报（不静默）。
    """
    if not isinstance(目录路径, str) or not 目录路径.strip():
        return 结果.失败("参数不合法", "目录路径必须是非空字符串", 来源="文件系统")
    if not isinstance(最大深度, int) or isinstance(最大深度, bool) or 最大深度 < 0:
        return 结果.失败("参数不合法", "最大深度 必须是 >= 0 的整数（0 = 不限深度）", 来源="文件系统")
    if not isinstance(条数上限, int) or isinstance(条数上限, bool) or 条数上限 < 1:
        return 结果.失败("参数不合法", "条数上限 必须是 >= 1 的整数", 来源="文件系统")
    if not isinstance(包含文件, bool) or not isinstance(含大小, bool):
        return 结果.失败("参数不合法", "包含文件/含大小 必须是逻辑型", 来源="文件系统")
    if 排除目录 is not None and not isinstance(排除目录, list):
        return 结果.失败("参数不合法", "排除目录 必须是字符串列表", 来源="文件系统")
    if not isinstance(名称模式, str):
        return 结果.失败("参数不合法", "名称模式 必须是文本型（空串 = 不过滤）", 来源="文件系统")
    根 = pathlib.Path(目录路径).expanduser()
    if not 根.is_dir():
        return 结果.失败("参数不合法", f"目录不存在或不是目录: {目录路径}", 来源="文件系统")

    排除集 = frozenset(排除目录) if 排除目录 else frozenset(默认排除目录)
    计数 = {"节点数": 0, "目录数": 0, "文件数": 0}
    截断 = {"已截断": False, "截断处": ""}
    根名 = 根.name or str(根)
    行表 = [根名 if 根名.endswith("/") else 根名 + "/"]

    def 遍历(目录: pathlib.Path, 前缀: str, 相对前缀: str, 层级: int) -> None:
        """深度优先前序收录一层（含其子层）。层级 1 = 树根的直接子项。"""
        可见 = []
        for 条目 in _列直接条目(目录, 排除集):
            if not 条目["是目录"]:
                if not 包含文件:
                    continue
                if 名称模式 and not fnmatch.fnmatch(条目["名称"], 名称模式):
                    continue
            可见.append(条目)
        for 序号, 条目 in enumerate(可见):
            末位 = 序号 == len(可见) - 1
            相对路径 = f"{相对前缀}/{条目['名称']}" if 相对前缀 else 条目["名称"]
            if 计数["节点数"] >= 条数上限:
                截断["已截断"] = True
                截断["截断处"] = 相对路径
                return
            计数["节点数"] += 1
            连接符 = "└── " if 末位 else "├── "
            子前缀 = 前缀 + ("    " if 末位 else "│   ")
            if 条目["是目录"]:
                计数["目录数"] += 1
                行表.append(f"{前缀}{连接符}{条目['名称']}/")
                if 最大深度 == 0 or 层级 < 最大深度:
                    遍历(pathlib.Path(条目["路径"]), 子前缀, 相对路径, 层级 + 1)
            else:
                计数["文件数"] += 1
                后缀 = f" ({_取大小(条目['路径'])} 字节)" if 含大小 else ""
                行表.append(f"{前缀}{连接符}{条目['名称']}{后缀}")
            if 截断["已截断"]:
                return

    遍历(根, "", "", 1)
    return 结果.成功结果({
        "树文本": "\n".join(行表),
        "节点数": 计数["节点数"],
        "目录数": 计数["目录数"],
        "文件数": 计数["文件数"],
        "已截断": 截断["已截断"],
        "截断处": 截断["截断处"],
    })
