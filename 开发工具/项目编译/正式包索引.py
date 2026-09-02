"""编译链唯一正式包索引。

这里是快速编译与独立项目编译共同使用的包发现事实源。模板、样板和
其它明确标记为非生产的包永远不会进入正式索引；如果调用方显式引用
被排除的包，必须由调用方得到明确的阻断，而不是静默忽略。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


非生产路径片段 = {"_模板", "模板", "样板", "非生产", "开发样例"}
非生产字段 = ("非生产", "仅供复制", "仅供开发", "模板", "样板")
聚合支持库名表 = {"系统核心支持库", "大语言模型支持库", "办公文档支持库",
              "文件系统支持库", "数据操作支持库", "网络通信支持库"}


def _是聚合父包(系统根: Path, 包路径: Path, 类型目录: str) -> bool:
    """判断只作目录视图的聚合父包，与运行时发现器保持同一口径。"""
    if 类型目录 != "支持库":
        return False
    try:
        相对部分 = 包路径.resolve().relative_to((系统根 / "支持库").resolve()).parts
    except ValueError:
        return False
    return (len(相对部分) >= 2
            and 相对部分[1] in 聚合支持库名表
            and not (包路径 / "能力定义.json").is_file())


def _读取(路径: Path) -> dict[str, Any]:
    try:
        数据 = json.loads(路径.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as 错误:
        raise ValueError(f"包声明不可读取: {路径}: {错误}") from 错误
    if not isinstance(数据, dict):
        raise ValueError(f"包声明必须是对象: {路径}")
    return 数据


def _是非生产包(声明路径: Path, 声明: dict[str, Any], 包id: str) -> bool:
    """按物理目录和显式声明双重判断，避免模板改名后漏入生产索引。"""
    if any(片段 in 非生产路径片段 for 片段 in 声明路径.parent.parts):
        return True
    if 包id.startswith("模块库._模板"):
        return True
    for 字段 in 非生产字段:
        值 = 声明.get(字段)
        if isinstance(值, bool) and 值:
            return True
        if isinstance(值, str) and 值.strip().lower() in {"是", "true", "1", "非生产"}:
            return True
    状态 = str(声明.get("状态", "")).strip().lower()
    return 状态 in {"非生产", "草稿", "模板", "样板", "deprecated", "废弃"}


def _扫描包(系统根: Path, 类型目录: str) -> tuple[
    dict[str, tuple[Path, dict[str, Any]]], dict[str, str]
]:
    """扫描一种包类型，返回正式包和被排除包的原因表。"""
    正式: dict[str, tuple[Path, dict[str, Any]]] = {}
    排除: dict[str, str] = {}
    根 = 系统根 / 类型目录
    if not 根.is_dir():
        return 正式, 排除
    for 声明路径 in sorted(根.rglob("包声明.json")):
        声明 = _读取(声明路径)
        包id = str(声明.get("包id", "")).strip()
        if not 包id:
            raise ValueError(f"包声明缺少包id: {声明路径}")
        if _是非生产包(声明路径, 声明, 包id):
            排除[包id] = f"非生产包排除: {声明路径.parent}"
            continue
        if _是聚合父包(系统根, 声明路径.parent, 类型目录):
            continue
        if 包id in 正式 and 正式[包id][0] != 声明路径.parent:
            raise ValueError(f"正式包id重复: {包id} -> {正式[包id][0]} / {声明路径.parent}")
        正式[包id] = (声明路径.parent, 声明)
    return 正式, 排除


def 构建索引(系统根: Path) -> dict[str, Any]:
    """建立唯一可调用索引；内部/外部能力只区分可见性，不分叉调用通道。"""
    系统根 = Path(系统根).resolve()
    支持库, 支持库排除 = _扫描包(系统根, "支持库")
    模块库, 模块库排除 = _扫描包(系统根, "模块库")
    所有包 = {**支持库, **模块库}
    能力所有者: dict[str, str] = {}
    依赖能力所有者: dict[str, str] = {}
    能力排除: dict[str, str] = {}
    能力冲突: dict[str, list[str]] = {}
    for 包id, (包路径, 声明) in sorted(所有包.items()):
        能力表 = 声明.get("能力", [])
        if not isinstance(能力表, list):
            raise ValueError(f"包 {包id} 的能力必须是列表")
        # 聚合父包只作视图，不占用子包 owner；真实叶子包即使没有
        # 能力定义.json（如前端描述包）仍必须进入唯一可调用索引。
        子声明 = [路径 for 路径 in 包路径.rglob("包声明.json") if 路径.parent != 包路径]
        if 子声明:
            continue
        # 加载器对六大后端聚合库内“无能力定义”的目录分组不装配，索引必须同口径。
        if 类型目录 := ("支持库" if 包路径.is_relative_to(系统根 / "支持库") else "模块库"):
            相对 = 包路径.relative_to(系统根 / 类型目录).parts
            聚合库名表 = {"系统核心支持库", "大语言模型支持库", "办公文档支持库",
                        "文件系统支持库", "数据操作支持库", "网络通信支持库"}
            if (类型目录 == "支持库" and len(相对) >= 3 and 相对[1] in 聚合库名表
                    and not (包路径 / "能力定义.json").is_file()):
                continue
        for 能力 in 能力表:
            if not isinstance(能力, dict) or not str(能力.get("能力id", "")).strip():
                raise ValueError(f"包 {包id} 存在无效能力声明")
            能力id = str(能力["能力id"]).strip()
            旧 = 依赖能力所有者.get(能力id)
            if 旧 and 旧 != 包id:
                能力冲突.setdefault(能力id, sorted({旧, 包id})).append(包id)
                能力冲突[能力id] = sorted(set(能力冲突[能力id]))
                依赖能力所有者[能力id] = "冲突:" + "|".join(能力冲突[能力id])
            else:
                依赖能力所有者[能力id] = 包id
            能力所有者[能力id] = 依赖能力所有者[能力id]
    for 包id, 原因 in {**支持库排除, **模块库排除}.items():
        # 排除包的能力只用于给显式引用提供清晰阻断原因，绝不进入 owner。
        for 根 in (系统根 / "支持库", 系统根 / "模块库"):
            for 声明路径 in 根.rglob("包声明.json") if 根.is_dir() else []:
                try:
                    声明 = _读取(声明路径)
                except ValueError:
                    continue
                if str(声明.get("包id", "")).strip() != 包id:
                    continue
                for 能力 in 声明.get("能力", []) if isinstance(声明.get("能力", []), list) else []:
                    if isinstance(能力, dict) and str(能力.get("能力id", "")).strip():
                        能力排除[str(能力["能力id"]).strip()] = 原因
    return {
        "支持库": 支持库,
        "模块库": 模块库,
        "能力所有者": 能力所有者,
        "依赖能力所有者": 依赖能力所有者,
        "能力冲突": 能力冲突,
        "能力排除": 能力排除,
        "排除包": {**支持库排除, **模块库排除},
    }


def 正式包表(系统根: Path) -> tuple[
    dict[str, tuple[Path, dict[str, Any]]], dict[str, tuple[Path, dict[str, Any]]]
]:
    索引 = 构建索引(系统根)
    return 索引["支持库"], 索引["模块库"]


def 能力所有者表(系统根: Path) -> dict[str, str]:
    return dict(构建索引(系统根)["能力所有者"])


def 排除包表(系统根: Path) -> dict[str, str]:
    return dict(构建索引(系统根)["排除包"])


def 校验显式包引用(系统根: Path, 包id: str) -> None:
    """显式引用模板/非生产包必须失败，提示真实排除原因。"""
    索引 = 构建索引(系统根)
    if 包id in 索引["排除包"]:
        raise ValueError(f"包 {包id} 被拒绝：{索引['排除包'][包id]}")
    if 包id not in 索引["支持库"] and 包id not in 索引["模块库"]:
        raise ValueError(f"正式包不存在: {包id}")


def 校验能力引用(系统根: Path, 能力id: str) -> None:
    索引 = 构建索引(系统根)
    if 能力id in 索引["能力排除"]:
        raise ValueError(f"能力 {能力id} 被拒绝：{索引['能力排除'][能力id]}")
    if 能力id not in 索引["能力所有者"]:
        raise ValueError(f"正式能力不存在: {能力id}")


def _依赖项目标(依赖: Any) -> tuple[str, str, str | None]:
    if isinstance(依赖, str):
        return 依赖.strip(), "", None
    if not isinstance(依赖, dict):
        return "", "", None
    包id = str(依赖.get("包id") or 依赖.get("包") or "").strip()
    能力id = str(依赖.get("能力id") or 依赖.get("能力") or "").strip()
    版本 = 依赖.get("版本")
    return 包id, 能力id, str(版本) if 版本 is not None else None


def 解析依赖闭包(
    系统根: Path,
    初始支持库: set[str],
    初始模块: set[str],
    *,
    支持库表: dict[str, tuple[Path, dict[str, Any]]] | None = None,
    模块表: dict[str, tuple[Path, dict[str, Any]]] | None = None,
    能力归属表: dict[str, str] | None = None,
) -> tuple[set[str], set[str], list[dict[str, Any]]]:
    """唯一依赖闭包解析器：缺包、owner冲突、循环一律阻断。"""
    索引 = 构建索引(系统根)
    支持库表 = 支持库表 if 支持库表 is not None else 索引["支持库"]
    模块表 = 模块表 if 模块表 is not None else 索引["模块库"]
    能力归属 = 能力归属表 if 能力归属表 is not None else 索引["依赖能力所有者"]
    全部包 = {**支持库表, **模块表}
    选中支持库, 选中模块 = set(), set()
    依赖锁: list[dict[str, Any]] = []
    已完成: set[str] = set()
    访问栈: list[str] = []

    def 加入(包id: str, 来源: str) -> None:
        if not 包id:
            raise ValueError(f"{来源} 的依赖缺少包id或能力")
        if 包id in 索引["排除包"] and 支持库表 is 索引["支持库"]:
            raise ValueError(f"{来源} 依赖非生产包 {包id}：{索引['排除包'][包id]}")
        if 包id not in 全部包:
            raise ValueError(f"{来源} 的依赖包不存在: {包id}")
        if 包id in 访问栈:
            循环 = " -> ".join(访问栈[访问栈.index(包id):] + [包id])
            raise ValueError(f"检测到依赖循环: {循环}")
        if 包id in 已完成:
            return
        if 包id.startswith("模块库."):
            选中模块.add(包id)
        elif 包id.startswith("支持库."):
            选中支持库.add(包id)
        else:
            raise ValueError(f"依赖包类型非法: {包id}")
        访问栈.append(包id)
        声明 = 全部包[包id][1]
        直接依赖 = 声明.get("依赖", []) or []
        if not isinstance(直接依赖, list):
            raise ValueError(f"包 {包id} 的依赖必须是列表")
        for 项 in 直接依赖:
            依赖包, 能力id, 依赖版本 = _依赖项目标(项)
            目标包 = 依赖包
            if 能力id:
                owner = 能力归属.get(能力id, "")
                if not owner:
                    if 能力id in 索引["能力排除"] and 支持库表 is 索引["支持库"]:
                        raise ValueError(f"包 {包id} 的能力依赖被拒绝: {能力id}")
                    raise ValueError(f"包 {包id} 的能力依赖无法解析: {能力id}")
                if owner.startswith("冲突:"):
                    raise ValueError(f"包 {包id} 的能力依赖 owner 冲突: {能力id} -> {owner}")
                if 依赖包 and owner != 依赖包:
                    raise ValueError(f"包 {包id} 的能力依赖 owner 不一致: {能力id} -> {依赖包} / {owner}")
                目标包 = owner
            加入(目标包, f"包 {包id}")
            依赖锁.append({"来源包": 包id, "目标包": 目标包, "能力id": 能力id, "版本": 依赖版本 or ""})
        访问栈.pop()
        已完成.add(包id)

    for 包id in sorted(set(初始支持库) | set(初始模块)):
        加入(包id, "项目引用")
    依赖锁 = sorted(
        {json.dumps(项, ensure_ascii=False, sort_keys=True): 项 for 项 in 依赖锁}.values(),
        key=lambda 项: (项["来源包"], 项["目标包"], 项["能力id"], 项["版本"]),
    )
    return 选中支持库, 选中模块, 依赖锁


__all__ = ["构建索引", "正式包表", "能力所有者表", "排除包表", "校验显式包引用", "校验能力引用", "解析依赖闭包"]
