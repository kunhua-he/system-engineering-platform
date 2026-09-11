"""办公文档支持库 · 轻量文本解析原子能力（不对外暴露，只经包级中文入口调用）。

把 V3 自持的 Markdown 分块与纯文本分块下沉为底座原子能力：
纯标准库、无状态、无副作用，一律返回统一结果，不抛异常。

只产出「中间块」——类型 / 文本 / 行起 / 行止 / 属性。
最终 source_ref（file_id、格式化、页码）与资源引用计数留在调用方组装，
底座不感知文件与资源清单。
"""

from __future__ import annotations

import re

from 公共契约.基础类型.结果类型 import 结果

# 完整语法集识别规则（逐条对齐 V3 Markdown解析器路由原有语义）
_标题 = re.compile(r"^(#{1,6})\s+(.+)$")
_代码围栏 = re.compile(r"^`{3,}\s*(\w*)$")
_表格行 = re.compile(r"^\|.+\|$")
_表格分隔 = re.compile(r"^\|\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|$")
_无序列表 = re.compile(r"^(\s*)[-*+]\s+")
_有序列表 = re.compile(r"^(\s*)\d+[.)]\s+")
_引用 = re.compile(r"^>\s?(.*)$")
_分隔线 = re.compile(r"^[-*_]{3,}\s*$")
_图像 = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")

_代码围栏前缀 = "```"
_空文件占位 = "(empty markdown file)"
_有效语法集 = ("完整", "简化")


def _失败(错误码: str, 消息: str) -> 结果:
    return 结果.失败(错误码, 消息, 来源="轻量文本解析")


def _中间块(类型: str, 文本: str, 行起: int | None, 行止: int | None,
            属性: dict) -> dict:
    return {"类型": 类型, "文本": 文本, "行起": 行起, "行止": 行止, "属性": 属性}


def _切行(文本: str) -> list[str]:
    """先归一化换行，再按行切分（行号自 1 起）。"""
    归一化 = 文本.replace("\r\n", "\n").replace("\r", "\n")
    return 归一化.splitlines(keepends=False)


# ---------- 完整语法集：8 类块 ----------

def _解析完整(行序列: list[str]) -> list[dict]:
    块列表: list[dict] = []
    在代码块 = False
    代码起始: int | None = None
    代码语言 = ""
    代码行: list[str] = []
    段落行: list[str] = []
    段落起始: int | None = None
    在表格 = False
    表格行: list[str] = []
    表格起始: int | None = None
    在列表 = False
    列表行: list[str] = []
    列表起始: int | None = None

    def 刷新段落(结束行: int | None = None) -> None:
        nonlocal 段落行, 段落起始
        if 段落行:
            文本 = "\n".join(段落行).strip()
            if 文本:
                块列表.append(_中间块(
                    "paragraph", 文本, 段落起始, 结束行, {"章节": "paragraph"}))
            段落行 = []
            段落起始 = None

    def 刷新代码(结束行: int | None = None) -> None:
        nonlocal 代码行, 代码语言, 代码起始
        if 代码行:
            属性 = {"章节": "code"}
            if 代码语言:
                属性["language"] = 代码语言
            块列表.append(_中间块(
                "code", "\n".join(代码行), 代码起始, 结束行, 属性))
        代码行 = []
        代码语言 = ""
        代码起始 = None

    def 刷新表格(结束行: int | None = None) -> None:
        nonlocal 表格行, 表格起始
        if 表格行:
            块列表.append(_中间块(
                "表格", "\n".join(表格行), 表格起始, 结束行, {"章节": "表格"}))
            表格行 = []
            表格起始 = None

    def 刷新列表(结束行: int | None = None) -> None:
        nonlocal 列表行, 列表起始
        if 列表行:
            块列表.append(_中间块(
                "列表项", "\n".join(列表行), 列表起始, 结束行, {"章节": "列表项"}))
            列表行 = []
            列表起始 = None

    for 行号, 行 in enumerate(行序列, start=1):
        围栏匹配 = _代码围栏.match(行)
        if 围栏匹配:
            if 在代码块:
                刷新代码(行号)
                在代码块 = False
            else:
                刷新段落(行号 - 1)
                刷新表格(行号 - 1)
                刷新列表(行号 - 1)
                代码语言 = 围栏匹配.group(1) or ""
                在代码块 = True
                代码起始 = 行号
            continue

        if 在代码块:
            代码行.append(行)
            continue

        if _表格分隔.match(行):
            continue

        if _表格行.match(行):
            刷新段落(行号 - 1)
            刷新列表(行号 - 1)
            在表格 = True
            if 表格起始 is None:
                表格起始 = 行号
            表格行.append(行)
            continue
        if 在表格:
            刷新表格(行号 - 1)
            在表格 = False

        标题匹配 = _标题.match(行)
        if 标题匹配:
            刷新段落(行号 - 1)
            刷新列表(行号 - 1)
            层级 = len(标题匹配.group(1))
            标题文本 = 标题匹配.group(2).strip()
            块类型 = "heading" if 层级 <= 2 else "paragraph"
            块列表.append(_中间块(
                块类型, 标题文本, 行号, 行号,
                {"章节": "heading", "level": 层级}))
            continue

        引用匹配 = _引用.match(行)
        if 引用匹配:
            刷新段落(行号 - 1)
            刷新列表(行号 - 1)
            引用文本 = 引用匹配.group(1).strip()
            if 引用文本:
                块列表.append(_中间块(
                    "quote", 引用文本, 行号, 行号, {"章节": "quote"}))
            continue

        if _分隔线.match(行):
            刷新段落(行号 - 1)
            刷新列表(行号 - 1)
            块列表.append(_中间块(
                "divider", "", 行号, 行号, {"章节": "divider"}))
            continue

        图像匹配 = _图像.fullmatch(行.strip())
        if 图像匹配:
            刷新段落(行号 - 1)
            刷新表格(行号 - 1)
            刷新列表(行号 - 1)
            块列表.append(_中间块(
                "图像", 图像匹配.group(1) or "", 行号, 行号,
                {"章节": "图像", "url": 图像匹配.group(2) or ""}))
            continue

        if _无序列表.match(行) or _有序列表.match(行):
            刷新段落(行号 - 1)
            在列表 = True
            if 列表起始 is None:
                列表起始 = 行号
            列表行.append(行)
            continue
        if 在列表:
            if 行.strip() == "":
                刷新列表(行号 - 1)
                在列表 = False
                continue
            if _无序列表.match(行) or _有序列表.match(行):
                列表行.append(行)
                continue
            列表行.append(行)
            continue

        if 行.strip() == "":
            刷新段落(行号 - 1)
            continue

        if 段落起始 is None:
            段落起始 = 行号
        段落行.append(行)

    刷新段落(len(行序列))
    刷新代码(len(行序列))
    刷新表格(len(行序列))
    刷新列表(len(行序列))
    if not 块列表:
        块列表.append(_中间块(
            "paragraph", _空文件占位, None, None,
            {"章节": "body", "empty": True}))
    return 块列表


