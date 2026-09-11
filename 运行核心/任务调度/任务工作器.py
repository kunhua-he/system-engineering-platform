"""独立任务工作器：在子进程中执行一个能力并返回 JSON 结果。"""

from __future__ import annotations

import inspect
import json
import sys
from collections.abc import Callable
from multiprocessing.connection import Connection
from pathlib import Path
from typing import Any


def _统一值(值: Any) -> Any:
    """用 JSON 往返拒绝跨进程泄漏任意 Python 对象。"""
    return json.loads(json.dumps(值, ensure_ascii=False))


def _调用能力(函数: Callable, 参数: dict[str, Any], 取消事件: Any) -> Any:
    """兼容单参数能力和接收取消事件的双参数能力。"""
    try:
        参数数量 = len(inspect.signature(函数).parameters)
    except (TypeError, ValueError):
        参数数量 = 1
    if 参数数量 >= 2:
        return 函数(参数, 取消事件)
    return 函数(参数)


def 执行单次任务(
    发送连接: Connection,
    函数: Callable,
    请求: dict[str, Any],
    取消事件: Any,
) -> None:
    """子进程入口；连接中只发送 UTF-8 JSON 字节。"""
    try:
        请求 = _统一值(请求)
        if 取消事件.is_set():
            响应 = {"任务id": 请求.get("任务id", ""), "取消": True}
        else:
            结果 = _调用能力(函数, 请求.get("参数") or {}, 取消事件)
            if isinstance(结果, tuple) and len(结果) == 2 and isinstance(结果[1], bool):
                值, 成功 = 结果
            else:
                值, 成功 = 结果, True
            响应 = {
                "任务id": 请求.get("任务id", ""),
                "成功": 成功,
                "值": _统一值(值),
            }
            if not 成功 and isinstance(值, dict):
                # 失败结果允许把能力自身的错误码/说明一并带回，父进程不再
                # 一律显示「内部错误」；缺字段时退回原语义。
                响应["错误码"] = str(值.get("错误码") or "内部错误")
                响应["错误说明"] = str(值.get("错误说明") or "任务执行失败")
    except Exception as 错误:  # noqa: BLE001 - 子进程边界必须把能力异常转换为协议错误
        响应 = {
            "任务id": 请求.get("任务id", "") if isinstance(请求, dict) else "",
            "成功": False,
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
                "成功": False,
                "错误码": "能力不存在",
                "错误说明": f"任务能力未注册: {请求.get('能力id', '')}",
            }
        else:
            try:
                值 = _调用能力(函数, 请求.get("参数") or {}, _空取消事件())
                响应 = {"任务id": 请求.get("任务id", ""), "成功": True, "值": _统一值(值)}
            except Exception as 错误:  # noqa: BLE001 - 独立脚本边界必须返回结构化失败
                响应 = {"任务id": 请求.get("任务id", ""), "成功": False,
                          "错误码": "内部错误", "错误说明": str(错误)}
        print(json.dumps(响应, ensure_ascii=False), flush=True)
    return 0


class _空取消事件:
    def is_set(self) -> bool:
        return False


if __name__ == "__main__":
    if len(sys.argv) > 1:
        系统根 = Path(sys.argv[1])
        if str(系统根) not in sys.path:
            sys.path.insert(0, str(系统根))
    raise SystemExit(主循环())
