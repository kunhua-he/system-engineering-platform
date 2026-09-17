"""灰度指标：落**底座运行库**（运行态唯一落点）、进程重启恢复、阈值自动回滚。

运行态入库（华哥 2026-09-15 定盘：运行态一律入库、不搞双写）：

- 观测 → 运行库 `灰度观测` 域（每次观测一行，主键 `观测id`）；
- 灰度比例/观察窗口/回滚原因 → 运行库 `灰度状态` 域（主键 `键` = `能力id@版本`）。

旧 `灰度指标.jsonl` / `灰度状态.json` 只做**只读兼容**（库里缺的按 指标键 一次性补齐），
**不再写文件**。写入失败不能破坏主调用：记入 `同步错误`（可见，不静默）。
"""

from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

阈值_失败率上限 = 0.05
阈值_超时率上限 = 0.10


@dataclass
class 灰度指标:
    """灰度观察指标（聚合视图）。"""

    能力id: str = ""
    版本: str = ""
    请求总数: int = 0
    成功数: int = 0
    失败数: int = 0
    超时数: int = 0
    平均耗时毫秒: float = 0.0
    最大耗时毫秒: float = 0.0
    当前灰度比例: float = 1.0
    观察窗口秒: int = 300
    触发回滚原因: str = ""

    def 失败率(self) -> float:
        return self.失败数 / self.请求总数 if self.请求总数 else 0.0

    def 超时率(self) -> float:
        return self.超时数 / self.请求总数 if self.请求总数 else 0.0

    def 转字典(self) -> dict[str, Any]:
        return {
            "能力id": self.能力id, "版本": self.版本, "请求总数": self.请求总数,
            "成功数": self.成功数, "失败数": self.失败数, "超时数": self.超时数,
            "平均耗时毫秒": round(self.平均耗时毫秒, 2), "最大耗时毫秒": self.最大耗时毫秒,
            "当前灰度比例": self.当前灰度比例, "观察窗口秒": self.观察窗口秒,
            "触发回滚原因": self.触发回滚原因, "失败率": round(self.失败率(), 4),
            "超时率": round(self.超时率(), 4),
        }


def _真值(值: Any) -> bool:
    """把库里的逻辑值归一成 bool。

    运行库早期把逻辑字段落成 TEXT，`"0"` 在 Python 里是**真值**（实测踩坑 2026-09-15），
    所以读取侧必须显式归一，兼容整数 0/1、文本 "0"/"1"、真 bool 三种形态。
    """
    if isinstance(值, bool):
        return 值
    if isinstance(值, (int, float)):
        return 值 != 0
    if isinstance(值, str):
        return 值.strip().lower() in {"1", "true", "是", "y", "yes"}
    return False


def _数(值: Any, 缺省: float) -> float:
    """把库里的数值归一成 float（兼容 TEXT 列写下的 "0.25"，取不到就用缺省）。"""
    try:
        return float(值)
    except (TypeError, ValueError):
        return 缺省


