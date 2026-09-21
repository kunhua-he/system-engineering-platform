"""开发效率巡检：**子代理到底把时间花在哪**，以及为什么慢（含趋势对比）。

## 为什么要常态化做这件事（华哥 2026-09-18 明确要求）
> "我觉得是不是应该时不时看看开发效率，总结一下为什么慢，反复探索这种"

在此之前只有出问题时才现场手算一次，量完就散 —— 下一批换个批号又踩同样的坑。
做成工具后：**每批收工跑一次**，指标进快照，趋势可对比，根因不靠猜。

## 它量什么（全部来自真实日志，不采样、不估算）
1. **工具分布**：子代理实际用了哪些工具、各多少次；
2. **四类占比**：探索 / 修改 / 验证 / 其他（探索占比高 = 找不到东西，是最大成本）；
3. **黑洞识别**（实测过的四类）：
   - `terminal` 里跑 `cat/head/tail/sed` 读文件 → 本该用 `read_file`；
   - `python3.14 -c` 一次性代码 → 每跑一次付一次解释器冷启动；
   - `Command timed out` → 命令缺超时，纯白等；
   - 全仓 `grep -r` → 本该先查代码地图；
4. **反复探索信号**：同一文件被读 ≥3 次（说明前一次读完没留下可用结论）；
5. **每路子代理耗时与状态**（含超时路）。

## 输出
- stdout：给人看的报告；
- `工程缓存/运行数据/开发效率巡检/<时间戳>.json`：快照（下次跑自动对比出趋势）；
- `--html`：自包含 HTML（给华哥看）。

## 用法
    python3.14 开发工具/开发效率巡检.py                # 扫最近 6 小时
    python3.14 开发工具/开发效率巡检.py --小时 24
    python3.14 开发工具/开发效率巡检.py --html         # 额外产 HTML
    python3.14 开发工具/开发效率巡检.py --目录 <路径>   # 指定 delegation live 目录

**纯只读**：只读日志与自己的快照，不碰仓库文件。
"""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import time
from pathlib import Path

默认日志根 = Path.home() / ".hermes/cache/delegation/live"
系统根 = Path(__file__).resolve().parents[1]
快照根 = 系统根 / "工程缓存/运行数据/开发效率巡检"

# 任务信标志串：**纪律是否真的送达子代理**的唯一判据（2026-09-18 新增）。
# 为什么必须有这一项：实测本批 8 路 kickoff 里「工具姿势/提交纪律/pathspec/命名规范」命中
# **全 0** —— 生成器 `开发工具/任务记忆/派活任务信.py` 已建好，但派活时仍手写 context，
# 而**没有任何检查会因此报红**。判据不挂在产出点 = 纪律随时静默丢失（哲学 14.3）。
纪律标志 = {
    "工具姿势": "工具姿势",
    "提交纪律": "提交纪律",
    "pathspec": "pathspec",
    "命令环境": "命令环境",
}
#: kickoff 段落在日志里的形态（append-only 转录的首行 user 条目）。
kickoff标记 = "| kickoff:"

探索词 = ("grep", "read_file", "search_files", "git show", "git log", "cat ", "head ", "tail ", "sed ",
        "ls ", "find ", "查询节点", "查询关系", "查询文件")
验证词 = ("py_compile", "pytest", "unittest", "反向", "验证", "assert", "curl")
读文件命令 = re.compile(r"\b(cat|head|tail|sed|nl)\b")


def 扫日志(日志根: Path, 小时: float) -> list[Path]:
    """只取最近 N 小时有更新的日志（避免扫几千个历史批次的目录）。"""
    截止 = time.time() - 小时 * 3600
    命中: list[Path] = []
    if not 日志根.is_dir():
        return 命中
    for 批次 in 日志根.iterdir():
        if not 批次.is_dir():
            continue
        for f in 批次.glob("*.log"):
            try:
                if f.stat().st_mtime >= 截止:
                    命中.append(f)
            except OSError:
                continue
    return sorted(命中, key=lambda p: p.stat().st_mtime)


#: 能力 id 判类词表（#211，2026-09-21）：全 MCP 化后 82% 的调用是 `capability_call`，
#: 其请求文本形如 `{'能力id': '文件系统支持库.文件操作.读取文件', '参数': {...}}`，**不含任何 CLI 关键词**
#: ⇒ 按文本匹配会把「读文件/搜代码/跑验证/改文件」统统归「其他」（实测 71.7%），四类占比失去分辨力。
#: 故能力调用改按**能力 id** 判类；顺序与 CLI 分支一致（修改 → 验证 → 探索 → 其他）。
能力_修改词 = ("写入文件", "应用精确替换", "批量应用精确替换", "改清单条目", "记踩坑",
              "登记", "写入索引", "建坑索引", "建索引", "提交", "生成文档", "写盘",
              "创建", "删除", "重命名", "人工改")
能力_验证词 = ("编译", "体检", "测试", "门禁", "摘要", "验证", "巡检", "自检", "漂移",
              "反向", "对账", "审计", "检查", "还原", "回滚")
能力_探索词 = ("读取", "搜索", "查询", "列出", "目录树", "查文档", "查记忆", "查哲学",
              "查开工", "索引", "地图", "扫描", "统计", "发现", "解析", "枚举")


