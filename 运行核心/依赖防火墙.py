"""依赖防火墙：统一 AST 依赖审计（进入发布门禁）。

**层向口径的唯一来源就是本文件的 `允许依赖表`（层 → 可依赖的目标层集合）与
`文件级豁免表`（层 + 文件相对路径 → 该文件额外可依赖的目标层）**：其余审计
（`开发工具/复用审计/能力调用图审计.py`、`开发工具/组件合规/模块合规.py`）
一律复用本文件的 `同包实现导入`，不许各自实现 —— 依据 `开发文档/未完成事项.md`
「分层审计的唯一口径」一节的华哥裁决：同一个写法只允许一把尺子，否则每加一个
包都会有人被莫名判红、又有人被放过。

允许方向镜像（**机器可校验的头注释镜像块**，与 `允许依赖表` 逐项同源；由
`检查头注释与表同源()` 解析比对，改表不改正本块即报差异）：

允许方向镜像（JSON，机器可校验）：
{
  "公共契约": [],
  "支持库": ["公共契约"],
  "模块库": ["公共契约", "支持库"],
  "技能库": ["公共契约"],
  "前端核心": ["公共契约", "运行核心"],
  "后端核心": ["公共契约", "运行核心"],
  "运行核心": ["公共契约", "支持库"],
  "平台控制面": ["公共契约", "支持库", "运行核心"],
  "项目适配层": ["公共契约", "运行核心"],
  "开发工具": ["公共契约", "支持库", "模块库", "运行核心", "后端核心", "前端核心", "项目适配层"],
  "其他": ["支持库", "模块库", "技能库", "前端核心", "后端核心", "运行核心", "平台控制面", "项目适配层", "开发工具"]
}

强制拒绝（这些是代码硬判据，不随上面两张表变动）：
导入任何 实现/ 目录（同包 `__init__` 导自身实现是合法入口模式，判据见 `同包实现导入`）；
支持库反向导入核心/模块/项目；模块导入第三方库或支持库内部文件；核心硬编码具体模块；
使用物理目录作为能力身份；动态导入绕过依赖审计；
非白名单层直连第三方发行包（唯一例外：`服务宿主SDK白名单` 里的服务宿主 + 其宿主 SDK）。

历史节点（已删层不留现役口径）：原 `MCP工具箱` 服务宿主层已于 2026-09-15 随 D 清场
整目录删除；接入面薄壳现居 `开发工具/薄壳/`，它的第三方宿主 SDK（mcp/starlette/uvicorn）
由 `服务宿主SDK白名单` 挂在 `开发工具` 层显式放行，不走「一第三方一支持库一提供者」口径。
"""

from __future__ import annotations

import ast
import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

系统根 = Path(__file__).resolve()
for _祖先 in 系统根.parents:
    if (_祖先 / "平台控制面").is_dir() and (_祖先 / "测试中心").is_dir():
        系统根 = _祖先
        break

层名称表 = {
    "公共契约": "公共契约",
    "支持库": "支持库",
    "模块库": "模块库",
    "技能库": "技能库",
    "前端核心": "前端核心",
    "后端核心": "后端核心",
    "运行核心": "运行核心",
    # 正式根之一（2026-09-15 起纳入装配，见 公共契约/正式根.py 与决策记录 0012）：
    # 平台治理类能力面（发布门禁/发布证据/指针/回滚/租约/作业反馈）补在这一层。
    "平台控制面": "平台控制面",
    "项目适配层": "项目适配层",
    "开发工具": "开发工具",
    # 平台自身的 MCP 服务宿主（薄壳）**已随 D 清场迁入 `开发工具/薄壳/`**：
    # 原 `MCP工具箱` 整目录已删除，本层注册同步移除；服务宿主 SDK 白名单随之
    # 改挂在 `开发工具` 上（见 `服务宿主SDK白名单`），不再需要独立层。
    "其他": "其他",
}

