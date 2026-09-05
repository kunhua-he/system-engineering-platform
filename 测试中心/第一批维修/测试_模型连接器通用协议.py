"""模型连接器通用协议契约的 TDD 测试：只访问本地 HTTP 夹具。"""
from __future__ import annotations

import json
import threading
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
    释放句柄,
)
from 支持库.后端.大语言模型支持库.模型连接器.实现 import 模型连接器 as 实现  # noqa: E402


class 请求夹具:
    def __init__(self) -> None:
        self.请求: list[tuple[str, dict]] = []
        self.响应状态 = 200
        self.服务 = ThreadingHTTPServer(("127.0.0.1", 0), self._处理器())
        self.线程 = threading.Thread(target=self.服务.serve_forever, daemon=True)
        self.线程.start()

    def _处理器(self):
        夹具 = self

        class 处理器(BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                长度 = int(self.headers.get("Content-Length", "0"))
                正文 = json.loads(self.rfile.read(长度) or b"{}")
                夹具.请求.append((self.path, 正文))
                if 夹具.响应状态 != 200:
                    数据 = json.dumps({"error": {"message": "夹具拒绝请求"}}).encode()
                elif self.path.endswith("/responses"):
                    数据 = json.dumps({"output_text": "codex夹具回复"}).encode()
                else:
                    数据 = json.dumps({
                        "choices": [{"message": {"content": "chat夹具回复"}}],
                        "usage": {"total_tokens": 3},
                    }).encode()
                self.send_response(夹具.响应状态)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(数据)))
                self.end_headers()
                self.wfile.write(数据)

            def log_message(self, format: str, *args) -> None:
                pass

        return 处理器

    @property
    def 地址(self) -> str:
        return f"http://127.0.0.1:{self.服务.server_port}/v1"

    def 关闭(self) -> None:
        self.服务.shutdown()
        self.服务.server_close()
        self.线程.join(timeout=2)


class 测试模型连接器通用协议(unittest.TestCase):
    def setUp(self) -> None:
        实现.连接表.clear()
        self.夹具 = 请求夹具()
        self.句柄表: list[int] = []

    def tearDown(self) -> None:
        for 句柄 in self.句柄表:
            释放句柄(句柄)
        实现.连接表.clear()
        self.夹具.关闭()

    def _连接(self, 协议: str | None = None):
        参数 = {
            "模型": "fixture-model",
            "提供者": "fixture-provider",
            "部署形态": "云端",
            "url": self.夹具.地址,
            "超时秒": 60,
        }
        if 协议 is not None:
            参数["协议"] = 协议
        try:
            结果 = 连接LLM(**参数)
        except TypeError as 错误:
            self.fail(f"连接LLM尚未暴露协议参数：{错误}")
        self.assertTrue(结果.成功, 结果.错误说明)
        self.句柄表.append(结果.值["句柄"])
        return 结果

    def test_连接LLM默认协议并随句柄配置保存(self) -> None:
        结果 = self._连接()
        句柄 = 结果.值["句柄"]
        self.assertEqual(结果.值["协议"], "chat_completions")
        self.assertEqual(实现.连接表[句柄]["配置"]["协议"], "chat_completions")

    def test_连接LLM允许codex_responses协议(self) -> None:
        结果 = self._连接("codex_responses")
        self.assertEqual(结果.值["协议"], "codex_responses")

    def test_chat非流式返回统一结果并组装协议请求(self) -> None:
        句柄 = self._连接().值["句柄"]
        结果 = 生成对话(句柄, [{"role": "user", "content": "你好"}])
        self.assertTrue(结果.成功, 结果.错误说明)
        self.assertEqual(结果.值["回复"], "chat夹具回复")
        self.assertEqual(len(self.夹具.请求), 1)
        路径, 请求体 = self.夹具.请求[0]
        self.assertEqual(路径, "/v1/chat/completions")
        self.assertEqual(请求体["model"], "fixture-model")
        self.assertEqual(请求体["messages"][0]["content"], "你好")
        self.assertIs(请求体["stream"], False)

    def test_codex_responses组装路径和请求体并返回统一结果(self) -> None:
        句柄 = self._连接("codex_responses").值["句柄"]
        结果 = 生成对话(
            句柄,
            [{"role": "user", "content": "只回复夹具"}],
            "系统规则",
        )
        self.assertTrue(结果.成功, 结果.错误说明)
        self.assertEqual(结果.值["回复"], "codex夹具回复")
        路径, 请求体 = self.夹具.请求[0]
        self.assertEqual(路径, "/v1/responses")
        self.assertEqual(请求体["model"], "fixture-model")
        self.assertNotIn("messages", 请求体)
        self.assertEqual(请求体["input"][0], {"role": "system", "content": "系统规则"})
        self.assertEqual(请求体["input"][1]["content"], "只回复夹具")
        self.assertIs(请求体["stream"], False)

    def test_codex_responses错误保持统一失败契约(self) -> None:
        self.夹具.响应状态 = 401
        句柄 = self._连接("codex_responses").值["句柄"]
        结果 = 生成对话(句柄, [{"role": "user", "content": "失败"}])
        self.assertFalse(结果.成功)
        self.assertIsNone(结果.值)
        self.assertEqual(结果.错误码, "认证失败")
        self.assertIsInstance(结果.错误说明, str)

    def test_流式输出为真不得静默降级且返回结构化错误(self) -> None:
        句柄 = self._连接().值["句柄"]
        try:
            结果 = 生成对话(
                句柄,
                [{"role": "user", "content": "不要伪造完成"}],
                流式输出=True,
            )
        except TypeError as 错误:
            self.fail(f"生成对话尚未暴露流式输出参数：{错误}")
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "流式能力未装配")
        self.assertIn("待补网关流", 结果.错误说明)
        self.assertEqual(结果.详细信息["流式输出"], True)
        self.assertEqual(self.夹具.请求, [])


if __name__ == "__main__":
    unittest.main()
