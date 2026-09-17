"""公开调用完整性门禁：正式公开包的六环一致性 + 错误码登记环 + 说明书字段环。

正式公开边界是**顶层正式根**（``公共契约/正式根.py:正式根名表``，唯一事实源：
``支持库`` / ``模块库`` / ``技能库`` / ``平台控制面`` / ``运行核心`` / ``启动监督器``），
不再把三根（``支持库/后端``、``模块库``、``技能库``）写死在门禁里。``支持库/适配层``
是 Provider/第三方实现边界：它可以声明内部实现能力，但不能成为公开能力
owner，也不能因为和正式包使用同一能力 id 而制造重复 owner（owner 表仍按此豁免，
见 ``运行门禁``）。模板目录（如 ``模块库/_模板``）同样不是正式包，
禁止进入扫描、注册和冲突统计。

**E-2（2026-09-17 扩扫范围）**：原扫描段只有三根，正式包 133 里有 **37 个圈外**
（平台控制面 + 支持库/前端 + 支持库/适配层），门禁 rc=0 却不报——那批包缺
``说明/使用说明.md``/``能力定义.json`` 时照样"通过"。现在扫描根取**唯一事实源**
``公共契约/正式根.py:正式根名表``（AST 读字面量，不 import：本模块直跑与包式调用
同一结果），逐根收录；读不成事实源 ⇒ 扫描面为空 ⇒ **判红**（fail-closed，
绝不退回硬编码三根）。
适配层豁免按 AGENTS.md 原样保留：``系统适配器名表``（配置读取/配置契约/提供者注册表/
提供者配置/配置安全/HTTP服务适配器/数据库适配器/本地进程适配器/动态库适配器/
密钥提供者/系统探针）不要求六件套，**但豁免只在"该目录没有 包声明.json"时成立**
（与 ``组件规范支持库.扫描正式包`` 的收录标记同口径）：名录不是免检牌，
谁给自己加了 ``包声明.json`` 就照六环检查——豁免不得自证。

**E-3（2026-09-17 字段级对账）**：六环原先只查 ``说明/使用说明.md`` 是否存在、
能力名/能力id 是否作为子串出现，版本/参数/必填/错误码/返回**全不比**——
说明书自称"调用权威"却可以整段滞后而门禁恒绿。现在 ``检查说明书字段`` 逐能力
按声明侧（``能力定义.json`` → ``能力契约/参数契约.json`` → ``包声明.json`` 逐级兜底）
比对五类结构化字段，含"声明侧有值、说明书却没载位"这一档（判不出 ≠ 通过）。
判据变更按铁律同批处理存量：本包旁的 ``公开调用完整性门禁存量基线.json``
按「包×缺口类型」分桶承载存量（**只减不增**：基线外的组合判红，桶内计数超出判红），
基线文件读不成 = 全量判红（不静默放过）。

**错误码登记环（2026-09-16 R1 新增，防第四批漂移）**：``能力定义.json``
里声明的每个错误码都必须在网关的 ``公开错误码状态映射`` 里登记；两张表
（状态映射 + 说明表）键集必须一致。缺键的代价见 ``本地网关.py``——
HTTP 状态码回落 500、错误说明回落「请求处理失败」，把可辨识的业务失败
伪装成服务端故障（R1 实测：77 码曾因此漏登，波及 13 条 HTML 黑盒场景）。

**注册表为唯一事实源（包声明.json 能力列表），公开调用必须经由注册能力导出。**
任一违规 → 退出码 1 并打印缺口类型/能力id/包/路径清单；全部通过 → 退出码 0。

**聚合父包豁免的边界（2026-09-17 修 fail-open）**：``_是聚合父包`` 原判据是「无
``能力定义.json`` 且有子目录含 ``包声明.json``」——于是**任何**包只要塞一个占位子目录
就能自证成聚合父包：六环整包跳过（连「能力定义.json缺失」都不报），能力也不进
``包能力表``，连带 ``检查全局`` 的「能力 id 全局唯一」硬约束一起失效。夹具实测：
两包声明同一能力 id → 违规 2 项（「能力定义.json缺失」+「重复提供者-同能力id多包」）；
给其中一个包加一个占位子目录 → 违规 **0** 项。现在补两条前置：
① ``_是聚合父包`` 只在**自己不拥有能力**（自己声明的能力 id 全部由子包声明持有）时成立，
父包只要声明了子包没有的能力就一律照六环检查；
② 全局唯一性判定看**全部**包声明的能力 id（含聚合父包的重声明，按
``正式包索引``／``能力索引`` 的 owner 去重口径：同一 id 同时出现在聚合父包与子包声明时
owner 取带 ``能力定义.json`` 的子包），不再依赖「是否进 ``包能力表``」这一个条件。
口径与 ``开发工具/项目编译/正式包索引.构建索引`` 的 owner 规则一致：无
``能力定义.json`` + 子包持有该能力 ⇒ 子包是 owner、父包只是视图。

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
import re
import sys
from pathlib import Path

仓库根 = Path(__file__).resolve().parents[1]
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
系统适配器名表 = frozenset({
    "配置读取", "配置契约", "提供者注册表", "提供者配置", "配置安全",
    "HTTP服务适配器", "数据库适配器", "本地进程适配器", "动态库适配器",
    "密钥提供者", "系统探针",
})
适配层根名 = ("支持库", "适配层")
说明书相对路径 = ("说明", "使用说明.md")
公开调用存量基线文件名 = "公开调用完整性门禁存量基线.json"

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

    判据三条，缺一不可（2026-09-17 修 fail-open）：

    ① 无 ``能力定义.json`` —— 自带能力定义的包即便含子包仍是真实能力 owner，
       与 ``正式包索引._是聚合父包`` 及 ``构建索引`` 的既有口径一致；
    ② 有子包 ``包声明.json``（递归，同 ``构建索引`` 的 ``子声明`` 口径）；
    ③ **自己声明的能力 id 全部由子包声明持有**（= 自己不拥有能力）。

    修改前判据只有 ①+②：**任何**包只要塞一个占位子目录就自证成聚合父包 —— 六环
    整包跳过，能力也不进 ``包能力表``，连带 ``检查全局`` 的唯一性硬约束对它整体失效。
    夹具实测：两包声明同一能力 id 时报 2 项违规（「能力定义.json缺失」+「重复提供者-
    同能力id多包」），加占位子目录后报 0 项。现在只要父包声明了子包没有的能力，
    一律照六环检查、并作为真实 owner 参与全局唯一性判定。

    为什么前置条件是「子包持有」而不是「自身能力列表为空」：真实仓库六大聚合支持库
    （``支持库/后端`` 下的系统核心/大语言模型/数据操作/文件系统/网络通信/办公文档支持库）
    的 ``包声明.json`` 里就是满篇子包能力的聚合视图（44/36/48/19/6/13 条，经核对均为
    子包声明 id 的子集），列表都不为空；按「列表必须为空」判定会把它们整体打红
    （6 包六环缺口 + 166 条伪重复），那是制造假红而不是修漏洞。``正式包索引``／
    ``能力索引`` 的 owner 口径同样是「同一 id 同时出现在聚合父包与子包声明时，
    owner 取带 ``能力定义.json`` 的子包」，故「自己不拥有能力」是与 owner 规则
    等价的口径。

    读不成 ``包声明.json``（缺失/不可读）→ **False**：交给六环报「不可读」，
    绝不因为一次读取故障白送一张豁免（fail-closed）。
    """
    if (包目录 / "能力定义.json").is_file():
        return False
    if 声明 is None:
        声明值, 诊断 = 读取json带诊断(包目录 / "包声明.json")
        if 诊断 is not None:
            return False
        声明 = 声明值 if isinstance(声明值, dict) else {}
    子声明 = _子包声明路径(包目录)
    if not 子声明:
        return False
    自己id = _声明能力id集(声明)
    if not 自己id:
        return True
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
        return False
    if not _是适配层(包目录):
        return False
    return not (包目录 / "包声明.json").is_file()


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