允许依赖表: dict[str, set[str]] = {
    "公共契约": set(),
    "支持库": {"公共契约"},
    # 支持库仅限包级公开入口（实现/ 已被强制拒绝）；也是 E-h 的**预留授权**：
    # 实测 模块库/** 对 支持库 静态导入 0 处（见 预留授权表），现役零引用。
    "模块库": {"公共契约", "支持库"},
    "技能库": {"公共契约"},  # 第三根正式包根：与 支持库 同口径，暂不放行 支持库 原子能力
    # 前端核心 → 运行核心 是 E-b 的**预留授权**：实测 前端核心/ 3 个 py 对其他层 import 0 处
    # （它只定义窗口/渲染契约 + 经统一能力调用器调后端能力），保留给「前端渲染/流式投递
    # 经 运行核心 网关」这条既定分工，见 预留授权表。
    "前端核心": {"公共契约", "运行核心"},
    "后端核心": {"公共契约", "运行核心"},
    "运行核心": {"公共契约", "支持库"},
    # 现场实测（2026-09-15）：平台控制面 的层间导入只落在 公共契约(4)/支持库(5)/运行核心(4)
    # 三处，按最小授权登记；不开放任意层导入。
    "平台控制面": {"公共契约", "支持库", "运行核心"},
    "项目适配层": {"公共契约", "运行核心"},
    # 开发工具 层实测导入落点（2026-09-16 全仓 AST 审计）：公共契约/支持库/模块库/运行核心/
    # 后端核心/前端核心/项目适配层 七处；`平台控制面` 刻意不在本集合 —— 发布门禁 → 平台控制面
    # 的处置走的是「补能力面」（`开发文档/未完成事项.md` 待裁决第 6 项确认口径），
    # 不是把整层开放。第三方宿主 SDK 见 `服务宿主SDK白名单`。
    "开发工具": {"公共契约", "支持库", "模块库", "运行核心", "后端核心", "前端核心", "项目适配层"},
    # 「其他」= 客户端/运维脚本/根下平铺文件等**不属于任何正式层**的平台外消费方与运维壳
    # （实测落点：`客户端/构建平台客户端.py`、`运维脚本/热接入.py`）。它们只做外部消费与运维、
    # 不被任何层依赖，故可依赖任意层；但**不自动继承**：新增层若要一并对它开放，必须同批写进
    # 本集合与头注释镜像块（fail-closed —— 漏写只会变红，不会悄悄放行）。
    "其他": {"支持库", "模块库", "技能库", "前端核心", "后端核心", "运行核心",
             "平台控制面", "项目适配层", "开发工具"},
}

# 文件级豁免表：`允许依赖表` 的**文件限定**补充（层 → {相对路径: 该文件额外可依赖的目标层}）。
# 为什么要有这张表：有些**启动编排边界**只该放行一个文件，不能把整层开放给另一个层。
# 唯一成员是网关启动脚本：它负责拉起后端核心（网关进程的装配点），但运行核心层里其余文件
# 都不许 import 后端核心 —— 所以 `允许依赖表["运行核心"]` **刻意不含** 后端核心，
# 整层放行会把「启动编排」这条边推广成普遍依赖。
# 原先这条豁免是审计函数体里的内联 if；搬到表里之后，豁免是**可列举、可审计的数据**，
# 改豁免不再需要改判定代码（E-a）。
文件级豁免表: dict[str, dict[str, frozenset[str]]] = {
    "运行核心": {
        "运行核心/启动运行核心网关.py": frozenset({"后端核心"}),
    },
}

# 预留授权表：(来源层, 目标层) → 理由。只登记 `允许依赖表` 里**已备案但当前零实际使用**的授权。
# 为什么要单独登记：空转授权在层表里看不出来，时间一长没人知道它是「真在用」还是
# 「当初备案、后来没用上」。登记后由 `检查预留授权()` 两头兜底：
#   ① 预留项必须仍在 `允许依赖表` 里被登记（表改了就报「预留失效」）；
#   ② 预留项一旦被真实使用，必须**转正**（去掉「预留」标注，并按真实用法核对授权范围）。
# 两者任一不成立即返回问题清单 → 由 `检查依赖口径()` 聚合，`测试中心/开发工具/测试_依赖防火墙口径.py` 变红。
预留授权表: dict[tuple[str, str], str] = {
    ("前端核心", "运行核心"): (
        "预留：前端核心 只定义窗口/页面/组件/状态/路由契约，经统一能力调用器调后端能力，"
        "文件里对 运行核心 的静态导入实测 0 处；保留给「前端渲染与流式投递经 运行核心 网关」"
        "这条既定分工，坐实前不得当成现役依赖。"),
    ("模块库", "支持库"): (
        "预留：模块一律经 获取能力调用器().调用能力，实测 模块库/** 对 支持库 静态导入 0 处；"
        "本授权只是过渡期容忍「模块组合走 支持库.适配层.<提供者> 公开入口」这一条，"
        "而且更严的第二腿在 `开发工具/复用审计/能力调用图审计.py::越界前缀表`（任何 支持库 "
        "静态导入判「支持库直连」），即本授权并非常态用法。"),
}

