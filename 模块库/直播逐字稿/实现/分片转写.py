"""分片转写：按片截取音频 → 逐片转写（带分段指标）→ 逐片落盘，支持断点续跑。

长场次的关键：整段转写一旦中断就得从头再来，且中途没有任何中间产物。
本文件把音频切成固定时长的小片，每片独立截取、独立转写、独立落盘；
已存在的分片音频与分片转写结果在指纹一致时直接复用，中断后只补缺失片。

分段时间戳统一换算成绝对时间（片内相对秒 + 片起始秒），供窗口切分与疑难标记直接使用。
"""

from __future__ import annotations

from pathlib import Path
from 公共契约.基础类型.逻辑类型 import 真, 假

_来源 = "直播逐字稿"
截取能力id = "媒体处理支持库.FFmpeg媒体.截取音频"
转写能力id = "转写支持库.转写.转写音频文件"
分片音频格式 = "mp3"
默认单片超时秒 = 600.0


def _底座(能力id: str, 参数: dict):
    """经唯一能力调用服务调用底座原子能力；未装配或异常时返回 None。"""
    from 公共契约.能力契约.调用器 import 获取能力调用器
    try:
        return 获取能力调用器().调用能力(能力id, 参数, 调用方=_来源)
    except Exception:
        return None


def _成功(结果对象) -> bool:
    return bool(结果对象 is not None and getattr(结果对象, "成功", 假))


def _读JSON(路径: Path) -> dict | None:
    """经底座读并解析 JSON；不存在或损坏返回 None。"""
    读 = _底座("文件系统支持库.文件操作.读取文件",
              {"文件路径": str(路径), "编码": "utf-8"})
    if not _成功(读) or not isinstance(getattr(读, "值", None), str):
        return None
    解析 = _底座("数据操作支持库.数据交换.反序列化JSON", {"文本": getattr(读, "值")})
    if not _成功(解析):
        return None
    return getattr(解析, "值", None)


def _写JSON(路径: Path, 数据: dict) -> bool:
    """经底座序列化并写 JSON（utf-8、缩进 2）；成功返回 True。"""
    序列化 = _底座("数据操作支持库.数据交换.序列化JSON", {"数据": 数据})
    if not _成功(序列化) or not isinstance(getattr(序列化, "值", None), str):
        return 假
    写 = _底座("系统核心支持库.资源管理.原子写入",
             {"目标路径": str(路径), "内容": getattr(序列化, "值") + "\n"})
    return _成功(写)


def 分片区间表(时长秒: float, 分片秒数: int) -> list[dict]:
    """按分片秒数切出 [(序号, 开始秒, 结束秒)]；末尾不足一片也算一片。"""
    总时长 = max(0.0, float(时长秒 or 0.0))
    片长 = max(1, int(分片秒数 or 300))
    区间表: list[dict] = []
    开始 = 0.0
    while 开始 < 总时长 - 0.05:
        结束 = min(总时长, 开始 + 片长)
        区间表.append({"序号": len(区间表) + 1, "开始秒": round(开始, 3), "结束秒": round(结束, 3)})
        开始 = 结束
    if not 区间表:
        区间表.append({"序号": 1, "开始秒": 0.0, "结束秒": round(总时长, 3)})
    return 区间表


def _截取分片(源文件路径: str, 缓存: dict, 区间: dict, 调用能力, 超时秒: float) -> tuple[str, str]:
    """把一片音频截到 02_分片/分片_NNNN.mp3；已存在直接复用。返回 (路径, 错误说明)。"""
    目标 = Path(缓存["分片"]) / f"分片_{区间['序号']:04d}.{分片音频格式}"
    存在 = _底座("文件系统支持库.文件操作.判断存在", {"文件路径": str(目标)})
    if bool(getattr(存在, "值", 假)):
        大小 = _底座("文件系统支持库.文件操作.获取大小", {"文件路径": str(目标)})
        if int(getattr(大小, "值", 0) or 0) > 0:
            return str(目标), ""
    结果对象 = 调用能力(截取能力id, {"文件路径": 源文件路径, "开始秒": 区间["开始秒"],
                                  "结束秒": 区间["结束秒"], "输出格式": 分片音频格式,
                                  "输出路径": str(目标), "超时秒": 超时秒,
                                  # 截取音频内部会对**源文件**做时长预检，底座默认上限 7200 秒；
                                  # 长场次（实测 10559 秒）不显式放宽会在每一片都判「超长媒体」。
                                  "最大时长秒": 43200.0})
    if not 结果对象.成功:
        return "", f"{结果对象.错误码}: {结果对象.错误说明}"
    return str(目标), ""


