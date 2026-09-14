"""能力级占用租约：多会话同仓开发时按能力原子互斥认领。

两层各司其职（华哥 2026-09-15 定盘：运行态一律入库，不搞双写）：
- **互斥判据**：平台控制面 `占用租约` 表（本就是数据库租约，靠活跃唯一索引
  `ON 占用租约(能力id) WHERE 状态='活跃'` 原子保证互斥），不建新表、不改版本；
  判据交给数据库，不再用 `is_file()` 那种"先查再写"的时间窗（TOCTOU）。
- **占用账本**：底座运行库 `工程缓存/运行数据/底座运行.db` 的 `能力占用` 域
  （主键 能力id，经唯一 SQLite 支持库访问），记录「谁在何时占了哪个能力、何时释放」，
  供查询与审计。旧 `工程缓存/能力占用/*.json` 只做只读兼容 + 首次搬迁，不再写文件。

四动作（申请/续租/释放/回收过期）全部委托 平台控制面.能力目录.服务.能力目录；
申请时会先回收心跳过期的占用，会话崩溃/断线后 300 秒即可被重新认领，不会死锁。
收口时按开工id一并释放，不留残锁。

契约保持与旧的 JSON 版一致：同能力异包占用 → 冲突拒绝；同包重复占用 → 幂等成功。
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

系统根 = Path(__file__).resolve().parents[1]

租约领域 = "能力"
默认心跳秒 = 300.0
参数不合法 = "参数不合法"
能力已占用 = "能力已占用"
占用冲突 = "占用冲突"
登记失败 = "登记失败"
错误码表 = (参数不合法, 能力已占用, 占用冲突, 登记失败)

账本状态_活跃 = "活跃"
账本状态_已释放 = "已释放"
账本状态_已回收 = "已回收"
账本状态_历史 = "历史"

# 最近一次运行库访问失败：失败必须可见（模块级字段 + stderr），不许静默吞异常。
同步错误 = ""

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


def _租约记录(服务, 租约id: str) -> dict[str, Any] | None:
    """按租约id取租约行（含已释放/已过期），用于回填占用账本的能力id。"""
    记录表 = 服务.状态.查询记录("占用租约", "租约id=?", (str(租约id),))
    return 记录表[0] if 记录表 else None


# ── 占用账本（底座运行库 `能力占用` 域；旧 JSON 只读兼容 + 首次搬迁）──────────

def 默认运行库路径() -> str:
    """底座运行库路径（运行态唯一落点；可用 `系统库运行库` 环境变量覆盖）。"""
    环境 = os.environ.get("系统库运行库", "").strip()
    if 环境:
        return 环境
    return str(系统根 / "工程缓存" / "运行数据" / "底座运行.db")


def 默认旧账本目录() -> Path:
    """旧 `工程缓存/能力占用/*.json` 目录（只读兼容 + 首次搬迁；不再写）。"""
    缓存根 = os.environ.get("系统底座_工程缓存根", "").strip()
    return (Path(缓存根) if 缓存根 else 系统根 / "工程缓存") / "能力占用"


def _现在文本() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def _记同步错误(说明: str) -> None:
    """记录运行库访问失败：写模块级 `同步错误` 并落 stderr（不静默）。"""
    global 同步错误
    同步错误 = 说明
    print(f"能力占用-运行库同步失败：{说明}", file=sys.stderr)


def _运行库调用(能力id: str, 参数: dict[str, Any]) -> Any:
    """经唯一调用入口访问底座运行库；不可用时记入 `同步错误` 并返回 None。"""
    try:
        # 注册惰性装配钩子：MCP 管理端进程不经加载器装配，缺这步会恒「未装配」。
        import 运行核心.能力调用.唯一能力调用  # noqa: F401

        from 公共契约.能力契约.调用器 import 获取能力调用器

        return 获取能力调用器().调用能力(能力id, 参数)
    except Exception as 错误:  # noqa: BLE001 —— 运行库不可用必须可见，见 同步错误
        _记同步错误(f"运行库不可用：{错误}")
        return None


def _写账本(运行库路径: str, 记录: dict[str, Any]) -> tuple[bool, str]:
    """写一条占用账本记录（主键 能力id）；返回（是否成功，失败说明）。"""
    结果对象 = _运行库调用(
        "数据库连接支持库.SQLite数据库.写入运行态",
        {"数据库路径": 运行库路径, "域": "能力占用", "记录": 记录, "超时秒": 10.0},
    )
    if 结果对象 is None or not 结果对象.成功:
        说明 = getattr(结果对象, "错误说明", "") or "运行库不可用"
        _记同步错误(f"能力占用账本落库失败（能力id {记录.get('能力id', '')}）：{说明}")
        return False, 说明
    return True, ""


def _账本记录(能力id: str, 提供包id: str, 开工id: str, 占用时间: str,
            状态: str, **附加: Any) -> dict[str, Any]:
    记录: dict[str, Any] = {
        "能力id": 能力id, "提供包id": 提供包id, "开工id": 开工id,
        "占用时间": 占用时间, "状态": 状态, "更新时间": _现在文本(),
    }
    记录.update({键: 值 for 键, 值 in 附加.items() if 值 not in (None, "")})
    return 记录


def _读账本(运行库路径: str) -> list[dict[str, Any]] | None:
    """从运行库读回占用账本；库不可用或为空时返回 None（交给旧文件回退）。"""
    结果对象 = _运行库调用(
        "数据库连接支持库.SQLite数据库.查询运行态",
        {"数据库路径": 运行库路径, "域": "能力占用", "限制": 1000, "超时秒": 10.0},
    )
    if 结果对象 is None or not 结果对象.成功:
        return None
    值 = 结果对象.值 if isinstance(结果对象.值, dict) else {}
    行列表 = 值.get("行列表") or []
    if not 行列表:
        return None
    记录表: list[dict[str, Any]] = []
    for 行 in 行列表:
        if not isinstance(行, dict):
            continue
        载荷 = 行.get("载荷")
        try:
            记录 = json.loads(载荷) if isinstance(载荷, str) and 载荷 else {}
        except json.JSONDecodeError:
            continue
        if isinstance(记录, dict) and 记录:
            记录表.append(记录)
    return 记录表 or None


def _读旧账本(旧账本目录: Path) -> list[dict[str, Any]]:
    """迁移期只读兼容：读旧 `工程缓存/能力占用/*.json`。"""
    记录表: list[dict[str, Any]] = []
    if not Path(旧账本目录).is_dir():
        return 记录表
    for 路径 in sorted(Path(旧账本目录).glob("*.json")):
        try:
            记录 = json.loads(路径.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(记录, dict) and 记录.get("能力id"):
            记录表.append(记录)
    return 记录表


def 查询占用账本(*, 运行库路径: str | None = None,
              旧账本目录: Path | None = None) -> dict[str, Any]:
    """查询能力占用账本：**库优先**；库空回退旧 JSON，旧 JSON 里库里没有的记录缺页补齐。

    旧 JSON 只读、不删、不覆盖库记录；补齐只在库里确实缺该 能力id 时发生（幂等，不双写）。
    """
    库路径 = str(运行库路径) if 运行库路径 else 默认运行库路径()
    旧目录 = Path(旧账本目录) if 旧账本目录 else 默认旧账本目录()
    记录表 = _读账本(库路径)
    已有 = {str(记录.get("能力id", "")) for 记录 in (记录表 or [])}
    缺失 = [记录 for 记录 in _读旧账本(旧目录)
            if str(记录.get("能力id", "")) not in 已有]
    for 记录 in 缺失:
        _写账本(库路径, {**记录, "状态": 记录.get("状态") or 账本状态_历史})
    来源 = "运行库" if 记录表 else "旧文件"
    合并表 = list(记录表 or []) + 缺失
    return {"成功": True, "来源": 来源, "数量": len(合并表),
            "运行库路径": 库路径, "记录": 合并表, "同步错误": 同步错误}


def 搬迁旧账本(*, 运行库路径: str | None = None,
            旧账本目录: Path | None = None) -> dict[str, Any]:
    """首次搬迁入口：把旧 `工程缓存/能力占用/*.json` 一次性搬入运行库；旧文件保留不删。"""
    库路径 = str(运行库路径) if 运行库路径 else 默认运行库路径()
    旧目录 = Path(旧账本目录) if 旧账本目录 else 默认旧账本目录()
    旧记录表 = _读旧账本(旧目录)
    已搬 = 0
    失败: list[str] = []
    for 记录 in 旧记录表:
        成功, 说明 = _写账本(库路径, {**记录, "状态": 记录.get("状态") or 账本状态_历史})
        if 成功:
            已搬 += 1
        else:
            失败.append(f"{记录.get('能力id', '')}: {说明}")
    return {"成功": not 失败, "旧文件数": len(旧记录表), "已搬迁": 已搬,
            "运行库路径": 库路径, "失败": 失败, "同步错误": 同步错误}


def _标账本终态(服务, 运行库路径: str, 租约id: str, 状态: str,
             证据: str) -> str:
    """把某租约对应的账本行标为终态（已释放/已回收）；返回失败说明（成功为 ""）。"""
    租约 = _租约记录(服务, 租约id)
    if 租约 is None:
        return ""
    能力id = str(租约.get("能力id", ""))
    if not 能力id:
        return ""
    成功, 说明 = _写账本(运行库路径, _账本记录(
        能力id, str(租约.get("所有者", "")), str(租约.get("任务", "")),
        _现在文本(), 状态, 释放时间=_现在文本(), 释放证据=str(证据),
    ))
    return "" if 成功 else 说明


def 申请能力占用(
    存储目录: Path, *, 能力id: Any, 提供包id: Any, 开工id: Any,
    心跳秒: float = 默认心跳秒, 运行库路径: str | None = None,
) -> dict[str, Any]:
    """登记能力占用；同能力异包冲突拒绝，同包重复占用幂等成功。

    成功后同步写占用账本（运行库 `能力占用` 域）；账本写失败不影响占用判据，
    但会把说明挂在返回值的 `同步错误` 上（不静默）。
    """
    键 = _标识(能力id, "能力id")
    包 = _标识(提供包id, "提供包id")
    开工 = _标识(开工id, "开工id")
    if 键 is None or 包 is None or 开工 is None:
        return _结果(False, 参数不合法,
                     {"消息": "能力id/提供包id/开工id 均不能为空且格式必须合法"})
    库路径 = str(运行库路径) if 运行库路径 else 默认运行库路径()
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
        值 = {
            "能力id": 键, "提供包id": 包, "开工id": str(现有.get("任务", 开工)),
            "占用时间": 现有.get("心跳"), "租约id": 现有.get("租约id", ""), "幂等": True,
        }
        账本成功, 说明 = _写账本(库路径, _账本记录(
            键, 包, 值["开工id"], _现在文本(), 账本状态_活跃,
            租约id=值["租约id"], 续租时间=_现在文本()))
        if not 账本成功:
            值["同步错误"] = f"占用账本未写：{说明}"
        return _结果(True, "", 值)
    值 = {
        "能力id": 键, "提供包id": 包, "开工id": 开工,
        "占用时间": time.time(), "租约id": 租约id, "幂等": False,
    }
    账本成功, 说明 = _写账本(库路径, _账本记录(
        键, 包, 开工, _现在文本(), 账本状态_活跃, 租约id=租约id))
    if not 账本成功:
        值["同步错误"] = f"占用账本未写：{说明}"
    return _结果(True, "", 值)


def 续租能力占用(存储目录: Path, 租约id表: list[Any],
               运行库路径: str | None = None) -> dict[str, Any]:
    """长任务进行中刷新心跳，避免占用过期被回收。"""
    服务 = _服务(存储目录)
    成功表: list[str] = []
    失败表: list[str] = []
    for 租约id in 租约id表 or []:
        文本 = str(租约id)
        (成功表 if 服务.续租(文本) else 失败表).append(文本)
    return {"成功": not 失败表, "续租": 成功表, "失败": 失败表}


def 释放能力占用(存储目录: Path, 租约id表: list[Any], *, 证据: str = "",
               运行库路径: str | None = None) -> dict[str, Any]:
    """按租约id释放能力占用，写明释放证据；同步把占用账本行标为「已释放」。"""
    库路径 = str(运行库路径) if 运行库路径 else 默认运行库路径()
    服务 = _服务(存储目录)
    成功表: list[str] = []
    失败表: list[str] = []
    账本失败: list[str] = []
    for 租约id in 租约id表 or []:
        文本 = str(租约id)
        if 服务.释放占用(文本, 证据=str(证据)):
            成功表.append(文本)
            说明 = _标账本终态(服务, 库路径, 文本, 账本状态_已释放, str(证据))
            if 说明:
                账本失败.append(f"{文本}: {说明}")
        else:
            失败表.append(文本)
    结果值 = {"成功": not 失败表, "释放": 成功表, "失败": 失败表}
    if 账本失败:
        结果值["同步错误"] = "占用账本未更新：" + "；".join(账本失败)
    return 结果值


def 释放开工id能力占用(存储目录: Path, 开工id: Any, *, 证据: str = "",
                   运行库路径: str | None = None) -> dict[str, Any]:
    """收口时按开工id释放其持有的全部活跃能力占用，不留残锁。"""
    开工 = _标识(开工id, "开工id")
    if 开工 is None:
        return {"成功": True, "释放数量": 0, "租约id": [], "消息": "开工id为空，跳过"}
    库路径 = str(运行库路径) if 运行库路径 else 默认运行库路径()
    服务 = _服务(存储目录)
    活跃 = 服务.状态.查询记录(
        "占用租约", "状态='活跃' AND 领域=? AND 任务=?", (租约领域, 开工),
    )
    释放id表 = [str(记录.get("租约id", "")) for 记录 in 活跃]
    # 同 文件租约.释放工作包文件租约：释放占用 的返回值必须真实消费，
    # 否则收口报告恒「不留残锁」，与按租约id释放那条口径也不一致。
    成功表: list[str] = []
    失败表: list[str] = []
    账本失败: list[str] = []
    for 租约id in 释放id表:
        if 服务.释放占用(租约id, 证据=str(证据)):
            成功表.append(租约id)
            说明 = _标账本终态(服务, 库路径, 租约id, 账本状态_已释放, str(证据))
            if 说明:
                账本失败.append(f"{租约id}: {说明}")
        else:
            失败表.append(租约id)
    结果值: dict[str, Any] = {"成功": not 失败表, "释放数量": len(成功表),
                              "租约id": 成功表, "失败": 失败表}
    if 账本失败:
        结果值["同步错误"] = "占用账本未更新：" + "；".join(账本失败)
    return 结果值


def 回收过期能力占用(存储目录: Path, 心跳超时秒: float = 默认心跳秒,
                 运行库路径: str | None = None) -> dict[str, Any]:
    """回收心跳过期的占用（委托现成的共享回收，同时覆盖能力租约与文件租约）。"""
    库路径 = str(运行库路径) if 运行库路径 else 默认运行库路径()
    服务 = _服务(存储目录)
    过期 = 服务.回收过期占用(心跳超时秒=float(心跳超时秒))
    账本失败: list[str] = []
    for 租约id in 过期:
        说明 = _标账本终态(服务, 库路径, str(租约id), 账本状态_已回收, "心跳过期自动回收")
        if 说明:
            账本失败.append(f"{租约id}: {说明}")
    结果值: dict[str, Any] = {"成功": True, "回收数量": len(过期), "租约id": 过期}
    if 账本失败:
        结果值["同步错误"] = "占用账本未更新：" + "；".join(账本失败)
    return 结果值


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