核心层表 = {"前端核心", "后端核心", "运行核心"}
第三方前缀表 = {
    "cryptography", "docx", "fitz", "openpyxl", "pdfplumber", "pg8000",
    "pptx", "psycopg", "psycopg2", "reportlab", "lxml", "pypdf", "PyPDF2",
    "numpy", "pandas", "PIL", "requests", "bs4", "yaml",
    # 存量表外第三方发行包（与 sys.stdlib_module_names 无冲突；补表后暴露存量违规）
    "mcp", "starlette", "uvicorn", "fastapi", "transformers", "torch",
    "psutil", "mlx_whisper", "tree_sitter", "tree_sitter_typescript",
}

# 第三方导入的**显式豁免白名单**：层 -> 该层允许直接导入的第三方包前缀集合。
# 与 `允许依赖表` 是两张不同语义的表，必须分开看：
#   * `允许依赖表` 管**层与层**之间的方向（谁能 import 哪个底座层）；
#   * 本表管**层与第三方 SDK**之间的边界，是「一第三方一支持库一提供者」口径的**唯一**开洞点。
# 目前唯一成员是 `MCP工具箱`：它是**平台自身的服务宿主**（MCP 服务本体——对外暴露
# tool/list 与 Streamable HTTP 入口），**不是能力消费者**。mcp / starlette / uvicorn 是它的
# 宿主运行时 SDK（协议服务端、ASGI 应用框架、ASGI 服务器）。把这三者封进
# `支持库/适配层/*提供者/` 在语义上做不到：提供者只应把第三方翻成不持有生命周期的可复用原子
# 能力，而「服务宿主」要起进程、挂路由、持有协议会话与连接生命周期——把宿主藏进能力层，
# 等于让一个声称原子的提供者持有宿主任期，反而破坏单一职责，也让「一第三方一支持库一提供者」
# 的口径失真。因此按「服务宿主而非能力提供者」显式放行。
# 放行范围**只限这三个包前缀**且只限这一个层：其它层直连第三方照旧报红；本层直连
# 白名单之外（例如 fastapi / torch / psutil）同样照旧报红。
服务宿主SDK白名单: dict[str, frozenset[str]] = {
    # 服务宿主（薄壳）迁入 开发工具/薄壳/ 后，宿主 SDK 白名单随层改挂。
    "开发工具": frozenset({"mcp", "starlette", "uvicorn"}),
}

标准库前缀表 = {
    "abc", "argparse", "ast", "asyncio", "base64", "collections", "contextlib",
    "copy", "csv", "dataclasses", "datetime", "decimal", "difflib", "enum",
    "functools", "getpass", "glob", "hashlib", "hmac", "html", "http",
    "importlib", "inspect", "io", "itertools", "json", "logging", "math",
    "multiprocessing", "os", "pathlib", "platform", "queue", "random", "re",
    "shutil", "signal", "socket", "sqlite3", "ssl", "statistics", "string",
    "struct", "subprocess", "sys", "tempfile", "textwrap", "threading", "time",
    "traceback", "types", "typing", "unicodedata", "urllib", "uuid", "warnings",
    "weakref", "xml", "zipfile", "zlib", "unittest", "select", "pydoc",
}


@dataclass
class 依赖违规:
    """一条依赖违规。"""

    来源层: str
    目标: str
    规则: str
    文件: str = ""
    行号: int = 0

    def 转字典(self) -> dict[str, Any]:
        return {"来源层": self.来源层, "目标": self.目标, "规则": self.规则,
                "文件": self.文件, "行号": self.行号}


@dataclass
class 依赖审计结果:
    """依赖审计结果。"""

    违规列表: list[依赖违规] = field(default_factory=list)
    审计文件数: int = 0

    @property
    def 成功(self) -> bool:
        return not self.违规列表


def _确定层(路径: Path) -> str:
    """按顶层目录确定层。"""
    相对 = 路径.relative_to(系统根)
    顶层 = 相对.parts[0] if 相对.parts else ""
    return 层名称表.get(顶层, "其他")


def 同包实现导入(文件: Path | str, 模块名: str) -> bool:
    """同包 `实现/` 导入判定：**全平台唯一权威口径**，三处审计共用本函数。

    判据按**路径段逐段相等**，不用字符串前缀：字符串前缀会把兄弟同名前缀包
    （`甲` 与 `甲子`）误判为同包，且在仓库根文件上退化为空前缀（`startswith("")`
    恒真）而全部放行。

    `文件` 是**相对审计根**（系统根 / 各审计器的显示根）的路径，`模块名` 是完整的
    点分模块名；文件所在目录的段表必须**恰好是**模块名段表的前缀才算同包。
    调用方：`运行核心/依赖防火墙.py::审计依赖`、`开发工具/复用审计/能力调用图审计.py`、
    `开发工具/组件合规/模块合规.py`（三者不得各自实现——各自实现就是 E-f 那种
    「同一行代码两个结论」的根因）。仓库根下平铺文件（段表为空）**不放行**。
    """
    文件包段 = tuple(Path(文件).with_suffix("").parts[:-1])
    return bool(文件包段) and tuple(模块名.split("."))[:len(文件包段)] == 文件包段