def _按能力id判类(参: str) -> str:
    """从 capability_call 的入参文本里取能力 id，按 id 判四类（#211）。

    取不到 id（非能力调用 / 文本里没有）就如实回「其他」，不猜。
    """
    m = (re.search(r"'能力id':\s*'([^']+)'", 参)
         or re.search(r'"能力id":\s*"([^"]+)"', 参))
    if not m:
        return "其他"
    能力id = m.group(1)
    if any(w in 能力id for w in 能力_修改词):
        return "修改"
    if any(w in 能力id for w in 能力_验证词):
        return "验证"
    if any(w in 能力id for w in 能力_探索词):
        return "探索"
    return "其他"


def 剖析一篇(路径: Path) -> dict:
    """剖析单个子代理日志。"""
    文 = 路径.read_text(encoding="utf-8", errors="ignore")
    行表 = 文.splitlines()
    工具 = {}
    分类 = {"探索": 0, "修改": 0, "验证": 0, "其他": 0}
    读过的文件: dict[str, int] = {}
    黑洞 = {"terminal读文件": 0, "一次性python": 0, "命令超时": 0, "全仓grep": 0,
          "慢命令(>10秒)": 0, "重复搜索同目标": 0, "sleep等后台": 0, "单命令超15秒": 0}
    慢命令明细: list[dict] = []
    搜索模式表: dict[str, int] = {}

    for l in 行表:
        m = re.search(r"-> (\w+)\((.*)", l)
        if m and "tool" in l:
            名, 参 = m.group(1), m.group(2)
            工具[名] = 工具.get(名, 0) + 1
            合并 = 名 + " " + 参
            if 名 in ("patch", "write_file"):
                分类["修改"] += 1
            elif 名.endswith("capability_call"):
                # 能力调用按**能力 id** 判类（#211）：按 CLI 关键词匹配会整批落「其他」。
                分类[_按能力id判类(参)] += 1
            elif any(w in 合并 for w in 验证词):
                分类["验证"] += 1
            elif any(w in 合并 for w in 探索词) or 名 == "read_file":
                分类["探索"] += 1
            else:
                分类["其他"] += 1
            if 名 == "read_file":
                p = re.search(r"path=[\"']?([^\"',\s]+)", 参)
                if p:
                    读过的文件[p.group(1).split("/")[-1]] = 读过的文件.get(p.group(1).split("/")[-1], 0) + 1
            if 名 == "terminal":
                if 读文件命令.search(参):
                    黑洞["terminal读文件"] += 1
                if "python3.14 -c" in 参 or "python3.14 -c" in 参:
                    黑洞["一次性python"] += 1
                if re.search(r"\b(grep|rg)\b", 参) and not re.search(
                        r"(运行核心|支持库|模块库|平台控制面|开发工具|测试中心|公共契约|技能库|项目适配层|文档)",
                        参):
                    黑洞["全仓grep"] += 1
                # 重复搜索同一目标（2026-09-19 新增）：同一条检索式查 ≥2 次 =
                # 上一次查完没留下可用结论，白付多轮生成。实测案例：同一关键词 `C-11`
                # 在一个子代理里搜了 5 次，其中 3 次是同一个文件。
                # 判据只认「检索式 + 目标范围」这个组合，不看结果，避免把分页读当成重复。
                for 检索 in re.findall(r"\b(?:rg|grep)\b[^\n`]{0,120}", 参):
                    键 = re.sub(r"\s+", " ", 检索).strip()[:100]
                    搜索模式表[键] = 搜索模式表.get(键, 0) + 1
        黑洞["命令超时"] += len(re.findall(r"Command timed out after", l))
        # **sleep 等后台（2026-09-19 立）**：华哥口径「调用一个命令超过 15 秒就是纯 bug」。
        # 实测最贵的形态就是 `sleep 420` / `sleep 400` —— 子代理用休眠等后台任务，
        # 单条就烧掉整个子代理的预算。正确姿势：后台任务用 `background=true` 起、
        # 用 `process_manage wait/poll` 拿结果；**一律不许 sleep**。
        if "sleep" in l and "-> " in l and re.search(r"\bsleep\s+\d+", l):
            黑洞["sleep等后台"] += 1
        # 慢命令：逐条解析「工具 ok X.Xs」的真实耗时，≥10 秒计入（华哥 2026-09-18：
        # 「时不时执行工具都很久，能修到加速不」→ 判据必须能量到「久在哪一条」）。
        for 秒文本 in re.findall(r"\| (\w+) ok ([\d.]+)s", l):
            秒 = float(秒文本[1])
            if 秒 >= 10:
                黑洞["慢命令(>10秒)"] += 1
                慢命令明细.append({"工具": 秒文本[0], "秒": 秒})
            # **单命令超 15 秒 = 纯 bug**（华哥 2026-09-19 口径）：
            # 实测 2018 条命令 >15 秒（全批），最贵 420 秒（超时上限）。这类不是"慢"，
            # 是**设计错误**：要么该后台、要么该限定范围、要么该用现成件。
            if 秒 >= 15 and 秒文本[0] != "delegate_task":
                黑洞["单命令超15秒"] += 1

    状态 = ""
    m = re.findall(r"final\s+\| end status=(\w+)", 文)
    if m:
        状态 = m[-1]
    # ★ 修判据（2026-09-19）：耗时在 `final | status=<状态> duration=<秒>s` 那行，
    # **不在** `final | end status=…` 那行（end 行只有 status 与 exit_reason）——
    # 原判据写 `end status=\w+ duration=` 要求同行紧邻，整批读不到 ⇒ 累计耗时恒为 0.0。
    m = re.search(r"final\s+\| status=\w+ duration=([\d.]+)s", 文)
    耗时 = float(m.group(1)) if m else 0.0
    调用数 = sum(工具.values())
    重复检索 = {k: v for k, v in 搜索模式表.items() if v >= 2}
    黑洞["重复搜索同目标"] = sum(v - 1 for v in 重复检索.values())
    return {
        "日志": str(路径),
        "批次": 路径.parent.name,
        "任务": 路径.stem,
        "状态": 状态 or "在跑",
        "耗时秒": round(耗时, 1),
        "调用数": 调用数,
        "工具": 工具,
        "分类": 分类,
        "黑洞": 黑洞,
        "慢命令明细": sorted(慢命令明细, key=lambda x: -x["秒"])[:5],
        "反复读": {k: v for k, v in 读过的文件.items() if v >= 3},
        "重复检索": dict(sorted(重复检索.items(), key=lambda x: -x[1])[:5]),
    }


