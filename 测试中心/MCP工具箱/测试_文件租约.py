"""文件级占用租约：批量互斥申请、全成功才开工、心跳续租、过期回收与按所有者释放。

测试全程使用临时隔离存储目录（不复用真实 工程缓存/平台控制面/权威状态.db）。
"""

from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path

from MCP工具箱.文件租约 import (
    申请文件租约, 续租文件租约, 释放文件租约, 释放工作包文件租约,
    回收过期文件租约, 查询文件占用, 归一化路径, 文件键,
)
from 平台控制面.平台状态 import 平台状态


class 文件租约测试(unittest.TestCase):
    def setUp(self) -> None:
        self._临时 = tempfile.TemporaryDirectory()
        self.存储目录 = Path(self._临时.name) / "平台控制面"

    def tearDown(self) -> None:
        self._临时.cleanup()

    def _改心跳(self, 键: str, 心跳: float) -> None:
        状态 = 平台状态(self.存储目录, 项目id="平台控制面")
        状态.条件更新("占用租约", {"心跳": 心跳}, "能力id=?", (键,))

    def test_申请成功与同文件互斥(self) -> None:
        首次 = 申请文件租约(self.存储目录, ["支持库/甲.py", "支持库/乙.py"],
                            所有者="aaaa000000000001", 任务="甲包改造")
        self.assertTrue(首次["成功"])
        self.assertEqual(首次["数量"], 2)
        self.assertEqual([项["文件路径"] for 项 in 首次["租约"]],
                         ["支持库/甲.py", "支持库/乙.py"])

        冲突 = 申请文件租约(self.存储目录, ["支持库/甲.py"],
                            所有者="bbbb000000000002", 任务="乙包改造")
        self.assertFalse(冲突["成功"])
        self.assertEqual(冲突["错误码"], "FILE_LEASE_CONFLICT")
        self.assertEqual(冲突["文件路径"], "支持库/甲.py")
        self.assertEqual(冲突["占用者"], "aaaa000000000001")

    def test_批量全成功才开工且失败回滚(self) -> None:
        占用 = 申请文件租约(self.存储目录, ["支持库/已有.py"], 所有者="aaaa000000000001")
        self.assertTrue(占用["成功"])

        结果 = 申请文件租约(
            self.存储目录, ["支持库/新一.py", "支持库/已有.py"], 所有者="bbbb000000000002",
        )
        self.assertFalse(结果["成功"])
        self.assertEqual(结果["文件路径"], "支持库/已有.py")
        # 同一批里先申请成功的"支持库/新一.py"必须被回滚，可被他人重新认领。
        self.assertEqual(结果["已回滚"], ["支持库/新一.py"])
        再申请 = 申请文件租约(self.存储目录, ["支持库/新一.py"], 所有者="cccc000000000003")
        self.assertTrue(再申请["成功"], "失败批次里已成功的租约应已回滚释放")

    def test_释放后可被重新认领(self) -> None:
        首次 = 申请文件租约(self.存储目录, ["契约/丙.json"], 所有者="aaaa000000000001")
        租约id = 首次["租约"][0]["租约id"]
        释放 = 释放文件租约(self.存储目录, [租约id], 证据="测试释放")
        self.assertTrue(释放["成功"])
        再申请 = 申请文件租约(self.存储目录, ["契约/丙.json"], 所有者="bbbb000000000002")
        self.assertTrue(再申请["成功"])

    def test_续租刷新心跳(self) -> None:
        首次 = 申请文件租约(self.存储目录, ["源码/丁.py"], 所有者="aaaa000000000001")
        租约id = 首次["租约"][0]["租约id"]
        键 = 文件键("源码/丁.py")
        self._改心跳(键, time.time() - 1000)
        续租 = 续租文件租约(self.存储目录, [租约id])
        self.assertTrue(续租["成功"])
        占用 = 查询文件占用(self.存储目录, ["源码/丁.py"])["占用"][0]
        self.assertLess(占用["空闲秒"], 5.0)

    def test_过期回收后可接管(self) -> None:
        首次 = 申请文件租约(self.存储目录, ["源码/戊.py"], 所有者="aaaa000000000001")
        self.assertTrue(首次["成功"])
        键 = 文件键("源码/戊.py")
        self._改心跳(键, time.time() - 1000)

        冲突 = 申请文件租约(self.存储目录, ["源码/戊.py"], 所有者="bbbb000000000002")
        self.assertTrue(冲突["成功"], "申请时会先回收过期占用，过期后应可接管")
        self.assertEqual(查询文件占用(self.存储目录, ["源码/戊.py"])["占用"][0]["所有者"],
                         "bbbb000000000002")

    def test_回收过期不误伤新鲜租约(self) -> None:
        申请文件租约(self.存储目录, ["源码/己.py"], 所有者="aaaa000000000001")
        回收 = 回收过期文件租约(self.存储目录)
        self.assertEqual(回收["回收数量"], 0)
        self.assertEqual(查询文件占用(self.存储目录)["数量"], 1)

    def test_查询只返回文件领域且可按路径过滤(self) -> None:
        申请文件租约(self.存储目录, ["支持库/庚.py"], 所有者="aaaa000000000001")
        # 伪造一条能力租约（领域不同），必须不被"查询文件占用"混入。
        状态 = 平台状态(self.存储目录, 项目id="平台控制面")
        状态.原子插入("占用租约", {
            "租约id": "cap0000000000001", "能力id": "数据操作支持库.数据集合.展平", "领域": "数据操作",
            "契约指纹": "", "任务": "能力占用", "所有者": "aaaa000000000001",
            "心跳": time.time(), "过期时间": time.time() + 3000, "释放证据": "", "状态": "活跃",
        })
        全部 = 查询文件占用(self.存储目录)
        self.assertEqual(全部["数量"], 1)
        self.assertEqual(全部["占用"][0]["文件路径"], "支持库/庚.py")
        过滤空 = 查询文件占用(self.存储目录, ["源码/不存在.py"])
        self.assertEqual(过滤空["数量"], 0)

    def test_按所有者释放工作包租约(self) -> None:
        申请文件租约(self.存储目录, ["A/一.py", "A/二.py"], 所有者="aaaa000000000001")
        申请文件租约(self.存储目录, ["B/三.py"], 所有者="bbbb000000000002")
        释放 = 释放工作包文件租约(self.存储目录, "aaaa000000000001", 证据="收口")
        self.assertEqual(释放["释放数量"], 2)
        剩余 = 查询文件占用(self.存储目录)
        self.assertEqual([项["文件路径"] for 项 in 剩余["占用"]], ["B/三.py"])

    def test_路径归一化(self) -> None:
        self.assertEqual(归一化路径("./支持库/甲.py"), "支持库/甲.py")
        self.assertEqual(归一化路径("支持库\\甲.py"), "支持库/甲.py")
        self.assertEqual(归一化路径("/支持库/甲.py/"), "支持库/甲.py")
        with self.assertRaises(ValueError):
            归一化路径("   ")
        self.assertEqual(文件键("./a.py"), "文件::a.py")

    def test_空所有者与空路径(self) -> None:
        拒绝 = 申请文件租约(self.存储目录, ["a.py"], 所有者="  ")
        self.assertFalse(拒绝["成功"])
        self.assertEqual(拒绝["错误码"], "参数无效")
        空 = 申请文件租约(self.存储目录, [], 所有者="aaaa000000000001")
        self.assertTrue(空["成功"])
        self.assertEqual(空["数量"], 0)


if __name__ == "__main__":
    unittest.main()
