"""直播逐字稿模块（功能模块）：组合 媒体处理/媒体转写 公开能力，把直播媒体文件变成逐字稿。

只经 获取能力调用器().调用能力 组合现有公开能力，不 import 支持库/提供者/实现目录。
对外能力：
- 检查可用性：探测 ffmpeg(媒体处理) 与 转写(媒体转写) 链路是否就绪。
- 转写媒体文件：传视频/音频绝对路径 → 探测 → 按类型走对应转写能力 → 产出带时间戳的原始逐字稿文件。
- 读取项目状态：读取输出目录下的项目状态（供断点续跑/进度查询）。
未配置模型如实返回 未配置模型，绝不伪造转写成功。
"""

from __future__ import annotations

import json
from pathlib import Path

from 公共契约.基础类型.结果类型 import 结果

来源 = "直播逐字稿"
默认转写超时秒 = 300.0
默认探测超时秒 = 60.0
默认分片秒数 = 300
默认重叠秒数 = 15


def _调用(能力id: str, 请求参数: dict) -> 结果:
    """经唯一能力调用服务调用支持库能力；未装配/异常时如实返回失败。"""
    from 公共契约.能力契约.调用器 import 获取能力调用器
    try:
        调用器 = 获取能力调用器()
        return 调用器.调用能力(能力id, 请求参数, 调用方=来源)
    except Exception as 错误:
        return 结果.失败("提供者不可用", f"{能力id} 调用失败: {错误}", 来源=来源)


def _校验文本(值, 名称: str, *, 必填: bool = True) -> 结果 | None:
    if 值 is None and not 必填:
        return None
    if not isinstance(值, str) or not 值.strip():
        return 结果.失败("参数不合法", f"{名称} 必须为非空文本", 来源=来源)
    return None


def _校验数值(值, 名称: str, 最小值: float = 0, *, 必填: bool = True) -> 结果 | None:
    if 值 is None and not 必填:
        return None
    if isinstance(值, bool) or not isinstance(值, (int, float)) or 值 < 最小值:
        return 结果.失败("参数不合法", f"{名称} 必须为不小于 {最小值} 的数", 来源=来源)
    return None


def 检查可用性(超时秒: float = 默认探测超时秒, 配置: dict | None = None) -> 结果:
    """检查直播逐字稿链路可用性：媒体探测(ffmpeg) 与 转写模型。"""
    错误 = _校验数值(超时秒, "超时秒")
    if 错误:
        return 错误
    if 配置 is not None and not isinstance(配置, dict):
        return 结果.失败("参数不合法", "配置 必须为对象", 来源=来源)
    转写参数 = {"超时秒": 超时秒}
    if 配置 is not None:
        转写参数["配置"] = 配置
    转写结果 = _调用("转写支持库.转写.检查可用性", 转写参数)
    媒体结果 = _调用("媒体处理支持库.FFmpeg媒体.检查提供者", {"超时秒": 超时秒})
    可用 = bool(转写结果.成功 and 媒体结果.成功)
    值 = {
        "可用": 可用,
        "ffmpeg可用": bool(媒体结果.成功),
        "转写可用": bool(转写结果.成功),
        "转写详情": 转写结果.值 if 转写结果.成功 else {"错误码": 转写结果.错误码},
    }
    if 可用:
        return 结果.成功结果(值)
    return 结果.失败("提供者不可用", "转写或媒体探测链路不可用", 来源=来源, 详情=值)


def _探测媒体(文件路径: str, 超时秒: float) -> 结果:
    """调用媒体处理支持库.探测媒体（注册表原子能力）；返回 结果(值=探测信息)。"""
    return _调用("媒体处理支持库.FFmpeg媒体.探测媒体", {"文件路径": 文件路径, "超时秒": 超时秒})


def _转写文件(文件路径: str, 超时秒: float, 模型配置: dict | None,
             附加术语: str = "") -> 结果:
    """调用 转写支持库.转写.转写音频文件（mlx_whisper 内部解码音轨，视频/音频均可）。"""
    模型参数: dict[str, object] = {"配置": 模型配置} if 模型配置 is not None else {}
    if 附加术语:
        模型参数["附加术语"] = 附加术语
    return _调用("转写支持库.转写.转写音频文件",
                 {"文件路径": 文件路径, "超时秒": 超时秒, **模型参数})


