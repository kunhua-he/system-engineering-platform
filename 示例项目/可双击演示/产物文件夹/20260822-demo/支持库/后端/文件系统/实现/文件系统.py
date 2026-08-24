"""文件系统原子能力实现（不对外暴露，只经包级中文入口调用）。

全部公开能力返回统一结果（成功/值/错误/错误码）；参数缺失或类型非法
返回 参数不合法，文件系统异常转换为稳定错误码，不吞异常、不以成功形状
伪装失败。文件读取一律显式关闭句柄（with/close 闭合）。
判断存在 为平台既有契约：直接返回布尔（统一验证器直接消费），
非法参数按不存在处理。
"""

from __future__ import annotations

import os
import shutil
import threading
from pathlib import Path
from typing import Any

from 公共契约.基础类型.结果类型 import 结果
from 公共契约.错误结构 import 错误结构


def 读取文件(文件路径: str = None, 编码: str = "utf-8") -> 结果:
    """按文本方式读取文件内容。"""
    if 文件路径 is None or not isinstance(文件路径, str) or not 文件路径.strip():
        return 结果.失败("参数不合法", "文件路径必须为非空文本", 来源="文件系统")
    if not isinstance(编码, str):
        return 结果.失败("参数不合法", "编码必须是文本", 来源="文件系统")
    路径 = Path(文件路径)
    if not 路径.is_file():
        return 结果.失败("文件不存在", f"文件不存在: {文件路径}", 来源="文件系统")
    try:
        return 结果.成功结果(路径.read_text(encoding=编码))
    except LookupError as 错误:
        return 结果.失败("参数不合法", f"未知编码: {错误}", 来源="文件系统")
    except OSError as 错误:
        return 结果.失败("文件读取失败", str(错误), 来源="文件系统")


def 写入文件(文件路径: str = None, 内容: str = None, 编码: str = "utf-8") -> 结果:
    """按文本方式写入文件（自动创建父目录）。"""
    if 文件路径 is None or not isinstance(文件路径, str) or not 文件路径.strip():
        return 结果.失败("参数不合法", "文件路径必须为非空文本", 来源="文件系统")
    if 内容 is None or not isinstance(内容, str):
        return 结果.失败("参数不合法", "内容必须为文本", 来源="文件系统")
    if not isinstance(编码, str):
        return 结果.失败("参数不合法", "编码必须是文本", 来源="文件系统")
    路径 = Path(文件路径)
    try:
        路径.parent.mkdir(parents=True, exist_ok=True)
        路径.write_text(内容, encoding=编码)
        return 结果.成功结果(True)
    except LookupError as 错误:
        return 结果.失败("参数不合法", f"未知编码: {错误}", 来源="文件系统")
    except OSError as 错误:
        return 结果.失败("文件不可写", str(错误), 来源="文件系统")


def 判断存在(文件路径: str = None) -> bool:
    """判断路径是否存在（平台既有契约：直接返回布尔；非法参数视为不存在）。"""
    if not isinstance(文件路径, str) or not 文件路径.strip():
        return False
    return Path(文件路径).exists()


def 列出目录(目录路径: str = None) -> 结果:
    """列出目录下条目名称（排序稳定）。"""
    if 目录路径 is None or not isinstance(目录路径, str) or not 目录路径.strip():
        return 结果.失败("参数不合法", "目录路径必须为非空文本", 来源="文件系统")
    路径 = Path(目录路径)
    if not 路径.is_dir():
        return 结果.失败("目录不存在", f"目录不存在: {目录路径}", 来源="文件系统")
    try:
        return 结果.成功结果(sorted(条目.name for 条目 in 路径.iterdir()))
    except OSError as 错误:
        return 结果.失败("目录读取失败", str(错误), 来源="文件系统")


def 删除文件(文件路径: str = None) -> 结果:
    """删除文件或空目录（不存在视为幂等成功）。"""
    if 文件路径 is None or not isinstance(文件路径, str) or not 文件路径.strip():
        return 结果.失败("参数不合法", "文件路径必须为非空文本", 来源="文件系统")
    路径 = Path(文件路径)
    if not 路径.exists():
        return 结果.成功结果(True)
    try:
        if 路径.is_dir():
            路径.rmdir()
        else:
            路径.unlink()
        return 结果.成功结果(True)
    except OSError as 错误:
        return 结果.失败("文件删除失败", str(错误), 来源="文件系统")


