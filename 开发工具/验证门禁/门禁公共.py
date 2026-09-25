"""验证门禁公共件：三个独立只读检查器共用的「扫描面 / 存量基线 / 空转即杀 / 退出码」骨架。

为什么要抽成公共件：三个检查器都要「按正式层名表收集源码 + 剪枝 + 冻结存量基线 +
扫描面为 0 判红 + 固定 0/1 退出码 + 打印 file:line」。各写一份就是三份会漂移的副本
（哲学 12.1「同一行代码只能一个结论」）。本文件**不含任何检查器判据**，
判据各自住在自己的文件里。

只读保证：本文件不写任何文件；基线只在显式 `--写基线` 时才落盘，且只写本门禁
自己的 `存量基线.json`。

口径（照 `开发工具/发布门禁/运行发布门禁.py::校验裸布尔防回潮` 的「按文件分桶」）：
  ① 命中的基线键 = `规则｜文件相对路径`（**不含行号**，避免行号漂移造成假新增）；
  ② 基线内 = 存量，只报不拦；基线外 = 新增，判红；
  ③ 基线文件缺失 / 坏 JSON / 不是对象 → 判红（fail-closed，不静默当无违规）；
  ④ 任一判据扫描面计数为 0 → 判红（哲学 1.4 空转即杀，不许报「通过」）；
  ⑤ 退出码唯一 0/1：0 = 无新增且扫描面非 0；1 = 其余一切（含超时、异常、基线不可用）。
"""

from __future__ import annotations

import ast
import json
import os
import signal
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

系统根 = next(
    祖先
    for 祖先 in Path(__file__).resolve().parents
    if (祖先 / "模块库").is_dir() and (祖先 / "测试中心").is_dir()
)
if str(系统根) not in sys.path:
    sys.path.insert(0, str(系统根))

# 唯一事实源，不本地另列（哲学 12.1）：
#   层名表      → `运行核心/依赖防火墙.py::层名称表`（含 公共契约/支持库/模块库/技能库/…/开发工具）
#   排除片段表  → `运行核心/依赖防火墙.py::排除片段表`（工程缓存=编译产物副本，实测占全仓 99.7%）
from 公共契约.基础类型.逻辑类型 import 假, 真  # noqa: E402
from 运行核心.依赖防火墙 import 层名称表, 排除片段表  # noqa: E402

正式层名表: tuple[str, ...] = tuple(层名称表)
剪枝目录表: frozenset[str] = frozenset(排除片段表)
门禁目录 = Path(__file__).resolve().parent
默认基线路径 = 门禁目录 / "存量基线.json"
墙钟上限秒 = 120
基线口径 = "文件+规则冻结：基线内只报不拦，基线外新增即判红；基线不可用判红（fail-closed）；扫描面为 0 判红"


class 门禁失败(RuntimeError):
    """门禁自身无法完成核验（超时 / 读不成 / 基线坏）：按判红处理，不当通过。"""


@dataclass
class 命中:
    """一条判据命中：精确到 文件:行号。"""

    规则: str
    文件: str
    行号: int
    详情: str = ""

    @property
    def 键(self) -> str:
        return f"{self.规则}｜{self.文件}"

    @property
    def 文本(self) -> str:
        尾 = f"  {self.详情}" if self.详情 else ""
        return f"{self.文件}:{self.行号}: [{self.规则}]{尾}"


@dataclass
class 检查结论:
    """一个检查器的完整结论：命中、扫描面、跳过面、判定。"""

    名称: str
    命中列表: list[命中] = field(default_factory=list)
    扫描面: dict[str, int] = field(default_factory=dict)
    跳过面: dict[str, int] = field(default_factory=dict)
    不可解析: list[str] = field(default_factory=list)
    新增: list[命中] = field(default_factory=list)
    存量: list[命中] = field(default_factory=list)
    可收敛: list[str] = field(default_factory=list)
    空扫描面规则: list[str] = field(default_factory=list)
    判定红: bool = 假
    判定理由: str = ""

    @property
    def 扫描面总数(self) -> int:
        return sum(self.扫描面.values())


def 收集源码(根: Path, 层名表: tuple[str, ...] | None = None) -> list[Path]:
    """按正式层名表收集 `.py`；进目录即剪枝 `排除片段表`（与依赖防火墙同口径）。

    剪枝用「目录名精确相等」而非子串命中：子串会连带剪掉文件名含该子串的真源码
    （同 `依赖防火墙.排除片段表` 的语义修正）。
    """
    出: list[Path] = []
    for 层名 in (层名表 if 层名表 is not None else 正式层名表):
        层目录 = 根 / 层名
        if not 层目录.is_dir():
            continue
        for 当前根, 子目录名表, 文件名表 in os.walk(层目录):
            子目录名表[:] = [名 for 名 in 子目录名表 if 名 not in 剪枝目录表]
            出 += [
                Path(当前根) / 名
                for 名 in 文件名表
                if 名.endswith(".py") and 名 not in 剪枝目录表
            ]
    return sorted(set(出))


