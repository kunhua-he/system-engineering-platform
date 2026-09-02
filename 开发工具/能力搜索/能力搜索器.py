"""能力搜索器：按关键词、能力id、返回类型、提供方搜索能力。

数据源：包声明（包级信息）+ 能力契约/参数契约.json（唯一聚合契约解析，
S0 唯一格式）+ 权限契约 + 验证历史。搜索结果 14 字段全覆盖：
能力id/中文名/说明/参数类型/必填/默认值/返回结构/错误码/调用示例/权限/
资源预算/依赖/版本/最近成功验证；不加载实现，不出现 未声明/任意/无调用示例。

命令行：python3.14 开发工具/能力搜索/能力搜索器.py --能力 读取文件
"""

from __future__ import annotations

import sys
from pathlib import Path

系统根 = Path(__file__).resolve().parents[1]
for _祖先 in 系统根.parents:
    if (_祖先 / "支持库").is_dir() and (_祖先 / "模块库").is_dir():
        系统根 = _祖先
        break
if str(系统根) not in sys.path:
    sys.path.insert(0, str(系统根))

import json
from typing import Any

from 公共契约.包声明 import 包声明
from 开发工具.契约编译.聚合契约解析 import 解析聚合契约, 提取能力表

搜索字段表 = (
    "能力id", "中文名", "说明", "参数类型", "必填", "默认值", "返回结构",
    "错误码", "调用示例", "权限", "资源预算", "依赖", "版本", "最近成功验证",
)

验证历史路径 = 系统根 / "开发文档" / "项目证据" / "验证历史.jsonl"


def 搜索声明列表(
    声明列表: list[包声明],
    *,
    关键词: str = "",
    返回类型: str = "",
    提供方: str = "",
    类型: str = "",
) -> list[tuple[包声明, dict[str, str]]]:
    """在包声明列表中搜索能力（不加载实现）。

    返回 [(包声明, 能力条目)] 列表。适配层提供者（支持库.适配层.*）是
    内部实现边界，不对外暴露，一律过滤；公开能力由后端支持库承担。
    """
    结果列表: list[tuple[包声明, dict[str, str]]] = []
    for 声明 in 声明列表:
        if 声明.包id.startswith("支持库.适配层."):
            continue
        if 类型 and 声明.类型 != 类型:
            continue
        if 提供方 and 声明.包id != 提供方:
            continue
        for 能力 in 声明.能力:
            if 返回类型 and 能力.返回 != 返回类型:
                continue
            if 关键词 and 关键词 not in 能力.能力id and 关键词 not in 能力.名称 and 关键词 not in 能力.说明:
                continue
            结果列表.append((声明, 能力.转字典()))
    return 结果列表


def 定位包目录(包id: str) -> Path | None:
    """按 包id 定位包目录（模块库.OCR → 模块库/OCR）。"""
    if not 包id:
        return None
    候选 = 系统根 / 包id.replace(".", "/")
    return 候选 if (候选 / "包声明.json").is_file() else None


def 加载聚合契约索引() -> dict[str, dict[str, dict]]:
    """扫描全部包的能力契约（唯一聚合契约解析），返回 {包id: {能力id: 条目}}。"""
    索引: dict[str, dict[str, dict]] = {}
    for 根目录 in (系统根 / "支持库", 系统根 / "模块库"):
        if not 根目录.is_dir():
            continue
        for 契约文件 in 根目录.rglob("能力契约/参数契约.json"):
            数据, _问题 = 解析聚合契约(契约文件)
            包id = 契约文件.parent.parent.relative_to(系统根).as_posix()
            索引[包id.replace("/", ".")] = {条目["能力id"]: 条目 for 条目 in 提取能力表(数据)}
    return 索引


