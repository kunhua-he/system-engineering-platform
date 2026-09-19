"""公开调用完整性门禁 · 检查与判定簇（拆分自 开发工具/公开调用完整性门禁.py）。

职责：三件事 ——
  ① 六环的**包级检查**（``检查包``：包声明/能力定义/注册/搜索/说明书/公开调用/验证场景）；
  ② 跨包**全局唯一性**判定（``检查全局``：能力 id 全局唯一，中文名重复豁免）；
  ③ 存量基线的**分桶消费**（``读取存量基线``/``分桶``/``应用存量基线``：只减不增）。

判据唯一事实源：owner 去重口径与 ``开发工具/项目编译/正式包索引.构建索引`` 一致
（无 ``能力定义.json`` 且子包持有该能力 ⇒ 子包是 owner、父包是视图）；
存量基线口径见 ``开发工具/公开调用完整性门禁存量基线.json``。

为什么拆出来：这簇是「判据」本体（怎么判、判不到算不算），与「接线」本体
（依赖锁环 / 消费者登记环 / 错误码登记环 / 装配与主程序）是两类东西 ——
基线只能在判据之后扣减，两簇混在一处会让人误以为扣减属于判据。对外名字一个不改。
"""
from __future__ import annotations

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

from 开发工具.公开调用完整性门禁_包发现 import (  # noqa: E402
    _公开owner字段, _是适配层Provider, 提取导出名, 提取注册映射,
    读取json带诊断, 读取文本带诊断,
)
from 开发工具.公开调用完整性门禁_说明书解析 import 检查说明书字段  # noqa: E402

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

    # 能力定义.json：缺失与不可读分两态（A-1 口径）。不可读时不静默回退到
    # 参数契约/包声明继续对账——那会把「定义读不成、字段对账整段降级」写成通过。
    定义路径 = 包目录 / "能力定义.json"
    if not 定义路径.is_file():
        违规.append({"能力id": "*", "包": 包id, "缺口类型": "声明-能力定义.json缺失", "路径": str(定义路径)})
    else:
        定义值, 定义诊断 = 读取json带诊断(定义路径)
        if 定义诊断 is not None:
            违规.append({"能力id": "*", "包": 包id,
                        "缺口类型": f"声明-能力定义.json{定义诊断}", "路径": str(定义路径)})
        elif not isinstance(定义值, dict):
            违规.append({"能力id": "*", "包": 包id,
                        "缺口类型": "声明-能力定义.json不是对象", "路径": str(定义路径)})
    if "注册能力" not in 源码 and not 数据路径.is_dir():
        违规.append({"能力id": "*", "包": 包id, "缺口类型": "注册-入口未注册能力", "路径": str(入口路径)})
    搜索数据, 搜索诊断 = 读取json带诊断(搜索路径)
    搜索id集 = {条.get("能力id") for 条 in 搜索数据} if isinstance(搜索数据, list) else set()
    if 搜索诊断 is not None:
        违规.append({"能力id": "*", "包": 包id, "缺口类型": f"搜索-能力搜索数据.json{搜索诊断}", "路径": str(搜索路径)})

    说明书, 说明诊断 = 读取文本带诊断(说明路径)
    if 说明诊断 == "缺失":
        违规.append({"能力id": "*", "包": 包id, "缺口类型": "说明书-使用说明.md缺失", "路径": str(说明路径)})
    elif 说明诊断 is not None:
        # A-1 同类：说明书在但读不成（编码坏/权限）单独出条目并带异常名，
        # 不得让解码异常冒到门禁外层（那会把「这份说明书读不成」写成「门禁坏了」）。
        违规.append({"能力id": "*", "包": 包id,
                    "缺口类型": f"说明书-使用说明.md{说明诊断}", "路径": str(说明路径)})
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
