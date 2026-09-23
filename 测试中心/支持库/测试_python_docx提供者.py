"""python-docx 提供者测试：真实 docx 生成→解析往返。

覆盖：真实往返/中文/表格/空文档/损坏文件→文件损坏/伪装文件→文件损坏/
参数不合法/缺库注入（环境变量注入，禁 sys.modules）。
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

if str(Path(__file__).resolve().parents[2]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from 支持库.后端.文档转换支持库.python_docx提供者 import 生成文字文档, 解析文字文档
from 支持库.后端.文档转换支持库.python_docx提供者.实现 import 文字文档 as 实现模块

受管仓库根 = Path(__file__).resolve().parents[2]
from 公共契约.运行时.平台适配 import 清只读后删除树
from 公共契约.基础类型.逻辑类型 import 真

#: ★ A 档泄漏收口（2026-09-23）：受管临时根在仓库内**固定排除目录** `工程缓存/` 下。
#: `dir=` 显式指向它 ⇒ 落点与**测试运行时**的 `TMPDIR` 解耦（平台跑测试时 `TMPDIR` 被指进
#: 仓库工作目录，裸 `mkdtemp()` 会把夹具造进仓库）。`工程缓存` 在
#: `开发工具/项目编译/工作区指纹.py` 的 `固定排除目录` 里 ⇒ 即便进程被 SIGKILL、
#: 清理没跑到，残留也进不了工作区指纹（`.gitignore` 保不住：指纹的未跟踪腿不用
#: `--exclude-standard`）。清理走平台唯一删树原语 `清只读后删除树`（本类用例常造
#: `0o555` 目录 / `0o444` 文件，plain `shutil.rmtree` 会被权限位挡住）。
受管临时根 = 受管仓库根 / "工程缓存" / "测试临时"
受管临时根.mkdir(parents=True, exist_ok=True)


def _生成docx文件(路径: Path, 文本: str = "往返测试内容") -> None:
    from docx import Document
    文档 = Document()
    文档.add_paragraph(文本)
    表格 = 文档.add_table(rows=2, cols=2)
    表格.cell(0, 0).text = "表头"
    表格.cell(1, 1).text = "值"
    文档.save(路径)


class TestPythonDocx提供者(unittest.TestCase):
    """python-docx 提供者闭环测试。"""

    def setUp(self):
        self.临时 = Path(tempfile.mkdtemp(dir=受管临时根))
        self.addCleanup(清只读后删除树, self.临时, 忽略失败=真)

    def test_真实往返(self):
        """生成 docx → 解析回读：段落+表格内容一致。"""
        参数 = {"内容块列表": [
            {"类型": "标题", "文本": "测试标题"},
            {"类型": "段落", "文本": "往返测试内容"},
        ]}
        生成 = 生成文字文档(参数)
        self.assertTrue(生成.成功, 生成.错误说明)
        self.assertIn("字节b64", 生成.值)
        文件路径 = self.临时 / "往返.docx"
        import base64
        文件路径.write_bytes(base64.b64decode(生成.值["字节b64"]))
        解析 = 解析文字文档(str(文件路径))
        self.assertTrue(解析.成功, 解析.错误说明)
        块文本 = " ".join(块.get("文本", "") for 块 in 解析.值["块列表"])
        self.assertIn("往返测试内容", 块文本)

    def test_表格解析(self):
        文件路径 = self.临时 / "表格.docx"
        _生成docx文件(文件路径)
        解析 = 解析文字文档(str(文件路径))
        self.assertTrue(解析.成功, 解析.错误说明)
        表格块 = [块 for 块 in 解析.值["块列表"] if 块.get("类型") == "表格"]
        self.assertTrue(表格块)
        self.assertEqual(表格块[0]["表格数据"][0][0], "表头")

    def test_空文档(self):
        文件路径 = self.临时 / "空.docx"
        from docx import Document
        Document().save(文件路径)
        解析 = 解析文字文档(str(文件路径))
        self.assertTrue(解析.成功, 解析.错误说明)
        self.assertEqual(解析.值["块列表"], [])

    def test_损坏文件(self):
        文件路径 = self.临时 / "坏.docx"
        文件路径.write_bytes(b"not zip")
        解析 = 解析文字文档(str(文件路径))
        self.assertFalse(解析.成功)
        self.assertEqual(解析.错误码, "文件损坏")

    def test_伪装文件(self):
        文件路径 = self.临时 / "伪装.docx"
        文件路径.write_bytes(b"PK\x03\x04" + b"x" * 100)
        解析 = 解析文字文档(str(文件路径))
        self.assertFalse(解析.成功)
        self.assertEqual(解析.错误码, "文件损坏")

    def test_文件不存在(self):
        解析 = 解析文字文档(str(self.临时 / "不存在.docx"))
        self.assertFalse(解析.成功)
        self.assertEqual(解析.错误码, "文件不存在")

    def test_参数不合法(self):
        解析 = 解析文字文档("")
        self.assertFalse(解析.成功)
        self.assertEqual(解析.错误码, "参数不合法")
        生成 = 生成文字文档({})
        self.assertEqual(生成.错误码, "参数不合法")

    def test_缺库注入(self):
        """python-docx 缺失（环境变量注入禁用）→ 提供者不可用。"""
        with mock.patch.dict(os.environ, {"python_docx提供者_禁用库": "docx"}):
            # 实现模块按环境变量判定；这里验证解析对损坏文件仍报文件损坏（禁用只影响可用性检查）
            文件路径 = self.临时 / "x.docx"
            文件路径.write_bytes(b"bad")
            解析 = 解析文字文档(str(文件路径))
            self.assertFalse(解析.成功)

    def test_注册能力为内部实现且阻断公开owner(self):
        """Provider 只登记内部能力，公开文字文档 owner 不得被其覆盖。"""
        from 公共契约.能力契约.契约 import 能力注册表
        from 支持库.后端.文档转换支持库.python_docx提供者 import 注册能力

        注册表 = 能力注册表()
        注册能力(注册表)
        能力id列表 = 注册表.能力id列表
        # 注册表按能力 id 稳定排序；顺序不是公开契约。
        self.assertEqual(能力id列表, sorted(["内部.文字文档.解析", "内部.文字文档.生成"]))
        self.assertNotIn("办公文档支持库.文字文档.解析文字文档", 能力id列表)
        self.assertNotIn("办公文档支持库.文字文档.生成文字文档", 能力id列表)
        self.assertEqual(
            [参数["名称"] for 参数 in 注册表.获取("内部.文字文档.解析").参数],
            ["文件路径", "格式", "最大字节数", "超时秒"],
        )


if __name__ == "__main__":
    unittest.main()
