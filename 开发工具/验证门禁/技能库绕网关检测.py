"""验证门禁三「技能库绕网关检测」——只读检查器，堵住审计件《重复腿与旁路》覆盖矩阵认定的缺口 3。

## 为什么需要它（现有门禁为什么盖不住）

现场证据（审计件 `开发文档/分析/审计_重复腿与旁路_20260919.md` §4.1/§4.3 与 I-4）：

- `开发工具/复用审计/能力调用图审计.py` 的扫描面**固定为 `模块库/`**
  （`审计模块库(实际目录)` 默认 `系统根/"模块库"`，`:298`）—— `技能库/**` **完全不在面内**；
- `运行核心/依赖防火墙.py` 的 `排除片段表`（`:460`）含 `测试中心/示例项目/开发文档/工程缓存`，
  **不含 `技能库`** —— 技能库确实被扫。但 `import sqlite3` 属标准库、在
  `标准库前缀表`（`:241`）里被直接放行，而**脚本里的 SQL 是字符串**，AST 抓不到；
- 技能库自身的 AST 审计（`技能库/后端/技能库/实现/技能库.py::审计脚本源码`）只拦
  「非标准库导入 / 进程派生 / `shell=True` / `eval`」，`sqlite3` 是标准库 → 放行；
- `开发工具/复用审计/提供者直连规则.py` 的扫描面只有 `支持库/适配层/**`。

于是平台自己明文规定的「技能脚本唯一的底座能力调用腿」在
`技能库/技能/交付收尾/scripts/交付收尾.py` 身上被绕成「直接开库」而**全部门禁都是绿的**。
`技能库/后端/技能库/说明/设计说明.md:77-94` 原文：「**可调能力白名单（技能脚本唯一的底座能力调用腿）**
…技能脚本**默认只能纯标准库**…脚本经该模块的 `调用底座能力(能力id, 参数)` 走**唯一网关**
`POST /网关/调用`」。

## 判据（三条规则）

- **规则 声明白名单未用**（审计件 I-4 最直接的形态）：`SKILL.md` 声明了 `可调能力白名单`，
  但同技能 `scripts/**.py` 里**一次都没出现** `技能底座能力` / `调用底座能力` → 命中。
  现场命中：`技能库/技能/交付收尾/SKILL.md`（对照：`技能库/技能/验证编排/SKILL.md:38-41` 有）。
- **规则 技能脚本直连底座资源**：技能脚本里出现直连库 / 自建 HTTP 客户端 / 派生进程的调用链
  → 命中。现场命中：`技能库/技能/交付收尾/scripts/交付收尾.py:148 sqlite3.connect`。
- **规则 技能脚本自拼网关地址**：技能脚本里出现 `127.0.0.1:<端口>` 或 `/网关/调用` 字面量
  → 命中（自建网关客户端 = 绕过受控执行注入的唯一腿）。**这是防未来新增的判据**：
  现场此刻 0 条（唯一腿由宿主注入，脚本只 `from 技能底座能力 import 调用底座能力`），
  判据守的是「不得新开第二条腿」，不报存量。

## 扫描面边界（为什么不能全扫技能库）

只有 `技能库/**/scripts/**.py` 是**技能脚本**（受控执行沙箱里的被执行方），才受
「唯一底座能力调用腿」约束。`技能库/后端/技能库/实现/技能库.py` 是**沙箱宿主本体**
（它 `import subprocess`、`subprocess.Popen` 起子进程、写网关合成模块），职责是「管住别人」
不是「被管」；`技能库/**/验证夹具/**` 是**故意的反面样本**（`越权技能/scripts/读项目.py`
刻意导入项目模块，用来验证沙箱在审计前就拦住）。两者进**显式跳过面**并计数上报，
不得静默当通过（2026-09-19 实测：不划这条线会得到 2 条永远为假的假红）。

## 覆盖不了什么（如实声明）

- 判不了「脚本经唯一腿调用、但用返回结果又去直连库」的组合形态（需数据流级判据）；
- 判不了「脚本改名 import」绕过的写法（`import sqlite3 as s`）—— 现场无此形态；
  本判据按**调用链**判（`sqlite3.connect` 与 `s.connect` 不同名），改名即漏。
"""

from __future__ import annotations

import ast
import json
import re
import sys
from pathlib import Path

if __name__ == "__main__" or __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from 公共契约.基础类型.逻辑类型 import 真  # noqa: E402
from 公共契约.运行时.平台适配 import 清只读后删除树  # noqa: E402
from 开发工具.验证门禁.门禁公共 import (  # noqa: E402
    新建夹具根,
    检查结论,
    命中,
)

检查器名 = "技能库绕网关检测"

规则_白名单未用 = "声明白名单未用"
规则_直连资源 = "技能脚本直连底座资源"
规则_自拼网关 = "技能脚本自拼网关地址"

