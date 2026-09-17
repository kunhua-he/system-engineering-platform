"""第一批维修：网关安全、线程预算、预检、断开与结果契约回归。"""

from __future__ import annotations

import contextlib
import email.message
import http.client
import inspect
import io
import json
import os
import socket
import struct
import sys
import threading
import time
import unittest
import urllib.parse
import urllib.error
from pathlib import Path
from unittest.mock import Mock, patch

系统根 = Path(__file__).resolve().parents[2]
if str(系统根) not in sys.path:
    sys.path.insert(0, str(系统根))

from 公共契约.基础类型.结果类型 import 结果
from 运行核心.能力调用.HTTP连接器 import HTTP连接器
from 运行核心.能力调用.唯一能力调用 import 唯一能力调用服务
from 运行核心.统一网关.本地网关 import 本地网关服务器
from 运行核心.统一网关.流式HTTP import 流式HTTP服务器
from 运行核心.统一网关.网关核心 import 网关响应, 网关核心
from 公共契约.诊断.忽略记录 import 记录忽略


测试凭证变量 = "第一批网关测试凭证"
测试凭证 = "test-only-token"
允许来源 = "https://allowed.example"


class 可控后端:
    def __init__(self) -> None:
        self.进入健康 = threading.Event()
        self.放行健康 = threading.Event()
        self.阻塞健康 = False
        self.调用次数 = 0

    def 健康检查(self):
        self.进入健康.set()
        if self.阻塞健康:
            self.放行健康.wait(2.0)
        return 结果.成功结果({"状态": "健康", "填充": "填充" * 65536})

    def 调用(self, 能力id, 参数, **_关键字):
        self.调用次数 += 1
        return 结果.成功结果({"能力id": 能力id, "参数": 参数})


class 失败后端(可控后端):
    def 调用(self, 能力id, 参数, **_关键字):
        self.调用次数 += 1
        return 结果.失败("能力失败", "具体能力失败说明", 来源="测试能力")


