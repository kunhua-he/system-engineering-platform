"""第十三阶段：控制面停止与恢复对账测试（3 个真实场景，跨进程真实执行）。

场景一：发布激活后模拟控制面不可用——新独立进程不启动控制面服务、数据库
只读打开，从持久化激活指针读到已激活目标，已激活调用面继续工作。
场景二：控制面恢复后对账——真实制造期望/实际不一致（真实写入激活指针），
以实际为准修复期望状态（发布记录），不反向改写实际指针。
场景三：恢复证据不覆盖旧证据——恢复对账证据追加写，停机期间原始失败证据
保留完整，证据链（原始失败证据 → 恢复证据）齐全。
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

系统根 = Path(__file__).resolve().parents[3]
if str(系统根) not in sys.path:
    sys.path.insert(0, str(系统根))

from 平台控制面.平台状态 import 平台状态
from 平台控制面.发布管理 import 发布管理
from 平台控制面.提供者.控制面对账 import 对账并记录恢复证据, 只读激活指针

包id = "包_控制面对账"
激活目标 = "制品摘要_控制面对账_2.0"
紧急切换目标 = "制品摘要_控制面对账_2.1"


def 运行独立进程(脚本: str) -> dict:
    """新独立进程执行脚本（控制面不可用/恢复的真实进程边界）。

    环境去除 PYTHONPATH（与验收命令一致），工作目录为系统根；
    返回脚本最后一行 JSON。
    """
    环境 = dict(os.environ)
    环境.pop("PYTHONPATH", None)
    结果 = subprocess.run(
        ["python3.14", "-c", 脚本], cwd=str(系统根), env=环境,
        capture_output=True, text=True, timeout=120)
    if 结果.returncode != 0:
        raise AssertionError(f"独立进程失败: {结果.stderr[-800:] or 结果.stdout[-800:]}")
    return json.loads(结果.stdout.strip().splitlines()[-1])


class Test控制面对账(unittest.TestCase):
    """控制面停止与恢复对账：3 个真实场景。"""

    def setUp(self):
        self.目录 = Path(tempfile.mkdtemp(prefix="控制面对账测试_"))
        self.状态 = 平台状态(self.目录, 项目id="控制面对账测试")
        self.发布 = 发布管理(self.状态)
        # 真实发布激活：登记期望版本 → 激活（激活指针持久化写入）
        self.发布id = self.发布.登记期望版本(包id=包id, 期望版本="2.0")
        成功, 消息 = self.发布.激活(发布id=self.发布id, 目标=激活目标)
        self.assertTrue(成功, 消息)
        # 发布激活证据（证据链起点）
        self.状态.追加证据(类型="发布", 主题=包id,
                          内容={"步骤": "激活", "制品摘要": 激活目标},
                          调用者="发布测试", 角色="发布者", 结果="发布")

    def tearDown(self):
        self.状态.关闭()
        shutil.rmtree(self.目录, ignore_errors=True)

    # ---- 场景一：控制面不可用，调用面从持久化激活指针继续 ----
    def test_场景一_控制面不可用时调用面只读持久化激活指针继续(self):
        """新独立进程（不启动控制面服务、只读打开数据库）读到已激活目标。"""
        脚本 = (
            "import json, sys\n"
            f"sys.path.insert(0, {json.dumps(str(系统根))})\n"
            "from 平台控制面.提供者.控制面对账 import 只读激活指针\n"
            f"指针 = 只读激活指针({json.dumps(str(self.目录))}, {json.dumps(包id)})\n"
            "print(json.dumps(指针, ensure_ascii=False))\n"
        )
        指针 = 运行独立进程(脚本)
        self.assertEqual(指针["目标"], 激活目标,
                         "控制面不可用时调用面必须从持久化激活指针读到已激活目标")
        self.assertEqual(指针["状态"], "激活")
        self.assertEqual(指针["版本"], 1)
        self.assertEqual(指针["栅栏令牌"], 1)
        # 控制面不可用期间的调用面降级证据（原始失败证据）
        self.状态.追加证据(类型="控制面不可用", 主题=包id,
                          内容={"阶段": "停机", "已激活目标": 激活目标,
                                "调用面": "从持久化激活指针继续"},
                          调用者="调用面", 角色="普通用户", 结果="降级")
        # 持久化激活指针未被控制面不可用影响
        self.assertEqual(self.发布.当前激活(包id)["目标"], 激活目标)

    # ---- 场景二：控制面恢复后对账，以实际为准修复期望状态 ----
    def test_场景二_控制面恢复对账以实际为准修复期望状态(self):
        """真实制造不一致（真实写入激活指针）→ 恢复后对账 → 以实际为准修复。"""
        # 控制面不可用期间实际状态被真实切换（紧急切换：CAS 真实写入）
        成功 = self.状态.条件更新(
            "激活指针", {"目标": 紧急切换目标, "版本": 2, "栅栏令牌": 2},
            "指针id=? AND 版本=? AND 栅栏令牌=?", (包id, 1, 1))
        self.assertTrue(成功, "真实写入制造不一致：激活指针紧急切换")
        发布记录 = self.状态.读取记录("发布", "发布id", self.发布id)
        self.assertEqual(发布记录["激活指针"], 激活目标, "期望状态仍为旧目标（不一致已制造）")
        指针 = self.状态.读取记录("激活指针", "指针id", 包id)
        self.assertEqual(指针["目标"], 紧急切换目标, "实际状态已切换（不一致已制造）")

        # 控制面恢复：新独立进程加载持久化状态 → 对账（以实际为准修复）
        脚本 = (
            "import json, sys\n"
            f"sys.path.insert(0, {json.dumps(str(系统根))})\n"
            "from 平台控制面.平台状态 import 平台状态\n"
            "from 平台控制面.发布管理 import 发布管理\n"
            "from 平台控制面.提供者.控制面对账 import 对账并记录恢复证据\n"
            f"状态 = 平台状态({json.dumps(str(self.目录))}, 项目id='控制面对账测试')\n"
            "发布 = 发布管理(状态)\n"
            "对账表, 证据id = 对账并记录恢复证据(状态, 发布)\n"
            "print(json.dumps({'对账表': 对账表, '证据id': 证据id}, ensure_ascii=False))\n"
            "状态.关闭()\n"
        )
        结果 = 运行独立进程(脚本)
        self.assertTrue(any(项.startswith("修正:") for 项 in 结果["对账表"]),
                        结果["对账表"])
        # 以实际为准修复：期望状态（发布记录）已修复为实际目标
        发布记录 = self.状态.读取记录("发布", "发布id", self.发布id)
        self.assertEqual(发布记录["激活指针"], 紧急切换目标,
                         "对账后期望状态以实际激活指针为准修复")
        # 实际指针未被反向改写（以实际为准）
        指针 = self.状态.读取记录("激活指针", "指针id", 包id)
        self.assertEqual(指针["目标"], 紧急切换目标)
        self.assertEqual(指针["版本"], 2, "实际指针版本不被对账改写")
        self.assertEqual(指针["栅栏令牌"], 2, "实际指针栅栏令牌不被对账改写")

    # ---- 场景三：恢复证据追加写，不覆盖旧证据 ----
    def test_场景三_恢复证据追加写不覆盖旧证据(self):
        """恢复对账证据追加写：原始失败证据保留完整，证据链齐全。"""
        # 控制面不可用期间的原始失败证据（调用面降级记录）
        原始证据id = self.状态.追加证据(
            类型="控制面不可用", 主题=包id,
            内容={"阶段": "停机", "已激活目标": 激活目标,
                  "调用面": "从持久化激活指针继续"},
            调用者="调用面", 角色="普通用户", 结果="降级")
        原始证据表 = self.状态.查询证据(类型="控制面不可用", 主题=包id, 限制=10)
        self.assertEqual(len(原始证据表), 1)
        原始内容快照 = json.dumps(原始证据表[0], ensure_ascii=False, sort_keys=True)

        # 制造不一致（真实写入）后恢复：对账并记录恢复证据（引用原始失败证据）
        成功 = self.状态.条件更新(
            "激活指针", {"目标": 紧急切换目标, "版本": 2, "栅栏令牌": 2},
            "指针id=? AND 版本=? AND 栅栏令牌=?", (包id, 1, 1))
        self.assertTrue(成功)
        脚本 = (
            "import json, sys\n"
            f"sys.path.insert(0, {json.dumps(str(系统根))})\n"
            "from 平台控制面.平台状态 import 平台状态\n"
            "from 平台控制面.发布管理 import 发布管理\n"
            "from 平台控制面.提供者.控制面对账 import 对账并记录恢复证据\n"
            f"状态 = 平台状态({json.dumps(str(self.目录))}, 项目id='控制面对账测试')\n"
            "发布 = 发布管理(状态)\n"
            f"对账表, 证据id = 对账并记录恢复证据(状态, 发布, 原始证据id={json.dumps(原始证据id)})\n"
            "print(json.dumps({'对账表': 对账表, '证据id': 证据id}, ensure_ascii=False))\n"
            "状态.关闭()\n"
        )
        结果 = 运行独立进程(脚本)
        self.assertTrue(any(项.startswith("修正:") for 项 in 结果["对账表"]), 结果["对账表"])
        恢复证据id = 结果["证据id"]
        self.assertNotEqual(恢复证据id, 原始证据id,
                            "恢复证据必须是追加写的新记录，不得复用旧证据id")

        # 恢复证据已追加，且引用原始失败证据（证据链）
        恢复证据表 = self.状态.查询证据(类型="恢复对账", 限制=10)
        self.assertTrue(any(项["证据id"] == 恢复证据id for 项 in 恢复证据表),
                        "恢复证据必须已写入证据账本")
        恢复 = next(项 for 项 in 恢复证据表 if 项["证据id"] == 恢复证据id)
        self.assertEqual(恢复["结果"], "已对账")
        self.assertEqual(恢复["内容"]["关联原始证据"], 原始证据id,
                         "证据链：恢复证据引用原始失败证据")

        # 原始失败证据未被覆盖：证据id 与内容完整保留（追加写）
        原始证据表2 = self.状态.查询证据(类型="控制面不可用", 主题=包id, 限制=10)
        self.assertEqual(len(原始证据表2), 1, "原始失败证据不得被覆盖或删除")
        self.assertEqual(json.dumps(原始证据表2[0], ensure_ascii=False, sort_keys=True),
                         原始内容快照, "原始失败证据内容完整保留")
        self.assertEqual(原始证据表2[0]["证据id"], 原始证据id)

        # 证据链完整：发布激活证据 + 原始失败证据 + 恢复证据 同时存在
        发布证据表 = self.状态.查询证据(类型="发布", 主题=包id, 限制=10)
        self.assertEqual(len(发布证据表), 1, "发布激活证据保留")
        self.assertEqual(len(恢复证据表), 1, "恢复证据存在")
        self.assertEqual(len(原始证据表2), 1, "原始失败证据存在")


if __name__ == "__main__":
    unittest.main()
