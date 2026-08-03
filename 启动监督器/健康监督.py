"""系统提供者健康监督：周期真实探针 + 健康状态查询 + 诊断证据。

对 LibreOffice（soffice --version）、textutil（textutil -help + macOS 版本）
等系统提供者，按周期（默认 60 秒，可配置）复用 支持库/适配层/系统探针.py
的 检查系统工具 做独立子进程健康探针（超时 terminate→kill/退出码/版本/
标准错误摘要）。

周期、探针超时、失败阈值（连续失败标记不可用次数）、证据保留策略
（保留条数/TTL）接入启动配置：读取健康监督配置 复用 项目适配层/配置适配
的 合并配置（默认→项目→环境→显式，来源追踪）与 校验配置（未知项/类型
错误，fail-closed）；配置非法时 从配置创建健康监督 抛 ValueError，绝不
静默接受。运行中改周期必须 停止周期检查 → 重建实例 → 启动周期检查
（不得直接改线程周期）。

失败语义：探针失败只把对应提供者标记为 健康=False + 错误码
「外部提供者不可用」（未达失败阈值时保持可用观察中），绝不 raise/崩溃，
主进程继续运行；不把不可用伪装成「环境未构建」。每次探针结果写入诊断
证据（工程缓存/启动监督器/健康证据.jsonl：
时间/提供者/健康/退出码/版本/标准错误摘要），并按证据保留策略裁剪。
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
from 项目适配层.配置适配.配置读取 import 配置读取结果, 读取JSON配置
from 项目适配层.配置适配.配置合并 import 合并配置, 解析环境配置
from 项目适配层.配置适配.配置校验 import 校验配置

系统根 = Path(__file__).resolve().parents[1]
默认证据文件 = 系统根 / "工程缓存" / "启动监督器" / "健康证据.jsonl"
时间格式 = "%Y-%m-%d %H:%M:%S"
标准错误摘要最大长度 = 300

# 健康监督启动配置默认值（配置来源=默认层；未提供时保持当前行为）
健康监督配置默认值: dict[str, Any] = {
    "健康监督周期秒": 60.0,
    "健康监督探针超时秒": 5.0,
    "健康监督失败阈值": 1,
    # 保留条数/TTL 为 0 表示不裁剪（保持证据无限追加现状）
    "健康监督证据保留策略": {"保留条数": 0, "保留TTL秒": 0},
}

# 健康监督配置声明表（未知配置项/类型错误 → 校验失败）
健康监督声明表: dict[str, dict[str, Any]] = {
    "健康监督周期秒": {"类型": "数字"},
    "健康监督探针超时秒": {"类型": "数字"},
    "健康监督失败阈值": {"类型": "数字"},
    "健康监督证据保留策略": {"类型": "字典"},
}


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
    """周期健康检查：真实子进程探针系统提供者，失败按阈值标记不可用。

    探针函数与探针清单可注入（测试用可控探针/清单）；生产默认
    检查系统工具 + 默认探针清单；证据文件可注入（测试用临时目录）。
    周期/探针超时/失败阈值/证据保留策略可经 读取健康监督配置 接入启动
    配置；运行中改周期必须 停止周期检查 → 重建实例 → 启动周期检查。
    """

    def __init__(self, *, 周期秒: float = 60.0, 探针清单=None,
                 探针函数: Callable | None = None,
                 证据文件=None,
                 探针超时秒: float = 5.0, 失败阈值: int = 1,
                 证据保留策略: dict | None = None) -> None:
        self._周期秒 = max(0.1, float(周期秒))
        self._探针超时秒 = max(0.1, float(探针超时秒))
        self._失败阈值 = max(1, int(失败阈值))
        self._证据保留策略 = (dict(证据保留策略)
                             if 证据保留策略 else None)
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

        失败阈值语义：连续失败达阈值才标记 健康=False + 「外部提供者
        不可用」；未达阈值保持可用（观察中），绝不 raise/崩溃，主进程
        继续运行。
        """
        时间戳 = time.strftime(时间格式)
        for 定义 in self._探针清单:
            状态 = self._探针提供者(定义, 时间戳)
            with self._锁:
                前状态 = self._状态.get(状态["提供者"])
                连续失败 = (前状态.get("连续失败次数") or 0
                            if 前状态 else 0)
                if not 状态["健康"]:
                    连续失败 += 1
                    状态["连续失败次数"] = 连续失败
                    if 连续失败 < self._失败阈值:
                        # 未达阈值：保持可用观察中，不标记不可用
                        状态["健康"] = True
                        状态["错误码"] = ""
                        状态["诊断"] = (
                            f"{状态['提供者']} 连续失败 {连续失败}/"
                            f"{self._失败阈值} 次，未达不可用阈值")
                else:
                    状态["连续失败次数"] = 0
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
                提供者名, 命令, 版本参数=定义["版本参数"],
                超时秒=self._探针超时秒)
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
        self._裁剪证据()

    def _裁剪证据(self) -> None:
        """按证据保留策略裁剪证据文件：保留条数（最近 N 条）/ TTL（保留 N 秒内）。

        策略未启用（保留条数/TTL 均为 0 或缺省）时不裁剪，保持无限追加；
        读取/重写失败静默（不拖垮主进程）；时间戳无法解析的行保守保留。
        """
        策略 = self._证据保留策略
        if not 策略:
            return
        保留条数 = 策略.get("保留条数") or 0
        保留TTL秒 = 策略.get("保留TTL秒") or 0
        if not 保留条数 and not 保留TTL秒:
            return
        try:
            行表 = self._证据文件.read_text(encoding="utf-8").splitlines()
        except OSError:
            return
        记录行表: list[tuple[float, str]] = []
        for 行 in 行表:
            try:
                记录 = json.loads(行)
                时间戳文本 = 记录.get("时间") or ""
                秒 = (time.mktime(time.strptime(时间戳文本, 时间格式))
                      if 时间戳文本 else float("inf"))
            except (ValueError, TypeError, json.JSONDecodeError):
                秒 = float("inf")  # 无法解析的时间戳保守保留
            记录行表.append((秒, 行))
        if 保留TTL秒:
            截止时间 = time.time() - 保留TTL秒
            记录行表 = [(秒, 行) for 秒, 行 in 记录行表
                        if 秒 == float("inf") or 秒 >= 截止时间]
        if 保留条数 and len(记录行表) > 保留条数:
            记录行表 = 记录行表[-保留条数:]
        try:
            self._证据文件.write_text(
                "\n".join(行 for _, 行 in 记录行表) + "\n", encoding="utf-8")
        except OSError:
            pass


