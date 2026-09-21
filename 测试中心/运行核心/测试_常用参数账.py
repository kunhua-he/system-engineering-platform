"""调用参数账定向测试：形状口径 + SQLite 计数 + 按次数倒序取前 N（含反向验证）。

口径来源：华哥 2026-09-21「参数组合是唯一值，每一次访问同一个参数自 +1，
然后返回的时候直接排序返回」。本测试钉住四件事：
① 形状键的算法（键序、类型名、`真` 不得被记成 `整数型`）；
② 同形状不同取值**只算一行**、次数自增；
③ 读时按调用次数倒序、`上限` 生效；
④ fail-soft：账不可读时回空组合并带 `问题`，**不抛异常**（统计是旁路，不许反噬主调用）。
"""

from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

if str(Path(__file__).resolve().parents[2]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from 公共契约.诊断.调用账本 import (
    调用参数账, 入参形状, 入参样例, 类型名,
    样例文本上限, 样例整串上限,
)

_源路径 = (Path(__file__).resolve().parents[2]
         / "公共契约" / "诊断" / "调用账本.py")


class 形状与样例口径(unittest.TestCase):
    """形状是计数账的分组键，键序/类型名错一处就会把同一格式拆成两行。"""

    def test_键序与类型名(self):
        # 键序按 `str(键)` 的码点序（中文即码点序：分 < 超 < 远），**只求确定、稳定**，
        # 不追求「看起来像拼音序」——形状串是分组键，稳定性才是判据。
        self.assertEqual(
            入参形状({"超时秒": 120, "远端": "origin", "分支": "主干"}),
            "分支:文本型|超时秒:整数型|远端:文本型")

    def test_同形状不同取值形状串相同(self):
        """形状只看键与类型，不看取值 —— 否则同一格式会拆成无数行，统计失去意义。"""
        self.assertEqual(
            入参形状({"远端": "origin", "超时秒": 120}),
            入参形状({"远端": "upstream", "超时秒": 1}))

    def test_逻辑型必须先于整数型判(self):
        """Python 里 bool 是 int 子类：先判 int 会把 `真` 记成 `整数型`，与契约声明不符。"""
        self.assertEqual(类型名(True), "逻辑型")
        self.assertEqual(类型名(1), "整数型")
        self.assertEqual(入参形状({"含常用参数": True}), "含常用参数:逻辑型")

    def test_空入参与非字典入参不入账(self):
        for 值 in [None, {}, [], "文本"]:
            self.assertEqual(入参形状(值), "", repr(值))
            self.assertEqual(入参样例(值), "", repr(值))

    def test_长文本折叠且整串有界(self):
        样例 = 入参样例({"旧文本": "字" * (样例文本上限 + 50), "新文本": "短"})
        self.assertIn(f"<文本 {样例文本上限 + 50} 字>", 样例)
        self.assertIn("短", 样例)
        self.assertLessEqual(len(样例), 样例整串上限 + len("…（已截断）"))

    def test_容器只留规模(self):
        样例 = 入参样例({"编辑列表": [{"文件路径": "a"}, {"文件路径": "b"}],
                       "开关": {"参数B": 1}})
        self.assertIn("<列表 2 项>", 样例)
        self.assertIn("<字典 1 键>", 样例)

    def test_样例是真JSON可解析(self):
        import json
        样例 = 入参样例({"远端": "origin", "超时秒": 120, "强制": False})
        还原 = json.loads(样例)
        self.assertEqual(还原["远端"], "origin")
        self.assertEqual(还原["超时秒"], 120)
        self.assertIs(还原["强制"], False)


class 计数与排序(unittest.TestCase):
    """SQLite 计数账：自增、同形状合并、按次数倒序、上限生效。"""

    def setUp(self):
        self.临时根 = Path(tempfile.mkdtemp(prefix="测试_调用参数账_"))
        self.库路径 = self.临时根 / "调用参数账.sqlite3"
        self.账 = 调用参数账(self.库路径)

    def tearDown(self):
        shutil.rmtree(self.临时根, ignore_errors=True)
        self.assertFalse(self.临时根.exists())

    def test_记一次调用建库并自增(self):
        self.assertFalse(self.库路径.exists(), "构造实例不该建库（只在真记时才建）")
        self.assertTrue(self.账.记一次调用("示例.能力", {"远端": "origin"}))
        self.assertTrue(self.库路径.is_file())
        self.assertTrue(self.账.记一次调用("示例.能力", {"远端": "upstream"}))
        查 = self.账.查常用参数("示例.能力")
        self.assertEqual(查["组合数"], 1, "同形状不同取值必须合并成一行")
        self.assertEqual(查["常用参数组合"][0]["调用次数"], 2)
        self.assertEqual(查["问题"], "")

    def test_按次数倒序且上限生效(self):
        for _ in range(3):
            self.账.记一次调用("示例.能力", {"参数B": "x"})
        for _ in range(7):
            self.账.记一次调用("示例.能力", {"参数A": "y"})
        self.账.记一次调用("示例.能力", {"参数C": "z", "参数D": 1})
        查 = self.账.查常用参数("示例.能力", 2)
        self.assertEqual([条["入参形状"] for 条 in 查["常用参数组合"]],
                         ["参数A:文本型", "参数B:文本型"])
        self.assertEqual(查["组合数"], 3, "组合数是全量，不受 上限 截断")
        self.assertEqual(查["常用参数组合"][0]["调用次数"], 7)

    def test_样例取最近一次(self):
        self.账.记一次调用("示例.能力", {"远端": "旧值"})
        self.账.记一次调用("示例.能力", {"远端": "新值"})
        条 = self.账.查常用参数("示例.能力")["常用参数组合"][0]
        self.assertIn("新值", 条["样例"], "样例必须是最近一次，不能停在首次")

    def test_能力id隔离(self):
        self.账.记一次调用("参数B.能力", {"参数B": 1})
        self.账.记一次调用("参数A.能力", {"参数A": 2})
        self.assertEqual(self.账.查常用参数("参数B.能力")["组合数"], 1)
        self.assertEqual(self.账.查常用参数("参数B.能力")["常用参数组合"][0]["能力id"], "参数B.能力")

    def test_跨能力汇总每段各取前N(self):
        for _ in range(3):
            self.账.记一次调用("参数B.能力", {"参数B": 1})
        self.账.记一次调用("参数B.能力", {"参数B": 2})
        for _ in range(5):
            self.账.记一次调用("参数A.能力", {"参数A": 1})
        查 = self.账.查常用参数("", 1)
        self.assertEqual(查["命中能力数"], 2)
        self.assertEqual(len(查["常用参数组合"]), 2, "每个能力各取前 1 组")

    def test_空入参不入账(self):
        self.assertFalse(self.账.记一次调用("示例.能力", {}))
        self.assertFalse(self.账.记一次调用("示例.能力", None))
        self.assertFalse(self.账.记一次调用("", {"参数B": 1}))
        self.assertEqual(self.账.查常用参数("示例.能力")["组合数"], 0)

    def test_没有库文件时是空组合而不是错误(self):
        """「从没调用过」与「账读不出来」必须可区分：前者 问题 为空。"""
        查 = 调用参数账(self.临时根 / "不存在.sqlite3").查常用参数("示例.能力")
        self.assertEqual(查["常用参数组合"], [])
        self.assertEqual(查["问题"], "")

    def test_账不可读时fail_soft且带问题(self):
        """库文件位置被占成目录 → sqlite 打不开：回空组合 + 问题，**不抛**。"""
        坏路径 = self.临时根 / "占用"
        坏路径.mkdir()
        查 = 调用参数账(坏路径).查常用参数("示例.能力")
        self.assertEqual(查["常用参数组合"], [])
        self.assertTrue(查["问题"], "读不出来必须如实报问题，不许冒充「没有记录」")


class 反向验证(unittest.TestCase):
    """判据必须钉在真实生效点上：把源码改成缺陷态，对应断言必须变红。"""

    def _缺陷态(self, 替换对: tuple[str, str]) -> dict:
        源 = _源路径.read_text(encoding="utf-8")
        旧, 新 = 替换对
        self.assertIn(旧, 源, f"反向样本未命中源码片段，判据需更新: {旧!r}")
        坏 = 源.replace(旧, 新)
        命名空间: dict = {"__name__": "反向样本", "__file__": str(_源路径)}
        exec(compile(坏, str(_源路径), "exec"), 命名空间)  # noqa: S102
        return 命名空间

    def test_退回bool后判缺陷态_真被记成整数型(self):
        """撤掉 `bool` 先判 ⇒ `真` 落到 `整数型`（与契约声明的 逻辑型 对不上）。"""
        命名空间 = self._缺陷态((
            '    if isinstance(值, bool):\n        return "逻辑型"\n', ""))
        self.assertEqual(命名空间["类型名"](True), "整数型",
                         "退回缺陷态后竟然还是 逻辑型 ⇒ 新判据测的不是真实生效点")

    def test_退回升序缺陷态_次数倒序失效(self):
        """把 ORDER BY 由倒序改成升序 ⇒ 最常用的必须不再排第一。

        夹具要选得让**主键序与次数序相反**（`参数B` 码点大于 `参数A`），否则撤掉排序后顺序
        碰巧不变，样本就测不到生效点（实测踩过：第一版夹具 `参数A` 既是次数冠军又主键靠前，
        撤掉 ORDER BY 首位仍是 `参数A`，样本假绿）。

        **为什么改方向而不是删 ORDER BY**（实测踩过第二次）：本表在 `(能力id, 调用次数 DESC)`
        上有索引，`WHERE 能力id=? LIMIT n` 正好走它 ⇒ **索引本身就给出了次数倒序**，
        把 ORDER BY 整句删掉顺序照样对，样本恒绿。故反向样本必须改**方向**，
        这样无论走索引还是走显式排序，结果都被真正翻过来。
        """
        命名空间 = self._缺陷态((
            "ORDER BY 调用次数 DESC, 入参形状 ASC LIMIT ?",
            "ORDER BY 调用次数 ASC, 入参形状 ASC LIMIT ?"))
        临时根 = Path(tempfile.mkdtemp(prefix="测试_调用参数账_反向_"))
        try:
            账 = 命名空间["调用参数账"](临时根 / "账.sqlite3")
            for _ in range(3):
                账.记一次调用("示例.能力", {"参数A": "y"})
            for _ in range(7):
                账.记一次调用("示例.能力", {"参数B": "x"})
            # 先确认正常口径下冠军确实是「参数B」（否则样本本身不成立）
            self.assertEqual(
                调用参数账(临时根 / "账.sqlite3").查常用参数("示例.能力", 2)
                ["常用参数组合"][0]["入参形状"], "参数B:文本型")
            查 = 账.查常用参数("示例.能力", 2)
            首位 = 查["常用参数组合"][0]["入参形状"]
            self.assertNotEqual(首位, "参数B:文本型",
                                "改成升序后最常用的仍排第一 ⇒ 排序断言不在生效点上")
        finally:
            shutil.rmtree(临时根, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
