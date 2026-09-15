"""真实 HTTP 事件流：逐事件写出，并在取消、超时或断开时释放资源。"""

from __future__ import annotations

import inspect
import ipaddress
import json
import logging
import select
import socket
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler
from typing import Any, Callable, Iterator

from 运行核心.统一网关.安全边界 import 安全配置, 凭证管理器, 提取访问凭证
from 运行核心.统一网关.本地网关 import 有界线程HTTP服务器
from 公共契约.运行时.端口策略 import 校验应用监听端口
from 公共契约.诊断.忽略记录 import 记录忽略

日志 = logging.getLogger("流式HTTP")


# 流式入口的请求与资源边界。超过边界必须在创建生产线程前拒绝。
请求体上限字节 = 1024 * 1024
最大事件数上限 = 10000
单事件payload上限字节 = 256 * 1024
累计payload上限字节 = 4 * 1024 * 1024
最大持续秒上限 = 3600.0
最小持续秒下限 = 0.01
最大并发通道上限 = 256


class HTTP流式通道:
    """一次可被 HTTP 消费端实时读取的事件通道。"""

    def __init__(self, *, 请求id: str = "", 任务id: str = "",
                 能力id: str = "", 最大事件数: int = 1000,
                 最大持续秒: float = 30.0,
                 单事件上限字节: int = 单事件payload上限字节,
                 累计事件上限字节: int = 累计payload上限字节,
                 结束回调: Callable[[str], None] | None = None) -> None:
        self.请求id = 请求id or uuid.uuid4().hex[:16]
        self.任务id = 任务id or uuid.uuid4().hex[:16]
        self.能力id = 能力id
        self.最大事件数 = 最大事件数
        self.最大持续秒 = 最大持续秒
        if not isinstance(单事件上限字节, int) or 单事件上限字节 < 1024:
            raise ValueError("单事件上限字节必须是不小于1024的整数")
        if not isinstance(累计事件上限字节, int) or 累计事件上限字节 < 单事件上限字节:
            raise ValueError("累计事件上限字节必须不小于单事件上限字节")
        self.单事件上限字节 = 单事件上限字节
        self.累计事件上限字节 = 累计事件上限字节
        self.累计事件字节数 = 0
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
        事件字节数 = len(self.格式事件行(事件))
        if 事件字节数 > self.单事件上限字节:
            raise ValueError(f"单事件负载超过上限 {self.单事件上限字节} 字节")
        if self.累计事件字节数 + 事件字节数 > self.累计事件上限字节:
            raise ValueError(f"累计事件负载超过上限 {self.累计事件上限字节} 字节")
        self.事件队列.append(事件)
        self.累计事件字节数 += 事件字节数
        self.条件.notify_all()
        return 事件

    def 追加事件(self, 事件类型: str, 数据: Any = None) -> dict[str, Any]:
        """追加非终止事件；负载超限时转成结构化失败终态。"""
        try:
            with self.条件:
                if self.结束:
                    return {}
                return self._追加事件(事件类型, 数据)
        except ValueError as 错误:
            return self._终止(
                "失败事件",
                {"错误码": "事件负载超限", "错误说明": str(错误)},
                "事件负载超限",
            )

    def _终止(self, 事件类型: str, 数据: Any = None, 原因: str = "") -> dict[str, Any]:
        with self.条件:
            if self.结束:
                return {}
            try:
                事件 = self._追加事件(事件类型, 数据)
            except ValueError:
                self.事件队列.clear()
                self.累计事件字节数 = 0
                事件 = self._追加事件(
                    "失败事件",
                    {"错误码": "事件负载超限", "错误说明": "终止事件负载超过流式预算"},
                )
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
            except Exception as 错误:  # 回调失败不得阻断通道终止，但要可观测
                try:
                    日志.error("流式通道结束回调异常 请求id=%s 原因=%s: %s",
                               self.请求id, 原因, 错误, exc_info=True)
                except Exception as 错误:  # 允许忽略，但留痕（哲学第 15 条）
                    记录忽略('流式HTTP._执行结束回调', 错误)

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
            self.累计事件字节数 = 0
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

    def __init__(self, 最大并发通道数: int = 64,
                 调用器: Any = None) -> None:
        self.调用器 = 调用器
        self.通道表: dict[str, HTTP流式通道] = {}
        self.锁 = threading.RLock()
        if (isinstance(最大并发通道数, bool)
                or not isinstance(最大并发通道数, int)
                or not 1 <= 最大并发通道数 <= 最大并发通道上限):
            raise ValueError(
                f"最大并发通道数必须是 1 到 {最大并发通道上限} 之间的整数"
            )
        self.最大并发通道数 = 最大并发通道数
        self._并发信号量 = threading.BoundedSemaphore(最大并发通道数)

    def 开始(self, *, 能力id: str, 事件生成函数: Callable,
             请求id: str = "", 任务id: str = "",
             最大事件数: int = 1000, 最大持续秒: float = 30.0,
             结束回调: Callable[[str], None] | None = None) -> HTTP流式通道:
        if not isinstance(最大事件数, int) or isinstance(最大事件数, bool):
            raise ValueError("最大事件数必须是整数")
        if not 1 <= 最大事件数 <= 最大事件数上限:
            raise ValueError(f"最大事件数必须在 1 到 {最大事件数上限} 之间")
        if isinstance(最大持续秒, bool) or not isinstance(最大持续秒, (int, float)):
            raise ValueError("最大持续秒必须是数值")
        if not (最小持续秒下限 <= float(最大持续秒) <= 最大持续秒上限):
            raise ValueError(f"最大持续秒必须在 {最小持续秒下限} 到 {最大持续秒上限} 之间")
        # 生产、超时检查和断开监视各自占用线程；通道数必须先受有界
        # 信号量保护，避免高并发请求把网关线程/文件描述符耗尽。
        if not self._并发信号量.acquire(blocking=False):
            raise RuntimeError("流式并发已达上限")
        通道 = HTTP流式通道(
            请求id=请求id, 任务id=任务id, 能力id=能力id,
            最大事件数=最大事件数, 最大持续秒=最大持续秒,
            结束回调=结束回调,
        )
        try:
            with self.锁:
                # 请求 id 是流式资源的唯一定位；覆盖旧通道会丢失其
                # 取消/清理引用，造成资源泄漏，故直接拒绝重复 id。
                if 通道.请求id in self.通道表:
                    raise ValueError("请求id已存在")
                self.通道表[通道.请求id] = 通道
        except Exception:
            self._并发信号量.release()
            raise
        原结束回调 = 结束回调

        def 终态清理(原因: str) -> None:
            try:
                if 原结束回调 is not None:
                    原结束回调(原因)
            finally:
                # 终态统一移除注册引用。消费端仍可持有返回的通道对象读取
                # 已排队事件；管理器不应因等待断开请求而累积完成态通道。
                with self.锁:
                    self.通道表.pop(通道.请求id, None)
                self._并发信号量.release()

        通道.结束回调 = 终态清理
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
                    if isinstance(数据, dict):
                        事件类型 = str(数据.get("类型", ""))
                        if 事件类型 == "完成":
                            通道.完成(数据)
                            return
                        if 事件类型 == "错误":
                            通道.失败(
                                str(数据.get("错误码") or "提供者错误"),
                                str(数据.get("错误说明") or "流式提供者返回错误"),
                            )
                            return
                        if 事件类型 == "增量":
                            通道.追加事件("增量事件", 数据)
                            continue
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
                    except Exception as 错误:  # 允许忽略，但留痕（哲学第 15 条）
                        记录忽略('流式HTTP.执行', 错误)

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
        """清理通道：走唯一结束收口（断开清理 + 终态回调），不能只 pop。

        直接 pop 会泄漏并发信号量并失去生产线程/超时线程的观察对象；
        必须设置停止事件、执行一次结束回调（内部 release 信号量并移除
        通道表），与 断开 保持同一收口路径。
        """
        通道 = self.查询(请求id)
        if 通道 is not None:
            通道.断开清理()
            with self.锁:
                self.通道表.pop(请求id, None)


