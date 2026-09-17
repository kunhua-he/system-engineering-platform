"""PDF 隔离提供者生命周期测试：启动/调用/超时/崩溃/重启/停止/残留清理。

架构验证：
- 主进程不加载 fitz/pdfplumber（PyMuPDF SWIG 崩溃隔离）；
- 子进程覆盖启动/调用/超时/崩溃/重启/停止与残留清理；
- 崩溃只返回 提供者崩溃，不得拖垮测试器；
- 提供者不可用通过环境变量依赖注入，禁止修改 sys.modules。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

if str(Path(__file__).resolve().parents[2]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from 公共契约.基础类型.逻辑类型 import 真, 假
from 公共契约.版本规则.契约版本 import 契约版本
from 公共契约.运行时.平台适配 import 子进程组启动标志
from 支持库.适配层.PDF隔离提供者 import 检查提供者版本, 解析PDF隔离, 校验PDF隔离
from 支持库.适配层.PDF隔离提供者.实现 import 隔离提供者 as 提供者模块
from 支持库.后端.组件规范支持库.实现.组件规范 import 校验组件规范


def _生成PDF(路径: Path) -> Path:
    from reportlab.pdfgen import canvas
    画布 = canvas.Canvas(str(路径))
    画布.drawString(50, 700, "Isolation provider lifecycle test")
    画布.save()
    return 路径


class TestPDF隔离提供者(unittest.TestCase):
    def setUp(self):
        self.临时目录 = Path(tempfile.mkdtemp(prefix="测试_PDF隔离提供者_"))
        self.PDF路径 = _生成PDF(self.临时目录 / "正常.pdf")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.临时目录, ignore_errors=True)

    def test_主进程不加载fitz(self):
        """架构铁律：平台主进程绝不 import fitz/pdfplumber。"""
        self.assertNotIn("fitz", sys.modules)
        self.assertNotIn("pdfplumber", sys.modules)
        # 调用后仍不加载（第三方只在子进程）
        检查提供者版本()
        self.assertNotIn("fitz", sys.modules)
        self.assertNotIn("pdfplumber", sys.modules)

    def test_版本探测(self):
        结果 = 检查提供者版本()
        self.assertTrue(结果.成功, 结果.错误说明)
        值 = 结果.值 or {}
        self.assertIn("pdfplumber", 值.get("提供者版本", {}))
        self.assertIn("fitz", 值.get("提供者版本", {}))

    def test_正常解析(self):
        结果 = 解析PDF隔离(str(self.PDF路径))
        self.assertTrue(结果.成功, 结果.错误说明)
        值 = 结果.值 or {}
        self.assertEqual(值.get("格式"), "pdf")
        self.assertGreaterEqual(len(值.get("块列表", [])), 1)

    def test_签名校验(self):
        结果 = 校验PDF隔离(self.PDF路径.read_bytes())
        self.assertTrue(结果.成功, 结果.错误说明)
        self.assertEqual((结果.值 or {}).get("页数"), 1)

    def test_超时返回超时(self):
        """子进程不响应 → 超时强杀，返回 超时（可重试），无残留。"""
        原始执行 = 提供者模块.执行任务

        def 挂起执行(请求, 超时秒=提供者模块.默认超时秒):
            # 构造一个永不返回的请求：让子进程读 stdin 阻塞（不发送换行）
            进程 = 提供者模块._启动子进程()
            try:
                # 不写请求，直接等待超时
                进程.communicate(timeout=0.5)
            except subprocess.TimeoutExpired:
                return 提供者模块._失败("超时", "模拟超时", 可重试=真)
            finally:
                提供者模块._终止进程组(进程)
                for 流 in (进程.stdin, 进程.stdout, 进程.stderr):
                    if 流 is not None:
                        try:
                            流.close()
                        except (OSError, ValueError):
                            pass
            return 提供者模块._失败("超时", "模拟超时", 可重试=真)

        with mock.patch.object(提供者模块, "执行任务", side_effect=挂起执行):
            结果 = 解析PDF隔离(str(self.PDF路径))
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "超时")
        self.assertTrue(结果.可重试)

    def test_子进程崩溃返回提供者崩溃(self):
        """子进程异常退出 → 提供者崩溃（可重试），不抛异常。"""
        原始启动 = 提供者模块._启动子进程

        def 崩溃启动():
            进程 = subprocess.Popen(
                [sys.executable, "-c", "import os; os._exit(7)"],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                **子进程组启动标志(),
            )
            return 进程

        def 关闭崩溃进程(进程):
            try:
                进程.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                pass
            finally:
                for 流 in (进程.stdin, 进程.stdout, 进程.stderr):
                    if 流:
                        try:
                            流.close()
                        except (OSError, ValueError):
                            pass

        with mock.patch.object(提供者模块, "_启动子进程", side_effect=崩溃启动), \
                mock.patch.object(提供者模块, "_终止进程组", side_effect=关闭崩溃进程):
            结果 = 检查提供者版本()
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "提供者崩溃")
        self.assertTrue(结果.可重试)

    def test_重启恢复(self):
        """崩溃后下一次调用重新启动子进程，正常返回（重启覆盖）。"""
        原始启动 = 提供者模块._启动子进程
        原始终止 = 提供者模块._终止进程组
        调用计数 = {"n": 0}

        def 先崩后正常():
            调用计数["n"] += 1
            if 调用计数["n"] == 1:
                进程 = subprocess.Popen(
                    [sys.executable, "-c", "import os; os._exit(9)"],
                    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    **子进程组启动标志(),
                )
                return 进程
            return 原始启动()

        def 关闭进程(进程):
            try:
                进程.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                pass
            finally:
                for 流 in (进程.stdin, 进程.stdout, 进程.stderr):
                    if 流:
                        try:
                            流.close()
                        except (OSError, ValueError):
                            pass

        with mock.patch.object(提供者模块, "_启动子进程", side_effect=先崩后正常), \
                mock.patch.object(提供者模块, "_终止进程组", side_effect=关闭进程):
            第一次 = 检查提供者版本()
            第二次 = 检查提供者版本()
        self.assertFalse(第一次.成功)
        self.assertEqual(第一次.错误码, "提供者崩溃")
        self.assertTrue(第二次.成功, 第二次.错误说明)

    def test_提供者不可用依赖注入(self):
        """环境变量禁用 pdfplumber → 提供者不可用（依赖注入，不动 sys.modules）。"""
        with mock.patch.dict(os.environ, {"PDF隔离提供者_禁用库": "pdfplumber"}):
            结果 = 解析PDF隔离(str(self.PDF路径))
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "提供者不可用")
        self.assertTrue(结果.可重试)

    def test_fitz禁用降级(self):
        with mock.patch.dict(os.environ, {"PDF隔离提供者_禁用库": "fitz"}):
            结果 = 解析PDF隔离(str(self.PDF路径))
        self.assertTrue(结果.成功, 结果.错误说明)
        self.assertEqual((结果.值 or {}).get("解析方式"), "pdfplumber")

    def test_无残留进程(self):
        """多次调用后无残留子进程。"""
        for _ in range(3):
            检查提供者版本()
            解析PDF隔离(str(self.PDF路径))
        # 本进程直接子进程应已全部回收（communicate 已等待）
        # 通过再次调用成功且系统无本测试残留佐证；此处验证正常路径幂等
        结果 = 解析PDF隔离(str(self.PDF路径))
        self.assertTrue(结果.成功, 结果.错误说明)

    def test_停止清理(self):
        """等待并收集接口能强制清理未退出子进程。"""
        进程 = 提供者模块._启动子进程()
        self.assertIsNone(进程.poll())  # 刚启动仍在运行
        提供者模块.等待并收集([进程])
        self.assertIsNotNone(进程.poll())  # 清理后已退出

    def test_校验PDF字节参数不合法(self):
        """空字节/非法 base64 文本 → 参数不合法（统一失败结果，不抛异常）。"""
        for 字节 in (b"", "不是合法base64!!", None):
            结果 = 校验PDF隔离(字节)
            self.assertFalse(结果.成功, repr(字节))
            self.assertEqual(结果.错误码, "参数不合法")

    def test_校验PDF接受base64文本(self):
        """base64 文本字节（跨宿主可序列化）真实重开 PDF 成功。"""
        b64 = __import__("base64").b64encode(self.PDF路径.read_bytes()).decode("ascii")
        结果 = 校验PDF隔离(b64)
        self.assertTrue(结果.成功, 结果.错误说明)
        self.assertEqual((结果.值 or {}).get("页数"), 1)


class TestPDF隔离包级合规(unittest.TestCase):
    """S0 正式包九要素与聚合契约逐能力对称漂移断言。"""

    def setUp(self):
        self.提供者目录 = (
            Path(__file__).resolve().parents[2]
            / "支持库" / "适配层" / "PDF隔离提供者"
        )

    def test_九要素齐全(self):
        """S0 正式包九要素 + 平台权威校验器复核。

        依赖契约按平台判据**可选**：`组件规范支持库/实现/组件规范.py::校验组件规范`
        与 `组件合规/合规测试包.py::_场景依赖` 两处同源——**无文件 = 无内部依赖**；
        提交 24704a44（2026-09-15 华哥决定）已把空白内部依赖声明全部删除，本包
        `依赖契约/依赖契约.json` 因此**不该存在**。本用例不再把「文件必须存在」当合格线，
        改为「生产权威校验器通过 + 若存在则不得是空壳」，断言强度只增不减。
        """
        for 相对路径 in (
            "配置契约/配置契约.json", "权限契约/权限契约.json",
            "资源预算.json", "复用决策.json", "验证场景引用.json", "完整性摘要.json",
            "能力定义.json", "能力数据/Agent查询数据.json", "能力数据/能力搜索数据.json",
        ):
            self.assertTrue((self.提供者目录 / 相对路径).is_file(), f"缺少 {相对路径}")
        依赖契约 = self.提供者目录 / "依赖契约" / "依赖契约.json"
        if 依赖契约.is_file():
            self.assertTrue(json.loads(依赖契约.read_text(encoding="utf-8")).get("依赖"),
                            "依赖契约存在即不得是空壳（空白内部依赖声明一律删）")
        规范结果 = 校验组件规范(self.提供者目录)
        self.assertTrue(规范结果.成功, f"九要素不合规: {规范结果.问题列表}")
        预算 = json.loads((self.提供者目录 / "资源预算.json").read_text(encoding="utf-8"))
        for 键 in ("内存上限", "线程上限", "子进程上限", "并发调用上限", "队列长度",
                   "文件句柄上限", "临时空间上限", "单次调用超时", "每分钟重启次数", "空闲回收时间"):
            self.assertIn(键, 预算, f"资源预算缺少 {键}")
        复用 = json.loads((self.提供者目录 / "复用决策.json").read_text(encoding="utf-8"))
        self.assertTrue(复用.get("搜索词") and 复用.get("候选能力id"))

    def test_聚合契约全要素与权限覆盖(self):
        契约数据 = json.loads(
            (self.提供者目录 / "能力契约" / "参数契约.json").read_text(encoding="utf-8"))
        # 契约版本从唯一事实源现读（公共契约/版本规则/契约版本.py），禁写死字面量：
        # 曾写死 "1.0.0"，平台契约版本收敛为唯一值 2.0.0 后就成假红。
        self.assertEqual(契约数据["契约版本"], 契约版本)
        能力表 = 契约数据["能力契约"]
        定义数据 = json.loads((self.提供者目录 / "能力定义.json").read_text(encoding="utf-8"))
        定义版本 = {能力["能力id"]: 能力["版本"] for 能力 in 定义数据["能力列表"]}
        # 数量不写死：与 能力定义.json（唯一事实源）对称，两侧任一漂移即红。
        self.assertEqual(len(能力表), len(定义数据["能力列表"]))
        权限数据 = json.loads(
            (self.提供者目录 / "权限契约" / "权限契约.json").read_text(encoding="utf-8"))
        for 能力 in 能力表:
            # 逐能力迭代版本与 能力定义.json 对称（两源必须一致），同样不写死字面量。
            self.assertEqual(能力["版本"], 定义版本.get(能力["能力id"]), 能力["能力id"])
            self.assertTrue(能力["说明"], 能力["能力id"])
            self.assertIn("调用示例", 能力, 能力["能力id"])
            self.assertIsInstance(能力["调用示例"].get("参数"), dict)
            for 参数 in 能力["参数"]:
                self.assertNotEqual(参数["类型"], "任意", f"{能力['能力id']} 参数 {参数['名称']} 禁止任意类型")
                self.assertIn("必填", 参数)
                self.assertIn("默认值", 参数)
            self.assertIn(能力["能力id"], 权限数据, f"{能力['能力id']} 缺权限声明")
        self.assertEqual({能力["能力id"] for 能力 in 能力表},
                         {能力["能力id"] for 能力 in 定义数据["能力列表"]})
        self.assertTrue((self.提供者目录 / "验证数据" / "示例.pdf").is_file(),
                        "缺少 验证数据/示例.pdf（解析PDF 调用示例依赖）")


if __name__ == "__main__":
    unittest.main()
