"""调用参数账：**入参形状/样例的规范化** + **按 (能力id, 形状) 计数**的 SQLite 账（各一处唯一实现）。

华哥 2026-09-21 定口径：「你这个账本用 db 不行吗？本质上参数组合是唯一值，每一次访问同一个
参数自 +1，然后返回的时候直接排序返回不就完了？」——本文件就是那个 db：
**主键 (能力id, 入参形状)，每调一次 `记一次调用` 自增 1，读的时候 `ORDER BY 调用次数 DESC`**。
比「每次查询重扫全账本再分组」少一次 O(N) 全表扫描，而且计数是**全时段精确值**，
不是「尾部窗口内的近似值」（重扫方案只能看最近 2000 条，得在返回里挂一句口径说明）。

为什么住公共契约（哲学第 1 条 2 项「同一件事两套实现即缺陷」）：
**写方在 `运行核心/统一网关`**（每条请求自增一次），**读方在 `模块库/能力目录`**
（`搜索能力` 与 `常用参数组合` 都要读）。`模块库` 按分层**不许** import `运行核心`
（实测：模块库对 运行核心 的 import 数为 0，平台控制面对它是允许的），
而两边都能依赖的只有 `公共契约` —— 故形状口径、表结构、读写都只在这里定义一次。
若各写一份，键的算法规格、样例截断长度必然走偏，统计出来的「常用参数」就是两拨对不上的数据。

落点与失败口径照 `运行核心/统一网关/运行态/幂等存储.py` 的既有模式：
独立库文件落平台运行数据目录、**每次操作开一条短连接**（不做跨线程共享连接，故不需额外锁）、
**fail-soft**（库打不开或读写失败一律当作「没这条统计」，只记忽略留痕，绝不反噬主调用）。
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Mapping

from 公共契约.基础类型.逻辑类型 import 真, 假
from 公共契约.诊断.忽略记录 import 记录忽略
from 公共契约.运行时.运行缓存 import 解析运行数据根

#: 调用参数账的库文件名（落 `<运行数据根>/` 下，与 权威状态.db / 网关幂等.sqlite3 同级）。
参数账文件名 = "调用参数账.sqlite3"
#: 单个文本值的**入库上限**（字符）：超过即折叠为 `<文本 N 字>`。
样例文本上限 = 80
#: 入参样例的**整串上限**（字符）：超过即截断并标注，保证单行有界。
样例整串上限 = 600
#: 单个能力最多记多少条入参键（防止一次调用带巨量键）。
样例键数上限 = 40
#: 表名。
表名 = "调用参数账"

建表语句 = (
    f"CREATE TABLE IF NOT EXISTS {表名} ("
    "能力id TEXT NOT NULL, "
    "入参形状 TEXT NOT NULL, "
    "调用次数 INTEGER NOT NULL DEFAULT 0, "
    "最近时间 REAL NOT NULL, "
    "样例 TEXT NOT NULL DEFAULT '', "
    "PRIMARY KEY (能力id, 入参形状))"
)
#: 按次数倒序取前 N 走索引，避免全表扫。
索引语句 = f"CREATE INDEX IF NOT EXISTS {表名}_次数 ON {表名}(能力id, 调用次数 DESC)"


def 参数账路径(系统根目录: Path | str | None = None) -> Path:
    """调用参数账库文件路径（`<运行数据根>/调用参数账.sqlite3`）。

    `系统根目录` 缺省按本文件位置推导（`<系统根>/公共契约/诊断/`）；
    制品态由唯一解析器识别并改道平台受管缓存，源码态 = `<系统根>/工程缓存/运行数据`。
    """
    if 系统根目录 is None:
        根 = Path(__file__).resolve().parents[2]
    else:
        根 = Path(系统根目录)
    return 解析运行数据根(根) / 参数账文件名


def 类型名(值: Any) -> str:
    """按 16 个正式类型名给一个**入参值**定性（形状统计用，不做契约校验）。

    `bool` 必须先于 `int` 判：Python 里 bool 是 int 子类，否则 `真` 会被记成 `整数型`，
    与契约声明的 `逻辑型` 对不上。
    """
    if isinstance(值, bool):
        return "逻辑型"
    if isinstance(值, int):
        return "整数型"
    if isinstance(值, float):
        return "双精度数型"
    if isinstance(值, str):
        return "文本型"
    if isinstance(值, (bytes, bytearray)):
        return "字节集型"
    if isinstance(值, (list, tuple)):
        return "列表型"
    if isinstance(值, Mapping):
        return "字典型"
    if 值 is None:
        return "空值型"
    return "JSON值型"


def 入参形状(参数: Any) -> str:
    """入参的**形状串**：`键:类型` 按键名升序、以 `|` 连接（如 `远端:文本型|超时秒:双精度数型`）。

    形状是计数账的**分组键**：同一形状的调用在格式上等价，调用方照任一条抄都不会错。
    非字典或空入参返回空串（该次调用不入账）。
    """
    if not isinstance(参数, Mapping) or not 参数:
        return ""
    return "|".join(f"{键}:{类型名(参数[键])}" for 键 in sorted(参数, key=lambda 键: str(键)))


def _压值(值: Any) -> Any:
    """把单个值压成**有界**的可入库形态（长文本折叠，容器只留规模）。"""
    if isinstance(值, str):
        return 值 if len(值) <= 样例文本上限 else f"<文本 {len(值)} 字>"
    if isinstance(值, (bytes, bytearray)):
        return f"<字节集 {len(值)} 字节>"
    if isinstance(值, (list, tuple)):
        return [f"<列表 {len(值)} 项>"]
    if isinstance(值, Mapping):
        return {f"<字典 {len(值)} 键>": 真}
    if isinstance(值, (bool, int, float)) or 值 is None:
        return 值
    return f"<{type(值).__name__}>"


#: **不落值的键名**（2026-09-23 安全收口）：命中即只存占位，绝不把真实取值写进库。
#:
#: 为什么在**本层**做、而不转调 `运行核心/运行诊断/运行事件/脱敏工具`：本模块住 `公共契约`
#: （最底层），脱敏腿住 `运行核心` —— 本层对上层 import 数为 0（见文件头部「为什么住公共契约」：
#: 模块库不许 import 运行核心，公共契约是唯一共同依赖）。从本层 import 上层即**向上依赖**，
#: 属分层违规。故此处只落「明显是凭证的键名不存值」这条**入库策略**，
#: **不复制**脱敏腿的模式规则（复制即第二套实现，哲学第 1 条 2 项）。
#:
#: **未覆盖（如实声明，不假装已解决）**：值与键名无关的凭证（如 `{"输入": "sk-live-…"}`）
#: 本条挡不住 —— 那要按**值特征**脱敏，须先把脱敏腿下移到本层或本层以下（属分层调整，不在本次范围）。
#: 判据：`strings 工程缓存/运行数据/调用参数账.sqlite3 | grep -c 'sk-'`。
敏感键名 = (
    "api_key", "apikey", "token", "secret", "password", "passwd", "pwd",
    "authorization", "auth", "credential", "private_key", "access_key",
    "密钥", "凭证", "口令", "密码", "令牌", "私钥",
)


def _样例值(键: str, 值: Any) -> Any:
    """单键样例取值：命中 `敏感键名` 只回占位，其余照旧走 `_压值`（长文本折叠）。"""
    小写 = 键.strip().lower()
    if any(词 in 小写 for 词 in 敏感键名):
        return "<已省略：疑似凭证>"
    return _压值(值)


def 入参样例(参数: Any) -> str:
    """入参的**样例串**：真实取值（长文本折叠、**疑似凭证省略**）的紧凑 JSON，整串有界。

    留真实取值而不是只留形状：调用方看 `{"远端": "origin", "超时秒": 120}` 一眼就知道
    怎么传；只看形状还得回去翻契约。样例**只作展示，不作校验依据**。

    ★ 2026-09-23 安全收口：改前**任何键**都把真实取值落库 —— 实测库里存在明文
    `api_key: sk-…`、`密钥b64` 等，且 `查常用参数` 能原样读回（等于明文凭证可回放）。
    现按 `敏感键名` 只存占位。口径边界见 `敏感键名` 的「未覆盖」段，不夸大。
    """
    if not isinstance(参数, Mapping) or not 参数:
        return ""
    键表 = sorted(参数, key=lambda 键: str(键))[:样例键数上限]
    紧凑 = {str(键): _样例值(str(键), 参数[键]) for 键 in 键表}
    文本 = json.dumps(紧凑, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return 文本 if len(文本) <= 样例整串上限 else 文本[:样例整串上限] + "…（已截断）"


class 调用参数账:
    """调用参数计数账（SQLite，fail-soft）。

    只在**热路径**做两件事：`记一次调用`（一条 UPSERT 自增）、`查常用参数`（一条带 LIMIT 的
    ORDER BY）。两者都短连接、都不抛异常 —— 统计是旁路，反噬主调用即事故。
    """

    def __init__(self, 库路径: Path | str | None = None) -> None:
        self.库路径 = Path(库路径) if 库路径 is not None else 参数账路径()
        self.写入失败数 = 0
        self.读取失败数 = 0
        self._已建表 = 假
        self._锁 = threading.Lock()

    def _连接(self) -> sqlite3.Connection:
        库 = sqlite3.connect(str(self.库路径), timeout=5.0)
        if not self._已建表:
            with self._锁:
                if not self._已建表:
                    库.execute(建表语句)
                    库.execute(索引语句)
                    库.commit()
                    self._已建表 = 真
        return 库

    def 记一次调用(self, 能力id: str, 参数: Any) -> bool:
        """把一次调用的入参形状计入账（同形状自增 1，并刷新最近时间与样例）。

        返回是否真的落库；**失败不抛**（调用方在网关热路径上，不许被统计拖垮）。
        """
        形状 = 入参形状(参数)
        标识 = str(能力id or "").strip()
        if not 形状 or not 标识:
            return 假
        try:
            self.库路径.parent.mkdir(parents=True, exist_ok=True)
            库 = self._连接()
            try:
                库.execute(
                    f"INSERT INTO {表名} (能力id, 入参形状, 调用次数, 最近时间, 样例) "
                    "VALUES (?, ?, 1, ?, ?) "
                    "ON CONFLICT(能力id, 入参形状) DO UPDATE SET "
                    "调用次数 = 调用次数 + 1, 最近时间 = excluded.最近时间, 样例 = excluded.样例",
                    (标识, 形状, time.time(), 入参样例(参数)),
                )
                库.commit()
            finally:
                库.close()
            return 真
        except (sqlite3.Error, OSError) as 错误:
            self.写入失败数 += 1
            记录忽略("调用参数账", f"入参计数失败: {type(错误).__name__}: {错误}")
            return 假

    def 查常用参数(self, 能力id: str = "", 上限: int = 5) -> dict[str, Any]:
        """按调用次数倒序取前 N 组；`能力id` 为空则跨能力取（按能力分段，每段前 N 组）。

        失败时返回**空组合**并如实带上 `问题`（不抛、不编造）——
        「一组都没有」与「账读不出来」是两件事，调用方据 `问题` 区分。
        """
        保留数 = max(1, int(上限))
        标识 = str(能力id or "").strip()
        结果: dict[str, Any] = {
            "能力id": 标识, "上限": 保留数, "组合数": 0,
            "命中能力数": 0, "常用参数组合": [], "问题": "",
        }
        try:
            if not self.库路径.exists():
                # 库还没建 = **如实**「没有记录」（上线后从没被调用过），不是错误。
                return 结果
            if not self.库路径.is_file():
                # 路径存在但不是文件（被目录/别的对象占了）＝ 坏状态，必须如实报出来；
                # 与「没记录」混为一谈会让坏状态永远无声（实测踩过：本判据缺位时，
                # 库路径被占成目录仍回「没有问题」，与「没调用过」完全同形）。
                结果["问题"] = f"调用参数账路径不是文件（{self.库路径}）；不是「没有记录」"
                return 结果
            库 = self._连接()
            try:
                库.row_factory = sqlite3.Row
                if 标识:
                    行表 = 库.execute(
                        f"SELECT 能力id, 入参形状, 调用次数, 最近时间, 样例 FROM {表名} "
                        "WHERE 能力id = ? ORDER BY 调用次数 DESC, 入参形状 ASC LIMIT ?",
                        (标识, 保留数),
                    ).fetchall()
                    总数 = 库.execute(
                        f"SELECT COUNT(*) FROM {表名} WHERE 能力id = ?", (标识,)
                    ).fetchone()[0]
                else:
                    行表 = 库.execute(
                        f"SELECT 能力id, 入参形状, 调用次数, 最近时间, 样例 FROM {表名} "
                        "ORDER BY 能力id ASC, 调用次数 DESC, 入参形状 ASC",
                    ).fetchall()
                    总数 = 库.execute(f"SELECT COUNT(*) FROM {表名}").fetchone()[0]
            finally:
                库.close()
        except (sqlite3.Error, OSError) as 错误:
            self.读取失败数 += 1
            记录忽略("调用参数账", f"常用参数读取失败: {type(错误).__name__}: {错误}")
            结果["问题"] = f"调用参数账不可读（{type(错误).__name__}）；不是「没有记录」"
            return 结果

        条目表 = [
            {
                "能力id": 行["能力id"], "入参形状": 行["入参形状"],
                "调用次数": int(行["调用次数"]),
                "样例": 行["样例"],
                "最近时间": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(行["最近时间"])),
            }
            for 行 in 行表
        ]
        if 标识:
            命中 = 条目表[:保留数]
        else:
            按能力: dict[str, list[dict]] = {}
            for 条 in 条目表:
                按能力.setdefault(条["能力id"], []).append(条)
            命中 = [条 for 组 in 按能力.values() for 条 in 组[:保留数]]
        结果.update({
            "组合数": int(总数), "命中能力数": len({条["能力id"] for 条 in 命中}),
            "常用参数组合": 命中,
        })
        return 结果


def 记一次调用(能力id: str, 参数: Any, *, 库路径: Path | str | None = None) -> bool:
    """便捷入口：一次性计数（内部建实例；网关热路径用实例方法避免重复建表判断）。"""
    return 调用参数账(库路径).记一次调用(能力id, 参数)


def 查常用参数(能力id: str = "", 上限: int = 5,
               *, 库路径: Path | str | None = None) -> dict[str, Any]:
    """便捷入口：查某能力最常用的参数组合。"""
    return 调用参数账(库路径).查常用参数(能力id, 上限)


__all__ = [
    "参数账文件名", "样例文本上限", "样例整串上限", "样例键数上限",
    "表名", "建表语句", "索引语句",
    "参数账路径", "类型名", "入参形状", "入参样例",
    "调用参数账", "记一次调用", "查常用参数",
]
