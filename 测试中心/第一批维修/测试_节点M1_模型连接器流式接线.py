"""节点M1：模型连接器内部流式入口的 TDD 测试。"""
from __future__ import annotations

import json
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import sys

系统根 = Path(__file__).resolve().parents[2]
if str(系统根) not in sys.path:
    sys.path.insert(0, str(系统根))

from 支持库.后端.大语言模型支持库.模型连接器 import (  # noqa: E402
    连接LLM,
    生成对话,
    流式生成对话,
    释放句柄,
)
from 支持库.后端.大语言模型支持库.模型连接器.实现 import 模型连接器 as 实现  # noqa: E402


class 可复用HTTP服务(ThreadingHTTPServer):
    allow_reuse_address = True


class SSE夹具:
    端口 = 45109

    def __init__(self, 模式: str) -> None:
        self.模式 = 模式
        self.请求: list[dict] = []
        self.关闭事件 = threading.Event()
        self.服务 = 可复用HTTP服务(("127.0.0.1", self.端口), self._处理器())
        self.线程 = threading.Thread(target=self.服务.serve_forever, daemon=True)
        self.线程.start()

    def _处理器(self):
        夹具 = self

        class 处理器(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.0"

            def do_POST(self) -> None:
                长度 = int(self.headers.get("Content-Length", "0"))
                正文 = json.loads(self.rfile.read(长度) or b"{}")
                夹具.请求.append({
                    "路径": self.path,
                    "正文": 正文,
                    "接收": self.headers.get("Accept"),
                    "授权": self.headers.get("Authorization"),
                })
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-cache")
                self.end_headers()
                if 夹具.模式 == "chat":
                    夹具._写入(self, [
                        'data: {"choices":[{"delta":{"content":"甲"}}]}\n\n'.encode(),
                        'data: {"choices":[{"delta":{"content":"乙"}}]}\n\n'.encode(),
                        b"data: [DONE]\n\n",
                    ])
                elif 夹具.模式 == "res":
                    夹具._写入(self, [
                        'data: {"type":"response.output_text.delta","delta":"A"}\n\n'.encode(),
                        'data: {"type":"response.output_text.delta","delta":"B"}\n\n'.encode(),
                        'data: {"type":"response.completed","response":{"usage":{"input_tokens":2}}}\n\n'.encode(),
                    ])
                elif 夹具.模式 == "错误":
                    夹具._写入(self, [
                        'data: {"error":{"message":"上游拒绝"}}\n\n'.encode(),
                    ])
                elif 夹具.模式 == "关闭":
                    夹具._写入(self, [
                        'data: {"choices":[{"delta":{"content":"首包"}}]}\n\n'.encode(),
                    ])
                    try:
                        self.connection.settimeout(1)
                        if not self.connection.recv(1, 2):  # MSG_PEEK=2：等待客户端关闭响应连接
                            夹具.关闭事件.set()
                    except (BrokenPipeError, ConnectionResetError, OSError, TimeoutError):
                        夹具.关闭事件.set()

            def log_message(self, format: str, *args) -> None:
                pass

        return 处理器

    @staticmethod
    def _写入(处理器: BaseHTTPRequestHandler, 块列表: list[bytes]) -> None:
        for 块 in 块列表:
            处理器.wfile.write(块)
            处理器.wfile.flush()

    @property
    def 地址(self) -> str:
        return f"http://127.0.0.1:{self.端口}/v1"

    def 关闭(self) -> None:
        self.服务.shutdown()
        self.服务.server_close()
        self.线程.join(timeout=2)
        if self.线程.is_alive():
            raise AssertionError("SSE夹具线程未在关闭后退出")


class 测试节点M1模型连接器流式接线(unittest.TestCase):
    def setUp(self) -> None:
        实现.连接表.clear()
        self.夹具: SSE夹具 | None = None
        self.句柄表: list[int] = []

    def tearDown(self) -> None:
        for 句柄 in self.句柄表:
            释放句柄(句柄)
        实现.连接表.clear()
        if self.夹具 is not None:
            self.夹具.关闭()

    def _连接(self, 协议: str, 模式: str) -> int:
        self.夹具 = SSE夹具(模式)
        连接 = 连接LLM(
            模型="fixture-model", 提供者="fixture-provider", 部署形态="云端",
            url=self.夹具.地址, api_key="fixture-key", 协议=协议, 超时秒=60,
        )
        self.assertTrue(连接.成功, 连接.错误说明)
        句柄 = 连接.值["句柄"]
        self.句柄表.append(句柄)
        return 句柄

    def test_chat流式入口保留增量完成顺序并发送stream_true(self) -> None:
        句柄 = self._连接("chat", "chat")
        事件 = list(流式生成对话(句柄, [{"role": "user", "content": "测试"}]))
        self.assertEqual(事件, [
            {"类型": "增量", "文本": "甲"},
            {"类型": "增量", "文本": "乙"},
            {"类型": "完成", "文本": "", "完成原因": "stop", "用量": {}},
        ])
        请求 = self.夹具.请求[0]
        self.assertEqual(请求["路径"], "/v1/chat/completions")
        self.assertIs(请求["正文"]["stream"], True)
        self.assertEqual(请求["接收"], "text/event-stream")
        self.assertEqual(请求["授权"], "Bearer fixture-key")

    def test_res流式入口保留增量完成顺序并发送stream_true(self) -> None:
        句柄 = self._连接("res", "res")
        事件 = list(流式生成对话(句柄, [{"role": "user", "content": "测试"}]))
        self.assertEqual(事件, [
            {"类型": "增量", "文本": "A"},
            {"类型": "增量", "文本": "B"},
            {"类型": "完成", "文本": "", "完成原因": "completed", "用量": {"input_tokens": 2}},
        ])
        请求 = self.夹具.请求[0]
        self.assertEqual(请求["路径"], "/v1/responses")
        self.assertIs(请求["正文"]["stream"], True)
        self.assertEqual(请求["接收"], "text/event-stream")

    def test_上游错误原样保留为有限错误事件(self) -> None:
        句柄 = self._连接("chat", "错误")
        事件 = list(流式生成对话(句柄, [{"role": "user", "content": "测试"}]))
        self.assertEqual(事件, [{
            "类型": "错误", "错误码": "上游错误", "错误说明": "上游拒绝",
            "异常类型": "ValueError", "可重试": False,
        }])
        self.assertIs(self.夹具.请求[0]["正文"]["stream"], True)

    def test_关闭连接器迭代器会关闭Provider上游迭代器(self) -> None:
        句柄 = self._连接("chat", "关闭")
        迭代器 = 流式生成对话(句柄, [{"role": "user", "content": "测试"}])
        # 先确认已经发起真实 SSE 请求，再主动关闭连接器边界迭代器。
        首个 = next(迭代器)
        self.assertEqual(首个, {"类型": "增量", "文本": "首包"})
        迭代器.close()
        self.assertTrue(self.夹具.关闭事件.wait(1.5), "关闭连接器迭代器未关闭上游 HTTP 响应")

    def test_非流式生成对话仍返回普通结果(self) -> None:
        句柄 = self._连接("chat", "chat")
        结果 = 生成对话(句柄, [{"role": "user", "content": "非流式"}])
        self.assertFalse(结果.成功, "SSE夹具没有JSON响应，测试应证明普通入口未被流式聚合")
        self.assertEqual(结果.错误码, "模型调用失败")

    def test_流式入口拒绝非整数句柄和空消息(self) -> None:
        for 句柄 in (True, 1.0, "1", 0, 1000000):
            with self.subTest(句柄=句柄):
                事件 = list(流式生成对话(句柄, [{"role": "user", "content": "测试"}]))
                self.assertEqual(事件[0]["类型"], "错误")
                self.assertEqual(事件[0]["错误码"], "参数不合法")
        for 消息列表 in (None, [], "消息"):
            with self.subTest(消息列表=消息列表):
                事件 = list(流式生成对话(1, 消息列表))
                self.assertEqual(事件[0]["类型"], "错误")
                self.assertEqual(事件[0]["错误码"], "参数不合法")

    def test_流式入口拒绝关闭的流式语义(self) -> None:
        事件 = list(流式生成对话(1, [{"role": "user", "content": "测试"}], 流式输出=False))
        self.assertEqual(事件[0]["错误码"], "参数不合法")
        self.assertIn("流式输出", 事件[0]["错误说明"])
        事件 = list(流式生成对话(1, [{"role": "user", "content": "测试"}], 流式输出="是"))
        self.assertEqual(事件[0]["错误码"], "参数不合法")

    def test_失效句柄和不支持连接类型返回结构化错误事件(self) -> None:
        句柄 = self._连接("chat", "chat")
        释放句柄(句柄)
        self.句柄表.remove(句柄)
        事件 = list(流式生成对话(句柄, [{"role": "user", "content": "测试"}]))
        self.assertEqual(事件[0]["错误码"], "句柄失效")

        连接 = 连接LLM(
            模型="fixture-model", 提供者="fixture-provider", 部署形态="云端",
            url=self.夹具.地址, api_key="fixture-key", 协议="chat", 超时秒=60,
        )
        self.assertTrue(连接.成功, 连接.错误说明)
        句柄 = 连接.值["句柄"]
        self.句柄表.append(句柄)
        实现.连接表[句柄]["类型"] = "向量"
        事件 = list(流式生成对话(句柄, [{"role": "user", "content": "测试"}]))
        self.assertEqual(事件[0]["错误码"], "不支持流式连接类型")
        self.assertEqual(len(self.夹具.请求), 0)

    def test_流式入口读取句柄中的协议地址和密钥交给Provider(self) -> None:
        句柄 = self._连接("chat", "chat")
        连接 = 实现.连接表[句柄]
        self.assertEqual(连接["配置"]["协议"], "chat_completions")
        self.assertEqual(连接["配置"]["url"], self.夹具.地址)
        self.assertEqual(连接["配置"]["api_key"], "fixture-key")
        事件 = list(流式生成对话(句柄, [{"role": "user", "content": "读取配置"}]))
        self.assertEqual(事件[-1]["类型"], "完成")

    def test_生成参数按协议映射进流式载荷(self) -> None:
        """与非流式 `生成对话` 同一张映射表：chat→response_format，res→text.format。"""
        工具 = [{"type": "function", "function": {"name": "查库存"}}]
        句柄 = self._连接("chat", "chat")
        事件 = list(流式生成对话(
            句柄, [{"role": "user", "content": "映射"}],
            温度=0.3, 最大令牌数=64,
            工具=工具, 响应格式={"type": "json_object"},
        ))
        self.assertEqual(事件[-1]["类型"], "完成")
        正文 = self.夹具.请求[0]["正文"]
        self.assertEqual(正文["temperature"], 0.3)
        self.assertEqual(正文["max_tokens"], 64)
        self.assertEqual(正文["tools"], 工具)
        self.assertEqual(正文["response_format"], {"type": "json_object"})
        self.assertNotIn("max_output_tokens", 正文)
        self.assertNotIn("text", 正文)

    def test_生成参数在res协议按output和text_format映射(self) -> None:
        工具 = [{"type": "function", "name": "查库存"}]
        句柄 = self._连接("res", "res")
        事件 = list(流式生成对话(
            句柄, [{"role": "user", "content": "映射"}],
            温度=0.7, 最大令牌数=128,
            工具=工具, 响应格式={"type": "json_object"},
        ))
        self.assertEqual(事件[-1]["类型"], "完成")
        正文 = self.夹具.请求[0]["正文"]
        self.assertEqual(正文["temperature"], 0.7)
        self.assertEqual(正文["max_output_tokens"], 128)
        self.assertEqual(正文["tools"], 工具)
        self.assertEqual(正文["text"], {"format": {"type": "json_object"}})
        self.assertNotIn("max_tokens", 正文)
        self.assertNotIn("response_format", 正文)

    def test_不传生成参数时流式载荷不含这四个键(self) -> None:
        """防漂移：不传即不下发，保证既有流式行为逐字节不变。"""
        for 协议, 模式 in (("chat", "chat"), ("res", "res")):
            with self.subTest(协议=协议):
                self.setUp()
                句柄 = self._连接(协议, 模式)
                事件 = list(流式生成对话(句柄, [{"role": "user", "content": "默认"}]))
                self.assertEqual(事件[-1]["类型"], "完成")
                正文 = self.夹具.请求[0]["正文"]
                for 键 in ("temperature", "max_tokens", "max_output_tokens",
                           "tools", "response_format", "text"):
                    self.assertNotIn(键, 正文, f"未传生成参数却下发了 {键}")
                self.tearDown()

    def test_生成参数类型非法即拒绝且不发请求(self) -> None:
        句柄 = self._连接("chat", "chat")
        非法表 = (
            {"温度": "热"}, {"温度": True},
            {"最大令牌数": 1.5}, {"最大令牌数": True},
            {"工具": {"名称": "查库存"}},
            {"响应格式": ["json"]},
        )
        for 非法 in 非法表:
            with self.subTest(**非法):
                事件 = list(流式生成对话(句柄, [{"role": "user", "content": "非法"}], **非法))
                self.assertEqual(事件[0]["类型"], "错误")
                self.assertEqual(事件[0]["错误码"], "参数不合法")
        self.assertEqual(len(self.夹具.请求), 0, "参数非法时不得发起上游请求")


if __name__ == "__main__":
    unittest.main()
