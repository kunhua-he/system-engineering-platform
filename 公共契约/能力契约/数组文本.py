"""数组文本：把 `capability_call` 的 `数组` 展开成该能力的**具名参数**（唯一节点）。

为什么要有：工具面 ② 只收 `能力id` ＋ `数组`（华哥 2026-09-25 口径「传参就完事了」），
位置数组必须先变成能力契约里的具名参数才发得出去。这件事**只在本模块做一次** ——
薄壳只调它；网关与能力侧不得再写第二套展开器（哲学 1.2 不保留第二套实现）。

判据来源：`能力目录.读取能力` 回的 `参数` 表（`名称/类型/必填/默认值`，**契约行序**）。
本模块**不手抄任何能力签名**，签名改了这里自动跟着改（哲学 1.3 结果唯一）。

口径（与 `工具清单.协议提示词` 那两句逐字一致）：
  · 按参数表**行序对位**；空位（`''` 或 `null`）跳过 ⇒ 用该参数自己的默认值；
  · 值按契约 `类型` 强转（转不过即报错，**不静默丢弃、不错位**）；
  · 位置多于参数表 ⇒ 报错（多出来的没地方放，宁可当场红也不静默丢）；
  · 报错一律回「完整参数表（按行序，必填带 `*`）＋ 一条能照抄的调用串」，
    让 agent 一次改对，而不是自己猜第二次（华哥 2026-09-25「数组错位是硬伤」）。
"""

from __future__ import annotations

import json
from typing import Any

from 公共契约.基础类型.逻辑类型 import 真

文本型类 = frozenset({"文本型"})
整数型类 = frozenset({"整数型", "长整数型"})
小数型类 = frozenset({"单精度数型", "双精度数型"})
逻辑型类 = frozenset({"逻辑型"})
列表型类 = frozenset({"列表型"})
字典型类 = frozenset({"字典型"})

#: 逻辑型的真/假写法（人写得到的那几种；`真/假` 是本平台中文口径，其余是 JSON/英文口径）。
真写法 = frozenset({"真", "true", "1", "是"})
假写法 = frozenset({"假", "false", "0", "否"})


def 参数名串(参数表: list[dict] | None) -> str:
    """参数名串：按契约**行序**，必填带 `*`，类型写括号里。

    ①（查询能力）回包与 ② 的报错**共用本函数**，不各写一份格式（否则两处必然漂移）。
    """
    段 = []
    for 项 in 参数表 or []:
        if not isinstance(项, dict) or not 项.get("名称"):
            continue
        名称 = str(项["名称"])
        星 = "*" if 项.get("必填") else ""
        类型 = str(项.get("类型") or "")
        段.append(f"{名称}{星}({类型})" if 类型 else f"{名称}{星}")
    return "，".join(段)


def 调用串(能力id: str, 样例: list[Any]) -> str:
    """一条能照抄的调用串（报错用）——位置数组照 `json` 写法，agent 直接改字即可。"""
    return (f"capability_call{{能力id={能力id}, "
            f"数组={json.dumps(list(样例), ensure_ascii=False)}}}")


def 样例数组(参数表: list[dict] | None) -> list[Any]:
    """按行序造一条样例数组：必填位给占位值，可选位留 `''`（＝跳过、用默认值）。

    例外（2026-09-25）：**列表型／字典型即使可选也给 `[]`／`{}`** —— 它们是「照抄式样」里
    唯一看不出形状的两类，回 `''` 等于把「这一位怎么写」藏起来（实测 agent 只能猜，猜错即
    「数组不合法」，白跑一轮）。空容器既教了形状，又语义等价于「不传」。
    """
    样例: list[Any] = []
    for 项 in 参数表 or []:
        if not isinstance(项, dict) or not 项.get("名称"):
            continue
        类型 = str(项.get("类型") or "")
        默认值 = 项.get("默认值")
        # ★ 列表型／字典型**先于**「可选位留 ''」判定（理由见本函数 docstring）。
        if 类型 in 列表型类:
            样例.append([])
        elif 类型 in 字典型类:
            样例.append({})
        elif 默认值 not in (None, "", [], {}):
            样例.append(默认值)
        elif not 项.get("必填"):
            样例.append("")
        elif 类型 in 整数型类:
            样例.append(0)
        elif 类型 in 逻辑型类:
            样例.append(真)
        else:
            样例.append("…")
    return 样例


