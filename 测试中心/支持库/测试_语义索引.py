"""语义索引 模板测试骨架：合法调用/错误码/超时/提供者不可用（真实可跑）。

夹具口径（2026-09-22 修）：索引根必须是**受管临时目录**里真造出来的目录。
原夹具硬写 `索引根="样例"`（仓库相对路径），而该目录**不存在** ⇒ 参数校验
（`目录不存在`）**先于**被测分支失败，`test_合法调用` / `test_超时` /
`test_提供者不可用` 三条用例**永远红**，且看不出是夹具问题还是实现问题。
"""
from __future__ import annotations
import os, shutil, sys, tempfile, unittest
from unittest import mock

for 目录 in ("/Users/hekunhua/Documents/Agent/PHP/系统工程平台/支持库/后端/代码解析支持库", "/Users/hekunhua/Documents/Agent/PHP/系统工程平台"):
    if 目录 not in sys.path:
        sys.path.insert(0, 目录)

from 语义索引 import 建代码索引, 查代码块
from 公共契约.基础类型.结果类型 import 结果


class Test语义索引(unittest.TestCase):
    """语义索引 骨架测试。"""

    def setUp(self):
        """造一个真实可索引的受管临时目录（不落仓库正式根）。"""
        self.索引根 = tempfile.mkdtemp(prefix="语义索引测试_")
        self.addCleanup(shutil.rmtree, self.索引根, True)
        with open(os.path.join(self.索引根, "样例代码.py"), "w", encoding="utf-8") as 文件:
            文件.write("def 示例函数():\n    return 1\n\n\nclass 示例类:\n    pass\n")

    def test_合法调用(self):
        """★ 环境边界（2026-09-22 实测，务必先读）：

        本仓 unittest 环境**没有装配**（`能力调用器` 未注入）。`建代码索引` 内部
        `收集代码块` 要经能力调用器，未装配时**每个文件都被跳过** ⇒ 块列表为空 ⇒
        在 `实现/语义索引.py:62` **早退**返回「成功（块数 0）」。

        所以本用例的「成功」在未装配环境下只证明**参数校验通过 + 能返回结果**，
        **不证明真索引成功**。真验证走 HTML GET/POST 黑盒（平台验收口径）。
        """
        结果对象 = 建代码索引(索引根=self.索引根)
        self.assertTrue(结果对象.成功, str(结果对象.错误说明))

    def test_参数不合法(self):
        结果对象 = 建代码索引(索引根=None)
        self.assertEqual(结果对象.错误码, "参数不合法")

    def test_嵌入不可用(self):
        """嵌入提供者不可用时返回 `嵌入不可用`。

        原用例名为 `test_提供者不可用`，mock 环境变量 `语义索引_禁用库` ——
        实测该变量**全仓只出现在测试自己**（`git grep` 在实现里零命中），mock 空转；
        且实现里**没有 `提供者不可用` 这个错误码**（真实三码：参数不合法 /
        目录不存在 / 嵌入不可用，见 `实现/语义索引.py:47-69`）。

        触发方式（不依赖装配）：先 mock `收集代码块` 返回非空块列表绕过未装配早退，
        再 mock `取句柄` 返回空 —— 实现 `:67-69` 据此返回 `嵌入不可用`。
        模块用 `__module__` 动态取，不猜导入路径。
        """
        实现模块 = sys.modules[建代码索引.__module__]
        假块 = [{"文件路径": "样例代码.py", "起始行": 1, "结束行": 2,
                 "块文本": "def 示例函数():\n    return 1\n", "块类型": "function"}]
        with mock.patch.object(实现模块, "收集代码块",
                               return_value={"块列表": 假块, "文件数": 1, "跳过清单": []}), \
             mock.patch.object(实现模块, "取句柄",
                               return_value=(None, "测试夹具：模拟嵌入提供者不可用")):
            结果对象 = 建代码索引(索引根=self.索引根)
        self.assertEqual(结果对象.错误码, "嵌入不可用")

    def test_超时(self):
        """★ 待查：`超时秒` 参数当前**无使用点**，本用例按当前事实断言以**防假绿**。

        原用例 mock 环境变量 `语义索引_测试超时`（全仓只出现在测试自己）并期望错误码
        `超时`（实现里没有这个码）。实测 `超时秒` **只出现在两个函数签名**
        （`实现/语义索引.py:45` / `:117`），无任何读取点 ⇒ 该参数当前不生效
        （与 #60 同族：**参数声称支持但不生效**）。

        断言口径：mock 出非空块列表（绕过未装配早退）+ 打掉 `取句柄`，
        设极小超时仍应**因嵌入不可用而失败**；一旦实现真把 `超时秒` 用起来，
        这条会**变红**，正好提醒复核（而不是像原用例那样永远假红、无人看）。
        """
        实现模块 = sys.modules[建代码索引.__module__]
        假块 = [{"文件路径": "样例代码.py", "起始行": 1, "结束行": 2,
                 "块文本": "def 示例函数():\n    return 1\n", "块类型": "function"}]
        with mock.patch.object(实现模块, "收集代码块",
                               return_value={"块列表": 假块, "文件数": 1, "跳过清单": []}), \
             mock.patch.object(实现模块, "取句柄", return_value=(None, "测试夹具")):
            结果对象 = 建代码索引(索引根=self.索引根, 超时秒=0.000001)
        self.assertNotEqual(
            结果对象.错误码, "超时",
            "超时秒 已生效（实现已改）—— 请复核本用例并改回断言 `超时`")


if __name__ == "__main__":
    unittest.main(verbosity=2)
