"""能力级占用租约：多会话同仓开发时按能力原子互斥认领。

复用平台控制面 `占用租约` 表，**不建新表、不改版本**：
能力租约与文件租约共用一表，key = 能力id（原样）、领域 = "能力"，
靠活跃唯一索引（ON 占用租约(能力id) WHERE 状态='活跃'）原子保证互斥——
判据交给数据库，不再用 `is_file()` 那种"先查再写"的时间窗（TOCTOU）。

四动作（申请/续租/释放/回收过期）全部委托 平台控制面.能力目录.服务.能力目录；
申请时会先回收心跳过期的占用，会话崩溃/断线后 300 秒即可被重新认领，不会死锁。
收口时按开工id一并释放，不留残锁。

契约保持与旧的 JSON 版一致：同能力异包占用 → 冲突拒绝；同包重复占用 → 幂等成功。
"""
from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any

租约领域 = "能力"
默认心跳秒 = 300.0
参数不合法 = "参数不合法"
能力已占用 = "能力已占用"
占用冲突 = "占用冲突"
登记失败 = "登记失败"
错误码表 = (参数不合法, 能力已占用, 占用冲突, 登记失败)

_标识正则 = re.compile(r"^[A-Za-z0-9_.一-鿿-]+$")


def _结果(成功: bool, 错误码: str = "", 值: Any = None) -> dict[str, Any]:
    return {"成功": 成功, "错误码": 错误码, "值": 值}


def _标识(文本: Any, 名称: str) -> str | None:
    值 = str(文本).strip()
    if not 值 or len(值) > 200 or not _标识正则.fullmatch(值) or ".." in 值:
        return None
    return 值


def 能力键(能力id: Any) -> str:
    文本 = _标识(能力id, "能力id")
    if 文本 is None:
        raise ValueError("能力id不能为空且格式必须合法")
    return 文本


def _服务(存储目录: Path):
    from 平台控制面.平台状态 import 平台状态
    from 平台控制面.能力目录.服务 import 能力目录
    return 能力目录(平台状态(Path(存储目录), 项目id="平台控制面"))


def _活跃记录(服务, 键: str) -> dict[str, Any] | None:
    记录表 = 服务.状态.查询记录("占用租约", "状态='活跃' AND 能力id=?", (键,))
    return 记录表[0] if 记录表 else None


def 申请能力占用(
    存储目录: Path, *, 能力id: Any, 提供包id: Any, 开工id: Any,
    心跳秒: float = 默认心跳秒,
) -> dict[str, Any]:
    """登记能力占用；同能力异包冲突拒绝，同包重复占用幂等成功。"""
    键 = _标识(能力id, "能力id")
    包 = _标识(提供包id, "提供包id")
    开工 = _标识(开工id, "开工id")
    if 键 is None or 包 is None or 开工 is None:
        return _结果(False, 参数不合法,
                     {"消息": "能力id/提供包id/开工id 均不能为空且格式必须合法"})
    服务 = _服务(存储目录)
    # 先回收心跳过期的占用：会话崩溃/断线后即可被重新认领，避免永久锁。
    服务.回收过期占用(心跳超时秒=默认心跳秒)
    成功, 消息, 租约id = 服务.申请占用(
        能力id=键, 领域=租约领域, 契约指纹="", 任务=开工,
        所有者=包, 心跳秒=float(心跳秒))
    if not 成功:
        现有 = _活跃记录(服务, 键)
        if 现有 is None:
            return _结果(False, 登记失败, {"消息": f"能力占用登记失败: {消息}"})
        if str(现有.get("所有者", "")) != 包:
            return _结果(False, 占用冲突, {
                "消息": f"能力 {键} 已被包 {现有.get('所有者')} 占用",
                "现有占用": {
                    "提供包id": 现有.get("所有者", ""),
                    "开工id": 现有.get("任务", ""),
                    "占用时间": 现有.get("心跳"),
                },
            })
        # 同包重复占用：幂等成功，并刷新心跳（相当于续租）。续租失败（租约已被回收/
        # 心跳刷新不进去）不能报成功——否则调用方以为占用仍被自己持有，实际已失去互斥。
        续租成功 = 服务.续租(str(现有.get("租约id", "")))
        if not 续租成功:
            return _结果(False, 登记失败, {
                "消息": f"能力 {键} 同包占用存在但心跳刷新失败，占用可能已被回收",
                "能力id": 键, "提供包id": 包, "租约id": 现有.get("租约id", ""),
            })
        return _结果(True, "", {
            "能力id": 键, "提供包id": 包, "开工id": str(现有.get("任务", 开工)),
            "占用时间": 现有.get("心跳"), "租约id": 现有.get("租约id", ""), "幂等": True,
        })
    return _结果(True, "", {
        "能力id": 键, "提供包id": 包, "开工id": 开工,
        "占用时间": time.time(), "租约id": 租约id, "幂等": False,
    })


