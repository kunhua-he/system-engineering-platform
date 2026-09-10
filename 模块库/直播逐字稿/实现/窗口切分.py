"""窗口切分：把转写分段按时间窗聚合成裁决窗口。

窗口是裁决的最小单位：一窗一次 LLM 调用，避免整场塞进上下文。
疑难段以“需重点核对”说明的形式跟随所属窗口；死循环区间写进元信息供排版阶段注明。
"""

from __future__ import annotations

默认窗口秒 = 900
默认每窗最大字符 = 6000


def 全部分段(分片转写列表: list[dict]) -> list[dict]:
    """把多片转写的分段拉平成一条带绝对时间的列表（按开始秒排序）。"""
    分段表: list[dict] = []
    偏移 = 0.0
    for 分片 in 分片转写列表 or []:
        if not isinstance(分片, dict):
            continue
        分片序号 = 分片.get("分片序号")
        for 段 in 分片.get("分段") or []:
            if not isinstance(段, dict):
                continue
            开始 = _数(段.get("开始秒"), 偏移)
            结束 = _数(段.get("结束秒"), 开始)
            分段表.append({
                "分片序号": 分片序号,
                "序号": 段.get("序号"),
                "开始秒": round(开始, 3),
                "结束秒": round(结束, 3),
                "文本": str(段.get("文本") or "").strip(),
                "平均对数概率": _数(段.get("平均对数概率"), 0.0),
                "压缩比": _数(段.get("压缩比"), 0.0),
                "无语音概率": _数(段.get("无语音概率"), 0.0),
            })
        if 分片.get("结束秒") is not None:
            偏移 = _数(分片.get("结束秒"), 偏移)
    分段表.sort(key=lambda 项: 项["开始秒"])
    return 分段表


def _数(值, 默认: float) -> float:
    try:
        return float(值)
    except (TypeError, ValueError):
        return 默认


def _格式时间(秒: float) -> str:
    总秒 = max(0.0, float(秒))
    分 = int(总秒 // 60)
    return f"{分:02d}:{总秒 - 分 * 60:04.1f}"


def 切窗口(分段列表: list[dict], 窗口秒: int = 默认窗口秒) -> list[dict]:
    """按时间窗聚合分段；每窗给出底稿文本、时间范围与对应分段。"""
    窗口列表: list[dict] = []
    当前: list[dict] = []
    窗口起点 = None
    for 段 in 分段列表 or []:
        if 窗口起点 is None:
            窗口起点 = 段["开始秒"]
        if 段["开始秒"] - 窗口起点 >= 窗口秒 and 当前:
            窗口列表.append(_收口(当前, len(窗口列表) + 1, 窗口起点))
            当前 = []
            窗口起点 = 段["开始秒"]
        当前.append(段)
    if 当前:
        窗口列表.append(_收口(当前, len(窗口列表) + 1, 窗口起点 if 窗口起点 is not None else 0.0))
    return 窗口列表


def _收口(分段: list[dict], 窗口id: int, 起点: float) -> dict:
    文本 = "".join(段["文本"] for 段 in 分段 if 段["文本"])
    return {
        "窗口id": 窗口id,
        "开始秒": round(起点, 3),
        "结束秒": round(分段[-1]["结束秒"] if 分段 else 起点, 3),
        "时间范围": f"{_格式时间(起点)}-{_格式时间(分段[-1]['结束秒'] if 分段 else 起点)}",
        "底稿文本": 文本,
        "分段": 分段,
        "疑难说明": "",
        "证据文本": "",
    }


def 关联疑难(窗口列表: list[dict], 疑难段: list[dict],
             每窗最多条数: int = 40, 单条最长: int = 120) -> None:
    """把疑难段按时间归属写入窗口的 疑难说明（就地修改）。

    只列最疑难的 N 条并截断单条长度：疑难说明整包灌入会把单窗请求体撑到上万字，
    实测 600 字输入约 39 秒，长场次耗时因此从十分钟级涨到二十分钟级。
    排序按「原因条数降序 + 时间升序」，保证多处可疑的段优先进入核对清单。
    """
    for 窗口 in 窗口列表:
        命中: list[tuple[int, float, str]] = []
        for 段 in 疑难段 or []:
            try:
                开始 = float(段.get("开始秒") or 0)
            except (TypeError, ValueError):
                continue
            if 窗口["开始秒"] <= 开始 <= 窗口["结束秒"]:
                原因 = "、".join(段.get("原因") or [])
                文本 = str(段.get("文本") or "")[:单条最长]
                命中.append((len(段.get("原因") or []), 开始,
                           f"[{_格式时间(开始)}] {文本}（原因：{原因}）"))
        命中.sort(key=lambda 项: (-项[0], 项[1]))
        选 = 命中[:max(1, int(每窗最多条数))]
        行 = [项[2] for 项 in 选]
        if len(命中) > len(选):
            行.append(f"（本窗另有 {len(命中) - len(选)} 处疑难未逐条列出，按原始识别正常精校即可）")
        窗口["疑难说明"] = "\n".join(行)


def 合并短窗(窗口列表: list[dict], 最小字符: int = 400) -> list[dict]:
    """把过短的窗口并入前一窗，减少 LLM 调用次数；只合并相邻两窗。"""
    合并后: list[dict] = []
    for 窗口 in 窗口列表:
        if (合并后 and len(窗口["底稿文本"]) < 最小字符
                and len(合并后[-1]["底稿文本"]) < 默认每窗最大字符):
            上一 = 合并后[-1]
            上一["结束秒"] = 窗口["结束秒"]
            上一["时间范围"] = f"{上一['时间范围'].split('-')[0]}-{窗口['时间范围'].split('-')[-1]}"
            上一["底稿文本"] += 窗口["底稿文本"]
            上一["分段"] = list(上一["分段"]) + list(窗口["分段"])
            if 窗口.get("疑难说明"):
                上一["疑难说明"] = "\n".join(项 for 项 in [上一.get("疑难说明"), 窗口.get("疑难说明")] if 项)
            continue
        合并后.append(窗口)
    for 序号, 窗口 in enumerate(合并后, start=1):
        窗口["窗口id"] = 序号
    return 合并后
