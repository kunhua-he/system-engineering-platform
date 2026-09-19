"""验证门禁二「调用腿唯一性检测」——只读检查器，堵住审计件《重复腿与旁路》覆盖矩阵认定的缺口 2。

## 为什么需要它（现有门禁为什么盖不住）

现场证据（审计件 `开发文档/分析/审计_重复腿与旁路_20260919.md` §4.1/§4.3 与 I-1/I-6/I-7）：

- `开发工具/复用审计/能力调用图审计.py` 判的是「模块是否越过 `实现/` 直连、是否复制原子实现」，
  **它不判「这个模块走的是哪条调用腿」**。实测：两腿「老腿」的 12 个包既不 import 支持库、
  也不 import 运行核心（连接器由装配点注入），**每条判据都过**；
- `运行核心/依赖防火墙.py` 只看 **import 方向**：老腿经注入、新腿经
  `公共契约/能力契约/调用器.py`，两者的 import 都合法 → 实测全绿（769 文件 / 0 违规）；
- `开发工具/复用审计/提供者直连规则.py` 判的是「直连第三方发行包/进程/HTTP/DB/grpc」，
  且**扫描面只有 `支持库/适配层/**`**（`第十四阶段门禁.py:375-446`），模块库/技能库根本不在面内；
- 唯一登记这件事的是人工文档 `开发文档/项目说明.md:864-870`（把它写成「两套模式」的常规做法）。

本检查器把「**同一层里调用腿只能有一条**」落成机器判据，并区分两层（判据不同、不混为一谈）：

- **模块库**：唯一合法腿 = `公共契约/能力契约/调用器.获取能力调用器().调用能力`。
  `def 设置HTTP连接器` 是历史第二腿（审计件 I-1 实测 12 个包），出现在**模块 `实现/**.py`** 即命中。
- **技能库**：唯一合法腿 = 受控执行注入的合成模块 `技能底座能力.调用底座能力`
  （`技能库/后端/技能库/说明/设计说明.md:77-94` 明文：「可调能力白名单（技能脚本唯一的底座能力
  调用腿）」）。技能脚本出现 `sqlite3.connect` / `http.client.HTTPConnection` /
  `urllib.request` / `subprocess.Popen` 等**直接触达底座资源**的调用即命中。
- **运行核心**：唯一合法腿 = 能力调用器或同层已有的能力腿样板。
  `sqlite3.connect` 直连例外（2026-09-19 首次落地，非确定结论）：按审计件 I-7 §「本类必须给出
  明确结论」的口径，只有「同层已有包走了能力腿、而本文件自建同类库」才判红 —— 判据是
  「同层同目的的能力腿样板存在」，样板从 `数据库连接支持库.SQLite数据库` 的能力调用点现场求。

## 判据（三条规则 + 一条样板存在性判据）

- **规则 运行核心自建库**：运行核心文件出现 `sqlite3.connect`，且**同层存在走能力的同类样板**
  （现场扫 `数据库连接支持库.SQLite数据库.{查询运行态,写入运行态}` 的调用点）→ 命中。
  样板不存在时**不判**（避免把「这一层还没收口完」误报成缺陷，也避免判据恒红）。
- **规则 模块库第二调用腿**：`模块库/**/实现/**.py` 出现 `def 设置HTTP连接器` → 命中。
- **规则 技能库直连底座资源**：技能脚本出现直连库/直连 HTTP/派生进程 → 命中。
- **规则 调用腿样板存在性**（判据自身的反向保护）：两条唯一腿的样板必须现场可见 ——
  `调用器.获取能力调用器` 与 `技能底座能力.调用底座能力` 的注入点都在，
  否则判红（判据失锚 = 门禁在空转，哲学 1.4）。

## 覆盖不了什么（如实声明）

- 判「有没有第二腿」，**不判「新腿在生产装配里真的会被注入」**（需运行时证据）；
- 技能库直连判据是**库/调用名**级，不是完整数据流级：改名绕过的写法（如自建一个叫别的名字的
  sqlite 包装）抓不到；
- 模块库判据只认 `def 设置HTTP连接器` 这一历史形态：改个名字的新腿抓不到
  （这类形态属「语义级判据」，本项目暂无）。
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

if __name__ == "__main__" or __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from 公共契约.基础类型.逻辑类型 import 假, 真  # noqa: E402
from 开发工具.验证门禁.门禁公共 import (  # noqa: E402
    新建夹具根,
    检查结论,
    命中,
)

检查器名 = "调用腿唯一性检测"

规则_模块库 = "模块库第二调用腿"
规则_模块库公开第二入口 = "模块库公开第二入口"
规则_技能库 = "技能库直连底座资源"
规则_技能库宿主 = "技能库宿主自建网关客户端"
规则_运行核心 = "运行核心自建库"
规则_样板 = "唯一腿样板存在性"

#: 模块库唯一合法腿的装配函数名（`公共契约/能力契约/调用器.py::获取能力调用器`）。
唯一腿调用器 = "获取能力调用器"
#: 模块库历史第二腿的注入函数名（审计件 I-1：12 个包）。
模块库第二腿名 = "设置HTTP连接器"

#: 技能库唯一合法腿的合成模块与入口（受控执行注入）。
技能唯一腿模块 = "技能底座能力"
技能唯一腿函数 = "调用底座能力"

#: 技能脚本的扫描面边界：只有 `技能库/**/scripts/**.py` 是「技能脚本」（受控执行沙箱里的被执行方），
#: 它才受「唯一底座能力调用腿」约束。
#:
#: 为什么必须划这条线（2026-09-19 实测假红）：
#: `技能库/后端/技能库/实现/技能库.py` 是**沙箱宿主本体**（它自己 `import subprocess`、
#: `subprocess.Popen` 起子进程、写网关合成模块）。它的职责就是「管住别人」，不是「被管」；
#: 把它算进技能脚本会得到一条永远红的假判据（哲学 1.4 空转即杀的反面：恒红即噪声）。
技能脚本目录名 = "scripts"

#: 显式跳过面：验证夹具目录里的脚本是**故意的反面样本**（如 `越权技能/scripts/读项目.py`
#: 刻意导入项目模块，用来验证沙箱在审计前就拦住）。跳过面必须可见，不得静默当通过。
技能夹具目录名 = "验证夹具"

#: 技能库直连底座资源的判据表：**属性调用链** → 说明。
#: 现场来源（审计件 I-4）：`技能库/技能/交付收尾/scripts/交付收尾.py:148` 的 `sqlite3.connect`。
技能直连调用链 = {
    "sqlite3.connect": "直连 SQLite 库（应经 平台控制面.能力目录.* 的租约能力）",
    "psycopg.connect": "直连 PostgreSQL 库",
    "http.client.HTTPConnection": "自建 HTTP 客户端（应经受控执行的 技能底座能力 注入）",
    "http.client.HTTPSConnection": "自建 HTTPS 客户端（应经受控执行的 技能底座能力 注入）",
    "urllib.request.urlopen": "自建 HTTP 请求（应经受控执行的 技能底座能力 注入）",
    "socket.socket": "自建套接字",
    "subprocess.Popen": "派生外部进程",
    "subprocess.run": "派生外部进程",
    "os.system": "派生外部进程",
}
技能直连模块 = ("sqlite3", "psycopg", "http.client", "urllib.request", "socket", "subprocess")

#: 运行核心自建库的判据：库连接调用链。
运行核心直连链 = {"sqlite3.connect": "自建 SQLite 幂等/运行态库（同层已有走能力的样板）"}
#: 「样板存在性」的现场探针：这两个能力 id 一旦在同层被调用，说明该层有走能力腿的同类样板。
样板能力痕迹 = ("数据库连接支持库.SQLite数据库.查询运行态", "数据库连接支持库.SQLite数据库.写入运行态")

#: 唯一腿锚点必须现场可见的两个位置（判据失锚即判红）。每种锚点一种检查形状：
#:
#: - `函数体`：目标必须是**真的顶层函数**，且语句数 ≥ `锚点函数体最少语句`。用于调用器
#:   （它是真函数，`def 获取能力调用器`）。
#: - `模板体`：技能库的唯一腿是**注入给子进程的合成模块源码**，它写在字符串模板里、
#:   靠 `组装合成模块源码` 落盘 —— 用顶层函数判据会误判（实测：模板里的 `def` 不是
#:   AST 函数节点）。故按「模板字符串内含该定义 + 有把它落盘的函数」判。
#:   形状：(相对路径, 检查形状, 目标名, 最少语句数)
样板锚点表: dict[str, tuple] = {
    唯一腿调用器: ("公共契约/能力契约/调用器.py", "函数体", 唯一腿调用器, 3),
    技能唯一腿函数: ("技能库/后端/技能库/实现/技能库.py", "模板体", 技能唯一腿函数, 1),
}
#: `模板体` 锚点还要求「把模板落盘的函数」存在：模板在、落盘函数没了 = 唯一腿不可达。
模板落盘函数 = "组装合成模块源码"


def _调用链(节点: ast.AST) -> str:
    """把 `a.b.c(...)` 折成 `a.b.c`；折不动返回空串。"""
    段: list[str] = []
    当前 = 节点
    while isinstance(当前, ast.Attribute):
        段.append(当前.attr)
        当前 = 当前.value
    if isinstance(当前, ast.Name):
        段.append(当前.id)
    return ".".join(reversed(段))


def _调用点(树: ast.AST) -> list[tuple[str, int]]:
    """收集全部调用链与行号。"""
    出: list[tuple[str, int]] = []
    for 节点 in ast.walk(树):
        if isinstance(节点, ast.Call):
            链 = _调用链(节点.func)
            if 链:
                出.append((链, 节点.lineno))
    return 出


def _导入名(树: ast.AST) -> list[tuple[str, int]]:
    出: list[tuple[str, int]] = []
    for 节点 in ast.walk(树):
        if isinstance(节点, ast.Import):
            出 += [(别名.name, 节点.lineno) for 别名 in 节点.names]
        elif isinstance(节点, ast.ImportFrom):
            出.append((节点.module or "", 节点.lineno))
    return 出


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


def _扫描样板锚点(根: Path, 结论: 检查结论) -> bool:
    """唯一腿样板必须现场可见且**不是壳**；否则判红（判据失锚 = 门禁空转）。

    形状判据见 `样板锚点表` 上方注释。为什么必须 AST 判「不是壳」：现场曾出现
    「锚点文件在、名字在、函数是 `return None` 壳」—— 那时判据指着的唯一腿并不存在。
    （字节数阈值不算：实测它会把合法的精简夹具误判成空转。）
    """
    def _去壳(函数: ast.AST) -> list:
        return [
            项
            for 项 in getattr(函数, "body", [])
            if not (isinstance(项, ast.Expr) and isinstance(项.value, ast.Constant))
        ]

    缺失: list[str] = []
    for 名字, (相对, 形状, 目标, 最少语句) in 样板锚点表.items():
        路径 = 根 / 相对
        if not 路径.is_file():
            缺失.append(f"锚点文件不存在 {相对}（{名字}）")
            continue
        文本 = 路径.read_text(encoding="utf-8")
        定义片段 = f"def {目标}("
        if 定义片段 not in 文本:
            缺失.append(f"{相对} 内找不到 {定义片段}（{名字} 锚点缺失）")
            continue
        try:
            树 = ast.parse(文本)
        except SyntaxError as 错误:
            缺失.append(f"{相对} 语法错误 行{错误.lineno}（{名字} 锚点不可解析）")
            continue
        if 形状 == "模板体":
            模板函数 = [
                节点
                for 节点 in ast.walk(树)
                if isinstance(节点, (ast.FunctionDef, ast.AsyncFunctionDef))
                and 节点.name == 模板落盘函数
            ]
            if not 模板函数 or sum(len(_去壳(函数)) for 函数 in 模板函数) < 最少语句:
                缺失.append(
                    f"{相对} 缺 {模板落盘函数}（模板里的 {目标} 落不了盘 = 唯一腿不可达）"
                )
            continue
        找到 = [
            节点
            for 节点 in ast.walk(树)
            if isinstance(节点, (ast.FunctionDef, ast.AsyncFunctionDef)) and 节点.name == 目标
        ]
        if not 找到:
            缺失.append(f"{相对} 内没有真的定义 {目标}（模板字符串里的定义不算，锚点是壳）")
            continue
        语句数 = sum(len(_去壳(节点)) for 节点 in 找到)
        if 语句数 < 最少语句:
            缺失.append(
                f"{相对} 的 {目标} 只有 {语句数} 条语句（< {最少语句}），锚点是壳"
            )
    if 缺失:
        结论.命中列表.append(命中(规则_样板, "N/A", 0, "；".join(缺失[:3])))
        return 假
    return 真


def _规则模块库第二调用腿(根: Path, 结论: 检查结论) -> None:
    模块根 = 根 / "模块库"
    if not 模块根.is_dir():
        结论.扫描面[规则_模块库] = 0
        return
    计数 = 0
    公开入口数 = 0
    for 源码 in sorted(模块根.rglob("*.py")):
        if "__pycache__" in 源码.parts:
            continue
        计数 += 1
        树 = _解析(源码, 结论, 根)
        if 树 is None:
            continue
        for 节点 in ast.walk(树):
            if (
                isinstance(节点, (ast.FunctionDef, ast.AsyncFunctionDef))
                and 节点.name == 模块库第二腿名
            ):
                结论.命中列表.append(
                    命中(规则_模块库, 源码.relative_to(根).as_posix(), 节点.lineno,
                        f"模块自建 {模块库第二腿名}（第二调用腿）；唯一合法腿 = "
                        f"{唯一腿调用器}().调用能力")
                )
        if 源码.name == "__init__.py":
            for 节点 in ast.walk(树):
                # 包级 re-export：`from 模块库.X.实现.X import 设置HTTP连接器`
                if isinstance(节点, ast.ImportFrom) and any(
                    别名.name == 模块库第二腿名 for 别名 in 节点.names
                ):
                    公开入口数 += 1
                    结论.命中列表.append(
                        命中(规则_模块库公开第二入口, 源码.relative_to(根).as_posix(),
                             节点.lineno,
                             f"包级 re-export {模块库第二腿名}（把实现内的第二腿抬成模块"
                             f"对外公开入口，审计件 I-6）")
                    )
                # `__all__` 条目：
                if (
                    isinstance(节点, ast.Assign)
                    and any(getattr(目标, "id", "") == "__all__" for 目标 in 节点.targets)
                    and isinstance(节点.value, (ast.List, ast.Tuple))
                ):
                    导出 = [
                        元素.value
                        for 元素 in 节点.value.elts
                        if isinstance(元素, ast.Constant)
                    ]
                    if 模块库第二腿名 in 导出:
                        公开入口数 += 1
                        结论.命中列表.append(
                            命中(规则_模块库公开第二入口, 源码.relative_to(根).as_posix(),
                                 节点.lineno,
                                 f"__all__ 含 {模块库第二腿名}（模块对外多出一条非能力 id 的"
                                 f"公开入口，审计件 I-6）")
                        )
    结论.扫描面[规则_模块库] = 计数
    结论.跳过面[f"{规则_模块库}：包级公开第二入口命中数（与实现内定义分开计）"] = 公开入口数


def _规则技能库直连(根: Path, 结论: 检查结论) -> None:
    技能根 = 根 / "技能库"
    if not 技能根.is_dir():
        结论.扫描面[规则_技能库] = 0
        return
    计数 = 0
    有腿技能数 = 0
    夹奇数 = 0
    导入痕迹数 = 0
    for 源码 in sorted(技能根.rglob("*.py")):
        if "__pycache__" in 源码.parts:
            continue
        # 扫描面边界：只有 `scripts/` 下的技能脚本受「唯一底座能力调用腿」约束。
        if 技能脚本目录名 not in 源码.parts:
            continue
        if 技能夹具目录名 in 源码.parts:
            夹奇数 += 1
            continue
        计数 += 1
        树 = _解析(源码, 结论, 根)
        if 树 is None:
            continue
        相对 = 源码.relative_to(根).as_posix()
        命中链 = [
            (链, 行号)
            for 链, 行号 in _调用点(树)
            if any(链 == 目标 or 链.endswith("." + 目标) or 链.startswith(目标) for 目标 in 技能直连调用链)
        ]
        # 判据只在**真的调用**时命中：`import sqlite3` 本身是标准库导入（沙箱放行），
        # 违规点是「拿它去连平台自己的库」。导入痕迹单独计数上报（可见，但不判红）。
        导入痕迹数 += sum(
            1
            for 模块名, _行号 in _导入名(树)
            if 模块名.split(".")[0] in {名.split(".")[0] for 名 in 技能直连模块}
        )
        if not 命中链:
            continue
        有腿技能数 += 1
        for 链, 行号 in 命中链:
            目标 = next(
                (键 for 键 in 技能直连调用链 if 链 == 键 or 链.endswith("." + 键) or 链.startswith(键)),
                "",
            )
            结论.命中列表.append(
                命中(规则_技能库, 相对, 行号,
                     f"{链} —— {技能直连调用链.get(目标, '直连底座资源')}；"
                     f"唯一合法腿 = {技能唯一腿模块}.{技能唯一腿函数}")
            )
    结论.扫描面[规则_技能库] = 计数
    结论.跳过面[f"{规则_技能库}：有直连调用的技能脚本数"] = 有腿技能数
    结论.跳过面[f"{规则_技能库}：跳过 验证夹具/ 下反面样本脚本数"] = 夹奇数
    结论.跳过面[f"{规则_技能库}：有直连资源模块导入痕迹（仅上报不判红）"] = 导入痕迹数


def _样板存在(根: Path, 结论: 检查结论) -> bool:
    """运行核心同层是否存在走能力腿的同类样板（决定规则「运行核心自建库」是否生效）。"""
    运行核心 = 根 / "运行核心"
    if not 运行核心.is_dir():
        return 假
    for 源码 in sorted(运行核心.rglob("*.py")):
        if "__pycache__" in 源码.parts:
            continue
        try:
            文本 = 源码.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if any(痕迹 in 文本 for 痕迹 in 样板能力痕迹):
            结论.跳过面["运行核心能力腿样板来源"] = 1
            return 真
    return 假


def _规则技能库宿主唯一(根: Path, 结论: 检查结论, 宿主相对: str) -> None:
    """技能库内「自建网关客户端」必须**唯一**：只允许宿主那一个文件建。

    为什么这是一条真判据（而不是重复判据一）：技能库的网关客户端是「唯一腿的产出方」，
    它在宿主里建一次就够。若别处又建一个（新写一个 `http.client.HTTPConnection` 之类的
    直连），那就是**第二条腿的入口**，而它不在 `scripts/` 下、判据一覆盖不到。
    现场实测：技能库内建网关客户端的文件恰好 1 个（宿主），判据守的是「不得新增第二个」。
    """
    技能根 = 根 / "技能库"
    if not 技能根.is_dir():
        结论.扫描面[规则_技能库宿主] = 0
        return
    建客户端: list[tuple[str, int]] = []
    计数 = 0
    for 源码 in sorted(技能根.rglob("*.py")):
        if "__pycache__" in 源码.parts:
            continue
        计数 += 1
        树 = _解析(源码, 结论, 根)
        if 树 is None:
            continue
        for 链, 行号 in _调用点(树):
            if 链 in ("http.client.HTTPConnection", "http.client.HTTPSConnection"):
                建客户端.append((源码.relative_to(根).as_posix(), 行号))
    结论.扫描面[规则_技能库宿主] = 计数
    结论.跳过面[f"{规则_技能库宿主}：建网关客户端的文件数"] = len({文件 for 文件, _ in 建客户端})
    for 文件, 行号 in 建客户端:
        if 文件 == 宿主相对:
            continue
        结论.命中列表.append(
            命中(规则_技能库宿主, 文件, 行号,
                 f"技能库内第二处自建网关客户端（唯一产出方应是 {宿主相对}）；"
                 f"第二处 = 第二条腿的入口")
        )


def _规则运行核心自建库(根: Path, 结论: 检查结论, 样板存在: bool) -> None:
    运行核心 = 根 / "运行核心"
    if not 运行核心.is_dir():
        结论.扫描面[规则_运行核心] = 0
        return
    计数 = 0
    建库点数 = 0
    for 源码 in sorted(运行核心.rglob("*.py")):
        if "__pycache__" in 源码.parts:
            continue
        计数 += 1
        树 = _解析(源码, 结论, 根)
        if 树 is None:
            continue
        for 链, 行号 in _调用点(树):
            if 链 not in 运行核心直连链:
                continue
            建库点数 += 1
            if not 样板存在:
                continue
            结论.命中列表.append(
                命中(规则_运行核心, 源码.relative_to(根).as_posix(), 行号,
                     f"{链} —— {运行核心直连链[链]}；同层样板 = "
                     f"{'、'.join(样板能力痕迹)}（走能力腿）")
            )
    结论.扫描面[规则_运行核心] = 计数
    结论.跳过面[f"{规则_运行核心}：建库点总数"] = 建库点数
    if not 样板存在:
        结论.跳过面[f"{规则_运行核心}：同层能力腿样板不存在 → 本规则本次不生效"] = 1


#: 技能库唯一腿的**产出方**（宿主）：技能库内只允许它建网关客户端。
技能库宿主相对 = "技能库/后端/技能库/实现/技能库.py"


def 构建结论(根: Path) -> 检查结论:
    结论 = 检查结论(名称=检查器名)
    锚点齐 = _扫描样板锚点(根, 结论)
    结论.扫描面[规则_样板] = len(样板锚点表) if 锚点齐 else 1
    _规则模块库第二调用腿(根, 结论)
    _规则技能库直连(根, 结论)
    _规则技能库宿主唯一(根, 结论, 技能库宿主相对)
    _规则运行核心自建库(根, 结论, _样板存在(根, 结论))
    return 结论


# ────────────────────────── 反向验证（变异样本必红）──────────────────────────
#: 每条判据对应一份「故意违规」样本：路径 → 内容。
变异样本表: tuple[tuple[str, str, str], ...] = (
    ("规则 模块库第二调用腿",
     "模块库/夹具包/实现/夹具包.py",
     "def 设置HTTP连接器(连接器):\n    return 连接器\n"),
    ("规则 技能库直连底座资源",
     "技能库/技能/夹具技能/scripts/夹具脚本.py",
     "import sqlite3\n\n\n连接 = sqlite3.connect('夹具.db')\n"),
    ("规则 运行核心自建库",
     "运行核心/夹具核心.py",
     "import sqlite3\n\n\n连接 = sqlite3.connect('夹具.sqlite3')\n"),
    ("规则 模块库公开第二入口（包级 re-export + __all__）",
     "模块库/夹具公开包/__init__.py",
     "from 模块库.夹具公开包.实现.夹具公开包 import 夹具动作, 设置HTTP连接器\n\n"
     '__all__ = ["夹具动作", "设置HTTP连接器"]\n'),
    ("规则 技能库宿主自建网关客户端（第二处）",
     "技能库/技能/夹具技能四/scripts/夹具脚本四.py",
     "import http.client\n\n\n连接 = http.client.HTTPConnection('127.0.0.1', 40007)\n"),
)

#: 拍一用的「合法样本」：全是唯一腿写法，必须一条都不报。
合法样本表: tuple[tuple[str, str], ...] = (
    ("模块库/夹具基准包/实现/夹具基准包.py",
     "def 夹具动作(输入):\n"
     "    from 公共契约.能力契约.调用器 import 获取能力调用器\n"
     "    return 获取能力调用器().调用能力('夹具.能力', {'输入': 输入})\n"),
    ("模块库/夹具基准包/__init__.py", "__all__ = ['夹具动作', '注册能力']\n"),
    ("技能库/技能/夹具基准技能/scripts/夹具基准脚本.py",
     "from 技能底座能力 import 调用底座能力\n\n\n结果 = 调用底座能力('测试支持库.验证结果判定', {})\n"),
)

#: 拍一的样板锚点：唯一腿锚点必须在夹具根里现场可见，否则判据失锚会判红。
锚点样本表: tuple[tuple[str, str], ...] = (
    ("公共契约/能力契约/调用器.py",
     "def 获取能力调用器(项目根=None):\n"
     "    \"\"\"夹具锚点：唯一能力调用器的装配入口（真实锚点见 公共契约/能力契约/调用器.py）。\"\"\"\n"
     "    调用器 = 夹具注册表.get('当前')\n"
     "    if 调用器 is None:\n"
     "        raise RuntimeError('未装配')\n"
     "    return 调用器\n"),
    ("技能库/后端/技能库/实现/技能库.py",
     "合成模块名 = '技能底座能力'\n\n\n"
     "合成模块模板 = '''\"\"\"技能底座能力：平台为本次受控执行注入的唯一底座能力调用腿。\"\"\"\n\n"
     "def 调用底座能力(能力id, 参数=None, 超时秒=None):\n"
     "    return {}\n'''\n"
     "\n"
     "\n"
     "def 组装合成模块源码(白名单, 网关地址, 凭证变量名):\n"
     "    源码 = 合成模块模板.replace('__注入白名单__', repr(list(白名单)))\n"
     "    源码 = 源码.replace('__注入网关地址__', 网关地址)\n"
     "    return 源码.replace('__注入凭证变量名__', 凭证变量名)\n"),
    ("运行核心/夹具样板模块.py",
     "from 公共契约.能力契约.调用器 import 获取能力调用器\n\n\n"
     "def 夹具写运行态(库, 键, 值):\n"
     "    获取能力调用器().调用能力('数据库连接支持库.SQLite数据库.写入运行态', {})\n"),
)


def _自证() -> int:
    """三拍自证：① 合法夹具根（唯一腿写法）→ 绿；② 注入违规样本 → 必红；③ 撤除 → 回绿。"""
    import shutil
    import subprocess

    根 = 新建夹具根("验证门禁二_自证_")
    基线 = 根 / "基线.json"
    结果: list[tuple[str, str]] = []
    for 相对, 内容 in 锚点样本表 + 合法样本表:
        路径 = 根 / 相对
        路径.parent.mkdir(parents=True, exist_ok=True)
        路径.write_text(内容, encoding="utf-8")
    (根 / "基线.json").write_text(
        '{"检查器": {"调用腿唯一性检测": {}}}', encoding="utf-8"
    )

    def _跑() -> int:
        return subprocess.run(
            [sys.executable, str(Path(__file__)), "--根", str(根), "--基线", str(基线)],
            capture_output=True, text=True, timeout=240,
        ).returncode

    第一拍 = _跑()
    结果.append((f"第一拍 合法夹具根 {根}", f"退出码 {第一拍}（期望 0=绿）"))
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
    shutil.rmtree(根, ignore_errors=True)
    return 0


def main(argv: list[str] | None = None) -> int:
    实参 = list(sys.argv[1:] if argv is None else argv)
    if "--自证" in 实参:
        return _自证()
    from 开发工具.验证门禁.门禁公共 import 跑标准主流程

    return 跑标准主流程(检查器名, 构建结论, 实参)


if __name__ == "__main__":
    sys.exit(main())
