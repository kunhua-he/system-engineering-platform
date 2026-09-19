"""公开调用完整性门禁 · 包与目录发现簇（拆分自 开发工具/公开调用完整性门禁.py）。

职责：**「哪些目录是正式公开包」这一件事的唯一落点** ——
正式根名表的读取、保留目录/适配层/聚合父包/系统适配器的判定、包目录枚举、
包入口源码的 AST 提取，以及三个读文件带诊断的原语（读取json带诊断/读取文本带诊断/
读取模块字面量字典）。

判据唯一事实源（本模块不自持，全部只读不改）：
  · 正式根名表 ← ``公共契约/正式根.py``（决策记录 0012）；
  · 聚合视图包 ← ``公共契约.正式根.是聚合视图包``（本模块只在其上追加更严的能力归属校验）；
  · 适配层系统适配器名录 ← ``AGENTS.md``「系统适配器豁免」（改名录必须同批改 AGENTS.md）。

为什么拆出来：这三件事（六环扫描根、找包目录、读契约源）是全仓多个门禁共用的
同一份判据，此前与六环/说明书/错误码/依赖锁四簇挤在一个 1541 行文件里，
任何一簇的判据变更都要在一个巨型文件里定位。拆分按**职责簇**切，对外名字一个不改
（原文件按名再导出，见 ``开发工具/公开调用完整性门禁.py`` 的对外导出面）。
"""
from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

仓库根 = Path(__file__).resolve().parents[1]
# —— 直跑与包式调用同一结果（2026-09-18 修）——
# 本模块既被发布门禁以包形式调用，也支持按文件名直跑。直跑时 sys.path 不含仓库根，
# `from 公共契约.…` 不成立（实测直跑会直接 ModuleNotFoundError 崩溃，比报红更糟）。
# 这里显式补根，与仓内其他按路径加载模块的写法同口径。
if str(仓库根) not in sys.path:
    sys.path.insert(0, str(仓库根))
from 公共契约.基础类型.逻辑类型 import 真, 假  # noqa: E402  （正式类型名，防回潮口径）

# —— E-2：六环扫描范围（唯一事实源，不再硬编码三根）——
# 修前：扫描段 = ("支持库/后端", "模块库", "技能库") —— 正式包 133 里 37 个
# 圈外（平台控制面 16 + 支持库/前端 9 + 支持库/适配层 17，2026-09-17 实测），
# 门禁 rc=0 却不报。修后：扫描根读 公共契约/正式根.py:正式根名表（平台对
# 「哪些顶层目录是正式包根」的唯一事实源，见 决策记录 0012），读不成即
# 扫描面为空 → 判红，不退回硬编码（fail-closed）。
正式根唯一事实源 = ("公共契约", "正式根.py")
正式根名表变量 = "正式根名表"


# 适配层豁免（AGENTS.md 原文名单）：这些**系统适配器**不对外提供能力契约，
# 不要求 包声明.json/完整性摘要.json/能力契约/验证场景引用.json。
# 豁免的两条前提缺一不可：① 目录名在本名单内（中央声明，不是包自己声明）；
# ② 该目录**没有** 包声明.json（与 扫描正式包 的收录标记同口径）。
# 名录不是免检牌：谁给自己加了 包声明.json，就照六环检查（豁免不得自证）。
# 名录命名口径（2026-09-18 配置双入口收口）：`提供者配置读取` 原名 `配置读取`，
# 为避免与项目门面层 `项目适配层/配置适配/配置读取.py` 同名混淆而改名 —— **只统一命名，
# 不合并**（两者是「提供者层读外部协议配置」与「项目门面层做项目配置加载/合并/校验」的
# 合法分层，定性依据见 `开发文档/分析/配置双入口收口_20260918.md`）。
# 名录与 `AGENTS.md`「系统适配器豁免」名录逐项同源；改本名录必须同批改 AGENTS.md。
系统适配器名表 = frozenset({
    "提供者配置读取", "配置契约", "提供者注册表", "提供者配置", "配置安全",
    "HTTP服务适配器", "数据库适配器", "本地进程适配器", "动态库适配器",
    "密钥提供者", "系统探针",
})
适配层根名 = ("支持库", "适配层")


def _是保留目录(路径: Path) -> bool:
    """模板、隐藏目录和缓存目录均不属于正式公开包。"""
    return 路径.name.startswith(("_", "."))


