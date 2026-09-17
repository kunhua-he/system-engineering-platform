"""安全审计 JSONL 有界读取与持久化测试。"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from 运行核心.运行诊断.安全审计.安全审计 import 安全审计
from 公共契约.基础类型.逻辑类型 import 真, 假


class 安全审计有界测试(unittest.TestCase):
    def test_查询最多返回指定记录数且取最近记录(self) -> None:
        with tempfile.TemporaryDirectory() as 临时目录:
            审计 = 安全审计(Path(临时目录))
            for 索引 in range(25):
                审计.记录(操作=f"操作{索引}", 成功=真)
            结果 = 审计.查询(最大记录数=5)
            self.assertEqual(len(结果), 5)
            self.assertEqual([项["操作"] for 项 in 结果], [f"操作{i}" for i in range(20, 25)])

    def test_查询默认有界且写入可回读(self) -> None:
        with tempfile.TemporaryDirectory() as 临时目录:
            审计 = 安全审计(Path(临时目录))
            审计id = 审计.记录(操作="读取", 项目id="项目1", 用户id="用户1")
            self.assertTrue(审计id)
            结果 = 审计.查询(项目id="项目1", 用户id="用户1")
            self.assertEqual(len(结果), 1)
            self.assertEqual(结果[0]["审计id"], 审计id)


if __name__ == "__main__":
    unittest.main()