技能脚本目录名 = "scripts"
技能夹具目录名 = "验证夹具"
技能包必需件 = "SKILL.md"

唯一腿模块 = "技能底座能力"
唯一腿函数 = "调用底座能力"
#: 声明「可调能力白名单」的标记：SKILL.md 里出现任一即算声明。
白名单声明标记 = ("可调能力白名单", "调用底座能力", "技能底座能力")

#: 直连底座资源的调用链 → 说明。
直连调用链 = {
    "sqlite3.connect": "直连 SQLite 库（应经 平台控制面.能力目录.* 的租约能力）",
    "sqlite3.connect_uri": "直连 SQLite 库",
    "psycopg.connect": "直连 PostgreSQL 库",
    "http.client.HTTPConnection": "自建 HTTP 客户端（应经宿主注入的唯一腿）",
    "http.client.HTTPSConnection": "自建 HTTPS 客户端（应经宿主注入的唯一腿）",
    "urllib.request.urlopen": "自建 HTTP 请求（应经宿主注入的唯一腿）",
    "socket.socket": "自建套接字",
    "subprocess.Popen": "派生外部进程",
    "subprocess.run": "派生外部进程",
    "os.system": "派生外部进程",
}

#: 自拼网关地址的判据：回环地址带端口，或网关路径字面量。
自拼网关判据 = re.compile(r"127\.0\.0\.1:\d+|/网关/调用|网关/调用")

#: 文档字符串的「空转」判据：模块/类/函数的第一条语句若是字符串常量，它就是 docstring。
def _文档字符串节点(树: ast.AST) -> set[int]:
    """收集全部 docstring 常量的 `id()`，用于把「说明里提到网关」与「代码里真拼网关」分开。

    为什么必须分开（2026-09-19 实测假红）：`技能库/技能/交付收尾/scripts/交付收尾.py:10`
    的**模块 docstring** 里原文写着「→ 唯一网关 `POST http://127.0.0.1:40007/网关/调用`」，
    那是**说明它在走唯一腿**，不是自建第二条腿。按行文本搜会把「说明」判成「违规」。
    """
    出: set[int] = set()
    for 节点 in ast.walk(树):
        for 域 in ("body", "orelse", "finalbody"):
            语句表 = getattr(节点, 域, None)
            if not isinstance(语句表, list) or not 语句表:
                continue
            首句 = 语句表[0]
            if (
                isinstance(首句, ast.Expr)
                and isinstance(首句.value, ast.Constant)
                and isinstance(首句.value.value, str)
            ):
                出.add(id(首句.value))
    return 出


def _调用链(节点: ast.AST) -> str:
    段: list[str] = []
    当前 = 节点
    while isinstance(当前, ast.Attribute):
        段.append(当前.attr)
        当前 = 当前.value
    if isinstance(当前, ast.Name):
        段.append(当前.id)
    return ".".join(reversed(段))


def _解析(路径: Path, 结论: 检查结论, 根: Path) -> ast.Module | None:
    try:
        源码 = 路径.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as 错误:
        结论.不可解析.append(f"{路径.relative_to(根).as_posix()}: {type(错误).__name__}")
        return None
    try:
        return ast.parse(源码)
    except SyntaxError as 错误:
        结论.不可解析.append(f"{路径.relative_to(根).as_posix()}: 语法错误 行{错误.lineno}")
        return None


def _技能包表(技能根: Path) -> list[Path]:
    """技能包的判据 = 目录里有 `SKILL.md`（技能六件套之一）。"""
    出 = [声明.parent for 声明 in sorted(技能根.rglob(技能包必需件))]
    return [包 for 包 in 出 if 技能夹具目录名 not in 包.parts]


def _技能脚本表(技能库根: Path) -> list[Path]:
    出: list[Path] = []
    for 源码 in sorted(技能库根.rglob("*.py")):
        if "__pycache__" in 源码.parts:
            continue
        if 技能脚本目录名 not in 源码.parts:
            continue
        if 技能夹具目录名 in 源码.parts:
            continue
        出.append(源码)
    return 出


