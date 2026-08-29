"""HTTP 真实提供者：真实本地 HTTP 服务（线程化）+ 真实 HTTP 客户端请求。

中文契约：
- 启动(处理器, 端口=0)：线程化起真实本地服务（127.0.0.1），0=随机端口。
- 请求(路径, 方法, 数据, 超时秒)：真实 urllib 请求 → 统一结果字典。
- 停止()：优雅关闭（shutdown + server_close）并释放端口，幂等可重复调用。

能力：状态码 / 超时（socket 超时）/ 取消（客户端断开、服务端终止）/
响应大小上限（截断）/ 连接释放（HTTP/1.0 每请求关闭）/ 有限重试边界。
"""

import http.server
import socket
import socketserver
import threading
import time
import urllib.error
import urllib.parse
import urllib.request


class 请求处理器(http.server.BaseHTTPRequestHandler):
    """真实请求处理器：转发处理器函数，支持任意状态码/JSON/延迟/大响应。"""

    处理器函数 = None
    活动连接数 = 0  # 子类实例级覆盖（type(self) 访问，多实例互不污染）
    连接锁 = threading.Lock()
    protocol_version = "HTTP/1.0"  # 每请求后关闭连接 → 连接释放

    def setup(self):
        super().setup()
        # 在解析请求头和读取正文前即设置硬截止，防止慢请求头耗尽线程/FD。
        self.connection.settimeout(10.0)
        with type(self).连接锁:
            type(self).活动连接数 += 1

    def finish(self):
        try:
            super().finish()
        finally:
            with type(self).连接锁:
                type(self).活动连接数 -= 1

    def do_GET(self):
        self._执行()

    def do_POST(self):
        self._执行()

    def _执行(self):
        try:
            长度 = int(self.headers.get("Content-Length") or 0)
            请求体 = self.rfile.read(长度) if 长度 else b""
            # 客户端可能发送 percent-编码路径（中文），解码后交给处理器（中文契约）
            解码路径 = urllib.parse.unquote(self.path)
            状态码, 响应体, 头部 = self.处理器函数(解码路径, self.command, 请求体)
            if isinstance(响应体, str):
                响应体 = 响应体.encode("utf-8")
            self.send_response(状态码)
            for 键, 值 in 头部.items():
                self.send_header(键, 值)
            self.send_header("Content-Length", str(len(响应体)))
            self.end_headers()
            self.wfile.write(响应体)
        except Exception:
            try:
                self.send_error(500, "处理器异常")
            except Exception:
                pass  # 连接已断开（客户端取消），无需再响应

    def log_message(self, 格式, *参数):
        pass  # 静默访问日志


class 线程HTTP服务(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True      # 优雅关闭不等待进行中的慢请求线程
    allow_reuse_address = True  # 停止后端口可立即重新绑定

class HTTP提供者:
    """HTTP 真实提供者：启动 / 请求 / 停止 中文契约。"""

    def __init__(self, 响应大小上限=1024 * 1024, 重试次数=2, 重试退避基数=0.05):
        self.响应大小上限, self.重试次数, self.重试退避基数 = 响应大小上限, 重试次数, 重试退避基数
        self._服务, self._端口, self._处理器类 = None, 0, None

    @property
    def 端口(self):
        return self._端口

    @property
    def 活动连接数(self):
        return self._处理器类.活动连接数 if self._处理器类 else 0

    def 启动(self, 处理器, 端口=0):
        """起真实本地 HTTP 服务；返回实际监听端口（0 表示随机）。"""
        if self._服务 is not None:
            raise RuntimeError("服务已在运行，请先停止")
        # staticmethod：防止普通函数作为类属性被描述符绑定（多传 self 导致处理器崩溃）
        # 活动连接数/锁 实例级：多提供者实例互不污染
        处理器类 = type("带处理器请求类", (请求处理器,), {
            "处理器函数": staticmethod(处理器), "活动连接数": 0,
            "连接锁": threading.Lock()})
        self._处理器类 = 处理器类
        self._服务 = 线程HTTP服务(("127.0.0.1", 端口), 处理器类)
        self._端口 = self._服务.server_address[1]
        threading.Thread(target=self._服务.serve_forever, daemon=True).start()
        return self._端口

    def 停止(self):
        """优雅关闭并释放端口；幂等，可重复调用。"""
        if self._服务 is None:
            return
        服务 = self._服务
        self._服务 = None
        服务.shutdown()
        服务.server_close()

    def 请求(self, 路径, 方法="GET", 数据=None, 超时秒=5, 响应上限=None):
        """真实 HTTP 请求；超限截断；连接类失败有限重试（指数退避）。"""
        上限 = self.响应大小上限 if 响应上限 is None else 响应上限
        编码路径 = urllib.parse.quote(路径, safe="/%?&=")  # 中文路径真实可用
        地址 = f"http://127.0.0.1:{self._端口}{编码路径}"
        最后错误 = ""
        for 尝试 in range(self.重试次数 + 1):
            结果 = self._单次请求(地址, 方法, 数据, 超时秒, 上限)
            if 结果["成功"] or not 结果["可重试"]:
                return 结果
            最后错误 = 结果["错误"]
            time.sleep(self.重试退避基数 * (2 ** 尝试))
        return {"成功": False, "状态码": 0, "响应": b"", "头部": {}, "截断": False,
                "错误": f"重试 {self.重试次数} 次后仍失败：{最后错误}",
                "重试次数": self.重试次数}

    def _单次请求(self, 地址, 方法, 数据, 超时秒, 上限):
        请求对象 = urllib.request.Request(地址, data=数据, method=方法)
        try:
            with urllib.request.urlopen(请求对象, timeout=超时秒) as 响应:
                响应体, 截断 = self._受限读取(响应, 上限)
                return {"成功": True, "状态码": 响应.status, "响应": 响应体,
                        "头部": dict(响应.headers.items()), "截断": 截断,
                        "错误": "", "可重试": False, "重试次数": 0}
        except urllib.error.HTTPError as 错误:
            响应体, 截断 = self._受限读取(错误, 上限)
            return {"成功": False, "状态码": 错误.code, "响应": 响应体,
                    "头部": dict(错误.headers.items()), "截断": 截断,
                    "错误": f"HTTP 状态码 {错误.code}", "可重试": False, "重试次数": 0}
        except Exception as 错误:
            if isinstance(错误, socket.timeout) or (
                    isinstance(错误, urllib.error.URLError)
                    and isinstance(错误.reason, socket.timeout)):
                return {"成功": False, "状态码": 0, "响应": b"", "头部": {}, "截断": False,
                        "错误": f"请求超时（{超时秒} 秒）", "可重试": False, "重试次数": 0}
            可重试 = isinstance(错误, (ConnectionRefusedError, ConnectionResetError))
            if isinstance(错误, urllib.error.URLError):
                可重试 = isinstance(错误.reason,
                                   (ConnectionRefusedError, ConnectionResetError))
            return {"成功": False, "状态码": 0, "响应": b"", "头部": {}, "截断": False,
                    "错误": f"请求失败：{错误}", "可重试": 可重试, "重试次数": 0}

    @staticmethod
    def _受限读取(文件对象, 上限):
        数据 = bytearray()
        while len(数据) <= 上限:
            块 = 文件对象.read(上限 + 1 - len(数据))
            if not 块:
                break
            数据.extend(块)
        return bytes(数据[:上限]), len(数据) > 上限
