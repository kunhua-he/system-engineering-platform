"""模型连接器支持库实现：LLM/向量/重排连接器 + 句柄生命周期 + 系统内存安全。

设计（华哥口径 2026-08-26）：
1. 连接器 = 创建模型连接，返回六位句柄；其他能力持句柄调用模型。
2. 本地与云端两类连接：本地传 GGUF 文件绝对路径，由底座直接调用 llama-server；云端传 url/api_key/模型/上下文长度。
3. 句柄生命周期：默认 1800 秒（30 分钟）无人使用自动释放（超时回收）；可续租；可显式释放。
4. 系统内存安全（核心）：连接模型前经「支持库.适配层.系统探针」的汉化原子能力
   《读取系统内存》查系统真实可用内存（第三方 psutil 只在适配层出现，支持库不直连），
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
from typing import Any, Callable, Iterator

from 公共契约.基础类型.结果类型 import 结果
from 公共契约.句柄体系 import 句柄体系, 句柄类型_资源
from 公共契约.运行时 import 平台适配, 进程终止

# ── 句柄与连接管理 ──────────────────────────────

句柄系统 = 句柄体系()
连接表: dict[int, dict[str, Any]] = {}          # 句柄id → 连接信息
调用函数表: dict[str, Callable] = {}             # 连接类型+本地/云端 → 真实调用函数
锁 = threading.Lock()

默认超时秒 = 1800                            # 华哥口径：不申报默认 30 分钟（1800 秒），模块/支持库应主动申报
内存安全阈值 = 0.80                              # 系统内存占用安全阈值（80%）
# 本地模型内存估算系数（2026-09-16 实测修正）：
#   Qwen3.6-27B-Q5_K_M.gguf 文件 18.5GB，加载完成（-c 8192 -ngl 99）后实测 RSS 19.7GB，
#   倍率 1.06。原实现按「文件大小 × 2」估算得 36.9GB，会把本机明明能跑的模型判成内存不足，
#   用户会误读成硬件不够。取 1.15 保留安全余量（覆盖 KV cache 与量化反量化缓冲）。
本地模型估算系数 = 1.15
连接类型表 = {"LLM": "对话", "向量": "嵌入", "重排": "排序"}
默认协议 = "chat_completions"
允许协议 = frozenset(("chat_completions", "codex_responses", "anthropic_messages"))
协议取值说明 = "协议必须是 chat_completions、codex_responses 或 anthropic_messages"
# 与 支持库/适配层/模型HTTP提供者.协议别名表 同表；测试中心.支持库.测试_模型协议别名
# 断言两份取值一致，防止漂移。
协议别名 = {
    "chat": "chat_completions",
    "chat_completions": "chat_completions",
    "res": "codex_responses",
    "codex_responses": "codex_responses",
    "anthropic": "anthropic_messages",
    "anthropic_messages": "anthropic_messages",
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
    """返回系统内存快照：总量/已用/可用/占用率（失败返回 可用=假，不伪造数字）。

    第三方只在适配层出现：本处经「支持库.适配层.系统探针」的汉化原子能力
    《读取系统内存》取真值，本实现不 import 任何第三方。探针不可用（未安装/
    适配层不可导入/取用异常）一律返回 可用=假，由 _内存守卫 fail-closed 拒绝新连接。
    """
    try:
        from 支持库.适配层.系统探针 import 读取系统内存
        快照 = 读取系统内存()
    except Exception as 错误:  # 适配层不可导入：与「探针不可用」同一语义，绝不静默放行
        降级记录表.append(f"系统内存探针不可用: {错误}")
        return {"可用": False, "说明": f"系统内存探针不可用，无法做系统内存检查: {错误}"}
    if not 快照.可用:
        return {"可用": False,
                "说明": 快照.不可用原因 or "系统内存探针不可用，无法做系统内存检查"}
    return {
        "可用": True,
        "总量字节": 快照.总量字节, "可用字节": 快照.可用字节, "已用字节": 快照.已用字节,
        "占用率": 快照.占用率,
        "说明": 快照.说明,
    }


def _预计占用(连接类型: str, 配置: dict) -> int:
    """估算一个新连接的内存占用（字节）。本地大模型按模型大小估算；云端按小头估算。"""
    部署形态 = 配置.get("部署形态") or "本地"
    if 部署形态 == "云端":
        return 512 * 1024 * 1024  # 云端连接占用小（512MB 预算）
    # 本地：优先按 模型大小 估算，否则按类型默认
    大小 = 配置.get("模型大小字节")
    if isinstance(大小, (int, float)) and 大小 > 0:
        # 估算系数可被调用方覆盖（内存估算系数），缺省用实测标定值
        系数 = 配置.get("内存估算系数")
        try:
            系数 = float(系数) if 系数 is not None else 本地模型估算系数
        except (TypeError, ValueError):
            系数 = 本地模型估算系数
        if 系数 <= 0:
            系数 = 本地模型估算系数
        return int(大小 * 系数)
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


默认HTTP请求超时秒 = 600
环境变量HTTP超时 = "模型HTTP_请求超时秒"


def _HTTP请求超时秒(配置: dict) -> float:
    """单次模型 HTTP 请求超时：配置优先，其次环境变量，默认 600 秒。

    原来硬编码 30 秒，长文本生成（逐字稿逐窗精校等）必然超时；
    30 秒对推理模型的千字级输出远远不够。
    """
    try:
        return float(配置.get("请求超时秒") or os.environ.get(环境变量HTTP超时) or 默认HTTP请求超时秒)
    except (TypeError, ValueError):
        return float(默认HTTP请求超时秒)


def _HTTP调用模型(连接类型: str, 配置: dict, 参数: dict) -> 结果:
    """URL连接的默认兼容调用器；与受管 Provider 保持同一协议契约。"""
    import json
    import urllib.error
    import urllib.request
    # 端点归一、anthropic 载荷、请求头可发送性三件事都由适配层唯一实现，
    # 此处延迟导入复用（适配层做响应归一化时也反查本模块，延迟导入避免环形依赖）。
    from 支持库.适配层.模型HTTP提供者 import (
        归一模型端点,
        构造anthropic载荷,
        检查不可发送请求头,
    )
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
        # 协议短值/长值必须与适配层同一裁决：`连接LLM` 存进配置的是归一后的长值，
        # 但直接调用本函数或配置手写短值（anthropic/chat/res）时也必须认，
        # 否则短值会静默落到 chat 分支（历史缺陷同类）。
        协议 = _规范化协议(配置.get("协议", 默认协议))
        if 协议 is None:
            return _失败("参数不合法", 协议取值说明)
        温度 = 参数.get("温度")
        最大令牌数 = 参数.get("最大令牌数")
        工具 = 参数.get("工具")
        响应格式 = 参数.get("响应格式")
        系统提示词 = 参数.get("系统提示词")
        if 协议 == "anthropic_messages":
            # anthropic 的 system 是顶层字段，不能作为 messages 里的 role；
            # 载荷构造复用适配层唯一实现（与流式侧同一份），不在此处另写一套映射。
            请求体, 载荷错误 = 构造anthropic载荷(
                配置, 消息, 系统提示词, 流式=False,
                温度=温度, 最大令牌数=最大令牌数, 工具=工具, 响应格式=响应格式,
            )
            if 载荷错误 or 请求体 is None:
                return _失败("参数不合法", 载荷错误 or "参数不合法")
            路径 = "/messages"
        else:
            if 系统提示词:
                消息.insert(0, {"role": "system", "content": 系统提示词})
            if 协议 == "codex_responses":
                路径, 请求体 = "/responses", {"model": 模型, "input": 消息, "stream": False}
                令牌键 = "max_output_tokens"
                if 响应格式:
                    请求体["text"] = {"format": 响应格式}
            else:
                路径, 请求体 = "/chat/completions", {"model": 模型, "messages": 消息, "stream": False}
                令牌键 = "max_tokens"
                if 响应格式:
                    请求体["response_format"] = 响应格式
                if 参数.get("chat_template_kwargs"):
                    请求体["chat_template_kwargs"] = 参数.get("chat_template_kwargs")
            if 温度 is not None:
                请求体["temperature"] = 温度
            if 最大令牌数 is not None:
                请求体[令牌键] = 最大令牌数
            if 工具:
                请求体["tools"] = 工具
    elif 连接类型 == "向量":
        路径, 请求体 = "/embeddings", {"model": 模型, "input": 参数.get("文本")}
    else:
        路径, 请求体 = "/rerank", {"model": 模型, "query": 参数.get("查询"), "documents": 参数.get("文档列表")}
    出站请求头 = {"Content-Type": "application/json"}
    if 配置.get("api_key"):
        if _规范化协议(配置.get("协议", 默认协议)) == "anthropic_messages":
            # anthropic 按协议规范走 x-api-key + 版本头，与适配层同一口径。
            from 支持库.适配层.模型HTTP提供者 import anthropic协议版本
            出站请求头["x-api-key"] = str(配置["api_key"])
            出站请求头["anthropic-version"] = anthropic协议版本
        else:
            出站请求头["Authorization"] = f"Bearer {配置['api_key']}"
    if isinstance(配置.get("额外请求头"), dict):
        出站请求头.update(配置["额外请求头"])
    if isinstance(参数.get("附加请求头"), dict):
        出站请求头.update(参数["附加请求头"])
    # 与适配层同一口径：HTTP 头只能承载 latin-1，非 ASCII 的密钥/头在此给出明确失败，
    # 不让它退化成笼统的「模型调用失败」。
    非法头 = 检查不可发送请求头(出站请求头)
    if 非法头:
        return _失败("参数不合法", 非法头)
    # 端点归一两层共用：url 不带 /v1 或已把后缀写全时，都能得到正确地址
    # （历史实现只做 基址 + 路径，url 不带 /v1 时整条链路必失败）。
    地址 = 归一模型端点(配置, 路径)
    if not 地址:
        return _失败("提供者不可用", f"{连接类型}连接未配置url")
    请求 = urllib.request.Request(
        地址, data=json.dumps(请求体, ensure_ascii=False).encode("utf-8"), method="POST",
        headers=出站请求头,
    )
    try:
        with urllib.request.urlopen(请求, timeout=_HTTP请求超时秒(配置)) as 响应:
            原始 = 响应.read(4 * 1024 * 1024 + 1)
            if len(原始) > 4 * 1024 * 1024:
                return _失败("超出限制", f"{连接类型} HTTP响应超过4MB上限")
            数据 = json.loads(原始.decode("utf-8"))
        if 连接类型 == "LLM":
            # 归一化：产出 内容/思考/工具调用/结束原因；保留 回复/用量 以兼容既有调用方
            归一 = _归一化响应体(数据, True)
            回复 = 归一.get("内容") or 数据.get("output_text")
            if not isinstance(回复, str):
                回复 = (((数据.get("choices") or [{}])[0].get("message") or {}).get("content"))
            if not isinstance(回复, str):
                回复 = ""
            if not 回复 and not 归一.get("工具调用"):
                return _失败("模型调用失败", "模型响应既没有可用文本也没有工具调用")
            值 = {"回复": 回复, "用量": 数据.get("usage", {}),
                  "内容": 归一.get("内容", ""), "思考": 归一.get("思考", ""),
                  "工具调用": 归一.get("工具调用", []), "结束原因": 归一.get("结束原因", "stop")}
            return 结果.成功结果(值)
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
           超时秒: int = None, 协议: str = 默认协议, 额外请求头: dict = None) -> 结果:
    """连接大语言模型，返回句柄。连接阶段只接受连接配置与协议参数；流式输出属于生成对话选项，未知关键字（包括连接阶段流式输出）由函数签名拒绝。

    缺参时使用 env 统一参数（加载环境配置后生效）。本地：部署形态=本地+GGUF 文件绝对路径，由底座直接启动 llama-server；云端：部署形态=云端+url/api_key/模型/上下文长度。
    额外请求头：连接级静态请求头，出站时叠加在内置头之上（生成对话的 附加请求头 可覆盖同名键）。
    """
    显式 = {"模型": 模型, "提供者": 提供者, "部署形态": 部署形态, "本地路径": 本地路径,
            "启动器": 启动器, "模型大小字节": 模型大小字节, "url": url, "api_key": api_key,
            "上下文长度": 上下文长度, "超时秒": 超时秒, "协议": 协议, "额外请求头": 额外请求头}
    显式 = _合入环境参数("LLM", 显式)
    模型, 提供者, 部署形态 = 显式["模型"], 显式["提供者"], 显式["部署形态"]
    url, api_key, 上下文长度, 超时秒 = (显式["url"], 显式["api_key"], 显式["上下文长度"],
                                       显式["超时秒"])
    规范协议 = _规范化协议(显式.get("协议", 默认协议))
    本地路径, 启动器, 模型大小字节 = 显式["本地路径"], 显式["启动器"], 显式["模型大小字节"]
    额外请求头 = 显式["额外请求头"]
    if not isinstance(模型, str) or not 模型.strip():
        return _失败("参数不合法", "模型必须是非空字符串（env 未配置默认LLM模型）")
    if 规范协议 is None:
        return _失败("参数不合法", 协议取值说明)
    if 额外请求头 is not None and not isinstance(额外请求头, dict):
        return _失败("参数不合法", "额外请求头必须是字典型或空值")
    协议 = 规范协议
    形态 = (部署形态 or "云端" if (url or api_key) else 部署形态 or "本地").lower()
    形态 = "云端" if 形态 in ("cloud", "api", "云") else "本地" if 形态 in ("local", "本机") else 形态
    if 形态 not in ("本地", "云端"):
        return _失败("参数不合法", f"部署形态必须是 本地 或 云端: {部署形态}")
    配置 = {"模型名": 模型, "提供者": 提供者 or "本地", "部署形态": 形态, "本地路径": 本地路径,
            "启动器": 启动器, "模型大小字节": 模型大小字节, "url": url, "api_key": api_key,
            "上下文长度": 上下文长度, "协议": 协议, "额外请求头": 额外请求头}
    if 形态 == "本地" and 本地路径:
        # 2026-09-17 修复（P0·阻塞生产）：原来 参数 只传了「协议」，调用方给的
        # 「上下文长度」在这一层就被丢掉 —— 于是下游 _构建本地启动命令 取不到它，
        # llama-server 永远以 -c 8192 启动。实测后果：逐字稿精校的裁决窗口输入
        # （证据包+提示词+底稿）远超 8192 tokens，模型回 500
        # `Context size has been exceeded.`，而调用方只看到「模型 HTTP 返回 500」。
        # 上下文长度是启动期参数，必须在这里带下去（协议一并保留）。
        return 启动本地模型(本地路径, 启动器, "LLM", 模型大小字节=模型大小字节,
                           参数={"协议": 协议, "上下文长度": 上下文长度}, 超时秒=超时秒)
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


# ── 统一环境参数（项目环境定义，支持库不独立传参）────────────

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
    """从项目环境文件读取统一模型参数。

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
        # 2026-09-16 实测修正：原顺序把 llama.cpp-old 排在 latest 前面。
        # 旧版二进制不支持新架构（实测 Qwen3.6-27B 的 SSM 张量
        # blk.64.ssm_conv1d.weight 缺失直接加载失败，报 missing tensor），
        # 而报错里看不出用了哪个二进制，极难定位——同一文件手动用 latest
        # 跑得好好的，经底座就失败，会被误判成权限或文件损坏。
        # 因此 latest 优先；需要走旧版时用 启动器 显式传绝对路径或设
        # 环境变量 LLAMA_CPP_SERVER_BIN。
        "llama.cpp-latest/build/bin/llama-server",
        "llama.cpp-old/build/bin/llama-server"))
    二进制 = next((路径 for 路径 in 候选二进制 if 路径 and os.path.isfile(路径) and os.access(路径, os.X_OK)), "")
    if not 二进制:
        raise FileNotFoundError("未找到 llama-server；请配置 LLAMA_CPP_SERVER_BIN")
    # 2026-09-17 修复（P0·阻塞生产）：「上下文长度」参数原来收了不用 —— 启动命令里
    # -c 是硬编码 8192。实测后果：直播逐字稿精校的裁决窗口输入（证据包 + 提示词 +
    # 底稿，实测单个窗口底稿 2400+ 字符）远超 8192 tokens，llama-server 直接回
    # 500 `Context size has been exceeded.`，而调用方只看到
    # 「模型调用失败: 模型 HTTP 返回 500」—— 极易误判成提示词或模型能力问题
    # （实测绕了两轮：先怀疑思考模式、再怀疑参数没透传）。
    # 现在按调用方给的 上下文长度 启动；未给或非法则保持原默认 8192（行为不变）。
    _上下文 = 参数.get("上下文长度")
    if isinstance(_上下文, bool) or not isinstance(_上下文, (int, str)):
        _上下文 = 8192
    else:
        try:
            _上下文 = int(_上下文)
        except (TypeError, ValueError):
            _上下文 = 8192
    if _上下文 <= 0:
        _上下文 = 8192
    命令 = [二进制, "-m", 模型路径, "--port", str(端口), "--sleep-idle-seconds", "300",
            "-c", str(_上下文), "-ngl", "99"]
    if 模型类型 == "向量":
        命令.extend(["--pooling", "cls", "--embeddings"])
    elif 模型类型 == "重排":
        命令.append("--rerank")
    额外参数 = 参数.get("启动参数列表")
    if isinstance(额外参数, list):
        命令.extend(str(值) for 值 in 额外参数)
    return 命令


