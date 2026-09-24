"""验证门禁一「同动作双路径检测」——只读检查器，堵住审计件《重复腿与旁路》覆盖矩阵认定的缺口 1。

## 为什么需要它（现有门禁为什么盖不住）

现场证据（审计件 `开发文档/分析/审计_重复腿与旁路_20260919.md` §4.1/§4.3）：

- `开发工具/复用审计/能力调用图审计.py` 扫描面**只有 `模块库/`**（`:298` 默认 `系统根/"模块库"`），
  判的是「是否越界 import / 是否复制原子实现」，**不判「同一个动作有几处实现」**；
- `运行核心/依赖防火墙.py` 只看 **import 方向**，同一个动作写成两份、两份各自 import 合法，
  它天然看不见（实测全绿：769 文件 / 0 违规）；
- `开发工具/公开调用完整性门禁.py` 判「六环一致性」，**不读调用点**；
- `开发工具/发布门禁/运行发布门禁.py` 的四条防回潮项（裸布尔/非正式类型名/英文错误码/占位代称）
  判的是**词法与命名形态**，与「实现腿条数」正交。

于是审计件 I-5 那类形态（同一个「读取能力契约」动作，A 处走唯一能力腿、B 处自己 rglob 扫声明文件）
在现有全部门禁里都是绿的。本检查器就在**「同一动作有几条实现路径」**这个正交维度上补一条判据。

## 判据（四条规则，全部只读 AST / 正则，不改任何文件）

- **规则 模块公开第二入口**：`模块库/<包>/__init__.py` 的 `__all__` 里出现 `设置HTTP连接器`
  → 模块公开面出现了一条「非能力 id 的对外调用入口」（哲学 7.4 明禁第二入口）。审计件 I-6。
- **规则 模块库跨包同名公开调用腿**：`模块库/` 下**不同包**出现同名同签名的公开函数
  → 跨包的第二条调用路径。`注册能力`（每包装配入口，平台约定）与 `设置HTTP连接器`
  （规则一已判，避免同一行两个结论）进基线，其余新出现即判红。
- **规则 同一动作两处配置表**：同名模块级表（名字以「表/映射」结尾）在两份**不同文件**里
  且**取值交叠 ≥2 条并覆盖较小一份的 50% 以上** → 同一动作的映射被各写一份（1.2「同一件事存在
  两套以上实现」）。实测命中：`稳定操作表`（`平台控制面/统一入口/核心.py:56` 与
  `开发工具/契约编译/消费者契约.py:17` 交叠 12/12）。
  ★ `敏感关键词表`（3 处交叠 9/9）**已于 2026-09-23 收口**（原债务行已随 2026-09-23 收口销账删除；开工
  `开工-20260923-115153-6dc8`）：五份互不覆盖的敏感键名表并成唯一腿
  `公共契约/基础类型/字段名册.py::敏感键名表`，其余四处转调 `是敏感键名`；
  对应基线条目已从 `存量基线.json` 下调（`只减不增`），故本规则不再命中它。
- **规则 同一动作的声明面扫描点**：同一份源码里存在 ≥2 处「带同一响应类型标记的声明文件扫描点」
  且都不是薄转调 → 同一个「读声明」动作有两条腿。实测命中 `开发工具/开发入口.py:50`
  （`rglob("能力契约/*.json")`，与 `模块库/能力目录.读取能力` 是同一个动作两条路）。

## 覆盖不了什么（如实声明，不假装覆盖）

- 判据是**静态**的：不证明「两条腿在生产路径上都会被走到」；
- 名字相同而动作确实不同的两处（如两个互不相关的通用工具函数）会命中 —— 这类
  由基线冻结承接（门禁绿 = 「没有新的第二腿」，不等于「存量已收口」）；
- 判不了「同一个动作写在两个文件里但函数名与表名都不同」的形态（需语义级判据，本项目暂无）。
"""

from __future__ import annotations

import ast
import json
import os
import sys
from pathlib import Path

if __name__ == "__main__" or __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from 公共契约.基础类型.逻辑类型 import 假, 真  # noqa: E402
from 公共契约.运行时.平台适配 import 清只读后删除树  # noqa: E402
from 开发工具.验证门禁.门禁公共 import (  # noqa: E402
    收集源码,
    新建夹具根,
    检查结论,
    命中,
    墙钟上限秒,
)

检查器名 = "同动作双路径检测"

