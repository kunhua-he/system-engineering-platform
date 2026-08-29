"""公开调用完整性门禁：正式公开包的六环一致性。

正式公开边界只有 ``支持库/后端`` 与 ``模块库``。``支持库/适配层`` 是
Provider/第三方实现边界：它可以声明内部实现能力，但不能成为公开能力
owner，也不能因为和正式包使用同一能力 id 而制造重复 owner。模板目录（如
``模块库/_模板``）同样不是正式包，禁止进入扫描、注册和冲突统计。

注册表为唯一事实源（包声明.json 能力列表），公开调用必须经由注册能力导出。
任一违规 → 退出码 1 并打印缺口类型/能力id/包/路径清单；全部通过 → 退出码 0。
"""
from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

仓库根 = Path(__file__).resolve().parents[1]
# 这里只列出可以向调用方公开能力的正式包根。适配层 Provider 有自己的
# 依赖/运行时门禁，不得混入公开能力六环或公开 owner 冲突统计。
扫描段 = ("支持库/后端", "模块库")


def _是保留目录(路径: Path) -> bool:
    """模板、隐藏目录和缓存目录均不属于正式公开包。"""
    return 路径.name.startswith(("_", "."))


def _是聚合父包(包目录: Path) -> bool:
    """聚合父包：无能力定义.json 且有子目录含包声明.json。

    0342d39 功能域分组后，``支持库/后端`` 直接子目录是聚合入口（如
    ``系统核心支持库``），能力由子域包（``系统核心支持库/幂等消息``）
    声明。聚合父包只做聚合视图，不拥有六环，门禁应跳过它，与正式包索引
    ``无能力定义.json 即聚合父包`` 的 owner 规则一致。
    """
    if (包目录 / "能力定义.json").is_file():
        return False
    return any(
        (子 / "包声明.json").is_file()
        for 子 in 包目录.iterdir() if 子.is_dir()
    )


def 读取json(路径: Path):
    try:
        return json.loads(路径.read_text(encoding="utf-8"))
    except Exception:
        return None


def 找包目录(根: Path) -> list[Path]:
    """返回正式公开包目录（递归到叶子包，跳过聚合父包与保留目录）。

    正式包边界是 ``支持库/后端`` 与 ``模块库``；聚合父包（无能力定义.json
    且有子域包）与 ``_``/``.`` 开头的保留目录不进入扫描。物理目录层级不是
    调用契约，但正式包根的边界是门禁的安全边界。
    """
    目录: list[Path] = []
    for 段 in 扫描段:
        扫描根 = 根 / 段
        if not 扫描根.is_dir():
            continue
        for 声明路径 in sorted(扫描根.rglob("包声明.json")):
            包目录 = 声明路径.parent
            相对 = 包目录.relative_to(扫描根)
            if any(片段.startswith(("_", ".")) for 片段 in 相对.parts):
                continue
            if _是聚合父包(包目录):
                continue
            目录.append(包目录)
    return sorted(目录)


def _公开owner字段(声明: dict) -> list[str]:
    """读取显式公开 owner 字段，供正式包反向阻断 Provider 越界声明。

    ``提供者`` 是实现路由字段，不等于公开 owner，因此不会被误判；只有
    明确写成 ``公开所有者``/``公开owner``/``owner`` 的字段才进入该检查。
    """
    字段值: list[str] = []
    for 键 in ("公开所有者", "公开owner", "owner"):
        值 = 声明.get(键)
        if isinstance(值, str) and 值:
            字段值.append(值)
    for 能力 in 声明.get("能力") or []:
        if not isinstance(能力, dict):
            continue
        for 键 in ("公开所有者", "公开owner", "owner"):
            值 = 能力.get(键)
            if isinstance(值, str) and 值:
                字段值.append(值)
    return 字段值


def _是适配层Provider(owner: str) -> bool:
    """判定 owner 是否指向适配层 Provider（只做声明门禁，不加载实现）。"""
    return owner.startswith("支持库.适配层.") and owner.endswith("提供者")


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
    for owner in _公开owner字段(声明):
        if _是适配层Provider(owner):
            违规.append({"能力id": "*", "包": 包id,
                        "缺口类型": "提供者-适配层Provider不得成为公开owner",
                        "路径": str(声明路径)})
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
    """跨包检查：只查能力 id 全局唯一，豁免中文名重复。

    华哥裁决（2026-08-27）：能力 id 是全局唯一标识（硬约束），中文名是
    显示层，模块库门面组合支持库、多后端提供者、通用能力名都可以同名。
    """
    额外: list[dict] = []
    id表: dict[str, set[str]] = {}
    for 包id, 能力id, 名称 in 包能力表:
        id表.setdefault(能力id, set()).add(包id)
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


def 主程序() -> int:
    根 = Path(sys.argv[1]) if len(sys.argv) > 1 else 仓库根
    违规 = 运行门禁(根)
    if not 违规:
        print("公开调用完整性门禁通过：六环一致，无违规")
        return 0
    print(f"公开调用完整性门禁失败：共 {len(违规)} 项违规（六环缺口+重复提供者）")
    for 条 in 违规:
        print(f"[{条['缺口类型']}] 能力id={条['能力id']} 包={条['包']} 路径={条['路径']}")
    return 1


if __name__ == "__main__":
    sys.exit(主程序())
