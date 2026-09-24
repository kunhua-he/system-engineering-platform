"""子进程入口：PDF 原生第三方提供者的独立进程 Worker。

本文件只在独立子进程中运行，由 隔离提供者.py 通过 subprocess 启动。
子进程内才允许 import fitz/pdfplumber（PyMuPDF 的 SWIG 绑定在解释器
关闭时可能段错误，隔离到子进程后崩溃不影响主进程/测试器/后端）。

协议：stdin 读一行 JSON 请求，stdout 写一行 JSON 响应。
请求：{"操作": "解析"|"校验"|"版本", ...参数}
响应：{"成功": true, "值": ...} | {"成功": false, "错误码":..., "错误说明":...}
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

系统根 = Path(__file__).resolve().parents[4]
导入根 = 系统根.parent if 系统根.name == "平台客户端" else 系统根
if str(导入根) not in sys.path:
    sys.path.insert(0, str(导入根))

from 支持库.适配层.PDF隔离提供者.实现.子进程解析 import (  # noqa: E402
    解析PDF为字典,
    校验PDF返回页数,
    获取提供者版本,
)


from 公共契约.运行时 import 子进程协议  # noqa: E402 - 单发协议唯一实现（平台根已在上方自举入 sys.path）


def _禁用库表() -> set[str]:
    """PDF隔离提供者_禁用库（逗号分隔）→ 集合；每次现算，与旧行为逐字同口径。"""
    return {库名.strip() for 库名 in os.environ.get("PDF隔离提供者_禁用库", "").split(",") if 库名.strip()}


def 主循环() -> int:
    """单发协议主循环；四类收口与信封组装唯一实现在 公共契约/运行时/子进程协议。"""
    return 子进程协议.单发主循环(
        {
            "解析": lambda 请求: 解析PDF为字典(
                str(请求.get("文件路径") or ""), 请求.get("最大页数", 500),
                请求.get("最大字节数", 0), _禁用库表()),
            "校验": lambda 请求: 校验PDF返回页数(
                _解码字节(str(请求.get("字节b64") or "")), _禁用库表()),
            "版本": lambda 请求: 获取提供者版本(_禁用库表()),
        },
        入口名="PDF隔离提供者",
    )


def _解码字节(字节b64: str) -> bytes:
    import base64
    if not 字节b64:
        return b""
    try:
        return base64.b64decode(字节b64)
    except Exception:
        return b""


if __name__ == "__main__":
    主循环()
    sys.stdout.flush()
    # 直接退出，跳过解释器关闭阶段的 SWIG 模块销毁（避免 PyMuPDF 段错误）
    os._exit(0)
