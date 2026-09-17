"""pdfplumber 提供者测试：真实 PDF 文本/表格解析 + 加密/损坏/超时/禁用语义。

pdfplumber 为纯 Python 库主进程导入；环境可用时走真实解析成功链；
禁用环境变量/缺库 → 提供者不可用（如实标记，不伪装成功）。
"""
from __future__ import annotations

import base64
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

if str(Path(__file__).resolve().parents[2]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from 支持库.适配层.pdfplumber提供者 import 解析PDF, 提取表格


def _生成文本PDF(路径: Path, 页数: int = 2) -> Path:
    from reportlab.pdfgen import canvas
    画布 = canvas.Canvas(str(路径))
    for 页 in range(页数):
        画布.drawString(50, 700, f"pdfplumber 提供者测试 第{页 + 1}页")
        画布.showPage()
    画布.save()
    return 路径


def _生成表格PDF(路径: Path) -> Path:
    from reportlab.lib import colors
    from reportlab.pdfgen import canvas
    from reportlab.platypus import Table
    from reportlab.platypus.tableofcontents import TableStyle
    画布 = canvas.Canvas(str(路径))
    表 = Table([["姓名", "数量"], ["张三", "1"], ["李四", "2"]])
    表.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.5, colors.black)]))
    表.wrapOn(画布, 300, 100)
    表.drawOn(画布, 72, 650)
    画布.save()
    return 路径


def _生成加密PDF(路径: Path) -> Path:
    """子进程内 fitz 生成带密码 PDF（测试进程仍不加载 fitz）。"""
    代码 = ("import fitz;d=fitz.open();d.new_page();"
            f"d.save({str(路径)!r}, encryption=fitz.PDF_ENCRYPT_AES_256, owner_pw='o', user_pw='u')")
    subprocess.run([sys.executable, "-c", 代码], check=True, capture_output=True)
    return 路径


