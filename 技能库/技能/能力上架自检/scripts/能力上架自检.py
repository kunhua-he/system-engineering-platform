# -*- coding: utf-8 -*-
"""能力上架自检：技能桥接脚本（stdin JSON 进，stdout JSON 出）。

契约：技能.能力上架自检

桥接协议：stdin 形如 {"参数": {...}}；stdout 只输出一个 JSON 对象——
成功 {"成功": true, "值": {...}}，失败 {"成功": false, "错误码": ..., "错误说明": ...}。
本脚本只用 依赖.json 声明的 标准库 json/sys/pathlib：不起进程、不调能力、不写文件。
"""

import json
import sys
from pathlib import Path

#: 五处契约的固定顺序（逐能力/缺口都按它判，结果稳定可比对）
处顺序 = ("能力定义", "参数契约", "包声明", "权限契约", "验证场景")

#: 处名 → 相对包目录的契约文件（平台真实文件名；夹具用 文件名映射 覆盖，见 主流程）
默认处文件 = {
    "能力定义": "能力定义.json",
    "参数契约": "能力契约/参数契约.json",
    "包声明": "包声明.json",
    "权限契约": "权限契约/权限契约.json",
    "验证场景": "验证场景引用.json",
}

#: 权限契约里不是能力id 的顶层键（平台既有写法）
权限契约保留键 = ("只读", "写路径")


class 值错误(Exception):
    """带错误码的入参/执行错误：由 主函数 转成固定的失败形状。"""

    def __init__(self, 错误码: str, 错误说明: str) -> None:
        super().__init__(错误说明)
        self.错误码 = 错误码
        self.错误说明 = 错误说明


