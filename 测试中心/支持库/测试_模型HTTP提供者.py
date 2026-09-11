"""模型HTTP提供者：注册进 调用函数表 的调用器必须收得下 生成对话 的全部生成参数。

本文件专盯一条冷启动才暴露的回归：

    生成对话(句柄, …, 温度, 最大令牌数, 工具, 响应格式)
      → _调用模型 → 调用函数表["LLM:部署形态"]  ← 注册模型HTTP提供者() 写入
      → 模型HTTP提供者.调用对话(配置=…, **参数)

`调用对话` 若签名收不下这四个生成参数，`**参数` 展开即 TypeError，40007 全链路
LLM 调用失效。该缺陷曾被掩盖：热接入重载 `支持库/后端` 会把模块级 `调用函数表`
重置为空，`_调用模型` 落回完整的 `_HTTP调用模型` 兜底，于是热态正常、冷启动即炸。

因此本文件刻意 **不清空** 调用函数表，反而显式注册，走注册路径断言协议契约。
（对照组：测试中心/第一批维修/测试_模型连接器HTTP.py 是清空函数表测兜底路径。）
"""

from __future__ import annotations

import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from 支持库.适配层.模型HTTP提供者 import 注册模型HTTP提供者
from 支持库.后端.大语言模型支持库.模型连接器 import (
    释放句柄,
    生成对话,
    连接LLM,
)


class _回显上游:
    """记录出站请求体与请求头的 OpenAI 兼容上游。"""

    def __init__(self) -> None:
        self.记录: list[dict] = []
        self.锁 = threading.Lock()
        self.服务 = ThreadingHTTPServer(("127.0.0.1", 0), self._造处理器())
        self.端口 = self.服务.server_port
        self.线程 = threading.Thread(target=self.服务.serve_forever, daemon=True)
        self.线程.start()

    def _造处理器(self):
        记录, 锁 = self.记录, self.锁

        class 处理器(BaseHTTPRequestHandler):
            def log_message(self, *args) -> None:
                pass

            def do_POST(self) -> None:
                长度 = int(self.headers.get("Content-Length") or 0)
                原文 = self.rfile.read(长度) if 长度 else b"{}"
                with 锁:
                    记录.append({"路径": self.path, "请求体": json.loads(原文.decode("utf-8")),
                                 "请求头": {k.lower(): v for k, v in self.headers.items()}})
                数据 = json.dumps(
                    {"choices": [{"message": {"content": "契约回显"}, "finish_reason": "stop"}],
                     "usage": {"total_tokens": 3}},
                    ensure_ascii=False,
                ).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(数据)))
                self.end_headers()
                self.wfile.write(数据)

        return 处理器

    def 关闭(self) -> None:
        self.服务.shutdown()
        self.服务.server_close()
        self.线程.join(timeout=2)


class 测试模型HTTP提供者注册契约(unittest.TestCase):
    def setUp(self) -> None:
        注册模型HTTP提供者()  # 保证冷启动态：调用函数表["LLM:本地"/"云端"] 非空

    def _连接(self, 上游: _回显上游, 协议: str) -> int:
        连接 = 连接LLM(模型="测试模型", 提供者="本地", 部署形态="本地",
                      url=f"http://127.0.0.1:{上游.端口}/v1", 协议=协议)
        self.assertTrue(连接.成功, f"连接失败: {连接.错误说明}")
        assert isinstance(连接.值, dict)
        return 连接.值["句柄"]

    def test_chat协议生成参数全量下传且响应归一化(self) -> None:
        上游 = _回显上游()
        句柄 = None
        try:
            句柄 = self._连接(上游, "chat_completions")
            对话 = 生成对话(句柄, [{"role": "user", "content": "契约"}],
                            温度=0.3, 最大令牌数=64,
                            工具=[{"type": "function", "function": {"name": "查天气"}}],
                            响应格式={"type": "json_object"})

            self.assertTrue(对话.成功, f"生成对话失败: {对话.错误说明}")
            assert isinstance(对话.值, dict)
            # 响应归一化键集（与 _HTTP调用模型 逐键一致）
            for 键 in ("回复", "用量", "内容", "思考", "工具调用", "结束原因"):
                self.assertIn(键, 对话.值, f"缺归一化键 {键}")
            self.assertEqual(对话.值["内容"], "契约回显")
            self.assertEqual(对话.值["回复"], "契约回显")
            self.assertEqual(对话.值["结束原因"], "stop")

            self.assertEqual(len(上游.记录), 1, "上游未收到请求")
            体 = 上游.记录[0]["请求体"]
            self.assertEqual(体["model"], "测试模型")
            self.assertEqual(体["temperature"], 0.3)
            self.assertEqual(体["max_tokens"], 64)
            self.assertEqual(体["tools"][0]["function"]["name"], "查天气")
            self.assertEqual(体["response_format"], {"type": "json_object"})
            self.assertNotIn("max_output_tokens", 体, "chat 协议不应出现 codex 令牌键")
        finally:
            if 句柄:
                释放句柄(句柄)
            上游.关闭()

    def test_codex协议生成参数按responses映射(self) -> None:
        上游 = _回显上游()
        句柄 = None
        try:
            句柄 = self._连接(上游, "codex_responses")
            对话 = 生成对话(句柄, [{"role": "user", "content": "契约"}],
                            温度=0.1, 最大令牌数=32,
                            响应格式={"type": "json_object"})

            self.assertTrue(对话.成功, f"生成对话失败: {对话.错误说明}")
            self.assertEqual(len(上游.记录), 1, "上游未收到请求")
            记录 = 上游.记录[0]
            self.assertTrue(记录["路径"].endswith("/responses"), 记录["路径"])
            体 = 记录["请求体"]
            self.assertEqual(体["temperature"], 0.1)
            self.assertEqual(体["max_output_tokens"], 32)
            self.assertEqual(体["text"], {"format": {"type": "json_object"}})
            self.assertNotIn("response_format", 体, "responses 协议不应出现 chat 格式键")
            self.assertNotIn("messages", 体, "responses 协议用 input 承载消息")
        finally:
            if 句柄:
                释放句柄(句柄)
            上游.关闭()

    def test_附加请求头覆盖连接级同名键(self) -> None:
        上游 = _回显上游()
        句柄 = None
        try:
            连接 = 连接LLM(模型="测试模型", 提供者="本地", 部署形态="本地",
                          url=f"http://127.0.0.1:{上游.端口}/v1", 协议="chat_completions",
                          额外请求头={"X-Tier": "conn-tier", "X-Both": "conn-both"})
            self.assertTrue(连接.成功, 连接.错误说明)
            assert isinstance(连接.值, dict)
            句柄 = 连接.值["句柄"]

            对话 = 生成对话(句柄, [{"role": "user", "content": "契约"}],
                            附加请求头={"X-Both": "call-both"})
            self.assertTrue(对话.成功, f"生成对话失败: {对话.错误说明}")

            头 = 上游.记录[0]["请求头"]
            self.assertEqual(头.get("x-tier"), "conn-tier")
            self.assertEqual(头.get("x-both"), "call-both", "单次级应覆盖连接级同名键")
        finally:
            if 句柄:
                释放句柄(句柄)
            上游.关闭()


if __name__ == "__main__":
    unittest.main()