def 转写媒体文件(文件路径: str, 输出目录: str, 分片秒数: int = 默认分片秒数,
                重叠秒数: int = 默认重叠秒数, 模型配置: dict | None = None,
                附加术语: str = "", 超时秒: float = 默认转写超时秒) -> 结果:
    """转写直播媒体文件为原始逐字稿（探测 → 转写 → 落盘 03_原始逐字稿.txt）。"""
    for 名称, 值, 类型 in (("文件路径", 文件路径, "文本"), ("输出目录", 输出目录, "文本")):
        错误 = _校验文本(值, 名称)
        if 错误:
            return 错误
    if not Path(文件路径).is_file():
        return 结果.失败("文件不存在", f"媒体文件不存在: {文件路径}", 来源=来源)
    错误 = _校验数值(分片秒数, "分片秒数", 1) or _校验数值(重叠秒数, "重叠秒数", 0) or _校验数值(超时秒, "超时秒", 1)
    if 错误:
        return 错误
    if 模型配置 is not None and not isinstance(模型配置, dict):
        return 结果.失败("参数不合法", "模型配置 必须为对象", 来源=来源)

    输出根 = Path(输出目录).expanduser().resolve()
    输出根.mkdir(parents=True, exist_ok=True)

    探测 = _探测媒体(文件路径, 60.0)
    if not 探测.成功:
        return 结果.失败(探测.错误码 or "媒体探测失败", 探测.错误说明 or "媒体探测失败", 来源=来源)
    时长秒 = float((探测.值 or {}).get("时长秒") or 0)
    格式 = str((探测.值 or {}).get("格式") or Path(文件路径).suffix.lstrip("."))

    转写 = _转写文件(文件路径, 超时秒, 模型配置, 附加术语)
    if not 转写.成功:
        return 结果.失败(转写.错误码 or "转写失败", 转写.错误说明 or "转写失败", 来源=来源,
                        详情={"文件路径": 文件路径})
    值 = 转写.值 or {}
    文本 = str(值.get("文本") or "").strip()
    语言 = str(值.get("语言") or "")

    元数据目录 = 输出根 / "00_元数据"
    转录底稿目录 = 输出根 / "02_转录底稿"
    元数据目录.mkdir(parents=True, exist_ok=True)
    转录底稿目录.mkdir(parents=True, exist_ok=True)
    原文路径 = 转录底稿目录 / "03_原始逐字稿.txt"

    行内容 = f"[00:00-{时长秒:06.1f}] {文本}" if 文本 else ""
    try:
        原文路径.write_text(行内容 + "\n", encoding="utf-8")
    except OSError as 错误:
        return 结果.失败("写入失败", f"无法写原始逐字稿: {错误}", 来源=来源)

    状态 = {
        "状态": "转写完成" if 文本 else "转写空结果",
        "阶段": "原始转写",
        "源文件": str(Path(文件路径).resolve()),
        "源格式": 格式,
        "时长秒": 时长秒,
        "文本长度": len(文本),
        "语言": 语言,
        "分片秒数": 分片秒数,
        "重叠秒数": 重叠秒数,
    }
    try:
        (元数据目录 / "项目状态.json").write_text(
            json.dumps(状态, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except OSError:
        pass

    if not 文本:
        return 结果.失败("转写失败", "转写返回空文本", 来源=来源, 详情={"输出目录": str(输出根)})
    return 结果.成功结果({
        "输出目录": str(输出根),
        "状态": "转写完成",
        "场次名": Path(文件路径).stem,
        "原始逐字稿路径": str(原文路径),
        "疑难清单路径": "",
        "已完成分片": 1,
        "分片总数": 1,
        "语言": 语言,
        "时长秒": 时长秒,
    })


def 读取项目状态(输出目录: str) -> 结果:
    """读取输出目录下的 00_元数据/项目状态.json（断点续跑查询用）。"""
    错误 = _校验文本(输出目录, "输出目录")
    if 错误:
        return 错误
    状态路径 = Path(输出目录).expanduser().resolve() / "00_元数据" / "项目状态.json"
    if not 状态路径.is_file():
        return 结果.失败("目录不存在", f"未找到项目状态文件: {状态路径}", 来源=来源)
    try:
        数据 = json.loads(状态路径.read_text(encoding="utf-8"))
    except Exception as 错误:
        return 结果.失败("读取失败", f"项目状态文件无法解析: {错误}", 来源=来源)
    return 结果.成功结果(数据)
