"""网关运行态同根判据测试（债务 #219）：纯判据正反向样本 + 两处接线不许断。

被测对象是 `开发工具/能力网关/重启网关.判定同根`（**纯函数**，不碰真网关），
故样本可以随意造正反两面；另加三条**接线**断言，防「判据在、门禁不调」——
#219 的病形正是「文档写了三处、漏了第四处」靠人手记，判据不接线就等于没修。

反向样本的依据（2026-09-21 实测原文）：plist 缺 `系统底座_工程缓存根` 时，
网关把 `制品仓库` 解析到 `~/Library/Caches/系统工程平台/运行缓存/制品仓库`，
而构建链写的是源码树 `工程缓存/制品仓库` ⇒ `制品根目录` 与 `稳定路径` 两个读数
**同时**指向另一棵树，而「健康 200／能力数 746／装配告警空」全绿。
"""

from __future__ import annotations

import ast
import sys
import tempfile
import unittest
from pathlib import Path

系统根 = Path(__file__).resolve().parents[2]
if str(系统根) not in sys.path:
    sys.path.insert(0, str(系统根))

from 开发工具.能力网关.重启网关 import (  # noqa: E402
    判定同根,
    期望运行缓存根,
    运行缓存变量名,
)

门禁分组文件 = 系统根 / "开发工具" / "发布门禁" / "运行发布门禁_执行项分组_制品与流程.py"
制品验证文件 = 系统根 / "开发工具" / "发布门禁" / "运行发布门禁_制品验证.py"
重启网关文件 = 系统根 / "开发工具" / "能力网关" / "重启网关.py"