# —— E-3：说明书结构化字段对账（2026-09-17） ——
# 六环原先只查「说明书是否存在 + 能力名/能力id 作为子串」，版本/参数/必填/错误码/
# 返回全不比：说明书自称「调用权威」，却可以整段滞后而门禁恒绿（E-1/E-3 的存量
# 就是这么做大的）。这里按**声明侧**（能力定义.json → 能力契约/参数契约.json →
# 包声明.json 逐级兜底）逐能力对账五类字段，并单列一档「声明侧有值、说明书没载位」
# ——判不出**不等于**通过。
表头行 = re.compile(r"^\s*\|(.+)\|\s*$")
标题行 = re.compile(r"^(#{2,4})\s+(.*)$")
版本行 = re.compile(r"^- 版本：(\S+)\s*$")
参数列表行 = re.compile(r"^- 参数列表：(.*)$")
必填参数行 = re.compile(r"^- 必填参数：(.*)$")
错误码行 = re.compile(r"^-?\s*\*{0,2}错误码\*{0,2}[：:]\s*(.*)$")
错误码分隔 = re.compile(r"[，,、;；]")
返回结构行 = re.compile(r"^- 返回结构：(.*)$")
返回结构粗体行 = re.compile(r"^\*\*返回结构\*\*[：:]\s*(.*)$")
返回类型紧排 = re.compile(r"[\"']类型[\"']\s*:\s*[\"']([^\"']+)[\"']")
能力id形 = re.compile(r"[^\s|`（）()]+(?:\.[^\s|`（）()]+)+")
# 返回类型名的判据用 16 项正式类型表的**唯一事实源**（与 HTML 验证器消费同一份：
# `公共契约/基础类型/类型表.py:正式类型表`）。读不成时退化为「以『型』结尾」这一
# 形状判据——仍要判，只是判据弱一档，不静默放过。
正式类型表唯一事实源 = ("公共契约", "基础类型", "类型表.py")
正式类型表变量 = "正式类型表"