def _启动日志路径(模型路径: str) -> str:
    """本地模型启动日志路径：工程缓存/模型日志/<模型名>.log。

    2026-09-16 实测背景：原来把 stdout/stderr 丢 DEVNULL，模型启动即退出时
    任务只能空转健康检查（上限 900 秒）后报一句「健康检查超时」，
    没有任何可用线索，必须人工用同款命令复现才拿得到日志。
    """
    from pathlib import Path
    from 公共契约.运行时.运行缓存 import 解析运行缓存根
    名字 = Path(模型路径).stem or "本地模型"
    # 2026-09-17 实测修复：原来直接拼 `<系统根>/工程缓存/模型日志`，制品态就是往不可变
    # 制品里写运行态（发布门禁「制品.摘要绑定」实测由绿转红，落点
    # `<制品>/平台客户端/工程缓存/模型日志/验证模型.log`）。改经唯一解析器：源码态仍是
    # `<系统根>/工程缓存/模型日志`（行为不变），制品态改道平台受管缓存。
    目录 = 解析运行缓存根(Path(__file__).resolve().parents[5]) / "模型日志"
    try:
        目录.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    return str(目录 / f"{名字}.log")


def _读启动日志尾部(模型路径: str, 行数: int = 12) -> str:
    """读启动日志尾部，供启动失败时随错误说明一并返回。"""
    try:
        with open(_启动日志路径(模型路径), "rb") as 文件:
            文件.seek(0, 2)
            大小 = 文件.tell()
            文件.seek(max(0, 大小 - 8192))
            文本 = 文件.read().decode("utf-8", "ignore")
        有效行 = [行.strip() for 行 in 文本.splitlines() if 行.strip()]
        if not 有效行:
            return ""
        return " | ".join(有效行[-行数:])[:1200]
    except OSError:
        return ""


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
            return _失败("参数不合法", 协议取值说明)
        启动参数["协议"] = 启动协议
    启动器名 = str(启动器 or "")
    if not isinstance(模型大小字节, (int, float)) or 模型大小字节 <= 0:
        模型大小字节 = _计算模型大小(模型路径) or None
    配置 = {"模型名": Path(规范路径).name, "提供者": "本地", "部署形态": "本地",
            "本地路径": 规范路径, "模型源格式": 源格式, "启动器": 启动器名, "模型类型": 类型,
            "模型大小字节": 模型大小字节, "端口": 端口, "url": f"http://127.0.0.1:{端口}/v1",
            "协议": 启动参数.get("协议", 默认协议) if 类型 == "LLM" else None}
    配置["内存估算系数"] = 启动参数.get("内存估算系数")
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
        # 启动日志落盘而非 DEVNULL：失败时可诊断（子进程持有独立 fd，
        # 父进程关闭文件对象不影响其继续写入）
        日志文件 = open(_启动日志路径(规范路径), "ab", buffering=0)
        try:
            表头 = ("\n" + "=" * 60 + "\n[启动] "
                    + time.strftime("%Y-%m-%d %H:%M:%S")
                    + "\n[命令] " + " ".join(命令) + "\n")
            日志文件.write(表头.encode("utf-8"))
        except OSError:
            pass
        try:
            进程 = subprocess.Popen(命令, **平台适配.子进程组启动标志(),
                                    stdout=日志文件, stderr=subprocess.STDOUT)
        finally:
            日志文件.close()
        本地进程表[连接键] = 进程
        句柄系统.登记资源(对象.句柄id, 资源类型="进程", PID=进程.pid, 端口=端口)
        if not _等待本地健康(端口, 有效超时):
            尾部 = _读启动日志尾部(规范路径)
            raise TimeoutError(
                f"本地模型启动后健康检查超时: {模型路径}（端口 {端口} 未在 "
                f"{min(max(10, 有效超时), 900)} 秒内就绪）"
                + (f"；启动日志尾部：{尾部}" if 尾部 else
                   "；启动日志为空，常见原因：端口被占用、模型文件损坏或启动器参数不被支持"))
        return 结果.成功结果({"句柄": 对象.句柄id, "模型类型": 类型, "模型路径": 规范路径,
                         "端口": 端口, "启动命令": 命令, "全局句柄": True,
                         "协议": 配置.get("协议") if 类型 == "LLM" else None,
                         "超时秒": 有效超时})
    except Exception as 错误:
        释放句柄(对象.句柄id)
        尾部 = _读启动日志尾部(规范路径)
        return _失败("提供者不可用", f"本地模型启动失败: {错误}"
                     + (f"；启动日志尾部：{尾部}" if 尾部 else ""))


