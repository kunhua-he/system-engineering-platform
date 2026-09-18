"""独立任务工作器：在子进程中执行一个能力并返回 JSON 结果。"""

from __future__ import annotations

import base64
import inspect
import json
import sys
from collections.abc import Callable
from multiprocessing.connection import Connection
from pathlib import Path
from typing import Any

# 说明：`公共契约` 一律**函数内延迟导入**——本模块既作子进程入口，也作独立脚本
# （`python 任务工作器.py <系统根>`）启动，后者在模块导入之后才把系统根塞进
# `sys.path`；模块级导入公共契约会让独立脚本模式直接 ImportError。

#: 跨边界编码的模式名（同一件事两种语义 → 同一份实现 + 模式变量，与网关入站/出站对应）
模式_入站 = "入站"
模式_出站 = "出站"


def _冻结字节集(值: Any) -> Any:
    """`json.dumps` 的 default 钩子：字节集编码成网关约定的冻结表示。

    与 HTTP 出站（`本地网关._写JSON` / `HTTP连接器._编码JSON值`）**同口径**：
    `{"类型": "字节集型", "base64": ...}`，对端按 `解码冻结值` 还原成 bytes。
    旧实现既不包装 bytes（`TypeError: Object of type bytes is not JSON
    serializable` → 异步任务链直接「内部错误」），也放行 NaN/Infinity（写出非法
    JSON，父进程读不出来只能判「崩溃」）—— 与 HTTP 边界的严格口径两套强度。
    """
    if isinstance(值, (bytes, bytearray, memoryview)):
        return {"类型": "字节集型", "base64": base64.b64encode(bytes(值)).decode("ascii")}
    raise TypeError(f"任务边界不支持的类型: {type(值).__name__}")


def _严格文本(值: Any) -> str:
    """跨进程边界的唯一严格 JSON 编码：拒 NaN/Infinity，字节集走冻结值包装。"""
    return json.dumps(值, ensure_ascii=False, allow_nan=False, default=_冻结字节集)


def _统一值(值: Any, *, 模式: str = 模式_出站) -> Any:
    """过一遍严格 JSON 编码，得到跨进程可传输的值（不可表达的对象在这里当场拒绝）。

    与 HTTP 边界逐字同口径（同一件事两种语义 = 同一份实现 + 模式变量）：
    - `入站`：还原冻结字节集为 `bytes`（能力收到真实二进制，与网关入站一致）；
    - `出站`：保留冻结表示（对端按同一套解码还原，与网关出站一致）。
    """
    if 模式 not in (模式_入站, 模式_出站):
        raise ValueError(f"未知模式: {模式}")
    数据 = json.loads(_严格文本(值))
    if 模式 == 模式_入站:
        from 公共契约.运行时.JSON解码 import 解码冻结值

        return 解码冻结值(数据, 模式="严格")
    return 数据


def _是失败信封(结果: Any) -> bool:
    """失败信封判据（唯一）—— **关键字标记**，不是「第二项是不是布尔」这种形状猜。

    三条同时成立才算失败信封：
    1. 结果是二元组（`任务接入._构造执行器` 的失败返回形态）；
    2. 第二项是**同一个 `假` 单例**（不是「任意布尔值」）；
    3. 首项是同时带 `错误码` 与 `错误说明` 两键的字典（错误结构的关键字标记）。

    旧实现只判 `len(结果) == 2 and isinstance(结果[1], bool)`：业务恰好返回二元组
    `(值, 真)` 会被当成信封拆开 —— 业务数据凭空少一半。现在只有**显式错误结构**
    才认信封，其余一切返回值一律按成功值原样下发。
    """
    from 公共契约.基础类型.逻辑类型 import 假

    if not isinstance(结果, tuple) or len(结果) != 2:
        return 假
    if 结果[1] is not 假:
        return 假
    首项 = 结果[0]
    return isinstance(首项, dict) and "错误码" in 首项 and "错误说明" in 首项


def _规整结果(结果: Any) -> tuple[Any, bool, str, str]:
    """把执行器返回值规整成 `(值, 成功, 错误码, 错误说明)`（唯一判据点）。"""
    from 公共契约.基础类型.逻辑类型 import 假, 真

    if _是失败信封(结果):
        错误 = 结果[0]
        return (错误, 假, str(错误.get("错误码") or "内部错误"),
                str(错误.get("错误说明") or "任务执行失败"))
    return 结果, 真, "", ""


