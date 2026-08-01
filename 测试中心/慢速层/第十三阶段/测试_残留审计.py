"""第十三阶段：发布门禁、四示例与残留资源综合审计（1 个综合场景）。

综合场景 = 基线快照 → 真实执行发布门禁（断言退出码 0 且「发布状态: 通过」）→
真实执行四个示例（适配层 / 前后端核心 / 真实浏览器 / 平台控制面，断言退出码 0
与关键输出）→ 回收示例遗留工作目录 → 残留核对：
  1. 无 python3.14 -S 子进程残留（本次运行新增为 0）
  2. 无 .临时_ / .安装临时_ 目录残留（本次运行新增为 0）
  3. 无 平台控制面示例 临时目录残留（回收后新增为 0）
  4. 无僵尸进程（本次运行新增为 0）
  5. 无监听端口残留（前后端/真实浏览器示例的本地网关端口已释放，
     python3.14 持有监听套接字新增为 0）
  6. 无 SQLite 连接残留（python3.14 持有 sqlite 文件的进程新增为 0）

残留核对采用「基线差值」口径：只判定本次审计运行新增的残留，不误伤
系统既有服务（如 WPS、业务嵌入服务）与并行会话的历史遗留。

递归防护：本场景真实执行发布门禁，而门禁内部会子进程再跑
测试中心/运行测试.py（其中包含本文件）——用环境变量标记嵌套实例，
嵌套实例只做轻量残留核对即通过，防止 门禁-测试 无限递归。
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

系统根 = Path(__file__).resolve().parents[3]
if str(系统根) not in sys.path:
    sys.path.insert(0, str(系统根))

递归防护环境变量 = "系统级支持库_残留审计_递归防护"
平台控制面前缀 = "平台控制面示例_"


class Test发布门禁与四示例残留综合审计(unittest.TestCase):
    """1 个综合审计场景：发布门禁 + 四示例 + 六类残留核对，全过才算通过。"""

    最长门禁秒 = 300
    最长示例秒 = 120

    def _运行子进程(self, 命令: list[str], 超时秒: float,
                  环境: dict | None = None) -> tuple[int, str]:
        """真实执行子进程；unset PYTHONPATH；返回 退出码 + 输出。"""
        环境 = dict(os.environ) if 环境 is None else dict(环境)
        环境.pop("PYTHONPATH", None)  # 铁律：必须 unset，防 hermes venv 污染
        进程 = subprocess.run(
            命令, cwd=str(系统根), env=环境,
            capture_output=True, text=True, timeout=超时秒)
        输出 = (进程.stdout or "") + (进程.stderr or "")
        return 进程.returncode, 输出

    # ---------- 六类残留快照 ----------

    def _S进程快照(self) -> set[str]:
        """python3.14 且带 -S 独立参数的子进程 pid 集合（本项目子进程模式标记）。"""
        try:
            输出 = subprocess.run(
                ["ps", "-axo", "pid=,command="], capture_output=True,
                text=True, timeout=20).stdout or ""
        except Exception:
            return set()
        集合: set[str] = set()
        for 行 in 输出.splitlines():
            if "python3.14" in 行 and re.search(r"(^|\s)-S(\s|$)", 行):
                集合.add(行.split(None, 1)[0])
        return 集合

    def _僵尸快照(self) -> set[str]:
        """状态以 Z 开头的僵尸进程 pid 集合。"""
        try:
            输出 = subprocess.run(
                ["ps", "-axo", "pid=,stat=,command="], capture_output=True,
                text=True, timeout=20).stdout or ""
        except Exception:
            return set()
        return {行.split(None, 2)[0] for 行 in 输出.splitlines()
                if len(行.split(None, 2)) >= 2 and 行.split(None, 2)[1].startswith("Z")}

    def _监听端口快照(self) -> tuple[set[str], set[str]]:
        """(全部监听套接字, python3.14 持有的监听套接字) 名称集合（地址:端口）。"""
        try:
            输出 = subprocess.run(
                ["lsof", "-nP", "-iTCP", "-sTCP:LISTEN"], capture_output=True,
                text=True, timeout=30).stdout or ""
        except Exception:
            return set(), set()
        全部: set[str] = set()
        项目进程: set[str] = set()
        for 行 in 输出.splitlines()[1:]:
            列 = 行.split()
            if len(列) >= 9:
                名称 = 列[8].replace("(LISTEN)", "").strip()
                全部.add(名称)
                if 列[0].startswith("python3.14"):
                    项目进程.add(名称)
        return 全部, 项目进程

    def _SQLite持有快照(self) -> set[str]:
        """持有 sqlite/权威状态 数据库文件的进程 pid 集合。"""
        try:
            输出 = subprocess.run(
                ["lsof", "-nP"], capture_output=True, text=True, timeout=30).stdout or ""
        except Exception:
            return set()
        集合: set[str] = set()
        for 行 in 输出.splitlines()[1:]:
            if re.search(r"sqlite|权威状态", 行, re.IGNORECASE) and 行.split():
                集合.add(行.split()[0] + ":" + 行.split()[1])
        return 集合

    def _平台控制面目录快照(self) -> set[Path]:
        """系统临时目录下的 平台控制面示例_* 工作目录。"""
        return set(Path(tempfile.gettempdir()).glob(平台控制面前缀 + "*"))

    def _安装临时目录快照(self) -> set[Path]:
        """系统根下 .临时_* / .安装临时_* 原子安装残留目录。"""
        集合: set[Path] = set()
        for 模式 in (".临时_*", ".安装临时_*"):
            集合.update(系统根.rglob(模式))
        return 集合

    def _全部快照(self) -> dict:
        return {
            "S进程": self._S进程快照(),
            "僵尸": self._僵尸快照(),
            "监听": self._监听端口快照()[1],
            "SQLite": self._SQLite持有快照(),
            "平台目录": self._平台控制面目录快照(),
            "安装临时": self._安装临时目录快照(),
        }

    def _清理平台目录新增(self, 基线: dict) -> int:
        """回收 平台控制面示例 遗留工作目录中不属于基线的新增项。"""
        回收数 = 0
        for 目录 in self._平台控制面目录快照() - 基线["平台目录"]:
            shutil.rmtree(目录, ignore_errors=True)
            回收数 += 1
        return 回收数

    def _断言无新增残留(self, 基线: dict, 阶段: str) -> None:
        当前 = self._全部快照()
        for 类别, 说明 in (
                ("S进程", "python3.14 -S 子进程"),
                ("僵尸", "僵尸进程"),
                ("监听", "监听端口"),
                ("SQLite", "SQLite 连接持有"),
                ("安装临时", ".临时_/ .安装临时_ 目录"),
                ("平台目录", "平台控制面示例 临时目录")):
            新增 = 当前[类别] - 基线[类别]
            self.assertEqual(新增, set(),
                             f"[{阶段}] 新增{说明}残留: {新增}")

    def test_发布门禁四示例与残留资源综合审计(self):
        """综合场景：真实执行门禁+四示例，六类残留零新增。"""
        if os.environ.get(递归防护环境变量) == "1":
            # 嵌套实例：门禁内部的 运行测试.py 已在执行本场景的完整链路，
            # 此处只做轻量残留核对（基线=此刻，前后无运行 → 必须零新增）
            基线 = self._全部快照()
            self._断言无新增残留(基线, "嵌套轻量")
            return
        # 1) 基线快照（只判定本次运行新增的残留）
        基线 = self._全部快照()
        门禁前监听全部 = self._监听端口快照()[0]

        # 2) 发布门禁：真实执行，断言 退出码 0 且 发布状态: 通过
        门禁环境 = dict(os.environ)
        门禁环境[递归防护环境变量] = "1"
        门禁退出码, 门禁输出 = self._运行子进程(
            [sys.executable, "开发工具/发布门禁/运行发布门禁.py"], self.最长门禁秒, 门禁环境)
        self.assertEqual(门禁退出码, 0,
                         f"发布门禁退出码非 0，输出尾部: {门禁输出[-800:]}")
        self.assertIn("发布状态: 通过", 门禁输出,
                      f"发布状态未通过，输出尾部: {门禁输出[-800:]}")
        # 门禁内部会跑 运行测试.py（含 消费者契约 的 平台控制面示例 回归，
        # 该示例按设计不清理自己的工作目录）→ 回收本次门禁运行新增的遗留目录
        回收数 = self._清理平台目录新增(基线)
        self._断言无新增残留(基线, "门禁后")

        # 3) 四个示例：真实执行，断言 退出码 0 与关键输出
        示例表 = [
            ("适配层示例", "示例项目/适配层示例/运行入口/运行.py",
             ["适配层示例运行成功"]),
            ("前后端核心示例", "示例项目/前后端核心示例/运行示例.py",
             ["前后端核心示例", "本地网关与后端核心已优雅关闭"]),
            ("真实浏览器交互示例", "示例项目/真实浏览器交互示例/运行示例.py",
             ["真实浏览器交互示例", "后端核心、普通网关与流式网关已优雅关闭"]),
            ("平台控制面示例", "示例项目/平台控制面示例/运行示例.py",
             ["平台控制面完整闭环示例通过 ✓"]),
        ]
        示例输出表: dict[str, str] = {}
        for 名称, 入口, 关键输出 in 示例表:
            退出码, 输出 = self._运行子进程(
                [sys.executable, 入口], self.最长示例秒)
            示例输出表[名称] = 输出
            self.assertEqual(退出码, 0,
                             f"{名称} 退出码非 0，输出尾部: {输出[-800:]}")
            for 模式 in 关键输出:
                self.assertIn(模式, 输出,
                              f"{名称} 缺少关键输出「{模式}」，输出尾部: {输出[-800:]}")
        # 4) 回收平台控制面示例 遗留工作目录（示例本身不清理，审计负责回收）
        匹配 = re.search(r"工作目录:\s*(\S+)", 示例输出表["平台控制面示例"])
        if 匹配:
            shutil.rmtree(Path(匹配.group(1)), ignore_errors=True)
            回收数 += 1
        回收数 += self._清理平台目录新增(基线)

        # 5) 终态核对：六类残留零新增；监听端口确认已释放
        self._断言无新增残留(基线, "终态")
        终态监听全部 = self._监听端口快照()[0]
        新增监听 = 终态监听全部 - 门禁前监听全部
        print(f"审计信息: 门禁前后监听端口全集差集={sorted(新增监听)}"
              f"（仅 python3.14 持有判定残留，全量差集仅作披露）")
        print(f"审计信息: 平台控制面示例 遗留工作目录回收数={回收数}，"
              f"门禁+四示例全部真实执行通过")


if __name__ == "__main__":
    unittest.main(verbosity=2)
