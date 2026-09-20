"""文档生成 · 生成区：通用边界识别与「只换生成区、人工区逐行保留」的合并原语。

设计口径（华哥 2026-09-20）：「你规范了生成器，后面应该是围绕着生成器去出文档才对。」
⇒ 生成器是**文档的生产者**，不是事后校验器。每份文档分两区：

| 区 | 谁写 | 判据 |
|---|---|---|
| 生成区 | 只有生成器 | 出文档后 `git diff` 为空 |
| 人工区 | 人写，生成器**原样保留** | 行级合并零丢失；丢一行即拒绝写盘 |

**边界必须机器无歧义**：两条标记行找不到即 fail-closed 报错，绝不猜（`切不出不猜`）。
"""

from __future__ import annotations

import re

#: 元信息头「最后更新」行（生成区：日期由生成器给）
最后更新行 = re.compile(r"^> 最后更新：")

#: 债务清单账目块的两条边界标记
账目起 = "> **当前真实账目"
账目尾 = "> **不计入待办的三类**"


class 边界缺失(Exception):
    """生成区标记行找不到：拒绝猜测，由调用方转明确失败。"""


def 找最后更新(行表: list[str]) -> int:
    """返回「> 最后更新：」行下标；找不到抛 边界缺失。"""
    for i, 行 in enumerate(行表):
        if 最后更新行.match(行):
            return i
    raise 边界缺失("找不到元信息头「> 最后更新：」行")


def 找账目块(行表: list[str]) -> tuple[int, int]:
    """返回账目块 (起, 末) 下标；末 = 引用块最后一行的下标。"""
    起 = next((i for i, 行 in enumerate(行表) if 行.startswith(账目起)), None)
    尾 = next((i for i, 行 in enumerate(行表) if 行.startswith(账目尾)), None)
    if 起 is None or 尾 is None:
        缺 = []
        if 起 is None:
            缺.append("起标记「" + 账目起 + "」")
        if 尾 is None:
            缺.append("尾标记「" + 账目尾 + "」")
        raise 边界缺失("找不到账目块 " + "、".join(缺))
    末 = 尾
    while 末 + 1 < len(行表) and 行表[末 + 1].startswith(">"):
        末 += 1
    return 起, 末


def 零丢失校验(原文本: str, 新文本: str, 人工区: list[str]) -> None:
    """人工区每一行都必须在新文本里出现且不减少；违反抛 边界缺失（拒绝写盘）。"""
    for 行 in 人工区:
        if 行 and 新文本.count(行) < 原文本.count(行):
            raise 边界缺失("人工行丢失，拒绝写盘：" + 行[:80])


def 换元信息头(文本: str, 新行: str) -> str:
    """只替换「最后更新」行；同段其余人工行原样保留。"""
    行表 = 文本.splitlines()
    更新 = 找最后更新(行表)
    行表[更新] = 新行
    return "\n".join(行表) + ("\n" if 文本.endswith("\n") else "")


def 换账目块(文本: str, 新块: list[str]) -> str:
    """只替换账目块；块外逐行原样保留，并做人工区零丢失自检。"""
    行表 = 文本.splitlines()
    起, 末 = 找账目块(行表)
    人工区 = 行表[:起] + 行表[末 + 1:]
    新文本 = "\n".join(行表[:起] + 新块 + 行表[末 + 1:])
    零丢失校验(文本, 新文本, 人工区)
    return 新文本 + ("\n" if 文本.endswith("\n") else "")


def 取账目块(文本: str) -> list[str]:
    """取现行账目块（含边界行）。"""
    行表 = 文本.splitlines()
    起, 末 = 找账目块(行表)
    return 行表[起:末 + 1]


def 取元信息头(文本: str, 行数: int = 4) -> list[str]:
    """取现行元信息头若干行（只看「> 」引用块）。"""
    return [行 for 行 in 文本.splitlines()[:行数] if 行.startswith("> ")]