class 流式HTTP服务器:
    """标准库本地 SSE 服务；创建/取消统一凭证、审计和请求边界。"""

    def __init__(self, *, 地址: str = "127.0.0.1", 端口: int = 0,
                 管理器: HTTP流式管理器 | None = None,
                 调用器: Any = None,
                 凭证环境变量: str = "系统库网关凭证",
                 要求凭证: bool = True,
                 允许来源表: set[str] | None = None,
                 并发上限: int = 64) -> None:
        self.地址 = 地址
        self.端口 = 端口
        self.管理器 = 管理器 or HTTP流式管理器(调用器=调用器)
        self.调用器 = 调用器
        self.服务器: 有界线程HTTP服务器 | None = None
        self.线程: threading.Thread | None = None
        if (isinstance(并发上限, bool) or not isinstance(并发上限, int)
                or not 1 <= 并发上限 <= 256):
            raise ValueError("并发上限必须是 1 到 256 之间的整数")
        self.并发上限 = 并发上限
        self.安全配置 = 安全配置(凭证环境变量=凭证环境变量,
                              要求凭证=bool(要求凭证),
                              允许来源表=set(允许来源表 or set()))
        self.凭证管理器 = 凭证管理器(凭证环境变量)
        self.审计记录表: list[dict[str, Any]] = []
        self.审计锁 = threading.Lock()

    @classmethod
    def 创建测试服务器(cls, *, 地址: str = "127.0.0.1", 端口: int = 0,
                 管理器: HTTP流式管理器 | None = None,
                 调用器: Any = None,
                 允许来源表: set[str] | None = None,
                 并发上限: int = 64) -> "流式HTTP服务器":
        """测试/演示显式免凭证构造器。"""
        return cls(
            地址=地址, 端口=端口, 管理器=管理器, 要求凭证=False,
            调用器=调用器,
            允许来源表=允许来源表, 并发上限=并发上限,
        )

    def 启动(self) -> tuple[bool, str]:
        管理器 = self.管理器
        服务器 = self

        try:
            校验应用监听端口(self.端口)
        except (TypeError, ValueError) as 错误:
            return False, str(错误)
        try:
            if not ipaddress.ip_address(str(self.地址)).is_loopback:
                return False, "流式服务仅允许回环监听地址"
        except ValueError:
            return False, "流式服务监听地址不合法"
        if self.安全配置.要求凭证:
            已加载, 加载说明 = self.凭证管理器.加载()
            if not 已加载:
                return False, f"流式服务启动拒绝：{加载说明}"
        if self.调用器 is None:
            try:
                from 公共契约.能力契约.调用器 import 获取能力调用器
                self.调用器 = 获取能力调用器()
            except Exception as 错误:
                return False, f"流式服务缺少统一能力调用器: {错误}"
        if not callable(getattr(self.调用器, "调用能力", None)):
            return False, "流式服务调用器不符合统一调用契约"
        调用器 = self.调用器

        class 处理器(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, 格式: str, *参数: Any) -> None:
                return

            def _读取(self) -> tuple[dict[str, Any] | None, str | None]:
                内容类型 = self.headers.get("Content-Type", "")
                if not 内容类型.lower().split(";", 1)[0].strip() == "application/json":
                    return None, "请求必须使用 application/json"
                if self.headers.get("Transfer-Encoding", "").strip():
                    return None, "暂不支持分块传输"
                try:
                    长度 = int(self.headers.get("Content-Length", "0"))
                    if 长度 < 0 or 长度 > 请求体上限字节:
                        return None, f"请求体超过上限 {请求体上限字节} 字节"
                    if not 长度:
                        return {}, None
                    原文 = self.rfile.read(长度).decode("utf-8")
                    def 拒绝非有限数(_文本: str):
                        raise ValueError("JSON 不允许 NaN 或 Infinity")
                    数据 = json.loads(原文, parse_constant=拒绝非有限数)
                    if not isinstance(数据, dict):
                        return None, "请求体必须是 JSON 对象"
                    return 数据, None
                except (ValueError, json.JSONDecodeError, UnicodeDecodeError, TimeoutError):
                    return None, "请求体 JSON 无效"

            def _读取并校验(self) -> dict[str, Any] | None:
                self.connection.settimeout(10.0)
                数据, 错误 = self._读取()
                if 错误:
                    self._写JSON(400, {"成功": False, "错误码": "参数不合法", "错误说明": 错误})
                    return None
                return 数据

            def _写JSON(self, 状态码: int, 数据: dict[str, Any]) -> None:
                try:
                    正文 = json.dumps(
                        数据, ensure_ascii=False, allow_nan=False,
                    ).encode("utf-8")
                except (TypeError, ValueError):
                    状态码 = 500
                    正文 = json.dumps({
                        "成功": False, "值": None,
                        "错误码": "返回结果不符合契约",
                        "错误说明": "网关响应包含不可传输的数据类型",
                    }, ensure_ascii=False).encode("utf-8")
                try:
                    self.send_response(状态码)
                    self.send_header("Content-Type", "application/json; charset=utf-8")
                    self.send_header("Content-Length", str(len(正文)))
                    来源 = self.headers.get("Origin", "")
                    if 来源 and 来源 in 服务器.安全配置.允许来源表:
                        self.send_header("Access-Control-Allow-Origin", 来源)
                        self.send_header("Vary", "Origin")
                        if 服务器.安全配置.要求凭证:
                            self.send_header("Access-Control-Allow-Credentials", "true")
                    self.end_headers()
                    self.wfile.write(正文)
                except (BrokenPipeError, ConnectionResetError, OSError) as 错误:
                    if isinstance(self.server, 有界线程HTTP服务器):
                        self.server.记录连接诊断("流式JSON写回断开", 错误)
                    self.close_connection = True

            def _校验凭证(self) -> bool:
                if not 服务器.安全配置.要求凭证:
                    return True
                凭证 = 提取访问凭证(self.headers)
                通过, _ = 服务器.凭证管理器.校验(凭证)
                if 通过:
                    return True
                服务器.记录审计(self.path, "", "", False, "权限不足")
                self._写JSON(401, {"成功": False, "错误码": "权限不足",
                                   "错误说明": "访问凭证缺失或无效"})
                return False

            def do_POST(self) -> None:
                from urllib.parse import unquote
                路径 = unquote(self.path)
                if 路径 not in ("/网关/流式", "/网关/流式/取消"):
                    self._写JSON(404, {"成功": False, "错误码": "未知路径"})
                    return
                if not self._校验凭证():
                    return
                数据 = self._读取并校验()
                if 数据 is None:
                    return
                if 路径 == "/网关/流式/取消":
                    请求id = str(数据.get("请求id", ""))
                    成功 = 管理器.取消(请求id)
                    服务器.记录审计(路径, 请求id, "", 成功,
                                  "" if 成功 else "请求不存在或已结束")
                    self._写JSON(200, {"成功": 成功, "请求id": 请求id})
                    return
                能力id = str(数据.get("能力id", ""))
                if not 能力id:
                    服务器.记录审计(路径, str(数据.get("请求id", "")), 能力id,
                                  False, "参数不合法")
                    self._写JSON(400, {"成功": False, "错误码": "参数不合法", "错误说明": "能力id不能为空"})
                    return
                参数 = 数据.get("参数") if isinstance(数据.get("参数"), dict) else {}
                try:
                    调用结果 = 调用器.调用能力(
                        能力id, 参数, 调用方="流式HTTP",
                        项目id=str(数据.get("项目id", "")),
                    )
                except Exception:
                    调用结果 = None
                if 调用结果 is None or not getattr(调用结果, "成功", False):
                    错误码 = getattr(调用结果, "错误码", "提供者不可用") if 调用结果 is not None else "提供者不可用"
                    错误说明 = getattr(调用结果, "错误说明", "统一能力调用器未返回结果") if 调用结果 is not None else "统一能力调用器调用失败"
                    服务器.记录审计(路径, str(数据.get("请求id", "")), 能力id,
                                  False, 错误码)
                    状态码 = 404 if 错误码 == "能力不存在" else 400
                    self._写JSON(状态码, {"成功": False, "错误码": 错误码, "错误说明": 错误说明})
                    return
                事件值 = 调用结果.值

                def 生产(停止事件: threading.Event):
                    if hasattr(事件值, "__iter__") and not isinstance(事件值, (str, bytes, dict)):
                        return iter(事件值)
                    return iter([事件值])

                try:
                    最大事件数 = 数据.get("最大事件数", 1000)
                    最大持续秒 = 数据.get("最大持续秒", 30.0)
                    通道 = 管理器.开始(
                        能力id=能力id, 事件生成函数=生产,
                        请求id=str(数据.get("请求id", "")),
                        任务id=str(数据.get("任务id", "")),
                        最大事件数=最大事件数,
                        最大持续秒=最大持续秒,
                    )
                except RuntimeError as 错误:
                    self._写JSON(429, {
                        "成功": False, "错误码": "限流", "错误说明": str(错误),
                    })
                    return
                except (TypeError, ValueError) as 错误:
                    状态码 = 409 if "请求id已存在" in str(错误) else 400
                    错误码 = "幂等键冲突" if 状态码 == 409 else "参数不合法"
                    self._写JSON(状态码, {
                        "成功": False, "错误码": 错误码, "错误说明": str(错误),
                    })
                    return
                服务器.记录审计(路径, 通道.请求id, 能力id, True, "")
                # 生成器可能长时间没有新事件，单靠下一次 wfile.write 无法发现
                # 客户端已断开。独立监视连接 EOF，统一走管理器断开清理路径。
                断开监视停止 = threading.Event()

                def 监视客户端断开() -> None:
                    while not 断开监视停止.is_set() and not 通道.停止事件.is_set():
                        try:
                            可读, _, _ = select.select([self.connection], [], [], 0.1)
                            if not 可读:
                                continue
                            数据 = self.connection.recv(1, socket.MSG_PEEK | socket.MSG_DONTWAIT)
                            if not 数据:
                                管理器.断开(通道.请求id)
                                return
                        except (BlockingIOError, InterruptedError):
                            continue
                        except (OSError, ValueError):
                            管理器.断开(通道.请求id)
                            return

                threading.Thread(
                    target=监视客户端断开,
                    name=f"流式断开监视-{通道.请求id}",
                    daemon=True,
                ).start()
                try:
                    self.send_response(200)
                    self.send_header("Content-Type", "text/event-stream; charset=utf-8")
                    self.send_header("Cache-Control", "no-cache, no-transform")
                    self.send_header("Connection", "close")
                    self.send_header("X-Accel-Buffering", "no")
                    来源 = self.headers.get("Origin", "")
                    if 来源 and 来源 in 服务器.安全配置.允许来源表:
                        self.send_header("Access-Control-Allow-Origin", 来源)
                        self.send_header("Vary", "Origin")
                        if 服务器.安全配置.要求凭证:
                            self.send_header("Access-Control-Allow-Credentials", "true")
                    self.end_headers()
                    for 事件 in 通道.迭代事件():
                        self.wfile.write(通道.格式事件行(事件))
                        self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError, OSError) as 错误:
                    if isinstance(self.server, 有界线程HTTP服务器):
                        self.server.记录连接诊断("流式写回断开", 错误)
                    管理器.断开(通道.请求id)
                finally:
                    断开监视停止.set()
                    管理器.清理(通道.请求id)
                    self.close_connection = True

            def do_OPTIONS(self) -> None:
                from urllib.parse import unquote
                路径 = unquote(self.path)
                来源 = self.headers.get("Origin", "")
                if (路径 not in ("/网关/流式", "/网关/流式/取消")
                        or not 来源 or 来源 not in 服务器.安全配置.允许来源表):
                    self._写JSON(403, {
                        "成功": False, "值": None, "错误码": "权限不足",
                        "错误说明": "跨域来源未授权",
                    })
                    return
                请求头表 = {
                    项.strip().lower()
                    for 项 in self.headers.get("Access-Control-Request-Headers", "").split(",")
                    if 项.strip()
                }
                if (服务器.安全配置.要求凭证
                        and not ({"authorization", "x-system-credential"} & 请求头表)):
                    self._写JSON(403, {
                        "成功": False, "值": None, "错误码": "权限不足",
                        "错误说明": "预检未声明受支持的凭证请求头",
                    })
                    return
                try:
                    self.send_response(204)
                    self.send_header("Access-Control-Allow-Origin", 来源)
                    self.send_header("Vary", "Origin")
                    self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
                    self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization, X-System-Credential, X-Request-ID")
                    if 服务器.安全配置.要求凭证:
                        self.send_header("Access-Control-Allow-Credentials", "true")
                    self.send_header("Access-Control-Max-Age", "86400")
                    self.end_headers()
                except (BrokenPipeError, ConnectionResetError, OSError) as 错误:
                    if isinstance(self.server, 有界线程HTTP服务器):
                        self.server.记录连接诊断("流式预检写回断开", 错误)
                    self.close_connection = True

            def _方法不允许(self) -> None:
                self._写JSON(405, {"成功": False, "错误码": "方法不允许", "错误说明": "流式入口仅支持 POST"})

            def do_GET(self) -> None:
                self._方法不允许()

            do_PUT = do_GET
            do_PATCH = do_GET
            do_DELETE = do_GET
            do_HEAD = do_GET

        try:
            self.服务器 = 有界线程HTTP服务器(
                (self.地址, self.端口), 处理器, 最大工作线程=self.并发上限,
            )
        except (OSError, ValueError) as 错误:
            return False, f"流式服务启动失败: {错误}"
        self.端口 = int(self.服务器.server_address[1])
        self.线程 = threading.Thread(target=self.服务器.serve_forever, daemon=True)
        self.线程.start()
        return True, f"流式服务已启动 http://{self.地址}:{self.端口}"

    def 连接诊断快照(self) -> list[dict[str, Any]]:
        服务器 = self.服务器
        return 服务器.连接诊断快照() if 服务器 is not None else []

    def 记录审计(self, 路径: str, 请求id: str, 能力id: str,
                成功: bool, 错误码: str) -> None:
        """记录有限审计摘要，不保存凭证、参数和响应内容。"""
        with self.审计锁:
            self.审计记录表.append({"路径": str(路径), "请求id": str(请求id)[:64],
                                  "能力id": str(能力id)[:128], "成功": bool(成功),
                                  "错误码": str(错误码)[:64]})
            if len(self.审计记录表) > 1000:
                del self.审计记录表[:-1000]

    def 审计快照(self) -> list[dict[str, Any]]:
        """返回审计摘要副本，供状态检查使用。"""
        with self.审计锁:
            return [dict(记录) for 记录 in self.审计记录表]

    def 优雅停止(self) -> bool:
        """停止流式服务；返回是否确认收敛（服务线程已退出、通道已清空）。

        线程 join 超时或通道仍残留时返回 False，调用方不得按“已停止”处理。
        """
        with self.管理器.锁:
            活动通道 = list(self.管理器.通道表.values())
        for 通道 in 活动通道:
            通道.取消()
        if self.服务器 is not None:
            self.服务器.shutdown()
            self.服务器.server_close()
            self.服务器 = None
        # 有界 join 服务线程，确认线程已退出才返回，避免停止后生产/
        # 超时/断开监视线程仍持有生成器、socket 或外部资源。
        收敛 = True
        if self.线程 is not None:
            self.线程.join(timeout=5.0)
            if self.线程.is_alive():
                收敛 = False
            self.线程 = None
        with self.管理器.锁:
            self.管理器.通道表.clear()
        return 收敛
