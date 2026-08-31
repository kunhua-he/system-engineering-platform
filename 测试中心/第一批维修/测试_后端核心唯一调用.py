"""后端核心只能委托唯一能力调用服务，不能自建执行路径。"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

根 = Path(__file__).resolve().parents[2]
if str(根) not in sys.path:
    sys.path.insert(0, str(根))

from 公共契约.基础类型.结果类型 import 结果
from 后端核心.后端核心 import 后端核心


class 假唯一调用服务:
    def __init__(self) -> None:
        self.调用记录: list[tuple[str, dict]] = []

    def 调用能力(self, 能力id: str, 参数: dict, **关键字) -> 结果:
        self.调用记录.append((能力id, dict(参数)))
        return 结果.成功结果({"来自": "唯一能力调用服务", "能力id": 能力id})


class 测试后端核心唯一调用(unittest.TestCase):
    def test_调用委托唯一能力调用服务(self) -> None:
        with tempfile.TemporaryDirectory(prefix="后端唯一调用_") as 临时:
            后端 = 后端核心(Path(临时))
            后端.状态.状态 = "运行中"
            假服务 = 假唯一调用服务()
            后端._唯一调用服务 = 假服务

            def 不允许直接执行(**_):
                raise AssertionError("后端核心不得直接执行注册表实现")

            后端.注册能力(
                "测试.不可直达", 不允许直接执行,
            )
            try:
                返回 = 后端.调用("测试.不可直达", {"参数": 1})
                self.assertTrue(返回.成功)
                self.assertEqual(返回.值["来自"], "唯一能力调用服务")
                self.assertEqual(假服务.调用记录, [("测试.不可直达", {"参数": 1})])
            finally:
                后端.资源句柄服务.关闭服务()


if __name__ == "__main__":
    unittest.main()
