"""验证场景可解析门禁：全仓每个包的 验证场景引用 必须能被验证器自己的解析器解开。

历史教训（2026-09-15）：`psycopg提供者` 的内联场景少了 `清理步骤` 键，验证器 `_解析多步骤场景`
直接抛 `ValueError: 验证场景字段不完整或为旧格式`，导致 HTML 黑盒「零有效验证场景」→ 发布门禁失败。
这类错误必须在提交前就被挡住——本门禁用**验证器自身的解析函数**遍历全仓，口径与门禁完全同源。
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

系统根 = Path(__file__).resolve().parents[2]
if str(系统根) not in sys.path:
    sys.path.insert(0, str(系统根))

from 开发工具.HTML验证.场景加载 import _解析场景引用, _解析多步骤场景

跳过 = ("__pycache__", "工程缓存", "示例项目")


def 全部引用文件():
    # 正式根必须扫全：漏扫任一正式根都会让该根下的场景「静默溜过」提交门
    # （先前只扫三个根，平台控制面 新增的场景因此长期未被校验）。
    for 顶层 in ("支持库", "模块库", "技能库", "平台控制面", "运行核心", "开发工具"):
        根 = 系统根 / 顶层
        if not 根.is_dir():
            continue
        for 文件 in sorted(根.rglob("验证场景引用.json")):
            if any(段 in 文件.parts for 段 in 跳过):
                continue
            yield 文件.parent


class 验证场景可解析门禁(unittest.TestCase):
    def test_全仓场景可被验证器解析(self):
        问题 = []
        包数 = 0
        for 包目录 in 全部引用文件():
            包数 += 1
            try:
                场景表 = _解析场景引用(包目录)
            except Exception as 错误:
                问题.append(f"{包目录.relative_to(系统根).as_posix()}: 引用解析失败 {错误}")
                continue
            for 原始, 所属包 in 场景表:
                try:
                    _解析多步骤场景(原始, 所属包, "0" * 64)
                except Exception as 错误:
                    问题.append(f"{包目录.relative_to(系统根).as_posix()}: 场景解析失败 {错误}")
        self.assertGreater(包数, 100, f"参与解析的包数异常: {包数}")
        self.assertEqual([], 问题[:10], f"{len(问题)} 个包的场景不可解析")


if __name__ == "__main__":
    unittest.main()
