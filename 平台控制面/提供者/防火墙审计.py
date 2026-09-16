"""平台控制面专属依赖防火墙：治理面静态审计 + 发布依赖判定。

比 运行核心/依赖防火墙.py 更严——平台控制面是治理面，只允许静态声明依赖：

强制拒绝（审计违规）：
1. 动态导入：__import__/import_module/动态导入 调用一律拒绝（标准库字面量
   豁免，如 __import__("hashlib") 属正常用法）；非字面量参数按路径拼接拒绝。
2. 反射导入：反射导入/动态加载/执行导入/spec_from_file_location/module_from_spec/
   exec_module 调用、eval/exec/compile 且源码含 import，一律拒绝。
3. 实现目录：任何导入不得深入实现目录（跨包导入实现目录段）；代码字符串引用
   实现目录路径同样拒绝——统一入口只经公开入口，不深入实现目录。
4. 提供者直连外部服务：直连外部连接 API（urlopen/socket/connect/CDLL 等）只允许
   出现在 提供者/__init__.py 已声明登记的提供者文件中；未登记文件直连 =
   绕过注册表，审计标记违规；已登记提供者在模块顶层直连同样违规。

发布依赖判定：依赖未声明（发布请求缺少依赖声明）或声明依赖未登记 →
DEPENDENCY_MISSING 拒绝发布（策略中心只拒绝"声明但未登记"，本防火墙补
"未声明"缺口，二者同错误码）。
"""
from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

from 运行核心.依赖防火墙 import 依赖审计结果, 依赖违规, 标准库前缀表
from 平台控制面.提供者.防火墙审计_规则 import (
    审计文件, 登记提供者表, 系统根, 平台控制面目录, 外部驱动模块表,
    实现路径标记表, 动态导入函数表, 反射导入函数表, 直连函数名表, 直连属性表)

# connect 属性只对外部数据库驱动判定（本地文件库 sqlite3.connect 是内部状态库，
# 属控制面对账等系统恢复路径，不是外部服务）



def 审计平台控制面(目标目录: Path | None = None,
                提供者声明文件: Path | None = None) -> 依赖审计结果:
    """平台控制面专属依赖防火墙：全目录四类规则审计。"""
    实际目录 = Path(目标目录) if 目标目录 is not None else 平台控制面目录
    登记表 = 登记提供者表(提供者声明文件 or 实际目录 / "提供者" / "__init__.py")
    结果 = 依赖审计结果()
    for 文件 in sorted(实际目录.rglob("*.py")):
        if "pycache" in str(文件):
            continue
        单文件 = 审计文件(文件, 登记表)
        结果.违规列表.extend(单文件.违规列表)
        结果.审计文件数 += 单文件.审计文件数
    return 结果


def 发布依赖判定(状态, *, 请求: dict[str, Any]) -> dict[str, Any]:
    """发布依赖策略：依赖未声明或声明依赖未登记 → 依赖缺失 拒绝。"""
    if "依赖" not in 请求:
        return {"允许": False, "错误码": "依赖缺失",
                "理由": "依赖未声明（发布请求缺少依赖声明），拒绝发布"}
    依赖 = 请求.get("依赖", [])
    声明 = {项["能力id"] for 项 in 依赖} if isinstance(依赖, list) else set()
    已登记 = {记录["能力id"] for 记录 in 状态.查询记录("能力条目")}
    缺失 = 声明 - 已登记
    if 缺失:
        return {"允许": False, "错误码": "依赖缺失",
                "理由": f"声明依赖未登记: {缺失}"}
    return {"允许": True, "理由": "依赖已声明且全部已登记"}