def 启动本地模型(模型路径: str | None = None, 启动器: str | None = None, 模型类型: str | None = None,
                端口: int | None = None, 模型大小字节: int | None = None, 参数: dict | None = None, 超时秒: int | None = None) -> 结果:
    """串行启动本地模型；同一路径的后续请求由内部索引复用全局句柄。"""
    with 本地启动锁:
        return _启动本地模型(模型路径, 启动器, 模型类型, 端口, 模型大小字节, 参数, 超时秒)


def _终止本地进程(句柄id: int) -> bool:
    """释放句柄时终止整个本地模型进程组。

    进程表取出与状态迁移在同一锁内完成（防并发释放/过期回收/启动失败
    回滚重复终止或状态不一致）；实际终止与等待放锁外执行。
    进程组回收统一走 公共契约.运行时.进程终止.强制结束子进程（平台差异
    只在收口层判定，本调用点不写平台判断）。
    """
    with 锁:
        进程 = 本地进程表.get(句柄id)
    if 进程 is None:
        return True
    try:
        if 进程.poll() is None:
            回收结果 = 进程终止.强制结束子进程(进程, 宽限秒=5.0, 等待秒=5.0)
            if not 回收结果.成功:
                降级记录表.append(
                    f"句柄 {句柄id} 本地模型进程强杀后仍未结束（{回收结果.错误码}）：{回收结果.错误说明}")
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
           系统提示词: str = None, 流式输出: bool = False,
           温度: float = None, 最大令牌数: int = None,
           工具: list = None, 响应格式: dict = None,
           附加请求头: dict = None, chat_template_kwargs: dict = None) -> 结果:
    """持句柄生成对话。

    可选生成参数（温度/最大令牌数/工具/响应格式）按协议映射到上游请求体：
    codex_responses → temperature / max_output_tokens / tools / text.format；
    chat_completions → temperature / max_tokens / tools / response_format。
    不传则不下发该字段（由上游取默认值）。
    附加请求头：单次调用级请求头，仅本次出站叠加，可覆盖连接级 额外请求头 的同名键。
    """
    if isinstance(句柄, bool) or not isinstance(句柄, int) or not 1 <= 句柄 <= 999999:
        return _失败("参数不合法", "句柄必须是1到999999的整数")
    if not isinstance(消息列表, list) or not 消息列表:
        return _失败("参数不合法", "消息列表必须是非空列表")
    if 温度 is not None and (isinstance(温度, bool) or not isinstance(温度, (int, float))):
        return _失败("参数不合法", "温度必须是数值")
    if 最大令牌数 is not None and (isinstance(最大令牌数, bool) or not isinstance(最大令牌数, int)):
        return _失败("参数不合法", "最大令牌数必须是整数")
    if 工具 is not None and not isinstance(工具, list):
        return _失败("参数不合法", "工具必须是列表")
    if 响应格式 is not None and not isinstance(响应格式, dict):
        return _失败("参数不合法", "响应格式必须是字典型")
    if 附加请求头 is not None and not isinstance(附加请求头, dict):
        return _失败("参数不合法", "附加请求头必须是字典型或空值")
    if not isinstance(流式输出, bool):
        return _失败("参数不合法", "流式输出必须是逻辑型")
    if chat_template_kwargs is not None and not isinstance(chat_template_kwargs, dict):
        return _失败("参数不合法", "chat_template_kwargs 必须是字典型或空值")
    return _调用模型(句柄, "LLM", {
        "消息列表": 消息列表, "系统提示词": 系统提示词, "流式输出": 流式输出,
        "温度": 温度, "最大令牌数": 最大令牌数, "工具": 工具, "响应格式": 响应格式,
        "附加请求头": 附加请求头, "chat_template_kwargs": chat_template_kwargs,
    })


