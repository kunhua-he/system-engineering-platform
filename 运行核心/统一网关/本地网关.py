"""标准库本地 HTTP 网关：安全边界校验后才进入网关核心。"""

from __future__ import annotations

import base64
import dataclasses
import json
import math
import os
import socket
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import unquote, urlsplit

from 运行核心.统一网关.安全边界 import 安全配置, 凭证管理器, 请求限制器, 提取访问凭证
from 运行核心.统一网关.网关核心 import 网关核心, 网关请求
from 公共契约.运行时.端口策略 import 校验应用监听端口


class 本地网关服务器:
    """配置驱动的本机网关；默认不允许绑定非回环地址。"""

    def __init__(self, *, 网关核心实例: 网关核心, 地址: str = "127.0.0.1",
                 端口: int = 0, 配置: dict[str, Any] | None = None) -> None:
        self.网关核心实例 = 网关核心实例
        self.配置 = dict(配置 or {})
        self.地址 = str(self.配置.get("网关地址", 地址))
        self.端口 = int(self.配置.get("网关端口", 端口))
        self.请求超时秒 = float(self.配置.get("请求超时秒", 10))
        self.请求体读取超时秒 = min(10.0, max(1.0, float(self.配置.get("请求体读取超时秒", 10))))
        self.并发上限 = max(1, int(self.配置.get("并发上限", 64)))
        # 客户端提交的项目/用户/会话/任务字段不能作为身份来源；只有
        # 经过受信服务端上下文注入的身份才可进入核心。兼容旧测试或
        # 专用内部夹具时，必须显式传入 False，不能依赖默认放行。
        self.禁止客户端身份 = bool(self.配置.get("禁止客户端身份", True))
        要求凭证 = bool(self.配置.get("要求凭证", bool(self.配置.get("凭证环境变量"))))
        self.安全配置 = 安全配置(
            凭证环境变量=str(self.配置.get("凭证环境变量", "系统库网关凭证")),
            请求大小上限=int(self.配置.get("请求大小上限", 1024 * 1024)),
            监听地址="127.0.0.1",
            允许路径表=set(self.配置.get("允许路径表", {"/健康", "/网关/调用", "/网关/流式"})),
            要求凭证=要求凭证,
            默认权限范围=set(self.配置.get("默认权限范围", {"查询", "调用", "任务"})),
            允许来源表=set(self.配置.get("允许来源表", set())),
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
            校验应用监听端口(self.端口)
        except (TypeError, ValueError) as 错误:
            return False, str(错误)
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
        请求体读取超时秒 = self.请求体读取超时秒
        并发信号量 = threading.BoundedSemaphore(self.并发上限)
        禁止客户端身份 = self.禁止客户端身份
        请求限制器实例 = self.请求限制器
        凭证管理器实例 = self.凭证管理器
        安全配置实例 = self.安全配置

        class 处理类(BaseHTTPRequestHandler):
            def setup(self) -> None:
                super().setup()
                self.connection.settimeout(请求超时秒)
                self._占用并发 = 并发信号量.acquire(blocking=False)

            def finish(self) -> None:
                try:
                    super().finish()
                finally:
                    if getattr(self, "_占用并发", False):
                        self._占用并发 = False
                        并发信号量.release()

            def log_message(self, 格式: str, *参数: Any) -> None:
                return

            def _写JSON(self, 状态码: int, 数据: dict[str, Any]) -> None:
                def _JSON默认值(值: Any):
                    # JSON 没有 bytes 类型；统一以可逆、带类型标记的 base64
                    # 对象传输，客户端负责还原为 bytes，禁止 str(bytes) 泄漏。
                    if isinstance(值, (bytes, bytearray, memoryview)):
                        return {
                            "类型": "字节集型",
                            "base64": base64.b64encode(bytes(值)).decode("ascii"),
                        }
                    # dataclass（如 通用文档）经 asdict 展开为 JSON 对象，否则
                    # HTTP 黑盒调用无法传输支持库返回的结构化对象。
                    if dataclasses.is_dataclass(值) and not isinstance(值, type):
                        return dataclasses.asdict(值)
                    # Path 统一转字符串（如 创建唯一运行目录 返回 Path）。
                    if isinstance(值, os.PathLike):
                        return str(值)
                    raise TypeError(f"响应值包含不可序列化类型: {type(值).__name__}")
                try:
                    正文 = json.dumps(
                        数据, ensure_ascii=False, allow_nan=False, default=_JSON默认值,
                    ).encode("utf-8")
                except (TypeError, ValueError):
                    # 结果契约无法编码时仍返回统一 JSON 错误，不能让 HTTP
                    # 线程异常断开并把内部堆栈暴露给客户端。
                    状态码 = 500
                    正文 = json.dumps({
                        "成功": False, "值": None, "错误码": "返回结果不符合契约",
                        "错误说明": "网关响应包含不可传输的数据类型",
                    }, ensure_ascii=False).encode("utf-8")
                self.send_response(状态码)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(正文)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                来源 = self.headers.get("Origin", "")
                if 来源 and 来源 in 安全配置实例.允许来源表:
                    self.send_header("Access-Control-Allow-Origin", 来源)
                    self.send_header("Vary", "Origin")
                    self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
                    self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization, X-系统凭证, X-请求-id")
                self.end_headers()
                try:
                    self.wfile.write(正文)
                except (BrokenPipeError, ConnectionResetError):
                    return

            def do_OPTIONS(self) -> None:
                """CORS 预检：浏览器跨域直连需要。"""
                来源 = self.headers.get("Origin", "")
                if not 来源 or 来源 not in 安全配置实例.允许来源表:
                    self._拒绝(403, "权限不足", "跨域来源未授权")
                    return
                self.send_response(204)
                self.send_header("Access-Control-Allow-Origin", 来源)
                self.send_header("Vary", "Origin")
                self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
                self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization, X-系统凭证, X-请求-id")
                self.send_header("Access-Control-Max-Age", "86400")
                self.end_headers()

            def _拒绝(self, 状态码: int, 错误码: str, 错误说明: str, 操作: str = "HTTP边界") -> None:
                # HTTP 头字段名必须是 ASCII；中文请求 id 仍放在 JSON 正文中。
                请求id = str(
                    self.headers.get("X-Request-ID", "")
                    or self.headers.get("X-请求-id", "")
                )
                try:
                    请求id = unquote(请求id)
                except Exception:
                    请求id = ""
                请求id = 请求id[:64] or uuid.uuid4().hex[:16]
                网关核心实例.审计.记录(
                    操作=操作, 请求id=请求id, 来源地址=self.client_address[0], 成功=False,
                    错误码=错误码, 失败原因=错误说明,
                    权限拒绝=错误码 == "权限不足",
                )
                # 边界拒绝也必须满足统一响应契约，避免连接器把原始错误
                # 二次归类成“返回结果不符合契约”而丢失真实故障原因。
                self._写JSON(状态码, {
                    "请求id": 请求id, "操作": 操作, "成功": False, "值": None,
                    "错误码": 错误码, "错误说明": 错误说明,
                    "句柄": None, "耗时毫秒": 0.0,
                })

            def _规范路径(self) -> str:
                return unquote(urlsplit(self.path).path)

            def _校验边界(self, 路径: str) -> bool:
                if not getattr(self, "_占用并发", False):
                    self._拒绝(429, "限流", "网关并发已达上限")
                    return False
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
                # 当前网关只实现有界 Content-Length 读取。若放行 chunked，
                # rfile.read(0) 会留下分块数据污染持久连接，绕过大小/超时边界。
                if self.headers.get("Transfer-Encoding", "").strip():
                    return False, {}, "暂不支持分块传输"
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
                    # 请求体读取不得继承能力执行的长超时，防止慢体连接
                    # 长时间占用网关线程和文件描述符。
                    self.connection.settimeout(请求体读取超时秒)
                    原始字节 = self.rfile.read(长度)
                    if len(原始字节) != 长度:
                        return False, {}, "请求正文长度不足"
                    原始 = 原始字节.decode("utf-8")
                    def 拒绝非有限数(_文本: str):
                        raise ValueError("JSON 不允许 NaN 或 Infinity")
                    数据 = json.loads(原始, parse_constant=拒绝非有限数)
                except (UnicodeDecodeError, json.JSONDecodeError, ValueError, TimeoutError, OSError):
                    return False, {}, "请求正文不是合法 JSON"
                finally:
                    self.connection.settimeout(请求超时秒)
                if not isinstance(数据, dict):
                    return False, {}, "请求正文必须是 JSON 对象"
                try:
                    数据 = self._解码JSON值(数据)
                except ValueError as 错误:
                    return False, {}, str(错误)
                return True, 数据, ""

            @staticmethod
            def _解码JSON值(值: Any) -> Any:
                """还原客户端传入的冻结字节集对象；非法编码一律拒绝。"""
                if isinstance(值, dict):
                    if 值.get("类型") == "字节集型":
                        编码 = 值.get("base64")
                        if not isinstance(编码, str):
                            raise ValueError("字节集型缺少合法 base64")
                        try:
                            return base64.b64decode(编码, validate=True)
                        except (ValueError, TypeError):
                            raise ValueError("字节集型 base64 不合法") from None
                    return {键: 处理类._解码JSON值(子值) for 键, 子值 in 值.items()}
                if isinstance(值, list):
                    return [处理类._解码JSON值(子值) for 子值 in 值]
                return 值

            def do_POST(self) -> None:
                路径 = self._规范路径()
                if not self._校验边界(路径):
                    return
                if 路径 != "/网关/调用":
                    self._拒绝(405, "方法不允许", "该路径不支持普通请求")
                    return
                self._处理网关请求()

            def do_GET(self) -> None:
                路径 = self._规范路径()
                if not self._校验边界(路径):
                    return
                if 路径 == "/健康":
                    # 健康必须经过同一网关核心，不能由 HTTP 层固定返回“健康”。
                    请求对象 = 网关请求(
                        操作="健康检查", 权限范围=sorted(安全配置实例.默认权限范围),
                        来源地址=self.client_address[0], 请求id=str(self.headers.get("X-请求-id", ""))[:64],
                        超时秒=请求超时秒,
                    )
                    try:
                        响应 = 网关核心实例.处理(请求对象)
                    except Exception:
                        self._拒绝(500, "内部错误", "网关处理失败", "健康检查")
                        return
                    self._写JSON(200 if 响应.成功 else 503, 响应.转字典())
                elif 路径 == "/网关/调用":
                    # 能力执行契约固定为 POST；拒绝 GET 旁路，避免有副作用的请求
                    # 被缓存/代理按安全方法处理。
                    self._拒绝(405, "方法不允许", "能力执行只支持 POST /网关/调用")
                else:
                    self._拒绝(405, "方法不允许", "该路径不支持普通请求")

            def _方法不允许(self) -> None:
                # BaseHTTPRequestHandler 默认会生成 HTML 501，破坏唯一网关
                # 的 JSON 错误契约；所有方法统一返回可解析的失败结果。
                self._拒绝(405, "方法不允许", "仅支持 GET /健康、POST /网关/调用")

            do_PUT = _方法不允许
            do_PATCH = _方法不允许
            do_DELETE = _方法不允许
            do_HEAD = _方法不允许

            def _处理网关请求(self) -> None:
                读取成功, 请求数据, 错误说明 = self._读请求体()
                if not 读取成功:
                    状态码 = 413 if "大小上限" in 错误说明 else 400
                    self._拒绝(状态码, "参数不合法", 错误说明)
                    return
                # 顶层请求字段是冻结契约的一部分。未知字段不能静默丢弃，
                # 否则客户端拼写错误会落入默认值并制造假绿。
                允许顶层字段 = {
                    "操作", "能力id", "目标", "参数", "句柄", "获取句柄",
                    "契约版本", "请求id", "项目id", "用户id", "会话id",
                    "任务id", "提供者", "超时秒",
                }
                未知顶层字段 = sorted(set(请求数据) - 允许顶层字段)
                if 未知顶层字段:
                    self._拒绝(
                        400, "参数不合法",
                        "请求包含未知字段: " + ", ".join(map(str, 未知顶层字段)),
                    )
                    return
                文本字段 = (
                    "能力id", "目标", "契约版本", "请求id", "项目id", "用户id",
                    "会话id", "任务id", "提供者",
                )
                for 字段 in 文本字段:
                    if 字段 in 请求数据 and not isinstance(请求数据[字段], str):
                        self._拒绝(400, "参数不合法", f"{字段}必须是文本型")
                        return
                if "请求id" in 请求数据 and len(请求数据["请求id"]) > 64:
                    self._拒绝(400, "参数不合法", "请求id长度不能超过64个字符")
                    return
                if 禁止客户端身份 and any(
                    str(请求数据.get(字段, ""))
                    for 字段 in ("项目id", "用户id", "会话id", "任务id")
                ):
                    self._拒绝(403, "权限不足", "项目/用户/会话/任务身份必须由网关凭证注入")
                    return
                操作 = 请求数据.get("操作") or (
                    "调用能力" if 请求数据.get("能力id") or 请求数据.get("目标") else ""
                )
                if not isinstance(操作, str) or not 操作:
                    self._拒绝(400, "参数不合法", "缺少操作；调用能力请求必须提供能力id")
                    return
                参数 = 请求数据.get("参数") if "参数" in 请求数据 else {}
                if not isinstance(参数, dict):
                    self._拒绝(400, "参数不合法", "参数必须是对象", 操作)
                    return
                try:
                    超时原值 = 请求数据.get("超时秒", 请求超时秒)
                    if isinstance(超时原值, bool) or not isinstance(超时原值, (int, float)):
                        raise TypeError("超时时间必须是数值型")
                    if not math.isfinite(float(超时原值)):
                        raise ValueError("超时时间必须是有限数值")
                    超时秒 = float(超时原值)
                except (TypeError, ValueError) as 错误:
                    self._拒绝(400, "参数不合法", str(错误), 操作)
                    return
                if 超时秒 <= 0 or 超时秒 > 请求超时秒:
                    self._拒绝(400, "参数不合法", "超时时间超出允许范围", 操作)
                    return
                句柄原值 = 请求数据.get("句柄")
                if 句柄原值 is not None and (
                    isinstance(句柄原值, bool) or not isinstance(句柄原值, int)
                    or not 1 <= 句柄原值 <= 999999
                ):
                    self._拒绝(400, "参数不合法", "句柄必须是 1 到 999999 的整数，只能使用网关返回值", 操作)
                    return
                获取句柄 = 请求数据.get("获取句柄", False)
                if not isinstance(获取句柄, bool):
                    self._拒绝(400, "参数不合法", "获取句柄必须是逻辑型", 操作)
                    return
                请求对象 = 网关请求(
                    操作=操作, 能力id=请求数据.get("能力id", ""),
                    目标=请求数据.get("目标", ""), 参数=参数,
                    句柄=句柄原值,
                    获取句柄=获取句柄,
                    项目id=请求数据.get("项目id", ""),
                    用户id=请求数据.get("用户id", ""),
                    会话id=请求数据.get("会话id", ""),
                    任务id=请求数据.get("任务id", ""),
                    提供者=请求数据.get("提供者", ""),
                    权限范围=sorted(安全配置实例.默认权限范围),
                    来源地址=self.client_address[0],
                    请求id=请求数据.get("请求id", self.headers.get("X-请求-id", "")),
                    超时秒=超时秒,
                )
                try:
                    响应 = 网关核心实例.处理(请求对象)
                except Exception:
                    self._拒绝(500, "内部错误", "网关处理失败", 操作)
                    return
                状态码 = 200
                if not 响应.成功:
                    状态码 = {
                        "权限不足": 403, "限流": 429, "能力不存在": 404,
                        "参数不合法": 400, "请求结构错误": 400,
                        "外部不可访问": 503, "提供者不可用": 503,
                        "超时": 504, "提供者崩溃": 502,
                        "句柄无效": 400, "句柄已过期": 410,
                        "资源释放失败": 500, "返回结果不符合契约": 502,
                        "幂等键冲突": 409, "契约不存在": 404,
                        "契约版本不兼容": 409, "版本冲突": 409,
                        "调用已取消": 409,
                    }.get(响应.错误码, 500)
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
