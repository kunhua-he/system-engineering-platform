"""公共契约：通用文档结果与生成产物结构。

平台文档解析/生成模块统一返回 结果[通用文档] / 结果[生成产物]。
本文件定义结构规范与构造辅助函数，供平台模块与外部项目适配层共同引用。
平台不认识外部项目内容-ir/v1；外部项目适配层负责把本结构映射为内容-ir/v1。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# 支持格式全集（统一小写、无点前缀）
支持格式集合 = {"doc", "docx", "xls", "xlsx", "ppt", "pptx", "pdf"}

# 保真级别
保真_高 = "高"
保真_中 = "中"
保真_低 = "低"

# 块类型
块_标题 = "标题"
块_段落 = "段落"
块_表格 = "表格"
块_图像 = "图像"
块_页面 = "页面"
块_工作表 = "工作表"
块_幻灯片 = "幻灯片"

# 错误码（**合法语义常量集，保留**；见下）
#
# B-7 定性（2026-09-16 现场核实，勿再按「第二套错误码常量源」处置）：
# 本组 10 条**不是**平行常量源 —— 它们的值是 能力定义.json 声明端的**子集**，全部逐字命中，
# 且 3 条无消费方（错误_转换失败/错误_生成失败/错误_取消）。它是**声明端契约的镜像**，
# 不是第二套事实源。若照 B-7 原文删除，**立刻打断真实消费方**（实测反向验证）：
#   `支持库/适配层/pdfplumber提供者/实现/PDF文本表格.py` 具名导入其中 7 条
#   → ImportError: cannot import name '错误_参数不合法' from '公共契约.基础类型.文档结构'。
#   （2026-09-18 引用口径修正：原文并列点名的
#   `支持库/后端/文档转换支持库/PDF文本表格/实现/PDF文本表格.py:16-19` 已收口为纯转调壳
#   ——该文件现全文 0 处引用本模块（`sys.modules[__name__] = 唯一实现`），
#   唯一真实消费方只剩上述适配层腿；行号引用已改为文件级，不再写 `:16-19`。）
# （另有 7 个文件各自定义同名局部常量 `错误_参数不合法 = "参数不合法"`，与本模块无关。）
# 结论：本组**保留**；平台错误码的唯一事实源仍是各包 能力定义.json（由 开发工具/公开调用完整性门禁
# 的「错误码登记环」固定：声明码 ⊆ 网关状态映射码 == 网关说明表码）。
错误_提供者不可用 = "提供者不可用"
错误_文件不存在 = "文件不存在"
错误_文件损坏 = "文件损坏"
错误_文件加密 = "文件加密"
错误_超出限制 = "超出限制"
错误_参数不合法 = "参数不合法"
错误_转换失败 = "转换失败"
错误_生成失败 = "生成失败"
错误_超时 = "超时"
错误_取消 = "取消"


@dataclass(frozen=True)
class 来源位置:
    """块在原始文件中的位置信息（页码/工作表/幻灯片等，按格式选用）。"""

    页码: int | None = None
    工作表: str | None = None
    幻灯片: int | None = None
    段落序号: int | None = None
    行号: int | None = None
    列号: int | None = None
    附加: dict[str, Any] = field(default_factory=dict)

    def 转字典(self) -> dict[str, Any]:
        结果: dict[str, Any] = dict(self.附加)
        if self.页码 is not None:
            结果["页码"] = self.页码
        if self.工作表 is not None:
            结果["工作表"] = self.工作表
        if self.幻灯片 is not None:
            结果["幻灯片"] = self.幻灯片
        if self.段落序号 is not None:
            结果["段落序号"] = self.段落序号
        if self.行号 is not None:
            结果["行号"] = self.行号
        if self.列号 is not None:
            结果["列号"] = self.列号
        return 结果


@dataclass(frozen=True)
class 文档块:
    """通用块：文本、表格、图像等。"""

    类型: str
    文本: str = ""
    来源位置: 来源位置 = field(default_factory=来源位置)
    资源引用: int | None = None
    表格数据: list[list[str]] | None = None
    附加: dict[str, Any] = field(default_factory=dict)

    def 转字典(self) -> dict[str, Any]:
        结果: dict[str, Any] = {
            "类型": self.类型,
            "文本": self.文本,
            "来源位置": self.来源位置.转字典(),
            "资源引用": self.资源引用,
        }
        if self.表格数据 is not None:
            结果["表格数据"] = self.表格数据
        结果.update(self.附加)
        return 结果


@dataclass(frozen=True)
class 文档资源:
    """内嵌资源（图像等），字节数据用 base64 文本承载。"""

    类型: str
    媒体类型: str = ""
    文件名: str = ""
    描述: str = ""
    字节数据b64: str = ""
    附加: dict[str, Any] = field(default_factory=dict)

    def 转字典(self) -> dict[str, Any]:
        结果: dict[str, Any] = {
            "类型": self.类型,
            "媒体类型": self.媒体类型,
            "文件名": self.文件名,
            "描述": self.描述,
            "字节数据b64": self.字节数据b64,
        }
        结果.update(self.附加)
        return 结果


@dataclass(frozen=True)
class 通用文档:
    """平台通用文档结果（解析产物）。"""

    文档类型: str
    格式: str
    标题: str = ""
    块列表: list[文档块] = field(default_factory=list)
    资源列表: list[文档资源] = field(default_factory=list)
    保真级别: str = 保真_高
    解析方式: str = ""
    警告: list[str] = field(default_factory=list)
    诊断: list[str] = field(default_factory=list)
    耗时秒: float = 0.0
    提供者版本: dict[str, str] = field(default_factory=dict)
    原始文件摘要: str = ""
    附加: dict[str, Any] = field(default_factory=dict)

    def 转字典(self) -> dict[str, Any]:
        结果: dict[str, Any] = {
            "文档类型": self.文档类型,
            "格式": self.格式,
            "标题": self.标题,
            "块列表": [块.转字典() for 块 in self.块列表],
            "资源列表": [资源.转字典() for 资源 in self.资源列表],
            "保真级别": self.保真级别,
            "解析方式": self.解析方式,
            "警告": self.警告,
            "诊断": self.诊断,
            "耗时秒": self.耗时秒,
            "提供者版本": dict(self.提供者版本),
            "原始文件摘要": self.原始文件摘要,
        }
        结果.update(self.附加)
        return 结果


@dataclass(frozen=True)
class 生成产物:
    """平台通用生成结果。"""

    格式: str
    字节: bytes = b""
    媒体类型: str = ""
    摘要: str = ""
    诊断: list[str] = field(default_factory=list)
    附加: dict[str, Any] = field(default_factory=dict)

    def 转字典(self) -> dict[str, Any]:
        结果: dict[str, Any] = {
            "格式": self.格式,
            "字节数": len(self.字节),
            "媒体类型": self.媒体类型,
            "摘要": self.摘要,
            "诊断": self.诊断,
        }
        结果.update(self.附加)
        return 结果


def 归一化格式(格式: str | None) -> str:
    """格式统一为小写无点前缀；非法格式抛 ValueError。"""
    值 = (格式 or "").lower().lstrip(".")
    if 值 not in 支持格式集合:
        raise ValueError(f"不支持的格式 '{格式}'，支持：{sorted(支持格式集合)}")
    return 值
