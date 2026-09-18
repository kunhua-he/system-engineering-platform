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
# 为什么必须有这一项：实测本批 8 路 kickoff 里「工具姿势/提交纪律/pathspec/禁甲乙丙丁」命中
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


def 剖析一篇(路径: Path) -> dict:
    """剖析单个子代理日志。"""
    文 = 路径.read_text(encoding="utf-8", errors="ignore")
    行表 = 文.splitlines()
    工具 = {}
    分类 = {"探索": 0, "修改": 0, "验证": 0, "其他": 0}
    读过的文件: dict[str, int] = {}
    黑洞 = {"terminal读文件": 0, "一次性python": 0, "命令超时": 0, "全仓grep": 0}

    for l in 行表:
        m = re.search(r"-> (\w+)\((.*)", l)
        if m and "tool" in l:
            名, 参 = m.group(1), m.group(2)
            工具[名] = 工具.get(名, 0) + 1
            合并 = 名 + " " + 参
            if 名 in ("patch", "write_file"):
                分类["修改"] += 1
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
        黑洞["命令超时"] += len(re.findall(r"Command timed out after", l))

    状态 = ""
    m = re.findall(r"final\s+\| end status=(\w+)", 文)
    if m:
        状态 = m[-1]
    m = re.search(r"final\s+\| end status=\w+ duration=([\d.]+)s", 文)
    耗时 = float(m.group(1)) if m else 0.0
    调用数 = sum(工具.values())
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
        "反复读": {k: v for k, v in 读过的文件.items() if v >= 3},
    }


def 查纪律送达(日志表: list[Path]) -> dict:
    """逐路检查 kickoff 里有没有任务信的固定条款（**唯一判据在产出点**）。

    返回 `{已送达, 未送达, 缺项表}`：
    - `已送达`：kickoff 里四个标志串全中的路由数；
    - `未送达`：缺任一标志串的路（**这就是纪律丢失的铁证**）；
    - `缺项表`：`[{"路": 文件名, "缺": [标志, …]}, …]`，便于直接照单修。
    """
    已送到, 未送到, 缺项表 = 0, 0, []
    for 日志 in 日志表:
        try:
            文 = 日志.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        # kickoff 只取首行（append-only 转录第一段 user 条目即派活原文）。
        行表 = [行 for 行 in 文.splitlines() if kickoff标记 in 行]
        if not 行表:
            continue
        段 = 行表[0]
        缺 = [名 for 名, 串 in 纪律标志.items() if 串 not in 段]
        if 缺:
            未送到 += 1
            缺项表.append({"路": 日志.name, "缺": 缺})
        else:
            已送到 += 1
    return {"已送达": 已送到, "未送达": 未送到, "缺项表": 缺项表}


def 汇总(剖析表: list[dict], 纪律结论: dict | None = None) -> dict:
    纪律结论 = 纪律结论 or {"已送达": 0, "未送达": 0, "缺项表": []}
    合计工具: dict[str, int] = {}
    合计分类 = {"探索": 0, "修改": 0, "验证": 0, "其他": 0}
    合计黑洞 = {"terminal读文件": 0, "一次性python": 0, "命令超时": 0, "全仓grep": 0}
    反复读: dict[str, int] = {}
    for a in 剖析表:
        for k, v in a["工具"].items():
            合计工具[k] = 合计工具.get(k, 0) + v
        for k in 合计分类:
            合计分类[k] += a["分类"][k]
        for k in 合计黑洞:
            合计黑洞[k] += a["黑洞"][k]
        for k, v in a["反复读"].items():
            反复读[k] = max(反复读.get(k, 0), v)
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
        "累计耗时秒": round(sum(a["耗时秒"] for a in 剖析表), 1),
        "纪律": 纪律结论,
    }


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
                    "→ 上一次读完没留下可用结论；应把结论写进任务包/落盘。")
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
    print("\n--- 归因 ---")
    for s in 归因表:
        print("  " + s)
    print("\n--- 趋势 ---")
    for s in 趋势:
        print("  " + s)


def 写快照(果: dict) -> Path:
    快照根.mkdir(parents=True, exist_ok=True)
    目标 = 快照根 / f"{time.strftime('%Y%m%d_%H%M%S')}.json"
    目标.write_text(json.dumps({"生成时间": time.strftime("%Y-%m-%d %H:%M:%S"), "汇总": 果},
                              ensure_ascii=False, indent=2), encoding="utf-8")
    return 目标


def 写HTML(果: dict, 归因表: list[str], 趋势: list[str]) -> Path:
    def 行(标题: str, 表: dict[str, object]) -> str:
        if not 表:
            return ""
        格 = "".join(f"<tr><td>{html.escape(str(k))}</td><td class='n'>{v}</td></tr>"
                    for k, v in 表.items())
        return f"<h2>{标题}</h2><table>{格}</table>"

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
<div class="卡"><b>{果['子代理数']}</b><span>子代理路数</span></div>
<div class="卡"><b>{果['总调用']}</b><span>工具调用</span></div>
<div class="卡"><b>{果['占比']['探索']}%</b><span>探索占比</span></div>
<div class="卡"><b>{果['黑洞']['命令超时']}</b><span>命令超时</span></div>
</div>
{行("工具调用分布", 果["工具"])}
{行("四类占比", {k: str(v) + "%" for k, v in 果["占比"].items()})}
{行("黑洞计数", 果["黑洞"])}
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
    解析.add_argument("--html", action="store_true", help="额外产 HTML 报告")
    参 = 解析.parse_args(argv)
    根 = Path(参.目录) if 参.目录 else 默认日志根
    日志 = 扫日志(根, 参.小时)
    if not 日志:
        print(f"最近 {参.小时} 小时内没有子代理日志：{根}")
        return 0
    剖析表 = [剖析一篇(p) for p in 日志]
    剖析表 = [a for a in 剖析表 if a["调用数"]]
    果 = 汇总(剖析表, 查纪律送达(日志))
    归因表 = 归因(果)
    趋势 = 比趋势(果)
    打印报告(果, 剖析表, 归因表, 趋势)
    快照 = 写快照(果)
    print(f"\n快照：{快照}")
    if 参.html:
        print(f"HTML：{写HTML(果, 归因表, 趋势)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
