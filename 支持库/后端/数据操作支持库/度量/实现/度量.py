"""度量原子能力：机器可读的计时数据规范化与摘要。

迁移自 V3 计时工具内核。容器键、名称键、耗时键、附带键的别名均可参数化
（默认值与原实现一致），底座内部不写死任何调用方的数据形状。
"""

from __future__ import annotations

import json
from typing import Any

from 公共契约.基础类型.结果类型 import 结果

来源标记 = "度量"
默认容器键 = ["items", "timings", "测试"]
默认名称键 = ["name", "tool", "target", "command"]
默认耗时键 = ["duration_seconds", "耗时", "seconds"]
默认状态键 = ["状态", "status"]
默认成功键 = "success"
默认附带键 = ["command", "level", "source"]


def _文本值(值: Any, 默认: str = "") -> str:
    if 值 is None:
        return 默认
    文本 = str(值).strip()
    return 文本 or 默认


def _秒值(值: Any) -> float | None:
    if 值 is None or 值 == "":
        return None
    try:
        return round(float(值), 3)
    except (TypeError, ValueError):
        return None


def _取首个命中(条目: dict, 键别名: list) -> Any:
    for 键 in 键别名:
        if 键 in 条目 and 条目.get(键) is not None:
            return 条目.get(键)
    return None


def 规范化计时条目(条目: Any, 索引: int = 0, 名称键别名: list | None = None,
                  耗时键别名: list | None = None, 状态键别名: list | None = None,
                  成功键: str | None = None, 附带键别名: list | None = None) -> 结果:
    """把一条原始计时数据规范化为 {名称, 状态, 耗时秒, …附带键}。

    条目不是对象时返回失败（由调用方决定是记警告还是中断）。
    名称缺失时用「计时_{索引+1}」兜底；状态缺失时若存在 success 键则按真假映射
    pass/fail，否则为 unknown。
    """
    if not isinstance(条目, dict):
        return 结果.失败("条目格式错误", f"计时条目 {索引} 不是对象", 来源=来源标记)

    名称键 = list(名称键别名) if isinstance(名称键别名, list) else list(默认名称键)
    耗时键 = list(耗时键别名) if isinstance(耗时键别名, list) else list(默认耗时键)
    状态键 = list(状态键别名) if isinstance(状态键别名, list) else list(默认状态键)
    成功键名 = 成功键 if isinstance(成功键, str) and 成功键 else 默认成功键
    附带键 = list(附带键别名) if isinstance(附带键别名, list) else list(默认附带键)

    名称 = _文本值(_取首个命中(条目, 名称键)) or f"计时_{索引 + 1}"
    耗时 = None
    for 键 in 耗时键:
        if 键 in 条目:
            耗时 = _秒值(条目.get(键))
            break
    状态值 = _取首个命中(条目, 状态键)
    状态 = _文本值(状态值)
    if not 状态 and 成功键名 in 条目:
        状态 = "pass" if bool(条目.get(成功键名)) else "fail"

    规范化: dict[str, Any] = {"名称": 名称, "状态": 状态 or "unknown", "耗时秒": 耗时}
    for 键 in 附带键:
        if 条目.get(键) is not None:
            规范化[键] = _文本值(条目.get(键))
    return 结果.成功结果({"条目": 规范化})


def _汇总(条目列表: list, 耗时键别名: list | None = None) -> dict[str, Any]:
    """汇总已规范化的计时条目（唯一实现，供能力与解析流程共用）。

    耗时键别名兼容调用方自己的字段命名（如 duration_seconds），默认「耗时秒」。
    """
    键候选 = list(耗时键别名) if isinstance(耗时键别名, list) and 耗时键别名 else ["耗时秒"]

    def 取耗时(项: dict) -> float | None:
        for 键 in 键候选:
            值 = 项.get(键)
            if isinstance(值, (int, float)) and not isinstance(值, bool):
                return float(值)
        return None

    耗时列表 = [x for x in (取耗时(项) for 项 in 条目列表 if isinstance(项, dict)) if x is not None]
    return {"数量": len(条目列表), "已计时数": len(耗时列表),
            "总耗时秒": round(sum(耗时列表), 3) if 耗时列表 else 0}   # 空列表返回整数 0，与原实现一致


def 汇总计时条目(条目列表: list, 耗时键别名: list | None = None) -> 结果:
    """汇总已规范化的计时条目：{数量, 已计时数, 总耗时秒}。

    耗时键别名兼容调用方自己的字段命名（如 duration_seconds）。
    """
    if not isinstance(条目列表, list):
        return 结果.失败("参数不合法", "条目列表必须是列表型", 来源=来源标记)
    return 结果.成功结果(_汇总(条目列表, 耗时键别名))


def 解析计时数据(原始文本: str = "", 容器键别名: list | None = None,
                名称键别名: list | None = None, 耗时键别名: list | None = None) -> 结果:
    """解析机器可读的计时数据（JSON 字符串），规范化条目并汇总。

    接受数组，或含容器键（默认 items/timings/测试）的对象，或单个条目对象。
    任何解析问题都记入警告列表并继续，不抛异常（与原实现一致）。
    返回 {条目列表, 摘要, 警告列表}。
    """
    if 原始文本 is None:
        原始文本 = ""
    if not isinstance(原始文本, str):
        return 结果.失败("参数不合法", "原始文本必须是字符串", 来源=来源标记)

    容器键 = list(容器键别名) if isinstance(容器键别名, list) else list(默认容器键)
    文本 = 原始文本.strip()
    条目列表: list[dict[str, Any]] = []
    警告列表: list[str] = []
    if not 文本:
        return 结果.成功结果({"条目列表": 条目列表, "摘要": _汇总([]), "警告列表": 警告列表})

    try:
        解码 = json.loads(文本)
    except json.JSONDecodeError as 错误:
        警告列表.append(f"计时数据已忽略：JSON 非法（第 {错误.pos} 个字符）")
        return 结果.成功结果({"条目列表": 条目列表, "摘要": _汇总([]), "警告列表": 警告列表})

    if isinstance(解码, dict):
        原始条目 = _取首个命中(解码, 容器键)
        if 原始条目 is None:
            原始条目 = [解码]
    elif isinstance(解码, list):
        原始条目 = 解码
    else:
        警告列表.append("计时数据已忽略：期望 JSON 数组或对象")
        return 结果.成功结果({"条目列表": 条目列表, "摘要": _汇总([]), "警告列表": 警告列表})

    if not isinstance(原始条目, list):
        警告列表.append("计时数据已忽略：容器键必须是列表")
        return 结果.成功结果({"条目列表": 条目列表, "摘要": _汇总([]), "警告列表": 警告列表})

    for 索引, 条目 in enumerate(原始条目):
        规范化 = 规范化计时条目(条目, 索引, 名称键别名, 耗时键别名)
        if not 规范化.成功:
            警告列表.append(f"计时条目 {索引} 已忽略：期望对象")
            continue
        条目列表.append((规范化.值 or {}).get("条目") or {})

    return 结果.成功结果({
        "条目列表": 条目列表,
        "摘要": _汇总(条目列表),
        "警告列表": 警告列表,
    })

