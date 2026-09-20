"""文档生成 · 统一入口（全项目 Markdown 只走这一个生成器，单一腿）。

华哥 2026-09-20 口径（原文）：

> 「能不能 **1 个统一的生成器**，专门维护去整个项目的 md 文档。
>   你可以**传参**到时候选择是什么类型的文档生成和修改等。」
> 「你把**包级说明，决策记录，方案，权威文档，规范**；这多种类型，**每一种规范一个格式**；
>   然后后面**传参就好了。后面就不能直接写文档了**。」
> 「一定要后面**全部收口好**，这个项目，**全部的编辑，全部归类到项目开发工具**，
>   类似于 **SDK 开发包**的那种一样……全部东西都**单一腿**，都能稳固好整个项目能力。」

⇒ 全仓 md 的编辑只经本入口；格式定义在 `开发文档/规范/文档类型判据.json`（数据侧），
`Markdown 文档体例规范.md` 是唯一真源。**新增一类文档 = 改数据一处，不加代码文件。**

## 用法

```bash
python3.14 -m 开发工具.MD文档生成 --列出                       # 有哪些类型（序号 + 处置方式）
python3.14 -m 开发工具.MD文档生成 --类型 债务清单 --校验         # 核验（门禁形态）
python3.14 -m 开发工具.MD文档生成 --类型 债务清单 --写盘         # 出文档（生成器形态）
python3.14 -m 开发工具.MD文档生成 --序号 2 --全部 --校验         # 按序号跑一整类
python3.14 -m 开发工具.MD文档生成 --类型 决策记录 --新建 --标题 <标题>   # 出骨架
```

**边界切不出即 fail-closed 报错**，绝不猜、绝不整文件重写（防「一次杀完」）。
"""

from __future__ import annotations

import argparse
import datetime
import sys
from pathlib import Path

from 开发工具.MD文档生成 import (文档类型_债务清单, 文档类型_通用, 元信息头,
                              机器印记, 生成区, 类型登记)

#: 有「可刷新生成区」的类型 → 处理函数（按类型名分派）
按类型分派 = {
    "债务清单": 文档类型_债务清单.主流程,
}

#: 走「元信息头」通用动作的类型（权威文档 / 规范）
走元信息头 = ("权威文档", "规范")


def 找项目根() -> Path:
    根 = Path(__file__).resolve()
    while 根.name and not (根 / "开发文档").is_dir():
        根 = 根.parent
    if not (根 / "开发文档").is_dir():
        raise SystemExit("找不到项目根（向上找不到含 开发文档/ 的目录）")
    return 根


def _跑元信息头(项目根: Path, 类型: dict, 写盘: bool,
              单文件: str | None, 允许补头: bool = False) -> tuple[int, list[str]]:
    类型名 = str(类型["类型"])
    if 单文件:
        相对表 = [单文件]
    else:
        相对表 = [p.relative_to(项目根).as_posix()
                 for p in 类型登记.枚举文件(项目根, 类型)]
    if not 相对表:
        return 2, [f"该类型下没找到现存文件（路径判据：{类型.get('路径判据')}）"]
    总码, 行表 = 0, []
    for 相对 in 相对表:
        try:
            if 写盘:
                码, 行 = 文档类型_通用.写元信息头(项目根, 相对, 允许补头)
            else:
                码, 行 = 文档类型_通用.核验元信息头(项目根, 相对)
            # 机器印记：`--写盘` 时同批加上（「机器管理的」标记，手写件靠它被识别）——
            # 无论该文件原有无元信息头都加（印记与元信息头是两件事：印记=归属，头=日期口径）
            if 写盘:
                码2, 行2 = 机器印记.加印记(项目根, 相对, 类型名)
                行 = 行 + 行2
        except 生成区.边界缺失 as 错:
            码, 行 = 2, [f"生成区边界缺失，拒绝处理（fail-closed）：{错}"]
        总码 = max(总码, 码)
        行表.append(f"  [{'写盘' if 写盘 else '核验'}] {相对}")
        行表.extend("      " + x for x in 行)
    return 总码, 行表


def _待归一清单(项目根: Path) -> int:
    """列出全仓仍未归一的 md（tracked、无机器印记）。"""
    清单 = 机器印记.全仓待归一(项目根)
    print(f"MD 文档生成 · 待归一清单（tracked md 里无机器印记者）共 {len(清单)} 份")
    for 相对 in 清单:
        print(f"  {相对}")
    if not 清单:
        print("  （全仓 md 已全部纳入机器管理）")
    return 0


