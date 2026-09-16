"""公开调用完整性门禁：正式公开包的六环一致性 + 错误码登记环。

正式公开边界是 ``支持库/后端``、``模块库`` 与 ``技能库``（技能库是顶层
第三根正式包根，包声明类型同为「支持库」）。``支持库/适配层`` 是
Provider/第三方实现边界：它可以声明内部实现能力，但不能成为公开能力
owner，也不能因为和正式包使用同一能力 id 而制造重复 owner。模板目录（如
``模块库/_模板``）同样不是正式包，禁止进入扫描、注册和冲突统计。

**错误码登记环（2026-09-16 R1 新增，防第四批漂移）**：``能力定义.json``
里声明的每个错误码都必须在网关的 ``公开错误码状态映射`` 里登记；两张表
（状态映射 + 说明表）键集必须一致。缺键的代价见 ``本地网关.py``——
HTTP 状态码回落 500、错误说明回落「请求处理失败」，把可辨识的业务失败
伪装成服务端故障（R1 实测：77 码曾因此漏登，波及 13 条 HTML 黑盒场景）。

**注册表为唯一事实源（包声明.json 能力列表），公开调用必须经由注册能力导出。**
任一违规 → 退出码 1 并打印缺口类型/能力id/包/路径清单；全部通过 → 退出码 0。

**可读性诊断（2026-09-16 A-1 修复）**：``包声明.json``、``能力搜索数据.json``、
``验证场景引用.json`` 的读取分三态出条目 —— 「可读」「缺失」「不可读:异常类型」。
原 ``读取json`` 用 ``except Exception: return None``，把「JSON 语法错 / 编码错 /
权限错」这类**验证器内部故障**与「声明可读但确实没列能力」压成同一个 ``None``：
报告里两者不可区分，按报告去修会把修复带偏（去补能力面，而不是去修那份坏 JSON）。
现在不可读一律出独立缺口类型并把异常类型写进报告，且**不再顺带产出**
「未列能力」——那是误诊断。

**实现侧错误码（2026-09-16 C-15 扩判据）**：登记环原判据只看
``能力定义.json`` **声明过的码**，实现侧直接写进代码的码是盲区。现在判据四：
**实现侧产生的码 ⊆ 状态映射码** —— 扫描各顶层目录下 ``实现/**.py`` 与包级
``__init__.py`` 的**信封渠道**（``错误码=<字面量>`` 关键字、``<结果>.失败(<字面量>, …)``
首参；字典 ``{"错误码": …}`` 不计，理由见 ``_实现侧字面量错误码``）。
同 A-1 口径，「扫不到」与「真缺」分开出条目：扫描面为空 →
``错误码-实现侧扫描面为空``；源码不可解析 →
``错误码-实现侧源码不可解析:<异常类型>``（不静默跳过）；扫到未登记码 →
``错误码-实现侧产生码未登记状态映射``（带出错文件路径）。

**说明表派生不变式（2026-09-17 新增，判据⑤）**：判据②只保证两张表**键集**一致，
看不见「状态码改了、说明表文案没跟」——而说明表 337 条里 **250 条其实是
「码 + 状态码模板」的机械派生**，却被逐条手写固定：同一条事实（这个码属于哪一类
失败）在状态映射与说明表各写一遍，改一处忘另一处时调用方会拿到 413 却被告知
「能力内部执行失败」。判据⑤固定 ``公开错误说明表 == 派生(公开错误码状态映射 ×
状态码文案模板 + 87 条手写例外)``，逐字比对；派生规范与判据六条落在
``开发工具/错误码文案派生.py``（可独立跑，含 ``--统计``／``--补登``）。
接线用 importlib 按路径载入，直跑与包式调用同一结果；规范模块读不到即 fail-closed。
**权威源判定**：``公开错误码状态映射`` 是权威；``能力定义.json.错误码`` 是上游
声明面；``公共契约/错误结构/错误结构.py`` 与 ``开发工具/契约编译/消费者契约.py``
只固定网关边界/鉴权类错误码的常量名，都是 337 码的真子集，不足以当权威源。
"""
from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

仓库根 = Path(__file__).resolve().parents[1]
# 这里只列出可以向调用方公开能力的正式包根。适配层 Provider 有自己的
# 依赖/运行时门禁，不得混入公开能力六环或公开 owner 冲突统计。
扫描段 = ("支持库/后端", "模块库", "技能库")

