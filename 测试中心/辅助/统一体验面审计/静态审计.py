"""工作包18 静态审计：五类视图必须把搜索/权限/调用/发布规则下沉到统一能力服务。

规则（命中即违规，进入阻断清单）：
1. 权限重复：视图在代码中（非字符串）使用 角色等级/操作最小角色，且全文没有
   服务.授权 或 服务.执行操作 兜底调用 → 自实现权限判定。
2. 搜索重复：视图自行扫描文件系统（rglob/iterdir/glob/listdir/walk），且调用
   不在 服务.目录 权威链上 → 自实现搜索。
3. 调用重复：视图直接执行外部进程（subprocess/Popen/run/system 等）→ 自实现调用。
4. 发布重复：视图直接编排发布链路（签名制品/开始灰度/激活）且不经 服务.仓库/
   服务.发布/服务.执行操作；或自实现签名（私钥+摘要本地计算，不经
   服务.仓库.签名制品）→ 复制发布规则。
5. 服务必达：每个视图至少一处 服务.执行操作( 或 服务.xxx. 权威公开能力调用。
警告（不阻断）：条件表达式直接使用角色等级表、直读授权私有会话表、
全表扫描能力条目、直读服务私有成员。仅允许 Python 标准库。
"""
from __future__ import annotations

import ast
from pathlib import Path
from typing import Any
系统根 = Path(__file__).resolve().parents[3]

视图文件表: dict[str, Path] = {
    "普通用户视图": 系统根 / "开发工具" / "统一能力入口" / "视图" / "普通用户视图.py",
    "调用Agent视图": 系统根 / "开发工具" / "统一能力入口" / "视图" / "调用Agent视图.py",
    "组件开发Agent视图": 系统根 / "开发工具" / "统一能力入口" / "视图" / "组件开发Agent视图.py",
    "维护者视图": 系统根 / "开发工具" / "统一能力入口" / "视图" / "维护者视图.py",
    "发布者视图": 系统根 / "开发工具" / "统一能力入口" / "视图" / "发布者视图.py",
}

文件扫描名 = {"rglob", "iterdir", "glob", "listdir", "walk"}
进程执行名 = {"subprocess", "Popen", "run", "system", "check_output", "popen"}
发布实现名 = {"签名制品", "开始灰度", "激活"}
权限索引名 = {"角色等级", "操作最小角色"}
服务公开名 = {"执行操作", "授权", "状态", "需求", "目录", "策略", "仓库",
              "发布", "监督", "快照", "提供者注册表"}


class 审计结果:
    """单视图审计结论：违规表（阻断）/ 警告表 / 服务调用命中表。"""

    def __init__(self, 视图名: str, 路径: Path) -> None:
        self.视图名 = 视图名
        self.路径 = 路径
        self.违规表: list[str] = []
        self.警告表: list[str] = []
        self.服务调用表: list[str] = []

    @property
    def 阻断项(self) -> list[str]:
        return self.违规表


def _链文本(节点) -> str:
    """把 ast 表达式还原为点分链文本；self.服务 前缀归一化为 服务。"""
    if isinstance(节点, ast.Name):
        return 节点.id
    if isinstance(节点, ast.Attribute):
        前缀 = _链文本(节点.value)
        链 = f"{前缀}.{节点.attr}" if 前缀 else 节点.attr
        return 链[5:] if 链.startswith("self.服务") else 链
    return ""


def _收集服务调用(树: ast.AST) -> list[str]:
    """收集源码中全部 服务.xxx 形态的点分调用链（去重保序）。"""
    链表: list[str] = []
    已见: set[str] = set()
    for 节点 in ast.walk(树):
        if isinstance(节点, ast.Call):
            链 = _链文本(节点.func)
            if 链.startswith("服务.") and 链 not in 已见:
                链表.append(链)
                已见.add(链)
    return 链表


def _命名索引使用(树: ast.AST) -> bool:
    """代码中（非字符串）是否使用 角色等级/操作最小角色 标识符。"""
    return any(isinstance(节点, ast.Name) and 节点.id in 权限索引名
               for 节点 in ast.walk(树))


