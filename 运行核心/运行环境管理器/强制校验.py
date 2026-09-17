"""提供者依赖锁强制校验：启动/装配前硬门禁（fail-closed）。

提供者在被启动或装配前必须通过本校验；任一规则不满足即拒绝运行：

1. 缺锁：提供者目录缺 依赖锁.json → 拒绝
2. 空锁：锁存在但 包 与 直接依赖 均为空 → 拒绝
3. 精确版本：锁内依赖必须是精确版本（禁止 ">=1.0" / "*" / "待定" 等范围或占位版本）
4. 依赖闭包：直接依赖必须已全部纳入 依赖闭包（闭包缺失即拒绝；
   无传递依赖的纯库允许闭包与直接依赖等集，规则判定"覆盖"而非"非空"）
5. 环境指纹：锁内 环境（Python/操作系统/CPU）与当前运行环境一致 ——
   Python 只比主次版本（3.14.4 与 3.14.9 一致；3.13 与 3.14 不一致）、
   操作系统只比系统大类（忽略版本与 Build 号，macOS/Darwin 同族）、
   CPU 架构精确一致；版本号无法解析即明确失败，不放行
6. 隔离环境：提供者必须在独立受管环境运行（复用 环境目录/校验环境）；
   环境缺失或与依赖锁摘要不匹配 → 拒绝并提示重建
7. 错误回滚：校验失败时复用 废弃环境 清理半态环境，不留残留

对外入口：校验提供者环境(提供者目录, 提供者id) → 校验结果（成功/问题列表）。
"""

from __future__ import annotations

import json
import platform
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from 公共契约.运行时 import 平台适配
from 运行核心.运行环境管理器.环境管理器 import (
    计算环境摘要,
    废弃环境,
    校验环境,
    环境目录,
    _是pip包,
)
from 公共契约.基础类型.逻辑类型 import 真, 假

锁文件名 = "依赖锁.json"
占位版本表 = {
    "*", "latest", "最新", "最新版本", "任意", "任意版本", "any",
    "待定", "未定", "todo", "稳定", "稳定版", "stable", "dev", "占位",
}


def 是精确版本(版本: Any) -> bool:
    """版本是否为精确锁定版本（禁止范围/通配/占位写法）。"""
    if not isinstance(版本, str) or not 版本.strip():
        return 假
    值 = 版本.strip()
    if 值.lower() in 占位版本表:
        return 假
    if 值[0] in "=<>!~^*":
        return 假
    if any(标记 in 值 for 标记 in (" ", ",", ";", "[", "]", "(", ")", "+")):
        return 假
    if not 值[0].isdigit():
        return 假
    return all(字符.isalnum() or 字符 in "._-" for 字符 in 值)


def _归一化系统名(系统名: str) -> str:
    """归一化系统名：去掉括号/空格后缀；macOS 与 Darwin 视为同族。"""
    名 = 系统名.strip().lower()
    for 分隔 in ("（", "(", " "):
        if 分隔 in 名:
            名 = 名.split(分隔)[0]
    if 名 == "macos":
        名 = "darwin"
    return 名


def 系统匹配(锁内系统: Any, 当前系统: str) -> bool:
    """锁内 操作系统 与当前系统是否匹配（兼容 "macOS（Darwin 26.5.2）" 写法）。"""
    if not isinstance(锁内系统, str) or not 锁内系统.strip():
        return 假
    return _归一化系统名(锁内系统) == _归一化系统名(当前系统)


def _版本主次段(版本: Any) -> tuple[int, int]:
    """解析版本号的主次段（major.minor）；解析失败抛 ValueError（禁止默默放行）。"""
    if not isinstance(版本, str) or not 版本.strip():
        raise ValueError(f"版本号不是非空字符串：{版本!r}")
    片段 = 版本.strip().split(".")
    if len(片段) < 2:
        raise ValueError(f"版本号缺少主次两段（形如 3.14 或 3.14.4）：{版本!r}")
    结果: list[int] = []
    for 序号, 段 in enumerate(片段[:2]):
        if not 段.isascii() or not 段.isdigit():
            raise ValueError(f"版本号 {版本!r} 的 {'主' if 序号 == 0 else '次'}版本段不是纯数字：{段!r}")
        结果.append(int(段))
    return 结果[0], 结果[1]


def 主次版本一致(锁内版本: Any, 当前版本: Any) -> bool:
    """主次版本是否一致：3.14 / 3.14.4 / 3.14.9 视为一致，3.13 与 3.14 不一致。

    只比主次版本是「相对安全，不做绝对安全」的口径（哲学第 9 条 5 项）：依赖锁
    声明的是系统大类内的可部署环境，把作者的 Python 微版本/Build 号写死进门禁
    会让本来就对得上的机器被拒之门外；而真正的环境错配（如 3.13 与 3.14）仍然
    明确拒绝。版本号解析失败抛 ValueError，由调用方转成明确的校验问题。
    """
    return _版本主次段(锁内版本) == _版本主次段(当前版本)


