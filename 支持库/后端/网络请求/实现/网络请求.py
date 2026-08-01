"""网络请求原子能力实现：HTTP 客户端（外部协议边界，仅标准库）。

安全约束：
- SSRF 防护：仅允许 http/https；默认拒绝 回环/内网/私有地址/文件等非公网目标；
  项目策略可显式允许回环（allow_loopback）用于本机测试。
- 响应大小上限：max_bytes 超限即中止，防止无界读入。
- 凭证安全：不记录请求头中的敏感字段到错误信息。
- 超时：connect/read 统一超时。
"""

from __future__ import annotations

import ipaddress
import json
import socket
import urllib.parse
import urllib.request
from typing import Any
from urllib.error import HTTPError, URLError

from 公共契约.基础类型.结果类型 import 结果

敏感头集合 = {"authorization", "x-api-key", "api-key", "cookie", "proxy-authorization"}
默认超时秒 = 10
默认最大字节数 = 5 * 1024 * 1024


def _成功(值: Any = None) -> 结果:
    return 结果.成功结果(值)


def _失败(错误码: str, 消息: str) -> 结果:
    return 结果.失败(错误码, 消息, 来源="网络请求")


def _解析地址(地址: str) -> urllib.parse.SplitResult:
    try:
        return urllib.parse.urlsplit(地址)
    except ValueError as 错误:
        raise ValueError(f"地址解析失败: {错误}") from 错误


def _校验协议与SSRF(地址: str, 允许回环: bool) -> None:
    """协议白名单 + SSRF 防护（拒绝回环/内网/私有/保留地址）。"""
    解析 = _解析地址(地址)
    if 解析.scheme not in ("http", "https"):
        raise ValueError(f"仅允许 http/https 协议: {解析.scheme}")
    try:
        主机 = 解析.hostname
        if not 主机:
            raise ValueError("地址缺少主机名")
        地址对象 = ipaddress.ip_address(主机)
    except ValueError:
        # 非 IP 主机名：解析后按 IP 判定（DNS rebinding 防护需在调用方配合）
        try:
            地址对象 = ipaddress.ip_address(socket.gethostbyname(主机))
        except OSError as 错误:
            raise ValueError(f"主机名解析失败: {错误}") from 错误
    if 地址对象.is_loopback:
        if not 允许回环:
            raise ValueError("SSRF防护: 禁止访问回环地址")
        return
    if 地址对象.is_private or 地址对象.is_link_local or 地址对象.is_reserved \
            or 地址对象.is_multicast:
        raise ValueError(f"SSRF防护: 禁止访问内网/保留地址: {地址对象}")


def 编码中文地址(地址: str) -> str:
    """把地址中非 ASCII 的路径与查询部分按 HTTP 协议编码（外部协议边界）。"""
    解析 = _解析地址(地址)
    编码路径 = urllib.parse.quote(解析.path, safe="/%:@!$&'()*+,;=-._~")
    编码查询 = urllib.parse.quote(解析.query, safe="=&%+,;?/:-._~!$'()*@")
    return urllib.parse.urlunsplit(
        (解析.scheme, 解析.netloc, 编码路径, 编码查询, 解析.fragment))


def 构建查询串(参数: dict) -> 结果:
    """把参数映射编码为 URL 查询串，空映射返回空串。"""
    if not isinstance(参数, dict):
        return _失败("参数不合法", "参数必须是映射")
    if not 参数:
        return _成功("")
    return _成功(urllib.parse.urlencode(参数))


def 发送请求(*, 地址: str, 方法: str = "GET", 请求参数: dict | None = None,
             超时秒: float = 默认超时秒, 最大字节数: int = 默认最大字节数,
             允许回环: bool = False, 取消标记: Any = None) -> 结果:
    """发送 HTTP 请求；返回统一结果（值=状态码/响应头/响应文本/错误信息）。"""
    try:
        if not isinstance(地址, str) or 地址.strip() == "":
            return _失败("参数不合法", "地址为空")
        地址 = 编码中文地址(地址)
        _校验协议与SSRF(地址, 允许回环)
        if 请求参数 is None:
            请求参数 = {}
        if not isinstance(请求参数, dict):
            return _失败("参数不合法", "请求参数必须是映射")
        if not isinstance(超时秒, (int, float)) or 超时秒 <= 0:
            return _失败("参数不合法", "超时秒必须是正数")
        if not isinstance(最大字节数, int) or 最大字节数 <= 0:
            return _失败("参数不合法", "最大字节数必须是正整数")
        方法 = str(方法 or "GET").upper()
        if 方法 not in ("GET", "POST"):
            return _失败("参数不合法", f"方法仅支持 GET 或 POST: {方法}")
        请求头 = dict(请求参数.get("请求头") or {})
        if not isinstance(请求头, dict):
            return _失败("参数不合法", "请求头必须是映射")
        数据 = 请求参数.get("数据")
        请求体 = None
        if 方法 == "POST" and 数据 is not None:
            try:
                请求体 = json.dumps(数据, ensure_ascii=False).encode("utf-8")
            except (TypeError, ValueError) as 错误:
                return _失败("参数不合法", f"请求数据无法序列化: {错误}")
            请求头.setdefault("Content-Type", "application/json")
        if 取消标记 is not None and getattr(取消标记, "是否取消", lambda: False)():
            return _失败("请求已取消", "请求被取消")
        try:
            请求 = urllib.request.Request(地址, data=请求体, headers=请求头, method=方法)
        except (TypeError, ValueError) as 错误:
            return _失败("参数不合法", f"请求构造失败: {错误}")
        with urllib.request.urlopen(请求, timeout=超时秒) as 响应:
            状态码 = 响应.getcode()
            响应头 = {键: 值 for 键, 值 in 响应.headers.items()}
            响应字节 = 响应.read(最大字节数 + 1)
            if len(响应字节) > 最大字节数:
                return _失败("响应超限", f"响应超过上限 {最大字节数} 字节")
            响应文本 = 响应字节.decode("utf-8", errors="replace")
        return _成功({"状态码": 状态码, "响应头": 响应头,
                      "响应文本": 响应文本, "错误信息": ""})
    except HTTPError as 错误:
        return _成功({"状态码": 错误.code, "响应头": {}, "响应文本": "",
                      "错误信息": f"网络失败: {错误.reason}"})
    except TimeoutError:
        return _失败("网络超时", "网络请求超时")
    except URLError as 错误:
        return _失败("网络失败", f"网络请求失败: {错误.reason}")
    except OSError as 错误:
        return _失败("网络失败", f"网络请求失败: {错误}")
    except ValueError as 错误:
        return _失败("参数不合法", str(错误))
