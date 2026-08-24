"""前端渲染提供者：测试渲染提供者 + 浏览器 HTML 最小渲染提供者。

前端核心只描述和调度，具体渲染由提供者完成。浏览器提供者使用标准库
生成 HTML 和 JavaScript；业务语义通过中文能力契约传递。
"""

from __future__ import annotations

import json
from typing import Any


def _安全脚本数据(值: Any) -> str:
    return (json.dumps(值, ensure_ascii=False, separators=(",", ":"))
            .replace("<", "\\u003c").replace(">", "\\u003e")
            .replace("&", "\\u0026").replace("\u2028", "\\u2028")
            .replace("\u2029", "\\u2029"))


class 测试渲染提供者:
    """测试渲染提供者：验证窗口/组件/状态/事件/调用/错误/关闭/释放。"""

    宿主类型 = "测试"
    渲染方式 = "纯文本"

    def 渲染(self, 请求: Any) -> dict[str, Any]:
        """渲染窗口为纯文本视图（供测试断言）。"""
        行列表 = [
            f"窗口: {请求.窗口定义.标题}（{请求.窗口定义.窗口id}）",
            f"状态: {请求.窗口定义.状态}",
        ]
        for 页面 in 请求.窗口定义.页面列表:
            行列表.append(f"页面: {页面.标题 or 页面.页面id}（路由 {页面.路由}）")
            for 组件 in 页面.组件列表:
                值 = 请求.状态表.get(组件.组件id, 组件.属性.get("默认值", ""))
                行列表.append(f"  组件[{组件.类型}]: {组件.组件id} = {值}")
        行列表.append(f"状态表: {json.dumps(请求.状态表, ensure_ascii=False)}")
        return {
            "成功": True, "宿主": self.宿主类型, "渲染方式": self.渲染方式,
            "文本": "\n".join(行列表),
        }


class HTML渲染提供者:
    """浏览器 HTML 提供者：统一复用真实 HTTP 交互实现。"""

    宿主类型 = "浏览器HTML"
    渲染方式 = "HTML"

    def __init__(self, 网关地址: str = "http://127.0.0.1:8899",
                 流式网关地址: str | None = None) -> None:
        from 前端核心.浏览器交互 import 浏览器交互提供者

        self._提供者 = 浏览器交互提供者(网关地址, 流式网关地址)

    def 渲染(self, 请求: Any) -> dict[str, Any]:
        """生成只通过 HTTP 网关调用后端的自包含页面。"""
        结果 = self._提供者.渲染(请求)
        结果["宿主"] = self.宿主类型
        结果["渲染方式"] = self.渲染方式
        return 结果


def 创建渲染提供者(宿主类型: str = "测试") -> Any:
    """按宿主类型创建渲染提供者。"""
    if 宿主类型 == "浏览器HTML":
        return HTML渲染提供者()
    return 测试渲染提供者()
