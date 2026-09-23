"""节点H：模型 HTTP Provider 上游 SSE 原子读取的 TDD 测试。"""
from __future__ import annotations

import json
import sys
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

系统根 = Path(__file__).resolve().parents[2]
if str(系统根) not in sys.path:
    sys.path.insert(0, str(系统根))

from 支持库.适配层 import 模型HTTP提供者 as 提供者


class 可复用HTTP服务(ThreadingHTTPServer):
    allow_reuse_address = True


class SSE夹具:
    端口 = 45108

    def __init__(self, 模式: str) -> None:
        self.模式 = 模式
        self.请求: list[dict] = []
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
                })
                if 夹具.模式 == "非流式":
                    数据 = json.dumps({
                        "choices": [{"message": {"content": "非流式仍可用"}}],
                        "usage": {"total_tokens": 2},
                    }).encode()
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(数据)))
                    self.end_headers()
                    self.wfile.write(数据)
                    return
                if 夹具.模式 == "HTTP错误":
                    数据 = json.dumps({"error": {"message": "凭证拒绝"}}).encode()
                    self.send_response(401)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(数据)))
                    self.end_headers()
                    self.wfile.write(数据)
                    return
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-cache")
                self.end_headers()
                if 夹具.模式 == "chat":
                    夹具._写入(self, [
                        b": keepalive\n\n",
                        b"event: chunk\n",
                        'data: {"choices":[{"delta":{"content":"你"}}]}\n\n'.encode(),
                        'data: {"choices":[{"delta":{"content":"好"}}]}\n\n'.encode(),
                        b"data: [DONE]\n\n",
                    ])
                elif 夹具.模式 == "chat空完成原因":
                    夹具._写入(self, [
                        b": keepalive\n\n",
                        b'event: chunk\n',
                        b'data: {"choices":[{"delta":{"role":"assistant","content":""},"finish_reason":""}]}\n\n',
                        'data: {"choices":[{"delta":{"content":"你"}}]}\n\n'.encode(),
                        'data: {"choices":[{"delta":{"content":"好"}}]}\n\n'.encode(),
                        b'data: {"choices":[{"delta":{"content":""},"finish_reason":"stop"}]}\n\n',
                        b"data: [DONE]\n\n",
                    ])
                elif 夹具.模式 == "codex":
                    夹具._写入(self, [
                        b'event: response.created\ndata: {"type":"response.created","response":{"status":"in_progress"}}\n\n',
                        b'event: response.in_progress\ndata: {"type":"response.in_progress","response":{"status":"in_progress"}}\n\n',
                        b'event: response.output_item.added\ndata: {"type":"response.output_item.added","item":{"type":"message"}}\n\n',
                        b'event: response.content_part.added\ndata: {"type":"response.content_part.added","part":{"type":"output_text"}}\n\n',
                        'data: {"type":"response.output_text.delta","delta":"第一段"}\n\n'.encode(),
                        'data: {"type":"response.output_text.delta","delta":"第二段"}\n\n'.encode(),
                        'event: response.output_text.done\ndata: {"type":"response.output_text.done","text":"第一段第二段"}\n\n'.encode(),
                        'event: response.content_part.done\ndata: {"type":"response.content_part.done","part":{"type":"output_text","text":"第一段第二段"}}\n\n'.encode(),
                        b'event: response.output_item.done\ndata: {"type":"response.output_item.done","item":{"type":"message"}}\n\n',
                        b'event: response.completed\ndata: {"type":"response.completed","response":{"usage":{"input_tokens":1}}}\n\n',
                    ])
                elif 夹具.模式 == "错误":
                    夹具._写入(self, [
                        'data: {"error":{"type":"invalid_request_error","message":"上游拒绝"}}\n\n'.encode(),
                    ])
                elif 夹具.模式 == "畸形":
                    夹具._写入(self, [b"data: {not-json}\n\n"])
                elif 夹具.模式 == "超限":
                    夹具._写入(self, [b'data: {"choices":[{"delta":{"content":"' + b"x" * 300 + b'"}}]}\n\n'])
                elif 夹具.模式 == "断开":
                    夹具._写入(self, [
                        'data: {"choices":[{"delta":{"content":"未完成"}}]}\n\n'.encode(),
                    ])
                elif 夹具.模式 == "超时":
                    time.sleep(0.2)
                    夹具._写入(self, [b'data: [DONE]\n\n'])

            @staticmethod
            def log_message(format: str, *args) -> None:
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
        self.assert_thread_stopped()

    def assert_thread_stopped(self) -> None:
        if self.线程.is_alive():
            raise AssertionError("SSE夹具线程未在关闭后退出")


