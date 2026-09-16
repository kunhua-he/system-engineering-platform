"""第十四阶段第 7 项（未声明提供者直连规则）真实扫描回归测试。

A-3 修复点：该项修前只跑两段硬编码样例（`import grpc` + 纯净函数），全仓
`直连规则注册表` 唯一调用点就在门禁里，从未跑在真实 `支持库/适配层/**` 上
—— 注册表整体坏掉或适配层直连漂移都不会被发现，属恒绿。

本文件锁三件事：
① 真实仓库：真实适配层扫描面非空、扫描真实通过（详情带文件数/命中数）；
② 扫描面为空（目录被移走）必须判红，不得恒绿；
③ 真实磁盘上的白名单外未登记直连（如 zmq）必须判红，白名单内已知模式
   （进程）只如实计数上报 —— 都不允许被过滤掉。
"""

from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

系统根 = Path(__file__).resolve().parents[2]
if str(系统根) not in sys.path:
    sys.path.insert(0, str(系统根))

from 开发工具.发布门禁.第十四阶段门禁 import (  # noqa: E402
    _遍历适配层源码, _项7_直连规则, _直连对照复算,
)


def 建适配层(根: Path, 文件名: str, 源码: str) -> Path:
    """在临时根建一个真实适配层源码文件（模拟 provider 实现）。"""
    路径 = 根 / "支持库" / "适配层" / "样本提供者" / "实现" / 文件名
    路径.parent.mkdir(parents=True, exist_ok=True)
    路径.write_text(源码, encoding="utf-8")
    return 路径


class Test第十四阶段直连规则真实扫描(unittest.TestCase):
    def test_真实仓库扫描面非空且通过(self) -> None:
        文件表 = _遍历适配层源码(系统根)
        self.assertTrue(文件表, "真实适配层源码清单不得为空（否则本项恒绿）")
        名称, 通过, 详情 = _项7_直连规则(系统根)
        self.assertEqual(名称, "第十四阶段-未声明提供者直连规则")
        self.assertTrue(通过, 详情)
        self.assertIn(f"真实适配层: 文件{len(文件表)}", 详情)
        self.assertIn("对照复算一致:True", 详情)

    def test_扫描面为空必须判红(self) -> None:
        空根 = Path(tempfile.mkdtemp(prefix="直连规则空根_"))
        self.addCleanup(shutil.rmtree, 空根, ignore_errors=True)
        self.assertEqual(_遍历适配层源码(空根), [])
        _, 通过, 详情 = _项7_直连规则(空根)
        self.assertFalse(通过, "扫描面为空必须判红（防恒绿）")
        self.assertIn("真实适配层扫描面为空", 详情)

    def test_白名单外未登记直连真实磁盘上必须判红(self) -> None:
        根 = Path(tempfile.mkdtemp(prefix="直连规则样本根_"))
        self.addCleanup(shutil.rmtree, 根, ignore_errors=True)
        建适配层(根, "样本zeromq.py", "import zmq\n\n通道 = zmq.Context()\n")
        建适配层(根, "样本进程.py", "import subprocess\n\n进程 = subprocess.Popen(['ls'])\n")
        _, 通过, 详情 = _项7_直连规则(根)
        self.assertFalse(通过, f"zmq（白名单外未登记）必须判红: {详情}")
        self.assertIn("白名单外未登记:1", 详情)
        # 白名单内已知模式（进程）不得被过滤掉：仍如实计入未登记上报
        self.assertIn("未登记3条", 详情)
        self.assertIn("进程2", 详情)
        self.assertIn("zeromq1", 详情)

    def test_对照复算对真实源码有独立信号(self) -> None:
        根 = Path(tempfile.mkdtemp(prefix="直连规则对照根_"))
        self.addCleanup(shutil.rmtree, 根, ignore_errors=True)
        文件 = 建适配层(根, "样本进程.py", "import subprocess\n\n进程 = subprocess.Popen(['ls'])\n")
        from 开发工具.复用审计.提供者直连规则 import 直连规则注册表

        特征表 = 直连规则注册表().导出规则()["内置规则"]
        对照 = _直连对照复算(文件.read_text(encoding="utf-8"), 特征表)
        self.assertIsNotNone(对照)
        assert 对照 is not None
        self.assertTrue(对照, "对照复算必须能独立命中真实源码（否则对照是空实现）")
        self.assertEqual(sorted({项["模式"] for 项 in 对照}), ["进程"])
        self.assertEqual(len(对照), 2, f"import + Popen 两处命中: {对照}")
        self.assertIsNone(_直连对照复算("def 坏(:\n", 特征表))


if __name__ == "__main__":
    unittest.main(verbosity=2)