def _校验健康监督值域(配置: dict[str, Any]) -> list[str]:
    """健康监督配置值域校验（fail-closed）：非法/过小值报问题，不静默接受。"""
    问题列表: list[str] = []

    周期秒 = 配置.get("健康监督周期秒")
    if (not isinstance(周期秒, (int, float)) or isinstance(周期秒, bool)
            or 周期秒 < 1.0):
        问题列表.append("健康监督周期秒 必须是数字且 >= 1 秒")

    探针超时秒 = 配置.get("健康监督探针超时秒")
    if (not isinstance(探针超时秒, (int, float))
            or isinstance(探针超时秒, bool) or 探针超时秒 <= 0):
        问题列表.append("健康监督探针超时秒 必须是数字且 > 0")

    失败阈值 = 配置.get("健康监督失败阈值")
    if (not isinstance(失败阈值, int) or isinstance(失败阈值, bool)
            or 失败阈值 < 1):
        问题列表.append("健康监督失败阈值 必须是正整数（>= 1）")

    策略 = 配置.get("健康监督证据保留策略")
    if not isinstance(策略, dict):
        问题列表.append("健康监督证据保留策略 必须是字典")
    else:
        for 键 in 策略:
            if 键 not in ("保留条数", "保留TTL秒"):
                问题列表.append(f"健康监督证据保留策略 未知配置项: {键}")
        保留条数 = 策略.get("保留条数") or 0
        if (not isinstance(保留条数, int) or isinstance(保留条数, bool)
                or 保留条数 < 0):
            问题列表.append("健康监督证据保留策略.保留条数 必须是非负整数")
        保留TTL秒 = 策略.get("保留TTL秒") or 0
        if (not isinstance(保留TTL秒, (int, float))
                or isinstance(保留TTL秒, bool) or 保留TTL秒 < 0):
            问题列表.append("健康监督证据保留策略.保留TTL秒 必须是非负数")
    return 问题列表


def 读取健康监督配置(*, 项目配置目录=None,
                     环境名称: str | None = None,
                     显式覆盖: dict | None = None) -> 配置读取结果:
    """按 默认→项目→环境→显式 读取健康监督配置，复用既有配置合并/校验/来源追踪。

    项目配置目录：含 默认配置.json/开发配置.json 等 的目录（默认取项目
    适配层/项目配置）；环境名称 对应 环境名+配置.json；显式覆盖 为运行入口
    层键值（如 {"健康监督周期秒": 10}）。返回 配置读取结果：成功=False
    表示配置错误（未知项/类型错误/非法值域，fail-closed），问题列表给出原因。
    """
    配置目录 = Path(项目配置目录) if 项目配置目录 \
        else 系统根 / "项目适配层" / "项目配置"
    项目默认配置: dict[str, Any] = {}
    默认路径 = 配置目录 / "默认配置.json"
    if 默认路径.is_file():
        项目默认配置 = 读取JSON配置(默认路径)
    环境配置 = (解析环境配置(环境名称, 配置目录)
               if 环境名称 else {})
    合并 = 合并配置(
        支持库默认=dict(健康监督配置默认值),
        项目默认=项目默认配置,
        环境配置=环境配置,
        显式覆盖=显式覆盖 if 显式覆盖 is not None else {},
    )
    if not 合并.成功:
        return 合并
    # 只提取健康监督段；未知 健康监督* 键经声明表校验报「未知配置项」
    健康配置 = {键: 值 for 键, 值 in 合并.配置.items()
                if 键.startswith("健康监督")}
    来源表 = {键: 合并.来源表[键] for 键 in 健康配置}
    校验结果 = 校验配置(健康配置, 声明表=健康监督声明表)
    问题列表 = list(校验结果.问题列表) + _校验健康监督值域(健康配置)
    if 问题列表:
        return 配置读取结果(成功=False, 问题列表=问题列表)
    return 配置读取结果(成功=True, 配置=健康配置, 来源表=来源表)


def 从配置创建健康监督(*, 项目配置目录=None,
                       环境名称: str | None = None,
                       显式覆盖: dict | None = None,
                       **构造参数) -> 系统提供者健康监督:
    """按启动配置创建健康监督；配置错误（非法值/未知项）抛 ValueError（fail-closed）。

    构造参数（探针清单/探针函数/证据文件等）可透传，供测试注入。
    """
    结果 = 读取健康监督配置(项目配置目录=项目配置目录,
                          环境名称=环境名称, 显式覆盖=显式覆盖)
    if not 结果.成功:
        raise ValueError("健康监督配置错误: " + "; ".join(结果.问题列表))
    配置 = 结果.配置
    return 系统提供者健康监督(
        周期秒=配置["健康监督周期秒"],
        探针超时秒=配置["健康监督探针超时秒"],
        失败阈值=int(配置["健康监督失败阈值"]),
        证据保留策略=dict(配置["健康监督证据保留策略"]),
        **构造参数)
