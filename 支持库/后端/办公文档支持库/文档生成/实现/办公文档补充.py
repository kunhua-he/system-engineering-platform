"""办公文档补充原子能力实现。"""
from __future__ import annotations
import os
from 公共契约.基础类型.结果类型 import 结果

def 合并文本文件(文件列表: list = None, 输出路径: str = None, 分隔符: str = None) -> 结果:
    """合并多个文本文件到输出文件。返回 {输出路径, 合并文件数, 总字节数}。"""
    if not isinstance(文件列表, list) or len(文件列表) < 2:
        return 结果.失败("参数不合法", "文件列表必须至少2个文件", 来源="办公文档")
    if not isinstance(输出路径, str) or not 输出路径.strip():
        return 结果.失败("参数不合法", "输出路径必须是非空字符串", 来源="办公文档")
    分隔 = 分隔符 or "\n"
    总字节 = 0
    合并数 = 0
    try:
        with open(输出路径, "w", encoding="utf-8") as 输出:
            for i, 路径 in enumerate(文件列表):
                if not os.path.isfile(路径):
                    continue
                with open(路径, "r", encoding="utf-8") as 输入:
                    内容 = 输入.read()
                if i > 0:
                    输出.write(分隔)
                输出.write(内容)
                总字节 += len(内容.encode("utf-8"))
                合并数 += 1
        return 结果.成功结果({"输出路径": 输出路径, "合并文件数": 合并数, "总字节数": 总字节})
    except Exception as 错误:
        return 结果.失败("合并失败", str(错误), 来源="办公文档")

def 文档统计(文件路径: str = None) -> 结果:
    """统计文档字数/行数/字符数。返回 {路径, 行数, 字数, 字符数, 字节数}。"""
    if not isinstance(文件路径, str) or not 文件路径.strip():
        return 结果.失败("参数不合法", "文件路径必须是非空字符串", 来源="办公文档")
    if not os.path.isfile(文件路径):
        return 结果.失败("文件不存在", f"文件不存在: {文件路径}", 来源="办公文档")
    try:
        with open(文件路径, "r", encoding="utf-8") as f:
            内容 = f.read()
        行数 = len(内容.splitlines())
        字数 = len(内容.split())
        字符数 = len(内容)
        字节数 = len(内容.encode("utf-8"))
        return 结果.成功结果({"路径": 文件路径, "行数": 行数, "字数": 字数,
                                "字符数": 字符数, "字节数": 字节数})
    except Exception as 错误:
        return 结果.失败("统计失败", str(错误), 来源="办公文档")