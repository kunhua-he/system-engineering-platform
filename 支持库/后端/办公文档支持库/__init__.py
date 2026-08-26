"""办公文档支持库 聚合入口。自动生成，所有子库能力统一导出。"""
from __future__ import annotations

from 支持库.后端.办公文档支持库.PDF文档 import 解析PDF
from 支持库.后端.办公文档支持库.文字文档 import 解析文字文档
from 支持库.后端.办公文档支持库.文档生成 import 生成DOCX
from 支持库.后端.办公文档支持库.文档生成 import 生成XLSX
from 支持库.后端.办公文档支持库.文档生成 import 生成PPTX
from 支持库.后端.办公文档支持库.文档生成 import 生成PDF
from 支持库.后端.办公文档支持库.文档生成 import 校验签名
from 支持库.后端.办公文档支持库.文档转换 import 检查提供者
from 支持库.后端.办公文档支持库.文档转换 import 转换文本文件
from 支持库.后端.办公文档支持库.文档转换 import 转换办公文件
from 支持库.后端.办公文档支持库.模板渲染 import 渲染模板
from 支持库.后端.办公文档支持库.模板渲染 import 提取变量名
from 支持库.后端.办公文档支持库.演示文稿 import 解析演示文稿
from 支持库.后端.办公文档支持库.表格文档 import 解析表格文档

__all__ = [
    "提取变量名",
    "校验签名",
    "检查提供者",
    "渲染模板",
    "生成DOCX",
    "生成PDF",
    "生成PPTX",
    "生成XLSX",
    "解析PDF",
    "解析文字文档",
    "解析演示文稿",
    "解析表格文档",
    "转换办公文件",
    "转换文本文件",
]


def 注册能力(注册表) -> None:
    """聚合注册：收集所有子库的能力注册。"""
    import importlib
    for 子库名 in ['PDF文档', '文字文档', '文档生成', '文档转换', '模板渲染', '演示文稿', '表格文档']:
        try:
            入口 = importlib.import_module("支持库.后端.办公文档支持库." + 子库名)
            注册函数 = getattr(入口, "注册能力", None)
            if callable(注册函数):
                注册函数(注册表)
        except Exception:
            pass
