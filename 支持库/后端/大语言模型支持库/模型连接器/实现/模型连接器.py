"""模型连接器支持库实现：LLM/向量/重排连接器 + 句柄生命周期 + 系统内存安全。

设计（华哥口径 2026-08-26）：
1. 连接器 = 创建模型连接，返回六位句柄；其他能力持句柄调用模型。
2. 本地与云端两类连接：本地传 GGUF 文件绝对路径，由底座直接调用 llama-server；云端传 url/api_key/模型/上下文长度。
3. 句柄生命周期：默认 1800 秒（30 分钟）无人使用自动释放（超时回收）；可续租；可显式释放。
4. 系统内存安全（核心）：连接模型前用 psutil 查系统真实可用内存，
   若「当前占用 + 新模型预计占用」超过安全阈值（默认 80%）→ 拒绝新连接，
   返回 资源不足（内存压力），防止同时启动多个大模型撑爆 96GB 内存。
5. 真实模型调用由统一 HTTP Provider 承接；本地模型进程由底座启动并绑定句柄，不模拟成功。
"""

from __future__ import annotations

import json
import os
import threading
import time
import uuid
from collections import deque
from typing import Any, Callable

from 公共契约.基础类型.结果类型 import 结果
from 公共契约.句柄体系 import 句柄体系, 句柄类型_资源

try:
    import psutil
except Exception:  # pragma: no cover - 环境无 psutil 时降级
    psutil = None

# ── 句柄与连接管理 ──────────────────────────────

句柄系统 = 句柄体系()
连接表: dict[int, dict[str, Any]] = {}          # 句柄id → 连接信息
调用函数表: dict[str, Callable] = {}             # 连接类型+本地/云端 → 真实调用函数
锁 = threading.Lock()

默认超时秒 = 1800                            # 华哥口径：不申报默认 30 分钟（1800 秒），模块/支持库应主动申报
内存安全阈值 = 0.80                              # 系统内存占用安全阈值（80%）
连接类型表 = {"LLM": "对话", "向量": "嵌入", "重排": "排序"}
默认协议 = "chat_completions"
允许协议 = frozenset(("chat_completions", "codex_responses"))
协议别名 = {
    "chat": "chat_completions",
    "chat_completions": "chat_completions",
    "res": "codex_responses",
    "codex_responses": "codex_responses",
}


def _规范化协议(协议: Any) -> str | None:
    """把公开短协议别名统一为内部长协议；非法值返回 None。"""
    return 协议别名.get(协议) if isinstance(协议, str) else None



降级记录表: deque[str] = deque(maxlen=1000)  # 尽力清理/降级异常，最多保留1000条

def _句柄键(句柄id: str | int) -> int:
    """连接表与公开网关统一使用整数句柄。"""
    return int(句柄id)

def _包申报超时() -> int:
    """读取本包 包声明.json 的 句柄超时秒（模块主动申报），缺省返回 默认超时秒。"""
    try:
        import json
        声明路径 = os.path.join(os.path.dirname(__file__), "..", "包声明.json")
        with open(声明路径, encoding="utf-8") as f:
            申报 = json.load(f).get("句柄超时秒")
        if isinstance(申报, int) and 申报 > 0:
            return 申报
    except Exception as 错误:
        降级记录表.append(str(错误))
    return 默认超时秒


def _失败(错误码: str, 消息: str, *, 可重试: bool = False,
        详情: dict[str, Any] | None = None) -> 结果:
    return 结果.失败(错误码, 消息, 来源="模型连接器", 可重试=可重试, 详情=详情)


def _系统内存快照() -> dict[str, Any]:
    """返回系统内存快照：总量/已用/可用/占用率。psutil 不可用时返回 未知。"""
    if psutil is None:
        return {"可用": False, "说明": "psutil 不可用，无法做系统内存检查"}
    vm = psutil.virtual_memory()
    return {
        "可用": True,
        "总量字节": vm.total, "可用字节": vm.available, "已用字节": vm.used,
        "占用率": round(vm.percent, 1),
        "说明": f"总 {vm.total/1024**3:.1f}GB / 可用 {vm.available/1024**3:.1f}GB / 占用 {vm.percent:.0f}%",
    }


def _预计占用(连接类型: str, 配置: dict) -> int:
    """估算一个新连接的内存占用（字节）。本地大模型按模型大小估算；云端按小头估算。"""
    部署形态 = 配置.get("部署形态") or "本地"
    if 部署形态 == "云端":
        return 512 * 1024 * 1024  # 云端连接占用小（512MB 预算）
    # 本地：优先按 模型大小 估算，否则按类型默认
    大小 = 配置.get("模型大小字节")
    if isinstance(大小, (int, float)) and 大小 > 0:
        return int(大小) * 2  # 加载后约 2 倍文件大小（量化+推理缓冲）
    默认表 = {"LLM": 8 * 1024**3, "向量": 2 * 1024**3, "重排": 2 * 1024**3}  # LLM 8GB/向量 2GB/重排 2GB
    return 默认表.get(连接类型, 2 * 1024**3)


def _内存守卫(连接类型: str, 配置: dict) -> 结果 | None:
    """系统内存安全检查：预计占用超安全阈值或探针不可用时拒绝。"""
    快照 = _系统内存快照()
    if not 快照.get("可用"):
        return _失败("资源预算未验证", "系统内存探针不可用，拒绝启动新模型以避免突破内存预算")
    预计 = _预计占用(连接类型, 配置)
    总量 = 快照["总量字节"]
    当前已用 = 快照["已用字节"]
    新占用率 = (当前已用 + 预计) / 总量
    阈值 = 配置.get("内存安全阈值") or 内存安全阈值
    if 新占用率 > 阈值:
        return _失败("资源不足",
                     f"系统内存压力：当前占用 {快照['占用率']}%，新连接预计 +{预计/1024**3:.1f}GB "
                     f"将达 {新占用率*100:.0f}%（安全阈值 {阈值*100:.0f}%），拒绝启动新模型以防撑爆内存。"
                     f"请释放不用的模型连接（{快照['说明']}）")
    return None


