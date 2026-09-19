"""入口定位：对外入口定位与「声明无实现」判据，附签名助手。

本模块是 `开发工具/契约编译/漂移检测.py` 的**内部搬家**产物（对外符号零变化）：
`漂移检测.py` 仍是契约漂移门禁的对外唯一门面，全部公开符号依然从那里导入；
本模块只承载实现，**不构成第二份判据**。原有文档串与注释一字未改。

依赖：`实现定位`（本包）+ `公共契约.基础类型.逻辑类型`。
"""


from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from 开发工具.契约编译.实现定位 import (
    包入口映射, 模块替换标记, _模块名到文件, _实现函数索引,
    _定位实现文件, _系统根, _文件内定义, _包入口导入表, _跟随转调,
)

from 公共契约.基础类型.逻辑类型 import 真, 假

# ---- 对外符号回托 ----
真 = 真
假 = 假

@dataclass
class 对外入口定位:
    """一次「能力 → 对外实现函数所在文件」的定位结果。"""

    文件: Path | None = None
    函数名: str = ""
    来源: str = ""
    状态: str = "未定位"        # 已定位 / 转调未解析 / 未定位
    详情: str = ""
def 定位对外入口(契约: dict[str, Any], *, 实现目录: Path,
                 包目录: Path | None = None,
                 实现索引: dict[str, tuple[Path, ast.AST]] | None = None,
                 系统根: Path | None = None) -> 对外入口定位:
    """定位能力的**对外实现**（注册映射优先，绝不「按文件名猜第一个同名函数」）。

    定位顺序（每一档都要「文件里真的有那个函数」才算命中）：
      ① **注册映射**：`__init__.py` 的 `注册能力` 登记 `能力id → 实现函数`（别名/包装闭包靠它）；
      ② **包入口本文件**：包装函数写在 `__init__.py` 里（`_包装解析代码文件`）；
      ③ **包入口导入目标**：`from 支持库.…实现.提供者 import 检查转写可用性` → 该文件；
      ④ **实现目录索引**：同名函数（对外优先，`子进程*` 垫底）；
      ⑤ **转调跟随**：命中文件里没有该函数、但它把本模块对象替换成唯一实现时，
         跟到被替换模块（D-2 收口形态）；跟不到 → 状态 `转调未解析`（与「真无实现」分开）。
    """
    能力id = str(契约.get("能力id") or "")
    能力名 = 能力id.split(".")[-1]
    if 实现索引 is None:
        实现索引 = _实现函数索引(实现目录)
    根 = 系统根 if 系统根 is not None else (_系统根(包目录) if 包目录 is not None else None)
    if not 能力id:
        return 对外入口定位(函数名=能力名, 来源="无能力id", 状态="未定位",
                          详情="契约缺少 能力id")
    登记 = 包入口映射(包目录).get(能力id) or {}
    函数名 = str(登记.get("函数名") or 能力名)
    来源 = str(登记.get("来源") or "能力名回退")
    # 候选条目 = (文件, 出处, **在该文件里应当找到的函数名**)。第三项必须跟着候选走：
    # 注册表里的 `实现函数` 是 `__init__` 里的**本地名**（可能是别名，如
    # `from …实现.组件规范支持库 import 生成完整性摘要 as 生成完整性摘要能力`），
    # 被导入模块里定义的是**原名**。
    候选: list[tuple[Path, str, str]] = []
    if 包目录 is not None:
        入口 = 包目录 / "__init__.py"
        if 入口.is_file() and _文件内定义(入口, 函数名):
            候选.append((入口, "包入口本文件", 函数名))
        导入表 = _包入口导入表(包目录)
        for 查名 in dict.fromkeys((函数名, 能力名)):
            条目 = 导入表.get(查名)
            if not 条目:
                continue
            目标 = _模块名到文件(条目[0], 根)
            if 目标 is not None:
                候选.append((目标, f"包入口导入 {条目[0]}", 条目[1] or 能力名))
                break
    命中 = 实现索引.get(函数名)
    if 命中:
        候选.append((命中[0], "实现目录索引", 函数名))
    命中能力名 = 实现索引.get(能力名)
    if 命中能力名 and 命中能力名[0] != (命中[0] if 命中 else None):
        候选.append((命中能力名[0], "实现目录索引（能力id 末段）", 能力名))
    for 文件, 出处, 核对名 in 候选:
        if 文件.is_file() and _文件内定义(文件, 核对名):
            return 对外入口定位(文件=文件, 函数名=核对名, 来源=出处, 状态="已定位",
                              详情=f"{出处}: {文件}（函数 {核对名}）")
    for 文件, 出处, 核对名 in 候选:
        if not 文件.is_file():
            continue
        目标, 说明 = _跟随转调(文件, 核对名, 根)
        if 目标 is not None:
            return 对外入口定位(文件=目标, 函数名=核对名, 来源=f"转调跟随（{出处}）",
                              状态="已定位", 详情=说明)
        if 说明:
            return 对外入口定位(文件=None, 函数名=核对名, 来源=出处,
                              状态="转调未解析", 详情=说明)
    return 对外入口定位(文件=None, 函数名=函数名, 来源=来源, 状态="未定位",
                      详情=f"{实现目录} 下未找到函数 {函数名}")