def _规则声明白名单未用(根: Path, 结论: 检查结论) -> None:
    技能根 = root_技能 = 根 / "技能库"
    if not 技能根.is_dir():
        结论.扫描面[规则_白名单未用] = 0
        return
    包表 = _技能包表(技能根)
    计数 = 0
    声明数 = 0
    for 包 in 包表:
        计数 += 1
        声明 = 包 / 技能包必需件
        try:
            文本 = 声明.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as 错误:
            结论.不可解析.append(f"{声明.relative_to(根).as_posix()}: {type(错误).__name__}")
            continue
        if not any(标记 in 文本 for 标记 in 白名单声明标记):
            continue
        声明数 += 1
        脚本表 = [
            源码
            for 源码 in _技能脚本表(技能根)
            if 包 in 源码.parents
        ]
        if not 脚本表:
            结论.命中列表.append(
                命中(规则_白名单未用, 声明.relative_to(根).as_posix(), 0,
                     "技能声明了可调能力白名单，但该技能 scripts/ 下没有任何脚本可承载唯一腿")
            )
            continue
        用到唯一腿 = False
        for 脚本 in 脚本表:
            子结论 = 检查结论(名称=检查器名)
            树 = _解析(脚本, 子结论, 根)
            结论.不可解析 += 子结论.不可解析
            if 树 is None:
                continue
            文本 = 脚本.read_text(encoding="utf-8")
            if 唯一腿模块 in 文本 or 唯一腿函数 in 文本:
                用到唯一腿 = True
                break
        if not 用到唯一腿:
            结论.命中列表.append(
                命中(规则_白名单未用, 声明.relative_to(根).as_posix(), 0,
                     f"声明了可调能力白名单，但 {len(脚本表)} 个脚本都没用 {唯一腿模块}.{唯一腿函数}"
                     f"（唯一腿被绕开）")
            )
    结论.扫描面[规则_白名单未用] = 计数
    结论.跳过面[f"{规则_白名单未用}：声明了白名单的技能包数"] = 声明数
    结论.跳过面[f"{规则_白名单未用}：跳过 验证夹具/ 下夹具技能包数"] = (
        len([声明 for 声明 in 技能根.rglob(技能包必需件) if 技能夹具目录名 in 声明.parts])
    )


def _规则直连资源(根: Path, 结论: 检查结论) -> None:
    技能根 = 根 / "技能库"
    if not 技能根.is_dir():
        结论.扫描面[规则_直连资源] = 0
        return
    脚本表 = _技能脚本表(技能根)
    结论.扫描面[规则_直连资源] = len(脚本表)
    有腿数 = 0
    for 脚本 in 脚本表:
        树 = _解析(脚本, 结论, 根)
        if 树 is None:
            continue
        相对 = 脚本.relative_to(根).as_posix()
        命中链 = [
            (链, 行号)
            for 节点 in ast.walk(树)
            if isinstance(节点, ast.Call)
            for 链 in (_调用链(节点.func),)
            if 链 and any(链 == 键 or 链.endswith("." + 键) or 链.startswith(键) for 键 in 直连调用链)
            for 行号 in (节点.lineno,)
        ]
        if not 命中链:
            continue
        有腿数 += 1
        for 链, 行号 in 命中链:
            目标 = next(
                (键 for 键 in 直连调用链 if 链 == 键 or 链.endswith("." + 键) or 链.startswith(键)),
                "",
            )
            结论.命中列表.append(
                命中(规则_直连资源, 相对, 行号,
                     f"{链} —— {直连调用链.get(目标, '直连底座资源')}；"
                     f"唯一腿 = {唯一腿模块}.{唯一腿函数}")
            )
    结论.跳过面[f"{规则_直连资源}：有直连调用的脚本数"] = 有腿数


def _规则自拼网关(根: Path, 结论: 检查结论) -> None:
    技能根 = 根 / "技能库"
    if not 技能根.is_dir():
        结论.扫描面[规则_自拼网关] = 0
        return
    脚本表 = _技能脚本表(技能根)
    结论.扫描面[规则_自拼网关] = len(脚本表)
    命中数 = 0
    文档提及数 = 0
    for 脚本 in 脚本表:
        树 = _解析(脚本, 结论, 根)
        if 树 is None:
            continue
        文档集 = _文档字符串节点(树)
        相对 = 脚本.relative_to(根).as_posix()
        for 节点 in ast.walk(树):
            if not isinstance(节点, ast.Constant) or not isinstance(节点.value, str):
                continue
            if not 自拼网关判据.search(节点.value):
                continue
            if id(节点) in 文档集:
                文档提及数 += 1
                continue
            命中数 += 1
            结论.命中列表.append(
                命中(规则_自拼网关, 相对, 节点.lineno,
                     f"技能脚本自拼网关地址：{节点.value.strip()[:60]}（应经宿主注入的唯一腿）")
            )
    结论.跳过面[f"{规则_自拼网关}：自拼网关地址行数"] = 命中数
    结论.跳过面[f"{规则_自拼网关}：docstring 里提及网关地址（说明走唯一腿，不判红）"] = 文档提及数


def 构建结论(根: Path) -> 检查结论:
    结论 = 检查结论(名称=检查器名)
    _规则声明白名单未用(根, 结论)
    _规则直连资源(根, 结论)
    _规则自拼网关(根, 结论)
    return 结论


