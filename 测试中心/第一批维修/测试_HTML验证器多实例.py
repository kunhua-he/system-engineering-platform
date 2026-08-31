"""HTML 验证器多实例制品池：端口池分配、场景分片、报告合并回归。"""
from __future__ import annotations

import unittest
from pathlib import Path

from 开发工具.HTML验证 import 验证器


class 端口池解析测试(unittest.TestCase):
    def test_区间端口池解析(self) -> None:
        端口表 = 验证器._解析端口池("45080-45083")
        self.assertEqual(端口表, [45080, 45081, 45082, 45083])

    def test_逗号端口池解析(self) -> None:
        端口表 = 验证器._解析端口池("45080,45082,45084")
        self.assertEqual(端口表, [45080, 45082, 45084])

    def test_单端口池解析(self) -> None:
        端口表 = 验证器._解析端口池("45080")
        self.assertEqual(端口表, [45080])

    def test_非法端口池阻断(self) -> None:
        with self.assertRaises(ValueError):
            验证器._解析端口池("45080-45079")
        with self.assertRaises(ValueError):
            验证器._解析端口池("abc")


class 场景分片测试(unittest.TestCase):
    def test_场景分片全部覆盖且不重复(self) -> None:
        from 开发工具.HTML验证.验证器 import 验证场景束, 多步骤验证场景
        场景表 = [
            多步骤验证场景(场景id=f"场景{i}", 包目录=Path("测试"), 前置步骤=[], 目标步骤=[], 清理步骤=[])
            for i in range(10)
        ]
        束 = 验证场景束(场景列表=场景表, 目标能力全集=set(), 制品摘要="测试")
        分片表 = 验证器._分片场景(束, 实例数=3)
        self.assertEqual(len(分片表), 3)
        全部场景id = []
        for 片 in 分片表:
            全部场景id.extend(场景.场景id for 场景 in 片)
        self.assertEqual(sorted(全部场景id), sorted(f"场景{i}" for i in range(10)))
        self.assertEqual(len(set(全部场景id)), 10)

    def test_资源键场景固定同实例(self) -> None:
        from 开发工具.HTML验证.验证器 import 验证场景束, 多步骤验证场景, 验证步骤
        资源步骤 = 验证步骤(步骤id="目标", 能力id="文档转换支持库.转换办公文件",
                      预期成功=True, 预期状态码=200)
        普通步骤 = 验证步骤(步骤id="目标", 能力id="文件系统支持库.读取文件",
                      预期成功=True, 预期状态码=200)
        场景A = 多步骤验证场景(场景id="转换A", 包目录=Path("测试"), 前置步骤=[], 目标步骤=[资源步骤], 清理步骤=[])
        场景B = 多步骤验证场景(场景id="转换B", 包目录=Path("测试"), 前置步骤=[], 目标步骤=[资源步骤], 清理步骤=[])
        场景C = 多步骤验证场景(场景id="普通C", 包目录=Path("测试"), 前置步骤=[], 目标步骤=[普通步骤], 清理步骤=[])
        束 = 验证场景束(场景列表=[场景A, 场景B, 场景C], 目标能力全集=set(), 制品摘要="测试")
        分片表 = 验证器._分片场景(束, 实例数=2)
        实例A = next(i for i, 片 in enumerate(分片表) if any(场景.场景id == "转换A" for 场景 in 片))
        实例B = next(i for i, 片 in enumerate(分片表) if any(场景.场景id == "转换B" for 场景 in 片))
        self.assertEqual(实例A, 实例B)

    def test_实例数为1时全部场景同实例(self) -> None:
        from 开发工具.HTML验证.验证器 import 验证场景束, 多步骤验证场景
        场景表 = [多步骤验证场景(场景id=f"场景{i}", 包目录=Path("测试"), 前置步骤=[], 目标步骤=[], 清理步骤=[])
                 for i in range(5)]
        束 = 验证场景束(场景列表=场景表, 目标能力全集=set(), 制品摘要="测试")
        分片表 = 验证器._分片场景(束, 实例数=1)
        self.assertEqual(len(分片表), 1)
        self.assertEqual(len(分片表[0]), 5)


if __name__ == "__main__":
    unittest.main()
