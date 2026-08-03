"""公开调用完整性门禁：六环一致性（声明→注册→说明书→搜索→公开调用→验证场景）。

扫描 支持库/适配层、支持库/后端 与 模块库/ 下全部包（有 包声明.json 的目录），
逐能力校验六环；另做跨包全局检查：同义能力（同名不同包）与重复提供者
（同能力id多包）。注册表为唯一事实源（包声明.json/能力定义.json 能力列表），
公开调用必须经由注册能力 导出，不得绕过。
任一违规 → 退出码 1 并打印 缺口类型/能力id/包/路径 清单；全部通过 → 退出码 0。
用法：python3.14 开发工具/公开调用完整性门禁.py [扫描根目录（默认仓库根）]
"""
from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

仓库根 = Path(__file__).resolve().parents[1]
扫描段 = ("支持库/适配层", "支持库/后端", "模块库")


def 读取json(路径: Path):
    try:
        return json.loads(路径.read_text(encoding="utf-8"))
    except Exception:
        return None


def 找包目录(根: Path) -> list[Path]:
    """扫描段下含 包声明.json 的目录（无声明的目录不是包，跳过）。"""
    目录 = [d for 段 in 扫描段 if (根 / 段).is_dir() for d in (根 / 段).iterdir()]
    return sorted(d for d in 目录 if (d / "包声明.json").is_file())


def 提取注册映射(源码: str) -> dict[str, str]:
    """AST 提取 注册能力 内的 (能力id → 实现函数名) 映射。"""
    映射: dict[str, str] = {}
    try:
        树 = ast.parse(源码)
    except SyntaxError:
        return 映射
    for 节点 in ast.walk(树):
        if not isinstance(节点, ast.FunctionDef) or 节点.name != "注册能力":
            continue
        for 子 in ast.walk(节点):
            if isinstance(子, ast.Call) and isinstance(子.func, ast.Attribute) and 子.func.attr == "注册" and 子.args and isinstance(子.args[0], ast.Call):
                kw = {k.arg: k.value for k in 子.args[0].keywords if k.arg}
                if isinstance(kw.get("能力id"), ast.Constant) and isinstance(kw.get("实现函数"), ast.Name):
                    映射[kw["能力id"].value] = kw["实现函数"].id
            elif isinstance(子, ast.Tuple) and len(子.elts) >= 2 and isinstance(子.elts[0], ast.Constant) and isinstance(子.elts[1], ast.Name):
                映射.setdefault(子.elts[0].value, 子.elts[1].id)
    return 映射


def 提取导出名(源码: str) -> set[str]:
    """包入口导出名：__all__ 存在取其元素，否则取顶层 import 名。"""
    try:
        树 = ast.parse(源码)
    except SyntaxError:
        return set()
    导出: set[str] = set()
    全名: set[str] | None = None
    for 节点 in 树.body:
        if isinstance(节点, ast.ImportFrom):
            导出.update(名.name for 名 in 节点.names if 名.name != "*")
        elif isinstance(节点, ast.Assign) and isinstance(节点.targets[0], ast.Name) and 节点.targets[0].id == "__all__":
            全名 = {e.value for e in 节点.value.elts if isinstance(e, ast.Constant)}
    return 全名 if 全名 is not None else 导出