class 灰度指标库:
    """灰度指标持久化门面：运行库为唯一落点，旧 JSONL 只读兼容 + 一次性搬迁。"""

    def __init__(self, 存储目录: Path | None = None, *, 运行库路径: str | None = None) -> None:
        self.存储目录 = Path(存储目录) if 存储目录 else Path(默认存储目录())  # 只用于读旧文件
        self.运行库路径 = str(运行库路径).strip() if 运行库路径 else 默认运行库路径()
        self.写入失败计数 = 0
        self.同步错误 = ""
        self.状态表: dict[str, dict[str, Any]] = {}
        self.恢复()

    # ── 落点 ────────────────────────────────────────────────────────────────

    @property
    def 旧指标文件(self) -> Path:
        return self.存储目录 / "灰度指标.jsonl"

    @property
    def 旧状态文件(self) -> Path:
        return self.存储目录 / "灰度状态.json"

    def _调用(self, 能力id: str, 参数: dict[str, Any]) -> Any:
        """经唯一调用入口访问底座运行库；不可用时记入 同步错误（可见，不静默）。"""
        try:
            # 注册惰性装配钩子：非加载器进程缺这步会恒「未装配」
            import 运行核心.能力调用.唯一能力调用  # noqa: F401
            from 公共契约.能力契约.调用器 import 获取能力调用器
            结果对象 = 获取能力调用器().调用能力(能力id, 参数)
        except Exception as 错误:  # 装配缺失/运行库异常都不能打断主调用
            self.同步错误 = f"灰度指标落库失败：{错误}"
            return None
        if 结果对象 is None or not getattr(结果对象, "成功", False):
            self.同步错误 = f"灰度指标落库失败：{getattr(结果对象, '错误说明', '') or '运行库不可用'}"
            return None
        return 结果对象.值 if isinstance(结果对象.值, dict) else {}

    def _查询行(self, 域: str, 条件: dict[str, Any] | None = None, 限制: int = 1000) -> list[dict[str, Any]]:
        值 = self._调用(
            "数据库连接支持库.SQLite数据库.查询运行态",
            {"数据库路径": self.运行库路径, "域": 域, "条件": 条件 or {}, "限制": 限制, "超时秒": 10.0},
        )
        return list((值 or {}).get("行列表") or [])

    def _写入行(self, 域: str, 记录: dict[str, Any]) -> bool:
        值 = self._调用(
            "数据库连接支持库.SQLite数据库.写入运行态",
            {"数据库路径": self.运行库路径, "域": 域, "记录": 记录, "超时秒": 10.0},
        )
        if 值 is None:
            self.写入失败计数 += 1
            return False
        return True

    # ── 恢复与搬迁 ──────────────────────────────────────────────────────────

    def 恢复(self) -> None:
        """进程重启后恢复灰度状态；库空而旧文件在 → 一次性搬迁。"""
        for 行 in self._查询行("灰度状态"):
            # 主键落在库的 id 列（运行库约定的公共主键列），域字段里没有「键」这一列
            键 = str(行.get("键") or 行.get("id") or "")
            if not 键:
                continue
            self.状态表[键] = {
                "当前灰度比例": _数(行.get("灰度比例"), 1.0),
                "观察窗口秒": int(_数(行.get("观察窗口秒"), 300.0)),
                "触发回滚原因": 行.get("触发回滚原因", ""),
            }
        if not self.状态表 and self.旧状态文件.is_file():
            try:
                旧 = json.loads(self.旧状态文件.read_text(encoding="utf-8"))
                if isinstance(旧, dict):
                    self.状态表 = {k: v for k, v in 旧.items() if isinstance(v, dict)}
                    if self.状态表:
                        self.保存状态()  # 搬迁到运行库（失败只记计数）
            except json.JSONDecodeError:
                self.同步错误 = "灰度状态.json 损坏，已跳过搬迁"
        if not self._查询行("灰度观测", 限制=1) and self.旧指标文件.is_file():
            self._搬迁旧观测()

    def _搬迁旧观测(self) -> None:
        """把旧 JSONL 里已有的观测搬进运行库（只搬不删，旧文件留作证据）。"""
        搬入 = 0
        for 行 in self.旧指标文件.read_text(encoding="utf-8").splitlines():
            try:
                条目 = json.loads(行)
            except json.JSONDecodeError:
                continue
            if self._写入行("灰度观测", {
                "观测id": f"{条目.get('时间', '')}-{uuid.uuid4().hex[:8]}",
                "时间": 条目.get("时间", ""), "能力id": 条目.get("能力id", ""),
                "版本": 条目.get("版本", ""), "成功": bool(条目.get("成功")),
                "耗时毫秒": float(条目.get("耗时毫秒", 0.0)), "超时": bool(条目.get("超时")),
            }):
                搬入 += 1
        self.搬迁观测数 = 搬入

    搬迁观测数 = 0

    # ── 对外行为（签名与旧版一致，调用方不用改）────────────────────────────

    def 保存状态(self) -> None:
        """把内存状态 upsert 进运行库（唯一落点）；失败只累计计数，不打断主调用。"""
        for 键, 值 in self.状态表.items():
            self._写入行("灰度状态", {
                "键": 键, "灰度比例": float(值.get("当前灰度比例", 1.0)),
                "观察窗口秒": int(值.get("观察窗口秒", 300)),
                "触发回滚原因": str(值.get("触发回滚原因", "")),
            })

    def 设置灰度比例(self, 能力id: str, 版本: str, 比例: float) -> None:
        键 = f"{能力id}@{版本}"
        self.状态表.setdefault(键, {})["当前灰度比例"] = 比例
        self.状态表[键]["观察窗口秒"] = 300
        self.保存状态()

    def 观测(self, *, 能力id: str, 版本: str, 成功: bool, 耗时毫秒: float = 0.0,
             超时: bool = False) -> list[str]:
        """记录一次观测；返回超阈值问题列表（空=正常）。"""
        键 = f"{能力id}@{版本}"
        写入成功 = self._写入行("灰度观测", {
            "观测id": f"{time.strftime('%Y-%m-%d %H:%M:%S')}-{uuid.uuid4().hex[:8]}",
            "时间": time.strftime("%Y-%m-%d %H:%M:%S"), "能力id": 能力id, "版本": 版本,
            "成功": bool(成功), "耗时毫秒": round(float(耗时毫秒), 2), "超时": bool(超时),
        })
        if not 写入成功:
            return []
        指标 = self.聚合(能力id=能力id, 版本=版本)
        if 键 in self.状态表:
            指标.当前灰度比例 = self.状态表[键].get("当前灰度比例", 1.0)
            if self.状态表[键].get("触发回滚原因"):
                指标.触发回滚原因 = str(self.状态表[键]["触发回滚原因"])
        return self.超阈值问题(指标)

    def 聚合(self, *, 能力id: str = "", 版本: str = "") -> 灰度指标:
        """聚合指定 能力@版本 的指标（从运行库重算，不依赖内存）。"""
        指标 = 灰度指标(能力id=能力id, 版本=版本)
        条件: dict[str, Any] = {}
        if 能力id:
            条件["能力id"] = 能力id
        if 版本:
            条件["版本"] = 版本
        for 行 in self._查询行("灰度观测", 条件=条件 or None):
            指标.请求总数 += 1
            if _真值(行.get("成功")):
                指标.成功数 += 1
                耗时 = float(行.get("耗时毫秒") or 0.0)
                指标.平均耗时毫秒 = (指标.平均耗时毫秒 * (指标.成功数 - 1) + 耗时) / 指标.成功数
                指标.最大耗时毫秒 = max(指标.最大耗时毫秒, 耗时)
            else:
                指标.失败数 += 1
            if _真值(行.get("超时")):
                指标.超时数 += 1
        return 指标

    def 超阈值问题(self, 指标: 灰度指标) -> list[str]:
        问题列表 = []
        if 指标.请求总数 >= 5:  # 样本量门槛
            if 指标.失败率() > 阈值_失败率上限:
                问题列表.append(f"失败率 {指标.失败率():.2%} 超过上限 {阈值_失败率上限:.0%}")
            if 指标.超时率() > 阈值_超时率上限:
                问题列表.append(f"超时率 {指标.超时率():.2%} 超过上限 {阈值_超时率上限:.0%}")
        return 问题列表

    def 全部指标(self) -> list[灰度指标]:
        键集合 = {(str(行.get("能力id") or ""), str(行.get("版本") or ""))
                  for 行 in self._查询行("灰度观测")}
        return [self.聚合(能力id=能力id, 版本=版本) for 能力id, 版本 in sorted(键集合)]

    def 触发回滚(self, 能力id: str, 版本: str, 原因: str) -> None:
        键 = f"{能力id}@{版本}"
        self.状态表.setdefault(键, {})["触发回滚原因"] = 原因
        self.保存状态()


def 默认存储目录() -> str:
    """旧文件所在目录（只读兼容用；不再是写入落点）。"""
    import tempfile
    return os.environ.get("系统库灰度目录", str(Path(tempfile.gettempdir()) / "系统级支持库_灰度"))


def 默认运行库路径() -> str:
    """底座运行库路径（运行态唯一落点；可用 `系统库运行库` 环境变量覆盖）。"""
    环境 = os.environ.get("系统库运行库", "").strip()
    if 环境:
        return 环境
    # 落点经唯一解析器（禁止裸拼 `工程缓存`）：制品进程里 `parents[3]` = 制品内 `平台客户端`，
    # 裸拼会把运行库建进不可变制品；源码态回落 `<系统根>/工程缓存/运行数据`（与旧值逐字一致）。
    from 公共契约.运行时.运行缓存 import 解析运行数据根

    return str(解析运行数据根(Path(__file__).resolve().parents[3]) / "底座运行.db")
