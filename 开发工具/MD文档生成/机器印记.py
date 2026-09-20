"""文档生成 · 机器印记：区分「生成器管理的 md」与「手写的 md」，手写一律拒绝。

华哥 2026-09-20 口径（原文）：

> 「后面可以新增这个生成器的原子能力，文档类型等，但是**不能手动写 md**，
>   **全部手动写的 md 都直接拒绝**。就行了。」

## 印记长什么样

紧跟 H1 之后插一行 HTML 注释（Markdown 渲染时不显示，机器解析无歧义）：

```text
<!-- 机器管理｜类型：决策记录｜生成器：开发工具.MD文档生成 -->
```

**语义（不是「每个字都是机器写的」）**：本文件在生成器管理下 —— 生成区（骨架、元信息头、
账目块、编号）由生成器维护，**人工区**（判断、结论、取舍理由）由人写。这正是体例规范 §3.2
「生成区与人工区」的操作化：**人只填内容，不整篇手写**。

## 为什么印记本身就是登记表

印记**写在文件里**，不另存一份「已采纳清单」：多一份清单就多一个会漂移的第二事实源
（哲学 1.2）。文件被删、被改名、被复制时，印记跟着它走，判据永远与现场一致。
"""

from __future__ import annotations

import re
from pathlib import Path

印记前缀 = "<!-- 机器管理｜类型："
印记正则 = re.compile(r"^<!-- 机器管理｜类型：(.+?)｜生成器：(.+?) -->\s*$")


def 造印记(类型名: str) -> str:
    return f"{印记前缀}{类型名}｜生成器：开发工具.MD文档生成 -->"


def 找印记(行表: list[str]) -> int | None:
    for i, 行 in enumerate(行表):
        if 印记正则.match(行):
            return i
    return None


def 取印记(行表: list[str]) -> tuple[str, str] | None:
    位 = 找印记(行表)
    if 位 is None:
        return None
    m = 印记正则.match(行表[位])
    return (m.group(1), m.group(2)) if m else None


def 插入位置(行表: list[str]) -> int:
    """印记插在 H1（及其后紧跟的引用块）之后，**前面留一个空行**分隔。"""
    实 = next((i for i, 行 in enumerate(行表) if 行.startswith("# ")), None)
    if 实 is None:
        return 0
    位 = 实 + 1
    while 位 < len(行表) and (行表[位].startswith(">") or 行表[位].strip() == ""):
        if 行表[位].strip() == "" and 位 + 1 < len(行表) and not 行表[位 + 1].startswith(">"):
            break
        位 += 1
    return 位


def 加印记(项目根: Path, 相对: str, 类型名: str) -> tuple[int, list[str]]:
    """给文件加机器印记；已加则不重复（幂等）。"""
    路径 = 项目根 / 相对
    文本 = 路径.read_text(encoding="utf-8")
    行表 = 文本.splitlines()
    现行 = 取印记(行表)
    if 现行:
        if 现行[0] == 类型名:
            return 0, [f"  已是机器管理（类型 {类型名}）"]
        位 = 找印记(行表)
        assert 位 is not None
        行表[位] = 造印记(类型名)
        路径.write_text("\n".join(行表) + ("\n" if 文本.endswith("\n") else ""),
                    encoding="utf-8")
        return 0, [f"  印记类型更正：{现行[0]} → {类型名}"]
    位 = 插入位置(行表)
    新表 = 行表[:位] + [造印记(类型名), ""] + 行表[位:]
    路径.write_text("\n".join(新表) + ("\n" if 文本.endswith("\n") else ""), encoding="utf-8")
    return 0, [f"  已加机器印记：{造印记(类型名)}"]


def 有印记(项目根: Path, 相对: str) -> bool:
    return 取印记((项目根 / 相对).read_text(encoding="utf-8").splitlines()) is not None


def 豁免前缀(项目根: Path) -> tuple[str, ...]:
    """从**判据文件**读「豁免目录」（唯一真源），失败退回内置最小值。

    原先各调用点各抄一份硬编码（`机器印记` 没有、`查重._n前缀` 又抄了一份），
    而判据文件 `文档类型判据.json` 的 `豁免` 字段**从没被读过** ⇒ 声明与实现不符：
    实测 `--待归一清单` 把豁免的 `开发文档/参考资料/`（168 份）、`开发文档/归档/`（6 份）
    一并列成「待归一」，而 `--列出` 的类型枚举又正确跳过它们 —— **同一份判据两套行为**
    （哲学 1.2：不留第二套）。改为一处读取、全仓共用。
    """
    import json
    try:
        数据 = json.loads(
            (项目根 / "开发文档/规范/文档类型判据.json").read_text(encoding="utf-8"))
        表 = tuple(str(x) for x in (数据.get("豁免") or []) if str(x).strip())
        if 表:
            return 表
    except (OSError, ValueError):
        pass
    return ("工程缓存/", "开发文档/参考资料/", "开发文档/归档/")


def 是豁免(项目根: Path, 相对: str) -> bool:
    return any(相对.startswith(x) for x in 豁免前缀(项目根))


def 全仓待归一(项目根: Path) -> list[str]:
    """全仓 tracked .md 里**没有机器印记**的相对路径（升序）——即「手写、尚未归一」的清单。

    **豁免目录不进清单**（判据文件 `豁免` 字段是唯一真源；`.git/`/`__pycache__/` 不可能是
    tracked 文件，无需另判）。豁免件本来就「不要求机器管理」，列进来只会虚报待办量。
    """
    输出 = _git(项目根, "ls-files", "*.md")
    相对表 = [x.strip() for x in 输出.splitlines() if x.strip()]
    return sorted(相对 for 相对 in 相对表
                  if not 是豁免(项目根, 相对) and not 有印记(项目根, 相对))


def _git(项目根: Path, *参数: str) -> str:
    import subprocess
    from pathlib import Path as _P
    二进制 = "/Library/Developer/CommandLineTools/usr/bin/git"
    if not _P(二进制).exists():
        二进制 = "git"
    try:
        结果 = subprocess.run([二进制, *参数], cwd=项目根, capture_output=True,
                            text=True, timeout=120, check=False)
    except (OSError, subprocess.SubprocessError):
        return ""
    return 结果.stdout if 结果.returncode == 0 else ""