def _回收过期句柄() -> None:
    """回收过期句柄：锁内只标记，实际释放和终态收口在锁外完成。"""
    now = time.time()
    待释放: list[tuple[int, Any]] = []
    with 锁:
        for 句柄id, 连接 in list(连接表.items()):
            if 连接.get("状态", "有效") != "有效":
                continue
            空闲 = now - 连接.get("最后活动时间", now)
            if 空闲 <= 连接.get("超时秒", 默认超时秒):
                continue
            连接["状态"] = "释放中"
            for 模型身份, 索引句柄 in list(全局模型索引.items()):
                if 索引句柄 == 句柄id:
                    全局模型索引.pop(模型身份, None)
            待释放.append((句柄id, 连接.get("释放函数")))
    _完成释放(待释放, "超时")


def _完成释放(待释放: list[tuple[int, Any]], 原因: str) -> None:
    """执行释放回调并按真实结果收口；失败时保留连接账本供重试。"""
    for 句柄id, 释放函数 in 待释放:
        成功 = True
        try:
            if 释放函数:
                返回值 = 释放函数(句柄id)
                成功 = 返回值 is not False
        except Exception as 错误:
            成功 = False
            降级记录表.append(f"句柄 {句柄id} {原因}释放回调失败: {错误}")
        with 锁:
            连接 = 连接表.get(句柄id)
            if 成功:
                连接表.pop(句柄id, None)
                句柄系统.失效(int(句柄id), 原因)
            elif 连接 is not None:
                连接["状态"] = "释放失败"


def _登记连接(连接类型: str, 配置: dict, *, 超时秒: int, 所有者: str = "") -> 结果:
    if 连接类型 not in 连接类型表:
        return _失败("参数不合法", f"未知连接类型: {连接类型}")
    _回收过期句柄()
    with 锁:
        # 系统内存安全守卫：撑爆内存前拒绝
        守卫 = _内存守卫(连接类型, 配置)
        if 守卫 is not None:
            return 守卫
        对象 = 句柄系统.创建句柄(句柄类型=句柄类型_资源, 资源id=f"模型连接-{连接类型}", 所有者=所有者)
        有效超时 = 超时秒 if isinstance(超时秒, int) and 超时秒 > 0 else _包申报超时()
        连接键 = _句柄键(对象.句柄id)
        连接表[连接键] = {
            "类型": 连接类型, "配置": dict(配置), "创建时间": time.time(),
            "最后活动时间": time.time(), "超时秒": 有效超时, "释放函数": None,
            "状态": "有效",
        }
        return 结果.成功结果({"句柄": 连接键, "连接类型": 连接类型,
                                "模型": 配置.get("模型名") or 配置.get("模型"),
                                "部署形态": 配置.get("部署形态") or "本地", "超时秒": 有效超时,
                                "协议": 配置.get("协议") if 连接类型 == "LLM" else None,
                                "说明": "句柄超时由包声明申报（默认 30 分钟），一直用持续重置，可续租，可显式释放"})


def _取连接(句柄id: int) -> tuple[dict[str, Any] | None, str]:
    _回收过期句柄()
    键 = _句柄键(句柄id)
    try:
        状态机id = int(键)
    except ValueError:
        return None, f"句柄格式不合法: {句柄id}"
    有效, 原因 = 句柄系统.校验(状态机id)
    if not 有效:
        return None, 原因
    连接 = 连接表.get(键)
    if 连接 is None:
        return None, f"句柄 {句柄id} 连接不存在（可能已自动释放）"
    if 连接.get("状态", "有效") != "有效":
        return None, f"句柄 {句柄id} 正在释放或释放失败，禁止继续调用"
    now = time.time()
    if now - 连接["最后活动时间"] > 连接["超时秒"]:
        _回收过期句柄()
        return None, f"句柄 {句柄id} 已超时自动释放（{连接['超时秒']} 秒无人使用）"
    连接["最后活动时间"] = now
    return 连接, ""


