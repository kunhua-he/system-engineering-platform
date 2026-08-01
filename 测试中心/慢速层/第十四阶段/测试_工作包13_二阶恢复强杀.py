"""第十四阶段工作包13：二阶恢复强杀测试（慢速层真实 kill -9）。

真实链路：一阶强杀（发布激活中途被杀，第十三阶段能力）留下未完成发布 →
真实子进程执行 发布管理.恢复未完成发布() 并在精确注入点（恢复动作提交
后、恢复证据写入前）被父进程真实 kill -9 → 主进程再次调用 恢复未完成
发布() 幂等完成恢复 → 再次调用结果稳定 → 证据链只新增恢复证据，恢复前
已有证据记录 内容/哈希 逐字节不变。

注入辅助模块：测试中心/辅助/灾难恢复审计/二阶恢复注入.py
生产校验模块：平台控制面/发布管理/二阶恢复.py
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

一阶脚本 = 系统根 / "平台控制面" / "提供者" / "发布强杀注入.py"
二阶脚本 = 系统根 / "测试中心" / "辅助" / "灾难恢复审计" / "二阶恢复注入.py"
二阶校验脚本 = 系统根 / "平台控制面" / "发布管理" / "二阶恢复.py"


def _加载(名称: str, 路径: Path):
    规格 = importlib.util.spec_from_file_location(名称, str(路径))
    模块 = importlib.util.module_from_spec(规格)
    规格.loader.exec_module(模块)
    return 模块


一阶注入 = _加载("一阶注入被测", 一阶脚本)
二阶校验 = _加载("二阶校验被测", 二阶校验脚本)
平台状态 = 一阶注入.平台状态
发布管理 = 一阶注入.发布管理

旧版摘要 = "旧版制品摘要-v1"
新版摘要 = "新版制品摘要-v2"
包id = "二阶恢复包"


def 子进程环境(存储目录, *, 模式, 注入点="无", 就绪文件=None, 版本="") -> dict:
    环境 = dict(os.environ, 注入模式=模式, 注入存储目录=str(存储目录), 注入点=注入点,
                注入就绪文件=str(就绪文件) if 就绪文件 else "",
                注入包id=包id, 注入版本=版本)
    环境.pop("PYTHONPATH", None)  # 验收约定：unset PYTHONPATH
    return 环境


class 测试二阶恢复强杀(unittest.TestCase):
    """真实场景：一阶强杀留未完成发布 → 恢复子进程在注入点被杀 → 幂等恢复。"""

    def setUp(self):
        self.目录 = Path(tempfile.mkdtemp(prefix="二阶恢复_"))
        self.进程 = None

    def tearDown(self):
        if self.进程 is not None and self.进程.poll() is None:
            try:
                os.killpg(self.进程.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass
            try:
                self.进程.wait(timeout=5)
            except Exception:
                pass
        shutil.rmtree(self.目录, ignore_errors=True)

    # ---- 子进程编排（全部真实 subprocess） ----
    def _跑子进程(self, *, 模式, 注入点="无", 就绪文件=None, 版本="") -> dict:
        进程 = subprocess.Popen([sys.executable, str(一阶脚本)],
                               env=子进程环境(self.目录, 模式=模式, 注入点=注入点,
                                              就绪文件=就绪文件, 版本=版本),
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               text=True, start_new_session=True)
        try:
            输出, 错误 = 进程.communicate(timeout=30)
        except subprocess.TimeoutExpired:
            进程.kill()
            输出, 错误 = 进程.communicate()
        if 进程.returncode != 0:
            self.fail(f"子进程失败 rc={进程.returncode} 输出={输出} 错误={错误}")
        return json.loads(输出)

    def _等待就绪(self, 就绪文件: Path, 进程, 超时秒: float = 15.0) -> dict:
        截止 = time.monotonic() + 超时秒
        while time.monotonic() < 截止:
            if 就绪文件.exists():
                return json.loads(就绪文件.read_text(encoding="utf-8"))
            if 进程.poll() is not None:
                self.fail(f"注入子进程提前退出 rc={进程.returncode}")
            time.sleep(0.02)
        self.fail("等待注入就绪信号超时")

    def _初始发布(self) -> str:
        """真实子进程完成初始发布（旧版激活成功），返回初始发布id。"""
        数据 = self._跑子进程(模式="发布", 注入点="无", 版本=旧版摘要)
        self.assertTrue(数据["结果"]["成功"], 数据["结果"]["消息"])
        return 数据["结果"]["发布id"]

    def _一阶强杀(self, 注入点: str) -> None:
        """真实子进程执行新版发布，在 准备后/切换后 被真实 kill -9（一阶强杀）。"""
        就绪文件 = self.目录 / "一阶就绪.json"
        进程 = subprocess.Popen([sys.executable, str(一阶脚本)],
                               env=子进程环境(self.目录, 模式="发布", 注入点=注入点,
                                              就绪文件=就绪文件, 版本=新版摘要),
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               text=True, start_new_session=True)
        就绪 = self._等待就绪(就绪文件, 进程)
        self.assertEqual(就绪["pid"], 进程.pid, "就绪信号必须来自本子进程")
        self.assertEqual(就绪["阶段"], 注入点, "一阶注入阶段必须等于注入点")
        os.killpg(进程.pid, signal.SIGKILL)
        进程.wait(timeout=10)
        self.assertEqual(进程.returncode, -9, "一阶注入子进程必须真实被 SIGKILL")
        进程.communicate()

    def _二阶恢复强杀(self) -> dict:
        """真实子进程执行 恢复未完成发布()，在注入点（恢复提交后）被真实 kill -9。"""
        就绪文件 = self.目录 / "二阶就绪.json"
        进程 = subprocess.Popen([sys.executable, str(二阶脚本)],
                               env=子进程环境(self.目录, 模式="恢复",
                                              注入点="恢复提交后", 就绪文件=就绪文件),
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               text=True, start_new_session=True)
        self.进程 = 进程
        就绪 = self._等待就绪(就绪文件, 进程)
        self.assertEqual(就绪["pid"], 进程.pid, "就绪信号必须来自恢复子进程")
        self.assertEqual(就绪["阶段"], "恢复提交后", "注入点必须为恢复动作提交后")
        # 精确时刻真实强杀：整个进程组 SIGKILL + wait 回收 + ps 验证消失
        os.killpg(进程.pid, signal.SIGKILL)
        进程.wait(timeout=10)
        self.assertEqual(进程.returncode, -9, "恢复子进程必须真实被 SIGKILL 杀死")
        残留 = subprocess.run(["ps", "-p", str(进程.pid), "-o", "pid="],
                              capture_output=True, text=True).stdout.strip()
        self.assertEqual(残留, "", f"PID {进程.pid} 应已从系统消失: {残留!r}")
        进程.communicate()
        return 就绪

    def _状态(self):
        return 平台状态(self.目录)

    def _造既有证据(self) -> dict:
        """恢复前已有证据（模拟历史发布证据），返回 {证据id: (内容, 哈希)} 快照。"""
        状态 = self._状态()
        状态.追加证据(类型="发布", 主题=包id, 内容={"步骤": "激活", "目标": 旧版摘要},
                      来源快照="初始发布")
        return {行["证据id"]: (行["内容"], 行["哈希"]) for 行 in 状态.查询证据(限制=1000)}

    def _无半激活断言(self, 状态) -> None:
        """指针要么明确旧版要么明确新版，发布状态明确且与指针一致。"""
        指针表 = 状态.查询记录("激活指针")
        发布记录表 = 状态.查询记录("发布")
        self.assertEqual(len(指针表), 1, "必须恰好一个激活指针")
        指针 = 指针表[0]
        self.assertEqual(指针["状态"], "激活")
        self.assertIn(指针["目标"], (旧版摘要, 新版摘要), "指针必须落在明确旧版或新版")
        self.assertEqual([r for r in 发布记录表 if r["状态"] in ("准备", "灰度")], [],
                         "恢复后不允许残留未完成发布")
        self.assertEqual(len([r for r in 发布记录表 if r["状态"] in ("完成", "已回滚")]),
                         len(发布记录表), "每条发布必须有明确落点（完成或已回滚）")

    # ---- 5 个真实测试 ----
    def test_1_恢复子进程在注入点被真实强杀(self):
        """真实子进程执行恢复，恢复动作提交后（证据写入前）被真实 kill -9。"""
        初始id = self._初始发布()
        self._一阶强杀("准备后")
        状态 = self._状态()
        新记录 = [r for r in 状态.查询记录("发布") if r["发布id"] != 初始id][0]
        self.assertEqual(新记录["状态"], "准备", "一阶强杀后发布必须处于未完成状态")
        self._造既有证据()
        就绪 = self._二阶恢复强杀()
        self.assertEqual(就绪["阶段"], "恢复提交后")
        # 被杀时恢复动作已真实提交（回滚），恢复证据未写入（注入点在证据写入前）
        状态 = self._状态()
        新记录 = [r for r in 状态.查询记录("发布") if r["发布id"] != 初始id][0]
        self.assertEqual(新记录["状态"], "已回滚", "恢复动作必须在被杀前已提交")
        self.assertEqual(新记录["回滚事务"], json.dumps({"恢复回滚": True}))
        指针 = 状态.读取记录("激活指针", "指针id", 包id)
        self.assertEqual(指针["目标"], 旧版摘要, "回滚场景指针必须仍是明确旧版")
        self.assertEqual(指针["版本"], 1, "回滚不得递增版本")
        证据表 = 状态.查询证据(限制=1000)
        self.assertEqual([行 for 行 in 证据表 if 行["类型"] == "恢复"], [],
                         "恢复证据不得在强杀前写入（注入点在证据写入前）")

    def test_2_强杀后再次恢复幂等完成且指针明确(self):
        """被强杀后主进程再次调用 恢复未完成发布()：幂等完成，指针明确。"""
        初始id = self._初始发布()
        self._一阶强杀("准备后")
        self._二阶恢复强杀()
        状态 = self._状态()
        新id = [r["发布id"] for r in 状态.查询记录("发布") if r["发布id"] != 初始id][0]
        发布 = 发布管理(状态)
        恢复表 = 发布.恢复未完成发布()
        self.assertEqual(恢复表, [], "恢复动作已提交，再次恢复必须幂等为空")
        指针 = 状态.读取记录("激活指针", "指针id", 包id)
        self.assertEqual(指针["目标"], 旧版摘要, "指针必须落在明确旧版")
        self.assertEqual(指针["版本"], 1, "幂等恢复不得递增版本")
        self.assertEqual(指针["栅栏令牌"], 1, "幂等恢复不得递增令牌")
        self._无半激活断言(状态)
        # 生产校验模块：完整校验链路（重复调用 恢复未完成发布()）
        结果 = 二阶校验.幂等恢复校验(状态, 新id, 新版摘要)
        self.assertTrue(结果["幂等"])
        self.assertEqual(结果["发布状态"], "已回滚")
        self.assertEqual(结果["指针目标"], 旧版摘要)
        self.assertEqual(结果["指针符合期望"], False, "回滚场景指针应为旧版而非新版")
        self.assertTrue(结果["原有证据未覆盖"])

    def test_3_证据链不覆盖只新增恢复证据(self):
        """恢复前已有证据 内容/哈希 逐字节不变，只是新增恢复证据。"""
        初始id = self._初始发布()
        self._一阶强杀("准备后")
        前快照 = self._造既有证据()
        self._二阶恢复强杀()
        状态 = self._状态()
        新id = [r["发布id"] for r in 状态.查询记录("发布") if r["发布id"] != 初始id][0]
        二阶校验.幂等恢复校验(状态, 新id, 新版摘要)
        后证据表 = 状态.查询证据(限制=1000)
        原证据 = [行 for 行 in 后证据表 if 行["证据id"] in 前快照]
        新增 = [行 for 行 in 后证据表 if 行["证据id"] not in 前快照]
        self.assertTrue(原证据, "必须存在恢复前证据")
        for 行 in 原证据:
            self.assertEqual((行["内容"], 行["哈希"]), 前快照[行["证据id"]],
                             f"恢复前证据被修改: {行['证据id']}")
        self.assertTrue(新增, "必须新增恢复证据")
        for 行 in 新增:
            self.assertEqual(行["类型"], "恢复", "新增证据必须是恢复证据")
            self.assertEqual(行["来源快照"], "二阶恢复强杀")
        self.assertEqual(len(新增), 1, "幂等校验只新增一条恢复证据")

    def test_4_连续两次恢复结果一致幂等(self):
        """强杀后连续两次调用 恢复未完成发布()：结果一致、状态逐字段不变。"""
        初始id = self._初始发布()
        self._一阶强杀("准备后")
        self._二阶恢复强杀()
        状态 = self._状态()
        发布 = 发布管理(状态)
        恢复1 = 发布.恢复未完成发布()
        指针1 = 状态.查询记录("激活指针")
        发布记录1 = 状态.查询记录("发布")
        恢复2 = 发布.恢复未完成发布()
        指针2 = 状态.查询记录("激活指针")
        发布记录2 = 状态.查询记录("发布")
        self.assertEqual(恢复1, 恢复2, "两次恢复结果必须一致")
        self.assertEqual(指针1, 指针2, "二次恢复后指针必须逐字段不变")
        self.assertEqual(发布记录1, 发布记录2, "二次恢复后发布记录必须逐字段不变")
        self._无半激活断言(状态)

    def test_5_恢复完成后发布状态明确完成或已回滚(self):
        """两个落点：准备后强杀→已回滚；切换后强杀→完成；均与指针一致。"""
        # 5a 回滚落点：激活前强杀 → 恢复为已回滚，指针明确旧版
        初始id = self._初始发布()
        self._一阶强杀("准备后")
        self._二阶恢复强杀()
        状态 = self._状态()
        新记录 = [r for r in 状态.查询记录("发布") if r["发布id"] != 初始id][0]
        self.assertEqual(新记录["状态"], "已回滚", "激活前强杀必须恢复为已回滚")
        self.assertEqual(状态.读取记录("激活指针", "指针id", 包id)["目标"], 旧版摘要)
        # 5b 完成落点：激活后强杀（指针已切新版）→ 恢复为完成，指针明确新版
        self.目录 = Path(tempfile.mkdtemp(prefix="二阶恢复b_"))
        self.进程 = None
        try:
            初始idb = self._初始发布()
            self._一阶强杀("切换后")
            self._二阶恢复强杀()
            状态b = self._状态()
            新记录b = [r for r in 状态b.查询记录("发布") if r["发布id"] != 初始idb][0]
            self.assertEqual(新记录b["状态"], "完成", "激活后强杀必须恢复为完成")
            指针b = 状态b.读取记录("激活指针", "指针id", 包id)
            self.assertEqual(指针b["目标"], 新版摘要, "激活后强杀指针必须为明确新版")
            self.assertEqual(指针b["版本"], 2, "激活后强杀版本必须单调递增")
            结果b = 二阶校验.幂等恢复校验(状态b, 新记录b["发布id"], 新版摘要)
            self.assertTrue(结果b["幂等"])
            self.assertEqual(结果b["发布状态"], "完成")
            self.assertEqual(结果b["指针符合期望"], True, "完成场景指针必须为期望新版")
            self._无半激活断言(状态b)
        finally:
            shutil.rmtree(self.目录, ignore_errors=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