def 查交付留痕(日志表: list[Path]) -> dict:
    """**硬判据：写任务必须有真交付**（2026-09-19 立，同类已连出三路）。

    为什么必须是硬判据（哲学 14.3）：同一根因实测连出三路 ——
    K2/P/Q子 各跑 19 分钟、`git commit` **0 次**、实现一行未改，
    最终回答却是「Let me plan…」「Now write the facades…」这种**将来时计划**。
    只写进任务信的「早提交锚点」「不许交计划当交付」是**软规则**，实测拦不住。

    判据（只看真实日志，不看自述）：
    - **有写类动作**（`patch` / `write_file` 落仓库内）或**有提交** ⇒ 有交付；
    - **有写类动作但 0 提交** ⇒ 黄灯「未落提交」；
    - **既无写类动作也无提交** ⇒ 红灯「零交付」（改都没改过）。
    - 只读任务（kickoff 带 `本任务只读`）不计入。
    """
    红灯, 黄灯 = [], []
    哈希 = re.compile(r"\b[0-9a-f]{40}\b")
    for 日志 in 日志表:
        try:
            文 = 日志.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if "本任务只读" in 文:
            continue
        # 仍在跑的路不算（还没结束，不能判它零交付）：判据只看**已结束**的路。
        if not re.search(r"final\s+\| end status=\w+", 文):
            continue
        # **任务性质分流**（2026-09-19）：核验/盘点/审计类任务**本就不改文件**，
        # 判它「零交付」是假红。判据只看 kickoff 首段的写意图标志。
        首 = 文[:4000]
        写任务 = ("允许修改" in 首) or ("修改路径" in 首) or ("开工ID" in 首)
        if not 写任务 and any(k in 首 for k in ("只读", "核验", "核实", "盘点", "审计", "评估", "分析")):
            continue
        # 判据口径（2026-09-19 修假红）：子代理多半在 `execute_code` 里提交与写盘，
        # 日志里**不出现** `-> write_file(` 与 `git commit` 字面量。真证据是
        # **40 位提交哈希**（`git show --stat` 回显）与仓库内写盘路径。
        提交数 = len(哈希.findall(文))
        写仓内 = len(re.findall(r"-> (?:patch|write_file)\(/Users", 文))
        写盘 = 写仓内 + len(re.findall(r"resolved_path[\"']?:\s*[\"']/Users", 文))
        # 红灯＝**三条同时成立**（最严口径，宁可不报也不假红）：
        # ① 仓库零写盘证据 ② 零 40 位提交哈希 ③ **尾答是将来时**
        # （「Let me plan / Now write / I'll / 接下来」= 交了计划没交活）。
        # 实测指纹：K2「Let me plan the split」/ P「Now write the facades」/
        # Q子「Now running the full gate battery」。仅凭前两条会误伤
        # 在 `execute_code` 里写盘的已交付路（M/A/N 实测被误判）。
        尾 = 文[-1500:]
        将来时 = re.search(r"(Let me plan|Now write|Now running|I'll |I will |下一步我|我要先|接下来我)", 尾)
        if 写盘 == 0 and 提交数 == 0 and 将来时:
            红灯.append({"路": 日志.name, "批次": 日志.parent.name,
                        "耗时秒": _耗时(文), "提交数": 0, "写仓内": 0})
        elif 写盘 == 0 and 提交数 == 0:
            黄灯.append({"路": 日志.name, "批次": 日志.parent.name,
                        "耗时秒": _耗时(文), "提交数": 0, "写仓内": 0})
        elif 提交数 == 0:
            黄灯.append({"路": 日志.name, "批次": 日志.parent.name,
                        "耗时秒": _耗时(文), "提交数": 0, "写仓内": 写盘})
    return {"零交付": 红灯, "未落提交": 黄灯,
            "判定": "红" if 红灯 else ("黄" if 黄灯 else "绿")}