def 解析相对导入(文件包段: tuple[str, ...], 层级: int, 模块: str) -> str:
    """把相对导入（`from .实现.提供者 import X`）解析成绝对模块名。

    为什么必须解析：相对导入的**点号层级**已经把目标钉死在本包内，不解析就只剩字面量
    `实现.提供者`，会被 `同包实现导入` 判成「跨包导入 实现/ 目录」——实测
    `支持库/后端/组件规范支持库/实现/支持库模板生成器.py` 产出的每一个新包，其包级入口
    `from .实现.提供者 import 注册能力` 都被误判成红（同一行代码，两个结论）。
    `层级 > 包段长度`（越过包根，语法上本就不该出现）时**回退为原字面量**，交回原有
    判定路径：fail-closed，绝不因为解析不出来就静默放行。
    """
    if 层级 - 1 > len(文件包段):
        return 模块
    基准 = 文件包段[:len(文件包段) - (层级 - 1)] if 层级 > 1 else 文件包段
    if not 模块:
        return ".".join(基准)
    return ".".join((*基准, *模块.split(".")))


def _解析导入(树: ast.AST, 文件包段: tuple[str, ...] = ()) -> list[tuple[str, int]]:
    """AST 解析全部导入（含动态 import 调用）。

    `文件包段` = 被解析文件所在目录的路径段（相对审计根）；相对导入要按它解析成
    绝对模块名，否则 `from .实现.提供者 import X` 只剩字面量、被判成跨包（见 `解析相对导入`）。
    """
    导入表: list[tuple[str, int]] = []
    # for 名称 in ["固定子包", ...] 形式是有界的聚合注册，不属于任意动态导入。
    有界变量 = {
        节点.target.id
        for 节点 in ast.walk(树)
        if isinstance(节点, ast.For)
        and isinstance(节点.target, ast.Name)
        and isinstance(节点.iter, (ast.List, ast.Tuple))
        and all(isinstance(元素, ast.Constant) and isinstance(元素.value, str)
                for 元素 in 节点.iter.elts)
    }

    def _聚合前缀(表达式: ast.AST) -> str | None:
        """受控聚合导入的模块前缀：只认「字面量在前、有界变量在后」的拼接形态。

        `"支持库.后端.甲." + 子库名` → 前缀 `支持库.后端.甲.`，随后照常走层向检查；
        `前缀变量 + 子库名`（前缀不是字面量）或前缀为空 → None，按动态参数报违规。
        """
        if isinstance(表达式, ast.Constant) and isinstance(表达式.value, str):
            return 表达式.value
        if isinstance(表达式, ast.BinOp) and isinstance(表达式.op, ast.Add):
            左 = _聚合前缀(表达式.left)
            if 左 is None:
                return None
            if isinstance(表达式.right, ast.Constant) and isinstance(表达式.right.value, str):
                return 左 + 表达式.right.value
            return 左 if (isinstance(表达式.right, ast.Name) and 表达式.right.id in 有界变量) else None
        if isinstance(表达式, ast.Name) and 表达式.id in 有界变量:
            return ""
        return None

    for 节点 in ast.walk(树):
        if isinstance(节点, ast.Import):
            for 别名 in 节点.names:
                导入表.append((别名.name, 节点.lineno))
        elif isinstance(节点, ast.ImportFrom):
            模块 = 节点.module or ""
            if 节点.level:
                模块 = 解析相对导入(文件包段, 节点.level, 模块)
            导入表.append((模块, 节点.lineno))
        elif isinstance(节点, ast.Call) and (
                (isinstance(节点.func, ast.Name) and 节点.func.id in ("__import__", "import_module", "动态导入"))
                or (isinstance(节点.func, ast.Attribute) and 节点.func.attr in ("import_module", "动态导入"))):
            try:
                参数 = 节点.args[0]
                if (isinstance(参数, ast.BinOp) and isinstance(参数.op, ast.Add)
                        and any(isinstance(部分, ast.Name) and 部分.id in 有界变量
                                for 部分 in ast.walk(参数))):
                    # 已由源码中的固定列表约束取值；但仍必须携带字面前缀参与层向检查，
                    # 否则 `import_module("模块库.乙." + 子库名)` 这类受控聚合会绕过越层判定。
                    聚合前缀 = _聚合前缀(参数)
                    导入表.append((聚合前缀 if 聚合前缀 else "<动态参数>", 节点.lineno))
                elif isinstance(参数, ast.BinOp) and isinstance(参数.op, ast.Add):
                    def _字面字符串(表达式: ast.AST) -> str:
                        if isinstance(表达式, ast.Constant) and isinstance(表达式.value, str):
                            return 表达式.value
                        if isinstance(表达式, ast.BinOp) and isinstance(表达式.op, ast.Add):
                            return _字面字符串(表达式.left) + _字面字符串(表达式.right)
                        raise ValueError("非字面字符串")
                    导入表.append((_字面字符串(参数), 节点.lineno))
                else:
                    导入表.append((ast.literal_eval(参数), 节点.lineno))
            except (ValueError, SyntaxError, IndexError, TypeError):
                导入表.append(("<动态参数>", 节点.lineno))
    return 导入表