# —— 错误码登记环的源与判据（2026-09-16 R1）——
# 两张表的键集是「对外错误码口径」，本地网关按 状态映射 缺键回落 500、
# 网关核心按 说明表 缺键回落「请求处理失败」；因此两张表的源文件路径、
# 变量名在这里写死一份，判据只用 AST 读字面量（不 import 网关：避免加载
# 依赖与副作用）。扫描面**故意大于六环**：错误码是网关对外契约，
# ``支持库/适配层`` 的提供者与 ``平台控制面`` 同样对调用方暴露错误码，
# 只扫六环三根会把它们整体漏检——R1 的 77 个缺登码**全部**落在六环之外。
错误码状态映射源 = ("运行核心", "统一网关", "本地网关.py")
错误码状态映射变量 = "公开错误码状态映射"
错误码说明表源 = ("运行核心", "统一网关", "网关核心.py")
错误码说明表变量 = "公开错误说明表"
错误码扫描排除根 = ("工程缓存",)
# —— 实现侧错误码扫描面（C-15）——
# 实现侧**自己写出来的**码（`结果.失败("危险路径", …)` 一类）不在任何 能力定义.json
# 里，因此四条判据里的前三条全都看不见它；而网关遇到未登记码照样回落 500。
# 扫描面限定「实现/ 下的源码 + 包级 __init__.py」：这两处是实现与包入口，
# 声明/契约/说明三处的码由 能力定义.json 负责（判据一）。
实现侧目录段 = "实现"
实现侧入口文件名 = "__init__.py"
错误码字面量键 = "错误码"
失败方法名 = "失败"


def _是保留目录(路径: Path) -> bool:
    """模板、隐藏目录和缓存目录均不属于正式公开包。"""
    return 路径.name.startswith(("_", "."))


def _是聚合父包(包目录: Path) -> bool:
    """聚合父包：无能力定义.json 且有子目录含包声明.json。

    0342d39 功能域分组后，``支持库/后端`` 直接子目录是聚合入口（如
    ``系统核心支持库``），能力由子域包（``系统核心支持库/幂等消息``）
    声明。聚合父包只做聚合视图，不拥有六环，门禁应跳过它，与正式包索引
    ``无能力定义.json 即聚合父包`` 的 owner 规则一致。
    """
    if (包目录 / "能力定义.json").is_file():
        return False
    return any(
        (子 / "包声明.json").is_file()
        for 子 in 包目录.iterdir() if 子.is_dir()
    )


def 读取json带诊断(路径: Path) -> tuple[object | None, str | None]:
    """读 JSON，返回 ``(值, 诊断)``；诊断把「缺失」「不可读」「可读」分成三态。

    - ``None``：读到合法 JSON（值非空）；
    - ``"缺失"``：路径不存在（调用点仍报原有「…缺失」缺口类型）；
    - ``"不可读:<异常类型名>"``：文件在但读取/解析失败（调用点报「…不可读:异常名」
      缺口类型）。异常类型名进报告是 A-1 的要点：内部故障必须可见、可定位。
    """
    if not 路径.is_file():
        return None, "缺失"
    try:
        return json.loads(路径.read_text(encoding="utf-8")), None
    except Exception as 错误:  # OSError/UnicodeDecodeError/JSONDecodeError 等一律显名上报
        return None, f"不可读:{type(错误).__name__}"


def 找包目录(根: Path) -> list[Path]:
    """返回正式公开包目录（递归到叶子包，跳过聚合父包与保留目录）。

    正式包边界是 ``支持库/后端`` 与 ``模块库``；聚合父包（无能力定义.json
    且有子域包）与 ``_``/``.`` 开头的保留目录不进入扫描。物理目录层级不是
    调用契约，但正式包根的边界是门禁的安全边界。
    """
    目录: list[Path] = []
    for 段 in 扫描段:
        扫描根 = 根 / 段
        if not 扫描根.is_dir():
            continue
        for 声明路径 in sorted(扫描根.rglob("包声明.json")):
            包目录 = 声明路径.parent
            相对 = 包目录.relative_to(扫描根)
            if any(片段.startswith(("_", ".")) for 片段 in 相对.parts):
                continue
            if _是聚合父包(包目录):
                continue
            目录.append(包目录)
    return sorted(目录)


