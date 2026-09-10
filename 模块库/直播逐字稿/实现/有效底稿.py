"""有效底稿：把死循环/无语音段从送裁决与质检用的底稿里剔除（底稿原始文件仍全量留证）。

长场次实测暴露：Whisper 在音乐/无声/嘈杂段会产生幻觉重复（同一行内重复上百次，
如“많이 많이…”“字字字字…”“我现在在江门我现在在江门…”）。
死循环段只标注不剔除时，这些噪音会随底稿进入裁决并被带进正文；
剔除后，稿件只包含有效发言，且质检的长度比按“有效底稿”计算才合理。

除整段剔除外，还要压缩“单段内短片段重复”（如“嗯嗯嗯嗯…”×32）：
疑难标记的段内重复检测有最短短语长度限制（12 字），单字/双字重复抓不到，
因此在本文件兜一道压缩，并在合成后对全文再压一次（双保险）。
"""

from __future__ import annotations

import re

重复压缩正则 = re.compile(r"(.{1,3})\1{3,}")
最大压缩轮数 = 6


def _数(值, 默认: float = 0.0) -> float:
    """宽松取数：0 是合法值，不能用 `or` 兜底。"""
    try:
        return float(值)
    except (TypeError, ValueError):
        return 默认


def 在死循环区间(段: dict, 死循环区间: list[dict] | None) -> bool:
    """分段开始秒是否落在任一死循环区间内。"""
    开始 = _数(段.get("开始秒"), -1.0)
    if 开始 < 0:
        return False
    for 区间 in 死循环区间 or []:
        if not isinstance(区间, dict):
            continue
        左 = _数(区间.get("开始秒"), -1.0)
        右 = _数(区间.get("结束秒"), -1.0)
        if 左 < 0 or 右 < 0:
            continue
        if 左 - 0.001 <= 开始 <= 右 + 0.001:
            return True
    return False


def 剔除死循环(分段列表: list[dict], 死循环区间: list[dict] | None) -> list[dict]:
    """返回剔除死循环区间后的分段列表（原列表不改动）。"""
    if not 死循环区间:
        return list(分段列表 or [])
    return [段 for 段 in (分段列表 or []) if not 在死循环区间(段, 死循环区间)]


def 压缩段内重复(文本: str) -> str:
    """把同一 1~3 字片段连续重复 ≥4 次压成 1 次。

    “嗯”×32 → “嗯”；“谢谢”×5 → “谢谢”；而“对对对”“可以可以”这类正常口语重复不受影响。
    多轮压缩直到文本不再变化（一轮只能消掉一组，长噪声要几轮）。
    """
    if not 文本:
        return ""
    当前 = str(文本)
    for _ in range(最大压缩轮数):
        新文本 = 重复压缩正则.sub(lambda 匹配: 匹配.group(1), 当前)
        if 新文本 == 当前:
            break
        当前 = 新文本
    return 当前


def 清洗分段(分段列表: list[dict], 死循环区间: list[dict] | None) -> list[dict]:
    """剔除死循环区间分段，并压缩剩余分段内的短片段重复（原列表不改动）。"""
    剩下 = 剔除死循环(分段列表, 死循环区间)
    return [{**段, "文本": 压缩段内重复(str(段.get("文本") or ""))} for 段 in 剩下]


def 有效文本(分段列表: list[dict]) -> str:
    """把分段列表拼成有效底稿文本（去空白后拼接）。"""
    return "".join(str(段.get("文本") or "").strip() for 段 in (分段列表 or []))


def 剔除摘要(分段列表: list[dict], 死循环区间: list[dict] | None, 剔除后: list[dict]) -> dict:
    """剔除前后对照，供状态与质检报告追溯。"""
    return {"分段总数": len(分段列表 or []), "剔除分段数": len(分段列表 or []) - len(剔除后 or []),
            "死循环区间数": len(死循环区间 or []),
            "有效字符数": len(有效文本(剔除后))}