def _HTTP调用模型(连接类型: str, 配置: dict, 参数: dict) -> 结果:
    """URL连接的默认兼容调用器；与受管 Provider 保持同一协议契约。"""
    import json
    import urllib.error
    import urllib.request
    基址 = str(配置.get("url") or "").rstrip("/")
    if not 基址:
        return _失败("提供者不可用", f"{连接类型}连接未配置url")
    模型 = 配置.get("模型名") or 配置.get("模型")
    if 连接类型 == "LLM":
        流式输出 = 参数.get("流式输出", False)
        if 流式输出 is True:
            return _失败(
                "流式能力未装配",
                "流式输出已请求，但40007网关尚未装配模型SSE传输，待补网关流；未伪造完成结果",
                详情={"流式输出": True, "协议": 配置.get("协议", 默认协议), "网关": "40007"},
            )
        消息 = list(参数.get("消息列表") or [])
        if 参数.get("系统提示词"):
            消息.insert(0, {"role": "system", "content": 参数["系统提示词"]})
        协议 = 配置.get("协议", 默认协议)
        if 协议 == "codex_responses":
            路径, 请求体 = "/responses", {"model": 模型, "input": 消息, "stream": False}
        else:
            路径, 请求体 = "/chat/completions", {"model": 模型, "messages": 消息, "stream": False}
    elif 连接类型 == "向量":
        路径, 请求体 = "/embeddings", {"model": 模型, "input": 参数.get("文本")}
    else:
        路径, 请求体 = "/rerank", {"model": 模型, "query": 参数.get("查询"), "documents": 参数.get("文档列表")}
    请求 = urllib.request.Request(
        基址 + 路径, data=json.dumps(请求体, ensure_ascii=False).encode("utf-8"), method="POST",
        headers={"Content-Type": "application/json", **(
            {"Authorization": f"Bearer {配置['api_key']}"} if 配置.get("api_key") else {})},
    )
    try:
        with urllib.request.urlopen(请求, timeout=30) as 响应:
            原始 = 响应.read(4 * 1024 * 1024 + 1)
            if len(原始) > 4 * 1024 * 1024:
                return _失败("超出限制", f"{连接类型} HTTP响应超过4MB上限")
            数据 = json.loads(原始.decode("utf-8"))
        if 连接类型 == "LLM":
            回复 = 数据.get("output_text")
            if not isinstance(回复, str):
                回复 = (((数据.get("choices") or [{}])[0].get("message") or {}).get("content"))
            if not isinstance(回复, str) or not 回复:
                return _失败("模型调用失败", "模型响应没有可用文本")
            return 结果.成功结果({"回复": 回复, "用量": 数据.get("usage", {})})
        if 连接类型 == "向量":
            向量 = 数据["data"][0]["embedding"]
            return 结果.成功结果({"向量": 向量, "维度": len(向量)})
        原始 = 数据.get("results") or 数据.get("data") or []
        重排结果 = [{"索引": 项.get("index"), "分数": 项.get("relevance_score", 项.get("score"))} for 项 in 原始]
        return 结果.成功结果({"重排结果": 重排结果})
    except urllib.error.HTTPError as 错误:
        错误码 = {401: "认证失败", 403: "认证失败", 404: "端点不存在", 408: "超时", 429: "请求限流"}.get(
            错误.code, "模型调用失败"
        )
        return _失败(错误码, f"模型 HTTP 返回 {错误.code}", 可重试=错误.code >= 500)
    except (OSError, ValueError, KeyError, IndexError, TypeError) as 错误:
        return _失败("模型调用失败", f"{连接类型} HTTP调用失败: {错误}")


def _调用模型(句柄id: int, 连接类型: str, 参数: dict) -> 结果:
    连接, 原因 = _取连接(句柄id)
    if 连接 is None:
        return _失败("句柄失效", 原因)
    if 连接["类型"] != 连接类型:
        return _失败("参数不合法", f"句柄 {句柄id} 是 {连接['类型']} 连接，不是 {连接类型}")
    部署形态 = 连接["配置"].get("部署形态") or "本地"
    调用函数 = 调用函数表.get(f"{连接类型}:{部署形态}")
    if 调用函数 is None:
        return _HTTP调用模型(连接类型, 连接["配置"], 参数)
    try:
        return 调用函数(配置=连接["配置"], **参数)
    except Exception as 错误:
        return _失败("模型调用失败", f"{连接类型} 调用异常: {错误}")


# ── 连接器（返回句柄）──────────────────────────────

def 连接LLM(模型: str = None, 提供者: str = None, 部署形态: str = None,
           本地路径: str = None, 启动器: str = None, 模型大小字节: int = None,
           url: str = None, api_key: str = None, 上下文长度: int = None,
           超时秒: int = None, 协议: str = 默认协议) -> 结果:
    """连接大语言模型，返回句柄。连接阶段只接受连接配置与协议参数；流式输出属于生成对话选项，未知关键字（包括连接阶段流式输出）由函数签名拒绝。

    缺参时使用 env 统一参数（加载环境配置后生效）。本地：部署形态=本地+GGUF 文件绝对路径，由底座直接启动 llama-server；云端：部署形态=云端+url/api_key/模型/上下文长度。
    """
    显式 = {"模型": 模型, "提供者": 提供者, "部署形态": 部署形态, "本地路径": 本地路径,
            "启动器": 启动器, "模型大小字节": 模型大小字节, "url": url, "api_key": api_key,
            "上下文长度": 上下文长度, "超时秒": 超时秒, "协议": 协议}
    显式 = _合入环境参数("LLM", 显式)
    模型, 提供者, 部署形态 = 显式["模型"], 显式["提供者"], 显式["部署形态"]
    url, api_key, 上下文长度, 超时秒 = (显式["url"], 显式["api_key"], 显式["上下文长度"],
                                       显式["超时秒"])
    规范协议 = _规范化协议(显式.get("协议", 默认协议))
    本地路径, 启动器, 模型大小字节 = 显式["本地路径"], 显式["启动器"], 显式["模型大小字节"]
    if not isinstance(模型, str) or not 模型.strip():
        return _失败("参数不合法", "模型必须是非空字符串（env 未配置默认LLM模型）")
    if 规范协议 is None:
        return _失败("参数不合法", "协议必须是 chat_completions 或 codex_responses")
    协议 = 规范协议
    形态 = (部署形态 or "云端" if (url or api_key) else 部署形态 or "本地").lower()
    形态 = "云端" if 形态 in ("cloud", "api", "云") else "本地" if 形态 in ("local", "本机") else 形态
    if 形态 not in ("本地", "云端"):
        return _失败("参数不合法", f"部署形态必须是 本地 或 云端: {部署形态}")
    配置 = {"模型名": 模型, "提供者": 提供者 or "本地", "部署形态": 形态, "本地路径": 本地路径,
            "启动器": 启动器, "模型大小字节": 模型大小字节, "url": url, "api_key": api_key,
            "上下文长度": 上下文长度, "协议": 协议}
    if 形态 == "本地" and 本地路径:
        return 启动本地模型(本地路径, 启动器, "LLM", 模型大小字节=模型大小字节,
                           参数={"协议": 协议}, 超时秒=超时秒)
    return _登记连接("LLM", 配置, 超时秒=超时秒)


