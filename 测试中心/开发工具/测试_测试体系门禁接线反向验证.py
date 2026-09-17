"""卡点 B 接线第 4 条 · 「测试体系门禁」接线反向验证（2026-09-18）。

验证的是**接线本身**（判定口径 + 分级 + 「未执行全量」声明 + 是否真在必经路径上），
不是重测 `测试体系门禁` 的四项判据（判据及其夹具自测在
`开发工具/测试体系门禁.py`、实现包 `开发工具/测试体系门禁实现/`）。

断言清单：
1. **真在必经路径**：门禁源码里确实调了 `校验测试体系门禁(...)` 并挂成强制项
   `检查("测试体系门禁", ...)` ——「定义了但没接线」正是本项要防的「半个强制」（13.1）。
   此前该模块在门禁里只出现 2 次且全是帮助文本、零调用，故这里连「导入名」一起锁。
2. **判据属主**：违规集来自 `测试体系门禁.运行检查`，本项不另立第二份实现
   （不自己扫 `测试中心/`、不另写聚合入口）。
3. **分级是真的执行范围切换**：快速级不启动真跑（真跑模块数 0），真跑级才执行
   —— 用夹具根证明，不靠读源码猜。
4. **「未执行全量」必须声明**：快速级下结果里 `未执行声明` 非空、且逐字含
   「本轮未执行全量测试」；真跑级下必须为空（跑了就不能再说没跑）。
5. **反向验证（本任务的硬要求）**：故意让一个测试变红 → 门禁**必须报红**并指出
   那个模块；还原 → 转绿。两相夹逼，证明「跑不过即红」不是空话。
6. **口径不得靠存量豁免放行**：红模块不在 `存量真跑红` 基线内时一律判违规
   （基线是空的；这里用「基线登记该模块」的对照证明基线确实在起作用而非形同虚设）。
7. **四级 fail-closed**：级别名非法 → 判红（不静默降级到默认档）；
   检查根不存在 `测试中心/` → 零测试违规（不是静默通过）。
8. **默认档显式配置**：`发布门禁测试级别` 是模块级显式常量且是合法级别名，
   默认档不是靠函数默认值隐含。
"""

from __future__ import annotations

import ast
import sys
import tempfile
import unittest
from pathlib import Path

系统根 = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(系统根))

from 公共契约.基础类型.逻辑类型 import 真, 假
from 开发工具.发布门禁.运行发布门禁 import (发布门禁测试级别, 校验测试体系门禁,
                                       校验测试体系门禁 as _接线入口)
from 开发工具.测试体系门禁 import (运行检查, 快速级, 真跑级, 测试体系分级,
                              未执行全量测试声明, 未执行全量测试声明 as _声明)

门禁源码路径 = 系统根 / "开发工具" / "发布门禁" / "运行发布门禁.py"
接线项名 = "测试体系门禁"

#: 夹具测试模块：先绿后红，用来做「故意变红 → 门禁必须报红」的反向验证。
夹具测试源码 = '''"""反向验证夹具：一个必然通过的用例。"""
from __future__ import annotations

import unittest


class 反向验证夹具(unittest.TestCase):
    def test_恒真(self) -> None:
        self.assertEqual(1 + 1, 2)
'''

#: 把断言改成必然失败（1+1 == 3）—— 这就是「故意让某个测试变红」。
夹具测试源码_变红 = 夹具测试源码.replace("self.assertEqual(1 + 1, 2)",
                                    "self.assertEqual(1 + 1, 3)")


def 建夹具根(临时根: Path, 测试源码: str) -> Path:
    """建一个最小可跑夹具根：含 测试中心/ 与 开发工具/，测试文件内容由调用方给定。

    `测试体系门禁` 只依赖「`测试中心/` 存在 + 文件名 `测试_*.py`」
    （发现口径 `rglob("测试_*.py")`），故夹具根不需要造真仓库结构。
    """
    (临时根 / "测试中心" / "夹具域").mkdir(parents=True, exist_ok=True)
    (临时根 / "开发工具").mkdir(parents=True, exist_ok=True)
    (临时根 / "测试中心" / "__init__.py").write_text("", encoding="utf-8")
    (临时根 / "测试中心" / "夹具域" / "__init__.py").write_text("", encoding="utf-8")
    (临时根 / "测试中心" / "夹具域" / "测试_夹具模块.py").write_text(
        测试源码, encoding="utf-8")
    return 临时根