def 检测声明无实现(契约: dict[str, Any], 实现目录: Path,
                   实现索引: dict[str, tuple[Path, ast.AST]] | None = None) -> str | None:
    """契约声明了能力但实现目录无对应实现（按**函数名**匹配，不按文件名）。

    原实现按「文件名含能力名」判，在本仓（一包一文件）实测：108 包 570 条全红、
    真缺口 0 条 —— 这是判据错误，不是被测缺陷（哲学 9.x：判据错误不得说成被测
    缺陷）。改为按函数名索引后，真缺口才如实报出。

    **它只认「能力id 末段 == 函数名」这一档**，故会把两类**合法**形态误报：
    ① 别名（`…PDF隔离提供者.解析PDF` 的实现函数是 `解析PDF隔离`）；
    ② 转调（`…PDF文本表格.实现/PDF文本表格.py` 用 `sys.modules[__name__] = 唯一实现`
       把模块对象换掉，文件里当然没有 `def 解析PDF`）。
    `全面漂移检测` 已改走 **`定位对外入口`**（注册映射 + 转调跟随）再判，不再直接调本
    函数；本函数保留给「拿不到包目录」的调用方（如反向破坏验证的临时夹具）。
    """
    能力id = 契约.get("能力id", "")
    if not 能力id:
        return None
    if 实现索引 is None:
        实现索引 = _实现函数索引(实现目录)
    能力名 = 能力id.split(".")[-1]
    if 能力名 in 实现索引:
        return None
    return f"声明能力但无实现: {能力id}（{实现目录} 下未找到函数 {能力名}）"
def _取能力函数定义(树: ast.AST, 函数名: str, *,
                   允许唯一函数回退: bool = False
                   ) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
    """按**函数名**取函数定义（AST，含嵌套闭包）。

    `允许唯一函数回退`：只在「文件里只有一个函数」时用它（生成入口/夹具即此形态）。
    多函数文件里找不到同名函数 = 本能力无可比对签名，**不拿别人的签名顶替**（那是错归属）。
    """
    函数表 = [节点 for 节点 in ast.walk(树)
            if isinstance(节点, (ast.FunctionDef, ast.AsyncFunctionDef))]
    命中 = next((节点 for 节点 in 函数表 if 节点.name == 函数名), None) if 函数名 else None
    if 命中 is not None:
        return 命中
    if 允许唯一函数回退 and len(函数表) == 1:
        return 函数表[0]
    return None
def _签名参数(函数定义: ast.FunctionDef | ast.AsyncFunctionDef) -> tuple[list[str], set[str]]:
    """函数签名 → (参数名序, 带默认值的参数名集合)。

    参数名序 = 位置参数（`posonlyargs + args`）紧接关键字专用参数（`kwonlyargs`）——
    全 kw-only 的能力入口（`def 启动桌面窗口(*, 标题=…)`）必须认。`self`/`cls`/`无参数`
    是平台占位形态，剔除。
    """
    位置 = list(函数定义.args.posonlyargs) + list(函数定义.args.args)
    默认数 = len(函数定义.args.defaults)
    有默认 = {参数.arg for 参数 in 位置[len(位置) - 默认数:]} if 默认数 else set()
    有默认 |= {参数.arg for 参数, 默认 in zip(函数定义.args.kwonlyargs,
                                           函数定义.args.kw_defaults)
             if 默认 is not None}
    参数名序 = [参数.arg for 参数 in 位置 + list(函数定义.args.kwonlyargs)
             if 参数.arg not in ("无参数", "self", "cls")]
    return 参数名序, 有默认
def _必填名序问题(必填: list[str], 入口参数: list[str]) -> tuple[list[str], list[str]]:
    """必填参数在入口签名里的**子序列**问题：返回 (缺失的必填项, 顺序颠倒的说明)。

    只比必填项的相对顺序：入口签名里带默认值的可选参数是平台允许的实现自由度，
    它们插在哪里都不算漂移（契约只登记对外必填面）。
    """
    位置表: dict[str, int] = {}
    for 序号, 名 in enumerate(入口参数):
        位置表.setdefault(名, 序号)
    缺失 = [名 for 名 in 必填 if 名 not in 位置表]
    顺序错: list[str] = []
    上一位 = -1
    上一个名 = ""
    for 名 in 必填:
        if 名 not in 位置表:
            continue
        位 = 位置表[名]
        if 位 < 上一位:
            顺序错.append(f"{名} 应在 {上一个名} 前")
            continue
        上一位 = 位
        上一个名 = 名
    return 缺失, 顺序错
