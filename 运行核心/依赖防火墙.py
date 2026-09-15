"""依赖防火墙：统一 AST 依赖审计（进入发布门禁）。

允许方向：
公共契约 -> 不依赖其他层
支持库 -> 公共契约
技能库 -> 公共契约（与 支持库 同口径）
模块库 -> 公共契约和公开能力调度
前端核心 -> 公共契约和私有引导适配器
后端核心 -> 公共契约和私有引导适配器
运行核心 -> 公共契约和支持库公开入口
项目适配层 -> 公共契约和核心公开入口
MCP工具箱 -> 平台自身的服务宿主层：只依赖它在源码里实际用到的层（公共契约、支持库、
              运行核心、开发工具）；它的第三方宿主 SDK（mcp/starlette/uvicorn）由
              `服务宿主SDK白名单` 显式放行，不走「一第三方一支持库一提供者」口径。

强制拒绝：
导入任何 实现/ 目录；支持库反向导入核心/模块/项目；
模块导入第三方库或支持库内部文件；核心硬编码具体模块；
使用物理目录作为能力身份；动态导入绕过依赖审计；
非白名单层直连第三方发行包（唯一例外：`服务宿主SDK白名单` 里的服务宿主 + 其宿主 SDK）。
"""

from __future__ import annotations

import ast
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
    "项目适配层": "项目适配层",
    "开发工具": "开发工具",
    # 平台自身的**服务宿主层**（见 `服务宿主SDK白名单` 的说明）：它不是能力消费者，而是
    # MCP 服务本体。它与 `允许依赖表` 必须**同批**登记——只加这一张表会让 MCP工具箱 退化成
    # 「其他」，`允许依赖表` 里的第三方/越层判据就全部落空。
    "MCP工具箱": "MCP工具箱",
    "其他": "其他",
}

允许依赖表: dict[str, set[str]] = {
    "公共契约": set(),
    "支持库": {"公共契约"},
    "模块库": {"公共契约", "支持库"},  # 支持库仅限包级公开入口（实现/ 已被强制拒绝）
    "技能库": {"公共契约"},  # 第三根正式包根：与 支持库 同口径，暂不放行 支持库 原子能力
    "前端核心": {"公共契约", "运行核心"},
    "后端核心": {"公共契约", "运行核心"},
    "运行核心": {"公共契约", "支持库"},
    "项目适配层": {"公共契约", "运行核心"},
    # 服务宿主层的最小授权：**只登记它在源码里实际用到的层**（现场实测其 12 条层间导入恰好
    # 落在这四个集合内），不开放「任意层导入」。它的第三方宿主 SDK 不在这里管，见
    # `服务宿主SDK白名单`。
    "MCP工具箱": {"公共契约", "支持库", "运行核心", "开发工具"},
    # `开发工具/开发入口.py`、`开发工具/统一能力入口/Agent查询/查询入口.py` 存量直引
    # `MCP工具箱.发布治理`；MCP工具箱 登记为层之后，这里必须同批放行，否则凭「越层依赖」
    # 新增 3 条红（是登记动作的副作用，不是新违规）。
    "开发工具": {"公共契约", "支持库", "模块库", "运行核心", "后端核心", "前端核心", "项目适配层", "MCP工具箱"},
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
    "MCP工具箱": frozenset({"mcp", "starlette", "uvicorn"}),
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


def _解析导入(树: ast.AST) -> list[tuple[str, int]]:
    """AST 解析全部导入（含动态 import 调用）。"""
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
        for 模块名, 行号 in _解析导入(树):
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
            if "实现" in 模块名.split("."):
                # 同包判定按**路径段逐段相等**，不用字符串前缀：
                # 字符串前缀会把兄弟同名前缀包（`甲` 与 `甲子`）误判为同包，
                # 且在仓库根文件上退化为空前缀（`startswith("")` 恒真）而全部放行。
                文件包段 = tuple(文件.relative_to(系统根).with_suffix("").parts[:-1])
                模块段表 = tuple(模块名.split("."))
                if not (文件包段 and 模块段表[:len(文件包段)] == 文件包段):
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
            # 允许方向检查（同层内部导入允许；工具层"其他"不受方向限制）
            if 顶层 in 层名称表 and 顶层 != "公共契约" and 顶层 != 来源层:
                # 网关启动脚本是唯一的启动编排边界：它负责拉起后端核心。
                # 只放行该文件，禁止把整个运行核心层开放给后端核心。
                if (来源层 == "运行核心"
                        and str(文件.relative_to(系统根)) == "运行核心/启动运行核心网关.py"
                        and 顶层 == "后端核心"):
                    continue
                if 来源层 == "其他":
                    continue  # 工具/门禁/验证 文件可依赖任意层
                允许表 = 允许依赖表.get(来源层, set())
                if 顶层 not in 允许表:
                    结果.违规列表.append(依赖违规(来源层, 模块名, f"越层依赖（{来源层} 不允许依赖 {顶层}）", str(文件.relative_to(系统根)), 行号))
    return 结果


def 审计结果转清单(结果: 依赖审计结果) -> list[str]:
    return [f"[{违规.来源层}→{违规.目标}] {违规.规则} @ {违规.文件}:{违规.行号}" for 违规 in 结果.违规列表]