def _所在包已废弃(文件: Path) -> bool:
    """文件所属包是否已废弃（向上找 包声明.json 的 已废弃 标记）。"""
    for 目录 in 文件.parents:
        if (目录 / "包声明.json").is_file():
            try:
                import json
                声明 = json.loads((目录 / "包声明.json").read_text(encoding="utf-8"))
                return bool(声明.get("已废弃", False))
            except (OSError, ValueError):
                return False
    return False


def _所在包是内部层(文件: Path) -> bool:
    """读取文件所属包声明，判断是否为不对外暴露的内部支持库。"""
    for 目录 in 文件.parents:
        声明路径 = 目录 / "包声明.json"
        if not 声明路径.is_file():
            continue
        try:
            import json
            声明 = json.loads(声明路径.read_text(encoding="utf-8"))
            return bool(声明.get("内部层", False))
        except (OSError, ValueError):
            return False
    return False


# 不参与活跃依赖审计的目录名 / 文件名表：缓存目录、编译制品、测试与说明文档树。
# 判定语义为**名称精确相等**：原先用子串命中，会误剪 `工程缓存回收.py`（含「工程缓存」）
# 与 `验证器.py` / `统一验证器.py`（含「验证器」）等真实源码文件。
排除片段表 = ("pycache", "__pycache__", "工程缓存", "测试中心", "示例项目", "开发文档")


def _遍历待审计源码(根: Path) -> list[Path]:
    """递归收集待审计 .py，但**在进入目录时就剪枝**。

    原先用 rglob 全量产出再按整条路径过滤：全仓 7 万余个 .py 里 99% 落在 `工程缓存/`
    （各虚拟环境与编译制品），遍历与排序全部白做 —— 全仓审计 11 秒里语法解析只占 0.4 秒。

    剪枝按「目录名 / 文件名是否**精确等于**排除表条目」判定（子串命中会误剪真实源码文件，
    如 `工程缓存回收.py`、`统一验证器.py`）：任一祖先目录名命中 ⇒ 其全部后代路径都命中；
    反之，若某条路径命中，命中处必是某个目录名或文件名自身。等价，但不再落进那 7 万个文件。
    """
    收集: list[Path] = []
    for 当前根, 子目录名表, 文件名表 in os.walk(根):
        子目录名表[:] = [名 for 名 in 子目录名表 if 名 not in 排除片段表]
        for 名 in 文件名表:
            if 名.endswith(".py") and 名 not in 排除片段表:
                收集.append(Path(当前根) / 名)
    return sorted(收集)


# 动态导入的行级豁免标记。少数边界本来就只能按数据取模块名（例如外部独立进程按项目声明
# 「模块绑定」的包id 给模块注入连接器），其有界性由声明文件保证、字面量表达不出来。
# 豁免必须与代码同处一文件、写在被豁免那一行或上一行，并且附非空理由，便于 grep 复核；
# 只对「动态导入绕过依赖审计」这一条规则生效；空标记、越界行号一律不豁免（fail-closed）。
行级豁免标记 = "依赖门禁豁免："


def _动态导入行级豁免(源码: str, 行号: int) -> bool:
    """被豁免行（或上一行）是否带「# 依赖门禁豁免：<理由>」形式的行级豁免。"""
    行表 = 源码.splitlines()
    for 候选 in (行号, 行号 - 1):
        if not 1 <= 候选 <= len(行表):
            continue
        行文本 = 行表[候选 - 1]
        if "#" not in 行文本:
            continue
        # 只认该行第一处 `#` 之后的注释位置：字符串里出现标记文本不会误豁免。
        注释 = 行文本.split("#", 1)[1].strip()
        if 注释.startswith(行级豁免标记) and 注释[len(行级豁免标记):].strip():
            return True
    return False


