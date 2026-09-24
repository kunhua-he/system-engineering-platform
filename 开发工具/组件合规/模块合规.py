"""模块合规验证：权威 13 项组件合规 + 模块专属边界审计。

MCP 校验模块合规 = 开发工具/组件合规/合规测试包.py（13 项强制场景，唯一权威）
+ 模块专属边界审计（AST）：支持库/提供者物理导入、实现目录导入、第三方导入、
运行核心实现导入、直接I/O、tempfile、subprocess、socket、数据库客户端、
格式解析原子实现、动态import 绕过；标准库按行为调用图判断（非无条件白名单）。
支持库.适配层.<提供者> 公开入口层为过渡期模块组成边界（收口后模块一律经
获取能力调用器().调用能力，物理导入归零）。

**同包 `实现/` 口径对齐（2026-09-16 E-f 修复）**：本文件原先**没有**同包判定，
凡是 `模块库.<自己>.**.实现.**` 一律落到「白名单外导入」——同一条 import 在
`运行核心/依赖防火墙.py` 与 `开发工具/复用审计/能力调用图审计.py` 里放行，在这里报红
（实测 `_分类导入('模块库.能力目录.实现.能力索引')` → `{'类别': '白名单外导入'}`）。
现在一律调权威函数 `运行核心/依赖防火墙.py::同包实现导入`；跨包 `实现/` 直连
（`模块库.包A` 导 `模块库.包B.实现`）照旧阻断，只是缺口类型从「白名单外导入」
纠正为「实现目录导入」（与防火墙同一结论、同一个词）。
审计作用域**不动**（仍是 `实现/**`）：扩到包级 `__init__.py` 会把
`from 实现.实现 import X` 这类短名入口判红，而 `组件合规._加载入口` 正是按短名
约定加载样本 —— 那会造出「同一份包在组件合规 13/13、在这里报违规」的新分歧。

统一结果结构：{"成功": bool, "错误码": str, "违规列表": [...]}；
错误码：模块不存在 / 权威违规 / 导入违规 / 边界违规。
"""

from __future__ import annotations

import ast
import json
import sys
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterator

系统根 = next(祖先 for 祖先 in Path(__file__).resolve().parents
             if (祖先 / "模块库").is_dir() and (祖先 / "测试中心").is_dir())
if str(系统根) not in sys.path:
    sys.path.insert(0, str(系统根))

# 同包 `实现/` 判定**不本地复刻**：依赖防火墙/能力调用图审计/本文件三处审计共用
# 同一个权威函数（E-f）。各自实现就是「同一行代码两个结论」的根因。
# 依赖方向核对：允许依赖表["开发工具"] 含 "运行核心"，反向无引用。
from 运行核心.依赖防火墙 import 同包实现导入  # noqa: E402 —— 须在 系统根 入 sys.path 之后
#: 第三方根模块表**不在本文件维护**（2026-09-24 批O·O-10 收口）：唯一真源 =
#: `开发文档/项目证据/第三方导入分布基线.json` 的 `分布` 键集，经其属主
#: `开发工具/第三方导入分布基线门禁.py` 读出（见 `第三方根模块集`）。
#:
#: 【为什么要收这一口（原实现的两个实测缺陷）】原表是一张 29 名的硬编码清单，
#: 与本仓**实测分布双向脱节**：
#:   · 表里 18 名与实测分布无关，其中 `sqlalchemy`/`cv2`/`matplotlib`/`pydub`/
#:     `moviepy`/`selenium`/`chardet` 在全仓 `.py` 里**零 import**（死条目）；
#:   · 分布里 11 名**真被 import**（`fastapi`/`mcp`/`uvicorn`/`psutil`/`networkx`/
#:     `transformers`/`tree_sitter` 等）却不在表里 ⇒ 真第三方 import 被归到
#:     「白名单外导入」而非「第三方导入」**错标**（两类别同在 `导入违规类别`，
#:     故判定同为违规，错的是类别名与可读性）。
#: 同一件事两份清单正是哲学 1.3 要收的口子 ⇒ 一律转调单一真源。
#: 标准库/仓内顶层目录/仓内模块名三条排除口径**照样由该门禁承担**，本文件不复刻。
数据库客户端根 = {"sqlite3", "pymongo", "mysql", "redis"}
核心根目录名 = {"运行核心", "前端核心", "后端核心"}
支持库内部目录段 = {"实现", "能力契约", "说明", "完整性摘要", "验证场景引用",
                "包声明", "默认配置", "能力数据", "__pycache__"}
实现目录段 = "实现"
标准库根模块 = frozenset(getattr(sys, "stdlib_module_names", set())) | {
    "__future__", "abc", "enum", "functools", "itertools", "operator",
}