#: 判据自指段：下面 `判据表` 的取值里必然出现被扫的常量字样（它是判据本身）。扫描时整段跳过，
#: 并在结论里上报豁免条数 —— 跳过面必须可见，不得静默当通过（照
#: `开发工具/发布门禁/运行发布门禁.py::校验占位代称防回潮` 的自指段口径）。
#:
#: 模块库装配入口「注册能力」：每个模块包都必须导出它（`模块库/*/__init__.py`，实测 143 处），
#: 平台既定装配契约，不是第二腿。
#:
#: 模块公开第二入口目标符号与判据表列名（`设置HTTP连接器` / 取值表 / 判据表）：
#: 判据自身必须能提到它们，否则写不出来。
模块装配入口名 = "注册能力"
公开第二入口名 = "设置HTTP连接器"
禁用库 = "禁用库"
扫描点响应标记 = "响应类型标记"

规则一 = "模块公开第二入口"
规则二 = "模块库跨包同名公开调用腿"
规则三 = "同一动作两处配置表"
规则四 = "同一文件两条声明面自建腿"
规则五 = "自建契约读取腿未收口唯一腿"
规则六 = "手写 markdown 语法解析（重复既有原子能力）"

#: markdown 语法解析的唯一腿（2026-09-11 下沉，提交 abd651f1）。唯一腿本体不判。
markdown语法唯一腿 = "支持库/后端/办公文档支持库/轻量文本解析"

#: 模块装配入口 `注册能力` 之外，仍属平台既定约定、不判第二腿的模块公开符号。
模块公开约定符号表 = frozenset({模块装配入口名})


#: 声明面扫描文件名（判据四）。
声明文件模式 = ("参数契约.json", "能力契约", "包声明.json", "能力定义.json")

#: 判据四的契约字段标记：命中 ≥3 个才说明这段代码的产出是「能力契约记录」。
契约字段标记 = ("参数", "返回", "错误码", "能力id")

#: 判据四的契约字段标记下限：命中 ≥3 个才说明这段代码的产出是「能力契约记录」。
契约字段下限 = 3

#: 唯一能力腿的调用痕迹：函数体里出现任一项即视为「已收口到唯一腿」，
#: 不再判第二腿（哲学 1.3「结果唯一即收口」——转调是把实现收口成一条腿的正解）。
唯一腿痕迹 = ("能力目录.读取能力", "读取能力", "调用唯一检索能力", "搜索公开能力")

#: 薄转调判据：函数体去掉 docstring 后只剩一个 return / 一个表达式，即「转调型」。
#: 转调型不判第二腿（哲学 1.3：结果唯一即收口，转调是把实现收口到唯一腿的正解）。
def _是薄转调(节点: ast.AST) -> bool:
    语句 = [
        项
        for 项 in getattr(节点, "body", [])
        if not (isinstance(项, ast.Expr) and isinstance(项.value, ast.Constant))
    ]
    if len(语句) != 1:
        return 假
    return isinstance(语句[0], (ast.Return, ast.Expr)) and getattr(语句[0], "value", None) is not None


def _常量集合(值: ast.AST) -> frozenset | None:
    """把模块级表/映射字面量折成取值集合；折不动（含变量引用）返回 None。"""
    if isinstance(值, ast.Dict):
        return frozenset(键.value for 键 in 值.keys if isinstance(键, ast.Constant))
    if isinstance(值, (ast.List, ast.Set, ast.Tuple, ast.Dict)):
        集 = set()
        for 元素 in 值.elts if hasattr(值, "elts") else []:
            try:
                集.add(ast.literal_eval(元素))
            except (ValueError, TypeError, SyntaxError):
                集.add(ast.unparse(元素))
        return frozenset(集)
    return None


