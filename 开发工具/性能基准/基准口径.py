"""性能基准的公共口径：错误分类、参数校验、采样与统计（只用标准库）。

这里只放「怎么量」的规矩，不放任何被测对象：
- 统一错误类型 `基准错误`：分 参数错误 / 场景失败 / 口径失败 / 落盘失败 四类，
  各自对应固定退出码 —— 基准**必须明确失败，绝不静默出 0**（铁律）。
- 参数校验：非法值当场拒绝，不做「非法即默认」的静默回落。
- 采样：串行 / 并发两种，返回逐次耗时样本（毫秒）与墙钟秒。
- 统计：p50 / p90 / p99 / 均值 / 最小 / 最大 / 标准差，全部由 `statistics` 与
  自实现的线性插值分位给出（`statistics.quantiles` 在样本少时口径不稳，不用）。
"""

from __future__ import annotations

import json
import math
import statistics
import threading
import time
from pathlib import Path
from typing import Any, Callable, NoReturn

基准版本 = "1.0.0"

# ── 默认口径（全部可经命令行覆盖，覆盖点唯一）──────────────────────
默认轮数 = 2000
默认预热轮数 = 200
默认重复 = 3
默认并发 = 4
默认抖动上限 = 0.35
轮数下限 = 10
轮数上限 = 200000
预热轮数上限 = 20000
重复上限 = 20
并发上限 = 64

# ── 退出码（基准自身的失败语义，不是网关公开错误码）─────────────────
# 说明：本工具**不新增任何网关公开错误码**（新增公开码必须同时登记到
# 统一网关.本地网关 的 公开错误码状态映射 与 网关核心 的 公开错误说明表，
# 而本任务只允许新增 开发工具/性能基准/ 下的文件）。故基准的失败一律用
# 进程退出码 + stderr 中文说明表达，不冒充公开错误码。
退出码_成功 = 0
退出码_参数错误 = 2
退出码_场景失败 = 3
退出码_口径失败 = 4
退出码_落盘失败 = 5

类别_参数错误 = "参数错误"
类别_场景失败 = "场景失败"
类别_口径失败 = "口径失败"
类别_落盘失败 = "落盘失败"

类别对应退出码 = {
    类别_参数错误: 退出码_参数错误,
    类别_场景失败: 退出码_场景失败,
    类别_口径失败: 退出码_口径失败,
    类别_落盘失败: 退出码_落盘失败,
}


class 基准错误(Exception):
    """基准的明确失败：类别 + 中文说明，绝不静默降级成 0。"""

    def __init__(self, 类别: str, 说明: str) -> None:
        super().__init__(f"{类别}：{说明}")
        self.类别 = 类别
        self.说明 = 说明


def 报参数错误(说明: str) -> NoReturn:
    raise 基准错误(类别_参数错误, 说明)


def 报场景失败(说明: str) -> NoReturn:
    raise 基准错误(类别_场景失败, 说明)


def 报口径失败(说明: str) -> NoReturn:
    raise 基准错误(类别_口径失败, 说明)


def 报落盘失败(说明: str) -> NoReturn:
    raise 基准错误(类别_落盘失败, 说明)


# ═══════════════════════════════════════════════════════════════
# 参数校验：非法值明确拒绝，不做静默回落
# ═══════════════════════════════════════════════════════════════
def 校验整数(名称: str, 原文: str | int, *, 下限: int, 上限: int) -> int:
    """把命令行原文解析为区间内整数；非法（非数字/越界/布尔）当场明确失败。"""
    if isinstance(原文, bool):
        报参数错误(f"{名称} 必须是整数，不能是布尔值（收到 {原文!r}）")
    if isinstance(原文, int):
        值 = 原文
    else:
        文本 = str(原文).strip()
        if not 文本:
            报参数错误(f"{名称} 不能为空")
        if not 文本.lstrip("+-").isdigit():
            报参数错误(f"{名称} 必须是整数（收到 {文本!r}）")
        值 = int(文本)
    if 值 < 下限 or 值 > 上限:
        报参数错误(f"{名称} 必须在 {下限} 到 {上限} 之间（收到 {值}）")
    return 值


