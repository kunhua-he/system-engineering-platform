"""模型连接基元：失败结果构造、协议归一与别名、降级留痕、HTTP 兼容调用器。

2026-09-19 从 `实现/模型连接器.py` 原样搬出（对外零变化，成员名一个不改），
照 `实现/响应归一化.py` / `实现/模型探针.py` 的先例单独成文件。本模块是连接器一族的**最小底座**：

- `协议别名` / `_规范化协议`：公开短协议（chat/res/anthropic）与内部长协议的唯一裁决。
  适配层 `模型HTTP提供者.py` 的 `协议别名表` 是同一张表的另一处接线，
  `测试中心/支持库/测试_模型协议别名.py` 断言两份取值一致（防漂移）；
- `降级记录表` + `_失败`：尽力清理/降级异常的统一留痕口（有界 1000 条）与
  连接器一族的失败结果构造（来源固定「模型连接器」）。**本表是各簇共用的同一份账本**：
  新模块按名导入本模块的 `降级记录表`，不各建一份；
- `_HTTP请求超时秒` / `_HTTP调用模型`：URL 连接的默认兼容调用器。端点归一、anthropic 载荷、
  请求头可发送性三件事全部复用适配层唯一实现，本模块不另写一套映射。

**依存方向（拆分后无环的根据）**：本模块只依赖标准库 + 公共契约 + 适配层，
对启动器段/句柄段/环境段的引用数为 0，因此可被其余三段单向依赖。

⚠️ 保真说明：`_HTTP调用模型` 内 `归一 = _归一化响应体(数据, True)` 这一句在拆分前就是
`NameError`（`_归一化响应体` 是 `实现/响应归一化.py` 的私有名，从未导出到本命名空间）。
**已修（2026-09-19）**：见文件末尾的模块级导入 —— 拆分时保留缺陷会留一条「LLM 非流式
调用必崩（NameError）」的隐雷，LLM 调用是主路径，不能因为「改它会动两个测试的判定」
就带着走。修它是**恢复本来的设计意图**（该函数本就在同包内），不是改口径。
"""
from __future__ import annotations

import json
import os
from collections import deque
from typing import Any

from 公共契约.基础类型.结果类型 import 结果


内存安全阈值 = 0.80                              # 系统内存占用安全阈值（80%）


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


def _失败(错误码: str, 消息: str, *, 可重试: bool = False,
        详情: dict[str, Any] | None = None) -> 结果:
    return 结果.失败(错误码, 消息, 来源="模型连接器", 可重试=可重试, 详情=详情)


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
        # 绕开系统代理探测：macOS 的 urllib 默认走 _scproxy 读系统代理设置，
        # 而 _scproxy 在「fork 出来的子进程 + 多线程」下会触发 CFPreferences 非线程安全
        # 崩溃（实测 SIGSEGV，栈顶 _os_log_preferences_refresh → SCDynamicStoreCopyProxies）。
        # 底座 HTTP连接器早已按同一口径用 ProxyHandler({}) 绕开，此处补齐。
        # 语义不变：本机模型端点（127.0.0.1）本就不该走代理。
        开放器 = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with 开放器.open(请求, timeout=_HTTP请求超时秒(配置)) as 响应:
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


# ── 收口导入（放文件末尾，与原文件同位；避开与 响应归一化 的环形导入）──────────
# 修的是「拆分前就存在的 NameError」：`_HTTP调用模型` 在 LLM 分支调用 `_归一化响应体`，
# 而它住在 `实现/响应归一化.py`。不导入 → LLM 非流式调用直接抛 NameError（主路径隐雷）。
# 原文件同样把这条 import 放在末尾（HEAD 版本第 1586 行），此处保持同一位置与口径。
from 支持库.后端.大语言模型支持库.模型连接器.实现.响应归一化 import (  # noqa: E402
    _归一化响应体,
)
