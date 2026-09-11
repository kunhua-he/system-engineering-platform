"""逐字稿复核调度：把疑难段聚类成复核区间，并对每个区间跑多轮独立转写。

聚类区间按时间间隔把疑难段合并成复核区间（按开始秒升序、id 从 1 连续）；复核区间
对单个区间用不同附加术语提示跑「轮数」轮独立转写，并落盘 复核_0001.json。
底层转写能力由调用方以「调用能力(能力id, 参数) -> 结果」句柄注入，本文件不 import
支持库/提供者/实现目录；失败一律写进 错误码/错误说明，不抛裸异常、不伪造识别文本。
"""

from __future__ import annotations

from pathlib import Path

_来源 = "直播逐字稿"
默认间隔秒 = 60
默认轮数 = 3
默认超时秒 = 600.0
转写能力id = "转写支持库.转写.转写音频文件"
截取能力id = "媒体处理支持库.FFmpeg媒体.截取音频"
区间音频格式 = "mp3"
轮次提示表 = (
    "第1轮：逐字照录，优先保住人名、品牌名、数字与专有名词。",
    "第2轮：换一种断句粒度复听，重点纠正同音误字与吞字。",
    "第3轮：以整句语义为准复听，标出仍无法确认的位置。",
)

def _底座(能力id: str, 参数: dict):
    """经唯一能力调用服务调用底座原子能力；未装配或异常时返回 None。"""
    from 公共契约.能力契约.调用器 import 获取能力调用器
    try:
        return 获取能力调用器().调用能力(能力id, 参数, 调用方=_来源)
    except Exception:
        return None


def _成功(结果对象) -> bool:
    return bool(结果对象 is not None and getattr(结果对象, "成功", False))


def _失败说明(结果对象, 兜底: str) -> str:
    return str(getattr(结果对象, "错误说明", "") or getattr(结果对象, "错误码", "") or 兜底)


def _取数(值) -> float | None:
    """宽松取数：数值或数字文本转 float，取不到返回 None。"""
    if isinstance(值, bool):
        return None
    if isinstance(值, (int, float)):
        return float(值)
    try:
        return float(str(值).strip())
    except (TypeError, ValueError):
        return None

def _可用段落(疑难段) -> list[tuple[float, float]]:
    """提取 (开始秒, 结束秒) 升序排列；非列表/坏条目直接跳过。"""
    if not isinstance(疑难段, list):
        return []
    段落表: list[tuple[float, float]] = []
    for 段 in 疑难段:
        if isinstance(段, dict):
            开始, 结束 = _取数(段.get("开始秒")), _取数(段.get("结束秒"))
            if 开始 is not None and 结束 is not None:
                段落表.append((min(开始, 结束), max(开始, 结束)))
    段落表.sort(key=lambda 项: (项[0], 项[1]))
    return 段落表

def _区间信息(区间) -> tuple[int | None, float, float]:
    """取 (区间id, 开始秒, 结束秒)；id 缺失或非法时返回 None 与区间时间。"""
    来源 = 区间 if isinstance(区间, dict) else {}
    值 = 来源.get("区间id")
    if not isinstance(值, int) or isinstance(值, bool):
        try:
            值 = int(str(值).strip())
        except (TypeError, ValueError):
            值 = None
    开始 = _取数(来源.get("开始秒")) or 0.0
    结束 = _取数(来源.get("结束秒"))
    return 值, 开始, max(开始, 结束 if 结束 is not None else 开始)

def 聚类区间(疑难段: list[dict], 间隔秒: int = 默认间隔秒) -> dict:
    """疑难段聚类成复核区间，返回 {"区间": [...]}。

    相邻疑难段间隔小于等于阈值即并入同一区间（与流程图第九节口径一致）；
    间隔严格大于阈值才另起一个区间。
    """
    阈值 = _取数(间隔秒)
    阈值 = 阈值 if (阈值 and 阈值 > 0) else 0.0
    区间表: list[dict] = []
    for 开始, 结束 in _可用段落(疑难段):
        if 区间表 and (开始 - 区间表[-1]["结束秒"]) <= 阈值:
            区间表[-1]["结束秒"] = max(区间表[-1]["结束秒"], 结束)
            区间表[-1]["疑难数"] += 1
        else:
            区间表.append({"区间id": 0, "开始秒": 开始, "结束秒": 结束, "疑难数": 1})
    for 序号, 区间 in enumerate(区间表, 1):
        区间["区间id"] = 序号
    return {"区间": 区间表}