# 标准库按行为调用图判断：仅调用下列函数/方法时违规（import 本身不算白名单）。
行为调用表 = {
    "tempfile": {"mkdtemp", "mkstemp", "NamedTemporaryFile", "TemporaryDirectory",
                 "gettempdir", "mktemp", "TemporaryFile"},
    "subprocess": {"run", "Popen", "call", "check_call", "check_output",
                   "getoutput", "getstatusoutput"},
    "os": {"system", "popen", "remove", "unlink", "makedirs", "mkdir", "rmdir",
           "rename", "replace", "open", "read", "write"},
    "shutil": {"copy", "copyfile", "move", "rmtree", "copytree", "unpack_archive"},
    "pathlib": {"read_text", "read_bytes", "write_text", "write_bytes", "open",
                "unlink", "mkdir", "rmdir", "rename", "replace", "touch"},
    "socket": {"socket", "create_connection", "create_server", "bind", "connect",
               "listen", "accept", "send", "sendall", "recv"},
    "json": {"loads", "dumps", "load", "dump"},
    "csv": {"reader", "writer", "DictReader", "DictWriter"},
    "xml": {"parse", "fromstring", "tostring", "ElementTree"},
    "yaml": {"safe_load", "load", "safe_dump", "dump"},
}
行为类别表 = {
    "tempfile": "临时目录操作", "subprocess": "进程调用", "os": "直接I/O",
    "shutil": "直接I/O", "pathlib": "直接I/O", "socket": "网络套接字",
    "json": "格式解析原子操作", "csv": "格式解析原子操作",
    "xml": "格式解析原子操作", "yaml": "格式解析原子操作",
}
动态导入调用 = {"import_module", "__import__", "exec", "eval"}
导入违规类别 = {"支持库导入", "实现目录导入", "第三方导入", "运行核心导入",
              "数据库客户端", "相对导入", "白名单外导入"}


@lru_cache(maxsize=1)
def 第三方根模块集() -> frozenset[str]:
    """第三方根模块集合：**单腿供数**，真源 = `第三方导入分布基线.json`。

    为什么这么取（而不是在本文件维护一份清单）：同一件事两份清单必然脱节——
    实测原 29 名清单与本仓真被 import 的 22 名分布之间 18/11 互不在对方表里，
    于是「真第三方」被错标成「白名单外导入」。本函数一律转调该基线的**属主**
    （`开发工具/第三方导入分布基线门禁.py::读取基线`），形状校验与 fail-closed
    口径都由属主承担，本文件不另写第二套解析。

    **取不到即返回空集**（不抛）：本函数只决定「这条 import 该叫什么类别」，
    不承担门禁职责；拿不到真源时退回旧行为（第三方落「白名单外导入」）——
    两类别同在 `导入违规类别` ⇒ **违规判定不变**，只是类别名不够精确。
    真源缺失这件事本身由 `第三方导入分布基线门禁` 判红，不在这里重复报。

    性能：命中一次即缓存（`lru_cache`）。基线是**构建期常量**（其变更走 `--冻结`
    重建并进提交），单次进程内读完即定，不引入跨进程缓存失效问题。
    """
    from 开发工具.第三方导入分布基线门禁 import 默认基线路径, 读取基线

    分布, 问题 = 读取基线(默认基线路径())
    if 问题 or not 分布:
        return frozenset()
    return frozenset(分布)


def _结果(违规列表: list[dict[str, Any]], 错误码: str = "") -> dict[str, Any]:
    """统一结果结构：成功/错误码/违规列表。"""
    return {"成功": not 违规列表, "错误码": 错误码, "违规列表": 违规列表}


def _定位模块目录(项目根: Path, 模块名: str) -> Path | None:
    """定位 模块库/<模块名> 目录；兼容 模块库. 前缀。"""
    模块名 = 模块名.strip().removeprefix("模块库.").strip("/")
    if not 模块名 or 模块名 in ("", "."):
        return None
    模块目录 = 项目根 / "模块库" / 模块名
    if not 模块目录.is_dir():
        return None
    return 模块目录


def _解析导入(源码路径: Path) -> Iterator[dict[str, Any]]:
    """AST 解析单个实现文件的 import 语句，产出 行/模块。"""
    try:
        树 = ast.parse(源码路径.read_text(encoding="utf-8"))
    except (OSError, SyntaxError, UnicodeDecodeError):
        return
    for 节点 in ast.walk(树):
        if isinstance(节点, ast.Import):
            for 别名 in 节点.names:
                yield {"行": 节点.lineno, "模块": str(别名.name)}
        elif isinstance(节点, ast.ImportFrom):
            if 节点.level:
                yield {"行": 节点.lineno, "模块": "." * 节点.level + (节点.module or "")}
            elif 节点.module:
                yield {"行": 节点.lineno, "模块": str(节点.module)}


