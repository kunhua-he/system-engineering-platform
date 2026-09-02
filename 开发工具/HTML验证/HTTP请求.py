"""回环 HTTP 请求与错误归一化。"""
from __future__ import annotations
import ipaddress, json, time, urllib.error, urllib.parse, urllib.request
from typing import Any
from 开发工具.HTML验证.常量 import 请求上限字节
from 开发工具.HTML验证.单步场景 import 验证场景
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

def _发送请求(地址: str, 场景: 验证场景, 超时秒: float) -> tuple[int, dict[str, Any], float]:
    开始 = time.monotonic()
    拆分 = urllib.parse.urlsplit(地址)
    基址 = f"{拆分.scheme}://{拆分.netloc}"
    路径 = 场景.路径 if 场景.路径.startswith("/") else "/" + 场景.路径
    目标 = 基址 + urllib.parse.quote(路径, safe="/:@._-")
    if 场景.方法 == "GET":
        请求 = urllib.request.Request(目标, method="GET")
    else:
        请求体 = {"能力id": 场景.能力id, "参数": 场景.参数}
        请求 = urllib.request.Request(
            目标,
            data=json.dumps(请求体, ensure_ascii=False).encode("utf-8"),
            method="POST",
            headers={"Content-Type": "application/json"},
        )
    try:
        with urllib.request.urlopen(请求, timeout=超时秒) as 响应:
            正文 = 响应.read(请求上限字节 + 1)
            if len(正文) > 请求上限字节:
                return 响应.status, {"成功": False, "错误码": "返回过大", "错误说明": "响应超过读取上限"}, (time.monotonic() - 开始) * 1000
            try:
                数据 = json.loads(正文.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                数据 = {"成功": False, "错误码": "返回非JSON", "错误说明": 正文[:200].decode("utf-8", errors="replace")}
            return 响应.status, 数据, (time.monotonic() - 开始) * 1000
    except urllib.error.HTTPError as 错误:
        try:
            正文 = 错误.read(请求上限字节 + 1)
            try:
                数据 = json.loads(正文[:请求上限字节].decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                数据 = {"成功": False, "错误码": "返回非JSON", "错误说明": 正文[:200].decode("utf-8", errors="replace")}
            return 错误.code, 数据, (time.monotonic() - 开始) * 1000
        finally:
            错误.close()
    except (urllib.error.URLError, TimeoutError, OSError) as 错误:
        return 502, {"成功": False, "错误码": "网关断开", "错误说明": str(错误)}, (time.monotonic() - 开始) * 1000
