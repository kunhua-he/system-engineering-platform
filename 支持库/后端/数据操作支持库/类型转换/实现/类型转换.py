"""无第三方依赖的确定性类型转换。"""
from __future__ import annotations

import math
from typing import Any

from 公共契约.基础类型.结果类型 import 结果
from 公共契约.基础类型.类型表 import 正式类型表
from 公共契约.基础类型.数值类型 import 数值类型定义, 校验数值类型
from 公共契约.基础类型.逻辑类型 import 校验逻辑类型
from 公共契约.基础类型.文本类型 import 校验文本类型
from 公共契约.基础类型.集合类型 import 校验列表类型, 校验字典类型
from 公共契约.基础类型.二进制类型 import 校验字节类型, 校验字节集类型
from 公共契约.基础类型.时间类型 import 校验日期时间类型
from 公共契约.基础类型.JSON类型 import 校验JSON值类型
from 公共契约.基础类型.空值类型 import 校验空值类型
from 公共契约.基础类型.资源引用类型 import 校验资源引用类型
from 公共契约.基础类型.结果类型 import 校验结果类型
from 公共契约.句柄体系 import 校验句柄型

# 数值四型的边界不在这里复制：唯一事实源是 公共契约/基础类型/数值类型.py。
数值类型名 = frozenset(数值类型定义)

# 公共契约已冻结严格校验、可直接委托的正式类型（缺一不可，多一个就是自造边界）。
# **2026-09-19 E-8 收口**：此前这里只有 2 项（逻辑型 / 句柄型），另有 4 类数值型走
# `数值类型名` 分支 ⇒ 16 型里**只有 6 型**能被本能力判定，其余 10 型一律明确失败并
# 回带缺口详情（`目标类型「X」缺公共契约校验层`）。现在 12 个非数值正式类型的判定
# 全部落进 `公共契约/基础类型/` 各模块，本表逐型委托，**16 型全覆盖、无缺口**。
# 判定强度与网关 JSON 边界逐项同源：网关 `类型匹配表` 也委托同一批函数（哲学第 5 条：口径唯一）。
委托校验表 = {
    "逻辑型": 校验逻辑类型,
    "文本型": 校验文本类型,
    "列表型": 校验列表类型,
    "字典型": 校验字典类型,
    "JSON值型": 校验JSON值类型,
    "字节型": 校验字节类型,
    "字节集型": 校验字节集类型,
    "日期时间型": 校验日期时间类型,
    "资源引用型": 校验资源引用类型,
    "句柄型": 校验句柄型,
    "结果型": 校验结果类型,
    "空值型": 校验空值类型,
}

def _文本(值: Any) -> 结果[str]:
    if not isinstance(值, str):
        return 结果.失败("参数不合法", "值必须是文本型")
    return 结果.成功结果(值.strip())

def 文本转整数(文本: str, 进制: int = 10) -> 结果[int]:
    try:
        值 = _文本(文本)
        if not 值.成功 or not 2 <= 进制 <= 36 or not 值.值:
            return 结果.失败("参数不合法", "文本或进制不合法")
        return 结果.成功结果(int(值.值, 进制))
    except ValueError:
        return 结果.失败("类型转换失败", "文本不是整数")
    except (OverflowError, TypeError):
        return 结果.失败("数值溢出", "整数超出范围")

def 文本转长整数(文本: str, 进制: int = 10) -> 结果[int]:
    return 文本转整数(文本, 进制)

def 整数转文本(整数: int) -> 结果[str]:
    if isinstance(整数, bool) or not isinstance(整数, int):
        return 结果.失败("参数不合法", "值必须是整数型")
    return 结果.成功结果(str(整数))

def 长整数转文本(长整数: int) -> 结果[str]:
    return 整数转文本(长整数)

def _浮点(文本: str, 单精度: bool = False) -> 结果[float]:
    try:
        值 = _文本(文本)
        if not 值.成功 or not 值.值:
            return 结果.失败("参数不合法", "文本不能为空")
        数值 = float(值.值)
        if not math.isfinite(数值):
            return 结果.失败("类型转换失败", "不接受 NaN 或无穷")
        if 单精度 and abs(数值) > 3.4028235e38:
            return 结果.失败("数值溢出", "单精度数超出范围")
        return 结果.成功结果(数值)
    except (ValueError, TypeError):
        return 结果.失败("类型转换失败", "文本不是数值")

