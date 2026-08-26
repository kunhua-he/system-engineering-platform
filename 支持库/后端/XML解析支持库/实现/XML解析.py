"""XML解析原子能力实现（不对外暴露，只经包级中文入口调用）。

职责：XML 解析/生成/查询节点（参考易语言 XML解析支持库，保持原子）。
纯标准库 xml.etree.ElementTree，不做业务逻辑。
"""

from __future__ import annotations

import xml.etree.ElementTree as ET

from 公共契约.基础类型.结果类型 import 结果


def 解析XML(XML文本: str = None) -> 结果:
    """XML 文本 → 树结构。返回 {根节点, 节点数}。"""
    if not isinstance(XML文本, str) or not XML文本.strip():
        return 结果.失败("参数不合法", "XML文本必须是非空字符串", 来源="XML解析")
    try:
        根 = ET.fromstring(XML文本)
    except ET.ParseError as 错误:
        return 结果.失败("解析失败", f"XML 格式错误: {错误}", 来源="XML解析")
    节点数 = sum(1 for _ in 根.iter())
    return 结果.成功结果({"根节点": {"名称": 根.tag, "属性": 根.attrib,
                                      "文本": 根.text.strip() if 根.text and 根.text.strip() else ""},
                            "节点数": 节点数})


def 生成XML(根节点名: str = None, 子节点: list = None) -> 结果:
    """结构 → XML 文本。返回 {XML文本}。"""
    if not isinstance(根节点名, str) or not 根节点名.strip():
        return 结果.失败("参数不合法", "根节点名必须是非空字符串", 来源="XML解析")
    根 = ET.Element(根节点名)
    for 子 in (子节点 or []):
        if not isinstance(子, dict):
            continue
        名 = 子.get("名称") or 子.get("name") or "节点"
        节点 = ET.SubElement(根, 名)
        节点.text = 子.get("文本") or 子.get("text") or ""
        for 属性名, 属性值 in (子.get("属性") or {}).items():
            节点.set(属性名, 属性值)
    try:
        XML文本 = ET.tostring(根, encoding="unicode", short_empty_elements=True)
        return 结果.成功结果({"XML文本": XML文本})
    except Exception as 错误:
        return 结果.失败("生成失败", str(错误), 来源="XML解析")


def 查询节点(XML文本: str = None, XPath: str = None) -> 结果:
    """XPath 查询节点。返回 {找到, 结果列表}。"""
    if not isinstance(XML文本, str) or not XML文本.strip():
        return 结果.失败("参数不合法", "XML文本必须是非空字符串", 来源="XML解析")
    if not isinstance(XPath, str) or not XPath.strip():
        return 结果.失败("参数不合法", "XPath必须是非空字符串", 来源="XML解析")
    try:
        根 = ET.fromstring(XML文本)
        命中 = 根.findall(XPath)
    except ET.ParseError as 错误:
        return 结果.失败("解析失败", f"XML 格式错误: {错误}", 来源="XML解析")
    except Exception as 错误:
        return 结果.失败("节点不存在", f"XPath 查询失败: {错误}", 来源="XML解析")
    结果列表 = [{"名称": n.tag, "文本": n.text.strip() if n.text and n.text.strip() else "",
                  "属性": dict(n.attrib)} for n in 命中]
    return 结果.成功结果({"找到": len(命中) > 0, "结果列表": 结果列表, "数量": len(结果列表)})
