"""文件系统支持库 聚合入口。自动生成，所有子库能力统一导出。"""
from __future__ import annotations

from 支持库.后端.文件系统支持库.文件操作 import 读取文件
from 支持库.后端.文件系统支持库.文件操作 import 读取二进制文件
from 支持库.后端.文件系统支持库.文件操作 import 读取文件头部字节
from 支持库.后端.文件系统支持库.文件操作 import 写入文件
from 支持库.后端.文件系统支持库.文件操作 import 判断存在
from 支持库.后端.文件系统支持库.文件操作 import 列出目录
from 支持库.后端.文件系统支持库.文件操作 import 删除文件
from 支持库.后端.文件系统支持库.文件操作 import 复制文件
from 支持库.后端.文件系统支持库.文件操作 import 移动文件
from 支持库.后端.文件系统支持库.文件操作 import 获取大小
from 支持库.后端.文件系统支持库.文件操作 import 获取修改时间
from 支持库.后端.文件系统支持库.文件操作 import 创建目录
from 支持库.后端.文件系统支持库.文件操作 import 登记临时资源
from 支持库.后端.文件系统支持库.文件操作 import 清理全部临时资源

__all__ = [
    "写入文件",
    "列出目录",
    "创建目录",
    "删除文件",
    "判断存在",
    "复制文件",
    "清理全部临时资源",
    "登记临时资源",
    "移动文件",
    "获取修改时间",
    "获取大小",
    "读取二进制文件",
    "读取文件",
    "读取文件头部字节",
]


def 注册能力(注册表) -> None:
    """聚合注册：收集所有子库的能力注册。"""
    import importlib
    for 子库名 in ['文件操作']:
        try:
            入口 = importlib.import_module("支持库.后端.文件系统支持库." + 子库名)
            注册函数 = getattr(入口, "注册能力", None)
            if callable(注册函数):
                注册函数(注册表)
        except Exception:
            pass
