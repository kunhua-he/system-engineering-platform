"""出站安全原子能力实现（不对外暴露，只经包级中文入口调用）。

职责：出站 URL 的 SSRF 防护 —— 拒绝指向私有/内网/回环/链路本地/多播/保留地址的请求。

迁移自 V3 `后端服务/应用层/核心/URL安全.py`（薄壳化 1-3），保持判定语义不变：
- 仅允许 http/https；不允许 URL 内嵌认证凭据
- 字面 IP 直接判定；主机名可选 DNS 解析后逐个地址判定
- 云元数据地址与主机名始终封锁（169.254.169.254 / metadata.google.internal 等）
- 运营商 NAT 网段 100.64.0.0/10 一并封锁
- IPv4-mapped IPv6（::ffff:…）按内嵌 IPv4 判定

只做判定，不发起任何网络请求。
"""

from __future__ import annotations

import ipaddress
import queue
import socket
import threading
from urllib.parse import urlparse

from 公共契约.基础类型.结果类型 import 结果

来源标识 = "出站安全"

DNS解析超时秒数默认 = 10.0

已封锁主机名 = frozenset({
    "metadata.google.internal",
    "metadata.goog",
    "169.254.169.254",
})

始终封锁IP列表 = frozenset(
    ipaddress.ip_address(地址)
    for 地址 in [
        "169.254.169.254",
        "169.254.170.2",
        "169.254.169.253",
        "fd00:ec2::254",
        "100.100.100.200",
        "::ffff:169.254.169.254",
        "::ffff:169.254.170.2",
        "::ffff:169.254.169.253",
        "::ffff:100.100.100.200",
    ]
)

始终封锁网络段 = [
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("::ffff:169.254.0.0/112"),
]

运营商NAT网络 = ipaddress.ip_network("100.64.0.0/10")


def 判断是否封锁IP(IP: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """判定单个 IP 是否属于需封锁的范围。"""
    if isinstance(IP, ipaddress.IPv6Address) and IP.ipv4_mapped is not None:
        嵌入IP = IP.ipv4_mapped
        return (
            嵌入IP.is_private or 嵌入IP.is_loopback or
            嵌入IP.is_link_local or 嵌入IP.is_reserved or
            嵌入IP.is_multicast or 嵌入IP.is_unspecified or
            嵌入IP in 运营商NAT网络
        )
    if IP.is_private or IP.is_loopback or IP.is_link_local or IP.is_reserved:
        return True
    if IP.is_multicast or IP.is_unspecified:
        return True
    if IP in 运营商NAT网络:
        return True
    return False


def 解析主机名带超时(主机名: str, 超时秒数: float) -> object:
    """带显式超时地解析主机名（守护线程 + 有界等待），失败抛 OSError。"""
    结果队列: "queue.Queue[tuple[str, object]]" = queue.Queue()

    def _解析() -> None:
        try:
            结果队列.put(("成功", socket.getaddrinfo(
                主机名, None, socket.AF_UNSPEC, socket.SOCK_STREAM)))
        except BaseException as 异常:
            结果队列.put(("失败", 异常))

    线程 = threading.Thread(target=_解析, name=f"出站安全-dns-{主机名[:24]}", daemon=True)
    线程.start()
    线程.join(超时秒数)
    if 线程.is_alive():
        raise TimeoutError(f"DNS解析超时：{主机名}")
    状态, 值 = 结果队列.get()
    if 状态 == "失败":
        if isinstance(值, BaseException):
            raise 值
        raise OSError(f"DNS解析失败：{主机名}")
    return 值


def 校验出站URL(地址: str = None, 解析DNS: bool = True, DNS超时秒: float = None) -> 结果:
    """校验出站 URL 是否满足 SSRF 安全要求。返回 {允许, 原因, 地址}。

    允许 → {允许: True, 原因: "", 地址: <规范化URL>}；
    拒绝 → {允许: False, 原因: "<中文原因>", 地址: ""}。
    只做判定，不发起网络请求。
    """
    if not isinstance(地址, str) or not 地址.strip():
        return 结果.失败("参数不合法", "地址必须是非空字符串", 来源=来源标识)
    原文 = 地址.strip()
    try:
        解析结果 = urlparse(原文)
    except Exception as 异常:
        return 结果.成功结果({"允许": False, "原因": f"URL格式无效：{异常}", "地址": ""})

    协议 = (解析结果.scheme or "").lower()
    if 协议 not in {"http", "https"}:
        return 结果.成功结果({"允许": False, "原因": "仅允许http/https协议的URL", "地址": ""})

    主机名 = (解析结果.hostname or "").strip().lower().rstrip(".")
    if not 主机名:
        return 结果.成功结果({"允许": False, "原因": "URL缺少主机名", "地址": ""})

    if 解析结果.username or 解析结果.password:
        return 结果.成功结果({"允许": False, "原因": "URL中不允许嵌入认证凭据", "地址": ""})

    if 主机名 in 已封锁主机名:
        return 结果.成功结果({"允许": False, "原因": "URL指向了被封锁的内网地址", "地址": ""})

    try:
        IP = ipaddress.ip_address(主机名)
    except ValueError:
        IP = None

    if IP is not None:
        if IP in 始终封锁IP列表 or any(IP in 网段 for 网段 in 始终封锁网络段):
            return 结果.成功结果({"允许": False, "原因": "URL指向了被封锁的内网地址", "地址": ""})
        if 判断是否封锁IP(IP):
            return 结果.成功结果({"允许": False, "原因": "URL指向了私有/内网地址", "地址": ""})
        return 结果.成功结果({"允许": True, "原因": "", "地址": 原文})

    if not 解析DNS:
        # 不做 DNS 判定：仅按字面主机名放行，由调用方自行承担解析后地址风险。
        return 结果.成功结果({"允许": True, "原因": "", "地址": 原文})

    超时 = DNS解析超时秒数默认 if DNS超时秒 is None else float(DNS超时秒)
    try:
        地址信息 = 解析主机名带超时(主机名, 超时)
    except TimeoutError:
        return 结果.成功结果({"允许": False, "原因": f"DNS解析超时：{主机名}", "地址": ""})
    except Exception:
        return 结果.成功结果({"允许": False, "原因": f"DNS解析失败：{主机名}", "地址": ""})

    if not isinstance(地址信息, list):
        return 结果.成功结果({"允许": False, "原因": f"DNS解析结果异常：{主机名}", "地址": ""})

    for 条目 in 地址信息:
        try:
            套接字地址 = 条目[4]
            IP字符串 = 套接字地址[0]
        except (IndexError, TypeError):
            continue
        if "%" in IP字符串:
            IP字符串 = IP字符串.split("%")[0]
        try:
            解析IP = ipaddress.ip_address(IP字符串)
        except ValueError:
            return 结果.成功结果({
                "允许": False, "原因": f"主机名{主机名}解析出的IP格式无法解析", "地址": ""})
        if 解析IP in 始终封锁IP列表 or any(解析IP in 网段 for 网段 in 始终封锁网络段):
            return 结果.成功结果({"允许": False, "原因": "URL解析到了被封锁的内网地址", "地址": ""})
        if 判断是否封锁IP(解析IP):
            return 结果.成功结果({"允许": False, "原因": "URL解析到了私有/内网地址", "地址": ""})

    return 结果.成功结果({"允许": True, "原因": "", "地址": 原文})