def _流式错误事件(错误码: str, 错误说明: str, *, 可重试: bool = False,
               **详情: Any) -> dict[str, Any]:
    事件: dict[str, Any] = {
        "类型": "错误", "错误码": 错误码, "错误说明": 错误说明,
        "可重试": 可重试,
    }
    事件.update(详情)
    return 事件


def 流式生成对话(句柄: int | None = None, 消息列表: list = None,
               系统提示词: str = None, 流式输出: bool = True,
               温度: float = None, 最大令牌数: int = None,
               工具: list = None, 响应格式: dict = None,
               附加请求头: dict = None,
               chat_template_kwargs: dict = None) -> Iterator[dict[str, Any]]:
    """按句柄配置调用 H 节点 Provider，并原样转发有限流式事件。

    这是连接器内部/包级流式边界，不是 HTTP 路由。流式输出必须显式保持为
    True；Provider 事件不聚合，返回的迭代器应消费至终态或由调用方 close。
    生成参数 温度/最大令牌数/工具/响应格式 与 `生成对话` 非流式侧同名同义同校验，
    经 Provider 按协议映射进流式载荷；不传即不下发。
    附加请求头：单次调用级请求头，仅本次流式出站叠加，覆盖连接级同名键。
    """
    if isinstance(句柄, bool) or not isinstance(句柄, int) or not 1 <= 句柄 <= 999999:
        return iter((_流式错误事件("参数不合法", "句柄必须是1到999999的整数"),))
    if not isinstance(消息列表, list) or not 消息列表:
        return iter((_流式错误事件("参数不合法", "消息列表必须是非空列表"),))
    if not isinstance(流式输出, bool):
        return iter((_流式错误事件("参数不合法", "流式输出必须是逻辑型"),))
    if not 流式输出:
        return iter((_流式错误事件("参数不合法", "流式生成对话要求流式输出为真"),))
    if 温度 is not None and (isinstance(温度, bool) or not isinstance(温度, (int, float))):
        return iter((_流式错误事件("参数不合法", "温度必须是数值"),))
    if 最大令牌数 is not None and (isinstance(最大令牌数, bool) or not isinstance(最大令牌数, int)):
        return iter((_流式错误事件("参数不合法", "最大令牌数必须是整数"),))
    if 工具 is not None and not isinstance(工具, list):
        return iter((_流式错误事件("参数不合法", "工具必须是列表"),))
    if 响应格式 is not None and not isinstance(响应格式, dict):
        return iter((_流式错误事件("参数不合法", "响应格式必须是字典型"),))
    if 附加请求头 is not None and not isinstance(附加请求头, dict):
        return iter((_流式错误事件("参数不合法", "附加请求头必须是字典型或空值"),))
    if chat_template_kwargs is not None and not isinstance(chat_template_kwargs, dict):
        return iter((_流式错误事件("参数不合法", "chat_template_kwargs 必须是字典型或空值"),))

    连接, 原因 = _取连接(句柄)
    if 连接 is None:
        return iter((_流式错误事件("句柄失效", 原因),))
    if 连接.get("类型") != "LLM":
        return iter((_流式错误事件(
            "不支持流式连接类型", f"句柄 {句柄} 是 {连接.get('类型')} 连接，流式生成对话只支持 LLM",
        ),))

    配置 = dict(连接.get("配置") or {})
    try:
        from 支持库.适配层 import 模型HTTP提供者 as 提供者
        上游迭代器 = 提供者.流式调用对话(
            配置=配置, 消息列表=消息列表, 系统提示词=系统提示词,
            温度=温度, 最大令牌数=最大令牌数,
            工具=工具, 响应格式=响应格式,
            附加请求头=附加请求头,
            chat_template_kwargs=chat_template_kwargs,
        )
    except Exception as 错误:
        return iter((_流式错误事件(
            "模型流式调用失败", f"调用 Provider 流式对话失败：{错误}",
            异常类型=type(错误).__name__,
        ),))

    def 转发() -> Iterator[dict[str, Any]]:
        try:
            yield from 上游迭代器
        except Exception as 错误:
            yield _流式错误事件(
                "模型流式调用失败", f"Provider 流式迭代异常：{错误}",
                异常类型=type(错误).__name__,
            )

    return 转发()


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