def _拒绝手写校验(项目根: Path) -> int:
    """门禁：**禁止手写 md**。

    华哥 2026-09-20 口径：「后面可以新增这个生成器的原子能力，文档类型等，
    但是**不能手动写 md，全部手动写的 md 都直接拒绝**。」

    判据（存量冻结 / 新增阻断，与本仓既有口径一致）：
    - **本轮改动集**（`git diff HEAD --name-only` + `git status`）里，凡是被
      **修改或新增**的 `.md` 而没有**机器印记** → **判红**（这就是「手写」）；
    - 已存在但本轮没碰的 md 不作红（存量逐批归一，不搞一次性大爆炸）。

    为什么这样切：一次性把 500+ 份存量判红等于门禁永远红、没人能提交（假红）。
    存量靠 `--待归一清单` 逐批推进，闸门只管「新增与本次改动」。
    """
    改动 = 机器印记._git(项目根, "diff", "HEAD", "--name-only", "--diff-filter=ACMR")
    清单 = [x for x in 改动.splitlines() if x.strip().endswith(".md")]
    # ★ 新增的**未跟踪**文件也必须算进来（只查 `git diff HEAD` 会漏掉全新文件 —— 那正是
    #   最典型的「手写 md 绕过生成器」路径；实测 2026-09-20 抓到该漏判）。
    未跟踪 = 机器印记._git(项目根, "ls-files", "--others", "--exclude-standard")
    for x in 未跟踪.splitlines():
        x = x.strip()
        if x.endswith(".md"):
            清单.append(x)
    清单 = sorted(set(清单))
    手写 = [x for x in 清单 if not 机器印记.有印记(项目根, x)]
    印记在 = [x for x in 清单 if x not in 手写]
    print(f"MD 文档生成 · 拒绝手写校验（本轮改动 md {len(清单)} 份）")
    if 印记在:
        for 相对 in 印记在:
            print(f"  [机器管理] {相对}")
    if 手写:
        print(f"**发现手写 md {len(手写)} 份：手写一律拒绝** —— 须走"
              f"`python3.14 -m 开发工具.MD文档生成 --类型 <类型> --写盘 --补头` 加机器印记，"
              f"或改建生成器再生成：")
        for 相对 in 手写:
            print(f"  [手写] {相对}")
        return 1
    print("通过：本轮改动的 md 全部在生成器管理下（无手写）")
    return 0


def _总览(项目根: Path, 全部类型: list[dict]) -> int:
    """逐类归一进度：每类扫全量现存文件，按该类格式判据报「符合 / 待归一份数」。

    华哥口径「生成器弄好之后，就要一点一点看了。整个项目 md 多了个去了。
    保持一下全部统一」⇒ 这条命令就是「一点一点看」的机器版本：一次跑完，
    哪类还没归一、差多少份，一眼看清；归一完再跑应全绿。
    """
    总计符合 = 总计待归一 = 0
    print("MD 文档生成 · 逐类归一进度（每类扫全量现存文件）")
    for x in 全部类型:
        类型名 = str(x.get("类型"))
        文件表 = 类型登记.枚举文件(项目根, x)
        if 类型名 == "债务清单":
            码, _ = 文档类型_债务清单.主流程(项目根, 写盘=False)
            状态 = "符合" if 码 == 0 else "待归一（生成区与正文不一致）"
            符合数, 待数 = (len(文件表), 0) if 码 == 0 else (0, len(文件表))
        elif 类型名 in 走元信息头:
            待 = 有头表 = 0
            for 路径 in 文件表:
                相对 = 路径.relative_to(项目根).as_posix()
                码, _ = 文档类型_通用.核验元信息头(项目根, 相对)
                行表 = 路径.read_text(encoding="utf-8").splitlines()
                if 元信息头.找元信息头块(行表) is None:
                    continue                      # 按自身体例，不计入分母
                有头表 += 1
                if 码 != 0:
                    待 += 1
            符合数, 待数 = 有头表 - 待, 待
            状态 = f"有元信息头 {有头表}/{len(文件表)} 份；其中符合 {符合数}、待归一 {待}"
        else:
            符合数, 待数 = 0, 0
            状态 = f"无生成区可刷（整份属人工区 / 另有唯一生成器）；现存 {len(文件表)} 份"
        总计符合 += 符合数
        总计待归一 += 待数
        print(f"  {x.get('序号')}  {类型名:<6} 现存 {len(文件表):>3} 份  {状态}")
    print()
    print(f"合计：符合 {总计符合} 份，待归一 {总计待归一} 份")
    return 0 if 总计待归一 == 0 else 1


