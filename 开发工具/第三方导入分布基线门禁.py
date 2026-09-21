"""第三方导入分布基线门禁：把「全仓有哪些第三方 import、各多少处」冻成可比对的分布。

**对应债务**：`开发文档/未完成事项.md` #100「第三方 import 分布需持续对账」——
2026-09-19 审计用 AST 复算全仓第三方 import 分布（当时 117 处），结论是
「分布已一致，边角新增 4 项」，但**没有任何判据持有跨时点的参照集**：
今天多一个 `import faster_whisper`，明天的审计要重新手工复算一遍才知道。
本件把那次一次性复算变成**基线 + 只增不改方向的门禁**。

## 判据（一条：当前分布 ⊇ 基线分布）

| 方向 | 判定 |
|---|---|
| 基线有、当前无（模块整体消失） | **留痕**（只报；依赖被移除是合法行为，但要人看见） |
| 当前多出基线外的模块 | **判红** —— 新第三方依赖必须**显式登记**（重跑 `--冻结`） |
| 同一模块的处数**超过**基线 | **判红** —— 分布是「模块 × 处数」，处数也是被冻结的量 |
| 同一模块的处数**低于**基线 | **留痕**（只报，提示基线可下调，即「只减不增」的合法方向） |

**为什么处数增加也判红**：本判据冻结的是**分布**，不是「模块名单」。
只冻结名单的话，`openpyxl` 从 12 处涨到 30 处（比如新增三个包各自 import 一遍）
门禁恒绿 —— 而「哪些件在直接吃第三方」正是审计要持续对账的那件事。
合法新增的出口只有一个：跑 `--冻结` **显式重建基线**（动作留痕、进提交）。

## 口径（第三方 = 不是标准库、不是仓内模块）

一条顶层 import 判为第三方，当且仅当它的顶层名**同时**满足：

1. 不在 `sys.stdlib_module_names`（标准库）；
2. 不是仓内顶层目录名（`支持库`/`模块库`/`开发工具`/…，见 `公共契约/正式根.py`）；
3. 不是**仓内模块名** —— 全仓 `.py` 词干 ∪ 含 `__init__.py` 的目录名 ∪
   本文件同包模块名（同目录/上级目录的 `.py` 与包子目录）。
   第 3 条必须逐文件判同包：`from 工具清单 import X` 这类**按 sys.path 自举**
   的仓内引用在 `开发工具/薄壳/` 下很常见，只按「仓内顶层目录」排除会把
   `工具清单`/`语义索引`/`薄壳服务` 一类**自家模块**计成第三方（实测 12 条假阳性）。

**扫描面**：`公共契约.正式根.遍历源码(系统根)`（进目录即剪枝生成式目录），
减去两类**不是平台源码面**的目录 —— 它们的 import 不是本仓的第三方依赖：

- `*/scripts/`：技能脚本，跑在技能工作区里，依赖**平台注入的合成模块**
  `技能底座能力`（`技能库/技能/交付收尾/scripts/交付收尾.py:36` 等），不是 PyPI 依赖；
- `*/验证夹具/*`：刻意写违规样本的夹具（`技能库/后端/技能库/验证夹具/技能工作区/
  越权技能/scripts/读项目.py:6` 故意 `from 功能模块.订单 import 查询订单`），
  把夹具的 import 计进基线会把基线变成噪声源。

## fail-closed（本项目核心纪律）

- 基线文件**缺失** → 判红（缺基线 = 无参照，不是「没有要检查的」）；
- 基线文件**不可读**（JSON 语法错/编码错/权限错/形状非法）→ 判红；
- 扫描面为空（0 个 `.py`，或 0 条第三方 import）→ 判红（空集不是通过）；
- 某个 `.py` **解析不了**（语法错/读不成/解码错）→ 判红，**不静默跳过**
  —— 跳过等于把「这份文件的依赖情况未知」压成「它没有第三方依赖」。

## 用法

    python3.14 -m 开发工具.第三方导入分布基线门禁            # 跑门禁（默认基线）
    python3.14 -m 开发工具.第三方导入分布基线门禁 --冻结      # 显式重建基线
    python3.14 -m 开发工具.第三方导入分布基线门禁 --基线 <路径>  # 指定基线（反向验证用）

退出码：0 = 通过（可能有留痕）；1 = 判红；2 = 用法错误。
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import sys
from pathlib import Path

仓库根 = Path(__file__).resolve().parents[1]
if str(仓库根) not in sys.path:
    sys.path.insert(0, str(仓库根))

from 公共契约.正式根 import 遍历源码, 正式根名表

#: 基线落点（与 `能力id冻结基线.json` 同目录：`开发文档/项目证据/`）。
基线相对路径 = ("开发文档", "项目证据", "第三方导入分布基线.json")

#: 扫描面排除的目录段（**不是平台源码面**，理由见模块 docstring）。
排除目录段 = ("scripts",)
#: 扫描面排除的路径片段（验证夹具：刻意写违规样本）。
排除路径片段 = ("验证夹具",)

#: 缺口类型常量（报告逐条打印；反向验证按这些字符串断言）。
缺基线文件 = "导入分布-基线文件缺失"
缺基线不可读 = "导入分布-基线文件不可读"
缺基线形状 = "导入分布-基线文件形状非法"
缺扫描面 = "导入分布-扫描面为空"
缺源码不可解析 = "导入分布-源码不可解析"
新增模块 = "导入分布-基线外新增第三方模块"
新增处数 = "导入分布-处数超出基线"

留痕消失 = "模块整体消失"
留痕减少 = "处数低于基线"


def 默认基线路径() -> Path:
    return 仓库根.joinpath(*基线相对路径)


# ── 现场取证 ────────────────────────────────────────────────

def _扫面内(路径: Path, 根: Path) -> bool:
    """该 .py 是否在第三方 import 扫描面内（排除技能脚本与验证夹具）。

    相对段一律按**传入的扫描根**算（不是模块级 `仓库根`）：`--根` 是给反向验证用的
    （在临时根造违规样本），拿模块级根去 `relative_to` 会当场 ValueError
    —— 2026-09-22 反向验证实测撞到过：`--根 <临时根>` 直接崩，等于
    「反向验证走不通的判据」（`--根` 声明了却不能用，是空头承诺）。
    """
    相对段 = 路径.relative_to(根).parts
    if "__pycache__" in 相对段:
        return False
    if any(片段 in 相对段 for 片段 in 排除路径片段):
        return False
    # `scripts/` 只在**技能目录**下排除：平台自己的 scripts 目录若将来出现，
    # 按同一理由（跑在注入环境里）也排除；当前全仓 `scripts/` 只出现在技能下。
    return not any(段 in 排除目录段 for 段 in 相对段[:-1])


def _同包模块名(文件: Path) -> set[str]:
    """本文件的同包模块名：同目录 `.py` 词干 + 同目录包子目录 + 上级目录同两项。

    与 `开发工具/依赖派生/生成依赖分两段.py::_同包模块名` 同一口径 ——
    仓内模块常按 `sys.path` 自举（`from 工具清单 import X`），不按同包排除就会
    把它们计成第三方（实测 12 条假阳性）。
    """
    根 = 文件.parent
    名字 = {p.stem for p in 根.glob("*.py")}
    名字 |= {p.name for p in 根.iterdir() if p.is_dir() and (p / "__init__.py").is_file()}
    上级 = 根.parent
    if 上级.name and 上级 != 根:
        名字 |= {p.stem for p in 上级.glob("*.py")}
        名字 |= {p.name for p in 上级.iterdir() if p.is_dir() and (p / "__init__.py").is_file()}
    return 名字


def 扫描分布(根: Path) -> tuple[dict[str, dict], list[str], int]:
    """``({模块名: {"处数": n, "文件": [...]}}, 不可解析清单, 扫描文件数)``。

    两遍：第一遍取全部扫描面内的 `.py` 与「仓内模块名」全集（`.py` 词干 +
    含 `__init__.py` 的目录名），第二遍逐文件判第三方 import。
    先有全集才能判「这个顶层名是不是自家模块」—— 单遍做不到（后扫到的文件
    可能就是先扫到的那条 import 的来源）。
    """
    根 = Path(根)
    全部 = [p for p in 遍历源码(根) if _扫面内(p, 根)]
    仓内模块名 = {p.stem for p in 全部}
    仓内模块名 |= {p.parent.name for p in 全部 if p.name == "__init__.py"}
    # 仓内**顶层目录名**必须单列：`from 运行核心.统一网关 import X` 的顶层名是
    # 顶层目录名，而顶层目录多数没有 `__init__.py`（命名空间包）、也没有同名 `.py`
    # ⇒ 只靠 `仓内模块名` 会把 `运行核心`/`开发工具`/`后端核心` 计成第三方
    # （实测假阳性 587 + 399 + 43 + … 处）。口径 = 扫描根下**实际存在**的顶层目录
    # ∪ `正式根名表`（夹具根下没有正式根目录时仍按事实源排除）。
    仓内顶层目录 = {p.name for p in 根.iterdir() if p.is_dir()}
    仓内顶层目录 |= set(正式根名表)
    标准库 = set(sys.stdlib_module_names)

    分布: dict[str, dict] = {}
    不可解析: list[str] = []
    for 文件 in 全部:
        相对 = 文件.relative_to(根).as_posix()
        try:
            源码 = 文件.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as 错误:
            不可解析.append(f"{相对}（{type(错误).__name__}）")
            continue
        try:
            树 = ast.parse(源码)
        except SyntaxError as 错误:
            不可解析.append(f"{相对}（SyntaxError: {错误.msg}@{错误.lineno}）")
            continue
        同包 = _同包模块名(文件)
        for 节点 in ast.walk(树):
            if isinstance(节点, ast.Import):
                名单 = [别名.name.split(".")[0] for 别名 in 节点.names]
            elif isinstance(节点, ast.ImportFrom) and 节点.module and 节点.level == 0:
                名单 = [节点.module.split(".")[0]]
            else:
                名单 = []
            for 顶层 in 名单:
                if not 顶层 or 顶层 == "__future__":
                    continue
                if (顶层 in 标准库 or 顶层 in 仓内顶层目录
                        or 顶层 in 仓内模块名 or 顶层 in 同包):
                    continue
                条目 = 分布.setdefault(顶层, {"处数": 0, "文件": []})
                条目["处数"] += 1
                if 相对 not in 条目["文件"]:
                    条目["文件"].append(相对)
    for 条目 in 分布.values():
        条目["文件"].sort()
    return 分布, 不可解析, len(全部)


# ── 基线 ────────────────────────────────────────────────────

def _读json(路径: Path) -> tuple[object | None, str | None]:
    """三态读 JSON：``(数据, None)`` / ``(None, "缺失")`` / ``(None, "不可读:…")``。"""
    if not 路径.is_file():
        return None, "缺失"
    try:
        文本 = 路径.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as 错误:
        return None, f"不可读:{type(错误).__name__}"
    try:
        return json.loads(文本), None
    except json.JSONDecodeError as 错误:
        return None, f"不可读:JSONDecodeError({错误.msg}@{错误.lineno})"


def 读取基线(路径: Path) -> tuple[dict[str, dict], list[dict]]:
    """读基线；**任何一处读不成 → 违规清单非空（fail-closed）**。"""
    数据, 诊断 = _读json(路径)
    if 诊断 == "缺失":
        return {}, [{"模块": "*", "缺口类型": 缺基线文件, "路径": str(路径),
                     "详情": "第三方导入分布基线不存在 ⇒ 无参照 ⇒ 判红（fail-closed）"}]
    if 诊断 is not None:
        return {}, [{"模块": "*", "缺口类型": 缺基线不可读, "路径": str(路径),
                     "详情": f"{诊断} ⇒ 判红（fail-closed）"}]
    if not isinstance(数据, dict):
        return {}, [{"模块": "*", "缺口类型": 缺基线形状, "路径": str(路径),
                     "详情": "顶层不是对象"}]
    条目 = 数据.get("分布")
    if not isinstance(条目, dict) or not 条目:
        return {}, [{"模块": "*", "缺口类型": 缺基线形状, "路径": str(路径),
                     "详情": "分布缺失或为空 ⇒ 空基线不是通过（fail-closed）"}]
    出: dict[str, dict] = {}
    坏: list[str] = []
    for 模块, 值 in 条目.items():
        if not isinstance(模块, str) or not 模块:
            坏.append(repr(模块))
            continue
        if not isinstance(值, dict) or not isinstance(值.get("处数"), int):
            坏.append(f"{模块}（处数缺失或不是整数）")
            continue
        出[模块] = 值
    if 坏:
        return {}, [{"模块": "*", "缺口类型": 缺基线形状, "路径": str(路径),
                     "详情": f"分布条目形状非法 {len(坏)} 条: {'；'.join(坏[:5])} ⇒ 判红（fail-closed）"}]
    return 出, []


# ── 门禁 ────────────────────────────────────────────────────

def 运行门禁(根: Path | None = None, 基线文件: Path | None = None
            ) -> tuple[list[dict], list[dict], dict]:
    """``(违规, 留痕, 统计)`` 三态返回。

    - ``违规``：判红项（基线缺失/不可读/形状非法、扫描面为空、源码不可解析、
      基线外新增模块、处数超出基线）；
    - ``留痕``：**允许但报到**（模块整体消失、处数低于基线 —— 「只减不增」方向）；
    - ``统计``：``{"文件数": n, "模块数": n, "处数": n, "基线模块数": n}``（供报告与断言）。
    """
    根 = Path(根 or 仓库根).resolve()
    基线文件 = Path(基线文件) if 基线文件 else 默认基线路径()

    基线, 基线违规 = 读取基线(基线文件)
    分布, 不可解析, 文件数 = 扫描分布(根)

    违规: list[dict] = list(基线违规)
    for 项 in 不可解析:
        违规.append({"模块": "-", "缺口类型": 缺源码不可解析, "路径": 项,
                     "详情": "该 .py 解析不了 ⇒ 它的第三方依赖情况未知（不静默跳过）"})
    处数总和 = sum(条目["处数"] for 条目 in 分布.values())
    if 文件数 == 0 or not 分布:
        违规.append({"模块": "*", "缺口类型": 缺扫描面, "路径": str(根),
                     "详情": f"扫描面 {文件数} 个 .py、第三方 import {处数总和} 处"
                             f" ⇒ 空集不是通过（fail-closed）"})

    统计 = {"文件数": 文件数, "模块数": len(分布), "处数": 处数总和,
           "基线模块数": len(基线)}

    留痕: list[dict] = []
    if 基线违规 or not 分布:
        # 基线读不成时不做集合比对（避免把一次读取故障说成「几十个模块消失」）。
        留痕.append({"模块": "*", "类型": "判据未生效",
                     "详情": "基线或当前面取证失败，本次不做分布比对（已单独判红）"})
        return 违规, 留痕, 统计

    for 模块 in sorted(set(分布) - set(基线)):
        条目 = 分布[模块]
        违规.append({"模块": 模块, "缺口类型": 新增模块,
                     "路径": "、".join(条目["文件"][:3]) +
                             (f" 等 {len(条目['文件'])} 处" if len(条目["文件"]) > 3 else ""),
                     "详情": f"基线外新增第三方 import {条目['处数']} 处 ⇒ "
                             "新增第三方依赖必须**显式登记**（确认合法后重跑 --冻结）"})
    for 模块 in sorted(set(基线) - set(分布)):
        留痕.append({"模块": 模块, "类型": 留痕消失,
                     "详情": f"基线 {基线[模块].get('处数')} 处 → 当前 0 处"
                             "（依赖被整体移除；确认后重跑 --冻结 下调基线）"})
    for 模块 in sorted(set(分布) & set(基线)):
        旧 = int(基线[模块].get("处数") or 0)
        新 = int(分布[模块]["处数"])
        if 新 > 旧:
            违规.append({"模块": 模块, "缺口类型": 新增处数,
                         "路径": "、".join(分布[模块]["文件"][:3]),
                         "详情": f"处数 {旧} → {新}（超出基线 {新 - 旧} 处）⇒ "
                                 "分布是「模块 × 处数」，处数新增同样须显式登记（重跑 --冻结）"})
        elif 新 < 旧:
            留痕.append({"模块": 模块, "类型": 留痕减少,
                         "详情": f"处数 {旧} → {新}（低于基线 {旧 - 新} 处）"
                                 "（只减不增的合法方向；可下调基线）"})
    return 违规, 留痕, 统计


def 冻结基线(根: Path | None = None, 基线文件: Path | None = None) -> tuple[int, str]:
    """现场重建基线。**只有显式 ``--冻结`` 才调用**（不让门禁自己改基线）。"""
    根 = Path(根 or 仓库根).resolve()
    基线文件 = Path(基线文件) if 基线文件 else 默认基线路径()
    分布, 不可解析, 文件数 = 扫描分布(根)
    if 不可解析:
        return 1, (f"冻结失败：{len(不可解析)} 个 .py 解析不了（{不可解析[:3]}），"
                   "拒绝写出基于不完整扫描的基线")
    if not 分布:
        return 1, "冻结失败：第三方 import 分布为空 ⇒ 拒绝写出空基线（fail-closed）"
    处数总和 = sum(条目["处数"] for 条目 in 分布.values())
    文档 = {
        "说明": "全仓第三方 import 分布基线。判据：当前分布 ⊇ 本基线分布；"
                "基线外新增模块、以及同模块处数超出基线 ⇒ 判红（新增须显式登记，"
                "出口是重跑 --冻结）。模块消失与处数下降只留痕（只减不增的合法方向）。"
                "**基线文件缺失/不可读 ⇒ fail-closed 判红**"
                "（见 开发工具/第三方导入分布基线门禁.py）。",
        "版本": 1,
        "口径": ("AST 顶层 import 名 ∉ 标准库 ∪ 仓内顶层目录 ∪ 仓内模块名"
                "（全仓 .py 词干 ∪ 含 __init__.py 的目录名 ∪ 本文件同包模块名）；"
                "扫描面 = 公共契约.正式根.遍历源码(仓根) 减去 */scripts/ 与 */验证夹具/*"),
        "扫描面": "公共契约.正式根.遍历源码(系统根)",
        "文件数": 文件数,
        "模块数": len(分布),
        "处数": 处数总和,
        "分布": {模块: {"处数": 条目["处数"], "文件数": len(条目["文件"]),
                        "文件": 条目["文件"]}
                for 模块, 条目 in sorted(分布.items())},
    }
    基线文件.parent.mkdir(parents=True, exist_ok=True)
    基线文件.write_text(json.dumps(文档, ensure_ascii=False, indent=2) + "\n",
                     encoding="utf-8")
    return 0, (f"已冻结第三方导入分布：{len(分布)} 个模块 / {处数总和} 处 / "
               f"扫描 {文件数} 个 .py → {基线文件}")


def 基线指纹(路径: Path) -> str:
    """基线文件内容指纹（前 16 位）—— 报告里带上，便于对账「同一份基线」。"""
    try:
        return hashlib.sha256(路径.read_bytes()).hexdigest()[:16]
    except OSError:
        return "不可读"


def 主程序(argv: list[str] | None = None) -> int:
    解析 = argparse.ArgumentParser(description="第三方导入分布基线门禁（债务 #100）")
    解析.add_argument("--冻结", action="store_true", help="显式重建基线")
    解析.add_argument("--基线", default=None, help="覆盖基线路径（反向验证用）")
    解析.add_argument("--根", default=None, help="覆盖扫描根（反向验证用）")
    参数 = 解析.parse_args(argv)
    根 = Path(参数.根).expanduser() if 参数.根 else 仓库根
    基线文件 = Path(参数.基线).expanduser() if 参数.基线 else 默认基线路径()

    if 参数.冻结:
        码, 说明 = 冻结基线(根, 基线文件)
        print(说明)
        return 码

    违规, 留痕, 统计 = 运行门禁(根, 基线文件)
    print(f"第三方导入分布门禁：根={根} 基线={基线文件}"
          f"（指纹 {基线指纹(基线文件)}）")
    print(f"  扫描 {统计['文件数']} 个 .py；第三方模块 {统计['模块数']} 个"
          f"（基线 {统计['基线模块数']} 个）；import 共 {统计['处数']} 处")
    for 条 in 留痕:
        print(f"  [留痕] {条['类型']} 模块={条['模块']} 详情={条['详情']}")
    if not 违规:
        print("第三方导入分布门禁通过：当前分布 ⊇ 基线分布，无基线外新增、无处数超出")
        return 0
    print(f"第三方导入分布门禁失败：共 {len(违规)} 项违规")
    for 条 in 违规:
        print(f"[{条['缺口类型']}] 模块={条['模块']} 路径={条.get('路径', '')} "
              f"详情={条.get('详情', '')}")
    return 1


if __name__ == "__main__":
    sys.exit(主程序())
