"""能力搜索器：按关键词、能力id、返回类型、提供方搜索能力。

搜索只读取已安装能力注册表与包声明，不加载实现，保证搜索轻量且安全。

命令行：python3.14 能力搜索器/能力搜索器.py --能力 读取文件
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

from typing import Any

from 公共契约.包声明 import 包声明
from 公共契约.能力契约 import 能力实现, 能力注册表


def 搜索注册表(
    注册表: 能力注册表,
    *,
    关键词: str = "",
    返回类型: str = "",
    提供方: str = "",
) -> list[能力实现]:
    """在已安装注册表中搜索能力实现。"""
    结果列表 = 注册表.搜索(关键词=关键词, 返回类型=返回类型)
    if 提供方:
        结果列表 = [实现 for 实现 in 结果列表 if 实现.包id == 提供方]
    return 结果列表


def 搜索声明列表(
    声明列表: list[包声明],
    *,
    关键词: str = "",
    返回类型: str = "",
    提供方: str = "",
    类型: str = "",
) -> list[tuple[包声明, dict[str, str]]]:
    """在包声明列表中搜索能力（不加载实现）。

    返回 [(包声明, 能力条目)] 列表。
    """
    结果列表: list[tuple[包声明, dict[str, str]]] = []
    for 声明 in 声明列表:
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


def 汇总能力清单(声明列表: list[包声明]) -> list[dict[str, Any]]:
    """汇总全部声明的能力清单（能力id、提供方、类型、版本、返回）。"""
    清单: list[dict[str, Any]] = []
    for 声明 in 声明列表:
        for 能力 in 声明.能力:
            清单.append(
                {
                    "能力id": 能力.能力id,
                    "名称": 能力.名称,
                    "提供方": 声明.包id,
                    "类型": 声明.类型,
                    "版本": 声明.版本,
                    "返回": 能力.返回,
                    "说明": 能力.说明,
                }
            )
    return sorted(清单, key=lambda 条目: (条目["能力id"], 条目["提供方"]))


def 格式化搜索结果(声明: 包声明, 能力: dict[str, Any]) -> dict[str, Any]:
    """把一次搜索结果格式化为完整能力描述（含调用示例与错误码说明）。

    搜索过程不加载实现代码；结果字段全部来自包声明。
    """
    参数列表 = 能力.get("参数", [])
    必填参数 = [条目 for 条目 in 参数列表 if 条目.get("必填", True)]
    可选参数 = [条目 for 条目 in 参数列表 if not 条目.get("必填", True)]
    参数示例 = ", ".join(f"{条目.get('名称', '参数')}=值" for 条目 in 参数列表[:3])
    调用示例 = f"{声明.包id} 提供能力 {能力['能力id']}"
    if 参数示例:
        调用示例 += f"（{参数示例}…）"
    return {
        "能力id": 能力["能力id"],
        "名称": 能力.get("名称", ""),
        "提供方": 声明.包id,
        "类型": 声明.类型,
        "版本": 声明.版本,
        "一句话说明": 能力.get("说明", ""),
        "参数列表": 参数列表,
        "必填参数": 必填参数,
        "可选参数": 可选参数,
        "返回": 能力.get("返回", ""),
        "错误码": ["参数不合法", "外部不可访问", "内部错误"],
        "调用示例": 调用示例,
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
    """搜索并返回 (格式化结果列表, 失败原因)。搜索失败必须返回明确原因。"""
    if not 关键词 and not 返回类型 and not 提供方:
        return [], "参数错误: 至少需要一个搜索条件（关键词/返回类型/提供方）"
    结果列表 = 搜索声明列表(
        声明列表, 关键词=关键词, 返回类型=返回类型, 提供方=提供方, 类型=类型
    )
    if not 结果列表:
        条件描述 = f"关键词={关键词 or '（无）'}" if 关键词 else "（无关键词）"
        return [], f"未找到匹配能力: {条件描述}"
    return [格式化搜索结果(声明, 能力) for 声明, 能力 in 结果列表], ""


def 主函数(argv: list[str] | None = None) -> int:
    """命令行入口：python3.14 能力搜索器/能力搜索器.py --能力 读取文件"""
    import argparse
    import sys as _系统
    from pathlib import Path as _路径

    系统根 = _路径(__file__).resolve().parents[1]
    for _祖先 in 系统根.parents:
        if (_祖先 / "支持库").is_dir() and (_祖先 / "模块库").is_dir():
            系统根 = _祖先
            break
    if str(系统根) not in _系统.path:
        _系统.path.insert(0, str(系统根))
    from 运行核心.加载器.包发现.发现器 import 发现全部

    解析器 = argparse.ArgumentParser(description="系统级能力搜索器")
    解析器.add_argument("--能力", required=True, help="搜索关键词（能力id/名称/说明）")
    解析器.add_argument("--类型", default="", help="过滤类型：支持库/模块")
    参数 = 解析器.parse_args(argv)

    发现 = 发现全部(系统根 / "支持库", 系统根 / "模块库")
    if not 发现.成功:
        print(f"发现失败: {发现.问题列表}")
        return 1
    结果列表 = 搜索声明列表(发现.声明列表, 关键词=参数.能力, 类型=参数.类型)
    if not 结果列表:
        print(f"未找到能力: {参数.能力}")
        return 1
    print(f"找到 {len(结果列表)} 个能力实现：")
    for 声明, 能力 in 结果列表:
        参数描述 = ", ".join(f"{条目.get('名称', '?')}:{条目.get('类型', '任意')}" for 条目 in 能力.get("参数", [])) or "无"
        print(f"  - 能力id: {能力['能力id']}")
        print(f"    名称: {能力.get('名称', '')}")
        print(f"    提供方: {声明.包id}（{声明.类型} {声明.版本}）")
        print(f"    参数: {参数描述}")
        print(f"    返回: {能力.get('返回', '')}")
        print(f"    说明: {能力.get('说明', '')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(主函数())
