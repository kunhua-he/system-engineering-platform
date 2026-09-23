"""包入口路径解析（唯一口径）：包内优先 → 系统根回退 → 越界拒绝。

支持库与模块的入口定位规则完全相同，此前在 支持库安装.py / 模块安装.py
各写一份（同一件事两套实现）。本模块是唯一事实源：装配前单包预检
（生命周期管理/管理器.py 的单包级隔离）也复用它，保证「预检查的入口」
与「真实加载的入口」永远是同一个路径。
"""

from __future__ import annotations

from pathlib import Path

from 公共契约.包声明 import 包声明
from 公共契约.基础类型.逻辑类型 import 真, 假
from 公共契约.运行时.平台适配 import 解析路径


def 定位系统根() -> Path:
    """从加载器内部向上寻找同时含 支持库 与 模块库 的祖先目录。

    找不到时退回 运行核心（与历史实现一致），由 解析入口路径 的
    越界校验兜住错误路径。
    """
    起点 = Path(__file__).resolve().parents[2]
    for 祖先 in 起点.parents:
        if (祖先 / "支持库").is_dir() and (祖先 / "模块库").is_dir():
            return 祖先
    return 起点


def 解析入口路径(声明: 包声明, 类型名: str) -> Path:
    """按 声明.入口 解析入口文件真实路径（不加载、不执行）。

    解析顺序：包根目录内 → 系统根回退；两种都越界或文件不存在即抛错。
    类型名 用于错误文案（支持库 / 模块），保持与历史消息逐字一致。

    「相对 → 绝对」一律转调 `公共契约.运行时.平台适配.解析路径`（全平台唯一那条腿），
    **显式传根**（包根 / 系统根，两者都由本模块推出，不走它的三级兜底）——
    本函数不自带 `is_absolute()` 拼根分支。
    """
    系统根 = 定位系统根()
    相对入口 = Path(声明.入口)
    if 相对入口.is_absolute() or ".." in 相对入口.parts:
        raise ValueError(f"{类型名}入口路径越界: {声明.入口}")
    try:
        包根 = Path(声明.来源路径).parent.resolve()
    except Exception:
        包根 = Path(getattr(声明, "来源路径", "") or "").parent.resolve()
    入口路径 = Path(解析路径(声明.入口, 包根)).resolve()
    使用系统根回退 = 假
    if not 入口路径.is_file() or not 入口路径.is_relative_to(包根):
        入口路径 = Path(解析路径(声明.入口, 系统根)).resolve()
        使用系统根回退 = 真
    if 使用系统根回退 and not 入口路径.is_relative_to(系统根.resolve()):
        raise ValueError(f"{类型名}入口路径越界: {声明.入口}")
    if not 入口路径.is_file():
        raise FileNotFoundError(f"{类型名} {声明.包id} 缺少入口文件: {声明.入口}")
    return 入口路径