# ────────────────────────── 反向验证（变异样本必红）──────────────────────────
#: 拍一/拍三用的合法技能包：声明白名单 **且** 脚本走唯一腿 → 必须一条都不报。
合法样本表: tuple[tuple[str, str], ...] = (
    ("技能库/技能/夹具基准技能/SKILL.md",
     "# 夹具基准技能\n\n## 调用约束\n\n可调能力白名单 = [\"测试支持库.验证结果判定\"]\n"
     "技能脚本经 `技能底座能力.调用底座能力(能力id, 参数)` 走唯一网关。\n"),
    ("技能库/技能/夹具基准技能/scripts/夹具基准脚本.py",
     "from 技能底座能力 import 调用底座能力\n\n\n"
     "结果 = 调用底座能力(\"测试支持库.验证结果判定\", {\"名称\": \"夹具\"})\n"
     "print(结果)\n"),
)

#: 每条判据一份「故意违规」样本：说明 → 相对路径 → 内容。
变异样本表: tuple[tuple[str, str, str], ...] = (
    ("规则 声明白名单未用",
     "技能库/技能/夹具技能一/SKILL.md",
     "# 夹具技能一\n\n## 调用约束\n\n可调能力白名单 = [\"测试支持库.验证结果判定\"]\n"
     "技能脚本经 技能底座能力 走唯一网关。\n"),
    ("规则 声明白名单未用（配套脚本，绕开唯一腿）",
     "技能库/技能/夹具技能一/scripts/夹具脚本一.py",
     "print(\"夹具：不调底座能力，直接算\")\n"),
    ("规则 技能脚本直连底座资源",
     "技能库/技能/夹具技能二/scripts/夹具脚本二.py",
     "import sqlite3\n\n\n连接 = sqlite3.connect('工程缓存/运行数据/底座运行.db')\n"),
    ("规则 技能脚本自拼网关地址",
     "技能库/技能/夹具技能三/scripts/夹具脚本三.py",
     "网关地址 = 'http://127.0.0.1:40007'\n\n\nprint(网关地址)\n"),
)


def _自证() -> int:
    """三拍自证：① 合法技能包（走唯一腿）→ 绿；② 注入 4 份违规样本 → 必红；③ 撤除 → 回绿。"""
    import subprocess

    根 = 新建夹具根("验证门禁三_自证_")
    基线 = 根 / "基线.json"
    结果: list[tuple[str, str]] = []
    for 相对, 内容 in 合法样本表:
        路径 = 根 / 相对
        路径.parent.mkdir(parents=True, exist_ok=True)
        路径.write_text(内容, encoding="utf-8")
    (根 / "技能库").mkdir(parents=True, exist_ok=True)
    (根 / "基线.json").write_text(
        json.dumps({"检查器": {检查器名: {}}}, ensure_ascii=False), encoding="utf-8"
    )

    def _跑() -> int:
        return subprocess.run(
            [sys.executable, str(Path(__file__)), "--根", str(根), "--基线", str(基线)],
            capture_output=True, text=True, timeout=240,
        ).returncode

    第一拍 = _跑()
    结果.append((f"第一拍 合法技能包 {根}", f"退出码 {第一拍}（期望 0=绿）"))
    for _说明, 相对, 内容 in 变异样本表:
        路径 = 根 / 相对
        路径.parent.mkdir(parents=True, exist_ok=True)
        路径.write_text(内容, encoding="utf-8")
    第二拍 = _跑()
    结果.append((f"第二拍 注入 {len(变异样本表)} 份违规样本", f"退出码 {第二拍}（期望 1=红）"))
    for _说明, 相对, _内容 in 变异样本表:
        路径 = 根 / 相对
        if 路径.is_file():
            路径.unlink()
    第三拍 = _跑()
    结果.append(("第三拍 撤除违规样本", f"退出码 {第三拍}（期望 0=绿）"))

    print(f"══ {检查器名} 自证（三拍）══")
    for 名, 值 in 结果:
        print(f"  {名}：{值}")
    通过 = 第一拍 == 0 and 第二拍 == 1 and 第三拍 == 0
    print(f"  自证结论：{'通过' if 通过 else '不通过'}")
    if not 通过:
        print(f"  ⚠ 夹具根保留供人工复核：{根}")
        return 1
    # 夹具根可能含只读条目 → 走唯一实现，不留 shutil.rmtree 裸调用
    清只读后删除树(根, 忽略失败=真)
    return 0


def main(argv: list[str] | None = None) -> int:
    实参 = list(sys.argv[1:] if argv is None else argv)
    if "--自证" in 实参:
        return _自证()
    from 开发工具.验证门禁.门禁公共 import 跑标准主流程

    return 跑标准主流程(检查器名, 构建结论, 实参)


if __name__ == "__main__":
    sys.exit(main())