def _公开owner字段(声明: dict) -> list[str]:
    """读取显式公开 owner 字段，供正式包反向阻断 Provider 越界声明。

    ``提供者`` 是实现路由字段，不等于公开 owner，因此不会被误判；只有
    明确写成 ``公开所有者``/``公开owner``/``owner`` 的字段才进入该检查。
    """
    字段值: list[str] = []
    for 键 in ("公开所有者", "公开owner", "owner"):
        值 = 声明.get(键)
        if isinstance(值, str) and 值:
            字段值.append(值)
    for 能力 in 声明.get("能力") or []:
        if not isinstance(能力, dict):
            continue
        for 键 in ("公开所有者", "公开owner", "owner"):
            值 = 能力.get(键)
            if isinstance(值, str) and 值:
                字段值.append(值)
    return 字段值


def _是适配层Provider(owner: str) -> bool:
    """判定 owner 是否指向适配层 Provider（只做声明门禁，不加载实现）。"""
    return owner.startswith("支持库.适配层.") and owner.endswith("提供者")


def 提取注册映射(源码: str) -> dict[str, str]:
    """AST 提取 注册能力 内的 (能力id → 实现函数名) 映射。"""
    映射: dict[str, str] = {}
    try:
        树 = ast.parse(源码)
    except SyntaxError:
        return 映射
    for 节点 in ast.walk(树):
        if not isinstance(节点, ast.FunctionDef) or 节点.name != "注册能力":
            continue
        for 子 in ast.walk(节点):
            if isinstance(子, ast.Call) and isinstance(子.func, ast.Attribute) and 子.func.attr == "注册" and 子.args and isinstance(子.args[0], ast.Call):
                kw = {k.arg: k.value for k in 子.args[0].keywords if k.arg}
                if isinstance(kw.get("能力id"), ast.Constant) and isinstance(kw.get("实现函数"), ast.Name):
                    映射[kw["能力id"].value] = kw["实现函数"].id
            elif isinstance(子, ast.Tuple) and len(子.elts) >= 2 and isinstance(子.elts[0], ast.Constant) and isinstance(子.elts[1], ast.Name):
                映射.setdefault(子.elts[0].value, 子.elts[1].id)
    return 映射


def 提取导出名(源码: str) -> set[str]:
    """包入口导出名：__all__ 存在取其元素，否则取顶层 import 名。"""
    try:
        树 = ast.parse(源码)
    except SyntaxError:
        return set()
    导出: set[str] = set()
    全名: set[str] | None = None
    for 节点 in 树.body:
        if isinstance(节点, ast.ImportFrom):
            导出.update(名.name for 名 in 节点.names if 名.name != "*")
        elif isinstance(节点, ast.Assign) and isinstance(节点.targets[0], ast.Name) and 节点.targets[0].id == "__all__":
            全名 = {e.value for e in 节点.value.elts if isinstance(e, ast.Constant)}
    return 全名 if 全名 is not None else 导出


