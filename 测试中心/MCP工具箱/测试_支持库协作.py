"""支持库协作工具集真实测试：临时目录写工程缓存，复用搜索扫描真实支持库。"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

if str(Path(__file__).resolve().parents[2]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from MCP工具箱.支持库协作 import (
    登记需求,
    复用搜索,
    参数不合法,
)


class 支持库协作测试(unittest.TestCase):
    def setUp(self) -> None:
        self._临时 = tempfile.TemporaryDirectory()
        self.工程缓存根 = Path(self._临时.name)
        self.项目根 = Path(__file__).resolve().parents[2]

    def tearDown(self) -> None:
        self._临时.cleanup()
        self.assertFalse(self.工程缓存根.exists())

    def test_登记需求写入快照并可读取(self) -> None:
        结果 = 登记需求(self.工程缓存根, 能力id="PDF渲染.检测加密页数",
                       说明="支持库新增 PDF 渲染能力",
                       来源任务="阶段26-工作包1", work_id="4efa32325b5b4d25",
                       项目根=self.项目根)
        self.assertTrue(结果["成功"], 结果)
        快照 = 结果["值"]
        self.assertIn("需求id", 快照)
        self.assertEqual(快照["能力id"], "PDF渲染.检测加密页数")
        self.assertEqual(快照["确认状态"], "未确认")
        self.assertIn("复用平台控制面需求登记语义", 快照["复用决策"])
        文件 = Path(快照["文件"])
        self.assertTrue(文件.is_file())
        磁盘 = json.loads(文件.read_text(encoding="utf-8"))
        self.assertEqual(磁盘["需求id"], 快照["需求id"])
        self.assertEqual(磁盘["版本"], "1")
        self.assertEqual(磁盘["来源任务"], "阶段26-工作包1")
        self.assertEqual(磁盘["确认状态"], "未确认")

    def test_登记需求参数不合法(self) -> None:
        空说明 = 登记需求(self.工程缓存根, 能力id="能力1", 说明="",
                        来源任务="任务1", work_id="work-a")
        self.assertFalse(空说明["成功"])
        self.assertEqual(空说明["错误码"], 参数不合法)
        穿越 = 登记需求(self.工程缓存根, 能力id="能力1", 说明="说明",
                       来源任务="任务1", work_id="../逃逸")
        self.assertFalse(穿越["成功"])
        self.assertEqual(穿越["错误码"], 参数不合法)

    def test_复用搜索真实扫描命中已有能力(self) -> None:
        图像 = 复用搜索(self.项目根, "图像")
        self.assertTrue(图像["成功"], 图像)
        self.assertEqual(图像["值"]["状态"], "已存在可复用")
        self.assertTrue(any("图像解码.解码图像" == 项["能力id"] for 项 in 图像["值"]["候选"]))
        PDF = 复用搜索(self.项目根, "PDF")
        self.assertTrue(PDF["成功"])
        self.assertEqual(PDF["值"]["状态"], "已存在可复用")
        self.assertTrue(any(项["能力id"].startswith("PDF渲染.") for 项 in PDF["值"]["候选"]))
        签名 = 复用搜索(self.项目根, "签名")
        self.assertTrue(签名["成功"])
        self.assertEqual(签名["值"]["状态"], "已存在可复用")
        self.assertTrue(any("密码签名.签名" == 项["能力id"] for 项 in 签名["值"]["候选"]))

    def test_复用搜索无现成标记(self) -> None:
        结果 = 复用搜索(self.项目根, "不存在的关键词xyz")
        self.assertTrue(结果["成功"], 结果)
        self.assertEqual(结果["值"]["状态"], "无现成")
        self.assertEqual(结果["值"]["候选"], [])

    def test_复用搜索参数不合法(self) -> None:
        结果 = 复用搜索(self.项目根, "  ")
        self.assertFalse(结果["成功"])
        self.assertEqual(结果["错误码"], 参数不合法)

    def test_零残留无临时文件(self) -> None:
        登记需求(self.工程缓存根, 能力id="能力1", 说明="说明",
                来源任务="任务1", work_id="work-a")
        残留 = sorted(self.工程缓存根.rglob("*.tmp"))
        self.assertEqual(残留, [])
        需求文件 = self.工程缓存根 / "需求登记" / "work-a.json"
        磁盘 = json.loads(需求文件.read_text(encoding="utf-8"))
        self.assertEqual(磁盘["能力id"], "能力1")


if __name__ == "__main__":
    unittest.main()
