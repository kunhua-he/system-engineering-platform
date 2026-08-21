"""本地大模型对话子进程入口（Worker 壳）。

stdin 一行 JSON 请求，stdout 一行 JSON 响应。崩溃不影响主进程。
"""

import json
import os
import sys
from pathlib import Path

系统根 = Path(__file__).resolve().parents[4]
if str(系统根) not in sys.path:
    sys.path.insert(0, str(系统根))

from 支持库.适配层.本地LLM提供者.实现.子进程解析 import 初始化, 检查可用性, 获取模型信息, 生成, 禁用库环境变量名


def _响应(成功: bool, 值=None, 错误码: str = "", 错误说明: str = "") -> str:
    return json.dumps(
        {"成功": 成功, "值": 值, "错误码": 错误码, "错误说明": 错误说明}, ensure_ascii=False
    )


def _禁用库表() -> set[str]:
    原文 = os.environ.get(禁用库环境变量名, "")
    return {项.strip() for 项 in 原文.split(",") if 项.strip()}


def _输出(结果: dict) -> int:
    if 结果.get("错误码"):
        return sys.stdout.write(_响应(False, 值=结果.get("值"), 错误码=结果.get("错误码"), 错误说明=结果.get("错误说明")))
    return sys.stdout.write(_响应(True, 值=结果.get("值")))


def _取参(请求: dict, 名称: str, 默认=""):
    值 = 请求.get(名称)
    return str(值) if 值 is not None else 默认


def 主循环() -> int:
    初始化(_禁用库表())
    请求行 = sys.stdin.readline()
    if not 请求行.strip():
        return sys.stdout.write(_响应(False, 错误码="参数不合法", 错误说明="空请求"))
    try:
        请求 = json.loads(请求行)
    except json.JSONDecodeError:
        return sys.stdout.write(_响应(False, 错误码="参数不合法", 错误说明="请求不是合法 JSON"))
    操作 = str(请求.get("操作") or "")
    模型路径 = _取参(请求, "模型路径")
    模型名 = _取参(请求, "模型名")
    if 操作 == "检查可用性":
        结果 = 检查可用性(模型路径, 模型名)
    elif 操作 == "获取模型信息":
        结果 = 获取模型信息(模型路径, 模型名)
    elif 操作 == "生成":
        结果 = 生成(
            _取参(请求, "提示"),
            _取参(请求, "系统提示"),
            int(请求.get("最大生成token") or 2048),
            float(请求.get("温度") or 0.7),
            模型路径,
            模型名,
        )
    else:
        return sys.stdout.write(_响应(False, 错误码="参数不合法", 错误说明=f"未知操作: {操作}"))
    try:
        return _输出(结果)
    except Exception as 错误对象:
        return sys.stdout.write(_响应(False, 错误码="进程崩溃", 错误说明=str(错误对象)))


if __name__ == "__main__":
    主循环()
    sys.stdout.flush()
    os._exit(0)