class Testpdfplumber提供者(unittest.TestCase):
    def setUp(self):
        self.临时目录 = Path(tempfile.mkdtemp(prefix="测试_pdfplumber提供者_"))
        self.文本PDF = _生成文本PDF(self.临时目录 / "文本.pdf")
        self.表格PDF = _生成表格PDF(self.临时目录 / "表格.pdf")

    def tearDown(self):
        shutil.rmtree(self.临时目录, ignore_errors=True)

    def test_解析PDF真实成功链(self):
        """真实 PDF 解析成功：文本块/标题/页数上限/提供者版本齐全。"""
        结果 = 解析PDF(str(self.文本PDF))
        self.assertTrue(结果.成功, 结果.错误说明)
        值 = 结果.值
        self.assertEqual(值["文档类型"], "PDF")
        self.assertTrue(值["块列表"], "文本 PDF 必须解析出块")
        self.assertTrue(all(块["类型"] in ("段落", "表格") for 块 in 值["块列表"]))
        self.assertIn("pdfplumber", 值["提供者版本"])
        self.assertTrue(值["原始文件摘要"])

    def test_解析PDF表格页真实成功(self):
        结果 = 解析PDF(str(self.表格PDF))
        self.assertTrue(结果.成功, 结果.错误说明)
        self.assertTrue(any(块["类型"] == "表格" for 块 in 结果.值["块列表"]))

    def test_提取表格成功(self):
        结果 = 提取表格(str(self.文本PDF), 1)
        self.assertTrue(结果.成功, 结果.错误说明)

    def test_提取表格页序号越界返回空列表(self):
        结果 = 提取表格(str(self.文本PDF), 9)
        self.assertTrue(结果.成功)
        self.assertEqual(结果.值, [])

    def test_解析PDF文件不存在(self):
        结果 = 解析PDF(str(self.临时目录 / "不存在.pdf"))
        self.assertEqual(结果.错误码, "文件不存在")

    def test_解析PDF参数不合法(self):
        self.assertEqual(解析PDF("").错误码, "参数不合法")
        self.assertEqual(解析PDF(str(self.文本PDF), 最大页数=-1).错误码, "参数不合法")
        self.assertEqual(解析PDF(str(self.文本PDF), 最大字节数=-1).错误码, "参数不合法")
        self.assertEqual(解析PDF(str(self.文本PDF), 超时秒="快").错误码, "参数不合法")

    def test_解析PDF加密文件返回文件加密(self):
        加密PDF = _生成加密PDF(self.临时目录 / "加密.pdf")
        结果 = 解析PDF(str(加密PDF))
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "文件加密")

    def test_解析PDF页数超限返回超出限制(self):
        结果 = 解析PDF(str(self.文本PDF), 最大页数=1)
        self.assertEqual(结果.错误码, "超出限制")

    def test_解析PDF文件大小超限(self):
        结果 = 解析PDF(str(self.文本PDF), 最大字节数=10)
        self.assertEqual(结果.错误码, "超出限制")

    def test_解析PDF损坏返回文件损坏(self):
        损坏 = self.临时目录 / "损坏.pdf"
        损坏.write_bytes(b"%PDF-1.4\n%%EOF broken-fragment")
        结果 = 解析PDF(str(损坏))
        self.assertEqual(结果.错误码, "文件损坏")

    def test_提供者禁用返回提供者不可用(self):
        with mock.patch.dict(sys.modules, {"pdfplumber": None}), \
                mock.patch.dict("os.environ", {"pdfplumber提供者_禁用库": "pdfplumber"}), \
                mock.patch("支持库.适配层.pdfplumber提供者.实现.PDF文本表格._提供者缓存", None):
            结果 = 解析PDF(str(self.文本PDF))
        self.assertEqual(结果.错误码, "提供者不可用")
        self.assertTrue(结果.可重试)

    def test_解析超时返回超时可重试(self):
        """工作线程 join 强约束：解析超过 超时秒 → 超时（可重试）。"""
        def 挂起解析(pdfplumber模块, 路径, 最大页数):
            import time
            time.sleep(30)
            return {"块列表": []}
        with mock.patch("支持库.适配层.pdfplumber提供者.实现.PDF文本表格._解析为字典", side_effect=挂起解析):
            结果 = 解析PDF(str(self.文本PDF), 超时秒=0.2)
        self.assertEqual(结果.错误码, "超时")
        self.assertTrue(结果.可重试)

    # ── 反向验证 ①：非法超时值必须明确报错，不得穿透 ──────────────────
    def test_超时值非法一律参数不合法(self):
        """NaN/inf/0/负数/超 TIMEOUT_MAX/超大整数/布尔/文本 → 参数不合法（不抛异常）。

        旧写法只判类型：`0` 与负数被 join 的 `max(值, 0.0)` 抹平后静默返回「超时」
        （把无效配置说成任务超时）；`inf`/`1e10`/`1e300` 让 `Thread.join()` 抛
        `OverflowError` 穿透错误边界；`10**400` 在 `float()` 那步就抛。
        """
        import threading as _线程
        import math as _数学
        非法表 = [
            ("NaN", float("nan")), ("正无穷", float("inf")), ("负无穷", float("-inf")),
            ("零", 0), ("零浮点", 0.0), ("负一", -1), ("负小数", -0.5),
            ("布尔真", True), ("布尔假", False), ("空值", None), ("文本", "60"),
            ("字节", b"60"), ("列表", []),
            ("超 TIMEOUT_MAX", _线程.TIMEOUT_MAX * 2),
            ("1e10", 1e10), ("1e300", 1e300), ("超大整数", 10 ** 400),
        ]
        for 名, 值 in 非法表:
            with self.subTest(超时值=名):
                try:
                    结果 = 解析PDF(str(self.文本PDF), 超时秒=值)
                except BaseException as 错误:  # noqa: BLE001 —— 穿透即失败
                    self.fail(f"{名} 让异常穿透错误边界: {type(错误).__name__}: {错误}")
                self.assertFalse(结果.成功, f"{名} 不应被接受")
                self.assertEqual(结果.错误码, "参数不合法", f"{名} 的错误码不对")
        self.assertTrue(_数学.isfinite(_线程.TIMEOUT_MAX))

    def test_超时值合法边界真解析成功(self):
        """合法超时值（含 TIMEOUT_MAX 边界）不得被误判为非法。"""
        import threading as _线程
        for 值 in (60.0, 1, 0.5, float(_线程.TIMEOUT_MAX)):
            结果 = 解析PDF(str(self.文本PDF), 超时秒=值)
            self.assertTrue(结果.成功, f"超时秒={值} 应解析成功，实得 {结果.错误码}")

    # ── 反向验证 ②：超时后线程数回到基线（进程真线程取证） ────────────
    def test_超时后线程数回到基线(self):
        """挂起解析触发超时 → 收尾等待内收敛，进程真线程数回到基线、登记清空。

        取证按 `threading.enumerate()`（进程真线程），不是「代码看起来回收了」：
        基线取调用前的线程集合，收敛后要求集合回到基线且本次调用的线程名从登记里消失。
        解析体内**没有**取消检测点（最坏形态），故用循环等待收敛而不是断言立即归零。
        断言按**本次调用自己的**线程名收口，不假设登记表里只有自己——同包其他用例
        （如 30 秒挂起那条）可能仍占着槽位，那不是本次调用的残留。
        """
        import threading as _线程
        import time as _时间
        from 支持库.适配层.pdfplumber提供者.实现 import PDF文本表格 as 模块
        基线总数 = _线程.active_count()
        基线集合 = set(_线程.enumerate())
        基线登记名 = set(模块.取消登记摘要()["在册线程名"])

        def 挂起解析(pdfplumber模块, 路径, 最大页数):
            _时间.sleep(2.0)
            return {"块列表": []}

        with mock.patch("支持库.适配层.pdfplumber提供者.实现.PDF文本表格._解析为字典",
                        side_effect=挂起解析):
            结果 = 解析PDF(str(self.文本PDF), 超时秒=0.1)
        self.assertEqual(结果.错误码, "超时")
        详情 = 结果.详细信息 or {}
        self.assertIn("线程", 详情)
        self.assertIn("进程真线程", 详情)
        self.assertEqual(详情["进程真线程"]["视图"],
                         "threading.enumerate()（进程真线程，含不由本包登记的线程）")
        本次线程名 = 详情["线程"]["线程名"]
        self.assertNotIn(本次线程名, 基线登记名, "本次调用的线程名不应预先在册")
        # 超时时点如实登记了终态（本形态线程不可强杀，不假装回收）
        self.assertIn(详情["线程"]["终态"], ("已退出（协作取消在收尾等待内收敛）",
                                         "仍在运行（不可强杀，如实登记，不假装回收）"))
        截止 = _时间.monotonic() + 10.0
        残留 = None
        while _时间.monotonic() < 截止:
            残留 = 模块.取消登记摘要()
            if 本次线程名 not in 残留["在册线程名"] and _线程.active_count() <= 基线总数:
                break
            _时间.sleep(0.1)
        self.assertNotIn(本次线程名, 模块.取消登记摘要()["在册线程名"],
                         "超时后本次调用的解析线程仍留在登记里")
        self.assertEqual(_线程.active_count(), 基线总数, "进程真线程数未回到基线")
        新增 = [线程.name for 线程 in _线程.enumerate() if 线程 not in 基线集合]
        self.assertEqual(新增, [], f"超时后仍有新增线程残留: {新增}")
        # 真线程视图与取消登记视图口径一致；本次调用的线程既不在册也不该算「未登记」
        快照 = 模块.真线程快照()
        登记 = 模块.取消登记摘要()
        self.assertEqual(快照["在册解析线程数"], 登记["存活条数"],
                         "真线程视图与取消登记视图对本包线程的口径不一致")
        self.assertNotIn(本次线程名, 快照["未登记线程名"],
                         "本包自己的解析线程不该被算进「未登记线程」")
        self.assertEqual(快照["上限"], 模块.取消登记上限)
        # 无其他在册线程时（空闲口径）：进程真线程未超预算 —— 「回到基线」是可读事实
        if 快照["在册解析线程数"] == 0:
            self.assertEqual(快照["判定口径"], f"空闲期间：进程真线程 {快照['进程线程数']} "
                                           f"对上上限 {快照['上限']}")
            self.assertFalse(快照["超预算"], f"空闲期间仍报超预算: {快照}")

    def test_真线程快照暴露未登记线程(self):
        """解析库自身起的线程不被 取消登记摘要 记名，但必须被 真线程快照 暴露。

        这是「线程有界」的取证缺口：`取消登记上限` 只约束本包登记的工作线程，
        库内部线程不受它约束。若只读自己的登记表，会把「线程无界」谎报成「有界」。
        """
        import threading as _线程
        from 支持库.适配层.pdfplumber提供者.实现 import PDF文本表格 as 模块
        库内线程名 = "替身解析库内部线程"
        放行 = _线程.Event()
        已起 = _线程.Event()

        def 库内长线程():
            已起.set()
            放行.wait(10.0)

        class 替身页面:
            def extract_text(self):
                线程 = _线程.Thread(target=库内长线程, daemon=True, name=库内线程名)
                import time as _替身时间
                线程.start()
                已起.wait(5.0)
                _替身时间.sleep(0.4)
                return "替身文本"

        class 替身文档:
            pages = [替身页面()]

            def close(self):
                pass

        class 替身库:
            __version__ = "替身"

            @staticmethod
            def open(路径):
                return 替身文档()

        原缓存 = 模块._提供者缓存
        模块._提供者缓存 = {"pdfplumber": 替身库, "版本": {"pdfplumber": "替身"}}
        try:
            结果 = 解析PDF(str(self.文本PDF), 超时秒=0.05)
            self.assertEqual(结果.错误码, "超时")
            登记 = 模块.取消登记摘要()
            self.assertEqual(登记["存活条数"], 0,
                             "库内部线程不应被记进本包取消登记表")
            快照 = 模块.真线程快照()
            self.assertIn(库内线程名, 快照["未登记线程名"],
                          "库内部线程必须被真线程视图暴露，不能只登记本包线程")
            self.assertGreaterEqual(快照["未登记线程数"], 1)
        finally:
            放行.set()
            模块._提供者缓存 = 原缓存

    def test_公开入口返回统一结果(self):
        """公开入口只返回 结果 对象；不泄漏 pdfplumber 对象/句柄。"""
        结果 = 解析PDF(str(self.文本PDF))
        self.assertTrue(hasattr(结果, "成功"))
        self.assertFalse(hasattr(结果, "pdf"))
        self.assertFalse(hasattr(结果, "open"))

    # ── 反向验证 ③：正常路径返回结构与错误码不变 ──────────────────────
    def test_正常路径返回结构不变(self):
        """正常解析：成功、顶层键集合与来源字段与修复前逐项一致。"""
        结果 = 解析PDF(str(self.文本PDF))
        self.assertTrue(结果.成功, 结果.错误说明)
        assert isinstance(结果.值, dict)
        值 = 结果.值
        self.assertEqual(sorted(值), sorted([
            "文档类型", "格式", "标题", "块列表", "资源列表", "保真级别", "解析方式",
            "警告", "诊断", "耗时秒", "提供者版本", "原始文件摘要", "附加",
        ]))
        self.assertEqual(值["文档类型"], "PDF")
        self.assertEqual(值["格式"], "pdf")
        self.assertEqual(值["解析方式"], "pdfplumber")
        self.assertEqual(值["保真级别"], "高")
        self.assertEqual(值["资源列表"], [])
        self.assertIsInstance(值["块列表"], list)
        for 块 in 值["块列表"]:
            self.assertEqual(sorted(块), sorted(["类型", "文本", "来源位置", "资源引用", "附加"]))
        # 错误码契约集未变：成功链错误码为空
        self.assertEqual(结果.错误码, "")


if __name__ == "__main__":
    unittest.main()
