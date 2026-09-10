"""浏览器自动化支持库 B2 实现：句柄、租约资源与 Provider 统一收口。"""

from __future__ import annotations

import threading
import uuid
from typing import Any

from 公共契约.基础类型.结果类型 import 结果
from 公共契约.句柄体系 import 句柄类型_会话, 句柄类型_资源, 句柄体系
from 支持库.适配层.浏览器自动化提供者 import 浏览器自动化提供者

来源 = "浏览器自动化支持库"
句柄系统 = 句柄体系()
_提供者 = 浏览器自动化提供者()
会话表: dict[int, str] = {}
截图表: dict[int, list[int]] = {}
锁 = threading.RLock()


def _统一(数据: dict[str, Any]) -> 结果:
    if 数据.get("成功"):
        return 结果.成功结果(数据.get("值"))
    return 结果.失败(
        str(数据.get("错误码") or "Provider执行失败"),
        str(数据.get("错误说明") or "浏览器 Provider 调用失败"),
        来源=来源,
        可重试=数据.get("错误码") in {"超时", "提供者不可用"},
    )


def _会话(句柄: int) -> tuple[str | None, str]:
    if isinstance(句柄, bool) or not isinstance(句柄, int):
        return None, "句柄必须是整数"
    有效, 原因 = 句柄系统.校验(句柄)
    if not 有效:
        return None, 原因
    名称 = 会话表.get(句柄)
    return (名称, "") if 名称 else (None, "浏览器会话句柄不存在")


def 创建会话(会话模式: str = "临时", 授权标识: str = "", 超时秒: int = 30,
            视口宽: int = 0, 视口高: int = 0) -> 结果:
    if 会话模式 not in {"临时", "授权快照"} or not isinstance(超时秒, int) or not 1 <= 超时秒 <= 1800:
        return 结果.失败("参数不合法", "会话模式或超时秒不符合契约", 来源=来源)
    if not isinstance(视口宽, int) or not isinstance(视口高, int) \
            or not 0 <= 视口宽 <= 10000 or not 0 <= 视口高 <= 10000:
        return 结果.失败("参数不合法", "视口宽高必须是 0-10000 的整数（0 表示用浏览器默认）", 来源=来源)
    数据 = _提供者.建立连接(超时秒=超时秒, 视口宽=视口宽, 视口高=视口高)
    if not 数据.get("成功"):
        return _统一(数据)
    会话名 = str((数据.get("值") or {}).get("会话名", ""))
    if not 会话名:
        return 结果.失败("启动失败", "Provider未返回会话名", 来源=来源)
    try:
        对象 = 句柄系统.创建句柄(
            句柄类型=句柄类型_会话,
            资源id=f"浏览器会话:{会话名}",
            版本="1.0.0",
        )
        句柄 = 对象.句柄id
        with 锁:
            会话表[句柄] = 会话名
            截图表[句柄] = []

        def 清理会话() -> None:
            清理结果 = _提供者.关闭会话(会话名=会话名)
            if not 清理结果.get("成功"):
                raise RuntimeError(清理结果.get("错误说明", "浏览器会话未收敛"))

        绑定, 说明 = 句柄系统.登记资源(句柄, 资源类型="连接", 清理函数=清理会话)
        if not 绑定:
            _提供者.关闭会话(会话名=会话名)
            句柄系统.失效(句柄, "创建失败")
            return 结果.失败("创建失败", 说明, 来源=来源)
        return 结果.成功结果({"句柄": 句柄, "状态": "已创建"})
    except (OSError, RuntimeError, ValueError) as 错误:
        _提供者.关闭会话(会话名=会话名)
        return 结果.失败("创建失败", str(错误), 来源=来源)


def 导航页面(句柄: int, 地址: str, 超时秒: int = 30) -> 结果:
    会话名, 原因 = _会话(句柄)
    if not 会话名:
        return 结果.失败("句柄无效", 原因, 来源=来源)
    if not isinstance(地址, str) or not 地址 or not isinstance(超时秒, int):
        return 结果.失败("参数不合法", "地址和超时秒不符合契约", 来源=来源)
    return _统一(_提供者.导航(会话名=会话名, 地址=地址, 超时秒=超时秒))


