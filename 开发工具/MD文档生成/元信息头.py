"""文档生成 · 元信息头：三行的机器侧部分（只生成「最后更新」，另两行是人的判断）。

依据 `开发文档/规范/Markdown 文档体例规范.md` §3.0 的**固定句式**：

```text
> 最后更新：YYYY-MM-DD（可附一句时点限定，如「审计报告落盘当天」）
> 口径：实测 | 历史快照（实测须紧跟取证命令的位置或指向；历史快照须写快照时点）
> 维护者：<文档职责名，不写人名>
```

## 为什么日期从 git 派生，而不是「生成当天」

若生成器把日期打成「跑生成器的那一天」，会有两个必然错误：

1. **假新鲜**：文档内容没变，日期天天变，读者以为刚改过。
2. **每天假红**：`--校验` 拿「今天」当应然，隔夜必与现行不符 —— 门禁天天无故转红，
   这正是本平台反复收口的「假绿/假红」病（哲学 12.4②）。

⇒ 唯一诚实且可机判的口径：**`最后更新` = 该文件最后一次提交的日期**；
文件有未提交改动时（`git status` 脏）取当天 —— 因为那一刻内容确实是新的。
这样「内容没变 ⇒ 日期不动 ⇒ 校验恒过」，把日期变成**事实**而不是**人为动作**。
"""

from __future__ import annotations

import datetime
import subprocess
from pathlib import Path

#: git 必须走真实二进制（`/usr/bin/git` 是 Xcode shim，许可未接受时会 exit 69）
GIT = "/Library/Developer/CommandLineTools/usr/bin/git"

待填口径 = "> 口径：（待填：实测 | 历史快照）"
待填维护者 = "> 维护者：（待填：文档职责名）"


def _git(项目根: Path, *参数: str) -> str:
    二进制 = GIT if Path(GIT).exists() else "git"
    try:
        结果 = subprocess.run([二进制, *参数], cwd=项目根, capture_output=True,
                            text=True, timeout=30, check=False)
    except (OSError, subprocess.SubprocessError):
        return ""
    return 结果.stdout if 结果.returncode == 0 else ""


def 文件是否脏(项目根: Path, 相对: str) -> bool:
    输出 = _git(项目根, "status", "--porcelain", "--", 相对)
    return bool(输出.strip())


def 最后提交日(项目根: Path, 相对: str) -> str:
    """返回该文件最后一次提交的日期（YYYY-MM-DD）；无提交记录返回空串。"""
    输出 = _git(项目根, "log", "-1", "--format=%ad", "--date=short", "--", 相对)
    return 输出.strip().splitlines()[0].strip() if 输出.strip() else ""


def 有实质改动(项目根: Path, 相对: str) -> bool:
    """除「最后更新」行以外还有未提交改动吗（工作区+暂存 vs HEAD）。

    只按 `git status` 判脏会**自相矛盾**：生成器自己把日期写进文件后文件必然变脏，
    于是「应然」跳到当天、刚写的日期立刻不符 ⇒ 判红 → 写盘 → 再判红（死循环）。
    故这里只看**除掉日期行的实质内容**是否变过。
    """
    d = _git(项目根, "diff", "HEAD", "-U0", "--", 相对)
    行 = [x for x in d.splitlines()
          if x[:1] in "+-" and not x.startswith(("+++", "---"))]
    return any("最后更新" not in x for x in 行)


def 应然日期(项目根: Path, 相对: str) -> str:
    """有实质改动 ⇒ 当天（内容确实是新的）；否则 ⇒ 最后一次提交日（事实）。"""
    if 有实质改动(项目根, 相对):
        return datetime.date.today().isoformat()
    提交日 = 最后提交日(项目根, 相对)
    return 提交日 or datetime.date.today().isoformat()


def 应然最后更新行(项目根: Path, 相对: str) -> str:
    return f"> 最后更新：{应然日期(项目根, 相对)}"


def 找元信息头块(行表: list[str]) -> tuple[int, int] | None:
    """返回元信息头块的 (起, 末) 行下标：从首个 `> 最后更新：` 起，连续 `> ` 行为止。"""
    起 = next((i for i, 行 in enumerate(行表) if 行.startswith("> 最后更新：")), None)
    if 起 is None:
        return None
    末 = 起
    while 末 + 1 < len(行表) and 行表[末 + 1].startswith(">"):
        末 += 1
    return 起, 末


def 插入位置(行表: list[str]) -> int:
    """没有元信息头时插在哪：H1 之后紧接的引用块（若紧随）之后，否则 H1 之后。"""
    实 = next((i for i, 行 in enumerate(行表) if 行.startswith("# ")), None)
    if 实 is None:
        return 0
    位 = 实 + 1
    while 位 < len(行表) and 行表[位].strip() == "":
        位 += 1
    while 位 < len(行表) and 行表[位].startswith(">"):
        位 += 1
    return 位
