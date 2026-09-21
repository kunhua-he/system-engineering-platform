"""网关边界面：HTTP 请求/响应边界簇（`本地网关.本地网关服务器` 的混入类）。

**为什么独立成文件**：这 18 个成员（`_写JSON` / `_拒绝` / `_规范路径` / `_校验边界` /
`_读请求体` / `_解码JSON值` / `do_OPTIONS` / `do_GET` / `do_POST` / `_方法不允许` 与
四个方法别名）原先住在 `本地网关.py`（1222 行）的 HTTP 处理类内部，共 440 行，是
**HTTP 边界唯一关口**：路径与凭证校验、请求体有界读取、CORS、响应信封、JSON 编码
兜底、路由分发。对外「网关任何异常路径都回统一 JSON 信封」的不变量由本簇固定。

**搬动方式（可核对）**：本文件正文＝拆分前 `本地网关.py` 第 490–929 行**全体成员，
缩进减 8 空格、逐字节未改**（无改名、无改签名、无改注释）；唯一外部符号从
`本地网关` 模块级改为 `from 运行核心.统一网关.安全.有界服务器 import 有界线程HTTP服务器`
（与 `流式HTTP.py` 同一行、同一注释）。闭包变量（`self.网关服务器.网关核心实例` / `请求超时秒` /
`self.网关服务器.请求体读取超时秒` / `禁止客户端身份` / `请求限制器实例` / `凭证管理器实例` /
`安全配置实例` / `流式管理器实例`）改为**宿主依赖**：同名类注解 + 正文用 `self.` 前缀，
MRO 与唯一事实源见下。

**对外零变化（2026-09-19 拆分）**：`本地网关.本地网关服务器` 的公开成员一个不改；
本类成员名与签名逐字保留。宿主属性口径的唯一事实源在 `本地网关.py`
`本地网关服务器.__init__`（类注解即契约：宿主缺哪个属性当场 `AttributeError`，
不会静默退回各自拼路径）。

**导入方向**：本文件只被 `本地网关.py` 模块级导入，**不得反向导入** `本地网关.py`
（会成环）；其余导入与拆分前逐字相同。
"""

from __future__ import annotations

import base64
import dataclasses
import json
import os
import uuid
from typing import Any
from urllib.parse import parse_qs, unquote, urlsplit

from 运行核心.统一网关.安全.有界服务器 import 有界线程HTTP服务器
from 运行核心.统一网关.安全.安全边界 import 提取访问凭证, 异常说明
from 运行核心.统一网关.网关核心 import 网关请求
from 公共契约.运行时.JSON解码 import 解码冻结值
from 公共契约.基础类型.逻辑类型 import 真, 假