def _声明能力id集(声明: dict) -> set[str]:
    """包声明里声明的能力 id 集合（只取非空字符串，空 id 不参与判定）。"""
    结果: set[str] = set()
    for 能力 in 声明.get("能力") or []:
        if not isinstance(能力, dict):
            continue
        值 = str(能力.get("能力id") or "").strip()
        if 值:
            结果.add(值)
    return 结果


def _子包声明路径(包目录: Path) -> list[Path]:
    """包目录下**子包**（不含自身）的 ``包声明.json``，跳过保留目录。

    与 ``正式包索引.构建索引`` 的 ``子声明``（``包路径.rglob("包声明.json")``，
    递归到孙子包）同口径，不只看直接子目录：只认直接子目录会给「隔一层才放子包」
    留同样的豁免后门。
    """
    路径表: list[Path] = []
    for 声明路径 in sorted(包目录.rglob("包声明.json")):
        相对 = 声明路径.parent.relative_to(包目录)
        if not 相对.parts:
            continue
        if any(片段.startswith(("_", ".")) for 片段 in 相对.parts):
            continue
        路径表.append(声明路径)
    return 路径表


def _是聚合父包(包目录: Path, 声明: dict | None = None) -> bool:
    """聚合父包（视图）：**自己不拥有任何能力**，目录只作子包能力的聚合视图。

    **本函数已不自持判据**（2026-09-18 债务 #38 收口）：物理判据取唯一事实源
    `公共契约.正式根.是聚合视图包`（无 `能力定义.json` 且含子包声明），
    本处只在其上追加一条**更严**的能力归属校验（③）。

    保留 ③ 的理由（2026-09-17 修 fail-open）：只判 ①+②时，**任何**包只要塞一个
    占位子目录就自证成聚合父包 —— 六环整包跳过，能力也不进 ``包能力表``，
    连带 ``检查全局`` 的唯一性硬约束对它整体失效。夹具实测：两包声明同一能力 id
    时报 2 项违规（「能力定义.json缺失」+「重复提供者-同能力id多包」），
    加占位子目录后报 0 项。现在只要父包声明了子包没有的能力，一律照六环检查、
    并作为真实 owner 参与全局唯一性判定。
    """
    from 公共契约.正式根 import 是聚合视图包

    if not 是聚合视图包(包目录):
        return 假
    if 声明 is None:
        声明值, 诊断 = 读取json带诊断(包目录 / "包声明.json")
        if 诊断 is not None:
            return 假
        声明 = 声明值 if isinstance(声明值, dict) else {}
    子声明 = _子包声明路径(包目录)
    if not 子声明:
        return 假
    自己id = _声明能力id集(声明)
    if not 自己id:
        return 真
    子id: set[str] = set()
    for 子路径 in 子声明:
        子值, 子诊断 = 读取json带诊断(子路径)
        if 子诊断 is None and isinstance(子值, dict):
            子id |= _声明能力id集(子值)
    return 自己id <= 子id


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


def 六环扫描根(根: Path) -> tuple[str, ...]:
    """六环扫描根 = 唯一事实源 ``公共契约/正式根.py:正式根名表`` 里**实际存在**的根。

    只读事实源的字面量（AST），不 import：本门禁既可 ``python3 开发工具/公开调用完整性门禁.py``
    直跑（此时 sys.path 不含仓库根，包式 import 不成立），也可被发布门禁以包形式调用，
    两种模式必须同一结果。读不成 ⇒ 返回空元组 ⇒ 调用方判「扫描面为空」红，
    **绝不**退回硬编码三根（那正是 E-2 的病根）。

    事实源取自**本模块所在仓库**（``仓库根``）：扫描范围是平台级常量，不是每个
    被测根各自声明的；``根`` 参数只用来过滤「该根下实际存在哪些正式根目录」。
    这样夹具根（临时目录）与真仓库共用同一份范围，判据不会因根而异。
    """
    return tuple(名 for 名 in 六环扫描根名() if (根 / 名).is_dir())

def 六环扫描根名() -> tuple[str, ...]:
    """从 ``仓库根/公共契约/正式根.py`` 读 ``正式根名表``；读不成返回空元组。"""
    名表 = 读取模块字面量字典(仓库根.joinpath(*正式根唯一事实源), 正式根名表变量)
    if not isinstance(名表, (tuple, list)) or not 名表:
        return ()
    return tuple(名 for 名 in 名表 if isinstance(名, str) and 名)


