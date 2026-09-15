"""标准库本地 HTTP 网关：安全边界校验后才进入网关核心。"""

from __future__ import annotations

import base64
import dataclasses
import json
import math
import os
import socket
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlsplit

from 平台控制面.能力反馈 import 能力反馈服务
from 运行核心.统一网关.安全边界 import 安全配置, 凭证管理器, 请求限制器, 提取访问凭证
from 运行核心.统一网关.网关核心 import 网关核心, 网关请求
from 公共契约.运行时.端口策略 import 校验应用监听端口


# 公开错误码 → HTTP 状态码：与 网关核心.公开错误说明表 逐码一一对应（批次0-3 + 批次1=34 码）。
# 缺键回落 500，所以「未登记码」的代价是**把可辨识的业务失败伪装成服务端故障**；
# 新增错误码时必须与 公开错误说明表 同一提交登记（含显式 内部错误: 500，
# 取代原先的隐式默认值，使未登记码一眼可辨）。
公开错误码状态映射 = {
    "参数不合法": 400, "请求结构错误": 400, "操作不存在": 400,
    "句柄无效": 400, "句柄失效": 500,   # 文档口径：类型不符→400 参数不合法；句柄不存在/已释放→句柄失效 500（保持既有验证场景期望）
    "权限不足": 403,
    "能力不存在": 404, "契约不存在": 404,
    "未知路径": 404, "路由不存在": 404, "反馈不存在": 404, "文件不存在": 404,
    "方法不允许": 405,
    "幂等键冲突": 409, "契约版本不兼容": 409, "版本冲突": 409,
    "状态版本冲突": 409, "调用已取消": 409,
    "句柄已过期": 410,
    "事件负载超限": 413,
    "限流": 429,
    "内部错误": 500, "资源释放失败": 500,
    "提供者崩溃": 502, "返回结果不符合契约": 502,
    "外部不可访问": 503, "提供者不可用": 503,
    "超时": 504,
    # 批次1 追加（与 网关核心.公开错误说明表 同一提交登记，34 码对 34 码）：
    # 定级按「谁的责任」——调用方给了危险命令/越界路径/超限参数 → 4xx；
    # 网关自身装配失败 → 500。
    "危险命令": 403,
    "超过解压上限": 400, "超过条目上限": 400,
    "超过压缩比上限": 400, "路径越界": 400,
    "热接入失败": 500,
}


