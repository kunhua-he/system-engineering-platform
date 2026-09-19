"""缺陷热点巡诊：**哪些代码经常出 bug**，以及为什么（含趋势对比）。

## 为什么要常态化做这件事（华哥 2026-09-19 明确要求）
> 「高频的都统计一下，然后拆分一下。看看是哪一些代码是经常 bug 的」
> 「没有现成工具，那就研发一个高效的工具。」

在此之前「哪块易错」只能靠印象；本工具把「修复频率」变成可查数字，
让**拆分优先级**从「行数大」升级为「**修复成本 × 行数**」——行数大但从不返工的
不该优先拆，改一次修三次的才该拆。

## 它量什么（全部来自真实 git 历史，不采样、不估算）
1. **修复类提交数**：提交标题命中修复词（修/bug/红/错/缺陷/纠/回退/坏/漏/漂移/不一致/
   失败/挂/崩/补/返工）的提交数；
2. **修复率** = 修复类提交 / 该文件总提交 —— 高修复率＝这块**天生易错**，而不是只是改得多；
3. **热度** = 修复类提交 × 当前行数 —— **改它的频率 × 改它的成本**，排序主判据；
4. **根因分类**（从提交标题二次归纳）：契约/类型、并发、跨平台、路径与编码、
   门禁判据、生成物同步、文档漂移 —— 看错都错在哪一类。

## 输出
- stdout：给人看的报告（热点榜 / 易错榜 / 根因分布）；
- `工程缓存/运行数据/缺陷巡诊/<时间戳>.json`：快照（下次跑自动对比出趋势）；
- `--html`：自包含 HTML（给华哥看）。

## 用法
    python3.14 开发工具/缺陷热点巡诊.py                 # 默认全历史
    python3.14 开发工具/缺陷热点巡诊.py --自 2026-08-01 # 只看某日期之后
    python3.14 开发工具/缺陷热点巡诊.py --html
    python3.14 开发工具/缺陷热点巡诊.py --顶级 40

**纯只读**：只读 git 历史与自己的快照，不碰仓库任何文件。
"""
from __future__ import annotations

import argparse
import html
import json
import os
import re
import subprocess
import time
from collections import Counter, defaultdict
from pathlib import Path

系统根 = Path(__file__).resolve().parents[1]
快照根 = 系统根 / "工程缓存" / "运行数据" / "缺陷巡诊"

# 修复类关键词：命中即算「这次提交是在修东西」。刻意保守，宁少不多（口径要能被复核）。
修复词 = re.compile(r"修|bug|BUG|红项|纠|回退|坏|漏声明|漂移|不一致|失败|挂掉|崩塌|返工|补丁")

# 根因分类：标题里出现即归类（一个提交可归多类，用于看分布）
根因表 = (
    ("契约与类型", re.compile(r"契约|类型|字段|裸布尔|参数|签名|枚举")),
    ("并发与竞态", re.compile(r"并发|竞态|锁|租约|原子|线程|死锁|进程组")),
    ("跨平台", re.compile(r"跨平台|Windows|Linux|POSIX|macOS|平台适配|路径分隔")),
    ("路径与编码", re.compile(r"路径|编码|中文名|fileURI|乱码|转义")),
    ("门禁与判据", re.compile(r"门禁|判据|基线|阈值|阻断|红项")),
    ("生成物同步", re.compile(r"生成物|摘要|说明书|参数契约|能力数据|派生物")),
    ("文档漂移", re.compile(r"文档|说明书|README|漂移")),
    ("超时与性能", re.compile(r"超时|性能|慢|耗时|挂后台|超时路")),
)

排除前缀 = ("工程缓存/", "开发文档/", "归档/", "__pycache__/")


def _git(参数: list[str], 超时: float = 600.0) -> str:
    """跑一条 git 命令并返回 stdout（环境已按项目要求前置 PATH）。"""
    环境 = dict(os.environ)
    环境["PATH"] = "/Library/Developer/CommandLineTools/usr/bin:/opt/homebrew/bin:" + 环境.get("PATH", "")
    结果 = subprocess.run(["git", *参数], capture_output=True, text=True,
                           env=环境, cwd=系统根, timeout=超时)
    return 结果.stdout


