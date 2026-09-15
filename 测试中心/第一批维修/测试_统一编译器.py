"""第一批维修：统一编译链安全边界、小单元编译、启动路由与字节指纹回归。"""
from __future__ import annotations

import json
import os
import select
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from unittest import mock

系统根 = Path(__file__).resolve().parents[2]
if str(系统根) not in sys.path:
    sys.path.insert(0, str(系统根))

from 开发工具.项目编译.工作区指纹 import 计算工作区字节指纹
from 开发工具.项目编译.项目编译器 import (
    _准备输出目录,
    _写入并编译Python,
    计算影响闭包,
    校验项目id,
    校验输出目录,
    _生成启动器,
    编译项目,
)


class 统一编译器安全边界测试(unittest.TestCase):
    def test_启动器响应和线程资源有界(self):
        启动器 = _生成启动器("示例项目.可双击演示")
        self.assertIn("响应.read(响应上限字节 + 1)", 启动器)
        self.assertIn('响应上限字节 = 4 * 1024 * 1024', 启动器)
        self.assertIn("有界线程HTTP服务器", 启动器)
        self.assertIn("BoundedSemaphore(并发上限)", 启动器)

    def test_输出拒绝项目根源码祖先和关键目录(self):
        with tempfile.TemporaryDirectory(prefix=f"隔离用例_{os.getpid()}_", dir="/tmp") as 临时:
            项目 = Path(临时) / "项目"
            项目.mkdir()
            危险目录 = [
                项目,
                项目.parent,
                系统根,
                系统根.parent,
                系统根 / "开发工具",
                系统根 / ".git",
                项目 / "前端",
            ]
            for 输出 in 危险目录:
                with self.subTest(输出=输出):
                    with self.assertRaisesRegex(ValueError, "输出目录.*拒绝|危险|源码|关键|祖先"):
                        校验输出目录(项目, 输出)

    def test_rmtree前执行最终校验且失败时不删除(self):
        """真实临时目录 + 真实校验拒绝：拒绝必须发生在任何递归删除之前。

        不 patch 校验入口，也不 patch shutil.rmtree（后者是进程级全局屏蔽，
        会让「未删除」恒真且掩盖真实删除缺陷）。
        """
        with tempfile.TemporaryDirectory(prefix=f"隔离用例_{os.getpid()}_", dir="/tmp") as 临时:
            项目 = Path(临时) / "项目"
            输出 = Path(临时) / "制品"
            项目.mkdir(); 输出.mkdir()
            哨兵 = 输出 / "不可删除.txt"
            哨兵.write_text("保留", encoding="utf-8")
            # 真实触发最终校验拒绝：输出目录落在项目源码目录内（生产校验真判危险）
            危险输出 = 项目 / "前端"
            危险输出.mkdir()
            源码哨兵 = 危险输出 / "源码保留.txt"
            源码哨兵.write_text("源码", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "输出目录危险"):
                _准备输出目录(项目, 危险输出)
            # 真实副作用断言：若生产先删除后校验，源码目录与其内容会真的消失
            self.assertTrue(危险输出.is_dir(), "被拒绝的危险输出目录不得被删除")
            self.assertTrue(源码哨兵.is_file(), "最终校验失败后源码哨兵必须原样存在")
            self.assertEqual(源码哨兵.read_text(encoding="utf-8"), "源码")
            # 对照：合法输出目录必须真实清理并重建（证明删除路径本身仍生效）
            返回 = _准备输出目录(项目, 输出)
            self.assertEqual(返回, 输出.resolve())
            self.assertFalse(哨兵.is_file(), "合法输出目录的旧内容必须被真实删除")
            self.assertTrue(输出.is_dir())

    def test_项目id必须是字符串和点分标识符(self):
        self.assertEqual(校验项目id("示例项目.可双击演示"), "示例项目.可双击演示")
        for 非法 in (None, 123, "", "含空格 id", "../逃逸", '坏项目\"\"\"\n执行代码()'):
            with self.subTest(非法=非法):
                with self.assertRaisesRegex(ValueError, "项目id"):
                    校验项目id(非法)

    def test_生成Python后立即执行py_compile(self):
        with tempfile.TemporaryDirectory(prefix=f"隔离用例_{os.getpid()}_", dir="/tmp") as 临时:
            文件 = Path(临时) / "启动.py"
            with mock.patch("开发工具.项目编译.项目编译器.py_compile.compile", wraps=__import__("py_compile").compile) as 编译:
                _写入并编译Python(文件, "项目id = " + json.dumps("示例.项目", ensure_ascii=False) + "\n")
            self.assertTrue(文件.is_file())
            self.assertEqual(编译.call_count, 1)
            self.assertEqual(list(Path(临时).rglob("*.pyc")), [])


