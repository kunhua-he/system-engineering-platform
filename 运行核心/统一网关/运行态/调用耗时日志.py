"""调用耗时日志：记录经网关的能力调用耗时，慢调用分级留痕（华哥 2026-09-21 裁决）。

华哥原话：

> 「html 需要加上一个调用时间的日志，就是耗时多少，超过 10 秒的需要优化，
>   超过 3 秒的可以考虑优化。尽量控制住所有时间，最优的方式仍然是亚秒级或者是毫秒级。」

**为什么要有它**：耗时此前只在响应信封里回一次（`耗时毫秒`），调用方看过就没了 ——
没人能回答「平台里哪些能力慢、慢在哪」，优化就永远靠感觉。本模块把慢调用**留痕**，
让「哪里该优化」变成可查的事实。

**本模块只记录，不裁决**（哲学 1.1 结果唯一）：判「超标」以及给出加速方向（八项
加速方式表）的唯一实现是能力 `数据操作支持库.度量.判定耗时超标`，本模块**不复制**
那套判据与话术。这里的 `等级` 只是**日志分级**（用来筛选与排序），不是优化裁决。

**热路径成本**：只有达到 `考虑优化秒` 的调用才落盘 —— 亚秒级调用（平台绝大多数，
实测网关 60 路并发平均 62ms）零开销，不加锁、不写盘、不分配。

**有界**：内存环形 + 文件行数上限（超出按「留新弃旧」重写），不无界增长。
"""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any

#: 分级阈值（秒）。默认取华哥 2026-09-21 口径；可经环境变量覆盖，便于按机器调整。
#: 注意：这是**日志分级**，不是「超标」裁决 —— 裁决在 `判定耗时超标`（默认 5 秒）。
默认考虑优化秒 = 3.0
默认必须优化秒 = 10.0
环境变量_考虑优化秒 = "系统底座_耗时日志_考虑优化秒"
环境变量_必须优化秒 = "系统底座_耗时日志_必须优化秒"
#: 落盘文件名（落在受管缓存根之下，不裸拼路径）。
日志文件名 = "调用耗时日志.jsonl"
#: 内存环形上限与文件行数上限（超出按「留新弃旧」重写，明细有界）。
内存上限 = 200
文件行数上限 = 2000


def _秒值(环境变量: str, 缺省: float) -> float:
    原文 = os.environ.get(环境变量, "").strip()
    if not 原文:
        return 缺省
    try:
        值 = float(原文)
    except ValueError:
        return 缺省
    return 值 if 值 > 0 else 缺省


def 阈值秒() -> tuple[float, float]:
    """返回 `(考虑优化秒, 必须优化秒)`；两者顺序错乱时自动纠正（必须 ≥ 考虑）。"""
    考虑 = _秒值(环境变量_考虑优化秒, 默认考虑优化秒)
    必须 = _秒值(环境变量_必须优化秒, 默认必须优化秒)
    return (考虑, 必须) if 必须 >= 考虑 else (考虑, 考虑)


def _定级(耗时秒: float, 考虑秒: float, 必须秒: float) -> str:
    if 耗时秒 >= 必须秒:
        return "必须优化"
    if 耗时秒 >= 考虑秒:
        return "考虑优化"
    return "正常"


