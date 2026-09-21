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

**2026-09-19 拆分（对外零变化，成员名一个不改）**：原 1591 行按职责簇原地搬出四段到同目录
新模块，本文件只留「句柄与连接管理 / 连接器入口 / 本地模型启动器（进程与句柄接线）/
持句柄调用 / 句柄生命周期」五段，并把搬出的符号按名再导入（re-export）回来 ——
`__init__.py`、`支持库/适配层/模型HTTP提供者.py` 与全部测试的导入路径零改动：

- `实现/模型连接基元.py`：失败结果构造、协议归一与别名、降级留痕、HTTP 兼容调用器；
- `实现/环境配置.py`：统一环境参数（读取 / 合入 / 查询）；
- `实现/本地启动准备与守卫.py`：模型源识别、供应链校验、内存守卫、启动命令与就绪等待；
- `实现/模型工具调度.py`：循环软护栏、工具调度、重试调度、工具清单门控（纯计算）。

**两段按 2026-09-18 实测结论仍不拆**（搬出即形成双向依赖，本文件继续承载）：
①「本地模型启动器」的进程与句柄段（`_启动本地模型` / `启动本地模型` / `_终止本地进程` /
`注册本地进程`）—— 与 `_内存守卫` / `_包申报超时` / `_句柄键` / `_回收过期句柄` /
`释放句柄` 互相引用；②「句柄与连接管理」段 —— 是其余各段的公共底座。
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
import uuid
from collections import deque          # 表面保留：拆分前在本模块可见（导入产物）
from pathlib import Path
from typing import Any, Callable, Iterator

from 公共契约.基础类型.结果类型 import 结果
from 公共契约.句柄体系 import 句柄体系, 句柄类型_资源
from 公共契约.运行时 import 平台适配, 进程终止

# 表面保留：拆分前 `_供应链校验` 在本模块可见（`import 模型供应链校验 as _供应链校验` 的产物）。
# 供应链接线已搬去 `实现/本地启动准备与守卫.py`，此处保留该名以维持对外零变化。
from 支持库.后端.大语言模型支持库.模型连接器.实现 import 模型供应链校验 as _供应链校验  # noqa: F401

# 搬出簇的符号按名接入（与拆分前同一命名空间口径：残留段一律按裸名调用，
# 不做 `模块.成员` 改写）。新模块若改名，这里当场 ImportError，不会静默漂移。
from 支持库.后端.大语言模型支持库.模型连接器.实现.模型连接基元 import (
    降级记录表,
    _失败,
    内存安全阈值,
    默认协议,
    允许协议,
    协议取值说明,
    协议别名,
    _规范化协议,
    默认HTTP请求超时秒,
    环境变量HTTP超时,
    _HTTP请求超时秒,
    _HTTP调用模型,
)
from 支持库.后端.大语言模型支持库.模型连接器.实现.环境配置 import (
    环境配置,
    环境键表,
    加载环境配置,
    查询环境配置,
    _合入环境参数,
)
from 支持库.后端.大语言模型支持库.模型连接器.实现.本地启动准备与守卫 import (
    校验模型完整性,
    本地模型估算系数,
    _识别模型源,
    _供应链系统根,
    _供应链守卫,
    _启动器守卫,
    _启动前供应链阻断,
    _供应链判定,
    _解析启动器二进制,
    _启动器校验,
    _系统内存快照,
    _预计占用,
    _内存守卫,
    _分配端口,
    _计算模型大小,
    _构建本地启动命令,
    _启动日志路径,
    _读启动日志尾部,
    _等待本地健康,
    本地进程空闲秒,
    就绪等待秒 as _就绪等待秒,
    看守包装代码,
    读取看守账本,
    看守账本路径,
    _写看守账本,
    回收看守残留,
)
from 支持库.后端.大语言模型支持库.模型连接器.实现.模型工具调度 import (
    循环软护栏,
    调度默认并行上限,
    调度工具调用,
    合成取消结果,
    默认最大重试次数,
    默认退避基数秒,
    默认抖动比例,
    重试最大上限,
    退避最大秒,
    重试模式别名,
    _归一化重试模式,
    重试调度,
    门控模式别名,
    工具名键表,
    _归一化门控模式,
    _取工具名,
    组装可用工具清单,
)

