"""文件租约存储：单 JSON 存储的原子读写与竞争互斥（唯一写入口）。

归属：文件租约是**多会话并发写同一文件**的平台级互斥，属平台治理面，落
`平台控制面.能力目录`。事实唯一落 `存储目录/文件租约.json`，与同包
`消费者契约注册表.py` 同一种做法（单 JSON 存储、按存储目录实例化，
**不建新表、不改任何既有存储结构**）。

**互斥保证（应用级唯一判定）**：认领 = 「进程内锁内重读 → 判定活跃占用 → 临时文件 +
`os.replace` 原子替换」。`os.replace` 原子，不存在半写状态；两个会话同时认领同一路径时，
后写入者必然在锁内重读到先写入者的活跃租约而失败，**不会静默双认领**。

**残余风险（缺 DB 唯一索引）**：`平台控制面/平台状态/状态存储.py` 不在本批允许域，且该库
既有部分唯一索引 `索引_占用活跃` 是按**单列 能力id** 建的 —— 文件键写回那张表会让
「同一能力 id 只有一条活跃租约」的单列唯一语义失效，故本批不写回该表；跨进程互斥由上面
这条应用级判定承担，不依赖数据库级唯一约束。
"""
from __future__ import annotations

import json
import os
import threading
import time
import uuid
from pathlib import Path

存储文件名 = "文件租约.json"
活跃状态 = "活跃"
状态_已释放 = "已释放"
状态_已过期 = "已过期"
默认持有秒 = 300.0
最长持有秒 = 86400.0


def 文件键(路径: str) -> str:
    """文件租约键：`文件::<项目根相对路径>`（与 平台状态.占用租约 表 能力id 列同形）。"""
    return f"文件::{路径}"


def 时间文本(时间戳: object) -> str:
    """时间戳 → 人读文本（本地时区 `%Y-%m-%d %H:%M:%S`，平台统一口径）。"""
    try:
        return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(float(时间戳)))  # type: ignore[arg-type]
    except (TypeError, ValueError, OSError):
        return ""


def 是活跃(记录: object) -> bool:
    """记录是否活跃（非活跃 = 可被同一路径重新认领）。"""
    return isinstance(记录, dict) and 记录.get("状态") == 活跃状态


class 文件租约存储:
    """文件租约存储；心跳单位为秒（浮点），键为 `文件::<路径>`。"""

    def __init__(self, 存储目录: Path | str) -> None:
        self.存储文件 = Path(存储目录) / 存储文件名
        self._锁 = threading.Lock()

    # ── 存储基础 ──────────────────────────────────────────────
    def 读取(self) -> tuple[dict, str]:
        """读取存储；文件缺失视为空库；**损坏即报错**（不按空库继续，避免静默丢租约）。"""
        if not self.存储文件.is_file():
            return {}, ""
        try:
            正文 = self.存储文件.read_text(encoding="utf-8")
        except OSError as 错误:
            return {}, f"文件租约存储不可读: {错误}"
        except UnicodeDecodeError as 错误:
            return {}, f"文件租约存储编码损坏: {错误}"
        try:
            数据 = json.loads(正文)
        except json.JSONDecodeError as 错误:
            return {}, f"文件租约存储损坏（拒绝按空库继续）: {错误}"
        return (数据 if isinstance(数据, dict) else {}), ""

    def 写入(self, 数据: dict) -> str:
        """临时文件 + `os.replace` 原子替换；返回问题说明（成功为空串）。"""
        try:
            self.存储文件.parent.mkdir(parents=True, exist_ok=True)
            临时文件 = self.存储文件.with_name(self.存储文件.name + ".临时")
            临时文件.write_text(
                json.dumps(数据, ensure_ascii=False, indent=2, sort_keys=True),
                encoding="utf-8")
            os.replace(临时文件, self.存储文件)
        except OSError as 错误:
            return f"文件租约存储写入失败: {错误}"
        return ""

    def 独占(self):
        """进程内独占区（跨进程互斥靠 原子替换 + 锁内重读，见模块头注释）。"""
        return self._锁

    @staticmethod
    def 按租约id找键(存储: dict, 租约id: str) -> str:
        for 键, 记录 in 存储.items():
            if isinstance(记录, dict) and str(记录.get("租约id") or "") == 租约id:
                return 键
        return ""

    @staticmethod
    def 新租约(路径: str, 所有者: str, 任务: str, 持有秒: float,
               存储标签: str, 现在: float | None = None) -> dict:
        """构造一条活跃租约记录（字段与 平台状态.占用租约 表列族同名同义）。"""
        时刻 = time.time() if 现在 is None else 现在
        return {
            "租约id": uuid.uuid4().hex[:16], "键": 文件键(路径), "路径": 路径,
            "所有者": 所有者, "任务": 任务, "存储标签": 存储标签,
            "心跳": 时刻, "申请时间": 时间文本(时刻),
            "过期时间": 时刻 + 持有秒, "状态": 活跃状态,
            "释放时间": "", "释放原因": "",
        }

    @staticmethod
    def 对外记录(记录: dict) -> dict:
        """对外读数：浮点心跳照给，另附人读时间字段（不改变内部字段名）。"""
        对外 = dict(记录)
        对外["心跳时间"] = 时间文本(记录.get("心跳"))
        对外["过期时间读数"] = 时间文本(记录.get("过期时间"))
        return 对外
