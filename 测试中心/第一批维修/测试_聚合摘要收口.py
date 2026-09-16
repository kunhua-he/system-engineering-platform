"""R3：聚合包完整性摘要必须与真实文件闭合。"""
from __future__ import annotations

import unittest
from pathlib import Path

from 支持库.后端.组件规范支持库 import 扫描正式包, 校验完整性摘要


class 聚合摘要收口测试(unittest.TestCase):
    def test_全部正式包摘要与文件闭合(self) -> None:
        系统根 = Path(__file__).resolve().parents[2]
        失败 = []
        for 包目录 in 扫描正式包(系统根):
            通过, 问题 = 校验完整性摘要(包目录)
            if not 通过:
                失败.append(f"{包目录.relative_to(系统根)}: {'；'.join(问题)}")
        self.assertEqual(失败, [], "；".join(失败))


if __name__ == "__main__":
    unittest.main()
