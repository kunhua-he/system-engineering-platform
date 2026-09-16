"""缓存目录准备、任务指纹与项目状态读写（断点续跑唯一依据）。

约定：任一阶段产物存在且任务指纹一致 → 该阶段可跳过；指纹不一致只重算受影响的下游。
本文件只负责路径、指纹与状态；不含任何转写/裁决逻辑。

文件读写、目录创建与 JSON 解析统一经唯一能力调用服务走底座原子能力，
本文件不直接触碰标准库 I/O。
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

来源 = "直播逐字稿"
指纹文件名 = "任务指纹.json"
状态文件名 = "项目状态.json"


def _底座(能力id: str, 参数: dict):
    """经唯一能力调用服务调用底座原子能力；未装配或异常时返回 None。"""
    from 公共契约.能力契约.调用器 import 获取能力调用器
    try:
        return 获取能力调用器().调用能力(能力id, 参数, 调用方=来源)
    except Exception:
        return None


def _成功(结果对象) -> bool:
    """结果对象是否成功。"""
    return bool(结果对象 is not None and getattr(结果对象, "成功", False))


def 现在文本() -> str:
    """当前本地时间，ISO 格式到秒。"""
    return datetime.now().isoformat(timespec="seconds")


def 准备缓存(缓存目录: str) -> dict[str, Path]:
    """创建缓存目录骨架并返回命名路径表（键为阶段名）。"""
    根 = Path(缓存目录).expanduser().resolve()
    路径表 = {
        "根": 根,
        "元数据": 根 / "00_元数据",
        "音频": 根 / "01_音频",
        "分片": 根 / "02_分片",
        "分片转写": 根 / "03_分片转写",
        "复核": 根 / "06_复核",
        "证据包": 根 / "07_证据包",
        "裁决": 根 / "08_裁决",
        "合成": 根 / "09_合成",
        "质检": 根 / "10_质检",
    }
    for 名称, 路径 in 路径表.items():
        if 名称 == "根":
            continue
        _底座("文件系统支持库.文件操作.创建目录", {"目录路径": str(路径), "递归": True})
    路径表["疑难清单"] = 根 / "04_疑难清单.json"
    路径表["复核区间"] = 根 / "05_复核区间.json"
    路径表["指纹"] = 路径表["元数据"] / 指纹文件名
    路径表["状态"] = 路径表["元数据"] / 状态文件名
    return 路径表


def 计算文件摘要(文件路径: str) -> str:
    """计算文件 sha256；取不到返回空串。

    空串是「未知摘要」的哨兵值（不是「两个文件相同」）：调用方必须把空串
    当未知处理（见 指纹一致：空串一律判不一致），绝不能拿两份空串互比。
    """
    结果对象 = _底座("系统核心支持库.资源管理.创建内容摘要",
                   {"文件路径": str(文件路径), "算法": "sha256"})
    if not _成功(结果对象):
        return ""
    return str(getattr(结果对象, "值", "") or "")


def 读JSON(路径: Path) -> dict | None:
    """读 JSON；不存在或损坏返回 None（不抛异常）。"""
    读 = _底座("文件系统支持库.文件操作.读取文件",
              {"文件路径": str(路径), "编码": "utf-8"})
    if not _成功(读):
        return None
    文本 = getattr(读, "值", None)
    if not isinstance(文本, str) or not 文本.strip():
        return None
    解析 = _底座("数据操作支持库.数据交换.反序列化JSON", {"文本": 文本})
    if not _成功(解析):
        return None
    return getattr(解析, "值", None)


def 写JSON(路径: Path, 数据: dict) -> bool:
    """写 JSON（utf-8、缩进 2）；成功返回 True。"""
    序列化 = _底座("数据操作支持库.数据交换.序列化JSON", {"数据": 数据})
    if not _成功(序列化):
        return False
    文本 = getattr(序列化, "值", None)
    if not isinstance(文本, str):
        return False
    写 = _底座("文件系统支持库.文件操作.写入文件",
              {"文件路径": str(路径), "内容": 文本 + "\n", "编码": "utf-8"})
    return _成功(写)


def 读指纹(缓存: dict) -> dict | None:
    """读任务指纹；不存在返回 None。"""
    return 读JSON(缓存["指纹"])


def 写指纹(缓存: dict, 指纹: dict) -> bool:
    """写任务指纹。"""
    return 写JSON(缓存["指纹"], 指纹)


def _未知(值) -> bool:
    """该指纹字段是否是「未知」（缺失/None/空串/0）。

    未知 ≠ 相同：字段取不到（如摘要能力不可用返回空串、大小取不到返回 0）时
    绝不能判「指纹一致」，否则两个不同源文件会被判成同一任务而复用旧产物。
    """
    if 值 is None:
        return True
    if isinstance(值, str):
        return not 值.strip()
    if isinstance(值, bool):
        return not 值
    if isinstance(值, (int, float)):
        return 值 == 0
    return False


# 必须有值的字段：值来自能力调用或数值口径，为空串/0 只可能来自兜底 → 未知，直接判不一致。
指纹必有值字段 = ("源文件摘要", "源文件大小字节", "模式", "分片秒数")
# 允许为空的字段：调用方直传，「空串」是合法取值（无附加术语/未指定模型名）→ 逐字比较。
指纹可空字段 = ("附加术语", "模型名")


def 指纹一致(旧指纹: dict | None, 新指纹: dict) -> bool:
    """比较指纹关键字段：源文件摘要、大小、模式、分片秒数、附加术语、模型名。

    任一关键字段缺失/为 None/空串/0（未知）→ 判不一致（未知 ≠ 相同），
    即宁可重跑一遍，也不复用来源不明的旧产物。
    """
    if not isinstance(旧指纹, dict) or not isinstance(新指纹, dict):
        return False
    for 字段 in 指纹必有值字段:
        旧值, 新值 = 旧指纹.get(字段), 新指纹.get(字段)
        if _未知(旧值) or _未知(新值):
            return False
        if 旧值 != 新值:
            return False
    for 字段 in 指纹可空字段:
        if 字段 not in 旧指纹 or 字段 not in 新指纹:
            return False
        if 旧指纹.get(字段) != 新指纹.get(字段):
            return False
    return True


def 写状态(缓存: dict, 状态: dict) -> bool:
    """写项目状态（追加更新时间）。"""
    内容 = dict(状态)
    内容["更新时间"] = 现在文本()
    return 写JSON(缓存["状态"], 内容)


def 读状态(缓存: dict) -> dict | None:
    """读项目状态；不存在返回 None。"""
    return 读JSON(缓存["状态"])


def 产物状态(缓存: dict, 键: str, 子项: str | None = None) -> bool | None:
    """三态判定某阶段产物：True=存在且有内容；False=不存在或为空；None=判不了。

    None 只出现在底座能力调用失败（判断存在/列出目录 都没给出结论）时：
    让调用方能区分「没产出」「有产出」「这条判不了」，而不是把「判不了」当「有产出」。
    """
    路径 = 缓存.get(键) if isinstance(缓存, dict) else None
    if 路径 is None:
        return False
    目标 = (Path(路径) / 子项) if 子项 else Path(路径)
    存在 = _底座("文件系统支持库.文件操作.判断存在", {"文件路径": str(目标)})
    if not _成功(存在):
        return None   # 判断存在都失败 → 判不了（绝不按「存在」放行）
    if not bool(getattr(存在, "值", False)):
        return False
    if 子项:
        return True
    列 = _底座("文件系统支持库.文件操作.列出目录", {"目录路径": str(目标)})
    if not _成功(列):
        # 判断存在 已确认路径存在，列出目录 报「目录不存在」→ 存在但不是目录，是文件，视为已存在。
        # 其余失败（目录读取失败/参数不合法/调用器未装配）→ 拿不到结论，判不了。
        # 过去这里不分失败原因一律 return True，会把「没产出的阶段」当成已完成整段跳过。
        if str(getattr(列, "错误码", "") or "") == "目录不存在":
            return True
        return None
    return bool(getattr(列, "值", None))


def 产物存在(缓存: dict, 键: str, 子项: str | None = None) -> bool:
    """判断某阶段产物是否已存在（子项为空时判目录非空）。

    fail-closed：只有确凿「存在且有内容」才返回 True；判不了（能力调用失败）
    一律按不存在返回 False，调用方据此重跑该阶段，不跳过。
    """
    return 产物状态(缓存, 键, 子项) is True