class 有界线程HTTP服务器(ThreadingHTTPServer):
    """在线程创建前执行预算；满载时同步返回结构化 429。"""

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

    def _写限流响应(self, request) -> None:
        正文 = json.dumps({
            "请求id": "", "操作": "HTTP边界", "成功": False, "值": None,
            "错误码": "限流", "错误说明": "网关工作线程已达上限",
            "句柄": None, "耗时毫秒": 0.0,
        }, ensure_ascii=False).encode("utf-8")
        响应头 = (
            "HTTP/1.1 429 Too Many Requests\r\n"
            "Content-Type: application/json; charset=utf-8\r\n"
            f"Content-Length: {len(正文)}\r\n"
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
        self.并发上限 = int(self.配置.get("并发上限", 64))
        if not 1 <= self.并发上限 <= 256:
            raise ValueError("并发上限必须在 1 到 256 之间")
        # 客户端提交的项目/用户/会话/任务字段不能作为身份来源；只有
        # 经过受信服务端上下文注入的身份才可进入核心。兼容旧测试或
        # 专用内部夹具时，必须显式传入 False，不能依赖默认放行。
        self.禁止客户端身份 = bool(self.配置.get("禁止客户端身份", True))
        要求凭证 = bool(self.配置.get("要求凭证", True))
        self.安全配置 = 安全配置(
            凭证环境变量=str(self.配置.get("凭证环境变量", "系统库网关凭证")),
            请求大小上限=int(self.配置.get("请求大小上限", 1024 * 1024)),
            监听地址="127.0.0.1",
            允许路径表=set(self.配置.get("允许路径表", {"/健康", "/网关/调用", "/网关/流式", "/网关/流式/取消", "/网关/热接入", "/平台/能力反馈", "/能力/搜索", "/能力/目录"})),
            要求凭证=要求凭证,
            默认权限范围=set(self.配置.get("默认权限范围", {"查询", "调用", "任务"})),
            允许来源表=set(self.配置.get("允许来源表", set())),
            允许本地不验证SSL=bool(self.配置.get("允许本地不验证SSL", False)),
        )
        self.请求限制器 = 请求限制器(self.安全配置)
        self.凭证管理器 = 凭证管理器(self.安全配置.凭证环境变量)
        默认缓存根 = os.environ.get("系统底座_工程缓存根", "工程缓存")
        反馈状态目录 = Path(self.配置.get(
            "反馈状态目录", str(Path(默认缓存根) / "平台控制面")))
        self.反馈处理凭证管理器 = 凭证管理器(
            str(self.配置.get("反馈处理凭证环境变量", "系统平台反馈处理凭证")))
        self.反馈处理凭证管理器.加载()
        self.反馈服务 = 能力反馈服务(
            str(反馈状态目录),
            lambda 能力id: 能力id in getattr(
                getattr(getattr(网关核心实例, "后端核心", None), "注册表", None), "能力id列表", []),
        )
        # 流式通道与普通调用共用同一 HTTP 服务、线程预算和安全边界。
        # 延迟导入避免 流式HTTP.py 的类型引用与本模块形成导入环。
        from 运行核心.统一网关.流式HTTP import HTTP流式管理器
        self.流式管理器 = HTTP流式管理器(最大并发通道数=self.并发上限)
        self.服务器: 有界线程HTTP服务器 | None = None
        self.线程: threading.Thread | None = None

    @classmethod
    def 创建测试服务器(cls, *, 网关核心实例: 网关核心,
                 地址: str = "127.0.0.1", 端口: int = 0,
                 配置: dict[str, Any] | None = None) -> "本地网关服务器":
        """测试/演示专用显式构造器；生产构造器不得隐式免凭证。"""
        测试配置 = dict(配置 or {})
        测试配置["要求凭证"] = False
        return cls(网关核心实例=网关核心实例, 地址=地址, 端口=端口, 配置=测试配置)

    def 启动(self) -> tuple[bool, str]:
        地址通过, 地址消息 = self.请求限制器.校验监听地址(self.地址)
        if not 地址通过:
            return False, 地址消息
        try:
            校验应用监听端口(self.端口)
        except (TypeError, ValueError) as 错误:
            return False, str(错误)
        if self.安全配置.要求凭证:
            凭证通过, 凭证消息 = self.凭证管理器.加载()
            if not 凭证通过:
                return False, 凭证消息
        try:
            self.服务器 = 有界线程HTTP服务器(
                (self.地址, self.端口), self._构造处理类(),
                最大工作线程=self.并发上限,
            )
        except (OSError, ValueError):
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

        禁止客户端身份 = self.禁止客户端身份
        请求限制器实例 = self.请求限制器
        凭证管理器实例 = self.凭证管理器
        安全配置实例 = self.安全配置
        流式管理器实例 = self.流式管理器
        反馈服务实例 = self.反馈服务
        凭证处理凭证管理器实例 = self.反馈处理凭证管理器

        class 处理类(BaseHTTPRequestHandler):
            def setup(self) -> None:
                super().setup()
                self.connection.settimeout(请求超时秒)

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
                try:
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
                        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization, X-System-Credential, X-Request-ID")
                        if 安全配置实例.要求凭证:
                            self.send_header("Access-Control-Allow-Credentials", "true")
                    self.end_headers()
                    self.wfile.write(正文)
                except (BrokenPipeError, ConnectionResetError, OSError) as 错误:
                    if isinstance(self.server, 有界线程HTTP服务器):
                        self.server.记录连接诊断("响应写回断开", 错误)
                    self.close_connection = True
                    return

            def do_OPTIONS(self) -> None:
                """CORS 预检：浏览器跨域直连需要。"""
                来源 = self.headers.get("Origin", "")
                路径通过, _ = 请求限制器实例.校验路径(self._规范路径())
                if not 路径通过 or not 来源 or 来源 not in 安全配置实例.允许来源表:
                    self._拒绝(403, "权限不足", "跨域来源未授权")
                    return
                请求头表 = {
                    项.strip().lower()
                    for 项 in self.headers.get("Access-Control-Request-Headers", "").split(",")
                    if 项.strip()
                }
                if (安全配置实例.要求凭证
                        and not ({"authorization", "x-system-credential"} & 请求头表)):
                    self._拒绝(403, "权限不足", "预检未声明受支持的凭证请求头")
                    return
                try:
                    self.send_response(204)
                    self.send_header("Access-Control-Allow-Origin", 来源)
                    self.send_header("Vary", "Origin")
                    self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
                    self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization, X-System-Credential, X-Request-ID")
                    if 安全配置实例.要求凭证:
                        self.send_header("Access-Control-Allow-Credentials", "true")
                    self.send_header("Access-Control-Max-Age", "86400")
                    self.end_headers()
                except (BrokenPipeError, ConnectionResetError, OSError) as 错误:
                    if isinstance(self.server, 有界线程HTTP服务器):
                        self.server.记录连接诊断("预检写回断开", 错误)
                    self.close_connection = True

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

            def _反馈响应(self, 状态码: int, 成功: bool, 值: Any = None,
                         错误码: str = "", 错误说明: str = "", 操作: str = "能力反馈") -> None:
                self._写JSON(状态码, {
                    "请求id": str(self.headers.get("X-请求-id", ""))[:64] or uuid.uuid4().hex[:16],
                    "操作": 操作, "成功": 成功, "值": 值 if 成功 else None,
                    "错误码": 错误码 if not 成功 else "",
                    "错误说明": 错误说明 if not 成功 else "",
                    "句柄": None, "耗时毫秒": 0.0,
                })

            def _反馈路径段(self) -> list[str]:
                return [段 for 段 in self._规范路径().split("/") if 段]

            def _反馈处理认证(self) -> bool:
                凭证 = self.headers.get("X-Platform-Feedback-Credential", "")
                通过, _ = 凭证处理凭证管理器实例.校验(凭证)
                if not 通过:
                    self._拒绝(403, "权限不足", "反馈状态迁移需要平台处理凭证", "能力反馈状态")
                    return False
                return True

            def _处理反馈登记(self) -> None:
                读取成功, 请求数据, 错误说明 = self._读请求体()
                if not 读取成功:
                    self._反馈响应(400, False, 错误码="参数不合法", 错误说明=错误说明,
                                 操作="能力反馈登记")
                    return
                成功, 错误码, 值 = 反馈服务实例.登记(请求数据)
                状态码 = 200 if 成功 else {"能力不存在": 404, "幂等键冲突": 409}.get(错误码, 400)
                self._反馈响应(状态码, 成功, 值, 错误码, 错误码, "能力反馈登记")

            def _处理反馈查询(self) -> None:
                段 = self._反馈路径段()
                反馈id = unquote(段[2]) if len(段) == 3 else ""
                查询 = parse_qs(urlsplit(self.path).query, encoding="utf-8")
                状态 = (查询.get("状态") or [""])[0]
                能力id = (查询.get("能力id") or [""])[0]
                限制原值 = (查询.get("限制") or ["50"])[0]
                try:
                    限制 = int(限制原值)
                except (TypeError, ValueError):
                    self._反馈响应(400, False, 错误码="参数不合法", 错误说明="限制必须是整数",
                                 操作="能力反馈查询")
                    return
                成功, 错误码, 列表 = 反馈服务实例.查询(反馈id, 状态, 能力id, 限制)
                if not 成功:
                    self._反馈响应(400, False, 错误码="参数不合法", 错误说明=错误码,
                                 操作="能力反馈查询")
                    return
                if 反馈id and not 列表:
                    self._反馈响应(404, False, 错误码="反馈不存在", 错误说明="反馈记录不存在",
                                 操作="能力反馈查询")
                    return
                self._反馈响应(200, True, {"记录表": 列表, "数量": len(列表)}, 操作="能力反馈查询")

            def _处理反馈状态(self) -> None:
                if not self._反馈处理认证():
                    return
                段 = self._反馈路径段()
                反馈id = unquote(段[2])
                读取成功, 请求数据, 错误说明 = self._读请求体()
                if not 读取成功:
                    self._反馈响应(400, False, 错误码="参数不合法", 错误说明=错误说明,
                                 操作="能力反馈状态")
                    return
                成功, 错误码, 值 = 反馈服务实例.迁移状态(反馈id, 请求数据)
                状态码 = 200 if 成功 else {"反馈不存在": 404, "状态版本冲突": 409,
                                             "状态迁移不允许": 409}.get(错误码, 400)
                self._反馈响应(状态码, 成功, 值, 错误码, 错误码, "能力反馈状态")

            def _是反馈路由(self) -> bool:
                return self._规范路径() == "/平台/能力反馈" or self._规范路径().startswith("/平台/能力反馈/")

            def do_POST(self) -> None:
                路径 = self._规范路径()
                if not self._校验边界(路径):
                    return
                if self._是反馈路由():
                    段 = self._反馈路径段()
                    if len(段) == 2:
                        self._处理反馈登记()
                    elif len(段) == 4 and 段[3] == "状态":
                        self._处理反馈状态()
                    else:
                        self._拒绝(404, "路由不存在", "能力反馈路由不合法", "能力反馈")
                    return
                if 路径 == "/网关/流式":
                    self._处理流式网关请求()
                    return
                if 路径 == "/网关/流式/取消":
                    self._处理流式取消请求()
                    return
                if 路径 == "/网关/热接入":
                    self._处理热接入请求()
                    return
                if 路径 != "/网关/调用":
                    self._拒绝(405, "方法不允许", "该路径不支持普通请求")
                    return
                self._处理网关请求()

            def do_GET(self) -> None:
                路径 = self._规范路径()
                if not self._校验边界(路径):
                    return
                if self._是反馈路由():
                    段 = self._反馈路径段()
                    if len(段) == 2 or len(段) == 3:
                        self._处理反馈查询()
                    else:
                        self._拒绝(404, "路由不存在", "能力反馈路由不合法", "能力反馈")
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
                elif 路径 == "/能力/搜索":
                    查询参数 = parse_qs(urlsplit(self.path).query, encoding="utf-8")
                    关键词 = (查询参数.get("关键词") or [""])[0]
                    限制文本 = (查询参数.get("限制") or ["50"])[0]
                    try:
                        限制 = max(1, min(int(限制文本), 200))
                    except ValueError:
                        限制 = 50
                    请求对象 = 网关请求(
                        操作="能力搜索", 参数={"关键词": 关键词, "限制": 限制},
                        权限范围=sorted(安全配置实例.默认权限范围),
                        来源地址=self.client_address[0], 请求id=str(self.headers.get("X-请求-id", ""))[:64],
                        超时秒=请求超时秒,
                    )
                    try:
                        响应 = 网关核心实例.处理(请求对象)
                    except Exception:
                        self._拒绝(500, "内部错误", "网关处理失败", "能力搜索")
                        return
                    self._写JSON(200 if 响应.成功 else 400, 响应.转字典())
                elif 路径 == "/能力/目录":
                    查询参数 = parse_qs(urlsplit(self.path).query, encoding="utf-8")
                    关键词 = (查询参数.get("关键词") or [""])[0]
                    偏移文本 = (查询参数.get("偏移") or ["0"])[0]
                    限制文本 = (查询参数.get("限制") or ["20"])[0]
                    try:
                        偏移 = max(0, int(偏移文本))
                    except ValueError:
                        偏移 = 0
                    try:
                        限制 = max(1, min(int(限制文本), 200))
                    except ValueError:
                        限制 = 20
                    请求对象 = 网关请求(
                        操作="能力目录", 参数={"关键词": 关键词, "偏移": 偏移, "限制": 限制},
                        权限范围=sorted(安全配置实例.默认权限范围),
                        来源地址=self.client_address[0], 请求id=str(self.headers.get("X-请求-id", ""))[:64],
                        超时秒=请求超时秒,
                    )
                    try:
                        响应 = 网关核心实例.处理(请求对象)
                    except Exception:
                        self._拒绝(500, "内部错误", "网关处理失败", "能力目录")
                        return
                    self._写JSON(200 if 响应.成功 else 400, 响应.转字典())
                elif 路径.startswith("/能力/契约/"):
                    能力id = unquote(urlsplit(self.path).path)[len("/能力/契约/"):]
                    请求对象 = 网关请求(
                        操作="能力详情", 参数={"能力id": 能力id},
                        权限范围=sorted(安全配置实例.默认权限范围),
                        来源地址=self.client_address[0], 请求id=str(self.headers.get("X-请求-id", ""))[:64],
                        超时秒=请求超时秒,
                    )
                    try:
                        响应 = 网关核心实例.处理(请求对象)
                    except Exception:
                        self._拒绝(500, "内部错误", "网关处理失败", "能力详情")
                        return
                    self._写JSON(200 if 响应.成功 else 404, 响应.转字典())
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

            def _处理流式取消请求(self) -> None:
                """按请求 id 取消同一 40007 服务中的流式通道。"""
                读取成功, 请求数据, 错误说明 = self._读请求体()
                if not 读取成功:
                    self._拒绝(400, "参数不合法", 错误说明, "流式取消")
                    return
                if 禁止客户端身份 and any(
                    str(请求数据.get(字段, ""))
                    for 字段 in ("项目id", "用户id", "会话id", "任务id")
                ):
                    self._拒绝(403, "权限不足", "项目/用户/会话/任务身份必须由网关凭证注入", "流式取消")
                    return
                # 兼容口径（哲学第 21 条）：未知字段忽略，不因上游多传字段而整条失败。
                请求id = 请求数据.get("请求id", "")
                if not isinstance(请求id, str) or not 请求id or len(请求id) > 64:
                    self._拒绝(400, "参数不合法", "取消请求必须提供不超过64字符的请求id", "流式取消")
                    return
                成功 = 流式管理器实例.取消(请求id)
                if not 成功:
                    self._拒绝(404, "句柄无效", "流式请求不存在或已经结束", "流式取消")
                    return
                网关核心实例.审计.记录(
                    操作="流式取消", 请求id=请求id, 成功=True,
                    来源地址=self.client_address[0],
                )
                self._写JSON(200, {
                    "请求id": 请求id, "操作": "流式取消", "成功": True,
                    "值": {"已取消": True}, "错误码": "", "错误说明": "",
                    "句柄": None, "耗时毫秒": 0.0,
                })

            def _处理流式网关请求(self) -> None:
                """在同一 40007 HTTP 服务内逐事件转发模型连接器 SSE。"""
                读取成功, 请求数据, 错误说明 = self._读请求体()
                if not 读取成功:
                    状态码 = 413 if "大小上限" in 错误说明 else 400
                    self._拒绝(状态码, "参数不合法", 错误说明, "流式生成对话")
                    return
                允许字段 = {"能力id", "参数", "句柄", "请求id", "最大事件数", "最大持续秒"}
                if 禁止客户端身份 and any(
                    str(请求数据.get(字段, ""))
                    for 字段 in ("项目id", "用户id", "会话id", "任务id")
                ):
                    self._拒绝(403, "权限不足", "项目/用户/会话/任务身份必须由网关凭证注入", "流式生成对话")
                    return
                # 冻结的流式字段清单（协议只增不删，只作说明，不再用于拒绝未知字段）：
                # 能力id / 参数 / 句柄 / 请求id / 最大事件数 / 最大持续秒
                # 兼容口径（哲学第 21 条）：未知字段忽略，只校验必填与类型。
                能力id = 请求数据.get("能力id", "")
                目标能力 = "大语言模型支持库.模型连接器.生成对话"
                if 能力id != 目标能力:
                    self._拒绝(404, "能力不存在", "流式入口只支持模型连接器生成对话", "流式生成对话")
                    return
                参数 = 请求数据.get("参数")
                if not isinstance(参数, dict):
                    self._拒绝(400, "参数不合法", "流式参数必须是对象", "流式生成对话")
                    return
                参数 = dict(参数)
                顶层句柄 = 请求数据.get("句柄")
                参数句柄 = 参数.get("句柄")
                if 顶层句柄 is not None and 参数句柄 is not None and 顶层句柄 != 参数句柄:
                    self._拒绝(400, "参数不合法", "顶层句柄与参数句柄不一致", "流式生成对话")
                    return
                句柄 = 顶层句柄 if 顶层句柄 is not None else 参数句柄
                if isinstance(句柄, bool) or not isinstance(句柄, int) or not 1 <= 句柄 <= 999999:
                    self._拒绝(400, "参数不合法", "句柄必须是 1 到 999999 的整数", "流式生成对话")
                    return
                消息列表 = 参数.get("消息列表")
                if not isinstance(消息列表, list) or not 消息列表:
                    self._拒绝(400, "参数不合法", "消息列表必须是非空列表", "流式生成对话")
                    return
                流式输出 = 参数.get("流式输出")
                if 流式输出 is not True:
                    self._拒绝(400, "参数不合法", "流式输出必须是逻辑型真值", "流式生成对话")
                    return
                请求id = str(请求数据.get("请求id", self.headers.get("X-请求-id", "")))[:64]
                if not 请求id:
                    请求id = uuid.uuid4().hex[:16]
                try:
                    最大事件数 = 请求数据.get("最大事件数", 1000)
                    最大持续秒 = 请求数据.get("最大持续秒", 请求超时秒)
                    def 事件生成函数(_停止事件):
                        # SSE 传输特例：JSON 结果契约装不下生成器，故直取模型连接器包级
                        # 中文入口导出的流式实现；实现目录未被穿透，不构成第二条跨包通道。
                        from 支持库.后端.大语言模型支持库.模型连接器 import 流式生成对话
                        return 流式生成对话(
                            句柄=句柄,
                            消息列表=消息列表,
                            系统提示词=参数.get("系统提示词"),
                            流式输出=True,
                            温度=参数.get("温度"),
                            最大令牌数=参数.get("最大令牌数"),
                            工具=参数.get("工具"),
                            响应格式=参数.get("响应格式"),
                            附加请求头=参数.get("附加请求头"),
                        )
                    通道 = 流式管理器实例.开始(
                        能力id=能力id,
                        事件生成函数=事件生成函数,
                        请求id=请求id,
                        最大事件数=最大事件数,
                        最大持续秒=最大持续秒,
                    )
                except RuntimeError as 错误:
                    self._拒绝(429, "限流", str(错误), "流式生成对话")
                    return
                except (TypeError, ValueError) as 错误:
                    状态码 = 409 if "请求id已存在" in str(错误) else 400
                    错误码 = "幂等键冲突" if 状态码 == 409 else "参数不合法"
                    self._拒绝(状态码, 错误码, str(错误), "流式生成对话")
                    return
                网关核心实例.审计.记录(
                    操作="流式生成对话", 能力id=能力id, 请求id=通道.请求id,
                    成功=True, 来源地址=self.client_address[0],
                )
                try:
                    self.send_response(200)
                    self.send_header("Content-Type", "text/event-stream; charset=utf-8")
                    self.send_header("Cache-Control", "no-cache, no-transform")
                    self.send_header("Connection", "close")
                    self.send_header("X-Accel-Buffering", "no")
                    self.end_headers()
                    for 事件 in 通道.迭代事件():
                        self.wfile.write(通道.格式事件行(事件))
                        self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError, OSError) as 错误:
                    if isinstance(self.server, 有界线程HTTP服务器):
                        self.server.记录连接诊断("流式写回断开", 错误)
                    流式管理器实例.断开(通道.请求id)
                finally:
                    流式管理器实例.清理(通道.请求id)
                    self.close_connection = True

            def _处理网关请求(self) -> None:
                读取成功, 请求数据, 错误说明 = self._读请求体()
                if not 读取成功:
                    状态码 = 413 if "大小上限" in 错误说明 else 400
                    self._拒绝(状态码, "参数不合法", 错误说明)
                    return
                # 顶层请求字段是冻结契约的一部分。**协议只增不删不改名**（哲学第 21 条）：
                # 新增字段一律先登记在这里；上游多传未登记字段不再拒绝（见下），
                # 旧名保留为别名永久可解析（如 `契约版本` 是 `请求版本` 的旧名）。
                允许顶层字段 = {
                    "操作", "能力id", "目标", "参数", "句柄", "获取句柄",
                    "契约版本", "请求版本", "请求id", "项目id", "用户id", "会话id",
                    "任务id", "提供者", "超时秒",
                }
                未知顶层字段 = sorted(set(请求数据) - 允许顶层字段)
                if 未知顶层字段:
                    # 兼容口径：未知字段**忽略**，不再 400——上游先升级、底座后升级时
                    # 不该整条调用失败（旧行为是「未知即拒」，属兼容性硬点，已废止）。
                    请求数据 = {键: 值 for 键, 值 in 请求数据.items()
                            if 键 in 允许顶层字段}
                文本字段 = (
                    "能力id", "目标", "契约版本", "请求版本", "请求id", "项目id", "用户id",
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
                SSL通过, SSL说明 = 请求限制器实例.校验SSL策略(参数)
                if not SSL通过:
                    self._拒绝(403, "权限不足", SSL说明, 操作)
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
                    请求版本=str(请求数据.get("请求版本") or 请求数据.get("契约版本") or ""),
                )
                try:
                    响应 = 网关核心实例.处理(请求对象)
                except Exception:
                    self._拒绝(500, "内部错误", "网关处理失败", 操作)
                    return
                状态码 = 200
                if not 响应.成功:
                    # 逐码映射见模块级 公开错误码状态映射（与 网关核心.公开错误说明表 一一对应）；
                    # 缺键回落 500，因此任何新错误码都必须先登记再抛。
                    状态码 = 公开错误码状态映射.get(响应.错误码, 500)
                self._写JSON(状态码, 响应.转字典())

            def _处理热接入请求(self) -> None:
                """热接入：扫描新增/变更支持库与模块，增量装配免重启投产。

                仅接受可选空请求体（未来可带 仅新增/仅变更 过滤），凭证由
                _校验边界 层强制；操作固定为 热接入，不可伪造其他操作。
                """
                读取成功, 请求数据, 错误说明 = self._读请求体()
                if not 读取成功:
                    self._拒绝(400, "参数不合法", 错误说明, "热接入")
                    return
                if 禁止客户端身份 and any(
                    str(请求数据.get(字段, ""))
                    for 字段 in ("项目id", "用户id", "会话id", "任务id")
                ):
                    self._拒绝(403, "权限不足", "项目/用户/会话/任务身份必须由网关凭证注入", "热接入")
                    return
                请求对象 = 网关请求(
                    操作="热接入", 参数={},
                    权限范围=sorted(安全配置实例.默认权限范围),
                    来源地址=self.client_address[0],
                    请求id=str(self.headers.get("X-请求-id", ""))[:64],
                    超时秒=请求超时秒,
                )
                try:
                    响应 = 网关核心实例.处理(请求对象)
                except Exception:
                    self._拒绝(500, "内部错误", "网关处理失败", "热接入")
                    return
                self._写JSON(200 if 响应.成功 else 400, 响应.转字典())

        return 处理类

    def 连接诊断快照(self) -> list[dict[str, Any]]:
        服务器 = self.服务器
        return 服务器.连接诊断快照() if 服务器 is not None else []


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
