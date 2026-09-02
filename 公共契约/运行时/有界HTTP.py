"""统一有界线程 HTTP 服务：超过并发预算时拒绝新连接。"""

from __future__ import annotations

import threading
from http.server import ThreadingHTTPServer
from typing import Any


class 有界线程HTTP服务器(ThreadingHTTPServer):
    """线程 HTTP 服务的统一并发上限实现。"""

    daemon_threads = True
    block_on_close = True

    def __init__(self, *参数: Any, 最大线程数: int = 32, **关键字: Any) -> None:
        super().__init__(*参数, **关键字)
        self._线程信号量 = threading.BoundedSemaphore(max(1, int(最大线程数)))

    def process_request(self, 请求: Any, 客户端地址: Any) -> None:  # type: ignore[override]
        if not self._线程信号量.acquire(blocking=False):
            self.shutdown_request(请求)
            return

        def 执行() -> None:
            try:
                self.process_request_thread(请求, 客户端地址)
            finally:
                self._线程信号量.release()

        threading.Thread(target=执行, daemon=True, name="有界HTTP请求").start()