def 校验小数(名称: str, 原文: str | float, *, 下限: float, 上限: float) -> float:
    """把命令行原文解析为区间内小数；非法当场明确失败。"""
    if isinstance(原文, bool):
        报参数错误(f"{名称} 必须是数值，不能是布尔值（收到 {原文!r}）")
    try:
        值 = float(原文)
    except (TypeError, ValueError):
        报参数错误(f"{名称} 必须是数值（收到 {原文!r}）")
    if not math.isfinite(值):
        报参数错误(f"{名称} 必须是有限数值（收到 {原文!r}）")
    if 值 < 下限 or 值 > 上限:
        报参数错误(f"{名称} 必须在 {下限} 到 {上限} 之间（收到 {值}）")
    return 值


# ═══════════════════════════════════════════════════════════════
# 统计
# ═══════════════════════════════════════════════════════════════
def 分位(有序样本: list[float], 分位值: float) -> float:
    """线性插值分位（样本已升序）。样本为空即明确失败，不返回 0。"""
    if not 有序样本:
        报口径失败("分位计算收到空样本（拒绝返回 0 冒充结果）")
    if len(有序样本) == 1:
        return 有序样本[0]
    位置 = (len(有序样本) - 1) * 分位值
    下 = int(math.floor(位置))
    上 = int(math.ceil(位置))
    if 下 == 上:
        return 有序样本[下]
    权重 = 位置 - 下
    return 有序样本[下] + (有序样本[上] - 有序样本[下]) * 权重


def 统计样本(样本表: list[float]) -> dict[str, Any]:
    """把逐次耗时样本（毫秒）统计成机器可读字典。"""
    if not 样本表:
        报口径失败("统计收到空样本（拒绝产出「0 毫秒」这种假结果）")
    for 序号, 值 in enumerate(样本表):
        if not isinstance(值, (int, float)) or isinstance(值, bool):
            报口径失败(f"第 {序号 + 1} 个样本不是数值：{值!r}")
        if not math.isfinite(float(值)) or float(值) < 0:
            报口径失败(f"第 {序号 + 1} 个样本不是有限非负数：{值!r}")
    有序 = sorted(float(值) for 值 in 样本表)
    return {
        "样本数": len(有序),
        "最小毫秒": round(有序[0], 4),
        "p50毫秒": round(分位(有序, 0.50), 4),
        "p90毫秒": round(分位(有序, 0.90), 4),
        "p99毫秒": round(分位(有序, 0.99), 4),
        "最大毫秒": round(有序[-1], 4),
        "均值毫秒": round(statistics.fmean(有序), 4),
        "标准差毫秒": round(statistics.pstdev(有序), 4) if len(有序) > 1 else 0.0,
    }


# ═══════════════════════════════════════════════════════════════
# 采样
# ═══════════════════════════════════════════════════════════════
def 采样串行(调用: Callable[[], Any], *, 轮数: int, 预热轮数: int) -> tuple[list[float], float]:
    """串行采样：先预热（不计入），再逐次计时。返回 (样本毫秒表, 墙钟秒)。"""
    for _ in range(预热轮数):
        调用()
    样本: list[float] = []
    开始 = time.perf_counter()
    for _ in range(轮数):
        起点 = time.perf_counter()
        调用()
        样本.append((time.perf_counter() - 起点) * 1000.0)
    墙钟秒 = time.perf_counter() - 开始
    return 样本, 墙钟秒


