"""原子能力实现（不对外暴露，只经包级中文入口调用）。

网页解析仅依赖 Python 标准库 html.parser，不引入任何第三方。
"""

from __future__ import annotations

import re as _re
from html.parser import HTMLParser
from typing import Any

from 公共契约.基础类型.结果类型 import 结果

_空白模式 = _re.compile(r"\s+")


def _成功(值: Any = None) -> 结果:
    return 结果.成功结果(值)


def _失败(错误码: str, 消息: str) -> 结果:
    return 结果.失败(错误码, 消息, 来源="网页解析")


class _标题提取器(HTMLParser):
    """提取 <title> 标签内文本。"""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.标题片段: list[str] = []
        self.在标题中 = False

    def handle_starttag(self, 标签: str, 属性表: list) -> None:
        if 标签 == "title":
            self.在标题中 = True

    def handle_endtag(self, 标签: str) -> None:
        if 标签 == "title":
            self.在标题中 = False

    def handle_data(self, 数据: str) -> None:
        if self.在标题中:
            self.标题片段.append(数据)


class _正文提取器(HTMLParser):
    """提取 body 内文本：剔除 script/style 内容，块级标签间加空格分隔。

    文档无 body 标签时回退提取整份文档（去掉 script/style）。
    """

    块级标签表 = {
        "article", "blockquote", "br", "div", "h1", "h2", "h3", "h4", "h5", "h6",
        "li", "ol", "p", "pre", "section", "table", "td", "th", "tr", "ul",
    }
    跳过标签表 = {"script", "style"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.文本片段: list[str] = []
        self.跳过深度 = 0
        self.body深度 = 0
        self.见到body = False

    def _在正文区(self) -> bool:
        return self.见到body and self.body深度 > 0

    def handle_starttag(self, 标签: str, 属性表: list) -> None:
        if 标签 == "body":
            self.见到body = True
            self.body深度 += 1
            # body 之前的 head 区文本（如 title）不属于正文，丢弃
            self.文本片段.clear()
            return
        if not self._在正文区():
            return
        if 标签 in self.跳过标签表:
            self.跳过深度 += 1

    def handle_endtag(self, 标签: str) -> None:
        if 标签 == "body" and self.body深度 > 0:
            self.body深度 -= 1
            return
        if not self._在正文区():
            return
        if 标签 in self.跳过标签表 and self.跳过深度 > 0:
            self.跳过深度 -= 1
        elif 标签 in self.块级标签表:
            self.文本片段.append(" ")

    def handle_data(self, 数据: str) -> None:
        if 跳过 := self.跳过深度:
            return
        if self.见到body and not self._在正文区():
            return
        self.文本片段.append(数据)


def _归一化空白(文本: str) -> str:
    """连续空白（含换行/制表）归一化为单个空格并去除首尾空白。"""
    return _空白模式.sub(" ", 文本).strip()


def 提取网页标题(网页内容: str) -> 结果:
    """从 HTML 内容提取 <title> 文本；无标题返回空字符串。"""
    if not isinstance(网页内容, str):
        return _失败("参数不合法", "网页内容必须为字符串")
    try:
        提取器 = _标题提取器()
        提取器.feed(网页内容)
        提取器.close()
    except Exception as 错误:
        return _失败("解析失败", f"标题解析异常: {错误}")
    标题 = "".join(提取器.标题片段)
    return _成功(标题.strip())


def 提取网页正文(网页内容: str, 最大长度: int = 20000) -> 结果:
    """从 HTML 内容提取 body 文本：剔除 script/style，空白归一化，截断到 最大长度。"""
    if not isinstance(网页内容, str):
        return _失败("参数不合法", "网页内容必须为字符串")
    if not isinstance(最大长度, int) or isinstance(最大长度, bool) or 最大长度 < 0:
        return _失败("参数不合法", "最大长度必须为非负整数")
    try:
        提取器 = _正文提取器()
        提取器.feed(网页内容)
        提取器.close()
    except Exception as 错误:
        return _失败("解析失败", f"正文解析异常: {错误}")
    正文 = _归一化空白("".join(提取器.文本片段))
    if 最大长度 > 0 and len(正文) > 最大长度:
        正文 = 正文[:最大长度]
    return _成功(正文)
