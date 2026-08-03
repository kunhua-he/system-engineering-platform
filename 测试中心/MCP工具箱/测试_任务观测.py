"""MCP任务观测的时间线、聚合和失败隔离测试。"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from MCP工具箱.任务观测 import 查询任务, 任务开始, 任务结束, 工具事件


class 任务观测测试(unittest.TestCase):
    def test_任务时间线可查询并聚合(self) -> None:
        with tempfile.TemporaryDirectory() as 临时目录:
            路径 = Path(临时目录) / "事件.jsonl"
            任务开始(路径, 任务id="任务甲", 开工id="开工甲", 角色="平台维护者")
            工具事件(路径, 任务id="任务甲", 开工id="开工甲", 工具="代码地图", 开始单调=0)
            任务结束(路径, 任务id="任务甲", 开工id="开工甲", 成功=True)
            结果 = 查询任务(路径, "任务甲")
            self.assertTrue(结果["成功"])
            self.assertEqual(结果["工具调用数"], 1)
            self.assertEqual(结果["失败工具数"], 0)

    def test_任务之间隔离(self) -> None:
        with tempfile.TemporaryDirectory() as 临时目录:
            路径 = Path(临时目录) / "事件.jsonl"
            任务开始(路径, 任务id="任务甲", 开工id="开工甲", 角色="平台维护者")
            结果 = 查询任务(路径, "任务乙")
            self.assertFalse(结果["成功"])
            self.assertEqual(结果["错误码"], "OBSERVATION_NOT_FOUND")


if __name__ == "__main__":
    unittest.main()
