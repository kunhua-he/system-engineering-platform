"""核心快照清单模板：快照目录结构骨架（清单/摘要/激活指针）生成与校验。

模板要素（与 核心治理.py 摘要语义一致）：
- 清单.json：范围、文件表（相对路径+sha256）、文件数、时间；
- 摘要.json：聚合摘要（范围+文件表，支持库.适配层.内容摘要）；
- 当前.json：激活指针（目标快照摘要/栅栏令牌/版本）。

回滚切换不可变旧制品、不恢复源码分支：模板只生成制品骨架与元数据，
激活指针仅记录目标摘要；供核心治理与发布回滚复用。

防御：目标目录已存在文件时拒绝覆盖；范围路径逃逸（绝对/..）拒绝。
校验：三文件存在 / 清单与磁盘一致 / 聚合摘要匹配 → 通过或 快照损坏。
"""

from __future__ import annotations

import hashlib
import json
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

# 自举前只能用标准库：本文件可能被当脚本跑（`sys.path[0]` 是 `实现/`），平台模块此刻
# **不可导入** ⇒ 不能调 `公共契约/运行时/导入前缀`（循环依赖）。判据仍是**同一套锚目录**
# （不是 `parents[N]` 那种一改目录结构就静默指错树的层数写法），与共享模块逐字同判；
# 形状由 `测试中心/开发工具/测试_导入前缀.py` 的 `自举段形状` 钉住，改这里必须同批改它。
系统根 = next(
    祖先 for 祖先 in Path(__file__).resolve().parents
    if (祖先 / "支持库").is_dir() and (祖先 / "模块库").is_dir()
)
if str(系统根) not in sys.path:
    sys.path.insert(0, str(系统根))

from 支持库.适配层 import 内容摘要
# 路径边界判定的唯一**判据**节点（2026-09-24 批H-H1）：绝对性 / 盘符 / `~` / `..` 段 / 段内 `.`
# 不再自己写一份，一律转调它（自举段已把 `系统根` 插进 `sys.path`，与上一行同一条导入腿）。
from 支持库.后端.系统核心支持库.路径安全 import 校验相对路径文本
# 生成器落盘的**唯一腿**（2026-09-23「生成器开窗」）：原子写 + 留写入凭据，
# 见 `开发工具/MD文档生成/机器印记.py` 同一处说明。本模块不再自己 `write_text`。
from 支持库.后端.文件系统支持库.文件操作 import 写入文件
# 落盘腿拒绝的**原样错误码载体**（`越界` 等真码不许被中间层收敛掉，2026-09-25）：
# 类型定义在生成器族唯一落盘腿所在的 `模板公共件`，本模块只 import 类型供 except 分支用。
from 支持库.后端.组件规范支持库.实现.模板公共件 import 写入被拒

清单文件名 = "清单.json"
摘要文件名 = "摘要.json"
激活指针文件名 = "当前.json"
排除目录名表 = {"__pycache__"}


def _规范化范围路径(路径: str) -> str:
    """校验范围目录相对路径：拒绝绝对路径与 .. 逃逸。

    判据（2026-09-24 批H-H1）：绝对性 / 盘符 / `~` **不再自己写** —— 转调唯一**判据**节点
    `支持库.后端.系统核心支持库.路径安全.校验相对路径文本`（同一职责只有那一份判据）。
    """
    if not 路径 or 路径 in (".", "/", "\\"):
        raise ValueError(f"空或根路径不允许: {路径!r}")
    判定 = 校验相对路径文本(路径)
    判定值 = 判定.值 if isinstance(判定.值, dict) else {}
    if not 判定.成功 or not 判定值.get("通过"):
        raise ValueError(f"{判定值.get('原因') or '相对路径不合法'}: {路径!r}")
    if any(段 in ("..", ".") for 段 in 路径.replace("\\", "/").split("/")):
        raise ValueError(f"路径逃逸不允许: {路径!r}")
    return 路径


def _聚合摘要(范围目录表: list[str], 文件表: dict[str, str]) -> str:
    """聚合摘要：范围 + 全部文件摘要（与核心治理 摘要语义一致）。"""
    return 内容摘要(json.dumps(
        {"范围": [str(项) for 项 in 范围目录表], "文件表": 文件表},
        ensure_ascii=False, sort_keys=True).encode("utf-8"))


def _收集文件表(范围目录表: list[str], 工作目录: Path) -> dict[str, str]:
    """扫描范围目录表全部正式文件：相对快照目录路径 + sha256。"""
    文件表: dict[str, str] = {}
    for 范围路径 in 范围目录表:
        规范路径 = _规范化范围路径(范围路径)
        范围目录 = (工作目录 / 规范路径).resolve()
        if not 范围目录.is_dir():
            raise OSError(f"范围目录不存在: {规范路径}")
        for 文件 in sorted(范围目录.rglob("*")):
            if not 文件.is_file() or any(段 in 排除目录名表 for 段 in 文件.parts):
                continue
            相对路径 = f"{规范路径}/{文件.relative_to(范围目录).as_posix()}"
            文件表[相对路径] = hashlib.sha256(文件.read_bytes()).hexdigest()
    return dict(sorted(文件表.items()))