class 网关用例(unittest.TestCase):
    def setUp(self) -> None:
        self.待停止: list[object] = []

    def tearDown(self) -> None:
        for 服务 in reversed(self.待停止):
            try:
                服务.优雅停止()
            except Exception as 错误:  # 允许忽略，但留痕（哲学第 3 条 2 项）
                记录忽略('测试_网关安全与有界并发.tearDown', 错误)

    def _启动主网关(self, 后端: 可控后端 | None = None, **覆盖):
        后端 = 后端 or 可控后端()
        配置 = {
            "凭证环境变量": 测试凭证变量,
            "允许来源表": {允许来源},
            "请求超时秒": 2,
            "请求体读取超时秒": 1,
            "并发上限": 2,
        }
        配置.update(覆盖)
        服务 = 本地网关服务器(网关核心实例=网关核心(后端), 端口=0, 配置=配置)
        成功, 消息 = 服务.启动()
        self.assertTrue(成功, 消息)
        self.待停止.append(服务)
        return 服务, 后端

    @staticmethod
    def _请求(服务, 方法: str, 路径: str, *, 数据=None, 请求头=None):
        连接 = http.client.HTTPConnection("127.0.0.1", 服务.端口, timeout=3)
        头 = dict(请求头 or {})
        if 数据 is not None:
            正文 = json.dumps(数据, ensure_ascii=False).encode("utf-8")
            头.setdefault("Content-Type", "application/json")
            头.setdefault("Content-Length", str(len(正文)))
        else:
            正文 = None
        连接.request(方法, urllib.parse.quote(路径, safe="/"), body=正文, headers=头)
        响应 = 连接.getresponse()
        原文 = 响应.read()
        结果数据 = json.loads(原文.decode("utf-8")) if 原文 else None
        状态码 = 响应.status
        响应头 = dict(响应.getheaders())
        连接.close()
        return 状态码, 结果数据, 响应头

    def test_生产主网关默认缺凭证即阻断且测试构造器显式分离(self):
        with patch.dict(os.environ, {"系统库网关凭证": ""}, clear=False):
            生产服务 = 本地网关服务器(网关核心实例=网关核心(可控后端()), 端口=0)
            成功, 消息 = 生产服务.启动()
        self.assertFalse(成功)
        self.assertIn("缺失凭证", 消息)

        创建测试服务器 = getattr(本地网关服务器, "创建测试服务器", None)
        self.assertTrue(callable(创建测试服务器), "测试/演示必须使用显式构造器")
        测试服务 = 创建测试服务器(网关核心实例=网关核心(可控后端()), 端口=0)
        self.assertTrue(测试服务.启动()[0])
        self.待停止.append(测试服务)

    def test_能力失败保留脱敏后的明确错误说明(self):
        with patch.dict(os.environ, {测试凭证变量: 测试凭证}, clear=False):
            服务, _ = self._启动主网关(失败后端())
            状态码, 数据, _ = self._请求(
                服务, "POST", "/网关/调用",
                数据={"能力id": "测试.失败能力", "参数": {}},
                请求头={"Authorization": f"Bearer {测试凭证}"},
            )
        self.assertEqual(状态码, 500)
        self.assertIsInstance(数据, dict)
        assert isinstance(数据, dict)
        self.assertFalse(数据["成功"])
        self.assertEqual(数据["错误码"], "能力失败")
        self.assertEqual(数据["错误说明"], "具体能力失败说明")

    def test_OPTIONS按来源和凭证策略返回204或403(self):
        with patch.dict(os.environ, {测试凭证变量: 测试凭证}, clear=False):
            服务, _ = self._启动主网关()
            允许头 = {
                "Origin": 允许来源,
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "Content-Type, Authorization",
            }
            try:
                状态码, 数据, 响应头 = self._请求(
                    服务, "OPTIONS", "/网关/调用", 请求头=允许头,
                )
            except http.client.RemoteDisconnected as 错误:
                self.fail(f"OPTIONS 未返回结构化响应：{错误}")
            self.assertEqual(状态码, 204)
            self.assertIsNone(数据)
            self.assertEqual(响应头.get("Access-Control-Allow-Origin"), 允许来源)
            self.assertEqual(响应头.get("Access-Control-Allow-Credentials"), "true")

            缺凭证策略头 = dict(允许头)
            缺凭证策略头["Access-Control-Request-Headers"] = "Content-Type"
            状态码, 数据, _ = self._请求(
                服务, "OPTIONS", "/网关/调用", 请求头=缺凭证策略头,
            )
            self.assertEqual(状态码, 403)
            self.assertEqual(数据["错误码"], "权限不足")

            状态码, 数据, _ = self._请求(
                服务, "OPTIONS", "/网关/调用",
                请求头={**允许头, "Origin": "https://evil.example"},
            )
            self.assertEqual(状态码, 403)
            self.assertEqual(数据["错误码"], "权限不足")

    def test_真实HTTP并发在线程预算前拒绝并返回结构化429(self):
        后端 = 可控后端()
        后端.阻塞健康 = True
        with patch.dict(os.environ, {测试凭证变量: 测试凭证}, clear=False):
            服务, _ = self._启动主网关(后端, 并发上限=1)
            第一结果: list[tuple] = []

            def 第一请求():
                第一结果.append(self._请求(
                    服务, "GET", "/健康",
                    请求头={"Authorization": f"Bearer {测试凭证}"},
                ))

            线程 = threading.Thread(target=第一请求)
            线程.start()
            self.assertTrue(后端.进入健康.wait(1.0), "首个请求未占用工作线程")
            状态码, 数据, _ = self._请求(
                服务, "GET", "/健康",
                请求头={"Authorization": f"Bearer {测试凭证}"},
            )
            self.assertEqual(状态码, 429)
            self.assertEqual(数据["错误码"], "限流")
            self.assertFalse(数据["成功"])
            self.assertEqual(
                {"请求id", "操作", "成功", "值", "错误码", "错误说明", "句柄", "耗时毫秒"}
                - set(数据), set(),
            )
            self.assertNotEqual(type(服务.服务器).__name__, "ThreadingHTTPServer")
            self.assertLessEqual(服务.服务器.活动工作线程数, 1)
            后端.放行健康.set()
            线程.join(2.0)
            self.assertFalse(线程.is_alive())
            截止 = time.monotonic() + 1.0
            while 服务.服务器.活动工作线程数 and time.monotonic() < 截止:
                time.sleep(0.01)
            self.assertEqual(服务.服务器.活动工作线程数, 0)

    def test_SSL关闭验证只允许受控本地策略(self):
        with patch.dict(os.environ, {测试凭证变量: 测试凭证}, clear=False):
            服务, 后端 = self._启动主网关(允许本地不验证SSL=False)
            请求 = {
                "能力id": "网络通信支持库.请求.发送请求",
                "参数": {"地址": "https://127.0.0.1:4443", "允许回环": True, "SSL验证": False},
                "获取句柄": False,
            }
            状态码, 数据, _ = self._请求(
                服务, "POST", "/网关/调用", 数据=请求,
                请求头={"Authorization": f"Bearer {测试凭证}"},
            )
            self.assertEqual(状态码, 403)
            self.assertEqual(数据["错误码"], "权限不足")
            self.assertEqual(后端.调用次数, 0)

            服务.优雅停止()
            self.待停止.remove(服务)
            服务, 后端 = self._启动主网关(允许本地不验证SSL=True)
            状态码, 数据, _ = self._请求(
                服务, "POST", "/网关/调用", 数据=请求,
                请求头={"Authorization": f"Bearer {测试凭证}"},
            )
            self.assertEqual(状态码, 200)
            self.assertTrue(数据["成功"])
            self.assertEqual(后端.调用次数, 1)

            请求["参数"]["地址"] = "https://example.com/"
            状态码, 数据, _ = self._请求(
                服务, "POST", "/网关/调用", 数据=请求,
                请求头={"Authorization": f"Bearer {测试凭证}"},
            )
            self.assertEqual(状态码, 403)
            self.assertEqual(数据["错误码"], "权限不足")
            self.assertEqual(后端.调用次数, 1)

    def test_客户端断开无堆栈噪声且线程预算归还(self):
        后端 = 可控后端()
        后端.阻塞健康 = True
        错误输出 = io.StringIO()
        with patch.dict(os.environ, {测试凭证变量: 测试凭证}, clear=False), contextlib.redirect_stderr(错误输出):
            服务, _ = self._启动主网关(后端, 并发上限=1)
            客户端 = socket.create_connection(("127.0.0.1", 服务.端口), timeout=2)
            客户端.sendall(
                (f"GET {urllib.parse.quote('/健康', safe='/')} HTTP/1.1\r\nHost: 127.0.0.1\r\n"
                 f"Authorization: Bearer {测试凭证}\r\nConnection: close\r\n\r\n").encode("ascii")
            )
            self.assertTrue(后端.进入健康.wait(1.0))
            客户端.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
            客户端.close()
            后端.放行健康.set()
            截止 = time.monotonic() + 2.0
            self.assertTrue(hasattr(服务.服务器, "活动工作线程数"), "服务器缺少线程预算计数")
            while 服务.服务器.活动工作线程数 and time.monotonic() < 截止:
                time.sleep(0.01)
            self.assertEqual(服务.服务器.活动工作线程数, 0)
            快照 = 服务.连接诊断快照()
            self.assertLessEqual(len(快照), 100)
        self.assertNotIn("Traceback", 错误输出.getvalue())


