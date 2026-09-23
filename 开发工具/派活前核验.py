"""派活前核验：这条待办是否已经被修好了？（防止重复派活白耗子代理）。

**为什么需要它（2026-09-18 主会话实测教训）**：
主会话按 `未完成事项.md` 条目批量派了 12 路，其中 **6 路开工后发现「缺陷早已在批A
（提交 `97ca5792`）修完」**——子代理正确地停下并改做独立复核，但整批仍白耗约 30 分钟。
根因不是条目没写清楚，是**派活流程缺一步「先核验该条是否已闭合」**。按哲学 14.3
（反复犯错的开发要补底层），补的是流程里那个缺口，不是再叮嘱一次。

**它怎么判**：对指定文件查 git 历史——最近几次改动、以及按关键词（`-S` 代码增删 +
`--grep` 提交信息）命中的提交。有命中 ⇒ 很可能已修，**改派「独立复核 + 反向验证」**。

用法：
    python3.14 开发工具/派活前核验.py --文件 运行核心/权威状态.py --关键词 A1 原子性
    python3.14 开发工具/派活前核验.py --多条 未完成事项.md
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

# 系统根必须在取正式类型名**之前**算好并插入 sys.path —— 否则全新解释器
# 下 `from 公共契约...` 会 ModuleNotFoundError（本工具的调用方常年在仓库外跑）。
# 边界项（批G L3 类2，**保留**）：本行是 `sys.path` 引导，必须在本文件下方
# `from 公共契约…` **之前**算好 —— 引导期 `公共契约` 尚不可导入，故不能改调唯一腿。
# 且唯一腿 `平台适配.解析路径` 只提供「显式根 → 环境变量 系统平台_项目根 → 进程 cwd」
# 三级兜底，**没有**「按本文件推本工具仓根」这一档；本工具常年在仓库外跑、必须认
# **自己所在的那棵树**，故该根保留自推。拼根已全部改调 `解析路径`（见本文件主函数）。
系统根 = Path(__file__).resolve().parents[1]
if str(系统根) not in sys.path:
    sys.path.insert(0, str(系统根))

from 公共契约.基础类型.逻辑类型 import 真, 假
from 公共契约.运行时.平台适配 import 解析路径

git = "/Library/Developer/CommandLineTools/usr/bin/git"


def 跑(参数: list[str]) -> str:
    """跑一条 git 命令；失败返回空串（不抛，核验工具本身不该阻断流程）。"""
    try:
        结果 = subprocess.run([git, *参数], cwd=系统根, capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return 结果.stdout.strip()


def 查文件(文件: str, 关键词: list[str]) -> dict:
    """对一个文件：最近提交 + 关键词命中的提交。"""
    最近 = 跑(["log", "--oneline", "-5", "--date=short", "--format=%h %ad %s", "--", 文件])
    命中: list[tuple[str, str]] = []
    for 词 in 关键词:
        段 = 跑(["log", "--oneline", "-3", f"-S{词}", "--", 文件]) or 跑(["log", "--oneline", "-3", f"--grep={词}", "--", 文件])
        if 段:
            命中.append((词, 段))
    return {"最近提交": 最近, "关键词命中": 命中}


def _打印(文件: str, 果: dict) -> bool:
    print(f"=== {文件} ===")
    print("最近 5 次改动：")
    print("  " + (果["最近提交"].replace("\n", "\n  ") if 果["最近提交"] else "（无提交记录）"))
    if 果["关键词命中"]:
        print("关键词命中（**先读这些提交，再决定派不派活**）：")
        for 词, 段 in 果["关键词命中"]:
            print(f"  [{词}] " + 段.replace("\n", "\n        "))
        return 真
    print("关键词无命中（该缺陷可能尚未修，可派活）")
    return 假


def 读HEAD(相对路径: str) -> str | None:
    """读 HEAD 版本的文件内容（**基准取 HEAD 不取工作树**）。

    并行维修期工作树里有别人的在途改动，拿工作树当基准会把「别人正在改」
    误判成「前提失效」。返回 None 表示 HEAD 中不存在该文件。
    """
    段 = 跑(["show", f"HEAD:{相对路径}"])
    return 段 if 段 else None


_全仓路径表: list[str] | None = None


def 取全仓路径表() -> list[str]:
    """HEAD 里全部文件路径（只取一次，供「包内相对路径」判据用）。"""
    global _全仓路径表
    if _全仓路径表 is None:
        _全仓路径表 = [行 for 行 in 跑(["ls-tree", "-r", "--name-only", "HEAD"]).splitlines() if 行]
    return _全仓路径表


def 核验落点(文本: str) -> list[dict]:
    """从任务包文本抽落点（`路径` 或 `路径:行号`），逐个对 HEAD 核验。

    判据四态：
      - **成立**：HEAD 里有该文件，且（给了行号时）行号在文件行数范围内；
      - **包内相对**：不是仓库根相对路径，但能以「后缀匹配」在全仓唯一命中 ——
        给出候选全路径（子代理需要它，否则会自己找一遍）；
      - **失效**：HEAD 里找不到（路径写错，或还没提交）；
      - **漂移**：文件在，但行号超出 HEAD 行数（文件已大幅变动，子代理会扑空）。

    **只收真落点**：含 `/` 的仓库内路径才算；散文里提一句的裸文件名（如
    `完整性摘要.json`）和占位路径（如 `<任务名>_回传.md`）一律跳过 ——
    否则工具会天天假报警，很快没人看。
    """
    行号模式 = re.compile(r"`([^`\s]+?\.(?:py|json|md|plist|sh|js|ts|html|txt)):(\d+)`")
    路径模式 = re.compile(r"`([^`\s]+?\.(?:py|json|md|plist|sh|js|ts|html|txt))`")
    已见: set = set()
    结果: list[dict] = []
    for 模式 in (行号模式, 路径模式):
        for m in 模式.finditer(文本):
            路径 = m.group(1)
            行号 = int(m.group(2)) if m.lastindex and m.lastindex >= 2 and m.group(2) else None
            if (路径.startswith("/") or " " in 路径 or "/" not in 路径
                    or "<" in 路径 or ">" in 路径 or (路径, 行号) in 已见):
                continue
            if any(k[0] == 路径 for k in 已见):
                continue
            已见.add((路径, 行号))
            条目 = {"落点": f"{路径}{':' + str(行号) if 行号 else ''}", "状态": "", "说明": ""}
            内容 = 读HEAD(路径)
            if 内容 is None:
                候选 = [p for p in 取全仓路径表() if p.endswith("/" + 路径)]
                if 候选:
                    条目["状态"] = "包内相对"
                    条目["说明"] = f"非根相对路径；候选：{'、'.join(候选[:3])}"
                else:
                    条目["状态"] = "失效"
                    条目["说明"] = "HEAD 中不存在（路径写错，或尚未提交）"
            else:
                总行 = 内容.count("\n") + 1
                if 行号 and 行号 > 总行:
                    条目["状态"] = "漂移"
                    条目["说明"] = f"行号 {行号} 超出 HEAD 的 {总行} 行（文件已大幅变动）"
                else:
                    条目["状态"] = "成立"
                    条目["说明"] = f"HEAD {总行} 行" + (f"，行号 {行号} 在范围内" if 行号 else "")
            结果.append(条目)
    return 结果


def 核验任务包(路径: Path) -> int:
    """核验一个任务包的全部落点；返回失效+漂移条数。"""
    结果 = 核验落点(路径.read_text(encoding="utf-8"))
    print(f"\n=== 落点核验：{路径.name} ===")
    if not 结果:
        print("  － 未抽到落点（任务包可能只写了行为、没写路径）")
        return 0
    坏 = 0
    for r in 结果:
        标 = {"成立": "✓", "包内相对": "～", "失效": "✗", "漂移": "⚠"}[r["状态"]]
        if r["状态"] in ("失效", "漂移"):
            坏 += 1
        print(f"  {标} {r['落点']:<56} {r['说明']}")
    print(f"  → 成立 {len([r for r in 结果 if r['状态'] == '成立'])}"
          f" / 包内相对 {len([r for r in 结果 if r['状态'] == '包内相对'])}"
          f" / 失效或漂移 {坏}")
    if 坏:
        print("  判据：**先修任务包落点再派活** —— 带失效落点派出去，子代理会先花十几分钟扑空。")
    return 坏


def 抽允许修改(文本: str) -> tuple[set[str], list[str]]:
    """抽任务包「允许修改」段里的文件路径集合，附带歧义项（多义/未命中的裸名）。

    **认多种标题写法**：`## 允许修改` / `## 可修改` / `## 任务（只改这三个文件）` ——
    实测任务包标题写法不统一，只认一种会让别的包整段漏读，
    查重于是报「无冲突」的**假绿**（比不查更危险）。

    返回 `(确定路径集, 歧义说明表)`：**歧义项不参与撞车比较** ——
    裸文件名（如 `完整性摘要.json`，全仓几十个）不是确定路径，拿它算交集会喷出
    十几对假撞车，真撞车反而被淹没。歧义只作提示。
    """
    段 = ""
    收集中 = 假
    for 行 in 文本.splitlines():
        净行 = 行.strip()
        if 净行.startswith("##") and ("允许修改" in 净行 or "可修改" in 净行 or "只改" in 净行):
            收集中 = 真
            continue
        if 收集中 and 净行.startswith("##"):
            break
        if 收集中:
            段 += 行 + "\n"
    路径集: set[str] = set()
    歧义列表: list[str] = []
    for m in re.finditer(r"`([^`\s]+?\.(?:py|json|md|plist|sh|js|ts|html|txt))(?::\d+)?`?", 段):
        路径 = m.group(1)
        if 路径.startswith("/") or " " in 路径 or "<" in 路径:
            continue
        if "/" in 路径:
            路径集.add(路径)
            continue
        # 裸文件名（如 `本地网关.py`）：任务包常这么写。用全仓路径表解析 ——
        # **唯一命中才算**；多命中或零命中的一律记入歧义列表，不参与撞车比较。
        候选 = [p for p in 取全仓路径表() if p.endswith("/" + 路径)]
        if len(候选) == 1:
            路径集.add(候选[0])
        elif 候选:
            歧义列表.append(f"{路径}（多义，{len(候选)} 处）")
        else:
            # 任务包里的「新增文件」必然未命中 —— 属正常，不算缺陷，也不参与比较。
            歧义列表.append(f"{路径}（未命中，可能是新增文件）")
    return 路径集, 歧义列表


def 查重(目录: Path) -> int:
    """任务包查重：**同一文件出现在两份包的「允许修改」里 ⇒ 两路会撞车或重复派活**。

    为什么必须有（2026-09-18 实测）：主会话另建了 `B6_睡眠唤醒重校准` 与
    `验收K`（内含 O 段），而 `二次审计M`/`二次审计O` 早已存在 ——
    **同一审计条目两份包 = 第二腿**，既浪费子代理又让事实源分裂。

    **同时报「未声明允许修改的包」**：查重只能查声明了范围的包；没声明的包
    等于「范围未知」，必须当成风险报出来（否则就是假绿）。
    """
    包表: list[tuple[str, set[str]]] = []
    未声明: list[str] = []
    歧义汇总: dict[str, list[str]] = {}
    for p in sorted(目录.glob("*.md")):
        文本 = p.read_text(encoding="utf-8")
        集, 歧义 = 抽允许修改(文本)
        if 集:
            包表.append((p.name, 集))
        else:
            未声明.append(p.name)
        if 歧义:
            歧义汇总[p.name] = 歧义
    print(f"\n=== 任务包查重（{len(包表)} 份可查 / {len(未声明)} 份未声明范围）===")
    冲突数 = 0
    for i in range(len(包表)):
        for j in range(i + 1, len(包表)):
            交集 = 包表[i][1] & 包表[j][1]
            if 交集:
                冲突数 += 1
                print(f"  ⚠ 撞车 {包表[i][0]}  ✕  {包表[j][0]}")
                print(f"     共有文件：{'、'.join(sorted(交集))}")
    if 歧义汇总:
        print("  － 未参与比较的裸文件名（多义/疑似新增，仅提示）：")
        for 名, 表 in 歧义汇总.items():
            print(f"     {名}: {'、'.join(表[:4])}")
    if 未声明:
        print(f"  ⚠ 未声明「允许修改」段（范围未知，查重对它们失效）：")
        for 名 in 未声明:
            print(f"     - {名}")
    if 冲突数 or 未声明:
        print(f"  → 撞车 {冲突数} 对 / 未声明 {len(未声明)} 份。判据：")
        print("     ① **同一审计条目只保留一份包**（哲学 1.2 不保留旧腿）；")
        print("     ② 每份包必须有可解析的 `## 允许修改` 段（认 `可修改`/`只改` 同义标题）；")
        print("     ③ 确有先后依赖的（如 L 与 C 同文件），包里写明「等谁收口」且只派一路。")
    else:
        print("  ✓ 无共有文件（可安全并发派活）")
    return 冲突数 + len(未声明)


def _切格(行: str) -> list[str]:
    """markdown 表格行 → 单元格列表；非表格行返回空表。"""
    if not 行.lstrip().startswith("|"):
        return []
    return [x.strip() for x in 行.strip().strip("|").split("|")]


def _是分隔行(格: list[str]) -> bool:
    """`|---|---|` 这种表格分隔行（单元格只由 `-`、`:`、空白组成且非空）。"""
    return bool(格) and all(c and set(c) <= set("-: ") for c in 格)


def 核验债务清单(清单文件: Path) -> int:
    """逐条核验债务清单：抽编号/状态/文件路径，去 git 历史核。

    **为什么要有它（2026-09-18 夜实测）**：清单是「待办线索」不是事实（§8.3.1 已立规），
    但实测 #50/#51/#54/#69 四条都已被提交，清单仍标「未派 / 维修中」——按字面派活就是
    派空任务。本函数把「逐条现场核实」做成一条命令，而不是每次靠人记得。

    **抽法（2026-09-23 重写）**：编号取表首列（数字 / `6b` / `—` / `A` 都认）；
    **状态只认表头里真有「状态/进度」列的表**；文件路径取条目正文里反引号包住的
    `*.py|json|md|plist`，解析走 `核验落点` 同一套「后缀唯一命中」口径（不另起一条腿）。

    **旧版为什么必须重写（2026-09-23 实测，这是本函数改写的唯一理由）**：
    旧版判据是「表首列首字符是数字」，而本清单 §四 的 **103 项首列全是 `—`** ⇒
    旧版把它们**整表跳过**，只看得见 §五 的 4 条，却照样打印
    「可疑 0 条 / 共 4 条」并 **exit 0**（＝报绿）。把「103 项一个字没读」报成
    「检查过且没问题」，正是 AGENTS.md 禁止的假绿（哲学第 3 条 2 项：失败必须明确）。
    旧版 docstring 还声称抽 ✅/⏳/🔧/📋 状态标注 —— 这四个字符在本文件里出现 **0 次**。

    **本版不做什么（2026-09-23 自己踩过的坑）**：初版重写曾把「正文点名的文件在 git 里
    有提交」当成「疑似已修」的线索 —— 那是**恒真**的（`git log -1 -- <文件>` 对任何
    有过提交的文件都非空），51 条线索全是噪声。⇒ 无状态列的表**只报事实**：
    文件的**最后提交日期**、以及**标题是否自称已修**。两者都不构成判定。

    判据（三档，不猜）：
    - **真可疑**：表**有**状态列，且「标完成但 git 查不到提交」/「标在办但文件有提交」；
    - **线索**：表**无**状态列 ⇒ 只报事实，**不判定**（任何 ✓/⚠️ 都是我编的）；
    - **抽不出**：正文里没有可解析的文件路径 ⇒ 如实报「需人核」。
    扫描面为 0 不得记作通过：一条都没读到（表格形态变了）⇒ 返回 2。
    """
    行表 = 清单文件.read_text(encoding="utf-8").splitlines()
    # 表头 = 紧挨分隔行**上面**那一行。只有表头能告诉我这一表到底有没有状态列。
    表头行号 = {i for i in range(len(行表) - 1)
              if _切格(行表[i]) and _是分隔行(_切格(行表[i + 1]))}
    # 编号 / 状态文本 / 有状态列 / 标题列 / 文件
    条目: list[tuple[str, str, bool, str, list[str]]] = []
    跳过 = 0
    当前表头: list[str] = []
    for i, 行 in enumerate(行表):
        格 = _切格(行)
        if not 格:
            当前表头 = []          # 出表：下一张表的表头要重新认（否则会串表）
            continue
        if _是分隔行(格):
            continue               # 分隔行本身不是条目；表头已在上一轮记下
        if i in 表头行号:
            当前表头 = 格
            continue
        # 条目行判据：首列短且不含空格（`4`/`6b`/`—`/`A` 都认；散文首列一律不认并如实计数）。
        if not 格[0] or len(格[0]) > 6 or " " in 格[0]:
            跳过 += 1
            continue
        状态列 = next((k for k, 名 in enumerate(当前表头)
                     if "状态" in 名 or "进度" in 名), None)
        状态 = 格[状态列] if (状态列 is not None and 状态列 < len(格)) else ""
        标题 = 格[1] if len(格) > 1 else ""
        文件 = re.findall(r"`([^`]+\.(?:py|json|md|plist))`", " ".join(格[1:]))
        条目.append((格[0], 状态, 状态列 is not None, 标题,
                    [f for f in dict.fromkeys(文件)][:4]))
    if not 条目:
        print(f"⚠️ 未从 {清单文件.name} 抽出任何条目（表格形态变了？）")
        return 2
    全仓 = 取全仓路径表()
    可疑 = 线索 = 抽不出 = 自称已修 = 0
    print(f"逐条核验 {清单文件.name}：共 {len(条目)} 条"
          + (f"（另有 {跳过} 行首列不是编号，已跳过并如实报出）" if 跳过 else ""))
    print("-" * 66)
    for 编号, 状态, 有状态列, 标题, 文件 in 条目:
        # 标题自称已修 → 先认出来：这类条目抽不出文件时不该被报成「需人核」（它们不是线索缺失）。
        自称 = "标题自称已修" if any(k in 标题 for k in ("已修", "已销账", "已闭合", "已落地")) else ""
        if 自称:
            自称已修 += 1
        if not 文件:
            抽不出 += 1
            print(f"  {编号:<4} {自称 or '（正文无文件路径，抽不出，需人核）'}")
            continue
        # 与 `核验落点` 同一套口径：裸文件名/包内相对路径按「后缀唯一命中」解析，多义不猜。
        真路径, 歧义 = [], []
        for f in 文件:
            if f in 全仓:
                真路径.append(f)
                continue
            命中 = [x for x in 全仓 if x.endswith("/" + f)]
            if len(命中) == 1:
                真路径.append(命中[0])
            else:
                歧义.append(f"{f}（{'多义' if 命中 else '零命中'}）")
        if not 真路径:
            抽不出 += 1
            print(f"  {编号:<4} （路径解析不出，需人核：{'、'.join(歧义)}）")
            continue
        最后 = ""
        for f in 真路径:
            段 = 跑(["log", "--oneline", "-1", "--format=%h %ad", "--date=short", "--", f])
            if 段:
                最后 = f"{f} 最后提交 {段}"
                break
        if not 有状态列:
            # 没有状态列就没有「判定」可言：只摆事实（文件最后提交日期 + 标题自称）。
            线索 += 1
            print(f"  · {编号:<4} {自称:<8} {最后 or '（该文件查不到提交）'}")
            continue
        if any(x in 状态 for x in ("⏳", "🔧")) and 最后:
            可疑 += 1
            print(f"  ⚠️ {编号:<4} 标「{状态[:12]}」但正文文件有提交 → 疑似已修（复核后改标）")
            print(f"        {最后}")
        elif "✅" in 状态 and not 最后:
            可疑 += 1
            print(f"  ⚠️ {编号:<4} 标「✅」但正文文件在 git 历史里查不到提交 → 疑似假完成")
            print(f"        查过的文件：{'、'.join(真路径)}")
        else:
            print(f"  ✓ {编号:<4} {状态[:14]:<16} 与现场一致")
    print("-" * 66)
    print(f"真可疑 {可疑} / 线索 {线索}（其中标题自称已修 {自称已修} 条）/ 抽不出 {抽不出} / "
          f"共 {len(条目)} 条。")
    print("判据：真可疑**逐条现场复核**，已修的直接改标并删过程（华哥口径：已修条目不留流水账）；"
          "线索**只报事实、不构成任何判定** —— 本清单 §四 无状态列，故 §四 全部落在线索档，"
          "要机器判它就必须先给 §四 补一列状态。")
    return 1 if 可疑 else 0


def 主函数(argv: list[str] | None = None) -> int:
    解析 = argparse.ArgumentParser(description="派活前核验：这条待办是否已经修好 / 落点是否仍成立 / 任务包是否重复")
    解析.add_argument("--文件", default="", help="待修文件的仓库相对路径")
    解析.add_argument("--关键词", nargs="*", default=[], help="缺陷关键词（如 A1 原子性）")
    解析.add_argument("--落点", default="", help="核验任务包的落点是否仍成立（传任务包路径或目录）")
    解析.add_argument("--查重", default="", help="任务包查重：找「允许修改」有交集的包（传目录）")
    解析.add_argument("--多条", default="", help="逐条核验债务清单（传 未完成事项.md）")
    参 = 解析.parse_args(argv)
    if 参.多条:
        目标 = 解析路径(参.多条, 系统根)
        if not 目标.is_file():
            print(f"⚠️ 需要文件：{参.多条}")
            return 2
        return 核验债务清单(目标)
    if 参.查重:
        目标 = 解析路径(参.查重, 系统根)
        if not 目标.is_dir():
            print(f"⚠️ 需要目录：{参.查重}")
            return 2
        return 1 if 查重(目标) else 0
    if 参.落点:
        目标 = 解析路径(参.落点, 系统根)
        if 目标.is_dir():
            坏 = sum(核验任务包(p) for p in sorted(目标.glob("*.md")))
        elif 目标.is_file():
            坏 = 核验任务包(目标)
        else:
            print(f"⚠️ 找不到：{参.落点}")
            return 2
        return 1 if 坏 else 0
    if not 参.文件:
        print("必须给 --文件 <仓库相对路径>，或 --落点 <任务包路径/目录>")
        return 2
    if not 解析路径(参.文件, 系统根).exists():
        print(f"⚠️ 该路径在主干不存在：{参.文件}")
        print("   → 可能已被搬走或删除。**先确认归属再派活**（别让子代理去全盘搜）。")
        return 2
    有命中 = _打印(参.文件, 查文件(参.文件, 参.关键词))
    print()
    if 有命中:
        print("判据：**很可能已经修好了** —— 不要再派「修」，改派「独立复核 + 反向验证」。")
    else:
        print("判据：无命中 —— 可按原样派「修」，但派前请把上面「最近改动」看一眼，防同类。")
    return 0


if __name__ == "__main__":
    raise SystemExit(主函数())
