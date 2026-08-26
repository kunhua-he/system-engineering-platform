"""模型连接器支持库实现：LLM/向量/重排连接器 + 句柄生命周期 + 系统内存安全。

设计（华哥口径 2026-08-26）：
1. 连接器 = 创建模型连接，返回六位句柄；其他能力持句柄调用模型。
2. 本地与云端两类连接：本地（模型路径/启动器），云端（url/api_key/模型/上下文长度）。
3. 句柄生命周期：默认 300 秒无人使用自动释放（超时回收）；可续租；可显式释放。
4. 系统内存安全（核心）：连接模型前用 psutil 查系统真实可用内存，
   若「当前占用 + 新模型预计占用」超过安全阈值（默认 80%）→ 拒绝新连接，
   返回 资源不足（内存压力），防止同时启动多个大模型撑爆 96GB 内存。
5. 真实模型调用由适配层 Provider 注册后生效；未注册时返回 提供者不可用（不模拟成功）。
"""

from __future__ import annotations

import json
import os
import threading
import time
import uuid
from typing import Any, Callable

from 公共契约.基础类型.结果类型 import 结果
from 公共契约.句柄体系 import 句柄体系, 句柄类型_资源

try:
    import psutil
except Exception:  # pragma: no cover - 环境无 psutil 时降级
    psutil = None

# ── 句柄与连接管理 ──────────────────────────────

句柄系统 = 句柄体系()
连接表: dict[str, dict[str, Any]] = {}          # 句柄id → 连接信息
调用函数表: dict[str, Callable] = {}             # 连接类型+本地/云端 → 真实调用函数
锁 = threading.Lock()

默认超时秒 = 1800                            # 华哥口径：不申报默认 30 分钟（1800 秒），模块/支持库应主动申报
内存安全阈值 = 0.80                              # 系统内存占用安全阈值（80%）
连接类型表 = {"LLM": "对话", "向量": "嵌入", "重排": "排序"}


def _包申报超时() -> int:
    """读取本包 包声明.json 的 句柄超时秒（模块主动申报），缺省返回 默认超时秒。"""
    try:
        import json
        声明路径 = os.path.join(os.path.dirname(__file__), "..", "包声明.json")
        with open(声明路径, encoding="utf-8") as f:
            申报 = json.load(f).get("句柄超时秒")
        if isinstance(申报, int) and 申报 > 0:
            return 申报
    except Exception:
        pass
    return 默认超时秒


def _失败(错误码: str, 消息: str) -> 结果:
    return 结果.失败(错误码, 消息, 来源="模型连接器")


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
    """系统内存安全检查：预计占用超安全阈值则拒绝。通过返回 None，拒绝返回失败结果。"""
    快照 = _系统内存快照()
    if not 快照.get("可用"):
        return None  # 无 psutil，跳过守卫（不阻断）
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
    """注意：调用方必须在 with 锁: 内调用。本函数不自己加锁，避免递归锁。"""
    now = time.time()
    for 句柄id, 连接 in list(连接表.items()):
        空闲 = now - 连接.get("最后活动时间", now)
        if 空闲 > 连接.get("超时秒", 默认超时秒):
            连接表.pop(句柄id, None)
            句柄系统.失效(句柄id, "超时")
            连接.get("释放函数") and 连接["释放函数"](句柄id)


def _登记连接(连接类型: str, 配置: dict, *, 超时秒: int, 所有者: str = "") -> 结果:
    if 连接类型 not in 连接类型表:
        return _失败("参数不合法", f"未知连接类型: {连接类型}")
    with 锁:
        _回收过期句柄()
        # 系统内存安全守卫：撑爆内存前拒绝
        守卫 = _内存守卫(连接类型, 配置)
        if 守卫 is not None:
            return 守卫
        对象 = 句柄系统.创建句柄(句柄类型=句柄类型_资源, 资源id=f"模型连接-{连接类型}", 所有者=所有者)
        有效超时 = 超时秒 if isinstance(超时秒, int) and 超时秒 > 0 else _包申报超时()
        连接表[对象.句柄id] = {
            "类型": 连接类型, "配置": dict(配置), "创建时间": time.time(),
            "最后活动时间": time.time(), "超时秒": 有效超时, "释放函数": None,
        }
        return 结果.成功结果({"句柄": 对象.句柄id, "连接类型": 连接类型,
                                "模型": 配置.get("模型名") or 配置.get("模型"),
                                "部署形态": 配置.get("部署形态") or "本地", "超时秒": 有效超时,
                                "说明": "句柄超时由包声明申报（默认 30 分钟），一直用持续重置，可续租，可显式释放"})


