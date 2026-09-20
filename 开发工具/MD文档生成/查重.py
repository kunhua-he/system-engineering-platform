"""文档生成 · 查重：落盘前判断「这内容是不是已经在别处写过了」。

华哥 2026-09-20 口径（原文）：

> 「有没有办法这个生成器，可以排查相似性？就是尽量写的时候，可以判断一下，
>   有没有重复的落盘了。**不然就变成了这里写一下，那里写一下，变成了文案都几条腿来。**」

## 为什么必须是「生成器自带」而不是另做一个工具

华哥要的是**写的时候就判**（落盘前拦一下），不是事后审计。所以它长在生成器里：
`--查重`（核验形态）与 `--新建 --查重`（出骨架前先查）。

## 判据怎么算（两级，先粗筛再精算）

1. **粗筛（便宜）**：把每份 md 归一化（去围栏、去空白、取字符 3-gram 集合），
   按 **Jaccard 相似度** 算粗略重合度，取前 N 名 —— 这一步避免 500×500 全量精算。
2. **精算（准）**：对短名单用 `difflib.SequenceMatcher` 算**文本相似比**（std 库，
   与本仓 `开发工具/说明书生成/合并重生成.py` 同一实现血统，不引第三方）。

**阈值是判据不是结论**：默认报 `≥0.40` 的（够像了才提醒），`≥0.70` 标为「高度疑似重复」。
阈值可由 `--阈值` 覆盖 —— 因为「该不该合并」最终是人的判断，机器只负责**把候选摆到面前**。

## 边界（如实声明，不包装成绝对保证）

- 它比的是**字面相似**，不做语义理解：换了说法讲同一件事（同义改写）**查不出来**；
- 反之，结构相同但内容不同的件（如同一模板出的两份说明书）**会报高相似**——
  这类要人看一眼再决定，机器不代替裁决。

⇒ 定位：**降噪器**，不是「重复检测的绝对边界」（哲学 9.5②：不许包装成绝对边界）。
"""

from __future__ import annotations

import difflib
import re
from pathlib import Path

#: 豁免目录（与生成器其它部分同一口径）
豁免前缀 = (".git/", "工程缓存/", "开发文档/参考资料/", "开发文档/归档/", "__pycache__/")

#: 默认阈值：报告这些以上的候选
默认报告阈值 = 0.40
#: 高度疑似重复
默认高度阈值 = 0.70

围栏 = re.compile(r"^\s*(```|~~~)")
非内容 = re.compile(r"[\s，。、；：！？（）「」『』【】《》…—·\-—_*|>#`\[\]()\"'=+:,.!?;/\\]+")


def 归一文本(文本: str) -> str:
    """去掉代码围栏内的内容与全部标点空白，只留「说了什么」的字符骨架。"""
    行表: list[str] = []
    在内 = False
    for 行 in 文本.splitlines():
        if 围栏.match(行):
            在内 = not 在内
            continue
        if 在内:
            continue
        行表.append(行)
    return 非内容.sub("", "\n".join(行表))


def 切片集合(归一: str, 宽: int = 3) -> set[str]:
    return {归一[i:i + 宽] for i in range(0, max(0, len(归一) - 宽 + 1))}


def 粗相似(甲: set[str], 乙: set[str]) -> float:
    if not 甲 or not 乙:
        return 0.0
    交 = len(甲 & 乙)
    return 交 / (len(甲) + len(乙) - 交)


def 精相似(甲: str, 乙: str) -> float:
    return difflib.SequenceMatcher(None, 甲, 乙).ratio()


class 库:
    """全仓 md 的查重索引（构造时读一遍，之后反复查）。"""

    def __init__(self, 项目根: Path, 排除: str | None = None):
        self.项目根 = 项目根
        self.条目: list[tuple[str, str, set[str]]] = []      # (相对路径, 归一文本, 3-gram 集合)
        for 路径 in sorted(项目根.rglob("*.md")):
            相对 = 路径.relative_to(项目根).as_posix()
            if any(相对.startswith(x) for x in 豁免前缀):
                continue
            if 排除 and 相对 == 排除:
                continue
            try:
                文本 = 路径.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            归一 = 归一文本(文本)
            if len(归一) < 50:                              # 太短的（占位/索引）不参与
                continue
            self.条目.append((相对, 归一, 切片集合(归一)))

    def 查(self, 待查文本: str, 取前: int = 5) -> list[tuple[str, float]]:
        """返回 [(相对路径, 相似度)] 降序；两级算法（先 Jaccard 粗筛，再 difflib 精算）。"""
        待归一 = 归一文本(待查文本)
        if len(待归一) < 50:
            return []
        待集 = 切片集合(待归一)
        # ① 粗筛：按 Jaccard 取前 待前 名（至少 12 个，避免精算漏掉）
        粗 = sorted(((粗相似(待集, 集), 相对) for 相对, _, 集 in self.条目),
                   reverse=True)[:max(12, 取前)]
        # ② 精算：对粗筛出的做 SequenceMatcher
        精 = [(相对, 精相似(待归一, self._归一(相对))) for _, 相对 in 粗]
        return sorted(精, key=lambda x: -x[1])[:取前]

    def _归一(self, 相对: str) -> str:
        for 路径, 归一, _ in self.条目:
            if 路径 == 相对:
                return 归一
        return ""


def 查文件(项目根: Path, 相对: str, 取前: int = 5) -> list[tuple[str, float]]:
    """查一份**已存在**的文件与其他文件的相似度（自身排除）。"""
    路径 = 项目根 / 相对
    文本 = 路径.read_text(encoding="utf-8")
    return 库(项目根, 排除=相对).查(文本, 取前=取前)
