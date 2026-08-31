"""记忆支持库契约与统一调用边界测试。"""
from __future__ import annotations

import json
import unittest
from pathlib import Path
from unittest.mock import patch

from 公共契约.基础类型.结果类型 import 结果
from 支持库.后端.记忆支持库.实现 import 记忆


class 假调用器:
    def __init__(self) -> None:
        self.调用记录: list[tuple[str, dict]] = []

    def 调用能力(self, 能力id: str, 参数: dict, **_) -> 结果:
        self.调用记录.append((能力id, dict(参数)))
        if 能力id.endswith("连接向量模型"):
            return 结果.成功结果({"句柄": 123456})
        if 能力id.endswith("生成嵌入"):
            return 结果.成功结果({"向量": [0.1, 0.2, 0.3], "维度": 3})
        if 能力id.endswith("释放句柄"):
            return 结果.成功结果({"句柄": 123456, "状态": "已结束并已释放"})
        return 结果.失败("能力不存在", 能力id)


class 测试记忆支持库(unittest.TestCase):
    根目录 = Path(__file__).resolve().parents[2]
    包目录 = 根目录 / "支持库" / "后端" / "记忆支持库"

    def test_生成向量只经统一调用器并释放句柄(self) -> None:
        调用器 = 假调用器()
        with patch("公共契约.能力契约.调用器.获取能力调用器", return_value=调用器):
            向量 = 记忆._生成向量("测试文本")
        self.assertEqual(向量, [0.1, 0.2, 0.3])
        self.assertEqual(
            [记录[0] for 记录 in 调用器.调用记录],
            [
                "大语言模型支持库.模型连接器.连接向量模型",
                "大语言模型支持库.模型连接器.生成嵌入",
                "大语言模型支持库.模型连接器.释放句柄",
            ],
        )
        self.assertEqual(调用器.调用记录[1][1]["句柄"], 123456)
        self.assertEqual(调用器.调用记录[2][1]["句柄"], 123456)

    def test_包依赖声明覆盖向量连接生成和释放(self) -> None:
        声明 = json.loads((self.包目录 / "包声明.json").read_text(encoding="utf-8"))
        依赖契约 = json.loads(
            (self.包目录 / "依赖契约" / "依赖契约.json").read_text(encoding="utf-8")
        )
        预期 = {
            "大语言模型支持库.模型连接器.连接向量模型",
            "大语言模型支持库.模型连接器.生成嵌入",
            "大语言模型支持库.模型连接器.释放句柄",
        }
        self.assertEqual({项目["能力"] for 项目 in 声明["依赖"]}, 预期)
        self.assertEqual({项目["能力"] for 项目 in 依赖契约["依赖"]}, 预期)

    def test_写能力副作用不是只读(self) -> None:
        定义 = json.loads((self.包目录 / "能力定义.json").read_text(encoding="utf-8"))
        写能力 = {"写入记忆", "追加记忆", "完成记忆", "删除记忆"}
        for 能力 in 定义["能力列表"]:
            if 能力["中文名称"] in 写能力:
                self.assertNotEqual(能力["行为"]["副作用"], "只读")


if __name__ == "__main__":
    unittest.main()