def 连接向量模型(模型: str = None, 提供者: str = None, 部署形态: str = None,
                本地路径: str = None, 启动器: str = None, 模型大小字节: int = None,
                url: str = None, api_key: str = None, 超时秒: int = None) -> 结果:
    """连接向量（嵌入）模型，返回句柄。缺参时用 env 统一参数（默认 Qwen3-Embedding-8B 4096 维本地）。"""
    显式 = {"模型": 模型, "提供者": 提供者, "部署形态": 部署形态, "本地路径": 本地路径,
            "启动器": 启动器, "模型大小字节": 模型大小字节, "url": url, "api_key": api_key, "超时秒": 超时秒}
    显式 = _合入环境参数("向量", 显式)
    模型, 提供者, 部署形态 = 显式["模型"], 显式["提供者"], 显式["部署形态"]
    url, api_key, 超时秒 = 显式["url"], 显式["api_key"], 显式["超时秒"]
    本地路径, 启动器, 模型大小字节 = 显式["本地路径"], 显式["启动器"], 显式["模型大小字节"]
    if not isinstance(模型, str) or not 模型.strip():
        return _失败("参数不合法", "模型必须是非空字符串（env 未配置默认向量模型）")
    形态 = (部署形态 or "云端" if (url or api_key) else 部署形态 or "本地").lower()
    形态 = "云端" if 形态 in ("cloud", "api", "云") else "本地" if 形态 in ("local", "本机") else 形态
    if 形态 not in ("本地", "云端"):
        return _失败("参数不合法", f"部署形态必须是 本地 或 云端: {部署形态}")
    配置 = {"模型名": 模型, "提供者": 提供者 or "本地", "部署形态": 形态, "本地路径": 本地路径,
            "启动器": 启动器, "模型大小字节": 模型大小字节, "url": url, "api_key": api_key}
    if 形态 == "本地" and 本地路径:
        return 启动本地模型(本地路径, 启动器, "向量", 模型大小字节=模型大小字节, 超时秒=超时秒)
    return _登记连接("向量", 配置, 超时秒=超时秒)


def 连接重排模型(模型: str = None, 提供者: str = None, 部署形态: str = None,
                本地路径: str = None, 启动器: str = None, 模型大小字节: int = None,
                url: str = None, api_key: str = None, 超时秒: int = None) -> 结果:
    """连接重排模型，返回句柄。缺参时用 env 统一参数（默认 Qwen3-Reranker-8B 本地）。"""
    显式 = {"模型": 模型, "提供者": 提供者, "部署形态": 部署形态, "本地路径": 本地路径,
            "启动器": 启动器, "模型大小字节": 模型大小字节, "url": url, "api_key": api_key, "超时秒": 超时秒}
    显式 = _合入环境参数("重排", 显式)
    模型, 提供者, 部署形态 = 显式["模型"], 显式["提供者"], 显式["部署形态"]
    url, api_key, 超时秒 = 显式["url"], 显式["api_key"], 显式["超时秒"]
    本地路径, 启动器, 模型大小字节 = 显式["本地路径"], 显式["启动器"], 显式["模型大小字节"]
    if not isinstance(模型, str) or not 模型.strip():
        return _失败("参数不合法", "模型必须是非空字符串（env 未配置默认重排模型）")
    形态 = (部署形态 or "云端" if (url or api_key) else 部署形态 or "本地").lower()
    形态 = "云端" if 形态 in ("cloud", "api", "云") else "本地" if 形态 in ("local", "本机") else 形态
    if 形态 not in ("本地", "云端"):
        return _失败("参数不合法", f"部署形态必须是 本地 或 云端: {部署形态}")
    配置 = {"模型名": 模型, "提供者": 提供者 or "本地", "部署形态": 形态, "本地路径": 本地路径,
            "启动器": 启动器, "模型大小字节": 模型大小字节, "url": url, "api_key": api_key}
    if 形态 == "本地" and 本地路径:
        return 启动本地模型(本地路径, 启动器, "重排", 模型大小字节=模型大小字节, 超时秒=超时秒)
    return _登记连接("重排", 配置, 超时秒=超时秒)


# ── 统一环境参数（V3 env 定义，支持库不独立传参）────────────

环境配置: dict[str, Any] = {}   # 键 → 值；连接器未显式传参时使用
环境键表 = {
    "默认向量模型": "默认向量模型", "DEFAULT_EMBEDDING_MODEL": "默认向量模型",
    "默认向量部署形态": "默认向量部署形态", "DEFAULT_EMBEDDING_DEPLOY": "默认向量部署形态",
    "默认LLM模型": "默认LLM模型", "DEFAULT_LLM_MODEL": "默认LLM模型",
    "默认LLM部署形态": "默认LLM部署形态", "DEFAULT_LLM_DEPLOY": "默认LLM部署形态",
    "默认重排模型": "默认重排模型", "DEFAULT_RERANK_MODEL": "默认重排模型",
    "默认重排部署形态": "默认重排部署形态", "DEFAULT_RERANK_DEPLOY": "默认重排部署形态",
    "云端地址": "云端地址", "MODEL_API_URL": "云端地址",
    "云端密钥": "云端密钥", "MODEL_API_KEY": "云端密钥",
    "默认上下文长度": "默认上下文长度", "DEFAULT_CONTEXT_LENGTH": "默认上下文长度",
    "模型超时秒": "模型超时秒", "MODEL_TIMEOUT_SECONDS": "模型超时秒",
    "内存安全阈值": "内存安全阈值", "MODEL_MEMORY_SAFE_RATIO": "内存安全阈值",
}


