"""环境变量原子能力实现（不对外暴露，只经包级中文入口调用）。

职责：环境变量读/写/删/列（参考易语言系统核心支持库）。
纯标准库 os.environ，不做业务逻辑。

安全口径（默认脱敏，落点清单_07 S-03）：
列/读类能力默认无差别回显进程环境与 .env 明文，会构成「凭证自举」——
拿网关凭证调一次能力即可把网关凭证/任意密钥原文取回来。本实现按
**敏感键关键词白名单 + 默认掩码**收口：键名（忽略大小写）命中
`敏感键关键词表` 时，值以 `默认掩码`（`***`）回显；需明文时由调用方
显式传 包含敏感值=True（可选参数，缺省 False，向后兼容）。
脱敏只作用于**回显**，`读取环境文件(写入进程=True)` 写入 os.environ 的
仍是真实值。
"""

from __future__ import annotations

import os

from 公共契约.基础类型.结果类型 import 结果

# 敏感键关键词表：键名（忽略大小写，含子串即命中）命中任一项即视为敏感。
# 覆盖英文通用命名与中文凭据命名——含平台自有的「系统库网关凭证」这类
# 非英文命名键；口径为「失败安全」：宁可多掩码，不漏码。
敏感键关键词表 = (
    "KEY", "TOKEN", "SECRET", "PASSWORD", "PASSWD", "PWD", "CREDENTIAL", "AUTH",
    "凭据", "凭证", "密钥", "私钥", "口令", "密码",
)

# 敏感值默认掩码（与 支持库.适配层.密钥提供者.掩码 同口径）。
默认掩码 = "***"


def 是敏感键(名称: str) -> bool:
    """键名是否为敏感键（忽略大小写，含子串即命中）。

    纯函数、无副作用；供回显脱敏与外部只读判断共用。
    """
    文本 = str(名称 or "").upper()
    return any(关键词 in 文本 for 关键词 in 敏感键关键词表)


def _回显值(名称: str, 值, 包含敏感值: bool):
    """按脱敏口径决定回显值。

    非敏感键、或调用方显式索取明文（包含敏感值=True）时原样返回；否则
    敏感键的值掩码为 `默认掩码`。空值原样返回空串（无敏感内容可泄露，
    也避免把「空」误显示成「有值」）。
    """
    if 包含敏感值 or not 是敏感键(名称):
        return 值
    return 默认掩码 if 值 else 值


def _校验包含敏感值(包含敏感值) -> 结果 | None:
    """校验脱敏开关类型（逻辑型）；合法返回 None，不合法返回失败结果。"""
    if not isinstance(包含敏感值, bool):
        return 结果.失败("参数不合法", "包含敏感值必须是逻辑型（True/False）", 来源="环境变量")
    return None


def 获取环境变量(名称: str = None, 包含敏感值: bool = False) -> 结果:
    """获取环境变量。返回 {名称, 值, 存在}。

    敏感键（见 `是敏感键`）的值默认以 `***` 回显；需明文时显式传
    包含敏感值=True。命中脱敏时 值 恒为 `***`（不回显长度/前缀）。
    """
    if not isinstance(名称, str) or not 名称.strip():
        return 结果.失败("参数不合法", "名称必须是非空字符串", 来源="环境变量")
    类型问题 = _校验包含敏感值(包含敏感值)
    if 类型问题 is not None:
        return 类型问题
    名称 = 名称.strip()
    if 名称 not in os.environ:
        return 结果.成功结果({"名称": 名称, "值": None, "存在": False})
    return 结果.成功结果(
        {"名称": 名称, "值": _回显值(名称, os.environ[名称], 包含敏感值), "存在": True}
    )