class Test测试体系门禁接线反向验证(unittest.TestCase):
    def setUp(self) -> None:
        import shutil
        self.临时根 = Path(tempfile.mkdtemp(prefix="测试体系接线反验_"))
        self.addCleanup(shutil.rmtree, self.临时根, True)

    # ---------- 一、真在必经路径 / 判据属主 ----------

    def test_接在必经路径且挂成强制项(self) -> None:
        """「定义了但没接线」＝半个强制（13.1）。直接对门禁源码断言调用与挂名。"""
        树 = ast.parse(门禁源码路径.read_text(encoding="utf-8"))
        调用处 = [节点 for 节点 in ast.walk(树)
                if isinstance(节点, ast.Call)
                and getattr(节点.func, "id", "") == "校验测试体系门禁"]
        self.assertTrue(调用处, "门禁源码里没有 校验测试体系门禁(...) 的真实调用")
        挂名 = [节点 for 节点 in ast.walk(树)
               if isinstance(节点, ast.Call)
               and getattr(节点.func, "id", "") == "检查"
               and 节点.args and isinstance(节点.args[0], ast.Constant)
               and 节点.args[0].value == 接线项名]
        self.assertTrue(挂名, f"门禁源码里没有把本项挂成「{接线项名}」检查项")
        # 强制项：`检查` 调用的 强制 关键字不得为常量 假（不得降级成只报项）
        for 节点 in 挂名:
            for 关键字 in 节点.keywords:
                if 关键字.arg == "强制" and isinstance(关键字.value, ast.Constant):
                    self.assertIsNot(关键字.value.value, False,
                                     "本项被降级成只报项（强制=假）")

    def test_判据只调运行检查不另立第二份(self) -> None:
        函数 = next(节点 for 节点 in ast.walk(
            ast.parse(门禁源码路径.read_text(encoding="utf-8")))
            if isinstance(节点, ast.FunctionDef) and 节点.name == "校验测试体系门禁")
        导入名 = {别名.asname or 别名.name
                for 节点 in ast.walk(函数) if isinstance(节点, ast.ImportFrom)
                for 别名 in 节点.names}
        self.assertIn("运行检查", 导入名, "本项必须复用 测试体系门禁 的既有主判定函数")
        self.assertIn("测试体系分级", 导入名,
                      "级别名必须从唯一真源取，不得在本文件另写级别表")
        本函数导入的模块 = {节点.module for 节点 in ast.walk(函数)
                       if isinstance(节点, ast.ImportFrom)}
        self.assertEqual(本函数导入的模块, {"开发工具.测试体系门禁"},
                         f"本项只应依赖测试体系门禁，实际导入：{本函数导入的模块}")

    # ---------- 二、分级是真的执行范围切换 ----------

    def test_快速级不启动真跑_真跑级才执行(self) -> None:
        """夹具根上跑两级：快速级真跑模块数必须是 0（没跑），真跑级必须 >0（真跑）。"""
        建夹具根(self.临时根, 夹具测试源码)
        快速 = 运行检查(self.临时根, 级别=快速级)
        self.assertEqual(快速["真跑模块数"], 0, "快速级不得启动真跑")
        self.assertEqual(快速["真跑通过数"], 0)
        self.assertEqual(快速["执行级别"], 快速级)
        self.assertEqual(快速["违规"], [], f"夹具应无违规，实际：{快速['违规']}")
        真跑 = 运行检查(self.临时根, 级别=真跑级)
        self.assertEqual(真跑["真跑模块数"], 1, "真跑级必须真执行夹具模块")
        self.assertEqual(真跑["真跑通过数"], 1)
        self.assertEqual(真跑["违规"], [], f"夹具应无违规，实际：{真跑['违规']}")

    # ---------- 三、「未执行全量」必须声明（不得静默） ----------

    def test_快速级必须声明未执行全量(self) -> None:
        建夹具根(self.临时根, 夹具测试源码)
        快速 = 运行检查(self.临时根, 级别=快速级)
        self.assertTrue(快速["未执行声明"], "快速级下「未执行全量」必须声明，不得静默")
        self.assertIn("本轮未执行全量测试", 快速["未执行声明"])
        self.assertEqual(快速["未执行级"], [真跑级])
        # 门禁项详情里也必须带上这句（不是只写在函数返回值里没人看）
        通过, 详情 = 校验测试体系门禁(级别=快速级, 根=self.临时根)
        self.assertIs(通过, 真)
        self.assertIn("本轮未执行全量测试", 详情)
        self.assertIn(f"执行级别={快速级}", 详情)

    def test_真跑级不得再声明未执行(self) -> None:
        """跑了就不能再说「没跑」——反向声明同样是假证据。"""
        建夹具根(self.临时根, 夹具测试源码)
        真跑 = 运行检查(self.临时根, 级别=真跑级)
        self.assertEqual(真跑["未执行声明"], "", "真跑级下不得再声明未执行全量")
        self.assertEqual(真跑["未执行级"], [])
        通过, 详情 = 校验测试体系门禁(级别=真跑级, 根=self.临时根)
        self.assertIs(通过, 真)
        self.assertNotIn("本轮未执行全量测试", 详情)
        self.assertIn("本轮已执行真跑级", 详情)

    def test_声明是同一份文本不另写(self) -> None:
        """发布门禁引用的声明必须与 测试体系门禁 定义的是同一份（两处措辞必然漂移）。"""
        self.assertEqual(未执行全量测试声明, _声明)
        self.assertIn("本轮未执行全量测试", 未执行全量测试声明)

    # ---------- 四、反向验证：故意变红 → 必须报红；还原 → 转绿 ----------

    def test_故意变红门禁必须报红且指出模块(self) -> None:
        """**本任务硬要求的反向验证**：改一个断言 → 真跑红 → 门禁项判红并点名模块。"""
        建夹具根(self.临时根, 夹具测试源码_变红)
        通过, 详情 = 校验测试体系门禁(级别=真跑级, 根=self.临时根)
        self.assertIs(通过, 假, f"故意变红必须判红，实际详情：{详情}")
        self.assertIn("违规", 详情)
        self.assertIn("测试中心.夹具域.测试_夹具模块", 详情)
        self.assertIn("真跑新增红", 详情)

    def test_变红还原后转绿(self) -> None:
        """红/绿互为逆命题：不许「红了就红着」。"""
        建夹具根(self.临时根, 夹具测试源码_变红)
        红前, _ = 校验测试体系门禁(级别=真跑级, 根=self.临时根)
        self.assertIs(红前, 假)
        (self.临时根 / "测试中心" / "夹具域" / "测试_夹具模块.py").write_text(
            夹具测试源码, encoding="utf-8")
        通过, 详情 = 校验测试体系门禁(级别=真跑级, 根=self.临时根)
        self.assertIs(通过, 真, f"还原后应转绿，实际详情：{详情}")

    def test_快速级不接住断言级红但接住导入级红(self) -> None:
        """分级不是「放宽判据」：快速级同样 fail-closed，只是范围小（不执行用例）。

        夹具文件**语法/导入**坏掉时，快速级的可导入性检查必须报红；
        而「断言写错」（能导入、用例红）是 ④ 真跑级的职责，快速级接不住 ——
        这正是「未执行全量」必须声明的原因：不声明就会把这种红当绿。
        """
        建夹具根(self.临时根, "import 不存在的模块_故意坏掉\n")
        通过, 详情 = 校验测试体系门禁(级别=快速级, 根=self.临时根)
        self.assertIs(通过, 假, f"导入坏掉必须判红，实际详情：{详情}")
        self.assertIn("导入失败", 详情)
        # 断言写错：快速级判绿（接不住），但必须带声明；真跑级判红。
        建夹具根(self.临时根, 夹具测试源码_变红)
        快速通过, 快速详情 = 校验测试体系门禁(级别=快速级, 根=self.临时根)
        self.assertIs(快速通过, 真)
        self.assertIn("本轮未执行全量测试", 快速详情,
                      "快速级接不住断言红，就必须声明「没跑全量」，否则是真假绿")
        真跑通过, _ = 校验测试体系门禁(级别=真跑级, 根=self.临时根)
        self.assertIs(真跑通过, 假)

    # ---------- 五、存量基线不豁免新增红 ----------

    def test_存量基线外的红一律判违规(self) -> None:
        """口径：跑不过即红，**不得靠存量豁免把测试红放行**。

        生产 `存量真跑红` 现为空元组（2026-09-17 清空的终态），夹具模块必然不在
        基线内 → 必须判违规。再显式传入「含夹具模块」的基线做对照，证明基线确实
        在起作用（不是「反正都判违规」的空判据）。
        """
        self.assertEqual(
            list(运行检查(系统根)["存量真跑红基线"]), [],
            "生产 存量真跑红 基线当前应为空（清空终态）；若新增存量必须同步本用例口径")
        建夹具根(self.临时根, 夹具测试源码_变红)
        默认红数 = 运行检查(self.临时根, 级别=真跑级)["新增真跑红数"]
        self.assertEqual(默认红数, 1, "基线为空时，夹具红必须计入「新增真跑红」")
        豁免 = 运行检查(self.临时根, 级别=真跑级,
                    存量=("测试中心.夹具域.测试_夹具模块",))
        self.assertEqual(豁免["新增真跑红数"], 0, "登记进基线后应转为存量红（只报告）")
        self.assertEqual(豁免["存量真跑红命中数"], 1)
        self.assertEqual(豁免["违规"], [], "存量基线内的红不判违规（只报告）")

    def test_违规红清单直接来自判据不二次加工(self) -> None:
        """接线入口返回的红必须与 `运行检查` 的违规集同源（同一份，不重算）。"""
        建夹具根(self.临时根, 夹具测试源码_变红)
        原生 = 运行检查(self.临时根, 级别=真跑级)["违规"]
        self.assertTrue(原生)
        通过, 详情 = _接线入口(级别=真跑级, 根=self.临时根)
        self.assertIs(通过, 假)
        for 条 in 原生[:3]:
            self.assertIn(条["文件"], 详情)
        self.assertIn(f"违规 {len(原生)} 项", 详情)

    # ---------- 六、fail-closed ----------

    def test_级别名非法即判红不静默降级(self) -> None:
        """级别名写错不得悄悄回落到默认档 —— 那是「配置错了却照跑」。"""
        建夹具根(self.临时根, 夹具测试源码)
        通过, 详情 = 校验测试体系门禁(级别="不存在的级别", 根=self.临时根)
        self.assertIs(通过, 假, f"非法级别名必须判红，实际详情：{详情}")
        self.assertIn("级别名非法", 详情)
        self.assertIn("fail-closed", 详情)

    def test_根下无测试中心即违规不静默通过(self) -> None:
        """「范围塌成 0 也判绿」是真假绿：根下没有 `测试中心/` 必须判红。"""
        空根 = self.临时根 / "没有测试中心"
        (空根 / "开发工具").mkdir(parents=True)
        通过, 详情 = 校验测试体系门禁(级别=快速级, 根=空根)
        self.assertIs(通过, 假, f"零测试文件必须判红，实际详情：{详情}")
        self.assertIn("零测试文件", 详情)

    def test_运行检查拒绝未知级别(self) -> None:
        夹具 = 建夹具根(self.临时根, 夹具测试源码)
        with self.assertRaises(ValueError):
            运行检查(夹具, 级别="不存在的级别")

    # ---------- 七、默认档显式配置 + 分级表只此一份 ----------

    def test_默认档显式配置且是合法级别名(self) -> None:
        self.assertIn(发布门禁测试级别, 测试体系分级,
                      f"默认档 {发布门禁测试级别!r} 必须是 测试体系分级 的键")
        self.assertEqual(发布门禁测试级别, 快速级,
                         "发布门禁默认档应为快速级（实测依据见 发布门禁测试级别 注释）")

    def test_分级表两份内容不重复定义(self) -> None:
        """级别名只在 测试体系门禁 定义一次；门禁源码不得再出现级别名字面量。"""
        门禁源码 = 门禁源码路径.read_text(encoding="utf-8")
        自源 = Path(系统根, "开发工具", "测试体系门禁.py").read_text(encoding="utf-8")
        self.assertIn("测试体系分级", 自源)
        # 门禁只允许在注释/docstring 里提级别名，不得出现级别表赋值
        self.assertNotIn("测试体系分级: dict", 门禁源码)
        self.assertNotIn("测试体系分级 = {", 门禁源码)

    def test_真跑级与快速级是分级表的两个键(self) -> None:
        self.assertEqual(set(测试体系分级), {快速级, 真跑级})
        self.assertEqual(测试体系分级[快速级], (真, 假))
        self.assertEqual(测试体系分级[真跑级], (真, 真))


if __name__ == "__main__":
    unittest.main(verbosity=2)
