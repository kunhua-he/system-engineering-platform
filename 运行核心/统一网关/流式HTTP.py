"""真实 HTTP 事件流：逐事件写出，并在取消、超时或断开时释放资源。"""

from __future__ import annotations

import inspect
import json
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable, Iterator

from 运行核心.统一网关.流式语义 import 流式管理器


class HTTP流式通道:
    """一次可被 HTTP 消费端实时读取的事件通道。"""

    def __init__(self, *, 请求id: str = "", 任务id: str = "",
                 能力id: str = "", 最大事件数: int = 1000,
                 最大持续秒: float = 30.0,
                 结束回调: Callable[[str], None] | None = None) -> None:
        self.请求id = 请求id or uuid.uuid4().hex[:16]
        self.任务id = 任务id or uuid.uuid4().hex[:16]
        self.能力id = 能力id
        self.最大事件数 = 最大事件数
        self.最大持续秒 = 最大持续秒
        self.序号 = 0
        self.事件队列: list[dict[str, Any]] = []
        self.条件 = threading.Condition(threading.RLock())
        self.结束 = False
        self.断开 = False
        self.开始时间 = time.monotonic()
        self.停止事件 = threading.Event()
        self.结束回调 = 结束回调
        self._回调已执行 = False

    def _追加事件(self, 事件类型: str, 数据: Any = None) -> dict[str, Any]:
        self.序号 += 1
        事件 = {
            "请求id": self.请求id,
            "任务id": self.任务id,
            "事件序号": self.序号,
            "事件类型": 事件类型,
            "数据": 数据,
            "时间": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }
        self.事件队列.append(事件)
        self.条件.notify_all()
        return 事件

    def 追加事件(self, 事件类型: str, 数据: Any = None) -> dict[str, Any]:
        """追加非终止事件；终止后不再接受新事件。"""
        with self.条件:
            if self.结束:
                return {}
            return self._追加事件(事件类型, 数据)

    def _终止(self, 事件类型: str, 数据: Any = None, 原因: str = "") -> dict[str, Any]:
        with self.条件:
            if self.结束:
                return {}
            事件 = self._追加事件(事件类型, 数据)
            self.结束 = True
            self.停止事件.set()
            self.条件.notify_all()
        self._执行结束回调(原因 or 事件类型)
        return 事件

    def _执行结束回调(self, 原因: str) -> None:
        with self.条件:
            if self._回调已执行:
                return
            self._回调已执行 = True
        if self.结束回调 is not None:
            try:
                self.结束回调(原因)
            except Exception:
                pass

    def 完成(self, 数据: Any = None) -> dict[str, Any]:
        return self._终止("完成事件", 数据, "完成")

    def 失败(self, 错误码: str, 错误说明: str) -> dict[str, Any]:
        return self._终止(
            "失败事件",
            {"错误码": 错误码, "错误说明": 错误说明},
            错误码,
        )

    def 取消(self) -> dict[str, Any]:
        return self._终止("取消事件", None, "取消")

    def 超时(self) -> dict[str, Any]:
        return self._终止(
            "超时事件",
            {"错误码": "超时", "错误说明": f"流式调用超过 {self.最大持续秒} 秒"},
            "超时",
        )

    def 断开清理(self) -> None:
        """客户端断开后停止生产端，并清除尚未消费的事件引用。"""
        with self.条件:
            if self.断开:
                return
            self.断开 = True
            self.结束 = True
            self.停止事件.set()
            self.事件队列.clear()
            self.条件.notify_all()
        self._执行结束回调("客户端断开")

    def 格式事件行(self, 事件: dict[str, Any]) -> bytes:
        """按 SSE 格式输出一条完整事件，调用方应立即 flush。"""
        事件名 = str(事件.get("事件类型", "事件"))
        数据 = json.dumps(事件, ensure_ascii=False, separators=(",", ":"))
        return f"event: {事件名}\ndata: {数据}\n\n".encode("utf-8")

    def 首次事件(self) -> dict[str, Any]:
        return self.追加事件("首个事件", {"能力id": self.能力id})

    def 迭代事件(self, 等待秒: float = 0.25) -> Iterator[dict[str, Any]]:
        """实时等待后续事件，不等生产端完成后再整体返回。"""
        已读数量 = 0
        while True:
            with self.条件:
                while len(self.事件队列) <= 已读数量 and not self.结束:
                    self.条件.wait(timeout=max(0.01, 等待秒))
                新事件 = list(self.事件队列[已读数量:])
                已读数量 += len(新事件)
                已结束 = self.结束
            for 事件 in 新事件:
                yield 事件
            if 已结束 and not 新事件:
                return


