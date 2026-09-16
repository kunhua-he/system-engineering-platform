"""前端描述的结构校验（纯计算：不打开文件与连接，不 import 前端核心）。

判据只有一条：字典的键、类型与枚举取值是否落在 `前端核心/前端核心.py` 五个数据类
的字段口径内（口径表见同目录 `契约口径.py`）。本模块不做渲染、路由或后端调用判定
—— 那些是 前端核心 与渲染提供者的职责，本包只做**边界校验与结果归一**。

问题列表按「字段路径 + 原因」逐条给出，顺序稳定（先自创字段、再按契约字段声明顺序），
同一输入恒得同一输出（哲学第 9 条 4 项：确定性优先）。
"""

from __future__ import annotations

from typing import Any

from 支持库.前端.前端契约校验.实现.契约口径 import 契约必填表, 契约字段表, 嵌套契约表

# 能力定义.json 的 行为.输入上限：单层列表项数上限（组件条数 / 页面条数 / 各资源项数）。
条数上限 = 1000


def 类型名(值: Any) -> str:
    """JSON 边界上的类型名（给人读的正式口径名，不是 Python 类名）。"""
    if isinstance(值, bool):
        return "逻辑型"
    if isinstance(值, str):
        return "文本型"
    if isinstance(值, dict):
        return "字典型"
    if isinstance(值, list):
        return "列表型"
    if isinstance(值, int):
        return "整数型"
    if isinstance(值, float):
        return "双精度数型"
    return "空值型" if 值 is None else "未知类型"


def 计数列表(值: Any) -> int:
    """列表型字段的原始条数（非列表记 0：条数只报真实读到的结构，不猜）。"""
    return len(值) if isinstance(值, list) else 0


def 校验结构(契约名: str, 数据: Any, 路径: str = "") -> list[str]:
    """按契约名逐字段校验，返回逐条问题原文；空列表 = 结构合法。"""
    位置 = 路径 or 契约名
    if not isinstance(数据, dict):
        return [f"{位置}: 必须是 JSON 对象（字典型），当前是 {类型名(数据)}"]
    规格 = 契约字段表[契约名]
    合法字段 = {字段 for 字段, _形态, _枚举 in 规格}
    问题列表 = [f"{位置}.{字段}: 不在前端核心 {契约名} 口径内（拒绝自创字段）"
              for 字段 in sorted(set(数据) - 合法字段)]
    for 字段, 形态, 枚举取值 in 规格:
        if 字段 not in 数据:
            if 字段 in 契约必填表[契约名]:
                问题列表.append(f"{位置}.{字段}: 缺少必填字段")
            continue
        问题列表.extend(_校验字段(f"{位置}.{字段}", 数据[字段], 形态, 枚举取值))
    return 问题列表


def _校验字段(路径: str, 值: Any, 形态: str, 枚举取值: tuple[str, ...] | None) -> list[str]:
    """单字段校验：先判形态，再判枚举取值；列表型逐项递归。"""
    if 形态 == "文本":
        if not isinstance(值, str):
            return [f"{路径}: 必须是文本型，当前是 {类型名(值)}"]
        if 枚举取值 and 值 not in 枚举取值:
            return [f"{路径}: 取值 {值!r} 不在 {list(枚举取值)} 内"]
        return []
    if 形态 == "字典":
        if isinstance(值, dict):
            return []
        return [f"{路径}: 必须是 JSON 对象（字典型），当前是 {类型名(值)}"]
    if not isinstance(值, list):
        return [f"{路径}: 必须是列表型，当前是 {类型名(值)}"]
    问题列表: list[str] = []
    if len(值) > 条数上限:
        问题列表.append(f"{路径}: {len(值)} 项超过输入上限 {条数上限} 项")
    if 形态 == "文本列表":
        问题列表.extend(f"{路径}[{序号}]: 列表项必须是文本型，当前是 {类型名(项)}"
                    for 序号, 项 in enumerate(值) if not isinstance(项, str))
        return 问题列表
    子契约名 = 嵌套契约表.get(形态)
    if 子契约名 is None:
        问题列表.append(f"{路径}: 未知字段形态 {形态}（口径表配置错误，请报缺陷）")
        return 问题列表
    for 序号, 项 in enumerate(值):
        问题列表.extend(校验结构(子契约名, 项, f"{路径}[{序号}]"))
    return 问题列表
