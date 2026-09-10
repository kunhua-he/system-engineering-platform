"""有效底稿：把死循环/无语音段从送裁决与质检用的底稿里剔除（底稿原始文件仍全量留证）。

长场次实测暴露：Whisper 在音乐/无声/嘈杂段会产生幻觉重复（同一行内重复上百次，
如“많이 많이…”“字字字字…”“我现在在江门我现在在江门…”）。
死循环段只标注不剔除时，这些噪音会随底稿进入裁决并被带进正文；
剔除后，稿件只包含有效发言，且质检的长度比按“有效底稿”计算才合理。
"""

from __future__ import annotations


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


def 有效文本(分段列表: list[dict]) -> str:
    """把分段列表拼成有效底稿文本（去空白后拼接）。"""
    return "".join(str(段.get("文本") or "").strip() for 段 in (分段列表 or []))


def 剔除摘要(分段列表: list[dict], 死循环区间: list[dict] | None, 剔除后: list[dict]) -> dict:
    """剔除前后对照，供状态与质检报告追溯。"""
    return {"分段总数": len(分段列表 or []), "剔除分段数": len(分段列表 or []) - len(剔除后 or []),
            "死循环区间数": len(死循环区间 or []),
            "有效字符数": len(有效文本(剔除后))}
