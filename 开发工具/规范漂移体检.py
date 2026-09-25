"""规范漂移体检：让「规则类文件」的指向可机器复核，而不是靠人工记得同步。

华哥 2026-09-20 口述「规则类的，最好是有一个统一的生成器去适配契约，人工维护容易偏移」。

## 这条意见的现场证据（为什么必须现在就做）

`AGENTS.md` 自己记着一次真实事故：**2026-09-16 文档收口**后，一批规范仍在让执行者
去调 `project_context` / `codegraph_explore` / `mcp_feedback` / `verify_and_record`
—— 那些接入面**当天就被删了**。整份规范因此不可执行，且**长期无人遵循**（没人跑得通，
自然就没人照做）。当时总结的教训是「规范不得指向已删除的东西」，但**没有留下机器判据**，
只能靠下一轮人工再发现一次。

本入口把那条教训做成判据：**规则文件里点名的每一个入口/命令/路径/锚点，现场核一遍**。

## 三类判据（都只看「指向是否还存在」，不评价规则内容好坏）

| 判据 | 查什么 | 判红条件 |
|---|---|---|
| ① 路径指向 | 规则里点名的 `开发工具/…`、`开发文档/…`、`支持库/…` 等仓库相对路径 | 路径不存在 |
| ② 锚点指向 | `原文位置` 里 `文件#锚` 的锚点 | 文件不存在，或文件里找不到该标题 |
| ③ 命令指向 | 规则里 `` `python3.14 …` `` 点名的模块/脚本 | 模块文件不存在 |

**判据口径**：只认**仓库相对路径**与 `python3.14 -m <模块>` 形态；外部 URL、
环境变量、通配符、`<占位>` 一律跳过（它们本就无法在此静态判定，硬查只会产出假红）。

用法：
    python3.14 -m 开发工具.规范漂移体检 [--只报]

退出码：0 = 无漂移；1 = 有漂移（指向已不存在的东西，规范不可执行）。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

系统根 = Path(__file__).resolve()
for _祖先 in 系统根.parents:
    if (_祖先 / "支持库").is_dir() and (_祖先 / "模块库").is_dir():
        系统根 = _祖先
        break
if str(系统根) not in sys.path:
    sys.path.insert(0, str(系统根))

from 公共契约.基础类型.逻辑类型 import 真, 假
from 公共契约.正式根 import 源码层名表

#: 规则类文件（人工维护、又要被执行的）：规范目录 + 两份根规则文档。
规范目录 = 系统根 / "开发文档" / "规范"
根规则文件 = (
    系统根 / "AGENTS.md",
    系统根 / "开发文档" / "主开发文档.md",
    系统根 / "开发文档" / "项目说明.md",
)

#: 仓库相对路径的起头（点名的路径必须以这些词开头才算「仓库内可查」）。
# 路径起头表**不本地复刻**：唯一事实源 = `公共契约/正式根.py::源码层名表`（源码层名 + "/"）。
# 原手抄 13 项缺 `技能库/`/`客户端/`/`运维脚本/`（三者都在 `源码层名表` 里）—— 属第二事实源；
# 缺了它们会让规则文件点名这三层的路径**静默跳过不查**（假绿）。
路径起头表 = tuple(名 + "/" for 名 in 源码层名表)
#: 允许不存在的路径（归档/历史位置/示例占位）。
忽略片段 = ("<", ">", "*", "（", "）", "…", "工程缓存/", "归档/", "分析/", "方案/")
#: 标准库模块（`python3.14 -m unittest` 这类不算项目模块）。
标准库模块表 = {"unittest", "py_compile", "json", "sys", "os", "time", "http",
          "unittest.mock", "venv", "pip", "compileall", "http.server"}
#: 反引号代码片段（规则里点名真实文件/命令的**唯一**承载形式）。
#: 只查它、不查散文 —— 散文里的 `支持库/模块必须申报`、`新建支持库/模块时` 是中文并列，
#: 拿它当路径查会产出大量假红（2026-09-20 实测：50 条里约 40 条是这样来的）。
代码片段句式 = re.compile(r"`([^`\n]+)`")
#: **否定/历史/枚举语境**：这类行里写出的路径名不是「让执行者去用」，而是
#: 讲历史、讲被否决的做法、或列举枚举值。判红会逼作者删掉这些说明。
#: 实证样本：`原 `开发工具/组件规范/` 已下沉`（历史）、
#: `实测 `支持库/核心/` 空壳仍在`（追述旧状态）、
#: `只认 `支持库/基础模块/功能模块``（包类型枚举值，不是目录）。
否定语境句式 = re.compile(
    r"已不存在|已下沉|已删(?:除)?|已清场|已下线|已迁移|已取代|已废弃|已收敛|原\s*`|旧路径|不再|废弃|改名为"
    r"|历史|教训|空壳|仍在|枚举|取值|合法值|只认|不一致")
#: **非本仓语境**：讲的是「别的项目/调用方自己传的目录」，不是本仓库内的路径。
非本仓语境句式 = re.compile(r"其他项目|别的项目|调用方传入|调用方传|项目自己|各自项目|各项目")
#: 占位符/模板名（`测试_XX.py`、`<包目录>`、`_模板`、`开发工具.<名>`）——
#: 本就是模板，不该查存在。
占位符句式 = re.compile(r"XX|NN|<[^>]*>|_模板|\*|\.\.\.")
#: **包类型枚举值**：这些词在路径里是被列举的类型名，不是目录
#: （`支持库/基础模块/功能模块` 讲的是「装配器只认这三种类型」）。
类型枚举词 = {"基础模块", "功能模块", "支持库", "模块", "适配层"}


def _路径存在(相对: str) -> bool:
    """仓库相对路径是否存在；无扩展名时按 `.py` / `.md` / `.json` 三态补试。

    **先把 `文件路径::符号` 与 `文件路径:行号` 的尾巴剥掉**：这两种是
    `AGENTS.md` 与 `项目说明.md` 里标准的「定点引用」写法（如
    `运行核心/加载器/生命周期管理/管理器.py:198`、`契约指纹.py::契约指纹()`），
    它们**指向的是真实存在的文件**，把整串当路径查必然假红。

    **末段做前缀匹配**：中文文件名含空格时（`Markdown 文档体例规范.md`），
    从散文里截出的半截 `开发文档/规范/Markdown` 应视为**指向该文件**而不是漂移。
    """
    净 = 相对.strip().rstrip("。，、；：）)]}`\"'")
    if not 净 or any(片 in 净 for 片 in 忽略片段):
        return 真
    # 剥 `::符号` / `:行号` 尾巴
    净 = re.split(r"::|:\d+$", 净)[0].rstrip(":：")
    if not 净:
        return 真
    if (系统根 / 净).exists():
        return 真
    if "." not in Path(净).name:
        for 后缀 in (".py", ".md", ".json"):
            if (系统根 / (净 + 后缀)).is_file():
                return 真
    # 末段前缀匹配（含空格的中文文件名被截断的情形）
    父 = (系统根 / 净).parent
    名 = (系统根 / 净).name
    if 名 and 父.is_dir():
        if any(子.name.startswith(名) for 子 in 父.iterdir() if 子.is_file()):
            return 真
    return 假


def _是路径形态(片段: str) -> bool:
    """该代码片段是否在点名一个**仓库相对路径**（而不是能力 id / 中文并列 / 占位符）。

    排除三类非路径写法（2026-09-20 实测，它们占了全部假红的绝大多数）：
    - **中文并列**：`支持库/模块必须申报`、`支持库/基础模块/功能模块`
      —— 斜杠是中文顿号义，不是路径分隔；
    - **能力 id**：`模块库/开工编排.开工准备`（末段含 `.` 且不是文件后缀）；
    - **占位符/模板名**：`测试中心/模块库/测试_XX.py`、`<包目录>`、`模块库/_模板`。
    """
    净 = 片段.strip()
    if not 净 or not 净.startswith(路径起头表):
        return 假
    if any(片 in 净 for 片 in 忽略片段) or 占位符句式.search(净):
        return 假
    # 剥定点的尾巴后判断
    核 = re.split(r"::|:\d+$", 净)[0].rstrip(":：")
    段 = [s for s in 核.split("/") if s]
    # **末段含空格**：`Markdown 文档体例规范.md` 这类中文文件名合法，
    # 但 `（多会话并行开发规约 / …` 这种散文里的斜杠串必须排除 —— 判据是「首段是不是目录名」。
    if any(" " in s for s in 段[:-1]):
        return 假
    # 路径段里出现非 ASCII 且含中文顿号义的整段（如 `基础模块`），多为中文并列词而非目录
    非路径段 = [s for s in 段[1:] if s and not re.fullmatch(r"[\w.\- ]+", s)]
    if 非路径段:
        return 假
    末段 = 段[-1]
    if "." in 末段 and not 末段.endswith((".py", ".md", ".json", ".sh", ".txt")):
        return 假        # 能力 id 形态（`开工编排.开工准备`）
    return 真


def 查命令指疑(文本: str) -> list[str]:
    """判据③：`` `python3.14 -m <模块>` `` 点名的**项目**模块（含 `.`）是否还存在。

    标准库模块（`unittest` / `py_compile` / `compileall` …）与占位符（`开发工具.xxx`、
    `开发工具.<名>`）一律跳过 —— 它们不指向项目文件，查存在必然假红。

    **末段必须以中文/字母结尾**：`python3.14 -m 开发工具.` 是散文里被截断的写法
    （原文 `python3.14 -m 开发工具.<名>`），不是真模块名。
    """
    问题: list[str] = []
    已见: set[str] = set()
    for 行 in 文本.splitlines():
        if 否定语境句式.search(行):
            continue
        for m in re.finditer(r"python3\.14\s+-m\s+([\w\u4e00-\u9fa5.]+)", 行):
            模块 = m.group(1).rstrip(".")
            if not 模块 or 模块 in 已见:
                continue
            已见.add(模块)
            if 模块 in 标准库模块表 or "." not in 模块 or 占位符句式.search(模块):
                continue
            # 末段为空或纯占位（`开发工具.`、`开发工具.xxx`）→ 不是真模块
            末段 = 模块.rsplit(".", 1)[-1]
            if not 末段 or 末段 in ("xxx", "名", "NN", "XX"):
                continue
            候选 = 系统根 / Path(*模块.split("."))
            if 候选.with_suffix(".py").is_file() or (候选 / "__main__.py").is_file() \
                    or (候选 / "__init__.py").is_file():
                continue
            问题.append(f"点名的模块不存在: python3.14 -m {模块}")
    return 问题


def 查路径指疑(文本: str) -> list[str]:
    """判据①：规则**反引号片段**里点名的仓库相对路径是否还存在。

    逐**行**判断（不是逐片段）：语境豁免是**行级**的 —— 同一行里说「旧路径 X 已不存在」，
    该行整体豁免。跨行豁免会把「上一行讲历史、下一行真指错」也一起放过。
    """
    问题: list[str] = []
    已见: set[str] = set()
    for 行 in 文本.splitlines():
        if 否定语境句式.search(行) or 非本仓语境句式.search(行):
            continue
        for m in 代码片段句式.finditer(行):
            片段 = m.group(1).strip()
            if not 片段:
                continue
            首词 = 片段.split()[0].rstrip("。，、；：）)]}")
            # 片段含空格说明它是**整句**而非单个路径；此时只取首词候选来查，
            # 不要把截断出的半截当路径（实测 `开发文档/规范/Markdown 文档体例规范.md`
            # 会被截成 `开发文档/规范/Markdown` 而假红）。
            候选表 = [首词] if " " in 片段 else [片段, 首词]
            for 路径 in 候选表:
                路径 = 路径.strip()
                if not 路径 or 路径 in 已见 or not _是路径形态(路径):
                    continue
                if 段皆类型枚举(路径):
                    continue
                已见.add(路径)
                if not _路径存在(路径):
                    问题.append(f"点名路径不存在: {路径}")
    return 问题


def 段皆类型枚举(路径: str) -> bool:
    """路径各段是否**全是包类型名枚举**（`支持库/基础模块/功能模块`）——那不是目录。

    实测样本：`项目说明.md:441` 写「装配器只认 `支持库/基础模块/功能模块`」，
    讲的是**可装配类型枚举**，不是三级目录；判它漂移会让执行者把这句话删掉。
    """
    段 = [s for s in re.split(r"::|:\d+$", 路径)[0].rstrip("/").split("/") if s]
    return bool(段) and all(s in 类型枚举词 for s in 段)


def 查锚点指疑(文本: str) -> list[str]:
    """判据②：`原文位置` 的 `文件#锚` 锚点是否真能在文件里找到。"""
    问题: list[str] = []
    for m in re.finditer(r"原文位置\s*[：:]\s*(\S+)", 文本):
        锚 = m.group(1).strip()
        文件, _, 片段 = 锚.partition("#")
        if not 文件:
            continue
        路径 = 系统根 / 文件
        if not 路径.is_file():
            问题.append(f"原文位置的文件不存在: {文件}（锚 {锚}）")
            continue
        if not 片段:
            continue
        try:
            正文 = 路径.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            问题.append(f"原文位置的文件不可读: {文件}")
            continue
        号 = re.sub(r"[^\d]", "", 片段)
        标题 = [行 for 行 in 正文.splitlines()
              if 行.lstrip().startswith("#") and 号 and 号 in 行]
        if not 标题:
            问题.append(f"原文位置的锚点对不上: {锚}（{文件} 里无含「{号}」的标题）")
    return 问题


def 规则文件表() -> list[Path]:
    """全部规则类文件（规范目录下的 .md/.json + 根规则文档）。"""
    表 = [p for p in sorted(规范目录.glob("*.md")) if p.is_file()]
    表 += [p for p in sorted(规范目录.glob("*.json")) if p.is_file()]
    表 += [p for p in 根规则文件 if p.is_file()]
    return 表


def 体检() -> list[str]:
    """逐份规则文件跑三类判据，返回（文件, 问题）文本列表。"""
    问题表: list[str] = []
    for 路径 in 规则文件表():
        try:
            文本 = 路径.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            问题表.append(f"{路径.name}: 不可读")
            continue
        相对 = 路径.relative_to(系统根).as_posix()
        for 项 in 查路径指疑(文本):
            问题表.append(f"{相对}: {项}")
        for 项 in 查锚点指疑(文本):
            问题表.append(f"{相对}: {项}")
        for 项 in 查命令指疑(文本):
            问题表.append(f"{相对}: {项}")
    return 问题表


def 主函数(argv: list[str] | None = None) -> int:
    解析器 = argparse.ArgumentParser(description="规范漂移体检：规则文件的指向是否还存在")
    解析器.add_argument("--只报", action="store_true", help="只报告，不改退出码语义")
    解析器.parse_args(argv)
    问题表 = 体检()
    for 问题 in 问题表[:60]:
        print(f"  [漂移] {问题}")
    if len(问题表) > 60:
        print(f"  …（另有 {len(问题表) - 60} 条）")
    print(f"规范漂移体检：扫描 {len(规则文件表())} 份规则文件，漂移 {len(问题表)} 条")
    if 问题表:
        print("⇒ 有规则指向已不存在的东西（规范不可执行，必须同步）")
        return 1
    print("⇒ 全部指向均现场存在")
    return 0


if __name__ == "__main__":
    raise SystemExit(主函数())
