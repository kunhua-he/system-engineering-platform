"""浏览器验证页和受控代理服务。"""
from __future__ import annotations
import json, threading, urllib.error, urllib.parse, urllib.request, uuid
from pathlib import Path
from 开发工具.HTML验证.常量 import 默认超时秒, 请求上限字节
from 开发工具.HTML验证.HTTP请求 import _校验直连地址
from 开发工具.HTML验证.场景加载 import _加载场景
from 开发工具.HTML验证.场景执行器 import _执行场景束
from 开发工具.HTML验证.验证证据 import 生成场景文件
from 公共契约.基础类型.逻辑类型 import 真, 假
from 公共契约.运行时.有界HTTP import 有界线程HTTP服务器
def 服务模式(制品地址: str, 服务端口: int = 45081, 制品目录: Path | None = None) -> int:
    from http.server import BaseHTTPRequestHandler

    制品地址 = _校验直连地址(制品地址)
    页面字节 = (Path(__file__).resolve().parent / "验证页.html").read_bytes()
    场景字节 = json.dumps({"来源": "包级验证场景引用", "验证场景": []}, ensure_ascii=False).encode()
    场景束: 验证场景束 | None = None
    if 制品目录 is not None:
        场景束 = _加载场景(制品目录, None)
        场景路径 = 生成场景文件(制品目录)
        场景字节 = 场景路径.read_bytes()
    执行锁 = threading.Lock()
    CSP = "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"

    class 处理器(BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            del format, args

        def _公共头(self) -> None:
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", CSP)

        def do_GET(self) -> None:
            解码路径 = urllib.parse.unquote(self.path)
            if 解码路径 in {"/", "/验证页.html"}:
                self.send_response(200)
                self._公共头()
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(页面字节)))
                self.end_headers()
                self.wfile.write(页面字节)
                return
            if 解码路径 == "/验证场景.json":
                self.send_response(200)
                self._公共头()
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(场景字节)))
                self.end_headers()
                self.wfile.write(场景字节)
                return
            if 解码路径 == "/代理/":
                self._转发("GET", 制品地址 + "/")
                return
            self.send_error(404)

        def do_POST(self) -> None:
            解码路径 = urllib.parse.unquote(self.path)
            if 解码路径 == "/执行验证":
                if 制品目录 is None or 场景束 is None:
                    self.send_error(409, "服务未绑定制品场景")
                    return
                with 执行锁:
                    报告 = _执行场景束(制品目录, 场景束, 制品地址)
                返回 = json.dumps(报告.转字典(), ensure_ascii=False).encode("utf-8")
                self.send_response(200 if 报告.失败数 == 0 else 409)
                self._公共头()
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(返回)))
                self.end_headers()
                self.wfile.write(返回)
                return
            self.send_error(404)

        def _转发(self, 方法: str, 目标: str, 正文: bytes = b"") -> None:
            拆分 = urllib.parse.urlsplit(目标)
            编码目标 = f"{拆分.scheme}://{拆分.netloc}{urllib.parse.quote(拆分.path, safe='/:@._-')}"
            try:
                请求 = urllib.request.Request(
                    编码目标, data=正文 or None, method=方法,
                    headers={"Content-Type": "application/json"},
                )
                with urllib.request.urlopen(请求, timeout=默认超时秒) as 响应:
                    状态码, 返回 = 响应.status, 响应.read(请求上限字节)
            except urllib.error.HTTPError as 错误:
                # #169（2026-09-20）：原实现只 `finally: 错误.close()` —— 若 `错误.read()`
                # 抛 OSError（连接中途断开 / 响应体解码失败），该异常**不在本 except 的
                # 捕获类型内**，也不会落到下面那个 except（一个 try 只进一个 except 分支），
                # 于是直接逃逸到 HTTPServer 顶层：调用方拿到的是连接被掐断（curl 52），
                # 而不是本服务约定的结构化 502「网关断开」。
                # 现把读取失败收成同一口径的结构化错误，保持出口唯一。
                try:
                    状态码, 返回 = 错误.code, 错误.read(请求上限字节)
                except OSError as 读取错误:
                    状态码 = 502
                    返回 = json.dumps({
                        "成功": 假, "值": None, "错误码": "网关断开",
                        "错误说明": f"读取错误响应体失败: {读取错误}",
                        "可重试": 真, "请求id": uuid.uuid4().hex, "耗时毫秒": 0,
                    }, ensure_ascii=False).encode()
                finally:
                    错误.close()
            except (urllib.error.URLError, TimeoutError, OSError) as 错误:
                状态码 = 502
                返回 = json.dumps({
                    "成功": False, "值": None, "错误码": "网关断开", "错误说明": str(错误),
                    "可重试": True, "请求id": uuid.uuid4().hex, "耗时毫秒": 0,
                }, ensure_ascii=False).encode()
            self.send_response(状态码)
            self._公共头()
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(返回)))
            self.end_headers()
            self.wfile.write(返回)

    服务 = 有界线程HTTP服务器(("127.0.0.1", 服务端口), 处理器)
    print(f"验证页已启动: http://127.0.0.1:{服务.server_port}/ （代理到 {制品地址}）")
    try:
        服务.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        服务.shutdown()
        服务.server_close()
    return 0
