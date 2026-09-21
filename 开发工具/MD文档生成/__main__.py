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

from 开发工具.MD文档生成 import (人工编辑, 文档类型_债务清单, 文档类型_目录树与命令,
                              文档类型_通用, 元信息头, 机器印记, 查重, 生成区, 类型登记)
from 开发工具.MD文档生成.说明书 import 类型入口 as _说明书入口

#: 有「可刷新生成区」的类型 → 处理函数（按类型名分派）
按类型分派 = {
    "债务清单": 文档类型_债务清单.主流程,
    "包级说明-目录树与命令": 文档类型_目录树与命令.主流程,
    "包级说明-使用说明": _说明书入口.主流程,
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


def _查重(项目根: Path, 类型: dict | None, 单文件: str | None,
         阈值: float | None, 取前: int) -> int:
    """查重：把「准备落盘的内容」与全仓比一遍，报相似候选（防同一件事写好几处）。

    两种用法：
    - `--查重 --类型 <类型>`：把该类现存文件逐个与**其它**文件比（找已有重复）；
    - `--查重 --文件 <路径>`：只查这一份。
    """
    报阈 = 阈值 if 阈值 is not None else 查重.默认报告阈值
    if 单文件:
        相对表 = [单文件]
    elif 类型 is not None:
        相对表 = [p.relative_to(项目根).as_posix()
                 for p in 类型登记.枚举文件(项目根, 类型)]
    else:
        print("请给 `--类型 <类型>` 或 `--文件 <路径>`（或加 --全部 扫全仓）")
        return 2
    if not 相对表:
        print("该类型下没找到现存文件")
        return 2
    库 = 查重.库(项目根)
    print(f"MD 文档生成 · 查重（{len(相对表)} 份待查；报阈 {报阈:.2f}，"
          f"≥{查重.默认高度阈值:.2f} 为高度疑似重复）")
    命中数 = 0
    for 相对 in 相对表:
        路径 = 项目根 / 相对
        if not 路径.is_file():
            print(f"  ! 不存在：{相对}")
            continue
        文本 = 路径.read_text(encoding="utf-8")
        待归一 = 查重.归一文本(文本)
        if len(待归一) < 50:
            continue
        待集 = 查重.切片集合(待归一)
        粗 = sorted(((查重.粗相似(待集, 集), 他) for 他, _, 集 in 库.条目
                    if 他 != 相对), reverse=True)[:max(12, 取前)]
        候选 = [(他, 查重.精相似(待归一, 库._归一(他))) for _, 他 in 粗]
        候选 = [x for x in sorted(候选, key=lambda t: -t[1]) if x[1] >= 报阈][:取前]
        if not 候选:
            continue
        命中数 += 1
        print(f"\n  {相对}")
        for 他, 分 in 候选:
            标 = "★高度疑似重复" if 分 >= 查重.默认高度阈值 else "疑似"
            print(f"    {标} {分:.2f}  {他}")
    print()
    if 命中数 == 0:
        print(f"无相似度 ≥{报阈:.2f} 的候选（{len(相对表)} 份）")
        return 0
    print(f"**{命中数} 份有相似候选** —— 落盘前先看：该不该合并到已有那份，"
          f"而不是另起一处（防「同一件事写好几条腿」）")
    return 1


def _查重全仓(项目根: Path, 阈值: float | None, 取前: int) -> int:
    """全仓查重：找「同一件事写了好几处」的候选对（只读，供人裁决合并）。"""
    报阈 = 阈值 if 阈值 is not None else 查重.默认报告阈值
    库 = 查重.库(项目根)
    print(f"MD 文档生成 · 全仓查重（{len(库.条目)} 份参与；报阈 {报阈:.2f}，"
          f"≥{查重.默认高度阈值:.2f} 为高度疑似重复）")
    对表: list[tuple[float, str, str]] = []
    条目 = 库.条目
    for i in range(len(条目)):
        for j in range(i + 1, len(条目)):
            甲路, 甲归一, 甲集 = 条目[i]
            乙路, 乙归一, 乙集 = 条目[j]
            if 查重.粗相似(甲集, 乙集) < 报阈:
                continue                       # 粗筛：先便宜地滤掉
            分 = 查重.精相似(甲归一, 乙归一)
            if 分 >= 报阈:
                对表.append((分, 甲路, 乙路))
    对表.sort(reverse=True)
    if not 对表:
        print(f"无相似度 ≥{报阈:.2f} 的文档对（{len(库.条目)} 份两两比过）")
        return 0
    print(f"\n发现 {len(对表)} 对相似文档（降序，只列前 {取前 * 10} 条）：")
    for 分, 甲, 乙 in 对表[:取前 * 10]:
        标 = "★高度疑似重复" if 分 >= 查重.默认高度阈值 else "疑似"
        print(f"  {标} {分:.2f}")
        print(f"      {甲}")
        print(f"      {乙}")
    print()
    print("**这是降噪器不是裁决器**：报的是**字面相似**候选，同义改写查不出来、"
          "同模板出的不同内容的件会报高相似。该不该合并由人看一眼决定。")
    return 1


def _加印记(项目根: Path, 类型: dict, 单文件: str | None) -> int:
    """把该类现存文件纳入机器管理（只加印记，不动正文、不刷生成区）。

    **归属复核（必须）**：`--类型` 是按路径判据枚举的，而兜底类（路径判据 `**/*.md`）
    会把前面所有类型的文件一并枚举进来；若照单全加，就会把已登记件的印记类型**覆写**
    成兜底类名（实测 2026-09-22：41 份 `分析` / `权威文档` 被刷成 `仓库内其他文档`）。
    故每份先按**优先级取首个匹配类型**复核归属，不属于本类的跳过（`--文件` 显式指定时不跳，
    那是调用方的明确意图）。
    """
    类型名 = str(类型["类型"])
    if 单文件:
        相对表 = [单文件]
    else:
        相对表 = [p.relative_to(项目根).as_posix()
                 for p in 类型登记.枚举文件(项目根, 类型)]
    if not 相对表:
        print(f"该类型下没找到现存文件（路径判据：{类型.get('路径判据')}）")
        return 2
    新加 = 已有 = 跳过 = 0
    for 相对 in 相对表:
        if not 单文件:
            归属 = 类型登记.命中类型(项目根, 相对)
            if 归属 is not None and str(归属.get("类型")) != 类型名:
                跳过 += 1
                continue
        码, 行 = 机器印记.加印记(项目根, 相对, 类型名)
        if 码 != 0:
            for x in 行:
                print(f"  ! {相对}: {x}")
            continue
        if any("已加机器印记" in x for x in 行):
            新加 += 1
            print(f"  [新加] {相对}")
        else:
            已有 += 1
    print(f"共 {len(相对表)} 份：新加印记 {新加}、已在机器管理 {已有}、归属他类已跳过 {跳过}")
    return 0


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
    组.add_argument("--加印记", action="store_true",
                     help="只加机器印记（把该类型的现存文件纳入机器管理；无生成区的类型用它）")
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
    解析.add_argument("--人工改", action="store_true",
                     help="人工改正文的唯一通道：--文件 <目标> + --正文文件 <草稿>"
                          "（校验类型判据与生成区，落盘并加印记；加 --写盘 才写入）")
    解析.add_argument("--正文文件", help="--人工改 用的草稿文件路径（人先写草稿，不直接写目标）")
    解析.add_argument("--查重", action="store_true",
                     help="查重：落盘前判断「这条内容是不是已经在别处写过了」（防几条腿）")
    解析.add_argument("--阈值", type=float, default=None,
                     help="查重报告阈值（默认 0.40；≥0.70 标为高度疑似重复）")
    解析.add_argument("--取前", type=int, default=5, help="查重返回前 N 名（默认 5）")
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

    # 「人工参与，但经生成器写」的唯一通道（华哥：禁止直接写，可以通过生成器写）
    if args.人工改:
        if not args.文件 or not args.正文文件:
            print("用法：--人工改 --文件 <目标路径> --正文文件 <草稿路径> [--写盘]")
            return 2
        return 人工编辑.入口(["--人工改", "--文件", args.文件, "--正文文件", args.正文文件]
                          + (["--写盘"] if args.写盘 else []))

    if args.查重:
        if not args.类型 and args.序号 is None and not args.文件:
            # 全仓模式：所有类型合起来查
            return _查重全仓(项目根, args.阈值, args.取前)
        类型 = None
        if args.类型 or args.序号 is not None:
            try:
                类型 = (类型登记.按名取(项目根, args.类型) if args.类型
                       else 类型登记.按序号取(项目根, args.序号))
            except 类型登记.类型定义缺失 as 错:
                print(f"{错}")
                return 2
        return _查重(项目根, 类型, args.文件 if args.文件 else None,
                    args.阈值, args.取前)

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

    # ①之2 --加印记：只把现存文件纳入机器管理（无生成区的类型用它）
    if args.加印记:
        return _加印记(项目根, 类型, args.文件 if args.文件 else None)

    # ② 按类型分派（有可刷新生成区）
    if 类型名 in 按类型分派:
        # `--文件 <路径>` 必须透传：不透传时「定向校验一份」会静默变成「扫全量」，
        # 且被定向的那份是否真红无从而知（实测：弄坏一份后仍报全绿）。
        # 用**签名嗅探**决定传不传（不用 `except TypeError` 兜底 —— 那会把函数体内的
        # 真 TypeError 一起吞掉，正是「宽 except 把故障伪装成正常」那一类）。
        import inspect
        处理 = 按类型分派[类型名]
        可传单文件 = "单文件" in inspect.signature(处理).parameters
        单文件 = args.文件 if args.文件 else None
        try:
            码, 行表 = (处理(项目根, 写盘=args.写盘, 今天=今天, 单文件=单文件)
                      if 可传单文件 else 处理(项目根, 写盘=args.写盘, 今天=今天))
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
