"""模型协议别名：短值与长值必须同一裁决，三协议（chat/res/anthropic）都收。

同一份协议名有两处入口：
- 连接器 `模型连接器.连接LLM`，经 `_规范化协议` 把 chat→chat_completions、res→codex_responses、
  anthropic→anthropic_messages；
- 适配层 `模型HTTP提供者.调用对话` / `流式调用对话`，直接吃 配置["协议"]。

历史缺陷：`流式调用对话` 抄了一份局部别名表收短值，而 `调用对话` 不归一化，
短值直接落到「协议必须是 ...」的失败分支 —— **同一文件内两个能力对同一种入参裁决不一致**，
且两份别名表各自维护、随时会漂移。

本文件锁定：短值/长值两处都收；两份别名表取值一致（漂移守卫）；
anthropic Messages 协议的端点、认证头、system 顶层、max_tokens 必填与工具形态。
"""

from __future__ import annotations

import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from 支持库.适配层 import 模型HTTP提供者
from 支持库.适配层.模型HTTP提供者 import 流式调用对话, 调用对话
from 支持库.后端.大语言模型支持库.模型连接器.实现.模型连接器 import 协议别名 as 连接器协议别名


class _回显上游:
    """回显上游：按路径回 chat / responses / anthropic 三种形状，并记录请求头与请求体。"""

    def __init__(self) -> None:
        self.路径记录: list[str] = []
        self.请求头记录: list[dict] = []
        self.请求体记录: list[dict] = []
        self.锁 = threading.Lock()
        self.服务 = ThreadingHTTPServer(("127.0.0.1", 0), self._造处理器())
        self.端口 = self.服务.server_port
        self.线程 = threading.Thread(target=self.服务.serve_forever, daemon=True)
        self.线程.start()

    def _造处理器(self):
        自身 = self

        class 处理器(BaseHTTPRequestHandler):
            def log_message(self, *args) -> None:
                pass

            def do_POST(self) -> None:
                长度 = int(self.headers.get("Content-Length") or 0)
                原始 = self.rfile.read(长度) if 长度 else b""
                try:
                    载荷 = json.loads(原始.decode("utf-8")) if 原始 else {}
                except Exception:
                    载荷 = {}
                with 自身.锁:
                    自身.路径记录.append(self.path)
                    自身.请求头记录.append({键.lower(): 值 for 键, 值 in self.headers.items()})
                    自身.请求体记录.append(载荷 if isinstance(载荷, dict) else {})
                if self.path.endswith("/messages"):
                    self._回anthropic(载荷)
                    return
                if self.path.endswith("/responses"):
                    数据 = json.dumps(
                        {"output": [{"content": [{"text": "res回显"}]}]},
                        ensure_ascii=False,
                    ).encode("utf-8")
                else:
                    数据 = json.dumps(
                        {"choices": [{"message": {"content": "chat回显"}, "finish_reason": "stop"}]},
                        ensure_ascii=False,
                    ).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(数据)))
                self.end_headers()
                self.wfile.write(数据)

            def _回anthropic(self, 载荷: dict) -> None:
                if 载荷.get("stream"):
                    事件序列 = [
                        ("message_start", {"type": "message_start", "message": {
                            "id": "msg_测试", "role": "assistant", "content": [],
                            "usage": {"input_tokens": 7, "output_tokens": 0}}}),
                        ("content_block_start", {"type": "content_block_start", "index": 0,
                                                 "content_block": {"type": "text", "text": ""}}),
                        ("content_block_delta", {"type": "content_block_delta", "index": 0,
                                                 "delta": {"type": "text_delta", "text": "流式"}}),
                        ("content_block_delta", {"type": "content_block_delta", "index": 0,
                                                 "delta": {"type": "text_delta", "text": "回显"}}),
                        ("content_block_stop", {"type": "content_block_stop", "index": 0}),
                        ("message_delta", {"type": "message_delta",
                                           "delta": {"stop_reason": "end_turn"},
                                           "usage": {"output_tokens": 4}}),
                        ("message_stop", {"type": "message_stop"}),
                    ]
                    正文 = "".join(
                        f"event: {事件名}\ndata: {json.dumps(数据, ensure_ascii=False)}\n\n"
                        for 事件名, 数据 in 事件序列
                    ).encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "text/event-stream")
                    self.send_header("Content-Length", str(len(正文)))
                    self.end_headers()
                    self.wfile.write(正文)
                    return
                数据 = json.dumps({
                    "id": "msg_测试", "type": "message", "role": "assistant",
                    "content": [{"type": "text", "text": "anthropic回显"}],
                    "stop_reason": "end_turn",
                    "usage": {"input_tokens": 11, "output_tokens": 6},
                }, ensure_ascii=False).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(数据)))
                self.end_headers()
                self.wfile.write(数据)

        return 处理器

    def 配置(self, 协议: str) -> dict:
        return {"url": f"http://127.0.0.1:{self.端口}/v1", "模型名": "测试模型",
                "协议": 协议, "api_key": "sk-test-key"}

    def 关闭(self) -> None:
        self.服务.shutdown()
        self.服务.server_close()
        self.线程.join(timeout=2)


