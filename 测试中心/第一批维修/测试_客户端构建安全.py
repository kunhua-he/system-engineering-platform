"""P0-17/P1-24：平台客户端构建失败即阻断与路径边界回归测试。"""
from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

系统根 = Path(__file__).resolve().parents[2]
if str(系统根) not in sys.path:
    sys.path.insert(0, str(系统根))

from 客户端 import 构建平台客户端 as 构建模块


class 测试客户端构建安全(unittest.TestCase):
    def setUp(self) -> None:
        self.临时根 = Path(tempfile.mkdtemp(prefix="客户端构建安全_"))
        self.源根 = self.临时根 / "源码"
        self.目标根 = self.临时根 / "目标"
        self.源根.mkdir()
        self.目标根.mkdir()

    def tearDown(self) -> None:
        shutil.rmtree(self.临时根, ignore_errors=True)

    def 断言失败含路径(
        self, 调用, 路径: Path, 异常类型: type[BaseException] = RuntimeError
    ) -> str:
        with self.assertRaises(异常类型) as 捕获:
            调用()
        消息 = str(捕获.exception)
        self.assertIn(str(路径), 消息)
        return 消息

    def test_坏语法报告文件与行号且不复制原源码(self) -> None:
        坏文件 = self.源根 / "坏语法.py"
        坏文件.write_text("def 坏函数(:\n    pass\n", encoding="utf-8")

        消息 = self.断言失败含路径(
            lambda: 构建模块.复制并重写(self.源根, self.目标根), 坏文件)

        self.assertIn(":1", 消息)
        self.assertFalse((self.目标根 / "坏语法.py").exists())

    def test_反解析失败报告文件与行号且不复制原源码(self) -> None:
        源文件 = self.源根 / "反解析失败.py"
        源文件.write_text("值 = 1\n", encoding="utf-8")

        with mock.patch.object(构建模块.ast, "unparse", side_effect=RuntimeError("模拟反解析失败")):
            消息 = self.断言失败含路径(
                lambda: 构建模块.复制并重写(self.源根, self.目标根), 源文件)

        self.assertIn(":1", 消息)
        self.assertIn("模拟反解析失败", 消息)
        self.assertFalse((self.目标根 / "反解析失败.py").exists())

    def test_AST解析非语法异常同样报告文件与行号(self) -> None:
        源文件 = self.源根 / "解析器栈溢出.py"
        源文件.write_text("值 = 1\n", encoding="utf-8")

        with mock.patch.object(构建模块.ast, "parse", side_effect=MemoryError("模拟解析器栈溢出")):
            消息 = self.断言失败含路径(
                lambda: 构建模块.复制并重写(self.源根, self.目标根), 源文件, Exception)

        self.assertIn(":1", 消息)
        self.assertIn("模拟解析器栈溢出", 消息)
        self.assertFalse((self.目标根 / "解析器栈溢出.py").exists())

    def test_源文件在resolve后替换为越界链接仍不得复制(self) -> None:
        源文件 = self.源根 / "竞态.py"
        源文件.write_text("值 = '内部'\n", encoding="utf-8")
        外部文件 = self.临时根 / "竞态外部.py"
        外部文件.write_text("值 = '外部'\n", encoding="utf-8")
        原解析 = 构建模块._解析受控源文件

        def 解析后替换(文件, 源根, 真实源根):
            真实文件 = 原解析(文件, 源根, 真实源根)
            文件.unlink()
            文件.symlink_to(外部文件)
            return 真实文件

        with mock.patch.object(构建模块, "_解析受控源文件", side_effect=解析后替换):
            self.断言失败含路径(
                lambda: 构建模块.复制并重写(self.源根, self.目标根), 源文件)

        self.assertFalse((self.目标根 / "竞态.py").exists())

    def test_目标在边界检查后替换为越界目录仍不得写出(self) -> None:
        子目录 = self.源根 / "子目录"
        子目录.mkdir()
        (子目录 / "资源.json").write_text("{}", encoding="utf-8")
        外部目录 = self.临时根 / "竞态目标外部"
        外部目录.mkdir()
        原目标检查 = 构建模块._受控目标路径

        def 检查后替换(目标根, 真实目标根, 相对):
            目标 = 原目标检查(目标根, 真实目标根, 相对)
            目标.parent.symlink_to(外部目录, target_is_directory=True)
            return 目标

        with mock.patch.object(构建模块, "_受控目标路径", side_effect=检查后替换):
            self.断言失败含路径(
                lambda: 构建模块.复制非Py文件(self.源根, self.目标根), self.目标根 / "子目录")

        self.assertFalse((外部目录 / "资源.json").exists())

    def test_Python文件符号链接越界必须阻断(self) -> None:
        外部文件 = self.临时根 / "外部.py"
        外部文件.write_text("值 = 2\n", encoding="utf-8")
        链接 = self.源根 / "越界.py"
        链接.symlink_to(外部文件)

        self.断言失败含路径(
            lambda: 构建模块.复制并重写(self.源根, self.目标根), 链接)

        self.assertFalse((self.目标根 / "越界.py").exists())

    def test_非Python文件符号链接越界必须阻断(self) -> None:
        外部文件 = self.临时根 / "外部.json"
        外部文件.write_text('{"外部": true}', encoding="utf-8")
        链接 = self.源根 / "越界.json"
        链接.symlink_to(外部文件)

        self.断言失败含路径(
            lambda: 构建模块.复制非Py文件(self.源根, self.目标根), 链接)

        self.assertFalse((self.目标根 / "越界.json").exists())

    def test_目录符号链接越界必须阻断(self) -> None:
        外部目录 = self.临时根 / "外部目录"
        外部目录.mkdir()
        (外部目录 / "资源.json").write_text("{}", encoding="utf-8")
        链接目录 = self.源根 / "越界目录"
        链接目录.symlink_to(外部目录, target_is_directory=True)

        self.断言失败含路径(
            lambda: 构建模块.复制非Py文件(self.源根, self.目标根), 链接目录)

    def test_目标目录经符号链接越界必须阻断且不得写到外部(self) -> None:
        (self.源根 / "子目录").mkdir()
        (self.源根 / "子目录" / "资源.json").write_text("{}", encoding="utf-8")
        外部目录 = self.临时根 / "目标外部"
        外部目录.mkdir()
        目标链接 = self.目标根 / "子目录"
        目标链接.symlink_to(外部目录, target_is_directory=True)

        self.断言失败含路径(
            lambda: 构建模块.复制非Py文件(self.源根, self.目标根), 目标链接)

        self.assertFalse((外部目录 / "资源.json").exists())

    def test_摘要阶段拒绝任何符号链接(self) -> None:
        (self.源根 / "正常.txt").write_text("正常", encoding="utf-8")
        外部文件 = self.临时根 / "摘要外部.txt"
        外部文件.write_text("外部", encoding="utf-8")
        链接 = self.源根 / "摘要链接.txt"
        链接.symlink_to(外部文件)

        self.断言失败含路径(
            lambda: 构建模块.计算制品摘要(self.源根), 链接)

    def test_正式构建前拒绝符号链接稳定指针且不覆盖外部(self) -> None:
        临时系统根 = self.临时根 / "临时系统"
        源码包 = 临时系统根 / "测试包"
        源码包.mkdir(parents=True)
        (源码包 / "__init__.py").write_text("值 = 1\n", encoding="utf-8")
        临时构建目录 = self.临时根 / "构建目录"
        临时制品目录 = self.临时根 / "制品目录"
        临时制品目录.mkdir()
        外部指针 = self.临时根 / "不可覆盖.json"
        外部指针.write_text("不可覆盖", encoding="utf-8")
        稳定指针 = 临时制品目录 / "当前.json"
        稳定指针.symlink_to(外部指针)

        with mock.patch.multiple(
            构建模块,
            系统根=临时系统根,
            顶层包表=["测试包"],
            构建目录=临时构建目录,
            制品目录=临时制品目录,
        ):
            self.断言失败含路径(lambda: 构建模块.构建(), 稳定指针)

        self.assertEqual(外部指针.read_text(encoding="utf-8"), "不可覆盖")

    def test_正式安装前拒绝环境目录符号链接(self) -> None:
        临时系统根 = self.临时根 / "安装系统"
        源码包 = 临时系统根 / "测试包"
        源码包.mkdir(parents=True)
        (源码包 / "__init__.py").write_text("值 = 1\n", encoding="utf-8")
        临时构建目录 = self.临时根 / "安装构建"
        临时制品目录 = self.临时根 / "安装制品"
        临时环境目录 = self.临时根 / "安装环境"
        临时环境目录.mkdir()
        外部文件 = self.临时根 / "环境外部.json"
        外部文件.write_text("外部", encoding="utf-8")
        环境链接 = 临时环境目录 / "当前.json"
        环境链接.symlink_to(外部文件)

        with mock.patch.multiple(
            构建模块,
            系统根=临时系统根,
            顶层包表=["测试包"],
            构建目录=临时构建目录,
            制品目录=临时制品目录,
            环境目录=临时环境目录,
        ), mock.patch.object(构建模块, "安装到环境") as 假安装:
            self.断言失败含路径(lambda: 构建模块.构建(安装=True), 环境链接)

        假安装.assert_not_called()
        self.assertFalse(临时制品目录.exists(), "安装环境含链接时必须在产生制品前阻断")

    def test_平台客户端制品壳复用统一启动器模板(self) -> None:
        构建模块.生成可运行制品壳(self.目标根)
        启动器 = self.目标根 / "运行入口" / "启动.py"
        页面 = self.目标根 / "前端" / "编译页面" / "index.html"
        路由 = self.目标根 / "前端" / "编译页面" / "路由表.json"
        self.assertTrue(启动器.is_file())
        self.assertTrue(页面.is_file())
        self.assertTrue(路由.is_file())
        源码 = 启动器.read_text(encoding="utf-8")
        self.assertIn("from 平台客户端.后端核心.后端核心 import 后端核心", 源码)
        self.assertNotIn("from 后端核心.后端核心 import 后端核心", 源码)


    def test_安装链无论成功都关闭制品接入状态库(self) -> None:
        class 假接入:
            最后实例 = None

            def __init__(self):
                type(self).最后实例 = self
                self.已关闭 = False

            @staticmethod
            def 生成或读取密钥():
                return b"private-key", b"public-key"

            def 入库(self, **_参数):
                return True, "入库成功", "a" * 32

            def 安装到环境(self, _摘要):
                return True, "安装成功", self.目标

            def 校验稳定路径(self):
                return True, "校验成功", {}

            def 关闭(self):
                self.已关闭 = True

        假接入.目标 = self.临时根 / "已安装"
        with mock.patch(
            "平台控制面.包仓库.平台客户端制品.平台客户端制品接入", 假接入
        ):
            结果 = 构建模块.安装到环境(self.源根)
        self.assertEqual(结果, 假接入.目标)
        self.assertIsNotNone(假接入.最后实例)
        self.assertTrue(假接入.最后实例.已关闭, "安装完成后必须关闭状态数据库")


if __name__ == "__main__":
    unittest.main()