def 循环软护栏(*, 历史调用: list = None, 工具名: str = None, 阈值档位: list = None) -> 结果:
    """检测重复工具调用并注入软提醒（DeepSeek repeat-tool-reminder 模式化落地）。

    参数:
        历史调用: 历史工具调用名列表（按时间顺序）
        工具名: 当前准备调用的工具名（可空，空则统计全部）
        阈值档位: 提醒触发阈值列表，默认 [3, 5, 8]

    行为: 不硬杀、不静默——同工具连续调用次数达到阈值档位时，返回提醒文本注入下一轮，
    把纠错权交给模型。返回 {触发: bool, 连续次数, 提醒文本, 阈值档位}。
    """
    try:
        历史 = list(历史调用 or [])
        档位 = list(阈值档位 or [3, 5, 8])
        if not 历史:
            return 结果.成功结果({"触发": False, "连续次数": 0, "提醒文本": "", "阈值档位": 档位})
        # 统计指定工具（或全部工具）的连续调用次数
        if 工具名:
            目标列表 = [名 for 名 in 历史 if 名 == 工具名]
        else:
            # 无指定工具时统计最近一个工具的连续次数
            目标列表 = 历史
        if not 目标列表:
            return 结果.成功结果({"触发": False, "连续次数": 0, "提醒文本": "", "阈值档位": 档位})
        最近工具 = 目标列表[-1]
        连续次数 = 0
        for 名 in reversed(目标列表):
            if 名 == 最近工具:
                连续次数 += 1
            else:
                break
        # 找最大命中档位
        命中档位 = None
        for 阈值 in sorted(档位):
            if 连续次数 >= 阈值:
                命中档位 = 阈值
        if 命中档位 is None:
            return 结果.成功结果({"触发": False, "连续次数": 连续次数, "提醒文本": "", "阈值档位": 档位})
        提醒文本 = (
            f"【软护栏提醒】工具「{最近工具}」已连续调用 {连续次数} 次（达到阈值 {命中档位}）。"
            "请确认是否陷入循环：若无新进展请换策略或停止，不要重复调用同一工具。"
        )
        return 结果.成功结果({
            "触发": True, "连续次数": 连续次数, "提醒文本": 提醒文本, "阈值档位": 档位,
        })
    except Exception as 异常:
        return 结果.失败("软护栏检查失败", str(异常), 来源="模型连接器")



# ═══════════════════════════════════════════════
# 工具并行调度：DeepSeek tool-calls 调度闭环模式化落地
# exclusive 调用成屏障（前后串行）；parallel 调用进有界池（默认10）；
# 分配并发但结果严格按 model 顺序提交（seq 关联）；取消合成 TOOL_ABORTED 错误结果。
# 0加密0限制：只做调度编排，不执行工具，脱敏由业务端自理。
# ═══════════════════════════════════════════════
调度默认并行上限 = 10


def 调度工具调用(*, 工具调用列表: list = None, 并行上限: int = None) -> 结果:
    """生成工具调用调度计划。返回 {批次列表, 顺序, 并行上限}。

    工具调用项: {"调用id", "工具名", "参数", "独占": bool}
    返回批次: 每批 = {"类型": "串行屏障"|"并行批", "调用列表": [...]}
    结果顺序 = 输入顺序（DeepSeek 按 model 序提交）。
    """
    try:
        if not isinstance(工具调用列表, list) or not 工具调用列表:
            return 结果.失败("参数不合法", "工具调用列表必须是非空列表", 来源="模型连接器")
        上限 = max(1, min(int(并行上限 or 调度默认并行上限), 100))
        批次列表 = []
        当前并行批 = []
        for 项 in 工具调用列表:
            if not isinstance(项, dict) or "调用id" not in 项 or "工具名" not in 项:
                return 结果.失败("参数不合法", f"工具调用项必须含 调用id/工具名: {项}", 来源="模型连接器")
            独占 = bool(项.get("独占", False))
            if 独占:
                # 先清空未满并行批
                if 当前并行批:
                    批次列表.append({"类型": "并行批", "调用列表": 当前并行批})
                    当前并行批 = []
                批次列表.append({"类型": "串行屏障", "调用列表": [项]})
            else:
                当前并行批.append(项)
                if len(当前并行批) >= 上限:
                    批次列表.append({"类型": "并行批", "调用列表": 当前并行批})
                    当前并行批 = []
        if 当前并行批:
            批次列表.append({"类型": "并行批", "调用列表": 当前并行批})
        # 结果顺序 = 输入顺序
        结果顺序 = [项["调用id"] for 项 in 工具调用列表]
        return 结果.成功结果({
            "批次列表": 批次列表,
            "结果顺序": 结果顺序,
            "并行上限": 上限,
            "总调用数": len(工具调用列表),
            "批次数": len(批次列表),
        })
    except Exception as 异常:
        return 结果.失败("调度失败", str(异常), 来源="模型连接器")


def 合成取消结果(*, 调用id: str = None, 工具名: str = None, 原因: str = None) -> 结果:
    """合成取消/未启动调用的错误结果。

    对外错误码一律中文（决策 0003）：`派发前已取消`——语义对齐上游 DeepSeek 的
    TOOL_ABORTED_BEFORE_DISPATCH；合成结果随工具回执回给模型，不落网关错误码表。
    """
    try:
        if not isinstance(调用id, str) or not 调用id.strip():
            return 结果.失败("参数不合法", "调用id不能为空", 来源="模型连接器")
        原因值 = str(原因 or "调度前已取消")
        return 结果.成功结果({
            "调用id": 调用id, "工具名": str(工具名 or ""),
            "合成结果": {"错误码": "派发前已取消", "原因": 原因值},
            "未执行": True,
        })
    except Exception as 异常:
        return 结果.失败("合成取消结果失败", str(异常), 来源="模型连接器")



