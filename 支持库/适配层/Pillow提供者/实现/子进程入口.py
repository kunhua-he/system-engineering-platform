"""子进程入口：Pillow（PIL，C 原生扩展）独立子进程 Worker。

只在独立子进程中运行，由 实现/提供者.py 通过 subprocess 启动。
子进程内才允许 import PIL；子进程完成后用 os._exit(0) 直接退出，
跳过解释器关闭阶段的模块销毁，崩溃不影响主进程/测试器/后端。
Pillow 操作逻辑见 子进程解析.py。

协议：stdin 读一行 JSON 请求，stdout 写一行 JSON 响应。
请求：{"操作": "解码图像"|"像素统计"|"生成占位图", ...}
响应：{"成功": true, "值": ...} | {"成功": false, "值": ...,
      "错误码": ..., "错误说明": ...}
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

系统根 = Path(__file__).resolve().parents[4]
if str(系统根) not in sys.path:
    sys.path.insert(0, str(系统根))

from 支持库.适配层.Pillow提供者.实现.子进程解析 import (  # noqa: E402
    初始化, 解码图像, 像素统计, 生成占位图, 禁用库环境变量名,
)


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
        "解码图像": lambda 请求: 解码图像(str(请求.get("字节b64") or "")),
        "像素统计": lambda 请求: 像素统计(str(请求.get("字节b64") or "")),
        "生成占位图": lambda 请求: 生成占位图(
            请求.get("宽度"), 请求.get("高度"), 请求.get("占位类型"),
            请求.get("背景颜色"), 请求.get("前景颜色"), 请求.get("文本")),
    }
    处理函数 = 操作表.get(str(请求.get("操作") or ""))
    if 处理函数 is None:
        print(_响应(False, 错误码="参数不合法", 错误说明=f"未知操作 '{请求.get('操作')}'"))
        return 0
    try:
        return _输出(处理函数(请求))
    except Exception as 错误:
        print(_响应(False, 错误码="提供者崩溃", 错误说明=f"子进程执行异常: {错误}"))
        return 0


if __name__ == "__main__":
    主循环()
    sys.stdout.flush()
    # 直接退出，跳过解释器关闭阶段的模块销毁
    os._exit(0)
