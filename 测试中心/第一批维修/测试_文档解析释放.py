"""P1-14：旧格式文档解析必须以资源释放结果作为最终门禁。"""

from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

if str(Path(__file__).resolve().parents[2]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from 公共契约.基础类型.结果类型 import 结果
from 模块库.文档解析.实现 import 文档解析 as 文档解析实现


class Test文档解析释放(unittest.TestCase):
    def setUp(self) -> None:
        self.临时根 = Path(tempfile.mkdtemp(prefix="测试_文档解析释放_"))
        文档解析实现.释放诊断.clear()

    def tearDown(self) -> None:
        shutil.rmtree(self.临时根, ignore_errors=True)
        文档解析实现.释放诊断.clear()

    def _运行旧格式解析(self, 主结果: 结果, 释放动作) -> 结果:
        运行目录 = self.临时根 / "运行目录"
        运行目录.mkdir()
        输出路径 = 运行目录 / "转换后.docx"

        def 调用支持库(能力id: str, 参数: dict, **_关键字参数) -> 结果:
            if 能力id.endswith("创建唯一运行目录"):
                return 结果.成功结果(str(运行目录))
            if 能力id.endswith("转换办公文件"):
                return 结果.成功结果({"输出路径": str(输出路径)})
            if 能力id.endswith("解析文字文档"):
                return 主结果
            if 能力id.endswith("安全释放"):
                return 释放动作(运行目录)
            raise AssertionError(f"未预期能力调用: {能力id}")

        with mock.patch.object(文档解析实现, "_调用支持库", side_effect=调用支持库):
            return 文档解析实现._解析旧格式("/输入/旧文档.doc", "doc", "docx")

    def test_解析成功但释放异常失败返回或目录残留均阻断成功(self) -> None:
        成功解析 = 结果.成功结果({"格式": "docx", "块列表": []})

        def 抛出异常(运行目录: Path) -> 结果:
            shutil.rmtree(运行目录)
            raise RuntimeError("释放调用异常")

        def 返回失败(运行目录: Path) -> 结果:
            shutil.rmtree(运行目录)
            return 结果.失败("释放器失败", "释放器明确返回失败")

        def 目录残留(_运行目录: Path) -> 结果:
            return 结果.成功结果(True)

        for 名称, 释放动作 in (
            ("释放调用抛异常", 抛出异常),
            ("释放调用返回失败", 返回失败),
            ("释放返回成功但目录仍存在", 目录残留),
        ):
            with self.subTest(名称=名称):
                输出 = self._运行旧格式解析(成功解析, 释放动作)
                self.assertFalse(输出.成功)
                self.assertEqual(输出.错误码, "资源释放失败")
                self.assertIn("释放", 输出.错误说明)
                self.assertTrue(输出.详细信息)
                self.assertLessEqual(len(文档解析实现.释放诊断), 100)

    def test_解析失败且释放失败时释放失败优先并保留原主错误(self) -> None:
        原主结果 = 结果.失败(
            "转换失败", "原解析失败", 来源="文档解析", 详情={"阶段": "解析转换结果"},
        )

        def 返回失败(运行目录: Path) -> 结果:
            shutil.rmtree(运行目录)
            return 结果.失败("释放器失败", "释放器明确返回失败")

        输出 = self._运行旧格式解析(原主结果, 返回失败)

        self.assertFalse(输出.成功)
        self.assertEqual(输出.错误码, "资源释放失败")
        self.assertEqual(输出.详细信息["原主错误"]["错误码"], "转换失败")
        self.assertEqual(输出.详细信息["原主错误"]["错误说明"], "原解析失败")
        self.assertEqual(
            输出.详细信息["原主错误"]["详细信息"], {"阶段": "解析转换结果"},
        )

    def test_释放成功且目录消失时保留解析成功结果(self) -> None:
        成功解析 = 结果.成功结果({"格式": "docx", "块列表": []})

        def 释放成功(运行目录: Path) -> 结果:
            shutil.rmtree(运行目录)
            return 结果.成功结果(True)

        输出 = self._运行旧格式解析(成功解析, 释放成功)

        self.assertTrue(输出.成功)
        self.assertIs(输出, 成功解析)
        self.assertEqual(list(文档解析实现.释放诊断), [])


if __name__ == "__main__":
    unittest.main()
