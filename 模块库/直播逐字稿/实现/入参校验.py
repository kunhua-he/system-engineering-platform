"""逐字稿全自动精校入参校验（阶段0）：三个绝对路径 + 模式号 + 可选项。

只做校验与必要的目录创建，不启动任何转写；通过返回 None，失败返回 结果.失败。
校验项与 `开发文档/当前流程图.md` 第九节 阶段0 一一对应。
"""

from __future__ import annotations

import shutil
from pathlib import Path

from 公共契约.基础类型.结果类型 import 结果
from 公共契约.基础类型.逻辑类型 import 真, 假

来源 = "直播逐字稿"


def _底座(能力id: str, 参数: dict):
    """经唯一能力调用服务调用底座原子能力；未装配或异常时返回 None。"""
    from 公共契约.能力契约.调用器 import 获取能力调用器
    try:
        return 获取能力调用器().调用能力(能力id, 参数, 调用方=来源)
    except Exception:
        return None


def _成功(结果对象) -> bool:
    return bool(结果对象 is not None and getattr(结果对象, "成功", 假))


媒体扩展名表 = {
    ".mp4", ".mov", ".mkv", ".flv", ".ts", ".avi", ".m4v", ".wmv", ".webm",
    ".m4a", ".mp3", ".wav", ".aac", ".flac", ".ogg", ".aiff", ".amr",
}
磁盘余量倍数 = 1.5


def 支持的媒体扩展名() -> set[str]:
    """返回内置支持的媒体扩展名集合（小写、含点）。"""
    return set(媒体扩展名表)


def _文本(参数: dict, 名称: str) -> str:
    return str(参数.get(名称) or "").strip()


def _校验绝对路径(值: str, 名称: str) -> 结果 | None:
    if not 值:
        return 结果.失败("参数不合法", f"{名称} 必须为非空文本", 来源=来源)
    if not Path(值).expanduser().is_absolute():
        return 结果.失败("参数不合法", f"{名称} 必须是绝对路径: {值}", 来源=来源)
    return None


def _校验可创建(目录: Path, 名称: str, 开工ID: str | None = None) -> 结果 | None:
    创建 = _底座("文件系统支持库.文件操作.创建目录",
              {"目录路径": str(目录), "递归": 真, "开工ID": 开工ID or ""})
    if not _成功(创建):
        说明 = getattr(创建, "错误说明", "") or "底座不可用"
        return 结果.失败("写入失败", f"{名称} 无法创建: {说明}", 来源=来源)
    return None


def _校验模式(参数: dict, 注册表: dict) -> 结果 | None:
    模式号 = 参数.get("模式")
    if isinstance(模式号, bool) or not isinstance(模式号, int):
        return 结果.失败("参数不合法", "模式 必须是整数编号", 来源=来源)
    合法编号 = [int(条目.get("模式")) for 条目 in (注册表.get("模式列表") or [])]
    if 模式号 not in 合法编号:
        return 结果.失败("未知模式", f"模式 {模式号} 不在模式注册表（可用：{合法编号}）", 来源=来源)
    return None


def _校验数值(参数: dict) -> 结果 | None:
    分片秒数 = 参数.get("分片秒数", 300)
    if isinstance(分片秒数, bool) or not isinstance(分片秒数, int) or 分片秒数 < 1:
        return 结果.失败("参数不合法", "分片秒数 必须为不小于 1 的整数", 来源=来源)
    超时秒 = 参数.get("超时秒", 3600.0)
    if isinstance(超时秒, bool) or not isinstance(超时秒, (int, float)) or 超时秒 <= 0:
        return 结果.失败("参数不合法", "超时秒 必须为正数", 来源=来源)
    if 参数.get("模型配置") is not None and not isinstance(参数.get("模型配置"), dict):
        return 结果.失败("参数不合法", "模型配置 必须为对象", 来源=来源)
    return None


def _校验磁盘(源文件大小: int, 缓存根: Path) -> 结果 | None:
    try:
        需要 = 源文件大小 * 磁盘余量倍数
        可用 = shutil.disk_usage(str(缓存根)).free
    except OSError as 错误:
        return 结果.失败("磁盘空间不足", f"无法读取磁盘空间: {错误}", 来源=来源)
    if 可用 < 需要:
        return 结果.失败(
            "磁盘空间不足",
            f"缓存盘可用 {可用 // 1048576}MB，小于所需的 {int(需要) // 1048576}MB",
            来源=来源)
    return None


def 校验入参(参数: dict, 注册表: dict, 开工ID: str | None = None) -> 结果 | None:
    """校验全自动精校入参；通过返回 None，失败返回 结果.失败。

    开工ID 穿透（2026-09-25）：本阶段会建 导出路径父目录 / 缓存目录（`创建目录`），
    按「活跃写租约所有者 == 开工ID」判授权，原样透传。
    """
    if not isinstance(参数, dict):
        return 结果.失败("参数不合法", "参数 必须为对象", 来源=来源)
    源文件原文 = _文本(参数, "源文件路径")
    导出原文 = _文本(参数, "导出路径")
    缓存原文 = _文本(参数, "缓存目录")
    for 名称, 值 in (("源文件路径", 源文件原文), ("导出路径", 导出原文), ("缓存目录", 缓存原文)):
        错误 = _校验绝对路径(值, 名称)
        if 错误:
            return 错误

    源文件 = Path(源文件原文).expanduser()
    导出路径 = Path(导出原文).expanduser()
    缓存根 = Path(缓存原文).expanduser()
    源文件大小 = _底座("文件系统支持库.文件操作.获取大小", {"文件路径": str(源文件)})
    if not _成功(源文件大小):
        return 结果.失败("文件不存在", f"源文件不存在或不是文件: {源文件}", 来源=来源)
    if 源文件.suffix.lower() not in 媒体扩展名表:
        return 结果.失败("不支持的媒体格式",
                        f"不支持的扩展名 {源文件.suffix or '(无)'}；支持：{sorted(媒体扩展名表)}",
                        来源=来源)
    if 导出路径.resolve() == 源文件.resolve():
        return 结果.失败("参数不合法", "导出路径 不能与源文件路径相同（防覆盖原始素材）", 来源=来源)
    缓存根已解析 = 缓存根.resolve()
    if 缓存根已解析 == 导出路径.resolve() or 缓存根已解析 in 导出路径.resolve().parents:
        return 结果.失败("参数不合法", "导出路径 不能位于缓存目录内（防交付物混进缓存）", 来源=来源)
    if 导出路径.resolve() in 源文件.resolve().parents:
        return 结果.失败("参数不合法", "导出路径 不能是源文件所在目录（防误覆盖原始素材）", 来源=来源)

    错误 = (_校验可创建(导出路径.parent, "导出路径的父目录", 开工ID)
            or _校验可创建(缓存根, "缓存目录", 开工ID))
    if 错误:
        return 错误
    错误 = _校验模式(参数, 注册表) or _校验数值(参数)
    if 错误:
        return 错误
    return _校验磁盘(int(getattr(源文件大小, "值", 0) or 0), 缓存根)