# ---------- 简化语法集：3 类块（标题 / 段落 / 代码） ----------

def _解析简化(行序列: list[str]) -> list[dict]:
    块列表: list[dict] = []
    段落行: list[str] = []
    段落起始: int | None = None
    代码行: list[str] = []
    代码起始: int | None = None
    在代码块 = False

    def 追加段落(结束行: int) -> None:
        nonlocal 段落行, 段落起始
        if 段落行:
            文本 = "\n".join(段落行).strip()
            if 文本:
                块列表.append(_中间块(
                    "paragraph", 文本, 段落起始, 结束行, {"章节": "body"}))
            段落行 = []
            段落起始 = None

    for 行号, 行 in enumerate(行序列, start=1):
        if 行.startswith(_代码围栏前缀):
            if 在代码块:
                if 代码行:
                    块列表.append(_中间块(
                        "code", "\n".join(代码行), 代码起始, 行号,
                        {"章节": "code"}))
                在代码块 = False
                代码行 = []
                代码起始 = None
            else:
                追加段落(行号 - 1)
                在代码块 = True
                代码起始 = 行号
            continue
        if 在代码块:
            代码行.append(行)
            continue
        if 行.startswith("#"):
            追加段落(行号 - 1)
            标题文本 = 行.lstrip("#").strip()
            if 标题文本:
                块列表.append(_中间块(
                    "heading", 标题文本, 行号, 行号, {"章节": "heading"}))
            continue
        if 行.strip() == "":
            追加段落(行号 - 1)
            continue
        if 段落起始 is None:
            段落起始 = 行号
        段落行.append(行)

    追加段落(len(行序列))
    if 代码行:
        块列表.append(_中间块(
            "code", "\n".join(代码行), 代码起始, len(行序列), {"章节": "code"}))
    return 块列表


# ---------- 纯文本：空行切段落 ----------

def _解析纯文本(行序列: list[str]) -> list[dict]:
    块列表: list[dict] = []
    段落行: list[str] = []
    段落起始: int | None = None

    def 追加段落(结束行: int) -> None:
        nonlocal 段落行, 段落起始
        if 段落行:
            文本 = "\n".join(段落行).strip()
            if 文本:
                块列表.append(_中间块(
                    "paragraph", 文本, 段落起始, 结束行, {"章节": "body"}))
            段落行 = []
            段落起始 = None

    for 行号, 行 in enumerate(行序列, start=1):
        if 行.strip() == "":
            追加段落(行号 - 1)
            continue
        if 段落起始 is None:
            段落起始 = 行号
        段落行.append(行)

    追加段落(len(行序列))
    return 块列表


# ---------- 对外原子能力 ----------

def 解析Markdown块(文本: str = None, 语法集: str = None) -> 结果:
    """把 Markdown 文本切成中间块列表。

    语法集「完整」：标题/段落/代码/表格/列表项/引用/分隔线/图像 共 8 类；
    语法集「简化」：仅标题/段落/代码 3 类。
    两者共用行号语义（1 起）与空文件行为，但块类型判定规则不同。
    """
    if not isinstance(文本, str):
        return _失败("参数不合法", "文本必须是文本")
    规整语法集 = 语法集 if isinstance(语法集, str) and 语法集 else "完整"
    if 规整语法集 not in _有效语法集:
        return _失败("参数不合法", f"语法集只支持 完整/简化，收到：{规整语法集}")
    行序列 = _切行(文本)
    块列表 = _解析完整(行序列) if 规整语法集 == "完整" else _解析简化(行序列)
    return 结果.成功结果({"块列表": 块列表})


def 解析纯文本块(文本: str = None) -> 结果:
    """把纯文本按空行切成段落中间块列表。"""
    if not isinstance(文本, str):
        return _失败("参数不合法", "文本必须是文本")
    行序列 = _切行(文本)
    return 结果.成功结果({"块列表": _解析纯文本(行序列)})