def 扫历史(自: str = "") -> tuple[dict, Counter]:
    """一次遍历 git 历史，按文件聚合计数与根因分布。

    用 `--no-merges --name-only --format=%x01%s` 一次拿全（标题用不可见字符做分隔，
    避免与文件名混行），比「每文件跑一次 git log」快两个数量级。
    """
    参数 = ["log", "--no-merges", "--name-only", "--format=%x01%s"]
    if 自:
        参数.insert(1, f"--since={自}")
    文本 = _git(参数)
    每文件: dict[str, dict] = defaultdict(lambda: {"总提交": 0, "修复提交": 0})
    根因 = Counter()
    标题 = ""
    for 行 in 文本.splitlines():
        if 行.startswith("\x01"):
            标题 = 行[1:]
            if 修复词.search(标题):
                for 名, 模式 in 根因表:
                    if 模式.search(标题):
                        根因[名] += 1
            continue
        文件 = 行.strip()
        if not 文件.endswith(".py") or any(文件.startswith(p) for p in 排除前缀):
            continue
        每文件[文件]["总提交"] += 1
        if 修复词.search(标题):
            每文件[文件]["修复提交"] += 1
    return 每文件, 根因


def 行数(相对路径: str) -> int:
    p = 系统根 / 相对路径
    try:
        return sum(1 for _ in open(p, encoding="utf-8", errors="replace"))
    except OSError:
        return 0


def 成表(每文件: dict) -> list[dict]:
    """把计数变成可排序清单；只保留仍存在的文件。"""
    表 = []
    for 文件, 计 in 每文件.items():
        if not 文件.endswith(".py"):
            continue
        行 = 行数(文件)
        if 行 == 0:
            continue
        总, 修 = 计["总提交"], 计["修复提交"]
        if 修 == 0:
            continue
        表.append({
            "文件": 文件, "行数": 行, "总提交": 总,
            "修复提交": 修, "修复率": round(修 / 总, 3) if 总 else 0.0,
            "热度": 修 * 行,
        })
    表.sort(key=lambda x: -x["热度"])
    return 表


def 比趋势(表: list[dict]) -> list[str]:
    """与上一份快照对比：新进榜、修复数上升的（趋势判据，不靠印象）。"""
    if not 快照根.is_dir():
        return ["（首份快照，无趋势可比）"]
    旧档 = sorted(快照根.glob("*.json"))
    if not 旧档:
        return ["（首份快照，无趋势可比）"]
    旧 = json.load(open(旧档[-1], encoding="utf-8"))
    旧修 = {x["文件"]: x["修复提交"] for x in 旧.get("清单", [])}
    新修 = {x["文件"]: x["修复提交"] for x in 表}
    行 = [f"对比上一份快照（{旧档[-1].stem}）："]
    上升 = sorted(((f, 新修[f] - 旧修.get(f, 0)) for f in 新修 if 新修[f] > 旧修.get(f, 0)),
                  key=lambda x: -x[1])[:8]
    if 上升:
        行.append("  修复数上升（说明这批仍在返工）：")
        行 += [f"    +{d}  {f}（{旧修.get(f, 0)}→{新修[f]}）" for f, d in 上升]
    else:
        行.append("  无文件修复数上升 ✓")
    return 行


def 打印报告(表: list[dict], 根因: Counter, 顶级: int, 趋势: list[str]) -> None:
    print("=" * 96)
    print(f"缺陷热点巡诊  {time.strftime('%Y-%m-%d %H:%M:%S')}   统计面 {len(表)} 个曾修复过的 .py")
    print("=" * 96)
    print("\n【热点榜】修复类提交 × 当前行数（改它的频率 × 改它的成本）")
    print(f"{'修复':>4} {'总':>4} {'修复率':>7} {'行数':>6} {'热度':>8}  文件")
    for x in 表[:顶级]:
        print(f"{x['修复提交']:>4} {x['总提交']:>4} {x['修复率']:>7.2f} {x['行数']:>6} {x['热度']:>8}  {x['文件']}")

    易错 = sorted([x for x in 表 if x["修复率"] >= 0.5 and x["修复提交"] >= 5],
                 key=lambda x: (-x["修复率"], -x["修复提交"]))
    if 易错:
        print(f"\n【易错榜】修复率 ≥0.50 且修复 ≥5 次（天生易错区，共 {len(易错)} 个）")
        for x in 易错[:20]:
            print(f"  {x['修复率']:.2f} ({x['修复提交']}/{x['总提交']}) {x['行数']:>5}行  {x['文件']}")

    双高 = [x for x in 表 if x["修复提交"] >= 8 and x["行数"] > 800]
    if 双高:
        print(f"\n【该拆第一名】修复 ≥8 次 且 >800 行（共 {len(双高)} 个）")
        for x in 双高:
            print(f"  {x['修复提交']:>3}修/{x['总提交']:>3}总 {x['行数']:>5}行  热度{x['热度']:>7}  {x['文件']}")

    if 根因:
        合计 = sum(根因.values())
        print(f"\n【根因分布】修复类提交的错都出在哪一类（合计 {合计} 次归类）")
        for 名, 数 in 根因.most_common():
            条 = "█" * max(1, round(数 / max(根因.values()) * 28))
            print(f"  {名:<12} {数:>4}  {条}")

    print("\n【趋势】")
    for 行 in 趋势:
        print(" ", 行)