class 统一编译器入口与小单元测试(unittest.TestCase):
    def _运行(self, *参数: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["python3.14", *参数], cwd=系统根,
            capture_output=True, text=True, timeout=30,
        )

    def test_快速编译和契约编译拒绝独立正式调用(self):
        快速 = self._运行("开发工具/快速编译/运行快速编译.py", "--文件", "支持库/__init__.py")
        契约 = self._运行("开发工具/契约编译/契约编译器.py")
        self.assertNotEqual(快速.returncode, 0)
        self.assertNotEqual(契约.returncode, 0)
        self.assertIn("内部阶段", 快速.stdout + 快速.stderr)
        self.assertIn("内部阶段", 契约.stdout + 契约.stderr)

    def test_统一CLI强制本次变更小单元且拒绝工作区全量(self):
        无单元 = self._运行(
            "开发工具/项目编译/项目编译器.py",
            "示例项目/可双击演示/开发文件夹", "--输出", str(Path(tempfile.gettempdir()) / "不应生成制品"),
        )
        全量 = self._运行(
            "开发工具/项目编译/项目编译器.py",
            "示例项目/可双击演示/开发文件夹", "--输出", str(Path(tempfile.gettempdir()) / "不应生成制品"),
            "--文件", "项目声明.json", "--范围", "工作区",
        )
        self.assertNotEqual(无单元.returncode, 0)
        self.assertIn("--文件", 无单元.stderr + 无单元.stdout)
        self.assertNotEqual(全量.returncode, 0)
        self.assertIn("工作区", 全量.stderr + 全量.stdout)

    def test_文件能力组件三类小单元计算契约依赖边界和影响闭包(self):
        with tempfile.TemporaryDirectory(prefix=f"隔离用例_{os.getpid()}_", dir="/tmp") as 临时:
            项目 = Path(临时)
            页面目录 = 项目 / "前端" / "页面"
            页面目录.mkdir(parents=True)
            页面1 = 页面目录 / "页面1.json"
            页面2 = 页面目录 / "页面2.json"
            页面1.write_text(json.dumps({
                "页面id": "页面1", "标题": "页面1", "路由": "/页面1",
                "组件列表": [{"组件id": "按钮1", "类型": "按钮", "属性": {"能力id": "示例能力1"}}],
            }, ensure_ascii=False), encoding="utf-8")
            页面2.write_text(json.dumps({
                "页面id": "页面2", "标题": "页面2", "路由": "/页面2",
                "组件列表": [{"组件id": "按钮2", "类型": "按钮", "属性": {"能力id": "示例能力2"}}],
            }, ensure_ascii=False), encoding="utf-8")
            文件闭包 = 计算影响闭包(项目, 文件=页面1)
            能力闭包 = 计算影响闭包(项目, 能力="示例能力2")
            组件闭包 = 计算影响闭包(项目, 组件="按钮1")
            self.assertEqual(文件闭包["受影响页面"], ["页面1.json"])
            self.assertEqual(能力闭包["受影响页面"], ["页面2.json"])
            self.assertEqual(组件闭包["受影响页面"], ["页面1.json"])
            for 闭包 in (文件闭包, 能力闭包, 组件闭包):
                self.assertIn("契约", 闭包)
                self.assertIn("依赖", 闭包)
                self.assertIn("边界", 闭包)
                self.assertTrue(闭包["边界"]["禁止测试中心和HTML全量"])

    def test_项目声明变更只生成其影响闭包且不调用测试中心或HTML全量(self):
        源项目 = 系统根 / "示例项目" / "可双击演示" / "开发文件夹"
        with tempfile.TemporaryDirectory(prefix=f"隔离用例_{os.getpid()}_", dir="/tmp") as 临时:
            项目 = Path(临时) / "项目"
            输出 = Path(临时) / "制品"
            shutil.copytree(源项目, 项目)
            第二页 = {
                "页面id": "关于", "标题": "关于", "路由": "/关于", "组件列表": [],
            }
            (项目 / "前端" / "页面" / "关于.json").write_text(
                json.dumps(第二页, ensure_ascii=False), encoding="utf-8")
            with mock.patch("subprocess.run", wraps=subprocess.run) as 子进程:
                清单 = 编译项目(项目, 输出, 变更单元={"文件": 项目 / "项目声明.json"})
            命令文本 = "\n".join(" ".join(map(str, 调用.args[0])) for 调用 in 子进程.call_args_list if 调用.args)
            self.assertNotIn("测试中心", 命令文本)
            self.assertNotIn("HTML验证", 命令文本)
            self.assertEqual(清单["变更单元"]["类型"], "文件")
            self.assertEqual(set(清单["影响闭包"]["页面"]), {"主页", "关于"})
            self.assertEqual({文件.name for 文件 in (输出 / "前端" / "编译页面").glob("*.html")}, {"index.html", "关于.html"})


