"""网络请求：3xx 响应必须把响应头（含 Location）带出，供调用方经唯一入口逐跳跟随。

`发送请求` 是出站 HTTP 的唯一入口，自带 SSRF 校验（回环/内网/保留地址默认拒绝）。
它若在 3xx 时只回传状态码、丢掉响应头，调用方就拿不到 `Location`：只能
「关掉自动重定向 → 手工 urllib 读 Location → 再手工发下一跳」，而手工那一跳
**绕过了本能力的 SSRF 防线**。所以 3xx 的响应头必须原样带出，让逐跳跟随
始终经本能力进行（每一跳都重跑 SSRF 校验）。

本文件锁定：
- 禁止自动重定向时，失败结果携带 状态码=3xx 与完整响应头（含 Location）；
- 默认行为仍是自动跟随到终点 200（不被本次改动破坏）；
- SSRF 防线不因此松动（未开 允许回环 时回环地址仍被拒）。
"""

from __future__ import annotations

import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from 支持库.后端.网络通信支持库.请求 import 发送请求


class _重定向上游:
    """/hop 返回 302 + Location: /dest；/dest 返回 200；其余 404。"""

    def __init__(self) -> None:
        self.路径记录: list[str] = []
        self.服务 = ThreadingHTTPServer(("127.0.0.1", 0), self._造处理器())
        self.端口 = self.服务.server_port
        self.线程 = threading.Thread(target=self.服务.serve_forever, daemon=True)
        self.线程.start()

    def _造处理器(self):
        路径记录 = self.路径记录

        class 处理器(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args) -> None:
                pass

            def do_GET(self) -> None:
                路径记录.append(self.path)
                if self.path == "/hop":
                    self.send_response(302)
                    self.send_header("Location", "/dest")
                    self.send_header("X-Redirect-Source", "localtest")
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                if self.path == "/dest":
                    正文 = "到达终点".encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "text/plain; charset=utf-8")
                    self.send_header("Content-Length", str(len(正文)))
                    self.end_headers()
                    self.wfile.write(正文)
                    return
                self.send_response(404)
                self.send_header("Content-Length", "0")
                self.end_headers()

        return 处理器

    def 关闭(self) -> None:
        self.服务.shutdown()
        self.服务.server_close()
        self.线程.join(timeout=2)

    def 地址(self, 路径: str) -> str:
        return f"http://127.0.0.1:{self.端口}{路径}"


class 测试网络请求重定向契约(unittest.TestCase):
    def test_禁止跟随重定向时回传状态码与完整响应头(self) -> None:
        上游 = _重定向上游()
        try:
            结果 = 发送请求(地址=上游.地址("/hop"), 允许回环=True, 跟随重定向=False)

            self.assertFalse(结果.成功, "3xx 不得包装成成功结果")
            self.assertEqual(结果.错误码, "HTTP错误")
            详情 = 结果.详细信息
            self.assertEqual(详情.get("状态码"), 302)
            响应头 = {str(键).lower(): 值 for 键, 值 in (详情.get("响应头") or {}).items()}
            self.assertEqual(响应头.get("location"), "/dest", "3xx 必须带出 Location")
            self.assertEqual(响应头.get("x-redirect-source"), "localtest", "3xx 响应头应完整带出")
        finally:
            上游.关闭()

    def test_默认自动跟随重定向到终点(self) -> None:
        上游 = _重定向上游()
        try:
            结果 = 发送请求(地址=上游.地址("/hop"), 允许回环=True)

            self.assertTrue(结果.成功, f"默认应自动跟随: {结果.错误说明}")
            assert isinstance(结果.值, dict)
            self.assertEqual(结果.值["状态码"], 200)
            self.assertIn("到达终点", 结果.值["响应文本"])
            self.assertEqual(上游.路径记录, ["/hop", "/dest"], "默认应自动跳转到终点")
        finally:
            上游.关闭()

    def test_回环地址未放行时仍被SSRF拒绝(self) -> None:
        上游 = _重定向上游()
        try:
            结果 = 发送请求(地址=上游.地址("/hop"))

            self.assertFalse(结果.成功, "未开 允许回环 时回环地址必须被拒")
            self.assertEqual(结果.错误码, "参数不合法")
            self.assertIn("SSRF", 结果.错误说明)
        finally:
            上游.关闭()


if __name__ == "__main__":
    unittest.main()