def _规则一模块公开第二入口(根: Path, 结论: 检查结论) -> None:
    """`模块库/<包>/__init__.py` 的 `__all__` 含第二入口符号 → 命中。"""
    模块根 = 根 / "模块库"
    if not 模块根.is_dir():
        结论.扫描面[规则一] = 0
        return
    # 判据自指段：本判据的常量定义与说明里必然出现被扫字样，跳过面必须可见。
    self_text = Path(__file__).read_text(encoding="utf-8")
    自指条数 = sum(1 for 行 in self_text.splitlines() if 公开第二入口名 in 行)
    结论.跳过面["判据自指段（本文件内出现被扫字样的行）"] = 自指条数
    计数 = 0
    for 入口 in sorted(模块根.glob("*/__init__.py")):
        计数 += 1
        try:
            树 = ast.parse(入口.read_text(encoding="utf-8"))
        except (OSError, SyntaxError, UnicodeDecodeError):
            结论.不可解析.append(f"{入口.relative_to(根).as_posix()}: 读不成/语法错")
            continue
        for 节点 in 树.body:
            if not isinstance(节点, ast.Assign) or not any(
                getattr(目标, "id", "") == "__all__" for 目标 in 节点.targets
            ):
                continue
            if not isinstance(节点.value, (ast.List, ast.Tuple)):
                continue
            导出 = [元素.value for 元素 in 节点.value.elts if isinstance(元素, ast.Constant)]
            if 公开第二入口名 in 导出:
                结论.命中列表.append(
                    命中(规则一, 入口.relative_to(根).as_posix(), 节点.lineno,
                         f"{公开第二入口名} 出现在 __all__（模块对外多出一条非能力 id 的调用入口）")
                )
    结论.扫描面[规则一] = 计数


def _规则二模块库跨包同名公开调用腿(根: Path, 结论: 检查结论) -> None:
    """`模块库/` 不同包出现同名同签名公开函数 → 跨包第二调用腿。"""
    模块根 = 根 / "模块库"
    组: dict[tuple[str, tuple[str, ...]], list[tuple[str, int, str]]] = {}
    文件数 = 0
    if 模块根.is_dir():
        for 源码 in sorted(模块根.rglob("*.py")):
            if "__pycache__" in 源码.parts:
                continue
            文件数 += 1
            树 = _解析(源码, 结论, 根)
            if 树 is None:
                continue
            段 = 源码.relative_to(根).parts
            包名 = 段[1] if len(段) > 1 else ""
            for 节点 in 树.body:
                if isinstance(节点, (ast.FunctionDef, ast.AsyncFunctionDef)) and not 节点.name.startswith("_"):
                    签名 = tuple(参数.arg for 参数 in 节点.args.args)
                    组.setdefault((节点.name, 签名), []).append(
                        (源码.relative_to(根).as_posix(), 节点.lineno, 包名)
                    )
    结论.扫描面[规则二] = 文件数
    for (名字, 签名), 出现表 in sorted(组.items()):
        if 名字 in 模块公开约定符号表:
            continue  # 装配入口，由约定承接（登记在判据自指段说明里）
        if len({包 for _, _, 包 in 出现表}) < 2:
            continue
        for 文件, 行号, 包 in 出现表:
            结论.命中列表.append(
                命中(规则二, 文件, 行号,
                     f"公开函数 {名字}{签名} 在 {len(出现表)} 个包各有一份（跨包第二调用腿）")
            )


def _规则三同一动作两处配置表(根: Path, 结论: 检查结论) -> None:
    """同名模块级表在两份文件里取值高度交叠 → 同一动作两处实现。"""
    组: dict[str, list[tuple[str, int, frozenset]]] = {}
    文件数 = 0
    for 源码 in 收集源码(根):
        文件数 += 1
        树 = _解析(源码, 结论, 根)
        if 树 is None:
            continue
        for 节点 in 树.body:
            if not isinstance(节点, (ast.Assign, ast.AnnAssign)):
                continue
            目标 = 节点.targets[0] if isinstance(节点, ast.Assign) else 节点.target
            名字 = getattr(目标, "id", None)
            if not 名字 or not (名字.endswith("表") or 名字.endswith("映射")):
                continue
            取值 = _常量集合(节点.value) if 节点.value is not None else None
            if not 取值:
                continue
            组.setdefault(名字, []).append(
                (源码.relative_to(根).as_posix(), 节点.lineno, 取值)
            )
    结论.扫描面[规则三] = 文件数
    已报: set[tuple[str, str]] = set()
    for 名字, 出现表 in sorted(组.items()):
        if len(出现表) < 2:
            continue
        for 序号, 左 in enumerate(出现表):
            for 右 in 出现表[序号 + 1:]:
                if 左[0] == 右[0]:
                    continue
                较小 = min(len(左[2]), len(右[2]))
                if 较小 < 2:
                    continue
                交叠 = 左[2] & 右[2]
                if len(交叠) < 2 or len(交叠) < 0.5 * 较小:
                    continue
                for 文件, 行号 in ((左[0], 左[1]), (右[0], 右[1])):
                    键 = (文件, f"{名字}#{行号}")
                    if 键 in 已报:
                        continue
                    已报.add(键)
                    结论.命中列表.append(
                        命中(规则三, 文件, 行号,
                             f"表 {名字} 与另一处交叠 {len(交叠)}/{较小} 条（同一动作两处实现）")
                    )


