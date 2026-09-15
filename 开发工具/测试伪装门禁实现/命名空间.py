"""生产命名空间判定与 patch 目标解析（规则 1 的事实基础）。

**生产根口径** 取自 `落点清单_02_测试体系.md` 硬规则 1：`patch` 目标解析后的
模块路径属于 `支持库/模块库/运行核心/公共契约/平台控制面/开发工具/发布门禁`
之一，即落在生产命名空间内；其中 `发布门禁` 是 `开发工具/发布门禁/` 子目录，
已含在 `开发工具` 内。其余顶层目录（`MCP工具箱`/`示例项目`/`技能库` 等）不在
硬规则 1 的射程内，命中只进「范围外」统计，不判违规。

**两级判定**（都基于「本测试文件 import 了什么」，可复现、不猜）：

- `P1 被测模块本体`：目标模块路径与本文件 import 的某个生产模块**精确相等**
  → 即「patch 被测对象自身」。`落点清单` B-1 的
  `mock.patch("支持库.适配层.系统探针.检查系统工具")` 落在这一级
  （该文件 `from 支持库.适配层.系统探针 import 检查系统工具`）。
- `P2 生产路径（跨模块）`：目标模块路径在生产命名空间内但不是本文件 import
  的模块本体（例如经生产模块转手的 `…环境管理器.校验环境`）。

**成员分类**（用生产模块自身的 AST 判定，不加载模块）：目标符号是该生产模块
「自身定义（def/class/赋值）」还是「它 import 进来的名字」。前者是
`本体成员`（patch 掉的是生产实现），后者是 `依赖边界`（patch 的是生产模块
转手的第三方/外部依赖，如 `…环境管理器.venv`、`…项目编译器.shutil.rmtree`）。
两类都判违规（`落点清单` B-2 的 `shutil.rmtree` 正属依赖边界），但分开计数，
便于按子类型批量豁免或分批清零。

本模块只做纯解析：不导入任何模块（只 `ast.parse` 生产源码文本）、不打印。
"""
from __future__ import annotations

import ast
from functools import lru_cache
from pathlib import Path

生产根 = ("支持库", "模块库", "运行核心", "公共契约", "平台控制面", "开发工具")
范围外根 = (
    "前端核心", "后端核心", "客户端", "启动监督器", "项目适配层",
    "示例项目", "运维脚本", "技能库", "测试中心", "工程缓存", "开发文档",
)
测试自身根 = ("测试中心",)

#: 断言/条件里出现这些字段名，视为「可区分结构」的强信号（规则 3）。
结构字段名 = frozenset({
    "错误码", "问题列表", "详细信息", "问题", "类型", "摘要", "记录", "字段",
    "版本", "退出码", "指纹", "诊断", "证据", "原因", "状态", "边界",
})

#: 真实副作用证据：对文件系统/注册表的真实存在性与内容读取。
副作用调用名 = frozenset({
    "is_file", "is_dir", "exists", "is_symlink", "read_text", "read_bytes",
    "stat", "rglob", "glob", "iterdir", "listdir", "scandir", "walk",
    "resolve", "samefile", "readlink",
})


def 是生产命名空间(模块路径: str) -> bool:
    return bool(模块路径) and 模块路径.split(".")[0] in 生产根


def 是范围外命名空间(模块路径: str) -> bool:
    return bool(模块路径) and 模块路径.split(".")[0] in 范围外根


def 解析字符串目标(文本: str) -> tuple[str, str]:
    """`"a.b.c.符号"` → `("a.b.c", "符号")`；不足两段或空 → `("", 原文)`。"""
    段 = [段 for 段 in str(文本).split(".") if 段]
    if len(段) < 2:
        return "", str(文本)
    return ".".join(段[:-1]), 段[-1]


def 收集导入表(树: ast.Module) -> dict[str, str]:
    """测试文件内 名字/别名 → 它指向的具体路径（模块或模块成员）。

    - `from 支持库.适配层 import 系统探针` → `{"系统探针": "支持库.适配层.系统探针"}`
    - `from 开发工具.项目编译.项目编译器 import 校验输出目录`
      → `{"校验输出目录": "开发工具.项目编译.项目编译器.校验输出目录"}`
    - `import 运行核心.环境管理器 as 管理器` → `{"管理器": "运行核心.环境管理器"}`

    覆盖函数级 import（`ast.walk`），因为本仓多个用例在方法体内做延迟导入。
    """
    表: dict[str, str] = {}
    for 节点 in ast.walk(树):
        if isinstance(节点, ast.ImportFrom):
            if 节点.level:
                continue
            基 = 节点.module or ""
            for 别名 in 节点.names:
                if 别名.name == "*":
                    continue
                名字 = 别名.asname or 别名.name
                表[名字] = f"{基}.{别名.name}" if 基 else 别名.name
        elif isinstance(节点, ast.Import):
            for 别名 in 节点.names:
                名字 = 别名.asname or 别名.name.split(".")[0]
                表[名字] = 别名.name
    return 表


