"""子进程入口：PDF 原生第三方提供者的独立进程 Worker。

本文件只在独立子进程中运行，由 隔离提供者.py 通过 subprocess 启动。
子进程内才允许 import fitz/pdfplumber（PyMuPDF 的 SWIG 绑定在解释器
关闭时可能段错误，隔离到子进程后崩溃不影响主进程/测试器/后端）。

协议：stdin 读一行 JSON 请求，stdout 写一行 JSON 响应。
请求：{"操作": "解析"|"校验"|"版本", ...参数}
响应：{"成功": true, "值": ...} | {"成功": false, "错误码":..., "错误说明":...}
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

系统根 = Path(__file__).resolve().parents[5]
if str(系统根) not in sys.path:
    sys.path.insert(0, str(系统根))

from 支持库.后端.文档转换支持库.PDF隔离提供者.实现.子进程解析 import (  # noqa: E402
    解析PDF为字典,
    校验PDF返回页数,
    获取提供者版本,
)


def _响应(成功: bool, 值=None, 错误码: str = "", 错误说明: str = "") -> str:
    return json.dumps({"成功": 成功, "值": 值, "错误码": 错误码, "错误说明": 错误说明}, ensure_ascii=False)


def 主循环() -> int:
    """读一行请求，执行，写一行响应，然后 os._exit 跳过 SWIG 清理。"""
    请求行 = sys.stdin.readline()
    if not 请求行.strip():
        print(_响应(False, 错误码="参数不合法", 错误说明="空请求"))
        return 0
    try:
        请求 = json.loads(请求行)
    except json.JSONDecodeError as 错误:
        print(_响应(False, 错误码="参数不合法", 错误说明=f"请求不是合法 JSON: {错误}"))
        return 0
    操作 = str(请求.get("操作") or "")
    禁用库表 = {
        库名.strip() for 库名 in os.environ.get("PDF隔离提供者_禁用库", "").split(",") if 库名.strip()
    }
    try:
        if 操作 == "解析":
            路径 = str(请求.get("文件路径") or "")
            值 = 解析PDF为字典(路径, 请求.get("最大页数", 500), 请求.get("最大字节数", 0), 禁用库表)
            return _输出(值)
        if 操作 == "校验":
            字节 = _解码字节(请求.get("字节b64", ""))
            值 = 校验PDF返回页数(字节, 禁用库表)
            return _输出(值)
        if 操作 == "版本":
            值 = 获取提供者版本(禁用库表)
            return _输出(值)
        print(_响应(False, 错误码="参数不合法", 错误说明=f"未知操作 '{操作}'"))
        return 0
    except Exception as 错误:  # 任何未预期异常都转稳定响应
        print(_响应(False, 错误码="提供者崩溃", 错误说明=f"子进程执行异常: {错误}"))
        return 0


def _输出(值) -> int:
    """输出结果；若解析函数返回错误字典（含 错误码），转失败响应。"""
    if isinstance(值, dict) and 值.get("错误码"):
        print(_响应(
            False,
            错误码=str(值.get("错误码") or "提供者崩溃"),
            错误说明=str(值.get("错误说明") or "子进程执行失败"),
        ))
        return 0
    print(_响应(True, 值=值))
    return 0


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
