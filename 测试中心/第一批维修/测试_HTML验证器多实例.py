"""HTML 验证器多实例制品池：端口池分配、场景分片、报告合并回归。"""
from __future__ import annotations

import unittest
from unittest import mock
from pathlib import Path

from 开发工具.HTML验证 import 端口池
from 开发工具.HTML验证.单步场景 import 验证步骤
from 开发工具.HTML验证.多步场景 import 验证场景束, 多步骤验证场景
from 开发工具.HTML验证 import 多实例制品池


class 端口池解析测试(unittest.TestCase):
    def test_区间端口池解析(self) -> None:
        端口表 = 端口池._解析端口池("45080-45083")
        self.assertEqual(端口表, [45080, 45081, 45082, 45083])

    def test_逗号端口池解析(self) -> None:
        端口表 = 端口池._解析端口池("45080,45082,45084")
        self.assertEqual(端口表, [45080, 45082, 45084])

    def test_单端口池解析(self) -> None:
        端口表 = 端口池._解析端口池("45080")
        self.assertEqual(端口表, [45080])

    def test_非法端口池阻断(self) -> None:
        with self.assertRaises(ValueError):
            端口池._解析端口池("45080-45079")
        with self.assertRaises(ValueError):
            端口池._解析端口池("abc")


class 场景分片测试(unittest.TestCase):
    def test_场景分片全部覆盖且不重复(self) -> None:
        场景表 = [
            多步骤验证场景(场景id=f"场景{i}", 包目录=Path("测试"), 前置步骤=[], 目标步骤=[], 清理步骤=[])
            for i in range(10)
        ]
        束 = 验证场景束(场景列表=场景表, 目标能力全集=set(), 制品摘要="测试")
        分片表 = 端口池._分片场景(束, 实例数=3)
        self.assertEqual(len(分片表), 3)
        全部场景id = []
        for 片 in 分片表:
            全部场景id.extend(场景.场景id for 场景 in 片)
        self.assertEqual(sorted(全部场景id), sorted(f"场景{i}" for i in range(10)))
        self.assertEqual(len(set(全部场景id)), 10)

    def test_资源键场景固定同实例(self) -> None:
        资源步骤 = 验证步骤(步骤id="目标", 能力id="文档转换支持库.转换办公文件",
                      预期成功=True, 预期状态码=200)
        普通步骤 = 验证步骤(步骤id="目标", 能力id="文件系统支持库.读取文件",
                      预期成功=True, 预期状态码=200)
        场景A = 多步骤验证场景(场景id="转换A", 包目录=Path("测试"), 前置步骤=[], 目标步骤=[资源步骤], 清理步骤=[])
        场景B = 多步骤验证场景(场景id="转换B", 包目录=Path("测试"), 前置步骤=[], 目标步骤=[资源步骤], 清理步骤=[])
        场景C = 多步骤验证场景(场景id="普通C", 包目录=Path("测试"), 前置步骤=[], 目标步骤=[普通步骤], 清理步骤=[])
        束 = 验证场景束(场景列表=[场景A, 场景B, 场景C], 目标能力全集=set(), 制品摘要="测试")
        分片表 = 端口池._分片场景(束, 实例数=2)
        实例A = next(i for i, 片 in enumerate(分片表) if any(场景.场景id == "转换A" for 场景 in 片))
        实例B = next(i for i, 片 in enumerate(分片表) if any(场景.场景id == "转换B" for 场景 in 片))
        self.assertEqual(实例A, 实例B)

    def test_实例数为1时全部场景同实例(self) -> None:
        场景表 = [多步骤验证场景(场景id=f"场景{i}", 包目录=Path("测试"), 前置步骤=[], 目标步骤=[], 清理步骤=[])
                 for i in range(5)]
        束 = 验证场景束(场景列表=场景表, 目标能力全集=set(), 制品摘要="测试")
        分片表 = 端口池._分片场景(束, 实例数=1)
        self.assertEqual(len(分片表), 1)
        self.assertEqual(len(分片表[0]), 5)


class 启动失败清理测试(unittest.TestCase):
    def test_部分启动失败仍回收已启动实例(self) -> None:
        场景束 = 验证场景束(场景列表=[], 目标能力全集=set(), 制品摘要="摘要")
        进程 = object()
        def 启动(_启动器, _制品, 端口):
            if 端口 == 45081:
                raise RuntimeError("模拟启动失败")
            return 进程, 端口, None
        with mock.patch.object(多实例制品池, "_制品全文件摘要", return_value={"制品摘要": "摘要"}), \
             mock.patch.object(多实例制品池, "_找启动器", return_value=Path("启动.py")), \
             mock.patch.object(多实例制品池, "_启动制品", side_effect=启动), \
             mock.patch.object(多实例制品池, "_回收进程组", return_value={}) as 回收:
            with self.assertRaises(RuntimeError):
                多实例制品池._验证全部多实例(
                    Path("制品"), 场景束, 实例数=2, 端口池="45080-45081")
        回收.assert_called_once_with(进程)


if __name__ == "__main__":
    unittest.main()