def _分类导入(导入模块: str, 文件相对: str | Path | None = None) -> dict[str, str] | None:
    """导入分类：放行 标准库/公共契约/支持库.适配层.<提供者> 公开入口层/同包 `实现/`。

    检出：支持库导入（后端/前端/第三方/内部目录/根）、实现目录导入、
    数据库客户端、第三方导入、运行核心导入、相对导入、白名单外导入。

    `文件相对` 是**相对项目根**的实现文件路径；同包 `实现/` 判定需要它，缺它
    （直接函数探针调用）时按**跨包实现导入**报红 —— fail-closed，不猜。
    """
    模块 = 导入模块.strip()
    if not 模块:
        return None
    根 = 模块.split(".")[0]
    if 根 in 数据库客户端根:
        return {"类别": "数据库客户端"}
    if 根 in 标准库根模块 or 模块.startswith("__future__"):
        return None
    if 模块 == "公共契约" or 模块.startswith("公共契约."):
        return None
    if 根 == "支持库":
        路径段 = 模块.split(".")
        if any(段 in 支持库内部目录段 for 段 in 路径段[1:]):
            return {"类别": "实现目录导入"}
        if len(路径段) in (2, 3) and 路径段[1] == "适配层":
            return None
        return {"类别": "支持库导入"}
    if 根 == "模块库":
        # 模块库内导 `实现/`：**同包**（路径段逐段相等）才放行，判据与依赖防火墙/
        # 能力调用图审计共用同一个权威函数（E-f）。
        if "实现" in 模块.split(".")[1:]:
            if 文件相对 is not None and 同包实现导入(文件相对, 模块):
                return None
            return {"类别": "实现目录导入"}
        return {"类别": "白名单外导入"}
    if 根 == 实现目录段:
        # `from 实现.X import Y`：不带包名的短名，只有把包目录塞进 sys.path 才成立
        # （`组件合规._加载入口` 正是这么加载样本的）。**同目录才放行** —— 判据是
        # 「本文件所在目录恰好是这个短名的目录」，不是「短名一律免检」，
        # 所以 `工具/` 里写 `from 实现.实现 import …` 照旧判红。
        if 文件相对 is not None:
            目录段 = Path(文件相对).with_suffix("").parts[:-1]
            if 目录段 and 目录段[-1] == 实现目录段:
                return None
        return {"类别": "实现目录导入"}
    if 根 in 核心根目录名:
        return {"类别": "运行核心导入"}
    if 根 in 第三方根模块集():
        return {"类别": "第三方导入"}
    if 模块.startswith("."):
        return {"类别": "相对导入"}
    return {"类别": "白名单外导入"}


def _解析别名(树: ast.AST) -> dict[str, str]:
    """import/from-import 别名表：名称 → 完整模块路径。"""
    别名表: dict[str, str] = {}
    for 节点 in ast.walk(树):
        if isinstance(节点, ast.Import):
            for 别名 in 节点.names:
                别名表[别名.asname or 别名.name.split(".")[0]] = 别名.name
        elif isinstance(节点, ast.ImportFrom):
            for 别名 in 节点.names:
                if 别名.name != "*":
                    别名表[别名.asname or 别名.name] = (
                        f"{节点.module}.{别名.name}" if 节点.module else 别名.name)
    return 别名表


def _根名称(节点) -> str:
    """取属性链/调用链最深层名称：tempfile.mkdtemp() → tempfile。"""
    while isinstance(节点, (ast.Attribute, ast.Call)):
        节点 = 节点.value if isinstance(节点, ast.Attribute) else 节点.func
    return 节点.id if isinstance(节点, ast.Name) else ""


def _审计行为(源码路径: Path) -> list[dict[str, Any]]:
    """标准库行为调用图审计：别名解析后按 模块路径+调用名 匹配违规行为。"""
    违规列表: list[dict[str, Any]] = []
    try:
        树 = ast.parse(源码路径.read_text(encoding="utf-8"))
    except (OSError, SyntaxError, UnicodeDecodeError):
        return 违规列表
    别名表 = _解析别名(树)
    for 节点 in ast.walk(树):
        if not isinstance(节点, ast.Call):
            continue
        if isinstance(节点.func, ast.Name):
            名称 = 节点.func.id
            if 名称 in {"open"}:
                违规列表.append({"行": 节点.lineno, "类别": "直接I/O", "调用": "open"})
            elif 名称 in 动态导入调用:
                违规列表.append({"行": 节点.lineno, "类别": "动态导入绕过", "调用": 名称})
            elif 名称 in 别名表:
                全名 = 别名表[名称]
                模块根 = 全名.split(".")[0]
                if 模块根 in 行为调用表 and 全名.rsplit(".", 1)[-1] in 行为调用表[模块根]:
                    违规列表.append({"行": 节点.lineno, "类别": 行为类别表[模块根], "调用": 全名})
                elif 全名 in {"importlib.import_module", "builtins.__import__"}:
                    违规列表.append({"行": 节点.lineno, "类别": "动态导入绕过", "调用": 全名})
        elif isinstance(节点.func, ast.Attribute):
            调用名 = 节点.func.attr
            if 调用名 in 动态导入调用:
                违规列表.append({"行": 节点.lineno, "类别": "动态导入绕过", "调用": 调用名})
                continue
            根 = _根名称(节点.func)
            模块路径 = 别名表.get(根, "")
            模块根 = 模块路径.split(".")[0]
            if 模块根 in 行为调用表 and 调用名 in 行为调用表[模块根]:
                违规列表.append({"行": 节点.lineno, "类别": 行为类别表[模块根],
                                  "调用": f"{模块路径}.{调用名}"})
    return 违规列表


