"""架构项A：装配对半成品包/坏依赖锁的单包级隔离（2026-09-15）。

口径（唯一权威在 `开发文档/新建支持库与模块指南.md` 第八节）：

- **单包级问题**（实现缺失 / 参数契约不可读 / 依赖锁内容为空或非法）
  → 只跳过该包并写入 `装配结果.跳过包列表` 告警，其余包照常装配；
- **跨包真冲突**（依赖缺失/版本冲突/多提供者冲突/能力重复注册/装配锁漂移/
  提供者环境未就绪/适配层缺依赖锁）→ 仍整体阻断，fail-closed 不许放松；
- 零包装配成功 = 真失败；被跳过的包不得留下任何半装配能力。

本文件对临时迷你系统根真实调用生产 `装配系统`，并用一个全新子进程复核
「生产链路里单包级跳过仍成立」。
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

系统根 = Path(__file__).resolve().parents[2]
if str(系统根) not in sys.path:
    sys.path.insert(0, str(系统根))

from 公共契约.能力契约.契约 import 能力实现, 能力注册表
from 运行核心.加载器.生命周期管理.管理器 import 装配系统

健康入口 = (
    "from 公共契约.能力契约.契约 import 能力实现\n"
    "def 注册能力(注册表):\n"
    "    注册表.注册(能力实现(\n"
    "        能力id='隔离.{名}能力', 包id='隔离.{名}', 实现函数=lambda: '隔离.{名}'))\n"
)


class 迷你根夹具(unittest.TestCase):
    """临时迷你系统根：支持库/ + 模块库/。"""

    def setUp(self) -> None:
        self.临时 = Path(tempfile.mkdtemp(prefix="单包隔离_"))
        (self.临时 / "支持库").mkdir()
        (self.临时 / "模块库").mkdir()

    def tearDown(self) -> None:
        shutil.rmtree(self.临时, ignore_errors=True)

    def 写包(
        self,
        目录名: str,
        *,
        包id: str,
        类型: str = "支持库",
        能力: list[str],
        依赖: list[dict] | None = None,
        入口源码: str | None = None,
        写入口: bool = True,
        写契约: bool | None = None,
        契约文本: str | None = None,
        依赖锁: dict | None = None,
        依赖锁文本: str | None = None,
    ) -> Path:
        """在迷你根里写一个包；契约/入口/依赖锁按参数精确控制（含各种坏形态）。"""
        根名 = "支持库" if 类型 == "支持库" else "模块库"
        目录 = self.临时 / 根名 / 目录名
        目录.mkdir(parents=True)
        (目录 / "包声明.json").write_text(json.dumps({
            "包id": 包id, "名称": 目录名, "类型": 类型, "版本": "1.0.0",
            "入口": "入口.py", "依赖": 依赖 or [],
            "能力": [{"能力id": 能力id, "名称": 能力id.split(".")[-1]} for 能力id in 能力],
        }, ensure_ascii=False), encoding="utf-8")
        if 写入口:
            (目录 / "入口.py").write_text(
                入口源码 if 入口源码 is not None
                else 健康入口.format(名=包id.rsplit(".", 1)[-1]),
                encoding="utf-8")
        if 契约文本 is not None:
            (目录 / "能力契约").mkdir(parents=True, exist_ok=True)
            (目录 / "能力契约" / "参数契约.json").write_text(契约文本, encoding="utf-8")
        elif 写契约 if 写契约 is not None else True:
            (目录 / "能力契约").mkdir(parents=True, exist_ok=True)
            (目录 / "能力契约" / "参数契约.json").write_text(json.dumps({
                "契约版本": "1.0.0",
                "能力契约": [{"能力id": 能力id, "版本": "1.0.0", "说明": 目录名,
                          "参数": [], "返回": {"类型": "dict", "说明": "统一结果"},
                          "错误码": [], "调用示例": "{}"} for 能力id in 能力],
            }, ensure_ascii=False), encoding="utf-8")
        if 依赖锁文本 is not None:
            (目录 / "依赖锁.json").write_text(依赖锁文本, encoding="utf-8")
        elif 依赖锁 is not None:
            (目录 / "依赖锁.json").write_text(json.dumps(依赖锁, ensure_ascii=False), encoding="utf-8")
        return 目录

    def 装配(self, 注册表: 能力注册表 | None = None):
        return 装配系统(self.临时 / "支持库", self.临时 / "模块库", 注册表)


class Test单包级问题只跳过该包(迷你根夹具):
    """三类单包级问题各自只跳过该包，健康包照常装配。"""

    def 健康包(self) -> None:
        self.写包("健康支持库", 包id="隔离.健康", 能力=["隔离.健康能力"])

    def 断言只跳过该包(self, 结果, 注册表, 关键字: str) -> None:
        self.assertTrue(结果.成功, str(结果.问题列表))
        self.assertEqual(结果.问题列表, [], "单包级问题不得整体阻断")
        self.assertEqual(len(结果.跳过包列表), 1, str(结果.跳过包列表))
        self.assertIn(关键字, 结果.跳过包列表[0])
        self.assertEqual(注册表.能力id列表, ["隔离.健康能力"], "被跳过的包不得留下能力")
        self.assertEqual(结果.声明能力数, 1)
        self.assertEqual(结果.已注册能力数, 1)

    def test_依赖锁为空只跳过该包(self):
        self.健康包()
        self.写包("半成品提供者", 包id="隔离.半成品", 能力=["隔离.半成品能力"],
                  依赖锁={"包": [], "直接依赖": [], "依赖闭包": [], "环境": {}})
        注册表 = 能力注册表()
        结果 = self.装配(注册表)
        self.断言只跳过该包(结果, 注册表, "依赖锁为空")
        self.assertIn("隔离.半成品", 结果.跳过包列表[0])
        self.assertIn("装配前预检", 结果.跳过包列表[0])
        # 坏锁的失败证据照落（审计链不丢）
        证据文件 = self.临时 / "工程缓存" / "提供者运行环境" / "缓存证据.jsonl"
        self.assertTrue(证据文件.is_file(), "坏锁必须留下缓存证据")
        证据 = [json.loads(行) for 行 in 证据文件.read_text(encoding="utf-8").splitlines() if 行.strip()]
        self.assertEqual(证据[-1]["类型"], "失败")
        self.assertEqual(证据[-1]["错误码"], "依赖锁为空")

    def test_依赖锁非法JSON只跳过该包不再抛穿(self):
        """非法 JSON 锁：原先 读取依赖锁 会抛 JSONDecodeError 打穿整个装配。"""
        self.健康包()
        self.写包("坏锁提供者", 包id="隔离.坏锁", 能力=["隔离.坏锁能力"],
                  依赖锁文本='{"包": [{"名称": "半')
        注册表 = 能力注册表()
        结果 = self.装配(注册表)
        self.断言只跳过该包(结果, 注册表, "依赖锁无效")

    def test_依赖锁顶层非对象只跳过该包(self):
        self.健康包()
        self.写包("锁型错提供者", 包id="隔离.锁型错", 能力=["隔离.锁型错能力"],
                  依赖锁文本="[]")
        注册表 = 能力注册表()
        结果 = self.装配(注册表)
        self.断言只跳过该包(结果, 注册表, "依赖锁无效")

    def test_入口缺失只跳过该包(self):
        self.健康包()
        目录 = self.写包("删入口", 包id="隔离.删入口", 能力=["隔离.删入口能力"])
        (目录 / "入口.py").unlink()
        注册表 = 能力注册表()
        结果 = self.装配(注册表)
        self.断言只跳过该包(结果, 注册表, "实现缺失")

    def test_实现模块未落盘只跳过该包(self):
        """入口在，但入口导入的 实现/ 文件还没落盘（子代理写一半）。"""
        self.健康包()
        入口 = (
            "from 隔离.未落盘.实现.还没有 import 能力\n"
            "from 公共契约.能力契约.契约 import 能力实现\n"
            "def 注册能力(注册表):\n"
            "    注册表.注册(能力实现(能力id='隔离.未落盘能力', 包id='隔离.未落盘', 实现函数=能力))\n"
        )
        self.写包("未落盘", 包id="隔离.未落盘", 能力=["隔离.未落盘能力"], 入口源码=入口)
        注册表 = 能力注册表()
        结果 = self.装配(注册表)
        self.断言只跳过该包(结果, 注册表, "装配失败")
        self.assertIn("未落盘", 结果.跳过包列表[0])

    def test_入口执行中途报错只跳过该包且不残留半装配(self):
        """入口注册前一半再抛异常：该包已注册的能力必须被撤回（零半装配）。"""
        self.健康包()
        入口 = (
            "from 公共契约.能力契约.契约 import 能力实现\n"
            "def 注册能力(注册表):\n"
            "    注册表.注册(能力实现(能力id='隔离.半路能力', 包id='隔离.半路', 实现函数=lambda: '半'))\n"
            "    raise RuntimeError('实现里半路炸了')\n"
        )
        self.写包("半路", 包id="隔离.半路", 能力=["隔离.半路能力"], 入口源码=入口)
        注册表 = 能力注册表()
        结果 = self.装配(注册表)
        self.assertTrue(结果.成功, str(结果.问题列表))
        self.assertEqual(注册表.能力id列表, ["隔离.健康能力"], "失败包已注册的能力必须撤回")
        self.assertIn("半路", 结果.跳过包列表[0])
        self.assertIn("实现里半路炸了", 结果.跳过包列表[0])

    def test_参数契约不可读只跳过该包(self):
        self.健康包()
        self.写包("坏契约包", 包id="隔离.坏契约", 能力=["隔离.坏契约能力"], 契约文本="{不是 JSON")
        注册表 = 能力注册表()
        结果 = self.装配(注册表)
        self.断言只跳过该包(结果, 注册表, "参数契约不可读")

    def test_依赖被跳过包的能力时级联跳过(self):
        """被跳过包的下游：依赖它的包也跳过并告警（不许带病装配）。"""
        self.健康包()
        self.写包("半成品提供者", 包id="隔离.半成品", 能力=["隔离.半成品能力"],
                  依赖锁={"包": [], "直接依赖": []})
        self.写包("下游模块", 包id="隔离.下游", 类型="基础模块", 能力=["隔离.下游能力"],
                  依赖=[{"能力": "隔离.半成品能力"}])
        注册表 = 能力注册表()
        结果 = self.装配(注册表)
        self.assertTrue(结果.成功, str(结果.问题列表))
        self.assertEqual(注册表.能力id列表, ["隔离.健康能力"])
        self.assertEqual(len(结果.跳过包列表), 2, str(结果.跳过包列表))
        下游告警 = [告警 for 告警 in 结果.跳过包列表 if "隔离.下游" in 告警]
        self.assertTrue(下游告警, str(结果.跳过包列表))
        self.assertIn("依赖级联", 下游告警[0])
        self.assertIn("隔离.半成品", 下游告警[0])

    def test_全部包都被跳过时装配失败(self):
        """零包装配成功 = 零可用能力：这才是真失败（fail-closed 底线）。"""
        self.写包("半成品提供者", 包id="隔离.半成品", 能力=["隔离.半成品能力"],
                  依赖锁={"包": [], "直接依赖": []})
        注册表 = 能力注册表()
        结果 = self.装配(注册表)
        self.assertFalse(结果.成功)
        self.assertTrue(any("未发现可装配的包" in 问题 for 问题 in 结果.问题列表),
                        str(结果.问题列表))
        self.assertEqual(注册表.能力id列表, [])

    def test_打印含跳过告警(self):
        self.健康包()
        self.写包("半成品提供者", 包id="隔离.半成品", 能力=["隔离.半成品能力"],
                  依赖锁={"包": [], "直接依赖": []})
        文本 = self.装配().打印()
        self.assertIn("单包级跳过告警", 文本)
        self.assertIn("隔离.半成品", 文本)
        self.assertIn("依赖锁为空", 文本)


class Test跨包真冲突仍整体阻断(迷你根夹具):
    """fail-closed 反证：单包级隔离不得把真错误降级成跳过。"""

    def test_适配层提供者完全缺依赖锁必须整体阻断(self):
        """删锁必须装配失败（fail-closed）：同根内有健康包也不许放行。"""
        self.写包("健康支持库", 包id="隔离.健康", 能力=["隔离.健康能力"])
        self.写包("缺锁提供者", 包id="支持库.适配层.缺锁提供者",
                  能力=["隔离.缺锁提供者能力"], 写契约=False)
        注册表 = 能力注册表()
        结果 = self.装配(注册表)
        self.assertFalse(结果.成功, "适配层缺锁必须整体阻断")
        self.assertTrue(any("提供者依赖锁缺失（装配阻断）" in 问题 for 问题 in 结果.问题列表),
                        str(结果.问题列表))
        self.assertEqual(注册表.能力id列表, [], "整体阻断不得留下半装配能力")

    def test_模块聚合契约缺失必须整体阻断(self):
        """删契约 fail-closed（模块契约缺失仍整体阻断，隔离只管「契约不可读」）。"""
        self.写包("健康支持库", 包id="隔离.健康", 能力=["隔离.健康能力"])
        self.写包("缺契约模块", 包id="隔离.缺契约", 类型="基础模块",
                  能力=["隔离.缺契约能力"], 写契约=False)
        结果 = self.装配(能力注册表())
        self.assertFalse(结果.成功, "模块契约缺失必须整体阻断")
        self.assertTrue(any("聚合契约缺失（装配阻断）" in 问题 for 问题 in 结果.问题列表),
                        str(结果.问题列表))

    def test_跨包能力重复注册必须整体阻断(self):
        """两个包抢同一个能力 id：属能力多提供者冲突，不许降级成跳过。"""
        self.写包("健康支持库", 包id="隔离.健康", 能力=["隔离.健康能力"])
        抢注册入口 = (
            "from 公共契约.能力契约.契约 import 能力实现\n"
            "def 注册能力(注册表):\n"
            "    注册表.注册(能力实现(能力id='隔离.抢占能力', 包id='{包id}', 实现函数=lambda: '抢'))\n"
        )
        for 序号 in (1, 2):
            self.写包(f"争用包{序号}", 包id=f"隔离.争用{序号}",
                      能力=[f"隔离.争用{序号}能力"],
                      入口源码=抢注册入口.format(包id=f"隔离.争用{序号}"))
        注册表 = 能力注册表()
        结果 = self.装配(注册表)
        self.assertFalse(结果.成功, "能力重复注册必须整体阻断")
        self.assertTrue(any("重复注册" in 问题 for 问题 in 结果.问题列表), str(结果.问题列表))
        self.assertEqual(注册表.能力id列表, [], "整体阻断不得留下半装配能力")

    def test_依赖缺失与版本冲突仍整体阻断(self):
        self.写包("健康支持库", 包id="隔离.健康", 能力=["隔离.健康能力"])
        self.写包("缺依赖模块", 包id="隔离.缺依赖", 类型="基础模块",
                  能力=["隔离.缺依赖能力"], 依赖=[{"能力": "根本没有.能力"}])
        结果 = self.装配(能力注册表())
        self.assertFalse(结果.成功, "依赖缺失必须整体阻断")
        self.assertTrue(any("无提供者" in 问题 or "缺失" in 问题 for 问题 in 结果.问题列表),
                        str(结果.问题列表))


class Test生产链路与真实树(迷你根夹具):
    """新进程链路复核 + 真实仓库基线不被隔离机制改写。"""

    def test_新进程里单包级跳过仍成立(self):
        """全新解释器、清空 PYTHONPATH：生产装配入口对半成品包同样只跳过并告警。"""
        self.写包("健康支持库", 包id="隔离.健康", 能力=["隔离.健康能力"])
        self.写包("半成品提供者", 包id="隔离.半成品", 能力=["隔离.半成品能力"],
                  依赖锁={"包": [], "直接依赖": []})
        环境 = {k: v for k, v in os.environ.items()
                if k not in ("PYTHONPATH", "PYTHONHOME", "PYTHONSTARTUP")}
        环境["PYTHONDONTWRITEBYTECODE"] = "1"
        脚本 = textwrap.dedent(f"""
            import json, sys
            from pathlib import Path
            sys.path.insert(0, {str(系统根)!r})
            sys.path.insert(0, {str(self.临时)!r})
            from 运行核心.加载器.生命周期管理.管理器 import 装配系统
            from 公共契约.能力契约.契约 import 能力注册表
            注册表 = 能力注册表()
            结果 = 装配系统(Path({str(self.临时 / "支持库")!r}), Path({str(self.临时 / "模块库")!r}), 注册表)
            print(json.dumps({{
                "成功": 结果.成功, "问题列表": 结果.问题列表,
                "跳过包列表": 结果.跳过包列表, "能力": 注册表.能力id列表,
            }}, ensure_ascii=False))
        """)
        进程 = subprocess.run([sys.executable, "-B", "-c", 脚本], capture_output=True,
                              text=True, encoding="utf-8", env=环境,
                              cwd=str(self.临时), timeout=120)
        self.assertEqual(进程.returncode, 0, 进程.stderr[-800:])
        数据 = json.loads(进程.stdout)
        self.assertTrue(数据["成功"], str(数据["问题列表"]))
        self.assertEqual(数据["能力"], ["隔离.健康能力"])
        self.assertEqual(len(数据["跳过包列表"]), 1)
        self.assertIn("隔离.半成品", 数据["跳过包列表"][0])

    def test_真实仓库装配基线不被隔离机制改写(self):
        """真实仓库：装配成功、跳过包为空、声明能力与注册能力闭环。"""
        结果 = 装配系统(系统根 / "支持库", 系统根 / "模块库", 能力注册表(), 系统根 / "技能库")
        self.assertTrue(结果.成功, str(结果.问题列表))
        self.assertEqual(结果.跳过包列表, [], "正式仓库不得出现被跳过的包")
        self.assertEqual(结果.问题列表, [])
        self.assertEqual(结果.声明能力数, 结果.已注册能力数, "声明/注册能力必须闭环")
        self.assertGreater(结果.已注册能力数, 300)


if __name__ == "__main__":
    unittest.main()