def 收集生产导入(树: ast.Module) -> dict[str, list[str]]:
    """测试文件 import 的生产模块 → 依据说明列表（用于 P1/P2 分级）。"""
    结果: dict[str, list[str]] = {}
    for 节点 in ast.walk(树):
        if isinstance(节点, ast.ImportFrom):
            if 节点.level or not 节点.module:
                continue
            模块 = 节点.module
            if 是生产命名空间(模块):
                结果.setdefault(模块, []).append(f"from {模块} import …")
        elif isinstance(节点, ast.Import):
            for 别名 in 节点.names:
                if 是生产命名空间(别名.name):
                    结果.setdefault(别名.name, []).append(f"import {别名.name}")
    return 结果


def 解析宿主(表达式: ast.AST, 导入表: dict[str, str]) -> tuple[str, str]:
    """`patch.object` 宿主表达式 → `(宿主模块路径, 宿主属性链)`。

    - `patch.object(校验环境模块, "同名")` → `("…校验环境模块路径", "")`
    - `patch.object(模块.psycopg, "connect")` → `("…实现.提供者", "psycopg")`

    解析不出模块路径（本地变量、字面量、mock 对象）→ `("", 表达式文本)`。
    """
    链: list[str] = []
    节点: ast.AST = 表达式
    while isinstance(节点, ast.Attribute):
        链.append(节点.attr)
        节点 = 节点.value
    if not isinstance(节点, ast.Name):
        return "", _安全unparse(表达式)
    基 = 导入表.get(节点.id, "")
    if not 基:
        return "", _安全unparse(表达式)
    链.reverse()
    return 基, ".".join(链)


def _安全unparse(节点: ast.AST) -> str:
    try:
        return ast.unparse(节点)
    except Exception:  # pragma: no cover - ast.unparse 对合法 AST 不会抛
        return "<无法反解>"


@lru_cache(maxsize=512)
def _读取生产模块源码(模块文件: Path) -> str:
    try:
        return 模块文件.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""


def 定位生产模块(根: Path, 模块路径: str) -> Path | None:
    """`模块路径` → 生产模块文件/包路径；不存在返回 None（不导入）。"""
    段 = [段 for 段 in 模块路径.split(".") if 段]
    if not 段:
        return None
    if any(段片段 in ("..", "/", "\\") for 段片段 in 段):
        return None
    直接文件 = 根.joinpath(*段).with_suffix(".py")
    if 直接文件.is_file():
        return 直接文件
    包文件 = 根.joinpath(*段) / "__init__.py"
    if 包文件.is_file():
        return 包文件
    return None


def 模块成员分类(根: Path, 模块路径: str, 首符号: str) -> str:
    """目标首符号在该生产模块里是「自身定义」还是「导入的名字」。

    - `自身定义`（def/class/赋值/带注解赋值）→ `本体成员`：patch 的是生产实现；
    - 出现在 import 语句里 → `依赖边界`：patch 的是生产模块转手的外部依赖
      （第三方库、stdlib），如 `shutil.rmtree`、`venv`、`psycopg`；
    - 两者都查不到（动态注册/`__getattr__`/名字来自 `globals()` 注入）→ `未知`。
    """
    if not 首符号:
        return "未知"
    模块文件 = 定位生产模块(根, 模块路径)
    if 模块文件 is None:
        return "未知"
    源码 = _读取生产模块源码(模块文件)
    if not 源码:
        return "未知"
    try:
        树 = ast.parse(源码)
    except SyntaxError:
        return "未知"
    导入名: set[str] = set()
    定义名: set[str] = set()
    for 节点 in 树.body:
        if isinstance(节点, ast.Import):
            导入名.update((别名.asname or 别名.name.split(".")[0]) for 别名 in 节点.names)
        elif isinstance(节点, ast.ImportFrom):
            导入名.update((别名.asname or 别名.name) for 别名 in 节点.names if 别名.name != "*")
        elif isinstance(节点, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            定义名.add(节点.name)
        elif isinstance(节点, ast.Assign):
            定义名.update(目标.id for 目标 in 节点.targets if isinstance(目标, ast.Name))
        elif isinstance(节点, ast.AnnAssign) and isinstance(节点.target, ast.Name):
            定义名.add(节点.target.id)
        elif isinstance(节点, (ast.If, ast.Try)):
            for 子 in ast.walk(节点):
                if isinstance(子, (ast.FunctionDef, ast.ClassDef)):
                    定义名.add(子.name)
    if 首符号 in 定义名:
        return "本体成员"
    if 首符号 in 导入名:
        return "依赖边界"
    return "未知"


def 受测模块集合(树: ast.Module) -> dict[str, list[str]]:
    """本测试文件直接 import 的生产模块（P1 判级的依据集合）。"""
    return 收集生产导入(树)


def 推断受测模块(树: ast.Module, 相对路径: str) -> tuple[str, str]:
    """按文件名推断「本次受测模块」，用于报告里的一句话定位。

    优先取「生产导入模块的末段 == 文件名去掉 `测试_`」的那个；没有则取第一
    个生产导入模块。返回 `(模块路径, 依据)`，推不出返回 `("", "")`。
    """
    导入 = 收集生产导入(树)
    if not 导入:
        return "", ""
    目标名 = Path(相对路径).stem.removeprefix("测试_")
    for 模块路径 in 导入:
        if 模块路径.split(".")[-1] == 目标名:
            return 模块路径, "文件名匹配（去 测试_ 前缀后与导入模块末段同名）"
    首个 = sorted(导入)[0]
    return 首个, "本文件首个生产导入（无文件名匹配）"