def 生成快照清单模板(目标目录: Path, 范围目录表: list[str], *,
                   工作目录: Path | None = None, 版本: str = "1.0.0",
                   栅栏令牌: str = "", 开工ID: str | None = None) -> dict[str, Any]:
    """生成核心快照结构骨架；已存在文件拒绝覆盖；路径逃逸拒绝。

    `开工ID`（2026-09-25 开工-20260925-161955-849f）：本次改动的开工ID，**原样透传**给三个
    元数据落盘调用（`写入文件`）——快照目录落在受管路径时由写腿第二判据核对活跃写租约所有者；
    缺它即写腿回 `越界`，本函数**原样回带该码**（经 `写入被拒`，不收敛成 `快照损坏`）。
    """
    工作根 = Path(工作目录) if 工作目录 else 系统根
    目标 = Path(目标目录)
    if 目标.exists() and any(目标.iterdir()):
        return {"成功": False, "错误码": "已存在",
                "消息": f"快照目录已存在，拒绝覆盖: {目标}", "快照目录": str(目标)}
    try:
        文件表 = _收集文件表(范围目录表, 工作根)
    except (OSError, ValueError) as 错误:
        return {"成功": False, "错误码": "参数无效",
                "消息": f"收集范围文件失败: {错误}", "快照目录": str(目标)}
    if not 文件表:
        return {"成功": False, "错误码": "参数无效",
                "消息": "范围目录表内无正式文件", "快照目录": str(目标)}
    摘要 = _聚合摘要(范围目录表, 文件表)
    时间 = datetime.now().isoformat(timespec="seconds")
    清单 = {"类型": "核心快照清单模板", "范围": list(范围目录表),
            "摘要": 摘要, "文件数": len(文件表), "文件表": 文件表, "时间": 时间}
    激活指针 = {"激活快照": str(目标), "目标摘要": 摘要,
               "栅栏令牌": 栅栏令牌 or uuid.uuid4().hex[:16],
               "版本": 版本, "时间": 时间,
               "说明": "回滚切换不可变旧制品，不恢复源码分支"}
    try:
        目标.mkdir(parents=True, exist_ok=True)
        for 相对路径 in 文件表:
            目标文件 = 目标 / 相对路径
            目标文件.parent.mkdir(parents=True, exist_ok=True)
            # 二进制拷贝：文件系统支持库目前**没有二进制写入腿**（只有文本 `写入文件`），
            # 故这一处如实保留 `write_bytes`、不上报为已收口（见交付回执的「未收口」栏）。
            目标文件.write_bytes((工作根 / 相对路径).read_bytes())
        写入文件(str(目标 / 清单文件名),
               json.dumps(清单, ensure_ascii=False, indent=2), 开工ID=开工ID).确保成功()
        写入文件(str(目标 / 摘要文件名),
               json.dumps({"摘要": 摘要}, ensure_ascii=False), 开工ID=开工ID).确保成功()
        写入文件(str(目标 / 激活指针文件名),
               json.dumps(激活指针, ensure_ascii=False, indent=2), 开工ID=开工ID).确保成功()
    except 写入被拒 as 错误:
        # 写腿第二判据（写入授权）拒绝：**原样回错误码**（`越界`），不收敛成 `快照损坏`
        # —— 那会把「没开工ID / 租约属别的凭证」这个真因洗掉（2026-09-25）。
        return {"成功": False, "错误码": 错误.错误码,
                "消息": 错误.错误说明, "快照目录": str(目标)}
    except (OSError, ValueError) as 错误:
        return {"成功": False, "错误码": "快照损坏",
                "消息": f"快照写入失败: {错误}", "快照目录": str(目标)}
    return {"成功": True, "错误码": "", "快照目录": str(目标),
            "摘要": 摘要, "文件数": len(文件表), "消息": "核心快照清单模板已生成"}


def 校验快照模板(快照目录: Path) -> tuple[bool, str]:
    """校验快照结构：三文件存在 / 清单与磁盘一致 / 聚合摘要匹配。"""
    目录 = Path(快照目录)
    for 文件名 in (清单文件名, 摘要文件名, 激活指针文件名):
        if not (目录 / 文件名).is_file():
            return False, f"快照缺少 {文件名}"
    try:
        清单 = json.loads((目录 / 清单文件名).read_text(encoding="utf-8"))
        摘要文件 = json.loads((目录 / 摘要文件名).read_text(encoding="utf-8"))
        激活指针 = json.loads((目录 / 激活指针文件名).read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as 错误:
        return False, f"快照元数据损坏: {错误}"
    文件表 = 清单.get("文件表")
    摘要 = 清单.get("摘要")
    if not isinstance(文件表, dict) or not isinstance(摘要, str):
        return False, "快照清单字段缺失"
    磁盘文件表: dict[str, str] = {}
    for 文件 in sorted(目录.rglob("*")):
        if not 文件.is_file():
            continue
        相对路径 = 文件.relative_to(目录).as_posix()
        if 相对路径 in (清单文件名, 摘要文件名, 激活指针文件名):
            continue
        磁盘文件表[相对路径] = hashlib.sha256(文件.read_bytes()).hexdigest()
    if 磁盘文件表 != 文件表:
        return False, "快照内容被篡改（磁盘文件摘要与清单不符）"
    范围 = [str(项) for 项 in 清单.get("范围", [])]
    if _聚合摘要(范围, 磁盘文件表) != 摘要:
        return False, "快照内容被篡改（聚合摘要与清单不符）"
    if 摘要文件.get("摘要") != 摘要 or 激活指针.get("目标摘要") != 摘要:
        return False, "快照元数据与清单摘要不一致"
    return True, "快照结构完整"


__all__ = ["生成快照清单模板", "校验快照模板",
           "清单文件名", "摘要文件名", "激活指针文件名"]
