"""文件系统原子能力实现（不对外暴露，只经包级入口调用）。"""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any

from 公共契约.基础类型.结果类型 import 结果
from 公共契约.错误结构 import 错误结构


def 读取文件(文件路径: str, 编码: str = "utf-8") -> 结果:
    路径 = Path(文件路径)
    if not 路径.is_file():
        return 结果.失败("文件不存在", f"文件不存在: {文件路径}", 来源="文件系统")
    try:
        return 结果.成功结果(路径.read_text(encoding=编码))
    except OSError as 错误:
        return 结果.失败("文件读取失败", str(错误), 来源="文件系统")


def 写入文件(文件路径: str, 内容: str, 编码: str = "utf-8") -> 结果:
    路径 = Path(文件路径)
    try:
        路径.parent.mkdir(parents=True, exist_ok=True)
        路径.write_text(内容, encoding=编码)
        return 结果.成功结果()
    except OSError as 错误:
        return 结果.失败("文件不可写", str(错误), 来源="文件系统")


def 判断存在(文件路径: str) -> bool:
    return Path(文件路径).exists()


def 列出目录(目录路径: str) -> 结果:
    路径 = Path(目录路径)
    if not 路径.is_dir():
        return 结果.失败("目录不存在", f"目录不存在: {目录路径}", 来源="文件系统")
    try:
        return 结果.成功结果(sorted(条目.name for 条目 in 路径.iterdir()))
    except OSError as 错误:
        return 结果.失败("目录读取失败", str(错误), 来源="文件系统")


def 删除文件(文件路径: str) -> 结果:
    路径 = Path(文件路径)
    if not 路径.exists():
        return 结果.成功结果()
    try:
        if 路径.is_dir():
            路径.rmdir()
        else:
            路径.unlink()
        return 结果.成功结果()
    except OSError as 错误:
        return 结果.失败("文件删除失败", str(错误), 来源="文件系统")


def 复制文件(源路径: str, 目标路径: str) -> 结果:
    源 = Path(源路径)
    if not 源.is_file():
        return 结果.失败("文件不存在", f"源文件不存在: {源路径}", 来源="文件系统")
    try:
        目标 = Path(目标路径)
        目标.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(源, 目标)
        return 结果.成功结果()
    except OSError as 错误:
        return 结果.失败("文件复制失败", str(错误), 来源="文件系统")


def 移动文件(源路径: str, 目标路径: str) -> 结果:
    源 = Path(源路径)
    if not 源.exists():
        return 结果.失败("文件不存在", f"源文件不存在: {源路径}", 来源="文件系统")
    try:
        目标 = Path(目标路径)
        目标.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(源), str(目标))
        return 结果.成功结果()
    except OSError as 错误:
        return 结果.失败("文件移动失败", str(错误), 来源="文件系统")


def 获取大小(文件路径: str) -> 结果:
    路径 = Path(文件路径)
    if not 路径.is_file():
        return 结果.失败("文件不存在", f"文件不存在: {文件路径}", 来源="文件系统")
    try:
        return 结果.成功结果(路径.stat().st_size)
    except OSError as 错误:
        return 结果.失败("文件大小读取失败", str(错误), 来源="文件系统")


def 获取修改时间(文件路径: str) -> 结果:
    路径 = Path(文件路径)
    if not 路径.exists():
        return 结果.失败("文件不存在", f"文件不存在: {文件路径}", 来源="文件系统")
    try:
        return 结果.成功结果(路径.stat().st_mtime)
    except OSError as 错误:
        return 结果.失败("修改时间读取失败", str(错误), 来源="文件系统")


def 创建目录(目录路径: str, 递归: bool = True) -> 结果:
    """创建目录；递归创建父目录。已存在视为成功（幂等）。"""
    路径 = Path(目录路径)
    if 路径.is_dir():
        return 结果.成功结果()
    try:
        if 递归:
            路径.mkdir(parents=True, exist_ok=True)
        else:
            路径.mkdir(exist_ok=True)
        return 结果.成功结果()
    except OSError as 错误:
        return 结果.失败("目录创建失败", str(错误), 来源="文件系统")


