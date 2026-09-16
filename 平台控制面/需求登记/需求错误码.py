"""需求登记包的稳定错误码映射：中文域错误码 → 平台稳定码（唯一映射表）。

为什么单独一份（第 1 条 3 项「结果唯一即收口」）：
需求闸门的稳定码（`REQUIREMENT_REQUIRED` / `REQUIREMENT_UNCONFIRMED`）此前只散落在
调用方（`平台控制面/统一入口.py` 的 4 处、`开发工具/契约编译/消费者契约.py` 的错误码表），
能力面看不到它们、能力 id 里也含不了「需求」。包化后把两份口径的**对应关系**收在本表：
本包能力一律返回中文域错误码（与 `平台控制面` 其余包同词表），调用方按本表映射为
稳定码即可，不另立第二套判定。

口径（逐字保持收敛前行为）：
- `需求id不能为空` → `REQUIREMENT_REQUIRED`（空需求id一律阻断，与统一入口 4 处同码）；
- `需求不存在` → `REQUIREMENT_UNCONFIRMED`（未确认或不存在一律阻断开发与发布放行，
  与 `统一入口.py` 的「需求未确认或不存在」同码——旧文案把两者并成一条，本表沿用）。
"""

from __future__ import annotations

稳定错误码映射: dict[str, str] = {
    "": "",
    "参数不合法": "INVALID_PARAMETER",
    "需求id不能为空": "REQUIREMENT_REQUIRED",
    "需求不存在": "REQUIREMENT_UNCONFIRMED",
    "需求登记失败": "REQUIREMENT_REGISTER_FAILED",
    "需求查询失败": "REQUIREMENT_QUERY_FAILED",
    "装配计划生成失败": "ASSEMBLY_PLAN_FAILED",
    "工作包登记失败": "WORK_PACKAGE_REGISTER_FAILED",
}

__all__ = ["稳定错误码映射"]
