"""网页浏览模块：只组合公开浏览器能力，不接触支持库实现。"""

from __future__ import annotations

from 公共契约.基础类型.结果类型 import 结果

来源 = "网页浏览"
连接器 = None
创建能力 = "浏览器自动化.创建会话"
导航能力 = "浏览器自动化.导航页面"
读取能力 = "浏览器自动化.读取页面"
关闭能力 = "浏览器自动化.关闭会话"


def 设置HTTP连接器(新连接器) -> None:
    global 连接器
    连接器 = 新连接器


def _调用(能力id: str, 参数: dict) -> 结果:
    if 连接器 is None:
        return 结果.失败("提供者不可用", "HTTP 连接器未装配", 来源=来源)
    try:
        数据 = 连接器.调用能力(能力id, 参数)
    except Exception as 错误:
        return 结果.失败("提供者不可用", str(错误), 来源=来源)
    if isinstance(数据, 结果):
        return 数据
    if not isinstance(数据, dict):
        return 结果.失败("返回结果不符合契约", "连接器返回不是对象", 来源=来源)
    if 数据.get("成功"):
        return 结果.成功结果(数据.get("值"))
    return 结果.失败(
        str(数据.get("错误码") or "提供者不可用"),
        str(数据.get("错误说明") or "浏览器能力调用失败"),
        来源=来源,
    )


def 打开并读取网页(地址: str, 最大长度: int = 20000, 会话模式: str = "临时") -> 结果:
    if not isinstance(地址, str) or not 地址.strip():
        return 结果.失败("参数不合法", "地址必须是非空文本", 来源=来源)
    if not isinstance(最大长度, int) or not 1 <= 最大长度 <= 100000:
        return 结果.失败("参数不合法", "最大长度必须在1到100000之间", 来源=来源)
    创建 = _调用(创建能力, {"会话模式": 会话模式})
    if not 创建.成功:
        return 创建
    句柄 = (创建.值 or {}).get("句柄")
    if not isinstance(句柄, int):
        return 结果.失败("返回结果不符合契约", "创建会话未返回句柄", 来源=来源)
    主结果 = None
    try:
        导航 = _调用(导航能力, {"句柄": 句柄, "地址": 地址})
        if not 导航.成功:
            主结果 = 导航
        else:
            主结果 = _调用(读取能力, {"句柄": 句柄, "最大长度": 最大长度})
    finally:
        关闭 = _调用(关闭能力, {"句柄": 句柄})
        if 主结果 is not None and 主结果.成功 and not 关闭.成功:
            主结果 = 结果.失败("资源未收敛", 关闭.错误说明 or "会话关闭失败", 来源=来源, 可重试=True)
    return 主结果 or 结果.失败("内部错误", "网页浏览流程没有产生结果", 来源=来源)
