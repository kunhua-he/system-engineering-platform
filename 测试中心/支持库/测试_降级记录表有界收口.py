"""降级记录表有界收口回归：4 处同型表的「有界 + 只读摘要入口」+ 关闭失败两腿同对象。

背景（未完成事项 §8.3 第 56 项 / 第 2 项）：4 处降级记录表原是无界 `list`，且全仓
**0 读取方**（只写不读的死登记）；`_关闭失败记录` 原是无界 list 且跨腿重复实现。
本轮按对照件 `模型连接器.py:64`（`deque(maxlen=1000)`）统一收口，并各接一个只读
摘要入口——**本测试就是这些摘要入口的真实消费方**（口径同
`适配层/pdfplumber提供者` 的 `关闭失败摘要()`：「供诊断/测试」）。

只钉两件事，不含任何桩：
1. 表是 `deque` 且有界；连写 1200 条后长度恒为上限、首元素被挤出（有界语义为真）；
2. 摘要入口可调、返回**快照**（改快照不回写表）、条数与上限如实；
3. 关闭失败两腿是**同一个模块对象、同一张表**（1.3 结果唯一即收口，不留第二份实现）。

不使用 mock：全部走真实模块对象与真实 append，摘要读回即真实副作用证据。
"""

from __future__ import annotations

import importlib
import sys
import unittest
from pathlib import Path

系统根 = Path(__file__).resolve().parents[2]
if str(系统根) not in sys.path:
    sys.path.insert(0, str(系统根))

# (简称, 模块名, 表名, 摘要入口名, 上限名)
四处表 = [
    ("工具执行", "支持库.后端.系统核心支持库.工具执行.实现.工具执行",
     "投递降级记录表", "投递降级记录摘要", "投递降级记录表上限"),
    ("系统信息", "支持库.后端.系统核心支持库.系统信息.实现.系统信息",
     "降级记录表", "降级记录摘要", "降级记录表上限"),
    ("进程管理", "支持库.后端.系统核心支持库.进程管理.实现.进程管理",
     "降级记录表", "降级记录摘要", "降级记录表上限"),
    ("会话存储", "支持库.后端.大语言模型支持库.会话存储.实现.会话存储",
     "降级记录表", "降级记录摘要", "降级记录表上限"),
]

中间量 = 1200


class 测试降级记录表有界(unittest.TestCase):
    """4 处表：有界为真 + 摘要入口是真读取方。"""

    def _模(self, 模块名: str):
        return importlib.import_module(模块名)

    def test_四处表都是有界deque(self) -> None:
        for 简称, 模块名, 表名, _摘要名, 上限名 in 四处表:
            with self.subTest(表=f"{简称}.{表名}"):
                模 = self._模(模块名)
                表 = getattr(模, 表名)
                上限 = getattr(模, 上限名)
                self.assertEqual(type(表).__name__, "deque", "收口后必须是 deque，不是无界 list")
                self.assertEqual(表.maxlen, 上限, "maxlen 必须等于本包声明的上限常量")
                self.assertEqual(上限, 1000, "上限照对照件 模型连接器.py:64")

    def test_写超上限后长度恒为上限且首元素被挤出(self) -> None:
        for 简称, 模块名, 表名, _摘要名, 上限名 in 四处表:
            with self.subTest(表=f"{简称}.{表名}"):
                模 = self._模(模块名)
                表 = getattr(模, 表名)
                上限 = getattr(模, 上限名)
                备份 = list(表)
                try:
                    表.clear()
                    for 序号 in range(中间量):
                        表.append(str(序号))
                    self.assertEqual(len(表), 上限, "有界语义：写超上限后长度恒为上限")
                    self.assertEqual(表[0], str(中间量 - 上限), "最早的超限条数被挤出")
                finally:
                    表.clear()
                    表.extend(备份)

    def test_摘要入口可调且返回快照(self) -> None:
        for 简称, 模块名, 表名, 摘要名, 上限名 in 四处表:
            with self.subTest(摘要=f"{简称}.{摘要名}"):
                模 = self._模(模块名)
                表 = getattr(模, 表名)
                摘要 = getattr(模, 摘要名)
                上限 = getattr(模, 上限名)
                备份 = list(表)
                try:
                    表.clear()
                    表.append("第1条")
                    表.append("第2条")
                    视图 = 摘要()
                    self.assertIsInstance(视图, dict, "摘要入口必须返回字典")
                    self.assertEqual(视图["在册条数"], 2)
                    self.assertEqual(视图["上限"], 上限)
                    self.assertEqual(视图["最近记录"], ["第1条", "第2条"])
                    # 快照语义：改读取方拿到的列表，不得回写表本体
                    视图["最近记录"].append("第3条")
                    self.assertEqual(len(表), 2, "摘要返回的必须是快照，不是表本体的可变视图")
                    self.assertEqual(摘要()["最近记录"], ["第1条", "第2条"])
                finally:
                    表.clear()
                    表.extend(备份)


