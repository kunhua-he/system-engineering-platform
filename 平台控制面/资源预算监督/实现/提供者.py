"""资源预算监督能力实现（只读/判定）：预算声明的唯一判据来自 资源监督器。

分工（第 2 条 1 项 分层与归属固定）：
- `平台控制面/资源监督.py`：必需预算项与预算声明的**唯一语义实现**；
- 本模块：能力边界参数校验 + 必需项/阈值两类判定，不复制必需项清单。

为什么只切「预算声明判定」：注册执行单元/提交任务/排空/优雅停止/运行中采样都要
依附进程内的监督器实例状态（线程池、信号量、活跃表），跨进程能力调用拿到的是
新实例的空状态，报出来的数就不是真实运行状态——按「不接受调用方手工峰值作为
唯一证据」的口径，这类动作不进本轮只读/判定能力面。
"""
from __future__ import annotations

from typing import Any

from 平台控制面.资源监督 import 资源监督器
from 公共契约.基础类型.逻辑类型 import 真, 假

来源名称 = "资源预算监督"
预算非字典说明 = "资源预算必须是字典型"

# 内存/临时空间类预算项：接受数字（MB）或带量纲文本（如 "64 MB"）
_量纲项 = ("内存上限", "临时空间上限")
# 正整数项：1 起
_正整数项 = ("线程上限", "并发调用上限", "队列长度", "文件句柄上限")
# 非负整数项：0 起
_非负整数项 = ("子进程上限", "每分钟重启次数", "空闲回收时间")


def _失败(错误码: str, 说明: str):
    from 公共契约.基础类型.结果类型 import 结果

    return 结果.失败(错误码, 说明, 来源=来源名称)


def _是预算(资源预算: Any) -> bool:
    """预算入参形态：必须是字典型（不是列表/文本/空值）。"""
    return isinstance(资源预算, dict)


def _解析量纲(值: Any) -> tuple[bool, str]:
    """解析内存/临时空间类取值：数字或 '数字 单位'（KB/MB/GB）文本。"""
    if isinstance(值, bool):
        return 假, "不能是逻辑型"
    if isinstance(值, (int, float)):
        return (值 > 0, "必须大于 0" if 值 <= 0 else "")
    文本 = str(值 or "").strip()
    if not 文本:
        return 假, "不能为空"
    片段 = 文本.replace(" ", "").replace("\t", "")
    单位 = ""
    for 候选 in ("KB", "MB", "GB", "kb", "mb", "gb"):
        if 片段.endswith(候选):
            单位 = 候选.upper()
            片段 = 片段[: -len(候选)]
            break
    try:
        数 = float(片段)
    except ValueError:
        return 假, f"取值无法解析为数量：{文本}"
    if 数 <= 0:
        return 假, "必须大于 0"
    if 单位 and 单位 not in ("KB", "MB", "GB"):
        return 假, f"单位不识别：{文本}"
    return 真, ""


def 查询必需预算项():
    """查询资源监督器要求的全部必需预算项（只读，判据来自 资源监督器.必需预算键）。"""
    from 公共契约.基础类型.结果类型 import 结果

    必需项 = list(资源监督器.必需预算键)
    return 结果.成功结果({
        "必需预算项": 必需项,
        "数量": len(必需项),
        "说明": "必需项口径唯一来源：平台控制面/资源监督.py 的 资源监督器.必需预算键",
    })


def 校验预算声明(资源预算: dict):
    """判定资源预算声明是否含全部必需项（判定，复用 资源监督器.校验预算声明）。"""
    from 公共契约.基础类型.结果类型 import 结果

    if not _是预算(资源预算):
        return _失败("参数不合法", 预算非字典说明)
    预算: dict = dict(资源预算)
    有效, 消息 = 资源监督器(None).校验预算声明(预算)
    缺失 = [键 for 键 in 资源监督器.必需预算键 if 键 not in 预算]
    return 结果.成功结果({"有效": bool(有效), "说明": str(消息), "缺失项": 缺失})


def 校验预算阈值(资源预算: dict):
    """判定预算项取值本身是否有效（判定，逐项给非法原因）。"""
    from 公共契约.基础类型.结果类型 import 结果

    if not _是预算(资源预算):
        return _失败("参数不合法", 预算非字典说明)
    预算: dict = dict(资源预算)
    非法项: list[dict[str, str]] = []
    for 项 in _量纲项:
        if 项 not in 预算:
            continue
        合法, 原因 = _解析量纲(预算[项])
        if not 合法:
            非法项.append({"项": 项, "原因": 原因})
    for 项 in _正整数项:
        if 项 not in 预算:
            continue
        值 = 预算[项]
        if isinstance(值, bool) or not isinstance(值, int) or 值 < 1:
            非法项.append({"项": 项, "原因": "必须是 ≥1 的整数型"})
    for 项 in _非负整数项:
        if 项 not in 预算:
            continue
        值 = 预算[项]
        if isinstance(值, bool) or not isinstance(值, int) or 值 < 0:
            非法项.append({"项": 项, "原因": "必须是 ≥0 的整数型"})
    if "单次调用超时" in 预算:
        值 = 预算["单次调用超时"]
        if isinstance(值, bool) or not isinstance(值, (int, float)) or 值 <= 0:
            非法项.append({"项": "单次调用超时", "原因": "必须是大于 0 的数值"})
    有效 = not 非法项
    说明 = "预算阈值全部合法" if 有效 else f"{len(非法项)} 项预算取值非法"
    return 结果.成功结果({"有效": 有效, "说明": 说明, "非法项": 非法项})