class 测试协议别名裁决(unittest.TestCase):
    def test_别名表与连接器取值一致(self) -> None:
        别名 = getattr(模型HTTP提供者, "协议别名表", None)
        self.assertIsInstance(别名, dict, "适配层应暴露模块级 协议别名表 供两处以单一来源复用")
        self.assertEqual(别名, 连接器协议别名, "适配层与连接器的协议别名表已漂移，须对齐")

    def test_三协议长短值都被收录(self) -> None:
        别名 = 模型HTTP提供者.协议别名表
        for 短值, 长值 in (("chat", "chat_completions"), ("res", "codex_responses"),
                          ("anthropic", "anthropic_messages")):
            self.assertEqual(别名.get(短值), 长值)
            self.assertEqual(别名.get(长值), 长值)

    def test_调用对话接受短值与长值(self) -> None:
        上游 = _回显上游()
        try:
            for 短值, 长值, 期望路径, 期望文本 in (
                ("chat", "chat_completions", "/chat/completions", "chat回显"),
                ("res", "codex_responses", "/responses", "res回显"),
                ("anthropic", "anthropic_messages", "/v1/messages", "anthropic回显"),
            ):
                with self.subTest(协议=短值):
                    结果 = 调用对话(配置=上游.配置(短值), 消息列表=[{"role": "user", "content": "契约"}])
                    self.assertTrue(结果.成功, f"短值 {短值} 应被接受: {结果.错误说明}")
                    assert isinstance(结果.值, dict)
                    self.assertTrue(上游.路径记录[-1].endswith(期望路径), 上游.路径记录[-1])
                    self.assertIn(期望文本, str(结果.值.get("内容") or 结果.值.get("回复") or ""))

                with self.subTest(协议=长值):
                    结果 = 调用对话(配置=上游.配置(长值), 消息列表=[{"role": "user", "content": "契约"}])
                    self.assertTrue(结果.成功, f"长值 {长值} 应被接受: {结果.错误说明}")
                    self.assertTrue(上游.路径记录[-1].endswith(期望路径), 上游.路径记录[-1])
        finally:
            上游.关闭()

    def test_anthropic载荷形态与认证头(self) -> None:
        """anthropic 面必须：x-api-key 认证、system 提顶层、max_tokens 必填、工具转 input_schema。"""
        上游 = _回显上游()
        try:
            结果 = 调用对话(
                配置=上游.配置("anthropic"),
                消息列表=[{"role": "user", "content": "契约"}],
                系统提示词="你是精简助手",
                温度=0.3,
                工具=[{"type": "function", "function": {
                    "name": "get_weather", "description": "查天气",
                    "parameters": {"type": "object", "properties": {"city": {"type": "string"}}}}}],
            )
            self.assertTrue(结果.成功, 结果.错误说明)
            头 = 上游.请求头记录[-1]
            体 = 上游.请求体记录[-1]
            self.assertEqual(头.get("x-api-key"), "sk-test-key", "anthropic 必须走 x-api-key")
            self.assertTrue(头.get("anthropic-version"), "anthropic 必须带版本头")
            self.assertNotIn("authorization", 头, "anthropic 面不应双发 Bearer 认证")
            self.assertEqual(体.get("system"), "你是精简助手", "system 必须是顶层字段")
            self.assertEqual(体.get("messages"), [{"role": "user", "content": "契约"}],
                             "messages 里不得出现 system 角色")
            self.assertIsInstance(体.get("max_tokens"), int, "anthropic 的 max_tokens 必填")
            self.assertEqual(体.get("temperature"), 0.3)
            工具 = (体.get("tools") or [{}])[0]
            self.assertEqual(工具.get("name"), "get_weather")
            self.assertIn("input_schema", 工具, "工具必须转成 anthropic 的 input_schema 形态")
            self.assertNotIn("function", 工具)
        finally:
            上游.关闭()

    def test_anthropic拒绝非法工具名与响应格式(self) -> None:
        """协议规范：工具名必须匹配 ^[a-zA-Z0-9_-]{1,64}$；响应格式在 anthropic 无对应语义。"""
        上游 = _回显上游()
        try:
            结果 = 调用对话(
                配置=上游.配置("anthropic"),
                消息列表=[{"role": "user", "content": "契约"}],
                工具=[{"type": "function", "function": {"name": "查询天气", "parameters": {}}}],
            )
            self.assertFalse(结果.成功)
            self.assertEqual(结果.错误码, "参数不合法")
            self.assertIn("工具名", 结果.错误说明)
            self.assertFalse(上游.路径记录, "非法工具名必须在出站前被拒，不发请求")

            结果 = 调用对话(
                配置=上游.配置("anthropic"),
                消息列表=[{"role": "user", "content": "契约"}],
                响应格式={"type": "json_object"},
            )
            self.assertFalse(结果.成功, "anthropic 无 response_format 语义，不得静默丢弃")
            self.assertEqual(结果.错误码, "参数不合法")
        finally:
            上游.关闭()

    def test_连接器与适配层端点归一一致(self) -> None:
        """同一份配置（url 不带 /v1）在两层必须得到同一端点，否则一层能用一层不能用。"""
        from 支持库.后端.大语言模型支持库.模型连接器.实现.模型连接器 import _HTTP调用模型
        上游 = _回显上游()
        try:
            配置 = 上游.配置("anthropic")
            配置["url"] = f"http://127.0.0.1:{上游.端口}"  # 故意不带 /v1
            结果 = _HTTP调用模型("LLM", 配置, {
                "消息列表": [{"role": "user", "content": "契约"}],
                "系统提示词": "系统", "最大令牌数": 32,
            })
            self.assertTrue(结果.成功, f"连接器应经同一归一补 /v1：{结果.错误说明}")
            self.assertTrue(上游.路径记录[-1].endswith("/v1/messages"), 上游.路径记录[-1])
            self.assertEqual(上游.请求体记录[-1].get("system"), "系统",
                             "连接器 anthropic 面同样要把 system 提顶层")
        finally:
            上游.关闭()

    def test_非ASCII密钥给出明确失败而非异常(self) -> None:
        """HTTP 头只能承载 latin-1：中文密钥必须变成可诊断失败，不得抛 UnicodeEncodeError。"""
        上游 = _回显上游()
        try:
            配置 = 上游.配置("anthropic")
            配置["api_key"] = "sk-中文密钥"
            结果 = 调用对话(配置=配置, 消息列表=[{"role": "user", "content": "契约"}])
            self.assertFalse(结果.成功)
            self.assertEqual(结果.错误码, "模型调用失败")
            self.assertIn("非 ASCII", 结果.错误说明)
            self.assertFalse(上游.路径记录, "不可发送的头必须在出站前被拒")
        finally:
            上游.关闭()

    def test_调用对话拒绝非法协议(self) -> None:
        上游 = _回显上游()
        try:
            结果 = 调用对话(配置=上游.配置("乱填"), 消息列表=[{"role": "user", "content": "契约"}])
            self.assertFalse(结果.成功)
            self.assertEqual(结果.错误码, "参数不合法")
        finally:
            上游.关闭()

    def test_流式调用对话接受短值(self) -> None:
        上游 = _回显上游()
        try:
            事件 = list(流式调用对话(
                配置=上游.配置("chat"),
                消息列表=[{"role": "user", "content": "契约"}],
            ))
            self.assertTrue(事件, "短值 chat 应能进入流式读取（至少产生一个事件）")
            首个 = 事件[0]
            if 首个.get("类型") == "错误":
                self.assertNotIn("参数不合法", str(首个.get("错误码")), "短值不应被判为参数不合法")
            self.assertTrue(上游.路径记录, "上游应收到流式请求")
            self.assertTrue(上游.路径记录[-1].endswith("/chat/completions"), 上游.路径记录[-1])
        finally:
            上游.关闭()

    def test_anthropic流式事件解析(self) -> None:
        """anthropic SSE：文本增量取 content_block_delta.text，完成取 message_stop/stop_reason。"""
        上游 = _回显上游()
        try:
            事件 = list(流式调用对话(
                配置=上游.配置("anthropic"),
                消息列表=[{"role": "user", "content": "契约"}],
            ))
            类型序列 = [事件.get("类型") for 事件 in 事件]
            self.assertIn("增量", 类型序列, f"应产生文本增量事件：{事件}")
            self.assertIn("完成", 类型序列, f"应产生完成事件：{事件}")
            增量文本 = "".join(str(事件.get("文本") or "") for 事件 in 事件 if 事件.get("类型") == "增量")
            self.assertEqual(增量文本, "流式回显")
            完成事件 = [事件 for 事件 in 事件 if 事件.get("类型") == "完成"][0]
            self.assertEqual(完成事件.get("完成原因"), "stop")
            self.assertTrue(上游.路径记录[-1].endswith("/v1/messages"), 上游.路径记录[-1])
        finally:
            上游.关闭()


if __name__ == "__main__":
    unittest.main()
