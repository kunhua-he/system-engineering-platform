"""定向测试：模型连接器新增能力「探测模型端点」（探针簇 TZ-20260918-01）。

覆盖（全部离线可跑，用夹具假端点，不依赖外部服务）：
1. 只给 url+key → 自动取模型 + 三协议依次试、命中即停
2. 给 url+key+协议 → 只打一枪
3. 给模型 → 跳过第一步取模型
4. 三协议全失败 → 三项失败原因都返回
5. 宽容服务器（任意路径回 200 但无特征）→ 必须判不可用
6. 反向：非法 url / 非法协议 / 缺必填 → 参数不合法
7. 第一步必须用 GET（POST /models 应不被采纳为模型清单来源）
"""

import json
import sys
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer

系统根 = "/Users/hekunhua/Documents/Agent/PHP/系统工程平台"
if 系统根 not in sys.path:
    sys.path.insert(0, 系统根)

from 支持库.后端.大语言模型支持库.模型连接器 import 探测模型端点


class 假模型端点(BaseHTTPRequestHandler):
    """可控夹具：按 类属性 决定哪些协议可用、GET/POST 行为。"""

    开启协议: set = set()
    允许GET模型清单: bool = True
    宽容模式: bool = False
    强制状态码: dict = {}
    记录: list = []

    def _回(self, 码: int, 体: dict) -> None:
        数据 = json.dumps(体).encode()
        self.send_response(码)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(数据)))
        self.end_headers()
        self.wfile.write(数据)

    def do_GET(self):
        type(self).记录.append(("GET", self.path))
        if self.path.endswith("/models") and self.允许GET模型清单:
            return self._回(200, {"object": "list", "data": [
                {"id": "夹具模型主"}, {"id": "夹具模型备"}]})
        return self._回(404, {"error": "not found"})

    def do_POST(self):
        长度 = int(self.headers.get("Content-Length", "0"))
        self.rfile.read(长度)
        type(self).记录.append(("POST", self.path))
        if self.path.endswith("/models"):
            # ★ 实测：llama-server 对 POST /models 返回 404
            return self._回(404, {"error": "File Not Found"})
        for 后缀, 强制码 in type(self).强制状态码.items():
            if self.path.endswith(后缀):
                return self._回(强制码, {"error": "forced"})
        if self.宽容模式:
            return self._回(200, {"随便": "什么东西"})   # 无任何协议特征
        映射 = {
            "/chat/completions": ("chat_completions",
                                  {"model": "夹具模型主", "choices": [{"message": {"content": "回包"}}]}),
            "/responses": ("codex_responses",
                           {"model": "夹具模型主", "output": [{"content": "回包"}]}),
            "/messages": ("anthropic_messages",
                          {"model": "夹具模型主", "type": "message",
                           "content": [{"type": "text", "text": "回包"}]}),
        }
        for 后缀, (协议名, 体) in 映射.items():
            if self.path.endswith(后缀):
                if 协议名 in type(self).开启协议:
                    return self._回(200, 体)
                return self._回(404, {"error": "该协议未开启"})
        return self._回(404, {"error": "not found"})

    def log_message(self, *a):
        pass


class 探针测试基类(unittest.TestCase):
    """所有测试共用同一个夹具服务器（避免每个类重复占用端口）。"""

    端口 = 46111
    服务 = None

    @classmethod
    def setUpClass(cls):
        if 探针测试基类.服务 is None:
            探针测试基类.服务 = HTTPServer(("127.0.0.1", cls.端口), 假模型端点)
            threading.Thread(target=探针测试基类.服务.serve_forever, daemon=True).start()
            time.sleep(0.3)

    @classmethod
    def tearDownClass(cls):
        pass  # 由 模块级 tearDownModule 统一关闭

    def setUp(self):
        假模型端点.开启协议 = set()
        假模型端点.允许GET模型清单 = True
        假模型端点.宽容模式 = False
        假模型端点.强制状态码 = {}
        假模型端点.记录 = []
        self.基址 = f"http://127.0.0.1:{self.端口}/v1"


def tearDownModule():
    if 探针测试基类.服务 is not None:
        探针测试基类.服务.shutdown()
        探针测试基类.服务.server_close()
        探针测试基类.服务 = None


class 测试_取模型与试协议(探针测试基类):
    def test_自动取模型并命中第一个协议(self):
        假模型端点.开启协议 = {"chat_completions", "codex_responses", "anthropic_messages"}
        r = 探测模型端点(url=self.基址, api_key="123")
        self.assertTrue(r.成功, r.错误说明)
        v = r.值
        self.assertTrue(v["可用"], f"应可用：{v}")
        self.assertEqual(v["命中协议"], "chat_completions")
        self.assertEqual(v["模型"], "夹具模型主", "应用清单第一个模型")
        self.assertEqual(len(v["逐项结果"]), 1, "命中即停：只应留 1 项")

    def test_命中即停不试后面的协议(self):
        假模型端点.开启协议 = {"anthropic_messages"}
        r = 探测模型端点(url=self.基址, api_key="123")
        v = r.值
        self.assertEqual(v["命中协议"], "anthropic_messages")
        self.assertEqual(len(v["逐项结果"]), 3, "前两个失败也要留原因")
        self.assertFalse(v["逐项结果"][0]["可用"])
        self.assertFalse(v["逐项结果"][1]["可用"])
        self.assertTrue(v["逐项结果"][2]["可用"])

    def test_取模型必须用GET(self):
        假模型端点.开启协议 = {"chat_completions"}
        探测模型端点(url=self.基址, api_key="123")
        取模型请求 = [方法 for 方法, 路径 in 假模型端点.记录 if 路径.endswith("/models")]
        self.assertIn("GET", 取模型请求, "第一步取模型必须用 GET")
        self.assertNotIn("POST", 取模型请求, "POST /models 在 llama-server 上会 404，不得用")

    def test_回带模型名(self):
        假模型端点.开启协议 = {"chat_completions"}
        v = 探测模型端点(url=self.基址, api_key="123").值
        self.assertEqual(v["逐项结果"][0].get("回带模型"), "夹具模型主")


