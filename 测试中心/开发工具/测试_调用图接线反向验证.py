"""卡点 B 接线第 1 条 · 「防回潮·能力调用图」接线反向验证（2026-09-18）。

验证的是**接线本身**（判定口径 + fail-closed + 是否真在必经路径上），不是重测
`能力调用图审计` 的判据（判据已有 17 例，见 `测试中心/开发工具/测试_调用图审计.py`）。

断言清单：
1. 真仓库当前存量判**绿**，且详情报出「审计面 61 份 / 计数 0 条」（存量实测可复核）。
2. 造一处真违规（直连第三方 `openpyxl`）→ 判**红**，且**指出那个文件**。
3. 违规还原 → 转**绿**（基线外新增与还原互为逆命题，不许「红了就红着」）。
4. 存量走基线：同一处违规，基线登记该文件上限 1 → 判绿（**不是零容忍硬判**）；
   上限 0（空表）→ 判红。两相夹逼证明「只减不增」口径真的生效。
5. fail-closed 三条：基线文件**缺失** / **内容不可解析** / **形状非法** → 一律判红，
   且详情写明「fail-closed」；不得静默放行（与「读不成回退总数模式」的降级不同）。
6. 判据属主：违规集来自 `能力调用图审计.审计模块库`，本项不另立第二份实现。
7. 审计面为 0（临时根下没有 `模块库`）→ **未核验**（None），不占通过位也不冒充失败。
8. 必经路径：门禁源码里那一处 for 循环的元组确实含 `("能力调用图", 校验能力调用图防回潮)`
   ——「定义了但没接线」正是本项要防的「半个强制」（13.1）。
"""

from __future__ import annotations

import ast
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

系统根 = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(系统根))

from 公共契约.基础类型.逻辑类型 import 真, 假
from 开发工具.发布门禁.运行发布门禁 import (防回潮存量基线路径, 防回潮阻断配置,
                                       校验能力调用图防回潮)

门禁源码路径 = 系统根 / "开发工具" / "发布门禁" / "运行发布门禁.py"
#: 真违规样本：直连第三方发行包（`运行核心/依赖防火墙.py::第三方前缀表` 内的成员）。
第三方直连源码 = "import openpyxl\n\n\ndef 注入能力(文本: str) -> str:\n    return openpyxl.__name__ + 文本\n"
干净源码 = "def 注入能力(文本: str) -> str:\n    return 文本\n"


def 构造模块包(根: Path, 包名: str, 实现文本: str) -> Path:
    """在临时根构造一个形态齐全的模块包（包声明 / 能力契约 / __init__ / 实现）。"""
    包目录 = 根 / "模块库" / 包名
    (包目录 / "实现").mkdir(parents=True)
    (包目录 / "能力契约").mkdir()
    (包目录 / "实现" / f"{包名}.py").write_text(实现文本, encoding="utf-8")
    能力id = f"{包名}.注入能力"
    (包目录 / "包声明.json").write_text(json.dumps({
        "包id": f"模块库.{包名}", "名称": 包名, "类型": "基础模块", "版本": "1.0.0",
        "入口": "__init__.py", "依赖": [],
        "能力": [{"能力id": 能力id, "名称": "注入能力", "参数": [], "返回": "结果"}],
    }, ensure_ascii=False), encoding="utf-8")
    (包目录 / "能力契约" / "参数契约.json").write_text(json.dumps({
        "能力契约": [{"能力id": 能力id, "参数": [], "返回": "结果"}],
    }, ensure_ascii=False), encoding="utf-8")
    (包目录 / "__init__.py").write_text(
        '"""入口。"""\n\nfrom __future__ import annotations\n\n'
        f"from 模块库.{包名}.实现.{包名} import 注入能力\n\n"
        '__all__ = ["注入能力"]\n\n\n'
        "def 注册能力(注册表) -> None:\n"
        "    from 公共契约.能力契约.契约 import 能力实现\n\n"
        f'    注册表.注册(能力实现(能力id="{能力id}", 包id="模块库.{包名}",'
        ' 实现函数="注入能力", 参数=[], 返回="结果", 说明=""))\n',
        encoding="utf-8")
    return 包目录


