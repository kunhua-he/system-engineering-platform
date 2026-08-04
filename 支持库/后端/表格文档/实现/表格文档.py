"""表格文档原子能力实现：经受管提供者能力解析 XLS/XLSX。

- XLSX 原生解析经受管提供者能力 `表格文档.解析表格文档`
  （openpyxl提供者）执行，本模块（主进程）绝不 import openpyxl；
- 旧格式 XLS 先经受管提供者能力 `LibreOffice转换.转换办公文件`
  转 XLSX 再解析；
- OOXML 不可信 ZIP 安全校验（成员数/单项大小/总解压体积/压缩比/
  路径逃逸/外部关系）保留在本模块（纯标准库 zipfile）；
- 能力经 公共契约.能力契约.调用器.获取能力调用器 注入的唯一能力
  调用服务调用；调用器未装配时如实返回 提供者不可用。

公式/值契约：默认 data_only=True 取缓存值；缓存缺失时回退为空值
（由受管提供者承担）。安全覆盖：损坏文件 → 文件损坏；超限 → 超出限制；
缺提供者 → 提供者不可用（不跳过）。
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from 公共契约.基础类型.文档结构 import (
    保真_高, 保真_中, 块_工作表, 文档块, 来源位置, 通用文档,
)
from 公共契约.基础类型.结果类型 import 结果

来源 = "表格文档"
解析表格文档能力id = "表格文档.解析表格文档"
转换办公能力id = "LibreOffice转换.转换办公文件"
默认最大字节数 = 200 * 1024 * 1024
默认超时秒 = 60.0
默认最大工作表数 = 50
默认最大行数 = 200_000


def _调用(能力id: str, 请求参数: dict) -> 结果:
    """经唯一能力调用服务调用受管提供者能力；调用器未装配时如实失败。"""
    from 公共契约.能力契约.调用器 import 获取能力调用器

    try:
        return 获取能力调用器().调用能力(能力id, 请求参数, 调用方=来源)
    except RuntimeError as 错误:
        return 结果.失败("提供者不可用", str(错误), 来源=来源, 可重试=True)


def _失败(错误码: str, 消息: str, *, 可重试: bool = False, 详情: dict[str, Any] | None = None) -> 结果:
    return 结果.失败(错误码, 消息, 来源=来源, 可重试=可重试, 详情=详情 or {})


def _成功(值: Any) -> 结果:
    return 结果.成功结果(值)


def _文件摘要(文件路径: Path) -> str:
    import hashlib
    摘要器 = hashlib.sha256()
    with open(文件路径, "rb") as 流:
        while 数据块 := 流.read(1024 * 1024):
            摘要器.update(数据块)
    return 摘要器.hexdigest()


def _转通用文档(字典: dict[str, Any], 格式: str, 原始路径: Path,
               解析方式: str, 保真: str) -> 通用文档:
    """把提供者返回的通用文档字典重建为平台通用文档 dataclass。"""
    块列表: list[文档块] = []
    for 块 in 字典.get("块列表", []):
        if not isinstance(块, dict):
            continue
        来源位置值 = 块.get("来源位置") if isinstance(块.get("来源位置"), dict) else {}
        块列表.append(文档块(
            类型=块_工作表,
            文本=块.get("文本", ""),
            来源位置=来源位置(工作表=来源位置值.get("工作表", "")),
            表格数据=块.get("表格数据"),
            附加=块.get("附加", {}),
        ))
    附加 = 字典.get("附加") if isinstance(字典.get("附加"), dict) else {}
    return 通用文档(
        文档类型="表格",
        格式=格式,
        标题=原始路径.name,
        块列表=块列表,
        资源列表=字典.get("资源列表", []),
        保真级别=保真,
        解析方式=解析方式,
        警告=字典.get("警告", []) + (["converted_from_xls"] if 解析方式 == "LibreOffice 转换" else []),
        诊断=字典.get("诊断", []),
        耗时秒=字典.get("耗时秒", 0.0),
        提供者版本=字典.get("提供者版本") if isinstance(字典.get("提供者版本"), dict) else {},
        原始文件摘要=_文件摘要(原始路径),
        附加=附加,
    )


def 解析表格文档(
    文件路径: str,
    格式: str = "xlsx",
    最大工作表数: int = 默认最大工作表数,
    最大行数: int = 默认最大行数,
    最大字节数: int = 默认最大字节数,
    超时秒: float = 默认超时秒,
) -> 结果:
    """解析 XLS/XLSX 为平台通用文档。xlsx 原生，xls 经 LibreOffice 转换。"""
    路径 = Path(文件路径)
    if not 路径.is_file():
        return _失败("文件不存在", f"文件不存在: {路径}")
    格式 = (格式 or "").lower().lstrip(".")
    if 格式 not in {"xls", "xlsx"}:
        return _失败("参数不合法", f"不支持的格式 '{格式}'")
    if 路径.stat().st_size > 最大字节数:
        return _失败("超出限制", f"文件大小 {路径.stat().st_size} 超过上限 {最大字节数}")

    解析路径 = 路径
    解析方式 = "原生"
    保真 = 保真_高
    临时目录: Path | None = None
    try:
        if 格式 == "xls":
            临时目录 = Path(tempfile.mkdtemp(prefix="平台表格文档转换_"))
            转换结果 = _转换xls为xlsx(路径, 临时目录, 超时秒)
            if not 转换结果.成功:
                return 转换结果
            解析路径 = Path(转换结果.值)
            解析方式 = "LibreOffice 转换"
            保真 = 保真_中

        调用结果 = _调用(解析表格文档能力id, {
            "文件路径": str(解析路径),
            "数据模式": True,
            "最大工作表数": 最大工作表数,
            "最大行数": 最大行数,
            "最大字节数": 最大字节数,
        })
        if not 调用结果.成功:
            return 调用结果
        字典 = 调用结果.值
        if not isinstance(字典, dict) or "错误码" in 字典:
            错误码 = str(字典.get("错误码") or "文件损坏") if isinstance(字典, dict) else "文件损坏"
            消息 = str(字典.get("错误说明") or "XLSX 解析失败") if isinstance(字典, dict) else "XLSX 解析失败"
            return _失败(错误码, 消息, 可重试=错误码 in ("提供者不可用", "超时"))
        文档 = _转通用文档(字典, 格式, 路径, 解析方式, 保真)
        return _成功(文档)
    finally:
        if 临时目录 is not None:
            import shutil
            shutil.rmtree(临时目录, ignore_errors=True)


def _转换xls为xlsx(源路径: Path, 临时目录: Path, 超时秒: float) -> 结果:
    """经受管提供者能力把旧格式 XLS 转为 XLSX，返回目标文件路径。"""
    转换结果 = _调用(转换办公能力id, {
        "输入路径": str(源路径),
        "目标格式": "xlsx",
        "输出目录": str(临时目录),
        "超时秒": 超时秒,
    })
    if not 转换结果.成功:
        return 转换结果
    值 = 转换结果.值
    if not isinstance(值, dict) or not 值.get("输出路径"):
        return _失败("转换失败", "LibreOffice 未产出转换文件")
    目标 = Path(值["输出路径"])
    if not 目标.is_file():
        return _失败("转换失败", f"LibreOffice 未产出文件: {目标.name}")
    return _成功(str(目标))