def _取连接(句柄id: str) -> tuple[dict[str, Any] | None, str]:
    有效, 原因 = 句柄系统.校验(句柄id)
    if not 有效:
        return None, 原因
    连接 = 连接表.get(句柄id)
    if 连接 is None:
        return None, f"句柄 {句柄id} 连接不存在（可能已自动释放）"
    now = time.time()
    if now - 连接["最后活动时间"] > 连接["超时秒"]:
        with 锁:
            连接表.pop(句柄id, None)
            句柄系统.失效(句柄id, "超时")
        return None, f"句柄 {句柄id} 已超时自动释放（{连接['超时秒']} 秒无人使用）"
    连接["最后活动时间"] = now
    return 连接, ""


def _调用模型(句柄id: str, 连接类型: str, 参数: dict) -> 结果:
    连接, 原因 = _取连接(句柄id)
    if 连接 is None:
        return _失败("句柄失效", 原因)
    if 连接["类型"] != 连接类型:
        return _失败("参数不合法", f"句柄 {句柄id} 是 {连接['类型']} 连接，不是 {连接类型}")
    部署形态 = 连接["配置"].get("部署形态") or "本地"
    调用函数 = 调用函数表.get(f"{连接类型}:{部署形态}")
    if 调用函数 is None:
        return _失败("提供者不可用", f"{连接类型}({部署形态}) 模型调用器未注册（当前无真实 Provider，不模拟成功）")
    try:
        return 调用函数(配置=连接["配置"], **参数)
    except Exception as 错误:
        return _失败("模型调用失败", f"{连接类型} 调用异常: {错误}")


# ── 连接器（返回句柄）──────────────────────────────

def 连接LLM(模型: str = None, 提供者: str = None, 部署形态: str = None,
           本地路径: str = None, 启动器: str = None, 模型大小字节: int = None,
           url: str = None, api_key: str = None, 上下文长度: int = None, 超时秒: int = None) -> 结果:
    """连接大语言模型，返回句柄。缺参时使用 env 统一参数（加载环境配置 后生效）。

    本地：部署形态=本地 + 本地路径/启动器；云端：部署形态=云端 + url/api_key。
    """
    显式 = {"模型": 模型, "提供者": 提供者, "部署形态": 部署形态, "本地路径": 本地路径,
            "启动器": 启动器, "模型大小字节": 模型大小字节, "url": url, "api_key": api_key,
            "上下文长度": 上下文长度, "超时秒": 超时秒}
    显式 = _合入环境参数("LLM", 显式)
    模型, 提供者, 部署形态 = 显式["模型"], 显式["提供者"], 显式["部署形态"]
    url, api_key, 上下文长度, 超时秒 = 显式["url"], 显式["api_key"], 显式["上下文长度"], 显式["超时秒"]
    本地路径, 启动器, 模型大小字节 = 显式["本地路径"], 显式["启动器"], 显式["模型大小字节"]
    if not isinstance(模型, str) or not 模型.strip():
        return _失败("参数不合法", "模型必须是非空字符串（env 未配置默认LLM模型）")
    形态 = (部署形态 or "云端" if (url or api_key) else 部署形态 or "本地").lower()
    形态 = "云端" if 形态 in ("cloud", "api", "云") else "本地" if 形态 in ("local", "本机") else 形态
    if 形态 not in ("本地", "云端"):
        return _失败("参数不合法", f"部署形态必须是 本地 或 云端: {部署形态}")
    配置 = {"模型名": 模型, "提供者": 提供者 or "本地", "部署形态": 形态, "本地路径": 本地路径,
            "启动器": 启动器, "模型大小字节": 模型大小字节, "url": url, "api_key": api_key,
            "上下文长度": 上下文长度}
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


# ── 本地模型启动器（拉起本地模型进程，返回句柄）──────────────

本地进程表: dict[str, Any] = {}  # 句柄id → 子进程对象