def _契约读取腿扫描(根: Path, 结论: 检查结论) -> None:
    """扫出「自建契约读取腿」并判两条规则。

    **一条腿**的定义（三条同时成立，缺一不算）：
    ① 函数体内有声明面扫描动作（`rglob/glob/iglob/walk` 且实参含声明文件名）；
    ② 该函数**自己的源码段**里带 ≥ `契约字段下限` 个契约字段标记（说明它的产出是「能力契约记录」，
       不是顺带扫一下目录）。用函数段而非整文件，是因为实测整文件口径会把
       3200 行的门禁文件整体算进来，把合法代码误报成腿；
    ③ 函数体内**没有**唯一腿痕迹（`能力目录.读取能力` 等）—— 已收口到唯一腿的实现不算腿
       （哲学 1.3「结果唯一即收口」）。

    判据四 = 同一文件 ≥2 条自建腿；判据五 = 任一文件存在自建腿（登记用，
    **每条都要求收口到 `模块库/能力目录.读取能力`**，审计件 I-5 的最小改法落点）。
    """
    扫描文件数 = 0
    多腿文件数 = 0
    有腿文件数 = 0
    for 源码 in 收集源码(根):
        扫描文件数 += 1
        树 = _解析(源码, 结论, 根)
        if 树 is None:
            continue
        函数表 = [
            节点
            for 节点 in ast.walk(树)
            if isinstance(节点, (ast.FunctionDef, ast.AsyncFunctionDef))
        ]

        def _范围(函数: ast.AST) -> tuple[int, int]:
            行号表 = [子.lineno for 子 in ast.walk(函数) if hasattr(子, "lineno")]
            return min(行号表, default=函数.lineno), max(行号表, default=函数.lineno)

        范围表 = {函数.name: _范围(函数) for 函数 in 函数表}
        扫描点: dict[str, list[int]] = {}
        for 节点 in ast.walk(树):
            if not isinstance(节点, ast.Call) or not isinstance(节点.func, ast.Attribute):
                continue
            if 节点.func.attr not in ("rglob", "glob", "iglob", "walk"):
                continue
            实参 = [
                参
                for 参 in 节点.args
                if isinstance(参, ast.Constant) and isinstance(参.value, str)
            ]
            if not any(模式 in 参.value for 参 in 实参 for 模式 in 声明文件模式):
                continue
            所属 = ""
            for 名字, (起点, 终点) in 范围表.items():
                if 起点 <= 节点.lineno <= 终点:
                    所属 = 名字
            if 所属:
                扫描点.setdefault(所属, []).append(节点.lineno)
        if not 扫描点:
            continue
        文本 = 源码.read_text(encoding="utf-8").splitlines()

        def _函数段(名字: str) -> str:
            起点, 终点 = 范围表[名字]
            return "\n".join(文本[起点 - 1: 终点])

        自建腿 = {
            名字: 标记数
            for 名字 in 扫描点
            for 标记数 in (
                sum(1 for 标记 in 契约字段标记 if 标记 in _函数段(名字)),
            )
            if 标记数 >= 契约字段下限
            and not any(痕迹 in _函数段(名字) for 痕迹 in 唯一腿痕迹)
        }
        if not 自建腿:
            continue
        有腿文件数 += 1
        相对 = 源码.relative_to(根).as_posix()
        for 名字, 标记数 in sorted(自建腿.items(), key=lambda 项: min(扫描点[项[0]])):
            for 行号 in 扫描点[名字]:
                结论.命中列表.append(
                    命中(规则五, 相对, 行号,
                         f"函数 {名字} 自建契约读取腿（契约字段标记 {标记数} 个），"
                         f"未转调 模块库/能力目录.读取能力")
                )
        if len(自建腿) >= 2:
            多腿文件数 += 1
            for 名字 in sorted(自建腿, key=lambda 项: min(扫描点[项])):
                结论.命中列表.append(
                    命中(规则四, 相对, min(扫描点[名字]),
                         f"同一文件内 {len(自建腿)} 条自建契约读取腿"
                         f"（{名字} 等）各扫一遍声明面 = 同一动作两条路")
                )
    # 扫描面 = **实际解析过的文件数**（这一项才承担「空转即杀」判据）。
    # 有腿文件数 / 多腿文件数 属「扫描结果」，写进下方跳过面统计里显式可见，
    # 不冒充扫描面：否则「本次没扫到腿」会被当成「没扫过」，把干净的绿色判成红
    # （2026-09-19 实测：夹具根里没有腿，扫描面记 0 → 自证第一拍被误判为红）。
    结论.扫描面[规则四] = 扫描文件数
    结论.扫描面[规则五] = 扫描文件数
    结论.跳过面[f"{规则五}：有自建腿的文件数"] = 有腿文件数
    结论.跳过面[f"{规则四}：同一文件两条自建腿的文件数"] = 多腿文件数