def 读取页面(句柄: int, 内容类型: str = "文本", 最大长度: int = 20000) -> 结果:
    会话名, 原因 = _会话(句柄)
    if not 会话名:
        return 结果.失败("句柄无效", 原因, 来源=来源)
    if 内容类型 not in {"文本", "HTML"} or not isinstance(最大长度, int) or not 1 <= 最大长度 <= 100000:
        return 结果.失败("参数不合法", "内容类型或最大长度不符合契约", 来源=来源)
    return _统一(_提供者.读取(会话名=会话名, 内容类型=内容类型, 最大长度=最大长度))


def 页面操作(句柄: int, 操作: str, 选择器: str = "", 文本: str = "", 超时秒: int = 30) -> 结果:
    会话名, 原因 = _会话(句柄)
    if not 会话名:
        return 结果.失败("句柄无效", 原因, 来源=来源)
    if 操作 not in {"点击", "填写", "按键", "等待"} or not isinstance(超时秒, int):
        return 结果.失败("参数不合法", "页面操作或超时秒不符合契约", 来源=来源)
    return _统一(_提供者.操作(
        会话名=会话名, 操作=操作, 选择器=选择器, 文本=文本, 超时秒=超时秒))


def 获取截图(句柄: int, 格式: str = "png", 最大字节数: int = 5242880) -> 结果:
    会话名, 原因 = _会话(句柄)
    if not 会话名:
        return 结果.失败("句柄无效", 原因, 来源=来源)
    if 格式 not in {"png", "jpeg"} or not isinstance(最大字节数, int) or not 1024 <= 最大字节数 <= 20971520:
        return 结果.失败("参数不合法", "截图格式或最大字节数不符合契约", 来源=来源)
    数据 = _提供者.截图(会话名=会话名, 格式=格式)
    if not 数据.get("成功"):
        return _统一(数据)
    值 = 数据.get("值") or {}
    if int(值.get("字节数", 0)) > 最大字节数:
        return 结果.失败("输出超限", "截图超过最大字节数", 来源=来源)
    try:
        对象 = 句柄系统.创建句柄(
            句柄类型=句柄类型_资源,
            资源id=f"浏览器截图:{uuid.uuid4().hex[:12]}",
            版本="1.0.0",
        )
        资源句柄 = 对象.句柄id
        绑定, 说明 = 句柄系统.登记资源(
            资源句柄, 资源类型="临时文件", 资源路径=str(值["路径"]))
        if not 绑定:
            句柄系统.失效(资源句柄, "登记失败")
            return 结果.失败("截图失败", 说明, 来源=来源)
        with 锁:
            截图表.setdefault(句柄, []).append(资源句柄)
        return 结果.成功结果({
            "资源句柄": 资源句柄, "格式": 值.get("格式", 格式),
            "字节数": int(值.get("字节数", 0)),
        })
    except (OSError, RuntimeError, ValueError, KeyError) as 错误:
        return 结果.失败("截图失败", str(错误), 来源=来源)


def 关闭会话(句柄: int) -> 结果:
    if isinstance(句柄, bool) or not isinstance(句柄, int):
        return 结果.失败("参数不合法", "句柄必须是整数", 来源=来源)
    with 锁:
        已有 = 句柄系统.句柄表.get(句柄)
        截图句柄表 = list(截图表.get(句柄, []))
    if 已有 is None:
        return 结果.成功结果({"句柄": 句柄, "状态": "未找到且已幂等", "已释放": True})
    for 截图句柄 in 截图句柄表:
        句柄系统.失效(截图句柄, "会话关闭")
    成功, 说明 = 句柄系统.失效(句柄, "释放")
    if not 成功:
        return 结果.失败("资源未收敛", 说明, 来源=来源, 可重试=True)
    with 锁:
        会话表.pop(句柄, None)
        截图表.pop(句柄, None)
    return 结果.成功结果({"句柄": 句柄, "状态": "已结束并已释放", "已释放": True})