# ── 句柄与连接管理 ──────────────────────────────

句柄系统 = 句柄体系()
连接表: dict[int, dict[str, Any]] = {}          # 句柄id → 连接信息
调用函数表: dict[str, Callable] = {}             # 连接类型+本地/云端 → 真实调用函数
锁 = threading.Lock()

默认超时秒 = 1800                            # 华哥口径：不申报默认 30 分钟（1800 秒），模块/支持库应主动申报
连接类型表 = {"LLM": "对话", "向量": "嵌入", "重排": "排序", "决策": "判断"}


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
    # ★ 入口 fail-closed（2026-09-21，与 _调用模型 同一条口径「唯一一条腿」）：
    # 本地形态只给模型名 -> 句柄里没有地址 -> 调用时必然不可用。
    # 以前会登记这么一个空壳句柄（连上但用不了，像连了个空 MySQL 连接），
    # 现在直接拦在入口并说清怎么修。
    if (配置.get("部署形态") or "本地") == "本地" and not str(配置.get("url") or "").strip():
        return _失败("本地路径缺失",
                     "本地形态连接必须给 本地路径（由底座拉起本地服务并将 127.0.0.1 地址写入句柄），"
                     "或显式给 url 连已在运行的本地服务；只给模型名拿到的句柄无法调用，已在此拦下")
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


def _调用模型(句柄id: int, 连接类型: str, 参数: dict) -> 结果:
    连接, 原因 = _取连接(句柄id)
    if 连接 is None:
        return _失败("句柄失效", 原因)
    if 连接["类型"] != 连接类型:
        return _失败("参数不合法", f"句柄 {句柄id} 是 {连接['类型']} 连接，不是 {连接类型}")
    部署形态 = 连接["配置"].get("部署形态") or "本地"
    调用函数 = 调用函数表.get(f"{连接类型}:{部署形态}")
    if 调用函数 is None:
        # ★ 唯一一条腿（2026-09-21 实测缺陷修复，华哥口径「连上就复用句柄，像 MySQL 一样」）：
        # 句柄即连接，连上后所有调用必须打**该句柄自己的地址**，不允许换腿。
        # 实测缺陷：此处此前对「本地形态」无条件回落 HTTP 调用器，而 HTTP 调用器读的是
        # 全局「云端地址」（MODEL_API_URL）——本地句柄在没有地址时会静默跑到云端那条腿，
        # 报出与真实原因无关的「未配置模型 HTTP 地址」（实测：语义索引建索引全块失败）。
        # 地址的唯一来源：本地由 启动本地模型 写 url=http://127.0.0.1:<端口>/v1，
        # 云端由连接参数或 env 写云端 url —— 两路都落在同一个字段上，所以它是句柄的地址真源。
        if not str(连接["配置"].get("url") or "").strip():
            return _失败("句柄不可用",
                         f"句柄 {句柄id} 是{部署形态}连接，但句柄里没有可用服务地址："
                         f"本地形态用 本地路径 连接（由底座拉起并把地址写入句柄），"
                         f"或显式给 url 连已有服务；云端形态请给 url。")
        return _HTTP调用模型(连接类型, 连接["配置"], 参数)
    try:
        return 调用函数(配置=连接["配置"], **参数)
    except Exception as 错误:
        return _失败("模型调用失败", f"{连接类型} 调用异常: {错误}")


# ── 连接器（返回句柄）──────────────────────────────