class 启动器页面路由测试(unittest.TestCase):
    def test_启动器按路由表真实GET全部页面且非法路径404(self):
        源项目 = 系统根 / "示例项目" / "可双击演示" / "开发文件夹"
        with tempfile.TemporaryDirectory(prefix=f"隔离用例_{os.getpid()}_", dir="/tmp") as 临时:
            项目 = Path(临时) / "项目"
            输出 = Path(临时) / "制品"
            shutil.copytree(源项目, 项目)
            (项目 / "前端" / "页面" / "关于.json").write_text(json.dumps({
                "页面id": "关于", "标题": "第二页面", "路由": "/关于", "组件列表": [],
            }, ensure_ascii=False), encoding="utf-8")
            编译项目(项目, 输出, 变更单元={"文件": 项目 / "项目声明.json"})
            环境 = dict(os.environ)
            环境["系统库网关凭证"] = "123"
            进程 = subprocess.Popen(
                ["python3.14", "-u", "-B", "运行入口/启动.py", "--端口", "0", "--不自动打开"],
                cwd=输出, env=环境, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                start_new_session=True,
            )
            try:
                地址 = ""
                截止 = time.monotonic() + 20
                while time.monotonic() < 截止 and 进程.poll() is None:
                    可读, _, _ = select.select([进程.stdout], [], [], 0.2)
                    if not 可读:
                        continue
                    行 = 进程.stdout.readline().strip()
                    if "独立项目已启动:" in 行:
                        地址 = 行.split("独立项目已启动:", 1)[1].strip()
                        break
                if not 地址:
                    错误 = 进程.stderr.read() if 进程.poll() is not None else "启动超时"
                    self.fail(f"启动器未就绪: {错误}")
                for 路由, 标题 in (("/", "底座演示"), ("/关于", "第二页面")):
                    编码路由 = urllib.parse.quote(路由, safe="/")
                    with urllib.request.urlopen(地址 + 编码路由, timeout=10) as 响应:
                        self.assertEqual(响应.status, 200)
                        self.assertIn(标题, 响应.read().decode("utf-8"))
                with self.assertRaises(urllib.error.HTTPError) as 捕获:
                    urllib.request.urlopen(地址 + "/not-found", timeout=10)
                self.assertEqual(捕获.exception.code, 404)
                捕获.exception.close()
            finally:
                if 进程.poll() is None:
                    os.killpg(进程.pid, signal.SIGINT)
                    try:
                        进程.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        os.killpg(进程.pid, signal.SIGKILL)
                        进程.wait(timeout=5)
                if 进程.stdout is not None:
                    进程.stdout.close()
                if 进程.stderr is not None:
                    进程.stderr.close()


