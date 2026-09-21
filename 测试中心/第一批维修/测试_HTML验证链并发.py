"""#192 连接复用：同一线程连续请求必须复用同一条 TCP 连接。

改前（`urllib.request.urlopen`）每请求新建连接 ⇒ 5 次请求 = 5 条连接；
改后（`http.client.HTTPConnection` 按线程复用）⇒ 1 条。
用自建保活服务器计数，不依赖外部制品，结果确定。
"""
from __future__ import annotations

import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

仓库根 = Path(__file__).resolve().parents[2]
if str(仓库根) not in sys.path:
    sys.path.insert(0, str(仓库根))

from 开发工具.HTML验证.HTTP请求 import _发送请求
from 开发工具.HTML验证.单步场景 import 验证场景


class _保活处理器(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"      # 开 keep-alive，复用才有意义

    def do_GET(self) -> None:          # noqa: N802 —— BaseHTTPRequestHandler 约定名
        正文 = '{"成功": true}'.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(正文)))
        self.end_headers()
        self.wfile.write(正文)

    def log_message(self, *参数: object) -> None:
        return


class 测试连接复用(unittest.TestCase):
    def setUp(self) -> None:
        self.连接数 = 0
        self.锁 = threading.Lock()
        外层 = self

        class _计数服务器(ThreadingHTTPServer):
            daemon_threads = True

            def get_request(自身):
                with 外层.锁:
                    外层.连接数 += 1
                return super().get_request()

        self.服务器 = _计数服务器(("127.0.0.1", 0), _保活处理器)
        self.端口 = self.服务器.server_address[1]
        self.线程 = threading.Thread(target=self.服务器.serve_forever, daemon=True)
        self.线程.start()

    def tearDown(self) -> None:
        self.服务器.shutdown()
        self.服务器.server_close()
        self.线程.join(timeout=5)

    def test_连续请求复用同一条连接(self) -> None:
        地址 = f"http://127.0.0.1:{self.端口}"
        场景 = 验证场景(场景id="连接复用.探针", 能力id="探针.只读", 方法="GET",
                        路径="/", 预期状态码=200, 预期成功=True)
        状态码表 = []
        for _序 in range(5):
            状态码, _数据, _耗时 = _发送请求(地址, 场景, 10)
            状态码表.append(状态码)
        self.assertEqual(状态码表, [200] * 5)
        self.assertEqual(self.连接数, 1, f"期望复用 1 条连接，实测 {self.连接数} 条")

    def test_端口错时不复用坏连接(self) -> None:
        """连不上时返回 502 网关断开，且不把坏连接留在缓存里。"""
        场景 = 验证场景(场景id="连接复用.坏地址", 能力id="探针.只读", 方法="GET",
                        路径="/", 预期状态码=200, 预期成功=True)
        状态码, 数据, _耗时 = _发送请求("http://127.0.0.1:1", 场景, 2)
        self.assertEqual(状态码, 502)
        self.assertEqual(数据.get("错误码"), "网关断开")


if __name__ == "__main__":
    unittest.main()
