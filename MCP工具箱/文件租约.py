"""文件级占用租约：多会话同仓开发时按文件原子互斥认领。

复用平台控制面 `占用租约` 表，**不建新表、不改版本**：
文件租约与能力租约共用一表，key = "文件::<仓库相对路径>"、领域 = "文件"，
靠活跃唯一索引（ON 占用租约(能力id) WHERE 状态='活跃'）原子保证互斥。

四动作（申请/续租/释放/回收过期）全部委托 平台控制面.能力目录.服务.能力目录；
过期回收同时覆盖能力租约与文件租约，不会出现死锁。
申请一批路径时**全成功才开工**：任一失败，已成功的立即释放并整体拒绝。
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any

键前缀 = "文件::"
租约领域 = "文件"
默认心跳秒 = 300.0
错误_冲突 = "FILE_LEASE_CONFLICT"
错误_参数 = "参数无效"


def 归一化路径(路径: Any) -> str:
    """仓库相对路径归一化：反斜杠转正斜杠、去首尾斜杠与前导 ./。"""
    文本 = str(路径).strip().replace("\\", "/")
    while 文本.startswith("./"):
        文本 = 文本[2:]
    文本 = 文本.strip("/")
    if not 文本:
        raise ValueError("文件路径不能为空")
    return 文本


def 文件键(路径: Any) -> str:
    return 键前缀 + 归一化路径(路径)


def _去前缀(键: str) -> str:
    return 键[len(键前缀):] if 键.startswith(键前缀) else 键


def _服务(存储目录: Path):
    from 平台控制面.平台状态 import 平台状态
    from 平台控制面.能力目录.服务 import 能力目录
    return 能力目录(平台状态(Path(存储目录), 项目id="平台控制面"))


def _活跃记录(服务, 键: str) -> dict[str, Any] | None:
    记录表 = 服务.状态.查询记录("占用租约", "状态='活跃' AND 能力id=?", (键,))
    return 记录表[0] if 记录表 else None


def 申请文件租约(
    存储目录: Path, 路径表: list[Any], *, 所有者: str, 任务: str = "",
    心跳秒: float = 默认心跳秒,
) -> dict[str, Any]:
    """批量申请文件租约；全成功才通过，任一失败回滚已成功的并整体拒绝。"""
    if not str(所有者).strip():
        return {"成功": False, "错误码": 错误_参数, "消息": "所有者不能为空"}
    路径列表: list[str] = []
    for 项 in 路径表 or []:
        路径 = 归一化路径(项)
        if 路径 not in 路径列表:
            路径列表.append(路径)
    if not 路径列表:
        return {"成功": True, "数量": 0, "租约": []}
    服务 = _服务(存储目录)
    # 先回收心跳过期的占用：会话崩溃/断线后 300 秒即可被重新认领，避免死锁。
    服务.回收过期占用(心跳超时秒=默认心跳秒)
    已得: list[tuple[str, str]] = []
    for 路径 in 路径列表:
        键 = 文件键(路径)
        成功, 消息, 租约id = 服务.申请占用(
            能力id=键, 领域=租约领域, 契约指纹="", 任务=str(任务 or ""),
            所有者=str(所有者), 心跳秒=float(心跳秒))
        if not 成功:
            现有 = _活跃记录(服务, 键) or {}
            for 已租约id, _ in 已得:
                服务.释放占用(已租约id, 证据=f"批量申请失败回滚：{路径} 已被占")
            return {
                "成功": False, "错误码": 错误_冲突, "文件路径": 路径,
                "占用者": 现有.get("所有者", "未知"), "占用开始时间": 现有.get("心跳"),
                "消息": 消息, "已回滚": [_去前缀(键) for _, 键 in 已得],
            }
        已得.append((租约id, 键))
    return {"成功": True, "数量": len(已得),
            "租约": [{"文件路径": _去前缀(键), "租约id": 租约id} for 租约id, 键 in 已得]}


def 续租文件租约(存储目录: Path, 租约id表: list[Any]) -> dict[str, Any]:
    """长任务进行中刷新心跳，避免租约过期被回收。"""
    服务 = _服务(存储目录)
    成功表: list[str] = []
    失败表: list[str] = []
    for 租约id in 租约id表 or []:
        文本 = str(租约id)
        (成功表 if 服务.续租(文本) else 失败表).append(文本)
    return {"成功": not 失败表, "续租": 成功表, "失败": 失败表}


def 释放文件租约(存储目录: Path, 租约id表: list[Any], *, 证据: str = "") -> dict[str, Any]:
    """按租约id释放文件占用，写明释放证据。"""
    服务 = _服务(存储目录)
    成功表: list[str] = []
    失败表: list[str] = []
    for 租约id in 租约id表 or []:
        文本 = str(租约id)
        (成功表 if 服务.释放占用(文本, 证据=str(证据)) else 失败表).append(文本)
    return {"成功": not 失败表, "释放": 成功表, "失败": 失败表}


def 释放工作包文件租约(存储目录: Path, 所有者: str, *, 证据: str = "") -> dict[str, Any]:
    """收口时按所有者释放其持有的全部活跃文件租约，不留残锁。"""
    服务 = _服务(存储目录)
    活跃 = 服务.状态.查询记录(
        "占用租约", "状态='活跃' AND 领域=? AND 所有者=?", (租约领域, str(所有者)),
    )
    释放id表 = [str(记录.get("租约id", "")) for 记录 in 活跃]
    for 租约id in 释放id表:
        服务.释放占用(租约id, 证据=str(证据))
    return {"成功": True, "释放数量": len(释放id表), "租约id": 释放id表}


def 回收过期文件租约(存储目录: Path, 心跳超时秒: float = 默认心跳秒) -> dict[str, Any]:
    """回收心跳过期的占用（委托现成的共享回收，同时覆盖能力租约与文件租约）。"""
    服务 = _服务(存储目录)
    过期 = 服务.回收过期占用(心跳超时秒=float(心跳超时秒))
    return {"成功": True, "回收数量": len(过期), "租约id": 过期}


def 查询文件占用(存储目录: Path, 路径表: list[Any] | None = None) -> dict[str, Any]:
    """查询活跃文件租约；给了路径表就只查这些，否则列出全部。"""
    服务 = _服务(存储目录)
    限定 = {归一化路径(项) for 项 in 路径表} if 路径表 else None
    现在 = time.time()
    结果: list[dict[str, Any]] = []
    for 记录 in 服务.状态.查询记录("占用租约", "状态='活跃' AND 领域=?", (租约领域,)):
        路径 = _去前缀(str(记录.get("能力id", "")))
        if 限定 is not None and 路径 not in 限定:
            continue
        心跳 = float(记录.get("心跳") or 现在)
        结果.append({
            "文件路径": 路径, "租约id": 记录.get("租约id", ""),
            "所有者": 记录.get("所有者", ""), "任务": 记录.get("任务", ""),
            "心跳": 心跳, "空闲秒": round(现在 - 心跳, 1),
        })
    结果.sort(key=lambda 项: 项["文件路径"])
    return {"成功": True, "数量": len(结果), "占用": 结果}
