"""检索准度基准：用平台自身数据造「带标准答案」的查询，量各路检索的准度。

为什么要有它（2026-09-21 华哥「搜索以准确为主」立项）：
「准不准」不能凭感觉。本脚本从平台既有数据**自动造题**——
能力层拿已注册能力的「一句话说明」当查询，标准答案就是它自己；
符号层拿代码地图节点名当查询，标准答案是它所在文件。
标准答案天然已知，固定随机种子保证**可重复**：改检索必重跑本基准。

★ 指标口径（华哥 2026-09-21 纠正，这是本基准的核心）：
    搜得出来 ≠ 准。返回 10 条里只有 1 条是你要的，准确率是 **10%**，不是 100%。
    只返回 1 条且就是你要的，才是 **100%**。
    所以主指标是 **精确率 = 命中题数 / 全部返回条数**（惩罚「给多了」），
    而不是「有没有命中」（那只算召回）。
    调用方本来只想要几条，由 `--期望条数` 控制；一般场景期望 1 条，
    确实需要多个选择时才调大（相当于「1 个决策 + N 个附属」）。

用法：
    python3.14 开发工具/检索准度基准.py                     # 期望 1 条 / 每路 30 题
    python3.14 开发工具/检索准度基准.py --期望条数 5         # 允许给 5 条，看精确率怎么掉
    python3.14 开发工具/检索准度基准.py --输出 记录.json
"""
from __future__ import annotations

import argparse
import json
import plistlib
import random
import statistics
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

# 路径含中文，必须 URL 编码；不编码会静默落到 404（实踩）。
网关地址 = "http://127.0.0.1:40007/" + urllib.parse.quote("网关/调用")
系统根 = Path(__file__).resolve().parents[1]
凭证键 = "系统库网关凭证"
网关配置 = Path.home() / "Library/LaunchAgents/com.huashi.gateway-40007.plist"
代码地图 = 系统根 / ".codegraph" / "codegraph.db"


def 取凭证() -> str:
    """从网关 launchd 配置取凭证；取不到如实报错，不猜、不写死。"""
    try:
        with 网关配置.open("rb") as 文件:
            配置 = plistlib.load(文件)
    except (OSError, plistlib.InvalidFileException) as 错误:
        raise SystemExit(f"读不到网关配置 {网关配置}：{错误}")
    凭证 = (配置.get("EnvironmentVariables") or {}).get(凭证键, "")
    if not 凭证:
        raise SystemExit(f"网关配置里没有环境变量 {凭证键}")
    return str(凭证)