def 加载环境配置(环境文件路径: str = None) -> 结果:
    """从环境文件（如 V3 后端服务/.env）读取统一模型参数。

    读取后存入 环境配置 全局，连接器缺参时自动使用。
    未传路径时读取当前进程环境变量（os.environ）同名键。
    返回 {已读取键数, 配置摘要}。
    """
    import os
    原始: dict[str, str] = {}
    if 环境文件路径 and os.path.isfile(环境文件路径):
        with open(环境文件路径, "r", encoding="utf-8") as f:
            for 行 in f:
                行 = 行.strip()
                if not 行 or 行.startswith("#") or "=" not in 行:
                    continue
                键, 值 = 行.split("=", 1)
                原始[键.strip()] = 值.strip().strip('"').strip("'")
    else:
        for 键 in 环境键表:
            if 键 in os.environ:
                原始[键] = os.environ[键]
    global 环境配置
    配置: dict[str, Any] = {}
    for 键, 值 in 原始.items():
        规范键 = 环境键表.get(键)
        if 规范键 is None:
            continue
        if 规范键 in ("内存安全阈值",):
            try:
                配置[规范键] = float(值)
            except ValueError:
                配置[规范键] = 内存安全阈值
        elif 规范键 in ("默认上下文长度", "模型超时秒"):
            try:
                配置[规范键] = int(值)
            except ValueError:
                配置[规范键] = None
        else:
            配置[规范键] = 值
    if "默认向量模型" not in 配置:
        配置["默认向量模型"] = "Qwen3-Embedding-8B"   # 4096 维大向量模型（本地）
    if "默认向量部署形态" not in 配置:
        配置["默认向量部署形态"] = "本地"
    if "默认重排模型" not in 配置:
        配置["默认重排模型"] = "Qwen3-Reranker-8B"
    if "默认重排部署形态" not in 配置:
        配置["默认重排部署形态"] = "本地"
    环境配置 = 配置
    return 结果.成功结果({"已读取键数": len(原始), "配置摘要": {
        "默认向量模型": 配置.get("默认向量模型"), "默认向量部署形态": 配置.get("默认向量部署形态"),
        "默认LLM模型": 配置.get("默认LLM模型"), "默认LLM部署形态": 配置.get("默认LLM部署形态"),
        "默认重排模型": 配置.get("默认重排模型"), "默认重排部署形态": 配置.get("默认重排部署形态"),
        "云端地址": 配置.get("云端地址"), "默认上下文长度": 配置.get("默认上下文长度"),
        "模型超时秒": 配置.get("模型超时秒"), "内存安全阈值": 配置.get("内存安全阈值"),
    }})


def 查询环境配置() -> 结果:
    """返回当前统一环境参数（不含密钥明文）。"""
    return 结果.成功结果({k: v for k, v in 环境配置.items() if k != "云端密钥"})


def _合入环境参数(连接类型: str, 显式: dict) -> dict:
    """把 env 默认值合入显式参数（显式优先）。

    连接类型 → env 键：LLM→默认LLM模型/默认LLM部署形态；向量→默认向量模型/默认向量部署形态；重排→默认重排模型/默认重排部署形态。
    """
    合并 = dict(显式)
    模型键 = f"默认{连接类型}模型"
    形态键 = f"默认{连接类型}部署形态"
    if not 合并.get("模型") and 环境配置.get(模型键):
        合并["模型"] = 环境配置[模型键]
    if not 合并.get("部署形态"):
        合并["部署形态"] = 环境配置.get(形态键) or "本地"
    if not 合并.get("url") and 环境配置.get("云端地址"):
        合并["url"] = 环境配置["云端地址"]
    if not 合并.get("api_key") and 环境配置.get("云端密钥"):
        合并["api_key"] = 环境配置["云端密钥"]
    if not 合并.get("上下文长度") and 环境配置.get("默认上下文长度"):
        合并["上下文长度"] = 环境配置["默认上下文长度"]
    if not 合并.get("超时秒") and 环境配置.get("模型超时秒"):
        合并["超时秒"] = 环境配置["模型超时秒"]
    return 合并


# ── 本地模型启动器（路径入参，底座负责启动并绑定句柄）────────

本地进程表: dict[int, Any] = {}  # 句柄id → 子进程对象
全局模型索引: dict[tuple[str, str], int] = {}  # (模型类型, 规范化源路径) → 全局句柄
本地启动锁 = threading.Lock()  # 防止同一路径并发启动出多个模型进程


def _分配端口(端口: int | None) -> int:
    if isinstance(端口, int) and 端口 > 0:
        return 端口
    import socket
    with socket.socket() as 套接字:
        套接字.bind(("127.0.0.1", 0))
        return int(套接字.getsockname()[1])


def _计算模型大小(模型路径: str) -> int:
    """计算模型文件总大小，供内存守卫使用；目录读取失败时返回 0。"""
    from pathlib import Path
    try:
        if os.path.isfile(模型路径):
            return os.path.getsize(模型路径)
        return sum(文件.stat().st_size for 文件 in Path(模型路径).rglob("*") if 文件.is_file())
    except OSError:
        return 0