def _解析(路径: Path, 结论: 检查结论, 根: Path) -> ast.Module | None:
    try:
        源码 = 路径.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as 错误:
        结论.不可解析.append(f"{路径.relative_to(根).as_posix()}: {type(错误).__name__}")
        return None
    try:
        return ast.parse(源码)
    except SyntaxError as 错误:
        结论.不可解析.append(f"{路径.relative_to(根).as_posix()}: 语法错误 行{错误.lineno}")
        return None


def _正则字面量(节点: ast.AST) -> str | None:
    """从 `re.compile(<常量>)` / `re.match(<常量>, …)` 取正则字面量文本；取不到返回 None。"""
    if not isinstance(节点, ast.Call):
        return None
    if getattr(节点.func, "attr", None) not in ("compile", "match", "fullmatch", "search"):
        return None
    if not 节点.args:
        return None
    首个 = 节点.args[0]
    if isinstance(首个, ast.Constant) and isinstance(首个.value, str):
        return 首个.value
    return None


def _是通用markdown语法(形态: str) -> bool:
    r"""是不是**通用 markdown 语法**的形态（业务自有约定不算）。

    `| 1 |` 这类**本件自己的编号约定**（如债务清单的 `编号行`，正则里带 `\d`）
    不在此列 —— 那是该件自己的数据约定，不是 markdown 语法，别误判。
    """
    去空 = 形态.replace(" ", "")
    主体 = 去空[1:] if 去空.startswith("^") else 去空
    # 允许 `^(#{2,4})` 这种**分组写法** —— 与 `^#{2,4}` 是同一判据的两种写法，
    # 只认后者会漏掉前者（2026-09-22 实测：说明书解析 用的就是分组写法）。
    主体 = 主体.lstrip("(")
    if 主体.startswith("#") or 主体.startswith("`{3"):
        return 真
    return 主体.startswith("\\|") and "\\d" not in 去空


def _规则六手写markdown语法解析(根: Path, 结论: 检查结论) -> None:
    """扫出「手写 markdown 语法解析」——与既有原子能力重复的**实现面**第二条腿。

    为什么补这一面（2026-09-22）：既有五条轴全是**声明面**重复（模块公开第二入口 /
    跨包同名调用腿 / 两处配置表 / 两条声明面自建腿 / 契约读取腿），没有一条覆盖
    **实现面**（手写语法解析）。实测：markdown 解析原子能力
    `办公文档支持库.轻量文本解析` 于 2026-09-11 下沉（提交 abd651f1），而
    `开发工具/MD文档生成/文档类型_债务清单.py` 到 2026-09-20 仍手写 `表格行/表格分隔/标题`
    正则 —— 晚 9 天，期间没有任何机器提醒「该用它」。唯一腿本体不判；
    判据只认**通用形态**（见 `_是通用markdown语法`）。
    """
    文件数 = 0
    for 源码 in 收集源码(根):
        相对 = 源码.relative_to(根).as_posix()
        if 相对.startswith(markdown语法唯一腿):
            continue
        文件数 += 1
        树 = _解析(源码, 结论, 根)
        if 树 is None:
            continue
        for 节点 in ast.walk(树):
            形态 = _正则字面量(节点)
            if 形态 is None or not _是通用markdown语法(形态):
                continue
            结论.命中列表.append(
                命中(规则六, 相对, getattr(节点, "lineno", 0),
                     f"手写 markdown 语法正则 {形态!r} —— 既有唯一腿 "
                     f"办公文档支持库.轻量文本解析.解析Markdown块 已提供该解析")
            )
    结论.扫描面[规则六] = 文件数