def 审计依赖(目标目录: Path | None = None, *, 返回违规: bool = True) -> 依赖审计结果:
    """AST 依赖审计：逐文件解析导入，按允许方向与强制拒绝规则判定。"""
    实际目录 = Path(目标目录) if 目标目录 is not None else 系统根
    结果 = 依赖审计结果()
    for 文件 in _遍历待审计源码(实际目录):
        # 已废弃包（保留为不可变回滚版本）不参与活跃依赖审计
        if _所在包已废弃(文件):
            continue
        try:
            源码 = 文件.read_text(encoding="utf-8")
            树 = ast.parse(源码)
        except (SyntaxError, OSError, UnicodeDecodeError) as 错误:
            结果.违规列表.append(依赖违规(_确定层(文件), str(错误), "源码无法解析", str(文件.relative_to(系统根)), 0))
            continue
        来源层 = _确定层(文件)
        结果.审计文件数 += 1
        文件相对 = 文件.relative_to(系统根)
        文件包段 = tuple(文件相对.with_suffix("").parts[:-1])
        for 模块名, 行号 in _解析导入(树, 文件包段):
            if not 模块名 or 模块名.startswith("_") and 模块名 not in ("__future__",):
                continue
            if 模块名 == "__future__":
                continue
            顶层 = 模块名.split(".")[0]
            if 顶层 in 标准库前缀表:
                continue
            if 顶层 == "公共契约":
                continue  # 公共契约可被全部层依赖
            # 强制拒绝 1：跨包导入 实现/ 目录（同包 __init__ 导自身实现是合法入口模式）
            # 同包判定唯一权威实现 = 同包实现导入（三处审计共用，见其 docstring）。
            if "实现" in 模块名.split("."):
                if not 同包实现导入(文件.relative_to(系统根), 模块名):
                    结果.违规列表.append(依赖违规(来源层, 模块名, "跨包禁止导入 实现/ 目录", str(文件.relative_to(系统根)), 行号))
                continue
            # 强制拒绝 2：支持库反向导入核心/模块/项目
            if 来源层 == "支持库" and 顶层 in ("模块库", "前端核心", "后端核心", "运行核心", "项目适配层"):
                结果.违规列表.append(依赖违规(来源层, 模块名, "支持库反向导入", str(文件.relative_to(系统根)), 行号))
                continue
            # 强制拒绝 4：核心硬编码具体模块（核心层导入 模块库）
            if 来源层 in 核心层表 and 顶层 == "模块库":
                结果.违规列表.append(依赖违规(来源层, 模块名, "核心硬编码具体模块", str(文件.relative_to(系统根)), 行号))
                continue
            # 强制拒绝 6：动态导入绕过审计（唯一例外：被豁免行写了行级豁免+理由）
            if 模块名 == "<动态参数>":
                if _动态导入行级豁免(源码, 行号):
                    continue
                结果.违规列表.append(依赖违规(来源层, 模块名, "动态导入绕过依赖审计", str(文件.relative_to(系统根)), 行号))
                continue
            # P6 规则 1：模块/项目适配层/核心 不得导入第三方发行包（docx/fitz/openpyxl 等）
            if 顶层 in 第三方前缀表:
                # ③ 服务宿主白名单（显式，且是唯一的第三方开洞点）：`MCP工具箱` 是平台自身的
                #    服务宿主，可直接导入它声明的宿主 SDK（mcp/starlette/uvicorn）——理由与被否
                #    掉的替代方案见 `服务宿主SDK白名单` 上方注释。判据是**层名 + 包前缀双重显式
                #    集合**，不是「按目录名跳过」：层名不在表里的层、包前缀不在集合里的第三方
                #    （fastapi/torch/psutil…）全部照旧报红。
                if 顶层 in 服务宿主SDK白名单.get(来源层, frozenset()):
                    continue
                # 适配层豁免判据：按**路径段**判，不用「适配层」子串——子串判定在
                # `支持库/后端/<某适配层>/…` 这类路径上会把不相干的文件算进豁免，
                # 且对 `支持库/x.py` 取 parts[2] 会直接 IndexError。
                # ① 根下直接文件豁免：`支持库/适配层/xxx.py`（不在任何子目录内）就是
                #    AGENTS.md「系统适配器豁免」所指的、**不对外提供能力契约**的内部
                #    适配器（模型服务.py、脱敏模式.py、系统探针.py…）：它们只为底座内部
                #    把系统/第三方能力翻成可复用的中文原语，不注册能力契约、不发布、
                #    不被模块调用。判它们违规等于要求「翻译层不许碰被翻译的库」，只会把
                #    适配代码塞进 `*提供者/` 冒充提供者，让「一第三方一支持库一提供者」
                #    的口径失真。密码适配.py（已废弃、仅测试可直引的历史兼容文件）也是
                #    根下直接文件，一并覆盖。
                # ② `*提供者/` 子目录：第三方依赖的**唯一合法落点**（AGENTS.md
                #    「第三方依赖必须封装在 支持库/适配层/ 对应提供者」），依据与 ① 不同，
                #    两条豁免不可互相扩张：① 不覆盖子目录（`配置读取/` 这类非提供者
                #    子目录里直连第三方仍报违规），② 也不覆盖根下的非适配层文件。
                #    注意 AGENTS.md「`*提供者` 包与对外发布支持库不受此豁免」说的是
                #    **结构要件**（包声明.json/完整性摘要.json…）的豁免不含提供者，
                #    与第三方导入豁免是两回事，不能据此把提供者的第三方导入判违规。
                相对段 = 文件.relative_to(系统根).parts
                是否提供者文件 = (
                    来源层 == "支持库"
                    and len(相对段) >= 3
                    and 相对段[:2] == ("支持库", "适配层")
                    and (len(相对段) == 3 or 相对段[2].endswith("提供者"))
                ) or (
                    "平台控制面/提供者" in str(文件.relative_to(系统根))
                ) or (
                    来源层 == "开发工具" and "发布门禁" in str(文件.relative_to(系统根))
                )
                if not 是否提供者文件 and not _所在包是内部层(文件):
                    结果.违规列表.append(依赖违规(来源层, 模块名, "第三方直连（一第三方一支持库，仅提供者可导入）", str(文件.relative_to(系统根)), 行号))
                    continue
            # P6 规则 2：适配层提供者只允许支持库层/运行核心/模块库（模块组合提供者）依赖
            if 顶层 == "支持库" and "适配层" in 模块名 and 模块名.split(".")[-1].endswith("提供者"):
                if 来源层 not in ("支持库", "运行核心", "模块库", "开发工具"):
                    结果.违规列表.append(依赖违规(来源层, 模块名, "正式代码直达支持库提供者（只调用模块）", str(文件.relative_to(系统根)), 行号))
                    continue
            # 允许方向检查（同层内部导入允许；`允许依赖表` + `文件级豁免表` 是唯一口径）
            if 顶层 in 层名称表 and 顶层 != "公共契约" and 顶层 != 来源层:
                相对路径 = str(文件.relative_to(系统根))
                允许表 = 允许依赖表.get(来源层, set())
                # 文件级豁免（如网关启动脚本拉起后端核心）与被登记在层表里的授权同源判定：
                # 两者都是**表数据**，判定代码里不再有「哪个文件例外」的分支（E-a）。
                文件豁免表 = 文件级豁免表.get(来源层, {})
                if 顶层 not in 允许表 and 顶层 not in 文件豁免表.get(相对路径, frozenset()):
                    结果.违规列表.append(依赖违规(来源层, 模块名, f"越层依赖（{来源层} 不允许依赖 {顶层}）", 相对路径, 行号))
    return 结果


