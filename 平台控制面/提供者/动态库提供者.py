"""动态库真实提供者：ctypes 真实加载系统动态库并调用最小接口。

中文契约：
- 调用(库名, 函数名, 参数表)：真实加载动态库、真实调用函数、返回真实值；
  库不存在或平台不支持时失败，错误码固定为 HOST_UNAVAILABLE，禁止伪造成功。
- 可用库列表()：真实探测已知系统库，返回库名、真实路径与可用状态。
- 宿主可用性()：探测当前宿主能否真实提供动态库调用；不可用状态为
  HOST_UNAVAILABLE。

未登记签名的函数拒绝调用（错误码"签名未登记"），绝不猜测签名导致崩溃。
只依赖 Python 标准库（ctypes）。
"""
from __future__ import annotations

import sys
from typing import Any

from 公共契约.基础类型.结果类型 import 结果

try:
    import ctypes
    import ctypes.util
except Exception:  # 平台缺少 ctypes：整体不可用，绝不伪造成功
    ctypes = None  # type: ignore[assignment]

宿主可用状态, 宿主不可用状态, 来源名称 = "可用", "HOST_UNAVAILABLE", "动态库提供者"

# find_library 找不到时的真实文件名候选
候选名表 = {
    "sqlite3": ["libsqlite3.dylib", "libsqlite3.so", "libsqlite3.so.0", "sqlite3.dll"],
    "c": ["libc.dylib", "libc.so.6", "libc.so", "msvcrt.dll"],
    "system": ["libSystem.dylib", "libSystem.B.dylib"],
}
已加载缓存: dict[str, Any] = {}

# 最小接口签名登记表：键=(逻辑库名, 函数名)，值=(参数类型表, 返回类型)。
# 未登记函数拒绝调用（"签名未登记"），避免猜测签名导致崩溃——不伪造成功。
签名表 = {
    ("sqlite3", "sqlite3_libversion"): ((), "字符串"),
    ("sqlite3", "sqlite3_libversion_number"): ((), "整数"),
    ("c", "strlen"): (("字符串",), "无符号整数"),
    ("c", "getpid"): ((), "整数"),
}

类型映射表 = {"字符串": ctypes.c_char_p if ctypes else None, "整数": ctypes.c_int if ctypes else None, "无符号整数": ctypes.c_size_t if ctypes else None, "浮点数": ctypes.c_double if ctypes else None}


def 归一化库名(库名: str) -> str:
    """libsqlite3.dylib/libc/System 等写法归一化为逻辑库名。"""
    名称 = 库名.strip().lower().removeprefix("lib")
    for 后缀 in (".dylib", ".so.0", ".so", ".dll"):
        if 名称.endswith(后缀):
            return 名称[: -len(后缀)]
    return 名称


def 查找库路径(库名: str) -> str | None:
    """真实查找库路径：find_library 优先，候选文件名逐个真实尝试。"""
    if ctypes is None:
        return None
    try:
        路径 = ctypes.util.find_library(库名)
        if 路径:
            return 路径
    except Exception:
        pass
    for 候选 in 候选名表.get(库名, []):
        try:
            已加载缓存.setdefault(库名, ctypes.CDLL(候选))
            return 候选
        except Exception:
            continue
    return None


def 加载库(库名: str) -> 结果:
    """真实加载动态库；加载失败返回 HOST_UNAVAILABLE（当前宿主不可用）。"""
    if ctypes is None:
        return 结果.失败(宿主不可用状态, "当前宿主不支持动态库调用（缺少 ctypes）", 来源=来源名称)
    if 库名 in 已加载缓存:
        return 结果.成功结果(已加载缓存[库名])
    路径 = 查找库路径(库名)
    if not 路径:
        return 结果.失败(宿主不可用状态, f"找不到动态库 {库名}（当前宿主不可用）", 来源=来源名称)
    try:
        库 = ctypes.CDLL(路径)
    except OSError as 错误:
        return 结果.失败(宿主不可用状态, f"加载动态库 {库名} 失败：{错误}", 来源=来源名称)
    已加载缓存[库名] = 库
    return 结果.成功结果(库)