def 采样并发(调用: Callable[[], Any], *, 轮数: int, 预热轮数: int,
             并发数: int) -> tuple[list[float], float]:
    """并发采样：`并发数` 条线程各跑 `轮数` 次；返回 (样本毫秒表, 墙钟秒)。

    墙钟秒是**整段并发墙钟**（不是各线程耗时之和），QPS 必须按它算，
    否则会把并发吞吐算成串行吞吐。预热同样在并发前跑满。
    """
    if 并发数 < 2:
        报参数错误(f"并发采样要求并发数 ≥ 2（收到 {并发数}）")
    for _ in range(预热轮数):
        调用()
    样本池: list[list[float]] = [[] for _ in range(并发数)]
    起点栏 = threading.Barrier(并发数)
    错误栏: list[BaseException] = []

    def 工作(序号: int) -> None:
        # 线程内任何异常都必须被收上来：否则线程静默死掉，样本数对不上，
        # 而基准只会看到一个「样本少了的漂亮数字」——正是要禁止的假绿。
        try:
            起点栏.wait(timeout=30)
        except threading.BrokenBarrierError as 异常:
            错误栏.append(异常)
            return
        try:
            for _ in range(轮数):
                起点 = time.perf_counter()
                调用()
                样本池[序号].append((time.perf_counter() - 起点) * 1000.0)
        except BaseException as 异常:  # noqa: BLE001 - 原样带回主线程
            错误栏.append(异常)

    线程表 = [threading.Thread(target=工作, args=(序号,), daemon=True)
              for 序号 in range(并发数)]
    开始 = time.perf_counter()
    for 线程 in 线程表:
        线程.start()
    for 线程 in 线程表:
        线程.join()
    墙钟秒 = time.perf_counter() - 开始
    if 错误栏:
        raise 错误栏[0]
    样本: list[float] = []
    for 段 in 样本池:
        样本.extend(段)
    if len(样本) != 轮数 * 并发数:
        报口径失败(f"并发采样样本数不符：期望 {轮数 * 并发数}，实得 {len(样本)}")
    return 样本, 墙钟秒


def 算每秒次数(样本数: int, 墙钟秒: float) -> float:
    """每秒次数（QPS/TPS）：样本数 ÷ 墙钟秒。墙钟秒为 0 即明确失败。"""
    if 墙钟秒 <= 0:
        报口径失败(f"墙钟秒必须为正（收到 {墙钟秒}），拒绝算出无穷大吞吐")
    return round(样本数 / 墙钟秒, 2)


# ═══════════════════════════════════════════════════════════════
# 统一结果的收口：非成功即明确失败（不静默出 0）
# ═══════════════════════════════════════════════════════════════
def 要求成功(结果对象: Any, 场景说明: str) -> Any:
    """把统一结果收口为「值」；失败/空返回一律明确抛错。

    为什么必须在这里拦：基准最容易出的假结果是「调用失败 → 样本为空 →
    统计返回 0 毫秒 → 看起来性能极好」。这条把该路径彻底堵死。
    """
    if 结果对象 is None:
        报场景失败(f"{场景说明}：调用返回 None（基准拒绝把空返回当成功）")
    成功 = getattr(结果对象, "成功", None)
    if 成功 is None and isinstance(结果对象, dict):
        成功 = 结果对象.get("成功")
    if 成功 is not True:
        错误码 = getattr(结果对象, "错误码", "") or (
            结果对象.get("错误码", "") if isinstance(结果对象, dict) else "")
        错误说明 = getattr(结果对象, "错误说明", "") or (
            结果对象.get("错误说明", "") if isinstance(结果对象, dict) else "")
        报场景失败(f"{场景说明}：调用失败（错误码 {错误码 or '未给出'}）："
                 f"{错误说明 or '未给出错误说明'}")
    值 = getattr(结果对象, "值", None)
    if 值 is None and isinstance(结果对象, dict):
        值 = 结果对象.get("值")
    return 值