def 检查头注释与表同源() -> list[str]:
    """头注释镜像块 与 `允许依赖表`/`层名称表` 逐项比对，返回差异清单（空 = 同源）。

    为什么要机器校验：头注释原先手写一份「允许方向」清单，改表不改正本块之后
    两份口径就对不上了（E-c）。现在头注释里的镜像块是**可解析数据**，本函数
    拿它和真正的表逐项比：键集合必须等于 `层名称表` 全层，每层的目标集合必须逐项相等。
    """
    镜像标记 = "允许方向镜像（JSON，机器可校验）："
    文本 = __doc__ or ""
    if 镜像标记 not in 文本:
        return [f"头注释缺少镜像块标记：{镜像标记}"]
    正文 = 文本.split(镜像标记, 1)[1].lstrip()
    try:
        镜像, _ = json.JSONDecoder().raw_decode(正文)
    except ValueError as 错误:
        return [f"头注释镜像块不是合法 JSON: {错误}"]
    if not isinstance(镜像, dict):
        return ["头注释镜像块必须是 层 → 目标层列表 的 JSON 对象"]
    问题列表: list[str] = []
    if set(镜像) != set(层名称表):
        缺 = sorted(set(层名称表) - set(镜像))
        多 = sorted(set(镜像) - set(层名称表))
        问题列表.append(f"镜像块层集合与 层名称表 不一致：缺 {缺}／多 {多}")
    for 层, 目标表 in 允许依赖表.items():
        镜像目标 = 镜像.get(层)
        if 镜像目标 is None:
            continue
        if sorted(镜像目标) != sorted(目标表):
            问题列表.append(f"{层}：镜像 {sorted(镜像目标)} ≠ 允许依赖表 {sorted(目标表)}")
    return 问题列表