def _耗时(文: str) -> float:
    r"""子代理真实耗时（秒）：取自 `final | status=<状态> duration=<秒>s` 那行。

    ★ 2026-09-19 修：原判据写成 `end status=\w+ duration=` —— 但 `end` 行**只有**
    `status` 与 `exit_reason`，耗时在**前一行**，故整批读不到、累计耗时恒为 0.0。
    """
    m = re.search(r"final\s+\| status=\w+ duration=([\d.]+)s", 文)
    return round(float(m.group(1)), 1) if m else 0.0


def 查纪律送达(日志表: list[Path]) -> dict:
    """逐路检查 kickoff 里有没有任务信的固定条款（**唯一判据在产出点**）。

    返回 `{已送达, 未送达, 缺项表}`：
    - `已送达`：四个标志串全中的路由数；
    - `未送达`：缺任一标志串的路（**这就是纪律丢失的铁证**）；
    - `缺项表`：`[{"路": 文件名, "缺": [标志, …]}, …]`，便于直接照单修。

    **2026-09-19 修假红（实测根因）**：原判据只取 kickoff **首行**，但派活转录会把该行
    截断到约 600 字符（行尾留 `…(+N chars)`），而任务信把固定条款排在**任务正文之后**
    （长任务信里条款落在 8KB 处）⇒ 一份**完全合格**的任务信也判「未送达」，
    8 路全红。这不是纪律丢了，是**判据看不到**。

    现在改为**两级判据**（都算送达，但如实标注来源）：
    ① 首选看 kickoff 首行（= 派活载荷原文，最强证据）；
    ② 首行截断时退回**全文**（子代理会按「开工第一步」读任务信/记忆包，条款必然进日志）。
       两者都没有，才判「未送达」——那才是真丢条款（手写 context 的典型症状）。
    """
    已送到, 未送到, 缺项表 = 0, 0, []
    截断退回 = 0
    for 日志 in 日志表:
        try:
            文 = 日志.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        行表 = [行 for 行 in 文.splitlines() if kickoff标记 in 行]
        if not 行表:
            continue
        首行 = 行表[0]
        # ① 首行优先；② 首行被转录截断时退回全文
        缺 = [名 for 名, 串 in 纪律标志.items() if 串 not in 首行]
        if 缺:
            缺 = [名 for 名, 串 in 纪律标志.items() if 串 not in 文]
            if not 缺:
                截断退回 += 1
        if 缺:
            未送到 += 1
            缺项表.append({"路": 日志.name, "缺": 缺})
        else:
            已送到 += 1
    return {"已送达": 已送到, "未送达": 未送到, "缺项表": 缺项表,
            "首行截断退回": 截断退回}


def 汇总(剖析表: list[dict], 纪律结论: dict | None = None,
        交付结论: dict | None = None) -> dict:
    纪律结论 = 纪律结论 or {"已送达": 0, "未送达": 0, "缺项表": []}
    合计工具: dict[str, int] = {}
    合计分类 = {"探索": 0, "修改": 0, "验证": 0, "其他": 0}
    合计黑洞 = {"terminal读文件": 0, "一次性python": 0, "命令超时": 0, "全仓grep": 0,
              "慢命令(>10秒)": 0, "重复搜索同目标": 0, "sleep等后台": 0, "单命令超15秒": 0}
    反复读: dict[str, int] = {}
    重复检索: dict[str, int] = {}
    for a in 剖析表:
        for k, v in a["工具"].items():
            合计工具[k] = 合计工具.get(k, 0) + v
        for k in 合计分类:
            合计分类[k] += a["分类"][k]
        for k in 合计黑洞:
            合计黑洞[k] += a["黑洞"][k]
        for k, v in a["反复读"].items():
            反复读[k] = max(反复读.get(k, 0), v)
        for k, v in (a.get("重复检索") or {}).items():
            重复检索[k] = 重复检索.get(k, 0) + v
    总 = sum(合计分类.values()) or 1
    return {
        "批次": len({a["批次"] for a in 剖析表}),
        "子代理数": len(剖析表),
        "完成": len([a for a in 剖析表 if a["状态"] == "completed"]),
        "超时": len([a for a in 剖析表 if a["状态"] == "timeout"]),
        "总调用": 总,
        "工具": dict(sorted(合计工具.items(), key=lambda x: -x[1])),
        "分类": 合计分类,
        "占比": {k: round(v / 总 * 100, 1) for k, v in 合计分类.items()},
        "黑洞": 合计黑洞,
        "反复读": dict(sorted(反复读.items(), key=lambda x: -x[1])[:10]),
        "重复检索": dict(sorted(重复检索.items(), key=lambda x: -x[1])[:10]),
        "累计耗时秒": round(sum(a["耗时秒"] for a in 剖析表), 1),
        "纪律": 纪律结论,
        "交付留痕": (留痕结论 := (交付结论 or {"零交付": [], "未落提交": [], "判定": "绿"})),
        "交付判定": 留痕结论["判定"],
    }


#: 归因条目的严重度：`⛔` 阻断、`⚠` 告警、`✓` 通过。
#: **唯一作用**是让 `main` 能算出诚实的退出码（2026-09-20 补，待办 #64）——
#: 原实现只把告警 append 进归因表，返回值恒 0，调用方（定时任务/CI）读到的
#: 永远是「成功」，判据等于没有。
归因判级 = {"⛔": 2, "⚠": 1, "✓": 0}


