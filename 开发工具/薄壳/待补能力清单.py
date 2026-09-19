"""待补能力清单：薄壳转发时遇到「能力未注册」的登记（追加 JSONL，按能力id幂等去重）。

薄壳只登记事实（谁在什么时候要哪个能力、网关原话错误说明），不实现补齐动作；
补齐能力属于底座模块库的活，登记文件只服务后续排期。
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

try:  # 非 POSIX（Windows 类）无 fcntl：退化为不锁，与同仓 安装能力._安装串行锁 同口径
    import fcntl
except ImportError:  # pragma: no cover - 平台分支
    fcntl = None  # type: ignore[assignment]

清单路径 = Path(__file__).resolve().parent / "待补能力清单.jsonl"
锁路径 = Path(__file__).resolve().parent / "待补能力清单.lock"


@contextmanager
def _登记串行锁():
    """登记互斥（`flock`）：把「读清单 + 判重 + 追加」收在同一把锁内。

    #171（2026-09-20）：原实现 `读取待补能力()` → 判重 → `open("a")` 追加是典型的
    read-modify-write，两个薄壳实例并发登记同一能力 id 时**都会读到「不存在」**
    然后各追加一行 —— 幂等去重形同虚设（同一缺口在清单里出现两次）。
    薄壳并发量低，但仍属真缺陷（幂等承诺与实际不符）。
    """
    if fcntl is None:
        yield
        return
    锁路径.parent.mkdir(parents=True, exist_ok=True)
    句柄 = 锁路径.open("a+")
    try:
        fcntl.flock(句柄.fileno(), fcntl.LOCK_EX)
        yield
    finally:
        try:
            fcntl.flock(句柄.fileno(), fcntl.LOCK_UN)
        finally:
            句柄.close()


def 读取待补能力() -> list[dict[str, Any]]:
    """读回已登记条目；文件不存在或行损坏时按空/跳过处理，不抛异常。"""
    if not 清单路径.is_file():
        return []
    条目表: list[dict[str, Any]] = []
    for 行 in 清单路径.read_text(encoding="utf-8").splitlines():
        if not 行.strip():
            continue
        try:
            条目 = json.loads(行)
        except json.JSONDecodeError:
            continue
        条目表.append(条目 if isinstance(条目, dict) else {})
    return 条目表


def 登记待补能力(能力id: str, 来源工具: str, 网关错误说明: str) -> dict[str, Any]:
    """登记一条缺口能力；同一能力id 只记一次（首次登记时间保留）。"""
    能力id = str(能力id or "").strip()
    # #171：读清单 → 判重 → 追加，整段在 flock 内完成（否则并发下判重恒为假）
    with _登记串行锁():
        已有 = 读取待补能力()
        if any(str(条目.get("能力id", "")) == 能力id for 条目 in 已有):
            return {"是否新增": False, "已登记条数": len(已有), "清单路径": str(清单路径)}
        条目 = {
            "能力id": 能力id,
            "来源工具": str(来源工具),
            "网关错误说明": str(网关错误说明)[:200],
            "登记时间": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        行 = json.dumps(条目, ensure_ascii=False)
        with 清单路径.open("a", encoding="utf-8") as 文件:
            文件.write(行 + "\n")
        return {"是否新增": True, "已登记条数": len(已有) + 1, "清单路径": str(清单路径)}
