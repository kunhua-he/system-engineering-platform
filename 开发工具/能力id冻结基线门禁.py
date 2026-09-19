"""能力 id「只增不改」静态门禁 + 冻结基线（第 29 项）。

**判据**：全仓能力 id 集**只增不改** —— 当前集 ⊇ 基线集。基线里有、当前没有的 id
= 被删或被改名 → **判红**；当前多出来的 id = 新增 → **允许**（只报，不拦）。

**口径（唯一权威 = 装配口径）**：能力 id 全集取 ``开发工具/项目编译/正式包索引.构建索引``
的 ``能力所有者``（= 装配后 owner 去重后的公开发布面）。本仓库 2026-09-18 实测：
装配口径 **679** 条，与 ``后端核心(根).启动()`` 注册表 能力id列表 集合**逐个相等**
（静态索引与真实装配同源，故门禁可离线、确定性地跑，不必每次拉起后端）。
**不得**用 ``包声明.json`` rglob 累加口径（实测 845 条，聚合父包与子包各登记一份
→ 同一条能力被计 2 次，虚高 166 条），也不得引用作废的「830」。裁定见
``开发文档/分析/能力面与拆分清单_20260918.md`` §1.1。

**fail-closed（本项目核心纪律）**：以下情形一律**判红**，绝不静默放行：
- 基线文件**缺失** → 红（缺基线 = 无参照，不是「没有要检查的」）；
- 基线文件**不可读**（JSON 语法错 / 编码错 / 权限错 / 形状非法 / 条目为空）→ 红；
- 扫描面为空（正式包索引读不成、或 0 条能力 id）→ 红（空集不是通过）；
- 某 id 的 owner 包 ``能力定义.json`` 取不到指纹 → 红（判不出 ≠ 通过）。

**契约变更是合法行为，但必须留痕**：已存在 id 的**内容指纹**变化、**归属包**变化、
以及**新增** id，三者都**不拦**，只作为留痕项打印（``[留痕]``／``[新增]``），
提醒复核者去读变更内容 —— 冻结的是「id 的存在性」，不是「id 的内容」。

**基线格式**（``开发文档/项目证据/能力id冻结基线.json``）::

    {
      "版本": 1, "口径": "装配口径", "基线时点": "...", "能力数": N,
      "条目": {
        "<能力id>": {"首次出现": "本次冻结时快照",
                     "归属包": "<owner 包id>",
                     "内容指纹": "<sha256[:16]>"}
      }
    }

``首次出现`` 用「本次冻结时快照」语义（不真取提交号：本仓 679 条 id 的历史首现
无法逐条从 git 可靠还原，写假提交号等于造假证据）；``内容指纹`` 是 owner 包
``能力定义.json`` 里该能力条目的规范化 JSON（``sort_keys``）的 sha256 前 16 位，
覆盖 参数/返回/错误码/行为/提供者 全字段。

**用法**::

    python3.14 开发工具/能力id冻结基线门禁.py                 # 跑门禁（默认基线）
    python3.14 开发工具/能力id冻结基线门禁.py --基线 <路径>     # 跑门禁（指定基线，反向验证用）
    python3.14 开发工具/能力id冻结基线门禁.py --冻结            # 显式重建/冻结基线
    python3.14 开发工具/能力id冻结基线门禁.py --冻结 --基线 <路径>

退出码：0 = 通过（可能有留痕/新增）；1 = 判红；2 = 用法错误。
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

仓库根 = Path(__file__).resolve().parents[1]
基线相对路径 = ("开发文档", "项目证据", "能力id冻结基线.json")
基线时点 = "2026-09-18"


def 本次冻结时点() -> str:
    """冻结时的**真实**日期（本地时区）。

    为什么不能继续用上面的常量：``--冻结`` 是**重建基线**的动作，写出的
    「基线时点」若恒为首次冻结日（2026-09-18），重建后的基线就会声称自己是
    9 天前的快照 —— 交付说明与门禁报告据此判断「基线是否新于被检变更」时会
    得出反向结论（实测：2026-09-20 重建后文件里仍写 2026-09-18）。
    常量保留只为兼容历史引用与文档口径，**写出时必须用本函数**。
    """
    from datetime import date
    return date.today().isoformat()
基线口径 = "装配口径"

# 缺口类型常量（报告里逐条打印；反向验证按这些字符串断言）
缺基线文件 = "冻结基线-基线文件缺失"
缺基线不可读 = "冻结基线-基线文件不可读"
缺基线形状 = "冻结基线-基线文件形状非法"
缺扫描面 = "冻结基线-扫描面为空"
缺id消失 = "冻结基线-能力id消失(被删或改名)"
缺指纹 = "冻结基线-内容指纹无法取证"

留痕指纹变 = "内容指纹变化"
留痕归属变 = "归属包变化"
留痕新增 = "新增能力id"


def 默认基线路径() -> Path:
    """冻结基线的落点：``开发文档/项目证据/能力id冻结基线.json``。"""
    本模块 = Path(__file__).resolve()
    # 本模块在 开发工具/ 下；仓库根 = parents[1]
    return 本模块.parents[1].joinpath(*基线相对路径)


def _读json(路径: Path) -> tuple[object | None, str | None]:
    """读 JSON 并分三态：``(数据, None)`` / ``(None, "缺失")`` / ``(None, "不可读:<异常>")``。

    与 ``公开调用完整性门禁.读取json带诊断`` 同一口径：把「验证器内部故障」与
    「声明可读但确实没内容」分开，不压成同一个 ``None``。
    """
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


def 计算内容指纹(能力条目: dict) -> str:
    """能力条目 → 规范化 JSON 的 sha256 前 16 位（键序无关，值结构全纳入）。"""
    规范 = json.dumps(能力条目, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(规范).hexdigest()[:16]


def 收集当前能力面(根: Path) -> tuple[dict[str, dict], list[dict]]:
    """当前能力面：``{能力id: {归属包, 内容指纹}}`` + 取证失败清单（fail-closed）。

    口径 = ``正式包索引.构建索引`` 的 ``能力所有者``（装配口径，装配后 owner 去重）。
    owner 包目录从索引的 支持库/模块库 两栏反查；指纹取该包 ``能力定义.json`` 里
    ``能力id`` 命中的那条能力（整条，含 参数/返回/错误码/行为/提供者）。
    """
    违规: list[dict] = []
    # 门禁自身所在的仓库根（用于 import 判据模块）与**被判目标根**都进 sys.path：
    # 夹具根（异仓/临时目录）下没有 开发工具/ 包，判据模块只能从本模块仓库取；
    # 而目标根的 公共契约 又要能被 正式包索引 读成事实源。两者都加，互不覆盖。
    本模块仓库根 = str(Path(__file__).resolve().parents[1])
    for 入径 in (str(根), 本模块仓库根):
        if 入径 not in sys.path:
            sys.path.insert(0, 入径)
    try:
        # 惰性 import：根目录不在 sys.path 时（夹具/异仓）也要给出可判红的原因，
        # 而不是让调用方拿到一个溯踪不明的 ImportError。
        from 开发工具.项目编译.正式包索引 import 构建索引
        索引 = 构建索引(根)
    except Exception as 错误:  # noqa: BLE001 —— 索引读不成 ⇒ 扫描面为空 ⇒ 判红
        return {}, [{"能力id": "*", "包": "全仓", "缺口类型": 缺扫描面,
                     "路径": str(根), "详情": f"正式包索引不可用: {type(错误).__name__}: {错误}"}]

    所有者 = 索引.get("能力所有者") or {}
    if not 所有者:
        return {}, [{"能力id": "*", "包": "全仓", "缺口类型": 缺扫描面,
                     "路径": str(根), "详情": "能力所有者为空（0 条能力 id）"}]

    包路径表: dict[str, Path] = {}
    for 栏 in ("支持库", "模块库", "技能库"):
        for 包id, 值 in (索引.get(栏) or {}).items():
            路 = 值[0] if isinstance(值, (tuple, list)) else 值
            包路径表[包id] = Path(路)

    定义缓存: dict[Path, dict[str, dict]] = {}

    def _取定义(包目录: Path) -> tuple[dict[str, dict] | None, str | None]:
        if 包目录 in 定义缓存:
            return 定义缓存[包目录], None
        定义路径 = 包目录 / "能力定义.json"
        数据, 诊断 = _读json(定义路径)
        if 诊断 is not None:
            return None, 诊断
        if not isinstance(数据, dict):
            return None, "不是对象"
        表: dict[str, dict] = {}
        for 条 in 数据.get("能力列表") or []:
            if isinstance(条, dict) and isinstance(条.get("能力id"), str) and 条["能力id"]:
                表[条["能力id"]] = 条
        定义缓存[包目录] = 表
        return 表, None

    当前: dict[str, dict] = {}
    for 能力id in sorted(所有者):
        owner = 所有者[能力id]
        if not isinstance(owner, str) or owner.startswith("冲突:"):
            违规.append({"能力id": 能力id, "包": str(owner), "缺口类型": 缺指纹,
                        "路径": "跨包", "详情": "owner 冲突，无法定位唯一 owner 包"})
            continue
        包目录 = 包路径表.get(owner)
        if 包目录 is None:
            违规.append({"能力id": 能力id, "包": owner, "缺口类型": 缺指纹,
                        "路径": "跨包", "详情": "owner 包不在正式包索引的包表里"})
            continue
        表, 诊断 = _取定义(包目录)
        if 表 is None:
            违规.append({"能力id": 能力id, "包": owner, "缺口类型": 缺指纹,
                        "路径": str(包目录 / "能力定义.json"),
                        "详情": f"能力定义.json {诊断}"})
            continue
        条目 = 表.get(能力id)
        if 条目 is None:
            违规.append({"能力id": 能力id, "包": owner, "缺口类型": 缺指纹,
                        "路径": str(包目录 / "能力定义.json"),
                        "详情": "能力定义.json 里未找到该能力 id"})
            continue
        当前[能力id] = {"归属包": owner, "内容指纹": 计算内容指纹(条目)}
    return 当前, 违规


def 读取基线(路径: Path) -> tuple[dict[str, dict], list[dict]]:
    """读冻结基线；**任何一处读不成 → 违规清单非空（fail-closed）**。"""
    数据, 诊断 = _读json(路径)
    if 诊断 == "缺失":
        return {}, [{"能力id": "*", "包": "全仓", "缺口类型": 缺基线文件,
                     "路径": str(路径),
                     "详情": "冻结基线不存在 ⇒ 无参照 ⇒ 判红（fail-closed，不静默放行）"}]
    if 诊断 is not None:
        return {}, [{"能力id": "*", "包": "全仓", "缺口类型": 缺基线不可读,
                     "路径": str(路径), "详情": f"{诊断} ⇒ 判红（fail-closed）"}]
    if not isinstance(数据, dict):
        return {}, [{"能力id": "*", "包": "全仓", "缺口类型": 缺基线形状,
                     "路径": str(路径), "详情": "顶层不是对象"}]
    条目 = 数据.get("条目")
    if not isinstance(条目, dict) or not 条目:
        return {}, [{"能力id": "*", "包": "全仓", "缺口类型": 缺基线形状,
                     "路径": str(路径),
                     "详情": "条目缺失或为空 ⇒ 空基线不是通过（fail-closed）"}]
    出: dict[str, dict] = {}
    坏: list[str] = []
    for 能力id, 值 in 条目.items():
        if not isinstance(能力id, str) or not 能力id:
            坏.append(repr(能力id))
            continue
        if not isinstance(值, dict):
            坏.append(f"{能力id}（值不是对象）")
            continue
        出[能力id] = 值
    if 坏:
        return {}, [{"能力id": "*", "包": "全仓", "缺口类型": 缺基线形状,
                     "路径": str(路径),
                     "详情": f"条目形状非法 {len(坏)} 条: {'；'.join(坏[:5])} ⇒ 判红（fail-closed）"}]
    return 出, []


def 运行冻结门禁(根: Path, 基线文件: Path | None = None
                 ) -> tuple[list[dict], list[dict], list[dict]]:
    """``(违规, 留痕, 新增)`` 三态返回。

    - ``违规``：判红项（基线缺失/不可读/形状非法、扫描面为空、能力 id 消失、指纹取不到）；
    - ``留痕``：**允许但报到**（已存 id 的内容指纹变化 / 归属包变化）；
    - ``新增``：当前集比基线集多出的 id（「只增」的合法方向，只报）。
    """
    根 = Path(根).resolve()
    if 基线文件 is None:
        基线文件 = 默认基线路径()
    基线文件 = Path(基线文件)

    基线, 基线违规 = 读取基线(基线文件)
    当前, 当前违规 = 收集当前能力面(根)

    # 扫描面为空同样是判红项：即便基线完整，「当前 0 条」也只能是读不成，
    # 绝不解释成「全仓能力 id 都被合法清理了」。
    违规 = 基线违规 + 当前违规
    # 基线读不成时不重复刷「id 消失」——那会把一次读取故障说成 679 条删除。
    if 基线违规 or 当前违规:
        留痕 = [{"能力id": "*", "包": "全仓", "类型": "判据未生效",
                 "详情": "基线或当前面取证失败，本次不做集合比对（已单独判红）"}]
        return 违规, 留痕, []

    消失 = sorted(set(基线) - set(当前))
    for 能力id in 消失:
        条目 = 基线[能力id]
        违规.append({"能力id": 能力id, "包": str(条目.get("归属包") or "?"),
                     "缺口类型": 缺id消失, "路径": str(基线文件),
                     "详情": "基线有、当前无 ⇒ 能力 id 被删或被改名（违反『只增不改』）；"
                             "确属合法下线须显式重建基线（--冻结）"})

    留痕: list[dict] = []
    新增: list[dict] = []
    for 能力id in sorted(set(当前) - set(基线)):
        新增.append({"能力id": 能力id, "包": 当前[能力id]["归属包"],
                     "类型": 留痕新增, "详情": f"指纹={当前[能力id]['内容指纹']}"})
    for 能力id in sorted(set(当前) & set(基线)):
        旧 = 基线[能力id]
        新 = 当前[能力id]
        旧指纹 = str(旧.get("内容指纹") or "")
        旧归属 = str(旧.get("归属包") or "")
        if 旧指纹 and 旧指纹 != 新["内容指纹"]:
            留痕.append({"能力id": 能力id, "包": 新["归属包"], "类型": 留痕指纹变,
                         "详情": f"内容指纹 {旧指纹} → {新['内容指纹']}"
                                 "（契约变更合法，但须复核并同步重建基线）"})
        if 旧归属 and 旧归属 != 新["归属包"]:
            留痕.append({"能力id": 能力id, "包": 新["归属包"], "类型": 留痕归属变,
                         "详情": f"归属包 {旧归属} → {新['归属包']}"})
    return 违规, 留痕, 新增


def 冻结基线(根: Path, 基线文件: Path | None = None) -> tuple[int, str]:
    """现场生成/重建冻结基线。**只有显式 ``--冻结`` 才调用**（不让门禁自己改基线）。"""
    根 = Path(根).resolve()
    if 基线文件 is None:
        基线文件 = 默认基线路径()
    基线文件 = Path(基线文件)
    当前, 违规 = 收集当前能力面(根)
    if 违规 or not 当前:
        return 1, f"冻结失败：取证不完整（{len(违规)} 项），拒绝写出不完整基线"
    条目 = {能力id: {"首次出现": "本次冻结时快照",
                     "归属包": 当前[能力id]["归属包"],
                     "内容指纹": 当前[能力id]["内容指纹"]}
            for 能力id in sorted(当前)}
    文档 = {
        "说明": "能力 id『只增不改』冻结基线。判据：当前装配口径能力 id 集 ⊇ 本基线集；"
                "少了就是被删/改名（判红）。已存 id 的内容指纹变化允许但必须留痕。"
                "**基线文件缺失/不可读 ⇒ fail-closed 判红**（见 开发工具/能力id冻结基线门禁.py）。"
                "口径 = 装配口径（正式包索引.能力所有者，与 后端核心 装配注册表集合相等）；"
                "不得用 包声明.json rglob 累加口径（845 虚高）。",
        "版本": 1,
        "口径": 基线口径,
        "基线时点": 本次冻结时点(),
        "能力数": len(条目),
        "条目": 条目,
    }
    基线文件.parent.mkdir(parents=True, exist_ok=True)
    基线文件.write_text(json.dumps(文档, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0, f"已冻结 {len(条目)} 条能力 id → {基线文件}"


def 主程序(argv: list[str]) -> int:
    冻结 = "--冻结" in argv
    基线文件: Path | None = None
    if "--基线" in argv:
        位置 = argv.index("--基线")
        if 位置 + 1 >= len(argv):
            print("用法错误：--基线 需要一个路径参数", file=sys.stderr)
            return 2
        基线文件 = Path(argv[位置 + 1]).expanduser()

    位置参数: list[str] = []
    跳过下一个 = False
    for 项 in argv[1:]:
        if 跳过下一个:
            跳过下一个 = False
            continue
        if 项 == "--基线":
            跳过下一个 = True
            continue
        if 项.startswith("--"):
            continue
        位置参数.append(项)
    根 = Path(位置参数[0]).expanduser() if 位置参数 else 仓库根

    if 冻结:
        码, 说明 = 冻结基线(根, 基线文件)
        print(说明)
        return 码

    实际基线 = 基线文件 or 默认基线路径()
    违规, 留痕, 新增 = 运行冻结门禁(根, 实际基线)
    print(f"能力 id 冻结门禁：根={根} 基线={实际基线}（口径={基线口径}）")
    if 新增:
        print(f"[新增] 能力 id 新增 {len(新增)} 条（「只增不改」的合法方向，只报不拦）：")
        for 条 in 新增:
            print(f"  [{条['类型']}] 能力id={条['能力id']} 包={条['包']} 详情={条['详情']}")
    if 留痕:
        print(f"[留痕] 契约变更 {len(留痕)} 条（允许但需复核）：")
        for 条 in 留痕:
            print(f"  [{条['类型']}] 能力id={条['能力id']} 包={条['包']} 详情={条['详情']}")
    if not 违规:
        print("能力 id 冻结门禁通过：当前集 ⊇ 基线集，无 id 消失（只增不改成立）")
        return 0
    print(f"能力 id 冻结门禁失败：共 {len(违规)} 项违规")
    for 条 in 违规:
        print(f"[{条['缺口类型']}] 能力id={条['能力id']} 包={条['包']} "
              f"路径={条.get('路径', '')} 详情={条.get('详情', '')}")
    return 1


if __name__ == "__main__":
    sys.exit(主程序(sys.argv))
