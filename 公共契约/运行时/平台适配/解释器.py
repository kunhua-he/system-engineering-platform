"""虚拟环境解释器相对路径（POSIX → ``bin/python3``；Windows → ``Scripts/python.exe``）与完整路径拼接。"""

from __future__ import annotations

from pathlib import Path

from 公共契约.运行时.平台适配.判定 import 是Windows


#: POSIX 虚拟环境解释器相对路径（``python -m venv`` 的固定布局）
POSIX解释器相对路径 = "bin/python3"
#: Windows 虚拟环境解释器相对路径（``python -m venv`` 的固定布局）
Windows解释器相对路径 = "Scripts/python.exe"


def 虚拟环境解释器相对路径() -> str:
    """返回虚拟环境内解释器相对其根的路径（无前导分隔符）。

    POSIX → ``bin/python3``；Windows → ``Scripts/python.exe``。

    供后续批次替换 ``运行核心/运行环境管理器/环境管理器.py`` 第 323/410/619/683/684 行与
    ``强制校验.py`` 第 281 行的硬编码 ``目标 / "bin" / "python3"``。
    """
    if 是Windows():
        return Windows解释器相对路径
    return POSIX解释器相对路径


def 虚拟环境解释器路径(环境根: str | Path) -> Path:
    """把虚拟环境根目录拼成解释器的完整路径（只拼路径，不校验存在、不创建）。

    ``环境根`` 可以是 ``str`` 或 ``Path``；返回 ``Path``。是否真实存在由调用方用
    ``.is_file()`` 判定（现有调用点就是这么用的，见环境管理器第 684 行）。
    """
    return Path(环境根) / 虚拟环境解释器相对路径()
