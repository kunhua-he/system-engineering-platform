"""python-pptx 提供者包级中文入口（目录名含连字符，实现按文件路径加载）。

调用者只从此入口导入 解析演示文稿 / 生成演示文稿；禁止深入 实现/ 目录。
公开能力：演示文稿.解析演示文稿 / 演示文稿.生成演示文稿。
python-pptx 纯 Python，主进程 import；OOXML 按不可信 ZIP 处理。
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

_实现路径 = Path(__file__).resolve().parent / "实现" / "演示文稿.py"
_规格 = importlib.util.spec_from_file_location("python_pptx提供者_实现", _实现路径)
_实现 = importlib.util.module_from_spec(_规格)
_规格.loader.exec_module(_实现)

解析演示文稿 = _实现.解析演示文稿
生成演示文稿 = _实现.生成演示文稿

__all__ = ["解析演示文稿", "生成演示文稿", "注册能力"]


def 注册能力(注册表) -> None:
    """由支持库加载器调用，向能力注册表注册本库能力。"""
    from 公共契约.能力契约.契约 import 能力实现

    for 能力id, 函数, 参数名 in [
        ("演示文稿.解析演示文稿", 解析演示文稿, ["文件路径", "格式", "最大幻灯片数", "最大字节数", "超时秒"]),
        ("演示文稿.生成演示文稿", 生成演示文稿, ["内容参数"]),
    ]:
        注册表.注册(
            能力实现(
                能力id=能力id,
                包id="支持库.适配层.python_pptx提供者",
                实现函数=函数,
                参数=[{"名称": 名称, "类型": "任意"} for 名称 in 参数名],
                返回="结果",
                说明="python-pptx 独立提供者能力",
            )
        )
