"""网络请求原子能力实现：HTTP 客户端，适配所有主流网络场景。

安全约束：
- SSRF 防护：仅允许 http/https；默认拒绝 回环/内网/私有/保留/链路本地/多播/
  未指定地址、云元数据、运营商 NAT 100.64.0.0/10、IPv4-mapped IPv6 与内嵌凭据。
  判定**不在本文件重复实现**，统一委托 出站安全.校验出站URL（唯一判定实现）。
- 重定向逐跳校验：默认跟随重定向时每一跳在发起前重跑同一份强校验，任何一跳
  命中禁目标即中止；不允许「首跳合法、第二跳打到内网/元数据」。
- 响应大小上限：max_bytes 超限即中止，防止无界读入
- 凭证安全：不记录请求头中的敏感字段到错误信息
- 超时：connect/read 统一超时
"""

from __future__ import annotations

import base64
import ipaddress
import json
import os
import socket
import urllib.parse
import urllib.request
from typing import Any
from urllib.error import HTTPError, URLError

from 公共契约.基础类型.结果类型 import 结果
from 支持库.后端.网络通信支持库.出站安全 import 校验出站URL

敏感头集合 = {"authorization", "x-api-key", "api-key", "cookie", "proxy-authorization"}
默认超时秒 = 10
默认最大字节数 = 5 * 1024 * 1024



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
        return False
    if not 主机:
        return False
    try:
        return _是回环地址(ipaddress.ip_address(主机))
    except ValueError:
        pass
    try:
        地址信息 = socket.getaddrinfo(主机, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
    except OSError:
        return False
    候选: list[ipaddress.IPv4Address | ipaddress.IPv6Address] = []
    for 条目 in 地址信息:
        try:
            文本 = str(条目[4][0]).split("%")[0]
            候选.append(ipaddress.ip_address(文本))
        except (IndexError, TypeError, ValueError):
            return False
    return bool(候选) and all(_是回环地址(单个) for 单个 in 候选)


def _校验协议与SSRF(地址: str, 允许回环: bool = False) -> None:
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
    判定 = 校验出站URL(地址=地址, 解析DNS=True)
    if not 判定.成功:
        raise ValueError(f"SSRF防护: {判定.错误说明}")
    判定值 = 判定.值 if isinstance(判定.值, dict) else {}
    if 判定值.get("允许"):
        return
    原因 = str(判定值.get("原因") or "未通过出站安全校验")
    if 允许回环 and _探是否纯回环目标(地址):
        return
    raise ValueError(f"SSRF防护: {原因}")


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
    """

    def __init__(self, 允许回环: bool = False) -> None:
        super().__init__()
        self._允许回环 = bool(允许回环)

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        放行回环 = self._允许回环 and _探是否纯回环目标(str(getattr(req, "full_url", "")))
        _校验协议与SSRF(newurl, 放行回环)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


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
              最大字节数: int = 默认最大字节数, 允许回环: bool = False,
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

        # 代理 + 重定向 统一用 opener；默认路径必须挂逐跳 SSRF 校验器
        from urllib.request import HTTPSHandler, ProxyHandler, build_opener
        处理程序 = []
        if 代理:
            处理程序.append(ProxyHandler({"http": 代理, "https": 代理}))
        if 跟随重定向 is False:
            class 不重定向(urllib.request.HTTPRedirectHandler):
                def redirect_request(self, req, fp, code, msg, headers, newurl):
                    return None
            处理程序.append(不重定向())
        else:
            # 默认（含显式 跟随重定向=True）走逐跳校验：3xx 的每一跳都重跑 SSRF 校验。
            处理程序.append(逐跳校验重定向(允许回环=允许回环))

        # SSL 验证：关掉验证时把上下文挂到 HTTPSHandler 上。
        # 旧实现只在 `urlopen` 分支传 context，一挂上 opener（代理或禁止重定向）
        # 就静默丢弃 SSL验证=False；现统一由 HTTPSHandler 承载，两条路径一致。
        ssl上下文 = None
        if SSL验证 is False:
            try:
                import ssl
                ssl上下文 = ssl._create_unverified_context()
            except Exception as 错误:
                降级记录表.append(str(错误))
        if ssl上下文 is not None:
            处理程序.append(HTTPSHandler(context=ssl上下文))
        打开器 = build_opener(*处理程序)

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


def 上传文件(*, 地址: str = None, 文件路径: str = None, 字段名: str = "file",
              额外字段: dict = None, 超时秒: float = 默认超时秒,
              允许回环: bool = False, 代理: str = None) -> 结果:
    """上传文件（multipart/form-data）。返回 {状态码, 响应文本}。"""
    try:
        if not isinstance(地址, str) or 地址.strip() == "":
            return 结果.失败("参数不合法", "地址为空", 来源="网络请求")
        if not isinstance(文件路径, str) or not os.path.isfile(文件路径):
            return 结果.失败("参数不合法", f"文件不存在: {文件路径}", 来源="网络请求")
        _校验协议与SSRF(地址, 允许回环)

        import email.mime.multipart
        import email.mime.base
        import email.mime.text
        from email import encoders

        消息 = email.mime.multipart.MIMEMultipart()
        for 键, 值 in (额外字段 or {}).items():
            消息.attach(email.mime.text.MIMEText(值))
        文件大小 = os.path.getsize(文件路径)
        上传上限字节 = 256 * 1024 * 1024
        if 文件大小 > 上传上限字节:
            return 结果.失败("超出限制", f"上传文件过大: {文件大小} 字节 > {上传上限字节}", 来源="网络请求")
        with open(文件路径, "rb") as f:
            附件 = email.mime.base.MIMEBase("application", "octet-stream")
            附件.set_payload(f.read())
            encoders.encode_base64(附件)
            附件.add_header("Content-Disposition", f"form-data; name=\"{字段名}\"; filename=\"{os.path.basename(文件路径)}\"")
            消息.attach(附件)

        请求体 = 消息.as_string().encode("utf-8")
        请求头 = {"Content-Type": 消息.get_content_type()}

        return 发送请求(地址=地址, 方法="POST", 请求头=请求头, 请求体=请求体,
                       超时秒=超时秒, 允许回环=允许回环, 代理=代理)
    except ValueError as 错误:
        return 结果.失败("参数不合法", str(错误), 来源="网络请求")
    except Exception as 错误:
        return 结果.失败("上传失败", str(错误), 来源="网络请求")


def 下载文件(*, 地址: str = None, 保存路径: str = None, 请求头: dict = None,
             超时秒: float = 默认超时秒, 允许回环: bool = False,
             代理: str = None, SSL验证: bool = None,
             最大字节数: int = 默认最大字节数) -> 结果:
    """从 URL 下载文件（流式写入，适配大文件）。返回 {状态码, 文件路径, 字节数}。"""
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

        # 代理 + 重定向：下载同样必须挂逐跳校验（修复前 302 可打到内网/元数据）
        from urllib.request import HTTPSHandler, ProxyHandler, build_opener
        处理程序 = []
        if 代理:
            处理程序.append(ProxyHandler({"http": 代理, "https": 代理}))
        处理程序.append(逐跳校验重定向(允许回环=允许回环))

        ssl上下文 = None
        if SSL验证 is False:
            try:
                import ssl
                ssl上下文 = ssl._create_unverified_context()
            except Exception as 错误:
                降级记录表.append(str(错误))
        if ssl上下文 is not None:
            处理程序.append(HTTPSHandler(context=ssl上下文))
        打开器 = build_opener(*处理程序)

        try:
            响应对象 = 打开器.open(请求, timeout=超时秒)
            with 响应对象 as 响应:
                状态码 = 响应.getcode()
                with open(保存路径, "wb") as f:
                    字节数 = 0
                    while True:
                        块 = 响应.read(65536)
                        if not 块:
                            break
                        字节数 += len(块)
                        if 字节数 > 最大字节数:
                            # 超限时删除截断文件，避免调用方误把部分内容当成
                            # 成功制品继续处理。
                            try:
                                os.unlink(保存路径)
                            except OSError:
                                pass
                            return 结果.失败(
                                "响应超限", f"下载内容超过上限 {最大字节数} 字节",
                                来源="网络请求",
                            )
                        f.write(块)
                return 结果.成功结果({"状态码": 状态码, "文件路径": 保存路径, "字节数": 字节数,
                                        "错误信息": ""})
        except HTTPError as 错误:
            return 结果.失败("下载失败", f"HTTP {错误.code}: {错误.reason}", 来源="网络请求")
        except TimeoutError:
            return 结果.失败("网络超时", "下载超时", 来源="网络请求")
        except URLError as 错误:
            return 结果.失败("下载失败", f"网络失败: {错误.reason}", 来源="网络请求")
    except ValueError as 错误:
        return 结果.失败("参数不合法", str(错误), 来源="网络请求")
    except OSError as 错误:
        return 结果.失败("下载失败", str(错误), 来源="网络请求")
