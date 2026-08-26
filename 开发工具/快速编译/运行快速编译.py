"""契约测试编译器与原则检查入口。

该入口只做确定性检查和临时装配，不启动外部 Provider。报告写入工程缓存，
退出码是调用方唯一判定依据：0 通过，10 契约/原则错误，20 装配冲突，
30 确定性样例失败，40 资源残留，50 外部 Provider 未验证。
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

系统根 = Path(__file__).resolve().parents[2]
if str(系统根) not in sys.path:
    sys.path.insert(0, str(系统根))
报告根 = 系统根 / "工程缓存" / "快速编译"
from 公共契约.基础类型.类型表 import 正式类型表
from 开发工具.项目编译.正式包索引 import 构建索引, 校验显式包引用, 解析依赖闭包

旧类型 = {"文本": "文本型", "整数": "整数型", "布尔": "逻辑型", "浮点数": "双精度数型",
        "数字": "双精度数型", "字典": "字典型", "列表": "列表型", "字节": "字节型",
        "字节集": "字节集型", "空": "空值型", "结果": "结果型"}


def _读取_json(路径: Path) -> dict[str, Any]:
    try:
        数据 = json.loads(路径.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as 错误:
        raise ValueError(f"JSON 不可读取: {路径}: {错误}") from 错误
    if not isinstance(数据, dict):
        raise ValueError(f"JSON 必须是对象: {路径}")
    return 数据


def _包根(目标: Path) -> Path:
    目标 = 目标.resolve()
    if 目标.is_file():
        目标 = 目标.parent
    for 当前 in (目标, *目标.parents):
        if (当前 / "包声明.json").is_file():
            return 当前
    raise ValueError(f"找不到包声明.json: {目标}")


def _能力表(包: Path, 声明: dict[str, Any]) -> list[dict[str, Any]]:
    能力 = 声明.get("能力", [])
    if not isinstance(能力, list):
        raise ValueError("包声明的能力必须是列表")
    结果: list[dict[str, Any]] = []
    for 索引, 条目 in enumerate(能力, 1):
        if not isinstance(条目, dict) or not str(条目.get("能力id", "")).strip():
            raise ValueError(f"第 {索引} 个能力缺少能力id")
        能力id = str(条目["能力id"])
        参数 = 条目.get("参数", [])
        if not isinstance(参数, list):
            raise ValueError(f"{能力id} 参数必须是列表")
        名称表: set[str] = set()
        for 参数项 in 参数:
            if not isinstance(参数项, dict) or not 参数项.get("名称"):
                raise ValueError(f"{能力id} 存在无名称参数")
            名称 = str(参数项["名称"])
            if 名称 in 名称表:
                raise ValueError(f"{能力id} 参数重复: {名称}")
            名称表.add(名称)
            类型 = 参数项.get("类型")
            if 类型 in 旧类型:
                raise ValueError(f"{能力id} 使用旧类型 {类型}，应改为 {旧类型[类型]}")
            if isinstance(类型, str) and 类型 and 类型 not in 正式类型表:
                if not (类型.startswith("结果型<") and 类型.endswith(">")):
                    raise ValueError(f"{能力id} 使用未注册类型 {类型}")
        结果.append(条目)
    return 结果


def _检查模块越界导入(包: Path) -> list[str]:
    问题: list[str] = []
    if not str(包).startswith(str(系统根 / "模块库")):
        return 问题
    for 文件 in 包.rglob("*.py"):
        if "__pycache__" in 文件.parts:
            continue
        try:
            树 = ast.parse(文件.read_text(encoding="utf-8"), filename=str(文件))
        except (OSError, SyntaxError, UnicodeDecodeError) as 错误:
            问题.append(f"{文件}: Python 解析失败: {错误}")
            continue
        for 节点 in ast.walk(树):
            if isinstance(节点, ast.ImportFrom) and 节点.module:
                模块名 = 节点.module
                if 模块名.startswith(("支持库.", "支持库.适配层", "第三方")):
                    问题.append(f"{文件}:{节点.lineno}: 模块禁止直接导入 {模块名}")
            elif isinstance(节点, ast.Import):
                for 名称 in 节点.names:
                    if 名称.name.startswith(("支持库.", "第三方")):
                        问题.append(f"{文件}:{节点.lineno}: 模块禁止直接导入 {名称.name}")
    return 问题


def _全局能力所有者() -> dict[str, str]:
    return dict(构建索引(系统根)["能力所有者"])


def 检查包(目标: Path, *, 执行样例: bool = False, 执行外部: bool = False) -> tuple[int, dict[str, Any]]:
    包 = _包根(目标)
    try:
        声明前 = _读取_json(包 / "包声明.json")
        校验显式包引用(系统根, str(声明前.get("包id", "")))
    except ValueError as 错误:
        报告 = {"包目录": str(包), "问题": [str(错误)], "退出码": 20}
        return 20, 报告
    声明 = _读取_json(包 / "包声明.json")
    问题: list[str] = []
    for 必需 in ("包id", "版本", "类型", "入口"):
        if not 声明.get(必需):
            问题.append(f"包声明缺少字段: {必需}")
    if not (包 / str(声明.get("入口", "__init__.py"))).is_file():
        问题.append("包入口不存在")
    if not (包 / "能力契约" / "参数契约.json").is_file() and 声明.get("能力"):
        问题.append("声明了能力但缺少能力契约/参数契约.json")
    try:
        能力 = _能力表(包, 声明)
    except ValueError as 错误:
        问题.append(str(错误)); 能力 = []
    所有者 = _全局能力所有者()
    for 条目 in 能力:
        能力id = str(条目["能力id"])
        当前包id = str(声明.get("包id"))
        if 当前包id.startswith("支持库.适配层."):
            continue
        owner = 所有者.get(能力id)
        if owner and (owner != 当前包id or owner.startswith("冲突:")):
            问题.append(f"能力重复 owner: {能力id} -> {owner}")
    try:
        解析依赖闭包(
            系统根,
            {str(声明.get("包id"))} if str(声明.get("包id", "")).startswith("支持库.") else set(),
            {str(声明.get("包id"))} if str(声明.get("包id", "")).startswith("模块库.") else set(),
        )
    except ValueError as 错误:
        问题.append(f"依赖闭包无效: {错误}")
    问题.extend(_检查模块越界导入(包))
    if 问题:
        退出码 = 20 if any("owner" in 项 or "装配" in 项 for 项 in 问题) else 10
    else:
        退出码 = 0
    if 执行样例 and 退出码 == 0 and str(声明.get("包id")) == "支持库.后端.数据操作支持库.类型转换":
        try:
            from 支持库.后端.数据操作支持库.类型转换 import 文本转整数
            结果 = 文本转整数("123")
            if not 结果.成功 or 结果.值 != 123:
                问题.append("确定性样例失败: 文本转整数('123')")
                退出码 = 30
        except Exception as 错误:  # noqa: BLE001
            问题.append(f"确定性样例异常: {错误}"); 退出码 = 30
    if 执行外部 and not 执行样例:
        退出码 = 50
        问题.append("外部 Provider 未执行确定性样例")
    报告 = {"包目录": str(包), "包id": 声明.get("包id"), "版本": 声明.get("版本"),
            "能力": [str(x["能力id"]) for x in 能力], "问题": 问题,
            "退出码": 退出码, "包摘要": hashlib.sha256((包 / "包声明.json").read_bytes()).hexdigest()}
    return 退出码, 报告


def 主函数() -> int:
    解析器 = argparse.ArgumentParser(description="契约测试编译器与原则检查")
    # 工作区范围不需要单独目标；包范围仍必须明确给出包目录或文件。
    目标组 = 解析器.add_mutually_exclusive_group(required=False)
    目标组.add_argument("--包目录", type=Path)
    目标组.add_argument("--文件", type=Path)
    解析器.add_argument("--范围", choices=("包", "工作区"), default="包")
    解析器.add_argument("--执行样例", action="store_true")
    解析器.add_argument("--执行外部", action="store_true")
    参数 = 解析器.parse_args()
    目标 = 参数.包目录 or 参数.文件
    if 参数.范围 == "包" and 目标 is None:
        解析器.error("包范围必须提供 --包目录 或 --文件")
    try:
        if 参数.范围 == "工作区":
            索引 = 构建索引(系统根)
            目标表 = [项[0] / "包声明.json" for 项 in [*索引["支持库"].values(), *索引["模块库"].values()]]
            结果表 = [检查包(项.parent, 执行样例=参数.执行样例, 执行外部=参数.执行外部)[1] for 项 in 目标表]
            退出码 = max((int(项["退出码"]) for 项 in 结果表), default=10)
            报告 = {"范围": "工作区", "结果": 结果表, "退出码": 退出码}
        else:
            退出码, 报告 = 检查包(目标, 执行样例=参数.执行样例, 执行外部=参数.执行外部)
    except (OSError, ValueError) as 错误:
        退出码, 报告 = 10, {"问题": [str(错误)], "退出码": 10}
    报告根.mkdir(parents=True, exist_ok=True)
    (报告根 / "最近一次.json").write_text(json.dumps(报告, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(报告, ensure_ascii=False, indent=2))
    return 退出码


if __name__ == "__main__":
    raise SystemExit(主函数())