def 审计模块边界(项目根: Path, 模块名: str) -> dict[str, Any]:
    """模块专属边界审计：AST 检查 实现/*.py 的导入分类与标准库行为调用图。

    违规项：{"文件", "行", "模块"|"调用", "类别"}；错误码 导入违规/
    边界违规。
    """
    模块目录 = _定位模块目录(项目根, 模块名)
    if 模块目录 is None:
        return _结果([{"文件": "模块库/" + 模块名.strip("模块库.").strip("/"),
                       "行": 0, "模块": 模块名, "类别": "模块不存在"}],
                      "模块不存在")
    违规列表: list[dict[str, Any]] = []
    实现目录 = 模块目录 / "实现"
    # 审计作用域**保持** `实现/**`：对齐到包级 `__init__.py` 看似与防火墙一致，
    # 实测却会把 `from 实现.实现 import X` 这类「只有把包目录塞进 sys.path 才成立」
    # 的短名入口判成「白名单外导入」，而 `组件合规` 的 `_加载入口` 正是按这个约定
    # 加载样本的 → 同一份包在组件合规里 13/13、在这里报违规（E-f 修的是「同一条
    # import 两个结论」，不是「把作用域扩大一圈制造新分歧」）。要扩作用域必须同批
    # 改 `_加载入口` 与 `_分类导入` 的短名放行规则，不属本轮。
    if 实现目录.is_dir():
        # 实现目录下的子目录同样属于模块边界，必须递归审计，避免通过
        # 子目录放置实现文件绕过导入和直接 I/O 检查。
        待审源码 = sorted(实现目录.rglob("*.py"))
    else:
        待审源码 = []
    for 源码路径 in 待审源码:
        相对路径 = 源码路径.relative_to(项目根).as_posix()
        for 导入 in _解析导入(源码路径):
            分类 = _分类导入(导入["模块"], 相对路径)
            if 分类 is None:
                continue
            违规列表.append({"文件": 相对路径, "行": int(导入["行"]),
                              "模块": 导入["模块"], "类别": 分类["类别"]})
        for 行为违规 in _审计行为(源码路径):
            违规列表.append({"文件": 相对路径, **行为违规})
    if not 违规列表:
        return _结果([])
    类别表 = {违规["类别"] for 违规 in 违规列表}
    错误码 = "导入违规" if 类别表 & 导入违规类别 else "边界违规"
    return _结果(违规列表, 错误码)


def _权威合规违规(项目根: Path, 模块名: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """调用权威 13 项组件合规验证器（合规测试包.py），产出违规项与报告摘要。"""
    from 开发工具.组件合规.合规测试包 import 组件合规
    模块目录 = _定位模块目录(项目根, 模块名)
    报告 = 组件合规(模块目录).执行()
    违规列表 = [{"文件": f"模块库/{模块名}", "行": 0, "模块": 模块名,
                "类别": "权威合规", "场景": 名称, "说明": 详情}
               for 名称, 通过, 详情 in 报告.场景结果表 if not 通过]
    摘要 = {"通过数": 报告.通过数, "场景数": len(报告.场景结果表), "成功": 报告.成功}
    return 违规列表, 摘要


def 校验模块合规(项目根: Path, 模块名: str) -> dict[str, Any]:
    """统一入口：权威 13 项合规 + 模块专属边界审计，两类违规合并判定。"""
    模块目录 = _定位模块目录(项目根, 模块名)
    if 模块目录 is None:
        return _结果([{"文件": "模块库/" + 模块名.strip("模块库.").strip("/"),
                       "行": 0, "模块": 模块名, "类别": "模块不存在"}],
                      "模块不存在")
    权威违规, 权威摘要 = _权威合规违规(项目根, 模块名)
    边界结果 = 审计模块边界(项目根, 模块名)
    违规列表 = 权威违规 + 边界结果.get("违规列表", [])
    结果 = _结果(违规列表)
    结果["权威合规"] = 权威摘要
    if 违规列表:
        结果["错误码"] = "权威违规" if 权威违规 else 边界结果["错误码"]
    return 结果