def 检查包(包目录: Path) -> list[dict]:
    """逐能力六环检查，返回违规清单（能力id/包/缺口类型/路径）。"""
    违规: list[dict] = []
    声明路径 = 包目录 / "包声明.json"
    入口路径 = 包目录 / "__init__.py"
    数据路径 = 包目录 / "能力数据"
    搜索路径 = 数据路径 / "能力搜索数据.json"
    说明路径 = 包目录 / "说明" / "使用说明.md"
    验证路径 = 包目录 / "验证场景引用.json"
    # A-1：可读性与内容分两态判定。不可读（异常）单独出条目并带异常类型，
    # 绝不与「声明可读但未列能力」共用同一缺口类型——两者修法完全不同。
    声明值, 声明诊断 = 读取json带诊断(声明路径)
    声明 = 声明值 if isinstance(声明值, dict) else {}
    包id = 声明.get("包id") or 包目录.name
    能力列表 = 声明.get("能力") or []
    源码 = 入口路径.read_text(encoding="utf-8") if 入口路径.is_file() else ""
    导出名 = 提取导出名(源码)
    映射 = 提取注册映射(源码)
    for owner in _公开owner字段(声明):
        if _是适配层Provider(owner):
            违规.append({"能力id": "*", "包": 包id,
                        "缺口类型": "提供者-适配层Provider不得成为公开owner",
                        "路径": str(声明路径)})
    if 声明诊断 is not None:
        违规.append({"能力id": "*", "包": 包id,
                    "缺口类型": f"声明-包声明.json{声明诊断}", "路径": str(声明路径)})
    elif not 能力列表:
        违规.append({"能力id": "*", "包": 包id, "缺口类型": "声明-包声明.json未列能力", "路径": str(声明路径)})

    if not (包目录 / "能力定义.json").is_file():
        违规.append({"能力id": "*", "包": 包id, "缺口类型": "声明-能力定义.json缺失", "路径": str(包目录 / "能力定义.json")})
    if "注册能力" not in 源码 and not 数据路径.is_dir():
        违规.append({"能力id": "*", "包": 包id, "缺口类型": "注册-入口未注册能力", "路径": str(入口路径)})
    搜索数据, 搜索诊断 = 读取json带诊断(搜索路径)
    搜索id集 = {条.get("能力id") for 条 in 搜索数据} if isinstance(搜索数据, list) else set()
    if 搜索诊断 is not None:
        违规.append({"能力id": "*", "包": 包id, "缺口类型": f"搜索-能力搜索数据.json{搜索诊断}", "路径": str(搜索路径)})

    说明书 = 说明路径.read_text(encoding="utf-8") if 说明路径.is_file() else None
    if 说明书 is None:
        违规.append({"能力id": "*", "包": 包id, "缺口类型": "说明书-使用说明.md缺失", "路径": str(说明路径)})
    验证场景, 验证场景诊断 = 读取json带诊断(验证路径)
    # 引用文件只是索引，必须继续读取实际场景，否则所有按文件引用组织的
    # 正式包都会被误报为“未覆盖能力”。读取失败保持 fail-closed。
    引用能力id: set[str] = set()
    # 包级声明：条目写 目标==本包id，即声明“本包由某资产场景整体覆盖”，
    # 此时不再逐能力要求出现 id（契约由 测试_公开调用完整性门禁 固定）。
    验证覆盖包 = False

    def _收集(对象):
        if isinstance(对象, dict):
            值 = 对象.get("能力id")
            if isinstance(值, str) and 值:
                引用能力id.add(值)
            for 子值 in 对象.values():
                _收集(子值)
        elif isinstance(对象, list):
            for 子值 in 对象:
                _收集(子值)
    _收集(验证场景)
    if isinstance(验证场景, dict):
        for 条 in 验证场景.get("验证场景引用", []):
            if not isinstance(条, dict):
                continue
            if 条.get("目标") == 包id:
                验证覆盖包 = True
            场景文件 = 条.get("场景文件")
            if not isinstance(场景文件, str) or not 场景文件:
                continue
            场景路径 = 包目录 / 场景文件
            场景数据, 场景诊断 = 读取json带诊断(场景路径)
            if 场景诊断 is not None:
                # A-1 同类：场景文件读不成不能静默跳过（跳过会连带误报
                # 「验证场景-未覆盖能力」，把验证器缺口说成被测包缺陷）。
                违规.append({"能力id": "*", "包": 包id,
                            "缺口类型": f"验证场景-场景文件{场景诊断}",
                            "路径": str(场景路径)})
                continue
            _收集(场景数据)
    if 验证场景诊断 is not None:
        违规.append({"能力id": "*", "包": 包id, "缺口类型": f"验证场景-验证场景引用.json{验证场景诊断}", "路径": str(验证路径)})

    for 能力 in 能力列表:
        能力id = 能力.get("能力id") or ""
        名称 = 能力.get("名称") or ""
        if 说明书 is not None and 名称 and 名称 not in 说明书 and 能力id not in 说明书:
            违规.append({"能力id": 能力id, "包": 包id, "缺口类型": "说明书-未含能力名", "路径": str(说明路径)})
        if 搜索数据 is not None and 能力id not in 搜索id集:
            违规.append({"能力id": 能力id, "包": 包id, "缺口类型": "搜索-未含能力id", "路径": str(搜索路径)})
        导出候选 = {能力id.split(".")[-1]}
        if 映射.get(能力id):
            导出候选.add(映射[能力id])
        if 能力id and not (导出候选 & 导出名):
            违规.append({"能力id": 能力id, "包": 包id, "缺口类型": "公开调用-声明未导出", "路径": str(入口路径)})
        # 原判据是 `能力id not in (引用能力id | {验证文本})`——右侧集合只有一个
        # 元素：整份 验证场景引用.json 的文本，等于「能力id 在该文件任意位置
        # 以子串出现即算覆盖」。一个写在路径/说明里的 id 就能免检，属子串后门。
        # 实测（真实仓库 85 包 + 本用例集）去掉子串兜底后判定零变化，故只认
        # 真实收集到的能力id 与包级声明。
        if 验证场景 is not None and not 验证覆盖包 and 能力id not in 引用能力id:
            违规.append({"能力id": 能力id, "包": 包id, "缺口类型": "验证场景-未覆盖能力", "路径": str(验证路径)})
    return 违规


