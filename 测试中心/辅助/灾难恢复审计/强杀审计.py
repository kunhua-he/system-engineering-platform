"""工作包19 恢复中强杀审计：真实子进程在恢复关键点被 kill -9，验证幂等恢复。

真实链路（复用工作包13 注入辅助）：初始发布 → 一阶强杀（发布激活中途被杀）
留下未完成发布 → 真实子进程执行 恢复未完成发布() 并在注入点（恢复动作提交
后、恢复证据写入前）被父进程真实 kill -9 → 再次恢复必须幂等、无半状态。
"""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

系统根 = Path(__file__).resolve().parents[3]
一阶强杀脚本 = 系统根 / "平台控制面" / "提供者" / "发布强杀注入.py"
二阶恢复脚本 = Path(__file__).resolve().parent / "二阶恢复注入.py"

包id = "审计包19"
旧版摘要 = "旧版摘要-审计19"
新版摘要 = "新版摘要-审计19"


def 子进程环境(存储目录: Path, *, 模式: str, 注入点: str = "无",
               就绪文件: Path | None = None, 版本: str = "") -> dict:
    """子进程环境变量；按验收约定移除 PYTHONPATH。"""
    环境 = dict(os.environ, 注入模式=模式, 注入存储目录=str(存储目录), 注入点=注入点,
                注入就绪文件=str(就绪文件) if 就绪文件 else "",
                注入包id=包id, 注入版本=版本)
    环境.pop("PYTHONPATH", None)
    return 环境


class 强杀攻击审计:
    """真实编排：初始发布 → 一阶强杀 → 恢复子进程注入点强杀 → 幂等恢复。"""

    def __init__(self, 临时根: Path) -> None:
        self.临时根 = Path(临时根)
        self.进程 = None

    def 清理残留(self) -> None:
        if self.进程 is not None and self.进程.poll() is None:
            try:
                os.killpg(self.进程.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass
            try:
                self.进程.wait(timeout=5)
            except Exception:
                pass

    def _等待就绪(self, 就绪文件: Path, 进程) -> dict:
        截止 = time.monotonic() + 15
        while time.monotonic() < 截止:
            if 就绪文件.exists():
                return json.loads(就绪文件.read_text(encoding="utf-8"))
            if 进程.poll() is not None:
                raise AssertionError(f"注入子进程提前退出 rc={进程.returncode}")
            time.sleep(0.02)
        raise AssertionError("等待注入就绪信号超时")

    def _初始发布(self) -> None:
        执行 = subprocess.run([sys.executable, str(一阶强杀脚本)],
                              env=子进程环境(self.临时根, 模式="发布", 版本=旧版摘要),
                              capture_output=True, text=True, timeout=60)
        if 执行.returncode != 0:
            raise AssertionError(f"初始发布子进程失败: {执行.stdout}{执行.stderr}")
        数据 = json.loads(执行.stdout)
        if not 数据["结果"]["成功"]:
            raise AssertionError(f"初始发布未成功: {数据['结果']}")

    def _一阶强杀(self) -> None:
        """真实子进程发布新版，在 准备后 被真实 kill -9。"""
        就绪文件 = self.临时根 / "一阶就绪.json"
        进程 = subprocess.Popen([sys.executable, str(一阶强杀脚本)],
                                env=子进程环境(self.临时根, 模式="发布", 注入点="准备后",
                                                就绪文件=就绪文件, 版本=新版摘要),
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                text=True, start_new_session=True)
        就绪 = self._等待就绪(就绪文件, 进程)
        if 就绪["阶段"] != "准备后":
            raise AssertionError(f"一阶注入阶段异常: {就绪}")
        os.killpg(进程.pid, signal.SIGKILL)
        进程.wait(timeout=10)
        进程.communicate()
        if 进程.returncode != -9:
            raise AssertionError(f"一阶注入子进程必须真实被 SIGKILL: rc={进程.returncode}")

    def _恢复中强杀(self) -> None:
        """真实子进程执行恢复，恢复动作提交后（证据写入前）被真实 kill -9。"""
        就绪文件 = self.临时根 / "二阶就绪.json"
        进程 = subprocess.Popen([sys.executable, str(二阶恢复脚本)],
                                env=子进程环境(self.临时根, 模式="恢复",
                                                注入点="恢复提交后", 就绪文件=就绪文件),
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                text=True, start_new_session=True)
        self.进程 = 进程
        就绪 = self._等待就绪(就绪文件, 进程)
        if 就绪["阶段"] != "恢复提交后":
            raise AssertionError(f"二阶注入阶段异常: {就绪}")
        os.killpg(进程.pid, signal.SIGKILL)
        进程.wait(timeout=10)
        残留 = subprocess.run(["ps", "-p", str(进程.pid), "-o", "pid="],
                              capture_output=True, text=True).stdout.strip()
        进程.communicate()
        if 进程.returncode != -9:
            raise AssertionError(f"恢复子进程必须真实被 SIGKILL: rc={进程.returncode}")
        if 残留:
            raise AssertionError(f"强杀后进程残留: {残留!r}")

    def _幂等恢复(self) -> dict:
        """强杀后连续两次真实子进程恢复：结果稳定、无半状态、无恢复证据。"""
        恢复表 = []
        for _ in range(2):
            执行 = subprocess.run([sys.executable, str(一阶强杀脚本)],
                                  env=子进程环境(self.临时根, 模式="恢复"),
                                  capture_output=True, text=True, timeout=60)
            if 执行.returncode != 0:
                raise AssertionError(f"幂等恢复子进程失败: {执行.stdout}{执行.stderr}")
            恢复表.append(json.loads(执行.stdout))
        if 恢复表[0] != 恢复表[1]:
            raise AssertionError(f"两次恢复输出不一致（非幂等）: {恢复表[0]} vs {恢复表[1]}")
        if 恢复表[0]["恢复表"] != []:
            raise AssertionError(f"恢复动作已提交，再次恢复必须幂等为空: {恢复表[0]['恢复表']}")
        指针表 = 恢复表[0]["指针表"]
        if len(指针表) != 1 or 指针表[0]["状态"] != "激活":
            raise AssertionError(f"指针必须唯一且激活: {指针表}")
        if 指针表[0]["目标"] != 旧版摘要:
            raise AssertionError(f"回滚场景指针必须明确旧版: {指针表[0]}")
        半状态 = [行 for 行 in 恢复表[0]["发布记录表"]
                  if 行["状态"] not in ("完成", "已回滚")]
        if 半状态:
            raise AssertionError(f"恢复后存在半状态发布: {半状态}")
        return {"恢复表": 恢复表[0]["恢复表"], "幂等": True,
                "指针目标": 指针表[0]["目标"], "指针版本": 指针表[0]["版本"],
                "发布落点": {行["发布id"]: 行["状态"] for 行 in 恢复表[0]["发布记录表"]}}

    def 审计(self) -> dict:
        """完整注入链；任一环节失败如实记录为缺陷。"""
        try:
            self._初始发布()
            self._一阶强杀()
            self._恢复中强杀()
            详情 = self._幂等恢复()
        except AssertionError as 错误:
            return {"场景": "恢复中强杀", "防御有效": False, "缺陷": str(错误), "详情": {}}
        finally:
            self.清理残留()
        return {"场景": "恢复中强杀", "防御有效": True, "缺陷": "", "详情": 详情}