class 网关边界面:
    """HTTP 请求/响应边界与普通路由分发。

    宿主依赖（类注解即契约，真源＝`本地网关.本地网关服务器.__init__`）：
    ``网关核心实例`` / ``请求限制器`` / ``凭证管理器`` / ``安全配置`` /
    ``流式管理器`` / ``请求超时秒`` / ``请求体读取超时秒`` / ``禁止客户端身份``。
    反馈三路由见 `反馈路由面`，流式两路由见 `流式路由面`，普通调用/热接入见
    `本地网关.普通路由面`（它继承本类；因 `公开错误码状态映射` 必须留在 `本地网关.py`）。
    """

    # ---- 宿主契约（由 本地网关.本地网关服务器 提供，只声明不赋值） ----
    网关核心实例: Any

    # 宿主服务器实例引用（由 `本地网关._构造处理类` 显式挂上：`处理类.网关服务器 = self`）
    网关服务器: Any
    流式管理器: Any
    禁止客户端身份: bool
    请求超时秒: float
    请求体读取超时秒: float
    请求限制器: Any
    凭证管理器: Any
    安全配置: Any
    _反馈调用器: Any
    headers: Any
    server: Any
    wfile: Any
    client_address: Any
    # 客户端套接字（`BaseHTTPRequestHandler.setup` 里 `self.connection = self.request`）。
    # 断连监视要 select/偷看它，故与 headers/wfile 同处登记（2026-09-21）。
    connection: Any
    close_connection: bool

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
                "成功": 假, "值": None, "错误码": "返回结果不符合契约",
                "错误说明": "网关响应包含不可传输的数据类型",
            }, ensure_ascii=False).encode("utf-8")
        try:
            self.send_response(状态码)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(正文)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            # HTTP 标准头（RFC 9110 §10.2.3）：429 必须告诉客户端「多久后可重试」，
            # 否则调用方只能盲目立刻重试 ⇒ 限流形同虚设。**收口在此处**：所有 429 都
            # 经 `_拒绝` → `_写JSON` 出去，调用点不要各写各的。
            # 常量真源＝`安全/限流器.py::建议重试秒`（该模块是最底层，延迟导入无环）。
            if 状态码 == 429:
                from 运行核心.统一网关.安全.限流器 import 建议重试秒

                self.send_header("Retry-After", str(建议重试秒))
            来源 = self.headers.get("Origin", "")
            if 来源 and 来源 in self.网关服务器.安全配置.允许来源表:
                self.send_header("Access-Control-Allow-Origin", 来源)
                self.send_header("Vary", "Origin")
                self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
                self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization, X-System-Credential, X-Request-ID")
                if self.网关服务器.安全配置.要求凭证:
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
        路径通过, _ = self.网关服务器.请求限制器.校验路径(self._规范路径())
        if not 路径通过 or not 来源 or 来源 not in self.网关服务器.安全配置.允许来源表:
            self._拒绝(403, "权限不足", "跨域来源未授权")
            return
        请求头表 = {
            项.strip().lower()
            for 项 in self.headers.get("Access-Control-Request-Headers", "").split(",")
            if 项.strip()
        }
        if (self.网关服务器.安全配置.要求凭证
                and not ({"authorization", "x-system-credential"} & 请求头表)):
            self._拒绝(403, "权限不足", "预检未声明受支持的凭证请求头")
            return
        try:
            self.send_response(204)
            self.send_header("Access-Control-Allow-Origin", 来源)
            self.send_header("Vary", "Origin")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization, X-System-Credential, X-Request-ID")
            if self.网关服务器.安全配置.要求凭证:
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
        self.网关服务器.网关核心实例.审计.记录(
            操作=操作, 请求id=请求id, 来源地址=self.client_address[0], 成功=假,
            错误码=错误码, 失败原因=错误说明,
            权限拒绝=错误码 == "权限不足",
        )
        # 边界拒绝也必须满足统一响应契约，避免连接器把原始错误
        # 二次归类成“返回结果不符合契约”而丢失真实故障原因。
        self._写JSON(状态码, {
            "请求id": 请求id, "操作": 操作, "成功": 假, "值": None,
            "错误码": 错误码, "错误说明": 错误说明,
            "句柄": None, "耗时毫秒": 0.0,
        })

    def _规范路径(self) -> str:
        return unquote(urlsplit(self.path).path)

    def _校验边界(self, 路径: str) -> bool:
        路径通过, 路径消息 = self.网关服务器.请求限制器.校验路径(路径)
        if not 路径通过:
            self._拒绝(404, "未知路径", 路径消息)
            return 假
        # 探针端点（/健康、/存活、/就绪）在「不要求凭证」的部署里免凭证；
        # /健康 的原有口径一字未动（既有调用方与验证场景在用）。
        if 路径 in ("/健康", "/存活", "/就绪") and not self.网关服务器.安全配置.要求凭证:
            return 真
        if self.网关服务器.安全配置.要求凭证:
            凭证 = 提取访问凭证(self.headers)
            凭证通过, _ = self.网关服务器.凭证管理器.校验(凭证)
            if not 凭证通过:
                self._拒绝(401, "权限不足", "访问凭证缺失或无效")
                return 假
        return 真

    def _读请求体(self) -> tuple[bool, dict[str, Any], str]:
        # 当前网关只实现有界 Content-Length 读取。若放行 chunked，
        # rfile.read(0) 会留下分块数据污染持久连接，绕过大小/超时边界。
        if self.headers.get("Transfer-Encoding", "").strip():
            return 假, {}, "暂不支持分块传输"
        长度文本 = self.headers.get("Content-Length", "0")
        try:
            长度 = int(长度文本)
        except (TypeError, ValueError):
            return 假, {}, "请求长度不合法"
        大小通过, 大小消息 = self.网关服务器.请求限制器.校验大小(长度)
        if not 大小通过:
            return 假, {}, 大小消息
        类型通过, 类型消息 = self.网关服务器.请求限制器.校验内容类型(
            self.headers.get("Content-Type", ""), 长度,
        )
        if not 类型通过:
            return 假, {}, 类型消息
        if 长度 == 0:
            return 真, {}, ""
        try:
            # 请求体读取不得继承能力执行的长超时，防止慢体连接
            # 长时间占用网关线程和文件描述符。
            self.connection.settimeout(self.网关服务器.请求体读取超时秒)
            原始字节 = self.rfile.read(长度)
            if len(原始字节) != 长度:
                return 假, {}, "请求正文长度不足"
            原始 = 原始字节.decode("utf-8")
            def 拒绝非有限数(_文本: str):
                raise ValueError("JSON 不允许 NaN 或 Infinity")
            数据 = json.loads(原始, parse_constant=拒绝非有限数)
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError, TimeoutError, OSError):
            return 假, {}, "请求正文不是合法 JSON"
        finally:
            self.connection.settimeout(self.网关服务器.请求超时秒)
        if not isinstance(数据, dict):
            return 假, {}, "请求正文必须是 JSON 对象"
        try:
            数据 = self._解码JSON值(数据)
        except ValueError as 错误:
            return 假, {}, str(错误)
        return 真, 数据, ""

    @staticmethod
    def _解码JSON值(值: Any) -> Any:
        """还原客户端传入的冻结字节集对象。

        委托全平台唯一实现（严格模式）：非法编码一律拒绝，且带
        最大深度/节点预算，深嵌套不再以 RecursionError 逃逸。
        """
        return 解码冻结值(值, 模式="严格")

    def do_POST(self) -> None:
        路径 = self._规范路径()
        if not self._校验边界(路径):
            return
        if self._是反馈路由():
            段 = self._反馈路径段()
            if len(段) == 2:
                self._反馈路由安全执行(self._处理反馈登记, "能力反馈登记")
            elif len(段) == 4 and 段[3] == "状态":
                self._反馈路由安全执行(self._处理反馈状态, "能力反馈状态")
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
                self._反馈路由安全执行(self._处理反馈查询, "能力反馈查询")
            else:
                self._拒绝(404, "路由不存在", "能力反馈路由不合法", "能力反馈")
            return
        if 路径 == "/健康":
            # 健康必须经过同一网关核心，不能由 HTTP 层固定返回“健康”。
            请求对象 = 网关请求(
                操作="健康检查", 权限范围=sorted(self.网关服务器.安全配置.默认权限范围),
                来源地址=self.client_address[0], 请求id=str(self.headers.get("X-请求-id", ""))[:64],
                超时秒=self.网关服务器.请求超时秒,
            )
            try:
                响应 = self.网关服务器.网关核心实例.处理(请求对象)
            except Exception as 错误:  # noqa: BLE001 - 细节不得丢（#157）
                self._拒绝(500, "内部错误", 异常说明(错误, "网关处理失败"), "健康检查")
                return
            self._写JSON(200 if 响应.成功 else 503, 响应.转字典())
        elif 路径 == "/存活":
            # 存活＝进程还在（**不碰装配、不碰后端核心**）：给编排器一个
            # 「要不要重启进程」的判据，与「能不能接流量」（/就绪）分开。
            # 这里不经网关核心，故也不触发任何装配状态机副作用。
            self._写JSON(200, {
                "请求id": str(self.headers.get("X-请求-id", ""))[:64],
                "操作": "存活检查", "成功": 真, "值": {"存活": 真},
                "错误码": "", "错误说明": "", "句柄": None, "耗时毫秒": 0.0,
            })
        elif 路径 == "/就绪":
            # 就绪＝装配完成 + 关键依赖就绪；未就绪对流量返回 503。
            # 依赖判定复用唯一健康检查链路（不另造第二套判据）。
            if self.网关服务器.网关核心实例.后端核心 is None:
                self._拒绝(503, "提供者不可用",
                          "网关装配未完成：后端核心未接入", "就绪检查")
                return
            请求对象 = 网关请求(
                操作="健康检查", 权限范围=sorted(self.网关服务器.安全配置.默认权限范围),
                来源地址=self.client_address[0], 请求id=str(self.headers.get("X-请求-id", ""))[:64],
                超时秒=self.网关服务器.请求超时秒,
            )
            try:
                响应 = self.网关服务器.网关核心实例.处理(请求对象)
            except Exception as 错误:  # noqa: BLE001 - 需按类型分流（#157）
                # 缺陷 #157：原先无论什么异常一律 503「提供者不可用」——
                # 把「就绪判定自身的编程 bug」也说成「提供者不可用」，误导调用方去查环境。
                # 现在分流：可达性类异常（连接/超时/OS 级）→ 503；其余（编程 bug）→ 500。
                if isinstance(错误, (ConnectionError, TimeoutError, OSError)):
                    self._拒绝(503, "提供者不可用", 异常说明(错误, "网关就绪判定失败"), "就绪检查")
                else:
                    self._拒绝(500, "内部错误", 异常说明(错误, "网关就绪判定失败"), "就绪检查")
                return
            数据 = 响应.转字典()
            明细 = 数据.get("值")
            if isinstance(明细, dict):
                明细 = dict(明细)
                明细["就绪"] = bool(响应.成功)
            else:
                明细 = {"就绪": bool(响应.成功), "健康明细": 明细}
            数据["值"] = 明细
            self._写JSON(200 if 响应.成功 else 503, 数据)
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
                权限范围=sorted(self.网关服务器.安全配置.默认权限范围),
                来源地址=self.client_address[0], 请求id=str(self.headers.get("X-请求-id", ""))[:64],
                超时秒=self.网关服务器.请求超时秒,
            )
            try:
                响应 = self.网关服务器.网关核心实例.处理(请求对象)
            except Exception as 错误:  # noqa: BLE001 - 细节不得丢（#157）
                self._拒绝(500, "内部错误", 异常说明(错误, "网关处理失败"), "能力搜索")
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
                权限范围=sorted(self.网关服务器.安全配置.默认权限范围),
                来源地址=self.client_address[0], 请求id=str(self.headers.get("X-请求-id", ""))[:64],
                超时秒=self.网关服务器.请求超时秒,
            )
            try:
                响应 = self.网关服务器.网关核心实例.处理(请求对象)
            except Exception as 错误:  # noqa: BLE001 - 细节不得丢（#157）
                self._拒绝(500, "内部错误", 异常说明(错误, "网关处理失败"), "能力目录")
                return
            self._写JSON(200 if 响应.成功 else 400, 响应.转字典())
        elif 路径.startswith("/能力/契约/"):
            能力id = unquote(urlsplit(self.path).path)[len("/能力/契约/"):]
            请求对象 = 网关请求(
                操作="能力详情", 参数={"能力id": 能力id},
                权限范围=sorted(self.网关服务器.安全配置.默认权限范围),
                来源地址=self.client_address[0], 请求id=str(self.headers.get("X-请求-id", ""))[:64],
                超时秒=self.网关服务器.请求超时秒,
            )
            try:
                响应 = self.网关服务器.网关核心实例.处理(请求对象)
            except Exception as 错误:  # noqa: BLE001 - 细节不得丢（#157）
                self._拒绝(500, "内部错误", 异常说明(错误, "网关处理失败"), "能力详情")
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
        self._拒绝(405, "方法不允许", "仅支持 GET /健康、/存活、/就绪，POST /网关/调用")

    do_PUT = _方法不允许
    do_PATCH = _方法不允许
    do_DELETE = _方法不允许
    do_HEAD = _方法不允许