def 相对路径(路径: Path, 根: Path) -> str:
    try:
        return 路径.relative_to(根).as_posix()
    except ValueError:
        return 路径.as_posix()


def 行号(源: str, 偏移: int) -> int:
    return 源[:偏移].count("\n") + 1


def 解析源码(路径: Path, 结论: 检查结论, 根: Path) -> ast.Module | None:
    """解析单份源码；读不成/语法错 → 记入「不可解析」并**判红**（读不成不等于没问题）。"""
    try:
        源码 = 路径.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as 错误:
        结论.不可解析.append(f"{相对路径(路径, 根)}: {type(错误).__name__}")
        return None
    try:
        return ast.parse(源码)
    except SyntaxError as 错误:
        结论.不可解析.append(f"{相对路径(路径, 根)}: 语法错误 行{错误.lineno}")
        return None


def 读基线(基线路径: Path, 检查器名: str) -> dict[str, dict]:
    """读本检查器在基线文件里的那一段；任何读不成的情形一律抛 `门禁失败`（fail-closed）。"""
    if not 基线路径.is_file():
        raise 门禁失败(f"存量基线不存在：{基线路径}（fail-closed，不得当作无违规）")
    try:
        全文 = json.loads(基线路径.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as 错误:
        raise 门禁失败(f"存量基线不可解析：{基线路径}（{type(错误).__name__}）") from 错误
    if not isinstance(全文, dict):
        raise 门禁失败(f"存量基线顶层不是对象：{基线路径}")
    段 = (全文.get("检查器") or {}).get(检查器名)
    if not isinstance(段, dict):
        raise 门禁失败(f"存量基线缺检查器段「{检查器名}」：{基线路径}")
    return 段


def 判定(结论: 检查结论, 基线段: dict[str, dict]) -> 检查结论:
    """按基线分桶：基线内=存量只报不拦；基线外=新增判红；扫描面为 0 判红。"""
    本次键集 = {条.键 for 条 in 结论.命中列表}
    结论.新增 = [条 for 条 in 结论.命中列表 if 条.键 not in 基线段]
    结论.存量 = [条 for 条 in 结论.命中列表 if 条.键 in 基线段]
    结论.可收敛 = sorted(键 for 键 in 基线段 if 键 not in 本次键集)
    结论.空扫描面规则 = [名 for 名, 数 in 结论.扫描面.items() if 数 <= 0]
    红项: list[str] = []
    if 结论.空扫描面规则:
        红项.append(f"扫描面为 0（空转即杀）：{'、'.join(结论.空扫描面规则)}")
    if 结论.不可解析:
        红项.append(f"{len(结论.不可解析)} 份源码不可解析（情况未知，不得当无违规）")
    if 结论.新增:
        红项.append(f"基线外新增 {len(结论.新增)} 条")
    结论.判定红 = 真 if 红项 else 假
    结论.判定理由 = "；".join(红项) if 红项 else (
        f"基线内 {len(结论.存量)} 条存量（只报不拦，只减不增）"
    )
    return 结论


def 打印结论(结论: 检查结论) -> None:
    """中文输出：扫描面（跳过面必须可见）→ 命中明细 → 分桶 → 结论。"""
    print(f"══ {结论.名称} ══")
    if 结论.扫描面:
        面 = "，".join(f"{名}={数}" for 名, 数 in sorted(结论.扫描面.items()))
        print(f"  扫描面：{面}（合计 {结论.扫描面总数}）")
    if 结论.跳过面:
        跳 = "，".join(f"{名}={数}" for 名, 数 in sorted(结论.跳过面.items()))
        print(f"  跳过面（显式声明，非静默）：{跳}")
    if 结论.不可解析:
        print(f"  不可解析 {len(结论.不可解析)} 份：{'；'.join(结论.不可解析[:5])}")
    if 结论.命中列表:
        print(f"  命中 {len(结论.命中列表)} 条：")
        for 条 in 结论.命中列表:
            print(f"    {条.文本}")
    else:
        print("  命中 0 条")
    if 结论.存量:
        print(f"  [存量] {len(结论.存量)} 条（基线内，只报不拦）：")
        for 条 in 结论.存量:
            print(f"    {条.文本}")
    if 结论.可收敛:
        print(f"  [可收敛] 基线有、本次未命中 {len(结论.可收敛)} 条（应下调基线）：")
        for 键 in 结论.可收敛[:10]:
            print(f"    {键}")
    if 结论.新增:
        print(f"  [新增] {len(结论.新增)} 条（判红）：")
        for 条 in 结论.新增:
            print(f"    {条.文本}")
    print(f"  结论：{'红' if 结论.判定红 else '绿'} —— {结论.判定理由}")


def 写基线段(基线路径: Path, 检查器名: str, 结论: 检查结论) -> None:
    """把当前命中冻结进基线（只写本门禁自己的基线文件）。"""
    全文: dict = {}
    if 基线路径.is_file():
        try:
            读回 = json.loads(基线路径.read_text(encoding="utf-8"))
            if isinstance(读回, dict):
                全文 = 读回
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            全文 = {}
    全文.setdefault("口径", 基线口径)
    全文.setdefault("检查器", {})[检查器名] = {
        条.键: {"行号": 条.行号, "详情": 条.详情} for 条 in 结论.命中列表
    }
    # 落盘走**唯一写腿**（`文件系统支持库.文件操作.写入文件`），不裸 `write_text`：
    # 该腿自带「内核只读锁的解锁窗口」与写入凭证判据（受管路径须被一条活跃写租约覆盖）；
    # 裸写会在整仓内核只读锁下被内核以 `Operation not permitted` 拒 ——
    # `开发工具/全量重算摘要.py` 2026-09-23 因**同一根因**已改走写腿，本处是同一形态的
    # 漏改处（2026-09-26 补齐）：改前 `--写基线` 出口在锁下**结构性不可用**（实测 EPERM）。
    # 无凭证 / 无租约时该腿 fail-closed（`确保成功` 抛出，错误说明自带可照抄的
    # `开工即占` 调用），不静默降级、不退回裸写。
    from 支持库.后端.文件系统支持库.文件操作 import 写入文件
    写入文件(
        str(基线路径), json.dumps(全文, ensure_ascii=False, indent=1) + "\n"
    ).确保成功()


def 读文件相对路径参数(argv: list[str]) -> tuple[Path, Path, bool, bool]:
    """解析 `--根 / --基线 / --写基线 / --自证`；默认根=系统根、基线=默认基线路径。"""
    根 = 系统根
    基线路径 = 默认基线路径
    写 = 假
    自证 = 假
    下标 = 0
    while 下标 < len(argv):
        项 = argv[下标]
        if 项 == "--根" and 下标 + 1 < len(argv):
            根 = Path(argv[下标 + 1]).resolve()
            下标 += 2
            continue
        if 项 == "--基线" and 下标 + 1 < len(argv):
            基线路径 = Path(argv[下标 + 1]).resolve()
            下标 += 2
            continue
        if 项 == "--写基线":
            写 = 真
            下标 += 1
            continue
        if 项 == "--自证":
            自证 = 真
            下标 += 1
            continue
        下标 += 1
    return 根, 基线路径, 写, 自证


def 墙钟守卫(秒数: int = 墙钟上限秒) -> None:
    """自设墙钟上限：超时抛 `门禁失败`（按判红处理，绝不按通过处理）。"""

    def _超时(_信号, _帧) -> None:
        raise 门禁失败(f"墙钟超时（>{秒数}秒），按判红处理，绝不按通过处理")

    if hasattr(signal, "SIGALRM"):
        signal.signal(signal.SIGALRM, _超时)
        signal.alarm(int(秒数))


def 取消墙钟守钟() -> None:
    if hasattr(signal, "SIGALRM"):
        signal.alarm(0)


def 跑标准主流程(
    检查器名: str,
    结论构建函数,
    argv: list[str] | None = None,
) -> int:
    """标准主流程：解析参数 → 跑判据 → 读基线 → 判定 → 打印 → 写基线（可选）→ 退出码。"""
    实参 = list(sys.argv[1:] if argv is None else argv)
    根, 基线路径, 要写基线, _自证 = 读文件相对路径参数(实参)
    开始 = time.monotonic()
    try:
        墙钟守卫()
        结论 = 结论构建函数(根)
        if 要写基线:
            写基线段(基线路径, 检查器名, 结论)
            print(f"已写基线段「{检查器名}」→ {基线路径}（{len(结论.命中列表)} 条）")
            结论 = 判定(结论, {条.键: {} for 条 in 结论.命中列表})
        else:
            结论 = 判定(结论, 读基线(基线路径, 检查器名))
        打印结论(结论)
        绿 = not 结论.判定红
        print(f"  耗时 {time.monotonic() - 开始:.2f}s；退出码 {0 if 绿 else 1}")
        return 0 if 绿 else 1
    except 门禁失败 as 错误:
        print(f"══ {检查器名} ══")
        print(f"  结论：红 —— {错误}（fail-closed）")
        print("  退出码 1")
        return 1
    except Exception as 错误:  # noqa: BLE001 —— 只用于「未知异常也必须判红」这一处兜底
        print(f"══ {检查器名} ══")
        print(f"  结论：红 —— 门禁自身异常 {type(错误).__name__}: {错误}（fail-closed）")
        print("  退出码 1")
        return 1
    finally:
        取消墙钟守钟()


def 新建夹具根(前缀: str) -> Path:
    import tempfile

    return Path(tempfile.mkdtemp(prefix=前缀))
