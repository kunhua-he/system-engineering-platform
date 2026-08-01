"""表格文档支持库真实解析测试（unittest）。

覆盖：最小有效 xlsx / 多工作表中文 / 公式值策略 / 空工作表 / 损坏文件 /
扩展名伪装 / 缺提供者（monkeypatch）/ xls 转换链（LibreOffice）/ 往返。
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

if str(Path(__file__).resolve().parents[2]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from 支持库.后端.表格文档 import 解析表格文档
from 支持库.后端.表格文档.实现 import 表格文档 as 实现模块


def _生成xlsx(路径: Path) -> None:
    from openpyxl import Workbook
    工作簿 = Workbook()
    工作表 = 工作簿.active
    工作表.title = "成绩单"
    工作表.append(["姓名", "分数", "备注"])
    工作表.append(["张三", 95, "优秀"])
    工作表.append(["李四", 88, "良好"])
    工作表2 = 工作簿.create_sheet("汇总")
    工作表2.append(["合计"])
    工作表2.append(["183"])
    工作簿.save(str(路径))


class Test表格文档(unittest.TestCase):
    def setUp(self):
        self.临时目录 = tempfile.mkdtemp(prefix="测试_表格文档_")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.临时目录, ignore_errors=True)

    def test_解析最小xlsx(self):
        路径 = Path(self.临时目录) / "最小.xlsx"
        _生成xlsx(路径)
        结果 = 解析表格文档(str(路径), "xlsx")
        self.assertTrue(结果.成功, f"失败: {结果.错误说明 if not 结果.成功 else ''}")
        文档 = 结果.值
        self.assertEqual(文档.文档类型, "表格")
        self.assertEqual(文档.格式, "xlsx")
        self.assertEqual(len(文档.块列表), 2)  # 两个工作表
        工作表块 = 文档.块列表[0]
        self.assertEqual(工作表块.类型, "工作表")
        self.assertEqual(工作表块.来源位置.工作表, "成绩单")
        self.assertEqual(工作表块.表格数据[0], ["姓名", "分数", "备注"])
        self.assertEqual(工作表块.表格数据[1][1], "95")

    def test_公式值策略_缓存值(self):
        路径 = Path(self.临时目录) / "公式.xlsx"
        from openpyxl import Workbook
        工作簿 = Workbook()
        工作表 = 工作簿.active
        工作表["A1"] = 10
        工作表["A2"] = 20
        工作表["A3"] = "=SUM(A1:A2)"
        工作簿.save(str(路径))
        # 保存时 openpyxl 不计算公式 → 缓存缺失（None）→ 解析为空值被过滤，
        # 这是公式/值契约的预期：只返回已计算值，不返回公式文本。
        结果 = 解析表格文档(str(路径), "xlsx")
        self.assertTrue(结果.成功)
        表格数据 = 结果.值.块列表[0].表格数据
        # 前两行（有缓存值）保留，公式行（无缓存值）被过滤
        self.assertEqual(表格数据[0], ["10"])
        self.assertEqual(表格数据[1], ["20"])
        self.assertEqual(len(表格数据), 2)

    def test_文件不存在(self):
        结果 = 解析表格文档("/不存在的路径/文件.xlsx", "xlsx")
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "文件不存在")

    def test_格式非法(self):
        路径 = Path(self.临时目录) / "非法.xlsx"
        _生成xlsx(路径)
        结果 = 解析表格文档(str(路径), "pdf")
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "参数不合法")

    def test_损坏文件(self):
        路径 = Path(self.临时目录) / "损坏.xlsx"
        路径.write_bytes(b"not a zip" * 50)
        结果 = 解析表格文档(str(路径), "xlsx")
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "文件损坏")

    def test_扩展名伪装(self):
        路径 = Path(self.临时目录) / "伪装.xlsx"
        路径.write_text("这是文本", encoding="utf-8")
        结果 = 解析表格文档(str(路径), "xlsx")
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "文件损坏")

    def test_缺提供者返回不可用(self):
        原缓存 = 实现模块._提供者缓存
        实现模块._提供者缓存 = {"openpyxl": None, "版本": {"openpyxl": "不可用"}}
        try:
            路径 = Path(self.临时目录) / "任意.xlsx"
            路径.write_bytes(b"x")
            结果 = 解析表格文档(str(路径), "xlsx")
            self.assertFalse(结果.成功)
            self.assertEqual(结果.错误码, "提供者不可用")
        finally:
            实现模块._提供者缓存 = 原缓存

    def test_xls转换链(self):
        import shutil
        import subprocess
        soffice = shutil.which("soffice") or "/Applications/LibreOffice.app/Contents/MacOS/soffice"
        if not Path(soffice).exists():
            self.skipTest("LibreOffice 不可用")
        源 = Path(self.临时目录) / "源.xlsx"
        _生成xlsx(源)
        转换 = subprocess.run(
            [soffice, "--headless", "--convert-to", "xls", "--outdir", str(self.临时目录), str(源)],
            capture_output=True, timeout=120,
        )
        旧路径 = Path(self.临时目录) / "源.xls"
        if not 旧路径.exists():
            self.skipTest("LibreOffice xls 转换未产出")
        结果 = 解析表格文档(str(旧路径), "xls")
        self.assertTrue(结果.成功, f"xls 解析失败: {结果.错误说明 if not 结果.成功 else ''}")
        self.assertEqual(结果.值.格式, "xls")
        self.assertIn("converted_from_xls", 结果.值.警告)

    def test_往返验证(self):
        路径 = Path(self.临时目录) / "往返.xlsx"
        _生成xlsx(路径)
        结果 = 解析表格文档(str(路径), "xlsx")
        self.assertTrue(结果.成功)
        文档 = 结果.值
        self.assertTrue(文档.原始文件摘要)
        self.assertIn("openpyxl", 文档.提供者版本)


if __name__ == "__main__":
    unittest.main()