def 展开(参数表: list[dict] | None, 数组: Any) -> tuple[dict[str, Any], str]:
    """位置数组 → 具名参数。返回 `(具名参数, 错误说明)`；错误说明非空即失败（具名为空）。

    调用方（薄壳 ②）拿到错误说明后**原样**回给 agent（不加工、不重写）。
    """
    位置表 = _归一数组(数组)
    if 位置表 is None:
        return {}, (f"数组 必须是数组（形如 ['值1','值2']，空位留 ''）；"
                    f"收到 {type(数组).__name__}: {数组!r}")
    有效参数表 = [项 for 项 in (参数表 or [])
                  if isinstance(项, dict) and 项.get("名称")]
    if not 有效参数表:
        return {}, "该能力没有可对位的参数表（先用 ① 查一次该能力，或该能力不接受参数）"
    if len(位置表) > len(有效参数表):
        return {}, (f"数组 有 {len(位置表)} 个位置，该能力只有 {len(有效参数表)} 个参数"
                    f"（按行序：{参数名串(有效参数表)}）；多出来的位置没有对应参数")
    具名: dict[str, Any] = {}
    for 位, 值 in enumerate(位置表):
        项 = 有效参数表[位]
        名称 = str(项["名称"])
        if 值 is None or 值 == "":
            continue  # 空位＝用该参数自己的默认值（不塞空串，免得把必填也变成空）
        转好, 说明 = _强转(名称, str(项.get("类型") or ""), 值)
        if 说明:
            return {}, (f"第 {位 + 1} 个位置（{名称}，契约类型 {项.get('类型')}）{说明}；"
                        f"该能力参数表（按行序，`*`＝必填）：{参数名串(有效参数表)}")
        具名[名称] = 转好
    return 具名, ""


def _归一数组(数组: Any) -> list[Any] | None:
    """把入参归一成位置数组：真数组原样；文本按 JSON 解析（MCP 客户端可能序列化过）。"""
    if isinstance(数组, list):
        return 数组
    if isinstance(数组, tuple):
        return list(数组)
    if isinstance(数组, str):
        文本 = 数组.strip()
        if not 文本:
            return []
        try:
            解析 = json.loads(文本)
        except (ValueError, TypeError):
            return None
        return 解析 if isinstance(解析, list) else None
    return None


def _强转(名称: str, 类型: str, 值: Any) -> tuple[Any, str]:
    """按契约类型强转一个位置值；返回 `(值, 说明)`，说明非空即失败。"""
    if 类型 in 整数型类:
        if isinstance(值, bool):
            return None, "收到逻辑值，要的是整数"
        if isinstance(值, int):
            return 值, ""
        if isinstance(值, float) and 值.is_integer():
            return int(值), ""
        if isinstance(值, str):
            try:
                return int(值.strip()), ""
            except ValueError:
                return None, f"转不成整数（收到 {值!r}）"
        return None, f"转不成整数（收到 {type(值).__name__}）"
    if 类型 in 小数型类:
        if isinstance(值, bool):
            return None, "收到逻辑值，要的是小数"
        if isinstance(值, (int, float)):
            return float(值), ""
        if isinstance(值, str):
            try:
                return float(值.strip()), ""
            except ValueError:
                return None, f"转不成小数（收到 {值!r}）"
        return None, f"转不成小数（收到 {type(值).__name__}）"
    if 类型 in 逻辑型类:
        if isinstance(值, bool):
            return 值, ""
        if isinstance(值, str):
            文本 = 值.strip().lower()
            if 文本 in 真写法:
                return True, ""
            if 文本 in 假写法:
                return False, ""
        return None, f"转不成逻辑值（要 真/假，收到 {值!r}）"
    if 类型 in 列表型类:
        if isinstance(值, list):
            return 值, ""
        return None, (f"要的是数组（收到 {type(值).__name__}: {值!r}）；"
                      f"该位契约是 列表型 ⇒ 要嵌一层数组，如 [\"值1\", \"值2\"]")
    if 类型 in 字典型类:
        if isinstance(值, dict):
            return 值, ""
        return None, (f"要的是键值对（收到 {type(值).__name__}: {值!r}）；"
                      f"该位契约是 字典型 ⇒ 要嵌一层对象，如 {{\"键\": \"值\"}}")
    if 类型 in 文本型类:
        if isinstance(值, str):
            return 值, ""
        if isinstance(值, (int, float)) and not isinstance(值, bool):
            return str(值), ""
        return None, f"要的是文本（收到 {type(值).__name__}）"
    # 未约束 / JSON值型 / 空值型 / 结果型：原样放行（契约没约束，薄壳也不替它猜）。
    return 值, ""