def 续租能力占用(存储目录: Path, 租约id表: list[Any]) -> dict[str, Any]:
    """长任务进行中刷新心跳，避免占用过期被回收。"""
    服务 = _服务(存储目录)
    成功表: list[str] = []
    失败表: list[str] = []
    for 租约id in 租约id表 or []:
        文本 = str(租约id)
        (成功表 if 服务.续租(文本) else 失败表).append(文本)
    return {"成功": not 失败表, "续租": 成功表, "失败": 失败表}


def 释放能力占用(存储目录: Path, 租约id表: list[Any], *, 证据: str = "") -> dict[str, Any]:
    """按租约id释放能力占用，写明释放证据。"""
    服务 = _服务(存储目录)
    成功表: list[str] = []
    失败表: list[str] = []
    for 租约id in 租约id表 or []:
        文本 = str(租约id)
        (成功表 if 服务.释放占用(文本, 证据=str(证据)) else 失败表).append(文本)
    return {"成功": not 失败表, "释放": 成功表, "失败": 失败表}


def 释放开工id能力占用(存储目录: Path, 开工id: Any, *, 证据: str = "") -> dict[str, Any]:
    """收口时按开工id释放其持有的全部活跃能力占用，不留残锁。"""
    开工 = _标识(开工id, "开工id")
    if 开工 is None:
        return {"成功": True, "释放数量": 0, "租约id": [], "消息": "开工id为空，跳过"}
    服务 = _服务(存储目录)
    活跃 = 服务.状态.查询记录(
        "占用租约", "状态='活跃' AND 领域=? AND 任务=?", (租约领域, 开工),
    )
    释放id表 = [str(记录.get("租约id", "")) for 记录 in 活跃]
    # 同 文件租约.释放工作包文件租约：释放占用 的返回值必须真实消费，
    # 否则收口报告恒「不留残锁」，与按租约id释放那条口径也不一致。
    成功表: list[str] = []
    失败表: list[str] = []
    for 租约id in 释放id表:
        (成功表 if 服务.释放占用(租约id, 证据=str(证据)) else 失败表).append(租约id)
    return {"成功": not 失败表, "释放数量": len(成功表), "租约id": 成功表, "失败": 失败表}


def 回收过期能力占用(存储目录: Path, 心跳超时秒: float = 默认心跳秒) -> dict[str, Any]:
    """回收心跳过期的占用（委托现成的共享回收，同时覆盖能力租约与文件租约）。"""
    服务 = _服务(存储目录)
    过期 = 服务.回收过期占用(心跳超时秒=float(心跳超时秒))
    return {"成功": True, "回收数量": len(过期), "租约id": 过期}


def 查询能力占用(存储目录: Path, 能力id表: list[Any] | None = None) -> dict[str, Any]:
    """查询活跃能力租约；给了能力id表就只查这些，否则列出全部。"""
    服务 = _服务(存储目录)
    限定 = {str(项).strip() for 项 in 能力id表} if 能力id表 else None
    现在 = time.time()
    占用表: list[dict[str, Any]] = []
    for 记录 in 服务.状态.查询记录("占用租约", "状态='活跃' AND 领域=?", (租约领域,)):
        能力id = str(记录.get("能力id", ""))
        if 限定 is not None and 能力id not in 限定:
            continue
        心跳 = float(记录.get("心跳") or 现在)
        占用表.append({
            "能力id": 能力id, "租约id": 记录.get("租约id", ""),
            "提供包id": 记录.get("所有者", ""), "开工id": 记录.get("任务", ""),
            "心跳": 心跳, "空闲秒": round(现在 - 心跳, 1),
        })
    占用表.sort(key=lambda 项: 项["能力id"])
    return {"成功": True, "数量": len(占用表), "占用": 占用表}