def 检查豁免表(目标目录: Path | None = None) -> list[str]:
    """文件级豁免体检：返回问题清单（空 = 每条豁免都还指得着真实文件）。

    豁免搬进表的目的是「可列举、可审计」（E-a），但表一旦不再指向真实文件，
    它就退化成**指向已删除东西的规范**（AGENTS.md 铁律）——豁免文件被删/改名后，
    这条豁免会一直挂在表里没人清，下一个人看不出它是活的还是死的。
    ① 豁免路径必须是真实存在的 `.py` 文件；
    ② 豁免的目标层必须在 `层名称表` 里（目标层写错就是永远不生效的豁免）；
    ③ `(层, 文件)` 不能重复登记（重复即两处口径，改一处漏一处）。
    """
    实际目录 = Path(目标目录) if 目标目录 is not None else 系统根
    问题列表: list[str] = []
    已见: set[tuple[str, str]] = set()
    for 来源层, 豁免组 in 文件级豁免表.items():
        if 来源层 not in 层名称表:
            # 「其他」层是合法来源层（不在 层名称表 的正式层里时按同源判定）
            问题列表.append(f"豁免来源层不在 层名称表：{来源层}")
        for 相对路径, 目标层集 in 豁免组.items():
            键 = (来源层, 相对路径)
            if 键 in 已见:
                问题列表.append(f"豁免重复登记：{来源层} → {相对路径}")
            已见.add(键)
            if not (实际目录 / 相对路径).is_file():
                问题列表.append(
                    f"豁免失效：{来源层} → {相对路径} 文件不存在"
                    f"（豁免必须指向真实文件；文件已删/改名时删除本豁免）")
            for 目标层 in 目标层集:
                if 目标层 not in 允许依赖表:
                    问题列表.append(f"豁免目标层未登记：{相对路径} → {目标层}")
    return 问题列表


def 检查依赖口径(目标目录: Path | None = None) -> list[str]:
    """三张表的**唯一体检入口**：头注释同源 + 预留授权 + 文件级豁免。

    为什么要有这个聚合入口：`检查头注释与表同源()` 与 `检查预留授权()` 曾写好了
    却**全仓 0 调用**（空转即杀：判据写了没人跑，等于没有这个判据），且两者的
    docstring 指向的 `测试中心/开发工具/测试_依赖防火墙口径.py` 并不存在。
    现在由本入口统一聚合，测试与门禁只调这一个，避免「体检函数各写各的、谁都没跑」。
    """
    return (检查头注释与表同源()
            + 检查预留授权(目标目录)
            + 检查豁免表(目标目录))


def 检查预留授权(目标目录: Path | None = None) -> list[str]:
    """预留授权体检：返回问题清单（空 = 预留标注与实际状态一致，见 `预留授权表`）。

    ① 每个预留项必须仍在 `允许依赖表` 里被登记（表删了授权就报「预留失效」）；
    ② 预留项若已被真实使用（来源层真有文件 import 了目标层），必须转正。
    """
    问题列表: list[str] = []
    for (来源层, 目标层), 理由 in 预留授权表.items():
        if 目标层 not in 允许依赖表.get(来源层, set()):
            问题列表.append(f"预留失效：{来源层} → {目标层} 已不在 允许依赖表，删标注或补表")
        if not 理由.strip():
            问题列表.append(f"预留理由为空：{来源层} → {目标层}")
    实际目录 = Path(目标目录) if 目标目录 is not None else 系统根
    for 文件 in _遍历待审计源码(实际目录):
        来源层 = _确定层(文件)
        目标层集合 = {目标 for (来源, 目标) in 预留授权表 if 来源 == 来源层}
        if not 目标层集合:
            continue
        if _所在包已废弃(文件):
            continue
        try:
            树 = ast.parse(文件.read_text(encoding="utf-8"))
        except (SyntaxError, OSError, UnicodeDecodeError):
            continue
        for 模块名, 行号 in _解析导入(树, tuple(文件.relative_to(系统根).with_suffix("").parts[:-1])):
            if 模块名.split(".")[0] in 目标层集合:
                问题列表.append(
                    f"预留授权已被实际使用：{文件.relative_to(系统根)}:{行号} 导入 {模块名}"
                    f"（{来源层} → {模块名.split('.')[0]}）→ 应转正：去掉「预留」标注并按真实用法核对授权范围")
    return 问题列表


def 审计结果转清单(结果: 依赖审计结果) -> list[str]:
    return [f"[{违规.来源层}→{违规.目标}] {违规.规则} @ {违规.文件}:{违规.行号}" for 违规 in 结果.违规列表]