def 连接LLM(模型: str = None, 提供者: str = None, 部署形态: str = None,
           本地路径: str = None, 启动器: str = None, 模型大小字节: int = None,
           url: str = None, api_key: str = None, 上下文长度: int = None,
           超时秒: int = None, 协议: str = 默认协议, 额外请求头: dict = None,
           内存估算系数: float = None, 内存安全阈值: float = None) -> 结果:
    """连接大语言模型，返回句柄。连接阶段只接受连接配置与协议参数；流式输出属于生成对话选项，未知关键字（包括连接阶段流式输出）由函数签名拒绝。

    缺参时使用 env 统一参数（加载环境配置后生效）。本地：部署形态=本地+GGUF 文件绝对路径，由底座直接启动 llama-server；云端：部署形态=云端+url/api_key/模型/上下文长度。
    额外请求头：连接级静态请求头，出站时叠加在内置头之上（生成对话的 附加请求头 可覆盖同名键）。
    """
    显式 = {"模型": 模型, "提供者": 提供者, "部署形态": 部署形态, "本地路径": 本地路径,
            "启动器": 启动器, "模型大小字节": 模型大小字节, "url": url, "api_key": api_key,
            "上下文长度": 上下文长度, "超时秒": 超时秒, "协议": 协议, "额外请求头": 额外请求头,
            # 内存守卫的两个可调参数：守卫本身早就读这两个键（见 _内存守卫 的
            # 配置.get("内存估算系数") / 配置.get("内存安全阈值")），但连接入口此前
            # 不接收它们 → 调用方按实测校准也传不进来（「参数收了不用」同类）。
            "内存估算系数": 内存估算系数, "内存安全阈值": 内存安全阈值}
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
            "上下文长度": 上下文长度, "协议": 协议, "额外请求头": 额外请求头,
            "内存估算系数": 显式.get("内存估算系数"), "内存安全阈值": 显式.get("内存安全阈值")}
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


def 连接决策模型(模型: str = None, 提供者: str = None, 部署形态: str = None,
                本地路径: str = None, 启动器: str = None, 模型大小字节: int = None,
                url: str = None, api_key: str = None, 超时秒: int = None) -> 结果:
    """连接决策模型，返回句柄。缺参时用 env 统一参数。

    决策模型 = 非自回归、一次前向产出「多选答案 + 标定置信度」的小模型（如 Laya）。
    与 LLM 的区别：不做自由文本生成，只按调用方给的问题定义在固定选项集上做判断，
    置信度经严格真分数规则训练、统计上可信，上层可据此决定是否需要人工兜底。
    本地形态要求权重目录含 config.json（HuggingFace 结构），由底座经 模型服务.py 拉起。
    """
    显式 = {"模型": 模型, "提供者": 提供者, "部署形态": 部署形态, "本地路径": 本地路径,
            "启动器": 启动器, "模型大小字节": 模型大小字节, "url": url, "api_key": api_key, "超时秒": 超时秒}
    显式 = _合入环境参数("决策", 显式)
    模型, 提供者, 部署形态 = 显式["模型"], 显式["提供者"], 显式["部署形态"]
    url, api_key, 超时秒 = 显式["url"], 显式["api_key"], 显式["超时秒"]
    本地路径, 启动器, 模型大小字节 = 显式["本地路径"], 显式["启动器"], 显式["模型大小字节"]
    if not isinstance(模型, str) or not 模型.strip():
        return _失败("参数不合法", "模型必须是非空字符串（env 未配置默认决策模型）")
    形态 = (部署形态 or "云端" if (url or api_key) else 部署形态 or "本地").lower()
    形态 = "云端" if 形态 in ("cloud", "api", "云") else "本地" if 形态 in ("local", "本机") else 形态
    if 形态 not in ("本地", "云端"):
        return _失败("参数不合法", f"部署形态必须是 本地 或 云端: {部署形态}")
    配置 = {"模型名": 模型, "提供者": 提供者 or "本地", "部署形态": 形态, "本地路径": 本地路径,
            "启动器": 启动器, "模型大小字节": 模型大小字节, "url": url, "api_key": api_key}
    if 形态 == "本地" and 本地路径:
        return 启动本地模型(本地路径, 启动器, "决策", 模型大小字节=模型大小字节, 超时秒=超时秒)
    return _登记连接("决策", 配置, 超时秒=超时秒)