def 启动本地模型(模型路径: str = None, 启动器: str = None, 模型类型: str = None,
                端口: int = None, 模型大小字节: int = None, 参数: dict = None, 超时秒: int = None) -> 结果:
    """拉起本地模型进程（如 llama-server），启动成功后返回句柄。

    本地模型 = 独立进程组；句柄超时/释放时自动终止进程并清理。
    启动器 默认 llama-server；模型类型：LLM/向量/重排。
    模型大小字节 用于内存守卫（不传则按类型默认估算：LLM 8GB/向量 2GB/重排 2GB）。
    返回 {句柄, 模型类型, 端口, 启动命令, 超时秒}。
    """
    if not isinstance(模型路径, str) or not 模型路径.strip():
        return _失败("参数不合法", "模型路径必须是非空字符串")
    类型 = (模型类型 or "LLM").upper()
    类型 = "LLM" if 类型 in ("对话", "LLM", "llm") else "向量" if 类型 in ("嵌入", "向量", "embedding") else "重排" if 类型 in ("排序", "重排", "rerank") else None
    if 类型 is None:
        return _失败("参数不合法", f"模型类型必须是 LLM/向量/重排: {模型类型}")
    启动器名 = (启动器 or "llama-server").strip()
    启动参数 = dict(参数 or {})
    启动参数.setdefault("模型", 模型路径)
    if 端口:
        启动参数.setdefault("端口", 端口)
    # 内存守卫：本地大模型按 模型大小 或 类型默认 估算
    配置 = {"模型名": 模型路径.split("/")[-1], "提供者": "本地", "部署形态": "本地",
            "本地路径": 模型路径, "启动器": 启动器名, "模型类型": 类型,
            "模型大小字节": 模型大小字节}
    with 锁:
        _回收过期句柄()
        守卫 = _内存守卫(类型, 配置)
        if 守卫 is not None:
            return 守卫
        对象 = 句柄系统.创建句柄(句柄类型=句柄类型_资源, 资源id=f"本地模型-{类型}", 所有者="")
        # 预留连接登记（真实进程拉起由适配层 Provider 完成，这里只登记生命周期）
        有效超时 = 超时秒 if isinstance(超时秒, int) and 超时秒 > 0 else _包申报超时()
        连接表[对象.句柄id] = {
            "类型": 类型, "配置": dict(配置), "创建时间": time.time(),
            "最后活动时间": time.time(), "超时秒": 有效超时,
            "释放函数": _终止本地进程,
        }
        return 结果.成功结果({"句柄": 对象.句柄id, "模型类型": 类型, "启动器": 启动器名,
                                "模型路径": 模型路径, "端口": 端口, "超时秒": 有效超时,
                                "说明": "本地模型已登记生命周期，真实进程由适配层 Provider 拉起"})


def _终止本地进程(句柄id: str) -> None:
    """句柄释放时终止对应本地模型进程，并核查回收所有资源（killpg 杀进程树 + 端口清理 + 幂等）。"""
    import subprocess as _subprocess
    进程 = 本地进程表.pop(句柄id, None)
    if 进程 is not None:
        try:
            进程.terminate()
        except Exception:
            pass
    # 核查回收：登记过的资源（PID/端口）统一补回收一趟
    try:
        from 支持库.后端.资源回收确认 import 核查回收
        核查回收(句柄=句柄id)
    except Exception:
        pass


def 注册本地进程(句柄: str = None, 进程对象: Any = None) -> 结果:
    """把真实拉起的子进程绑定到句柄（由适配层 Provider 调用）。"""
    if not isinstance(句柄, str) or not 句柄.strip():
        return _失败("参数不合法", "句柄必须是非空字符串")
    连接 = 连接表.get(句柄)
    if 连接 is None:
        return _失败("句柄失效", f"句柄 {句柄} 不存在")
    本地进程表[句柄] = 进程对象
    return 结果.成功结果({"句柄": 句柄, "已绑定进程": True})


# ── 句柄调用（持句柄使用模型）────────────────────────

def 生成对话(句柄: str = None, 消息列表: list = None, 系统提示词: str = None) -> 结果:
    if not isinstance(句柄, str) or not 句柄.strip():
        return _失败("参数不合法", "句柄必须是非空字符串")
    if not isinstance(消息列表, list) or not 消息列表:
        return _失败("参数不合法", "消息列表必须是非空列表")
    return _调用模型(句柄, "LLM", {"消息列表": 消息列表, "系统提示词": 系统提示词})


