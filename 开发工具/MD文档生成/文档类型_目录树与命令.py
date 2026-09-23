"""文档生成 · 类型动作：包级「目录树与命令」（`**/说明/目录树与命令.md` 的树块）。

## 为什么单独一类

`开发文档/规范/Markdown 文档体例规范.md` 第四节把 `目录树与命令.md` 列为包级三件套之一
（条件必备）。实测（2026-09-20）全仓 **67 份**，但**没有任何生成器覆盖它** ——
`开发工具.MD文档生成.说明书.合并重生成` 写死 `说明书相对名=("说明","使用说明.md")`，
`文档类型判据.json` 里声明的「唯一生成器 = 合并重生成」在本类上是**空头承诺**。
结果：树块靠人手抄 `完整性摘要.json`，抄漏就永久漂移（实测 1 份真漂移，见下）。

## 判据与边界（刻意最小）

**唯一事实源 = 同包 `完整性摘要.json` 的文件清单**。本动作只做一件事：
报出/删掉「树里写了、摘要里没有」的条目 —— 这类条目**照它执行会打不开文件**，
是 `#181`/`#186` 那一类「文件搬动后说明未同步」的真缺陷。

**刻意不做的三件事**（防「一次杀完」）：

1. **不重排、不补条、不换格式**。「关键文件清单」是**人工选定的子集**（实测：绝大多数
   排除 `说明/设计说明.md`/`说明/目录树与命令.md`/`验证场景/*.json`，但 `Git提供者`
   偏偏含 `能力定义.json` —— 选择规则本身就不统一），补齐等于替人做内容决策。
2. **不碰「公开命令」与「规范边界」两段**（人工区）。
3. **判据留兜底**：树里写裸文件名（省略层级）或带行尾注释都算命中，不误判为漂移
   —— 实测初版判据误伤 61 份（根目录行、`完整性摘要.json` 自身、行尾注释），已逐条收紧。

**目录条目**（以 `/` 结尾）与**根目录行**（树块第 1 行 = 包目录名）不参与对账。
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from 开发工具.MD文档生成 import 生成区
# 生成器落盘的**唯一腿**（2026-09-23「生成器开窗」）：原子写 + 留写入凭据，
# 见 `机器印记.py` 同一处说明。本层不再各自 `write_text`。
from 支持库.后端.文件系统支持库.文件操作 import 写入文件

树块标题 = "## 目录树"
摘要文件名 = "完整性摘要.json"
#: 本类型的登记名（判据文件 `文档类型判据.json` 里的 `类型`）
类型名 = "包级说明-目录树与命令"
#: 树块围栏内、允许出现的树线字符
树线 = "│├└─ "


def 包目录(项目根: Path, 相对: str) -> Path:
    """`<包>/说明/目录树与命令.md` → `<包>`。"""
    return (项目根 / 相对).parent.parent


def 读摘要清单(包目录: Path) -> list[str] | None:
    """同包 `完整性摘要.json` 的文件清单（路径表）；缺文件/非法即 None（不猜）。"""
    路径 = 包目录 / 摘要文件名
    if not 路径.is_file():
        return None
    try:
        数据 = json.loads(路径.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    清单 = 数据.get("文件清单")
    if not isinstance(清单, list):
        return None
    return [str(x.get("路径")) for x in 清单
            if isinstance(x, dict) and x.get("路径")]


def 树块范围(行表: list[str]) -> tuple[int, int] | None:
    """树块围栏内的行号区间 `(起, 止)`（半开）；找不到即 None。"""
    起 = None
    for i, 行 in enumerate(行表):
        if 行.strip() == 树块标题:
            起 = i
            break
    if 起 is None:
        return None
    for j in range(起 + 1, len(行表)):
        if 行表[j].strip().startswith("```"):
            for k in range(j + 1, len(行表)):
                if 行表[k].strip() == "```":
                    return (j + 1, k)
            return None
    return None


def 树条目(行表: list[str], 起: int, 止: int) -> list[tuple[int, str]]:
    """树块里的「文件条目」：(行号, 原文行)。跳过首行（包目录名）与目录条目。"""
    结果: list[tuple[int, str]] = []
    for i in range(起, 止):
        行 = 行表[i]
        if not 行.strip():
            continue
        if i == 起:
            continue                       # 根目录行 = 包目录名自身
        m = re.match(rf"^[{树线}]*([^\s{树线}].*?)\s*$", 行)
        if not m:
            continue
        条目 = m.group(1).strip()
        if not 条目 or 条目.endswith("/"):
            continue                       # 目录条目只作分组，不入清单
        结果.append((i, 条目))
    return 结果


def _条目名(条目: str) -> str:
    """条目名：去掉行尾注释（`__init__.py  # 包级中文入口`）。"""
    return re.split(r"\s+#", 条目)[0].strip()


def 漂移条目(项目根: Path, 相对: str) -> list[str] | None:
    """树里写了、而同包 `完整性摘要.json` 没有的条目；摘要缺失即 None（不判红）。"""
    包 = 包目录(项目根, 相对)
    清单 = 读摘要清单(包)
    if 清单 is None:
        return None
    名集 = {Path(x).name for x in 清单}
    文件集 = set(清单)
    out: list[str] = []
    行表 = (项目根 / 相对).read_text(encoding="utf-8").splitlines()
    范围 = 树块范围(行表)
    if 范围 is None:
        return []
    for _, 条目 in 树条目(行表, *范围):
        净 = _条目名(条目)
        # 目录判定必须在**去注释之后**：实测 `能力数据/   # 能力搜索数据` 这类带注释的目录行
        # 若先判 endswith("/") 会漏网，被误报成漂移（`模块库/直播逐字稿` 就是这一例）。
        if not 净 or 净.endswith("/"):
            continue
        if 净 == 摘要文件名:              # 摘要自身不入自身清单，不算漂移
            continue
        if 净 in 文件集 or Path(净).name in 名集:
            continue
        out.append(净)
    return out


def 核验(项目根: Path, 相对: str) -> tuple[int, list[str]]:
    """门禁形态：树块与 `完整性摘要.json` 对账，有漂移即判红。"""
    漂移 = 漂移条目(项目根, 相对)
    if 漂移 is None:
        return 0, [f"  同包缺 {摘要文件名}，未参与对账（如实放过，不判红）"]
    if not 漂移:
        return 0, ["  树块与完整性摘要一致"]
    return 1, [f"  树里写了但摘要里没有（照它执行会打不开文件）：{x}" for x in 漂移]


def 出文档(项目根: Path, 相对: str) -> tuple[int, list[str]]:
    """生成器形态：**只删**树块里对不上摘要的条目；不重排、不补条、不换格式。

    「缺摘要」与「无漂移」的结论必须与 `核验` **完全一致**（同一情形两套结论即缺陷：
    实测初版写盘侧返回 2、核验侧返回 0，同一份 MySQL提供者 两边说法相反）。
    故此处同判 0：缺摘要 = 没有可对账的基准，**如实放过、不判红、也不改**。
    """
    漂移 = 漂移条目(项目根, 相对)
    if 漂移 is None:
        return 0, [f"  同包缺 {摘要文件名}，未参与对账（如实放过，不判红）"]
    if not 漂移:
        return 0, ["  树块与完整性摘要一致，无需改动"]
    路径 = 项目根 / 相对
    文本 = 路径.read_text(encoding="utf-8")
    行表 = 文本.splitlines()
    范围 = 树块范围(行表)
    if 范围 is None:
        raise 生成区.边界缺失(f"找不到 {树块标题} 的 ```text 围栏：{相对}（边界切不出即拒改）")
    去掉 = {i for i, 条目 in 树条目(行表, *范围) if _条目名(条目) in set(漂移)}
    新表 = [行 for i, 行 in enumerate(行表) if i not in 去掉]
    写入文件(str(路径),
           "\n".join(新表) + ("\n" if 文本.endswith("\n") else "")).确保成功()
    return 0, [f"  已删漂移条目 {len(去掉)} 行：{x}" for x in 漂移]


def 主流程(项目根: Path, 写盘: bool, 今天: str | None = None,
           单文件: str | None = None) -> tuple[int, list[str]]:
    """本类型的入口（签名与 `文档类型_债务清单.主流程` 一致，见 `__main__.py` 的统一分派）。

    类型定义从判据文件按名取（**不另抄一份路径判据**）；`单文件` 为 `--文件 <路径>` 的定向模式。
    """
    from 开发工具.MD文档生成 import 类型登记
    类型 = 类型登记.按名取(项目根, 类型名)
    表 = [单文件] if 单文件 else [p.relative_to(项目根).as_posix()
                              for p in 枚举(项目根, 类型)]
    if not 表:
        return 2, [f"该类型下没找到现存文件（路径判据：{类型.get('路径判据')}）"]
    总码, 行表 = 0, []
    for 相对 in 表:
        码, 行 = 出文档(项目根, 相对) if 写盘 else 核验(项目根, 相对)
        总码 = max(总码, 码)
        行表.append(f"  [{'写盘' if 写盘 else '核验'}] {相对}")
        行表.extend("      " + x for x in 行)
    return 总码, 行表


def 枚举(项目根: Path, 类型: dict) -> list[Path]:
    """该类型下的现存文件（复用统一类型登记的判据，不另写一份匹配规则）。"""
    from 开发工具.MD文档生成 import 类型登记
    return 类型登记.枚举文件(项目根, 类型)