# ── 本地模型启动器（路径入参，底座负责启动并绑定句柄）────────
# 本段按 2026-09-18 实测结论**不拆**：与 _内存守卫 / _包申报超时 / _句柄键 /
# _回收过期句柄 / 释放句柄 互相引用，搬出即形成双向依赖。其中的启动准备层
# （模型源识别/供应链/内存守卫/启动命令/就绪等待）已搬去 `实现/本地启动准备与守卫.py`，
# 本段只剩进程与句柄接线。

本地进程表: dict[int, Any] = {}  # 句柄id → 子进程对象
全局模型索引: dict[tuple[str, str], int] = {}  # (模型类型, 规范化源路径) → 全局句柄
本地启动锁 = threading.Lock()  # 防止同一路径并发启动出多个模型进程


def _启动本地模型(模型路径: str | None = None, 启动器: str | None = None, 模型类型: str | None = None,
                端口: int | None = None, 模型大小字节: int | None = None, 参数: dict | None = None, 超时秒: int | None = None) -> 结果:
    """由底座按模型绝对路径启动独立进程，并返回已绑定资源的句柄。"""
    if not isinstance(模型路径, str) or not 模型路径.strip() or not os.path.exists(模型路径):
        return _失败("参数不合法", "模型路径必须是存在的绝对路径")
    类型 = (模型类型 or "LLM").lower()
    类型 = "LLM" if 类型 in ("对话", "llm") else "向量" if 类型 in ("嵌入", "向量", "embedding") else "重排" if 类型 in ("排序", "重排", "rerank") else "决策" if 类型 in ("判断", "决策", "decision") else None
    if 类型 is None:
        return _失败("参数不合法", f"模型类型必须是 LLM/向量/重排/决策: {模型类型}")
    源格式, 规范路径 = _识别模型源(模型路径)
    if 源格式 == "不支持":
        return _失败("参数不合法", "底座不支持该模型源；本地模型应为 GGUF 文件或含 config.json 的权重目录")
    模型身份 = (类型, 规范路径)
    from pathlib import Path
    import subprocess
    _回收过期句柄()
    # 2026-09-19（G 路·孤儿自愈）：上一代看守若已死、它拉起的模型进程还活着，
    # 那就是**上一代的孤儿**（看守没来得及收工就被 kill -9）。这里按「归属 + 世代」
    # 判一次：账本 + 启动时刻 + 命令行端口三重证据都指向本代才回收；
    # 看守还活着就一律不动（那是正在用的这一代）。
    上代回收: dict[str, Any] = {}
    _上代账本 = 读取看守账本(规范路径)
    if _上代账本.get("状态") == "看守中":
        _看守号 = _上代账本.get("看守进程号")
        if (isinstance(_看守号, int) and not isinstance(_看守号, bool)
                and not 进程终止.进程存活(_看守号)):
            try:
                上代回收 = 回收看守残留(规范路径)
                降级记录表.append(f"本地模型上一代孤儿自愈：{上代回收.get('原因')}")
            except Exception as 错误:
                降级记录表.append(f"上一代孤儿回收异常: {错误}")
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
    # 供应链校验（B9）：必须在**创建句柄与拉起进程之前**——校验不过就不该产生任何资源。
    # 被替换/截断的权重、未登记的启动器、清单读不成，都在这里被拦下并给出中文原因。
    供应链阻断 = _启动前供应链阻断(规范路径, 类型, str(启动器 or ""))
    if 供应链阻断 is not None:
        return 供应链阻断
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
        # 2026-09-19（G 路）：本地模型**进程**的空闲阈值对齐到本支持库包声明的
        # 「句柄超时秒」（唯一真源，见 本地进程空闲秒）—— 华哥口径「拉起后 5 分钟
        # 没人用就自动释放」。调用方显式传了 超时秒 就按调用方（显式租约优先）。
        有效超时 = 超时秒 if isinstance(超时秒, int) and not isinstance(超时秒, bool) \
            and 超时秒 > 0 else 本地进程空闲秒()
        连接键 = _句柄键(对象.句柄id)
        连接表[连接键] = {"类型": 类型, "配置": dict(配置), "创建时间": time.time(),
                         "最后活动时间": time.time(), "超时秒": 有效超时, "释放函数": _终止本地进程,
                         "全局句柄": True, "模型身份": 模型身份}
        全局模型索引[模型身份] = 连接键
    try:
        空闲秒 = 有效超时
        启动参数["进程空闲秒"] = 空闲秒
        命令 = _构建本地启动命令(规范路径, 类型, 启动器名, 端口, 启动参数)
        日志路径 = _启动日志路径(规范路径)
        # 就绪等待与空闲阈值**解耦**（2026-09-19 实测教训）：两个口径本来就不是一回事，
        # 原来都取「有效超时」——把空闲阈值下调到 5 分钟，就绪等待也跟着从 900 秒
        # 缩到 300 秒，19GB 权重在大模型冷启动时可能因此被误判「启动失败」。
        # 就绪是启动期（加载权重，与模型大小相关），空闲是运行期（没人用），
        # 各取各的常量，互不牵连。
        就绪秒 = _就绪等待秒
        # 启动日志落盘而非 DEVNULL：失败时可诊断（看守持有独立 fd，
        # 父进程关闭文件对象不影响其继续写入）
        日志文件 = open(日志路径, "ab", buffering=0)
        try:
            表头 = ("\n" + "=" * 60 + "\n[启动] "
                    + time.strftime("%Y-%m-%d %H:%M:%S")
                    + "\n[命令] " + " ".join(命令)
                    + f"\n[看守] 空闲秒={空闲秒}（真源：本支持库包声明 句柄超时秒）\n")
            日志文件.write(表头.encode("utf-8"))
        except OSError:
            pass
        try:
            # 2026-09-19（G 路·进程级自退）：父进程持有的**不是** llama-server，
            # 而是一个独立看守进程；看守再拉起 llama-server 并独占其生命周期。
            # 这样「调用方被 SIGNAL 干掉」与「调用方 kill -9」两种情况下，
            # 看守都还在，能自己走到空闲阈值收工 —— 孤儿自退就落在这一层。
            # 归属判据不靠端口：账本 + 启动时刻（世代）+ 命令行端口三重证据。
            世代 = uuid.uuid4().hex[:12]
            看守命令 = [sys.executable, "-c", 看守包装代码(_供应链系统根()),
                      "--端口", str(端口), "--空闲秒", str(空闲秒),
                      "--日志路径", 日志路径, "--世代", 世代,
                      "--模型路径", 规范路径, "--", *命令]
            进程 = subprocess.Popen(看守命令, **平台适配.子进程组启动标志(),
                                    stdout=日志文件, stderr=subprocess.STDOUT)
        finally:
            日志文件.close()
        本地进程表[连接键] = 进程
        句柄系统.登记资源(对象.句柄id, 资源类型="进程", PID=进程.pid, 端口=端口)
        if not _等待本地健康(端口, 就绪秒):
            尾部 = _读启动日志尾部(规范路径)
            raise TimeoutError(
                f"本地模型启动后健康检查超时: {模型路径}（端口 {端口} 未在 "
                f"{min(max(10, 就绪秒), 900)} 秒内就绪）"
                + (f"；启动日志尾部：{尾部}" if 尾部 else
                   "；启动日志为空，常见原因：端口被占用、模型文件损坏或启动器参数不被支持"))
        return 结果.成功结果({"句柄": 对象.句柄id, "模型类型": 类型, "模型路径": 规范路径,
                         "端口": 端口, "启动命令": 命令, "全局句柄": True,
                         "看守进程号": 进程.pid, "世代": 世代,
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

    2026-09-21 补（看守 + 模型进程双层归属）：父进程持有的只是**看守**，
    模型进程由看守二次 `Popen` 且各自独立成组；只收看守会在账本里留下
    孤儿模型进程（实测：释放句柄返回「已结束并已释放」——旧词表，现统一为「已释放」；
     端口与模型进程仍在）。
    故收完看守再按看守账本（看守进程号 + 模型进程号双匹配）回收模型进程组 ——
    世代不符一律不动，避免误杀正在用的那一代。
    """
    with 锁:
        进程 = 本地进程表.get(句柄id)
        _连接 = 连接表.get(句柄id) or {}
        _模型路径 = str(_连接.get("配置", {}).get("本地路径") or "")
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
        _回收看守名下模型进程(_模型路径, 进程.pid)
        return True
    except Exception as 错误:
        降级记录表.append(str(错误))
        return False


def _回收看守名下模型进程(模型路径: str, 看守进程号: int) -> None:
    """收看守之后，按账本把该代看守拉起的模型进程组一并回收（归属不符不动）。"""
    if not 模型路径:
        return
    try:
        账本 = 读取看守账本(模型路径)
    except Exception:
        return
    if 账本.get("看守进程号") != 看守进程号:
        return
    模型进程号 = 账本.get("模型进程号")
    if not isinstance(模型进程号, int) or isinstance(模型进程号, bool) or 模型进程号 <= 0:
        return
    if 进程终止.进程存活(模型进程号):
        try:
            进程终止.终止进程组(模型进程号, 信号="终止")
            if not 进程终止.等待进程消失(模型进程号, 超时秒=5.0):
                进程终止.终止进程组(模型进程号, 信号="强杀")
                进程终止.等待进程消失(模型进程号, 超时秒=5.0)
        except Exception as 错误:
            降级记录表.append(f"看守名下模型进程 {模型进程号} 回收异常: {错误}")
    try:
        账本.update({"状态": "已回收", "回收时刻": time.strftime("%Y-%m-%d %H:%M:%S")})
        _写看守账本(看守账本路径(模型路径), 账本)
    except Exception:
        pass


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


def 执行决策(句柄: int | None = None, 文本: str = None, 问题: dict = None) -> 结果:
    """按问题定义对一段文本做决策，返回选项/概率/置信度。

    问题形状（沿用模型原生三型，键为问题名）：
        {"环节": {"type": "choice", "instructions": "…", "criteria": {"选项A": "…", …}}}
    type 三型：choice（多选一）/ score（分档打分）/ noul（是或否）。
    返回每题的答案对象；choice 型含 选项/概率/置信度，置信度可直接用于「是否需要人工」判定。
    """
    if isinstance(句柄, bool) or not isinstance(句柄, int) or not 1 <= 句柄 <= 999999:
        return _失败("参数不合法", "句柄必须是1到999999的整数")
    if not isinstance(文本, str) or not 文本.strip():
        return _失败("参数不合法", "文本必须是非空字符串")
    if not isinstance(问题, dict) or not 问题:
        return _失败("参数不合法", "问题必须是定义决策问题的非空字典")
    return _调用模型(句柄, "决策", {"文本": 文本, "问题": 问题})


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
                return 结果.成功结果({"句柄": 句柄, "状态": "已释放", "已释放": True})
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


# ── 响应归一化的 re-export（2026-09-18 拆分）──────────────────────
# 该段已独立成 `实现/响应归一化.py`；这里 re-export 两个对外符号，
# **保证 `__init__.py` 的导入路径与全部调用方零改动**（对外零变化）。
from 支持库.后端.大语言模型支持库.模型连接器.实现.响应归一化 import (  # noqa: E402
    归一化对话响应,
    归一化流式分块,
)

__all__ = [*globals().get("__all__", []), "归一化对话响应", "归一化流式分块"]