def _识别模型源(模型路径: str) -> tuple[str, str]:
    """按实体文件判断模型源格式，返回（格式, 规范化绝对路径）。"""
    from pathlib import Path
    路径 = Path(模型路径).expanduser().resolve()
    if 路径.is_file() and 路径.suffix.lower() == ".gguf":
        return "GGUF", str(路径)
    if 路径.is_dir() and (路径 / "config.json").is_file():
        if any(路径.glob("*.safetensors")) or any(路径.glob("*.bin")):
            return "HuggingFace", str(路径)
    return "不支持", str(路径)


def _构建本地启动命令(模型路径: str, 模型类型: str, 启动器: str, 端口: int, 参数: dict) -> list[str]:
    import shutil
    from pathlib import Path
    格式, 规范路径 = _识别模型源(模型路径)
    if 格式 == "HuggingFace":
        import sys
        服务脚本 = Path(__file__).resolve().parents[5] / "支持库" / "适配层" / "模型服务.py"
        if not 服务脚本.is_file():
            raise FileNotFoundError(f"底座内部模型加载器不存在: {服务脚本}")
        return [sys.executable, str(服务脚本), "--model-path", 规范路径, "--model-type", 模型类型, "--port", str(端口)]
    if 格式 != "GGUF":
        raise ValueError("底座不支持该模型源；本地模型应为 GGUF 文件或含 config.json 的权重目录")
    候选二进制 = [启动器, os.environ.get("LLAMA_CPP_SERVER_BIN", ""), shutil.which("llama-server")]
    候选二进制.extend(str(Path.home() / 路径) for 路径 in (
        "llama.cpp-old/build/bin/llama-server", "llama.cpp-latest/build/bin/llama-server"))
    二进制 = next((路径 for 路径 in 候选二进制 if 路径 and os.path.isfile(路径) and os.access(路径, os.X_OK)), "")
    if not 二进制:
        raise FileNotFoundError("未找到 llama-server；请配置 LLAMA_CPP_SERVER_BIN")
    命令 = [二进制, "-m", 模型路径, "--port", str(端口), "--sleep-idle-seconds", "300", "-c", "8192", "-ngl", "99"]
    if 模型类型 == "向量":
        命令.extend(["--pooling", "cls", "--embeddings"])
    elif 模型类型 == "重排":
        命令.append("--rerank")
    额外参数 = 参数.get("启动参数列表")
    if isinstance(额外参数, list):
        命令.extend(str(值) for 值 in 额外参数)
    return 命令


def _等待本地健康(端口: int, 超时秒: int) -> bool:
    import urllib.request
    网址 = f"http://127.0.0.1:{端口}/v1/models"
    截止时间 = time.monotonic() + min(max(10, 超时秒), 900)
    while time.monotonic() < 截止时间:
        try:
            with urllib.request.urlopen(网址, timeout=3) as 响应:
                if 200 <= 响应.status < 300:
                    return True
        except Exception as 错误:
            降级记录表.append(str(错误))
        time.sleep(0.5)
    return False