def 检查全局(包能力表: list[tuple[str, str, str]]) -> list[dict]:
    """跨包检查：只查能力 id 全局唯一，豁免中文名重复。

    华哥裁决（2026-08-27）：能力 id 是全局唯一标识（硬约束），中文名是
    显示层，模块库门面组合支持库、多后端提供者、通用能力名都可以同名。
    """
    额外: list[dict] = []
    id表: dict[str, set[str]] = {}
    for 包id, 能力id, 名称 in 包能力表:
        id表.setdefault(能力id, set()).add(包id)
    for 能力id, 包们 in id表.items():
        if 能力id and len(包们) > 1:
            额外.append({"能力id": 能力id, "包": "、".join(sorted(包们)), "缺口类型": "重复提供者-同能力id多包", "路径": "跨包"})
    return 额外


def _错误码声明文件(根: Path):
    """错误码声明面：根下每个非保留、非缓存的顶层目录里的全部 能力定义.json。

    与六环的 ``扫描段`` 不同，这里不限定 ``支持库/后端`` 三根：错误码是网关
    对外契约，``支持库/适配层`` 的提供者与 ``平台控制面`` 同样声明并暴露错误码。
    ``工程缓存`` 是制品/缓存区（R1 时点 592 份制品内 能力定义.json），既不是
    声明源也不该被扫——它会把「制品里的旧声明」当成新契约。
    """
    for 顶层 in sorted(根.iterdir()):
        if not 顶层.is_dir() or 顶层.name.startswith(("_", ".")):
            continue
        if 顶层.name in 错误码扫描排除根:
            continue
        yield from sorted(顶层.rglob("能力定义.json"))


def 读取模块字面量字典(源路径: Path, 变量名: str):
    """AST 读模块级字面量字典；读不出（缺文件/语法错/非字面量）返回 None。

    不 import 网关模块：门禁只读契约源，不为查一张表把网关依赖与副作用拉进来。
    """
    try:
        树 = ast.parse(源路径.read_text(encoding="utf-8"))
    except (OSError, SyntaxError, UnicodeDecodeError):
        return None
    for 节点 in 树.body:
        if not isinstance(节点, ast.Assign):
            continue
        if not any(getattr(目标, "id", None) == 变量名 for 目标 in 节点.targets):
            continue
        try:
            return ast.literal_eval(节点.value)
        except (ValueError, SyntaxError):
            return None
    return None


