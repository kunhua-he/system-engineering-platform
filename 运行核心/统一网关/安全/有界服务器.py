"""网关域唯一有界线程 HTTP 服务实现（`有界线程HTTP服务器`）。

**为什么独立成文件（2026-09-19 拆分）**：本类被 `本地网关.py` 与同包两个混入类
（`网关边界面.py` / `流式路由面.py`）共同依赖。若留在 `本地网关.py`，混入类只能
反向 `from 运行核心.统一网关.本地网关 import …`，而 `本地网关.py` 又要模块级导入
混入类 → 双向依赖（实测 `ImportError: cannot import name '有界线程HTTP服务器'
from partially initialized module`）。故按「被双方依赖的符号下沉到更底层模块」的
标准做法搬到本文件；`本地网关.py` 与 `流式HTTP.py` 的导入路径**原样再导出**，
`测试中心/运行核心/测试_优雅停机.py` 等调用点零改动。

**实现一字未改**：本文件正文＝拆分前 `本地网关.py` 第 242–343 行，逐字节搬动
（含顶部 22 行说明），无改名、无改签名、无改注释。本类是**网关域唯一的有界线程
实现**（满载写 `429 + 网关响应信封 JSON` 再关连接），**不得**改用
`公共契约/运行时/有界HTTP.py` 那份（满载 `shutdown_request` 不回任何响应）。

**导入方向**：本文件不导入 `统一网关` 同目录任何模块（含 `本地网关.py`），
也不导入 `网关核心.py` / `流式HTTP.py`，是最底层。
"""

from __future__ import annotations

import json
import sys
import threading
from http.server import ThreadingHTTPServer
from typing import Any

from 公共契约.基础类型.逻辑类型 import 假
from 公共契约.运行时.端口策略 import 校验应用监听端口


class 有界线程HTTP服务器(ThreadingHTTPServer):
    """在线程创建前执行预算；满载时同步返回结构化 429。

    **本类是本仓「网关域」（本地网关 + 流式HTTP）唯一的有界线程 HTTP 实现**：
    流式HTTP 直接从本模块 import，不再另立一份。但本仓还有第二份同名实现
    `公共契约/运行时/有界HTTP.py`（被编辑器/能力网关/浏览器宿主使用），两者
    **满载行为不同**，属已知的「同一件事两套实现」（违反哲学 1.3 结果唯一即收口）：

    - 满载行为：本类写 `429 + 网关响应信封 JSON` 再关连接；公共契约那份直接
      `shutdown_request`，**不回任何响应**（调用方只见连接断开，分不清限流与故障）。
    - 预算参数：本类为 `最大工作线程`（1..256，默认 64）；那份为 `最大线程数`（默认 32）。
    - 可观测：本类有 `活动工作线程数/拒绝请求数 + 连接诊断`；那份无计数、无诊断。

    收敛方案（本轮只在本域收口，`公共契约` 与域外调用方不碰；精确改法见同批回传）：
    1. 通用部分（信号量预算 + 线程回收 + 满载出口回调）下沉到
       `公共契约/运行时/有界HTTP.py`——它是下层，`运行核心` 反向依赖它合法；
    2. 满载响应体属**网关协议**，留在本域，用「满载响应回调」注入给下层；
       `公共契约` 不得认识网关响应信封（否则下层反向依赖运行核心，破分层铁律）；
    3. 本类改为继承下层实现并注入 `_写限流响应`，构造签名与计数保留（调用方零改动）；
    4. 域外调用方（`开发工具/轻代码前端编辑器/启动编辑器.py`、`开发工具/能力网关/能力网关.py`、
       `支持库/前端/浏览器宿主/实现/浏览器宿主.py`）在下层补默认满载出口后
       自动获得统一行为，不需要改调用点。
    """

    daemon_threads = True
    block_on_close = True

    def __init__(self, 地址, 处理器类, *, 最大工作线程: int = 64) -> None:
        if (isinstance(最大工作线程, bool) or not isinstance(最大工作线程, int)
                or not 1 <= 最大工作线程 <= 256):
            raise ValueError("最大工作线程必须是 1 到 256 之间的整数")
        self.最大工作线程 = 最大工作线程
        self.request_queue_size = min(128, 最大工作线程)
        self._工作线程信号量 = threading.BoundedSemaphore(最大工作线程)
        self._计数锁 = threading.Lock()
        self.活动工作线程数 = 0
        self.拒绝请求数 = 0
        self._连接诊断: list[dict[str, Any]] = []
        super().__init__(地址, 处理器类)

    def process_request(self, request, client_address) -> None:
        if not self._工作线程信号量.acquire(blocking=False):
            with self._计数锁:
                self.拒绝请求数 += 1
            self._写限流响应(request)
            self.shutdown_request(request)
            return
        with self._计数锁:
            self.活动工作线程数 += 1
        try:
            super().process_request(request, client_address)
        except BaseException:
            self._归还线程预算()
            raise

    def process_request_thread(self, request, client_address) -> None:
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._归还线程预算()

    def _归还线程预算(self) -> None:
        with self._计数锁:
            self.活动工作线程数 = max(0, self.活动工作线程数 - 1)
        self._工作线程信号量.release()

    #: 429 响应带 HTTP 标准头 `Retry-After` 的秒数（RFC 9110 §10.2.3）。
    #: 真源＝`安全/限流器.py::建议重试秒`；本文件受分层约束（见文件头：不导入同目录
    #: 任何模块）不能 import，故就地复制 —— **值必须与真源一致**。**不要**改成 0
    #: （等于让客户端立刻重试 ⇒ 没限流），也不要删掉该头（调用方只能盲目重试）。
    限流建议重试秒 = 1

    def _写限流响应(self, request) -> None:
        正文 = json.dumps({
            "请求id": "", "操作": "HTTP边界", "成功": 假, "值": None,
            "错误码": "限流", "错误说明": "网关工作线程已达上限",
            "句柄": None, "耗时毫秒": 0.0,
        }, ensure_ascii=False).encode("utf-8")
        响应头 = (
            "HTTP/1.1 429 Too Many Requests\r\n"
            "Content-Type: application/json; charset=utf-8\r\n"
            f"Content-Length: {len(正文)}\r\n"
            # HTTP 标准头（RFC 9110 §10.2.3）：429 必须告诉客户端「多久后可重试」，
            # 否则调用方只能盲目立刻重试 ⇒ 限流形同虚设。
            f"Retry-After: {self.限流建议重试秒}\r\n"
            "Cache-Control: no-store\r\n"
            "Connection: close\r\n\r\n"
        ).encode("ascii")
        try:
            request.sendall(响应头 + 正文)
        except (BrokenPipeError, ConnectionResetError, OSError) as 错误:
            self.记录连接诊断("限流响应断开", 错误)

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

    def handle_error(self, request, client_address) -> None:
        """连接断开和处理器异常只留有限分类，不向标准错误打印堆栈。"""
        错误 = sys.exc_info()[1]
        self.记录连接诊断("请求处理异常", 错误 or "未知异常")

