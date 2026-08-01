"""前端核心：平台无关的前端描述与调度契约。

前端核心只定义契约：窗口/页面/组件/状态/事件/资源/路由/调用/渲染。
不绑定 Vue、React、原生桌面或任何 CSS 框架。具体渲染由提供者完成
（测试渲染提供者/浏览器 HTML 渲染提供者/桌面渲染提供者）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class 组件定义:
    """一个前端组件定义。"""

    组件id: str
    类型: str = "文本"  # 文本/输入框/按钮/列表/状态区
    属性: dict[str, Any] = field(default_factory=dict)
    事件: list[str] = field(default_factory=list)  # 如 点击/输入


@dataclass
class 页面定义:
    """一个页面定义（组件列表 + 路由名）。"""

    页面id: str
    路由: str = ""
    标题: str = ""
    组件列表: list[组件定义] = field(default_factory=list)


@dataclass
class 窗口定义:
    """一个窗口定义（页面 + 生命周期）。"""

    窗口id: str
    标题: str = ""
    页面列表: list[页面定义] = field(default_factory=list)
    资源需求: list[str] = field(default_factory=list)
    后端能力依赖: list[str] = field(default_factory=list)
    状态: str = "已创建"  # 已创建/已打开/已关闭


@dataclass
class 执行单元声明:
    """前端执行单元声明。"""

    执行单元id: str
    宿主类型: str = "测试"  # 测试/浏览器HTML/桌面
    渲染方式: str = "纯文本"  # 纯文本/HTML/原生
    输入资源: list[str] = field(default_factory=list)
    导出窗口: list[str] = field(default_factory=list)
    导出事件: list[str] = field(default_factory=list)
    后端能力依赖: list[str] = field(default_factory=list)

    def 转字典(self) -> dict[str, Any]:
        return {
            "执行单元id": self.执行单元id, "宿主类型": self.宿主类型,
            "渲染方式": self.渲染方式, "输入资源": self.输入资源,
            "导出窗口": self.导出窗口, "导出事件": self.导出事件,
            "后端能力依赖": self.后端能力依赖,
        }


@dataclass
class 渲染请求:
    """一次渲染请求（提供给渲染提供者）。"""

    窗口定义: 窗口定义
    状态表: dict[str, Any] = field(default_factory=dict)
    宿主类型: str = "测试"

    def 转字典(self) -> dict[str, Any]:
        return {
            "窗口id": self.窗口定义.窗口id, "标题": self.窗口定义.标题,
            "状态表": self.状态表, "宿主类型": self.宿主类型,
        }


class 前端核心:
    """前端核心：窗口/页面/组件/状态/事件/路由 的调度与渲染分派。"""

    def __init__(self, 渲染提供者: Any = None) -> None:
        self.窗口表: dict[str, 窗口定义] = {}
        self.状态表: dict[str, Any] = {}
        self.事件处理表: dict[str, list[Callable]] = {}
        self.渲染提供者 = 渲染提供者
        self.调用函数: Callable | None = None  # 后端能力调用入口（网关/直连）

    def 注册窗口(self, 窗口: 窗口定义) -> None:
        self.窗口表[窗口.窗口id] = 窗口

    def 设置状态(self, 键: str, 值: Any) -> None:
        self.状态表[键] = 值
        self.触发事件("状态变化", {"键": 键, "值": 值})

    def 获取状态(self, 键: str, 默认值: Any = None) -> Any:
        return self.状态表.get(键, 默认值)

    def 绑定事件(self, 事件名: str, 处理函数: Callable) -> None:
        self.事件处理表.setdefault(事件名, []).append(处理函数)

    def 触发事件(self, 事件名: str, 数据: Any = None) -> list[Any]:
        结果列表 = []
        for 处理函数 in self.事件处理表.get(事件名, []):
            结果列表.append(处理函数(数据))
        return 结果列表

    def 打开窗口(self, 窗口id: str) -> dict[str, Any]:
        窗口 = self.窗口表.get(窗口id)
        if 窗口 is None:
            return {"成功": False, "错误码": "窗口不存在", "错误说明": f"窗口未注册: {窗口id}"}
        窗口.状态 = "已打开"
        self.状态表.setdefault("窗口状态", {})[窗口id] = "已打开"
        return {"成功": True, "窗口id": 窗口id}

    def 关闭窗口(self, 窗口id: str) -> dict[str, Any]:
        窗口 = self.窗口表.get(窗口id)
        if 窗口 is None:
            return {"成功": False, "错误码": "窗口不存在", "错误说明": f"窗口未注册: {窗口id}"}
        窗口.状态 = "已关闭"
        self.状态表.setdefault("窗口状态", {})[窗口id] = "已关闭"
        return {"成功": True, "窗口id": 窗口id}

    def 设置调用入口(self, 调用函数: Callable) -> None:
        """设置后端能力调用入口（网关客户端或直连）。"""
        self.调用函数 = 调用函数

    def 调用后端能力(self, 能力id: str, 参数: dict | None = None) -> Any:
        """经调用入口调用后端能力（统一结果）。"""
        if self.调用函数 is None:
            return {"成功": False, "错误码": "网关未连接", "错误说明": "未设置后端调用入口"}
        return self.调用函数(能力id, 参数 or {})

    def 渲染(self, 窗口id: str) -> Any:
        """把窗口分派给渲染提供者渲染。"""
        窗口 = self.窗口表.get(窗口id)
        if 窗口 is None:
            return {"成功": False, "错误码": "窗口不存在", "错误说明": f"窗口未注册: {窗口id}"}
        if self.渲染提供者 is None:
            return {"成功": False, "错误码": "渲染提供者缺失", "错误说明": "未设置渲染提供者"}
        return self.渲染提供者.渲染(渲染请求(窗口, dict(self.状态表)))

    def 状态快照(self) -> dict[str, Any]:
        return {"窗口数": len(self.窗口表), "状态项数": len(self.状态表),
                "事件绑定数": sum(len(处理列表) for 处理列表 in self.事件处理表.values())}