class 工作区字节指纹测试(unittest.TestCase):
    def _git(self, 根: Path, *参数: str) -> None:
        结果 = subprocess.run(["git", *参数], cwd=根, capture_output=True, text=True, timeout=10)
        self.assertEqual(结果.returncode, 0, 结果.stderr)

    def test_同一路径内容变化必须改变指纹(self):
        with tempfile.TemporaryDirectory(prefix=f"隔离用例_{os.getpid()}_", dir="/tmp") as 临时:
            根 = Path(临时)
            self._git(根, "init", "-q")
            self._git(根, "config", "user.email", "fingerprint@example.invalid")
            self._git(根, "config", "user.name", "指纹测试")
            文件 = 根 / "正式.py"
            文件.write_text("值 = '基线'\n", encoding="utf-8")
            self._git(根, "add", "正式.py")
            self._git(根, "commit", "-qm", "基线")
            文件.write_text("值 = '第一次'\n", encoding="utf-8")
            第一次 = 计算工作区字节指纹(根)
            文件.write_text("值 = '第二次'\n", encoding="utf-8")
            第二次 = 计算工作区字节指纹(根)
            self.assertNotEqual(第一次["工作区字节指纹"], 第二次["工作区字节指纹"])
            self.assertEqual(第一次["语义"], "HEAD+暂存区差异字节+未暂存正式文件字节+未跟踪正式文件字节")
            self.assertEqual(第一次["排除目录"], 第二次["排除目录"])

    def test_暂存差异和未跟踪正式文件都进入冻结指纹(self):
        with tempfile.TemporaryDirectory(prefix=f"隔离用例_{os.getpid()}_", dir="/tmp") as 临时:
            根 = Path(临时)
            self._git(根, "init", "-q")
            self._git(根, "config", "user.email", "fingerprint@example.invalid")
            self._git(根, "config", "user.name", "指纹测试")
            正式 = 根 / "正式.py"
            正式.write_text("值 = 1\n", encoding="utf-8")
            self._git(根, "add", "正式.py")
            self._git(根, "commit", "-qm", "基线")
            干净 = 计算工作区字节指纹(根)
            正式.write_text("值 = 2\n", encoding="utf-8")
            self._git(根, "add", "正式.py")
            暂存 = 计算工作区字节指纹(根)
            self.assertGreater(int(暂存["暂存差异字节数"]), 0)
            self.assertNotEqual(干净["工作区字节指纹"], 暂存["工作区字节指纹"])
            (根 / "新增.py").write_text("新增 = True\n", encoding="utf-8")
            未跟踪 = 计算工作区字节指纹(根)
            self.assertEqual(未跟踪["未跟踪正式文件数"], 1)
            self.assertNotEqual(暂存["工作区字节指纹"], 未跟踪["工作区字节指纹"])


    def test_正式制品只允许唯一启动入口(self):
        from 开发工具.HTML验证.制品事实 import _找启动器
        with tempfile.TemporaryDirectory(prefix=f"启动入口_{os.getpid()}_", dir="/tmp") as 临时:
            制品 = Path(临时)
            (制品 / "运行入口").mkdir()
            (制品 / "运行入口" / "启动器.py").write_text("", encoding="utf-8")
            with self.assertRaises(FileNotFoundError):
                _找启动器(制品)
            (制品 / "运行入口" / "启动.py").write_text("", encoding="utf-8")
            self.assertEqual(_找启动器(制品), 制品 / "运行入口" / "启动.py")

    def test_命令行支持缓存状态和强制重编译(self):
        帮助 = subprocess.run(
            ["python3.14", "开发工具/项目编译/项目编译器.py", "--help"],
            cwd=系统根, capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(帮助.returncode, 0, 帮助.stderr)
        self.assertIn("--缓存根目录", 帮助.stdout)
        self.assertIn("--强制重新编译", 帮助.stdout)


class 编译产物缓存与稳定指针测试(unittest.TestCase):
    """第一批：源码只生产不可变产物，重复编译必须命中缓存。"""

    def setUp(self):
        self.源项目 = 系统根 / "示例项目" / "可双击演示" / "开发文件夹"
        self.临时根 = Path(tempfile.mkdtemp(prefix=f"编译缓存_{os.getpid()}_", dir="/tmp"))
        self.项目 = self.临时根 / "项目"
        self.输出 = self.临时根 / "输出"
        self.缓存 = self.临时根 / "缓存"
        shutil.copytree(self.源项目, self.项目)

    def tearDown(self):
        shutil.rmtree(self.临时根, ignore_errors=True)

    def _编译(self):
        return 编译项目(
            self.项目,
            self.输出,
            变更单元={"文件": self.项目 / "项目声明.json"},
            缓存根目录=self.缓存,
        )

    def test_重复编译命中缓存并返回同一制品指纹(self):
        第一次 = self._编译()
        第二次 = self._编译()
        self.assertEqual(第一次["编译状态"], "重新编译")
        self.assertEqual(第二次["编译状态"], "命中缓存")
        self.assertEqual(第一次["制品指纹"], 第二次["制品指纹"])
        self.assertTrue(Path(第二次["制品版本目录"]).is_dir())
        self.assertTrue((self.输出 / "候选.json").is_file())

    def test_修改页面生成新版本且保留旧版本(self):
        第一次 = self._编译()
        旧版本 = Path(第一次["制品版本目录"])
        (self.项目 / "前端" / "页面" / "关于.json").write_text(json.dumps({
            "页面id": "关于", "标题": "关于页面", "路由": "/关于", "组件列表": [],
        }, ensure_ascii=False), encoding="utf-8")
        第二次 = self._编译()
        新版本 = Path(第二次["制品版本目录"])
        self.assertEqual(第二次["编译状态"], "重新编译")
        self.assertNotEqual(第一次["制品指纹"], 第二次["制品指纹"])
        self.assertTrue(旧版本.is_dir(), "旧版本必须保留用于回滚")
        self.assertTrue((新版本 / "前端" / "编译页面" / "关于.html").is_file())
        指针 = json.loads((self.输出 / "候选.json").read_text(encoding="utf-8"))
        self.assertEqual(指针["候选制品指纹"], 第二次["制品指纹"])


if __name__ == "__main__":
    unittest.main()
