"""HTTP连接器黑盒测试：只通过真实 HTTP 验证连接器边界。

不导入能力实现，不调用网关核心；用真实 ThreadingHTTPServer 作为被测边界，
验证请求体、返回结构、整数句柄和传输失败语义。
"""

from __future__ import annotations

import json
import sqlite3
import threading
import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
import sys
from types import SimpleNamespace

系统根 = Path(__file__).resolve().parents[2]
if str(系统根) not in sys.path:
    sys.path.insert(0, str(系统根))

from 运行核心.能力调用.HTTP连接器 import HTTP连接器


def _读取HTTP错误JSON(错误: urllib.error.HTTPError) -> dict:
    try:
        return json.loads(错误.read().decode("utf-8"))
    finally:
        错误.close()
from 运行核心.统一网关.网关核心 import 网关核心
from 运行核心.统一网关.本地网关 import 本地网关服务器
from 公共契约.基础类型.结果类型 import 结果
from 运行核心.资源协调.句柄服务 import 资源句柄服务


class _测试处理器(BaseHTTPRequestHandler):
    请求体: dict = {}
    返回数据: object = {"成功": True, "值": {"结果": 42}, "错误码": "", "错误说明": ""}
    返回类型: str = "json"
    状态码 = 200
    请求次数 = 0
    延迟秒 = 0.0
    锁 = threading.Lock()

    def log_message(self, 格式: str, *参数) -> None:
        return

    def _安全写(self, 正文: bytes) -> None:
        try:
            self.wfile.write(正文)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_POST(self) -> None:
        长度 = int(self.headers.get("Content-Length", "0"))
        原文 = self.rfile.read(长度)
        with type(self).锁:
            type(self).请求次数 += 1
            try:
                type(self).请求体 = json.loads(原文.decode("utf-8"))
            except Exception:
                type(self).请求体 = {}
        if type(self).延迟秒:
            time.sleep(type(self).延迟秒)
        if type(self).返回类型 == "空":
            self.send_response(200)
            self.end_headers()
            return
        if type(self).返回类型 == "非JSON":
            正文 = b"not-json"
            self.send_response(200)
            self.send_header("Content-Length", str(len(正文)))
            self.end_headers()
            self._安全写(正文)
            return
        if type(self).返回类型 == "超大":
            正文 = b"x" * (4 * 1024 * 1024 + 1)
            self.send_response(200)
            self.send_header("Content-Length", str(len(正文)))
            self.end_headers()
            self._安全写(正文)
            return
        返回数据 = dict(type(self).返回数据)
        返回数据.setdefault("请求id", type(self).请求体.get("请求id", "响应请求"))
        返回数据.setdefault("句柄", None)
        返回数据.setdefault("耗时毫秒", 0)
        正文 = json.dumps(返回数据, ensure_ascii=False).encode("utf-8")
        self.send_response(type(self).状态码)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(正文)))
        self.end_headers()
        self._安全写(正文)


