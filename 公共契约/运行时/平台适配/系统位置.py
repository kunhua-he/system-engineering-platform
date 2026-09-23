"""系统位置表 / 家目录敏感位置表（危险路径护栏的**平台差异**收口，2026-09-21 #174）。"""

from __future__ import annotations

from 公共契约.运行时.平台适配.判定 import 是Windows


# ── 系统位置表 / 家目录敏感位置表（危险路径护栏的**平台差异**收口，2026-09-21 #174）──
#
# 起因：`支持库/后端/文件系统支持库/文件操作/实现/危险路径.py` 的判据表原本**全是 Unix 路径**
# （`/etc`、`/private/etc`、`/System`、`/usr`…）。Windows 上 `Path("/etc")` 会解析成
# **当前盘根下的 `\etc`**，而真正该拦的 `C:\Windows\System32\drivers\etc\hosts`、
# 启动文件夹、`C:\Program Files`、PowerShell profile **一条判据都没有**
# （只有 `~/.ssh` 因同名侥幸命中）。
#
# 平台差异（POSIX 系统位置 vs Windows 系统位置）是**同一件事的两种语义**，按
# 「平台判断只许出现在收口层」铁律收口到本模块：调用点（危险路径.py）只调
# `系统位置表()` / `家目录敏感位置表()` 拿表，**不写 `是Windows()` 分支**
# （写了就是「取值后自行分叉」，会被 `开发工具/验证门禁/平台判断越界检测.py` 规则二判红）。

#: POSIX（macOS / Linux）系统位置：目录本身及其全部子路径都在护栏范围内
POSIX系统位置表: tuple[str, ...] = (
    "/etc",
    "/private/etc",
    "/System",
    "/private/System",
    "/usr",
    "/bin",
    "/sbin",
    "/var/db",
    "/private/var/db",
    "/Library/LaunchDaemons",
    "/Library/LaunchAgents",
    "/dev",
    "/boot",
)

#: Windows 系统位置（#174 补，2026-09-21）：全部为**绝对路径**（盘符 + 反斜杠），
#: 按微软文档的固定位置取，不做模糊匹配、不做环境变量展开（本表只列**固定字面位置**）。
#:
#: 覆盖 #174 点名的四类：① `drivers\etc`（含 hosts）；② 启动文件夹
#: （`ProgramData\…\Start Menu`，含其下 `Programs\StartUp`）；③ `C:\Program Files`（含 x86）；
#: ④ PowerShell profile（`WindowsPowerShell` 整棵，含机器级 `v1.0\profile.ps1`）。
#: 用户级 PowerShell profile（`~/Documents/PowerShell`）与用户启动文件夹属**家目录内**，
#: 列在 `Windows家目录敏感位置表`。
Windows系统位置表: tuple[str, ...] = (
    r"C:\Windows\System32\drivers\etc",
    r"C:\Windows\System32\config",
    r"C:\Windows\System32\WindowsPowerShell",
    r"C:\Windows\System32",
    r"C:\Windows",
    r"C:\Program Files",
    r"C:\Program Files (x86)",
    r"C:\ProgramData\Microsoft\Windows\Start Menu",
)

#: 家目录内的敏感位置（**相对家目录的路径**；目录本身及其子路径都在护栏范围内）
#: —— POSIX 分支与 #174 修前逐字一致（`.ssh` + `Library/Keychains`）
POSIX家目录敏感位置表: tuple[str, ...] = (
    ".ssh",
    "Library/Keychains",
)

#: Windows 家目录内的敏感位置（#174 补）：`.ssh` 两平台同名故两表都有；
#: 另补用户级 PowerShell 配置目录与用户启动文件夹。
Windows家目录敏感位置表: tuple[str, ...] = (
    ".ssh",
    r"Documents\PowerShell",
    r"Documents\WindowsPowerShell",
    r"AppData\Roaming\Microsoft\Windows\Start Menu\Programs\Startup",
)


def 系统位置表() -> tuple[str, ...]:
    """返回**当前平台**的「系统位置」表（危险路径护栏的判据数据源；绝对路径，含子路径）。

    平台差异的唯一落点：POSIX 系 → ``POSIX系统位置表``；Windows → ``Windows系统位置表``。
    调用点（`危险路径.py`）只调本函数拿表并逐条比对，**不写平台分支**。

    不认识的平台（``当前平台() == "未知"``）→ 返回 ``POSIX系统位置表``：
    与 #174 修前的既有行为逐字一致（修前只有 POSIX 表），是**保持现状**而不是新决策。
    """
    if 是Windows():
        return Windows系统位置表
    return POSIX系统位置表


def 家目录敏感位置表() -> tuple[str, ...]:
    """返回**当前平台**的「家目录内敏感位置」表（相对家目录的路径，含子路径）。

    平台差异的唯一落点：POSIX 系 → ``POSIX家目录敏感位置表``；Windows → ``Windows家目录敏感位置表``。
    调用点（`危险路径.py`）只调本函数拿表，**不写平台分支**。
    不认识的平台 → 返回 ``POSIX家目录敏感位置表``（与 #174 修前行为逐字一致）。
    """
    if 是Windows():
        return Windows家目录敏感位置表
    return POSIX家目录敏感位置表
