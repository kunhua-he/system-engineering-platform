"""多路召回：并行调各路检索能力，各自取候选，不做任何排序决策。

为什么要把召回和融合分开：
- 召回只管「尽力捞」——每路取 候选深度 条，宁可多取，因为下一步靠 RRF 定序；
- 融合只管「怎么排」——只看排名不看分数，所以各路分数尺度不同也不用归一化；
- 分开后新增一路只需动本文件，融合层完全不变。

★ 单路失败不拖垮整轮：某路报错就记下来继续跑其它路，最后把各路状态如实带回。
  检索是「多路互补」，一路挂掉不该让调用方拿不到东西。
"""

from __future__ import annotations

import json
import plistlib
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

默认网关地址 = "http://127.0.0.1:40007/" + urllib.parse.quote("网关/调用")
凭证键 = "系统库网关凭证"
网关配置 = Path.home() / "Library/LaunchAgents/com.huashi.gateway-40007.plist"

# ★ 目标路由（2026-09-21 实测所得，这条比公式更重要）：
# 三路指向的东西**粒度不同**——能力层指向「能力」，符号层指向「代码位置」，
# 文本层指向「文本行」。RRF 的共识奖励在跨粒度混排时会变成「噪音路也能挤掉正确答案」：
# 实测 `目标=全部` 时精确率 0.875，**反而低于能力层单路的 1.0**。
# 所以默认只走能力层（agent 绝大多数时候就是找能力），要找代码才显式选 代码/全部。
默认目标 = "能力"
目标路表 = {
    "能力": ("能力层",),
    "代码": ("符号层", "文本层"),
    "全部": ("能力层", "符号层", "文本层"),
}

# 各路权重：能力层实测精确率 1.0（又准又克制）→ 最高；
# 文本层实测召回仅 0.6（克制但漏）→ 压一档，只当补充。
# 调参入口：调用方传 路权重 覆盖；权重存在这里是为了「加减权」可调且只有一处事实源。
默认路权重 = {"能力层": 1.0, "符号层": 1.0, "文本层": 0.6}


def _取凭证(凭证: str) -> str:
    """凭证优先用调用方传的；没传就从网关 launchd 配置读，读不到如实报错不猜。"""
    if 凭证:
        return 凭证
    try:
        with 网关配置.open("rb") as 文件:
            取值 = (plistlib.load(文件).get("EnvironmentVariables") or {}).get(凭证键, "")
    except (OSError, plistlib.InvalidFileException):
        return ""
    return str(取值)


def _调一路(地址: str, 凭证: str, 项目根: str, 能力id: str, 参数: dict) -> dict:
    """调一路能力，只回原始信封；异常不抛，交给调用方记入路状态。"""
    体 = json.dumps({"操作": "调用能力", "能力id": 能力id, "参数": 参数,
                     "项目根": 项目根}, ensure_ascii=False).encode("utf-8")
    请求 = urllib.request.Request(地址, data=体, method="POST", headers={
        "Content-Type": "application/json; charset=utf-8",
        "Authorization": f"Bearer {凭证}"})
    try:
        with urllib.request.urlopen(请求, timeout=120) as 响应:
            return json.loads(响应.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as 错误:
        return json.loads(错误.read().decode("utf-8", "replace"))
    except Exception as 错误:  # noqa: BLE001 - 单路异常记状态，不中断整轮
        return {"成功": False, "错误码": type(错误).__name__, "错误说明": str(错误)}


def _抽条(信封: dict, 列表键: str, 身份键: str, 摘要键: str) -> list[dict]:
    """从一路信封里抽出有序候选；列表顺序就是这一路的排名（RRF 只看这个）。"""
    if not 信封.get("成功"):
        return []
    行 = ((信封.get("值") or {}).get(列表键) or [])
    return [{"身份": str(项.get(身份键, "")), "摘要": str(项.get(摘要键, ""))}
            for 项 in 行 if 项.get(身份键)]


def 多路召回(关键词: str, 候选深度: int = 50, 目标: str = 默认目标, 项目根: str = "",
             代码地图路径: str = "", 网关地址: str = "", 凭证: str = "") -> tuple[list, dict]:
    """按 目标 选路依次召回（本地 HTTP，毫秒级），回 (各路候选表, 各路明细)。

    各路明细 里带每路的 成功/错误码/候选数/耗时，让调用方能看出「哪一路没出东西、为什么」，
    而不是只拿到一个空结果。
    """
    选路 = 目标路表.get(目标)
    if 选路 is None:
        raise ValueError(f"目标必须是 {'/'.join(目标路表)} 之一，收到 {目标!r}")
    地址 = 网关地址 or 默认网关地址
    真凭证 = _取凭证(凭证)
    根 = 项目根 or str(Path(__file__).resolve().parents[5])

    全部路定义 = [
        ("能力层", "能力目录.搜索能力",
         {"关键词": 关键词, "限制": 候选深度}, "能力列表", "能力id", "一句话说明"),
        ("符号层", "代码解析支持库.代码地图.查询节点",
         {"代码地图路径": 代码地图路径 or str(Path(根) / ".codegraph/codegraph.db"),
          "关键词": 关键词, "模式": "名称子串", "最大条数": 候选深度},
         "节点列表", "文件路径", "名称"),
        ("文本层", "文件系统支持库.内容检索.正则搜索",
         {"根目录": 根, "模式": 关键词, "最大匹配数": 候选深度}, "匹配列表", "文件", "文本"),
    ]

    候选: list[dict] = []
    明细: dict[str, dict] = {}
    for 路名, 能力id, 参数, 列表键, 身份键, 摘要键 in 全部路定义:
        if 路名 not in 选路:
            continue
        信封 = _调一路(地址, 真凭证, 根, 能力id, 参数)
        条 = _抽条(信封, 列表键, 身份键, 摘要键)
        明细[路名] = {"能力id": 能力id, "成功": bool(信封.get("成功")),
                      "错误码": str(信封.get("错误码", "")),
                      "错误说明": str(信封.get("错误说明", ""))[:200],
                      "候选数": len(条), "耗时毫秒": 信封.get("耗时毫秒")}
        候选.extend({"路": 路名, "排名": 序, "身份": f"{路名}·{项['身份']}",
                     "摘要": 项["摘要"], "指向": 项["身份"]}
                    for 序, 项 in enumerate(条, 1))
    return 候选, 明细
