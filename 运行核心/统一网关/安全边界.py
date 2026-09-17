"""网关安全边界：本地访问凭证引用、请求限制、路径校验与脱敏。

凭证不写入代码/说明书/日志；凭证通过环境变量或受控配置引用；缺失
凭证明确失败；凭证错误明确失败；不允许模块读取全部环境变量。
"""

from __future__ import annotations

import hmac
import ipaddress
import os
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import unquote, urlsplit

from 运行核心.运行诊断.运行事件.脱敏工具 import 脱敏文本, 脱敏值
from 公共契约.基础类型.逻辑类型 import 真, 假


@dataclass
class 安全配置:
    """网关安全配置。"""

    凭证环境变量: str = "系统库网关凭证"
    请求大小上限: int = 1024 * 1024  # 1MB
    监听地址: str = "127.0.0.1"  # 默认只监听本机
    允许路径表: set[str] = field(default_factory=lambda: {"/健康", "/网关/调用", "/网关/流式", "/能力/搜索", "/能力/目录", "/能力/契约"})
    要求凭证: bool = 真
    默认权限范围: set[str] = field(default_factory=lambda: {"查询", "调用", "任务"})
    # 浏览器跨域来源必须显式配置；空集合表示不允许跨域调用。
    允许来源表: set[str] = field(default_factory=set)
    # 关闭证书验证只能由生产装配显式放行，且目标仍必须是本机回环。
    允许本地不验证SSL: bool = 假


class 凭证管理器:
    """本地访问凭证引用机制：环境变量引用，不在代码/日志留明文。"""

    def __init__(self, 环境变量名: str = "系统库网关凭证") -> None:
        self.环境变量名 = 环境变量名
        self._内存凭证 = ""
        self.已加载 = 假

    def 加载(self) -> tuple[bool, str]:
        """从环境变量加载凭证；缺失明确失败。"""
        值 = os.environ.get(self.环境变量名, "")
        if not 值:
            return 假, f"缺失凭证: 环境变量 {self.环境变量名} 未设置"
        self._内存凭证 = 值
        self.已加载 = 真
        return 真, "凭证已加载（仅存内存）"

    def 校验(self, 提供凭证: str) -> tuple[bool, str]:
        """校验凭证；错误明确失败；不泄露细节。"""
        if not self.已加载:
            return 假, "凭证未加载（缺失环境变量）"
        if not 提供凭证:
            return 假, "缺少访问凭证"
        if hmac.compare_digest(self._内存凭证.encode("utf-8"), 提供凭证.encode("utf-8")):
            return 真, "凭证校验通过"
        return 假, "凭证错误"

    def 清除(self) -> None:
        self._内存凭证 = ""
        self.已加载 = 假

    def 读取环境变量白名单(self, 允许变量表: set[str]) -> dict[str, str]:
        """受限读取环境变量：不允许任意模块读取全部环境变量。"""
        return {名称: os.environ.get(名称, "") for 名称 in 允许变量表
                if os.environ.get(名称, "")}


class 请求限制器:
    """请求大小限制与路径校验。"""

    def __init__(self, 配置: 安全配置 | None = None) -> None:
        self.配置 = 配置 or 安全配置()

    def 校验大小(self, 长度: int) -> tuple[bool, str]:
        if 长度 < 0:
            return 假, "请求长度不合法"
        if 长度 > self.配置.请求大小上限:
            return 假, f"请求超过大小上限 {self.配置.请求大小上限} 字节"
        return 真, ""

    def 校验路径(self, 路径: str) -> tuple[bool, str]:
        try:
            规范路径 = unquote(urlsplit(路径).path)
        except ValueError:
            return 假, "请求路径不合法"
        if "\x00" in 规范路径 or any(段 in (".", "..") for 段 in 规范路径.split("/")):
            return 假, "请求路径不合法"
        if 规范路径 not in self.配置.允许路径表 and not 规范路径.startswith("/平台/能力反馈/") and not 规范路径.startswith("/能力/契约/"):
            return 假, "请求路径未授权"
        return 真, ""

    def 校验监听地址(self, 地址: str) -> tuple[bool, str]:
        """当前服务器实现固定 IPv4；禁止配置无法被实际绑定的 IPv6 地址。"""
        if 地址 in {"localhost", "127.0.0.1"}:
            return 真, ""
        try:
            ip = ipaddress.ip_address(地址)
        except ValueError:
            return 假, "监听地址不合法或不是本机回环地址"
        if ip.version != 4 or not ip.is_loopback:
            return 假, "网关当前只允许监听 IPv4 本机回环地址"
        return 真, ""

    def 校验内容类型(self, 内容类型: str, 长度: int) -> tuple[bool, str]:
        if 长度 > 0 and "application/json" not in (内容类型 or "").lower():
            return 假, "请求正文必须使用 JSON"
        return 真, ""

    def 校验SSL策略(self, 参数: dict[str, Any]) -> tuple[bool, str]:
        """SSL验证=False 只允许显式策略放行的 HTTPS 回环目标。"""
        if not isinstance(参数, dict) or 参数.get("SSL验证") is not 假:
            return 真, ""
        if not self.配置.允许本地不验证SSL:
            return 假, "关闭 SSL 验证未获本地受控策略授权"
        if 参数.get("允许回环") is not 真:
            return 假, "关闭 SSL 验证必须同时显式允许回环"
        地址 = 参数.get("地址")
        if not isinstance(地址, str):
            return 假, "关闭 SSL 验证必须提供 HTTPS 回环地址"
        try:
            解析 = urlsplit(地址)
            主机 = 解析.hostname or ""
            if 解析.scheme.lower() != "https":
                return 假, "关闭 SSL 验证只允许 HTTPS 回环地址"
            if 主机.lower() == "localhost":
                return 真, ""
            if ipaddress.ip_address(主机).is_loopback:
                return 真, ""
        except ValueError:
            pass
        return 假, "关闭 SSL 验证只允许明确的本机回环目标"


def 脱敏错误信息(文本: str) -> str:
    """错误信息脱敏：密钥片段替换为 已脱敏（不可逆）。"""
    return 脱敏文本(文本)


def 脱敏参数(参数: dict[str, Any], 敏感键表: set[str]) -> dict[str, Any]:
    """敏感参数不可逆脱敏：值替换为 已脱敏，无法还原。"""
    return {键: ("已脱敏" if 键 in 敏感键表 else 脱敏值(值, 键))
            for 键, 值 in (参数 or {}).items()}


def 提取访问凭证(请求头: Any) -> str:
    """只从受支持的请求头提取凭证，不接受查询参数中的凭证。"""
    授权头 = str(请求头.get("Authorization", ""))
    if 授权头.startswith("Bearer "):
        return 授权头[7:].strip()
    return str(
        请求头.get("X-System-Credential", "")
        or 请求头.get("X-系统凭证", "")
    ).strip()