def 归因退出码(归因表: list[str]) -> tuple[int, dict]:
    """把归因条目折算成退出码（**诚实的返回值，不是只打印**）。

    口径与「零交付」硬门禁同级，不新造第二套严重度：

    - 只要有一条 `⛔` 阻断 ⇒ 退 2（纪律未送达 / sleep 等后台 / 单命令超 15 秒）；
    - 否则只要有一条 `⚠` 告警 ⇒ 退 1（含本待办点名的三处阈值：探索占 ≥50%、
      terminal 占 ≥60%、慢命令 ≥10 秒）；
    - 其余（全是 `✓`）⇒ 退 0。

    返回 `(退出码, 判级明细)`，明细进快照，便于下次对比「红灯在收敛还是在扩散」。
    """
    明细: dict[str, int] = {"阻断": 0, "告警": 0, "通过": 0}
    for 一条 in 归因表:
        首 = 一条.lstrip()[:1]
        if 首 == "⛔":
            明细["阻断"] += 1
        elif 首 == "⚠":
            明细["告警"] += 1
        elif 首 == "✓":
            明细["通过"] += 1
    if 明细["阻断"]:
        return 2, 明细
    if 明细["告警"]:
        return 1, 明细
    return 0, 明细


def 归因(果: dict) -> list[str]:
    """把指标映射到已知根因（每条都给判据，不含猜测）。"""
    结语: list[str] = []
    占比 = 果["占比"]
    黑 = 果["黑洞"]
    工具 = 果["工具"]
    总调用 = 果["总调用"] or 1
    terminal_占比 = 工具.get("terminal", 0) / 总调用 * 100

    if 占比.get("探索", 0) >= 50:
        结语.append(f"⚠ 探索占 {占比['探索']}%（≥50%）→ 子代理在找东西上花掉一半以上。"
                    "查：代码地图是否已同步到本次改动、任务包里是否给了精确落点。")
    if 黑["terminal读文件"] >= 10:
        结语.append(f"⚠ terminal 里用 cat/head/tail/sed 读文件 {黑['terminal读文件']} 次 "
                    "→ 本该用 read_file（带行号、可翻页、不进 shell 开销）。")
    if 黑["一次性python"] >= 20:
        结语.append(f"⚠ python3.14 -c 一次性代码 {黑['一次性python']} 次 "
                    "→ 每跑一次付一次解释器冷启动；成组动作应落脚本跑一次。")
    if 黑["命令超时"]:
        结语.append(f"⚠ 命令超时 {黑['命令超时']} 次（每次白等 180 秒 ≈ "
                    f"{黑['命令超时']*3} 分钟）→ 命令必须带超时；全仓扫描先查代码地图。")
    if 黑["全仓grep"] >= 20:
        结语.append(f"⚠ 全仓 grep {黑['全仓grep']} 次 → 代码地图有 19,744 节点，"
                    "应先查地图拿 文件:行号，再定向核。")
    if terminal_占比 >= 60:
        结语.append(f"⚠ terminal 占工具调用 {terminal_占比:.0f}%（≥60%）→ terminal 万能化："
                    "读文件用 read_file、找文件用 search_files、查符号用代码地图。")
    if 果["反复读"]:
        结语.append(f"⚠ 有文件被反复读 ≥3 次：{'、'.join(list(果['反复读'])[:5])} "
                    "→ 上一次读完没留下可用结论；应把结论写进任务包/落盘。\n"
                    "  **注意**：分页读大文件（`read_file L401-800`）不算此列 —— 那是正确姿势。")
    if 果.get("重复检索"):
        例 = "、".join(f"「{k[:40]}」×{v}" for k, v in list(果["重复检索"].items())[:3])
        结语.append(f"⚠ 重复搜索同目标 {黑.get('重复搜索同目标', 0)} 次 → 同一条检索式查了 ≥2 遍，"
                    f"上一次查完没留下结论。例：{例}。"
                    "应一次查全（一条命令带够 glob 与目标文件）并把结论落盘，而不是反复重查。")
    if 果["超时"]:
        结语.append(f"⚠ 本批超时 {果['超时']} 路 → 先现场盘点产物（超时≠零产出），"
                    "再判是任务过大还是探索过多。")
    纪律 = 果.get("纪律") or {}
    送达, 未送达 = 纪律.get("已送达", 0), 纪律.get("未送达", 0)
    if 未送达:
        示例 = "、".join(f"{x['路']}（缺 {'/'.join(x['缺'])}）"
                      for x in (纪律.get("缺项表") or [])[:3])
        结语.insert(0, f"⛔ 任务信纪律未送达 {未送达} 路（已送达 {送达} 路）→ "
                       f"派活**必须经 `开发工具/任务记忆/派活任务信.py` 生成**，"
                       f"手写 context 会整批丢失固定条款。示例：{示例}")
    elif 送达:
        结语.append(f"✓ 任务信纪律已送达 {送达} 路（工具姿势/提交纪律/pathspec/命令环境 全中）。")
    if 黑.get("sleep等后台"):
        结语.append(f"⛔ sleep 等后台 {黑['sleep等后台']} 次 → **纯 bug**（华哥 2026-09-19：「调用一个命令"
                     "超过 15 秒就是纯 bug」）。实测最贵形态就是 `sleep 420`/`sleep 400`，单条烧光整路子代理预算。"
                     "正确姿势：后台任务用 `background=true` 起、用 `process_manage wait/poll` 拿结果，或落脚本后台跑；"
                     "**一律不许 sleep**。")
    if 黑.get("单命令超15秒"):
        结语.append(f"⛔ 单命令超 15 秒 {黑['单命令超15秒']} 条 → 按华哥口径这**不是慢，是 bug**。"
                     "三类必改：① 该后台的挂了前台（>15 秒一律 `background=true, notify=true`）；"
                     "② 该限定范围的做了全仓扫描（全仓 `grep -r` 9.8GB 要 15.62 秒，`rg` 只要 0.07 秒）；"
                     "③ 该用现成件的手写了第二实现。")
    if 黑.get("慢命令(>10秒)"):
        明细 = 果.get("慢命令明细") or []
        例 = "、".join(f"{x['工具']} {x['秒']}s" for x in 明细[:3])
        结语.append(f"⚠ 慢命令（单条 ≥10 秒）{黑['慢命令(>10秒)']} 条 → 看是哪种命令慢（例：{例}）。"
                     f"实测口径：全仓 `grep -r .` 在 9.8GB 工程缓存下要 15.62 秒，"
                     f"`rg` 只要 0.07 秒（223 倍）；重活应落脚本后台跑，别让单次调用干等。")
    if not 结语:
        结语.append("✓ 未发现已知黑洞（四类黑审计数与占比均在阈值内）。")
    return 结语