def 写基线(路径: Path, 分桶: dict[str, int] | None) -> None:
    """写一份只含「能力调用图」一项的临时分桶基线；`分桶=None` 写成形状非法件。"""
    路径.write_text(json.dumps({
        "说明": "反向验证用临时基线",
        "项": {"能力调用图": {"条目数": len(分桶) if 分桶 else 0, "条目": 分桶}},
    }, ensure_ascii=False), encoding="utf-8")


class Test能力调用图接线反向验证(unittest.TestCase):
    def setUp(self) -> None:
        self.临时根 = Path(tempfile.mkdtemp(prefix="调用图接线反验_"))
        self.临时基线 = self.临时根 / "临时基线.json"

    def tearDown(self) -> None:
        shutil.rmtree(self.临时根, ignore_errors=True)

    def _判定(self, 根: Path, 基线: Path | None = None) -> tuple[bool | None, str]:
        通过, 详情 = 校验能力调用图防回潮(根, **({"基线路径": 基线} if 基线 else {}))
        return 通过, 详情

    # ---------- 一、真仓库存量 ----------

    def test_真仓库存量判绿且报出审计面(self) -> None:
        通过, 详情 = self._判定(系统根)
        self.assertIs(通过, 真, f"真仓库当前存量应为 0（判绿），实际详情：{详情}")
        # 不写死份数：分包会让模块库包内源码自然增多，写死即「假红」。
        份数 = int(详情.split("审计面=模块库 包内全量源码 ")[1].split(" 份")[0])
        self.assertGreater(份数, 30, f"审计面异常过小，判据可能塌缩：{详情}")
        self.assertIn("本次计数 0 条", 详情)
        self.assertIn("按文件分桶判定", 详情)

    def test_存量基线条目为空表即零容忍(self) -> None:
        """生产基线里本项条目必须是**空表**：任何一处新违规都无处容身。"""
        数据 = json.loads(防回潮存量基线路径.read_text(encoding="utf-8"))
        条目 = 数据["项"]["能力调用图"]["条目"]
        self.assertEqual(条目, {}, f"本项基线应为空表（存量 0），实际：{条目}")

    # ---------- 二、真违规注入 → 红且指出文件 ----------

    def test_真违规注入判红并指出文件(self) -> None:
        构造模块包(self.临时根, "注入包", 第三方直连源码)
        写基线(self.临时基线, {})
        通过, 详情 = self._判定(self.临时根, self.临时基线)
        self.assertIs(通过, 假, f"直连第三方必须判红，实际详情：{详情}")
        self.assertIn("基线外新增", 详情)
        self.assertIn("模块库/注入包/实现/注入包.py", 详情)
        self.assertIn("第三方直连", 详情)

    def test_违规还原后转绿(self) -> None:
        包目录 = 构造模块包(self.临时根, "注入包", 第三方直连源码)
        写基线(self.临时基线, {})
        红前, _ = self._判定(self.临时根, self.临时基线)
        self.assertIs(红前, 假)
        (包目录 / "实现" / "注入包.py").write_text(干净源码, encoding="utf-8")
        通过, 详情 = self._判定(self.临时根, self.临时基线)
        self.assertIs(通过, 真, f"违规还原后应转绿，实际详情：{详情}")
        self.assertIn("本次计数 0 条", 详情)

    # ---------- 三、口径就是「存量走基线」 ----------

    def test_存量走基线内不判红_基线外才判红(self) -> None:
        """两相夹逼：上限 1 → 绿（存量走基线）；上限 0（空表）→ 红（基线外新增即红）。"""
        构造模块包(self.临时根, "注入包", 第三方直连源码)
        命中文件 = "模块库/注入包/实现/注入包.py"
        写基线(self.临时基线, {命中文件: 1})
        通过, 详情 = self._判定(self.临时根, self.临时基线)
        self.assertIs(通过, 真, f"基线内存量不得判红，实际详情：{详情}")
        self.assertIn("收敛", 详情)
        写基线(self.临时基线, {})
        通过, 详情 = self._判定(self.临时根, self.临时基线)
        self.assertIs(通过, 假, f"基线外新增必须判红，实际详情：{详情}")

    # ---------- 四、fail-closed ----------

    def test_基线缺失即判红(self) -> None:
        """缺基线＝无参照，不是「没有要检查的」——必须红，不得静默放行。"""
        构造模块包(self.临时根, "注入包", 干净源码)
        通过, 详情 = self._判定(self.临时根, self.临时根 / "不存在的基线.json")
        self.assertIs(通过, 假, f"基线缺失必须判红，实际详情：{详情}")
        self.assertIn("fail-closed", 详情)
        self.assertIn("基线缺失或不可读", 详情)

    def test_基线不可解析即判红(self) -> None:
        构造模块包(self.临时根, "注入包", 干净源码)
        self.临时基线.write_text("{\"项\": {\"能力调用图\": ", encoding="utf-8")
        通过, 详情 = self._判定(self.临时根, self.临时基线)
        self.assertIs(通过, 假, f"基线损坏必须判红，实际详情：{详情}")
        self.assertIn("fail-closed", 详情)

    def test_基线形状非法即判红(self) -> None:
        构造模块包(self.临时根, "注入包", 干净源码)
        self.临时基线.write_text(json.dumps({
            "项": {"能力调用图": {"条目数": 1, "条目": "不是字典"}},
        }, ensure_ascii=False), encoding="utf-8")
        通过, 详情 = self._判定(self.临时根, self.临时基线)
        self.assertIs(通过, 假, f"基线形状非法必须判红，实际详情：{详情}")
        self.assertIn("fail-closed", 详情)

    def test_审计面为0判未核验(self) -> None:
        """临时根下没有 `模块库`：判据什么都没看 → 未核验，不占通过位也不冒充失败。"""
        写基线(self.临时基线, {})
        通过, 详情 = self._判定(self.临时根, self.临时基线)
        self.assertIsNone(通过, f"审计面为 0 应为未核验，实际：{通过} / {详情}")
        self.assertIn("审计面为 0", 详情)

    # ---------- 五、不另立第二份实现 / 真在必经路径 ----------

    def test_判据只调审计模块库不另立第二份(self) -> None:
        源码 = 门禁源码路径.read_text(encoding="utf-8")
        树 = ast.parse(源码)
        函数 = next(节点 for 节点 in ast.walk(树)
                  if isinstance(节点, ast.FunctionDef) and 节点.name == "校验能力调用图防回潮")
        导入名 = {别名.asname or 别名.name
                for 节点 in ast.walk(函数) if isinstance(节点, ast.ImportFrom)
                for 别名 in 节点.names}
        self.assertIn("审计模块库", 导入名, "本项必须复用审计器既有主判定函数")
        # 本项不得自带 AST 扫描实现（判据第二份实现是 E-f 类根因：同一行两个结论）。
        本函数导入的模块 = {节点.module for 节点 in ast.walk(函数)
                       if isinstance(节点, ast.ImportFrom)}
        self.assertEqual(本函数导入的模块, {"开发工具.复用审计.能力调用图审计"},
                         f"本项只应依赖审计器，实际导入：{本函数导入的模块}")

    def test_接在必经路径的for元组里(self) -> None:
        """「定义了但没接线」＝半个强制（13.1）。这里直接对门禁源码断言接线元组。"""
        树 = ast.parse(门禁源码路径.read_text(encoding="utf-8"))
        接线对: list[tuple[str, str]] = []
        for 节点 in ast.walk(树):
            if not isinstance(节点, ast.For) or not isinstance(节点.iter, ast.Tuple):
                continue
            for 元素 in 节点.iter.elts:
                if (isinstance(元素, ast.Tuple) and len(元素.elts) == 2
                        and isinstance(元素.elts[0], ast.Constant)
                        and isinstance(元素.elts[1], ast.Name)):
                    接线对.append((str(元素.elts[0].value), 元素.elts[1].id))
        self.assertIn(("能力调用图", "校验能力调用图防回潮"), 接线对,
                      f"接线元组缺失，实际：{接线对}")
        self.assertIn("能力调用图", 防回潮阻断配置,
                      "阻断口径必须显式配置（13.2：不靠『未新增即放行』隐含）")


if __name__ == "__main__":
    unittest.main(verbosity=2)