def 读取二进制文件(受控根目录: str, 相对路径: str, 最大字节数: int = 0) -> 结果:
    """在受控根目录内按相对路径读取二进制文件（路径边界校验 + 大小上限）。

    相对路径不得越出受控根目录（防路径逃逸）；最大字节数>0 时超限拒绝
    （防一次性无界读入内存）。供文件资产主链路经项目适配层调用。
    """
    根目录 = Path(受控根目录).resolve()
    if not 根目录.is_dir():
        return 结果.失败("目录不存在", f"受控根目录不存在: {受控根目录}", 来源="文件系统")
    目标 = (根目录 / 相对路径).resolve()
    try:
        import os as _os
        if os.path.commonpath([str(根目录), str(目标)]) != str(根目录):
            return 结果.失败("路径越界", f"路径越出受控根目录: {相对路径}", 来源="文件系统")
    except ValueError:
        return 结果.失败("路径越界", f"路径越出受控根目录: {相对路径}", 来源="文件系统")
    if not 目标.is_file():
        return 结果.失败("文件不存在", f"文件不存在: {相对路径}", 来源="文件系统")
    try:
        文件大小 = 目标.stat().st_size
        if 最大字节数 and 文件大小 > 最大字节数:
            return 结果.失败("文件超限", f"文件 {文件大小} 字节超过上限 {最大字节数}", 来源="文件系统")
        return 结果.成功结果(目标.read_bytes())
    except OSError as 错误:
        return 结果.失败("文件读取失败", str(错误), 来源="文件系统")


def 读取文件头部字节(受控根目录: str, 相对路径: str, 字节数: int = 4096) -> 结果:
    """在受控根目录内按相对路径只读文件头部 N 字节（不加载全文件）。

    受控根 + 相对路径 双重路径边界校验（防路径逃逸）；只读头部字节数，
    大文件也不会整体载入内存。供文件头嗅探/预览等只读场景调用。
    """
    根目录 = Path(受控根目录).resolve()
    if not 根目录.is_dir():
        return 结果.失败("目录不存在", f"受控根目录不存在: {受控根目录}", 来源="文件系统")
    目标 = (根目录 / 相对路径).resolve()
    try:
        if os.path.commonpath([str(根目录), str(目标)]) != str(根目录):
            return 结果.失败("路径越界", f"路径越出受控根目录: {相对路径}", 来源="文件系统")
    except ValueError:
        return 结果.失败("路径越界", f"路径越出受控根目录: {相对路径}", 来源="文件系统")
    if not 目标.is_file():
        return 结果.失败("文件不存在", f"文件不存在: {相对路径}", 来源="文件系统")
    try:
        with 目标.open("rb") as 文件流:
            return 结果.成功结果(文件流.read(max(int(字节数), 0)))
    except OSError as 错误:
        return 结果.失败("文件读取失败", str(错误), 来源="文件系统")


_临时资源登记表: list[str] = []


def 登记临时资源(路径: str) -> 结果:
    """登记一个临时资源（文件或目录），由 清理全部临时资源 统一释放。"""
    if not isinstance(路径, str) or not 路径.strip():
        return 结果.失败("参数不合法", "路径必须为非空文本", 来源="文件系统")
    if 路径 not in _临时资源登记表:
        _临时资源登记表.append(路径)
    return 结果.成功结果(len(_临时资源登记表))


def 清理全部临时资源() -> 结果:
    """清理全部已登记临时资源（文件删除/目录递归删除，不存在视为幂等成功）。"""
    清理失败表 = []
    for 路径 in list(_临时资源登记表):
        try:
            目标 = Path(路径)
            if 目标.is_dir():
                shutil.rmtree(目标)
            else:
                目标.unlink(missing_ok=True)
        except OSError as 错误:
            清理失败表.append(f"{路径}: {错误}")
    _临时资源登记表.clear()
    if 清理失败表:
        return 结果.失败("清理失败", "；".join(清理失败表), 来源="文件系统")
    return 结果.成功结果()