规则七 = "同职责路径判定"

#: 路径安全的唯一腿本体（本判据不判它自己，同 规则六 对 markdown 唯一腿的处理）。
路径安全唯一腿前缀 = "支持库/后端/系统核心支持库/路径安全"

#: 路径判定职责的函数名词表（同职责的不同写法都归到这里）。
#:
#: 【2026-09-24 批O·O-10 清死条目】原表 8 项里有两项已死，同批处理：
#:   ① `"校验路径在仓库内"` —— 该函数已改名为 `归一化仓库内路径`
#:      （`支持库/适配层/Git提供者/实现/白名单.py`），旧名全仓零命中 ⇒ 死条目，删；
#:      中文仓库实测：改名后**必须按新名登记**，否则该文件（实测 :98）不再入判据面。
#:   ② `"校验路径文本"` 在本表里**重复登记了两次**（同一表内同名两项），去重保留一项。
#: 注：判据同时按下条「名字含『路径』」取函数（`if "路径" not in 名字 and 名字 not in 路径判定词表`），
#: 故 `归一化仓库内路径` 本来就命中；登记新名只是让「同职责写法表」与现场名一致、不留假名。
路径判定词表 = (
    "校验路径", "校验相对路径", "规范化相对路径", "归一化相对路径",
    "安全合并路径", "校验路径文本", "归一化仓库内路径",
)

#: 函数段里的「边界判定痕迹」：出现任一即认为该函数在做路径边界判定，
#: 不是单纯拼接/归一化。用**痕迹**而不是函数名，是因为 8 处实现的函数名各不相同
#: （实测：`校验路径` / `校验相对路径` / `规范化相对路径` / `_安全合并路径` / …），
#: 按名字分组会一条都报不出来 —— 而它们判的确实是同一件事。
路径判定痕迹 = ("..", "unquote", "路径越界")

#: 已转调唯一腿的痕迹：函数段里出现即不算第二腿（哲学 1.3「结果唯一即收口」）。
#: 2026-09-23 S4·T3：唯一腿已拆出纯判定节点 `校验相对路径文本`，转调它也视为已收口。
路径唯一腿转调痕迹 = ("系统核心支持库.路径安全", "路径安全.校验路径", "校验相对路径文本(")


