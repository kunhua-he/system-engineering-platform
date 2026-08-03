"""系统提供者健康监督：周期真实探针 + 健康状态查询 + 诊断证据。

对 LibreOffice（soffice --version）、textutil（textutil -help + macOS 版本）
等系统提供者，按周期（默认 60 秒，可配置）复用 支持库/适配层/系统探针.py
的 检查系统工具 做独立子进程健康探针（超时 terminate→kill/退出码/版本/
标准错误摘要）。

失败语义：探针失败只把对应提供者标记为 健康=False + 错误码
「外部提供者不可用」，绝不 raise/崩溃，主进程继续运行；不把不可用
伪装成「环境未构建」。每次探针结果写入诊断证据
（工程缓存/启动监督器/健康证据.jsonl：
时间/提供者/健康/退出码/版本/标准错误摘要）。
"""
from __future__ import annotations

import json
import os
import platform
import shutil
import threading
import time
from pathlib import Path
from typing import Any, Callable

from 支持库.适配层.系统探针 import 检查系统工具, 探针结果

系统根 = Path(__file__).resolve().parents[1]
默认证据文件 = 系统根 / "工程缓存" / "启动监督器" / "健康证据.jsonl"
时间格式 = "%Y-%m-%d %H:%M:%S"
标准错误摘要最大长度 = 300


def 查找LibreOffice命令() -> list[str] | None:
    """soffice 可执行解析：环境变量 → PATH → macOS 固定安装路径。"""
    候选列表 = [
        os.getenv("LIBREOFFICE_BIN") or os.getenv("SOFFICE_BIN"),
        "soffice", "libreoffice",
        "/Applications/LibreOffice.app/Contents/MacOS/soffice",
    ]
    路径 = next((c for c in 候选列表 if c and shutil.which(c)), None)
    return [路径] if 路径 else None


def 查找textutil命令() -> list[str] | None:
    """textutil 可执行解析：PATH → macOS 系统固定路径。"""
    路径 = next((c for c in ("textutil", "/usr/bin/textutil")
                 if c and shutil.which(c)), None)
    return [路径] if 路径 else None


def macOS版本() -> str:
    """macOS 系统版本（textutil 无独立版本号，版本取系统版本）。"""
    return platform.mac_ver()[0] or platform.release()


默认探针清单: tuple[dict[str, Any], ...] = (
    {
        "提供者": "LibreOffice",
        "命令": 查找LibreOffice命令,
        "版本参数": "--version",
        "版本回退": "",
    },
    {
        "提供者": "textutil",
        "命令": 查找textutil命令,
        "版本参数": "-help",
        "版本回退": macOS版本(),
    },
)


