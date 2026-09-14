"""底座运行库回归：七个域表初始化、写入查询闭环、并发写入、参数口径。

华哥定盘（`开发文档/临时文档/57_底座收口总清单_审计.md` 第四节）：运行态一律入库，
库文件统一放 `工程缓存/运行数据/`，且一律经唯一 SQLite 支持库访问（禁止各包自己连库）。

本测试只碰临时目录里的库文件，不写仓库内任何数据。
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

if str(Path(__file__).resolve().parents[2]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from 支持库.后端.数据库连接支持库.SQLite数据库 import (
    初始化运行数据库, 写入运行态, 查询运行态,
)

七个域 = ["任务", "作业", "协作状态", "能力占用", "检查点索引", "会话", "缓存索引"]


def 取成功值(用例: unittest.TestCase, 结果对象: Any) -> dict[str, Any]:
    """断言调用成功并取回字典型值（值可能为 None，必须先断言再取）。"""
    用例.assertTrue(结果对象.成功, 结果对象.错误说明)
    值 = 结果对象.值
    用例.assertIsInstance(值, dict)
    return dict(值)


class 运行数据库回归(unittest.TestCase):
    def setUp(self):
        self.临时目录 = tempfile.TemporaryDirectory()
        self.库路径 = str(Path(self.临时目录.name) / "底座运行.db")

    def tearDown(self):
        self.临时目录.cleanup()

    def test_初始化建出七个域表且幂等(self):
        第一次 = 取成功值(self, 初始化运行数据库(self.库路径))
        self.assertEqual(sorted(第一次["表清单"]), sorted(七个域))
        第二次 = 取成功值(self, 初始化运行数据库(self.库路径))
        self.assertEqual(sorted(第二次["表清单"]), sorted(七个域), "重复初始化必须幂等")

    def test_写入后可按域查询(self):
        初始化运行数据库(self.库路径)
        写入 = 取成功值(self, 写入运行态(self.库路径, "任务", {
            "任务id": "任务-1", "能力id": "直播逐字稿.全自动精校", "请求id": "请求-1",
            "状态": "运行中",
        }))
        self.assertTrue(写入["已写入"])
        self.assertEqual(写入["域"], "任务")
        查询 = 取成功值(self, 查询运行态(self.库路径, "任务", 限制=10))
        self.assertEqual(查询["总数"], 1)
        行列表 = 查询["行列表"]
        self.assertIsInstance(行列表, list)
        self.assertEqual(行列表[0]["状态"], "运行中")
        self.assertIn("任务-1", json.dumps(行列表[0], ensure_ascii=False))

    def test_未知域报参数不合法(self):
        初始化运行数据库(self.库路径)
        写入 = 写入运行态(self.库路径, "不存在的域", {"x": 1})
        self.assertFalse(写入.成功)
        self.assertEqual(写入.错误码, "参数不合法")
        self.assertIn("域必须是", 写入.错误说明)
        查询 = 查询运行态(self.库路径, "不存在的域")
        self.assertFalse(查询.成功)
        self.assertEqual(查询.错误码, "参数不合法")

    def test_空路径报参数不合法(self):
        初始化 = 初始化运行数据库("")
        self.assertFalse(初始化.成功)
        self.assertEqual(初始化.错误码, "参数不合法")
        写入 = 写入运行态(self.库路径, "任务", {})
        self.assertFalse(写入.成功)
        self.assertEqual(写入.错误码, "参数不合法")

    def test_并发写入不丢记录(self):
        初始化运行数据库(self.库路径)

        def 写(序号: int) -> bool:
            return 写入运行态(self.库路径, "作业", {
                "作业id": f"作业-{序号}", "工具": "run_release_gate", "状态": "运行中",
            }).成功

        with ThreadPoolExecutor(max_workers=8) as 池:
            结果 = list(池.map(写, range(12)))
        self.assertTrue(all(结果), "并发写入不得有失败")
        查询 = 取成功值(self, 查询运行态(self.库路径, "作业", 限制=50))
        self.assertEqual(查询["总数"], 12, "并发写入不得丢记录")

    def test_运行库不落仓库内(self):
        """库文件由调用方显式给定路径；本测试用的必须是临时目录。"""
        self.assertTrue(self.库路径.startswith(tempfile.gettempdir()))


if __name__ == "__main__":
    unittest.main()
