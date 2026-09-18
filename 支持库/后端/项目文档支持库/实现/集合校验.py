"""项目文档支持库 · 集合级判据校验原子能力（进程内实现，不对外暴露）。

与 `规范校验`（单文档内判据）并列：本模块处理**跨文档关系**判据 ——
「全仓只允许一份自称唯一」「本地链接目标必须存在」「子方案提了待办债务清单须登记」
「状态行取值必须落在枚举内」这类**单看一份文档判不出来**的规则。

判据仍来自**数据文件**（集合判据 JSON），与 `规范校验` 同口径：
规范改一句只改数据，判据与规范同源，不漂移（哲学 5.1 / 4.4）。

判据文件结构（唯一真源：开发文档/规范/方案文档生命周期规范.md）：

    {
      "判据版本": "1.0.0",
      "唯一真源": "开发文档/规范/方案文档生命周期规范.md",
      "根目录": "开发文档/方案",
      "文件名模式": "*.md",
      "豁免目录": ["开发文档/归档"],
      "判据": [
        {"判据id": "编排唯一", "严重级": "阻断", "说明": "...",
         "类型": "集合唯一", "参数": {"模式": "^# .*唯一入口", "期望": 1, "跳过围栏": true}},
        ...
      ]
    }

集合判据类型（类型 → 语义）：

| 类型 | 参数 | 语义 |
|---|---|---|
| 集合唯一 | 模式 / 期望 / 跳过围栏 | **全仓**命中文档数必须等于期望 |
| 引用可达 | 无 | 文档内本地链接的目标文件必须存在 |
| 跨文档配对 | 触发模式 / 登记文件 / 登记模式 | 文档命中触发模式时，登记文件必须含登记模式（按文档名匹配）|
| 状态枚举 | 行前缀 / 取值枚举 | 该前缀行的取值必须 ∈ 枚举 |

未实现的判据类型**明确报错**（不假装通过）—— 与 `规范校验` 的 `_跑一条` 同口径。
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from 公共契约.基础类型.结果类型 import 结果

围栏行模式 = re.compile(r"^\s*```")
链接模式 = re.compile(r"\[([^\]]*)\]\(([^)\s]+)\)")


def _读判据(判据文件: str) -> dict | None:
    """读集合判据文件；不可读或结构不符返回 None（由调用方转明确失败）。"""
    路径 = Path(判据文件)
    if not 路径.is_file():
        return None
    try:
        数据 = json.loads(路径.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(数据, dict) or not isinstance(数据.get("判据"), list):
        return None
    return 数据


def _扫集合(根: Path, 模式: str, 豁免: list[str]) -> list[tuple[str, str]]:
    """扫出一批 ``(相对路径, 正文)``。

    豁免口径**复用** `集合扫描._归一豁免`/`_被豁免`，不在本模块另写一遍
    （2026-09-18 实测教训：同一口径写两遍时，两处都漏剥首段，豁免双双静默失效）。
    """
    from 支持库.后端.项目文档支持库.实现.集合扫描 import _归一豁免, _被豁免

    豁免表 = _归一豁免(豁免, 根.name)
    结果表: list[tuple[str, str]] = []
    for 路径 in sorted(路径 for 路径 in 根.rglob(模式) if 路径.is_file()):
        部分 = 路径.relative_to(根).parts
        if _被豁免(部分, 豁免表):
            continue
        try:
            结果表.append(("/".join(部分), 路径.read_text(encoding="utf-8")))
        except (OSError, UnicodeDecodeError):
            continue
    return 结果表


def _命中行(正文: str, 模式: str, 跳过围栏: bool) -> list[int]:
    """返回命中的行号（1 起）；跳过围栏 为真时忽略代码块内的行。"""
    编译 = re.compile(模式)
    命中: list[int] = []
    在围栏内 = False
    for 序号, 行 in enumerate(正文.split("\n"), start=1):
        if 围栏行模式.match(行):
            在围栏内 = not 在围栏内
            continue
        if 跳过围栏 and 在围栏内:
            continue
        if 编译.search(行):
            命中.append(序号)
    return 命中


def _集合唯一(文档表: list[tuple[str, str]], 参数: dict) -> list[dict]:
    """全仓命中文档数必须等于期望；报出**每份命中文档**的行号。"""
    模式 = str(参数.get("模式", ""))
    跳过围栏 = bool(参数.get("跳过围栏", False))
    期望 = int(参数.get("期望", 0) or 0)
    命中明细: list[dict] = []
    for 相对路径, 正文 in 文档表:
        行号列表 = _命中行(正文, 模式, 跳过围栏)
        if 行号列表:
            命中明细.append({"文件": 相对路径, "行号": 行号列表[0]})
    if len(命中明细) == 期望:
        return []
    # 数量不符：逐份报出（多一份要能指出是哪份，少一份要能看出缺在哪）
    return 命中明细 or [{"文件": "", "行号": 0}]


行内代码模式 = re.compile(r"`[^`]*`")


def _去行内代码(行: str) -> str:
    """剔除行内代码段（反引号内），避免把写在 `[...](...)` 示例里的链接当成真链接。

    2026-09-18 实测踩坑：`| \\`链接文字一致\\` | \\`[X](Y)\\` 的文字 X = Y |` 这类**规范文档里的写法示例**
    被当成真链接，报了假「链接目标不存在: Y」。
    """
    return 行内代码模式.sub("", 行)


def _引用可达(文档表: list[tuple[str, str]], 参数: dict, 根: Path | None = None) -> list[dict]:
    """文档内本地链接目标必须存在；外链/锚点/行内代码/围栏跳过。

    **路径基准**（修过一处真 bug）：一律**相对文档所在目录**解析，并拼上扫描根。
    2026-09-18 实测踩坑：只用文档相对路径做基准时，候选路径会相对**进程当前工作目录**
    解析，链接永远找不到，正向用例必红。
    """
    _ = 参数
    命中: list[dict] = []
    for 相对路径, 正文 in 文档表:
        基准 = (根 or Path(".")) / Path(相对路径).parent
        在围栏内 = False
        for 序号, 行 in enumerate(正文.split("\n"), start=1):
            if 围栏行模式.match(行):
                在围栏内 = not 在围栏内
                continue
            if 在围栏内:
                continue
            for _文字, 目标 in 链接模式.findall(_去行内代码(行)):
                if 目标.startswith(("http://", "https://", "#", "mailto:")):
                    continue
                纯目标 = 目标.split("#")[0]
                if not 纯目标:
                    continue
                # 链接可能是相对仓库根（本仓惯例：开发文档内互链多从仓库根写起）
                候选 = [基准 / 纯目标]
                if 根 is not None:
                    候选.append(根 / 纯目标)
                if not any(x.exists() for x in 候选):
                    命中.append({"文件": 相对路径, "行号": 序号,
                                "说明": f"链接目标不存在: {纯目标}"})
    return 命中


def _跨文档配对(文档表: list[tuple[str, str]], 参数: dict, 根: Path | None = None) -> list[dict]:
    """文档命中「触发模式」时，登记文件须含该文档名的登记（治「隐形债」）。

    配对口径：触发文档的**文件名**必须出现在登记文件正文里（按文件名匹配，
    不用路径，避免写法差异导致假红）。

    **登记文件自身不参与触发判定**（修过一处真 bug）：登记文件正文里写着「待修 / 待办」
    这类词是常态，把它自己也当成「待登记的文档」会自我报红，正向用例必红。
    """
    触发模式 = re.compile(str(参数.get("触发模式", "")))
    登记文件 = str(参数.get("登记文件", ""))
    跳过围栏 = bool(参数.get("跳过围栏", False))

    登记正文 = ""
    登记名字 = Path(登记文件).name
    登记路径 = Path(登记文件)
    if 登记路径.is_file():
        try:
            登记正文 = 登记路径.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            登记正文 = ""
    命中: list[dict] = []
    for 相对路径, 正文 in 文档表:
        if Path(相对路径).name == 登记名字:
            continue          # 登记文件自己不算待登记的文档
        if 根 is not None and (根 / 相对路径).resolve() == 登记路径.resolve():
            continue
        if not _命中行(正文, 触发模式.pattern, 跳过围栏):
            continue
        文件名 = Path(相对路径).name
        if 文件名 not in 登记正文:
            命中.append({"文件": 相对路径, "行号": 0,
                        "说明": f"含待办但登记文件未登记本文: {登记文件}"})
    return 命中


def _状态枚举(文档表: list[tuple[str, str]], 参数: dict) -> list[dict]:
    """行前缀命中的行，其取值必须 ∈ 取值枚举（治「写了 `已删除` 也能骗过存在性检查」）。

    参数 `必须存在`（默认 假）为真时，**完全没有该前缀行的文档也报违规** ——
    对应规范「每份方案文档头部必须有状态声明」这条；为假时只查「写了的那行取值合不合法」。
    """
    前缀 = str(参数.get("行前缀", ""))
    枚举 = [str(x) for x in (参数.get("取值枚举") or [])]
    必须存在 = bool(参数.get("必须存在", False))
    命中: list[dict] = []
    for 相对路径, 正文 in 文档表:
        有前缀行 = False
        for 序号, 行 in enumerate(正文.split("\n"), start=1):
            if not 行.startswith(前缀):
                continue
            有前缀行 = True
            if any(取值 in 行 for 取值 in 枚举):
                continue
            命中.append({"文件": 相对路径, "行号": 序号,
                        "说明": f"取值不在枚举内: {行.strip()[:60]}"})
        if 必须存在 and not 有前缀行:
            命中.append({"文件": 相对路径, "行号": 0,
                        "说明": f"缺状态声明（必须以 {前缀} 开头）"})
    return 命中


执行表 = {
    "集合唯一": _集合唯一,
    "引用可达": _引用可达,
    "跨文档配对": _跨文档配对,
    "状态枚举": _状态枚举,
}


def _跑一条(文档表: list[tuple[str, str]], 判据: dict, 根: Path) -> list[dict] | None:
    """跑单条集合判据；不通过返回违规条目列表，通过返回 None。

    带 `根` 的判据（引用可达）需要它解析相对路径；不带 `根` 的判据按签名兼容调用。
    """
    类型 = str(判据.get("类型", ""))
    执行 = 执行表.get(类型)
    if 执行 is None:
        return [{"文件": "", "行号": 0,
                 "说明": f"未实现的判据类型 {类型}（判据文件与支持库版本不一致）"}]
    参数 = 判据.get("参数") or {}
    if 类型 in {"引用可达", "跨文档配对"}:
        return 执行(文档表, 参数, 根)
    return 执行(文档表, 参数)


def 校验集合判据(根目录: str = None, 判据文件: str = None, 文件名模式: str = "",
                豁免目录=None) -> 结果:
    """按集合判据文件校验一批文档（只读）。

    参数：根目录（绝对路径）/ 判据文件（绝对路径）/ 文件名模式（留空取判据文件里的声明）/
    豁免目录（留空取判据文件里的声明；传了则覆盖）。
    返回：``{通过, 违规条目, 条目数, 驳回项数, 文档数, 唯一真源}``；
    判据文件不可读时**明确失败**（无判据的「通过」是假绿）。
    """
    if not isinstance(根目录, str) or not 根目录.strip():
        return 结果.失败("参数不合法", "根目录必须是非空文本", 来源="项目文档支持库")
    if not isinstance(判据文件, str) or not 判据文件.strip():
        return 结果.失败("参数不合法", "判据文件必须是非空文本", 来源="项目文档支持库")
    数据 = _读判据(判据文件)
    if 数据 is None:
        return 结果.失败("判据文件不存在", f"判据文件不可读或结构不符: {判据文件}",
                     来源="项目文档支持库")
    根 = Path(根目录.strip())
    if not 根.is_dir():
        return 结果.失败("根目录不存在", f"根目录不是已存在的目录: {根}", 来源="项目文档支持库")

    模式 = str(文件名模式 or 数据.get("文件名模式") or "*.md")
    豁免 = 豁免目录 if 豁免目录 is not None else (数据.get("豁免目录") or [])
    文档表 = _扫集合(根, 模式, list(豁免))

    条目: list[dict] = []
    for 判据 in 数据["判据"]:
        命中 = _跑一条(文档表, 判据, 根)
        for 明细 in (命中 or []):
            条目.append({
                "判据id": str(判据.get("判据id", "")),
                "严重级": str(判据.get("严重级", "建议")),
                "说明": str(明细.get("说明") or 判据.get("说明", "")),
                "文件": str(明细.get("文件", "")),
                "行号": int(明细.get("行号", 0) or 0),
            })
    驳回项 = [x for x in 条目 if x["严重级"] == "阻断"]
    return 结果.成功结果({
        "通过": not 驳回项,
        "违规条目": 条目,
        "条目数": len(条目),
        "驳回项数": len(驳回项),
        "文档数": len(文档表),
        "唯一真源": str(数据.get("唯一真源", "")),
    })