class HTTP流式管理器:
    """创建流式生产线程，并管理取消、超时和断开清理。"""

    def __init__(self, 内部管理器: 流式管理器 | None = None) -> None:
        self.内部管理器 = 内部管理器 or 流式管理器()
        self.通道表: dict[str, HTTP流式通道] = {}
        self.锁 = threading.RLock()

    def 开始(self, *, 能力id: str, 事件生成函数: Callable,
             请求id: str = "", 任务id: str = "",
             最大事件数: int = 1000, 最大持续秒: float = 30.0,
             结束回调: Callable[[str], None] | None = None) -> HTTP流式通道:
        通道 = HTTP流式通道(
            请求id=请求id, 任务id=任务id, 能力id=能力id,
            最大事件数=最大事件数, 最大持续秒=最大持续秒,
            结束回调=结束回调,
        )
        with self.锁:
            self.通道表[通道.请求id] = 通道
        通道.首次事件()

        def 执行() -> None:
            生成器 = None
            try:
                参数数量 = len(inspect.signature(事件生成函数).parameters)
                生成器 = 事件生成函数(通道.停止事件) if 参数数量 else 事件生成函数()
                for 数据 in 生成器:
                    if 通道.停止事件.is_set():
                        return
                    if 通道.序号 >= 最大事件数:
                        通道.失败("事件过多", f"事件数超过上限 {最大事件数}")
                        return
                    通道.追加事件("中间事件", 数据)
                if not 通道.结束 and not 通道.断开:
                    通道.完成()
            except Exception:
                if not 通道.结束:
                    通道.失败("提供者崩溃", "流式提供者执行失败")
            finally:
                if 生成器 is not None and hasattr(生成器, "close"):
                    try:
                        生成器.close()
                    except Exception:
                        pass

        线程 = threading.Thread(target=执行, name=f"流式-{通道.请求id}", daemon=True)
        线程.start()

        def 超时检查() -> None:
            if not 通道.停止事件.wait(max(0.01, 最大持续秒)):
                通道.超时()

        threading.Thread(target=超时检查, name=f"流式超时-{通道.请求id}", daemon=True).start()
        return 通道

    def 查询(self, 请求id: str) -> HTTP流式通道 | None:
        with self.锁:
            return self.通道表.get(请求id)

    def 取消(self, 请求id: str) -> bool:
        通道 = self.查询(请求id)
        if 通道 is None:
            return False
        with 通道.条件:
            if 通道.结束:
                return False
        return bool(通道.取消())

    def 断开(self, 请求id: str) -> None:
        通道 = self.查询(请求id)
        if 通道 is not None:
            通道.断开清理()
            with self.锁:
                self.通道表.pop(请求id, None)

    def 清理(self, 请求id: str) -> None:
        with self.锁:
            self.通道表.pop(请求id, None)


class 流式HTTP服务器:
    """标准库本地 SSE 服务，能力生产器由调用方注册。"""

    def __init__(self, *, 地址: str = "127.0.0.1", 端口: int = 0,
                 管理器: HTTP流式管理器 | None = None) -> None:
        self.地址 = 地址
        self.端口 = 端口
        self.管理器 = 管理器 or HTTP流式管理器()
        self.能力表: dict[str, Callable] = {}
        self.服务器: ThreadingHTTPServer | None = None
        self.线程: threading.Thread | None = None

    def 注册能力(self, 能力id: str, 事件生成函数: Callable) -> None:
        self.能力表[能力id] = 事件生成函数

    def 启动(self) -> tuple[bool, str]:
        能力表 = self.能力表
        管理器 = self.管理器

        class 处理器(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, 格式: str, *参数: Any) -> None:
                return

            def _读取(self) -> dict[str, Any]:
                try:
                    长度 = int(self.headers.get("Content-Length", "0"))
                    return json.loads(self.rfile.read(长度).decode("utf-8")) if 长度 else {}
                except (ValueError, json.JSONDecodeError, UnicodeDecodeError):
                    return {}

            def _写JSON(self, 状态码: int, 数据: dict[str, Any]) -> None:
                正文 = json.dumps(数据, ensure_ascii=False).encode("utf-8")
                self.send_response(状态码)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(正文)))
                self.end_headers()
                self.wfile.write(正文)

            def do_POST(self) -> None:
                from urllib.parse import unquote
                路径 = unquote(self.path)
                数据 = self._读取()
                if 路径 == "/网关/流式/取消":
                    请求id = str(数据.get("请求id", ""))
                    self._写JSON(200, {"成功": 管理器.取消(请求id), "请求id": 请求id})
                    return
                if 路径 != "/网关/流式":
                    self._写JSON(404, {"成功": False, "错误码": "未知路径"})
                    return
                能力id = str(数据.get("能力id", ""))
                能力 = 能力表.get(能力id)
                if 能力 is None:
                    self._写JSON(404, {"成功": False, "错误码": "能力不存在"})
                    return
                参数 = 数据.get("参数") if isinstance(数据.get("参数"), dict) else {}

                def 生产(停止事件: threading.Event):
                    参数数量 = len(inspect.signature(能力).parameters)
                    if 参数数量 >= 2:
                        return 能力(参数, 停止事件)
                    if 参数数量 == 1:
                        return 能力(参数)
                    return 能力()

                通道 = 管理器.开始(
                    能力id=能力id, 事件生成函数=生产,
                    请求id=str(数据.get("请求id", "")),
                    任务id=str(数据.get("任务id", "")),
                    最大事件数=int(数据.get("最大事件数", 1000)),
                    最大持续秒=float(数据.get("最大持续秒", 30.0)),
                )
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream; charset=utf-8")
                self.send_header("Cache-Control", "no-cache, no-transform")
                self.send_header("Connection", "close")
                self.send_header("X-Accel-Buffering", "no")
                self.end_headers()
                try:
                    for 事件 in 通道.迭代事件():
                        self.wfile.write(通道.格式事件行(事件))
                        self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError, OSError):
                    管理器.断开(通道.请求id)
                finally:
                    管理器.清理(通道.请求id)
                    self.close_connection = True

        try:
            self.服务器 = ThreadingHTTPServer((self.地址, self.端口), 处理器)
            self.服务器.daemon_threads = True
        except OSError as 错误:
            return False, f"流式服务启动失败: {错误}"
        self.端口 = int(self.服务器.server_address[1])
        self.线程 = threading.Thread(target=self.服务器.serve_forever, daemon=True)
        self.线程.start()
        return True, f"流式服务已启动 http://{self.地址}:{self.端口}"

    def 优雅停止(self) -> None:
        with self.管理器.锁:
            活动通道 = list(self.管理器.通道表.values())
        for 通道 in 活动通道:
            通道.取消()
        if self.服务器 is not None:
            self.服务器.shutdown()
            self.服务器.server_close()
            self.服务器 = None
        with self.管理器.锁:
            self.管理器.通道表.clear()
