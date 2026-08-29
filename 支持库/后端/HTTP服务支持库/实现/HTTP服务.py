"""独立、有限资源的本地 HTTP 能力服务。"""

from __future__ import annotations

import json
import ipaddress
import socket
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn
from typing import Any, Callable

内部调用路径 = "/内部/能力调用"


class _线程HTTP服务器(ThreadingMixIn, HTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, 地址, 处理器类, 并发上限: int):
        super().__init__(地址, 处理器类)
        self.并发信号 = threading.BoundedSemaphore(max(1, 并发上限))


class HTTP服务:
    """提供健康检查和 JSON 能力调用的独立 HTTP 服务。"""

    def __init__(self, *, 地址: str = "127.0.0.1", 端口: int = 0,
                 并发上限: int = 16, 请求体上限: int = 1024 * 1024,
                 启动重试次数: int = 2, 请求超时秒: float = 10.0) -> None:
        self.地址, self.端口 = 地址, 端口
        self.并发上限 = max(1, int(并发上限))
        self.请求体上限 = max(1, int(请求体上限))
        self.启动重试次数 = max(0, int(启动重试次数))
        if 请求超时秒 <= 0:
            raise ValueError("请求超时秒必须大于 0")
        self.请求超时秒 = float(请求超时秒)
        self.能力表: dict[str, Callable[[dict[str, Any]], Any]] = {}
        self.契约表: dict[str, dict[str, Any]] = {}
        self._服务器: _线程HTTP服务器 | None = None
        self._线程: threading.Thread | None = None
        self._锁 = threading.RLock()

    @property
    def 实际端口(self) -> int:
        return self._服务器.server_address[1] if self._服务器 else 0

    @property
    def 已启动(self) -> bool:
        return self._服务器 is not None

    def 注册能力(self, 能力id: str, 实现函数: Callable, 契约: dict[str, Any] | None = None) -> None:
        if not isinstance(能力id, str) or not 能力id or not callable(实现函数):
            raise ValueError("能力id或实现函数不合法")
        with self._锁:
            if 能力id in self.能力表 and self.能力表[能力id] is not 实现函数:
                raise ValueError(f"能力重复注册：{能力id}")
            self.能力表[能力id] = 实现函数
            if 契约 is not None:
                self.契约表[能力id] = dict(契约)

    def 启动(self) -> int:
        with self._锁:
            if self._服务器 is not None:
                return self.实际端口
            try:
                解析地址 = ipaddress.ip_address(str(self.地址))
            except ValueError:
                try:
                    解析地址 = ipaddress.ip_address(socket.gethostbyname(str(self.地址)))
                except (OSError, ValueError) as 错误:
                    raise ValueError("HTTP服务监听地址无法解析") from 错误
            if not 解析地址.is_loopback:
                raise ValueError("HTTP服务仅允许回环监听地址")
            最后错误 = None
            for _ in range(self.启动重试次数 + 1):
                try:
                    服务对象 = self
                    class 处理器(BaseHTTPRequestHandler):
                        def setup(self):
                            super().setup()
                            # 请求行、请求头和请求体都必须有硬截止，避免
                            # 慢体连接永久占用 ThreadingMixIn 线程与 FD。
                            self.connection.settimeout(服务对象.请求超时秒)
                        def do_GET(self):
                            服务对象._处理GET(self)
                        def do_POST(self):
                            服务对象._处理POST(self)
                        def log_message(self, *args):
                            return
                        def _方法不允许(self):
                            服务对象._响应(self, 405, {
                                "成功": False, "错误码": "方法不允许",
                                "错误说明": f"仅支持 GET /健康、POST {内部调用路径}",
                            })
                        do_PUT = _方法不允许
                        do_PATCH = _方法不允许
                        do_DELETE = _方法不允许
                        do_HEAD = _方法不允许
                    self._服务器 = _线程HTTP服务器((self.地址, self.端口), 处理器, self.并发上限)
                    self._线程 = threading.Thread(target=self._服务器.serve_forever, daemon=True,
                                                   name="HTTP服务")
                    self._线程.start()
                    return self.实际端口
                except OSError as 错误:
                    最后错误 = 错误
            raise OSError(f"HTTP服务启动失败：{最后错误}")

    def 停止(self) -> None:
        with self._锁:
            服务对象, self._服务器 = self._服务器, None
            服务线程, self._线程 = self._线程, None
        if 服务对象 is not None:
            # 排空：先阻止新请求，再关闭监听；对服务线程有界 join，确认
            # 线程已退出才返回，避免停止后仍有请求线程/处理器在运行。
            服务对象.shutdown()
            服务对象.server_close()
        if 服务线程 is not None:
            服务线程.join(timeout=5.0)
            if 服务线程.is_alive():
                raise OSError("HTTP服务停止未收敛：服务线程 5 秒内未退出")

    def 健康(self) -> dict[str, Any]:
        return {"成功": self.已启动, "状态": "正常" if self.已启动 else "已停止",
                "端口": self.实际端口, "能力数": len(self.能力表)}

    def _响应(self, 请求, 状态码: int, 数据: dict[str, Any]) -> None:
        try:
            原文 = json.dumps(
                数据, ensure_ascii=False, allow_nan=False,
                separators=(",", ":"),
            ).encode("utf-8")
        except (TypeError, ValueError):
            # 能力返回值无法传输属于服务端契约故障，不能伪装成请求参数错误。
            状态码 = 502
            原文 = json.dumps({
                "成功": False, "值": None,
                "错误码": "返回结果不符合契约",
                "错误说明": "能力返回值无法传输",
            }, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        请求.send_response(状态码)
        请求.send_header("Content-Type", "application/json; charset=utf-8")
        请求.send_header("Content-Length", str(len(原文)))
        请求.end_headers()
        请求.wfile.write(原文)

    def _处理GET(self, 请求) -> None:
        with self._锁:
            服务对象 = self._服务器
        if 服务对象 is None or not 服务对象.并发信号.acquire(blocking=False):
            self._响应(请求, 429, {"成功": False, "错误码": "并发超限", "错误说明": "服务繁忙"})
            return
        try:
            路径 = urllib.parse.unquote(请求.path)
            if 路径 == "/健康":
                self._响应(请求, 200, self.健康())
            else:
                self._响应(请求, 404, {"成功": False, "错误码": "路径不存在", "错误说明": "路径不存在"})
        finally:
            服务对象.并发信号.release()

    def _处理POST(self, 请求) -> None:
        # 捕获本次请求所属服务器的固定信号量；停止流程会先清空
        # self._服务器，不能在 finally 再读取可变属性。
        with self._锁:
            服务对象 = self._服务器
        if 服务对象 is None:
            self._响应(请求, 503, {"成功": False, "错误码": "外部不可访问", "错误说明": "HTTP服务已停止"})
            return
        if not 服务对象.并发信号.acquire(blocking=False):
            self._响应(请求, 429, {"成功": False, "错误码": "并发超限", "错误说明": "服务繁忙"})
            return
        try:
            try:
                长度 = int(请求.headers.get("Content-Length", "0"))
            except (TypeError, ValueError):
                self._响应(请求, 400, {"成功": False, "错误码": "参数不合法", "错误说明": "请求长度不合法"})
                return
            if 长度 < 0 or 长度 > self.请求体上限:
                self._响应(请求, 413, {"成功": False, "错误码": "请求过大", "错误说明": "请求体超过上限"})
                return
            if 长度 and "application/json" not in (请求.headers.get("Content-Type", "")).lower():
                self._响应(请求, 415, {"成功": False, "错误码": "参数不合法", "错误说明": "请求正文必须使用 JSON"})
                return
            # socket.read(n) 允许短读；必须循环读满 Content-Length，避免
            # 并发/分片到达时把完整 JSON 截断后误判为业务错误。
            缓冲 = bytearray()
            while len(缓冲) < 长度:
                块 = 请求.rfile.read(长度 - len(缓冲))
                if not 块:
                    self._响应(请求, 400, {
                        "成功": False, "错误码": "请求结构错误",
                        "错误说明": "请求正文短读，连接提前结束",
                    })
                    return
                缓冲.extend(块)
            原文 = bytes(缓冲)
            路径 = urllib.parse.unquote(请求.path)
            if 路径 == "/健康":
                self._响应(请求, 200, self.健康()); return
            if 路径 != 内部调用路径:
                self._响应(请求, 404, {"成功": False, "错误码": "路径不存在", "错误说明": "路径不存在"}); return
            if 请求.headers.get("X-Internal-Call", "") != "1":
                self._响应(请求, 403, {"成功": False, "错误码": "内部调用被拒绝", "错误说明": "缺少内部调用标记"}); return
            try:
                数据 = json.loads(原文.decode("utf-8"))
                if not isinstance(数据, dict):
                    raise TypeError("请求正文必须是 JSON 对象")
                能力id = 数据.get("能力id")
                参数 = 数据.get("参数", {})
                if not isinstance(能力id, str) or not 能力id:
                    raise ValueError("缺少能力id")
                if not isinstance(参数, dict):
                    raise TypeError("参数必须是对象")
                函数 = self.能力表[能力id]
                值 = 函数(参数)
                self._响应(请求, 200, {"成功": True, "值": 值, "错误码": "", "错误说明": ""})
            except (json.JSONDecodeError, UnicodeDecodeError, TypeError, ValueError):
                self._响应(请求, 400, {"成功": False, "错误码": "参数不合法", "错误说明": "请求参数不符合契约"})
            except KeyError:
                self._响应(请求, 400, {"成功": False, "错误码": "能力不存在", "错误说明": "能力未注册"})
            except Exception:
                self._响应(请求, 500, {"成功": False, "错误码": "提供者异常", "错误说明": "能力执行失败"})
        finally:
            服务对象.并发信号.release()