def 比趋势(果: dict) -> list[str]:
    """与上一次快照对比（没有就跳过）。"""
    快照根.mkdir(parents=True, exist_ok=True)
    旧表 = sorted(快照根.glob("*.json"))
    if not 旧表:
        return ["（首次巡检，无趋势可比 —— 下次跑会自动对比）"]
    旧 = json.loads(旧表[-1].read_text(encoding="utf-8"))["汇总"]
    结语 = [f"对比上一次（{旧表[-1].stem}）："]
    for 键, 名 in (("总调用", "总调用"), ("子代理数", "子代理数"), ("超时", "超时路")):
        a, b = 旧.get(键, 0), 果.get(键, 0)
        箭 = "↑" if b > a else ("↓" if b < a else "=")
        结语.append(f"  {名} {a} {箭} {b}")
    for k in ("探索", "修改", "验证"):
        a, b = 旧.get("占比", {}).get(k, 0), 果["占比"].get(k, 0)
        箭 = "↑" if b > a else ("↓" if b < a else "=")
        好 = "✓ 改善" if (k == "探索" and b < a) or (k != "探索" and b > a) else (
            "⚠ 变差" if a and b != a else "")
        结语.append(f"  {k}占比 {a}% {箭} {b}%  {好}")
    for k, v in 果["黑洞"].items():
        旧v = 旧.get("黑洞", {}).get(k, 0)
        if 旧v or v:
            箭 = "↑" if v > 旧v else ("↓" if v < 旧v else "=")
            结语.append(f"  {k} {旧v} {箭} {v}")
    return 结语