class 网关运行态同根测试(unittest.TestCase):
    """判定同根 的正反样本；期望根用临时目录，不依赖现场那棵树。"""

    def setUp(self) -> None:
        self._临时 = tempfile.TemporaryDirectory()
        self.期望根 = Path(self._临时.name).resolve()
        self.制品仓库 = self.期望根 / "制品仓库"
        self.制品仓库.mkdir(parents=True, exist_ok=True)
        self.制品模式工作目录 = self.制品仓库 / "平台客户端环境" / "平台客户端"
        self.制品模式工作目录.mkdir(parents=True, exist_ok=True)
        # 真值全绿样本：网关侧两个读数都指向构建链那棵树
        self.真值 = {
            "制品根目录": str(self.制品仓库),
            "稳定路径有效": True,
            "稳定路径激活路径": str(self.制品模式工作目录),
        }
        self.制品模式环境 = {运行缓存变量名: str(self.期望根)}

    def tearDown(self) -> None:
        self._临时.cleanup()

    def _判(self, 真值=None, 环境=None, 工作目录=None) -> dict:
        return 判定同根(
            self.真值 if 真值 is None else 真值,
            self.制品模式环境 if 环境 is None else 环境,
            str(self.制品模式工作目录) if 工作目录 is None else 工作目录,
            期望根=self.期望根,
        )

    # —— 正面样本：制品模式 + plist 第四处已设 ——

    def test_制品模式且plist第四处已设_判同根(self) -> None:
        结论 = self._判()
        self.assertTrue(结论["同根"], 结论["说明"])
        self.assertTrue(结论["制品模式"])
        self.assertIn(str(self.制品仓库), 结论["说明"])

    def test_源码树模式_不要求plist第四处(self) -> None:
        """源码树模式（WorkingDirectory 不在制品仓库下）本来就落在 `工程缓存`，无分叉可言。"""
        结论 = self._判(环境={}, 工作目录=str(self.期望根))
        self.assertTrue(结论["同根"], 结论["说明"])
        self.assertFalse(结论["制品模式"])

    # —— 反向样本：四种病形各判红一次 ——

    def test_网关侧制品根指向别棵树_判红(self) -> None:
        """#219 实测病形：网关解析到 `~/Library/Caches/…`，构建链写的是源码树。"""
        真值 = dict(self.真值, 制品根目录="/Users/某人/Library/Caches/系统工程平台/运行缓存/制品仓库")
        结论 = self._判(真值=真值)
        self.assertFalse(结论["同根"])
        self.assertIn("分叉", 结论["说明"])

    def test_稳定路径校验无效_判红(self) -> None:
        """#219 处置栏点名的口径：`校验平台客户端稳定路径` 必须 `有效=true`。"""
        结论 = self._判(真值=dict(self.真值, 稳定路径有效=False))
        self.assertFalse(结论["同根"])
        self.assertIn("稳定路径", 结论["说明"])

    def test_稳定路径激活路径在别棵树_判红(self) -> None:
        结论 = self._判(真值=dict(self.真值, 稳定路径激活路径="/Users/某人/Library/Caches/别处/平台客户端"))
        self.assertFalse(结论["同根"])
        self.assertIn("激活路径", 结论["说明"])

    def test_制品模式但plist缺第四处_判红并点名下次重启(self) -> None:
        """这一问防的是回潮：`launchctl kickstart` 不重读 plist ⇒ 现在同根 ≠ 重启后同根。"""
        结论 = self._判(环境={})
        self.assertFalse(结论["同根"])
        self.assertIn("下次重启", 结论["说明"])

    def test_制品模式但plist第四处指错树_判红(self) -> None:
        结论 = self._判(环境={运行缓存变量名: "/Users/某人/别的仓库/工程缓存"})
        self.assertFalse(结论["同根"])
        self.assertIn("下次重启", 结论["说明"])

    def test_取不到网关真值_判红且不许当通过(self) -> None:
        """fail-closed：判据取不到就判红，不许静默当成通过。"""
        结论 = self._判(真值={"制品根目录": "", "稳定路径有效": None, "稳定路径激活路径": ""})
        self.assertFalse(结论["同根"])
        self.assertIn("fail-closed", 结论["说明"])

    def test_期望根默认取本仓工程缓存(self) -> None:
        """`期望运行缓存根()` = 本仓 `工程缓存`（构建链写入的那棵树）。"""
        self.assertEqual(期望运行缓存根(), (系统根 / "工程缓存").resolve())

    # —— 接线断言：判据在 ≠ 判据覆盖（#219 就是「只写文档、不接门禁」）——

    def _源码(self, 文件: Path) -> str:
        return 文件.read_text(encoding="utf-8")

    def test_探活与重启的成功定义都含同根(self) -> None:
        源码 = self._源码(重启网关文件)
        self.assertIn('结果["运行态同根"] = 运行态同根(凭证)', 源码)
        self.assertEqual(
            源码.count('结果["成功"] = bool(结果["网关活着"] and 结果["运行态同根"]["同根"])'), 1,
            "探活的成功定义必须含同根")
        self.assertEqual(
            源码.count('结果["成功"] = bool(结果["能力数"] and 结果["运行态同根"]["同根"])'), 1,
            "重启的成功定义必须含同根")

    def test_发布门禁接线到同根判据(self) -> None:
        分组源码 = self._源码(门禁分组文件)
        self.assertIn('检查("网关运行态与构建链同根", *校验网关运行态同根())', 分组源码)
        验证源码 = self._源码(制品验证文件)
        self.assertIn("def 校验网关运行态同根()", 验证源码)
        self.assertIn("from 开发工具.能力网关.重启网关 import 读取凭证, 运行态同根", 验证源码)

    def test_判据只有一处实现_发布门禁不复制判据(self) -> None:
        """发布门禁侧只许转调，不许再写一份「制品根目录 == 期望」的比较（哲学 1.2）。"""
        验证源码 = self._源码(制品验证文件)
        树 = ast.parse(验证源码)
        本函数体 = ""
        for 节点 in ast.walk(树):
            if isinstance(节点, ast.FunctionDef) and 节点.name == "校验网关运行态同根":
                本函数体 = ast.unparse(节点)
        self.assertTrue(本函数体, "没找到 校验网关运行态同根")
        self.assertNotIn("期望制品仓库", 本函数体, "发布门禁侧复制了判据本体")
        self.assertNotIn("is_relative_to", 本函数体, "发布门禁侧复制了判据本体")


