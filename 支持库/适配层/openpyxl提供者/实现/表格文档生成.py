"""openpyxl 独立提供者生成实现：内容参数 → XLSX 字节 → 生成产物字典。

内容参数：{"工作表列表": [{"表名"|"name"|"标题", "列"|"columns": [...],
"行"|"rows": [...]}]}，兼容单元格字典（文本/标注/value/name）。稳定
错误码：参数不合法/提供者不可用/生成失败。
"""

from __future__ import annotations

import base64
import hashlib
import io
import time

import 支持库.适配层.openpyxl提供者.实现.表格文档 as _公共
from 公共契约.基础类型.结果类型 import 结果

媒体类型_xlsx = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _取表名(工作表: dict) -> str:
    名称 = 工作表.get("表名") or 工作表.get("name") or 工作表.get("标题") or "工作表"
    return str(名称)[:31] or "工作表"


def _取单元格文本(值) -> str:
    if isinstance(值, dict):
        for 键 in ("文本", "标注", "value", "name"):
            if 键 in 值 and 值[键] is not None:
                return str(值[键])
        return str(值)
    return "" if 值 is None else str(值)


def _标准化行(行数据, 列: list) -> list:
    if isinstance(行数据, dict):
        if 列:
            return [_取单元格文本(行数据.get(列单元格)) for 列单元格 in 列]
        return [_取单元格文本(值) for 值 in 行数据.values()]
    if isinstance(行数据, (list, tuple)):
        return [_取单元格文本(值) for 值 in 行数据]
    return [_取单元格文本(行数据)]


def _生成XLSX字节(工作表列表: list) -> bytes:
    """按 工作表列表 生成 XLSX 字节；无可写单元格时抛 ValueError。"""
    from openpyxl import Workbook
    工作簿 = Workbook()
    工作簿.remove(工作簿.active)
    写入格数 = 0
    for 工作表 in 工作表列表:
        if not isinstance(工作表, dict):
            continue
        列 = 工作表.get("列") or 工作表.get("columns") or []
        行 = 工作表.get("行") or 工作表.get("rows") or []
        列 = 列 if isinstance(列, list) else []
        行 = 行 if isinstance(行, list) else []
        表单 = 工作簿.create_sheet(title=_取表名(工作表))
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


def 生成表格文档(内容参数: dict) -> 结果:
    """按 工作表列表 生成 XLSX，返回生成产物字典（字节b64/媒体类型/摘要）。"""
    if not isinstance(内容参数, dict):
        return _公共._失败("参数不合法", "内容参数必须是字典")
    提供者 = _公共.加载提供者()
    if 提供者["openpyxl"] is None:
        return _公共._失败("提供者不可用", "openpyxl 不可用，无法生成表格文档", 可重试=True)
    工作表列表 = 内容参数.get("工作表列表") or []
    if not isinstance(工作表列表, list) or not 工作表列表:
        return _公共._失败("参数不合法", "工作表列表不能为空，至少需要一个工作表")
    开始时刻 = time.monotonic()
    try:
        字节 = _生成XLSX字节(工作表列表)
    except ValueError as 错误:
        return _公共._失败("参数不合法", str(错误))
    except Exception as 错误:
        return _公共._失败("生成失败", f"XLSX 生成异常: {错误}")
    if not 字节:
        return _公共._失败("生成失败", "XLSX 生成结果为空")
    return 结果.成功结果({
        "格式": "xlsx",
        "字节b64": base64.b64encode(字节).decode("ascii"),
        "媒体类型": 媒体类型_xlsx,
        "摘要": hashlib.sha256(字节).hexdigest(),
        "诊断": [f"XLSX 生成成功，耗时 {time.monotonic() - 开始时刻:.3f} 秒"],
        "提供者版本": dict(提供者["版本"]),
        "字节数": len(字节),
    })
