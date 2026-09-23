"""reportlab 提供者测试：真实 PDF 生成 / 中文可提取 / 段落 / 表格 / 参数不合法。

覆盖：生成产物字典（字节b64/媒体类型/摘要）、中文字体真实可提取
（用平台 PDF 解析提供者回读验证）、段落与表格渲染、参数不合法、
提供者不可用注入、注册能力与声明一致、完整性摘要与文件清单一致。

隔离形态（第 10 对收口后）：本包是「隔离子进程形态」的唯一实现 ——
主进程绝不 import reportlab，第三方库只在 实现/子进程入口.py 内加载；
后端腿 支持库/后端/文档转换支持库/PDF生成 的同名件是转调门面（同一模块对象）。
"""

from __future__ import annotations

import base64
import contextlib
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

if str(Path(__file__).resolve().parents[2]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from 公共契约.基础类型.逻辑类型 import 真, 假
from 公共契约.能力契约.契约 import 能力注册表
from 支持库.适配层.PDF隔离提供者 import 解析PDF隔离
from 支持库.适配层.reportlab提供者 import 生成PDF, 注册能力
from 支持库.适配层.reportlab提供者.实现 import 子进程管理器 as 实现模块
from 支持库.后端.文档转换支持库.PDF生成.实现 import 生成PDF as 后端腿门面
from 支持库.后端.文档转换支持库.PDF生成.实现 import 子进程入口 as 后端腿入口门面

提供者目录 = (
    Path(__file__).resolve().parents[2]
    / "支持库" / "适配层" / "reportlab提供者"
)
后端腿目录 = (
    Path(__file__).resolve().parents[2]
    / "支持库" / "后端" / "文档转换支持库" / "PDF生成"
)
# 契约声明的三项错误码（子进程超时/崩溃一律归并到 生成失败，不新增未声明错误码）
契约错误码 = ("参数不合法", "提供者不可用", "生成失败")


def _提取文本(路径: Path) -> str:
    """用平台 PDF 解析提供者提取全部文本（失败抛 AssertionError）。"""
    结果 = 解析PDF隔离(str(路径))
    if not 结果.成功:
        raise AssertionError(f"解析失败: {结果.错误说明}")
    return "".join(块.get("文本", "") for 块 in (结果.值 or {}).get("块列表", []))


class TestReportlab提供者(unittest.TestCase):
    def setUp(self):
        self.临时目录 = Path(tempfile.mkdtemp(prefix="测试_reportlab提供者_"))

    def tearDown(self):
        shutil.rmtree(self.临时目录, ignore_errors=True)

    def test_真实生成PDF产物字典(self):
        """真实生成：标题+段落+表格，校验产物字典四要素。"""
        结果 = 生成PDF({
            "标题": "报告标题",
            "段落列表": ["第一段正文"],
            "表格列表": [{"表头": ["姓名", "数量"], "行": [["张三", "1"]]}],
        })
        self.assertTrue(结果.成功, 结果.错误说明)
        产物 = 结果.值
        字节 = base64.b64decode(产物["字节b64"])
        self.assertTrue(字节.startswith(b"%PDF"))
        self.assertEqual(产物["媒体类型"], "application/pdf")
        self.assertEqual(产物["摘要"], hashlib.sha256(字节).hexdigest())
        self.assertEqual(产物["字节数"], len(字节))
        self.assertGreater(产物["字节数"], 100)
        self.assertIn("reportlab", 产物["提供者版本"])

    def test_中文可提取(self):
        """中文内容真实写入 PDF 且可被平台解析提供者提取。"""
        结果 = 生成PDF({"标题": "示例品牌", "段落列表": ["支持库报告生成测试。"]})
        self.assertTrue(结果.成功, 结果.错误说明)
        路径 = self.临时目录 / "中文.pdf"
        路径.write_bytes(base64.b64decode(结果.值["字节b64"]))
        文本 = _提取文本(路径)
        self.assertIn("示例品牌", 文本)
        self.assertIn("支持库报告生成测试", 文本)

    def test_段落渲染全部可提取(self):
        """多个段落（含加粗字典项）全部真实渲染可提取。"""
        结果 = 生成PDF({
            "段落列表": ["第一段。", "第二段。", {"文本": "加粗段。", "加粗": 真}],
        })
        self.assertTrue(结果.成功, 结果.错误说明)
        路径 = self.临时目录 / "段落.pdf"
        路径.write_bytes(base64.b64decode(结果.值["字节b64"]))
        文本 = _提取文本(路径)
        for 片段 in ("第一段。", "第二段。", "加粗段。"):
            self.assertIn(片段, 文本)

    def test_表格渲染表头与单元格可提取(self):
        """表格表头与行单元格全部真实渲染可提取。"""
        结果 = 生成PDF({
            "表格列表": [{"表头": ["名称", "数量"], "行": [["苹果", "3"], ["香蕉", "5"]]}],
        })
        self.assertTrue(结果.成功, 结果.错误说明)
        路径 = self.临时目录 / "表格.pdf"
        路径.write_bytes(base64.b64decode(结果.值["字节b64"]))
        文本 = _提取文本(路径)
        for 片段 in ("名称", "数量", "苹果", "3", "香蕉", "5"):
            self.assertIn(片段, 文本)

    def test_参数不合法(self):
        """非法参数一律返回 参数不合法。"""
        for 参数 in (
            "不是字典",
            {},
            {"段落列表": "不是列表"},
            {"标题": "x", "表格列表": "不是列表"},
            {"标题": 123},
        ):
            结果 = 生成PDF(参数)
            self.assertFalse(结果.成功, f"应失败: {参数!r}")
            self.assertEqual(结果.错误码, "参数不合法")

    def test_提供者不可用(self):
        """子进程拉不起来（依赖缺失的同口径）→ 提供者不可用（隔离形态下的不可用判据）。

        造的是**真实依赖边界故障**：`subprocess.Popen` 抛 OSError（解释器/入口起不来）。
        旧写法打桩生产自己的 `_启动子进程`（`测试伪装门禁` 规则 1 判红），
        把「怎么起进程」整段跳过，测的是一个不存在的实现。
        """
        with mock.patch("subprocess.Popen", autospec=True,
                        side_effect=OSError("模拟 reportlab 环境不可用")):
            结果 = 生成PDF({"标题": "测试"})
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "提供者不可用")
        self.assertTrue(结果.可重试, "提供者不可用必须标可重试")

    def test_主进程不加载reportlab(self):
        """隔离子进程形态判据：全新解释器只导入两腿包级入口后，主进程仍无 reportlab。"""
        代码 = "\n".join([
            "import sys",
            f"sys.path.insert(0, {str(提供者目录.parents[2])!r})",
            "import 支持库.适配层.reportlab提供者  # 适配层腿公开入口",
            "import 支持库.后端.文档转换支持库.PDF生成  # 后端腿公开入口（门面）",
            "assert 'reportlab' not in sys.modules, sorted(m for m in sys.modules if m.startswith('reportlab'))",
            "print('主进程零 reportlab')",
        ])
        运行 = subprocess.run(
            [sys.executable, "-c", 代码], capture_output=True, text=True,
            cwd=str(提供者目录.parents[2]), timeout=60,
        )
        self.assertEqual(运行.returncode, 0, 运行.stderr)
        self.assertIn("主进程零 reportlab", 运行.stdout)

    def test_子进程入口按脚本路径真跑(self):
        """按 `Popen([sys.executable, 子进程入口.py])` 那条真实路径跑一次（隔离进程真生成）。"""
        入口路径 = 提供者目录 / "实现" / "子进程入口.py"
        self.assertTrue(入口路径.is_file(), f"隔离子进程入口缺失: {入口路径}")
        请求 = json.dumps({
            "操作": "生成",
            "内容参数": {"标题": "子进程真跑", "段落列表": ["隔离进程生成。"]},
        }, ensure_ascii=False) + "\n"
        运行 = subprocess.run(
            [sys.executable, str(入口路径)],
            input=请求.encode("utf-8"), capture_output=True, timeout=120,
        )
        self.assertEqual(运行.returncode, 0, 运行.stderr.decode("utf-8", errors="replace"))
        响应 = json.loads(运行.stdout.decode("utf-8"))
        self.assertTrue(响应["成功"], 响应)
        self.assertTrue(base64.b64decode(响应["值"]["字节b64"]).startswith(b"%PDF"))

    def test_后端腿能力经注册表真调用(self):
        """后端腿（门面）能力经能力注册表真调用 —— 走隔离子进程全链路，非 import 假绿。"""
        from 支持库.后端.文档转换支持库.PDF生成 import 注册能力 as 后端腿注册

        注册表 = 能力注册表()
        后端腿注册(注册表)
        实现 = 注册表.获取("文档转换支持库.PDF生成.生成PDF")
        self.assertIsNotNone(实现)
        结果 = 实现.实现函数({"标题": "后端腿真调用", "段落列表": ["门面下仍是真实能力。"]})
        self.assertTrue(结果.成功, 结果.错误说明)
        self.assertTrue(base64.b64decode(结果.值["字节b64"]).startswith(b"%PDF"))

    def test_两腿同一模块对象_实现承载方是适配层腿(self):
        """第 10 对收口判据：后端腿两份都只是转调门面，实现承载方必须在适配层腿。"""
        for 名, 模块, 唯一实现名 in (
            ("生成PDF", 后端腿门面, "支持库.适配层.reportlab提供者.实现.子进程管理器"),
            ("子进程入口", 后端腿入口门面, "支持库.适配层.reportlab提供者.实现.子进程入口"),
        ):
            with self.subTest(模块=名):
                self.assertIs(模块, sys.modules[唯一实现名],
                              f"后端腿 {名} 与适配层唯一实现不是同一个模块对象（又分叉了）")
                self.assertEqual(模块.__name__, 唯一实现名,
                                 f"模块对象归属漂移，实现在「{模块.__name__}」而不在适配层腿")

    def test_子进程入口_自举段逐字保留(self):
        """唯一实现必须保留「激活指针解析 + 注入」自举段（丢它会 ModuleNotFoundError）。"""
        源 = (提供者目录 / "实现" / "子进程入口.py").read_text(encoding="utf-8")
        行集 = {行.strip() for 行 in 源.splitlines()}
        for 片段 in ('激活指针文件名 = "当前.json"', "def 解析平台客户端环境目录()",
                     "def 注入平台客户端路径()"):
            self.assertIn(片段, 源, f"唯一实现丢了自举段片段: {片段}")
        # 注入必须是**模块级真调用**（只有 def 没有调用 = 自举形同不存在）
        self.assertIn("注入平台客户端路径()", 行集,
                      "唯一实现丢了模块级自举调用「注入平台客户端路径()」—— 部署布局下会 ModuleNotFoundError")
        # 后端腿门面不得重复承载自举：门面只转调，且缺件即明确报错、不静默降级
        后端源 = (后端腿目录 / "实现" / "子进程入口.py").read_text(encoding="utf-8")
        self.assertIn("sys.modules[__name__] = sys.modules[唯一实现名]", 后端源)
        self.assertIn("载入唯一实现(", 后端源)

    def test_错误码归并到契约声明的三项(self):
        """子进程的未声明错误码一律归并到 生成失败；声明内的两项才透传。"""
        class _假进程:
            returncode = 0
            stdin = stdout = stderr = None

            def poll(self):
                return 0

        @contextlib.contextmanager
        def _打桩响应(子进程响应: dict):
            """桩掉隔离子进程**边界**（怎么起进程、怎么通信）；错误码归并逻辑全程真跑。

            `autospec=True` 让桩带**真实签名**：`受限通信(...)` 的参数名/形状一旦漂移，
            这里当场 TypeError 而不是静默通过 —— 旧写法给的是裸 `Mock`，签名不校验。
            """
            with mock.patch.multiple(实现模块, autospec=True,
                                     _启动子进程=mock.DEFAULT,
                                     受限通信=mock.DEFAULT) as 桩:
                桩["_启动子进程"].return_value = _假进程()
                桩["受限通信"].return_value = (
                    json.dumps(子进程响应, ensure_ascii=False).encode("utf-8"), b"", 假, 假)
                yield

        with _打桩响应({"成功": 假, "错误码": "提供者崩溃", "错误说明": "子进程崩了"}):
            结果 = 生成PDF({"标题": "子进程崩溃"})
        self.assertEqual(结果.错误码, "生成失败", "未声明的子进程错误码必须归并到 生成失败")
        self.assertIn("提供者崩溃", 结果.错误说明, "真实原因必须写进 错误说明，不许丢")
        self.assertIn(结果.错误码, 契约错误码)

        with _打桩响应({"成功": 假, "错误码": "提供者不可用", "错误说明": "reportlab 缺失"}):
            结果 = 生成PDF({"标题": "依赖缺失"})
        self.assertEqual(结果.错误码, "提供者不可用", "契约声明内的错误码必须原样透传")
        self.assertTrue(结果.可重试)

    def test_注册能力与声明一致(self):
        """注册能力可获取且与包声明能力一致（P3 唯一事实源格式）。"""
        注册表 = 能力注册表()
        注册能力(注册表)
        实现 = 注册表.获取("PDF生成.生成PDF")
        self.assertIsNotNone(实现)
        声明数据 = json.loads((提供者目录 / "包声明.json").read_text(encoding="utf-8"))
        self.assertEqual(实现.能力id, "PDF生成.生成PDF")
        self.assertIn("PDF生成.生成PDF", [能力["能力id"] for 能力 in 声明数据["能力"]])
        # 能力定义是唯一事实源：声明能力清单与能力定义一致
        定义数据 = json.loads((提供者目录 / "能力定义.json").read_text(encoding="utf-8"))
        定义能力表 = [能力["能力id"] for 能力 in 定义数据["能力列表"]]
        self.assertIn("PDF生成.生成PDF", 定义能力表)

    def test_完整性摘要一致(self):
        """完整性摘要与包声明一致（文件清单格式，门禁口径）。"""
        摘要数据 = json.loads((提供者目录 / "完整性摘要.json").read_text(encoding="utf-8"))
        self.assertEqual(摘要数据["包id"], "支持库.适配层.reportlab提供者")
        self.assertEqual(摘要数据["摘要算法"], "sha256")
        self.assertTrue(摘要数据["文件清单"], "文件清单不得为空")
        清单路径 = {项["路径"] for 项 in 摘要数据["文件清单"]}
        self.assertIn("__init__.py", 清单路径)
        self.assertIn("能力定义.json", 清单路径)


if __name__ == "__main__":
    unittest.main()
