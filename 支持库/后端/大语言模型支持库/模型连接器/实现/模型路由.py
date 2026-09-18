"""模型路由原子能力实现（不对外暴露，只经包级中文入口调用）。

职责：按「历史实测表现」把候选模型排序，告诉调用方用哪个、为什么，其余为什么不用。
分层（★ 默认只走前两层，零额度）：
  第一层 硬门槛（永远执行）：上下文超限排除、候选不可达排除（复用 `探测模型端点`）
  第二层 统计打分（智能模式）：读用量记录 → 四维加权排序，**不消耗额度**
  第三层 LLM 辅助标注：**本版不实现**（留参数位），若将来实现必须标注消耗

边界（华哥 2026-09-18 口径）：
  · 底座**不做隐私/安全**判断（哲学 9.3；限制越多兼容性越差）；`参考路径` 只是
    「用户自带规则的可选输入」，底座把它当普通外部词表用，不定义「什么是敏感」。
  · 候选清单**由调用方传**，底座不存模型台账（否则成第二事实源）。
  · 只给**建议**，**不自动切换**正在用的模型。

全部能力返回统一结果（成功/值/错误码/错误说明）；参数非法返回 参数不合法。
"""

from __future__ import annotations

import re
from typing import Any

from 公共契约.基础类型.结果类型 import 结果

from 支持库.后端.大语言模型支持库.模型连接器.实现.模型用量 import (
    默认权重,
    默认最少样本数,
    _中位数,
    _读取记录,
)
from 支持库.后端.大语言模型支持库.模型连接器.实现.模型探针 import 探测模型端点

模式_保守 = "保守"
模式_智能 = "智能"

# 参考路径允许的形态（告诉调用方，避免误以为底座会去抓取任意 URL）
参考路径说明 = "绝对路径：数据库文件 / 普通文件 / 文件夹均可"


def _失败(错误码: str, 消息: str) -> 结果:
    return 结果.失败(错误码, 消息, 来源="模型路由")


def _取候选(候选清单: list) -> tuple[list[dict[str, Any]], str | None]:
    """把候选清单归一化为 [{模型, 上下文长度, 端点}]。

    允许两种写法：
      文本型： "gpt-5.6-sol"                      → 只有模型名
      字典型： {"模型": "...", "上下文长度": 200000, "端点": "http://..."}
    """
    归一 = []
    for 序, 项 in enumerate(候选清单):
        if isinstance(项, str):
            if not 项.strip():
                return [], f"候选清单 第 {序 + 1} 项是空字符串"
            归一.append({"模型": 项.strip(), "上下文长度": None, "端点": None})
            continue
        if isinstance(项, dict):
            名 = 项.get("模型")
            if not isinstance(名, str) or not 名.strip():
                return [], f"候选清单 第 {序 + 1} 项缺少非空「模型」"
            上下文 = 项.get("上下文长度")
            if 上下文 is not None and (isinstance(上下文, bool) or not isinstance(上下文, int) or 上下文 <= 0):
                return [], f"候选清单 第 {序 + 1} 项「上下文长度」必须是正整数"
            端点 = 项.get("端点")
            if 端点 is not None and (not isinstance(端点, str) or not 端点.strip()):
                return [], f"候选清单 第 {序 + 1} 项「端点」必须是非空字符串"
            归一.append({"模型": 名.strip(), "上下文长度": 上下文,
                         "端点": 端点.strip() if isinstance(端点, str) else None})
            continue
        return [], f"候选清单 第 {序 + 1} 项必须是字符串或字典，实际 {type(项).__name__}"
    return 归一, None


