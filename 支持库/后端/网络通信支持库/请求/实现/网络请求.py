"""网络请求原子能力实现：HTTP 客户端，适配所有主流网络场景。

安全约束：
- SSRF 防护：仅允许 http/https；默认拒绝 回环/内网/私有地址/文件等非公网目标
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

敏感头集合 = {"authorization", "x-api-key", "api-key", "cookie", "proxy-authorization"}
默认超时秒 = 10
默认最大字节数 = 5 * 1024 * 1024



降级记录表: list[str] = []  # 尽力清理/降级场景的异常记录（不阻断主流程）

def _解析地址(地址: str) -> urllib.parse.SplitResult:
    try:
        return urllib.parse.urlsplit(地址)
    except ValueError as 错误:
        raise ValueError(f"地址解析失败: {错误}") from 错误


def _校验协议与SSRF(地址: str, 允许回环: bool) -> None:
    解析 = _解析地址(地址)
    if 解析.scheme not in ("http", "https"):
        raise ValueError(f"仅允许 http/https 协议: {解析.scheme}")
    try:
        主机 = 解析.hostname
        if not 主机:
            raise ValueError("地址缺少主机名")
        地址对象 = ipaddress.ip_address(主机)
    except ValueError:
        try:
            地址对象 = ipaddress.ip_address(socket.gethostbyname(主机))
        except OSError as 错误:
            raise ValueError(f"主机名解析失败: {错误}") from 错误
    if 地址对象.is_loopback:
        if not 允许回环:
            raise ValueError("SSRF防护: 禁止访问回环地址")
        return
    if 地址对象.is_private or 地址对象.is_link_local or 地址对象.is_reserved or 地址对象.is_multicast:
        raise ValueError(f"SSRF防护: 禁止访问内网/保留地址: {地址对象}")


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

        # 代理 + 重定向 统一用 opener
        from urllib.request import ProxyHandler, build_opener
        处理程序 = []
        if 代理:
            处理程序.append(ProxyHandler({"http": 代理, "https": 代理}))
        if 跟随重定向 is False:
            class 不重定向(urllib.request.HTTPRedirectHandler):
                def redirect_request(self, req, fp, code, msg, headers, newurl):
                    return None
            处理程序.append(不重定向())
        打开器 = build_opener(*处理程序) if 处理程序 else urllib.request.urlopen

        # SSL 验证
        ssl上下文 = None
        if SSL验证 is False:
            try:
                import ssl
                ssl上下文 = ssl._create_unverified_context()
            except Exception as 错误:
                降级记录表.append(str(错误))

        # 普通请求
        try:
            if 打开器 is urllib.request.urlopen:
                响应对象 = 打开器(请求, timeout=超时秒, context=ssl上下文)
            else:
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
            # 3xx（调用方关掉自动重定向时）必须把响应头原样带出：调用方要靠
            # Location 经本能力逐跳跟随，每一跳都重跑 SSRF 校验；不带出就等于
            # 逼调用方绕过本能力手工发请求，SSRF 防线形同虚设。
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

        打开器 = None
        代理处理 = None
        if 代理:
            from urllib.request import ProxyHandler, build_opener
            代理处理 = ProxyHandler({"http": 代理, "https": 代理})
            打开器 = build_opener(代理处理)

        ssl上下文 = None
        if SSL验证 is False:
            try:
                import ssl
                ssl上下文 = ssl._create_unverified_context()
            except Exception as 错误:
                降级记录表.append(str(错误))

        目标 = 打开器 if 打开器 else urllib.request.urlopen
        try:
            if 目标 is urllib.request.urlopen:
                响应对象 = 目标(请求, timeout=超时秒, context=ssl上下文)
            else:
                响应对象 = 目标.open(请求, timeout=超时秒)
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
