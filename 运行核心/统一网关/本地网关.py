"""标准库本地 HTTP 网关：安全边界校验后才进入网关核心。"""

from __future__ import annotations

import json
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import unquote, urlsplit

from 运行核心.统一网关.安全边界 import 安全配置, 凭证管理器, 请求限制器, 提取访问凭证
from 运行核心.统一网关.网关核心 import 网关核心, 网关请求


class 本地网关服务器:
    """配置驱动的本机网关；默认不允许绑定非回环地址。"""

    def __init__(self, *, 网关核心实例: 网关核心, 地址: str = "127.0.0.1",
                 端口: int = 0, 配置: dict[str, Any] | None = None) -> None:
        self.网关核心实例 = 网关核心实例
        self.配置 = dict(配置 or {})
        self.地址 = str(self.配置.get("网关地址", 地址))
        self.端口 = int(self.配置.get("网关端口", 端口))
        self.请求超时秒 = float(self.配置.get("请求超时秒", 10))
        要求凭证 = bool(self.配置.get("要求凭证", bool(self.配置.get("凭证环境变量"))))
        self.安全配置 = 安全配置(
            凭证环境变量=str(self.配置.get("凭证环境变量", "系统库网关凭证")),
            请求大小上限=int(self.配置.get("请求大小上限", 1024 * 1024)),
            监听地址="127.0.0.1",
            允许路径表=set(self.配置.get("允许路径表", {"/健康", "/网关/请求", "/网关/流式"})),
            要求凭证=要求凭证,
            默认权限范围=set(self.配置.get("默认权限范围", {"查询", "调用", "任务"})),
        )
        self.请求限制器 = 请求限制器(self.安全配置)
        self.凭证管理器 = 凭证管理器(self.安全配置.凭证环境变量)
        self.服务器: ThreadingHTTPServer | None = None
        self.线程: threading.Thread | None = None

    def 启动(self) -> tuple[bool, str]:
        地址通过, 地址消息 = self.请求限制器.校验监听地址(self.地址)
        if not 地址通过:
            return False, 地址消息
        if self.安全配置.要求凭证:
            凭证通过, 凭证消息 = self.凭证管理器.加载()
            if not 凭证通过:
                return False, 凭证消息
        try:
            self.服务器 = ThreadingHTTPServer((self.地址, self.端口), self._构造处理类())
            self.服务器.daemon_threads = True
        except OSError:
            return False, "端口占用或监听地址不可用"
        self.端口 = int(self.服务器.server_address[1])
        self.线程 = threading.Thread(target=self.服务器.serve_forever, daemon=True)
        self.线程.start()
        return True, f"网关已启动 http://{self.地址}:{self.端口}"

    def 优雅停止(self) -> tuple[bool, str]:
        服务器 = self.服务器
        线程 = self.线程
        self.服务器 = None
        self.线程 = None
        if 服务器 is not None:
            服务器.shutdown()
            服务器.server_close()
        if 线程 is not None and 线程.is_alive():
            线程.join(timeout=max(1.0, self.请求超时秒))
        self.凭证管理器.清除()
        return True, "网关已优雅停止"

    def _构造处理类(self):
        网关核心实例 = self.网关核心实例
        请求超时秒 = self.请求超时秒
        请求限制器实例 = self.请求限制器
        凭证管理器实例 = self.凭证管理器
        安全配置实例 = self.安全配置

        class 处理类(BaseHTTPRequestHandler):
            def setup(self) -> None:
                super().setup()
                self.connection.settimeout(请求超时秒)

            def log_message(self, 格式: str, *参数: Any) -> None:
                return

            def _写JSON(self, 状态码: int, 数据: dict[str, Any]) -> None:
                正文 = json.dumps(数据, ensure_ascii=False).encode("utf-8")
                self.send_response(状态码)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(正文)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.end_headers()
                try:
                    self.wfile.write(正文)
                except (BrokenPipeError, ConnectionResetError):
                    return

            def _拒绝(self, 状态码: int, 错误码: str, 错误说明: str, 操作: str = "HTTP边界") -> None:
                网关核心实例.审计.记录(
                    操作=操作, 来源地址=self.client_address[0], 成功=False,
                    错误码=错误码, 失败原因=错误说明,
                    权限拒绝=错误码 == "权限不足",
                )
                self._写JSON(状态码, {"成功": False, "错误码": 错误码, "错误说明": 错误说明})

            def _规范路径(self) -> str:
                return unquote(urlsplit(self.path).path)

            def _校验边界(self, 路径: str) -> bool:
                路径通过, 路径消息 = 请求限制器实例.校验路径(路径)
                if not 路径通过:
                    self._拒绝(404, "未知路径", 路径消息)
                    return False
                if 路径 == "/健康" and not 安全配置实例.要求凭证:
                    return True
                if 安全配置实例.要求凭证:
                    凭证 = 提取访问凭证(self.headers)
                    凭证通过, _ = 凭证管理器实例.校验(凭证)
                    if not 凭证通过:
                        self._拒绝(401, "权限不足", "访问凭证缺失或无效")
                        return False
                return True

            def _读请求体(self) -> tuple[bool, dict[str, Any], str]:
                长度文本 = self.headers.get("Content-Length", "0")
                try:
                    长度 = int(长度文本)
                except (TypeError, ValueError):
                    return False, {}, "请求长度不合法"
                大小通过, 大小消息 = 请求限制器实例.校验大小(长度)
                if not 大小通过:
                    return False, {}, 大小消息
                类型通过, 类型消息 = 请求限制器实例.校验内容类型(
                    self.headers.get("Content-Type", ""), 长度,
                )
                if not 类型通过:
                    return False, {}, 类型消息
                if 长度 == 0:
                    return True, {}, ""
                try:
                    原始 = self.rfile.read(长度).decode("utf-8")
                    数据 = json.loads(原始)
                except (UnicodeDecodeError, json.JSONDecodeError):
                    return False, {}, "请求正文不是合法 JSON"
                if not isinstance(数据, dict):
                    return False, {}, "请求正文必须是 JSON 对象"
                return True, 数据, ""

            def do_POST(self) -> None:
                路径 = self._规范路径()
                if not self._校验边界(路径):
                    return
                if 路径 != "/网关/请求":
                    self._拒绝(405, "方法不允许", "该路径不支持普通请求")
                    return
                self._处理网关请求()

            def do_GET(self) -> None:
                路径 = self._规范路径()
                if not self._校验边界(路径):
                    return
                if 路径 == "/健康":
                    self._写JSON(200, {"成功": True, "值": {"状态": "健康", "时间": time.strftime("%H:%M:%S")}})
                elif 路径 == "/网关/请求":
                    self._处理网关请求()
                else:
                    self._拒绝(405, "方法不允许", "该路径不支持普通请求")

            def _处理网关请求(self) -> None:
                读取成功, 请求数据, 错误说明 = self._读请求体()
                if not 读取成功:
                    状态码 = 413 if "大小上限" in 错误说明 else 400
                    self._拒绝(状态码, "参数不合法", 错误说明)
                    return
                操作 = 请求数据.get("操作", "")
                if not isinstance(操作, str) or not 操作:
                    self._拒绝(400, "参数不合法", "缺少操作")
                    return
                参数 = 请求数据.get("参数") or {}
                if not isinstance(参数, dict):
                    self._拒绝(400, "参数不合法", "参数必须是对象", 操作)
                    return
                try:
                    超时秒 = float(请求数据.get("超时秒", 请求超时秒))
                except (TypeError, ValueError):
                    self._拒绝(400, "参数不合法", "超时时间不合法", 操作)
                    return
                if 超时秒 <= 0 or 超时秒 > 请求超时秒:
                    self._拒绝(400, "参数不合法", "超时时间超出允许范围", 操作)
                    return
                请求对象 = 网关请求(
                    操作=操作, 能力id=str(请求数据.get("能力id", "")), 参数=参数,
                    项目id=str(请求数据.get("项目id", "")),
                    用户id=str(请求数据.get("用户id", "")),
                    会话id=str(请求数据.get("会话id", "")),
                    任务id=str(请求数据.get("任务id", "")),
                    提供者=str(请求数据.get("提供者", "")),
                    权限范围=sorted(安全配置实例.默认权限范围),
                    来源地址=self.client_address[0],
                    请求id=str(self.headers.get("X-请求-id", ""))[:64],
                    超时秒=超时秒,
                )
                响应 = 网关核心实例.处理(请求对象)
                状态码 = 200
                if not 响应.成功:
                    状态码 = {"权限不足": 403, "限流": 429, "能力不存在": 404,
                           "参数不合法": 400, "外部不可访问": 503}.get(响应.错误码, 500)
                self._写JSON(状态码, 响应.转字典())

        return 处理类


def 检查端口可用(端口: int) -> bool:
    """只探测本机回环地址，并确保套接字总能关闭。"""
    套接字 = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        套接字.bind(("127.0.0.1", 端口))
        return True
    except OSError:
        return False
    finally:
        套接字.close()