def _条件中索引行(树: ast.AST) -> list[int]:
    """收集在条件表达式（If/While/IfExp/Compare）内使用角色等级表的行号。"""
    命中行: list[int] = []
    for 节点 in ast.walk(树):
        条件区 = 节点.test if isinstance(节点, (ast.If, ast.While, ast.IfExp)) else (
            节点 if isinstance(节点, ast.Compare) else None)
        if 条件区 is None:
            continue
        for 子 in ast.walk(条件区):
            if isinstance(子, ast.Name) and 子.id in 权限索引名:
                命中行.append(节点.lineno)
                break
    return 命中行


def _按名找调用(树: ast.AST, 名称集: set[str]) -> list[str]:
    """收集最终属性名命中 名称集 的全部点分调用链。"""
    return [_链文本(节点.func) for 节点 in ast.walk(树)
            if isinstance(节点, ast.Call)
            and _链文本(节点.func).split(".")[-1] in 名称集]


def 审计单个视图(视图名: str) -> 审计结果:
    """静态审计单个视图文件：返回 违规表/警告表/服务调用命中表。"""
    路径 = 视图文件表.get(视图名)
    结果 = 审计结果(视图名, 路径 or Path(""))
    if 路径 is None or not 路径.is_file():
        结果.违规表.append(f"视图文件不存在: {路径}")
        return 结果
    文本 = 路径.read_text(encoding="utf-8")
    try:
        树 = ast.parse(文本)
    except SyntaxError as 错误:
        结果.违规表.append(f"视图源码解析失败: {错误}")
        return 结果
    # 规则5（正面）：服务调用命中
    结果.服务调用表 = _收集服务调用(树)
    if not 结果.服务调用表:
        结果.违规表.append("未调用任何统一能力服务公开能力（无 服务.执行操作/服务.xxx）")
    # 规则1：权限重复
    if _命名索引使用(树) and "服务.授权" not in 文本 and "服务.执行操作" not in 文本:
        结果.违规表.append("自行比较 角色等级/操作最小角色 且无 服务.授权/服务.执行操作 兜底")
    for 行 in _条件中索引行(树):
        结果.警告表.append(
            f"条件表达式中直接使用角色等级表（行{行}）：只允许展示过滤，访问判定必须经服务")
    # 规则2：搜索重复；规则3：调用重复
    for 链 in _按名找调用(树, 文件扫描名):
        if not 链.startswith("服务.目录"):
            结果.违规表.append(f"自行扫描文件系统实现搜索: {链}")
    for 链 in _按名找调用(树, 进程执行名):
        结果.违规表.append(f"视图直接执行外部进程/提供者: {链}")
    # 规则4：发布重复
    for 链 in _按名找调用(树, 发布实现名):
        if not 链.startswith(("服务.仓库", "服务.发布", "服务.执行操作")):
            结果.违规表.append(f"自行编排发布链路: {链}")
    if ("私钥" in 文本 or "PEM" in 文本) and ("hashlib" in 文本 or "sha256" in 文本) \
            and "服务.仓库.签名制品" not in 文本:
        结果.违规表.append("自实现签名（私钥+摘要本地计算，不经 服务.仓库.签名制品）")
    # 警告（不阻断）
    if "服务.授权._会话表" in 文本:
        结果.警告表.append("直接读取授权私有会话表（建议经服务公开能力获取会话信息）")
    if '查询记录("能力条目"' in 文本 or "查询记录('能力条目'" in 文本:
        结果.警告表.append("全表扫描能力条目（只读维护场景允许，搜索必须经 搜索能力）")
    if "_签名密钥环" in 文本 or "_提供者表" in 文本:
        结果.警告表.append("直接读取服务私有成员（密钥环/提供者表，建议经服务公开能力）")
    return 结果


def 审计全部视图() -> list[审计结果]:
    """审计五个视图（固定顺序：普通用户→调用Agent→组件开发Agent→维护者→发布者）。"""
    return [审计单个视图(名) for 名 in 视图文件表]


def 阻断清单() -> list[dict[str, Any]]:
    """只返回存在违规的视图；全部合规返回空表（测试7 断言为空）。"""
    return [{"视图名": 结果.视图名, "违规": list(结果.违规表)}
            for 结果 in 审计全部视图() if 结果.违规表]
