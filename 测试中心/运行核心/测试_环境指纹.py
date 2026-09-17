"""环境指纹测试：指纹确定性/环境变化失效/证据记录往返。"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

if str(Path(__file__).resolve().parents[2]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from 运行核心.环境指纹 import (
    计算环境指纹, 生成证据记录, 读取证据环境指纹, 校验证据有效,
)
from 公共契约.基础类型.逻辑类型 import 真, 假


class Test环境指纹(unittest.TestCase):
    """环境指纹闭环测试。"""

    def test_指纹确定性(self):
        一 = 计算环境指纹(含外部应用=假)
        二 = 计算环境指纹(含外部应用=假)
        self.assertTrue(一.成功)
        self.assertEqual(一.指纹, 二.指纹)

    def test_指纹含平台信息(self):
        指纹 = 计算环境指纹(含外部应用=假)
        self.assertIn("python", 指纹.详细信息)
        self.assertIn("os", 指纹.详细信息)
        self.assertIn("架构", 指纹.详细信息)
        self.assertIn("第三方", 指纹.详细信息)

    def test_第三方版本探测(self):
        指纹 = 计算环境指纹(含外部应用=假)
        第三方 = 指纹.详细信息["第三方"]
        self.assertIn("python-docx", 第三方)
        self.assertIn("openpyxl", 第三方)

    def test_证据记录往返(self):
        临时 = Path(tempfile.mkdtemp())
        证据文件 = 临时 / "证据.json"
        生成证据记录(证据文件, {"测试": "通过"})
        记录指纹 = 读取证据环境指纹(证据文件)
        self.assertTrue(记录指纹)
        # 生成与校验使用相同参数（默认含外部应用）→ 指纹一致
        校验 = 校验证据有效(证据文件)
        self.assertTrue(校验.成功, str(校验.问题列表))

    def test_环境变化失效(self):
        """环境指纹漂移 → 证据失效。"""
        临时 = Path(tempfile.mkdtemp())
        证据文件 = 临时 / "证据.json"
        记录 = {
            "环境指纹": "旧指纹0000000000",
            "指纹详情": {"python": "旧", "os": "旧", "架构": "旧", "第三方": {}},
        }
        证据文件.write_text(json.dumps(记录, ensure_ascii=False), encoding="utf-8")
        校验 = 校验证据有效(证据文件, 含外部应用=假)
        self.assertFalse(校验.成功)
        self.assertTrue(any("环境指纹漂移" in 问题 for 问题 in 校验.问题列表))

    def test_无证据记录失效(self):
        临时 = Path(tempfile.mkdtemp())
        校验 = 校验证据有效(临时 / "不存在.json", 含外部应用=假)
        self.assertFalse(校验.成功)
        self.assertTrue(any("无证据" in 问题 for 问题 in 校验.问题列表))


if __name__ == "__main__":
    unittest.main()
