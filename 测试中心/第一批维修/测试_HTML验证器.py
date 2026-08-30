"""HTML 黑盒验证器第一批维修回归测试。"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import time
import types
import unittest
from pathlib import Path
from unittest import mock

系统根 = Path(__file__).resolve().parents[2]
验证器路径 = 系统根 / "开发工具" / "HTML验证" / "验证器.py"
规格 = importlib.util.spec_from_file_location("HTML验证器", 验证器路径)
验证器 = importlib.util.module_from_spec(规格)
assert 规格 and 规格.loader
sys.modules[规格.name] = 验证器
规格.loader.exec_module(验证器)


def 写JSON(路径: Path, 数据) -> None:
    路径.parent.mkdir(parents=True, exist_ok=True)
    路径.write_text(json.dumps(数据, ensure_ascii=False), encoding="utf-8")


def 建制品(根: Path, 能力表: list[tuple[str, dict]], 场景表: list[dict] | None) -> Path:
    包 = 根 / "模块库" / "样例包"
    声明能力 = [{"能力id": 能力id} for 能力id, _ in 能力表]
    契约能力 = [{"能力id": 能力id, "参数": 参数, "返回": {"类型": "结果型"}}
            for 能力id, 参数 in 能力表]
    写JSON(包 / "包声明.json", {"包id": "模块库.样例包", "能力": 声明能力})
    写JSON(包 / "能力定义.json", {"能力列表": 声明能力})
    写JSON(包 / "能力契约" / "参数契约.json", {"契约版本": "1.0.0", "能力契约": 契约能力})
    if 场景表 is not None:
        写JSON(包 / "验证场景引用.json", {"验证场景引用": 场景表})
    return 根


def 成功场景(能力id="样例.相加", 场景id="相加成功", 参数=None) -> dict:
    return {
        "场景id": 场景id,
        "能力id": 能力id,
        "方法": "POST",
        "路径": "/网关/调用",
        "参数": 参数 or {"甲": 1, "乙": 2},
        "预期": {"成功": True, "值类型": "字典型", "关键值": {"和": 3}},
    }


def 统一成功返回(值=None) -> dict:
    return {
        "成功": True,
        "值": {"和": 3} if 值 is None else 值,
        "错误码": "",
        "错误说明": "",
        "可重试": False,
        "请求id": "请求-1",
        "耗时毫秒": 1.2,
    }


def 绑定场景(场景, 制品: Path):
    场景.制品摘要 = 验证器._制品全文件摘要(制品)["制品摘要"]
    return 场景


class Test场景事实源与阻断(unittest.TestCase):
    def test_聚合父包声明不重复占用子包能力owner(self):
        with tempfile.TemporaryDirectory() as 临时:
            制品 = 建制品(Path(临时), [("样例.相加", {})], [成功场景()])
            写JSON(
                制品 / "模块库" / "聚合父包" / "包声明.json",
                {"包id": "模块库.聚合父包", "能力": [{"能力id": "样例.相加"}]},
            )
            场景 = 验证器._加载场景(制品, None)
            self.assertEqual([项.能力id for 项 in 场景], ["样例.相加"])

    def test_平台客户端嵌套制品仍使用同一公开能力扫描链(self):
        with tempfile.TemporaryDirectory() as 临时:
            制品 = Path(临时)
            嵌套根 = 制品 / "平台客户端"
            建制品(嵌套根, [("样例.相加", {"甲": {"必填": True}})], [成功场景()])
            场景 = 验证器._加载场景(制品, None)
            self.assertEqual([项.能力id for 项 in 场景], ["样例.相加"])
            self.assertEqual(
                场景[0].制品摘要,
                验证器._制品全文件摘要(制品)["制品摘要"],
            )

    def test_包级引用提供真实成功参数且不从契约猜输入(self):
        with tempfile.TemporaryDirectory() as 临时:
            制品 = 建制品(Path(临时), [("样例.相加", {"甲": {"必填": True}})], [成功场景()])
            场景 = 验证器._加载场景(制品, None)
            self.assertEqual(len(场景), 1)
            self.assertEqual(场景[0].参数, {"甲": 1, "乙": 2})
            self.assertTrue(场景[0].预期成功)
            self.assertEqual(场景[0].预期关键值, {"和": 3})
            self.assertEqual(场景[0].制品摘要, 验证器._制品全文件摘要(制品)["制品摘要"])

    def test_每个公开能力必须有真实成功场景(self):
        with tempfile.TemporaryDirectory() as 临时:
            负向 = {
                "场景id": "相加缺参", "能力id": "样例.相加", "参数": {},
                "预期": {"成功": False, "错误码": "参数不合法"},
            }
            制品 = 建制品(Path(临时), [("样例.相加", {})], [负向])
            with self.assertRaisesRegex(ValueError, "真实成功场景"):
                验证器._加载场景(制品, None)

    def test_零场景空文件和全无效均阻断(self):
        for 内容 in ({"验证场景引用": []}, {"验证场景引用": [None, "坏场景"]}):
            with self.subTest(内容=内容), tempfile.TemporaryDirectory() as 临时:
                制品 = 建制品(Path(临时), [("样例.相加", {})], None)
                写JSON(制品 / "模块库" / "样例包" / "验证场景引用.json", 内容)
                with self.assertRaises(ValueError):
                    验证器._加载场景(制品, None)

    def test_坏JSON坏契约缺能力id与重复均阻断(self):
        情况表 = ["坏JSON", "坏契约", "缺能力id", "重复能力id"]
        for 情况 in 情况表:
            with self.subTest(情况=情况), tempfile.TemporaryDirectory() as 临时:
                制品 = 建制品(Path(临时), [("样例.相加", {})], [成功场景()])
                契约 = 制品 / "模块库" / "样例包" / "能力契约" / "参数契约.json"
                if 情况 == "坏JSON":
                    (制品 / "模块库" / "样例包" / "验证场景引用.json").write_text("{坏", encoding="utf-8")
                elif 情况 == "坏契约":
                    契约.write_text("{坏", encoding="utf-8")
                elif 情况 == "缺能力id":
                    写JSON(契约, {"能力契约": [{"参数": []}]})
                else:
                    写JSON(契约, {"能力契约": [{"能力id": "样例.相加"}, {"能力id": "样例.相加"}]})
                with self.assertRaises(ValueError):
                    验证器._加载场景(制品, None)

    def test_重复场景和契约场景差集均阻断(self):
        for 场景表 in (
            [成功场景(), 成功场景(场景id="相加成功")],
            [成功场景(), 成功场景("样例.多余", "多余成功")],
        ):
            with self.subTest(), tempfile.TemporaryDirectory() as 临时:
                制品 = 建制品(Path(临时), [("样例.相加", {})], 场景表)
                with self.assertRaises(ValueError):
                    验证器._加载场景(制品, None)

    def test_外部场景束必须绑定当前制品摘要且来源为包级引用(self):
        with tempfile.TemporaryDirectory() as 临时:
            制品 = 建制品(Path(临时) / "制品", [("样例.相加", {})], [成功场景()])
            场景束 = Path(临时) / "场景.json"
            写JSON(场景束, {
                "来源": "包级验证场景引用", "制品摘要": "错误摘要", "验证场景": [成功场景()],
            })
            with self.assertRaisesRegex(ValueError, "制品摘要"):
                验证器._加载场景(制品, 场景束)


class Test返回契约(unittest.TestCase):
    def setUp(self):
        self.场景 = 验证器.验证场景.从字典(成功场景())

    def test_成功结果必须具备统一字段与正确类型(self):
        for 返回 in (
            {"成功": True, "值": {"和": 3}},
            {**统一成功返回(), "成功": 1},
            {**统一成功返回(), "请求id": ""},
            {**统一成功返回(), "耗时毫秒": "1"},
        ):
            with self.subTest(返回=返回):
                通过, 原因, _ = 验证器._判定(self.场景, 200, 返回)
                self.assertFalse(通过)
                self.assertTrue(原因)

    def test_成功值不可为空且成功错误字段互斥(self):
        for 返回 in (
            统一成功返回(None) | {"值": None},
            统一成功返回() | {"错误码": "参数不合法"},
            统一成功返回() | {"错误说明": "不应存在"},
        ):
            with self.subTest(返回=返回):
                self.assertFalse(验证器._判定(self.场景, 200, 返回)[0])

    def test_错误结果值为空且错误字段完整(self):
        错误场景 = 验证器.验证场景.从字典({
            "场景id": "负向", "能力id": "样例.相加", "参数": {},
            "预期": {"成功": False, "错误码": "参数不合法"},
        })
        正确 = {
            "成功": False, "值": None, "错误码": "参数不合法", "错误说明": "缺参数",
            "可重试": False, "请求id": "请求-2", "耗时毫秒": 1,
        }
        self.assertTrue(验证器._判定(错误场景, 400, 正确)[0])
        self.assertFalse(验证器._判定(错误场景, 400, {**正确, "值": {}})[0])
        self.assertFalse(验证器._判定(错误场景, 400, {**正确, "错误说明": ""})[0])

    def test_校验关键值值类型完整值和返回契约(self):
        基础 = 成功场景()
        基础["预期"].update({
            "值": {"和": 3, "明细": [1, 2]},
            "返回契约": {"必需字段": ["和", "明细"], "字段类型": {"和": "整数型", "明细": "列表型"}},
        })
        场景 = 验证器.验证场景.从字典(基础)
        self.assertTrue(验证器._判定(场景, 200, 统一成功返回({"和": 3, "明细": [1, 2]}))[0])
        self.assertFalse(验证器._判定(场景, 200, 统一成功返回({"和": "3", "明细": [1, 2]}))[0])
        self.assertFalse(验证器._判定(场景, 200, 统一成功返回({"和": 3, "明细": []}))[0])


class Test直连异常与证据(unittest.TestCase):
    def test_直连地址只接受显式端口的IP回环HTTP根地址(self):
        for 地址 in ("http://127.0.0.1:45080", "http://[::1]:45080"):
            self.assertEqual(验证器._校验直连地址(地址), 地址)
        for 地址 in ("http://localhost:45080", "https://example.com:443", "http://127.0.0.1", "http://127.0.0.1:45080/x", "ftp://127.0.0.1:21"):
            with self.subTest(地址=地址), self.assertRaises(ValueError):
                验证器._校验直连地址(地址)

    def test_直连模式绝不查找启动器(self):
        with tempfile.TemporaryDirectory() as 临时:
            制品 = Path(临时)
            场景 = 绑定场景(验证器.验证场景.从字典(成功场景()), 制品)
            with mock.patch.object(验证器, "_找启动器", side_effect=AssertionError("不应查启动器")), \
                 mock.patch.object(验证器, "_发送请求", return_value=(200, 统一成功返回(), 1)):
                报告, _, 进程 = 验证器.验证全部(制品, [场景], 直连地址="http://127.0.0.1:45080")
            self.assertEqual(报告.失败数, 0)
            self.assertIsNone(进程)

    def test_单任务异常转成结构化失败而不击穿总流程(self):
        with tempfile.TemporaryDirectory() as 临时:
            制品 = Path(临时)
            场景 = 绑定场景(验证器.验证场景.从字典(成功场景()), 制品)
            with mock.patch.object(验证器, "_发送请求", return_value=(200, {}, 1)), \
                 mock.patch.object(验证器, "验证单个", side_effect=RuntimeError("任务爆炸")):
                报告, _, _ = 验证器.验证全部(制品, [场景], 直连地址="http://127.0.0.1:45080")
            self.assertEqual(报告.失败数, 1)
            self.assertIn("任务爆炸", 报告.结果列表[-1].失败原因)

    def test_制品全文件摘要前后漂移阻断(self):
        with tempfile.TemporaryDirectory() as 临时:
            制品 = Path(临时)
            (制品 / "a.txt").write_text("甲", encoding="utf-8")
            前 = 验证器._制品全文件摘要(制品)
            (制品 / "a.txt").write_text("乙", encoding="utf-8")
            后 = 验证器._制品全文件摘要(制品)
            self.assertNotEqual(前["制品摘要"], 后["制品摘要"])
            报告 = 验证器.验证报告(制品摘要前=前, 制品摘要后=后)
            验证器._校验制品前后绑定(报告)
            self.assertGreater(报告.失败数, 0)

    def test_证据按制品摘要隔离且同秒不覆盖(self):
        with tempfile.TemporaryDirectory() as 临时:
            制品 = Path(临时) / "制品"; 制品.mkdir()
            (制品 / "a").write_text("x", encoding="utf-8")
            摘要 = 验证器._制品全文件摘要(制品)
            报告 = 验证器.验证报告(
                制品路径=str(制品), 制品摘要前=摘要, 制品摘要后=摘要,
                场景制品摘要=摘要["制品摘要"],
            )
            输出 = Path(临时) / "证据"
            一 = 验证器.保存证据(报告, 制品, 输出)
            二 = 验证器.保存证据(报告, 制品, 输出)
            self.assertNotEqual(一, 二)
            self.assertEqual(一.parent.name, 摘要["制品摘要"])
            数据 = json.loads(一.read_text(encoding="utf-8"))
            self.assertEqual(数据["证据绑定"]["制品摘要"], 摘要["制品摘要"])
            self.assertEqual(数据["证据绑定"]["场景制品摘要"], 摘要["制品摘要"])

    def test_执行时拒绝未绑定或错绑制品的场景(self):
        with tempfile.TemporaryDirectory() as 临时:
            制品 = Path(临时)
            场景 = 验证器.验证场景.从字典(成功场景())
            场景.制品摘要 = "旧制品"
            报告, _, _ = 验证器.验证全部(制品, [场景], 直连地址="http://127.0.0.1:45080")
            self.assertGreater(报告.失败数, 0)
            self.assertIn("场景制品摘要", 报告.结果列表[0].失败原因)

    def test_主流程异常也在finally保存失败证据(self):
        with tempfile.TemporaryDirectory() as 临时:
            参数 = types.SimpleNamespace(
                制品=临时, 只生成场景=False, 服务=0, 场景="",
                并发=1, 超时秒=1, 端口=45080, 直连地址="",
            )
            with mock.patch.object(验证器, "_加载场景", side_effect=ValueError("坏场景")), \
                 mock.patch.object(验证器, "保存证据") as 保存:
                退出码 = 验证器.主函数(参数)
        self.assertNotEqual(退出码, 0)
        保存.assert_called_once()
        self.assertGreater(保存.call_args.args[0].失败数, 0)

    def test_工作区指纹复用编译控制面实现(self):
        with mock.patch.object(验证器, "_编译来源指纹", return_value={
            "提交": "abc", "工作区摘要": "def", "工作区状态": "干净",
        }) as 公共实现:
            指纹 = 验证器._工作区指纹()
        公共实现.assert_called_once_with(None)
        self.assertEqual(指纹["工作区摘要"], "def")

    def test_自启动后总流程异常仍由finally回收进程(self):
        with tempfile.TemporaryDirectory() as 临时:
            制品 = Path(临时)
            (制品 / "运行入口").mkdir()
            启动器 = 制品 / "运行入口" / "启动.py"
            启动器.write_text("", encoding="utf-8")
            场景 = 绑定场景(验证器.验证场景.从字典(成功场景()), 制品)
            假进程 = object()
            参数 = types.SimpleNamespace(
                制品=临时, 只生成场景=False, 服务=0, 场景="",
                并发=1, 超时秒=1, 端口=45080, 直连地址="",
            )
            with mock.patch.object(验证器, "_加载场景", return_value=[场景]), \
                 mock.patch.object(验证器, "_启动制品", return_value=(假进程, 45080, {})), \
                 mock.patch.object(验证器, "_检查端口可用", return_value=(True, "")), \
                 mock.patch.object(验证器, "_发送请求", side_effect=RuntimeError("健康检查爆炸")), \
                 mock.patch.object(验证器, "_回收进程组", return_value={"已回收": True}) as 回收, \
                 mock.patch.object(验证器, "保存证据"):
                退出码 = 验证器.主函数(参数)
        self.assertNotEqual(退出码, 0)
        self.assertIn(mock.call(假进程), 回收.call_args_list)


@unittest.skipUnless(os.name == "posix", "进程组回收仅在 POSIX 验证")
class Test进程生命周期(unittest.TestCase):
    def test_自启动独立进程组且子进程一并回收(self):
        with tempfile.TemporaryDirectory() as 临时:
            根 = Path(临时)
            启动器 = 根 / "启动.py"
            启动器.write_text(
                "import subprocess,time,os\n"
                "子=subprocess.Popen(['sleep','60'])\n"
                "open('子进程.pid','w').write(str(子.pid))\n"
                "print('已启动 http://127.0.0.1:45080',flush=True)\n"
                "time.sleep(60)\n", encoding="utf-8")
            进程, _, _ = 验证器._启动制品(启动器, 根, 45080, 2, 1024)
            子pid = int((根 / "子进程.pid").read_text())
            self.assertNotEqual(os.getpgid(进程.pid), os.getpgid(0))
            回收 = 验证器._回收进程组(进程)
            self.assertTrue(回收["已回收"])
            self.assertIsNotNone(进程.poll())
            状态 = subprocess.run(["ps", "-p", str(子pid), "-o", "stat="], capture_output=True, text=True).stdout.strip()
            self.assertTrue(not 状态 or 状态.startswith("Z"), 状态)

    def test_静默启动硬超时且输出有界并回收(self):
        with tempfile.TemporaryDirectory() as 临时:
            根 = Path(临时)
            启动器 = 根 / "启动.py"
            启动器.write_text("import sys,time\nprint('X'*10000,flush=True)\ntime.sleep(60)\n", encoding="utf-8")
            开始 = time.monotonic()
            with self.assertRaisesRegex(RuntimeError, "启动超时") as 上下文:
                验证器._启动制品(启动器, 根, 45080, 0.3, 256)
            self.assertLess(time.monotonic() - 开始, 2)
            self.assertLess(len(str(上下文.exception).encode()), 1024)


class Test验证页安全与并发(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.HTML = (系统根 / "开发工具" / "HTML验证" / "验证页.html").read_text(encoding="utf-8")

    def test_动态内容不使用innerHTML且服务添加最小CSP(self):
        self.assertNotIn(".innerHTML", self.HTML)
        self.assertIn("Content-Security-Policy", 验证器路径.read_text(encoding="utf-8"))

    def test_页面使用真实有界并发池并显示峰值(self):
        self.assertIn("并发峰值", self.HTML)
        self.assertIn("运行有界并发池", self.HTML)
        self.assertNotIn("Promise.allSettled(场景表.map", self.HTML)

    def test_页面与核心同样校验完整值和返回契约(self):
        self.assertIn("预期.返回契约", self.HTML)
        self.assertIn("Object.prototype.hasOwnProperty.call(预期, '值')", self.HTML)


if __name__ == "__main__":
    unittest.main()
