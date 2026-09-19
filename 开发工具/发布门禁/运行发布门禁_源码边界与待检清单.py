"""正式源码边界与待检清单。

内容：`正式源码目录名表`、`_正式Python源码文件`、`_是聚合父包`、`_正式待检包目录`、
`_监听端口快照`、`_是否已废弃包`、`_校验文件清单摘要`。

**本文件由 `开发工具/发布门禁/运行发布门禁.py` 按检查项簇**逐字搬移**（成员名一个不改、
判据一处不复制）。依赖方向**单向**：本文件只依赖底座/同族子模块，**不得 import 主文件**
（主文件 import 本文件；反向 import 会成循环）。主文件仍 re-export 本文件全部对外符号，
故 `from 开发工具.发布门禁.运行发布门禁 import <名>` 照旧可用。
"""

from __future__ import annotations

from 开发工具.发布门禁.运行发布门禁_底座 import (
    系统根,
)
from pathlib import Path
from 开发工具.公开调用完整性门禁 import _是聚合父包 as _聚合父包权威判据
import subprocess

正式源码目录名表 = (
    "公共契约", "平台控制面", "启动监督器", "运行核心", "前端核心", "后端核心",
    "支持库", "模块库", "项目适配层", "开发工具", "客户端", "示例项目",
)
def _正式Python源码文件() -> list[Path]:
    """只枚举生产源码边界；发布门禁不读取开发期测试源码。"""
    return sorted(
        文件
        for 名称 in 正式源码目录名表
        for 文件 in (系统根 / 名称).rglob("*.py")
        if (系统根 / 名称).is_dir() and "__pycache__" not in 文件.parts
    )
def _是聚合父包(包目录: Path) -> bool:
    """包目录是不是「聚合父包」（只有目录聚合视图、自己不拥有任何能力）。

    **本函数已不再自持判据**：口径直接取 `开发工具/公开调用完整性门禁._是聚合父包`
    （2026-09-17 修 fail-open 后的权威版本），与 `开发工具/项目编译/正式包索引` 的
    owner 口径同源。保留本包装只是为了不改动本文件内既有调用点。

    修前本文件自带一份**更宽松**的判据：「只要目录内存在任意后代 包声明.json 就整包
    豁免」，连「无 能力定义.json」都不要求，也不看能力 id 的归属。后果：一个自带
    能力定义.json/能力契约/实现的真实包，塞一个占位子目录即整包逃出「包结构完整 /
    包声明合法 / 完整性摘要」待检清单（夹具实测：真包 包声明缺 `类型` + 占位子目录
    时，修前违规条目 0 条）。现判据三条件缺一不可：①无 能力定义.json；②有子包
    包声明.json（递归，跳过保留目录）；③自己声明的能力 id 全部由子包声明持有。
    读不成 包声明.json → False（fail-closed）。
    """
    return _聚合父包权威判据(包目录)
def _正式待检包目录(根: Path) -> list[Path]:
    """正式待检包清单：`支持库` + `模块库` 的全部包（排除模板 / 已废弃 / 聚合父包）。

    抽成独立函数是为了让夹具用**同一份生产代码**在隔离根上跑「待检清单选择」，
    验证「聚合父包豁免判据」的真假两向行为，而不是靠复制表达式（复制件会随生产
    代码漂移，正是这类门禁漏洞的温床）。
    """
    return sorted(
        [路径.parent for 路径 in (根 / "支持库").rglob("包声明.json")
         if not _是否已废弃包(路径.parent) and not _是聚合父包(路径.parent)]
        + [路径.parent for 路径 in (根 / "模块库").rglob("包声明.json")
           if 路径.parent.name != "_模板" and not _是否已废弃包(路径.parent)
           and not _是聚合父包(路径.parent)]
    )
def _监听端口快照() -> set[str]:
    """读取当前 TCP 监听端点；工具不可用或输出异常时 fail-closed。"""
    try:
        结果 = subprocess.run(
            ["lsof", "-nP", "-iTCP", "-sTCP:LISTEN"],
            capture_output=True, timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired) as 错误:
        raise RuntimeError(f"无法获取监听端口快照: {错误}") from 错误
    if 结果.returncode != 0:
        错误输出 = 结果.stderr or b""
        if isinstance(错误输出, bytes):
            错误输出 = 错误输出.decode("utf-8", errors="replace")
        raise RuntimeError(f"监听端口快照失败（退出码 {结果.returncode}）: {错误输出[:200]}")
    原始输出 = 结果.stdout or b""
    if isinstance(原始输出, bytes):
        # lsof 的命令/路径字段可能来自系统原始字节，不能让本地编码污染发布门禁。
        原始输出 = 原始输出.decode("utf-8", errors="replace")
    端点表: set[str] = set()
    for 行 in 原始输出.splitlines()[1:]:
        列 = 行.split()
        if len(列) < 9:
            continue
        端点表.add(列[8].replace("(LISTEN)", "").strip())
    return 端点表
def _是否已废弃包(包目录: Path) -> bool:
    """已废弃包保留文件但不参与装配/审计/门禁（与发现器/加载器同口径）。"""
    try:
        import json as _json
        声明 = _json.loads((包目录 / "包声明.json").read_text(encoding="utf-8"))
        return bool(声明.get("已废弃"))
    except Exception:
        return False
def _校验文件清单摘要(包目录: Path) -> tuple[bool, str]:
    """委托唯一校验器：完整性摘要.json 必须为文件清单格式且与真实文件闭合。"""
    from 支持库.后端.组件规范支持库 import 校验完整性摘要

    通过, 问题列表 = 校验完整性摘要(包目录)
    if 通过:
        return True, "逐文件校验通过，清单与实际文件闭合"
    return False, "；".join(问题列表[:3])