def 打印报告(果: dict, 剖析表: list[dict], 归因表: list[str], 趋势: list[str]) -> None:
    print("=" * 72)
    print(f"开发效率巡检  {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 72)
    print(f"批次 {果['批次']} 个 / 子代理 {果['子代理数']} 路 "
          f"（完成 {果['完成']} / 超时 {果['超时']}）/ 累计耗时 {果['累计耗时秒']/60:.1f} 分钟")
    print(f"\n工具调用分布（合计 {果['总调用']}）：")
    for k, v in 果["工具"].items():
        print(f"  {k:<16}{v:>5}  {v / (果['总调用'] or 1) * 100:>5.1f}%")
    print(f"\n四类占比：探索 {果['占比']['探索']}% / 修改 {果['占比']['修改']}% / "
          f"验证 {果['占比']['验证']}% / 其他 {果['占比']['其他']}%")
    print("\n黑洞：")
    for k, v in 果["黑洞"].items():
        print(f"  {k:<16}{v:>5}")
    if 果["反复读"]:
        print("\n被反复读（≥3 次）：")
        for k, v in 果["反复读"].items():
            print(f"  {k:<40}{v} 次")
    print("\n--- 交付留痕（硬判据：写任务必须有真交付）---")
    留 = 果.get("交付留痕") or {}
    红, 黄 = 留.get("零交付") or [], 留.get("未落提交") or []
    if not 红 and not 黄:
        print("  全绿：每路都有真实改动且已落提交")
    for x in 红:
        print(f"  ❌ 零交付 {x['批次']}/{x['路']} 耗时 {x['耗时秒']}s（改动 0 处、提交 0 次）")
    for x in 黄:
        print(f"  ⚠ 未落提交 {x['批次']}/{x['路']} 耗时 {x['耗时秒']}s（写了 {x['写仓内']} 处但 0 提交）")
    print(f"  交付判定：{留.get('判定', '绿')}")
    print("\n--- 归因 ---")
    for s in 归因表:
        print("  " + s)
    print("\n--- 趋势 ---")
    for s in 趋势:
        print("  " + s)


def 写快照(果: dict, 判级: dict | None = None) -> Path:
    快照根.mkdir(parents=True, exist_ok=True)
    目标 = 快照根 / f"{time.strftime('%Y%m%d_%H%M%S')}.json"
    目标.write_text(json.dumps({"生成时间": time.strftime("%Y-%m-%d %H:%M:%S"), "汇总": 果,
                                "归因判级": 判级 or {}},
                              ensure_ascii=False, indent=2), encoding="utf-8")
    return 目标


def 写HTML(果: dict, 归因表: list[str], 趋势: list[str],
           剖析表: list[dict] | None = None) -> Path:
    """产自包含 HTML 报告（华哥 2026-09-21：「下次一个 html 就能告诉我答案」）。

    修前只有四类占比 + 黑洞计数 —— 要答「效率正常吗 / 多出来的时间去哪 / 怎么优化」
    仍得回去读快照、翻日志、读实现。现补齐三块：**慢命令明细**（久在哪一条）、
    **逐路明细**（哪条路最贵）、**优化方案**（按判据给动作）。
    """
    剖析表 = 剖析表 or []

    def 行(标题: str, 表: dict[str, object]) -> str:
        if not 表:
            return ""
        格 = "".join(f"<tr><td>{html.escape(str(k))}</td><td class='n'>{v}</td></tr>"
                    for k, v in 表.items())
        return f"<h2>{标题}</h2><table>{格}</table>"

    慢命令表: list[tuple] = []
    for a in 剖析表:
        for x in a.get("慢命令明细", []):
            慢命令表.append((float(x.get("秒", 0)), str(x.get("工具", "")),
                          str(a.get("路") or a.get("日志") or "")))
    慢命令表.sort(reverse=True)
    慢行 = "".join(f"<tr><td class='n'>{秒:.1f}s</td><td>{html.escape(工具)}</td>"
                  f"<td>{html.escape(路)}</td></tr>" for 秒, 工具, 路 in 慢命令表[:20])

    逐路表: list[tuple] = []
    for a in 剖析表:
        黑 = a.get("黑洞", {})
        逐路表.append((int(sum(黑.values())), str(a.get("路") or a.get("日志") or "?"),
                     int(a.get("调用数", 0)), int(黑.get("单命令超15秒", 0))))
    逐路表.sort(reverse=True)
    逐路行 = "".join(f"<tr><td>{html.escape(名)}</td><td class='n'>{调用}</td>"
                    f"<td class='n'>{黑数}</td><td class='n'>{超15}</td></tr>"
                    for 黑数, 名, 调用, 超15 in 逐路表)

    纪律 = 果.get("纪律", {})
    结语 = "".join(f"<li>{html.escape(s)}</li>" for s in 归因表)
    趋势表 = "".join(f"<li>{html.escape(s)}</li>" for s in 趋势)
    页 = f"""<!doctype html><html lang="zh-CN"><meta charset="utf-8">
<title>开发效率巡检</title>
<style>
body{{font-family:ui-sans-serif,-apple-system,"PingFang SC",sans-serif;max-width:920px;margin:32px auto;padding:0 16px;color:#111}}
h1{{font-size:22px;margin:0 0 4px}} .sub{{color:#666;font-size:13px;margin-bottom:20px}}
h2{{font-size:15px;margin:22px 0 8px;padding-bottom:4px;border-bottom:2px solid #eee}}
table{{border-collapse:collapse;width:100%;font-size:13px}}
td{{padding:5px 10px;border-bottom:1px solid #f0f0f0}} td.n{{text-align:right;font-variant-numeric:tabular-nums;font-weight:600}}
ul{{font-size:13.5px;line-height:1.75;padding-left:20px}} li{{margin:2px 0}}
.卡{{display:inline-block;margin:0 10px 10px 0;padding:10px 14px;background:#f7f7f8;border-radius:8px;min-width:120px}}
.卡 b{{display:block;font-size:20px;font-variant-numeric:tabular-nums}} .卡 span{{color:#666;font-size:12px}}
</style>
<h1>开发效率巡检</h1><div class="sub">{time.strftime('%Y-%m-%d %H:%M:%S')} · 数据来自真实子代理日志</div>
<div>
<div class='卡'><b>{果['子代理数']}</b><span>子代理路数</span></div>
<div class='卡'><b>{果['总调用']}</b><span>工具调用</span></div>
<div class='卡'><b>{果['累计耗时秒']/60:.0f}</b><span>累计分钟</span></div>
<div class='卡'><b>{果['完成']}/{果['超时']}</b><span>完成/超时路</span></div>
<div class='卡'><b>{果['占比']['探索']}%</b><span>探索占比</span></div>
<div class='卡'><b>{果['占比']['修改']}%</b><span>修改占比</span></div>
<div class='卡'><b>{果['黑洞']['慢命令(>10秒)']}</b><span>慢命令&gt;10秒</span></div>
<div class='卡'><b>{果['黑洞']['单命令超15秒']}</b><span>单命令超15秒</span></div>
<div class='卡'><b>{果['黑洞']['sleep等后台']}</b><span>sleep等后台</span></div>
<div class='卡'><b>{纪律.get('未送达', 0)}</b><span>纪律未送达</span></div>
</div>
{行("工具调用分布", 果["工具"])}
{行("四类占比", {k: str(v) + "%" for k, v in 果["占比"].items()})}
{行("黑洞计数", 果["黑洞"])}
<h2>慢命令明细（Top 20：久在哪一条）</h2><table><tr class='头'><th>耗时</th><th>工具</th><th>路</th></tr>{慢行}</table>
<h2>逐路明细（按黑洞数降序）</h2><table><tr class='头'><th>路</th><th>调用数</th><th>黑洞合计</th><th>其中超15秒</th></tr>{逐路行}</table>
<h2>优化方案（按判据）</h2><ol>
<li><b>sleep 清零</b>：实测最贵形态 `sleep 420` 单条烧光整路子代理预算 → 后台任务用 background 起、用 process_manage wait/poll 拿结果。<i>判据：本页「sleep 等后台」= 0。</i></li>
<li><b>&gt;15 秒一律后台化</b>：三类必改 —— 该后台的挂了前台 / 该限定范围的做了全仓扫描（全仓 grep 15.62s vs rg 0.07s）/ 该用现成件的手写了第二实现。<i>判据：本页「单命令超15秒」显著下降。</i></li>
<li><b>派活经 开发工具/任务记忆/派活任务信.py 生成</b>：手写 context 会整批丢固定条款（工具姿势/提交纪律/pathspec/命令环境）。<i>判据：本页「纪律未送达」= 0。</i></li>
<li><b>「改一个能力」的派生物收敛</b>：说明书两份/验证场景/权限契约目前靠手改，漏一份即被判红。<i>判据：新增能力后 包体检 直接 0 缺项。</i></li>
<li><b>编译口瘦身</b>：单轮 39.3 秒（md查重 14.09 秒是大头）。<i>判据：单轮 &lt; 15 秒。</i></li>
</ol>
{行("被反复读（≥3 次）", 果["反复读"])}
<h2>归因</h2><ul>{结语}</ul>
<h2>趋势（对比上一次快照）</h2><ul>{趋势表}</ul>
</html>"""
    目标 = 快照根 / f"{time.strftime('%Y%m%d_%H%M%S')}.html"
    目标.write_text(页, encoding="utf-8")
    return 目标


def main(argv: list[str] | None = None) -> int:
    解析 = argparse.ArgumentParser(description="开发效率巡检：子代理时间花在哪、为什么慢")
    解析.add_argument("--小时", type=float, default=6.0, help="只看最近 N 小时有更新的日志（默认 6）")
    解析.add_argument("--目录", default="", help="delegation live 目录（默认 ~/.hermes/cache/delegation/live）")
    解析.add_argument("--html", action=argparse.BooleanOptionalAction, default=True,
                      help="产 HTML 报告（默认产；--no-html 关掉）—— 华哥 2026-09-21 口径"
                           "「下次一个 html 就能告诉我答案」")
    参 = 解析.parse_args(argv)
    根 = Path(参.目录) if 参.目录 else 默认日志根
    日志 = 扫日志(根, 参.小时)
    if not 日志:
        print(f"最近 {参.小时} 小时内没有子代理日志：{根}")
        return 0
    剖析表 = [剖析一篇(p) for p in 日志]
    剖析表 = [a for a in 剖析表 if a["调用数"]]
    留痕 = 查交付留痕(日志)
    果 = 汇总(剖析表, 查纪律送达(日志), 留痕)
    归因表 = 归因(果)
    趋势 = 比趋势(果)
    打印报告(果, 剖析表, 归因表, 趋势)
    # **诚实退出码（2026-09-20 补，待办 #64）**：归因表里的 `⛔`/`⚠` 原先只打印、
    # 不进返回值 ⇒ 调用方读到的永远是 0。先算退出码再写快照，快照里留判级明细。
    码, 判级 = 归因退出码(归因表)
    快照 = 写快照(果, 判级)
    print(f"\n快照：{快照}")
    print(f"归因判级：⛔ {判级['阻断']} 条 / ⚠ {判级['告警']} 条 / ✓ {判级['通过']} 条"
          f" → 退出码 {码}")
    if 参.html:
        print(f"HTML：{写HTML(果, 归因表, 趋势, 剖析表)}")
    # **硬门禁（2026-09-19）**：零交付必须让调用方看到非零退出码，
    # 否则判据等于没有 —— 原实现无论多红都 `return 0`。
    if 留痕["零交付"]:
        print(f"\n❌ 交付留痕红灯：{len(留痕['零交付'])} 路零交付"
              f"（改了 0 处、提交 0 次）—— 这轮作废，按半成品口径重派：")
        for x in 留痕["零交付"]:
            print(f"   - {x['批次']}/{x['路']} 耗时 {x['耗时秒']}s")
        # 零交付红灯不**降级**归因码：⛔ 阻断比它更重，取两者最大，
        # 否则「有阻断项」会被掩成 1，调用方看到的严重度失真。
        return max(1, 码)
    if 码:
        print(f"\n❌ 归因未清零（退出码 {码}）："
              f"{'⛔ 有阻断项' if 码 == 2 else '⚠ 有告警项'}—— 判据已进退出码，"
              f"调用方/CI 按非零处理（原实现此处恒 0，等于没有判据）。")
    return 码


if __name__ == "__main__":
    raise SystemExit(main())
