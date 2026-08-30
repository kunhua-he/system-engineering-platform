"""模型连接器：URL连接默认走OpenAI兼容HTTP。"""
from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading
import unittest

from 支持库.后端.大语言模型支持库.模型连接器 import (
    连接LLM, 连接向量模型, 连接重排模型,
    生成对话, 生成嵌入, 执行重排, 释放句柄,
)
from 支持库.后端.大语言模型支持库.模型连接器.实现 import 模型连接器 as 实现


class 处理器(BaseHTTPRequestHandler):
    def do_POST(self):
        长度 = int(self.headers.get("Content-Length", "0"))
        json.loads(self.rfile.read(长度) or b"{}")
        if self.path.endswith("/chat/completions"):
            值 = {"choices": [{"message": {"content": "场景通过"}}], "usage": {"total_tokens": 3}}
        elif self.path.endswith("/embeddings"):
            值 = {"data": [{"embedding": [0.1, 0.2]}]}
        else:
            值 = {"results": [{"index": 0, "relevance_score": 0.9}]}
        数据 = json.dumps(值).encode()
        self.send_response(200); self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(数据))); self.end_headers(); self.wfile.write(数据)
    def log_message(self, format: str, *args) -> None:
        pass


class 测试模型连接器HTTP(unittest.TestCase):
    def test_三种URL连接均有默认真实HTTP调用器(self) -> None:
        服务 = ThreadingHTTPServer(("127.0.0.1", 0), 处理器)
        线程 = threading.Thread(target=服务.serve_forever, daemon=True); 线程.start()
        地址 = f"http://127.0.0.1:{服务.server_port}/v1"
        句柄表 = []
        原调用函数表 = dict(实现.调用函数表)
        实现.调用函数表.clear()
        try:
            连接表 = [
                (连接LLM(模型="测试", 提供者="本地", 部署形态="本地", url=地址), "LLM"),
                (连接向量模型(模型="测试", 提供者="本地", 部署形态="本地", url=地址), "向量"),
                (连接重排模型(模型="测试", 提供者="本地", 部署形态="本地", url=地址), "重排"),
            ]
            for 连接, _ in 连接表:
                self.assertTrue(连接.成功, 连接.错误说明)
                assert isinstance(连接.值, dict)
                句柄表.append(连接.值["句柄"])
            对话 = 生成对话(句柄表[0], [{"role": "user", "content": "测试"}])
            嵌入 = 生成嵌入(句柄表[1], "测试")
            重排 = 执行重排(句柄表[2], "测试", ["文档"])
            assert isinstance(对话.值, dict) and isinstance(嵌入.值, dict) and isinstance(重排.值, dict)
            self.assertEqual(对话.值["回复"], "场景通过")
            self.assertEqual(嵌入.值["维度"], 2)
            self.assertEqual(重排.值["重排结果"][0]["索引"], 0)
        finally:
            for 句柄 in 句柄表:
                释放句柄(句柄)
            实现.调用函数表.clear(); 实现.调用函数表.update(原调用函数表)
            服务.shutdown(); 服务.server_close(); 线程.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