def 文本转单精度数(文本: str) -> 结果[float]:
    return _浮点(文本, True)

def 文本转双精度数(文本: str) -> 结果[float]:
    return _浮点(文本)

def 数值转文本(数值: int | float, 小数位数: int | None = None) -> 结果[str]:
    if isinstance(数值, bool) or not isinstance(数值, (int, float)):
        return 结果.失败("参数不合法", "值必须是数值（正式类型：整数型 或 双精度数型；布尔不算）")
    if isinstance(数值, float) and not math.isfinite(数值):
        return 结果.失败("类型转换失败", "不接受 NaN 或无穷")
    if 小数位数 is None:
        return 结果.成功结果(str(数值))
    if isinstance(小数位数, bool) or not isinstance(小数位数, int) or not 0 <= 小数位数 <= 15:
        return 结果.失败("参数不合法", "小数位数必须为 0 到 15 的整数")
    return 结果.成功结果(f"{数值:.{小数位数}f}")

def 逻辑转文本(逻辑值: bool) -> 结果[str]:
    if not isinstance(逻辑值, bool):
        return 结果.失败("参数不合法", "值必须是逻辑型")
    return 结果.成功结果("真" if 逻辑值 else "假")

def 文本转逻辑(文本: str) -> 结果[bool]:
    值 = _文本(文本)
    if not 值.成功:
        return 结果.失败("参数不合法", "值必须是文本型")
    if 值.值 in ("真", "true", "True", "1"):
        return 结果.成功结果(True)
    if 值.值 in ("假", "false", "False", "0"):
        return 结果.成功结果(False)
    return 结果.失败("类型转换失败", "文本不是逻辑型")

def 校验类型(值: Any, 目标类型: str) -> 结果[bool]:
    """按公共契约校验值是否属于目标正式类型：只检查，不转换，不修改输入。

    分派口径（唯一事实源 = `公共契约/基础类型/`，本包不复制任何类型边界）：

    - 数值四型（`整数型`／`长整数型`／`单精度数型`／`双精度数型`）→
      委托 ``公共契约.基础类型.数值类型.校验数值类型``：32/64 位边界、
      IEEE 754 binary32 可编码性、拒绝布尔混入整数，全部由那一份实现判定。
      原先本包自己写的 ``isinstance(值, int)`` 无边界，等于放行 ``2**40`` 当
      ``整数型``（走 HTTP 被拒、走能力调用却放行，契约被绕道），已删除。
    - `逻辑型` → 委托 ``公共契约.基础类型.逻辑类型.校验逻辑类型``。
    - `句柄型` → 委托 ``公共契约.句柄体系.校验句柄型``（六位数字句柄或进程内可调用句柄，
      唯一强度判定；本包不再直接引用 `是合法句柄id`，避免与可调用形态口径脱节）。
    - 其余正式类型 → 委托 ``公共契约.基础类型.`` 各自的公共校验函数
      （**2026-09-19 E-8 收口**：此前它们**没有公共校验层**，本能力只能明确失败并
      回带缺口详情；现在 16 型全覆盖，缺口分支只剩「非正式类型名」一种走法）。
      判定强度与网关 JSON 边界逐项同源——两边委托的是同一批函数。
    - 非正式类型名（含历史短名、空文本）→ 失败「未知目标类型」。
    """
    if not isinstance(目标类型, str) or not 目标类型:
        return 结果.失败("参数不合法", "目标类型必须是非空文本")
    if 目标类型 in 数值类型名:
        try:
            合法 = 校验数值类型(值, 目标类型)
        except (TypeError, ValueError):
            合法 = False
        return 结果.成功结果(bool(合法))
    委托 = 委托校验表.get(目标类型)
    if 委托 is not None:
        return 结果.成功结果(bool(委托(值)))
    return 结果.失败("参数不合法", f"未知目标类型：{目标类型}")
