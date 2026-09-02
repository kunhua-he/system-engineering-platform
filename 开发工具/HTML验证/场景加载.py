"""包级验证场景解析与全集闭合校验。"""
from __future__ import annotations
import copy, json
from pathlib import Path
from typing import Any
from 开发工具.HTML验证.常量 import 场景契约版本
from 开发工具.HTML验证.单步场景 import 验证步骤
from 开发工具.HTML验证.多步场景 import 多步骤验证场景, 验证场景束
from 开发工具.HTML验证.制品事实 import _读取JSON严格, _扫描公开能力, _制品全文件摘要
from 开发工具.HTML验证.路径安全 import _安全合并路径, _校验动态声明
def _解析场景引用(包目录: Path) -> list[tuple[dict[str, Any], Path]]:
    """读取唯一 v1 契约；旧的一请求一场景格式直接阻断。"""
    引用路径 = 包目录 / "验证场景引用.json"
    数据 = _读取JSON严格(引用路径, "验证场景引用")
    if not isinstance(数据, dict) or 数据.get("契约版本") != 场景契约版本:
        raise ValueError(f"验证场景引用契约版本不合法或为旧格式: {引用路径}")
    if set(数据) != {"契约版本", "验证场景引用"} or not isinstance(数据.get("验证场景引用"), list):
        raise ValueError(f"验证场景引用契约不合法: {引用路径}")
    原始列表 = 数据["验证场景引用"]
    if not 原始列表:
        raise ValueError(f"验证场景引用为空: {引用路径}")
    场景表: list[tuple[dict[str, Any], Path]] = []
    for 序号, 引用 in enumerate(原始列表):
        if not isinstance(引用, dict) or not ({"场景"} <= set(引用) or {"场景文件"} <= set(引用)):
            raise ValueError(f"无效或旧格式验证场景引用: {引用路径}#{序号}")
        if "场景" in 引用:
            if set(引用) != {"场景"} or not isinstance(引用["场景"], dict):
                raise ValueError(f"内联场景引用不合法: {引用路径}#{序号}")
            场景表.append((引用["场景"], 包目录))
            continue
        if set(引用) - {"场景文件", "场景id", "范围"}:
            raise ValueError(f"场景文件引用含未知字段: {引用路径}#{序号}")
        相对 = 引用.get("场景文件")
        if not isinstance(相对, str) or not 相对:
            raise ValueError(f"场景文件引用不合法: {引用路径}#{序号}")
        文件 = _安全合并路径(包目录, 相对, "场景文件")
        场景数据 = _读取JSON严格(文件, "验证场景")
        if (not isinstance(场景数据, dict) or 场景数据.get("契约版本") != 场景契约版本
                or set(场景数据) != {"契约版本", "验证场景"}
                or not isinstance(场景数据.get("验证场景"), list)):
            raise ValueError(f"验证场景文件契约不合法或为旧格式: {文件}")
        引用id = 引用.get("场景id")
        命中 = [项 for 项 in 场景数据["验证场景"]
              if isinstance(项, dict) and (not 引用id or 项.get("场景id") == 引用id)]
        if not 命中:
            raise ValueError(f"场景文件没有命中引用: {文件}#{引用id}")
        场景表.extend((项, 包目录) for 项 in 命中)
    return 场景表