class 测试_参数缺省行为(探针测试基类):
    def test_给了协议只打一枪(self):
        假模型端点.开启协议 = {"codex_responses"}
        r = 探测模型端点(url=self.基址, api_key="123", 协议="codex_responses")
        v = r.值
        self.assertEqual(len(v["逐项结果"]), 1, "给了协议不应串行")
        post请求 = [路径 for 方法, 路径 in 假模型端点.记录 if 方法 == "POST"]
        self.assertEqual(len(post请求), 1, f"只应发 1 个 POST，实际 {post请求}")

    def test_给了模型跳过取模型(self):
        r = 探测模型端点(url=self.基址, api_key="123", 模型="指定的模型")
        v = r.值
        self.assertEqual(v["模型"], "指定的模型")
        self.assertEqual(v["模型清单"], [])
        self.assertEqual(v["诊断"], [], "给了模型就不该去取清单")
        取模型请求 = [p for _, p in 假模型端点.记录 if p.endswith("/models")]
        self.assertEqual(取模型请求, [], "不应请求 /models")


class 测试_失败与反向(探针测试基类):
    def test_三协议全失败时三项原因都返回(self):
        假模型端点.开启协议 = set()
        r = 探测模型端点(url=self.基址, api_key="123")
        v = r.值
        self.assertFalse(v["可用"])
        self.assertEqual(v["命中协议"], "都不通")
        self.assertEqual(len(v["逐项结果"]), 3)
        for 项 in v["逐项结果"]:
            self.assertFalse(项["可用"])
            self.assertTrue(项["判据"], "每项都要有判据")

    def test_宽容服务器200但无特征判不可用(self):
        假模型端点.宽容模式 = True
        v = 探测模型端点(url=self.基址, api_key="123").值
        self.assertFalse(v["可用"], "200 但无协议特征不得判可用")
        self.assertIn("无该协议特征", v["逐项结果"][0]["判据"])

    def test_连接失败分类为连接失败(self):
        v = 探测模型端点(url="http://127.0.0.1:59998/v1", api_key="123").值
        self.assertFalse(v["可用"])
        self.assertIn("连接失败", v["逐项结果"][0]["判据"])

    def test_非法url报参数不合法(self):
        r = 探测模型端点(url="not-a-url")
        self.assertFalse(r.成功)
        self.assertEqual(r.错误码, "参数不合法")
        for 值 in ["", None, "ftp://x/y", 123]:
            self.assertEqual(探测模型端点(url=值).错误码, "参数不合法", f"url={值!r} 应被拒")

    def test_非法协议报参数不合法(self):
        r = 探测模型端点(url=self.基址, 协议="乱写")
        self.assertFalse(r.成功)
        self.assertEqual(r.错误码, "参数不合法")

    def test_非法超时秒报参数不合法(self):
        self.assertEqual(探测模型端点(url=self.基址, 超时秒="abc").错误码, "参数不合法")
        self.assertEqual(探测模型端点(url=self.基址, 超时秒=0).错误码, "参数不合法")
        self.assertEqual(探测模型端点(url=self.基址, 超时秒=-5).错误码, "参数不合法")

    def test_取模型失败不中断流程(self):
        """端点不给 /models 时，应继续用占位名探协议，并在诊断里说明。"""
        假模型端点.允许GET模型清单 = False
        假模型端点.开启协议 = {"chat_completions"}
        v = 探测模型端点(url=self.基址, api_key="123").值
        self.assertTrue(v["可用"], "取清单失败不该阻断探协议")
        self.assertEqual(v["模型"], "unknown")
        self.assertTrue(any("未取到模型清单" in x for x in v["诊断"]), v["诊断"])

    def test_非ASCII密钥在参数校验阶段被拒(self):
        """★ 实测坑：HTTP 头只允许 latin-1，中文 key 会被 urllib 抛 UnicodeEncodeError。

        若不拦，用户会看到「连接失败」这种误导性判据（其实是编码错误）。
        """
        r = 探测模型端点(url=self.基址, api_key="中文密钥")
        self.assertFalse(r.成功, "非 ASCII 密钥应被参数校验拦下")
        self.assertEqual(r.错误码, "参数不合法")
        self.assertIn("ASCII", r.错误说明)

    def test_鉴权失败分类正确(self):
        """夹具回 401 时，必须报「鉴权失败」，不能笼统报「不通」。"""
        假模型端点.开启协议 = set()
        假模型端点.强制状态码 = {"/chat/completions": 401, "/responses": 401, "/messages": 401}
        v = 探测模型端点(url=self.基址, api_key="x").值
        self.assertFalse(v["可用"])
        self.assertTrue(any("鉴权失败" in 项["判据"] for 项 in v["逐项结果"]),
                        [项["判据"] for 项 in v["逐项结果"]])


if __name__ == "__main__":
    unittest.main(verbosity=2)
