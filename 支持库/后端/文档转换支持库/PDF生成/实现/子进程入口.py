"""子进程入口：PDF 生成（reportlab）的独立进程 Worker。

本文件只在独立子进程中运行，由 实现/生成PDF.py 通过 subprocess 启动。子进程内才
允许加载 reportlab —— 而且是经 支持库.适配层.reportlab提供者 的**公开入口**调用：
reportlab 的唯一实现在适配层腿，本包不再保留第二份渲染代码（D-2/D-3 收口）。

协议：stdin 读一行 JSON 请求，stdout 写一行 JSON 响应。
请求：{"操作": "生成", "内容参数": {...}}
响应：{"成功": true, "值": ...} | {"成功": false, "错误码":..., "错误说明":...}
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

系统根 = next(
    祖先 for 祖先 in Path(__file__).resolve().parents
    if (祖先 / "支持库").is_dir() and (祖先 / "模块库").is_dir()
)
导入根 = 系统根.parent if 系统根.name == "平台客户端" else 系统根
if str(导入根) not in sys.path:
    sys.path.insert(0, str(导入根))

from 支持库.适配层.reportlab提供者 import 生成PDF as _唯一实现生成PDF  # noqa: E402


def _响应(成功: bool, 值=None, 错误码: str = "", 错误说明: str = "") -> str:
    return json.dumps({"成功": 成功, "值": 值, "错误码": 错误码, "错误说明": 错误说明},
                      ensure_ascii=False)


def 主循环() -> int:
    """读一行请求，执行，写一行响应。"""
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
    if 操作 != "生成":
        print(_响应(False, 错误码="参数不合法", 错误说明=f"未知操作 '{操作}'"))
        return 0
    try:
        结果 = _唯一实现生成PDF(请求.get("内容参数"))
    except Exception as 错误:  # 任何未预期异常都转稳定响应，不拖垮主进程
        print(_响应(False, 错误码="提供者崩溃", 错误说明=f"子进程执行异常: {错误}"))
        return 0
    if 结果.成功:
        print(_响应(True, 值=结果.值))
        return 0
    print(_响应(False, 错误码=str(结果.错误码 or "生成失败"),
                错误说明=str(结果.错误说明 or "PDF 生成失败")))
    return 0


if __name__ == "__main__":
    主循环()
    sys.stdout.flush()
    # 直接退出，跳过解释器关闭阶段（与同仓其它受管提供者子进程同一收口方式）
    os._exit(0)