class 流式网关用例(unittest.TestCase):
    def test_流式OPTIONS和凭证策略一致(self):
        self.assertIn(
            "允许来源表", inspect.signature(流式HTTP服务器.__init__).parameters,
            "流式服务器缺少显式来源策略",
        )
        with patch.dict(os.environ, {测试凭证变量: 测试凭证}, clear=False):
            服务 = 流式HTTP服务器(
                端口=0, 凭证环境变量=测试凭证变量, 允许来源表={允许来源},
            )
            self.assertTrue(服务.启动()[0])
            try:
                连接 = http.client.HTTPConnection("127.0.0.1", 服务.端口, timeout=2)
                连接.request("OPTIONS", urllib.parse.quote("/网关/流式", safe="/"), headers={
                    "Origin": 允许来源,
                    "Access-Control-Request-Method": "POST",
                    "Access-Control-Request-Headers": "Content-Type, Authorization",
                })
                响应 = 连接.getresponse()
                self.assertEqual(响应.status, 204)
                self.assertEqual(响应.getheader("Access-Control-Allow-Credentials"), "true")
                响应.read()
                连接.close()

                连接 = http.client.HTTPConnection("127.0.0.1", 服务.端口, timeout=2)
                连接.request("OPTIONS", urllib.parse.quote("/网关/流式", safe="/"), headers={
                    "Origin": "https://evil.example",
                    "Access-Control-Request-Headers": "Authorization",
                })
                响应 = 连接.getresponse()
                self.assertEqual(响应.status, 403)
                数据 = json.loads(响应.read().decode("utf-8"))
                self.assertEqual(数据["错误码"], "权限不足")
                连接.close()
            finally:
                self.assertTrue(服务.优雅停止())


