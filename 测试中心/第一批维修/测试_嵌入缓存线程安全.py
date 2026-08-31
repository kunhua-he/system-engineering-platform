"""嵌入缓存 SQLite 并发访问回归。"""
from __future__ import annotations

import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from 支持库.后端.大语言模型支持库.嵌入缓存 import 查询嵌入, 存储嵌入


class 嵌入缓存并发测试(unittest.TestCase):
    def test_同一受管数据库允许并发读写且返回统一结果(self) -> None:
        with tempfile.TemporaryDirectory(prefix="嵌入缓存并发_") as 临时:
            数据库 = str(Path(临时) / "缓存.sqlite3")

            def 写入(序号: int):
                return 存储嵌入(
                    文本=f"文本{序号}", 向量=[序号 / 10], 模型名="测试模型",
                    提供者="测试提供者", 数据库路径=数据库)

            with ThreadPoolExecutor(max_workers=8) as 并发池:
                写入结果 = list(并发池.map(写入, range(8)))
            self.assertTrue(all(结果.成功 for 结果 in 写入结果), 写入结果)

            def 查询(序号: int):
                return 查询嵌入(
                    文本=f"文本{序号}", 模型名="测试模型",
                    提供者="测试提供者", 数据库路径=数据库)

            with ThreadPoolExecutor(max_workers=8) as 并发池:
                查询结果 = list(并发池.map(查询, range(8)))
            self.assertTrue(all(结果.成功 for 结果 in 查询结果), 查询结果)
            self.assertTrue(all((结果.值 or {}).get("命中") for 结果 in 查询结果))


if __name__ == "__main__":
    unittest.main(verbosity=2)
