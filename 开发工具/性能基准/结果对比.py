"""两次基准结果的对比：按「场景 + 测量项」配对，给出 p50/p99/吞吐的变化。

口径：
- 只比较**第 1 轮**结果（`重复 > 1` 时后续轮次是稳定性样本，不参与配对）；
- 同一场景的同一测量项才配对；只有一边有的项如实列为「仅基线有 / 仅当前有」，
  绝不静默丢弃（静默丢弃会让「口径变了」看起来像「性能变好了」）；
- 变化率 = (当前 − 基线) ÷ 基线；基线为 0 时不给变化率（拒绝算出无穷大或 0/0）。
"""

from __future__ import annotations

from typing import Any


def _索引(结果: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    表: dict[tuple[str, str], dict[str, Any]] = {}
    for 场景 in 结果.get("场景结果", []):
        if 场景.get("轮次") != 1:
            continue
        for 测量 in 场景.get("测量项", []):
            表[(str(场景.get("场景")), str(测量.get("测量项")))] = 测量
    return 表


def _变化率(基线值: Any, 当前值: Any) -> float | None:
    if not isinstance(基线值, (int, float)) or not isinstance(当前值, (int, float)):
        return None
    if isinstance(基线值, bool) or isinstance(当前值, bool):
        return None
    if 基线值 == 0:
        return None
    return round((当前值 - 基线值) / 基线值, 4)


def 对比结果(基线: dict[str, Any], 当前: dict[str, Any], *,
             基线文件: str = "") -> dict[str, Any]:
    """生成对比结论（机器可读）。"""
    基线表 = _索引(基线)
    当前表 = _索引(当前)
    if not 基线表:
        raise ValueError("基线结果里没有第 1 轮场景结果，无法对比")
    if not 当前表:
        raise ValueError("当前结果里没有第 1 轮场景结果，无法对比")
    明细: list[dict[str, Any]] = []
    for 键 in sorted(set(基线表) & set(当前表)):
        甲, 乙 = 基线表[键], 当前表[键]
        明细.append({
            "场景": 键[0], "测量项": 键[1],
            "基线p50毫秒": 甲.get("p50毫秒"), "当前p50毫秒": 乙.get("p50毫秒"),
            "p50变化率": _变化率(甲.get("p50毫秒"), 乙.get("p50毫秒")),
            "基线p99毫秒": 甲.get("p99毫秒"), "当前p99毫秒": 乙.get("p99毫秒"),
            "p99变化率": _变化率(甲.get("p99毫秒"), 乙.get("p99毫秒")),
            "基线每秒次数": 甲.get("每秒次数"), "当前每秒次数": 乙.get("每秒次数"),
            "每秒次数变化率": _变化率(甲.get("每秒次数"), 乙.get("每秒次数")),
        })
    return {
        "基线文件": 基线文件,
        "基线生成时间": 基线.get("生成时间"),
        "当前生成时间": 当前.get("生成时间"),
        "基线参数": 基线.get("参数"),
        "当前参数": 当前.get("参数"),
        "配对明细": 明细,
        "仅基线有": [f"{场景} / {测量}" for 场景, 测量 in sorted(set(基线表) - set(当前表))],
        "仅当前有": [f"{场景} / {测量}" for 场景, 测量 in sorted(set(当前表) - set(基线表))],
    }


def _百分比(值: Any) -> str:
    if not isinstance(值, (int, float)):
        return "无法比较"
    return f"{值 * 100:+.2f}%"


def 渲染对比(对比: dict[str, Any]) -> str:
    """把对比结论渲染成中文（终端可读）。"""
    行 = ["", "-" * 78,
          f"与基线对比（基线：{对比.get('基线文件') or '未记录'}，"
          f"生成时间 {对比.get('基线生成时间')}）",
          "-" * 78]
    if 对比.get("基线参数") != 对比.get("当前参数"):
        行.append("注意：两次口径参数不同（轮数/预热/重复/并发），"
                  "数字不可直接横比 —— 详见各自 参数 字段。")
    for 项 in 对比.get("配对明细", []):
        行.append(f"  {项['场景']} / {项['测量项']}")
        行.append(f"      p50 {项['基线p50毫秒']} → {项['当前p50毫秒']} 毫秒"
                  f"（{_百分比(项['p50变化率'])}）")
        行.append(f"      p99 {项['基线p99毫秒']} → {项['当前p99毫秒']} 毫秒"
                  f"（{_百分比(项['p99变化率'])}）")
        行.append(f"      每秒次数 {项['基线每秒次数']} → {项['当前每秒次数']}"
                  f"（{_百分比(项['每秒次数变化率'])}）")
    for 名称 in ("仅基线有", "仅当前有"):
        if 对比.get(名称):
            行.append(f"  {名称}（口径变化，未配对）：{'；'.join(对比[名称])}")
    if not 对比.get("配对明细"):
        行.append("  没有任何配对项 —— 两次结果的可比口径不重合。")
    return "\n".join(行)