# ═══════════════════════════════════════════════
# 重试调度：按错误码白名单/兜底模式判定是否重试，并给出带抖动的指数退避秒数。
# 纯计算、只读；不发起任何模型、网络或工具调用。
# ═══════════════════════════════════════════════
默认最大重试次数 = 3
默认退避基数秒 = 0.5
默认抖动比例 = 0.1
重试最大上限 = 100            # 最大重试次数上限（防止退避指数溢出）
退避最大秒 = 300.0            # 单次退避秒数硬上限
重试模式别名 = {
    "1": 1, "normal": 1, "白名单": 1,
    "2": 2, "always": 2, "兜底": 2,
}


def _归一化重试模式(值: Any) -> int | None:
    """把重试模式归一化为 1（normal 白名单）或 2（always 兜底）；非法返回 None。"""
    if isinstance(值, int) and not isinstance(值, bool) and 值 in (1, 2):
        return 值
    if isinstance(值, str):
        return 重试模式别名.get(值.strip())
    return None


def 重试调度(*, 重试模式: Any = None, 错误码白名单: list | None = None,
             实际错误码: Any = None,
             最大重试次数: int | None = None, 退避基数秒: Any = None,
             抖动比例: Any = None) -> 结果:
    """根据错误码白名单与重试模式判定是否重试，并算出带抖动的指数退避秒数。

    参数:
        重试模式: 1=normal 白名单（仅白名单命中才重试）/2=always 兜底（无条件重试）
        错误码白名单: 可重试错误码列表（模式1 生效，空即不命中）
        实际错误码: 本次真实错误码（**可选**）。传了则模式1 按「实际错误码 ∈ 白名单」判定命中；
                    不传则沿用旧行为（白名单非空即重试），保证既有调用方与场景零影响
        最大重试次数: 重试次数上限，默认 3
        退避基数秒: 指数退避基数秒，默认 0.5
        抖动比例: 退避上浮比例，默认 0.1（确定性上浮，测试可复现）

    返回 {是否重试: bool, 下次退避秒: float, 原因: str}；退避计划全文写入 原因。
    第 i 次重试退避 = 退避基数秒 × 2^i × (1 + 抖动比例)，单次上限 300 秒。
    """
    try:
        模式 = _归一化重试模式(重试模式)
        if 模式 is None:
            return _失败("参数不合法", "重试模式必须是 1(normal 白名单) 或 2(always 兜底)")
        if isinstance(最大重试次数, bool) or (
                最大重试次数 is not None and not isinstance(最大重试次数, int)):
            return _失败("参数不合法", "最大重试次数必须是整数")
        上限次数 = 默认最大重试次数 if 最大重试次数 is None else 最大重试次数
        if 上限次数 < 0 or 上限次数 > 重试最大上限:
            return _失败("参数不合法", f"最大重试次数必须在 0 到 {重试最大上限} 之间")
        if isinstance(退避基数秒, bool) or (
                退避基数秒 is not None and not isinstance(退避基数秒, (int, float))):
            return _失败("参数不合法", "退避基数秒必须是数值")
        基数 = 默认退避基数秒 if 退避基数秒 is None else float(退避基数秒)
        if 基数 <= 0:
            return _失败("参数不合法", "退避基数秒必须大于 0")
        if isinstance(抖动比例, bool) or (
                抖动比例 is not None and not isinstance(抖动比例, (int, float))):
            return _失败("参数不合法", "抖动比例必须是数值")
        抖动 = 默认抖动比例 if 抖动比例 is None else float(抖动比例)
        if 抖动 < 0 or 抖动 > 1:
            return _失败("参数不合法", "抖动比例必须在 0 到 1 之间")
        if 错误码白名单 is None:
            白名单列表: list[str] = []
        elif isinstance(错误码白名单, list):
            if any(not isinstance(项, str) or not 项.strip() for 项 in 错误码白名单):
                return _失败("参数不合法", "错误码白名单的元素必须是非空文本")
            白名单列表 = [项.strip() for 项 in 错误码白名单]
        else:
            return _失败("参数不合法", "错误码白名单必须是列表")
        if 实际错误码 is not None and (not isinstance(实际错误码, str) or not 实际错误码.strip()):
            return _失败("参数不合法", "实际错误码必须是文本（可选；不传沿用旧行为）")

        # 条件判定：模式2 兜底无条件重试；模式1 只有白名单命中才重试
        if 模式 == 2:
            是否重试 = 上限次数 > 0
            原因 = (f"always 兜底模式：忽略错误码白名单无条件重试（上限 {上限次数} 次）"
                    if 是否重试 else "always 兜底模式：最大重试次数为 0，不重试")
        else:
            if 实际错误码 is None:
                # 旧行为（未传 实际错误码）：白名单非空即重试 —— 保持向后兼容
                是否重试 = bool(白名单列表) and 上限次数 > 0
                if 上限次数 <= 0:
                    原因 = "normal 白名单模式：最大重试次数为 0，不重试"
                elif 是否重试:
                    原因 = f"白名单命中：可重试错误码 {白名单列表}（上限 {上限次数} 次）"
                else:
                    原因 = "白名单未命中：错误码白名单为空，不重试"
            else:
                # 新行为（传了 实际错误码）：按「实际错误码 ∈ 白名单」判定真正的命中
                命中 = 实际错误码.strip() in 白名单列表
                是否重试 = 命中 and 上限次数 > 0
                if 上限次数 <= 0:
                    原因 = f"normal 白名单模式：最大重试次数为 0，不重试（实际错误码 {实际错误码}）"
                elif 命中:
                    原因 = (f"白名单命中：实际错误码 {实际错误码} 在可重试集合 {白名单列表} 内"
                            f"（上限 {上限次数} 次）")
                else:
                    原因 = (f"白名单未命中：实际错误码 {实际错误码} 不在可重试集合 "
                            f"{白名单列表} 内，不重试")

        if not 是否重试:
            return 结果.成功结果({"是否重试": False, "下次退避秒": 0.0, "原因": 原因})

        # 带抖动的指数退避计划：第 i 次重试 = 基数 × 2^i × (1 + 抖动比例)
        退避计划 = [round(min(基数 * (2 ** 序号) * (1 + 抖动), 退避最大秒), 6)
                    for 序号 in range(上限次数)]
        return 结果.成功结果({
            "是否重试": True,
            "下次退避秒": 退避计划[0],
            "原因": f"{原因}；退避计划={退避计划}",
        })
    except Exception as 异常:
        return 结果.失败("重试调度失败", str(异常), 来源="模型连接器")


# ═══════════════════════════════════════════════
# 组装可用工具清单：按门控模式过滤/排序调用方传入的工具清单。
# 不内嵌任何业务角色判断——清单全部由调用方传入，本能力只做纯计算去重与排序。
# ═══════════════════════════════════════════════
门控模式别名 = {
    "1": 1, "全量": 1, "all": 1,
    "2": 2, "显式清单": 2, "显式列表": 2, "显式": 2,
}
工具名键表 = ("名称", "工具名", "tool", "name")


