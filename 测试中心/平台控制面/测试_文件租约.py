"""文件租约能力面定向测试：互斥/边界/幂等/回收/统一结果契约。

运行（仓库根目录）：
    export PATH=/Library/Developer/CommandLineTools/usr/bin:$PATH; unset PYTHONPATH;
    python3.14 -m unittest 测试中心.平台控制面.测试_文件租约 -v

测试只碰临时目录（`存储目录` 显式指向 tempfile），不污染仓库运行态，不改任何既有测试。
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from 公共契约.基础类型.逻辑类型 import 真, 假
from 平台控制面.能力目录.实现.文件租约申请 import 申请文件租约
from 平台控制面.能力目录.实现.文件租约维护 import (
    回收过期文件租约,
    续租文件租约,
    释放文件租约,
    查询文件租约,
    文件租约留言,
)
from 平台控制面.能力目录.租约路径 import 校验相对路径
from 平台控制面.能力目录.文件租约存储 import 文件键, 计算内容指纹

仓库根 = Path(__file__).resolve().parents[2]
文件1 = "模块库/开工编排/实现/开工编排.py"
文件2 = "平台控制面/能力目录/服务.py"


def 值(结果) -> dict:
    """取统一结果的值（成功结果才有值）；失败即抛出断言信息。"""
    if not 结果.成功:
        raise AssertionError(f"预期成功，实为失败: {结果.错误码} {结果.错误说明}")
    return 结果.值


class 文件租约测试基类(unittest.TestCase):
    """每个用例一个独立存储目录（临时目录），用例之间零共享。"""

    def setUp(self) -> None:
        self._临时 = tempfile.TemporaryDirectory(prefix="文件租约测试")
        self.存储目录 = self._临时.name

    def tearDown(self) -> None:
        self._临时.cleanup()

    def 申请(self, 路径, 所有者="会话1", 任务="测试任务", 持有秒=300.0):
        return 申请文件租约(修改路径=路径, 所有者=所有者, 任务=任务,
                          持有秒=持有秒, 存储目录=self.存储目录)


class 批量原子认领测试(文件租约测试基类):
    def test_批量认领成功且能按路径查询到(self) -> None:
        结果 = self.申请([文件1, 文件2])
        self.assertTrue(结果.成功, 结果.错误说明)
        self.assertEqual(值(结果)["申请数"], 2)
        self.assertEqual(值(结果)["认领数"], 2)
        self.assertEqual(值(结果)["冲突清单"], [])
        查询 = 值(查询文件租约(修改路径=[文件1], 存储目录=self.存储目录))
        self.assertEqual(查询["数量"], 1)
        self.assertEqual(查询["记录表"][0]["路径"], 文件1)
        self.assertEqual(查询["记录表"][0]["所有者"], "会话1")
        self.assertTrue(查询["记录表"][0]["申请时间"])

    def test_第二个会话抢同一文件必须失败并回带占用者与占用开始时间(self) -> None:
        第一条 = 值(self.申请([文件1], 所有者="会话1"))
        self.assertEqual(len(第一条["租约id清单"]), 1)
        self.assertTrue(第一条["租约清单"][0]["申请时间"])
        第二条 = self.申请([文件1], 所有者="会话2")
        self.assertFalse(第二条.成功, "第二个会话抢同一文件必须失败，不得静默成功")
        self.assertEqual(第二条.错误码, "文件已被占用")
        self.assertIn("会话1", 第二条.错误说明)
        self.assertIn("占用开始时间", 第二条.错误说明)
        self.assertIn(第一条["租约id清单"][0], 第二条.错误说明)

    def test_批量里任一条被占用即整体失败不留半批(self) -> None:
        值(self.申请([文件1], 所有者="会话1"))
        结果 = self.申请([文件1, 文件2], 所有者="会话2")
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "文件已被占用")
        查询 = 值(查询文件租约(存储目录=self.存储目录))
        self.assertEqual(查询["数量"], 1, "被拒绝的批次不得留下任何半批租约")

    def test_跨进程第二个会话抢同一文件必须失败(self) -> None:
        值(self.申请([文件1], 所有者="会话1"))
        脚本 = (
            "import json,sys;"
            "from 平台控制面.能力目录.实现.文件租约申请 import 申请文件租约;"
            f"r=申请文件租约(修改路径=[{文件1!r}], 所有者='会话2', 任务='跨进程抢文件',"
            f" 存储目录={self.存储目录!r});"
            "print(json.dumps({'成功': r.成功, '错误码': r.错误码, '错误说明': r.错误说明},"
            " ensure_ascii=False))"
        )
        环境 = {键: 值_ for 键, 值_ in __import__("os").environ.items() if 键 != "PYTHONPATH"}
        进程 = subprocess.run([sys.executable, "-c", 脚本], cwd=str(仓库根), env=环境,
                             capture_output=True, text=True, timeout=120)
        self.assertEqual(进程.returncode, 0, f"子进程异常: {进程.stderr}")
        返回 = json.loads(进程.stdout.strip().splitlines()[-1])
        self.assertFalse(返回["成功"], "跨进程第二次认领必须失败")
        self.assertEqual(返回["错误码"], "文件已被占用")
        self.assertIn("会话1", 返回["错误说明"])


class 路径边界测试(文件租约测试基类):
    def test_越界相对路径必须硬失败(self) -> None:
        结果 = self.申请(["../平台控制面/能力目录/服务.py"], 所有者="会话2")
        self.assertFalse(结果.成功, "`../` 越界路径必须硬失败（旧实现只归一化是缺陷）")
        self.assertEqual(结果.错误码, "路径越界")
        self.assertIn("..", 结果.错误说明)

    def test_绝对路径与家目录写法必须硬失败(self) -> None:
        for 原始 in ("/etc/passwd", "~/Documents/x.py", "C:\\Windows\\x.py"):
            结果 = self.申请([原始], 所有者="会话2")
            self.assertFalse(结果.成功, f"必须拒绝: {原始}")
            self.assertEqual(结果.错误码, "路径越界", f"必须判 路径越界: {原始}")

    def test_越界与合法混投即整体拒绝(self) -> None:
        结果 = self.申请([文件1, "../../etc/passwd"], 所有者="会话1")
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "路径越界")
        查询 = 值(查询文件租约(存储目录=self.存储目录))
        self.assertEqual(查询["数量"], 0, "整体拒绝后不得留下任何租约")

    def test_路径校验口径逐条验证(self) -> None:
        通过, 问题 = 校验相对路径("./模块库/开工编排/实现/开工编排.py")
        self.assertEqual((通过, 问题), ("模块库/开工编排/实现/开工编排.py", ""))
        self.assertTrue(校验相对路径("..")[1])
        self.assertTrue(校验相对路径("a/../../b")[1])
        self.assertTrue(校验相对路径("")[1])
        self.assertTrue(校验相对路径(None)[1])


class 幂等与回收测试(文件租约测试基类):
    def test_释放后同一路径必须能立刻再次申请成功(self) -> None:
        第一条 = 值(self.申请([文件1], 所有者="会话1"))
        租约id = 第一条["租约id清单"][0]
        释放 = 值(释放文件租约(租约id清单=[租约id], 原因="收口",
                           存储目录=self.存储目录))
        self.assertEqual(释放["释放数"], 1)
        第二条 = self.申请([文件1], 所有者="会话2")
        self.assertTrue(第二条.成功, f"释放后必须能立刻再申请: {第二条.错误说明}")
        self.assertNotEqual(第二条.值["租约id清单"][0], 租约id)

    def test_重复释放幂等且已释放租约不复活(self) -> None:
        租约id = 值(self.申请([文件1]))["租约id清单"][0]
        值(释放文件租约(租约id清单=[租约id], 存储目录=self.存储目录))
        第二次 = 值(释放文件租约(租约id清单=[租约id], 存储目录=self.存储目录))
        self.assertEqual(第二次["释放数"], 0)
        self.assertEqual(第二次["幂等清单"][0]["结果"], "已结束且已释放")
        未知 = 值(释放文件租约(租约id清单=["不存在"], 存储目录=self.存储目录))
        self.assertEqual(未知["幂等清单"][0]["结果"], "未找到且已幂等")
        续租 = 续租文件租约(租约id清单=[租约id], 存储目录=self.存储目录)
        self.assertFalse(续租.成功, "已释放租约不得复活")
        self.assertEqual(续租.错误码, "租约不存在")

    def test_续租幂等只前推心跳(self) -> None:
        租约id = 值(self.申请([文件1], 持有秒=60.0))["租约id清单"][0]
        第一次 = 值(续租文件租约(租约id清单=[租约id], 持有秒=120.0,
                             存储目录=self.存储目录))
        第二次 = 值(续租文件租约(租约id清单=[租约id], 持有秒=120.0,
                             存储目录=self.存储目录))
        self.assertEqual(第一次["续租数"], 1)
        self.assertEqual(第二次["续租数"], 1)
        self.assertGreaterEqual(第二次["续租清单"][0]["心跳"],
                            第一次["续租清单"][0]["心跳"])
        查询 = 值(查询文件租约(存储目录=self.存储目录))
        self.assertEqual(查询["数量"], 1, "续租不得新建租约（幂等）")

    def test_回收过期幂等且过期后可被他人认领(self) -> None:
        值(self.申请([文件1], 所有者="会话1"))
        第一次 = 值(回收过期文件租约(心跳超时秒=0.0, 存储目录=self.存储目录))
        self.assertEqual(第一次["回收数"], 1)
        self.assertEqual(第一次["回收清单"][0]["状态"], "已过期")
        第二次 = 值(回收过期文件租约(心跳超时秒=0.0, 存储目录=self.存储目录))
        self.assertEqual(第二次["回收数"], 0, "回收必须幂等：第二次回带空清单")
        重新 = self.申请([文件1], 所有者="会话2")
        self.assertTrue(重新.成功, f"过期后必须可被其他会话认领: {重新.错误说明}")

    def test_未过期租约不被回收(self) -> None:
        值(self.申请([文件1], 持有秒=3600.0))
        回收 = 值(回收过期文件租约(心跳超时秒=300.0, 存储目录=self.存储目录))
        self.assertEqual(回收["回收数"], 0)


class 统一结果契约测试(文件租约测试基类):
    def test_失败一律走统一结果不抛异常(self) -> None:
        用例 = (
            (self.申请([]), "参数不合法"),
            (self.申请([文件1], 所有者=""), "参数不合法"),
            (self.申请([文件1], 所有者="会话1", 任务=""), "参数不合法"),
            (self.申请([文件1], 所有者="会话1", 持有秒=-1), "参数不合法"),
            (self.申请(["/tmp/x"], 所有者="会话1"), "路径越界"),
            (续租文件租约(租约id清单=[], 存储目录=self.存储目录), "参数不合法"),
            (续租文件租约(租约id清单=["x"], 存储目录=self.存储目录), "租约不存在"),
            (释放文件租约(租约id清单=[], 存储目录=self.存储目录), "参数不合法"),
            (回收过期文件租约(心跳超时秒="x", 存储目录=self.存储目录), "参数不合法"),
            (查询文件租约(修改路径=["../../x"], 存储目录=self.存储目录), "路径越界"),
        )
        for 结果, 预期码 in 用例:
            self.assertFalse(结果.成功)
            self.assertEqual(结果.错误码, 预期码)
            self.assertTrue(结果.错误说明, "失败必须带错误说明")

    def test_成功结果字段齐备且值可读(self) -> None:
        结果 = self.申请([文件1])
        self.assertTrue(结果.成功)
        self.assertIsNone(结果.错误码 or None)
        for 键 in ("租约清单", "租约id清单", "申请数", "认领数", "冲突清单"):
            self.assertIn(键, 结果.值)
        self.assertEqual(set(结果.值["租约清单"][0]) >= {"租约id", "键", "路径", "所有者",
                                                      "任务", "心跳", "申请时间", "过期时间",
                                                      "状态"}, 真)
        self.assertEqual(结果.值["租约清单"][0]["键"], 文件键(文件1))

    def test_存储损坏必须报错不得静默当空库(self) -> None:
        存储文件 = Path(self.存储目录) / "文件租约.json"
        存储文件.write_text("{不是合法 JSON", encoding="utf-8")
        结果 = self.申请([文件1])
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "存储目录不可用")
        self.assertIn("损坏", 结果.错误说明)
        查询 = 查询文件租约(存储目录=self.存储目录)
        self.assertFalse(查询.成功)
        self.assertEqual(查询.错误码, "存储目录不可用")


class 内容指纹与留言测试(文件租约测试基类):
    """内容指纹（乐观锁的「内容」那一半）与句柄留言（审计链）。

    专测「A 改了文件、B 拿旧认知来改」这条链：指纹登记 → 现场比对 → 内容已变更 →
    留言时间线 → 按现状重新认领。测试只读仓库内既有文件（不改仓库），改动场景用
    **临时目录里的自造文件**，保证用例不写仓库。
    """

    def setUp(self) -> None:
        super().setUp()
        self._文件临时 = tempfile.TemporaryDirectory(prefix="指纹测试文件")
        self.临时根 = Path(self._文件临时.name)
        self.临时相对 = "测试文件.txt"
        self.真实文件 = self.临时根 / self.临时相对
        self.真实文件.write_text("原始内容", encoding="utf-8")

    def tearDown(self) -> None:
        self._文件临时.cleanup()
        super().tearDown()

    def 指纹(self) -> str:
        指纹值, 问题 = 计算内容指纹(self.临时根, self.临时相对)
        self.assertEqual(问题, "")
        return 指纹值

    def 申请带指纹(self, 声明指纹, 所有者="会话1", 校验=True):
        # 项目根由平台内部固定（指纹算的是仓库内文件）；本用例的「文件」在临时根下，
        # 故直接经存储层验证语义，能力面走 计算内容指纹 的口径一致性。
        return 申请文件租约(
            修改路径=[{"路径": 文件1, "指纹": 声明指纹}], 所有者=所有者,
            任务="指纹用例", 存储目录=self.存储目录, 校验指纹=校验)

    def test_认领时登记内容指纹且指纹一致为真(self) -> None:
        现场, _ = 计算内容指纹(仓库根, 文件1)
        self.assertTrue(现场.startswith("sha256:"))
        结果 = self.申请带指纹(现场)
        self.assertTrue(结果.成功, 结果.错误说明)
        记录 = 结果.值["租约清单"][0]
        self.assertEqual(记录["内容指纹"], 现场)
        self.assertEqual(记录["已声明指纹"], 现场)
        self.assertEqual(记录["指纹一致"], 真)
        self.assertEqual(记录["留言"], [])
        self.assertEqual(记录["留言数"], 0)

    def test_校验指纹时声明与现场不一致必须内容已变更(self) -> None:
        结果 = self.申请带指纹("sha256:" + "0" * 64)
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "内容已变更")
        self.assertIn("内容已变更", 结果.错误说明)
        self.assertIn("查询文件租约", 结果.错误说明)

    def test_不校验指纹时旧声明也能认领但登记不一致(self) -> None:
        结果 = self.申请带指纹("sha256:" + "0" * 64, 校验=False)
        self.assertTrue(结果.成功, 结果.错误说明)
        self.assertEqual(结果.值["租约清单"][0]["指纹一致"], 假)

    def test_新建的文件也能认领且指纹登记为不存在(self) -> None:
        现场, 问题 = 计算内容指纹(仓库根, "不存在的目录/新文件.py")
        self.assertEqual(问题, "")
        self.assertEqual(现场, "不存在")
        结果 = 申请文件租约(修改路径=["不存在的目录/新文件.py"], 所有者="会话1",
                        任务="新建文件", 存储目录=self.存储目录)
        self.assertTrue(结果.成功, 结果.错误说明)
        self.assertEqual(结果.值["租约清单"][0]["内容指纹"], "不存在")

    def test_留言只增不改且挂非活跃租约必须失败(self) -> None:
        租约id = 值(self.申请([文件1]))["租约id清单"][0]
        第一条 = 文件租约留言(租约id=租约id, 作者="会话1", 留言="改了 A", 存储目录=self.存储目录)
        self.assertTrue(第一条.成功, 第一条.错误说明)
        self.assertEqual(第一条.值["留言数"], 1)
        第二条 = 文件租约留言(租约id=租约id, 作者="会话1", 留言="又改了 B", 存储目录=self.存储目录)
        self.assertTrue(第二条.成功)
        self.assertEqual(第二条.值["留言数"], 2)
        查询 = 值(查询文件租约(修改路径=[文件1], 存储目录=self.存储目录))
        留言表 = 查询["记录表"][0]["留言"]
        self.assertEqual([条["留言"] for 条 in 留言表], ["改了 A", "又改了 B"])
        # 释放后留言必须被拒（留言是「在场记录」，不许挂到已结束的句柄上）
        释放文件租约(租约id清单=[租约id], 存储目录=self.存储目录)
        第三条 = 文件租约留言(租约id=租约id, 作者="会话1", 留言="事后补记", 存储目录=self.存储目录)
        self.assertFalse(第三条.成功)
        self.assertEqual(第三条.错误码, "租约不存在")

    def test_留言参数不合法一律拒绝(self) -> None:
        租约id = 值(self.申请([文件1]))["租约id清单"][0]
        for 参数, 名 in (({"租约id": "", "作者": "会话1", "留言": "x"}, "租约id"),
                       ({"租约id": 租约id, "作者": "", "留言": "x"}, "作者"),
                       ({"租约id": 租约id, "作者": "会话1", "留言": "   "}, "留言")):
            结果 = 文件租约留言(存储目录=self.存储目录, **参数)
            self.assertFalse(结果.成功, 名)
            self.assertEqual(结果.错误码, "参数不合法")

    def test_查询含现场指纹读出内容是否变更(self) -> None:
        现场, _ = 计算内容指纹(仓库根, 文件1)
        self.申请带指纹(现场)
        查询 = 值(查询文件租约(修改路径=[文件1], 存储目录=self.存储目录, 含现场指纹=真))
        记录 = 查询["记录表"][0]
        self.assertEqual(记录["现场指纹"], 现场)
        self.assertEqual(记录["现场指纹一致"], 真)
        self.assertEqual(记录["内容是否变更"], 假)
        # 不带 含现场指纹 时不该多出这三个读数（参数要真起作用）
        查询2 = 值(查询文件租约(修改路径=[文件1], 存储目录=self.存储目录))
        self.assertNotIn("现场指纹", 查询2["记录表"][0])

    def test_批量字典写法与文本写法混投时未声明指纹即整体拒绝(self) -> None:
        """批量语义是**整体原子**：任一条指纹不符即整批拒绝（不留半批）。

        文本项不带声明指纹 ⇒ 校验指纹=真 时它「无可比」⇒ 视为不符 ⇒ 整批拒绝。
        要混投就必须**每条都带指纹**（字典写法），这正是华哥口述口径的直接结果。
        """
        现场, _ = 计算内容指纹(仓库根, 文件1)
        现场2, _ = 计算内容指纹(仓库根, 文件2)
        整体拒 = 申请文件租约(修改路径=[{"路径": 文件1, "指纹": 现场}, 文件2],
                          所有者="会话1", 任务="混投", 存储目录=self.存储目录,
                          校验指纹=真)
        self.assertFalse(整体拒.成功)
        self.assertEqual(整体拒.错误码, "内容已变更")
        self.assertIn(文件2, 整体拒.错误说明)
        # 每条都带指纹 → 整批成功
        全部带 = 申请文件租约(
            修改路径=[{"路径": 文件1, "指纹": 现场}, {"路径": 文件2, "指纹": 现场2}],
            所有者="会话1", 任务="全带指纹", 存储目录=self.存储目录, 校验指纹=真)
        self.assertTrue(全部带.成功, 全部带.错误说明)
        self.assertEqual(全部带.值["认领数"], 2)
        self.assertEqual(全部带.值["租约清单"][0]["指纹一致"], 真)


class 批量字典写法校验测试(文件租约测试基类):
    def test_字典项缺路径必须报错(self) -> None:
        结果 = 申请文件租约(修改路径=[{"指纹": "sha256:abc"}], 所有者="会话1",
                        任务="缺路径", 存储目录=self.存储目录)
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "参数不合法")
        self.assertIn("路径", 结果.错误说明)

    def test_非文本非字典项必须报错(self) -> None:
        结果 = 申请文件租约(修改路径=[123], 所有者="会话1", 任务="非法项",
                        存储目录=self.存储目录)
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "参数不合法")


if __name__ == "__main__":
    unittest.main(verbosity=2)
