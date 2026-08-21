"""本地大模型对话（真实库调用，仅在子进程加载）。

惰性加载门：mlx_lm 只在子进程 import；Ollama 模式经 urllib 请求本地服务。
模型路径/模型名来自配置；未配置模型如实返回 未配置模型。
全部函数返回 dict，不抛异常到入口。
"""

import json
import os
import urllib.request
from pathlib import Path

禁用库环境变量名 = "本地LLM提供者_禁用库"
_库模块 = None
_后端 = ""


def _加载库(禁用库表: set[str]) -> None:
    """决定后端：优先 mlx_lm（模型路径），否则 ollama（仅模型名）。"""
    global _库模块, _后端
    if "mlx_lm" in 禁用库表:
        _库模块 = None
    else:
        try:
            import mlx_lm  # 仅在子进程

            _库模块 = mlx_lm
        except Exception:
            _库模块 = None
    _后端 = "mlx" if _库模块 is not None else "ollama"


def 初始化(禁用库表) -> bool:
    _加载库(禁用库表)
    return _库模块 is not None or _后端 == "ollama"


def _不可用():
    return {"错误码": "提供者不可用", "错误说明": "本地 LLM 库不可用，请安装 mlx-lm 或配置 Ollama", "值": None}


def _未配置():
    return {"错误码": "未配置模型", "错误说明": "未配置模型路径或模型名", "值": None}


def _模型缺失(模型路径: str):
    return {"错误码": "模型缺失", "错误说明": f"模型路径不是目录: {模型路径}", "值": None}


def _检查模型(模型路径: str, 模型名: str):
    if not 模型路径 and not 模型名:
        return _未配置()
    模型路径对象 = Path(模型路径) if 模型路径 else None
    if 模型路径对象 is not None and not 模型路径对象.is_dir():
        return _模型缺失(模型路径)
    return None


def _ollama生成(模型名: str, 提示: str, 系统提示: str, 最大生成token: int, 温度: float) -> dict:
    消息 = []
    if 系统提示 and str(系统提示).strip():
        消息.append({"role": "system", "content": 系统提示})
    消息.append({"role": "user", "content": 提示})
    请求体 = json.dumps(
        {"model": 模型名, "messages": 消息, "max_tokens": 最大生成token, "temperature": 温度},
        ensure_ascii=False,
    ).encode("utf-8")
    try:
        with urllib.request.urlopen(
            urllib.request.Request(
                "http://127.0.0.1:11434/v1/chat/completions",
                data=请求体,
                headers={"Content-Type": "application/json"},
            ),
            timeout=300,
        ) as 响应:
            数据 = json.loads(响应.read().decode("utf-8", errors="replace"))
    except Exception as 错误对象:
        return {"错误码": "生成失败", "错误说明": f"Ollama 请求失败: {错误对象}", "值": None}
    文本 = 数据.get("choices", [{}])[0].get("message", {}).get("content", "")
    if not 文本:
        return {"错误码": "生成失败", "错误说明": "Ollama 未返回文本", "值": None}
    return {"值": {"文本": 文本, "模型名": 模型名, "是否截断": False}}


def 检查可用性(模型路径: str, 模型名: str) -> dict:
    if _库模块 is None and _后端 == "ollama":
        检查 = _检查模型("", 模型名)
        if 检查 is not None:
            return 检查
        try:
            with urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=10) as 响应:
                数据 = json.loads(响应.read().decode("utf-8", errors="replace"))
            模型列表 = [项.get("name") for 项 in 数据.get("models", [])]
            return {"值": {"可用": True, "模型名": 模型名, "模型版本": "ollama:" + ",".join(模型列表[:5])}}
        except Exception:
            return {"错误码": "提供者不可用", "错误说明": "Ollama 服务不可达", "值": None}
    检查 = _检查模型(模型路径, 模型名)
    if 检查 is not None:
        return 检查
    try:
        import mlx_lm  # noqa: F401

        return {"值": {"可用": True, "模型名": 模型名 or 模型路径, "模型版本": "mlx-lm"}}
    except Exception as 错误对象:
        return {"错误码": "提供者不可用", "错误说明": f"mlx_lm 加载失败: {错误对象}", "值": None}


def 获取模型信息(模型路径: str, 模型名: str) -> dict:
    if _库模块 is None and _后端 == "ollama":
        检查 = _检查模型("", 模型名)
        if 检查 is not None:
            return 检查
        try:
            with urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=10) as 响应:
                数据 = json.loads(响应.read().decode("utf-8", errors="replace"))
            模型列表 = [项.get("name") for 项 in 数据.get("models", [])]
            return {"值": {"可用模型清单": 模型列表, "当前模型名": 模型名, "库版本": "ollama"}}
        except Exception:
            return {"错误码": "提供者不可用", "错误说明": "Ollama 服务不可达", "值": None}
    检查 = _检查模型(模型路径, 模型名)
    if 检查 is not None:
        return 检查
    try:
        import mlx_lm  # noqa: F401

        return {"值": {"可用模型清单": [模型名 or 模型路径], "当前模型名": 模型名 or 模型路径, "库版本": "mlx-lm"}}
    except Exception as 错误对象:
        return {"错误码": "提供者不可用", "错误说明": f"mlx_lm 加载失败: {错误对象}", "值": None}


def 生成(提示: str, 系统提示: str, 最大生成token: int, 温度: float, 模型路径: str, 模型名: str) -> dict:
    if _库模块 is None and _后端 == "ollama":
        if not 模型名:
            return _未配置()
        return _ollama生成(模型名, 提示, 系统提示, 最大生成token, 温度)
    检查 = _检查模型(模型路径, 模型名)
    if 检查 is not None:
        return 检查
    目标 = 模型路径 or 模型名
    try:
        import mlx_lm.generate as 生成模块
        from mlx_lm import load as 加载模块

        模型, 分词器 = 加载模块(目标)
        消息 = [{"role": "system", "content": 系统提示}] if 系统提示 and str(系统提示).strip() else []
        消息.append({"role": "user", "content": 提示})
        文本 = 生成模块(模型, 分词器, 消息=消息, max_tokens=最大生成token, temp=温度)
        del 模型, 分词器
    except Exception as 错误对象:
        return {"错误码": "生成失败", "错误说明": f"mlx_lm 生成失败: {错误对象}", "值": None}
    if not 文本 or not str(文本).strip():
        return {"错误码": "生成失败", "错误说明": "生成未返回文本", "值": None}
    是否截断 = len(文本) >= 最大生成token
    return {"值": {"文本": 文本, "模型名": 模型名 or 模型路径, "是否截断": 是否截断}}