def _归一化门控模式(值: Any) -> int | None:
    """把门控模式归一化为 1（全量）或 2（显式清单）；非法返回 None。"""
    if isinstance(值, int) and not isinstance(值, bool) and 值 in (1, 2):
        return 值
    if isinstance(值, str):
        return 门控模式别名.get(值.strip())
    return None


def _取工具名(项: Any) -> str | None:
    """从工具项提取工具名：文本直接取；字典取 名称/工具名；其他返回 None。"""
    if isinstance(项, str):
        return 项.strip() or None
    if isinstance(项, dict):
        for 键 in 工具名键表:
            值 = 项.get(键)
            if isinstance(值, str) and 值.strip():
                return 值.strip()
    return None


def 组装可用工具清单(*, 门控模式: Any = None, 全部工具清单: list | None = None,
                     可用工具清单: list | None = None) -> 结果:
    """按门控模式过滤并排序工具清单，不内嵌任何业务角色判断（清单由调用方传入）。

    参数:
        门控模式: 1=全量（返回全部）/2=显式清单（只返回可用清单命中的工具）
        全部工具清单: 调用方传入的全量工具清单（文本或含 名称/工具名 的字典）
        可用工具清单: 显式可用工具清单（门控模式=2 生效）

    返回 {工具清单: list[str], 数量: int}；按工具名去重（保序）后升序排序，稳定可复现。
    """
    try:
        模式 = _归一化门控模式(门控模式)
        if 模式 is None:
            return _失败("参数不合法", "门控模式必须是 1(全量) 或 2(显式清单)")
        if not isinstance(全部工具清单, list):
            return _失败("参数不合法", "全部工具清单必须是列表")
        全量名表: list[str] = []
        for 项 in 全部工具清单:
            名 = _取工具名(项)
            if 名 is None:
                return _失败("参数不合法",
                             f"全部工具清单的元素必须是文本或含 名称/工具名 的字典: {项!r}")
            全量名表.append(名)
        全量去重 = list(dict.fromkeys(全量名表))       # 去重且保序
        if 模式 == 1:
            结果名表 = 全量去重
        else:
            显式清单 = 可用工具清单 if 可用工具清单 is not None else []
            if not isinstance(显式清单, list):
                return _失败("参数不合法", "可用工具清单必须是列表")
            可用名表: list[str] = []
            for 项 in 显式清单:
                名 = _取工具名(项)
                if 名 is None:
                    return _失败("参数不合法",
                                 f"可用工具清单的元素必须是文本或含 名称/工具名 的字典: {项!r}")
                可用名表.append(名)
            允许集 = set(可用名表)
            结果名表 = [名 for 名 in 全量去重 if 名 in 允许集]
        结果名表 = sorted(结果名表)
        return 结果.成功结果({"工具清单": 结果名表, "数量": len(结果名表)})
    except Exception as 异常:
        return 结果.失败("组装工具清单失败", str(异常), 来源="模型连接器")

# ── 模型响应归一化（迁移自 V3 网关适配器；支持 4 种协议） ──────────────

_流事件类型_令牌 = "令牌"
_流事件类型_思考中 = "思考中"
_流事件类型_完成 = "完成"
_流事件类型_错误 = "错误"
_流事件类型_工具调用 = "工具调用"


def _归一化用量(原始数据: dict):
    """提取用量：兼容 prompt_tokens/completion_tokens 与 input_tokens/output_tokens 两套命名。"""
    用量数据 = 原始数据.get("usage")
    if not isinstance(用量数据, dict):
        return None
    输入令牌 = 用量数据.get("prompt_tokens") or 用量数据.get("input_tokens") or 0
    输出令牌 = 用量数据.get("completion_tokens") or 用量数据.get("output_tokens") or 0
    if isinstance(输入令牌, bool) or isinstance(输出令牌, bool):
        return None
    if not isinstance(输入令牌, int) or not isinstance(输出令牌, int):
        return None
    if 输入令牌 <= 0 and 输出令牌 <= 0:
        return None
    return {"提示词令牌数": 输入令牌, "补全令牌数": 输出令牌, "总令牌数": 输入令牌 + 输出令牌}


def _归一化工具调用(消息: dict) -> list:
    """把 message.tool_calls 归一化：arguments 字符串 JSON 解析为对象。"""
    import json as _json
    结果 = []
    for 调用 in (消息 or {}).get("tool_calls") or []:
        if not isinstance(调用, dict):
            continue
        函数 = 调用.get("function") or {}
        参数 = 函数.get("arguments", {})
        if isinstance(参数, str):
            try:
                参数 = _json.loads(参数)
            except Exception:
                参数 = {}
        结果.append({"id": 调用.get("id", ""), "type": "function",
                     "function": {"name": 函数.get("name", ""), "arguments": 参数}})
    return 结果


def _归一化响应体(原始数据: dict, 包含思考: bool) -> dict:
    """把 4 种协议的原始响应归一化成统一结构。"""
    用量 = _归一化用量(原始数据)

    # ① codex_responses：object=response 或 output 是列表
    if 原始数据.get("object") == "response" or isinstance(原始数据.get("output"), list):
        内容片段, 思考片段 = [], []
        for 条目 in 原始数据.get("output") or []:
            if not isinstance(条目, dict):
                continue
            条目类型 = 条目.get("type")
            if 条目类型 == "reasoning" and 包含思考:
                for 摘要 in 条目.get("summary") or []:
                    if isinstance(摘要, dict) and 摘要.get("text"):
                        思考片段.append(str(摘要["text"]))
                continue
            if 条目类型 != "message":
                continue
            for 片段 in 条目.get("content") or []:
                if not isinstance(片段, dict):
                    continue
                if 片段.get("type") in {"output_text", "text"} and 片段.get("text") is not None:
                    内容片段.append(str(片段["text"]))
        结束原因 = "stop"
        if 原始数据.get("status") and 原始数据.get("status") != "completed":
            结束原因 = str(原始数据.get("status"))
        return {"内容": "\n".join(x for x in 内容片段 if x),
                "思考": "\n".join(x for x in 思考片段 if x),
                "工具调用": [], "结束原因": 结束原因, "用量": 用量}

    # ② anthropic：content[] 是块数组
    if isinstance(原始数据.get("content"), list) and not 原始数据.get("choices"):
        内容片段, 思考片段, 工具调用 = [], [], []
        for 块 in 原始数据.get("content") or []:
            if not isinstance(块, dict):
                continue
            块类型 = 块.get("type")
            if 块类型 == "text" and 块.get("text") is not None:
                内容片段.append(str(块["text"]))
            elif 块类型 == "thinking" and 包含思考 and 块.get("thinking"):
                思考片段.append(str(块["thinking"]))
            elif 块类型 == "tool_use":
                工具调用.append({"id": 块.get("id", ""), "type": "function",
                                 "function": {"name": 块.get("name", ""),
                                              "arguments": 块.get("input") or {}}})
        停止原因 = 原始数据.get("stop_reason") or "stop"
        return {"内容": "".join(内容片段),
                "思考": "\n".join(x for x in 思考片段 if x),
                "工具调用": 工具调用,
                "结束原因": "tool_calls" if 停止原因 == "tool_use" else "stop",
                "用量": 用量}

    # ③ ollama：message.content
    if isinstance(原始数据.get("message"), dict) and not 原始数据.get("choices"):
        消息 = 原始数据.get("message") or {}
        return {"内容": str(消息.get("content") or ""),
                "思考": str(消息.get("reasoning_content") or "") if 包含思考 else "",
                "工具调用": _归一化工具调用({"tool_calls": 消息.get("tool_calls")}),
                "结束原因": str(原始数据.get("done_reason") or "stop"), "用量": 用量}

    # ④ chat_completions：choices[0].message
    选项列表 = 原始数据.get("choices") or []
    选项 = 选项列表[0] if 选项列表 and isinstance(选项列表[0], dict) else {}
    消息 = 选项.get("message") or {}
    return {"内容": str(消息.get("content") or ""),
            "思考": str(消息.get("reasoning_content") or "") if 包含思考 else "",
            "工具调用": _归一化工具调用(消息),
            "结束原因": str(选项.get("finish_reason") or "stop"),
            "用量": 用量}


