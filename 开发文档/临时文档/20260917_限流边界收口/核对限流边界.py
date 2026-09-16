"""限流边界取证与核对（可复跑，无 sleep、无外部依赖）。

用法（在项目根执行）：
    /opt/homebrew/bin/python3.14 开发文档/临时文档/20260917_限流边界收口/核对限流边界.py
    /opt/homebrew/bin/python3.14 .../核对限流边界.py --文件 /tmp/坏的限流器.py   # 反向验证：改坏即变红

它同时做两件事：
  一、**行为取证**：五维各自落在哪个内存键、窗口是固定还是滑动、重启/多实例是否保留。
  二、**文档断言**：`限流器.py` 里必须如实写明「进程内固定窗口 / 不跨重启 / 不跨实例 /
      多实例需外部共享限流」，少一句就失败（防止措辞被改回夸大版本）。
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import unittest
from pathlib import Path

项目根 = Path(__file__).resolve().parents[3]
if str(项目根) not in sys.path:
    sys.path.insert(0, str(项目根))

from 运行核心.统一网关.限流器 import 限流器  # noqa: E402


def 读源码(覆盖文件: Path | None = None) -> str:
    路径 = 覆盖文件 or (项目根 / "运行核心" / "统一网关" / "限流器.py")
    return 路径.read_text(encoding="utf-8")


class 一_机制取证(unittest.TestCase):
    """五维究竟怎么实现的——用真实调用而不是读注释来判定。"""

    def test_五维落在同一个进程内状态表_只是维度键不同(self):
        器 = 限流器(单项目频率=10, 单用户频率=10, 单能力频率=10, 单任务频率=10, 单提供者频率=10)
        通过, 说明 = 器.进入请求(
            项目id="项目A", 用户id="用户A", 能力id="能力A", 任务id="任务A", 提供者="提供者A",
        )
        self.assertTrue(通过, 说明)
        self.assertEqual(
            sorted(标识[0] for 标识 in 器.状态表),
            sorted(["任务", "提供者", "能力", "用户", "项目"]),
            "五维必须落在同一个 self.状态表 上，以 (维度, 键) 为标识",
        )
        self.assertEqual(
            sorted(标识[1] for 标识 in 器.状态表),
            sorted(["任务A", "提供者A", "能力A", "用户A", "项目A"]),
        )
        # 五维共用同一个 限流状态 结构体类型：没有第二套机制
        self.assertEqual({type(状态).__name__ for 状态 in 器.状态表.values()}, {"限流状态"})
        器.离开请求(
            项目id="项目A", 用户id="用户A", 能力id="能力A", 任务id="任务A", 提供者="提供者A",
        )

    def test_未传的维度不建键_维度是可选的(self):
        器 = 限流器(单用户频率=5)
        通过, 说明 = 器.进入请求(用户id="只有用户")
        self.assertTrue(通过, 说明)
        self.assertEqual(sorted(器.状态表), [("用户", "只有用户")])
        器.离开请求(用户id="只有用户")

    def test_窗口到点整体清零_是固定窗口而非滑动窗口(self):
        器 = 限流器(单用户频率=2, 窗口秒=3600.0)  # 窗口拉到 1 小时，确保本测试内不会自然滚动
        上限 = 器.频率上限表["用户"]
        for _ in range(上限):
            self.assertTrue(器.进入请求(用户id="用户A")[0])
            器.离开请求(用户id="用户A")
        通过, 说明 = 器.进入请求(用户id="用户A")
        self.assertFalse(通过, "窗口计数满后必须拒绝")
        self.assertIn("用户调用频率超过上限", 说明)
        self.assertTrue(说明.startswith("限流: "), "错误码文案是契约，不得变化")
        # 直接拨动窗口起点模拟时间流逝（确定性，不 sleep）：整窗清零 = 固定窗口。
        状态 = 器.状态表[("用户", "用户A")]
        self.assertEqual(状态.窗口计数, 上限)
        状态.窗口开始 -= 器.窗口秒
        器.进入请求(用户id="用户A")
        self.assertEqual(状态.窗口计数, 1, "窗口一过整体归零重数：固定窗口，不是滑动窗口的连续衰减")

    def test_状态不落盘_重启即归零(self):
        器 = 限流器(单用户频率=5)
        器.进入请求(用户id="用户A")
        器.离开请求(用户id="用户A")
        self.assertEqual(len(器.状态表), 1)
        新实例 = 限流器(单用户频率=5)  # 等价「进程重启」：状态只活在实例里
        self.assertEqual(新实例.状态表, {})
        self.assertEqual(新实例.状态快照()["五维状态"], [])
        self.assertEqual(新实例.累计拒绝数, 0)
        源码 = 读源码()
        for 持久化痕迹 in ("sqlite3", "pickle", "json.dump", "open(", "shelve", "mmap"):
            self.assertNotIn(持久化痕迹, 源码, f"限流器不得出现持久化痕迹：{持久化痕迹}")

    def test_多实例各算各的_进程间不共享(self):
        甲 = 限流器(单用户频率=2)
        乙 = 限流器(单用户频率=2)
        for _ in range(2):
            self.assertTrue(甲.进入请求(用户id="用户A")[0])
            甲.离开请求(用户id="用户A")
        self.assertFalse(甲.进入请求(用户id="用户A")[0], "甲应该已经打满")
        self.assertTrue(乙.进入请求(用户id="用户A")[0], "乙是另一个实例，计数互不影响")
        乙.离开请求(用户id="用户A")
        源码 = 读源码()
        for 跨进程痕迹 in ("multiprocessing", "shared_memory", "socket", "redis", "文件锁"):
            self.assertNotIn(跨进程痕迹, 源码, f"限流器不得出现跨进程共享痕迹：{跨进程痕迹}")

    def test_跨进程实测_两个进程互不可见(self):
        片段 = (
            "import sys; sys.path.insert(0, r'{根}');"
            "from 运行核心.统一网关.限流器 import 限流器;"
            "器 = 限流器(单用户频率=2);"
            "r = [器.进入请求(用户id='用户A')[0] for _ in range(3)];"
            "print(r)"
        ).format(根=项目根)
        输出 = []
        for _ in range(2):
            完成 = subprocess.run(
                [sys.executable, "-c", 片段],
                capture_output=True, text=True, cwd=str(项目根), timeout=60,
            )
            self.assertEqual(完成.returncode, 0, 完成.stderr)
            输出.append(完成.stdout.strip())
        self.assertEqual(输出, ["[True, True, False]"] * 2, "每个进程都从零开始：计数不跨进程/不跨实例")

    def test_并发保护还在_不许为了口径变弱(self):
        """收口只改措辞，不得删掉并发保护：全局并发与单维度并发都必须仍生效。"""
        器 = 限流器(最大并发请求=1, 单维度并发=40, 单用户频率=1000)
        self.assertTrue(器.进入请求(用户id="用户A")[0])
        通过, 说明 = 器.进入请求(用户id="用户B")
        self.assertFalse(通过, "全局并发上限必须仍然生效")
        self.assertIn("并发请求数超过上限", 说明)
        器.离开请求(用户id="用户A")

        器2 = 限流器(最大并发请求=50, 单维度并发=1, 单用户频率=1000)
        self.assertTrue(器2.进入请求(用户id="用户A")[0])
        通过, 说明 = 器2.进入请求(用户id="用户A")
        self.assertFalse(通过, "单维度并发上限必须仍然生效")
        self.assertIn("用户并发超过上限", 说明)

    def test_任务与流式入口只认全局计数_不查五维(self):
        """取证实况：进入任务/进入流式 收五个维度参数但并不使用，只比对全局计数器。"""
        器 = 限流器(最大任务数=1, 单任务频率=1, 窗口秒=3600.0)
        self.assertTrue(器.进入任务(任务id="任务A")[0])
        通过, 说明 = 器.进入任务(任务id="任务A")
        self.assertFalse(通过)
        self.assertIn("任务数超过上限", 说明)
        self.assertEqual(器.状态表, {}, "进入任务 不建任何维度状态键")
        器.离开任务()

        器2 = 限流器(最大流式连接=1, 单能力频率=1, 窗口秒=3600.0)
        self.assertTrue(器2.进入流式(能力id="能力A")[0])
        通过, 说明 = 器2.进入流式(能力id="能力A")
        self.assertFalse(通过)
        self.assertIn("流式连接数超过上限", 说明)
        self.assertEqual(器2.状态表, {}, "进入流式 不建任何维度状态键")
        器2.离开流式()


class 二_文档断言(unittest.TestCase):
    """名字必须与实现相符：少一句如实边界就变红。"""

    必须出现 = [
        "进程内",
        "固定窗口",
        "不跨重启",
        "不跨实例",
        "外部共享限流",
        "单进程",
    ]

    def test_模块与类说明写明进程内固定窗口边界(self):
        源码 = 读源码(测试用文件)
        for 措辞 in self.必须出现:
            self.assertIn(措辞, 源码, f"限流器.py 缺少如实边界措辞：{措辞}")
        模块说明 = 源码.split('"""')[1].strip()
        第一行 = 模块说明.splitlines()[0]
        self.assertIn(
            "进程内固定窗口", 第一行,
            "模块首行（名字层）必须直接写明机制，不得再只写「五维限流与并发治理」这种抽象高于实现的措辞",
        )

    def test_说明文档存在且写明边界(self):
        说明路径 = 项目根 / "运行核心" / "统一网关" / "说明" / "限流边界说明.md"
        self.assertTrue(说明路径.exists(), f"缺少包级边界说明：{说明路径}")
        文本 = 说明路径.read_text(encoding="utf-8")
        for 措辞 in self.必须出现 + ["不跨进程", "不提供", "429"]:
            self.assertIn(措辞, 文本, f"限流边界说明.md 缺少：{措辞}")


测试用文件: Path | None = None


def 主() -> int:
    global 测试用文件
    解析 = argparse.ArgumentParser(description="核对限流器边界与措辞")
    解析.add_argument("--文件", type=Path, default=None, help="改读指定的 限流器.py（反向验证用）")
    参数, 剩余 = 解析.parse_known_args()
    测试用文件 = 参数.文件

    装载 = unittest.TestSuite()
    装载.addTests(unittest.defaultTestLoader.loadTestsFromTestCase(一_机制取证))
    装载.addTests(unittest.defaultTestLoader.loadTestsFromTestCase(二_文档断言))
    结果 = unittest.TextTestRunner(verbosity=2).run(装载)
    return 0 if 结果.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(主())
