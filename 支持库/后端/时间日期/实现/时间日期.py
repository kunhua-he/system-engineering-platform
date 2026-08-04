"""原子能力实现（不对外暴露，只经包级中文入口调用）。

时区策略：固定使用 项目时区（Asia/Shanghai），不依赖进程机器的隐式本地时区。
时钟策略：模块级 时钟提供者 可注入（测试用），生产默认系统时钟。
全部公开能力返回统一结果（成功/值/错误/错误码）；参数缺失或类型非法
返回 参数不合法，不抛出异常、不以成功形状伪装失败。
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Callable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from 公共契约.基础类型.结果类型 import 结果

项目时区 = ZoneInfo("Asia/Shanghai")
默认格式 = "%Y-%m-%d %H:%M:%S"

# 可注入时钟：生产默认 datetime.now(项目时区)；测试可替换为固定时钟
时钟提供者: Callable[[], datetime] = lambda: datetime.now(项目时区)


def 注入时钟(提供者: Callable[[], datetime]) -> None:
    """测试用：替换时钟提供者（禁止在生产调用）。"""
    global 时钟提供者
    时钟提供者 = 提供者


def 恢复默认时钟() -> None:
    """恢复系统时钟（测试 tearDown 用）。"""
    global 时钟提供者
    时钟提供者 = lambda: datetime.now(项目时区)


def _成功(值: Any = None) -> 结果:
    return 结果.成功结果(值)


def _失败(错误码: str, 消息: str) -> 结果:
    return 结果.失败(错误码, 消息, 来源="时间日期")


def _解析时区(时区名: str) -> ZoneInfo:
    """解析 IANA 时区名（默认项目时区）。"""
    if not 时区名:
        return 项目时区
    return ZoneInfo(时区名)


def 获取当前时间(时区: str = "Asia/Shanghai") -> 结果:
    """返回当前时间的 ISO 格式（含 T，秒精度），固定 Asia/Shanghai 时区。"""
    if not isinstance(时区, str):
        return _失败("参数不合法", "时区必须为文本")
    try:
        目标时区 = _解析时区(时区)
    except ZoneInfoNotFoundError:
        return _失败("参数不合法", f"未知时区: {时区}")
    return _成功(时钟提供者().astimezone(目标时区).isoformat(timespec="seconds"))


def 格式化为文本(时间戳: float = None, 格式: str = 默认格式) -> 结果:
    """把时间戳按格式化为文本（Asia/Shanghai 时区）。"""
    if 时间戳 is None or isinstance(时间戳, bool) or not isinstance(时间戳, (int, float)):
        return _失败("参数不合法", "时间戳必须为数字")
    if not isinstance(格式, str):
        return _失败("参数不合法", "格式必须为文本")
    try:
        return _成功(datetime.fromtimestamp(float(时间戳), 项目时区).strftime(格式))
    except (ValueError, OSError) as 错误:
        return _失败("参数不合法", f"时间戳无效: {错误}")


def 解析文本时间(文本: str = None, 格式: str = 默认格式) -> 结果:
    """按格式解析时间文本为时间戳（Asia/Shanghai 时区）。"""
    if 文本 is None or not isinstance(文本, str) or not 文本.strip():
        return _失败("参数不合法", "文本必须为非空字符串")
    if not isinstance(格式, str):
        return _失败("参数不合法", "格式必须为文本")
    try:
        时刻 = datetime.strptime(文本, 格式).replace(tzinfo=项目时区)
        return _成功(时刻.timestamp())
    except ValueError as 错误:
        return _失败("参数不合法", f"时间文本无效: {错误}")


def 时间戳转换(时间戳: float = None) -> 结果:
    """把时间戳转换为年月日时分秒结构（Asia/Shanghai 时区）。"""
    if 时间戳 is None or isinstance(时间戳, bool) or not isinstance(时间戳, (int, float)):
        return _失败("参数不合法", "时间戳必须为数字")
    try:
        结构 = datetime.fromtimestamp(float(时间戳), 项目时区).timetuple()
        return _成功({
            "年": 结构.tm_year, "月": 结构.tm_mon, "日": 结构.tm_mday,
            "时": 结构.tm_hour, "分": 结构.tm_min, "秒": 结构.tm_sec,
        })
    except (ValueError, OSError) as 错误:
        return _失败("参数不合法", f"时间戳无效: {错误}")


def 计算间隔(起始时间戳: float = None, 结束时间戳: float = None) -> 结果:
    """计算两个时间戳的间隔秒数（保留 3 位小数）。"""
    if 起始时间戳 is None or isinstance(起始时间戳, bool) \
            or not isinstance(起始时间戳, (int, float)):
        return _失败("参数不合法", "起始时间戳必须为数字")
    if 结束时间戳 is None or isinstance(结束时间戳, bool) \
            or not isinstance(结束时间戳, (int, float)):
        return _失败("参数不合法", "结束时间戳必须为数字")
    return _成功(round(float(结束时间戳) - float(起始时间戳), 3))