def 设置环境变量(名称: str = None, 值: str = None) -> 结果:
    """设置环境变量（进程内）。返回 {名称, 值}。"""
    if not isinstance(名称, str) or not 名称.strip():
        return 结果.失败("参数不合法", "名称必须是非空字符串", 来源="环境变量")
    if 值 is None:
        return 结果.失败("参数不合法", "值不能为空", 来源="环境变量")
    名称 = 名称.strip()
    os.environ[名称] = str(值)
    return 结果.成功结果({"名称": 名称, "值": str(值), "说明": "仅对当前进程生效"})


def 删除环境变量(名称: str = None) -> 结果:
    """删除环境变量。返回 {名称, 已删除}。"""
    if not isinstance(名称, str) or not 名称.strip():
        return 结果.失败("参数不合法", "名称必须是非空字符串", 来源="环境变量")
    名称 = 名称.strip()
    已删除 = 名称 in os.environ
    if 已删除:
        os.environ.pop(名称, None)
    return 结果.成功结果({"名称": 名称, "已删除": 已删除})


def 列出环境变量(前缀: str = None, 包含敏感值: bool = False) -> 结果:
    """列出环境变量（可过滤前缀）。返回 {数量, 变量列表}。

    敏感键的**键名照常列出**，值默认以 `***` 回显；需明文时显式传
    包含敏感值=True。数量为实际条目数（不因脱敏变化）。
    """
    类型问题 = _校验包含敏感值(包含敏感值)
    if 类型问题 is not None:
        return 类型问题
    前缀 = (前缀 or "").strip()
    变量列表 = [{"名称": 键, "值": _回显值(键, 值, 包含敏感值)}
               for 键, 值 in os.environ.items()
               if not 前缀 or 键.startswith(前缀)]
    return 结果.成功结果({"数量": len(变量列表), "变量列表": 变量列表})

def 读取环境文件(文件路径: str = None, 写入进程: bool = False, 覆盖已存在: bool = False,
                包含敏感值: bool = False) -> 结果:
    """读取 .env 文件为键值字典。

    解析规则（与主流 .env 约定一致）：
    - 跳过空行与以 # 开头的注释行；
    - 含 "=" 才作为一条记录，仅按第一个 "=" 切分；
    - 键与值均去首尾空白；值剥离成对的首尾引号（单引号或双引号）。

    写入进程=True 时把结果写入 os.environ（仅当前进程）。
    覆盖已存在=False 时，已存在的进程环境变量不被覆盖。
    文件不存在不算失败：返回 文件存在=False 与空字典。

    安全口径：返回的 环境 里，敏感键的值默认以 `***` 回显；需明文时显式传
    包含敏感值=True。脱敏只作用于回显——写入进程 落进 os.environ 的始终是
    文件里的真实值（否则加载 .env 就失效了）。
    """
    from pathlib import Path as _Path

    if not isinstance(文件路径, str) or not 文件路径.strip():
        return 结果.失败("参数不合法", "文件路径必须是非空字符串", 来源="环境变量")
    类型问题 = _校验包含敏感值(包含敏感值)
    if 类型问题 is not None:
        return 类型问题
    路径 = _Path(文件路径.strip())
    if not 路径.is_file():
        return 结果.成功结果({"文件存在": False, "条数": 0, "环境": {}})

    环境: dict[str, str] = {}
    try:
        文本 = 路径.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as 错误:
        return 结果.失败("读取失败", f"无法读取环境文件: {错误}", 来源="环境变量")

    for 原始行 in 文本.splitlines():
        行 = 原始行.strip()
        if not 行 or 行.startswith("#") or "=" not in 行:
            continue
        键, 值 = 行.split("=", 1)
        键 = 键.strip()
        if not 键:
            continue
        环境[键] = 值.strip().strip('"').strip("'")

    if 写入进程:
        for 键, 值 in 环境.items():
            if 覆盖已存在 or 键 not in os.environ:
                os.environ[键] = 值

    回显环境 = {键: _回显值(键, 值, 包含敏感值) for 键, 值 in 环境.items()}
    return 结果.成功结果({"文件存在": True, "条数": len(环境), "环境": 回显环境})