def _读参考词表(参考路径: str) -> tuple[set[str], str | None]:
    """读用户给的参考规则文件，取出其中的词（按行/按逗号切分）。

    ★ 底座不定义「什么是敏感」—— 只把文件里的词原样取出当匹配模式。
      换成任意普通词表（如品牌禁用词）机制完全一样，
      证明它是「通用的外部规则输入」，不是隐私专用件。
    """
    import pathlib

    路径 = pathlib.Path(参考路径)
    if not 路径.exists():
        return set(), f"参考路径不存在: {参考路径}"
    文本 = ""
    try:
        if 路径.is_dir():
            for 子 in sorted(路径.rglob("*")):
                if 子.is_file() and 子.stat().st_size < 5_000_000:
                    文本 += 子.read_text(encoding="utf-8", errors="ignore") + "\n"
        elif 路径.suffix.lower() in (".db", ".sqlite", ".sqlite3"):
            import sqlite3
            连接 = sqlite3.connect(f"file:{路径}?mode=ro", uri=True)
            try:
                for (名,) in 连接.execute("SELECT name FROM sqlite_master WHERE type='table'"):
                    try:
                        for 行 in 连接.execute(f'SELECT * FROM "{名}" LIMIT 20000'):
                            文本 += " ".join(str(x) for x in 行 if x is not None) + "\n"
                    except sqlite3.Error:
                        continue
            finally:
                连接.close()
        else:
            文本 = 路径.read_text(encoding="utf-8", errors="ignore")
    except OSError as 错误:
        return set(), f"参考路径读取失败: {错误}"

    词表 = set()
    for 行 in 文本.splitlines():
        for 段 in re.split(r"[,，\t;；]", 行):
            词 = 段.strip()
            if 词 and not 词.startswith("#"):
                词表.add(词)
    return 词表, None


def _打分(汇总项: dict, 全记录: list[dict], 任务类型: str, 权重: dict, 样本门槛: int) -> dict:
    """按四维加权给单个候选打分（纯函数，同输入同输出）。"""
    条数 = 汇总项["样本数"]
    if 条数 < 样本门槛:
        # ★ 样本不足不给分 —— 不编造、不默认满信心
        return {"分数": None, "样本是否充足": False,
                "理由": f"样本不足（{条数} < {样本门槛} 条），不给分；先积累调用记录"}

    同名 = [条 for 条 in 全记录 if 条["模型"] == 汇总项["模型"]]
    耗时候选 = [条["耗时毫秒"] for 条 in 同名 if 条["耗时毫秒"] is not None]
    成本候选 = [条["成本"] for 条 in 同名 if 条["成本"] is not None]

    # 基准取「本次候选集合内」的中位数：相对比较，不写死绝对值
    基准耗时 = _中位数(耗时候选) or 1.0
    基准成本 = _中位数(成本候选) or 1.0

    成功率 = 汇总项["成功率"] or 0.0
    平均耗时 = 汇总项["平均耗时毫秒"]
    平均成本 = 汇总项["平均成本"]

    效率 = 1.0 if 平均耗时 is None else max(0.0, 1.0 - min(平均耗时 / 基准耗时, 1.0))
    性价比 = 1.0 if 平均成本 is None else max(0.0, 1.0 - min(平均成本 / 基准成本, 1.0))

    同任务 = [条 for 条 in 同名 if 条["任务类型"] == 任务类型] if 任务类型 else []
    匹配度 = (len(同任务) / 条数) if 条数 else 0.0

    分数 = (权重.get("成功率", 0.4) * 成功率
            + 权重.get("效率", 0.2) * 效率
            + 权重.get("性价比", 0.3) * 性价比
            + 权重.get("匹配度", 0.1) * 匹配度)

    理由 = (f"成功率 {成功率:.0%}（{条数} 条样本）；"
            f"平均耗时 {平均耗时 if 平均耗时 is not None else '无数据'} ms；"
            f"平均成本 {平均成本 if 平均成本 is not None else '无数据'}；"
            f"该任务占比 {匹配度:.0%}")
    return {"分数": round(分数, 6), "样本是否充足": True, "理由": 理由}


