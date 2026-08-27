"""子进程入口：mlx-whisper 独立子进程 Worker。

只在独立子进程中运行，由 实现/提供者.py 通过 subprocess 启动。
子进程内才允许加载 mlx_whisper；完成后 os._exit(0) 直接退出，
崩溃不影响平台主进程/测试器。解析逻辑见 子进程解析.py。

协议：stdin 读一行 JSON 请求，stdout 写一行 JSON 响应。
请求：{"操作": "检查可用性"|"获取模型版本"|"转写音频", ...}
响应：{"成功": true, "值": ...} | {"成功": false, "值": ...,
      "错误码": ..., "错误说明": ...}
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

系统根 = Path(__file__).resolve().parents[5]
if str(系统根) not in sys.path:
    sys.path.insert(0, str(系统根))

from 支持库.后端.转写支持库.转写.实现.子进程解析 import (  # noqa: E402
    初始化, 检查可用性, 获取模型版本, 转写音频,
)
from 支持库.后端.转写支持库.转写.实现.子进程解析 import 禁用库环境变量名  # noqa: E402


def _响应(成功: bool, 值=None, 错误码: str = "", 错误说明: str = "") -> str:
    return json.dumps({"成功": 成功, "值": 值, "错误码": 错误码, "错误说明": 错误说明}, ensure_ascii=False)


def _禁用库表() -> set[str]:
    return {名.strip() for 名 in os.environ.get(禁用库环境变量名, "").split(",") if 名.strip()}


def _输出(结果: dict) -> int:
    """输出结果；错误字典（含 错误码）转失败响应并保留 值。"""
    if 结果.get("错误码"):
        print(_响应(False, 值=结果.get("值"), 错误码=str(结果["错误码"]),
                     错误说明=str(结果.get("错误说明") or "子进程执行失败")))
        return 0
    print(_响应(True, 值=结果.get("值")))
    return 0


def 主循环() -> int:
    初始化(_禁用库表())
    请求行 = sys.stdin.readline()
    if not 请求行.strip():
        print(_响应(False, 错误码="参数不合法", 错误说明="空请求"))
        return 0
    try:
        请求 = json.loads(请求行)
    except json.JSONDecodeError as 错误:
        print(_响应(False, 错误码="参数不合法", 错误说明=f"请求不是合法 JSON: {错误}"))
        return 0
    操作表 = {
        "检查可用性": lambda 请求: 检查可用性(str(请求.get("模型路径") or ""), str(请求.get("模型名") or "")),
        "获取模型版本": lambda 请求: 获取模型版本(str(请求.get("模型路径") or ""), str(请求.get("模型名") or "")),
        "转写音频": lambda 请求: 转写音频(str(请求.get("文件路径") or ""),
                                         str(请求.get("模型路径") or ""), str(请求.get("模型名") or "")),
    }
    处理函数 = 操作表.get(str(请求.get("操作") or ""))
    if 处理函数 is None:
        print(_响应(False, 错误码="参数不合法", 错误说明=f"未知操作 '{请求.get('操作')}'"))
        return 0
    try:
        return _输出(处理函数(请求))
    except Exception as 错误:
        print(_响应(False, 错误码="进程崩溃", 错误说明=f"子进程执行异常: {错误}"))
        return 0


if __name__ == "__main__":
    主循环()
    sys.stdout.flush()
    os._exit(0)