class 重载配置腿测试(unittest.TestCase):
    """plist 改了要能生效：`--重载配置` 这条腿必须存在，且不复制收尾判据。

    现场依据（2026-09-24 实测，批J）：plist 补了 `SoftResourceLimits.NumberOfFiles = 65536`，
    而 `kickstart -k` 重启后进程真实软限**仍是 256**（经 MCP `执行命令` 起子进程读
    `resource.getrlimit(RLIMIT_NOFILE)` 实测 `(256, …)`）⇒「配置级修复永远只停在文件上」。
    本类钉三件事：① 腿在且接在入口上；② 两条腿共用同一处收尾判据（哲学 1.2）；
    ③ `bootout → bootstrap` 的竞态有退避重试（实测首次必 EIO，不许留给人工救场）。
    """

    def _源码(self) -> str:
        return 重启网关文件.read_text(encoding="utf-8")

    def test_重载配置两个形态都接在入口上(self) -> None:
        源码 = self._源码()
        self.assertIn('if "--重载配置" in 参:', 源码)
        self.assertIn("raise SystemExit(重载配置(凭, _超时秒(参)))", 源码)
        self.assertIn('if "--重载配置后台" in 参:', 源码)
        self.assertIn('触发后台重启(参, "--重载配置")', 源码)

    def test_重载用bootout加bootstrap而不是kickstart(self) -> None:
        """比对**代码体**，不比 docstring —— 说明里引用 kickstart 正是在讲它为什么不重读 plist。"""
        树 = ast.parse(self._源码())
        节点 = next((项 for 项 in ast.walk(树)
                     if isinstance(项, ast.FunctionDef) and 项.name == "重载配置"), None)
        self.assertIsNotNone(节点, "没找到 重载配置")
        语句表 = list(节点.body)
        if 语句表 and isinstance(语句表[0], ast.Expr) and isinstance(语句表[0].value, ast.Constant):
            语句表 = 语句表[1:]                      # 跳过 docstring
        代码体 = "\n".join(ast.unparse(语句) for 语句 in 语句表)
        self.assertIn("bootout", 代码体)
        self.assertIn("bootstrap", 代码体)
        self.assertNotIn("kickstart", 代码体, "kickstart 不重读 plist，重载腿不许用它")

    def test_收尾判据只有一处实现(self) -> None:
        源码 = self._源码()
        self.assertEqual(源码.count("def _收尾("), 1, "收尾必须只有一处实现")
        self.assertEqual(
            源码.count('结果["成功"] = bool(结果["能力数"] and 结果["运行态同根"]["同根"])'), 1,
            "重启/重载共用同一处成功定义，不许各写一遍")
        self.assertEqual(源码.count("return _收尾(结果, 凭证, 超时秒)"), 2,
                         "两条腿都必须走同一个收尾")

    def test_bootout后bootstrap有退避重试(self) -> None:
        """实测首次必 EIO 的竞态必须被这条腿自己吃掉，否则每次都要人工救场。"""
        from 开发工具.能力网关.重启网关 import 重载重试次数, 重载重试间隔秒
        self.assertGreaterEqual(重载重试次数, 2)
        self.assertGreater(重载重试间隔秒, 0)
        源码 = self._源码()
        self.assertIn("for 轮次 in range(1, 重载重试次数 + 1):", 源码)
        self.assertIn('结果["bootstrap轮次"] = 轮次', 源码,
                      "轮次要记进结论（判据要能区分「第一次就成」与「重试才成」）")

    def test_后台触发只有一处实现且模式参数化(self) -> None:
        """两条腿共用「脱离进程组起子进程」的姿势，不许各写一遍 Popen。

        比对**代码体**：模块 docstring 里也写着 `start_new_session=True`（那是在解释姿势）。
        """
        源码 = self._源码()
        树 = ast.parse(源码)
        代码体 = 源码.replace(ast.get_docstring(树) or "", "", 1)
        self.assertEqual(代码体.count("def 触发后台重启("), 1)
        self.assertEqual(代码体.count("平台适配.子进程组启动标志()"), 1,
                         "脱离进程组的姿势只许有一处（唯一腿：平台适配.子进程组启动标志）")


if __name__ == "__main__":
    unittest.main()
