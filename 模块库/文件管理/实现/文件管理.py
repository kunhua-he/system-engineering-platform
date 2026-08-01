"""文件管理模块：只经文件系统支持库公开入口组合，不深入实现目录。"""

from __future__ import annotations

from 公共契约.基础类型.结果类型 import 结果
from 支持库.后端.文件系统 import (
    删除文件 as _删除文件,
    复制文件 as _复制文件,
    读取文件 as _读取文件,
    列出目录 as _列出目录,
    移动文件 as _移动文件,
    写入文件 as _写入文件,
)


def 读取文件(文件路径: str) -> 结果:
    return _读取文件(文件路径)


def 写入文件(文件路径: str, 内容: str) -> 结果:
    return _写入文件(文件路径, 内容)


def 复制文件(源路径: str, 目标路径: str) -> 结果:
    return _复制文件(源路径, 目标路径)


def 移动文件(源路径: str, 目标路径: str) -> 结果:
    return _移动文件(源路径, 目标路径)


def 删除文件(文件路径: str) -> 结果:
    return _删除文件(文件路径)


def 列出文件(目录路径: str) -> 结果:
    return _列出目录(目录路径)