class 调用耗时日志:
    """线程安全的慢调用留痕（内存环形 + JSONL 追加）。"""

    def __init__(self, 日志路径: Path | str | None = None) -> None:
        self.日志路径 = Path(日志路径) if 日志路径 is not None else None
        self._锁 = threading.Lock()
        self._内存: list[dict[str, Any]] = []
        self._已写行数 = 0

    # ── 写入 ──────────────────────────────────────────────────

    def 记录(self, *, 能力id: str = "", 操作: str = "", 耗时毫秒: float = 0.0,
             成功: bool = True, 错误码: str = "") -> dict[str, Any] | None:
        """记录一次调用；未达「考虑优化」阈值直接返回 None（热路径零开销）。"""
        考虑秒, 必须秒 = 阈值秒()
        耗时秒 = max(0.0, float(耗时毫秒) / 1000.0)
        等级 = _定级(耗时秒, 考虑秒, 必须秒)
        if 等级 == "正常":
            return None
        条目 = {
            "时间": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
            "能力id": str(能力id)[:120],
            "操作": str(操作)[:32],
            "耗时毫秒": round(float(耗时毫秒), 1),
            "耗时秒": round(耗时秒, 3),
            "等级": 等级,
            "成功": bool(成功),
            "错误码": str(错误码)[:40],
            "阈值": {"考虑优化秒": 考虑秒, "必须优化秒": 必须秒},
        }
        with self._锁:
            self._内存.append(条目)
            if len(self._内存) > 内存上限:
                del self._内存[:-内存上限]
            self._追加落盘(条目)
        return 条目

    def _追加落盘(self, 条目: dict[str, Any]) -> None:
        """追加一行；失败只吞掉（日志是观测面，绝不能因为它把请求搞失败）。"""
        路径 = self.日志路径
        if 路径 is None:
            return
        try:
            路径.parent.mkdir(parents=True, exist_ok=True)
            if self._已写行数 >= 文件行数上限:
                self._重写为最新一半()
            with 路径.open("a", encoding="utf-8") as 文件:
                文件.write(json.dumps(条目, ensure_ascii=False) + "\n")
            self._已写行数 += 1
        except OSError:
            return

    def _重写为最新一半(self) -> None:
        路径 = self.日志路径
        if 路径 is None:
            return
        try:
            行表 = 路径.read_text(encoding="utf-8").splitlines()
        except OSError:
            self._已写行数 = 0
            return
        保留 = 行表[-(文件行数上限 // 2):]
        路径.write_text("\n".join(保留) + ("\n" if 保留 else ""), encoding="utf-8")
        self._已写行数 = len(保留)

    # ── 读取 ──────────────────────────────────────────────────

    def 快照(self, 上限: int = 50, 只要等级: str = "") -> list[dict[str, Any]]:
        """按**最慢优先**返回留痕（内存环形，够查最近情况；全量看文件）。"""
        with self._锁:
            条目表 = list(self._内存)
        if 只要等级:
            条目表 = [项 for 项 in 条目表 if 项.get("等级") == 只要等级]
        条目表.sort(key=lambda 项: -float(项.get("耗时毫秒") or 0))
        return 条目表[:max(0, int(上限))]

    def 汇总(self) -> dict[str, Any]:
        """按等级计数 + 最慢几条（给「哪里该优化」一个直接答案）。"""
        考虑秒, 必须秒 = 阈值秒()
        with self._锁:
            条目表 = list(self._内存)
        计数 = {"必须优化": 0, "考虑优化": 0}
        for 项 in 条目表:
            等级 = 项.get("等级")
            if 等级 in 计数:
                计数[等级] += 1
        return {
            "阈值秒": {"考虑优化秒": 考虑秒, "必须优化秒": 必须秒},
            "留痕条数": len(条目表),
            "分级计数": 计数,
            "最慢": self.快照(上限=5),
            "日志路径": str(self.日志路径) if self.日志路径 else "",
            "说明": ("本表只做日志分级；「超标」裁决与加速方向见能力 "
                   "数据操作支持库.度量.判定耗时超标（默认阈值 5 秒）"),
        }


#: 进程级唯一实例（网关在装配期 `装配` 一次；未装配时 `记录` 是空操作）。
_实例: 调用耗时日志 | None = None
_实例锁 = threading.Lock()


def 装配(日志路径: Path | str | None = None) -> 调用耗时日志:
    """装配进程级唯一实例（重复装配以最后一次为准，返回当前实例）。"""
    global _实例
    with _实例锁:
        _实例 = 调用耗时日志(日志路径)
        return _实例


def 取实例() -> 调用耗时日志 | None:
    with _实例锁:
        return _实例


def 记录耗时(*, 能力id: str = "", 操作: str = "", 耗时毫秒: float = 0.0,
             成功: bool = True, 错误码: str = "") -> dict[str, Any] | None:
    """便捷入口：未装配时静默返回 None（**不阻断调用**，日志永远不是必经路径）。"""
    实例 = 取实例()
    if 实例 is None:
        return None
    return 实例.记录(能力id=能力id, 操作=操作, 耗时毫秒=耗时毫秒,
                     成功=成功, 错误码=错误码)
