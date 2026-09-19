"""Git 提供者仓库根白名单：提交/合并/切换分支的越界执行防护（高危漏洞修复口径）。

唯一事实源：`MCP工具箱/工作区管理.py` 的 `_提交根白名单:55` 与 `_校验提交根:72`。
该处注释（`工作区管理.py:73-77`）写明修复前的漏洞：入口把调用者传入的 path 直接当
项目根，可对任意 Git 仓执行 `git add -A` + `commit`、`switch` + `merge`（越界提交/合并）。
按哲学第 34 条「安全边界必须落在能力层」——防护只留在工具层，换门（AI 直调能力）即把
漏洞重新打开，故本模块把同一口径下沉到 Git 能力层，`提交`/`合并分支`/`切换分支` 共用。

白名单构成（全部 resolve 后比较；命中规则 = 等于根或位于根内）：
1. 底座仓库根：本包向上定位到的仓库根（含其下 `工程缓存/` 内的一次性仓与 worktree）；
2. 环境变量 `工作区允许提交根`（os.pathsep 分隔）：显式授权其他仓库，需人工决定；
3. 系统临时目录：只用于「自建一次性 Git 仓」的测试与一次性工作区场景
   （业务仓库位于用户目录，不落系统临时目录）；环境变量 `工作区严格提交根`
   = 1/true/yes/on 时关闭该放行。

白名单外一律返回 路径越界（沿用契约已登记、网关侧已定级 400 的错误码，
不新造未登记错误码）；白名单内容只读，不做任何写操作。
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from 公共契约.基础类型.结果类型 import 结果
from 支持库.适配层.Git提供者.实现.白名单 import 失败结果

提交根环境变量 = "工作区允许提交根"
严格提交根环境变量 = "工作区严格提交根"
_真值集合 = {"1", "true", "yes", "on"}


def 底座仓库根() -> Path:
    """底座仓库根：本文件位于 <仓库根>/支持库/适配层/Git提供者/实现/。"""
    return Path(__file__).resolve().parents[4]


def 严格提交根() -> bool:
    """严格模式：`工作区严格提交根` 为真值时，系统临时目录也不再放行。"""
    return os.environ.get(严格提交根环境变量, "").strip().lower() in _真值集合


def 提交根白名单() -> list[Path]:
    """提交/合并/切换分支允许的仓库根白名单（全部 resolve 后比较）。

    与 `工作区管理.py:_提交根白名单` 同口径：底座仓库根 → 环境变量显式加白 →
    系统临时目录（严格模式下不加）。顺序稳定，便于错误说明回带。
    """
    白名单: list[Path] = []
    候选表 = [底座仓库根()]
    for 项 in os.environ.get(提交根环境变量, "").split(os.pathsep):
        if 项.strip():
            候选表.append(Path(项.strip()))
    if not 严格提交根():
        候选表.append(Path(tempfile.gettempdir()))
    for 候选 in 候选表:
        try:
            解析后 = 候选.resolve()
        except OSError:
            continue
        if 解析后 not in 白名单:
            白名单.append(解析后)
    return 白名单


def 校验提交根(仓库路径: object) -> 结果 | None:
    """变更类能力的仓库根校验：白名单外路径一律 路径越界。

    对应 `工作区管理.py:73-77` 的 M1 修复口径——不校验就等于允许对任意 Git 仓
    执行提交/合并/切换分支。命中白名单返回 None（继续后续校验）。
    """
    if not isinstance(仓库路径, str) or not 仓库路径.strip():
        return 失败结果("参数不合法", "仓库路径必须是非空文本")
    try:
        目标 = Path(仓库路径).resolve()
    except OSError as 错误:
        return 失败结果("参数不合法", f"仓库路径无法解析: {错误}")
    白名单 = 提交根白名单()
    if any(目标 == 根 or 目标.is_relative_to(根) for 根 in 白名单):
        return None
    允许文本 = os.pathsep.join(str(根) for 根 in 白名单)
    return 失败结果(
        "路径越界",
        f"仓库根不在白名单内（越界提交/合并/切换分支拒绝）: {目标}；"
        f"授权其他仓库请设置环境变量 {提交根环境变量}（分隔符 {os.pathsep}），"
        f"当前白名单: {允许文本}",
        详情={"仓库根": str(目标), "白名单": [str(根) for 根 in 白名单]},
    )