# ═══════════════════════════════════════════════════════════════
# 结果落盘与读取
# ═══════════════════════════════════════════════════════════════
def 写结果(结果: dict[str, Any], 目录: Path, 文件名: str) -> Path:
    """把机器可读结果写成 UTF-8 JSON；目录建不了/写不进即明确失败。"""
    目录 = Path(目录)
    try:
        目录.mkdir(parents=True, exist_ok=True)
    except OSError as 异常:
        报落盘失败(f"结果目录不可用 {目录}：{type(异常).__name__}: {异常}")
    目标 = 目录 / 文件名
    try:
        目标.write_text(json.dumps(结果, ensure_ascii=False, indent=2) + "\n",
                       encoding="utf-8")
    except OSError as 异常:
        报落盘失败(f"结果写不进 {目标}：{type(异常).__name__}: {异常}")
    return 目标


def 读结果(路径: Path) -> dict[str, Any]:
    """读一份基准结果 JSON；不存在/不是 JSON/不是对象都明确失败。"""
    路径 = Path(路径)
    if not 路径.is_file():
        报参数错误(f"结果文件不存在：{路径}")
    try:
        数据 = json.loads(路径.read_text(encoding="utf-8"))
    except (OSError, ValueError) as 异常:
        报参数错误(f"结果文件读不出合法 JSON {路径}：{type(异常).__name__}: {异常}")
    if not isinstance(数据, dict) or "场景结果" not in 数据:
        报参数错误(f"结果文件不是基准结果（缺少 场景结果）：{路径}")
    return 数据


# ═══════════════════════════════════════════════════════════════
# 人读摘要（中文）
# ═══════════════════════════════════════════════════════════════
def 渲染摘要(结果: dict[str, Any]) -> str:
    """把基准结果渲染成中文人读摘要（终端直接可看）。"""
    行: list[str] = []
    行.append("=" * 78)
    行.append(f"性能基准摘要 · 版本 {结果.get('基准版本', '未知')} · "
              f"生成时间 {结果.get('生成时间', '未知')}")
    参数 = 结果.get("参数", {})
    行.append(f"口径：轮数 {参数.get('轮数')} · 预热 {参数.get('预热轮数')} · "
              f"重复 {参数.get('重复')} · 并发 {参数.get('并发')}")
    行.append("=" * 78)
    for 场景 in 结果.get("场景结果", []):
        行.append("")
        行.append(f"【{场景.get('场景')}】{场景.get('说明', '')}")
        for 测量 in 场景.get("测量项", []):
            行.append(f"  - {测量.get('测量项')}")
            行.append(f"      样本 {测量.get('样本数')} 次 · "
                      f"p50 {测量.get('p50毫秒')} 毫秒 · "
                      f"p99 {测量.get('p99毫秒')} 毫秒 · "
                      f"均值 {测量.get('均值毫秒')} 毫秒 · "
                      f"标准差 {测量.get('标准差毫秒')} 毫秒")
            if "每秒次数" in 测量:
                行.append(f"      每秒次数 {测量.get('每秒次数')} 次/秒"
                          f"（{测量.get('每秒口径', '')}）")
            if 测量.get("附加结论"):
                for 键, 值 in 测量["附加结论"].items():
                    行.append(f"      {键}：{值}")
    for 场景 in 结果.get("场景结果", []):
        for 注释 in 场景.get("口径注释", []):
            行.append(f"注·{场景.get('场景')}：{注释}")
    重复 = 结果.get("重复稳定性")
    if 重复:
        行.append("")
        行.append(f"【重复稳定性】{重复.get('结论', '')}")
        for 项 in 重复.get("明细", []):
            行.append(f"  - {项.get('测量项')}：各轮 p50 {项.get('各轮p50毫秒')}，"
                      f"最大相对差异 {项.get('最大相对差异')}")
    抖动 = 结果.get("抖动自检")
    if 抖动:
        行.append("")
        行.append(f"【抖动自检】{抖动.get('结论', '')}")
        行.append(f"  两轮同输入 p50：{抖动.get('第一轮p50毫秒')} / "
                  f"{抖动.get('第二轮p50毫秒')} 毫秒，"
                  f"相对差异 {抖动.get('相对差异')}（上限 {抖动.get('上限')}）")
    行.append("")
    行.append("=" * 78)
    return "\n".join(行)
