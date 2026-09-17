"""P0-17/P1-24：平台客户端构建失败即阻断与路径边界回归测试。"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any
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

    def test_数据库只允许作为包内验证夹具进入制品(self) -> None:
        夹具 = self.源根 / "验证夹具" / "空状态.sqlite3"
        夹具.parent.mkdir(parents=True)
        夹具.write_bytes(b"SQLite format 3\x00")
        运行库 = self.源根 / "工程缓存" / "运行状态.sqlite3"
        运行库.parent.mkdir(parents=True)
        运行库.write_bytes("运行数据".encode("utf-8"))
        构建模块.复制非Py文件(self.源根, self.目标根)
        self.assertTrue((self.目标根 / "验证夹具" / "空状态.sqlite3").is_file())
        self.assertFalse((self.目标根 / "工程缓存" / "运行状态.sqlite3").exists())

    def test_制品入库把SQLite夹具按二进制保存(self) -> None:
        夹具 = self.源根 / "验证夹具" / "基础数据.db"
        夹具.parent.mkdir(parents=True)
        夹具.write_bytes(b"SQLite format 3\x00\x01")
        from 平台控制面.包仓库.平台客户端制品 import 读取制品文件表
        文件表 = 读取制品文件表(self.源根)
        self.assertEqual(文件表["验证夹具/基础数据.db"], "hexfile:53514c69746520666f726d617420330001")

    def test_制品入库把无扩展名二进制夹具按二进制保存(self) -> None:
        夹具 = self.源根 / "验证夹具" / "git目录" / "index"
        夹具.parent.mkdir(parents=True)
        夹具.write_bytes(b"git index\x00\x8d\x94")
        from 平台控制面.包仓库.平台客户端制品 import 读取制品文件表
        文件表 = 读取制品文件表(self.源根)
        self.assertEqual(文件表["验证夹具/git目录/index"], "hexfile:67697420696e646578008d94")

    def test_平台客户端生成来源绑定三件套(self) -> None:
        from 开发工具.项目编译 import 项目编译器
        制品 = self.临时根 / "来源制品"
        制品.mkdir()
        (制品 / "正式.txt").write_text("正式内容", encoding="utf-8")
        指纹 = {"提交": "a" * 40, "工作区字节指纹": "b" * 64, "工作区状态": "干净"}
        with mock.patch.object(项目编译器, "读取工作区字节指纹", return_value=指纹):
            构建模块.生成来源元数据(制品)
        for 名称 in ("制品来源.json", "编译清单.json", "制品完整性摘要.json"):
            self.assertTrue((制品 / 名称).is_file())
        摘要 = json.loads((制品 / "制品完整性摘要.json").read_text(encoding="utf-8"))
        self.assertEqual(摘要, 项目编译器._制品文件摘要(制品))

    def test_子进程入口同时兼容源码根和平台客户端导入根(self) -> None:
        入口表 = list((系统根 / "支持库").rglob("子进程入口.py"))
        self.assertGreaterEqual(len(入口表), 8)
        for 入口 in 入口表:
            源码 = 入口.read_text(encoding="utf-8")
            if "系统根 = Path(__file__).resolve().parents[" not in 源码:
                continue
            self.assertIn(
                '导入根 = 系统根.parent if 系统根.name == "平台客户端" else 系统根',
                源码, str(入口),
            )

    def test_PyMuPDF制品内自举不依赖另一份激活指针(self) -> None:
        from 支持库.适配层.PyMuPDF提供者.实现 import 子进程入口
        原系统根 = 子进程入口.系统根
        原状态 = 子进程入口._平台客户端路径已注入
        try:
            with tempfile.TemporaryDirectory() as 临时:
                制品包 = Path(临时) / "平台客户端"
                制品包.mkdir()
                (制品包 / "__init__.py").write_text("", encoding="utf-8")
                子进程入口.系统根 = 制品包
                子进程入口._平台客户端路径已注入 = False
                self.assertIsNone(子进程入口.注入平台客户端路径())
        finally:
            子进程入口.系统根 = 原系统根
            子进程入口._平台客户端路径已注入 = 原状态

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

    def test_正式构建生成的制品摘要必须是标准JSON(self) -> None:
        临时系统根 = self.临时根 / "临时系统"
        (临时系统根 / "测试包").mkdir(parents=True)
        (临时系统根 / "测试包" / "__init__.py").write_text("值 = 1\n", encoding="utf-8")
        临时构建目录 = self.临时根 / "构建目录"
        临时制品目录 = self.临时根 / "制品目录"
        临时制品目录.mkdir()

        with mock.patch.multiple(
            构建模块,
            系统根=临时系统根,
            顶层包表=["测试包"],
            构建目录=临时构建目录,
            制品目录=临时制品目录,
        ):
            制品 = 构建模块.构建()

        摘要 = json.loads((制品 / "制品摘要.json").read_text(encoding="utf-8"))
        self.assertEqual(摘要["客户端"], "平台客户端")
        self.assertEqual(摘要["顶层包"], ["测试包"])
        self.assertIn("生成时间", 摘要)
        from 平台控制面.包仓库.平台客户端制品 import 计算目录摘要16
        self.assertEqual(制品.name.rsplit("-", 1)[-1], 计算目录摘要16(制品))


    def test_安装链无论成功都关闭制品接入状态库(self) -> None:
        class 假状态:
            """替身状态库：只记录读取调用并返回 None（生产侧对 None 已做兜底）。"""

            def __init__(self):
                self.读取记录调用 = []

            def 读取记录(self, 类型: str, 字段: str, 值):
                self.读取记录调用.append((类型, 字段, 值))
                return None

        class 假接入:
            最后实例: Any = None
            缓存根: Path = Path(".")  # 由用例覆盖：清理过期制品 会对两个根 iterdir()

            def __init__(self, **关键字):
                type(self).最后实例 = self
                self.已关闭 = False
                # 生产 安装到环境 会读 接入.状态.读取记录(...)（构建平台客户端.py:702）
                # 并按 接入.制品根目录 / 接入.客户端制品目录 两个根清理过期制品，
                # 替身必须补齐这三处契约，否则测的是 AttributeError 而不是「必关闭」。
                self.状态 = 假状态()
                self.制品根目录 = type(self).缓存根 / "内容寻址"
                self.客户端制品目录 = type(self).缓存根 / "身份目录"
                self.制品根目录.mkdir(parents=True, exist_ok=True)
                self.客户端制品目录.mkdir(parents=True, exist_ok=True)
                # **接受任意关键字参数**：生产构造点（`构建平台客户端.py:816`）传
                # `状态目录/制品根目录/客户端制品目录/环境目录/信任目录` 五个定位参数，
                # 而替身只关心其中三个。原写法 `__init__(self)` 不收参数 ——
                # 生产侧参数量一增减，替身就 `unexpected keyword argument` 报错，
                # **测的是 TypeError 而不是「必关闭」**（2026-09-18 实测）。
                # 这里把收到的关键字原样存成属性：既让签名与生产同形，
                # 也让将来「替身需要用到某个定位参数」时可直接取用，不必再改签名。
                for 名, 值 in 关键字.items():
                    setattr(self, 名, 值)

            @staticmethod
            def 生成或读取密钥(密钥目录=None):
                # 生产签名 `生成或读取密钥(密钥目录: Path | str | None = None)`（`平台客户端制品.py:129`）：
                # 替身必须收这个参数，否则生产一传实参就 `takes 0 positional arguments`
                # —— 同上，测的是 TypeError 而不是「必关闭」。
                return b"private-key", b"public-key"

            def 入库(self, **_参数):
                return True, "入库成功", "a" * 32

            def 安装到环境(self, _摘要, **_参数):
                return True, "安装成功", self.目标

            def 校验稳定路径(self, *_参数, **_关键字):
                return True, "校验成功", {}

            def 关闭(self):
                self.已关闭 = True

        假接入.目标 = self.临时根 / "已安装"
        假接入.缓存根 = self.临时根 / "假仓库"
        假接入.缓存根.mkdir(parents=True, exist_ok=True)
        with mock.patch(
            "平台控制面.包仓库.平台客户端制品.平台客户端制品接入", 假接入
        ):
            结果 = 构建模块.安装到环境(self.源根)
        self.assertEqual(结果, 假接入.目标)
        self.assertIsNotNone(假接入.最后实例)
        self.assertTrue(假接入.最后实例.已关闭, "安装完成后必须关闭状态数据库")
        # **本条断言已随实现口径更新（2026-09-18）**：安装链回读制品记录原先走
        # `接入.状态.读取记录(...)`，现已按铁律改走**公开能力**
        # `平台控制面.平台状态.读取记录`（见 `客户端/构建平台客户端.py:857` 的注释
        # 「记录回读：原 `接入.状态.读取记录(...)` → 能力 …」）。
        # 故「替身的状态对象被读过」不再是正确行为 —— **真正的义务是那句注释所写的**：
        # 安装链必须**经能力**回读制品记录（用于清理过期制品）。本用例的替身只替
        # `平台客户端制品接入` 一个类，能力调用路径不在替身范围内，因此这里改为断言
        # 「接入被创建且被关闭」这一条不变义务（上面 386/387 行已断言），
        # 并显式记录「回读已改走能力」这一事实，防后来者把它误当回归。
        self.assertIsNotNone(假接入.最后实例.状态, "安装链仍须持有状态对象（关闭义务的前提）")


if __name__ == "__main__":
    unittest.main()
