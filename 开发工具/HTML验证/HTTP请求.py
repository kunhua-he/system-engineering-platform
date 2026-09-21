"""回环 HTTP 请求与错误归一化。"""
from __future__ import annotations
import http.client, ipaddress, json, threading, time, urllib.parse
from typing import Any
from 开发工具.HTML验证.常量 import 请求上限字节
from 开发工具.HTML验证.单步场景 import 验证场景

#: 每线程一条长连接（未完成事项 #192）：键=(主机, 端口)，值=http.client.HTTPConnection。
#: 用线程本地而不是全局池：验证链一个场景的多个步骤本就在同一线程内串行执行，
#: 线程本地天然做到「同一场景的步骤复用同一条连接」，且无需加锁。
_连接缓存 = threading.local()


def _取连接(主机: str, 端口: int, 超时秒: float) -> http.client.HTTPConnection:
    """按 (主机, 端口) 取本线程的长连接，没有就新建（#192 连接复用）。"""
    连接表 = getattr(_连接缓存, "连接表", None)
    if 连接表 is None:
        连接表 = {}
        _连接缓存.连接表 = 连接表
    键 = (主机, 端口)
    连接 = 连接表.get(键)
    if 连接 is None:
        连接 = http.client.HTTPConnection(主机, 端口, timeout=超时秒)
        连接表[键] = 连接
    else:
        连接.timeout = 超时秒
    return 连接


def _丢弃连接(主机: str, 端口: int) -> None:
    """丢弃本线程的这条连接：任何传输异常后都必须重建，绝不复用半死连接。"""
    连接表 = getattr(_连接缓存, "连接表", None)
    if not 连接表:
        return
    连接 = 连接表.pop((主机, 端口), None)
    if 连接 is not None:
        try:
            连接.close()
        except OSError:
            pass


def _校验直连地址(地址: str) -> str:
    if not isinstance(地址, str) or not 地址:
        raise ValueError("直连地址不能为空")
    try:
        拆分 = urllib.parse.urlsplit(地址)
        主机 = 拆分.hostname
        端口 = 拆分.port
    except ValueError as 错误:
        raise ValueError(f"直连地址不合法: {地址}") from 错误
    if 拆分.scheme != "http" or not 主机 or 端口 is None:
        raise ValueError("直连地址必须是带显式端口的 HTTP 回环 URL")
    try:
        if not ipaddress.ip_address(主机).is_loopback:
            raise ValueError("直连地址必须使用 IP 回环地址")
    except ValueError as 错误:
        raise ValueError("直连地址必须使用 IP 回环地址，不能使用主机名") from 错误
    if 拆分.username or 拆分.password or 拆分.path not in {"", "/"} or 拆分.query or 拆分.fragment:
        raise ValueError("直连地址不得包含凭据、业务路径、查询或片段")
    return 地址.rstrip("/")

def _单次请求(目标: str, 场景: 验证场景, 超时秒: float) -> tuple[int, dict[str, Any]]:
    """发一次真实 HTTP 请求并把响应归一成 (状态码, 数据)。

    #192（2026-09-21）：传输层从 `urllib.request.urlopen` 换成
    `http.client.HTTPConnection` **按线程复用长连接**。原实现每请求都新建 TCP
    连接（DNS + 三次握手），一个多步场景就要握手 N 次；复用后同一线程只握一次。
    状态码与错误归一化口径（返回过大 / 返回非JSON / 网关断开 502）逐字不变。
    """
    拆分 = urllib.parse.urlsplit(目标)
    主机 = 拆分.hostname or ""
    端口 = 拆分.port or 80
    路径 = 拆分.path or "/"
    if 拆分.query:
        路径 = f"{路径}?{拆分.query}"
    方法 = "GET" if 场景.方法 == "GET" else "POST"
    请求体: bytes | None = None
    请求头 = {"Accept": "application/json"}
    if 方法 == "POST":
        请求体 = json.dumps(
            {"能力id": 场景.能力id, "参数": 场景.参数}, ensure_ascii=False
        ).encode("utf-8")
        请求头["Content-Type"] = "application/json"
    try:
        连接 = _取连接(主机, 端口, 超时秒)
        连接.request(方法, 路径, body=请求体, headers=请求头)
        响应 = 连接.getresponse()
        try:
            状态码 = 响应.status
            正文 = 响应.read(请求上限字节 + 1)
        finally:
            响应.close()
    except (http.client.HTTPException, OSError, TimeoutError) as 错误:
        # 半死连接绝不复用：丢弃后下次调用重建（与「传输层无响应重试一次」配套）。
        _丢弃连接(主机, 端口)
        return 502, {"成功": False, "错误码": "网关断开", "错误说明": str(错误)}
    if len(正文) > 请求上限字节:
        return 状态码, {"成功": False, "错误码": "返回过大", "错误说明": "响应超过读取上限"}
    try:
        数据 = json.loads(正文.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        数据 = {"成功": False, "错误码": "返回非JSON", "错误说明": 正文[:200].decode("utf-8", errors="replace")}
    return 状态码, 数据


def _发送请求(地址: str, 场景: 验证场景, 超时秒: float) -> tuple[int, dict[str, Any], float]:
    """回环真实 HTTP 请求；**传输层无响应断连重试一次**（写进证据，不掩盖语义失败）。

    历史现象（2026-09-15 实测）：制品在 64 路并发下偶发
    `Remote end closed connection without response`——连接建立后被对端关闭、**一个字节响应都没有**。
    这属传输抖动，不是能力语义失败；因此只对「无任何响应」重试一次并把 `传输重试` 记进证据。
    **有响应的失败**（4xx/5xx/非 JSON/返回过大）一律不重试，保持真实口径。
    """
    开始 = time.monotonic()
    拆分 = urllib.parse.urlsplit(地址)
    基址 = f"{拆分.scheme}://{拆分.netloc}"
    路径 = 场景.路径 if 场景.路径.startswith("/") else "/" + 场景.路径
    目标 = 基址 + urllib.parse.quote(路径, safe="/:@._-")
    状态码, 数据 = _单次请求(目标, 场景, 超时秒)
    if 状态码 == 502 and 数据.get("错误码") == "网关断开":
        time.sleep(0.2)
        状态码, 数据 = _单次请求(目标, 场景, 超时秒)
        数据 = dict(数据)
        数据["传输重试"] = 1
    return 状态码, 数据, (time.monotonic() - 开始) * 1000