def _启动本地模型(模型路径: str | None = None, 启动器: str | None = None, 模型类型: str | None = None,
                端口: int | None = None, 模型大小字节: int | None = None, 参数: dict | None = None, 超时秒: int | None = None) -> 结果:
    """由底座按模型绝对路径启动独立进程，并返回已绑定资源的句柄。"""
    if not isinstance(模型路径, str) or not 模型路径.strip() or not os.path.exists(模型路径):
        return _失败("参数不合法", "模型路径必须是存在的绝对路径")
    类型 = (模型类型 or "LLM").lower()
    类型 = "LLM" if 类型 in ("对话", "llm") else "向量" if 类型 in ("嵌入", "向量", "embedding") else "重排" if 类型 in ("排序", "重排", "rerank") else None
    if 类型 is None:
        return _失败("参数不合法", f"模型类型必须是 LLM/向量/重排: {模型类型}")
    源格式, 规范路径 = _识别模型源(模型路径)
    if 源格式 == "不支持":
        return _失败("参数不合法", "底座不支持该模型源；本地模型应为 GGUF 文件或含 config.json 的权重目录")
    模型身份 = (类型, 规范路径)
    from pathlib import Path
    import subprocess
    _回收过期句柄()
    with 锁:
        现有句柄 = 全局模型索引.get(模型身份)
        现有连接 = 连接表.get(现有句柄) if 现有句柄 else None
        现有进程 = 本地进程表.get(现有句柄) if 现有句柄 else None
        if 现有连接 is not None and 现有进程 is not None and 现有进程.poll() is None:
            现有连接["最后活动时间"] = time.time()
            return 结果.成功结果({"句柄": 现有句柄, "模型类型": 类型, "模型路径": 规范路径,
                             "端口": 现有连接["配置"].get("端口"), "全局句柄": True,
                             "已复用": True,
                             "超时秒": 现有连接["超时秒"]})
        if 现有句柄:
            全局模型索引.pop(模型身份, None)
            连接表.pop(现有句柄, None)
            句柄系统.失效(int(现有句柄), "进程暴毙")
    端口 = _分配端口(端口)
    启动参数 = dict(参数 or {})
    if 类型 == "LLM":
        启动协议 = _规范化协议(启动参数.get("协议", 默认协议))
        if 启动协议 is None:
            return _失败("参数不合法", "协议必须是 chat_completions 或 codex_responses")
        启动参数["协议"] = 启动协议
    启动器名 = str(启动器 or "")
    if not isinstance(模型大小字节, (int, float)) or 模型大小字节 <= 0:
        模型大小字节 = _计算模型大小(模型路径) or None
    配置 = {"模型名": Path(规范路径).name, "提供者": "本地", "部署形态": "本地",
            "本地路径": 规范路径, "模型源格式": 源格式, "启动器": 启动器名, "模型类型": 类型,
            "模型大小字节": 模型大小字节, "端口": 端口, "url": f"http://127.0.0.1:{端口}/v1",
            "协议": 启动参数.get("协议", 默认协议) if 类型 == "LLM" else None}
    with 锁:
        守卫 = _内存守卫(类型, 配置)
        if 守卫 is not None:
            return 守卫
        对象 = 句柄系统.创建句柄(句柄类型=句柄类型_资源, 资源id=f"本地模型-{类型}", 所有者="")
        有效超时 = 超时秒 if isinstance(超时秒, int) and 超时秒 > 0 else _包申报超时()
        连接键 = _句柄键(对象.句柄id)
        连接表[连接键] = {"类型": 类型, "配置": dict(配置), "创建时间": time.time(),
                         "最后活动时间": time.time(), "超时秒": 有效超时, "释放函数": _终止本地进程,
                         "全局句柄": True, "模型身份": 模型身份}
        全局模型索引[模型身份] = 连接键
    try:
        命令 = _构建本地启动命令(规范路径, 类型, 启动器名, 端口, 启动参数)
        进程 = subprocess.Popen(命令, start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        本地进程表[连接键] = 进程
        句柄系统.登记资源(对象.句柄id, 资源类型="进程", PID=进程.pid, 端口=端口)
        if not _等待本地健康(端口, 有效超时):
            raise TimeoutError(f"本地模型启动后健康检查超时: {模型路径}")
        return 结果.成功结果({"句柄": 对象.句柄id, "模型类型": 类型, "模型路径": 规范路径,
                         "端口": 端口, "启动命令": 命令, "全局句柄": True,
                         "协议": 配置.get("协议") if 类型 == "LLM" else None,
                         "超时秒": 有效超时})
    except Exception as 错误:
        释放句柄(对象.句柄id)
        return _失败("提供者不可用", f"本地模型启动失败: {错误}")


def 启动本地模型(模型路径: str | None = None, 启动器: str | None = None, 模型类型: str | None = None,
                端口: int | None = None, 模型大小字节: int | None = None, 参数: dict | None = None, 超时秒: int | None = None) -> 结果:
    """串行启动本地模型；同一路径的后续请求由内部索引复用全局句柄。"""
    with 本地启动锁:
        return _启动本地模型(模型路径, 启动器, 模型类型, 端口, 模型大小字节, 参数, 超时秒)


def _终止本地进程(句柄id: int) -> bool:
    """释放句柄时终止整个本地模型进程组。

    进程表取出与状态迁移在同一锁内完成（防并发释放/过期回收/启动失败
    回滚重复 kill 或状态不一致）；实际 kill/wait 放锁外执行。
    """
    import os
    import signal
    import subprocess
    with 锁:
        进程 = 本地进程表.get(句柄id)
    if 进程 is None:
        return True
    try:
        if 进程.poll() is None:
            try:
                os.killpg(进程.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                进程.wait(timeout=5)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(进程.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                try:
                    进程.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    降级记录表.append(f"句柄 {句柄id} 本地模型进程强杀后仍未结束")
                    return False
        if 进程.poll() is None:
            return False
        with 锁:
            本地进程表.pop(句柄id, None)
        return True
    except Exception as 错误:
        降级记录表.append(str(错误))
        return False


def 注册本地进程(句柄: int | None = None, 进程对象: Any = None) -> 结果:
    """把真实拉起的子进程绑定到句柄，并登记到状态机统一回收（由适配层 Provider 调用）。"""
    if isinstance(句柄, bool) or not isinstance(句柄, int) or not 1 <= 句柄 <= 999999:
        return _失败("参数不合法", "句柄必须是1到999999的整数")
    连接 = 连接表.get(句柄)
    if 连接 is None:
        return _失败("句柄失效", f"句柄 {句柄} 不存在")
    if 进程对象 is None:
        if 本地进程表.get(句柄) is None:
            return _失败("进程未绑定", f"句柄 {句柄} 尚未绑定本地进程")
        return 结果.成功结果({"句柄": 句柄, "已绑定进程": True})
    本地进程表[句柄] = 进程对象
    # 登记到状态机（句柄体系）：进程资源，失效时统一回收
    try:
        pid = getattr(进程对象, "pid", None)
        端口 = 连接.get("配置", {}).get("端口")
        if isinstance(pid, int):
            句柄系统.登记资源(int(句柄), 资源类型="进程", PID=pid, 端口=端口 if isinstance(端口, int) else None)
    except Exception as 错误:
        降级记录表.append(str(错误))
    return 结果.成功结果({"句柄": 句柄, "已绑定进程": True})


# ── 句柄调用（持句柄使用模型）────────────────────────

def 生成对话(句柄: int | None = None, 消息列表: list = None,
           系统提示词: str = None, 流式输出: bool = False) -> 结果:
    if isinstance(句柄, bool) or not isinstance(句柄, int) or not 1 <= 句柄 <= 999999:
        return _失败("参数不合法", "句柄必须是1到999999的整数")
    if not isinstance(消息列表, list) or not 消息列表:
        return _失败("参数不合法", "消息列表必须是非空列表")
    if not isinstance(流式输出, bool):
        return _失败("参数不合法", "流式输出必须是逻辑型")
    return _调用模型(句柄, "LLM", {
        "消息列表": 消息列表, "系统提示词": 系统提示词, "流式输出": 流式输出,
    })


def 生成嵌入(句柄: int | None = None, 文本: str = None) -> 结果:
    if isinstance(句柄, bool) or not isinstance(句柄, int) or not 1 <= 句柄 <= 999999:
        return _失败("参数不合法", "句柄必须是1到999999的整数")
    if not isinstance(文本, str) or not 文本.strip():
        return _失败("参数不合法", "文本必须是非空字符串")
    return _调用模型(句柄, "向量", {"文本": 文本})


def 执行重排(句柄: int | None = None, 查询: str = None, 文档列表: list = None) -> 结果:
    if isinstance(句柄, bool) or not isinstance(句柄, int) or not 1 <= 句柄 <= 999999:
        return _失败("参数不合法", "句柄必须是1到999999的整数")
    if not isinstance(查询, str) or not 查询.strip():
        return _失败("参数不合法", "查询必须是非空字符串")
    if not isinstance(文档列表, list) or not 文档列表:
        return _失败("参数不合法", "文档列表必须是非空列表")
    return _调用模型(句柄, "重排", {"查询": 查询, "文档列表": 文档列表})


# ── 句柄生命周期 ──────────────────────────────────

def 续租句柄(句柄: int | None = None, 租约秒: int = None) -> 结果:
    if isinstance(句柄, bool) or not isinstance(句柄, int) or not 1 <= 句柄 <= 999999:
        return _失败("参数不合法", "句柄必须是1到999999的整数")
    连接, 原因 = _取连接(句柄)
    if 连接 is None:
        return _失败("句柄失效", 原因)
    with 锁:
        连接["最后活动时间"] = time.time()
        if isinstance(租约秒, int) and 租约秒 > 0:
            连接["超时秒"] = 租约秒
    return 结果.成功结果({"句柄": 句柄, "已续租": True, "超时秒": 连接["超时秒"]})


def 释放句柄(句柄: int | None = None) -> 结果:
    if isinstance(句柄, bool) or not isinstance(句柄, int) or not 1 <= 句柄 <= 999999:
        return _失败("参数不合法", "句柄必须是1到999999的整数")
    with 锁:
        连接 = 连接表.get(句柄)
        if 连接 is not None:
            if 连接.get("状态", "有效") == "释放中":
                return 结果.失败("资源释放中", "句柄已有释放请求，等待收敛后重试", 来源="模型连接器")
            连接["状态"] = "释放中"
            模型身份 = 连接.get("模型身份")
            if isinstance(模型身份, tuple):
                全局模型索引.pop(模型身份, None)
            释放函数 = 连接.get("释放函数")
        else:
            释放函数 = None
    if 连接 is not None:
        成功 = True
        try:
            if 释放函数:
                成功 = 释放函数(句柄) is not False
        except Exception as 错误:
            成功 = False
            降级记录表.append(f"句柄 {句柄} 显式释放失败: {错误}")
        with 锁:
            if 成功:
                连接表.pop(句柄, None)
                句柄系统.失效(int(句柄), "释放")
                return 结果.成功结果({"句柄": 句柄, "状态": "已结束并已释放", "已释放": True})
            现有 = 连接表.get(句柄)
            if 现有 is not None:
                现有["状态"] = "释放失败"
            return 结果.失败("资源未收敛", "结束请求已发出但未收敛，资源账本已保留供重试",
                            来源="模型连接器", 可重试=True,
                            详情={"句柄": 句柄, "状态": "结束请求已发出但未收敛"})
    return 结果.成功结果({"句柄": 句柄, "状态": "未找到且已幂等", "已释放": True,
                       "说明": "句柄不存在或已释放（幂等）"})


def 查询句柄状态(句柄: int | None = None) -> 结果:
    if isinstance(句柄, bool) or not isinstance(句柄, int) or not 1 <= 句柄 <= 999999:
        return _失败("参数不合法", "句柄必须是1到999999的整数")
    连接 = 连接表.get(句柄)
    if 连接 is None:
        有效, _ = 句柄系统.校验(int(句柄))
        return 结果.成功结果({"句柄": 句柄, "状态": "已失效" if not 有效 else "不存在", "连接类型": "", "剩余秒": 0})
    剩余 = max(0, int(连接["超时秒"] - (time.time() - 连接["最后活动时间"])))
    return 结果.成功结果({"句柄": 句柄, "状态": "有效", "连接类型": 连接["类型"],
                            "模型": 连接["配置"].get("模型名"), "部署形态": 连接["配置"].get("部署形态"),
                            "协议": 连接["配置"].get("协议") if 连接["类型"] == "LLM" else None,
                            "全局句柄": bool(连接.get("全局句柄")),
                            "剩余秒": 剩余})


def 资源快照() -> 结果:
    """返回资源快照：系统内存 + 活跃连接分布。"""
    _回收过期句柄()
    with 锁:
        分布 = {}
        for 连接 in 连接表.values():
            键 = f"{连接['类型']}({连接['配置'].get('部署形态') or '本地'})"
            分布[键] = 分布.get(键, 0) + 1
    内存 = _系统内存快照()
    return 结果.成功结果({"系统内存": 内存, "活跃连接": 分布, "连接总数": sum(分布.values()),
                            "内存安全阈值": 内存安全阈值, "说明": "系统内存占用超阈值时拒绝新连接"})


def 注册调用器(连接类型: str, 部署形态: str, 调用函数: Callable) -> None:
    """注册真实模型调用器；统一归一化本地/云端形态。"""
    形态 = "云端" if 部署形态 in ("cloud", "api", "云", "云端") else "本地"
    调用函数表[f"{连接类型}:{形态}"] = 调用函数