def 复制文件(源路径: str = None, 目标路径: str = None) -> 结果:
    """复制文件到目标路径（自动创建父目录）。"""
    if 源路径 is None or not isinstance(源路径, str) or not 源路径.strip():
        return 结果.失败("参数不合法", "源路径必须为非空文本", 来源="文件系统")
    if 目标路径 is None or not isinstance(目标路径, str) or not 目标路径.strip():
        return 结果.失败("参数不合法", "目标路径必须为非空文本", 来源="文件系统")
    源 = Path(源路径)
    if not 源.is_file():
        return 结果.失败("文件不存在", f"源文件不存在: {源路径}", 来源="文件系统")
    try:
        目标 = Path(目标路径)
        目标.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(源, 目标)
        return 结果.成功结果(True)
    except OSError as 错误:
        return 结果.失败("文件复制失败", str(错误), 来源="文件系统")


def 移动文件(源路径: str = None, 目标路径: str = None) -> 结果:
    """移动文件或目录到目标路径（自动创建父目录）。"""
    if 源路径 is None or not isinstance(源路径, str) or not 源路径.strip():
        return 结果.失败("参数不合法", "源路径必须为非空文本", 来源="文件系统")
    if 目标路径 is None or not isinstance(目标路径, str) or not 目标路径.strip():
        return 结果.失败("参数不合法", "目标路径必须为非空文本", 来源="文件系统")
    源 = Path(源路径)
    if not 源.exists():
        return 结果.失败("文件不存在", f"源文件不存在: {源路径}", 来源="文件系统")
    try:
        目标 = Path(目标路径)
        目标.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(源), str(目标))
        return 结果.成功结果(True)
    except OSError as 错误:
        return 结果.失败("文件移动失败", str(错误), 来源="文件系统")


def 获取大小(文件路径: str = None) -> 结果:
    """获取文件大小（字节）。"""
    if 文件路径 is None or not isinstance(文件路径, str) or not 文件路径.strip():
        return 结果.失败("参数不合法", "文件路径必须为非空文本", 来源="文件系统")
    路径 = Path(文件路径)
    if not 路径.is_file():
        return 结果.失败("文件不存在", f"文件不存在: {文件路径}", 来源="文件系统")
    try:
        return 结果.成功结果(路径.stat().st_size)
    except OSError as 错误:
        return 结果.失败("文件大小读取失败", str(错误), 来源="文件系统")


def 获取修改时间(文件路径: str = None) -> 结果:
    """获取文件修改时间戳（秒）。"""
    if 文件路径 is None or not isinstance(文件路径, str) or not 文件路径.strip():
        return 结果.失败("参数不合法", "文件路径必须为非空文本", 来源="文件系统")
    路径 = Path(文件路径)
    if not 路径.exists():
        return 结果.失败("文件不存在", f"文件不存在: {文件路径}", 来源="文件系统")
    try:
        return 结果.成功结果(路径.stat().st_mtime)
    except OSError as 错误:
        return 结果.失败("修改时间读取失败", str(错误), 来源="文件系统")


def 创建目录(目录路径: str = None, 递归: bool = True) -> 结果:
    """创建目录（递归创建父目录；已存在视为幂等成功）。"""
    if 目录路径 is None or not isinstance(目录路径, str) or not 目录路径.strip():
        return 结果.失败("参数不合法", "目录路径必须为非空文本", 来源="文件系统")
    路径 = Path(目录路径)
    if 路径.is_dir():
        return 结果.成功结果(True)
    try:
        if 递归:
            路径.mkdir(parents=True, exist_ok=True)
        else:
            路径.mkdir(exist_ok=True)
        return 结果.成功结果(True)
    except OSError as 错误:
        return 结果.失败("目录创建失败", str(错误), 来源="文件系统")