@dataclass
class 校验问题:
    """一条依赖锁校验问题。"""

    提供者id: str
    原因: str
    路径: str = ""

    def 转字典(self) -> dict[str, Any]:
        return {"提供者id": self.提供者id, "原因": self.原因, "路径": self.路径}


@dataclass
class 校验结果:
    """提供者依赖锁强制校验结果。"""

    问题列表: list[校验问题] = field(default_factory=list)

    @property
    def 成功(self) -> bool:
        return not self.问题列表

    def 转字典(self) -> dict[str, Any]:
        return {"成功": self.成功, "问题列表": [问题.转字典() for 问题 in self.问题列表]}


def 校验提供者环境(提供者目录: Path, 提供者id: str = "", *, 自动清理: bool = 真) -> 校验结果:
    """提供者启动/装配前强制校验（fail-closed：任一规则不满足即拒绝运行）。

    提供者id 缺省取 提供者目录.name；自动清理 为真时校验失败会废弃半态环境。
    """
    提供者id = 提供者id or 提供者目录.name
    锁文件 = 提供者目录 / 锁文件名
    结果 = 校验结果()

    # 规则 1：缺锁
    if not 锁文件.is_file():
        结果.问题列表.append(校验问题(
            提供者id, "缺少 依赖锁.json（禁止运行：提供者必须携带精确依赖锁）", str(锁文件),
        ))
        return 结果
    try:
        锁 = json.loads(锁文件.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as 错误:
        结果.问题列表.append(校验问题(
            提供者id, f"依赖锁.json 无法解析（{错误}），禁止运行", str(锁文件),
        ))
        return 结果
    if not isinstance(锁, dict):
        结果.问题列表.append(校验问题(提供者id, "依赖锁.json 顶层必须是对象", str(锁文件)))
        return 结果

    包表 = 锁.get("包", [])
    直接依赖 = 锁.get("直接依赖", [])
    if not isinstance(包表, list) or not isinstance(直接依赖, list):
        结果.问题列表.append(校验问题(提供者id, "包/直接依赖 必须是列表", str(锁文件)))

    # 规则 2：空锁（包 与 直接依赖 均为空 → 无可校验内容，直接拒绝）
    if isinstance(包表, list) and isinstance(直接依赖, list) and not 包表 and not 直接依赖:
        结果.问题列表.append(校验问题(
            提供者id, "空锁（包 与 直接依赖 均为空），禁止运行", str(锁文件),
        ))
        return 结果

    # 规则 3：精确版本（包）
    if isinstance(包表, list):
        for 项 in 包表:
            if not isinstance(项, dict):
                结果.问题列表.append(校验问题(提供者id, "包条目必须是对象", str(锁文件)))
                continue
            名称 = 项.get("名称", "")
            版本 = 项.get("版本", "")
            模块名 = 项.get("模块名", "")
            if not 名称 or not isinstance(名称, str):
                结果.问题列表.append(校验问题(提供者id, "包条目缺少 名称", str(锁文件)))
            if not 模块名 or not isinstance(模块名, str):
                结果.问题列表.append(校验问题(提供者id, f"包条目 {名称} 缺少 模块名", str(锁文件)))
            if not 是精确版本(版本):
                结果.问题列表.append(校验问题(
                    提供者id, f"包 {名称} 版本 {版本!r} 不是精确版本（禁止范围/通配/占位版本）", str(锁文件),
                ))

    # 规则 3：精确版本（直接依赖）+ 规则 4：依赖闭包覆盖
    if isinstance(直接依赖, list):
        for 项 in 直接依赖:
            if not isinstance(项, dict):
                结果.问题列表.append(校验问题(提供者id, "直接依赖条目必须是对象", str(锁文件)))
                continue
            名称 = 项.get("名称", "")
            版本 = 项.get("版本", "")
            if not 名称 or not isinstance(名称, str):
                结果.问题列表.append(校验问题(提供者id, "直接依赖条目缺少 名称", str(锁文件)))
            if not 是精确版本(版本):
                结果.问题列表.append(校验问题(
                    提供者id, f"直接依赖 {名称} 版本 {版本!r} 不是精确版本（禁止范围/通配/占位版本）", str(锁文件),
                ))

    闭包 = 锁.get("依赖闭包")
    if not isinstance(闭包, list):
        结果.问题列表.append(校验问题(
            提供者id, "依赖闭包 缺失（必须声明直接依赖的完整传递闭包）", str(锁文件),
        ))
    else:
        # 规则 4：直接依赖必须已全部纳入闭包（覆盖判定，非"闭包非空"判定）
        for 项 in 直接依赖 if isinstance(直接依赖, list) else []:
            if not isinstance(项, dict) or not 项.get("名称"):
                continue
            名称 = 项.get("名称", "")
            版本 = 项.get("版本", "")
            已纳入 = any(
                isinstance(闭包项, dict)
                and 闭包项.get("名称") == 名称
                and str(闭包项.get("版本", "")) == 版本
                for 闭包项 in 闭包
            )
            if not 已纳入:
                结果.问题列表.append(校验问题(
                    提供者id, f"直接依赖 {名称}=={版本} 未纳入 依赖闭包（闭包必须完整覆盖直接依赖）", str(锁文件),
                ))
        # 规则 3：闭包内版本同样必须精确
        for 闭包项 in 闭包:
            if not isinstance(闭包项, dict):
                结果.问题列表.append(校验问题(提供者id, "依赖闭包条目必须是对象", str(锁文件)))
                continue
            名称 = 闭包项.get("名称", "")
            版本 = 闭包项.get("版本", "")
            if not 名称 or not isinstance(名称, str):
                结果.问题列表.append(校验问题(提供者id, "依赖闭包条目缺少 名称", str(锁文件)))
            elif not 是精确版本(版本):
                结果.问题列表.append(校验问题(
                    提供者id, f"闭包依赖 {名称} 版本 {版本!r} 不是精确版本（禁止范围/通配/占位版本）", str(锁文件),
                ))

    # 规则 5：环境指纹（锁内声明环境 必须与当前运行环境一致）
    当前python = sys.version.split()[0]
    当前系统 = platform.system()
    当前架构 = platform.machine()
    环境 = 锁.get("环境")
    if not isinstance(环境, dict) or not 环境:
        结果.问题列表.append(校验问题(
            提供者id, "环境 指纹缺失（必须声明 Python/操作系统/CPU）", str(锁文件),
        ))
    else:
        try:
            python一致 = 主次版本一致(环境.get("Python"), 当前python)
        except ValueError as 错误:
            结果.问题列表.append(校验问题(
                提供者id,
                f"环境指纹无法判定：{错误}（锁内 Python {环境.get('Python')!r} / 当前 {当前python}），"
                f"禁止运行（请按当前环境重建依赖锁）",
                str(锁文件),
            ))
        else:
            if not python一致:
                结果.问题列表.append(校验问题(
                    提供者id,
                    f"环境指纹不符：锁内 Python {环境.get('Python')!r} ≠ 当前 {当前python}"
                    f"，判定依据：主次版本不一致（请按当前环境重建依赖锁）",
                    str(锁文件),
                ))
        if not 系统匹配(环境.get("操作系统"), 当前系统):
            结果.问题列表.append(校验问题(
                提供者id, f"环境指纹不符：锁内 操作系统 {环境.get('操作系统')!r} ≠ 当前 {当前系统}（请按当前环境重建依赖锁）", str(锁文件),
            ))
        if 环境.get("CPU") != 当前架构:
            结果.问题列表.append(校验问题(
                提供者id, f"环境指纹不符：锁内 CPU {环境.get('CPU')!r} ≠ 当前 {当前架构}（请按当前环境重建依赖锁）", str(锁文件),
            ))

    # 规则 6：隔离环境（独立受管环境必须已按当前锁摘要就绪）
    # 仅外部应用/系统工具（非 pip 包）的提供者使用系统解释器，无独立 venv
    pip包表 = [包 for 包 in 锁.get("包", []) if _是pip包(包)]
    if not pip包表:
        return 结果
    摘要 = 计算环境摘要(锁, 提供者id)
    目标 = 环境目录(提供者目录, 摘要)
    # 解释器路径按平台解析（POSIX 与 Windows 的 venv 布局不同，后者在 Scripts/ 下）：
    # 这是「独立受管环境就绪」的唯一判定出口，硬编码 POSIX 布局会让非 POSIX 平台
    # 恒判「环境缺失」，从而每个 pip 提供者都在装配期报不可用。
    解释器 = 平台适配.虚拟环境解释器路径(目标)
    环境就绪 = 解释器.is_file() and 校验环境(解释器, 锁)
    if not 环境就绪:
        # 规则 7：错误回滚——半态环境（存在但无效）废弃清理，不留残留
        if 目标.exists() and 自动清理:
            废弃环境(提供者目录)
        结果.问题列表.append(校验问题(
            提供者id,
            f"独立受管环境缺失或与依赖锁摘要不匹配（环境摘要 {摘要}），禁止运行；请先重建（确保环境）",
            str(目标),
        ))
    return 结果