def _解析多步骤场景(原始: Any, 包目录: Path, 制品摘要: str) -> 多步骤验证场景:
    if not isinstance(原始, dict):
        raise ValueError("验证场景必须是对象")
    if set(原始) != {"场景id", "前置步骤", "目标步骤", "清理步骤"}:
        raise ValueError("验证场景字段不完整或为旧格式")
    场景id = 原始.get("场景id")
    if not isinstance(场景id, str) or not 场景id.strip():
        raise ValueError("验证场景缺少场景id")
    for 阶段 in ("前置步骤", "目标步骤", "清理步骤"):
        if not isinstance(原始[阶段], list):
            raise ValueError(f"场景 {场景id} 的{阶段}必须是列表")
    if not 原始["目标步骤"]:
        raise ValueError(f"场景 {场景id} 必须至少有一个目标步骤")
    已出现: set[str] = set()
    分段: dict[str, list[验证步骤]] = {}
    for 阶段 in ("前置步骤", "目标步骤", "清理步骤"):
        步骤表: list[验证步骤] = []
        for 步骤原始 in 原始[阶段]:
            步骤 = 验证步骤.从字典(步骤原始, 场景id)
            if 步骤.步骤id in 已出现:
                raise ValueError(f"场景 {场景id} 重复步骤id: {步骤.步骤id}")
            _校验动态声明(步骤.参数, 场景id, 已出现)
            步骤.制品摘要 = 制品摘要
            步骤表.append(步骤)
            已出现.add(步骤.步骤id)
        分段[阶段] = 步骤表
    return 多步骤验证场景(
        场景id.strip(), 包目录.resolve(), 分段["前置步骤"], 分段["目标步骤"], 分段["清理步骤"],
    )

def _校验场景全集(
    公开能力: set[str], 场景原始表: list[tuple[dict[str, Any], Path]], 制品摘要: str,
) -> 验证场景束:
    if not 场景原始表:
        raise ValueError("无任何有效验证场景")
    场景列表: list[多步骤验证场景] = []
    场景id集合: set[str] = set()
    全步骤能力: set[str] = set()
    for 原始, 包目录 in 场景原始表:
        场景 = _解析多步骤场景(原始, 包目录, 制品摘要)
        if 场景.场景id in 场景id集合:
            raise ValueError(f"重复场景id: {场景.场景id}")
        场景id集合.add(场景.场景id)
        场景列表.append(场景)
        全步骤能力.update(步骤.能力id for 阶段 in (场景.前置步骤, 场景.目标步骤, 场景.清理步骤) for 步骤 in 阶段)
    未公开 = 全步骤能力 - 公开能力
    if 未公开:
        raise ValueError(f"步骤绑定了非正式公开能力: {sorted(未公开)}")
    正向目标能力 = {
        步骤.能力id for 场景 in 场景列表 for 步骤 in 场景.目标步骤 if 步骤.预期成功
    }
    if 正向目标能力 != 公开能力:
        raise ValueError(
            "正式公开能力全集 != 正向目标步骤能力全集: "
            f"缺目标={sorted(公开能力 - 正向目标能力)} 多目标={sorted(正向目标能力 - 公开能力)}"
        )
    return 验证场景束(场景列表, set(公开能力), 制品摘要)

def _加载场景(制品目录: Path, 场景路径: Path | None) -> 验证场景束:
    公开能力, 包目录表 = _扫描公开能力(制品目录)
    摘要 = _制品全文件摘要(制品目录)["制品摘要"]
    if 场景路径 is None:
        原始表 = [条目 for 包目录 in 包目录表 for 条目 in _解析场景引用(包目录)]
    else:
        束 = _读取JSON严格(场景路径, "外部验证场景束")
        if not isinstance(束, dict) or 束.get("来源") != "包级验证场景引用":
            raise ValueError("外部场景束来源必须是包级验证场景引用")
        if 束.get("制品摘要") != 摘要:
            raise ValueError(f"外部场景束制品摘要不匹配: {束.get('制品摘要')} != {摘要}")
        if 束.get("契约版本") != 场景契约版本 or not isinstance(束.get("验证场景"), list):
            raise ValueError("外部场景束契约版本不合法或为旧格式")
        原始表 = []
        for 原始 in 束["验证场景"]:
            if not isinstance(原始, dict) or not isinstance(原始.get("包相对目录"), str):
                raise ValueError("外部场景束缺包相对目录")
            包目录 = _安全合并路径(制品目录, 原始["包相对目录"], "包相对目录")
            场景数据 = {键: 值 for 键, 值 in 原始.items() if 键 != "包相对目录"}
            原始表.append((场景数据, 包目录))
    return _校验场景全集(公开能力, 原始表, 摘要)