class 测试节点H模型Provider流式读取(unittest.TestCase):
    def setUp(self) -> None:
        self.夹具: SSE夹具 | None = None

    def tearDown(self) -> None:
        if self.夹具 is not None:
            self.夹具.关闭()

    def _配置(self, 协议: str = "chat_completions", **额外) -> dict:
        配置 = {
            "模型名": "fixture-model",
            "提供者": "fixture-provider",
            "url": self.夹具.地址,
            "api_key": "fixture-key",
            "协议": 协议,
            "请求超时秒": 2,
        }
        配置.update(额外)
        return 配置

    def _读取(self, 模式: str, 协议: str = "chat_completions", **额外) -> list[dict]:
        self.夹具 = SSE夹具(模式)
        函数 = getattr(提供者, "流式调用对话", None)
        self.assertIsNotNone(函数, "Provider 尚未提供流式调用对话")
        if 函数 is None:
            return []
        return list(函数(
            配置=self._配置(协议, **额外),
            消息列表=[{"role": "user", "content": "测试"}],
            系统提示词="系统",
        ))

    def test_chat协议逐事件增量完成且请求stream为真(self) -> None:
        事件 = self._读取("chat")
        self.assertEqual(
            事件,
            [
                {"类型": "增量", "文本": "你"},
                {"类型": "增量", "文本": "好"},
                {"类型": "完成", "文本": "", "完成原因": "stop", "用量": {}},
            ],
        )
        请求 = self.夹具.请求[0]
        self.assertEqual(请求["路径"], "/v1/chat/completions")
        self.assertIs(请求["正文"]["stream"], True)
        # chat 协议流式默认不回传 usage，必须显式索取，否则用量追踪恒为零。
        self.assertEqual(请求["正文"]["stream_options"], {"include_usage": True})
        self.assertEqual(请求["正文"]["messages"][0], {"role": "system", "content": "系统"})
        self.assertEqual(请求["接收"], "text/event-stream")

    def test_chat首个空完成原因不会吞掉后续增量(self) -> None:
        事件 = self._读取("chat空完成原因")
        self.assertEqual(事件, [
            {"类型": "增量", "文本": "你"},
            {"类型": "增量", "文本": "好"},
            {"类型": "完成", "文本": "", "完成原因": "stop", "用量": {}},
        ])

    def test_codex协议解析Responses增量和完成事件(self) -> None:
        事件 = self._读取("codex", "codex_responses")
        self.assertEqual(事件[0], {"类型": "增量", "文本": "第一段"})
        self.assertEqual(事件[1], {"类型": "增量", "文本": "第二段"})
        self.assertEqual(事件[2], {
            "类型": "完成", "文本": "", "完成原因": "completed",
            "用量": {"input_tokens": 1},
        })
        请求 = self.夹具.请求[0]
        self.assertEqual(请求["路径"], "/v1/responses")
        self.assertIs(请求["正文"]["stream"], True)
        # codex/responses 自带用量，不应出现 chat 专有的 stream_options。
        self.assertNotIn("stream_options", 请求["正文"])
        self.assertEqual(请求["正文"]["input"][0]["content"], "系统")
        self.assertEqual(请求["接收"], "text/event-stream")

    def test_上游错误转结构化错误终态(self) -> None:
        事件 = self._读取("错误")
        self.assertEqual(len(事件), 1)
        self.assertEqual(事件[0]["类型"], "错误")
        self.assertEqual(事件[0]["错误码"], "上游错误")
        self.assertEqual(事件[0]["错误说明"], "上游拒绝")
        self.assertFalse(事件[0]["可重试"])

    def test_畸形SSE数据转事件格式错误终态(self) -> None:
        事件 = self._读取("畸形")
        self.assertEqual(事件[-1]["类型"], "错误")
        self.assertEqual(事件[-1]["错误码"], "事件格式错误")

    def test_响应超出上限立即转超限终态(self) -> None:
        事件 = self._读取("超限", 流式响应上限字节=128)
        self.assertEqual(事件[-1]["类型"], "错误")
        self.assertEqual(事件[-1]["错误码"], "响应超限")
        self.assertEqual(事件[-1]["上限字节"], 128)

    def test_上游提前断开转断开终态而不伪造完成(self) -> None:
        事件 = self._读取("断开")
        self.assertEqual(事件[0], {"类型": "增量", "文本": "未完成"})
        self.assertEqual(事件[-1]["类型"], "错误")
        self.assertEqual(事件[-1]["错误码"], "上游断开")

    def test_读取超时转超时终态(self) -> None:
        事件 = self._读取("超时", 请求超时秒=0.05)
        self.assertEqual(事件[-1]["类型"], "错误")
        self.assertEqual(事件[-1]["错误码"], "超时")

    def test_HTTP错误转结构化上游失败终态(self) -> None:
        """HTTP 错误必须带服务端正文（2026-09-21 提交 8a23f34d「模型 HTTP 错误正文透传」）。

        该提交把 HTTPError 分支从只回 `HTTP {code}` 改为**透传错误正文**
        （唯一取值点 `模型HTTP提供者.取错误正文`，非流式/流式两处同口径）——
        原断言写死旧文案「模型 HTTP 返回 401」，随该行为改进而过期；
        现按夹具真实返回体（`{"error": {"message": "凭证拒绝"}}`）断言，判据强度不变。
        """
        事件 = self._读取("HTTP错误")
        # 正文按**服务端原始字节**透传（`json.dumps` 默认 `ensure_ascii=True` ⇒ 中文为
        # `\uXXXX` 转义），故期望值用原始字符串（不预先解码），与生产口径逐字一致。
        self.assertEqual(事件, [{
            "类型": "错误", "错误码": "认证失败",
            "错误说明": r'模型 HTTP 返回 401：{"error": {"message": "\u51ed\u8bc1\u62d2\u7edd"}}',
            "状态码": 401, "可重试": False, "异常类型": "HTTPError",
        }])

    def test_现有非流式调用保持JSON路径(self) -> None:
        self.夹具 = SSE夹具("非流式")
        结果 = 提供者.调用对话(
            配置=self._配置(),
            消息列表=[{"role": "user", "content": "保留"}],
        )
        self.assertTrue(结果.成功, 结果.错误说明)
        self.assertEqual(结果.值["回复"], "非流式仍可用")
        self.assertIs(self.夹具.请求[0]["正文"]["stream"], False)


if __name__ == "__main__":
    unittest.main()