class 契约用例(unittest.TestCase):
    def test_HTTP错误响应读取后必须显式关闭(self):
        响应流 = io.BytesIO(json.dumps({
            "成功": False, "值": None, "错误码": "提供者不可用",
            "错误说明": "故意失败", "句柄": None, "请求id": "请求一", "耗时毫秒": 1,
        }, ensure_ascii=False).encode("utf-8"))
        错误响应 = urllib.error.HTTPError(
            "http://127.0.0.1/网关/调用", 503, "Service Unavailable",
            email.message.Message(), 响应流)
        开放器 = Mock()
        开放器.open.side_effect = 错误响应
        with patch("urllib.request.build_opener", return_value=开放器):
            状态码, 数据, _ = HTTP连接器()._请求({"请求id": "请求一"})
        self.assertEqual(状态码, 503)
        self.assertIsNotNone(数据)
        assert 数据 is not None
        self.assertEqual(数据["错误码"], "提供者不可用")
        self.assertTrue(响应流.closed, "HTTPError响应流必须在返回前关闭")

    # ── 网关字典结果判定：按现行哲学三类分桶（哲学第 5 条 2 项、第 3 条 2 项）──
    # 现行口径（权威=`网关核心._设置后端字典结果` docstring）：信封只增不改不删、缺键补默认；
    # 旧口径「缺任一必填键即判 502 返回结果不符合契约」是实现少写一个键就整条链路失败的
    # 兼容性硬点，**已废止**。三类判定：
    #   ① 缺 `成功` 且未声明 `错误码`/`错误说明` → 业务值，按成功返回该字典；
    #   ② 缺 `成功` 但声明了 `错误码`/`错误说明` → 失败，取该错误码（缺则 `内部错误`）；
    #   ③ 键存在但类型不符（`成功` 非真布尔 / `错误码`、`错误说明` 非文本）→ 仍判违约。
    # 本组用例重写自旧用例 `test_缺统一结果字段的字典绝不包装成功`（守的是已废止口径）。

    @staticmethod
    def _后端字典响应(值):
        """走网关唯一字典结果入口取信封；判定逻辑不在本文件重写。"""
        响应 = 网关响应()
        网关核心()._设置后端字典结果(响应, 值)
        return 响应

    def test_缺成功键且未声明错误的字典按业务值成功返回(self):
        """① 缺 `成功`、也没有 `错误码`/`错误说明`：这是业务字典，不是契约违约。"""
        业务值 = {"消息": "看似成功"}
        响应 = self._后端字典响应(业务值)
        self.assertTrue(响应.成功)
        self.assertEqual(响应.值, {"消息": "看似成功"})
        self.assertEqual(响应.错误码, "")
        self.assertEqual(响应.错误说明, "")

        # 带 `值` 键但没有 `成功`：仍是业务字典，整字典透出，不得被拆包成信封。
        响应 = self._后端字典响应({"值": 1, "业务字段": 2})
        self.assertTrue(响应.成功)
        self.assertEqual(响应.值, {"值": 1, "业务字段": 2})
        self.assertEqual(响应.错误码, "")

    def test_缺成功键但声明了错误码的字典判失败并取该错误码(self):
        """② 声明了失败就必须失败（哲学第 3 条 2 项：失败必须明确），错误码按声明取。"""
        响应 = self._后端字典响应(
            {"错误码": "能力失败", "错误说明": "具体能力失败说明"})
        self.assertFalse(响应.成功)
        self.assertEqual(响应.错误码, "能力失败")
        self.assertEqual(响应.错误说明, "具体能力失败说明")
        self.assertIsNone(响应.值)
        self.assertNotEqual(响应.错误码, "返回结果不符合契约")

    def test_缺成功键只声明错误说明时错误码回落内部错误(self):
        """②（续）只有 `错误说明`、或 `错误码` 为空串：失败，错误码回落 `内部错误`。"""
        响应 = self._后端字典响应({"错误说明": "没写错误码的失败"})
        self.assertFalse(响应.成功)
        self.assertEqual(响应.错误码, "内部错误")
        self.assertEqual(响应.错误说明, "没写错误码的失败")
        self.assertIsNone(响应.值)

        响应 = self._后端字典响应({"错误码": ""})
        self.assertFalse(响应.成功)
        self.assertEqual(响应.错误码, "内部错误")

    def test_成功键存在但不是真布尔仍判契约违约(self):
        """③ 类型漂移必拦：1/0/文本/None/容器都不是真布尔，绝不按真值放行。"""
        for 非法 in (1, 0, "是", "true", None, [], {}):
            with self.subTest(成功值=repr(非法)):
                响应 = self._后端字典响应(
                    {"成功": 非法, "值": {"真实": 1}, "错误码": "", "错误说明": ""})
                self.assertFalse(响应.成功)
                self.assertEqual(响应.错误码, "返回结果不符合契约")
                self.assertIsNone(响应.值)

    def test_错误码或错误说明不是文本仍判契约违约(self):
        """③（续）错误码/错误说明 类型漂移同样必拦，不许静默补默认掩过去。"""
        for 键, 非法值 in (("错误码", 500), ("错误码", None), ("错误码", ["码"]),
                          ("错误说明", 3.14), ("错误说明", {"说明": "文本"})):
            with self.subTest(字段=键, 值=repr(非法值)):
                响应 = self._后端字典响应({"成功": True, "值": {"真实": 1}, 键: 非法值})
                self.assertFalse(响应.成功)
                self.assertEqual(响应.错误码, "返回结果不符合契约")
                self.assertIsNone(响应.值)

    def test_成功真透出值_成功假取错误码_缺键补默认(self):
        """④ 正常信封：成功真透出 `值`；成功假取错误码；缺 `值`/`错误码` 键补默认。"""
        响应 = self._后端字典响应(
            {"成功": True, "值": {"真实": 1}, "错误码": "", "错误说明": ""})
        self.assertTrue(响应.成功)
        self.assertEqual(响应.值, {"真实": 1})
        self.assertEqual(响应.错误码, "")

        响应 = self._后端字典响应({"成功": True})  # 缺 值/错误码/错误说明 三键
        self.assertTrue(响应.成功)
        self.assertIsNone(响应.值)
        self.assertEqual(响应.错误码, "")

        响应 = self._后端字典响应({
            "成功": False, "值": None, "错误码": "提供者不可用", "错误说明": "服务不可达",
        })
        self.assertFalse(响应.成功)
        self.assertEqual(响应.错误码, "提供者不可用")
        self.assertEqual(响应.错误说明, "服务不可达")
        self.assertIsNone(响应.值)

        响应 = self._后端字典响应(
            {"成功": False, "值": None, "错误码": "", "错误说明": ""})
        self.assertFalse(响应.成功)
        self.assertEqual(响应.错误码, "内部错误")

    def test_非字典后端结果原样透出为业务值(self):
        """非字典结果本就不是信封：按业务值透出，这条不受缺键补默认影响。"""
        for 值 in ("裸文本", 3, None, [1, 2], True):
            with self.subTest(值=repr(值)):
                响应 = self._后端字典响应(值)
                self.assertTrue(响应.成功)
                self.assertEqual(响应.值, 值)
                self.assertEqual(响应.错误码, "")

    def test_唯一能力调用层字典判定仍为旧口径_与网关层差异待裁决(self):
        """**分层差异登记**（不是对旧口径的背书，也不是放宽断言）：

        - 网关层（本类上面 7 条）已按现行哲学「缺键补默认、类型漂移必拦」；
        - 能力调用层 `唯一能力调用服务._规范化结果` 仍是「跨包字典必须完整满足统一结果契约，
          缺键即判 `返回结果不符合契约`」——即**实现返回裸业务字典在真实调用链
          （网关 → 后端核心.调用 → 唯一能力调用服务.调用能力）上仍会被判违约**，
          与已废止的兼容性硬点同源（同一旧口径还见于 `网关核心._能力结果类型合法`）。
        裁决前不得改动实现行为，故此处如实锁定现状：实现一旦对齐，本条必须同步改成断言成功；
        若确认保留旧口径，则必须与 网关核心._设置后端字典结果 正式分治并写进口径文档。
        """
        结果对象 = 唯一能力调用服务._规范化结果({"状态": "看似成功"})
        self.assertFalse(结果对象.成功)
        self.assertEqual(结果对象.错误码, "返回结果不符合契约")
        self.assertEqual(结果对象.错误说明, "字典返回缺少统一结果字段")

    def test_完整统一结果字典才可转换(self):
        结果对象 = 唯一能力调用服务._规范化结果({
            "成功": True, "值": {"真实": 1}, "错误码": "", "错误说明": "",
        })
        self.assertTrue(结果对象.成功)
        self.assertEqual(结果对象.值, {"真实": 1})

    def test_统一句柄冻结为整数且连接器只接受同一类型(self):
        合法 = {
            "请求id": "请求一", "成功": True, "值": None,
            "错误码": "", "错误说明": "", "句柄": 7, "耗时毫秒": 1.0,
        }
        self.assertTrue(HTTP连接器._返回结构合法(合法))
        self.assertFalse(HTTP连接器._返回结构合法({**合法, "句柄": "7"}))
        句柄注解 = inspect.signature(唯一能力调用服务.调用能力).parameters["句柄"].annotation
        self.assertEqual(句柄注解, "int | None")
        契约 = json.loads((系统根 / "公共契约" / "HTTP路由契约.json").read_text(encoding="utf-8"))
        self.assertIn("整数型", 契约["唯一执行入口"]["请求"]["句柄"])
        self.assertEqual(契约["唯一执行入口"]["方法"], "POST")
        self.assertEqual(契约["唯一执行入口"]["路径"], "/网关/调用")


if __name__ == "__main__":
    unittest.main(verbosity=2)