def 读取二进制文件(受控根目录: str = None, 相对路径: str = None,
                    最大字节数: int = 0) -> 结果:
    """在受控根目录内按相对路径读取二进制文件（路径边界校验 + 大小上限）。

    相对路径不得越出受控根目录（防路径逃逸）；最大字节数>0 时超限拒绝
    （防一次性无界读入内存）。供文件资产主链路经项目适配层调用。
    """
    if 受控根目录 is None or not isinstance(受控根目录, str) or not 受控根目录.strip():
        return 结果.失败("参数不合法", "受控根目录必须为非空文本", 来源="文件系统")
    if 相对路径 is None or not isinstance(相对路径, str):
        return 结果.失败("参数不合法", "相对路径必须为文本", 来源="文件系统")
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
        文件大小 = 目标.stat().st_size
        if 最大字节数 and 文件大小 > 最大字节数:
            return 结果.失败("文件超限", f"文件 {文件大小} 字节超过上限 {最大字节数}", 来源="文件系统")
        return 结果.成功结果(目标.read_bytes())
    except OSError as 错误:
        return 结果.失败("文件读取失败", str(错误), 来源="文件系统")


def 读取文件头部字节(受控根目录: str = None, 相对路径: str = None,
                     字节数: int = 4096) -> 结果:
    """在受控根目录内按相对路径只读文件头部 N 字节（不加载全文件）。

    受控根 + 相对路径 双重路径边界校验（防路径逃逸）；只读头部字节数，
    大文件也不会整体载入内存。供文件头嗅探/预览等只读场景调用。
    """
    if 受控根目录 is None or not isinstance(受控根目录, str) or not 受控根目录.strip():
        return 结果.失败("参数不合法", "受控根目录必须为非空文本", 来源="文件系统")
    if 相对路径 is None or not isinstance(相对路径, str):
        return 结果.失败("参数不合法", "相对路径必须为文本", 来源="文件系统")
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
        with open(目标, "rb") as 文件流:
            return 结果.成功结果(文件流.read(max(int(字节数), 0)))
    except OSError as 错误:
        return 结果.失败("文件读取失败", str(错误), 来源="文件系统")


_临时资源登记表: set[str] = set()
_临时资源锁 = threading.Lock()


def 登记临时资源(路径: str = None) -> 结果:
    """登记一个临时资源（文件或目录），由 清理全部临时资源 统一释放。"""
    if not isinstance(路径, str) or not 路径.strip():
        return 结果.失败("参数不合法", "路径必须为非空文本", 来源="文件系统")
    with _临时资源锁:
        _临时资源登记表.add(路径)
        return 结果.成功结果(len(_临时资源登记表))


def 清理全部临时资源(路径前缀: str = "") -> 结果:
    """清理已登记临时资源（文件删除/目录递归删除，不存在视为幂等成功）。

    路径前缀 非空时只清理以此前缀开头的登记资源；无匹配登记资源时返回
    资源不存在（避免静默什么都不做）。登记表变更全部在锁内完成。
    """
    if 路径前缀 is None or not isinstance(路径前缀, str):
        return 结果.失败("参数不合法", "路径前缀必须为文本", 来源="文件系统")
    with _临时资源锁:
        待清理 = _临时资源登记表 if not 路径前缀 else {
            路径 for 路径 in _临时资源登记表 if 路径.startswith(路径前缀)
        }
        if 路径前缀 and not 待清理:
            return 结果.失败("资源不存在", f"无匹配前缀 {路径前缀} 的登记资源", 来源="文件系统")
        清理失败表 = []
        清理数量 = 0
        for 路径 in list(待清理):
            try:
                目标 = Path(路径)
                if 目标.is_dir():
                    shutil.rmtree(目标)
                else:
                    目标.unlink(missing_ok=True)
                清理数量 += 1
                _临时资源登记表.discard(路径)
            except OSError as 错误:
                清理失败表.append(f"{路径}: {错误}")
    if 清理失败表:
        return 结果.失败("清理失败", "；".join(清理失败表), 来源="文件系统")
    return 结果.成功结果(清理数量)
