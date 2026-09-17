"""网络请求原子能力实现：HTTP 客户端，适配所有主流网络场景。

安全约束：
- SSRF 防护：仅允许 http/https；默认拒绝 回环/内网/私有/保留/链路本地/多播/
  未指定地址、云元数据、运营商 NAT 100.64.0.0/10、IPv4-mapped IPv6 与内嵌凭据。
  判定**不在本文件重复实现**，统一委托 出站安全.校验出站URL（唯一判定实现）。
- **校验地址与连接地址绑定**：校验通过后，本能力自己解析出候选 IP、逐个交给同一份
  权威判定（`校验出站URL`）复核，随后**只连这些已复核的 IP**（显式指定连接目标，
  不再让 urllib 二次解析主机名）。URL 的 host 原样保留，`Host` 头与 TLS SNI 均为
  原始主机名，因此不破坏 TLS 校验与虚拟主机。修复前：校验解析一次、urllib 连接时
  再解析一次，两次解析之间可被 DNS 重绑定（首次返回公网 IP 通过校验、二次返回
  127.0.0.1/内网）绕过。任一跳找不到可用候选 IP 时 fail-closed 拒绝。
- 重定向逐跳校验：默认跟随重定向时每一跳在发起前重跑同一份强校验，任何一跳
  命中禁目标即中止；不允许「首跳合法、第二跳打到内网/元数据」。
  逐跳同样重做 IP 绑定（每一跳各自解析、各自复核、各自绑定）。
- 响应大小上限：max_bytes 超限即中止，防止无界读入
- 凭据安全：不记录请求头中的敏感字段到错误信息
- 超时：connect/read 统一超时

已知边界（不扩大授权，只如实标注）：显式传 `代理` 或命中系统代理时，连接目标由
代理决定、代理自行解析主机名，本能力无法把 IP 绑定到「代理→目标」那一段；此路径
下 IP 绑定不生效（代理可信时才应使用 `代理` 参数）。
"""

from __future__ import annotations

import base64
import http.client
import ipaddress
import json
import os
import socket
import ssl
import urllib.parse
import urllib.request
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import HTTPHandler, HTTPSHandler, ProxyHandler, build_opener

from 公共契约.基础类型.结果类型 import 结果
from 支持库.后端.网络通信支持库.出站安全 import 校验出站URL
from 公共契约.基础类型.逻辑类型 import 真, 假

敏感头集合 = {"authorization", "x-api-key", "api-key", "cookie", "proxy-authorization"}
默认超时秒 = 10
默认最大字节数 = 5 * 1024 * 1024
默认端口表 = {"http": 80, "https": 443}
已校验地址属性 = "已校验地址列表"  # 挂在 urllib Request 上，供连接处理器取用



降级记录表: list[str] = []  # 尽力清理/降级场景的异常记录（不阻断主流程）

def _解析地址(地址: str) -> urllib.parse.SplitResult:
    try:
        return urllib.parse.urlsplit(地址)
    except ValueError as 错误:
        raise ValueError(f"地址解析失败: {错误}") from 错误