def _表格行(行: str) -> list[str] | None:
    """markdown 表行 → 单元格列表；非表行返回 None。"""
    匹配 = 表头行.match(行)
    if 匹配 is None:
        return None
    格 = [单元.strip() for 单元 in 匹配.group(1).split("|")]
    if 格 and all(set(单元) <= {"-", ":"} and 单元 for 单元 in 格):
        return None  # 分隔行
    return 格


def _清单形(格: list[str]) -> bool:
    """该表行是否是「能力清单」行（首格是能力 id）。"""
    return bool(格) and bool(能力id形.fullmatch(格[0])) and "." in 格[0]


def _是表头行(格: list[str]) -> bool:
    """markdown 表头行判定：首格是列名族、第二格是它的**元信息列名**。

    为什么必须两格一起判：``错误码`` 既可能是列名（``| 错误码 | 触发条件 |``），
    也可能是**参数名**（``平台控制面.平台状态.追加证据`` 的参数里就有 ``错误码``：
    ``| 错误码 | 文本型 | 否 | … |``）。只看首格会把参数行当表头，整张参数表就丢了；
    只看第二格会把任何以「类型」结尾的中文列当表头。两格同时命中的集合才是表头。

    单列表头（``| 错误码 |`` + 下方逐行码，见 ``平台控制面/平台状态`` 与
    ``平台控制面/包仓库`` 的既有体例）也认：那种表只有一列，第二格不存在。
    """
    列名族 = {"参数", "入参", "错误码", "字段", "值字段", "返回", "返回结构"}
    if len(格) == 1:
        return 格[0] in 列名族
    return (len(格) >= 2 and 格[0] in 列名族
            and 格[1] in {"类型", "说明", "含义", "默认值", "触发条件"})


def _解析参数散文(文本: str) -> dict[str, tuple[str | None, bool | None]]:
    """把散文式参数描述解析成 ``{名称: (类型, 必填)}``（两种既有写法）。

    - 甲支/清单表写法：``身份id:文本型（必填），所有者:文本型``
    - 金标记法：``临时根目录(文本型,必填)、清单路径(文本型,必填)``
    解析不出的片段**不猜**（不计入），解析结果只用于「名称集合/类型/必填」三类比对；
    名称集合这一档对本函数是可判的，类型与必填在写法缺失时为 ``None``（不比）。
    """
    出: dict[str, tuple[str | None, bool | None]] = {}
    for 片段 in re.split(r"[，,、;；]", 文本 or ""):
        片段 = 片段.strip().strip("`")
        if not 片段 or 片段 in {"无", "（无）", "(无)"}:
            continue
        冒号 = re.match(r"^([^:：()（）]+)[:：]\s*(.*)$", 片段)
        if 冒号:
            名称 = 冒号.group(1).strip()
            尾 = 冒号.group(2).strip()
            必填 = None
            if 尾.endswith(("（必填）", "(必填)")):
                必填 = True
                尾 = 尾[: -len("（必填）")].strip() if 尾.endswith("（必填）") else 尾[: -len("(必填)")].strip()
            elif 尾.endswith(("（可选）", "(可选)")) or "默认" in 尾:
                必填 = False
            类型 = 尾.split("，")[0].split(",")[0].strip()
            if 名称:
                出.setdefault(名称, (类型 or None, 必填))
            continue
        括号 = re.match(r"^([^()（）、]+)[（(]([^()）]+)[)）]\s*$", 片段)
        if 括号:
            名称 = 括号.group(1).strip()
            内 = 括号.group(2)
            件 = [项.strip() for 项 in re.split(r"[，,]", 内)]
            类型 = 件[0] or None
            必填 = None
            if any(项 == "必填" for 项 in 件[1:]):
                必填 = True
            elif any(项 in {"可选", "非必填"} for 项 in 件[1:]):
                必填 = False
            if 名称:
                出.setdefault(名称, (类型, 必填))
            continue
    return 出


def _说明书包级版本(头部行: list[str], 全文行: list[str]) -> str | None:
    """包级版本：首个 ``- 版本：X``（在第一个标题之前）或包级表 ``| 版本 | X |``。"""
    for 行 in 头部行:
        匹配 = 版本行.match(行)
        if 匹配:
            return 匹配.group(1)
    for 行 in 全文行:
        格 = _表格行(行)
        if 格 and len(格) >= 2 and 格[0] in {"版本", "包版本"}:
            return 格[1]
    return None