class 测试关闭失败两腿收口(unittest.TestCase):
    """两腿必须是同一模块对象、同一张表、同一个摘要入口（1.3 结果唯一即收口）。"""

    def test_两腿同对象同表同入口(self) -> None:
        适配腿 = importlib.import_module("支持库.适配层.pdfplumber提供者.实现.PDF文本表格")
        转换腿 = importlib.import_module("支持库.后端.文档转换支持库.PDF文本表格.实现.PDF文本表格")
        self.assertIs(适配腿, 转换腿, "两腿必须是同一模块对象，不留第二份实现")
        self.assertIs(适配腿._关闭失败记录, 转换腿._关闭失败记录, "两腿必须同一张表")
        self.assertIs(适配腿.关闭失败摘要, 转换腿.关闭失败摘要, "两腿必须同一个摘要入口")
        # 真实副作用证据：经适配腿登记，必须能从转换腿的摘要入口读到同一条
        备份 = list(适配腿._关闭失败记录)
        累计备份 = 适配腿._关闭失败总数
        try:
            适配腿._关闭失败记录.clear()
            适配腿._关闭失败总数 = 0
            文本 = 适配腿._记录关闭失败(OSError("跨腿同一性验收"))
            self.assertEqual(文本, "跨腿同一性验收")
            视图 = 转换腿.关闭失败摘要()
            self.assertEqual(视图["在册条数"], 1, "经适配腿登记的失败必须出现在转换腿的视图里")
            self.assertEqual(视图["最近记录"], ["跨腿同一性验收"])
            self.assertEqual(视图["累计条数"], 1)
        finally:
            适配腿._关闭失败记录.clear()
            适配腿._关闭失败记录.extend(备份)
            适配腿._关闭失败总数 = 累计备份

    def test_关闭失败表有界且摘要如实(self) -> None:
        模 = importlib.import_module("支持库.适配层.pdfplumber提供者.实现.PDF文本表格")
        表 = 模._关闭失败记录
        上限 = 模.关闭失败记录上限
        self.assertEqual(type(表).__name__, "deque")
        self.assertEqual(表.maxlen, 上限)
        备份 = list(表)
        累计备份 = 模._关闭失败总数
        try:
            表.clear()
            模._关闭失败总数 = 0
            # 走真实登记路径（不是直接 append）：证明有界登记与累计计数同时为真
            for 序号 in range(上限 * 3):
                模._记录关闭失败(OSError(f"第{序号}次关闭失败"))
            self.assertEqual(len(表), 上限, "关闭失败登记必须有界")
            视图 = 模.关闭失败摘要()
            self.assertEqual(视图["在册条数"], 上限)
            self.assertEqual(视图["上限"], 上限)
            self.assertEqual(视图["累计条数"], 上限 * 3, "累计条数如实计数，不为其保留明细")
        finally:
            表.clear()
            表.extend(备份)
            模._关闭失败总数 = 累计备份


if __name__ == "__main__":
    unittest.main()