def 检查包(包目录: Path) -> list[dict]:
    """逐能力六环检查，返回违规清单（能力id/包/缺口类型/路径）。"""
    违规: list[dict] = []
    声明 = 读取json(包目录 / "包声明.json") or {}
    包id = 声明.get("包id") or 包目录.name
    能力列表 = 声明.get("能力") or []
    声明路径 = 包目录 / "包声明.json"
    入口路径 = 包目录 / "__init__.py"
    数据路径 = 包目录 / "能力数据"
    搜索路径 = 数据路径 / "能力搜索数据.json"
    说明路径 = 包目录 / "说明" / "使用说明.md"
    验证路径 = 包目录 / "验证场景引用.json"
    源码 = 入口路径.read_text(encoding="utf-8") if 入口路径.is_file() else ""
    导出名 = 提取导出名(源码)
    映射 = 提取注册映射(源码)
    if not 能力列表:
        违规.append({"能力id": "*", "包": 包id, "缺口类型": "声明-包声明.json未列能力", "路径": str(声明路径)})
    if not (包目录 / "能力定义.json").is_file():
        违规.append({"能力id": "*", "包": 包id, "缺口类型": "声明-能力定义.json缺失", "路径": str(包目录 / "能力定义.json")})
    if "注册能力" not in 源码 and not 数据路径.is_dir():
        违规.append({"能力id": "*", "包": 包id, "缺口类型": "注册-入口未注册能力", "路径": str(入口路径)})
    搜索数据 = 读取json(搜索路径)
    搜索id集 = {条.get("能力id") for 条 in 搜索数据} if isinstance(搜索数据, list) else set()
    if 搜索数据 is None:
        违规.append({"能力id": "*", "包": 包id, "缺口类型": "搜索-能力搜索数据.json缺失", "路径": str(搜索路径)})
    说明书 = 说明路径.read_text(encoding="utf-8") if 说明路径.is_file() else None
    if 说明书 is None:
        违规.append({"能力id": "*", "包": 包id, "缺口类型": "说明书-使用说明.md缺失", "路径": str(说明路径)})
    验证场景 = 读取json(验证路径)
    验证文本 = json.dumps(验证场景, ensure_ascii=False) if 验证场景 else ""
    验证覆盖包 = any(条.get("目标") == 包id for 条 in 验证场景.get("验证场景引用", []) if isinstance(条, dict)) if 验证场景 else False
    if 验证场景 is None:
        违规.append({"能力id": "*", "包": 包id, "缺口类型": "验证场景-验证场景引用.json缺失", "路径": str(验证路径)})
    for 能力 in 能力列表:
        能力id = 能力.get("能力id") or ""
        名称 = 能力.get("名称") or ""
        if 说明书 is not None and 名称 and 名称 not in 说明书 and 能力id not in 说明书:
            违规.append({"能力id": 能力id, "包": 包id, "缺口类型": "说明书-未含能力名", "路径": str(说明路径)})
        if 搜索数据 is not None and 能力id not in 搜索id集:
            违规.append({"能力id": 能力id, "包": 包id, "缺口类型": "搜索-未含能力id", "路径": str(搜索路径)})
        if 能力id and (映射.get(能力id) or 能力id.split(".")[-1]) not in 导出名:
            违规.append({"能力id": 能力id, "包": 包id, "缺口类型": "公开调用-声明未导出", "路径": str(入口路径)})
        if 验证场景 is not None and not 验证覆盖包 and 能力id not in 验证文本:
            违规.append({"能力id": 能力id, "包": 包id, "缺口类型": "验证场景-未覆盖能力", "路径": str(验证路径)})
    return 违规


def 检查全局(包能力表: list[tuple[str, str, str]]) -> list[dict]:
    """跨包检查：同义能力（同名）与重复提供者（同能力id）。"""
    额外: list[dict] = []
    名称表: dict[str, set[str]] = {}
    id表: dict[str, set[str]] = {}
    for 包id, 能力id, 名称 in 包能力表:
        名称表.setdefault(名称, set()).add(包id)
        id表.setdefault(能力id, set()).add(包id)
    for 名称, 包们 in 名称表.items():
        if 名称 and len(包们) > 1:
            额外.append({"能力id": 名称, "包": "、".join(sorted(包们)), "缺口类型": "同义能力-跨包同名", "路径": "跨包"})
    for 能力id, 包们 in id表.items():
        if 能力id and len(包们) > 1:
            额外.append({"能力id": 能力id, "包": "、".join(sorted(包们)), "缺口类型": "重复提供者-同能力id多包", "路径": "跨包"})
    return 额外


def 运行门禁(根: Path) -> list[dict]:
    """扫描根目录下全部包，返回六环与全局检查的完整违规清单。"""
    违规: list[dict] = []
    包能力表: list[tuple[str, str, str]] = []
    for 包目录 in 找包目录(根):
        声明 = 读取json(包目录 / "包声明.json") or {}
        包id = 声明.get("包id") or 包目录.name
        包能力表.extend((包id, 能力.get("能力id") or "", 能力.get("名称") or "") for 能力 in 声明.get("能力") or [])
        违规.extend(检查包(包目录))
    违规.extend(检查全局(包能力表))
    return 违规


def main() -> int:
    根 = Path(sys.argv[1]) if len(sys.argv) > 1 else 仓库根
    违规 = 运行门禁(根)
    if not 违规:
        print("公开调用完整性门禁通过：六环一致，无违规")
        return 0
    print(f"公开调用完整性门禁失败：共 {len(违规)} 项违规（六环缺口+同义/重复）")
    for 条 in 违规:
        print(f"[{条['缺口类型']}] 能力id={条['能力id']} 包={条['包']} 路径={条['路径']}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