def _段内载位(行列表: list[str]) -> dict:
    """一个能力段落内的字段载位：版本/参数/必填/错误码/返回。

    ``错误码原文`` 是错误码载体的**逐字文本**（既有体例里码后面常跟一句说明，
    如 ``参数不合法（命令不是列表…）``，甚至把码写在句子里）。逐字文本只在**该能力段内**
    参与「码是否出现」判定，不扩到整份文档——那是原来的子串后门。
    """
    载位 = {"版本": None, "参数": {}, "必填": {}, "错误码": set(), "错误码原文": [],
            "返回": set(), "参数载体": False}
    表头: list[str] = []
    for 行 in 行列表:
        匹配 = 版本行.match(行)
        if 匹配 and 载位["版本"] is None:
            载位["版本"] = 匹配.group(1)
            continue
        匹配 = 参数列表行.match(行)
        if 匹配:
            载位["参数载体"] = True
            for 名称, (类型, 必填) in _解析参数散文(匹配.group(1)).items():
                载位["参数"].setdefault(名称, 类型)
                if 必填 is not None:
                    载位["必填"].setdefault(名称, 必填)
            continue
        匹配 = 必填参数行.match(行)
        if 匹配:
            载位["参数载体"] = True
            for 名称 in 匹配.group(1).split(", "):
                名称 = 名称.strip()
                if 名称 and 名称 != "无":
                    载位["必填"][名称] = True
            continue
        匹配 = 错误码行.match(行)
        if 匹配:
            原文 = 匹配.group(1)
            载位["错误码原文"].append(原文)
            for 名称 in 错误码分隔.split(原文):
                名称 = 名称.strip().split("（")[0].split("(")[0].strip()
                if 名称 and 名称 not in {"无", "（无）"}:
                    载位["错误码"].add(名称)
            continue
        for 正则, 键 in ((返回结构行, "返回"), (返回结构粗体行, "返回")):
            匹配 = 正则.match(行)
            if 匹配:
                载位["返回"].update(_返回类型名(匹配.group(1)))
                break
        格 = _表格行(行)
        if 格 is None:
            continue
        if _是表头行(格):
            表头 = 格
            continue
        if 表头 and 表头[0] == "参数" and len(格) >= 3:
            载位["参数载体"] = True
            载位["参数"].setdefault(格[0], 格[1] or None)
            if 格[2] in {"是", "否"}:
                载位["必填"].setdefault(格[0], 格[2] == "是")
            continue
        if 表头 and 表头[0] == "错误码":
            名称 = 格[0].strip().split("（")[0].strip()
            if 名称 and 名称 != "无":
                载位["错误码"].add(名称)
            载位["错误码原文"].append(" ".join(格))
            continue
    return 载位


def 正式类型名集() -> frozenset[str]:
    """16 项正式类型名（唯一事实源 ``公共契约/基础类型/类型表.py:正式类型表``）。"""
    集合 = 读取模块字面量字典(仓库根.joinpath(*正式类型表唯一事实源), 正式类型表变量)
    return frozenset(集合) if isinstance(集合, (set, frozenset, list, tuple)) else frozenset()


def _像类型名(文本: str) -> bool:
    """该文本像不像一个类型名：正式类型表命中，或以「型」结尾（弱一档的兜底形状判据）。"""
    文本 = (文本 or "").strip()
    if not 文本:
        return False
    return 文本 in 正式类型名集() or (文本.endswith("型") and len(文本) <= 8 and " " not in 文本)


def _返回类型名(文本: str) -> set[str]:
    """返回结构描述里的类型名：``{"类型": "结果型", …}`` / ``结果型（…）``。"""
    匹配 = 返回类型紧排.search(文本 or "")
    if 匹配:
        return {匹配.group(1)}
    首位 = re.split(r"[（(（]", (文本 or "").strip())[0].strip().strip("`")
    return {首位} if 首位 else set()


def _解析说明书(文本: str) -> tuple[list[str], list[str], dict[str, list[str]],
                                    dict[str, dict], str]:
    """说明书 → (头部行, 全文行, 段表{能力id: 行列表}, 清单表{能力id: {格, 列}}, 包级错误码原文)。

    ``包级错误码原文`` = 标题里含「错误码」的章节正文（乙支体例把错误码集中写在
    ``## 错误码`` 一节，逐能力不再重复）。它只作**最后一档**错误码载体，见
    ``检查说明书字段``。
    """
    全文行 = 文本.split("\n")
    头部行: list[str] = []
    段表: dict[str, list[str]] = {}
    当前: list[str] | None = None
    for 行 in 全文行:
        匹配 = 标题行.match(行)
        if 匹配:
            名称 = 匹配.group(2)
            当前 = 段表.setdefault(名称, [])
            continue
        if 当前 is None:
            头部行.append(行)
        else:
            当前.append(行)
    # 段表按「标题里含能力 id」建索引；清单表按「行首格是能力 id」建索引
    # （清单表是乙支说明书的字段载体：能力清单一行就是一条能力的结构化描述）。
    索引段: dict[str, list[str]] = {}
    清单表: dict[str, dict] = {}
    清单列: list[str] = []
    for 标题, 行列表 in 段表.items():
        for 标识 in 能力id形.findall(标题):
            索引段.setdefault(标识, 行列表)
        for 标识 in 能力id形.findall(" ".join(行列表[:2])):
            索引段.setdefault(标识, 行列表)
    for 行 in 全文行:
        格 = _表格行(行)
        if not 格:
            continue
        if "能力id" in 格:
            清单列 = 格
            continue
        if _清单形(格):
            清单表.setdefault(格[0].strip("`"), {"格": 格, "列": list(清单列)})
    包级错误码原文 = "\n".join(
         "\n".join(行列表) for 标题, 行列表 in 段表.items() if "错误码" in 标题)
    return 头部行, 全文行, 索引段, 清单表, 包级错误码原文


