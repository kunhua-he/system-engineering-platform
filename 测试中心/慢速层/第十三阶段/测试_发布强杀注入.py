"""第十三阶段：发布阶段真实强杀注入测试。

真实子进程（独立进程组，start_new_session）执行发布操作（登记期望→灰度→
激活，与 统一入口._签名发布 第 4 步同构），父进程在精确时刻真实 kill -9：

- 场景1 激活前强杀（状态=准备，指针未切）→ 重启进程调 恢复未完成发布()
  → 明确回滚，指针保持旧版（版本/令牌不变）；
- 场景2 激活后强杀（指针已切，状态未完成）→ 重启进程调 恢复未完成发布()
  → 幂等完成新版（版本/令牌单调递增且不再二次递增）；
- 场景3 重复恢复幂等：回滚与完成两类落点二次恢复均为空且状态逐字段不变。

恢复全部通过正式入口（恢复未完成发布/对账），断言不允许半激活：
指针要么明确旧版要么明确新版，发布状态明确完成或已回滚且与指针一致。
强杀注入辅助模块：平台控制面/提供者/发布强杀注入.py（真实写入提交后才
暂停，不改变任何状态语义）。
"""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

系统根 = Path(__file__).resolve().parents[3]
if str(系统根) not in sys.path:
    sys.path.insert(0, str(系统根))

# 按文件路径加载被测辅助模块（阶段惯例：不依赖共享 提供者/__init__.py 当前导入链）
_规格 = importlib.util.spec_from_file_location(
    "发布强杀注入被测", str(系统根 / "平台控制面" / "提供者" / "发布强杀注入.py"))
_被测模块 = importlib.util.module_from_spec(_规格)
_规格.loader.exec_module(_被测模块)
平台状态 = _被测模块.平台状态
辅助脚本 = 系统根 / "平台控制面" / "提供者" / "发布强杀注入.py"

旧版摘要 = "旧版制品摘要-v1"
新版摘要 = "新版制品摘要-v2"
包id = "发布包"


def 子进程环境(存储目录, *, 模式, 注入点="无", 就绪文件=None, 版本="", 对账="") -> dict:
    环境 = dict(os.environ, 注入模式=模式, 注入存储目录=str(存储目录), 注入点=注入点,
                注入就绪文件=str(就绪文件) if 就绪文件 else "",
                注入包id=包id, 注入版本=版本, 注入对账=对账)
    环境.pop("PYTHONPATH", None)  # 验收约定：unset PYTHONPATH
    return 环境