def 转换参数(参数类型表: tuple, 参数表: list[Any]) -> 结果:
    """按登记签名把 Python 参数真实转换为 ctypes 实参。"""
    if len(参数表) != len(参数类型表):
        return 结果.失败("参数不匹配", f"函数需要 {len(参数类型表)} 个参数，实际传入 {len(参数表)} 个", 来源=来源名称)
    转换后: list[Any] = []
    for 类型, 值 in zip(参数类型表, 参数表):
        类型对象 = 类型映射表.get(类型)
        if 类型对象 is None:
            return 结果.失败("签名未登记", f"未知参数类型 {类型}", 来源=来源名称)
        if 类型 == "字符串" and not isinstance(值, (bytes, bytearray)):
            if not isinstance(值, str):
                return 结果.失败("参数不匹配", f"参数 {值!r} 不是文本或字节串", 来源=来源名称)
            值 = 值.encode("utf-8")
        elif 类型 == "整数" and (not isinstance(值, int) or isinstance(值, bool)):
            return 结果.失败("参数不匹配", f"参数 {值!r} 不是整数", 来源=来源名称)
        转换后.append(类型对象(值))
    return 结果.成功结果(转换后)


def 调用(库名: str, 函数名: str, 参数表: list[Any] | tuple = ()) -> 结果:
    """真实加载动态库并真实调用函数；失败绝不伪装成功。"""
    逻辑库名 = 归一化库名(库名)
    加载结果 = 加载库(逻辑库名)
    if not 加载结果.成功:
        return 加载结果  # 库不存在/加载失败 → HOST_UNAVAILABLE
    签名 = 签名表.get((逻辑库名, 函数名))
    if 签名 is None:
        return 结果.失败("签名未登记", f"函数 {函数名} 未登记签名，拒绝猜测调用", 来源=来源名称)
    参数类型表, 返回类型名 = 签名
    参数转换结果 = 转换参数(参数类型表, list(参数表))
    if not 参数转换结果.成功:
        return 参数转换结果
    try:
        函数 = getattr(加载结果.值, 函数名)
        函数.argtypes = [类型映射表[类型] for 类型 in 参数类型表]
        函数.restype = 类型映射表[返回类型名]
        原始值 = 函数(*参数转换结果.值)
    except AttributeError:
        return 结果.失败("函数不存在", f"动态库 {逻辑库名} 中不存在函数 {函数名}", 来源=来源名称)
    except OSError as 错误:
        return 结果.失败("调用失败", f"调用 {函数名} 失败：{错误}", 来源=来源名称)
    值 = 原始值
    if 返回类型名 == "字符串" and 值 is not None:
        值 = 值.decode("utf-8", errors="replace") if isinstance(值, bytes) else str(值)
    elif 返回类型名 in ("整数", "无符号整数") and 值 is not None:
        值 = int(值)
    return 结果.成功结果(值)


def 可用库列表() -> list[dict[str, Any]]:
    """真实探测已知系统库：返回库名、真实路径与可用状态。"""
    结果表: list[dict[str, Any]] = []
    for 逻辑库名 in ("sqlite3", "c", "system"):
        路径 = 查找库路径(逻辑库名)
        加载结果 = 加载库(逻辑库名) if 路径 else 结果.失败(宿主不可用状态, f"找不到动态库 {逻辑库名}", 来源=来源名称)
        可用 = 加载结果.成功
        结果表.append({"库名": 逻辑库名, "路径": 路径 or "",
                       "状态": 宿主可用状态 if 可用 else 宿主不可用状态,
                       "说明": "" if 可用 else 加载结果.错误说明})
    return 结果表


def 宿主可用性() -> dict[str, Any]:
    """探测当前宿主能否真实提供动态库调用；不可用状态为 HOST_UNAVAILABLE。"""
    探测 = 加载库("sqlite3")
    可用 = 探测.成功
    return {"可用": 可用, "状态": 宿主可用状态 if 可用 else 宿主不可用状态, "平台": sys.platform, "说明": "" if 可用 else 探测.错误说明}
