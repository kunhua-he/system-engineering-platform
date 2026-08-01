"""XLSX 原子生成：按工作表列表用 openpyxl 生成字节。

缺库抛 ImportError（上层转 提供者不可用）、参数非法抛 ValueError
（上层转 参数不合法）。
"""

from __future__ import annotations

import io


def 生成XLSX字节(参数: dict) -> bytes:
    """按 工作表列表 生成 XLSX 字节。"""
    from openpyxl import Workbook  # 缺库时 ImportError 冒泡

    工作表列表 = 参数.get("工作表列表") or []
    if not isinstance(工作表列表, list) or not 工作表列表:
        raise ValueError("工作表列表不能为空，至少需要一个工作表")

    工作簿 = Workbook()
    工作簿.remove(工作簿.active)
    写入格数 = 0
    for 工作表 in 工作表列表:
        if not isinstance(工作表, dict):
            continue
        表名 = _取表名(工作表)
        列 = _取列表(工作表.get("列") or 工作表.get("columns") or [])
        行 = _取列表(工作表.get("行") or 工作表.get("rows") or [])
        表单 = 工作簿.create_sheet(title=表名)
        if 列:
            表单.append([_取单元格文本(单元格) for 单元格 in 列])
            写入格数 += len(列)
        for 行数据 in 行:
            行值 = _标准化行(行数据, 列)
            if 行值:
                表单.append(行值)
                写入格数 += len(行值)

    if 写入格数 == 0:
        raise ValueError("工作表列表中没有可写单元格（列/行均为空）")

    缓冲 = io.BytesIO()
    工作簿.save(缓冲)
    return 缓冲.getvalue()


def _取表名(工作表: dict) -> str:
    名称 = (
        工作表.get("表名")
        or 工作表.get("name")
        or 工作表.get("标题")
        or "工作表"
    )
    return str(名称)[:31] or "工作表"


def _标准化行(行数据, 列: list) -> list:
    if isinstance(行数据, dict):
        if 列:
            return [_取单元格文本(行数据.get(列单元格)) for 列单元格 in 列]
        return [_取单元格文本(值) for 值 in 行数据.values()]
    if isinstance(行数据, (list, tuple)):
        return [_取单元格文本(值) for 值 in 行数据]
    return [_取单元格文本(行数据)]


def _取单元格文本(值) -> str:
    if isinstance(值, dict):
        for 键 in ("文本", "标注", "value", "name"):
            if 键 in 值 and 值[键] is not None:
                return str(值[键])
        return str(值)
    return "" if 值 is None else str(值)


def _取列表(值) -> list:
    return 值 if isinstance(值, list) else []