def _清单载位(清单条目: dict | None) -> dict:
    """能力清单表行 → 载位（版本/返回/参数），只认列名，不猜列位。"""
    载位 = {"版本": None, "参数": {}, "必填": {}, "错误码": set(), "错误码原文": [],
            "返回": set(), "参数载体": False}
    if not 清单条目:
        return 载位
    格, 列 = 清单条目["格"], 清单条目["列"]
    for 位置, 列名 in enumerate(列):
        if 位置 >= len(格) or not 列名:
            continue
        值 = 格[位置].strip()
        if 列名 in {"版本", "能力版本"}:
            载位["版本"] = 值 or None
        elif 列名 in {"返回", "返回结构"}:
            载位["返回"].update(_返回类型名(值))
        elif 列名 in {"参数", "入参", "参数列表"}:
            参数 = _解析参数散文(值)
            if 参数:
                载位["参数载体"] = True
                for 名称, (类型, 必填) in 参数.items():
                    载位["参数"].setdefault(名称, 类型)
                    if 必填 is not None:
                        载位["必填"].setdefault(名称, 必填)
        elif 列名 in {"错误码"}:
            载位["错误码"].update(码.strip() for 码 in re.split(r"[，,、]", 值) if 码.strip())
    return 载位


def 期望能力字段(包目录: Path, 声明: dict) -> dict[str, dict]:
    """声明侧的字段基准：``能力定义.json`` → ``参数契约.json`` → ``包声明.json`` 兜底。

    为什么以 ``能力定义.json`` 为主：它是平台唯一的能力声明面（``包声明.json`` 与
    各包 ``参数契约.json`` 都是它的编译产物），包内说明书亦自称「唯一口径 = 能力定义.json」
    （见 ``支持库/后端/组件规范支持库/说明/使用说明.md``）。三级兜底保证"声明侧有值"
    就一定会被说明书对账，不因某级缺失而静默放过。
    """
    定义 = 读取json带诊断(包目录 / "能力定义.json")[0]
    契约 = 读取json带诊断(包目录 / "能力契约" / "参数契约.json")[0]
    定义表 = {}
    if isinstance(定义, dict):
        for 条 in 定义.get("能力列表") or []:
            if isinstance(条, dict) and 条.get("能力id"):
                定义表[条["能力id"]] = 条
    契约表 = {}
    if isinstance(契约, dict):
        for 条 in 契约.get("能力契约") or []:
            if isinstance(条, dict) and 条.get("能力id"):
                契约表[条["能力id"]] = 条
    出: dict[str, dict] = {}
    for 能力 in 声明.get("能力") or []:
        if not isinstance(能力, dict):
            continue
        能力id = 能力.get("能力id")
        if not 能力id:
            continue
        定义条 = 定义表.get(能力id) or {}
        契约条 = 契约表.get(能力id) or {}
        参数源 = None
        来源 = ""
        for 候选, 名 in ((定义条.get("参数"), "能力定义"), (契约条.get("参数"), "参数契约"),
                        (能力.get("参数"), "包声明")):
            if isinstance(候选, list) and 候选:
                参数源, 来源 = 候选, 名
                break
        参数 = {}
        for 项 in 参数源 or []:
            if isinstance(项, dict) and 项.get("名称"):
                参数[项["名称"]] = (项.get("类型") or None, bool(项.get("必填", True)))
        错误码 = set()
        for 候选 in (定义条.get("错误码"), 契约条.get("错误码"), 能力.get("错误码")):
            if isinstance(候选, list) and 候选:
                # 「无」是声明侧的占位写法（``系统信息`` 的能力就写着 ``["无"]``），
                # 它不是错误码：说明书按约定把它读成「没有错误码」，两边都不该出条目。
                错误码 = {码 for 码 in 候选
                       if isinstance(码, str) and 码 and 码 != "无"}
                break
        返回条 = 定义条.get("返回") or 契约条.get("返回") or 能力.get("返回")
        返回类型 = None
        if isinstance(返回条, dict) and isinstance(返回条.get("类型"), str):
            返回类型 = 返回条["类型"]
        elif isinstance(返回条, str) and 返回条:
            返回类型 = 返回条.split("（")[0].strip()
        版本 = 定义条.get("版本") or 契约条.get("版本") or 声明.get("版本")
        出[能力id] = {"版本": 版本, "参数": 参数, "错误码": 错误码,
                     "返回类型": 返回类型, "参数来源": 来源}
    return 出


