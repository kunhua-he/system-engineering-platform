"""统一有界线程 HTTP 服务：超过并发预算时拒绝新连接。

**本模块是全仓唯一的有界线程 HTTP 实现（2026-09-24 批Q · Q-i 收口）**：收口前
`运行核心/统一网关/安全/有界服务器.py` 另养一份同名实现，两份的差异是**行为**
不是冗余，故逐项参数化后只留下层（本模块）一处实现（哲学 1.3 结果唯一即收口）：

- `满载响应回调`：满载时先写响应再关连接。缺省 `None` ＝不写响应、只关连接
  （本模块原行为，域外调用方逐字不变）；网关域注入 `_写限流响应` 写
  `429 + 网关响应信封 JSON`。**满载响应体属网关协议，本模块不得认识它**
  （否则下层反向依赖运行核心，破分层铁律）。
- `请求队列上限`：缺省 `None` ＝不动 `request_queue_size`（本模块原行为）；
  网关域传 `min(128, 最大工作线程)`。
- 计数与连接诊断（`活动工作线程数` / `拒绝请求数` / `记录连接诊断` /
  `连接诊断快照`）原先只有网关域有，现下沉到本模块一处 —— 域外调用方只增属性、
  行为不变。
"""

from __future__ import annotations

import threading
from http.server import ThreadingHTTPServer
from typing import Any


class 有界线程HTTP服务器(ThreadingHTTPServer):
    """线程 HTTP 服务的统一并发上限实现。

    **在线程创建前执行预算**：预算不足时不排进队列、不阻塞监听，直接按
    `满载响应回调` 的出口处理（缺省只关连接、不回响应）。
    """

    daemon_threads = True
    block_on_close = True

    def __init__(self, *参数: Any, 最大线程数: int = 32,
                 满载响应回调: Any = None, 请求队列上限: int | None = None,
                 **关键字: Any) -> None:
        # `request_queue_size` 必须赶在 `super().__init__`（建监听 socket）之前生效。
        if 请求队列上限 is not None:
            self.request_queue_size = int(请求队列上限)
        super().__init__(*参数, **关键字)
        self._线程信号量 = threading.BoundedSemaphore(max(1, int(最大线程数)))
        self._满载响应回调 = 满载响应回调
        self._计数锁 = threading.Lock()
        self.活动工作线程数 = 0
        self.拒绝请求数 = 0
        self._连接诊断: list[dict[str, Any]] = []

    def process_request(self, 请求: Any, 客户端地址: Any) -> None:  # type: ignore[override]
        if not self._线程信号量.acquire(blocking=False):
            with self._计数锁:
                self.拒绝请求数 += 1
            if self._满载响应回调 is not None:
                self._满载响应回调(请求)
            self.shutdown_request(请求)
            return
        with self._计数锁:
            self.活动工作线程数 += 1

        def 执行() -> None:
            try:
                self.process_request_thread(请求, 客户端地址)
            finally:
                self._归还线程预算()

        try:
            threading.Thread(target=执行, daemon=True, name="有界HTTP请求").start()
        except BaseException:
            # 线程没起来也必须把预算还回去，否则一次失败永久吃掉一个并发额度。
            self._归还线程预算()
            raise

    def _归还线程预算(self) -> None:
        with self._计数锁:
            self.活动工作线程数 = max(0, self.活动工作线程数 - 1)
        self._线程信号量.release()

    def 记录连接诊断(self, 类型: str, 错误: BaseException | str = "") -> None:
        with self._计数锁:
            self._连接诊断.append({
                "类型": str(类型)[:32],
                "异常类型": type(错误).__name__ if isinstance(错误, BaseException) else "",
            })
            if len(self._连接诊断) > 100:
                del self._连接诊断[:-100]

    def 连接诊断快照(self) -> list[dict[str, Any]]:
        with self._计数锁:
            return [dict(项) for 项 in self._连接诊断]
