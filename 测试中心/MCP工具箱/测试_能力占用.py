"""能力级占用租约：同能力原子互斥、同包幂等、心跳续租、过期回收与按开工id释放。

测试全程使用临时隔离存储目录（不复用真实 工程缓存/平台控制面/权威状态.db）。
"""

from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path

from MCP工具箱.能力占用 import (
    申请能力占用, 续租能力占用, 释放能力占用, 释放开工id能力占用,
    回收过期能力占用, 查询能力占用, 能力键,
    参数不合法, 占用冲突,
)
from 平台控制面.平台状态 import 平台状态


class 能力占用测试(unittest.TestCase):
    def setUp(self) -> None:
        self._临时 = tempfile.TemporaryDirectory()
        self.存储目录 = Path(self._临时.name) / "平台控制面"

    def tearDown(self) -> None:
        self._临时.cleanup()

    def _改心跳(self, 键: str, 心跳: float) -> None:
        状态 = 平台状态(self.存储目录, 项目id="平台控制面")
        状态.条件更新("占用租约", {"心跳": 心跳}, "能力id=?", (键,))

    def test_申请成功与同能力互斥(self) -> None:
        首次 = 申请能力占用(self.存储目录, 能力id="图像解码.解码图像",
                          提供包id="支持库.适配层.Pillow提供者", 开工id="work-a")
        self.assertTrue(首次["成功"], 首次)
        self.assertFalse(首次["值"]["幂等"])
        self.assertEqual(首次["值"]["能力id"], "图像解码.解码图像")
        self.assertTrue(首次["值"]["租约id"])

        异包 = 申请能力占用(self.存储目录, 能力id="图像解码.解码图像",
                          提供包id="支持库.后端.图像处理", 开工id="work-c")
        self.assertFalse(异包["成功"])
        self.assertEqual(异包["错误码"], 占用冲突)
        self.assertEqual(异包["值"]["现有占用"]["提供包id"], "支持库.适配层.Pillow提供者")

    def test_同包重复占用幂等(self) -> None:
        首次 = 申请能力占用(self.存储目录, 能力id="PDF渲染.检测加密页数",
                          提供包id="支持库.后端.PDF渲染", 开工id="work-a")
        self.assertTrue(首次["成功"], 首次)
        同包 = 申请能力占用(self.存储目录, 能力id="PDF渲染.检测加密页数",
                          提供包id="支持库.后端.PDF渲染", 开工id="work-b")
        self.assertTrue(同包["成功"], 同包)
        self.assertTrue(同包["值"]["幂等"])
        self.assertEqual(同包["值"]["租约id"], 首次["值"]["租约id"])
        self.assertEqual(查询能力占用(self.存储目录)["数量"], 1)

    def test_参数不合法(self) -> None:
        空能力 = 申请能力占用(self.存储目录, 能力id="",
                          提供包id="包甲", 开工id="work-a")
        self.assertFalse(空能力["成功"])
        self.assertEqual(空能力["错误码"], 参数不合法)
        空包 = 申请能力占用(self.存储目录, 能力id="能力甲", 提供包id="  ", 开工id="work-a")
        self.assertEqual(空包["错误码"], 参数不合法)
        空开工 = 申请能力占用(self.存储目录, 能力id="能力甲", 提供包id="包甲", 开工id="")
        self.assertEqual(空开工["错误码"], 参数不合法)
        with self.assertRaises(ValueError):
            能力键("坏 id")

    def test_释放后可被重新认领(self) -> None:
        首次 = 申请能力占用(self.存储目录, 能力id="密码签名.签名",
                          提供包id="支持库.后端.密码签名", 开工id="work-a")
        租约id = 首次["值"]["租约id"]
        释放 = 释放能力占用(self.存储目录, [租约id], 证据="测试释放")
        self.assertTrue(释放["成功"])
        再申请 = 申请能力占用(self.存储目录, 能力id="密码签名.签名",
                          提供包id="支持库.后端.密码签名乙", 开工id="work-b")
        self.assertTrue(再申请["成功"], "释放后应可被其他包重新认领")
        self.assertFalse(再申请["值"]["幂等"])

    def test_续租刷新心跳(self) -> None:
        首次 = 申请能力占用(self.存储目录, 能力id="数据操作.展平",
                          提供包id="支持库.后端.数据操作", 开工id="work-a")
        租约id = 首次["值"]["租约id"]
        self._改心跳(能力键("数据操作.展平"), time.time() - 1000)
        续租 = 续租能力占用(self.存储目录, [租约id])
        self.assertTrue(续租["成功"])
        占用 = 查询能力占用(self.存储目录, ["数据操作.展平"])["占用"][0]
        self.assertLess(占用["空闲秒"], 5.0)

    def test_过期回收后可接管(self) -> None:
        首次 = 申请能力占用(self.存储目录, 能力id="表格.解析单元格地址",
                          提供包id="支持库.后端.办公文档", 开工id="work-a")
        self.assertTrue(首次["成功"])
        self._改心跳(能力键("表格.解析单元格地址"), time.time() - 1000)

        接管 = 申请能力占用(self.存储目录, 能力id="表格.解析单元格地址",
                          提供包id="支持库.后端.办公文档乙", 开工id="work-b")
        self.assertTrue(接管["成功"], "申请时会先回收过期占用，过期后应可接管")
        self.assertEqual(查询能力占用(self.存储目录, ["表格.解析单元格地址"])["占用"][0]["提供包id"],
                         "支持库.后端.办公文档乙")

    def test_回收过期不误伤新鲜租约(self) -> None:
        申请能力占用(self.存储目录, 能力id="图像解码.解码图像",
                   提供包id="支持库.适配层.Pillow提供者", 开工id="work-a")
        回收 = 回收过期能力占用(self.存储目录)
        self.assertEqual(回收["回收数量"], 0)
        self.assertEqual(查询能力占用(self.存储目录)["数量"], 1)

    def test_查询只返回能力领域且可按能力id过滤(self) -> None:
        申请能力占用(self.存储目录, 能力id="图像解码.解码图像",
                   提供包id="支持库.适配层.Pillow提供者", 开工id="work-a")
        # 伪造一条文件租约（领域不同），必须不被"查询能力占用"混入。
        状态 = 平台状态(self.存储目录, 项目id="平台控制面")
        状态.原子插入("占用租约", {
            "租约id": "file000000000001", "能力id": "文件::支持库/甲.py", "领域": "文件",
            "契约指纹": "", "任务": "文件占用", "所有者": "aaaa000000000001",
            "心跳": time.time(), "过期时间": time.time() + 3000, "释放证据": "", "状态": "活跃",
        })
        全部 = 查询能力占用(self.存储目录)
        self.assertEqual(全部["数量"], 1)
        self.assertEqual(全部["占用"][0]["能力id"], "图像解码.解码图像")
        过滤空 = 查询能力占用(self.存储目录, ["源码/不存在.py"])
        self.assertEqual(过滤空["数量"], 0)

    def test_按开工id释放(self) -> None:
        申请能力占用(self.存储目录, 能力id="数据操作.展平",
                   提供包id="支持库.后端.数据操作", 开工id="work-a")
        申请能力占用(self.存储目录, 能力id="数据操作.分组",
                   提供包id="支持库.后端.数据操作", 开工id="work-a")
        申请能力占用(self.存储目录, 能力id="图像解码.解码图像",
                   提供包id="支持库.适配层.Pillow提供者", 开工id="work-b")
        释放 = 释放开工id能力占用(self.存储目录, "work-a", 证据="收口：work-a")
        self.assertEqual(释放["释放数量"], 2)
        剩余 = 查询能力占用(self.存储目录)
        self.assertEqual([项["能力id"] for 项 in 剩余["占用"]], ["图像解码.解码图像"])

    def test_开工id为空时跳过(self) -> None:
        结果 = 释放开工id能力占用(self.存储目录, "  ", 证据="收口")
        self.assertTrue(结果["成功"])
        self.assertEqual(结果["释放数量"], 0)

    def test_查询无占用返回空(self) -> None:
        结果 = 查询能力占用(self.存储目录)
        self.assertTrue(结果["成功"])
        self.assertEqual(结果["数量"], 0)
        self.assertEqual(结果["占用"], [])


if __name__ == "__main__":
    unittest.main()