def 归一化对话响应(原始数据: dict = None, 包含思考: bool = False) -> 结果:
    """把模型原始响应归一化为统一结构。

    支持 4 种协议，按响应形状自动判别：
    - codex_responses（object=response 或 output 是列表）
    - anthropic（content[] 块数组）
    - ollama（message.content）
    - chat_completions（choices[0].message）

    返回 {内容, 思考, 工具调用, 结束原因, 用量}；纯计算、无状态。
    """
    if not isinstance(原始数据, dict):
        return _失败("参数不合法", "原始数据必须是字典型")
    if not isinstance(包含思考, bool):
        return _失败("参数不合法", "包含思考必须是逻辑型")
    try:
        return 结果.成功结果(_归一化响应体(原始数据, 包含思考))
    except Exception as 错误:
        return _失败("归一化失败", f"响应形状无法识别: {错误}")


def _归一化分块体(分块: dict, 包含思考: bool):
    """把流式单块归一化成统一事件；结构事件返回 None（跳过）。"""
    类型 = 分块.get("type")

    # ① codex_responses 流式：response.* 事件
    if isinstance(类型, str) and 类型.startswith("response."):
        if 类型 == "response.output_text.delta":
            增量 = 分块.get("delta")
            return {"类型": _流事件类型_令牌, "内容": str(增量), "工具调用": [], "用量": None} if 增量 else None
        if 类型 == "response.reasoning_summary_text.delta":
            if 包含思考 and 分块.get("delta"):
                return {"类型": _流事件类型_思考中, "内容": str(分块["delta"]), "工具调用": [], "用量": None}
            return None
        if 类型 == "response.completed":
            响应 = 分块.get("response") or {}
            return {"类型": _流事件类型_完成, "内容": "", "工具调用": [],
                    "用量": _归一化用量(响应) or _归一化用量(分块)}
        if 类型 in {"response.failed", "response.incomplete"}:
            响应 = 分块.get("response") or {}
            错误 = 响应.get("error") or 分块.get("error") or 类型
            return {"类型": _流事件类型_错误, "内容": str(错误), "工具调用": [], "用量": None}
        return None

    # ② anthropic 流式：content_block_delta / message_delta / message_stop / error
    if 类型 in {"content_block_delta", "message_delta", "message_stop", "message_start",
                "content_block_start", "content_block_stop", "ping", "error"}:
        if 类型 == "content_block_delta":
            增量 = 分块.get("delta") or {}
            增量类型 = 增量.get("type")
            if 增量类型 == "text_delta" and 增量.get("text"):
                return {"类型": _流事件类型_令牌, "内容": str(增量["text"]), "工具调用": [], "用量": None}
            if 增量类型 == "thinking_delta" and 包含思考 and 增量.get("thinking"):
                return {"类型": _流事件类型_思考中, "内容": str(增量["thinking"]), "工具调用": [], "用量": None}
            return None
        if 类型 in {"message_delta", "message_stop"}:
            return {"类型": _流事件类型_完成, "内容": "", "工具调用": [], "用量": _归一化用量(分块)}
        if 类型 == "error":
            错误 = 分块.get("error") or {}
            return {"类型": _流事件类型_错误,
                    "内容": str(错误.get("message") or 错误 or "anthropic 流式错误"),
                    "工具调用": [], "用量": None}
        return None

    # ③ ollama 流式
    if 分块.get("done") and not 分块.get("choices"):
        return {"类型": _流事件类型_完成, "内容": "", "工具调用": [], "用量": _归一化用量(分块)}
    if isinstance(分块.get("message"), dict) and not 分块.get("choices"):
        消息 = 分块.get("message") or {}
        工具调用 = _归一化工具调用({"tool_calls": 消息.get("tool_calls")})
        if 工具调用:
            return {"类型": _流事件类型_工具调用, "内容": "", "工具调用": 工具调用, "用量": None}
        思考 = 消息.get("reasoning_content") or ""
        if 包含思考 and 思考:
            return {"类型": _流事件类型_思考中, "内容": str(思考), "工具调用": [], "用量": None}
        if 消息.get("content"):
            return {"类型": _流事件类型_令牌, "内容": str(消息["content"]), "工具调用": [], "用量": None}
        return None

    # ④ chat_completions 流式
    选项列表 = 分块.get("choices") or []
    选项 = 选项列表[0] if 选项列表 and isinstance(选项列表[0], dict) else {}
    增量 = 选项.get("delta") or {}
    if 增量.get("tool_calls"):
        return None
    if 选项.get("finish_reason"):
        return {"类型": _流事件类型_完成, "内容": "", "工具调用": [], "用量": _归一化用量(分块)}
    思考 = 增量.get("reasoning_content") or ""
    if 包含思考 and 思考:
        return {"类型": _流事件类型_思考中, "内容": str(思考), "工具调用": [], "用量": None}
    if 增量.get("content"):
        return {"类型": _流事件类型_令牌, "内容": str(增量["content"]), "工具调用": [], "用量": None}
    return None


def 归一化流式分块(分块: dict = None, 包含思考: bool = False) -> 结果:
    """把模型流式单块归一化为统一事件。

    返回 {类型, 内容, 工具调用, 用量}；结构事件（心跳/开始/结束标记等）
    归一化为 {"类型": "跳过"}，调用方应丢弃。纯计算、无状态。
    """
    if not isinstance(分块, dict):
        return _失败("参数不合法", "分块必须是字典型")
    if not isinstance(包含思考, bool):
        return _失败("参数不合法", "包含思考必须是逻辑型")
    try:
        事件 = _归一化分块体(分块, 包含思考)
    except Exception as 错误:
        return _失败("归一化失败", f"分块形状无法识别: {错误}")
    if 事件 is None:
        return 结果.成功结果({"类型": "跳过", "内容": "", "工具调用": [], "用量": None})
    return 结果.成功结果(事件)