def _是回环地址(地址对象: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """IPv6 按内嵌 IPv4 判定（::ffff:127.0.0.1 也算回环）。"""
    if isinstance(地址对象, ipaddress.IPv6Address) and 地址对象.ipv4_mapped is not None:
        return 地址对象.ipv4_mapped.is_loopback
    return 地址对象.is_loopback


def _探是否纯回环目标(地址: str) -> bool:
    """判定地址是否「整体解析为回环」（字面回环 IP，或主机名全部解析到回环）。

    只在调用方显式传 `允许回环=True` 时用于放行本机自测链路；任一候选地址不是
    回环即返回 False（fail-closed），避免「回环 + 内网混合解析」被整体放行。
    解析失败一律返回 False —— 这种情况下不放行。
    """
    try:
        主机 = _解析地址(地址).hostname
    except ValueError:
        return 假
    if not 主机:
        return 假
    try:
        return _是回环地址(ipaddress.ip_address(主机))
    except ValueError:
        pass
    try:
        地址信息 = socket.getaddrinfo(主机, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
    except OSError:
        return 假
    候选: list[ipaddress.IPv4Address | ipaddress.IPv6Address] = []
    for 条目 in 地址信息:
        try:
            文本 = str(条目[4][0]).split("%")[0]
            候选.append(ipaddress.ip_address(文本))
        except (IndexError, TypeError, ValueError):
            return 假
    return bool(候选) and all(_是回环地址(单个) for 单个 in 候选)


def _校验协议与SSRF(地址: str, 允许回环: bool = 假) -> None:
    """SSRF 强校验：**委托** 出站安全.校验出站URL（唯一判定实现），不复制判定逻辑。

    覆盖：协议白名单（仅 http/https）、URL 内嵌凭据、云元数据地址与主机名
    （169.254.169.254 / 169.254.170.2 / fd00:ec2::254 / 100.100.100.200 /
    metadata.google.internal 等）、运营商 NAT 100.64.0.0/10、IPv4-mapped IPv6
    （::ffff:…）、私有/回环/链路本地/保留/多播/未指定地址；主机名做**逐地址**
    DNS 判定（任一条目为禁目标即拒）。

    `允许回环=True` 只在目标整体解析为回环时放行（本机自测链路），绝不放行内网、
    云元数据、非 http(s) 或内嵌凭据目标。不通过时抛 ValueError，由各能力统一
    转成 结果.失败("参数不合法", "SSRF防护: …")。
    """
    判定 = 校验出站URL(地址=地址, 解析DNS=真)
    if not 判定.成功:
        raise ValueError(f"SSRF防护: {判定.错误说明}")
    判定值 = 判定.值 if isinstance(判定.值, dict) else {}
    if 判定值.get("允许"):
        return
    原因 = str(判定值.get("原因") or "未通过出站安全校验")
    if 允许回环 and _探是否纯回环目标(地址):
        return
    raise ValueError(f"SSRF防护: {原因}")


def _判定单个IP是否放行(IP文本: str) -> str:
    """把单个 IP 交给唯一判定实现复核（不改写判定逻辑）。

    返回 "" 表示放行；否则返回中文拒绝原因。
    """
    if ":" in IP文本:
        规范化 = f"[{IP文本}]"
    else:
        规范化 = IP文本
    判定 = 校验出站URL(地址=f"http://{规范化}/", 解析DNS=假)
    if not 判定.成功:
        return str(判定.错误说明)
    判定值 = 判定.值 if isinstance(判定.值, dict) else {}
    if 判定值.get("允许"):
        return ""
    return str(判定值.get("原因") or "未通过出站安全校验")


def _解析候选地址(地址: str, 允许回环: bool = 假) -> tuple[str, str, int, list[str]]:
    """解析 URL 并返回 (主机名, 协议, 端口, 已复核IP列表)。

    关键：候选 IP **逐个** 交给唯一判定实现（`校验出站URL`）复核，只保留复核通过
    的地址；随后连接阶段只连这些地址。这样「校验的 IP」与「连的 IP」是同一批，
    两次 DNS 解析之间的重绑定无法生效。

    一次都解析不出可用地址时抛 ValueError（fail-closed），绝不放行到第二次解析。
    `允许回环=True` 时回环 IP 才可能进候选（与 `_校验协议与SSRF` 同一口径）。
    """
    解析 = _解析地址(地址)
    协议 = (解析.scheme or "").lower()
    主机名 = (解析.hostname or "").strip()
    if not 主机名:
        raise ValueError("SSRF防护: URL缺少主机名")
    try:
        端口 = 解析.port or 默认端口表.get(协议, 0)
    except ValueError as 错误:
        raise ValueError(f"SSRF防护: 端口非法（{错误}）") from 错误
    if not 端口:
        raise ValueError("SSRF防护: 无法确定端口")

    规范化主机 = 主机名.split("%")[0]

    # 字面 IP：无需解析，直接构造为唯一候选（URL 级判定已在 _校验协议与SSRF 做过）
    try:
        字面对象 = ipaddress.ip_address(规范化主机)
    except ValueError:
        字面对象 = None
    if 字面对象 is not None:
        if _判定单个IP是否放行(规范化主机):
            if 允许回环 and _是回环地址(字面对象):
                return 规范化主机, 协议, 端口, [规范化主机]
            raise ValueError(f"SSRF防护: 字面地址 {规范化主机} 未通过出站安全校验")
        return 规范化主机, 协议, 端口, [规范化主机]

    try:
        地址信息 = socket.getaddrinfo(规范化主机, 端口, socket.AF_UNSPEC, socket.SOCK_STREAM)
    except OSError as 错误:
        raise ValueError(f"SSRF防护: DNS解析失败：{规范化主机}") from 错误

    全部文本: list[str] = []
    for 条目 in 地址信息:
        try:
            文本 = str(条目[4][0]).split("%")[0]
        except (IndexError, TypeError):
            continue
        if 文本 not in 全部文本:
            全部文本.append(文本)

    # 整体纯回环：只有「所有解析结果都是回环」才允许调用方以 允许回环=True 放行本机
    # 自测链路（与 _探是否纯回环目标 同一口径）。混合解析（公网+回环）不放行。
    整体纯回环 = bool(全部文本) and all(_是回环地址(ipaddress.ip_address(文本)) for 文本 in 全部文本)

    候选: list[str] = []
    原因池: list[str] = []
    for IP文本 in 全部文本:
        否定原因 = _判定单个IP是否放行(IP文本)
        if not 否定原因:
            候选.append(IP文本)
            continue
        if 允许回环 and 整体纯回环 and _是回环地址(ipaddress.ip_address(IP文本)):
            候选.append(IP文本)
            continue
        原因池.append(f"{IP文本}（{否定原因}）")

    if not 候选:
        明细 = "；".join(原因池) if 原因池 else "无可用解析结果"
        raise ValueError(f"SSRF防护: 主机名{规范化主机}没有可用的安全解析地址：{明细}")
    return 规范化主机, 协议, 端口, 候选


def _是否走代理(地址: str) -> bool:
    """判定该 URL 是否会经 **系统代理**（显式 `代理` 参数由调用方另判）。

    走代理时连接目标由代理决定、代理解析主机名，IP 绑定无法生效；此时保持原有
    路径不变（不绑定），避免把发往代理的连接错误地钉到目标 IP 上。
    """
    try:
        解析 = urllib.parse.urlsplit(地址)
        主机名 = 解析.hostname or ""
        协议 = (解析.scheme or "").lower()
    except ValueError:
        return 假
    try:
        if urllib.request.proxy_bypass(主机名):
            return 假
        代理表 = urllib.request.getproxies()
    except Exception:
        return 假
    return bool(代理表.get(协议) or 代理表.get("all"))


def _绑定地址到请求(请求: urllib.request.Request, 地址: str,
                    允许回环: bool = 假, 显式代理: str = None) -> list[str]:
    """把「校验阶段解析并复核过的 IP」挂到请求上，供连接处理器绑定。

    两种走代理的情况都无法绑定（连接目标是代理，代理解析真实主机名）：
    - 调用方显式传了 `代理`；
    - 未传 `代理` 但命中系统代理（`build_opener` 会自动挂上系统代理处理器）。
    这两种情况返回 [] 且不挂属性，保持原有代理路径行为不变，避免把发往代理的连接
    错误地钉到目标 IP 上。
    """
    if 显式代理 or _是否走代理(地址):
        return []
    主机名, 协议, 端口, 候选IP列表 = _解析候选地址(地址, 允许回环=允许回环)
    setattr(请求, 已校验地址属性, {"主机": 主机名, "端口": 端口, "协议": 协议, "IP列表": 候选IP列表})
    return 候选IP列表


class _绑定IP连接处理器:
    """混入类：把连接目标固定为 **已校验的 IP**，同时保留 Host 头与 TLS SNI。

    继承链：`绑定地址HTTP连接` / `绑定地址HTTPS连接` 把本类排在 http.client 连接类
    之前，`__init__` 收下已复核 IP 列表后照常用**原始主机名**调父类构造 —— 因此
    `self.host` 仍是主机名，HTTP 的 `Host` 头（urllib 用 req.host 生成）与 HTTPS 的
    `server_hostname`（SNI + 证书校验用）都是原始主机名，虚拟主机与 TLS 不受影响。

    真正建立套接字的 `_create_connection` 被换成「只连已复核 IP」：按序尝试候选 IP，
    全部失败才抛错。**主机名从未交给系统解析器**，所以不存在第二次解析，DNS 重绑定
    没有生效窗口；候选 IP 为空时也不会退回按主机名解析（fail-closed）。
    """

    def __init__(self, *参数, 已校验IP列表=None, **关键字):
        self._已校验IP列表 = [str(单项) for 单项 in (已校验IP列表 or [])]
        super().__init__(*参数, **关键字)

    def connect(self):
        原始创建连接 = socket.create_connection
        候选IP列表 = self._已校验IP列表
        if 候选IP列表:
            def 只连已校验IP(地址二元组, *参数, **关键字):
                端口 = 地址二元组[1]
                最后错误: Exception | None = None
                for IP文本 in 候选IP列表:
                    try:
                        # IP 字面量：create_connection 内部 getaddrinfo 只做数字解析，
                        # 不会触发 DNS 查询 —— 这正是「不再二次解析」的关键。
                        return 原始创建连接((IP文本, 端口), *参数, **关键字)
                    except OSError as 错误:
                        最后错误 = 错误
                raise 最后错误 or OSError("SSRF防护: 没有可用的已校验连接地址")
            self._create_connection = 只连已校验IP
        return super().connect()


class 绑定地址HTTP连接(_绑定IP连接处理器, http.client.HTTPConnection):
    """http.client.HTTPConnection + 已校验 IP 绑定。"""


class 绑定地址HTTPS连接(_绑定IP连接处理器, http.client.HTTPSConnection):
    """http.client.HTTPSConnection + 已校验 IP 绑定（SNI 仍是原始主机名）。"""


def _取已校验IP列表(请求: urllib.request.Request) -> list[str]:
    元信息 = getattr(请求, 已校验地址属性, None)
    if isinstance(元信息, dict):
        列表 = 元信息.get("IP列表")
        if isinstance(列表, list) and 列表:
            return 列表
    return []


class _绑定地址HTTPHandler(HTTPHandler):
    """http 处理器：请求带已校验 IP 时，连接只打那些 IP。"""

    def do_open(self, http_class, req, **额外参数):
        已校验 = _取已校验IP列表(req)
        if 已校验:
            return super().do_open(绑定地址HTTP连接, req, 已校验IP列表=已校验, **额外参数)
        return super().do_open(http_class, req, **额外参数)

    http_request = HTTPHandler.do_request_


class _绑定地址HTTPSHandler(HTTPSHandler):
    """https 处理器：连接只打已校验 IP，TLS 用原始主机名做 SNI 与证书校验。

    urllib 的 `AbstractHTTPHandler.do_open` 用 `http_class(host, ...)` 建连接，host
    仍是主机名，故 `HTTPSConnection.connect` 里的 `server_hostname = self.host` 天然
    就是原主机名 —— SNI 与虚拟主机不受影响，只有套接字目标被换成已复核 IP。
    """

    def https_open(self, req):
        已校验 = _取已校验IP列表(req)
        if 已校验:
            # 只传 `context`，**不要传 check_hostname**：CPython 3.14 的 `HTTPSHandler.__init__`
            # 虽收 `check_hostname` 参数，却只把 `_debuglevel`/`_context` 存成实例属性
            # （3.9 会存 `self._check_hostname`）→ 取 `self._check_hostname` 会 AttributeError。
            # 证书校验开关本就在 `context` 里（`check_hostname` 是 context 的属性），
            # 传 context 已足够，无需再传该参数。
            return self.do_open(绑定地址HTTPS连接, req, 已校验IP列表=已校验,
                                context=self._context)
        return super().https_open(req)

    https_request = HTTPSHandler.do_request_


def _构造打开器(*, 代理: str = None, 允许回环: bool = 假, 跟随重定向: bool = 真,
                 ssl上下文=None) -> urllib.request.OpenerDirector:
    """统一构造 opener：逐跳 SSRF 校验 + 已校验 IP 绑定（两处连接点共用一份）。

    - 显式 `代理`：连接目标由代理决定，逐跳校验保留、IP 绑定关闭（原行为不变）；
    - `跟随重定向=False`：不挂重定向器，3xx 原样交回调用方；
    - https 恒用 `_绑定地址HTTPSHandler` 承载 ssl 上下文，避免出现两个 https 处理器
      导致绑定被旁路。
    """
    处理程序: list[Any] = []
    if 代理:
        处理程序.append(ProxyHandler({"http": 代理, "https": 代理}))
    if 跟随重定向:
        处理程序.append(逐跳校验重定向(允许回环=允许回环, 启用绑定=not bool(代理)))
    else:
        class 不重定向(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, headers, newurl):
                return None
        处理程序.append(不重定向())
    处理程序.append(_绑定地址HTTPHandler())
    处理程序.append(_绑定地址HTTPSHandler(context=ssl上下文))
    return build_opener(*处理程序)


def _构造SSL上下文(SSL验证: bool | None):
    """SSL验证=False → 不校验证书的上下文；否则 None（用默认上下文）。"""
    if SSL验证 is 假:
        try:
            return ssl._create_unverified_context()
        except Exception as 错误:
            降级记录表.append(str(错误))
    return None


class 逐跳校验重定向(urllib.request.HTTPRedirectHandler):
    """默认跟随重定向时的逐跳 SSRF 校验器。

    修复前：只有首个 URL 过校验，302 之后的每一跳直接由 urllib 默认重定向器
    发起 —— 合法公网地址可以把请求「跳」到 0.0.0.0/127.0.0.1/169.254.169.254
    等被禁目标并取回内容（已在本机假服务复现）。

    修复后：每一跳在真正发起前重跑同一份强校验（即 `_校验协议与SSRF`），命中禁
    目标即抛 ValueError 中止，不再继续跟随。

    `允许回环` 的逐跳口径（不扩大调用方授权）：
    - 产生本次 302 的那一跳本身是回环目标时，才沿用调用方的 `允许回环=True`
      （本机自测链路 127.0.0.1 → 127.0.0.1 仍可跟随，既有契约不破）；
    - 产生 302 的那一跳不是回环（公网/其它）时，后续跳一律按 `允许回环=False`
      校验 —— 公网地址无法借 302 把请求「跳」回本机回环。
    - 任何情况下 `0.0.0.0`/内网/保留/云元数据/非 http(s)/内嵌凭据目标都被拒。

    显式 `跟随重定向=False` 时不使用本类（改为 不重定向，把 3xx + Location 原样
    交回调用方）。

    **逐跳 IP 绑定**：`redirect_request` 里对 newurl 重跑校验后立刻重做解析与复核，
    把新的已复核 IP 列表挂到新的 Request 上；下一跳的连接只打这批 IP。这样每一跳
    各自「校验解析 = 连接目标」，302 也无法借第二次解析把请求引向内网。
    `启用绑定=False`（走代理时）则只做校验、不绑定，保持原代理路径行为。
    """

    def __init__(self, 允许回环: bool = 假, 启用绑定: bool = 真) -> None:
        super().__init__()
        self._允许回环 = bool(允许回环)
        self._启用绑定 = bool(启用绑定)

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        放行回环 = self._允许回环 and _探是否纯回环目标(str(getattr(req, "full_url", "")))
        _校验协议与SSRF(newurl, 放行回环)
        新请求 = super().redirect_request(req, fp, code, msg, headers, newurl)
        if 新请求 is not None and self._启用绑定:
            已校验IP列表 = _绑定地址到请求(新请求, newurl, 允许回环=放行回环)
            if not 已校验IP列表 and _是否走代理(newurl):
                降级记录表.append(f"逐跳地址经代理，未启用IP绑定：{newurl}")
        return 新请求


def 编码中文地址(地址: str) -> str:
    解析 = _解析地址(地址)
    编码路径 = urllib.parse.quote(解析.path, safe="/%:@!$&'()*+,;=-._~")
    编码查询 = urllib.parse.quote(解析.query, safe="=&%+,;?/:-._~!$'()*@")
    return urllib.parse.urlunsplit((解析.scheme, 解析.netloc, 编码路径, 编码查询, 解析.fragment))


def 构建查询串(参数: dict = None) -> 结果:
    if not isinstance(参数, dict):
        return 结果.失败("参数不合法", "参数必须是映射", 来源="网络请求")
    return 结果.成功结果(urllib.parse.urlencode(参数) if 参数 else "")


def 发送请求(*, 地址: str = None, 方法: str = "GET", 请求头: dict = None,
              请求体: Any = None, 超时秒: float = 默认超时秒,
              最大字节数: int = 默认最大字节数, 允许回环: bool = 假,
              代理: str = None, SSL验证: bool = None, 跟随重定向: bool = None,
              Cookie: str = None) -> 结果:
    """发送 HTTP 请求，适配所有主流场景。

    支持的场景：
    - GET/POST/PUT/DELETE/PATCH/HEAD/OPTIONS
    - JSON 请求体 / 表单数据 / 原始字节
    - 自定义请求头 / Cookie
    - 代理（http/socks）
    - SSL 证书验证开关
    - 跟随/禁止重定向
    - 超时/SSRF防护/响应上限
    """
    try:
        if not isinstance(地址, str) or 地址.strip() == "":
            return 结果.失败("参数不合法", "地址为空", 来源="网络请求")
        地址 = 编码中文地址(地址)
        _校验协议与SSRF(地址, 允许回环)
        方法 = str(方法 or "GET").upper()
        超时秒 = 超时秒 if isinstance(超时秒, (int, float)) and 超时秒 > 0 else 默认超时秒
        最大字节数 = 最大字节数 if isinstance(最大字节数, int) and 最大字节数 > 0 else 默认最大字节数

        # 构造请求
        请求头 = dict(请求头 or {})
        if Cookie:
            请求头.setdefault("Cookie", Cookie)

        # 序列化请求体
        请求体字节 = None
        if 请求体 is not None:
            if isinstance(请求体, dict):
                # 自动检测 Content-Type
                if not 请求头.get("Content-Type", "").startswith("multipart/"):
                    请求头.setdefault("Content-Type", "application/json")
                    请求体字节 = json.dumps(请求体, ensure_ascii=False).encode("utf-8")
                else:
                    # multipart 上传：文件上传由调用方构造
                    return 结果.失败("参数不合法", "multipart 请使用 上传文件 能力", 来源="网络请求")
            elif isinstance(请求体, str):
                请求体字节 = 请求体.encode("utf-8")
            elif isinstance(请求体, bytes):
                请求体字节 = 请求体
            else:
                return 结果.失败("参数不合法", "请求体必须是 dict/str/bytes", 来源="网络请求")

        try:
            请求 = urllib.request.Request(地址, data=请求体字节, headers=请求头, method=方法)
        except (TypeError, ValueError) as 错误:
            return 结果.失败("参数不合法", f"请求构造失败: {错误}", 来源="网络请求")

        # 关键安全步骤：把「校验阶段解析并复核过的 IP」绑定到本次连接上（走代理时不绑定）。
        # 绑定后连接只打这些 IP，urllib 不再二次解析主机名 —— DNS 重绑定失去生效窗口。
        _绑定地址到请求(请求, 地址, 允许回环=允许回环, 显式代理=代理)

        # 代理 + 重定向 + IP 绑定 + SSL 上下文 统一由 _构造打开器 装配（两处连接点同一份）
        打开器 = _构造打开器(
            代理=代理,
            允许回环=允许回环,
            跟随重定向=跟随重定向 is not 假,
            ssl上下文=_构造SSL上下文(SSL验证),
        )

        # 普通请求
        try:
            响应对象 = 打开器.open(请求, timeout=超时秒)
            with 响应对象 as 响应:
                状态码 = 响应.getcode()
                响应头 = {键: 值 for 键, 值 in 响应.headers.items()}
                响应字节 = 响应.read(最大字节数 + 1)
                if len(响应字节) > 最大字节数:
                    return 结果.失败("响应超限", f"响应超过上限 {最大字节数} 字节", 来源="网络请求")
                响应文本 = 响应字节.decode("utf-8", errors="replace")
                return 结果.成功结果({"状态码": 状态码, "响应头": 响应头,
                                        "响应文本": 响应文本, "错误信息": ""})
        except HTTPError as 错误:
            # HTTP 4xx/5xx 是远端请求失败，不能包装成成功结果；否则模块
            # 会把服务端拒绝、鉴权失败或网关错误误判为业务成功。
            # 3xx 只在调用方显式 跟随重定向=False 时才会走到这里：此时必须把
            # 状态码与响应头（含 Location）原样带出，调用方才能按业务语义处理
            # （默认路径本能力已内建逐跳 SSRF 校验，不需要调用方手工跟随）。
            try:
                状态码, 原因 = 错误.code, 错误.reason
                响应头 = dict(错误.headers.items()) if 错误.headers else {}
            finally:
                错误.close()
            return 结果.失败(
                "HTTP错误", f"HTTP {状态码}: {原因}",
                来源="网络请求", 可重试=状态码 >= 500,
                详情={"状态码": 状态码, "响应头": 响应头},
            )
        except TimeoutError:
            return 结果.失败("网络超时", "网络请求超时", 来源="网络请求")
        except URLError as 错误:
            return 结果.失败("网络失败", f"网络请求失败: {错误.reason}", 来源="网络请求")
    except ValueError as 错误:
        return 结果.失败("参数不合法", str(错误), 来源="网络请求")
    except OSError as 错误:
        return 结果.失败("网络失败", str(错误), 来源="网络请求")


def _multipart头部转义(值: str) -> str:
    """multipart 头部词组转义：反斜杠与双引号按 RFC 7578/2046 转义（防改写头部结构）。"""
    return str(值).replace("\\", "\\\\").replace('"', '\\"')


def _构造multipart正文(字段名: str, 文件路径: str, 文件名: str,
                       额外字段: dict | None) -> tuple[bytes, str]:
    """手工拼装标准 `multipart/form-data` 正文，返回（正文字节、boundary）。

    B-26 修正：历史实现直接用 `email.mime.multipart.MIMEMultipart` + `as_string()`，
    真实报文出现四处不符（已在本机端点复现）：

    1. `Content-Type: multipart/mixed`（MIMEMultipart 默认 subtype 是 mixed，
       不是 form-data）；
    2. 额外字段用 `MIMEText` 拼 → 只有 `Content-Type: text/plain`，
       没有 `Content-Disposition: form-data; name="…"`，服务端取不到字段名；
    3. 文件载荷 `encoders.encode_base64` → base64 文本，不是原始字节；
    4. `as_string()` 把 `Content-Type`/`MIME-Version` 等 MIME 头写进了 **body** 首部。

    这里改为「boundary + 二进制拼接」：每片自带 `Content-Disposition: form-data`
    头、文件字节原样、结尾 `--boundary--`，`Content-Type` 由调用方带 boundary 传出。

    boundary 必须是 **纯 ASCII**：`Content-Type` 走 HTTP 头，urllib 按 latin-1 编码
    头部，含中文的 boundary 会在发请求前就抛 UnicodeEncodeError（本机复现）。
    各分片的 `name`/`filename` 在 **body** 里（bytes，UTF-8），不受头部编码限制；
    文件名非 ASCII 时额外附 RFC 5987 的 `filename*=UTF-8''…` 供严格服务端取用。
    """
    import uuid as _uuid
    边界 = "----FormBoundary" + _uuid.uuid4().hex
    分片: list[bytes] = []
    for 键, 值 in (额外字段 or {}).items():
        分片.append(
            f"--{边界}\r\n"
            f'Content-Disposition: form-data; name="{_multipart头部转义(键)}"\r\n\r\n'
            f"{值}\r\n".encode("utf-8"))
    文件名声明 = f'filename="{_multipart头部转义(文件名)}"'
    if any(序 > 127 for 序 in 文件名.encode("utf-8")):
        文件名声明 += f"; filename*=UTF-8''{urllib.parse.quote(文件名, safe='')}"
    分片.append(
        f"--{边界}\r\n"
        f'Content-Disposition: form-data; name="{_multipart头部转义(字段名)}"; '
        f"{文件名声明}\r\n"
        "Content-Type: application/octet-stream\r\n\r\n".encode("utf-8"))
    with open(文件路径, "rb") as 文件:
        分片.append(文件.read())        # 原始字节，不 base64
    分片.append(f"\r\n--{边界}--\r\n".encode("utf-8"))
    return b"".join(分片), 边界


def 上传文件(*, 地址: str = None, 文件路径: str = None, 字段名: str = "file",
              额外字段: dict = None, 超时秒: float = 默认超时秒,
              允许回环: bool = 假, 代理: str = None) -> 结果:
    """上传文件（multipart/form-data）。返回 {状态码, 响应文本}。"""
    try:
        if not isinstance(地址, str) or 地址.strip() == "":
            return 结果.失败("参数不合法", "地址为空", 来源="网络请求")
        if not isinstance(文件路径, str) or not os.path.isfile(文件路径):
            return 结果.失败("参数不合法", f"文件不存在: {文件路径}", 来源="网络请求")
        _校验协议与SSRF(地址, 允许回环)

        文件大小 = os.path.getsize(文件路径)
        上传上限字节 = 256 * 1024 * 1024
        if 文件大小 > 上传上限字节:
            return 结果.失败("超出限制", f"上传文件过大: {文件大小} 字节 > {上传上限字节}", 来源="网络请求")
        文件名 = os.path.basename(文件路径)
        请求体, 边界 = _构造multipart正文(str(字段名 or "file"), 文件路径, 文件名, 额外字段)
        请求头 = {"Content-Type": f"multipart/form-data; boundary={边界}"}

        return 发送请求(地址=地址, 方法="POST", 请求头=请求头, 请求体=请求体,
                       超时秒=超时秒, 允许回环=允许回环, 代理=代理)
    except ValueError as 错误:
        return 结果.失败("参数不合法", str(错误), 来源="网络请求")
    except Exception as 错误:
        return 结果.失败("上传失败", str(错误), 来源="网络请求")


def 下载文件(*, 地址: str = None, 保存路径: str = None, 请求头: dict = None,
             超时秒: float = 默认超时秒, 允许回环: bool = 假,
             代理: str = None, SSL验证: bool = None,
             最大字节数: int = 默认最大字节数) -> 结果:
    """从 URL 下载文件（流式写入，适配大文件）。返回 {状态码, 文件路径, 字节数}。

    落盘口径（B-33）：**先写同目录 `.part` 临时文件，全部成功才 `os.replace` 到
    `保存路径`**。任何失败路径（超时/网络错误/HTTP 错误/超限/写盘错误）都删掉临时
    文件，`保存路径` 保持原样。历史实现直接 `open(保存路径, "wb")`：
    - 一打开就把旧文件清空，失败后旧文件已毁、目录里只剩半截新内容；
    - 只有「超限」一条路径删文件，TimeoutError/URLError 路径不删 → 半截文件残留，
      调用方无法区分「完整制品」与「失败残片」。
    """
    try:
        if not isinstance(地址, str) or 地址.strip() == "":
            return 结果.失败("参数不合法", "地址为空", 来源="网络请求")
        if not isinstance(保存路径, str) or not 保存路径.strip():
            return 结果.失败("参数不合法", "保存路径为空", 来源="网络请求")
        if isinstance(最大字节数, bool) or not isinstance(最大字节数, int) or 最大字节数 <= 0:
            return 结果.失败("参数不合法", "最大字节数必须是正整数", 来源="网络请求")
        地址 = 编码中文地址(地址)
        _校验协议与SSRF(地址, 允许回环)

        请求 = urllib.request.Request(地址, headers=dict(请求头 or {}), method="GET")

        # 下载同样必须绑定已校验 IP（修复前 302 与二次解析都能打到内网/元数据）
        _绑定地址到请求(请求, 地址, 允许回环=允许回环, 显式代理=代理)

        打开器 = _构造打开器(
            代理=代理,
            允许回环=允许回环,
            跟随重定向=真,
            ssl上下文=_构造SSL上下文(SSL验证),
        )

        import uuid as _uuid
        临时路径 = f"{保存路径}.{_uuid.uuid4().hex}.part"
        try:
            响应对象 = 打开器.open(请求, timeout=超时秒)
            with 响应对象 as 响应:
                状态码 = 响应.getcode()
                with open(临时路径, "wb") as f:
                    字节数 = 0
                    while True:
                        块 = 响应.read(65536)
                        if not 块:
                            break
                        字节数 += len(块)
                        if 字节数 > 最大字节数:
                            # 超限：由 finally 删临时文件，保存路径不动
                            return 结果.失败(
                                "响应超限", f"下载内容超过上限 {最大字节数} 字节",
                                来源="网络请求",
                            )
                        f.write(块)
            # 只有完整读完才落正式路径（同目录 os.replace：原子替换，失败不留半截）
            os.replace(临时路径, 保存路径)
            return 结果.成功结果({"状态码": 状态码, "文件路径": 保存路径, "字节数": 字节数,
                                    "错误信息": ""})
        except HTTPError as 错误:
            return 结果.失败("下载失败", f"HTTP {错误.code}: {错误.reason}", 来源="网络请求")
        except TimeoutError:
            return 结果.失败("网络超时", "下载超时", 来源="网络请求")
        except URLError as 错误:
            return 结果.失败("下载失败", f"网络失败: {错误.reason}", 来源="网络请求")
        finally:
            # 失败/超限/超时一律清掉临时文件（成功时已被 os.replace 移走，missing_ok 兜底）
            try:
                os.unlink(临时路径)
            except FileNotFoundError:
                pass
            except OSError as 清理错误:
                降级记录表.append(f"下载临时文件清理失败 {临时路径}: {清理错误}")
    except ValueError as 错误:
        return 结果.失败("参数不合法", str(错误), 来源="网络请求")
    except OSError as 错误:
        return 结果.失败("下载失败", str(错误), 来源="网络请求")
