"""开发入口 发布相关函数的回归覆盖（MCP 层收敛到 开发工具/发布门禁/发布治理 之后补）。

覆盖口径：
1. `查看验证状态` 没有正式发布证据时必须**如实返回失败**，不得凭空造"通过"；
2. `执行发布检查` 透传退出码与发布状态；只有「退出码 0 且 发布状态=通过」才算成功；
3. 命令桩退出码 0 但**没有状态行**时必须失败（防假绿），状态与退出码矛盾时也必须失败。
"""

from __future__ import annotations

import pathlib
import sys
import tempfile
import unittest

系统根 = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(系统根))

from 开发工具 import 开发入口

解释器 = sys.executable


def _命令(代码: str) -> list[str]:
    return [解释器, "-B", "-c", 代码]


class 开发入口发布检查测试(unittest.TestCase):
    def test_查看验证状态_无证据必须如实失败(self) -> None:
        with tempfile.TemporaryDirectory() as 临时:
            状态 = 开发入口.查看验证状态(证据目录参数=临时)
        self.assertFalse(状态["成功"], "空证据目录不得判为通过")
        self.assertTrue(状态["错误码"], "失败必须带错误码")
        self.assertNotIn("通过", str(状态.get("说明", ""))[:12])

    def test_执行发布检查_状态通过且退出码零判成功(self) -> None:
        结果 = 开发入口.执行发布检查(
            命令列表=_命令("print('发布状态: 通过')"))
        self.assertTrue(结果["成功"], 结果)
        self.assertEqual(结果["退出码"], 0)
        self.assertEqual(结果["发布状态"], "通过")

    def test_执行发布检查_状态失败必须判失败(self) -> None:
        结果 = 开发入口.执行发布检查(
            命令列表=_命令("print('发布状态: 失败')"))
        self.assertFalse(结果["成功"])
        self.assertEqual(结果["发布状态"], "失败")

    def test_执行发布检查_退出码零但无状态行必须判失败(self) -> None:
        结果 = 开发入口.执行发布检查(
            命令列表=_命令("print('一切正常')"))
        self.assertFalse(结果["成功"], "没有明确状态不得靠退出码充当通过")
        self.assertEqual(结果["发布状态"], "未知")

    def test_执行发布检查_退出码非零但状态写通过必须判失败(self) -> None:
        结果 = 开发入口.执行发布检查(
            命令列表=_命令("print('发布状态: 通过'); raise SystemExit(1)"))
        self.assertFalse(结果["成功"], "退出码非 0 时状态行不得单独成立")
        self.assertEqual(结果["退出码"], 1)


if __name__ == "__main__":
    unittest.main()