def _执行一轮(调用能力, 源音频路径: str, 超时: float, 模型配置, 序号: int) -> dict:
    """跑一轮转写（每轮术语提示不同）；底层失败或异常记进该轮条目，文本留空。"""
    提示 = 轮次提示表[序号 - 1] if 1 <= 序号 <= len(轮次提示表) else f"第{序号}轮：独立复听，核对上轮未确认处。"
    条目 = {"轮": 序号, "文本": "", "分段": [], "成功": False, "错误码": "", "错误说明": ""}
    参数 = {"文件路径": 源音频路径, "超时秒": 超时, "配置": 模型配置,
            "附加术语": 提示, "返回分段": True}
    try:
        结果 = 调用能力(转写能力id, 参数)
    except Exception as 错误:  # 底层异常不得外泄给调用方
        条目["错误码"] = "调用异常"
        条目["错误说明"] = f"第{序号}轮调用异常: {错误}"
        return 条目
    if not bool(getattr(结果, "成功", False)):
        条目["错误码"] = str(getattr(结果, "错误码", "") or "转写失败")
        条目["错误说明"] = str(getattr(结果, "错误说明", "") or f"第{序号}轮转写失败")
        return 条目
    值 = getattr(结果, "值", None)
    值字典 = 值 if isinstance(值, dict) else {}
    分段 = 值字典.get("分段")
    条目.update({"成功": True, "文本": str(值字典.get("文本") or "").strip(),
                "分段": 分段 if isinstance(分段, list) else []})
    return 条目

def _写复核盘(复核目录: str, 区间id: int, 数据: dict) -> tuple[str, str]:
    """写 复核_0001.json（id 补 4 位）；返回 (路径, 错误说明)。"""
    try:
        路径 = Path(复核目录).expanduser() / f"复核_{区间id:04d}.json"
    except (TypeError, ValueError) as 错误:
        return "", str(错误)
    序列化 = _底座("数据操作支持库.数据交换.序列化JSON", {"数据": 数据})
    if not _成功(序列化) or not isinstance(getattr(序列化, "值", None), str):
        return "", "数据无法序列化为 JSON"
    写 = _底座("系统核心支持库.资源管理.原子写入",
             {"目标路径": str(路径), "内容": getattr(序列化, "值") + "\n"})
    if not _成功(写):
        return "", _失败说明(写, "写盘失败")
    return str(路径), ""

def _截取区间(调用能力, 源音频路径: str, 开始: float, 结束: float,
             复核目录: str, 区间id: int, 超时: float) -> tuple[str, str]:
    """把区间音频截取到复核目录（复核只对区间音频转写，不对整场重复转写）。

    返回 (区间音频路径, 错误说明)；截取失败时路径为空、错误说明非空，调用方如实失败。
    """
    try:
        输出路径 = str(Path(复核目录).expanduser() / f"区间_{区间id:04d}.{区间音频格式}")
    except (TypeError, ValueError) as 错误:
         return "", f"复核目录不合法: {错误}"
    try:
        结果 = 调用能力(截取能力id, {"文件路径": 源音频路径, "开始秒": 开始, "结束秒": 结束,
                                    "输出格式": 区间音频格式, "输出路径": 输出路径, "超时秒": 超时})
    except Exception as 错误:  # 底层异常不得外泄给调用方
        return "", f"截取异常: {错误}"
    if not bool(getattr(结果, "成功", False)):
        return "", f"{str(getattr(结果, '错误码', '') or '截取失败')}: {str(getattr(结果, '错误说明', '') or '区间截取失败')}"
    return 输出路径, ""