class 系统提供者健康监督:
    """周期健康检查：真实子进程探针系统提供者，失败只标记不可用。

    探针函数与探针清单可注入（测试用可控探针/清单）；生产默认
    检查系统工具 + 默认探针清单；证据文件可注入（测试用临时目录）。
    """

    def __init__(self, *, 周期秒: float = 60.0, 探针清单=None,
                 探针函数: Callable | None = None,
                 证据文件=None) -> None:
        self._周期秒 = max(0.1, float(周期秒))
        self._探针清单 = list(探针清单) if 探针清单 else list(默认探针清单)
        self._探针函数 = 探针函数 or 检查系统工具
        self._证据文件 = Path(证据文件) if 证据文件 else 默认证据文件
        try:
            self._证据文件.parent.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass  # 证据目录不可创建时静默：探针与主进程不受影响
        self._状态: dict[str, dict[str, Any]] = {}
        self._锁 = threading.Lock()
        self._停止事件 = threading.Event()
        self._线程: threading.Thread | None = None

    def 执行一次周期检查(self) -> dict[str, Any]:
        """对所有探针清单提供者各执行一次探针，更新健康状态并写证据。

        探针失败只标记对应提供者 健康=False + 「外部提供者不可用」，
        永不 raise/崩溃，主进程继续运行。
        """
        时间戳 = time.strftime(时间格式)
        for 定义 in self._探针清单:
            状态 = self._探针提供者(定义, 时间戳)
            with self._锁:
                self._状态[状态["提供者"]] = 状态
            self._写入证据(状态, 时间戳)
        with self._锁:
            状态表 = {名: dict(状态) for 名, 状态 in self._状态.items()}
        return {
            "成功": True,
            "提供者数": len(状态表),
            "健康提供者数": sum(1 for 状态 in 状态表.values()
                                if 状态.get("健康")),
            "最后检查时间": 时间戳,
            "提供者": 状态表,
        }

    def 查询健康状态(self) -> dict[str, Any]:
        """查询健康状态：提供者/健康/版本/最后检查时间/标准错误摘要。"""
        with self._锁:
            状态表 = {名: dict(状态) for 名, 状态 in self._状态.items()}
        最后检查时间 = max((状态.get("最后检查时间") or ""
                            for 状态 in 状态表.values()), default="")
        return {
            "成功": True,
            "提供者数": len(状态表),
            "健康提供者数": sum(1 for 状态 in 状态表.values()
                                if 状态.get("健康")),
            "最后检查时间": 最后检查时间,
            "提供者": 状态表,
        }

    def 启动周期检查(self) -> bool:
        """后台线程周期执行探针（间隔 周期秒），已运行返回 False。"""
        with self._锁:
            if self._线程 is not None and self._线程.is_alive():
                return False
        self._停止事件.clear()
        线程 = threading.Thread(target=self._周期循环, daemon=True,
                                name="系统提供者健康监督")
        with self._锁:
            self._线程 = 线程
        线程.start()
        return True

    def 停止周期检查(self) -> bool:
        """停止周期线程并等待其退出；未启动返回 False。"""
        self._停止事件.set()
        with self._锁:
            线程 = self._线程
        if 线程 is None:
            return False
        线程.join(timeout=self._周期秒 + 2.0)
        return not 线程.is_alive()

    def _周期循环(self) -> None:
        while not self._停止事件.wait(self._周期秒):
            self.执行一次周期检查()

    def _探针提供者(self, 定义: dict[str, Any], 时间戳: str) -> dict[str, Any]:
        提供者名 = 定义["提供者"]
        状态: dict[str, Any] = {
            "提供者": 提供者名, "健康": False, "错误码": "外部提供者不可用",
            "退出码": None, "版本": "", "标准错误摘要": "", "诊断": "",
            "最后检查时间": 时间戳,
        }
        try:
            命令 = (定义["命令"]() if callable(定义["命令"])
                    else 定义["命令"])
        except Exception as 错误:
            状态["标准错误摘要"] = str(错误)[:标准错误摘要最大长度]
            状态["诊断"] = f"{提供者名} 命令解析异常: {错误}"
            return 状态
        if not 命令:
            状态["诊断"] = f"{提供者名} 未找到（工具缺失，不在 PATH 或路径不存在）"
            return 状态
        try:
            探针: 探针结果 = self._探针函数(
                提供者名, 命令, 版本参数=定义["版本参数"])
        except Exception as 错误:
            # 探针函数异常也收敛为不可用：主进程不得崩溃
            状态["标准错误摘要"] = str(错误)[:标准错误摘要最大长度]
            状态["诊断"] = f"{提供者名} 探针调用异常: {错误}"
            return 状态
        状态["退出码"] = 探针.退出码
        状态["标准错误摘要"] = 探针.标准错误摘要
        if 探针.成功:
            状态["健康"] = True
            状态["错误码"] = ""
            # 无独立版本号的提供者（如 textutil）用版本回退（macOS 版本）
            状态["版本"] = 定义.get("版本回退") or 探针.版本 or ""
            return 状态
        # 探针失败只标记不可用：明确「外部提供者不可用」，
        # 不伪装成环境未构建；诊断保留原始探针错误码明细
        状态["健康"] = False
        状态["错误码"] = "外部提供者不可用"
        状态["诊断"] = (f"{提供者名} 探针失败（{探针.错误码}）: "
                        f"{探针.诊断 or '无明细'}")
        return 状态

    def _写入证据(self, 状态: dict[str, Any], 时间戳: str) -> None:
        """每次探针结果追加一行诊断证据；写入失败静默（不拖垮主进程）。"""
        记录 = {
            "时间": 时间戳,
            "提供者": 状态["提供者"],
            "健康": 状态["健康"],
            "错误码": 状态["错误码"],
            "退出码": 状态["退出码"],
            "版本": 状态["版本"],
            "标准错误摘要": 状态["标准错误摘要"],
            "诊断": 状态["诊断"],
        }
        try:
            with open(self._证据文件, "a", encoding="utf-8") as 文件:
                文件.write(json.dumps(记录, ensure_ascii=False) + "\n")
        except OSError:
            pass