def 主流程(argv: list[str] | None = None) -> int:
    解析 = argparse.ArgumentParser(
        prog="python3.14 -m 开发工具.MD文档生成",
        description="全项目 Markdown 统一生成器：一个入口，传参（类型或序号）选文档类型")
    解析.add_argument("--类型", help="文档类型中文名（--列出 可查）")
    解析.add_argument("--序号", type=int, help="文档类型序号（1 权威文档 / 2 规范 / …）")
    解析.add_argument("--列出", "--列表", dest="列出", action="store_true",
                     help="列出全部文档类型与处置方式")
    组 = 解析.add_mutually_exclusive_group()
    组.add_argument("--写盘", action="store_true", help="出文档（生成器形态）")
    组.add_argument("--校验", action="store_true", help="核验生成区（门禁形态，默认）")
    组.add_argument("--新建", action="store_true", help="按格式出骨架（如决策记录）")
    解析.add_argument("--文件", help="只处理这一个文件（须属该类型路径判据）")
    解析.add_argument("--补头", action="store_true",
                     help="允许给缺元信息头的文件补头（默认只刷已有的，不强加）")
    解析.add_argument("--全部", action="store_true", help="处理该类型下全部现存文件")
    解析.add_argument("--标题", help="--新建 时用的标题（决策记录）")
    解析.add_argument("--今天", help="覆盖生成日期（YYYY-MM-DD，默认系统当天）")
    解析.add_argument("--总览", action="store_true",
                     help="逐类归一进度：每类扫全量文件并按格式判据报红/绿（一条命令看全局）")
    解析.add_argument("--拒绝手写校验", "--手写校验", dest="拒绝手写校验", action="store_true",
                     help="门禁形态：禁止手写 md —— 本轮改动集里出现「无机器印记的 md」即判红"
                          "（存量未归一的不算红，逐批消掉）")
    解析.add_argument("--待归一清单", action="store_true",
                     help="列出全仓仍未归一的 md（无机器印记），供逐批推进")
    args = 解析.parse_args(argv)

    项目根 = 找项目根()
    try:
        全部类型 = 类型登记.取类型表(项目根)
    except 类型登记.类型定义缺失 as 错:
        print(f"文档类型定义不可用：{错}")
        return 2

    if args.总览:
        return _总览(项目根, 全部类型)

    if args.待归一清单:
        return _待归一清单(项目根)

    if args.拒绝手写校验:
        return _拒绝手写校验(项目根)

    if args.列出 or (not args.类型 and args.序号 is None):
        print("MD 文档生成 · 已登记的文档类型（格式定义：开发文档/规范/文档类型判据.json）")
        for x in 全部类型:
            文件数 = len(类型登记.枚举文件(项目根, x))
            print(f"  {x.get('序号')}  {str(x.get('类型')):<6} 现存 {文件数:>3} 份  "
                  f"{str(x.get('处置', ''))[:64]}")
        print()
        print("用法：--类型 <名> 或 --序号 <n>  [--校验|--写盘|--新建] [--全部] [--文件 <路径>]")
        return 0

    try:
        类型 = (类型登记.按名取(项目根, args.类型) if args.类型
               else 类型登记.按序号取(项目根, args.序号))
    except 类型登记.类型定义缺失 as 错:
        print(f"{错}")
        return 2

    今天 = args.今天 or datetime.date.today().isoformat()
    类型名 = str(类型["类型"])
    print(f"MD 文档生成 · {类型名}（序号 {类型.get('序号')}）")

    # ① --新建：出骨架
    if args.新建:
        if 类型名 == "决策记录":
            码, 行表 = 文档类型_通用.出决策骨架(项目根, args.标题 or "", 今天)
        else:
            码, 行表 = 2, [f"「{类型名}」暂未提供出骨架动作（现有：决策记录）"]
        for 行 in 行表:
            print(行)
        return 码

    # ② 按类型分派（有可刷新生成区）
    if 类型名 in 按类型分派:
        try:
            码, 行表 = 按类型分派[类型名](项目根, 写盘=args.写盘, 今天=今天)
        except 生成区.边界缺失 as 错:
            print(f"生成区边界缺失，拒绝写盘（fail-closed）：{错}")
            return 2
        for 行 in 行表:
            print(行)
        return 码

    # ③ 元信息头型（权威文档 / 规范）
    if 类型名 in 走元信息头:
        码, 行表 = _跑元信息头(项目根, 类型, args.写盘,
                               args.文件 if args.文件 else None, args.补头)
        for 行 in 行表:
            print(行)
        return 码

    # ④ 其余类型：如实说明该类型的生成区与唯一生成器，不假装能刷
    print(f"  该类型的生成区：{类型.get('生成区')}")
    print(f"  处置：{类型.get('处置')}")
    if 类型.get("唯一生成器"):
        print(f"  唯一生成器：{类型['唯一生成器']}")
    if 类型.get("核验"):
        print(f"  核验命令：{类型['核验']}")
    print("  （本类型没有可自动刷新的生成区；正文全部属人工区）")
    return 0


if __name__ == "__main__":
    sys.exit(主流程())