def 检查说明书字段(包目录: Path, 声明: dict) -> list[dict]:
    """逐能力对账说明书的结构化字段（版本/参数/必填/错误码/返回），返回违规清单。

    判据一律 **只在声明侧有值时**成立（声明侧没这个值 → 没有可比项，不是豁免）；
    声明侧有值而说明书无载位/不一致 → 出条目。文件缺失由既有「说明书-使用说明.md缺失」
    负责，本函数不重复出条目。
    """
    说明路径 = 包目录.joinpath(*说明书相对路径)
    if not 说明路径.is_file():
        return []
    说明文本 = 说明路径.read_text(encoding="utf-8")
    头部行, 全文行, 段表, 清单表, 包级错误码原文 = _解析说明书(说明文本)
    期望表 = 期望能力字段(包目录, 声明)
    if not 期望表:
        return []
    包id = 声明.get("包id") or 包目录.name
    违规: list[dict] = []

    def _记(缺口类型: str, 能力id: str, 详情: str = "") -> None:
        违规.append({"能力id": 能力id, "包": 包id, "缺口类型": 缺口类型,
                    "路径": str(说明路径), "详情": 详情})

    包级版本 = _说明书包级版本(头部行, 全文行)
    声明包版本 = 声明.get("版本")
    if isinstance(声明包版本, str) and 声明包版本:
        if 包级版本 is None:
            _记("说明书-缺包级版本载位", "*")
        elif 包级版本 != 声明包版本:
            _记("说明书-包级版本不一致", "*", f"{包级版本} ← {声明包版本}")
    for 能力id, 期望 in 期望表.items():
        段 = 段表.get(能力id)
        清单载位 = _清单载位(清单表.get(能力id))
        if 段 is None and not 清单表.get(能力id):
            _记("说明书-缺能力段", 能力id)
            continue
        载位 = _段内载位(段 or [])
        版本 = 载位["版本"] or 清单载位["版本"]
        if 期望["版本"]:
            if 版本 is None:
                _记("说明书-缺能力级版本载位", 能力id)
            elif 版本 != 期望["版本"]:
                _记("说明书-能力级版本不一致", 能力id, f"{版本} ← {期望['版本']}")
        if 期望["参数"]:
            参数 = dict(载位["参数"]) if 载位["参数载体"] else {}
            if not 参数:
                参数 = dict(清单载位["参数"])
            if not 参数:
                _记("说明书-缺参数载位", 能力id, f"声明侧 {len(期望['参数'])} 个参数")
            else:
                for 名称, (类型, 必填) in 期望["参数"].items():
                    if 名称 not in 参数:
                        _记("说明书-缺参数", 能力id, 名称)
                        continue
                    实际类型 = 参数.get(名称)
                    if 类型 and 实际类型 and 实际类型 != 类型:
                        _记("说明书-参数类型不一致", 能力id, f"{名称} {实际类型} ← {类型}")
                    if 名称 in 载位["必填"] and 载位["必填"][名称] != 必填:
                        _记("说明书-必填不一致", 能力id, f"{名称} {载位['必填'][名称]} ← {必填}")
                for 名称 in 参数:
                    if 名称 not in 期望["参数"]:
                        _记("说明书-多参数", 能力id, 名称)
        if 期望["错误码"]:
            段错误码 = set(载位["错误码"]) | set(清单载位["错误码"])
            原文 = "\n".join(载位["错误码原文"] + 清单载位["错误码原文"])
            for 码 in sorted(期望["错误码"]):
                if 码 not in 段错误码 and 码 not in 原文 and 码 not in 包级错误码原文:
                    # 三档载体，逐档变弱但都在判：① 能力段内候选集合 → ② 能力段内
                    # 错误码行/表逐字原文（既有体例把码写在句子里、或码后带说明）
                    # → ③ 包级「错误码」章节正文（乙支体例把码集中写在包级一节，
                    # 逐能力不再重复；这一档没有能力级映射，是已知强度折让）。
                    _记("说明书-缺错误码", 能力id, 码)
        if 期望["返回类型"]:
            段返回 = set(载位["返回"]) | set(清单载位["返回"])
            if not 段返回:
                _记("说明书-缺返回载位", 能力id, 期望["返回类型"])
            elif 期望["返回类型"] not in 段返回 and any(_像类型名(名) for 名 in 段返回):
                _记("说明书-返回类型不一致", 能力id,
                    f"{'、'.join(sorted(段返回))} ← {期望['返回类型']}")
            elif 期望["返回类型"] not in 段返回:
                # 载位里写的不是类型名（例如乙支清单表把「值结构」正文写进返回列）：
                # 口径是**没有可比的返回类型名**，不是「写错了类型」。
                _记("说明书-缺返回载位", 能力id, 期望["返回类型"])
    return 违规


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
    # E-3：说明书结构化字段对账（版本/参数/必填/错误码/返回）。
    # 修前六环只查「说明书存在 + 能力名/能力id 子串」，字段级漂移整段漏检。
    if 说明书 is not None:
        违规.extend(检查说明书字段(包目录, 声明))
    return 违规


