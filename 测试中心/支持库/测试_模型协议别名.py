"""模型协议别名：短值 chat/res 与长值 chat_completions/codex_responses 必须同一裁决。

同一份协议名有两处入口：
- 连接器 `模型连接器.连接LLM`，经 `_规范化协议` 把 chat→chat_completions、res→codex_responses；
- 适配层 `模型HTTP提供者.调用对话` / `流式调用对话`，直接吃 配置["协议"]。

历史缺陷：`流式调用对话` 抄了一份局部别名表收短值，而 `调用对话` 不归一化，
短值直接落到「协议必须是 chat_completions 或 codex_responses」的失败分支 ——
**同一文件内两个能力对同一种入参裁决不一致**，且两份别名表各自维护、随时会漂移。

本文件锁定：短值/长值两处都收；两份别名表取值一致（漂移守卫）。
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
    """OpenAI 兼容上游：按路径回 chat / responses 两种形状，并记录收到的请求。"""

    def __init__(self) -> None:
        self.路径记录: list[str] = []
        self.锁 = threading.Lock()
        self.服务 = ThreadingHTTPServer(("127.0.0.1", 0), self._造处理器())
        self.端口 = self.服务.server_port
        self.线程 = threading.Thread(target=self.服务.serve_forever, daemon=True)
        self.线程.start()

    def _造处理器(self):
        路径记录, 锁 = self.路径记录, self.锁

        class 处理器(BaseHTTPRequestHandler):
            def log_message(self, *args) -> None:
                pass

            def do_POST(self) -> None:
                长度 = int(self.headers.get("Content-Length") or 0)
                if 长度:
                    self.rfile.read(长度)
                with 锁:
                    路径记录.append(self.path)
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

        return 处理器

    def 配置(self, 协议: str) -> dict:
        return {"url": f"http://127.0.0.1:{self.端口}/v1", "模型名": "测试模型", "协议": 协议}

    def 关闭(self) -> None:
        self.服务.shutdown()
        self.服务.server_close()
        self.线程.join(timeout=2)


class 测试协议别名裁决(unittest.TestCase):
    def test_别名表与连接器取值一致(self) -> None:
        别名 = getattr(模型HTTP提供者, "协议别名表", None)
        self.assertIsInstance(别名, dict, "适配层应暴露模块级 协议别名表 供两处以单一来源复用")
        self.assertEqual(别名, 连接器协议别名, "适配层与连接器的协议别名表已漂移，须对齐")

    def test_调用对话接受短值与长值(self) -> None:
        上游 = _回显上游()
        try:
            for 短值, 长值, 期望路径, 期望文本 in (
                ("chat", "chat_completions", "/chat/completions", "chat回显"),
                ("res", "codex_responses", "/responses", "res回显"),
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


if __name__ == "__main__":
    unittest.main()