def 调能力(能力id: str, 参数: dict, 凭证: str) -> dict:
    """经唯一网关调一条能力；失败如实返回信封，不抛（单题异常不能中断整轮）。"""
    体 = json.dumps({"操作": "调用能力", "能力id": 能力id, "参数": 参数,
                     "项目根": str(系统根)}, ensure_ascii=False).encode("utf-8")
    请求 = urllib.request.Request(网关地址, data=体, method="POST", headers={
        "Content-Type": "application/json; charset=utf-8",
        "Authorization": f"Bearer {凭证}"})
    try:
        with urllib.request.urlopen(请求, timeout=120) as 响应:
            return json.loads(响应.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as 错误:
        return json.loads(错误.read().decode("utf-8", "replace"))
    except Exception as 错误:  # noqa: BLE001 - 单题异常计入失败，不中断整轮
        return {"成功": False, "错误码": type(错误).__name__, "错误说明": str(错误)}


def 报错并停(标签: str, 信封: dict) -> None:
    """造题阶段拿不到数据就是硬阻塞：必须报出真实错误，不能静默交空报告。"""
    print(f"✗ {标签}失败：HTTP {信封.get('HTTP状态码')} / 错误码 {信封.get('错误码')!r} / "
          f"错误说明 {信封.get('错误说明')!r}")
    print(f"  信封原文：{json.dumps(信封, ensure_ascii=False)[:400]}")


def 造能力题(凭证: str, 题数: int, 种子: int) -> list[dict]:
    """能力层造题：查询＝能力的一句话说明，标准答案＝该能力 id。"""
    池: dict[str, dict] = {}
    for 词 in ("文件", "代码", "能力", "模型", "文档", "进程", "搜索", "目录"):
        信封 = 调能力("能力目录.搜索能力",
                      {"关键词": 词, "限制": 50, "细节级别": "完整契约"}, 凭证)
        if not 信封.get("成功"):
            报错并停(f"能力池造题（关键词「{词}」）", 信封)
            return []
        for 项 in ((信封.get("值") or {}).get("能力列表") or []):
            if 项.get("能力id") and 项.get("一句话说明"):
                池[项["能力id"]] = 项
    候选 = sorted(池.values(), key=lambda 项: 项["能力id"])
    return [{"查询": 项["一句话说明"], "标准答案": 项["能力id"]}
            for 项 in random.Random(种子).sample(候选, min(题数, len(候选)))]


def 判能力题(题: dict, 凭证: str, 期望条数: int) -> dict:
    信封 = 调能力("能力目录.搜索能力", {"关键词": 题["查询"], "限制": 期望条数}, 凭证)
    命中 = [项.get("能力id", "") for 项 in ((信封.get("值") or {}).get("能力列表") or [])]
    排名 = 命中.index(题["标准答案"]) + 1 if 题["标准答案"] in 命中 else 0
    return {"查询": 题["查询"][:40], "标准答案": 题["标准答案"],
            "排名": 排名, "命中": 排名 > 0, "返回数": len(命中)}


def 造符号题(凭证: str, 题数: int, 种子: int) -> list[dict]:
    """符号层造题：查询＝节点名称，标准答案＝它所在文件（相对项目根）。"""
    信封 = 调能力("代码解析支持库.代码地图.查询节点",
                  {"代码地图路径": str(代码地图), "关键词": "解析",
                   "模式": "名称子串", "最大条数": 300}, 凭证)
    if not 信封.get("成功"):
        报错并停("符号池造题", 信封)
        return []
    节点 = ((信封.get("值") or {}).get("节点列表") or [])
    候选 = [{"查询": 项["名称"], "标准答案": 项["文件路径"]}
            for 项 in 节点 if 项.get("名称") and 项.get("文件路径")]
    return random.Random(种子).sample(候选, min(题数, len(候选)))


def 判符号题(题: dict, 凭证: str, 期望条数: int) -> dict:
    信封 = 调能力("代码解析支持库.代码地图.查询节点",
                  {"代码地图路径": str(代码地图), "关键词": 题["查询"],
                   "模式": "名称子串", "最大条数": 期望条数}, 凭证)
    命中 = [项.get("文件路径", "") for 项 in ((信封.get("值") or {}).get("节点列表") or [])]
    排名 = 命中.index(题["标准答案"]) + 1 if 题["标准答案"] in 命中 else 0
    return {"查询": 题["查询"], "标准答案": 题["标准答案"],
            "排名": 排名, "命中": 排名 > 0, "返回数": len(命中)}


def 判文本题(题: dict, 凭证: str, 期望条数: int) -> dict:
    """文本层：正则搜符号定义，看标准答案文件是否出现在命中列表里。"""
    信封 = 调能力("文件系统支持库.内容检索.正则搜索",
                  {"根目录": str(系统根), "模式": f"def {题['查询']}\\(",
                   "最大匹配数": 期望条数}, 凭证)
    命中 = [项.get("文件", "") for 项 in ((信封.get("值") or {}).get("匹配列表") or [])]
    排名 = next((序 for 序, 文件 in enumerate(命中, 1)
                 if 题["标准答案"].endswith(文件) or 文件.endswith(题["标准答案"])), 0)
    return {"查询": 题["查询"], "标准答案": 题["标准答案"],
            "排名": 排名, "命中": 排名 > 0, "返回数": len(命中)}


def 汇总(名称: str, 结果表: list[dict], 期望条数: int) -> dict:
    """★ 主指标是精确率（命中题数 / 全部返回条数）——华哥 2026-09-21 口径。

    返回 10 条里只有 1 条对 = 10%；只返回 1 条且对 = 100%。
    召回率（命中题数/题数）与首条准确率（P@1）同时给出，三个数一起看。
    """
    题数 = len(结果表)
    命中数 = sum(1 for 项 in 结果表 if 项["命中"])
    首位 = sum(1 for 项 in 结果表 if 项["排名"] == 1)
    返回总数 = sum(项["返回数"] for 项 in 结果表)
    倒数 = [1 / 项["排名"] for 项 in 结果表 if 项["排名"] > 0]
    return {"路": 名称, "题数": 题数, "期望条数": 期望条数,
            "精确率": round(命中数 / 返回总数, 4) if 返回总数 else 0.0,
            "首条准确率": round(首位 / 题数, 4) if 题数 else 0.0,
            "召回率": round(命中数 / 题数, 4) if 题数 else 0.0,
            "平均返回条数": round(返回总数 / 题数, 2) if 题数 else 0.0,
            "超发量": round(返回总数 / 题数 - 期望条数, 2) if 题数 else 0.0,
            "MRR": round(statistics.fmean(倒数), 4) if 倒数 else 0.0}


def 主流程(题数: int, 期望条数: int, 种子: int, 输出: str) -> int:
    凭证 = 取凭证()
    print(f"系统根 {系统根}\n代码地图 {代码地图}（存在={代码地图.is_file()}）\n"
          f"每路 {题数} 题 / 期望条数 {期望条数} / 种子 {种子}\n")
    报告: dict = {"题数": 题数, "期望条数": 期望条数, "种子": 种子, "路": []}

    能力题 = 造能力题(凭证, 题数, 种子)
    if 能力题:
        报告["路"].append(汇总("能力层·搜索能力",
                              [判能力题(题, 凭证, 期望条数) for 题 in 能力题], 期望条数))
    else:
        print("⚠ 能力层造题失败（能力池为空），如实跳过，不伪造数字")

    符号题 = 造符号题(凭证, 题数, 种子)
    if 符号题:
        报告["路"].append(汇总("符号层·代码地图",
                              [判符号题(题, 凭证, 期望条数) for 题 in 符号题], 期望条数))
        报告["路"].append(汇总("文本层·正则搜索",
                              [判文本题(题, 凭证, 期望条数) for 题 in 符号题], 期望条数))
    else:
        print("⚠ 符号层造题失败（代码地图无节点），如实跳过，不伪造数字")

    print(f"{'路':<18}{'精确率':>9}{'首条准确':>10}{'召回率':>9}{'平均返回':>10}{'MRR':>8}")
    for 行 in 报告["路"]:
        print(f"{行['路']:<18}{行['精确率']:>9}{行['首条准确率']:>10}"
              f"{行['召回率']:>9}{行['平均返回条数']:>10}{行['MRR']:>8}")
    if 输出:
        Path(输出).write_text(json.dumps(报告, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n已写入 {输出}")
    return 0


def 入口() -> int:
    解析 = argparse.ArgumentParser(description="检索准度基准（主指标：精确率）")
    解析.add_argument("--题数", type=int, default=30, help="每路题数（默认 30）")
    解析.add_argument("--期望条数", type=int, default=1,
                     help="调用方本来想要几条（默认 1）；精确率的分母由此决定")
    解析.add_argument("--种子", type=int, default=20260921, help="随机种子（固定以保证可重复）")
    解析.add_argument("--输出", default="", help="可选：把报告写成 JSON")
    取值 = 解析.parse_args()
    return 主流程(取值.题数, 取值.期望条数, 取值.种子, 取值.输出)


if __name__ == "__main__":
    raise SystemExit(入口())
