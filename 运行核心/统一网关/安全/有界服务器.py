"""网关域有界线程 HTTP 服务：满载写网关 429 信封（差异由参数注入下层）。

**为什么独立成文件（2026-09-19 拆分）**：本类被 `本地网关.py` 与同包两个混入类
（`网关边界面.py` / `流式路由面.py`）共同依赖。若留在 `本地网关.py`，混入类只能
反向 `from 运行核心.统一网关.本地网关 import …`，而 `本地网关.py` 又要模块级导入
混入类 → 双向依赖（实测 `ImportError: cannot import name '有界线程HTTP服务器'
from partially initialized module`）。故按「被双方依赖的符号下沉到更底层模块」的
标准做法搬到本文件；`本地网关.py` 与 `流式HTTP.py` 的导入路径**原样再导出**，
`测试中心/运行核心/测试_优雅停机.py` 等调用点零改动。

**2026-09-24 批Q · Q-i 收口（第二份实现 → 差异注入）**：收口前本文件与
`公共契约/运行时/有界HTTP.py` 是**同一件事的两套实现**（违反哲学 1.3）。两份的
差异是**行为**不是冗余，故**逐项参数化后只留下层一处实现**，本类只注入差异：

| 差异（收口前各一份） | 收口后的载体 |
|---|---|
| 满载出口：写 `429 + 网关响应信封 JSON` 再关连接（vs 只关连接、不回响应） | 注入 `满载响应回调=self._写限流响应` |
| 预算参数：`最大工作线程`（1..256，默认 64）（vs `最大线程数`，默认 32） | 本类构造签名校验后转发下层 |
| 队列上限：`min(128, 最大工作线程)`（vs 不动 `request_queue_size`） | 传 `请求队列上限` |
| 连接异常只留有限分类、不向标准错误打堆栈 | 本类覆写 `handle_error` |

信号量预算 / 线程回收 / 计数与连接诊断**已下沉下层唯一一处**；
`活动工作线程数` / `拒绝请求数` / `记录连接诊断` / `连接诊断快照` 读数语义不变。

**导入方向**：本文件不导入 `统一网关` 同目录任何模块（含 `本地网关.py`），
也不导入 `网关核心.py` / `流式HTTP.py`，是最底层。
"""

from __future__ import annotations

import json
import sys

from 公共契约.基础类型.逻辑类型 import 假
from 公共契约.运行时.有界HTTP import 有界线程HTTP服务器 as _下层有界线程HTTP服务器


class 有界线程HTTP服务器(_下层有界线程HTTP服务器):
    """网关域有界线程服务：满载时同步返回结构化 429。

    通用部分（信号量预算 + 线程回收 + 满载出口 + 计数与连接诊断）唯一实现在
    `公共契约/运行时/有界HTTP.py`；本类只注入网关协议差异（见文件头对照表）。
    """

    #: 429 响应带 HTTP 标准头 `Retry-After` 的秒数（RFC 9110 §10.2.3）。
    #: 真源＝`安全/限流器.py::建议重试秒`；本文件受分层约束（见文件头：不导入同目录
    #: 任何模块）不能 import，故就地复制 —— **值必须与真源一致**。**不要**改成 0
    #: （等于让客户端立刻重试 ⇒ 没限流），也不要删掉该头（调用方只能盲目重试）。
    限流建议重试秒 = 1

    def __init__(self, 地址, 处理器类, *, 最大工作线程: int = 64) -> None:
        if (isinstance(最大工作线程, bool) or not isinstance(最大工作线程, int)
                or not 1 <= 最大工作线程 <= 256):
            raise ValueError("最大工作线程必须是 1 到 256 之间的整数")
        self.最大工作线程 = 最大工作线程
        super().__init__(地址, 处理器类, 最大线程数=最大工作线程,
                         满载响应回调=self._写限流响应,
                         请求队列上限=min(128, 最大工作线程))

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

    def handle_error(self, request, client_address) -> None:
        """连接断开和处理器异常只留有限分类，不向标准错误打印堆栈。"""
        错误 = sys.exc_info()[1]
        self.记录连接诊断("请求处理异常", 错误 or "未知异常")