class 测试发布强杀注入(unittest.TestCase):
    """3 个真实场景：真实子进程执行发布 → 精确时刻 kill -9 → 重启恢复。"""

    def setUp(self):
        self.目录 = Path(tempfile.mkdtemp(prefix="发布强杀_"))
        self.注入进程 = None

    def tearDown(self):
        if self.注入进程 is not None and self.注入进程.poll() is None:
            try:
                os.killpg(self.注入进程.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass
            try:
                self.注入进程.wait(timeout=5)
            except Exception:
                pass
        shutil.rmtree(self.目录, ignore_errors=True)

    # ---- 子进程编排（全部真实 subprocess） ----
    def _跑子进程(self, *, 模式, 注入点="无", 就绪文件=None, 版本="", 对账="", 超时秒=30) -> dict:
        进程 = subprocess.Popen(
            [sys.executable, str(辅助脚本)],
            env=子进程环境(self.目录, 模式=模式, 注入点=注入点, 就绪文件=就绪文件,
                           版本=版本, 对账=对账),
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True)
        try:
            输出, 错误 = 进程.communicate(timeout=超时秒)
        except subprocess.TimeoutExpired:
            进程.kill()
            输出, 错误 = 进程.communicate()
        if 进程.returncode != 0:
            self.fail(f"子进程失败 rc={进程.returncode} 输出={输出} 错误={错误}")
        return json.loads(输出)

    def _初始发布(self) -> str:
        """真实子进程完成初始发布（旧版激活成功），返回初始发布id。"""
        数据 = self._跑子进程(模式="发布", 注入点="无", 版本=旧版摘要)
        self.assertTrue(数据["结果"]["成功"], 数据["结果"]["消息"])
        return 数据["结果"]["发布id"]

    def _注入发布(self, 注入点: str) -> None:
        """真实子进程执行新版发布，在注入点被父进程真实 kill -9。"""
        就绪文件 = self.目录 / "就绪.json"
        进程 = subprocess.Popen(
            [sys.executable, str(辅助脚本)],
            env=子进程环境(self.目录, 模式="发布", 注入点=注入点, 就绪文件=就绪文件,
                           版本=新版摘要),
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True)
        self.注入进程 = 进程
        就绪 = self._等待就绪(就绪文件, 进程)
        self.assertEqual(就绪["pid"], 进程.pid, "就绪信号必须来自本子进程")
        self.assertEqual(就绪["阶段"], 注入点, "就绪阶段必须等于注入点")
        # 精确时刻真实强杀：整个进程组 SIGKILL + wait 回收 + ps 验证消失
        os.killpg(进程.pid, signal.SIGKILL)
        进程.wait(timeout=10)
        self.assertEqual(进程.returncode, -9, "必须真实被 SIGKILL 杀死")
        残留 = subprocess.run(["ps", "-p", str(进程.pid), "-o", "pid="],
                              capture_output=True, text=True).stdout.strip()
        self.assertEqual(残留, "", f"PID {进程.pid} 应已从系统消失: {残留!r}")
        进程.communicate()

    def _等待就绪(self, 就绪文件: Path, 进程, 超时秒: float = 15.0) -> dict:
        截止 = time.monotonic() + 超时秒
        while time.monotonic() < 截止:
            if 就绪文件.exists():
                return json.loads(就绪文件.read_text(encoding="utf-8"))
            if 进程.poll() is not None:
                self.fail(f"注入子进程提前退出 rc={进程.returncode}")
            time.sleep(0.02)
        self.fail("等待注入就绪信号超时")

    def _恢复(self, 对账: str = "") -> dict:
        """重启进程：真实子进程调用正式恢复入口 恢复未完成发布()（可叠加 对账()）。"""
        return self._跑子进程(模式="恢复", 对账=对账)

    def _杀后快照(self) -> tuple[list, list]:
        """父进程直读被杀后的状态：指针必须已明确（旧版或新版），无半指针。"""
        状态 = 平台状态(self.目录)
        return 状态.查询记录("激活指针"), 状态.查询记录("发布")

    # ---- 半激活守护：指针要么旧版要么新版，发布状态明确且与指针一致 ----
    def _断言无半激活(self, 指针表: list, 发布记录表: list, 明确目标: str) -> None:
        self.assertEqual(len(指针表), 1, "必须恰好一个激活指针")
        指针 = 指针表[0]
        self.assertEqual(指针["状态"], "激活")
        self.assertIn(指针["目标"], (旧版摘要, 新版摘要), "指针必须落在明确旧版或新版")
        self.assertEqual(指针["目标"], 明确目标, "指针目标必须与场景期望一致")
        完成记录 = [r for r in 发布记录表
                   if r["状态"] == "完成" and r["激活指针"] == 指针["目标"]]
        self.assertTrue(完成记录,
                        "半激活：指针指向该目标但无对应完成发布记录")
        for 记录 in 发布记录表:
            if 记录["状态"] == "已回滚" and 记录["激活指针"] == 指针["目标"]:
                self.fail(f"半激活：已回滚记录 {记录['发布id']} 的激活目标与激活指针一致")
        self.assertEqual([r for r in 发布记录表 if r["状态"] in ("准备", "灰度")], [],
                         "恢复后不允许残留未完成发布")

    # ---- 场景 ----
    def test_场景1_激活前强杀恢复回滚到明确旧版(self):
        """新版激活到'准备'（指针未切）被 kill -9 → 恢复回滚，旧版指针原样。"""
        初始id = self._初始发布()
        self._注入发布("准备后")
        # 杀后：指针必须仍明确指向旧版（从未切换），发布状态=准备（未完成）
        指针表, 记录表 = self._杀后快照()
        self.assertEqual(指针表[0]["目标"], 旧版摘要, "激活前强杀不得切换指针")
        self.assertEqual(指针表[0]["版本"], 1, "激活前强杀不得递增版本")
        self.assertEqual(指针表[0]["栅栏令牌"], 1, "激活前强杀不得递增令牌")
        新记录 = [r for r in 记录表 if r["发布id"] != 初始id][0]
        self.assertEqual(新记录["状态"], "准备", "杀后发布必须处于未完成状态")
        self.assertEqual(新记录["激活指针"], "", "指针未切前不得落账激活目标")
        # 重启：正式恢复入口 → 明确回滚，对账无修正
        恢复 = self._恢复(对账="是")
        self.assertEqual(恢复["恢复表"], [f"{新记录['发布id']}:回滚"],
                         f"激活前强杀必须回滚: {恢复['恢复表']}")
        self.assertEqual(恢复["对账表"], [], f"对账不应有修正: {恢复['对账表']}")
        # 落点：指针仍是明确旧版（版本/令牌不变），新发布已回滚，无半激活
        self._断言无半激活(恢复["指针表"], 恢复["发布记录表"], 旧版摘要)
        self.assertEqual(恢复["指针表"][0]["版本"], 1, "回滚后版本必须仍为 1")
        self.assertEqual(恢复["指针表"][0]["栅栏令牌"], 1, "回滚后令牌必须仍为 1")
        已回滚 = [r for r in 恢复["发布记录表"] if r["状态"] == "已回滚"]
        self.assertEqual(len(已回滚), 1, "必须恰好一条已回滚记录")
        self.assertEqual(已回滚[0]["回滚事务"], json.dumps({"恢复回滚": True}))

    def test_场景2_激活后强杀恢复幂等完成新版(self):
        """新版指针已切（状态未完成）被 kill -9 → 恢复幂等完成，明确新版。"""
        初始id = self._初始发布()
        self._注入发布("切换后")
        # 杀后：指针已明确切到新版（CAS 已提交），发布状态=准备（完成步未执行）
        指针表, 记录表 = self._杀后快照()
        self.assertEqual(指针表[0]["目标"], 新版摘要, "切换后指针必须已是新版")
        self.assertEqual(指针表[0]["版本"], 2, "版本必须单调递增")
        self.assertEqual(指针表[0]["栅栏令牌"], 2, "栅栏令牌必须单调递增")
        新记录 = [r for r in 记录表 if r["发布id"] != 初始id][0]
        self.assertEqual(新记录["状态"], "准备", "杀后发布必须处于未完成状态")
        self.assertEqual(新记录["激活指针"], 新版摘要, "激活目标必须已落账（持久意图）")
        # 重启：正式恢复入口（恢复未完成发布 + 对账）→ 幂等完成
        恢复 = self._恢复(对账="是")
        完成表 = [x for x in 恢复["恢复表"] if x.startswith(f"{新记录['发布id']}:完成")]
        self.assertEqual(len(完成表), 1, f"激活后强杀必须幂等完成: {恢复['恢复表']}")
        self._断言无半激活(恢复["指针表"], 恢复["发布记录表"], 新版摘要)
        新记录 = [r for r in 恢复["发布记录表"] if r["发布id"] != 初始id][0]
        self.assertEqual(新记录["状态"], "完成", "恢复后新发布必须完成")
        self.assertEqual(新记录["激活指针"], 新版摘要)
        # 幂等：恢复只补完成标记，不得重跑激活（版本/令牌保持 2 而非 3）
        self.assertEqual(恢复["指针表"][0]["版本"], 2, "恢复必须幂等，不得再次激活递增版本")
        self.assertEqual(恢复["指针表"][0]["栅栏令牌"], 2, "恢复必须幂等，不得再次激活递增令牌")
        # 对账（第二正式入口）：只可能修正历史完成记录，不得扰动恢复结果
        for 项 in 恢复["对账表"]:
            self.assertNotIn("缺指针", 项)
            self.assertNotIn("保留回滚", 项)
        self.assertTrue(恢复["对账表"], f"多发布历史下对账应报告历史修正: {恢复['对账表']}")
        self.assertEqual(恢复["指针表"][0]["目标"], 新版摘要, "对账后指针必须仍是新版")

    def test_场景3_重复恢复幂等(self):
        """回滚与完成两类落点：二次恢复均为空，且状态逐字段不变。"""
        # 3a 回滚幂等：激活前强杀 → 恢复回滚 → 再恢复为空且状态不变
        目录a = self.目录
        初始ida = self._跑子进程(模式="发布", 注入点="无", 版本=旧版摘要)["结果"]["发布id"]
        self._注入发布("准备后")
        恢复1 = self._恢复(对账="是")
        self.assertEqual(len(恢复1["恢复表"]), 1, f"必须恰好恢复一条: {恢复1['恢复表']}")
        self.assertTrue(恢复1["恢复表"][0].endswith(":回滚"), 恢复1["恢复表"])
        self.assertEqual(恢复1["对账表"], [], f"回滚场景对账应干净: {恢复1['对账表']}")
        恢复2 = self._恢复()
        self.assertEqual(恢复2["恢复表"], [], "二次恢复必须为空")
        self.assertEqual(恢复2["指针表"], 恢复1["指针表"], "二次恢复后指针必须逐字段不变")
        self.assertEqual(恢复2["发布记录表"], 恢复1["发布记录表"], "二次恢复后发布记录必须逐字段不变")
        self._断言无半激活(恢复2["指针表"], 恢复2["发布记录表"], 旧版摘要)
        shutil.rmtree(目录a, ignore_errors=True)

        # 3b 完成幂等：激活后强杀 → 恢复完成 → 再恢复为空且状态不变
        self.目录 = Path(tempfile.mkdtemp(prefix="发布强杀b_"))
        self.注入进程 = None
        try:
            初始idb = self._跑子进程(模式="发布", 注入点="无", 版本=旧版摘要)["结果"]["发布id"]
            self._注入发布("切换后")
            恢复b1 = self._恢复()
            self.assertTrue(any(":完成(" in x for x in 恢复b1["恢复表"]), 恢复b1["恢复表"])
            self._断言无半激活(恢复b1["指针表"], 恢复b1["发布记录表"], 新版摘要)
            恢复b2 = self._恢复()
            self.assertEqual(恢复b2["恢复表"], [], "二次恢复必须为空")
            self.assertEqual(恢复b2["指针表"], 恢复b1["指针表"], "二次恢复后指针必须逐字段不变")
            self.assertEqual(恢复b2["发布记录表"], 恢复b1["发布记录表"],
                             "二次恢复后发布记录必须逐字段不变")
            self.assertEqual(恢复b2["指针表"][0]["版本"], 2, "完成幂等不得递增版本")
            self.assertEqual(恢复b2["指针表"][0]["栅栏令牌"], 2, "完成幂等不得递增令牌")
            self.assertIn(初始idb, [r["发布id"] for r in 恢复b2["发布记录表"]])
        finally:
            shutil.rmtree(self.目录, ignore_errors=True)
            self.目录 = 目录a


if __name__ == "__main__":
    unittest.main(verbosity=2)