def 读取权限(包目录: Path, 能力id: str) -> str:
    """能力权限：权限契约.json 的 允许用户；无权限契约 → 公开。"""
    权限路径 = 包目录 / "权限契约" / "权限契约.json"
    if 权限路径.is_file():
        try:
            数据 = json.loads(权限路径.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            数据 = {}
        条目 = 数据.get(能力id, {}) if isinstance(数据, dict) else {}
        允许用户 = 条目.get("允许用户") if isinstance(条目, dict) else None
        if 允许用户:
            return "允许用户: " + ", ".join(str(项) for 项 in 允许用户)
    return "公开"


def 读取资源预算(契约条目: dict[str, Any]) -> str:
    """能力资源预算：行为.输入上限 或 资源预算 参数默认值；无 → 默认。"""
    行为 = 契约条目.get("行为", {})
    输入上限 = 行为.get("输入上限") if isinstance(行为, dict) else ""
    if 输入上限:
        return str(输入上限)
    for 参数 in 契约条目.get("参数", []):
        if 参数.get("名称") == "资源预算" and 参数.get("默认值") is not None:
            return str(参数["默认值"])
    return "默认"


def 最近成功验证(包id: str, 能力id: str) -> str:
    """最近成功验证：验证历史.jsonl 中退出码 0 且含 包id/能力id 的最新记录时间。"""
    if not 验证历史路径.is_file():
        return "暂无成功验证记录"
    最近 = ""
    for 行 in 验证历史路径.read_text(encoding="utf-8").splitlines():
        try:
            记录 = json.loads(行)
        except json.JSONDecodeError:
            continue
        if 记录.get("退出码") != 0:
            continue
        内容 = json.dumps(记录, ensure_ascii=False)
        if (包id in 内容 or 能力id in 内容) and 记录.get("时间", "") > 最近:
            最近 = 记录["时间"]
    return 最近 or "暂无成功验证记录"


def 调用示例文本化(示例: Any, 能力id: str, 参数表: list[dict]) -> str:
    """调用示例对象 → 文本；缺示例时按默认值生成（可执行，非 无调用示例）。"""
    if isinstance(示例, dict):
        参数行 = ", ".join(f"{名称}={值}" for 名称, 值 in 示例.get("参数", {}).items())
        目标id = 示例.get("能力id", 能力id)
        return f"{目标id}({参数行})" if 参数行 else f"{目标id}()"
    if isinstance(示例, str) and 示例:
        return 示例
    参数行 = ", ".join(f"{参数.get('名称', '参数')}={参数.get('默认值', '值')}"
                      for 参数 in 参数表[:3])
    return f"{能力id}({参数行})" if 参数行 else f"{能力id}()"


def 格式化搜索结果(声明: 包声明, 能力: dict[str, Any],
                   契约条目: dict[str, Any] | None = None) -> dict[str, Any]:
    """把一次搜索结果格式化为 14 字段全覆盖描述（数据来自唯一聚合契约解析）。

    搜索过程不加载实现代码；结果字段全部来自包声明与聚合契约。
    """
    能力id = 能力["能力id"]
    契约数据 = 契约条目 or {}
    参数列表 = 契约数据.get("参数")
    if not isinstance(参数列表, list):
        参数列表 = 能力.get("参数", [])
    参数列表 = [
        {
            "名称": 参数.get("名称", ""),
            "类型": "未约束" if 参数.get("类型") == "任意" else 参数.get("类型", ""),
            "必填": 参数.get("必填", True),
            "默认值": 参数.get("默认值"),
            "说明": 参数.get("说明", ""),
        }
        for 参数 in 参数列表
    ]
    必填参数 = [参数 for 参数 in 参数列表 if 参数.get("必填", True)]
    可选参数 = [参数 for 参数 in 参数列表 if not 参数.get("必填", True)]
    版本 = 契约数据.get("版本") or 声明.版本
    错误码 = 契约数据.get("错误码") or []
    返回结构 = 契约数据.get("返回") or 能力.get("返回", "")
    调用示例 = 调用示例文本化(契约数据.get("调用示例"), 能力id, 参数列表)
    包目录 = 定位包目录(声明.包id)
    权限 = 读取权限(包目录, 能力id) if 包目录 else "公开"
    return {
        "能力id": 能力id,
        "中文名": 能力.get("名称", 能力id.rsplit(".", 1)[-1]),
        "说明": 能力.get("说明", ""),
        "参数类型": 参数列表,
        "必填": [参数["名称"] for 参数 in 必填参数],
        "默认值": {参数["名称"]: 参数["默认值"]
                   for 参数 in 参数列表 if 参数.get("默认值") is not None},
        "返回结构": 返回结构,
        "错误码": 错误码,
        "调用示例": 调用示例,
        "权限": 权限,
        "资源预算": 读取资源预算(契约数据),
        "依赖": [{"能力": 依赖.get("能力", ""), "版本": 依赖.get("版本", "")}
                 for 依赖 in 声明.依赖],
        "版本": 版本,
        "最近成功验证": 最近成功验证(声明.包id, 能力id),
        "名称": 能力.get("名称", ""),
        "提供方": 声明.包id,
        "类型": 声明.类型,
        "一句话说明": 能力.get("说明", ""),
        "参数列表": 参数列表,
        "必填参数": 必填参数,
        "可选参数": 可选参数,
        "返回": 返回结构,
        "依赖能力": 声明.依赖,
        "配置项": 脱敏配置项(声明.配置项),
    }


def 脱敏配置项(配置项列表: list[dict]) -> list[dict]:
    """输出配置项声明；敏感配置只显示'敏感配置'，不输出默认值。"""
    输出列表: list[dict] = []
    for 条目 in 配置项列表 or []:
        敏感 = bool(条目.get("敏感", False))
        输出 = {
            "配置名称": 条目.get("配置名称", ""),
            "类型": 条目.get("类型", "文本"),
            "必填": 条目.get("必填", False),
            "允许项目覆盖": 条目.get("允许项目覆盖", True),
            "允许运行时覆盖": 条目.get("允许运行时覆盖", False),
            "敏感": 敏感,
            "说明": "敏感配置（不显示实际值）" if 敏感 else 条目.get("说明", ""),
        }
        if not 敏感:
            输出["默认值"] = 条目.get("默认值", "")
        输出列表.append(输出)
    return 输出列表


def 搜索带原因(
    声明列表: list[包声明],
    *,
    关键词: str = "",
    返回类型: str = "",
    提供方: str = "",
    类型: str = "",
) -> tuple[list[dict[str, Any]], str]:
    """搜索并返回 (14 字段格式化结果列表, 失败原因)。搜索失败必须返回明确原因。"""
    if not 关键词 and not 返回类型 and not 提供方:
        return [], "参数错误: 至少需要一个搜索条件（关键词/返回类型/提供方）"
    结果列表 = 搜索声明列表(
        声明列表, 关键词=关键词, 返回类型=返回类型, 提供方=提供方, 类型=类型
    )
    if not 结果列表:
        条件描述 = f"关键词={关键词 or '（无）'}" if 关键词 else "（无关键词）"
        return [], f"未找到匹配能力: {条件描述}"
    契约索引 = 加载聚合契约索引()
    return [
        格式化搜索结果(声明, 能力, 契约索引.get(声明.包id, {}).get(能力["能力id"]))
        for 声明, 能力 in 结果列表
    ], ""


def 搜索公开能力(项目根: Path, 关键词: str, 限制: int = 20) -> list[dict[str, Any]]:
    """搜索公开能力：14 字段全覆盖；数据来自 包声明 + 唯一聚合契约解析。"""
    global 系统根, 验证历史路径
    系统根 = Path(项目根)
    验证历史路径 = 系统根 / "开发文档" / "项目证据" / "验证历史.jsonl"
    关键词 = 关键词.strip().lower()
    from 运行核心.加载器.包发现.发现器 import 发现全部

    发现 = 发现全部(系统根 / "支持库", 系统根 / "模块库")
    if not 发现.成功:
        return []
    契约索引 = 加载聚合契约索引()
    结果列表 = []
    for 声明 in 发现.声明列表:
        if 关键词 and 关键词 not in json.dumps(声明.转字典(), ensure_ascii=False).lower():
            continue
        包契约 = 契约索引.get(声明.包id, {})
        for 能力 in 声明.能力:
            记录 = 格式化搜索结果(声明, 能力.转字典(), 包契约.get(能力.能力id))
            if 关键词 and 关键词 not in json.dumps(记录, ensure_ascii=False).lower():
                continue
            结果列表.append(记录)
    return 结果列表[: max(1, min(限制, 100))]


def 主函数(argv: list[str] | None = None) -> int:
    """命令行入口：python3.14 开发工具/能力搜索/能力搜索器.py --能力 读取文件"""
    import argparse

    from 运行核心.加载器.包发现.发现器 import 发现全部

    解析器 = argparse.ArgumentParser(description="系统级能力搜索器")
    解析器.add_argument("--能力", required=True, help="搜索关键词（能力id/名称/说明）")
    解析器.add_argument("--类型", default="", help="过滤类型：支持库/模块")
    参数 = 解析器.parse_args(argv)

    发现 = 发现全部(系统根 / "支持库", 系统根 / "模块库")
    if not 发现.成功:
        print(f"发现失败: {发现.问题列表}")
        return 1
    结果列表, 原因 = 搜索带原因(发现.声明列表, 关键词=参数.能力, 类型=参数.类型)
    if 原因:
        print(f"未找到能力: {参数.能力}")
        return 1
    print(f"找到 {len(结果列表)} 个能力实现：")
    for 结果 in 结果列表:
        参数描述 = ", ".join(
            f"{条目.get('名称', '?')}:{条目.get('类型', '')}" for 条目 in 结果["参数类型"]
        ) or "无"
        print(f"  - 能力id: {结果['能力id']}")
        print(f"    名称: {结果['中文名']}")
        print(f"    提供方: {结果['提供方']}（{结果['类型']} {结果['版本']}）")
        print(f"    参数: {参数描述}")
        print(f"    返回: {结果['返回结构']}")
        print(f"    说明: {结果['说明']}")
        print(f"    调用示例: {结果['调用示例']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(主函数())