def _绝对化分段(分段: list, 片开始秒: float) -> list[dict]:
    """把片内相对时间戳换算成绝对时间，供整场窗口与疑难判定使用。"""
    结果: list[dict] = []
    for 段 in 分段 or []:
        if not isinstance(段, dict):
            continue
        条目 = dict(段)
        try:
            条目["开始秒"] = round(float(段.get("开始秒") or 0.0) + 片开始秒, 3)
            条目["结束秒"] = round(float(段.get("结束秒") or 0.0) + 片开始秒, 3)
        except (TypeError, ValueError):
            continue
        结果.append(条目)
    return 结果


def _取数(值, 默认: float) -> float:
    """宽松取数：数值或数字文本转 float；取不到才用默认（不能用 `or`，0.0 是合法值）。"""
    try:
        return float(值)
    except (TypeError, ValueError):
        return 默认


def _区间吻合(已有: dict, 区间: dict) -> bool:
    """复用判定：已落盘分片的序号与时间区间必须与当前分片一致（防整段旧产物被误复用）。"""
    try:
        return (int(_取数(已有.get("分片序号"), 0.0)) == int(区间["序号"])
                and abs(_取数(已有.get("开始秒"), -1.0) - float(区间["开始秒"])) < 0.01
                and abs(_取数(已有.get("结束秒"), -1.0) - float(区间["结束秒"])) < 0.01)
    except (TypeError, ValueError, KeyError):
        return 假


def _转写一片(音频路径: str, 区间: dict, 缓存: dict, 调用能力, 模型配置,
             附加术语: str, 超时秒: float, 续跑: bool) -> tuple[dict | None, str, bool]:
    """转写一片（已落盘且区间吻合才复用）；返回 (分片转写条目, 错误说明, 是否复用)。"""
    落盘 = Path(缓存["分片转写"]) / f"分片_{区间['序号']:04d}.json"
    if 续跑:
        已有 = _读JSON(落盘)
        if isinstance(已有, dict) and isinstance(已有.get("分段"), list) and _区间吻合(已有, 区间):
            return 已有, "", 真
    参数 = {"文件路径": 音频路径, "超时秒": 超时秒, "配置": 模型配置,
            "附加术语": 附加术语, "返回分段": 真}
    结果对象 = 调用能力(转写能力id, 参数)
    if not 结果对象.成功:
        return None, f"第{区间['序号']}片转写失败: {结果对象.错误码} {结果对象.错误说明}", 假
    值 = 结果对象.值 or {}
    条目 = {"分片序号": 区间["序号"], "开始秒": 区间["开始秒"], "结束秒": 区间["结束秒"],
            "文本": str(值.get("文本") or "").strip(),
            "分段": _绝对化分段(值.get("分段") or [], 区间["开始秒"]),
            "语言": str(值.get("语言") or "")}
    _写JSON(落盘, 条目)
    return 条目, "", 假


def 分片转写(源文件路径: str, 缓存: dict, 时长秒: float, 分片秒数: int, 调用能力,
             模型配置: dict | None = None, 附加术语: str = "",
             超时秒: float = 默认单片超时秒, 续跑: bool = 真) -> dict:
    """逐片截取并转写，产出 分片转写列表（与单次整段转写同构，可直接喂疑难标记）。"""
    区间表 = 分片区间表(时长秒, 分片秒数)
    分片转写列表: list[dict] = []
    错误表: list[str] = []
    复用数 = 0
    for 区间 in 区间表:
        音频路径, 截取错误 = _截取分片(源文件路径, 缓存, 区间, 调用能力, 超时秒)
        if 截取错误:
            错误表.append(f"第{区间['序号']}片截取失败: {截取错误}")
            continue
        条目, 转写错误, 复用 = _转写一片(音频路径, 区间, 缓存, 调用能力, 模型配置,
                                     附加术语, 超时秒, 续跑)
        if 转写错误:
            错误表.append(转写错误)
            continue
        if 条目 is None:
            continue
        if 复用:
            复用数 += 1
        分片转写列表.append(条目)
    return {"分片转写列表": 分片转写列表, "分片总数": len(区间表),
            "已完成": len(分片转写列表), "复用": 复用数,
            "状态": "完成" if len(分片转写列表) == len(区间表) else "部分失败",
            "错误说明": "；".join(错误表)}