def 读JSON(路径: Path):
    """只读解析 JSON；缺失或非法回 None（按「该处未登记」如实处置，不猜）。"""
    if not 路径.is_file():
        return None
    try:
        return json.loads(路径.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None


def 取条目表(文档, *候选键: str) -> list:
    """取契约文档里的能力条目列表；文档本身是列表时原样返回。"""
    if isinstance(文档, list):
        return 文档
    if not isinstance(文档, dict):
        return []
    for 键名 in 候选键:
        值 = 文档.get(键名)
        if isinstance(值, list):
            return 值
    return []


def 取场景对象列表(文档, 根目录: Path = None) -> list:
    """把「内嵌式」与「引用式」两种验证场景写法归一成场景对象列表。

    内嵌式：条目里直接有 目标步骤（夹具用）。
    引用式：条目只有 场景文件（平台既有写法，见 验证场景引用.json）——
    跟随引用读同目录的场景文件，再取它的 验证场景 列表。
    只读不写；读不到就跳过（按「该处未登记」如实处置，不猜）。
    """
    场景列表 = []
    for 条目 in 取条目表(文档, "验证场景引用", "验证场景"):
        if not isinstance(条目, dict):
            continue
        场景 = 条目.get("场景")
        if isinstance(场景, dict):
            场景列表.append(场景)
            continue
        场景文件 = 条目.get("场景文件")
        if isinstance(场景文件, str) and 场景文件.strip() and 根目录 is not None:
            场景列表.extend(取条目表(读JSON(根目录 / 场景文件), "验证场景"))
            continue
        场景列表.append(条目)
    return 场景列表


def 取验证场景能力(文档, 根目录: Path = None) -> set:
    """验证场景只认「目标步骤 + 预期.成功=真」的覆盖：失败用例不算覆盖（与包体检同口径）。"""
    命中 = set()
    for 场景 in 取场景对象列表(文档, 根目录):
        if not isinstance(场景, dict):
            continue
        for 步骤 in 场景.get("目标步骤") or []:
            if not isinstance(步骤, dict):
                continue
            能力id = 步骤.get("能力id")
            预期 = 步骤.get("预期")
            if isinstance(能力id, str) and 能力id and isinstance(预期, dict) and 预期.get("成功") is True:
                命中.add(能力id)
    return 命中


def 取已登记(处名: str, 文档, 根目录: Path = None) -> set:
    """该处已登记的能力id集合。根目录 只给 验证场景 的引用式写法用。"""
    if 处名 == "权限契约":
        if not isinstance(文档, dict):
            return set()
        return {键 for 键 in 文档 if 键 not in 权限契约保留键}
    if 处名 == "验证场景":
        return 取验证场景能力(文档, 根目录)
    return {条目.get("能力id") for 条目 in 取条目表(文档, "能力列表", "能力契约", "能力")
            if isinstance(条目, dict) and isinstance(条目.get("能力id"), str) and 条目.get("能力id")}


def 修法文案(处名: str, 能力id: str) -> str:
    """缺该处时的具体修法（不让调用方猜）。"""
    if 处名 == "能力定义":
        return f'在 能力定义.json 的能力列表里补 "{能力id}" 条目'
    if 处名 == "参数契约":
        return f'在 能力契约/参数契约.json 里补 "{能力id}" 条目'
    if 处名 == "包声明":
        return f'在 包声明.json 的能力列表里补 "{能力id}" 条目'
    if 处名 == "权限契约":
        return f'在 权限契约/权限契约.json 里补 "{能力id}": {{"允许用户": ["*"]}}'
    return f'在 验证场景.json（由 验证场景引用.json 引用）里补一个 预期 成功=true 的目标步骤：能力id={能力id}'


def 取处路径(根: Path, 处名: str, 文件名映射: dict) -> Path:
    """该处契约文件路径：默认用平台真实文件名，夹具可经 文件名映射 覆盖相对路径。"""
    相对 = 文件名映射.get(处名) or 默认处文件[处名]
    return 根 / str(相对)


def 主流程(参数: dict) -> dict:
    """五处契约覆盖自检：逐能力判齐备，缺哪处给修法。"""
    包目录 = 参数.get("包目录")
    能力id列表 = 参数.get("能力id列表")
    文件名映射 = 参数.get("文件名映射") or {}
    if not isinstance(文件名映射, dict):
        raise 值错误("参数不合法", "文件名映射 必须是对象：{处名: 相对路径}")
    if not isinstance(包目录, str) or not 包目录.strip():
        raise 值错误("参数不合法", "包目录 必填：目标包根目录（绝对路径优先）")
    if not isinstance(能力id列表, list) or not 能力id列表:
        raise 值错误("参数不合法", "能力id列表 必填：本次上架/改动的公开能力id清单")
    for 条目 in 能力id列表:
        if not isinstance(条目, str) or not 条目.strip():
            raise 值错误("参数不合法", "能力id列表 里每一项都必须是非空文本")
    根 = Path(包目录).expanduser()
    已登记表 = {处名: 取已登记(处名, 读JSON(取处路径(根, 处名, 文件名映射)), 根) for 处名 in 处顺序}
    逐能力 = []
    缺口 = []
    for 能力id in 能力id列表:
        覆盖 = {处名: (能力id in 已登记表[处名]) for 处名 in 处顺序}
        逐能力.append({"能力id": 能力id, **覆盖})
        for 处名 in 处顺序:
            if not 覆盖[处名]:
                缺口.append({"能力id": 能力id, "处": 处名, "修法": 修法文案(处名, 能力id)})
    齐备 = not 缺口
    return {
        "包目录": 包目录,
        "能力数": len(能力id列表),
        "处数": len(处顺序),
        "齐备": 齐备,
        "逐能力": 逐能力,
        "缺口": 缺口,
        "缺口数": len(缺口),
        "下一步": (["五处齐备：可跑 开发工具/包体检.py 与 开发工具.契约编译.能力定义编译器",
                    "改完契约必须重跑 开发工具.全量重算摘要 与 开发工具.开发编译口.编译口 --变更"]
                   if 齐备 else [f"先补齐 缺口 列出的 {len(缺口)} 处，再重跑本技能"]),
    }


def 输出失败(错误码: str, 错误说明: str) -> int:
    print(json.dumps({"成功": False, "错误码": 错误码, "错误说明": 错误说明}, ensure_ascii=False))
    return 0


def 主函数() -> int:
    """读 stdin、跑主流程、把结果写成单行 JSON。"""
    原文 = sys.stdin.read()
    try:
        载荷 = json.loads(原文) if 原文.strip() else {}
    except json.JSONDecodeError as 错误:
        return 输出失败("参数不合法", f"stdin 不是合法 JSON: {错误}")
    参数 = 载荷.get("参数") or {}
    if not isinstance(参数, dict):
        return 输出失败("参数不合法", "参数必须是 JSON 对象")
    try:
        值 = 主流程(参数)
    except 值错误 as 错误:
        return 输出失败(错误.错误码, 错误.错误说明)
    except Exception as 错误:  # 失败要明确，不吞
        return 输出失败("脚本执行失败", f"{type(错误).__name__}: {错误}")
    print(json.dumps({"成功": True, "值": 值}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(主函数())