def 写快照(表: list[dict], 根因: Counter, 参数: dict) -> Path:
    快照根.mkdir(parents=True, exist_ok=True)
    落点 = 快照根 / f"{time.strftime('%Y%m%d_%H%M%S')}.json"
    json.dump({
        "生成时间": time.strftime("%Y-%m-%d %H:%M:%S"),
        "参数": 参数,
        "口径": "修复类提交数（标题命中修复词）× 当前行数；根因按标题二次归类",
        "条数": len(表),
        "根因分布": dict(根因),
        "清单": 表,
    }, open(落点, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return 落点


def 写HTML(表: list[dict], 根因: Counter, 趋势: list[str]) -> Path:
    行HTML = []
    for x in 表[:40]:
        行HTML.append(
            "<tr><td>%d</td><td>%d</td><td>%.2f</td><td>%d</td><td>%d</td><td class=f>%s</td></tr>"
            % (x["修复提交"], x["总提交"], x["修复率"], x["行数"], x["热度"],
               html.escape(x["文件"])))
    根因HTML = "".join(
        f"<tr><td>{html.escape(名)}</td><td>{数}</td></tr>" for 名, 数 in 根因.most_common())
    文档 = f"""<!DOCTYPE html><html lang=zh-CN><meta charset=utf-8>
<title>缺陷热点巡诊</title><style>
body{{font:14px/1.6 -apple-system,"PingFang SC",sans-serif;margin:24px;color:#1a1a1a}}
h1{{font-size:20px;margin:0 0 4px}} .sub{{color:#777;font-size:12px;margin-bottom:16px}}
table{{border-collapse:collapse;width:100%;margin-bottom:22px}}
th,td{{border:1px solid #e3e3e3;padding:6px 8px;text-align:right}}
th{{background:#f6f8fa;text-align:right}} td.f{{text-align:left;font-family:ui-monospace,Menlo,monospace;font-size:12px}}
h2{{font-size:15px;margin:20px 0 8px}} pre{{background:#f6f8fa;padding:10px;border-radius:6px;font-size:12px}}
</style>
<h1>缺陷热点巡诊</h1>
<div class=sub>哪些代码经常出 bug ｜ 修复类提交 × 当前行数 ｜ {time.strftime('%Y-%m-%d %H:%M:%S')} ｜ 统计面 {len(表)} 个文件</div>
<h2>热点榜 TOP40</h2>
<table><tr><th>修复</th><th>总提交</th><th>修复率</th><th>行数</th><th>热度</th><th style=text-align:left>文件</th></tr>
{''.join(行HTML)}</table>
<h2>根因分布</h2>
<table><tr><th style=text-align:left>根因类</th><th>次数</th></tr>{根因HTML}</table>
<h2>趋势</h2><pre>{html.escape(chr(10).join(趋势))}</pre>
</html>"""
    落点 = 快照根 / f"{time.strftime('%Y%m%d_%H%M%S')}.html"
    落点.parent.mkdir(parents=True, exist_ok=True)
    落点.write_text(文档, encoding="utf-8")
    return 落点


def main(argv: list[str] | None = None) -> int:
    解析 = argparse.ArgumentParser(description="缺陷热点巡诊：哪些代码经常出 bug")
    解析.add_argument("--自", default="", help="只看该日期之后的提交，如 2026-08-01")
    解析.add_argument("--顶级", type=int, default=30, help="榜单条数，默认 30")
    解析.add_argument("--html", action="store_true", help="额外产 HTML 报告")
    参数 = 解析.parse_args(argv)

    每文件, 根因 = 扫历史(自=参数.自)
    表 = 成表(每文件)
    if not 表:
        print("没有统计到任何修复类提交（检查 --自 日期是否过早或 git 历史为空）")
        return 1
    趋势 = 比趋势(表)
    打印报告(表, 根因, 参数.顶级, 趋势)
    快照 = 写快照(表, 根因, {"自": 参数.自, "顶级": 参数.顶级})
    print(f"\n快照：{快照}")
    if 参数.html:
        print(f"HTML：{写HTML(表, 根因, 趋势)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