def _调用能力(函数: Callable, 参数: dict[str, Any], 取消事件: Any) -> Any:
    """兼容单参数能力和接收取消事件的双参数能力。"""
    try:
        参数数量 = len(inspect.signature(函数).parameters)
    except (TypeError, ValueError):
        参数数量 = 1
    if 参数数量 >= 2:
        return 函数(参数, 取消事件)
    return 函数(参数)


def _组装响应(任务id: str, 返回: Any) -> dict[str, Any]:
    """按唯一口径把执行器返回值组装成响应信封（成功/失败走同一处判据）。"""
    值, 成功, 错误码, 错误说明 = _规整结果(返回)
    响应: dict[str, Any] = {"任务id": 任务id, "成功": 成功, "值": _统一值(值)}
    if not 成功:
        # 失败结果把能力自身的错误码/说明原样带回，父进程不再一律显示「内部错误」。
        响应["错误码"] = 错误码
        响应["错误说明"] = 错误说明
    return 响应


def 执行单次任务(
    发送连接: Connection,
    函数: Callable,
    请求: dict[str, Any],
    取消事件: Any,
) -> None:
    """子进程入口；连接中只发送 UTF-8 JSON 字节。"""
    from 公共契约.基础类型.逻辑类型 import 真, 假

    try:
        请求 = _统一值(请求, 模式=模式_入站)
        if 取消事件.is_set():
            响应 = {"任务id": 请求.get("任务id", ""), "取消": 真}
        else:
            try:
                响应 = _组装响应(
                    请求.get("任务id", ""),
                    _调用能力(函数, 请求.get("参数") or {}, 取消事件))
            except Exception as 错误:  # noqa: BLE001 - 能力异常必须转成协议错误
                响应 = {
                    "任务id": 请求.get("任务id", ""),
                    "成功": 假,
                    "错误码": "内部错误",
                    "错误说明": str(错误),
                }
    except Exception as 错误:  # noqa: BLE001 - 子进程边界必须把异常转换为协议错误
        响应 = {
            "任务id": 请求.get("任务id", "") if isinstance(请求, dict) else "",
            "成功": 假,
            "错误码": "内部错误",
            "错误说明": str(错误),
        }
    try:
        发送连接.send_bytes(json.dumps(响应, ensure_ascii=False).encode("utf-8"))
    finally:
        发送连接.close()


# 保留独立脚本协议，供外部提供者直接启动工作器时使用。
能力实现表: dict[str, Callable] = {}


def 注册能力(能力id: str, 函数: Callable) -> None:
    能力实现表[能力id] = 函数


def 主循环() -> int:
    from 公共契约.基础类型.逻辑类型 import 假

    print("READY", flush=True)
    for 行 in sys.stdin:
        try:
            请求 = json.loads(行)
        except json.JSONDecodeError:
            continue
        if 请求.get("类型") == "停止":
            break
        函数 = 能力实现表.get(请求.get("能力id", ""))
        if 函数 is None:
            响应 = {
                "任务id": 请求.get("任务id", ""),
                "成功": 假,
                "错误码": "能力不存在",
                "错误说明": f"任务能力未注册: {请求.get('能力id', '')}",
            }
        else:
            try:
                # 与子进程入口走**同一处判据与编码**（旧实现这里不认失败信封、
                # 也不包装字节集，同一件事两套口径）。
                响应 = _组装响应(
                    请求.get("任务id", ""),
                    _调用能力(函数, 请求.get("参数") or {}, _空取消事件()))
            except Exception as 错误:  # noqa: BLE001 - 独立脚本边界必须返回结构化失败
                响应 = {"任务id": 请求.get("任务id", ""), "成功": 假,
                          "错误码": "内部错误", "错误说明": str(错误)}
        print(json.dumps(响应, ensure_ascii=False), flush=True)
    return 0


class _空取消事件:
    def is_set(self) -> bool:
        from 公共契约.基础类型.逻辑类型 import 假

        return 假


if __name__ == "__main__":
    if len(sys.argv) > 1:
        系统根 = Path(sys.argv[1])
        if str(系统根) not in sys.path:
            sys.path.insert(0, str(系统根))
    raise SystemExit(主循环())
