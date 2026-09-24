"""子进程入口：跨平台语音转写独立子进程 Worker（**一份实现 + 按平台选后端**）。

只在独立子进程中运行，由 实现/提供者.py 通过 subprocess 启动。
子进程内才允许加载转写库（Apple Silicon → mlx_whisper；Windows/Linux → faster_whisper，
由 `公共契约/运行时/平台适配.转写后端()` 唯一判定）；完成后 os._exit(0) 直接退出，
崩溃不影响平台主进程/测试器。解析逻辑见 子进程解析.py。

协议：stdin 读一行 JSON 请求，stdout 写一行 JSON 响应。
请求：{"操作": "检查可用性"|"获取模型版本"|"转写音频", ...}
响应：{"成功": true, "值": ...} | {"成功": false, "值": ...,
      "错误码": ..., "错误说明": ...}
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

系统根 = Path(__file__).resolve().parents[4]
导入根 = 系统根.parent if 系统根.name == "平台客户端" else 系统根
if str(导入根) not in sys.path:
    sys.path.insert(0, str(导入根))

from 支持库.适配层.MLXWhisper提供者.实现.子进程解析 import (  # noqa: E402
    初始化, 检查可用性, 获取模型版本, 转写音频,
)
from 支持库.适配层.MLXWhisper提供者.实现.子进程解析 import 禁用库环境变量名  # noqa: E402


from 公共契约.运行时 import 子进程协议  # noqa: E402 - 单发协议唯一实现（平台根已在上方自举入 sys.path）


def _禁用库表() -> set[str]:
    return {名.strip() for 名 in os.environ.get(禁用库环境变量名, "").split(",") if 名.strip()}


def _前置() -> str | None:
    """初始化转写后端（按平台选 mlx_whisper / faster_whisper）；本腿恒不失败。"""
    初始化(_禁用库表())
    return None


def 主循环() -> int:
    """单发协议主循环；四类收口与信封组装唯一实现在 公共契约/运行时/子进程协议。"""
    操作表 = {
        "检查可用性": lambda 请求: 检查可用性(str(请求.get("模型路径") or ""), str(请求.get("模型名") or "")),
        "获取模型版本": lambda 请求: 获取模型版本(str(请求.get("模型路径") or ""), str(请求.get("模型名") or "")),
        "转写音频": lambda 请求: 转写音频(str(请求.get("文件路径") or ""),
                                         str(请求.get("模型路径") or ""), str(请求.get("模型名") or ""),
                                         str(请求.get("附加术语") or ""),
                                         bool(请求.get("返回分段"))),
    }
    # 崩溃码沿用本腿既有「进程崩溃」（提供者.py 把它计入可重试错误码，改它会改调用方重试判据）
    return 子进程协议.单发主循环(
        操作表, 入口名="MLXWhisper提供者", 前置=_前置, 崩溃错误码="进程崩溃")


if __name__ == "__main__":
    主循环()
    sys.stdout.flush()
    os._exit(0)