def 收集声明错误码(根: Path) -> dict[str, dict[str, list[str]]]:
    """全库 能力定义.json 声明的错误码 → ``{码: {"能力": [...], "文件": [...]}}``。"""
    声明: dict[str, dict[str, list[str]]] = {}
    for 定义路径 in _错误码声明文件(根):
        try:
            数据 = json.loads(定义路径.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            continue
        if not isinstance(数据, dict):
            continue
        能力列表 = 数据.get("能力列表") or 数据.get("能力") or []
        for 能力 in 能力列表:
            if not isinstance(能力, dict):
                continue
            for 码 in 能力.get("错误码") or []:
                if not isinstance(码, str) or not 码:
                    continue
                条 = 声明.setdefault(码, {"能力": [], "文件": []})
                条["能力"].append(str(能力.get("能力id") or "?"))
                路径文本 = str(定义路径.relative_to(根))
                if 路径文本 not in 条["文件"]:
                    条["文件"].append(路径文本)
    return 声明


def _实现侧源码清单(根: Path):
    """实现侧错误码的扫描面：各顶层目录下 ``实现/**.py`` 与包级 ``__init__.py``。

    与 ``_错误码声明文件`` 同一套顶层遍历（含保留目录/缓存目录排除），保证
    「声明面」与「实现面」是同一个仓库切片，不会一方扫到另一方扫不到的地方。
    """
    for 顶层 in sorted(根.iterdir()):
        if not 顶层.is_dir() or 顶层.name.startswith(("_", ".")):
            continue
        if 顶层.name in 错误码扫描排除根:
            continue
        for 源码路径 in sorted(顶层.rglob("*.py")):
            if "__pycache__" in 源码路径.parts:
                continue
            if 源码路径.name == 实现侧入口文件名 or 实现侧目录段 in 源码路径.parts:
                yield 源码路径


def _实现侧字面量错误码(树: ast.AST) -> set[str]:
    """AST 取实现侧产码的两条**信封渠道**：

    ① ``错误码=<字面量>`` 关键字实参（``_响应(False, 错误码="提供者不可用", …)``）；
    ② ``<结果>.失败(<字面量>, …)`` 的**首个位置实参** —— 全仓 475 处 ``结果.失败`` 走的就是这条。

    为什么必须两条一起扫：实测真仓库里走 ① 的只有 4 种码、走 ② 的 240 种码；
    只扫 ① 本判据在真仓库上等于恒绿（真盲区一个都看不见，属 A-3 那类自证）。

    **不扫** ``{"错误码": <字面量>}`` 字典项：那一形式同时出现在**行为声明**
    （``默认行为 = {"错误码": "统一", …}``）、**模板生成内容**与**值内字段**里，
    计进来会把「声明」和「返回给调用方的值字段」说成「实现侧产码」——
    正是 A-1 那条病根（把判据错误说成被测缺陷）。字面量之外的动态码读不到，
    属已知口径边界，写在这里而不是假装扫到了。
    """
    码集: set[str] = set()
    for 节点 in ast.walk(树):
        if isinstance(节点, ast.keyword) and 节点.arg == 错误码字面量键:
            值 = 节点.value
            if isinstance(值, ast.Constant) and isinstance(值.value, str) and 值.value:
                码集.add(值.value)
        elif (isinstance(节点, ast.Call) and isinstance(节点.func, ast.Attribute)
                and 节点.func.attr == 失败方法名 and 节点.args):
            首参 = 节点.args[0]
            if isinstance(首参, ast.Constant) and isinstance(首参.value, str) and 首参.value:
                码集.add(首参.value)
    return 码集


def 收集实现侧错误码(根: Path) -> tuple[dict[str, list[str]], list[dict], int]:
    """实现侧产生的码 → ``{码: [相对路径…]}``；返回 (码表, 不可解析清单, 扫描文件数)。

    不可解析（语法坏/读不成/解码错）**不静默跳过**：跳过等于把「这份实现的错误码
    情况未知」压成「它没有错误码」，正是 A-1/A-2 那条病根。三条信息分开返回，
    由 ``检查错误码登记`` 分别出条目。
    """
    码表: dict[str, list[str]] = {}
    不可解析: list[dict] = []
    扫描数 = 0
    for 源码路径 in _实现侧源码清单(根):
        扫描数 += 1
        路径文本 = str(源码路径.relative_to(根))
        try:
            树 = ast.parse(源码路径.read_text(encoding="utf-8"))
        except (OSError, SyntaxError, UnicodeDecodeError) as 错误:
            不可解析.append({"路径": 路径文本, "异常": type(错误).__name__})
            continue
        for 码 in _实现侧字面量错误码(树):
            文件们 = 码表.setdefault(码, [])
            if 路径文本 not in 文件们:
                文件们.append(路径文本)
    return 码表, 不可解析, 扫描数


def _实现侧条目(码: str, 缺口类型: str, 文件们: list[str]) -> dict:
    """实现侧错误码条目：路径来自实现源码，包取该源码所在包目录。"""
    路径文本 = "、".join(sorted(文件们)[:2]) + (
        " 等 %d 处" % len(文件们) if len(文件们) > 2 else "")
    包文本 = str(Path(sorted(文件们)[0]).parent) if 文件们 else "跨包"
    return {"能力id": "*", "包": 包文本, "缺口类型": 缺口类型,
            "错误码": 码, "路径": 路径文本}


def _错误码条目(码: str, 缺口类型: str, 来源: dict | None = None,
                路径文本: str = "") -> dict:
    """统一构造错误码环违规条目（字段与六环条目同形，便于同一处打印）。"""
    if 来源:
        能力们 = sorted(set(来源.get("能力") or []))
        能力文本 = "、".join(能力们[:3]) + (" 等 %d 条声明" % len(能力们) if len(能力们) > 3 else "")
        文件们 = sorted(来源.get("文件") or [])
        路径文本 = "、".join(文件们[:2]) + (" 等 %d 处" % len(文件们) if len(文件们) > 2 else "")
        包文本 = str(Path(文件们[0]).parent) if 文件们 else "跨包"
    else:
        能力文本, 包文本 = "*", "运行核心.统一网关"
    return {"能力id": 能力文本, "包": 包文本, "缺口类型": 缺口类型,
            "错误码": 码, "路径": 路径文本}


def 检查错误码登记(根: Path) -> list[dict]:
    """错误码登记环：**能力定义声明码 ⊆ 状态映射码**，两张表键集一致，且**实现侧产码 ⊆ 状态映射码**。

    判据四条（同一条门禁项，缺口类型前缀 ``错误码-``）：
      ① 声明码 ⊆ 状态映射码 —— 缺键即回落 500，正是 R1 的 77 码病根；
      ② 状态映射码 == 说明表码   —— 同仓既有的「同一提交同步三处」纪律，
         单向缺一侧都会让调用方拿到「500 或没有原因的失败」；
      ③ 真仓库自身读不到两张表即 fail-closed（临时测试根没有网关源，
         由六环检查判该根，这里不造条目）；
      ④ **实现侧产生的码 ⊆ 状态映射码**（C-15）—— 实现侧直接写进代码的码
         不经 ``能力定义.json``，前三条全都看不见它；扫不到 / 源码不可解析 /
         真缺码 分别出条目（同 A-1 口径，不许把「没扫到」说成「不违规」）。
    """
    状态映射 = 读取模块字面量字典(根.joinpath(*错误码状态映射源), 错误码状态映射变量)
    说明表 = 读取模块字面量字典(根.joinpath(*错误码说明表源), 错误码说明表变量)
    if not isinstance(状态映射, dict) or not isinstance(说明表, dict):
        if 根.resolve() != 仓库根.resolve():
            return []
        缺失 = []
        if not isinstance(状态映射, dict):
            缺失.append(_错误码条目("-", "错误码-状态映射源不可读"))
        if not isinstance(说明表, dict):
            缺失.append(_错误码条目("-", "错误码-错误说明源不可读"))
        return 缺失
    违规: list[dict] = []
    for 码, 来源 in sorted(收集声明错误码(根).items()):
        if 码 not in 状态映射:
            违规.append(_错误码条目(码, "错误码-能力定义声明码未登记状态映射", 来源))
    for 码 in sorted(set(状态映射) - set(说明表)):
        违规.append(_错误码条目(码, "错误码-状态映射码缺错误说明"))
    for 码 in sorted(set(说明表) - set(状态映射)):
        违规.append(_错误码条目(码, "错误码-错误说明码缺状态映射"))
    实现码表, 不可解析, 扫描数 = 收集实现侧错误码(根)
    for 条 in 不可解析:
        违规.append(_实现侧条目(条["异常"], f"错误码-实现侧源码不可解析:{条['异常']}", [条["路径"]]))
    if 扫描数 == 0:
        # 扫描面为空 = 本判据什么都没看（那份仓库切片被移走/改名），
        # 恒绿而不是通过：与 A-3「扫描面为空必须判红」同一条纪律。
        违规.append({"能力id": "*", "包": "全仓实现侧", "错误码": "-",
                    "缺口类型": "错误码-实现侧扫描面为空", "路径": "实现/** 与 包级 __init__.py"})
    for 码, 文件们 in sorted(实现码表.items()):
        if 码 not in 状态映射:
            违规.append(_实现侧条目(码, "错误码-实现侧产生码未登记状态映射", 文件们))
    # ⑤ 「说明表 == 派生结果」不变式（2026-09-17）。
    #    判据②只保证两张表**键集**一致，看不见「状态码改了、说明表文案没跟」这条
    #    漂移：说明表 337 条里 250 条其实是「码 + 状态码模板」的机械派生，却被逐条
    #    手写固定 —— 同一条事实（这个码属于哪一类失败）在状态映射与说明表各写一遍。
    #    派生规范（状态码文案模板 + 87 条手写例外）与逐字比对落在
    #    ``开发工具/错误码文案派生.py``，这里只做接线与 fail-closed。
    #    守卫：比对对象是真仓库的契约源；临时夹具根（单测只写两份最小表）没有派生
    #    规范，按 根 守卫跳过；真仓库侧读不到派生规范模块即判红，不静默放过。
    if 根.resolve() == 仓库根.resolve():
        违规.extend(检查错误说明派生(根))
    return 违规


def 检查错误说明派生(根: Path) -> list[dict]:
    """不变式：``公开错误说明表 == 派生(公开错误码状态映射 × 状态码文案模板 + 手写例外)``。

    委派 ``开发工具/错误码文案派生.py::校验``（该模块是派生规范的唯一落点：
    模板、例外文案、逐字比对判据都在那里）。用 importlib 按路径载入 —— 本门禁既
    可 ``python3 开发工具/公开调用完整性门禁.py`` 直跑（此时 sys.path[0] 是
    ``开发工具``，包式 import 不成立），也可被 ``发布门禁`` 以包形式调用，
    按路径载入两种模式同一结果。载入失败 **fail-closed** 出条目。
    """
    import importlib.util
    规范路径 = 仓库根 / "开发工具" / "错误码文案派生.py"
    if not 规范路径.is_file():
        return [_错误码条目("-", "错误码-派生规范模块缺失", {"路径": [str(规范路径)]})]
    try:
        规格 = importlib.util.spec_from_file_location("_错误码文案派生规范", 规范路径)
        if 规格 is None or 规格.loader is None:
            raise ImportError("无法构造模块规格")
        模块 = importlib.util.module_from_spec(规格)
        规格.loader.exec_module(模块)
    except Exception as 异常:
        return [_错误码条目("-", f"错误码-派生规范模块载入失败:{type(异常).__name__}",
                            {"路径": [str(规范路径)]})]
    return 模块.校验(根)


def 运行门禁(根: Path) -> list[dict]:
    """扫描根目录下全部包，返回六环、全局检查与错误码登记的完整违规清单。"""
    违规: list[dict] = []
    包能力表: list[tuple[str, str, str]] = []
    for 包目录 in 找包目录(根):
        声明值, 声明诊断 = 读取json带诊断(包目录 / "包声明.json")
        违规.extend(检查包(包目录))
        # 不可读的包声明由 检查包 单独出「不可读」条目；这里既不重复出条目，
        # 也不把不可读静默当成「无能力」进包能力表（那会让全局重复提供者检查
        # 对整包失效，等于用一次读取故障换一片检查盲区）。
        if 声明诊断 is not None:
            continue
        声明 = 声明值 if isinstance(声明值, dict) else {}
        包id = 声明.get("包id") or 包目录.name
        包能力表.extend((包id, 能力.get("能力id") or "", 能力.get("名称") or "") for 能力 in 声明.get("能力") or [])
    违规.extend(检查全局(包能力表))
    违规.extend(检查错误码登记(根))
    return 违规


def 主程序() -> int:
    根 = Path(sys.argv[1]) if len(sys.argv) > 1 else 仓库根
    违规 = 运行门禁(根)
    if not 违规:
        print("公开调用完整性门禁通过：六环一致 + 错误码登记环一致，无违规")
        return 0
    print(f"公开调用完整性门禁失败：共 {len(违规)} 项违规（六环缺口+重复提供者+错误码登记）")
    for 条 in 违规:
        尾 = f" 错误码={条['错误码']}" if 条.get("错误码") else ""
        print(f"[{条['缺口类型']}] 能力id={条['能力id']} 包={条['包']} 路径={条['路径']}{尾}")
    return 1


if __name__ == "__main__":
    sys.exit(主程序())