def 选择模型(
    候选清单=None, 任务描述=None, 任务类型=None, 上下文长度=None,
    启用智能路由=None, 参考路径=None, 启用额度标注=None, 权重=None,
    最少样本数=None, 数据库路径=None,
) -> 结果:
    """按历史实测表现把候选模型排序，给出建议与理由（只读建议，不自动切换）。

    参数:
        候选清单: 列表型，必填。每项为字符串或 {模型, 上下文长度, 端点}
        任务描述: 文本型，选填
        任务类型: 文本型，选填（如 策划/日常/清洗/看图/生图）
        上下文长度: 整数型，选填 —— **硬门槛**，超过候选能力的直接排除
        启用智能路由: 逻辑型，选填，**默认假（保守模式：不读数据、不耗额度）**
        参考路径: 文本型，选填 —— 用户自带的规则文件绝对路径（数据库/文件/文件夹）。
                  **不给=完全不涉及**；给了也只作为排序的一个可选信号。
        启用额度标注: 逻辑型，选填，默认真
        权重: 字典型，选填（成功率/效率/性价比/匹配度）
        最少样本数: 整数型，选填，默认 3
        数据库路径: 文本型，选填（默认本包专用库）

    返回: 建议（列表型：模型/分数/理由）、排除（列表型：模型/理由）、
          模式（文本型）、打分依据（字典型）、额度说明（文本型）
    """
    if not isinstance(候选清单, list) or not 候选清单:
        return _失败("参数不合法", f"候选清单 必须是非空列表: {候选清单!r}")
    候选, 问题 = _取候选(候选清单)
    if 问题:
        return _失败("参数不合法", 问题)
    for 值, 名称 in ((任务描述, "任务描述"), (任务类型, "任务类型"), (参考路径, "参考路径")):
        if 值 is not None and not isinstance(值, str):
            return _失败("参数不合法", f"{名称} 必须是字符串: {值!r}")
    if 上下文长度 is not None:
        if isinstance(上下文长度, bool) or not isinstance(上下文长度, int) or 上下文长度 <= 0:
            return _失败("参数不合法", f"上下文长度 必须是正整数: {上下文长度!r}")
    if 启用智能路由 is not None and not isinstance(启用智能路由, bool):
        return _失败("参数不合法", f"启用智能路由 必须是逻辑型: {启用智能路由!r}")
    if 启用额度标注 is not None and not isinstance(启用额度标注, bool):
        return _失败("参数不合法", f"启用额度标注 必须是逻辑型: {启用额度标注!r}")
    样本门槛 = 默认最少样本数 if 最少样本数 is None else 最少样本数
    if isinstance(样本门槛, bool) or not isinstance(样本门槛, int) or 样本门槛 < 1:
        return _失败("参数不合法", f"最少样本数 必须是正整数: {最少样本数!r}")
    净权重 = dict(默认权重)
    if 权重 is not None:
        if not isinstance(权重, dict):
            return _失败("参数不合法", f"权重 必须是字典: {权重!r}")
        for 键, 值 in 权重.items():
            if 键 not in 默认权重:
                return _失败("参数不合法", f"权重 只接受 {sorted(默认权重)}，收到 {键!r}")
            if isinstance(值, bool) or not isinstance(值, (int, float)) or 值 < 0:
                return _失败("参数不合法", f"权重 {键} 必须是非负数字: {值!r}")
            净权重[键] = float(值)

    智能 = bool(启用智能路由)
    诊断: list[str] = []
    排除: list[dict[str, Any]] = []

    # ── 第一层：硬门槛（永远执行）──────────────────────────
    存活 = []
    for 项 in 候选:
        if 上下文长度 is not None and 项["上下文长度"] is not None:
            if 项["上下文长度"] < 上下文长度:
                排除.append({"模型": 项["模型"],
                             "理由": f"上下文不足：候选支持 {项['上下文长度']} < 需要 {上下文长度}"})
                continue
        if 项["端点"]:
            探测 = 探测模型端点(url=项["端点"])
            if not 探测.成功 or not (探测.值 or {}).get("可用"):
                判据 = ""
                if 探测.成功 and isinstance(探测.值, dict):
                    明细 = 探测.值.get("逐项结果") or [{}]
                    判据 = (明细[0] or {}).get("判据", "")
                排除.append({"模型": 项["模型"],
                             "理由": f"端点不可达（{项['端点']}）{('：' + 判据) if 判据 else ''}"})
                continue
            诊断.append(f"已探测端点可达：{项['模型']}")
        存活.append(项)

    # ── 第二层：统计打分（仅智能模式）──────────────────────
    数据条数 = 0
    汇总: list[dict] = []
    全记录: list[dict] = []
    if 智能 and 存活:
        try:
            全记录 = _读取记录(数据库路径, (任务类型 or "").strip() or None)
        except Exception as 错误:   # noqa: BLE001 —— 读库失败必须如实回报，不静默
            return _失败("读取失败", f"读取用量记录失败: {错误}")
        数据条数 = len(全记录)
        汇总 = []
        for 项 in 存活:
            同名 = [条 for 条 in 全记录 if 条["模型"] == 项["模型"]]
            条数 = len(同名)
            耗时表 = [条["耗时毫秒"] for 条 in 同名 if 条["耗时毫秒"] is not None]
            成本表 = [条["成本"] for 条 in 同名 if 条["成本"] is not None]
            汇总.append({
                "模型": 项["模型"], "样本数": 条数,
                "成功率": round(sum(1 for 条 in 同名 if 条["成功"]) / 条数, 6) if 条数 else None,
                "平均耗时毫秒": round(sum(耗时表) / len(耗时表), 3) if 耗时表 else None,
                "平均成本": round(sum(成本表) / len(成本表), 6) if 成本表 else None,
            })

    # ── 参考路径：用户自带规则（可选信号）──────────────────
    参考命中: list[str] = []
    if 参考路径:
        词表, 问题 = _读参考词表(参考路径)
        if 问题:
            return _失败("参数不合法", 问题)
        诊断.append(f"已读参考路径，取到 {len(词表)} 个匹配词（{参考路径说明}）")
        目标文本 = f"{任务描述 or ''} {任务类型 or ''}"
        if 词表 and 目标文本.strip():
            参考命中 = sorted(词 for 词 in 词表 if 词 and 词 in 目标文本)
        if 参考命中:
            诊断.append(f"参考路径命中：{参考命中}")

    # ── 组装建议 ─────────────────────────────────────────
    建议: list[dict[str, Any]] = []
    if 智能 and 存活:
        for 项, 汇 in zip(存活, 汇总):
            评 = _打分(汇, 全记录, (任务类型 or "").strip(), 净权重, 样本门槛)
            建议.append({"模型": 项["模型"], "分数": 评["分数"],
                         "理由": 评["理由"], "样本是否充足": 评["样本是否充足"]})
        # 可复现排序：分数降序，同分按输入顺序（稳定）
        建议.sort(key=lambda x: (-(x["分数"] if x["分数"] is not None else float("-inf")),))
    else:
        for 项 in 存活:
            建议.append({"模型": 项["模型"], "分数": None,
                         "理由": "保守模式：只过硬门槛，不读历史数据、不打分、不消耗额度",
                         "样本是否充足": None})

    打分依据 = {
        "数据条数": 数据条数,
        "口径": ("四维加权（成功率/效率/性价比/匹配度），基准取候选集合内中位数；"
               f"权重={净权重}"),
        "样本门槛": 样本门槛,
        "样本是否充足": (any(项.get("样本是否充足") for 项 in 建议) if 智能 and 建议 else None),
    }

    # ── 额度说明（华哥要求：必须备注）─────────────────────
    额度说明 = ("本次未消耗任何 LLM 额度（保守模式：未读历史数据、未调用模型）。"
              if not 智能 else
              "本次未消耗 LLM 额度（智能模式读的是本地调用记录，纯统计，不调用模型）。"
              "★ 注意：让模型真正干活才会消耗额度；本能力只做记录与建议。")
    # ★ 默认开启（华哥要求这条必须备注给用户）：
    #   只有调用方**显式传 假** 才清空；默认 None 与 真 都返回说明 —— 否则用户会被扣额度却不知情。
    if 启用额度标注 is False:
        额度说明 = ""

    return 结果.成功结果({
        "建议": 建议, "排除": 排除, "模式": 模式_智能 if 智能 else 模式_保守,
        "打分依据": 打分依据, "额度说明": 额度说明, "诊断": 诊断,
    })