def 检查全局(包能力表: list[tuple[str, str, str]],
            视图包id集: set[str] | frozenset[str] = frozenset()) -> list[dict]:
    """跨包检查：只查能力 id 全局唯一，豁免中文名重复。

    华哥裁决（2026-08-27）：能力 id 是全局唯一标识（硬约束），中文名是
    显示层，模块库门面组合支持库、多后端提供者、通用能力名都可以同名。

    2026-09-17：判定**不再依赖「是否进 包能力表」这一个条件** —— ``运行门禁``
    把**所有**包声明（含聚合父包）的能力 id 都送进来。聚合父包是视图，它对子包能力的
    重声明按 owner 口径去重：同一 id 同时出现在聚合父包与子包声明时，owner 取带
    ``能力定义.json`` 的子包（与 ``正式包索引``／``能力索引`` 的既有去重口径一致），
    不构成第二个 owner。这样「塞一个占位子包把整包移出全局检查」这条路不再成立。
    """
    非视图声明id集 = {能力id for 包id, 能力id, _名称 in 包能力表
                if 能力id and 包id not in 视图包id集}
    额外: list[dict] = []
    id表: dict[str, set[str]] = {}
    for 包id, 能力id, 名称 in 包能力表:
        if not 能力id:
            continue
        if 包id in 视图包id集 and 能力id in 非视图声明id集:
            continue
        id表.setdefault(能力id, set()).add(包id)
    for 能力id, 包们 in id表.items():
        if len(包们) > 1:
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


def 默认存量基线路径() -> Path:
    """存量基线的落点：与本模块同目录（``开发工具/公开调用完整性门禁存量基线.json``）。"""
    return Path(__file__).resolve().with_name(公开调用存量基线文件名)


def 读取存量基线(路径: Path | None) -> dict[str, int] | None:
    """读存量基线 ``{包|缺口类型: 允许条数}``；读不成返回 ``None``（= 不豁免任何条目）。"""
    if 路径 is None or not Path(路径).is_file():
        return None
    try:
        数据 = json.loads(Path(路径).read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, UnicodeDecodeError):
        return None
    if not isinstance(数据, dict):
        return None
    条目 = 数据.get("条目")
    if not isinstance(条目, dict):
        return None
    出: dict[str, int] = {}
    for 键, 值 in 条目.items():
        if isinstance(键, str) and isinstance(值, int) and 值 >= 0:
            出[键] = 值
    return 出


def 分桶(条目: dict, 根: Path) -> str:
    """存量基线的桶键：``包相对路径|缺口类型``（包按相对路径，而不是包id：
    包id 与目录不一致时仍能定位到人可复核的位置）。"""
    包 = str(条目.get("包") or "")
    路径 = Path(str(条目.get("路径") or ""))
    try:
        相对 = 路径.parent.parent if 路径.name == "使用说明.md" else 路径.parent
        包 = str(相对.resolve().relative_to(根.resolve()).as_posix())
    except (ValueError, OSError):
        pass
    return f"{包}|{条目.get('缺口类型')}"


def 应用存量基线(违规: list[dict], 根: Path,
                 基线文件: Path | None = None) -> tuple[list[dict], list[dict], list[dict]]:
    """按「包×缺口类型」分桶消费存量基线，返回 ``(新增, 存量, 收敛)``。

    **只减不增**：桶在基线内且计数 ≤ 基线值 → 存量（只报，不进违规）；计数 > 基线值
    或桶不在基线里 → 新增（判红）。桶计数 < 基线值 → 收敛提示（存量已好转，应下调）。

    基线读不成（缺失/坏 JSON/形状非法）⇒ 基线为空 ⇒ **全部条目都算新增**（fail-closed：
    不做静默豁免）。基线只在 ``根`` 是本模块所在仓库时自动生效（夹具根不吃基线，
    否则新判据在夹具上永远测不出来）。
    """
    桶: dict[str, list[dict]] = {}
    for 条 in 违规:
        桶.setdefault(分桶(条, 根), []).append(条)
    基线 = 读取存量基线(基线文件)
    if 基线 is None:
        基线 = {}
    新增: list[dict] = []
    存量: list[dict] = []
    收敛: list[dict] = []
    for 键, 条们 in 桶.items():
        上限 = 基线.get(键, 0)
        if len(条们) > 上限:
            新增.extend(条们[上限:])
        存量.extend(条们[:上限])
        if len(条们) < 上限:
            收敛.append({"桶": 键, "当前": len(条们), "基线": 上限})
    return 新增, 存量, 收敛


