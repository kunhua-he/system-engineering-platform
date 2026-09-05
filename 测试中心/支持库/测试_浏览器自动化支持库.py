"""浏览器自动化支持库 B1 契约回归。"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

系统根 = Path(__file__).resolve().parents[2]
if str(系统根) not in sys.path:
    sys.path.insert(0, str(系统根))

包目录 = 系统根 / "支持库" / "后端" / "浏览器自动化支持库"
能力id表 = {
    "浏览器自动化.创建会话",
    "浏览器自动化.导航页面",
    "浏览器自动化.读取页面",
    "浏览器自动化.页面操作",
    "浏览器自动化.获取截图",
    "浏览器自动化.关闭会话",
}


class 测试浏览器自动化支持库契约(unittest.TestCase):
    def test_包级入口注册六项公开能力(self) -> None:
        from 支持库.后端.浏览器自动化支持库 import 注册能力

        class 注册表:
            def __init__(self) -> None:
                self.能力表 = []

            def 注册(self, 能力) -> None:
                self.能力表.append(能力)

        表 = 注册表()
        注册能力(表)
        self.assertEqual({能力.能力id for 能力 in 表.能力表}, 能力id表)

    def test_契约文件声明六项公开能力(self) -> None:
        数据 = json.loads(
            (包目录 / "能力定义.json").read_text(encoding="utf-8")
        )
        self.assertEqual(
            {能力["能力id"] for 能力 in 数据["能力列表"]},
            能力id表,
        )

    def test_有状态能力的首参数必须是句柄(self) -> None:
        数据 = json.loads(
            (包目录 / "能力契约" / "参数契约.json").read_text(encoding="utf-8")
        )
        for 能力 in 数据["能力契约"]:
            if 能力["能力id"] in {"浏览器自动化.创建会话"}:
                continue
            self.assertEqual(能力["参数"][0]["名称"], "句柄")
            self.assertEqual(能力["参数"][0]["类型"], "整数型")

    def test_包入口不暴露Provider实现对象(self) -> None:
        from 支持库.后端 import 浏览器自动化支持库

        self.assertFalse(hasattr(浏览器自动化支持库, "浏览器自动化提供者"))
        self.assertTrue(callable(浏览器自动化支持库.注册能力))


if __name__ == "__main__":
    unittest.main(verbosity=2)