def _规则七同职责路径判定(根: Path, 结论: 检查结论) -> None:
    """扫出「同一职责的路径边界判定在多份文件各写一遍」。

    为什么补这一面（2026-09-23，S4·T3）：既有六条轴没有一条覆盖**路径边界判定**这个职责。
    实测（`开发文档/分析/路径安全实现处与分歧实测_20260923.md`）：同一职责至少 8 处各自实现，
    6 处口径分歧（`C:foo` / `C:/foo` / `a\\..\\b` / `~/x` / `a/./b` / `.`），而本检查器跑绿 ——
    因为 13 条基线里没有任何路径类条目 ⇒ **判据看不见这件事**。

    判据（三条同时成立才算一条腿）：
    ① 模块级函数，名字含「路径」或命中 `路径判定词表`；
    ② 函数段里出现 ≥1 个 `路径判定痕迹`（真的在做边界判定，不是单纯拼接）；
    ③ 函数段里**没有** `路径唯一腿转调痕迹`。

    同一职责（路径边界判定）落在 ≥2 个文件 ⇒ 报「同职责第二腿」。
    唯一腿本体（`支持库/后端/系统核心支持库/路径安全`）不判。

    覆盖不了什么（如实声明）：判不了「职责相同但写成表驱动/正则」的形态；
    也判不了「同一函数在类方法里」（只扫模块级函数）；不证明两条腿都会在生产路径上被走到。
    """
    组: dict[str, list[tuple[str, int]]] = {}
    文件数 = 0
    for 源码 in 收集源码(根):
        相对 = 源码.relative_to(根).as_posix()
        if 相对.startswith(路径安全唯一腿前缀):
            continue          # 唯一腿本体不判（同 规则六 对 markdown 唯一腿的处理）
        if 相对.endswith("验证门禁/同动作双路径检测.py"):
            # 判据自指段：本文件里就有本判据自己的函数（名字含「路径」、段里含 `..`），
            # 不跳它就会自己报自己。跳过面必须可见，不得静默当通过。
            结论.跳过面[f"{规则七}：判据自指段（本文件）"] = 1
            continue
        文件数 += 1
        树 = _解析(源码, 结论, 根)
        if 树 is None:
            continue
        文本 = 源码.read_text(encoding="utf-8").splitlines()
        for 节点 in 树.body:
            if not isinstance(节点, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            名字 = 节点.name
            起 = 节点.lineno
            止 = max(
                (子.lineno for 子 in ast.walk(节点) if hasattr(子, "lineno")), default=起
            )
            段 = "\n".join(文本[起 - 1: 止])
            if "路径" not in 名字 and 名字 not in 路径判定词表:
                continue
            if not any(痕迹 in 段 for 痕迹 in 路径判定痕迹):
                continue
            if any(痕迹 in 段 for 痕迹 in 路径唯一腿转调痕迹):
                continue
            组.setdefault(规则七, []).append((相对, 起))
    结论.扫描面[规则七] = 文件数
    出现表 = 组.get(规则七, [])
    if len({文件 for 文件, _ in 出现表}) < 2:
        return
    for 文件, 行号 in 出现表:
        结论.命中列表.append(
            命中(规则七, 文件, 行号,
                 f"同职责路径边界判定在 {len(出现表)} 处各有一份实现"
                 f"（唯一腿 = 支持库/后端/系统核心支持库/路径安全.校验路径）")
        )


def 构建结论(根: Path) -> 检查结论:
    结论 = 检查结论(名称=检查器名)
    _规则一模块公开第二入口(根, 结论)
    _规则二模块库跨包同名公开调用腿(根, 结论)
    _规则三同一动作两处配置表(根, 结论)
    _契约读取腿扫描(根, 结论)
    _规则六手写markdown语法解析(根, 结论)
    _规则七同职责路径判定(根, 结论)
    return 结论


# ────────────────────────── 反向验证（变异样本必红）──────────────────────────
#: 每条判据对应一份「故意违规」的变异样本；夹具根里只放足够命中的最小结构。
变异样本表: tuple[tuple[str, str, str], ...] = (
    ("规则一 模块公开第二入口",
     "模块库/夹具包一/__init__.py",
     '__all__ = ["设置HTTP连接器", "夹具能力"]\n'),
    ("规则二 模块库跨包同名公开调用腿",
     "模块库/夹具包二/实现/夹具包二.py",
     "def 夹具调用腿(输入):\n    return 输入\n"),
    ("规则三 同一动作两处配置表",
     "支持库/后端/夹具支持库/实现/夹具第二份.py",
     '夹具状态表 = {"已停止": 1, "已卸载": 2, "已校验": 3}\n'),
    # 变异样本形态 = 审计件 I-5 的现场形态：同一份源码里「读契约」有两条自建腿
    # （两处都是 rglob 扫声明文件、两段产出都带契约字段），且都不转调唯一能力腿。
    ("规则四 同一动作声明面扫描点",
     "开发工具/夹具工具/夹具入口.py",
     "def 夹具查看契约(目录):\n"
     "    结果 = {}\n"
     "    for 契约文件 in 目录.rglob('能力契约/*.json'):\n"
     "        结果[契约文件.name] = None\n"
     "    return {'能力id': '夹具', '参数': 结果, '返回': '结果型', '错误码': []}\n"
     "\n"
     "\n"
     "def 夹具第二套读取契约(目录):\n"
     "    结果 = {}\n"
     "    for 契约文件 in 目录.glob('**/能力契约/参数契约.json'):\n"
     "        结果[契约文件.name] = None\n"
     "    return {'能力id': '夹具', '参数': 结果, '返回': '结果型', '错误码': []}\n",
     ),
    ("规则六 手写 markdown 语法解析",
     "开发工具/夹具工具/夹具手写markdown.py",
     'import re\n\n表格分隔 = re.compile(r"^\\|[\\s:|-]+\\|$")\n'),
)

#: 规则二/规则三 的第一份样本（成对出现才算命中）。
变异样本补充表: tuple[tuple[str, str], ...] = (
    ("模块库/夹具包三/实现/夹具包三.py", "def 夹具调用腿(输入):\n    return 输入\n"),
    ("支持库/后端/夹具支持库/实现/夹具第一份.py",
     '夹具状态表 = {"已停止": 1, "已卸载": 2, "已校验": 3, "已启用": 4}\n'),
)


def _自证() -> int:
    """三拍自证：① 干净夹具根 → 绿；② 逐条注入变异样本 → 必红；③ 撤除样本 → 回绿。"""
    根 = 新建夹具根("验证门禁一_自证_")
    基线 = 根 / "基线.json"
    结果: list[tuple[str, str]] = []
    # 拍一：干净夹具根（只放必需的最小目录结构 + 一份**合法**模块入口）→ 判绿、扫描面非 0。
    # 注意：合法样本的路径**不得与任何变异样本重合**，否则拍三撤除时会把合法样本一起删掉，
    # 扫描面塌成 0 → 第三拍假红（2026-09-19 实测，夹具包一 同时是规则一的变异路径）。
    for 层名 in ("模块库", "支持库", "开发工具"):
        (根 / 层名).mkdir(parents=True, exist_ok=True)
    (根 / "模块库" / "夹具基准包").mkdir(parents=True, exist_ok=True)
    (根 / "模块库" / "夹具基准包" / "__init__.py").write_text(
        '__all__ = ["夹具能力"]\n', encoding="utf-8"
    )
    # 规则六的**合法样本**（必须一条都不报）：① 唯一腿本体；② 业务自有约定（带 \d 的编号行）。
    # 路径不得与任何变异样本重合，否则拍三撤除时会被一起删掉 → 第三拍假红。
    唯一腿实现目录 = 根 / markdown语法唯一腿 / "实现"
    唯一腿实现目录.mkdir(parents=True, exist_ok=True)
    (唯一腿实现目录 / "轻量文本解析.py").write_text(
        'import re\n\n表格行 = re.compile(r"^\\|.+\\|$")\n', encoding="utf-8"
    )
    (根 / "开发工具" / "夹具自有约定.py").write_text(
        'import re\n\n编号行 = re.compile(r"^\\|\\s*(\\d+)\\s*\\|")\n', encoding="utf-8"
    )
    (根 / "基线.json").write_text(
        json.dumps({"检查器": {检查器名: {}}}, ensure_ascii=False), encoding="utf-8"
    )
    import subprocess

    def _跑() -> int:
        return subprocess.run(
            [sys.executable, str(Path(__file__)), "--根", str(根), "--基线", str(基线)],
            capture_output=True, text=True, timeout=墙钟上限秒,
        ).returncode

    第一拍 = _跑()
    结果.append((f"第一拍 干净夹具根 {根}", f"退出码 {第一拍}（期望 0=绿）"))
    # 拍二：逐条注入变异
    全部样本 = [(说明, 相对, 内容) for 说明, 相对, 内容 in 变异样本表] + [
        (f"补样本 {相对}", 相对, 内容) for 相对, 内容 in 变异样本补充表
    ]
    for _说明, 相对, 内容 in 全部样本:
        路径 = 根 / 相对
        路径.parent.mkdir(parents=True, exist_ok=True)
        路径.write_text(内容, encoding="utf-8")
    第二拍 = _跑()
    结果.append((f"第二拍 注入 {len(全部样本)} 份变异样本", f"退出码 {第二拍}（期望 1=红）"))
    # 拍三：撤除全部变异样本 → 回绿
    for _说明, 相对, _内容 in 全部样本:
        路径 = 根 / 相对
        if 路径.is_file():
            路径.unlink()
    第三拍 = _跑()
    结果.append((f"第三拍 撤除变异样本", f"退出码 {第三拍}（期望 0=绿）"))

    print(f"══ {检查器名} 自证（三拍）══")
    for 名, 值 in 结果:
        print(f"  {名}：{值}")
    通过 = 第一拍 == 0 and 第二拍 == 1 and 第三拍 == 0
    print(f"  自证结论：{'通过' if 通过 else '不通过'}")
    if not 通过:
        print(f"  ⚠ 夹具根保留供人工复核：{根}")
        return 1
    # 夹具根可能含只读条目（夹具故意造权限场景）→ 走唯一实现，不留 shutil.rmtree 裸调用
    清只读后删除树(根, 忽略失败=真)
    return 0


def main(argv: list[str] | None = None) -> int:
    实参 = list(sys.argv[1:] if argv is None else argv)
    if "--自证" in 实参:
        return _自证()
    from 开发工具.验证门禁.门禁公共 import 跑标准主流程

    return 跑标准主流程(检查器名, 构建结论, 实参)


if __name__ == "__main__":
    sys.exit(main())
