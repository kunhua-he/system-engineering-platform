"""网络通信支持库 聚合入口。自动生成，所有子库能力统一导出。"""
from __future__ import annotations

from 支持库.后端.网络通信支持库.网页解析 import 提取网页标题
from 支持库.后端.网络通信支持库.网页解析 import 提取网页正文
from 支持库.后端.网络通信支持库.网页解析 import 注册能力
from 支持库.后端.网络通信支持库.请求 import 发送请求
from 支持库.后端.网络通信支持库.请求 import 构建查询串

__all__ = [
    "发送请求",
    "提取网页标题",
    "提取网页正文",
    "构建查询串",
    "注册能力",
]


def 注册能力(注册表) -> None:
    """聚合注册：收集所有子库的能力注册。"""
    import importlib
    for 子库名 in ['网页解析', '请求']:
        try:
            入口 = importlib.import_module("支持库.后端.网络通信支持库." + 子库名)
            注册函数 = getattr(入口, "注册能力", None)
            if callable(注册函数):
                注册函数(注册表)
        except Exception as 错误:
            raise RuntimeError(f"聚合子库 {子库名} 注册失败: {错误}") from 错误