class 测试HTTP连接器(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.服务器 = ThreadingHTTPServer(("127.0.0.1", 0), _测试处理器)
        cls.线程 = threading.Thread(target=cls.服务器.serve_forever, daemon=True)
        cls.线程.start()
        cls.连接器 = HTTP连接器(网关端口=cls.服务器.server_address[1], 默认超时秒=2)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.服务器.shutdown()
        cls.服务器.server_close()
        cls.线程.join(timeout=2)

    def setUp(self) -> None:
        _测试处理器.请求体 = {}
        _测试处理器.请求次数 = 0
        _测试处理器.返回类型 = "json"
        _测试处理器.状态码 = 200
        _测试处理器.返回数据 = {"成功": True, "值": {"结果": 42}, "错误码": "", "错误说明": ""}
        _测试处理器.延迟秒 = 0.0

    def test_健康检查编码中文路径并返回成功(self) -> None:
        """健康探测必须能编码中文路径，且使用连接器超时配置。"""
        原处理 = _测试处理器.do_GET if hasattr(_测试处理器, "do_GET") else None
        def 健康处理(请求):
            请求.send_response(200)
            请求.send_header("Content-Length", "0")
            请求.end_headers()
        _测试处理器.do_GET = 健康处理
        try:
            self.assertTrue(self.连接器.健康检查())
        finally:
            if 原处理 is None:
                delattr(_测试处理器, "do_GET")
            else:
                _测试处理器.do_GET = 原处理

    def test_请求级超时约束真实等待时间(self) -> None:
        """显式超时应传到 urlopen，而不是被默认超时覆盖。"""
        _测试处理器.延迟秒 = 0.8
        开始 = time.monotonic()
        结果 = self.连接器.调用能力("测试.读取", {}, 超时秒=0.1)
        self.assertFalse(结果["成功"])
        self.assertEqual(结果["错误码"], "超时")
        self.assertLess(time.monotonic() - 开始, 0.6)

    def test_真实HTTP成功并透传整数句柄(self) -> None:
        _测试处理器.返回数据 = {
            "成功": True, "值": {"结果": 42}, "错误码": "", "错误说明": "", "句柄": 428101,
        }
        结果 = self.连接器.调用能力(
            "测试.读取", {"资源id": "资源甲"}, 句柄=428101,
            项目id="项目甲", 用户id="用户甲",
        )
        self.assertTrue(结果["成功"])
        self.assertEqual(结果["句柄"], 428101)
        self.assertEqual(_测试处理器.请求体["句柄"], 428101)
        self.assertEqual(_测试处理器.请求体["能力id"], "测试.读取")

    def test_句柄只能是整数不能传字符串(self) -> None:
        结果 = self.连接器.调用能力("测试.读取", {}, 句柄="428101")
        self.assertFalse(结果["成功"])
        self.assertEqual(结果["错误码"], "参数不合法")
        self.assertIn("句柄", 结果["错误说明"])
        self.assertEqual(_测试处理器.请求次数, 0)

    def test_非法参数不发HTTP请求(self) -> None:
        结果 = self.连接器.调用能力("测试.读取", [])
        self.assertFalse(结果["成功"])
        self.assertEqual(结果["错误码"], "参数不合法")
        self.assertEqual(_测试处理器.请求次数, 0)

    def test_不可JSON编码参数返回统一参数错误(self) -> None:
        """字典内嵌不可传输值不能把 TypeError 泄漏给调用方。"""
        结果 = self.连接器.调用能力("测试.读取", {"集合": {1, 2}})
        self.assertFalse(结果["成功"])
        self.assertEqual(结果["错误码"], "参数不合法")
        self.assertIn("JSON", 结果["错误说明"])
        self.assertEqual(_测试处理器.请求次数, 0)

    def test_空响应拒绝成功(self) -> None:
        _测试处理器.返回类型 = "空"
        结果 = self.连接器.调用能力("测试.读取", {})
        self.assertFalse(结果["成功"])
        self.assertEqual(结果["错误码"], "返回结果不符合契约")

    def test_非JSON响应拒绝成功(self) -> None:
        _测试处理器.返回类型 = "非JSON"
        结果 = self.连接器.调用能力("测试.读取", {})
        self.assertFalse(结果["成功"])
        self.assertEqual(结果["错误码"], "返回结果不符合契约")

    def test_超大响应被拒绝(self) -> None:
        _测试处理器.返回类型 = "超大"
        结果 = self.连接器.调用能力("测试.读取", {})
        self.assertFalse(结果["成功"])
        self.assertEqual(结果["错误码"], "返回结果不符合契约")

    def test_成功字段非布尔值拒绝成功(self) -> None:
        """返回成功字段不是布尔值时，不能被 bool 字符串强转放行。"""
        _测试处理器.返回数据 = {
            "成功": "false", "值": {"结果": "伪成功"},
            "错误码": "内部错误", "错误说明": "真实失败",
        }
        结果 = self.连接器.调用能力("测试.读取", {})
        self.assertFalse(结果["成功"])
        self.assertEqual(结果["错误码"], "返回结果不符合契约")

    def test_响应请求id不一致拒绝成功(self) -> None:
        """响应必须回显本次请求 id，防止响应串线。"""
        _测试处理器.返回数据 = {
            "成功": True, "值": {"结果": 42}, "错误码": "", "错误说明": "",
            "请求id": "伪造请求",
        }
        结果 = self.连接器.调用能力("测试.读取", {}, 请求id="本次请求")
        self.assertFalse(结果["成功"])
        self.assertEqual(结果["错误码"], "返回结果不符合契约")
        self.assertEqual(结果["请求id"], "本次请求")

    def test_HTTP500携带成功JSON不得返回成功(self) -> None:
        """传输层 5xx 优先于正文成功字段。"""
        _测试处理器.状态码 = 500
        结果 = self.连接器.调用能力("测试.读取", {}, 请求id="服务端错误")
        self.assertFalse(结果["成功"])
        self.assertEqual(结果["错误码"], "提供者不可用")

    def test_网关不可达返回具体错误(self) -> None:
        连接器 = HTTP连接器(网关端口=1, 默认超时秒=0.5)
        结果 = 连接器.调用能力("测试.读取", {})
        self.assertFalse(结果["成功"])
        self.assertIn(结果["错误码"], {"提供者不可用", "超时"})
        self.assertIn("网关", 结果["错误说明"])


class _假后端:
    """只用于真实 HTTP 集成测试的最小后端，不代替正式能力实现。"""

    调用次数 = 0
    最后句柄 = None
    资源句柄服务 = None
    返回对象 = None

    def 资源状态(self, 句柄, *, 项目id="", 所有者=""):
        return self.资源句柄服务.状态(句柄, 项目id=项目id, 所有者=所有者)

    def 资源关闭(self, 句柄, *, 项目id="", 所有者=""):
        return self.资源句柄服务.关闭(句柄, 项目id=项目id, 所有者=所有者)

    def 资源续租(self, 句柄, *, 租约秒=300, 项目id="", 所有者=""):
        return self.资源句柄服务.续租(句柄, 租约秒=租约秒, 项目id=项目id, 所有者=所有者)

    def 健康检查(self) -> 结果:
        return 结果.成功结果({"状态": "健康"})

    def 调用(self, 能力id, 参数, *, 上下文, 超时秒):
        if 能力id != "测试.HTTP能力":
            return 结果.失败("能力不存在", f"能力未注册: {能力id}")
        type(self).调用次数 += 1
        type(self).最后句柄 = 上下文.句柄
        if type(self).返回对象 is not None:
            return type(self).返回对象
        return 结果.成功结果({"收到": 参数, "通过": True})


class 测试HTTP连接器接入统一网关(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        _假后端.调用次数 = 0
        _假后端.最后句柄 = None
        _假后端.返回对象 = None
        cls.临时目录 = tempfile.TemporaryDirectory(prefix="HTTP连接器账本_")
        _假后端.资源句柄服务 = 资源句柄服务(Path(cls.临时目录.name) / "状态")
        cls.后端 = _假后端()
        核心 = 网关核心(cls.后端)
        cls.网关 = 本地网关服务器.创建测试服务器(网关核心实例=核心, 端口=0)
        成功, 说明 = cls.网关.启动()
        if not 成功:
            raise RuntimeError(说明)
        cls.连接器 = HTTP连接器(网关端口=cls.网关.端口, 默认超时秒=2)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.网关.优雅停止()
        assert _假后端.资源句柄服务 is not None
        _假后端.资源句柄服务.关闭服务()
        cls.临时目录.cleanup()

    def test_二进制参数按字节集契约往返(self) -> None:
        """bytes 参数必须可经 JSON 传输并在网关后端还原为 bytes。"""
        结果 = self.连接器.调用能力("测试.HTTP能力", {
            "字节": b"\x00\x01" + "华哥".encode("utf-8"),
            "嵌套": [bytearray(b"abc"), {"视图": memoryview(b"def")}],
        })
        self.assertTrue(结果["成功"])
        self.assertEqual(结果["值"]["收到"], {
            "字节": b"\x00\x01" + "华哥".encode("utf-8"),
            "嵌套": [b"abc", {"视图": b"def"}],
        })

    def test_统一入口真实调用返回值(self) -> None:
        结果字典 = self.连接器.调用能力("测试.HTTP能力", {"输入": "华哥"})
        self.assertTrue(结果字典["成功"])
        self.assertEqual(结果字典["值"]["收到"], {"输入": "华哥"})

    def test_网关拒绝后端返回的非逻辑型成功字段(self) -> None:
        """后端返回字符串成功标记时，网关不能把它当作逻辑型放行。"""
        原返回对象 = _假后端.返回对象
        _假后端.返回对象 = SimpleNamespace(
            成功="false", 值={"伪成功": True}, 错误码="内部错误", 错误说明="真实失败",
        )
        try:
            结果字典 = self.连接器.调用能力("测试.HTTP能力", {})
        finally:
            _假后端.返回对象 = 原返回对象
        self.assertFalse(结果字典["成功"])
        self.assertEqual(结果字典["错误码"], "返回结果不符合契约")

    def test_网关拒绝请求中的非逻辑型获取句柄(self) -> None:
        """请求中的“获取句柄”若存在，必须是真逻辑型。"""
        地址 = f"http://127.0.0.1:{self.网关.端口}/网关/调用"
        请求 = urllib.request.Request(
            urllib.parse.quote(地址, safe=":/@._-"),
            data=json.dumps({
                "能力id": "测试.HTTP能力", "参数": {}, "获取句柄": "false",
            }).encode("utf-8"),
            method="POST", headers={"Content-Type": "application/json"},
        )
        with self.assertRaises(urllib.error.HTTPError) as 上下文:
            urllib.request.urlopen(请求, timeout=2)
        self.assertEqual(上下文.exception.code, 400)
        响应 = _读取HTTP错误JSON(上下文.exception)
        self.assertFalse(响应["成功"])
        self.assertEqual(响应["错误码"], "参数不合法")

    def test_网关拒绝GET执行旁路(self) -> None:
        """执行入口固定为 POST；GET 携带请求体也不得触发能力。"""
        地址 = f"http://127.0.0.1:{self.网关.端口}/网关/调用"
        请求 = urllib.request.Request(
            urllib.parse.quote(地址, safe=":/@._-"),
            data=json.dumps({"能力id": "测试.HTTP能力", "参数": {}}).encode("utf-8"),
            method="GET", headers={"Content-Type": "application/json"},
        )
        with self.assertRaises(urllib.error.HTTPError) as 上下文:
            urllib.request.urlopen(请求, timeout=2)
        self.assertEqual(上下文.exception.code, 405)
        响应 = _读取HTTP错误JSON(上下文.exception)
        self.assertFalse(响应["成功"])
        self.assertEqual(响应["错误码"], "方法不允许")

    def test_边界拒绝仍返回完整统一结果(self) -> None:
        """真实 HTTP 边界错误不能丢失请求 id/操作/句柄/耗时字段。"""
        地址 = f"http://127.0.0.1:{self.网关.端口}/网关/调用"
        请求 = urllib.request.Request(
            urllib.parse.quote(地址, safe=":/@._-"), data=b"{}", method="POST",
            headers={"Content-Type": "text/plain", "X-Request-ID": "boundary-request"},
        )
        with self.assertRaises(urllib.error.HTTPError) as 上下文:
            urllib.request.urlopen(请求, timeout=2)
        响应 = _读取HTTP错误JSON(上下文.exception)
        self.assertEqual(上下文.exception.code, 400)
        self.assertEqual(
            set(("请求id", "操作", "成功", "值", "错误码", "错误说明", "句柄", "耗时毫秒")),
            set(响应),
        )
        self.assertEqual(响应["请求id"], "boundary-request")
        self.assertEqual(响应["错误码"], "参数不合法")

    def test_网关拒绝请求文本字段类型漂移(self) -> None:
        """文本字段传入数字/列表时，网关不能用 str 强转后放行。"""
        文本字段 = (
            "能力id", "目标", "契约版本", "请求id", "项目id", "用户id",
            "会话id", "任务id", "提供者",
        )
        for 字段 in 文本字段:
            请求数据 = {"能力id": "测试.HTTP能力", "参数": {}, 字段: 123}
            if 字段 == "能力id":
                请求数据[字段] = 123
            地址 = f"http://127.0.0.1:{self.网关.端口}/网关/调用"
            请求 = urllib.request.Request(
                urllib.parse.quote(地址, safe=":/@._-"),
                data=json.dumps(请求数据).encode("utf-8"),
                method="POST", headers={"Content-Type": "application/json"},
            )
            with self.assertRaises(urllib.error.HTTPError) as 上下文:
                urllib.request.urlopen(请求, timeout=2)
            self.assertEqual(上下文.exception.code, 400, 字段)
            响应 = _读取HTTP错误JSON(上下文.exception)
            self.assertEqual(响应["错误码"], "参数不合法", 字段)

    def test_网关拒绝数值字段文本和逻辑值漂移(self) -> None:
        """超时秒显式传入文本或逻辑值时，网关不能隐式转换。"""
        for 值 in ("1", True):
            地址 = f"http://127.0.0.1:{self.网关.端口}/网关/调用"
            请求 = urllib.request.Request(
                urllib.parse.quote(地址, safe=":/@._-"),
                data=json.dumps({
                    "能力id": "测试.HTTP能力", "参数": {}, "超时秒": 值,
                }).encode("utf-8"),
                method="POST", headers={"Content-Type": "application/json"},
            )
            with self.assertRaises(urllib.error.HTTPError) as 上下文:
                urllib.request.urlopen(请求, timeout=2)
            self.assertEqual(上下文.exception.code, 400)
            响应 = _读取HTTP错误JSON(上下文.exception)
            self.assertFalse(响应["成功"])
            self.assertEqual(响应["错误码"], "参数不合法")

    def test_请求id相同参数幂等重放不同参数冲突(self) -> None:
        """同请求id同参数只执行一次；改参数必须在网关边界冲突。"""
        请求id = "固定幂等请求"
        调用前 = _假后端.调用次数
        首次 = self.连接器.调用能力(
            "测试.HTTP能力", {"输入": "相同"}, 请求id=请求id,
        )
        重放 = self.连接器.调用能力(
            "测试.HTTP能力", {"输入": "相同"}, 请求id=请求id,
        )
        self.assertTrue(首次["成功"])
        for 字段 in ("成功", "值", "错误码", "错误说明", "句柄", "请求id"):
            self.assertEqual(重放[字段], 首次[字段], 字段)
        self.assertIsInstance(重放["耗时毫秒"], (int, float))
        self.assertEqual(_假后端.调用次数, 调用前 + 1)
        冲突 = self.连接器.调用能力(
            "测试.HTTP能力", {"输入": "不同"}, 请求id=请求id,
        )
        self.assertFalse(冲突["成功"])
        self.assertEqual(冲突["错误码"], "幂等键冲突")
        self.assertEqual(_假后端.调用次数, 调用前 + 1)

    def test_同一请求id并发只执行一次(self) -> None:
        """同一幂等键并发到达时，网关只允许一次真实能力执行。"""
        请求id = "并发幂等请求"
        调用前 = _假后端.调用次数

        def 发送(_: int) -> dict:
            return self.连接器.调用能力(
                "测试.HTTP能力", {"输入": "并发相同"}, 请求id=请求id,
            )

        with ThreadPoolExecutor(max_workers=8) as 并发池:
            结果表 = list(并发池.map(发送, range(8)))
        self.assertEqual(len(结果表), 8)
        self.assertTrue(all(结果["成功"] for 结果 in 结果表))
        self.assertEqual(
            {json.dumps(结果["值"], ensure_ascii=False, sort_keys=True) for 结果 in 结果表},
            {json.dumps({"收到": {"输入": "并发相同"}, "通过": True}, ensure_ascii=False, sort_keys=True)},
        )
        self.assertEqual({结果["句柄"] for 结果 in 结果表}, {结果表[0]["句柄"]})
        self.assertEqual(_假后端.调用次数, 调用前 + 1)

    def test_网关参数非对象原地拒绝(self) -> None:
        """空列表不能被网关的真假值兜底转换成空对象后放行。"""
        地址 = f"http://127.0.0.1:{self.网关.端口}/网关/调用"
        请求 = urllib.request.Request(
            urllib.parse.quote(地址, safe=":/@._-"),
            data=json.dumps({"能力id": "测试.HTTP能力", "参数": []}).encode("utf-8"),
            method="POST", headers={"Content-Type": "application/json"},
        )
        with self.assertRaises(urllib.error.HTTPError) as 上下文:
            urllib.request.urlopen(请求, timeout=2)
        self.assertEqual(上下文.exception.code, 400)
        响应 = _读取HTTP错误JSON(上下文.exception)
        self.assertFalse(响应["成功"])
        self.assertEqual(响应["错误码"], "参数不合法")

    def test_首次调用返回网关生成的整数句柄后续可用(self) -> None:
        首次 = self.连接器.调用能力("测试.HTTP能力", {"输入": "首次"})
        self.assertTrue(首次["成功"])
        self.assertIsInstance(首次["句柄"], int)
        self.assertGreaterEqual(首次["句柄"], 1)
        后续 = self.连接器.调用能力("测试.HTTP能力", {"输入": "后续"}, 句柄=首次["句柄"])
        self.assertTrue(后续["成功"])
        self.assertEqual(_假后端.最后句柄, 首次["句柄"])
        账本记录 = self.后端.资源句柄服务.权威状态.读取句柄(首次["句柄"])
        self.assertIsNotNone(账本记录)
        self.assertEqual(账本记录["状态"], "有效")

    def test_伪造整数句柄在网关边界拒绝(self) -> None:
        调用前 = _假后端.调用次数
        结果字典 = self.连接器.调用能力("测试.HTTP能力", {}, 句柄=123456)
        self.assertFalse(结果字典["成功"])
        self.assertEqual(结果字典["错误码"], "句柄无效")
        self.assertEqual(_假后端.调用次数, 调用前)

    def test_释放后账本失效且再次调用返回句柄超时(self) -> None:
        首次 = self.连接器.调用能力("测试.HTTP能力", {})
        句柄 = 首次["句柄"]
        地址 = f"http://127.0.0.1:{self.网关.端口}/网关/调用"
        请求体 = json.dumps({
            "操作": "资源关闭", "句柄": 句柄, "项目id": "", "用户id": "",
        }).encode("utf-8")
        请求 = urllib.request.Request(
            urllib.parse.quote(地址, safe=":/@._-"), data=请求体, method="POST",
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(请求, timeout=2) as 响应:
            关闭结果 = json.loads(响应.read().decode("utf-8"))
        self.assertTrue(关闭结果["成功"])
        再次 = self.连接器.调用能力("测试.HTTP能力", {}, 句柄=句柄)
        self.assertFalse(再次["成功"])
        self.assertEqual(再次["错误码"], "句柄已过期")
        账本记录 = self.后端.资源句柄服务.权威状态.读取句柄(句柄)
        self.assertEqual(账本记录["状态"], "已失效")
        self.assertEqual(账本记录["失效原因"], "主动释放")
        数据库 = sqlite3.connect(str(Path(self.临时目录.name) / "状态" / "权威状态.db"))
        try:
            租约 = 数据库.execute(
                "SELECT 已回收 FROM 租约 WHERE 句柄id=?", (句柄,)
            ).fetchone()
            证据数 = 数据库.execute(
                "SELECT COUNT(*) FROM 回收证据 WHERE 句柄id=?", (句柄,)
            ).fetchone()[0]
        finally:
            数据库.close()
        self.assertEqual(租约, (1,))
        self.assertEqual(证据数, 1)

    def test_沉默超时自动失效并写入账本(self) -> None:
        原超时 = self.后端.资源句柄服务.默认超时秒
        self.后端.资源句柄服务.默认超时秒 = 0.03
        try:
            首次 = self.连接器.调用能力("测试.HTTP能力", {})
            句柄 = 首次["句柄"]
            time.sleep(0.06)
            再次 = self.连接器.调用能力("测试.HTTP能力", {}, 句柄=句柄)
            self.assertFalse(再次["成功"])
            self.assertEqual(再次["错误码"], "句柄已过期")
            账本记录 = self.后端.资源句柄服务.权威状态.读取句柄(句柄)
            self.assertEqual(账本记录["状态"], "已失效")
            self.assertEqual(账本记录["失效原因"], "句柄超时")
        finally:
            self.后端.资源句柄服务.默认超时秒 = 原超时

    def test_统一入口批量多线程每个请求都有明确返回(self) -> None:
        def 发送(序号: int) -> dict:
            return self.连接器.调用能力("测试.HTTP能力", {"序号": 序号})

        with ThreadPoolExecutor(max_workers=8) as 并发池:
            结果表 = list(并发池.map(发送, range(32)))
        self.assertEqual(len(结果表), 32)
        self.assertTrue(all(isinstance(结果, dict) for 结果 in 结果表))
        self.assertTrue(all(结果["成功"] for 结果 in 结果表))
        self.assertTrue(all(结果["请求id"] and 结果["句柄"] for 结果 in 结果表))

        错误 = self.连接器.调用能力("测试.HTTP能力", [])
        self.assertFalse(错误["成功"])
        self.assertEqual(错误["错误码"], "参数不合法")

    def test_旧网关请求入口直接拒绝(self) -> None:
        地址 = f"http://127.0.0.1:{self.网关.端口}/网关/请求"
        请求 = urllib.request.Request(
            urllib.parse.quote(地址, safe=":/@._-"),
            data=b"{}", method="POST", headers={"Content-Type": "application/json"},
        )
        with self.assertRaises(urllib.error.HTTPError) as 上下文:
            urllib.request.urlopen(请求, timeout=2)
        self.assertEqual(上下文.exception.code, 404)
        上下文.exception.close()

    def test_非有限数与超长请求id在HTTP边界拒绝(self) -> None:
        地址 = f"http://127.0.0.1:{self.网关.端口}/网关/调用"
        for 原文 in (
            '{"能力id":"测试.HTTP能力","参数":{"值":NaN}}'.encode("utf-8"),
            json.dumps({"能力id": "测试.HTTP能力", "请求id": "A" * 65}).encode("utf-8"),
        ):
            请求 = urllib.request.Request(
                urllib.parse.quote(地址, safe=":/@._-"), data=原文,
                method="POST", headers={"Content-Type": "application/json"},
            )
            with self.assertRaises(urllib.error.HTTPError) as 上下文:
                urllib.request.urlopen(请求, timeout=2)
            self.assertEqual(上下文.exception.code, 400)
            响应 = _读取HTTP错误JSON(上下文.exception)
            self.assertFalse(响应["成功"])
            self.assertEqual(响应["错误码"], "参数不合法")


if __name__ == "__main__":
    unittest.main()
