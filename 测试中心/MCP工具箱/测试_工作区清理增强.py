"""工作区关闭前资源联动清理增强测试：真实 git 仓库与真实资源，禁止桩。

覆盖：关闭前联动清理登记资源（文件/子进程/端口）并移除 worktree、
无 work_id 时按工作区路径扫描定位清单、清理失败拒绝关闭并写结构化证据
（工程缓存/清理失败证据/{work_id}.json：时间/资源列表/失败原因）、
关闭前释放 ps 匹配工作区路径的残留子进程、登记资源 work_id 维度与清理幂等。
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

系统根 = Path(__file__).resolve().parents[2]
if str(系统根) not in sys.path:
    sys.path.insert(0, str(系统根))

from MCP工具箱.测试资源 import 清理资源, 登记资源
from MCP工具箱.工作区管理 import 创建工作区, 关闭工作区


def _运行(根目录: Path, 命令: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(命令, cwd=根目录, capture_output=True, text=True, check=False)


class 工作区清理增强测试(unittest.TestCase):
    def setUp(self) -> None:
        self._临时 = tempfile.TemporaryDirectory()
        根 = Path(self._临时.name)
        self.项目根 = 根 / "主仓库"
        self.工作区根 = 根 / "旁路"
        self.项目根.mkdir()
        self.工作区根.mkdir()
        初始化 = _运行(self.项目根, ["git", "init", "-b", "main"])
        self.assertEqual(初始化.returncode, 0, 初始化.stderr)
        _运行(self.项目根, ["git", "config", "user.name", "测试用户"])
        _运行(self.项目根, ["git", "config", "user.email", "测试@示例.本地"])
        (self.项目根 / "初始.txt").write_text("初始内容\n", encoding="utf-8")
        _运行(self.项目根, ["git", "add", "."])
        提交 = _运行(self.项目根, ["git", "commit", "-m", "初始提交"])
        self.assertEqual(提交.returncode, 0, 提交.stderr)

    def tearDown(self) -> None:
        self._临时.cleanup()

    def 创建真实工作区(self, 任务id: str) -> tuple[Path, Path]:
        结果 = 创建工作区(self.项目根, self.工作区根, 任务id=任务id)
        self.assertTrue(结果["成功"], 结果)
        工作区 = Path(结果["路径"])
        清单 = self.项目根 / "工程缓存" / "测试资源清单" / f"{任务id}.jsonl"
        return 工作区, 清单

    def test_关闭前联动清理登记资源并移除工作区(self) -> None:
        工作区, 清单 = self.创建真实工作区("任务甲")
        临时文件 = 工作区 / "临时文件.txt"
        临时文件.write_text("临时内容", encoding="utf-8")
        登记资源(清单, 资源路径=str(临时文件), 临时根目录=工作区, work_id="任务甲")
        子进程 = subprocess.Popen(["sleep", "300"], start_new_session=True)
        try:
            登记资源(清单, 资源路径=f"子进程:{子进程.pid}", 临时根目录=工作区,
                      资源类型="子进程", 附加信息={"pid": 子进程.pid}, work_id="任务甲")
            监听 = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            监听.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            监听.bind(("127.0.0.1", 0))
            监听.listen(1)
            端口号 = int(监听.getsockname()[1])
            try:
                登记资源(清单, 资源路径=f"端口:{端口号}", 临时根目录=工作区,
                          资源类型="端口", 附加信息={"端口": 端口号, "占用pid": os.getpid()},
                          work_id="任务甲")
                监听.close()
                结果 = 关闭工作区(self.项目根, str(工作区), work_id="任务甲")
                self.assertTrue(结果["成功"], 结果)
                self.assertFalse(工作区.exists(), "worktree 必须被移除")
                self.assertFalse(临时文件.exists(), "登记文件必须被清理")
                self.assertGreaterEqual(int(结果.get("清理数", 0)), 3)
                self.assertFalse(清单.exists(), "登记清单必须被删除")
                截止 = time.monotonic() + 5
                while 子进程.poll() is None and time.monotonic() < 截止:
                    time.sleep(0.05)
                self.assertIsNotNone(子进程.poll(), "登记子进程必须被终止")
                检查 = subprocess.run(["ps", "-p", str(子进程.pid)],
                                      capture_output=True, text=True)
                self.assertNotEqual(检查.returncode, 0, "ps 必须报告子进程不存在")
                验证 = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                try:
                    验证.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                    验证.bind(("127.0.0.1", 端口号))
                    验证.listen(1)
                finally:
                    验证.close()
                证据目录 = self.项目根 / "工程缓存" / "清理失败证据"
                self.assertFalse((证据目录 / "任务甲.json").exists(),
                                 "成功场景不得写失败证据")
            finally:
                监听.close()
        finally:
            if 子进程.poll() is None:
                子进程.kill()
                子进程.wait()

    def test_无work_id按工作区路径扫描定位清单(self) -> None:
        工作区, 清单 = self.创建真实工作区("任务乙")
        扫描文件 = 工作区 / "扫描文件.txt"
        扫描文件.write_text("内容", encoding="utf-8")
        登记资源(清单, 资源路径=str(扫描文件), 临时根目录=工作区)
        结果 = 关闭工作区(self.项目根, str(工作区))
        self.assertTrue(结果["成功"], 结果)
        self.assertFalse(扫描文件.exists(), "扫描定位的清单资源必须被清理")
        self.assertFalse(工作区.exists(), "worktree 必须被移除")
        self.assertFalse(清单.exists(), "登记清单必须被删除")

    def test_清理失败拒绝关闭并写结构化证据(self) -> None:
        工作区, 清单 = self.创建真实工作区("任务丙")
        只读目录 = 工作区 / "只读目录"
        只读目录.mkdir()
        占位 = 只读目录 / "占位.txt"
        占位.write_text("占位", encoding="utf-8")
        os.chmod(占位, 0o000)
        os.chmod(只读目录, 0o000)
        try:
            os.chflags(占位, stat.UF_IMMUTABLE)
        except (AttributeError, OSError):
            pass
        登记资源(清单, 资源路径=str(只读目录), 临时根目录=工作区,
                  资源类型="目录", work_id="任务丙")
        结果 = 关闭工作区(self.项目根, str(工作区), work_id="任务丙")
        self.assertFalse(结果["成功"], "清理失败必须返回失败（非零语义）")
        self.assertEqual(结果["错误码"], "WORKSPACE_CLEANUP_FAILED")
        self.assertTrue(结果["失败表"], "失败表必须非空")
        self.assertEqual(结果["失败表"][0]["类型"], "目录")
        证据路径 = Path(str(结果["证据路径"]))
        self.assertTrue(证据路径.is_file(), f"缺少结构化证据：{证据路径}")
        self.assertEqual(证据路径.name, "任务丙.json", "证据必须按 work_id 命名")
        证据 = json.loads(证据路径.read_text(encoding="utf-8"))
        self.assertEqual(证据["运行id"], "任务丙")
        self.assertTrue(证据["时间"], "证据必须含时间")
        self.assertTrue(证据["失败原因"], "证据必须含失败原因")
        self.assertTrue(证据["资源列表"], "证据必须含资源列表")
        self.assertEqual(证据["资源列表"][0]["类型"], "目录")
        self.assertTrue(证据["资源列表"][0]["原因"], "资源列表项必须含失败原因")
        self.assertTrue(工作区.exists(), "清理失败必须保留现场，不删除工作区")
        self._恢复删除权限(工作区)
        shutil.rmtree(工作区, ignore_errors=True)
        证据路径.unlink(missing_ok=True)
        self.assertFalse(证据路径.exists(), "测试自身清场")

    def test_关闭前释放匹配工作区路径的残留子进程(self) -> None:
        工作区, 清单 = self.创建真实工作区("任务丁")
        残留 = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(60)", str(工作区)],
            start_new_session=True,
        )
        try:
            结果 = 关闭工作区(self.项目根, str(工作区), work_id="任务丁")
            self.assertTrue(结果["成功"], 结果)
            截止 = time.monotonic() + 5
            while 残留.poll() is None and time.monotonic() < 截止:
                time.sleep(0.05)
            self.assertIsNotNone(残留.poll(), "ps 匹配工作区路径的残留进程必须被释放")
            self.assertFalse(工作区.exists(), "worktree 必须被移除")
        finally:
            if 残留.poll() is None:
                残留.kill()
                残留.wait()

    def test_登记资源work_id维度与清理幂等(self) -> None:
        工作区, 清单 = self.创建真实工作区("任务戊")
        幂等文件 = 工作区 / "幂等.txt"
        幂等文件.write_text("内容", encoding="utf-8")
        登记资源(清单, 资源路径=str(幂等文件), 临时根目录=工作区, work_id="任务戊")
        记录 = json.loads(清单.read_text(encoding="utf-8").splitlines()[0])
        self.assertEqual(记录["work_id"], "任务戊", "登记记录必须携带 work_id 维度")
        第一次 = 关闭工作区(self.项目根, str(工作区), work_id="任务戊")
        self.assertTrue(第一次["成功"], 第一次)
        self.assertFalse(工作区.exists(), "worktree 必须被移除")
        self.assertFalse(清单.exists(), "清单关闭后必须删除")
        幂等清理 = 清理资源(
            清单, 临时根目录=工作区,
            证据目录=self.项目根 / "工程缓存" / "清理失败证据", work_id="任务戊",
        )
        self.assertTrue(幂等清理["成功"], "清单已删除后重复清理必须幂等成功")
        证据目录 = self.项目根 / "工程缓存" / "清理失败证据"
        self.assertFalse((证据目录 / "任务戊.json").exists(),
                         "成功场景不得写失败证据")

    @staticmethod
    def _恢复删除权限(根: Path) -> None:
        """清除不可变标记并恢复权限，避免测试留下永久污染。"""
        if not 根.exists():
            return
        候选 = [根]
        候选.extend(根.glob("只读目录/*"))
        候选.append(根 / "只读目录")
        for 文件 in 候选:
            try:
                os.chflags(文件, 0)
            except (AttributeError, OSError):
                pass
            try:
                os.chmod(文件, 0o755)
            except OSError:
                pass


if __name__ == "__main__":
    unittest.main()
