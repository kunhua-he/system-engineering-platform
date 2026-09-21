"""目录树支持库：深度/过滤/条数预算 + 忽略型 glob + 估算token（E1）。

为什么单独建这个文件（2026-09-21 批 4）：`文件系统支持库.文件操作.目录树` 此前
**全仓没有任何测试** —— 它 2026-09-21 才落地，此后一直无人锁住对外形状。
按「每处修复必须配反向验证」的口径，新增的 E1 两件（`忽略模式` / `估算token`）
必须同时锁住「不传新参数时行为逐字不变」，否则新参数会悄悄改掉老调用方的输出。

全部用例在临时目录里造真实目录树，走真实实现（不 mock）。
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

if str(Path(__file__).resolve().parents[2]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from 支持库.后端.文件系统支持库.文件操作 import 目录树  # noqa: E402


def 取值(结果对象: Any) -> dict[str, Any]:
    """取成功结果的值字典（失败时为空字典，让断言先报失败原因）。"""
    值 = 结果对象.值
    return 值 if isinstance(值, dict) else {}


def 值行表(树文本: str) -> list[str]:
    """把树文本拆成行（判据读**结构**而不读渲染文本：树是分层渲染的，
    `保留/` 与 `留.py` 不在同一行，拿 `保留/留.py` 去子串匹配必然假红）。"""
    return [行 for 行 in str(树文本 or "").splitlines() if 行.strip()]


class 目录树基础测试(unittest.TestCase):
    def setUp(self) -> None:
        self._临时 = tempfile.TemporaryDirectory(prefix="测试_目录树_")
        self.根 = Path(self._临时.name)
        (self.根 / "子目录").mkdir()
        (self.根 / "子目录" / "深层").mkdir()
        (self.根 / "子目录" / "深层" / "深文件.py").write_text("x", encoding="utf-8")
        (self.根 / "子目录" / "中文件.md").write_text("y", encoding="utf-8")
        (self.根 / "根文件.py").write_text("z", encoding="utf-8")
        (self.根 / "噪音.log").write_text("n", encoding="utf-8")

    def tearDown(self) -> None:
        self._临时.cleanup()

    def _树(self, **额外):
        return 目录树(目录路径=str(self.根), 最大深度=0, 条数上限=200, **额外)

    def test_一次拿到整棵树(self) -> None:
        结果 = self._树()
        self.assertTrue(结果.成功, 结果.错误说明)
        值 = 取值(结果)
        self.assertGreaterEqual(值["文件数"], 4)
        self.assertIn("根文件.py", 值["树文本"])
        self.assertIn("深文件.py", 值["树文本"], "最大深度=0 表示不限，深层文件必须出现")

    def test_条数上限如实截断不静默(self) -> None:
        结果 = 目录树(目录路径=str(self.根), 最大深度=0, 条数上限=2)
        self.assertTrue(结果.成功, 结果.错误说明)
        值 = 取值(结果)
        self.assertTrue(值["已截断"], "超限必须标 已截断")
        self.assertTrue(值["截断处"], "超限必须给出 截断处")


class 忽略模式测试(unittest.TestCase):
    """E1（2026-09-21 批 4）：`忽略模式` = 忽略型 glob，与 `名称模式`（含型）方向相反。

    两条口径必须同时成立：① 不传时输出**逐字不变**（原调用方零感知）；
    ② 传了才剪枝，且**目录连子树**一起剪（不只是名字对不上）。
    """

    def setUp(self) -> None:
        self._临时 = tempfile.TemporaryDirectory(prefix="测试_忽略模式_")
        self.根 = Path(self._临时.name)
        (self.根 / "保留").mkdir()
        (self.根 / "保留" / "留.py").write_text("a", encoding="utf-8")
        (self.根 / "缓存").mkdir()
        (self.根 / "缓存" / "生成物.py").write_text("b", encoding="utf-8")
        (self.根 / "调试.log").write_text("c", encoding="utf-8")
        (self.根 / "主.py").write_text("d", encoding="utf-8")

    def tearDown(self) -> None:
        self._临时.cleanup()

    def _树(self, **额外):
        return 目录树(目录路径=str(self.根), 最大深度=0, 条数上限=200, **额外)

    def test_不传忽略模式时输出逐字与改前一致(self) -> None:
        # 不传 = 行为不变：这是「只增的可选参数」的判据本体。
        基线 = 取值(self._树())
        self.assertIn("缓存/", 基线["树文本"])
        self.assertIn("生成物.py", 基线["树文本"])
        self.assertIn("调试.log", 基线["树文本"])
        self.assertNotIn("忽略模式", self._树.__doc__ or "")

    def test_忽略目录时连子树一起剪(self) -> None:
        值 = 取值(self._树(忽略模式=["缓存"]))
        self.assertNotIn("缓存/", 值["树文本"], "被忽略的目录本身要剪掉")
        self.assertNotIn("生成物.py", 值["树文本"], "被忽略目录的**子树**也要剪掉")
        self.assertIn("主.py", 值["树文本"], "未命中的文件必须留下")
        self.assertIn("留.py", 值["树文本"])

    def test_忽略文件名通配(self) -> None:
        值 = 取值(self._树(忽略模式=["*.log"]))
        self.assertNotIn("调试.log", 值["树文本"])
        self.assertIn("主.py", 值["树文本"])

    def test_忽略模式可同时按相对路径匹配(self) -> None:
        # 只看「名称」表达不了带目录的模式（`保留/留.py` 与 `缓存/留.py` 分不开），
        # 故实现要求**整段相对路径也参与匹配**。
        # 判据读结构而不读渲染文本：树文本是分层渲染的（`保留/` 与 `留.py` 不在同一行），
        # 拿 `保留/留.py` 去子串匹配必然假红。
        (self.根 / "缓存" / "留.py").write_text("e", encoding="utf-8")
        值 = 取值(self._树(忽略模式=["缓存/*.py"]))
        # `缓存/留.py` 被剪 ⇒ 缓存目录那份不在树里；`保留/留.py` 仍在 ⇒ 保留目录下要有文件行。
        行表 = 值行表(值["树文本"])
        self.assertEqual(sum(1 for 行 in 行表 if "留.py" in 行), 1,
                         "只有 保留/留.py 该留下，缓存/留.py 必须被剪掉")

    def test_忽略模式与名称模式可同时用(self) -> None:
        值 = 取值(self._树(忽略模式=["缓存"], 名称模式="*.py"))
        self.assertNotIn("生成物.py", 值["树文本"])
        self.assertIn("主.py", 值["树文本"])

    def test_忽略模式非列表被拒(self) -> None:
        结果 = self._树(忽略模式="不是列表")
        self.assertFalse(结果.成功)
        self.assertEqual("参数不合法", 结果.错误码)


class 估算token测试(unittest.TestCase):
    """E1：`估算token` 是**只增字段**，口径必须明写（字符数/3，与仓库地图同一把尺子）。

    为什么必须有这条：同仓已有三把 token 尺子（地图 字符/3、上下文压缩 中文×0.8+英文/4、
    薄壳 纯字符上限）。口径不写清、或与地图不一致，调用方把两个数放在一起看就会被误导。
    """

    def setUp(self) -> None:
        self._临时 = tempfile.TemporaryDirectory(prefix="测试_估算token_")
        self.根 = Path(self._临时.name)
        (self.根 / "文件1.py").write_text("a", encoding="utf-8")

    def tearDown(self) -> None:
        self._临时.cleanup()

    def test_估算token存在且口径明写(self) -> None:
        值 = 取值(目录树(目录路径=str(self.根), 最大深度=0))
        self.assertIn("估算token", 值)
        self.assertIsInstance(值["估算token"], int)
        self.assertIn("3", str(值.get("估算口径", "")), "口径必须写明（字符数 / 3）")
        self.assertIn("仓库地图", str(值.get("估算口径", "")), "必须点名同一把尺子是谁")

    def test_估算token与树文本字符数同口径(self) -> None:
        值 = 取值(目录树(目录路径=str(self.根), 最大深度=0))
        self.assertEqual(值["估算token"], len(值["树文本"]) // 3,
                         "估算token 必须等于 字符数 // 3（口径与仓库地图一致）")

    def test_树越大估算token越大(self) -> None:
        小 = 取值(目录树(目录路径=str(self.根), 最大深度=0))["估算token"]
        for 序号 in range(20):
            (self.根 / f"填充{序号}.py").write_text("b", encoding="utf-8")
        大 = 取值(目录树(目录路径=str(self.根), 最大深度=0))["估算token"]
        self.assertGreater(大, 小, "估算token 必须随树增长（否则它没有决策价值）")


_目录树源 = (Path(__file__).resolve().parents[2] / "支持库" / "后端" / "文件系统支持库"
          / "文件操作" / "实现" / "目录树.py")
_剪枝行 = "            if 忽略模式表 and _被忽略(相对候选, 条目[\"名称\"], 忽略模式表):\n                continue\n"


class 忽略模式反向验证(unittest.TestCase):
    """反向验证：拆掉忽略闸门后，「忽略目录时连子树一起剪」必须变红。

    没有这层，那条用例可能在「忽略模式传了但不生效」的实现下照样绿 ——
    等于没证明这道剪枝真的在起作用（实测踩过：参数没进注册侧就被网关过滤掉，
    表现正是「传了没反应」，用例只断言「输出的确有剪」时不一定抓得住）。
    """

    def _缺陷态模块(self):
        源 = _目录树源.read_text(encoding="utf-8")
        坏 = 源.replace(_剪枝行, "")
        if 坏 == 源:
            raise AssertionError("忽略闸门片段未命中，反向样本失效（判据需更新）")
        命名空间: dict = {"__name__": "反向样本_目录树", "__file__": str(_目录树源)}
        exec(compile(坏, str(_目录树源), "exec"), 命名空间)  # noqa: S102
        return 命名空间

    def test_拆掉闸门后忽略模式不起作用(self) -> None:
        模块 = self._缺陷态模块()
        with tempfile.TemporaryDirectory(prefix="测试_反验忽略_") as 临时:
            根 = Path(临时)
            (根 / "缓存").mkdir()
            (根 / "缓存" / "生成物.py").write_text("b", encoding="utf-8")
            缺陷 = 模块["目录树"](目录路径=str(根), 最大深度=0, 忽略模式=["缓存"])
            缺陷文本 = (缺陷.值 or {}).get("树文本", "")
            self.assertIn("生成物.py", 缺陷文本, "缺陷态下必须真的没剪（这正是坏行为）")
        with tempfile.TemporaryDirectory(prefix="测试_现行忽略_") as 临时:
            根 = Path(临时)
            (根 / "缓存").mkdir()
            (根 / "缓存" / "生成物.py").write_text("b", encoding="utf-8")
            现行 = 目录树(目录路径=str(根), 最大深度=0, 忽略模式=["缓存"])
            现行文本 = (现行.值 or {}).get("树文本", "")
            self.assertNotIn("生成物.py", 现行文本, "现行实现必须剪掉")
        self.assertNotEqual("生成物.py" in 缺陷文本, "生成物.py" in 现行文本,
                          "反向样本与现行实现的结论必须不同，否则样本失效")


if __name__ == "__main__":
    unittest.main(verbosity=1)
