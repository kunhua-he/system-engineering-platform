"""第十四阶段工作包19：灾难恢复与可信仓库攻击审计（P2-19）。

只读审计模块：对 权威数据备份契约/新机器恢复编排器/可信仓库元数据/二阶恢复
真实注入七类攻击——空目录恢复、备份损坏、旧快照重放、过期元数据、签名替换、
恢复中强杀、备份缺失。发现生产缺陷只生成阻断清单，不修改任何被测实现，
阻断项由主 Agent 在 S2 串行修复。
"""
from __future__ import annotations

import sys
from pathlib import Path

_系统根 = Path(__file__).resolve().parents[3]
_自身目录 = Path(__file__).resolve().parent
for _路径 in (_系统根, _自身目录,
              _系统根 / "平台控制面" / "备份恢复",
              _系统根 / "平台控制面" / "包仓库"):
    if str(_路径) not in sys.path:
        sys.path.insert(0, str(_路径))

from 阻断清单 import 阻断清单
from 恢复攻击 import 恢复攻击审计
from 仓库攻击 import 仓库攻击审计
from 强杀审计 import 强杀攻击审计

__all__ = ["阻断清单", "恢复攻击审计", "仓库攻击审计", "强杀攻击审计"]