def 运行门禁(根: Path, 基线文件: Path | None = None) -> list[dict]:
    """扫描根目录下全部包，返回六环、说明书字段、全局检查与错误码登记的**新增**违规清单。

    ``找全部包目录`` 覆盖到聚合父包：它**照样参与全局唯一性判定**（其重声明按
    owner 口径去重），只是不参与六环。跳过六环 ≠ 跳出唯一性检查 —— 这正是
    2026-09-17 修掉的漏洞边界。

    E-2 两条：
    - **扫描面为空判红**：``六环扫描根`` 读不成事实源、或事实源里一个包声明都扫不到，
      都出 ``六环-扫描面为空`` 条目。空集不是通过，是「这份切片被判据整块漏过」。
    - **owner 表仍按适配层 Provider 豁免**：``支持库/适配层`` 的提供者可以声明内部
      实现能力，但不进 ``包能力表``（不参与公开 owner 冲突统计）。六环文件面（六件套）
      与 owner 面是两件事：E-2 扩的是文件面，owner 口径不变。

    存量消费：``基线文件`` 传 None 且 ``根`` 是本模块所在仓库时，自动取
    ``默认存量基线路径()``（发布门禁与直跑同一份基线）；夹具根不自动吃基线。
    存量项由 ``运行门禁并分诊`` 出（只报不拦），本函数只返回**新增**。
    """
    return 运行门禁并分诊(根, 基线文件)[0]


def 运行门禁并分诊(根: Path, 基线文件: Path | None = None) -> tuple[list[dict], list[dict], list[dict]]:
    """``(新增, 存量, 收敛)`` 三态返回：``运行门禁`` 只是它的「新增」一栏。

    存量项**不进**违规清单（只报不拦）；收敛项是「桶计数低于基线」的提示，
    提醒把基线往下调（只减不增的正常方向）。
    """
    根 = Path(根)
    if 基线文件 is None and 根.resolve() == 仓库根.resolve():
        基线文件 = 默认存量基线路径()
    原始 = 检查门禁原始项(根)
    if 基线文件 is None:
        return 原始, [], []
    return 应用存量基线(原始, 根, 基线文件)


def 检查门禁原始项(根: Path) -> list[dict]:
    """不做存量消费的原始违规清单（六环 + 说明书字段 + 全局 + 错误码登记）。

    与 ``运行门禁`` 分开是刻意的：**基线只能在这之后扣减**，否则「基线里有的桶」
    就再也没法被复算出来了（存量只报与新增判红必须同源可比）。
    """
    违规: list[dict] = []
    根 = Path(根)
    扫描根列表 = 六环扫描根(根)
    包目录们 = 找全部包目录(根)
    if not 扫描根列表 or not 包目录们:
        违规.append({"能力id": "*", "包": "全仓", "缺口类型": "六环-扫描面为空",
                    "路径": str(根.joinpath(*正式根唯一事实源)),
                    "详情": f"扫描根={list(扫描根列表)} 包声明数={len(包目录们)}"})
    包能力表: list[tuple[str, str, str]] = []
    视图包id集: set[str] = set()
    for 包目录 in 包目录们:
        声明值, 声明诊断 = 读取json带诊断(包目录 / "包声明.json")
        声明 = 声明值 if isinstance(声明值, dict) else {}
        包id = 声明.get("包id") or 包目录.name
        if 声明诊断 is None and _是聚合父包(包目录, 声明):
            # 声明读不成时绝不判视图：那等于用一次读取故障换一张整包豁免。
            视图包id集.add(包id)
        else:
            违规.extend(检查包(包目录))
        # 不可读的包声明由 检查包 单独出「不可读」条目；这里既不重复出条目，
        # 也不把不可读静默当成「无能力」进包能力表（那会让全局重复提供者检查
        # 对整包失效，等于用一次读取故障换一片检查盲区）。
        if 声明诊断 is not None:
            continue
        if _是适配层(包目录):
            # 适配层 Provider：六环文件面照查（E-2），owner 面仍豁免（既有口径）。
            continue
        包能力表.extend((包id, 能力.get("能力id") or "", 能力.get("名称") or "")
                     for 能力 in 声明.get("能力") or [])
    违规.extend(检查全局(包能力表, 视图包id集))
    违规.extend(检查错误码登记(根))
    return 违规


def 主程序() -> int:
    根 = Path(sys.argv[1]) if len(sys.argv) > 1 else 仓库根
    违规, 存量, 收敛 = 运行门禁并分诊(根)
    if 存量:
        计数: dict[str, int] = {}
        for 条 in 存量:
            键 = 分桶(条, 根)
            计数[键] = 计数.get(键, 0) + 1
        print(f"存量基线（只报不拦，只减不增）：共 {len(存量)} 项")
        for 键, 数 in sorted(计数.items()):
            print(f"  [存量] {键} × {数}")
    for 条 in 收敛:
        print(f"  [可收敛] {条['桶']}: 当前 {条['当前']} < 基线 {条['基线']}（应下调基线）")
    if not 违规:
        print("公开调用完整性门禁通过：六环一致 + 说明书字段一致 + 错误码登记环一致，无新增违规")
        return 0
    print(f"公开调用完整性门禁失败：共 {len(违规)} 项新增违规（六环缺口+说明书字段+重复提供者+错误码登记）")
    for 条 in 违规:
        尾 = f" 错误码={条['错误码']}" if 条.get("错误码") else ""
        详情 = f" 详情={条['详情']}" if 条.get("详情") else ""
        print(f"[{条['缺口类型']}] 能力id={条['能力id']} 包={条['包']} 路径={条['路径']}{尾}{详情}")
    return 1


if __name__ == "__main__":
    sys.exit(主程序())
