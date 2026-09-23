"""制品新鲜度门禁判据件（批J，2026-09-24）：正反向样本 + 三处接线不许断。

被测对象是 `开发工具/制品新鲜度门禁.py::判定`，它自己**不含任何比对逻辑**
（判据唯一腿在发布门禁 `运行发布门禁_制品验证`），故本件同时钉两件事：

① **判据真的会红**：合成制品（来源提交 = 一个真实的历史提交 / 缺提交字段 /
   落后 0 但来源字节指纹不符）三种形态都必须判红，且说明里带上落后提交数或
   来源绑定原因 —— 防「判据恒绿」。
② **判据只有一处实现、且真的接在必经路径上**：`开发编译口` 的门禁清单里必须有
   本项（角色=只报告）；`开发工具/制品新鲜度门禁.py` 里**不许**出现 `git rev-list`
   或阈值数字（那是 `校验制品落后提交数` / `制品落后提交阈值` 的事）。

反向样本的现实依据（2026-09-24 实测，非推演）：本仓激活制品停在 `7dd1f57b`，
落后 HEAD **10 个提交**，而「健康 200／能力数对／装配告警空／编译口全绿」——
批F 的 fd 修复因此没上线，表现为同一个 bug 被修了两次。
"""

from __future__ import annotations

import ast
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path

系统根 = Path(__file__).resolve().parents[2]
if str(系统根) not in sys.path:
    sys.path.insert(0, str(系统根))

from 开发工具.制品新鲜度门禁 import 判定  # noqa: E402

#: 真实历史提交（现场 `工程缓存/制品仓库/平台客户端环境/平台客户端/制品来源.json` 的 提交 字段）。
历史提交 = "7dd1f57b8bdc7f896709f2fbae5844e8b07bd82f"

编译口文件 = 系统根 / "开发工具" / "开发编译口" / "编译口.py"
新鲜度门禁文件 = 系统根 / "开发工具" / "制品新鲜度门禁.py"
发布门禁分组文件 = 系统根 / "开发工具" / "发布门禁" / "运行发布门禁_执行项分组_制品与流程.py"


class 制品新鲜度门禁测试(unittest.TestCase):
    """判定 的正反样本：制品目录一律用临时目录，不依赖现场那棵树。"""

    def setUp(self) -> None:
        self._临时 = tempfile.TemporaryDirectory()
        self.制品 = Path(self._临时.name).resolve() / "平台客户端"
        # 正式运行入口必须存在：`选择待验证制品` 以此拒绝「不是正式制品」的目录，
        # 合成样本要走到判据那一步，就得先满足它的入口判据。
        (self.制品 / "运行入口").mkdir(parents=True, exist_ok=True)
        (self.制品 / "运行入口" / "启动.py").write_text("# 合成样本\n", encoding="utf-8")

    def tearDown(self) -> None:
        self._临时.cleanup()

    def _写来源(self, 来源: dict) -> None:
        (self.制品 / "制品来源.json").write_text(
            json.dumps(来源, ensure_ascii=False), encoding="utf-8")

    def test_合成制品落后HEAD_判红并报落后提交数(self) -> None:
        self._写来源({"提交": 历史提交, "工作区字节指纹": "x" * 64})
        结论 = 判定(self.制品)
        self.assertFalse(结论["通过"], "落后 HEAD 的制品必须判红")
        self.assertIsInstance(结论["落后提交数"], int)
        self.assertGreater(结论["落后提交数"], 0, "历史提交必然落后当前 HEAD")
        self.assertIn("落后", 结论["说明"])

    def test_制品来源缺提交字段_判红且不许当通过(self) -> None:
        self._写来源({})
        结论 = 判定(self.制品)
        self.assertFalse(结论["通过"], "缺 提交 字段 = 判不出落后数 ⇒ fail-closed 判红")
        self.assertIn("落后", 结论["说明"])

    def test_制品来源文件缺失_判红且不许当通过(self) -> None:
        结论 = 判定(self.制品)
        self.assertFalse(结论["通过"], "制品来源.json 不可读 ⇒ fail-closed 判红")

    def test_落后为零但来源字节指纹不符_仍判红(self) -> None:
        """落后 0 个提交 ≠ 新鲜：制品还得由**当前工作区**那批字节构建。"""
        from 开发工具.发布门禁.运行发布门禁_制品验证 import 读取统一工作区字节指纹
        指纹 = 读取统一工作区字节指纹()
        self._写来源({"提交": str(指纹.get("提交") or ""), "工作区字节指纹": "0" * 64})
        结论 = 判定(self.制品)
        self.assertFalse(结论["通过"], "来源字节指纹不符必须判红（同一 HEAD、不同字节）")
        self.assertIn("来源", 结论["说明"])

    def test_显式制品与默认定位都走同一判据(self) -> None:
        """`--制品` 只是换制品来源，判定分支不许出现第二套。"""
        源码 = 新鲜度门禁文件.read_text(encoding="utf-8")
        self.assertEqual(源码.count("def 判定("), 1, "判定 只许有一处定义")


class 制品新鲜度接线测试(unittest.TestCase):
    """判据在、门禁不调 = 半个强制（哲学 13.1）：三处接线逐条钉住。"""

    def test_编译口门禁清单含制品新鲜度且为只报告(self) -> None:
        源码 = 编译口文件.read_text(encoding="utf-8")
        块 = re.search(r'\{"名字": "制品新鲜度".*?\},', 源码, re.S)
        self.assertIsNotNone(块, "开发编译口门禁清单必须有「制品新鲜度」一项")
        文本 = 块.group(0)
        self.assertIn("开发工具.制品新鲜度门禁", 文本)
        self.assertIn('"角色": "只报告"', 文本,
                      "开发循环里只能是只报告：提交会移动 HEAD，制品只能在提交后重建")

    def test_发布门禁仍阻断制品落后(self) -> None:
        源码 = 发布门禁分组文件.read_text(encoding="utf-8")
        self.assertIn("校验制品落后提交数", 源码,
                      "阻断留在发布门禁：提交 → 重建 → 再发，那条链才闭合")

    def test_本模块不复制判据(self) -> None:
        """判据只有一处实现：本模块只许**转调**发布门禁那两条腿。

        比对**代码体**，不比 docstring —— 文档里引用现场提交号是留证据（应当保留），
        只有把提交号写进判据逻辑才算第二套实现。
        """
        源码 = 新鲜度门禁文件.read_text(encoding="utf-8")
        树 = ast.parse(源码)
        模块说明 = ast.get_docstring(树) or ""
        代码体 = 源码.replace(模块说明, "", 1)
        self.assertNotIn("git rev-list", 代码体, "落后提交数的唯一腿在发布门禁，不许自己算一遍")
        self.assertNotIn("7dd1f57b", 代码体, "不许把现场提交号写死进判据")
        self.assertIn("校验制品落后提交数", 代码体, "必须转调发布门禁的落后判据")
        self.assertIn("校验制品来源绑定", 代码体, "必须转调发布门禁的来源绑定判据")


if __name__ == "__main__":
    unittest.main()
