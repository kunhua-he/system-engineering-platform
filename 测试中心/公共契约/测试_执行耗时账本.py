"""执行耗时账本的判据（含反向验证）。

覆盖三件事：
1. **开关关着时零写入** —— 不是「写了个空行」，是**一个字节都不碰盘**（华哥口径：
   「如果是关了日志功能，直接丢了就行……不用硬盘 IO」）。
2. 开关打开后字段真的落进去（时刻/来源/命令/工作目录/退出码/耗时秒/输出字节）。
3. **反向**：把 `开关()` 换成恒真，第 1 条必须变红 —— 否则「关时零写入」可能是
   「恰好这次没写」而不是开关在起作用，等于没证明。

夹具一律用 `系统库运行库` 环境变量指到 `tempfile` 临时库（该环境变量就是生产口径的
覆盖口，见模块 docstring），**不碰真仓库的 底座运行.db**。
"""

from __future__ import annotations

import os
import shutil
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

if str(Path(__file__).resolve().parents[2]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from 公共契约.运行时 import 执行耗时账本 as 账本


class Test执行耗时账本(unittest.TestCase):

    def setUp(self):
        self.临时根 = Path(tempfile.mkdtemp(prefix="测试_执行耗时账本_"))
        self.库 = self.临时根 / "底座运行.db"
        self.原库 = os.environ.get(账本.库环境变量)
        self.原开关 = os.environ.get(账本.开关环境变量)
        os.environ[账本.库环境变量] = str(self.库)
        os.environ.pop(账本.开关环境变量, None)

    def tearDown(self):
        for 名, 原值 in ((账本.库环境变量, self.原库), (账本.开关环境变量, self.原开关)):
            if 原值 is None:
                os.environ.pop(名, None)
            else:
                os.environ[名] = 原值
        shutil.rmtree(self.临时根, ignore_errors=True)

    def _行表(self) -> list[tuple]:
        连接 = sqlite3.connect(str(self.库))
        try:
            表 = 连接.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                (账本.表名,)).fetchone()
            if 表 is None:
                return []
            return list(连接.execute(f"SELECT {', '.join(账本.列)} FROM {账本.表名}"))
        finally:
            连接.close()

    def test_关着时一个字节都不写盘(self):
        self.assertFalse(账本.开关(), "夹具前提：开关必须处于关的状态")
        账本.记一笔("自检", "echo 关", 1.0, 0)
        账本.记一笔("自检", "echo 关2", 2.0, 0)
        # ★ 连**库文件都不该被创建**：建库就要碰盘，而关掉的口径是「不用硬盘 IO」。
        # 这一条必须**先**判：`_行表()` 里的 `sqlite3.connect` 自己就会把库文件建出来
        # （实测：先调 `_行表()` 再判存在性，红的是测试自己的辅助函数，不是被测代码）。
        self.assertFalse(self.库.exists(), "开关关着时不得创建库文件（创建即碰盘）")
        self.assertEqual([], self._行表(), "开关关着时不得落任何行")

    def test_开着时字段真的落进去(self):
        os.environ[账本.开关环境变量] = "真"
        账本.记一笔("某能力.某方法", "python3.14 -m 某事", 12.5, 退出码=3,
                  工作目录="/tmp", 输出字节=42)
        行 = self._行表()
        self.assertEqual(1, len(行), f"应恰好一行，实际：{行}")
        时刻, 来源, 命令, 工作目录, 退出码, 耗时秒, 输出字节 = 行[0]
        self.assertEqual("某能力.某方法", 来源)
        self.assertEqual("python3.14 -m 某事", 命令)
        self.assertEqual("/tmp", 工作目录)
        self.assertEqual(3, 退出码)
        self.assertAlmostEqual(12.5, 耗时秒, places=3)
        self.assertEqual(42, 输出字节)
        self.assertRegex(时刻, r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$")

    def test_反向_开关恒真时关档零写入必红(self):
        """把开关换成恒真，「关着时不写盘」这条必须变红 —— 否则它证明不了开关在起作用。

        没有这一拍，上面那条在「实现里根本没判开关」的情况下照样可能绿
        （只是恰好那次没写），那就成了装饰。
        """
        原 = 账本.开关
        账本.开关 = lambda: True
        try:
            账本.记一笔("自检", "echo 关", 1.0, 0)
        finally:
            账本.开关 = 原
        self.assertNotEqual([], self._行表(),
                            "反向样本：开关恒真时必须真的落盘（否则正向那条是假绿）")

    def test_超长命令按上限截断(self):
        os.environ[账本.开关环境变量] = "真"
        账本.记一笔("自检", "x" * (账本.命令上限 + 500), 0.1, 0)
        命令 = self._行表()[0][2]
        self.assertEqual(账本.命令上限, len(命令),
                         "账本是索引不是全文库：超长命令必须截断，否则单行会把库撑爆")

    def test_自检报出开关库路径与行数(self):
        os.environ[账本.开关环境变量] = "真"
        账本.记一笔("自检", "echo 一", 0.1, 0)
        信息 = 账本.自检()
        self.assertTrue(信息["开关"])
        self.assertEqual(str(self.库), 信息["库路径"], "自检必须走同一个库路径口径")
        self.assertEqual(1, 信息["行数"])
        self.assertEqual("", 信息["最近写入错误"])

    def test_写不进去也不影响被测执行(self):
        """观测设施不是判据：库路径指向一个**不可写**的位置时，`记一笔` 必须静默吞掉。

        这条与仓内「fail-closed」相反是**有意的**：判据取不到证据要判红，
        而观测取不到数据不能把生产执行判死（见模块 docstring）。
        """
        os.environ[账本.开关环境变量] = "真"
        os.environ[账本.库环境变量] = str(self.临时根 / "不存在的目录" / "x.db")
        账本.记一笔("自检", "echo 一", 0.1, 0)   # 不得抛异常
        self.assertNotEqual("", 账本.自检()["最近写入错误"],
                            "写失败必须留痕（供自检读），不能连失败都看不出来")


if __name__ == "__main__":
    unittest.main()