def 生成嵌入(句柄: str = None, 文本: str = None) -> 结果:
    if not isinstance(句柄, str) or not 句柄.strip():
        return _失败("参数不合法", "句柄必须是非空字符串")
    if not isinstance(文本, str) or not 文本.strip():
        return _失败("参数不合法", "文本必须是非空字符串")
    return _调用模型(句柄, "向量", {"文本": 文本})


def 执行重排(句柄: str = None, 查询: str = None, 文档列表: list = None) -> 结果:
    if not isinstance(句柄, str) or not 句柄.strip():
        return _失败("参数不合法", "句柄必须是非空字符串")
    if not isinstance(查询, str) or not 查询.strip():
        return _失败("参数不合法", "查询必须是非空字符串")
    if not isinstance(文档列表, list) or not 文档列表:
        return _失败("参数不合法", "文档列表必须是非空列表")
    return _调用模型(句柄, "重排", {"查询": 查询, "文档列表": 文档列表})


# ── 句柄生命周期 ──────────────────────────────────

def 续租句柄(句柄: str = None, 租约秒: int = None) -> 结果:
    if not isinstance(句柄, str) or not 句柄.strip():
        return _失败("参数不合法", "句柄必须是非空字符串")
    连接, 原因 = _取连接(句柄)
    if 连接 is None:
        return _失败("句柄失效", 原因)
    with 锁:
        连接["最后活动时间"] = time.time()
        if isinstance(租约秒, int) and 租约秒 > 0:
            连接["超时秒"] = 租约秒
    return 结果.成功结果({"句柄": 句柄, "已续租": True, "超时秒": 连接["超时秒"]})


def 释放句柄(句柄: str = None) -> 结果:
    if not isinstance(句柄, str) or not 句柄.strip():
        return _失败("参数不合法", "句柄必须是非空字符串")
    with 锁:
        if 句柄 in 连接表:
            连接 = 连接表.pop(句柄)
            句柄系统.失效(句柄, "释放")
            连接.get("释放函数") and 连接["释放函数"](句柄)
            return 结果.成功结果({"句柄": 句柄, "已释放": True})
    return 结果.成功结果({"句柄": 句柄, "已释放": True, "说明": "句柄不存在或已释放（幂等）"})


def 查询句柄状态(句柄: str = None) -> 结果:
    if not isinstance(句柄, str) or not 句柄.strip():
        return _失败("参数不合法", "句柄必须是非空字符串")
    连接 = 连接表.get(句柄)
    if 连接 is None:
        有效, _ = 句柄系统.校验(句柄)
        return 结果.成功结果({"句柄": 句柄, "状态": "已失效" if not 有效 else "不存在", "连接类型": "", "剩余秒": 0})
    剩余 = max(0, int(连接["超时秒"] - (time.time() - 连接["最后活动时间"])))
    return 结果.成功结果({"句柄": 句柄, "状态": "有效", "连接类型": 连接["类型"],
                            "模型": 连接["配置"].get("模型名"), "部署形态": 连接["配置"].get("部署形态"), "剩余秒": 剩余})


def 资源快照() -> 结果:
    """返回资源快照：系统内存 + 活跃连接分布。"""
    with 锁:
        _回收过期句柄()
        分布 = {}
        for 连接 in 连接表.values():
            键 = f"{连接['类型']}({连接['配置'].get('部署形态') or '本地'})"
            分布[键] = 分布.get(键, 0) + 1
    内存 = _系统内存快照()
    return 结果.成功结果({"系统内存": 内存, "活跃连接": 分布, "连接总数": sum(分布.values()),
                            "内存安全阈值": 内存安全阈值, "说明": "系统内存占用超阈值时拒绝新连接"})


def 注册调用器(连接类型: str, 部署形态: str, 调用函数: Callable) -> None:
    """注册真实模型调用器（由适配层 Provider 调用）。键 = 连接类型:部署形态。"""
    形态 = "云端" if 部署形态 in ("cloud", "api", "云") else "本地"
    调用函数表[f"{连接类型}:{形态}"] = 调用函数