def _是适配层(包目录: Path) -> bool:
    """目录路径里是否出现 ``支持库/适配层`` 这一段（owner 表按此豁免）。"""
    部分 = 包目录.parts
    return any(部分[i] == 适配层根名[0] and 部分[i + 1] == 适配层根名[1]
               for i in range(len(部分) - 1))


def _是系统适配器(包目录: Path) -> bool:
    """适配层**系统适配器**豁免：名录内 + 无 ``包声明.json``，两条缺一不可。

    - 名录是中央声明（``系统适配器名表``），不接受包自己声明豁免；
    - 一旦该目录带上 ``包声明.json``，它就是**自认的正式包**，照六环检查
      （豁免不得自证，fail-closed：名录不是免检牌）。
    """
    if 包目录.name not in 系统适配器名表:
        return 假
    if not _是适配层(包目录):
        return 假
    return not (包目录 / "包声明.json").is_file()


def 读取文本带诊断(路径: Path) -> tuple[str | None, str | None]:
    """读 UTF-8 文本，返回 ``(文本, 诊断)``；诊断口径与 ``读取json带诊断`` 完全一致。

    A-1 同类：文件在但读不成（权限/编码坏）必须**显名上报**，不得压成「缺失」，
    也不得让 UnicodeDecodeError 冒到门禁外层变成「审计异常」——那会把
    「这份说明书读不成」写成「门禁坏了」，修复方向被带偏。
    """
    if not 路径.is_file():
        return None, "缺失"
    try:
        return 路径.read_text(encoding="utf-8"), None
    except Exception as 错误:  # OSError/UnicodeDecodeError 等一律显名上报
        return None, f"不可读:{type(错误).__name__}"


def 找全部包目录(根: Path) -> list[Path]:
    """扫描根内**所有**包的 ``包声明.json`` 所在目录（含聚合父包），跳过保留目录。

    唯一性判定必须看到每一个包的声明：2026-09-17 的 fail-open 正是「跳过聚合父包」
    这一步顺带把它的能力 id 一起移出了全局唯一性判定。六环扫描（``找包目录``）
    与唯一性扫描（本函数）因此必须是两个面。

    E-2：扫描根取 ``六环扫描根``（唯一事实源），不再硬编码 ``支持库/后端`` 三根。
    """
    目录: list[Path] = []
    for 段 in 六环扫描根(根):
        扫描根 = 根 / 段
        for 声明路径 in sorted(扫描根.rglob("包声明.json")):
            包目录 = 声明路径.parent
            相对 = 包目录.relative_to(扫描根)
            if any(片段.startswith(("_", ".")) for 片段 in 相对.parts):
                continue
            if _是系统适配器(包目录):
                continue
            目录.append(包目录)
    return sorted(目录)


def 找包目录(根: Path) -> list[Path]:
    """返回正式公开包目录（递归到叶子包，跳过聚合父包与保留目录）。

    正式包边界由 ``六环扫描根``（``公共契约/正式根.py:正式根名表``）给出；
    聚合父包（视图，判据见 ``_是聚合父包``）、``_``/``.`` 开头的保留目录
    与适配层系统适配器不进入六环扫描。物理目录层级不是调用契约，
    但正式包根的边界是门禁的安全边界。
    """
    return [包目录 for 包目录 in 找全部包目录(根) if not _是聚合父包(包目录)]


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


def 读取模块字面量字典(源路径: Path, 变量名: str):
    """AST 读模块级字面量赋值；读不出（缺文件/语法错/非字面量）返回 None。

    不 import 网关模块：门禁只读契约源，不为查一张表把网关依赖与副作用拉进来。
    两种赋值形态都认：``名 = 字面量``（Assign）与 ``名: 类型 = 字面量``（AnnAssign）
    —— ``公共契约/正式根.py:正式根名表`` 就是后者（带类型标注），只认 Assign
    会让「扫描范围读唯一事实源」直接读空。
    """
    try:
        树 = ast.parse(源路径.read_text(encoding="utf-8"))
    except (OSError, SyntaxError, UnicodeDecodeError):
        return None
    for 节点 in 树.body:
        值 = None
        if isinstance(节点, ast.Assign) and any(
                getattr(目标, "id", None) == 变量名 for 目标 in 节点.targets):
            值 = 节点.value
        elif isinstance(节点, ast.AnnAssign) and isinstance(节点.target, ast.Name) \
                and 节点.target.id == 变量名 and 节点.value is not None:
            值 = 节点.value
        if 值 is None:
            continue
        try:
            return ast.literal_eval(值)
        except (ValueError, SyntaxError):
            return None
    return None
