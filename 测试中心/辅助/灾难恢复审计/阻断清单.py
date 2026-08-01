"""工作包19 阻断清单：汇总七类攻击审计结果，生成生产缺陷阻断清单。"""
from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from 备份缺失审计 import 备份缺失攻击审计
from 恢复攻击 import 恢复攻击审计
from 仓库攻击 import 仓库攻击审计
from 强杀审计 import 强杀攻击审计


def 审计全部场景() -> list[dict]:
    """真实注入七类攻击（每类独立临时目录），按固定顺序返回全部结果。"""
    临时根 = Path(tempfile.mkdtemp(prefix="工作包19攻击审计_"))
    try:
        恢复审计 = 恢复攻击审计(临时根)
        仓库审计 = 仓库攻击审计(临时根)
        强杀审计 = 强杀攻击审计(临时根 / "强杀现场")
        缺失审计 = 备份缺失攻击审计(临时根)
        return [恢复审计.审计空目录恢复(), 恢复审计.审计备份损坏(),
                恢复审计.审计旧快照重放(), 仓库审计.审计过期元数据(),
                仓库审计.审计签名替换(), 强杀审计.审计(), 缺失审计.审计()]
    finally:
        shutil.rmtree(临时根, ignore_errors=True)


def 阻断清单(结果表: list[dict] | None = None) -> list[dict]:
    """只返回存在缺陷的场景（阻断项）；全部通过返回空表。"""
    结果表 = 结果表 if 结果表 is not None else 审计全部场景()
    return [{"场景": 结果["场景"], "缺陷": 结果["缺陷"]}
            for 结果 in 结果表 if not 结果["防御有效"]]
