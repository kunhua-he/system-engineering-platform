"""完整性摘要唯一生成器与校验器：文件清单 sha256 格式为唯一权威。

正式包 完整性摘要.json 只允许一种格式：
{
  "包id": ...,
  "版本": ...,
  "摘要算法": "sha256",
  "文件清单": [{"路径": ..., "sha256": ...}, ...]
}
生成时排除 完整性摘要.json 自身与 __pycache__ 缓存，保证可重复生成。
旧"能力数/能力清单"格式或缺失 文件清单 的输入一律校验失败（拒绝漂移）。

B-14（2026-09-17 收口）：能力派生字段（能力数/能力清单/能力定义摘要）**写入后必须回读对账**。
修前它们只有写者、全仓无读者，属"声明了字段却没人校验"。现在 ``校验完整性摘要`` 用同一个
派生函数（``生成能力派生字段``）重算并逐字比对，口径三条：可派生 ⇒ 三字段必须齐全且相等；
存在定义但派生不出 ⇒ 判红（不当作"没有派生字段"）；无定义却带派生字段 ⇒ 判红。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Iterable

from 公共契约.基础类型.逻辑类型 import 真, 假

摘要文件名 = "完整性摘要.json"
排除目录名 = {"__pycache__", "工程缓存"}
排除文件后缀 = {".pyc", ".pyo"}
排除文件名 = {摘要文件名, ".DS_Store"}


def 是否应当收录(文件: Path, 包目录: Path) -> bool:
    """文件是否属于正式包内容（排除摘要自身与缓存）。"""
    if not 文件.is_file() or 文件.name in 排除文件名:
        return 假
    相对路径 = 文件.relative_to(包目录)
    if any(部分 in 排除目录名 for 部分 in 相对路径.parts):
        return 假
    return 文件.suffix not in 排除文件后缀


def 计算文件摘要(文件: Path) -> str:
    """以分块方式计算文件的完整 SHA-256。"""
    摘要器 = hashlib.sha256()
    with 文件.open("rb") as 文件流:
        while 数据块 := 文件流.read(1024 * 1024):
            摘要器.update(数据块)
    return 摘要器.hexdigest()


def 生成能力派生字段(包目录: Path) -> dict[str, Any] | None:
    """能力派生字段的**唯一派生者**：由 ``能力定义.json`` 算出 ``能力数/能力清单/能力定义摘要``。

    读不成 / 不是对象 / 能力列表形状不合法时返回 ``None``——**不静默降级成空值集**：
    「读不到」与「这个包真没有能力」是两件事，压成同一个空集就是 B-14 那条病根
    （派生字段无人校验，且读写两侧各自解释）。``生成完整性摘要`` 与 ``校验完整性摘要``
    共用本函数，保证「写进去的」与「回读比对的」是同一条算式。
    """
    定义路径 = 包目录 / "能力定义.json"
    if not 定义路径.is_file():
        return None
    try:
        定义 = json.loads(定义路径.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, UnicodeDecodeError):
        return None
    if not isinstance(定义, dict):
        return None
    能力列表 = 定义.get("能力列表")
    if not isinstance(能力列表, list):
        return None
    清单: list[str] = []
    for 能力 in 能力列表:
        if not isinstance(能力, dict):
            continue
        能力id = 能力.get("能力id")
        if isinstance(能力id, str) and 能力id:
            清单.append(能力id)
    return {
        "能力数": len(能力列表),
        "能力清单": 清单,
        "能力定义摘要": hashlib.sha256(
            json.dumps(定义, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()[:16],
    }


def 生成完整性摘要(包目录: Path, *, 包id: str, 版本: str) -> dict[str, Any]:
    """生成完整性摘要（**唯一生成器**：路径有序、与时间无关）。

    能力字段（能力数/能力清单/能力定义摘要）也由本函数产出，保证全平台只有一种形状——
    原先编译器在委托本函数后自行追加字段，导致"编译器写的摘要"与"重算的摘要"形状不一，
    依赖生命周期审计按唯一生成器重算即报「摘要漂移」（2026-09-15 审计修复）。
    """
    文件列表 = sorted(
        (文件 for 文件 in 包目录.rglob("*") if 是否应当收录(文件, 包目录)),
        key=lambda 文件: 文件.relative_to(包目录).as_posix(),
    )
    if not 文件列表:
        raise ValueError(f"包内没有可纳入摘要的正式文件: {包目录}")
    数据: dict[str, Any] = {
        "包id": 包id,
        "版本": 版本,
        "摘要算法": "sha256",
        "文件清单": [
            {
                "路径": 文件.relative_to(包目录).as_posix(),
                "sha256": 计算文件摘要(文件),
            }
            for 文件 in 文件列表
        ],
    }
    定义路径 = 包目录 / "能力定义.json"
    if 定义路径.is_file():
        派生 = 生成能力派生字段(包目录)
        if 派生 is not None:
            数据.update(派生)
    return 数据


def 校验能力派生字段(包目录: Path, 摘要: dict[str, Any]) -> list[str]:
    """回读对账 ``能力数/能力清单/能力定义摘要``（B-14）。

    修前这三个字段**只有写者没有读者**：``生成完整性摘要`` 写、全仓无任何校验者读，
    于是「能力定义改了、摘要里的派生字段没跟」「派生字段被手改成别的数」都无人发现。
    判据三条，全部 fail-closed（判不出即不通过）：

    ① ``能力定义.json`` 存在且可派生 ⇒ 三个派生字段必须**齐全且逐字相等**；
       缺一个字段即算漂移（生成侧对可读的定义一定写满三个字段）；
    ② ``能力定义.json`` 存在但派生不出（不可读/形状坏）⇒ 判红并点名异常原因，
       **不得**当作「这个包没有派生字段」放过；
    ③ ``能力定义.json`` 不存在却带着派生字段 ⇒ 判红（字段无来源，必是漂移或误拷）。
    """
    声明派生键 = ("能力数", "能力清单", "能力定义摘要")
    存在键 = [键 for 键 in 声明派生键 if 键 in 摘要]
    定义路径 = 包目录 / "能力定义.json"
    派生 = 生成能力派生字段(包目录)
    if 派生 is None:
        if 存在键:
            return [f"派生字段存在但 能力定义.json 缺失或不可派生（无法回读对账: {存在键}）"]
        return []
    缺失 = [键 for 键 in 声明派生键 if 键 not in 摘要]
    if 缺失:
        return [f"能力派生字段缺失: {缺失}"]
    问题: list[str] = []
    for 键 in 声明派生键:
        if 摘要.get(键) != 派生[键]:
            问题.append(f"能力派生字段与能力定义不一致: {键}")
    return 问题


def 校验完整性摘要(包目录: Path) -> tuple[bool, list[str]]:
    """校验包目录 完整性摘要.json 与真实文件闭合。

    拒绝：缺摘要/非 JSON/缺 文件清单 或为空（旧"能力数"格式）/
    摘要算法不合法/包id或版本与声明不一致/路径越界/清单文件不存在/
    文件摘要不一致/清单不闭合（未登记或多余）。
    """
    问题列表: list[str] = []
    摘要路径 = 包目录 / 摘要文件名
    if not 摘要路径.is_file():
        return 假, ["缺少 完整性摘要.json"]
    try:
        摘要 = json.loads(摘要路径.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as 错误:
        return 假, [f"摘要不可读: {错误}"]
    文件清单 = 摘要.get("文件清单")
    if not isinstance(文件清单, list) or not 文件清单:
        return 假, ["文件清单缺失或为空（旧'能力数'格式或空清单；文件清单为唯一权威格式）"]
    # 原判据放行「没有 摘要算法 字段」的摘要（`not in (None, "sha256")`），
    # 与本文档串「只允许一种格式」相冲：一份不带算法声明的摘要能被当成
    # sha256 通过，将来换成别的算法也无从发现。全仓 120 份 摘要文件实测
    # 摘要算法 全部为 "sha256"（无缺省），故收紧为必须显式声明。
    if 摘要.get("摘要算法") != "sha256":
        return 假, [f"摘要算法不合法: {摘要.get('摘要算法') or '未声明（必须显式声明 sha256）'}"]
    声明路径 = 包目录 / "包声明.json"
    if 声明路径.is_file():
        try:
            声明 = json.loads(声明路径.read_text(encoding="utf-8"))
            if 摘要.get("包id") != 声明.get("包id") or 摘要.get("版本") != 声明.get("版本"):
                return 假, ["摘要中的包id或版本与包声明不一致"]
        except (json.JSONDecodeError, OSError):
            return 假, ["包声明.json 不可读"]
    声明路径集合: set[str] = set()
    包目录解析 = 包目录.resolve()
    for 条目 in 文件清单:
        if not isinstance(条目, dict):
            return 假, ["文件清单条目必须包含路径和sha256"]
        相对路径 = str(条目.get("路径", ""))
        期望摘要 = str(条目.get("sha256", "")).lower()
        # 原实现只要求 ≥16 位十六进制，再用 startswith 比对：一个**截断到 16 位
        # 的摘要**（64 位熵）就能代表整份文件被认定为「一致」，等于允许弱摘要
        # 冒充 sha256。唯一的写入者 生成完整性摘要 产出的就是 64 位 hexdigest
        # （全仓 2520 条实测全为 64 位），故要求完整长度 + 全十六进制 + 精确相等。
        if (not 相对路径 or len(期望摘要) != 64
                or any(字符 not in "0123456789abcdef" for 字符 in 期望摘要)):
            return 假, [f"文件清单条目不完整（sha256 必须为 64 位十六进制）: {相对路径 or '缺少路径'}"]
        文件 = (包目录 / 相对路径).resolve()
        try:
            文件.relative_to(包目录解析)
        except ValueError:
            return 假, [f"文件路径越界: {相对路径}"]
        if not 文件.is_file():
            return 假, [f"清单文件不存在: {相对路径}"]
        实际摘要 = hashlib.sha256(文件.read_bytes()).hexdigest()
        if 实际摘要 != 期望摘要:
            return 假, [f"文件摘要不一致: {相对路径}"]
        声明路径集合.add(Path(相对路径).as_posix())
    实际路径集合 = {
        文件.relative_to(包目录).as_posix()
        for 文件 in 包目录.rglob("*")
        if 文件.is_file() and 是否应当收录(文件, 包目录)
    }
    缺少清单 = sorted(实际路径集合 - 声明路径集合)
    多余清单 = sorted(声明路径集合 - 实际路径集合)
    if 缺少清单 or 多余清单:
        return 假, [f"清单不闭合: 未登记{缺少清单[:3]} 多余{多余清单[:3]}"]
    # B-14：能力派生字段回读对账（能力数/能力清单/能力定义摘要）。
    # 修前这三个字段只有 生成完整性摘要 一个写者、全仓零读者：能力定义改了摘要没跟、
    # 字段被手改、字段整块缺失，三种漂移都无人发现。判据见 校验能力派生字段。
    问题列表.extend(校验能力派生字段(包目录, 摘要))
    return (not 问题列表), 问题列表


def 扫描正式包(系统根: Path) -> list[Path]:
    """查找全部拥有包声明的正式包目录（**含聚合视图父包**）。

    口径唯一来自 `公共契约.正式根`（`全仓口径`：全正式根 + 含聚合视图父包）：
    本函数要的是「哪些目录有 `包声明.json`」——完整性摘要、说明书每个包声明
    目录都有一份，聚合视图父包**必须**含在内（`开发文档/项目证据/说明书白名单.json`
    的 6 个聚合父包就靠这条进账）。此前本函数自带一份 `rglob` + 只读 `存在根名`，
    与装配口径的差别没有写明白，是债务 #38 的分叉面之一。
    """
    from 公共契约.正式根 import 全仓口径, 枚举包目录

    return 枚举包目录(系统根, 全仓口径)



def 迁移旧格式摘要(系统根: Path, 排除路径: Iterable[Path] = ()) -> list[Path]:
    """扫描全仓正式包，旧格式（缺/空 文件清单）或内容漂移用唯一生成器重算。

    排除路径内的包不参与重算，供并发写盘期间避让。
    返回重算写入的摘要路径列表。
    """
    排除集 = {Path(路径).resolve() for 路径 in 排除路径}
    重算列表: list[Path] = []
    for 包目录 in 扫描正式包(系统根):
        if 包目录.resolve() in 排除集:
            continue
        通过, _ = 校验完整性摘要(包目录)
        if 通过:
            continue
        声明路径 = 包目录 / "包声明.json"
        try:
            声明 = json.loads(声明路径.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            声明 = {}
        摘要 = 生成完整性摘要(
            包目录,
            包id=声明.get("包id", 包目录.name),
            版本=声明.get("版本", "1.0.0"),
        )
        摘要路径 = 包目录 / 摘要文件名
        摘要路径.write_text(
            json.dumps(摘要, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        重算列表.append(摘要路径)
    return 重算列表