def _读已有复核(复核目录: str, 区间id: int) -> dict | None:
    """复用已落盘复核：文件存在、区间id一致且轮次非空；否则返回 None（重新复核）。"""
    try:
        路径 = Path(复核目录).expanduser() / f"复核_{区间id:04d}.json"
    except (TypeError, ValueError):
        return None
    读 = _底座("文件系统支持库.文件操作.读取文件",
              {"文件路径": str(路径), "编码": "utf-8"})
    if not _成功(读) or not isinstance(getattr(读, "值", None), str):
        return None
    解析 = _底座("数据操作支持库.数据交换.反序列化JSON", {"文本": getattr(读, "值")})
    if not _成功(解析):
        return None
    数据 = getattr(解析, "值", None)
    try:
        一致 = isinstance(数据, dict) and int(数据.get("区间id") or 0) == int(区间id)
    except (TypeError, ValueError):
        return None
    if not 一致:
        return None
    轮次 = 数据.get("轮次")
    if not isinstance(轮次, list) or not 轮次:
        return None
    完成 = all(bool(条目.get("成功")) for 条目 in 轮次 if isinstance(条目, dict))
    return {"区间id": 区间id, "开始秒": 数据.get("开始秒"), "结束秒": 数据.get("结束秒"),
            "轮次": 轮次, "区间音频路径": 数据.get("区间音频路径") or "",
            "状态": "完成" if 完成 else "部分失败", "错误码": "", "错误说明": "",
            "写入路径": str(路径), "复用": True}


def 复核区间(源音频路径: str, 区间: dict, 复核目录: str, 调用能力,
             轮数: int = 默认轮数, 模型配置: dict | None = None,
             超时秒: float = 默认超时秒, 续跑: bool = True) -> dict:
    """对单个区间先截取区间音频、再跑多轮独立转写并落盘；已落盘且区间一致时直接复用。"""
    区间id, 开始, 结束 = _区间信息(区间)
    超时 = _取数(超时秒)

    def 失败(说明: str, 错误码: str = "参数不合法") -> dict:
        return {"区间id": 区间id if 区间id is not None else 0, "开始秒": 开始, "结束秒": 结束,
                "轮次": [], "状态": "失败", "错误码": 错误码, "错误说明": 说明,
                "区间音频路径": "", "写入路径": ""}

    检查表 = (
        (not isinstance(源音频路径, str) or not 源音频路径.strip(), "源音频路径 必须为非空文本"),
        (not isinstance(复核目录, str) or not 复核目录.strip(), "复核目录 必须为非空文本"),
        (区间id is None, "区间 必须为对象且含整数 区间id"),
        (not callable(调用能力), "调用能力 必须是可调用对象"),
        (isinstance(轮数, bool) or not isinstance(轮数, int) or 轮数 < 1, "轮数 必须为正整数"),
        (模型配置 is not None and not isinstance(模型配置, dict), "模型配置 必须为对象"),
        (超时 is None or 超时 <= 0, "超时秒 必须为正数"),
    )
    错误说明 = next((说明 for 触发, 说明 in 检查表 if 触发), "")
    if 错误说明:
        return 失败(错误说明)
    区间id = int(区间id)
    超时 = float(超时)

    if 续跑 and callable(调用能力):
        已有 = _读已有复核(复核目录, 区间id)
        if 已有 is not None:
            return 已有

    区间音频, 截取错误 = _截取区间(调用能力, 源音频路径, 开始, 结束, 复核目录, 区间id, 超时)
    if 截取错误:
        return 失败(f"区间截取失败: {截取错误}", "截取失败")

    轮次列表 = [_执行一轮(调用能力, 区间音频, 超时, 模型配置, 序号)
                for 序号 in range(1, 轮数 + 1)]
    写入路径, 写盘错误 = _写复核盘(
        复核目录, 区间id, {"区间id": 区间id, "开始秒": 开始, "结束秒": 结束,
                        "区间音频路径": 区间音频, "轮次": 轮次列表})
    失败轮 = [条目 for 条目 in 轮次列表 if not 条目["成功"]]
    说明列表 = [f"第{条目['轮']}轮: {条目['错误说明']}" for 条目 in 失败轮]
    if 写盘错误:
        说明列表.append(f"写盘失败: {写盘错误}")
    完成 = not 失败轮 and not 写盘错误
    return {"区间id": 区间id, "开始秒": 开始, "结束秒": 结束, "轮次": 轮次列表,
            "区间音频路径": 区间音频,
            "状态": "完成" if 完成 else "部分失败",
            "错误码": "" if 完成 else (失败轮[0]["错误码"] if 失败轮 else "写盘失败"),
            "错误说明": "" if 完成 else "；".join(说明列表), "写入路径": 写入路径}
