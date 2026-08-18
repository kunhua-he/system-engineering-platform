"""系统提供者健康监督：周期真实探针 + 健康状态查询 + 诊断证据。

对 LibreOffice（soffice --version）、textutil（textutil -help + macOS 版本）
等系统提供者，按周期（默认 60 秒，可配置）复用 支持库/适配层/系统探针.py
的 检查系统工具 做独立子进程健康探针（超时 terminate→kill/退出码/版本/
标准错误摘要）。

周期、探针超时、失败阈值（连续失败标记不可用次数）、证据保留策略
（保留条数/TTL）接入启动配置：读取健康监督配置 复用 项目适配层/配置适配
的 合并配置（默认→项目→环境→显式，来源追踪）与 校验配置（未知项/类型
错误，fail-closed）；健康监督证据保留策略 额外经 段级深合并配置 逐子
字段合并（各层只覆盖自己提供的子字段，未提供的子字段继承上层值）。配置
非法时 从配置创建健康监督 抛 ValueError，绝不静默接受。运行中改周期必须
停止周期检查 → 重建实例 → 启动周期检查（不得直接改线程周期）。

失败语义：探针失败只把对应提供者标记为 健康=False，错误码透传探针
分类（工具缺失/探针超时/退出码非零），命令解析异常与探针函数异常归类
「探针异常」（未达失败阈值时保持可用观察中，但错误码保留分类），绝不
raise/崩溃，主进程继续运行；不把不可用伪装成「环境未构建」。每次探针
结果写入诊断证据（工程缓存/启动监督器/健康证据.jsonl：时间/提供者/
健康/错误码/退出码/版本/标准错误摘要/诊断/成功/耗时秒/错误摘要/可重试/
来源），并按证据保留策略裁剪（失败证据行与本轮当前任务行受保护永不
裁剪，TTL/条数只作用于非保护行，文件总行数可能超过保留条数）。
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
from 项目适配层.配置适配.配置合并 import (
    段级深合并配置,
    合并配置,
    解析环境配置,
)
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
    # 默认启用证据保留：只保留最近 2000 条非保护行（失败证据行受保护）
    "健康监督证据保留策略": {"保留条数": 2000, "保留TTL秒": 0},
}

# 失败保护行软上限：超过该数量的失败证据行也裁剪最旧（防失败风暴无界增长）
失败保护行软上限 = 2000

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

        失败阈值语义：连续失败达阈值才标记 健康=False（错误码保留探针
        分类）；未达阈值保持可用（观察中，错误码保留分类不清空），绝不
        raise/崩溃，主进程继续运行。证据写入失败只标记 证据写入失败，
        健康/错误码/成功 不受影响；结果顶层返回 证据写入失败提供者数。
        """
        时间戳 = time.strftime(时间格式)
        证据写入失败提供者数 = 0
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
                        # 未达阈值：保持可用观察中，错误码保留分类不清空
                        状态["健康"] = True
                        状态["诊断"] = (
                            f"{状态['诊断']}；连续失败 {连续失败}/"
                            f"{self._失败阈值} 次，未达不可用阈值")
                else:
                    状态["连续失败次数"] = 0
                self._状态[状态["提供者"]] = 状态
            if not self._写入证据(状态, 时间戳):
                证据写入失败提供者数 += 1
        with self._锁:
            状态表 = {名: dict(状态) for 名, 状态 in self._状态.items()}
        return {
            "成功": True,
            "提供者数": len(状态表),
            "健康提供者数": sum(1 for 状态 in 状态表.values()
                                if 状态.get("健康")),
            "证据写入失败提供者数": 证据写入失败提供者数,
            "最后检查时间": 时间戳,
            "提供者": 状态表,
        }

    def 查询健康状态(self) -> dict[str, Any]:
        """查询健康状态：提供者/健康/错误码/成功/版本/退出码/耗时秒/
        错误摘要/可重试/来源/证据写入失败。"""
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

    def 汇入进程健康(self, 健康表: dict[str, dict[str, Any]]) -> None:
        """汇入运行核心提供的进程健康状态（第三十阶段C3 接线）。

        健康表: {提供者名: {"健康": bool, "错误码": str, "成功": bool,
        "诊断": str, "版本": str, "来源": str, ...}}。汇入与周期探针
        状态共存（同一 _状态 事实点），不启动线程、不影响周期检查；
        查询健康状态 自动包含汇入结果。运行核心进程健康由
        运行核心/运行环境管理器/提供者生命周期 统一管理，本监督器只
        汇入展示，不做第二套健康判定。
        """
        时间戳 = time.strftime(时间格式)
        with self._锁:
            for 提供者名, 状态 in 健康表.items():
                合并状态 = dict(状态)
                合并状态["提供者"] = 提供者名
                合并状态.setdefault("健康", False)
                合并状态.setdefault("成功", False)
                合并状态.setdefault("错误码", "")
                合并状态.setdefault("退出码", None)
                合并状态.setdefault("版本", "")
                合并状态.setdefault("标准错误摘要", "")
                合并状态.setdefault("诊断", "运行核心进程健康汇入")
                合并状态.setdefault("耗时秒", 0.0)
                合并状态.setdefault("错误摘要", "")
                合并状态.setdefault("可重试", False)
                合并状态.setdefault("来源", "进程健康汇入")
                合并状态["证据写入失败"] = False
                合并状态["最后检查时间"] = 时间戳
                self._状态[提供者名] = 合并状态

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
            "提供者": 提供者名, "健康": False, "错误码": "",
            "退出码": None, "版本": "", "标准错误摘要": "", "诊断": "",
            "最后检查时间": 时间戳,
            "成功": False, "耗时秒": 0.0, "错误摘要": "",
            "可重试": False, "来源": "周期探针检查",
            "证据写入失败": False,
        }
        try:
            命令 = (定义["命令"]() if callable(定义["命令"])
                    else 定义["命令"])
        except Exception as 错误:
            # 命令解析异常归类「探针异常」，不吞成同一种不可用
            异常文本 = str(错误)[:标准错误摘要最大长度]
            状态["错误码"] = "探针异常"
            状态["标准错误摘要"] = 异常文本
            状态["错误摘要"] = 异常文本
            状态["诊断"] = f"{提供者名} 命令解析异常: {错误}"
            return 状态
        if not 命令:
            状态["错误码"] = "工具缺失"
            状态["诊断"] = f"{提供者名} 未找到（工具缺失，不在 PATH 或路径不存在）"
            return 状态
        try:
            探针: 探针结果 = self._探针函数(
                提供者名, 命令, 版本参数=定义["版本参数"],
                超时秒=self._探针超时秒)
        except Exception as 错误:
            # 探针函数异常归类「探针异常」：主进程不得崩溃
            异常文本 = str(错误)[:标准错误摘要最大长度]
            状态["错误码"] = "探针异常"
            状态["标准错误摘要"] = 异常文本
            状态["错误摘要"] = 异常文本
            状态["诊断"] = f"{提供者名} 探针调用异常: {错误}"
            return 状态
        状态["退出码"] = 探针.退出码
        状态["标准错误摘要"] = 探针.标准错误摘要
        状态["耗时秒"] = 探针.耗时秒
        状态["错误摘要"] = 探针.错误摘要
        状态["可重试"] = 探针.可重试
        if 探针.成功:
            状态["成功"] = True
            状态["健康"] = True
            状态["错误码"] = ""
            # 无独立版本号的提供者（如 textutil）用版本回退（macOS 版本）
            状态["版本"] = 定义.get("版本回退") or 探针.版本 or ""
            return 状态
        # 探针失败：透传探针分类错误码（工具缺失/探针超时/退出码非零），
        # 不统一改写成「外部提供者不可用」；可重试透传（超时=True）
        状态["成功"] = False
        状态["健康"] = False
        状态["错误码"] = 探针.错误码 or "退出码非零"
        状态["诊断"] = (f"{提供者名} 探针失败（{探针.错误码}）: "
                        f"{探针.诊断 or '无明细'}")
        return 状态

    def _写入证据(self, 状态: dict[str, Any], 时间戳: str) -> bool:
        """每次探针结果追加一行诊断证据；返回写入是否成功。

        证据写入失败只标记 证据写入失败=True 并在 错误摘要 追加原因，
        健康/错误码/成功 不受影响（证据写入失败不是探针失败，不得把
        提供者标记不可用）；不 raise 拖垮主进程。
        """
        记录 = {
            "时间": 时间戳,
            "提供者": 状态["提供者"],
            "健康": 状态["健康"],
            "错误码": 状态["错误码"],
            "退出码": 状态["退出码"],
            "版本": 状态["版本"],
            "标准错误摘要": 状态["标准错误摘要"],
            "诊断": 状态["诊断"],
            "成功": 状态["成功"],
            "耗时秒": 状态["耗时秒"],
            "错误摘要": 状态["错误摘要"],
            "可重试": 状态["可重试"],
            "来源": "周期探针检查",
        }
        try:
            with open(self._证据文件, "a", encoding="utf-8") as 文件:
                文件.write(json.dumps(记录, ensure_ascii=False) + "\n")
        except OSError as 错误:
            状态["证据写入失败"] = True
            原因文本 = str(错误)[:标准错误摘要最大长度]
            原摘要 = 状态.get("错误摘要") or ""
            状态["错误摘要"] = (
                f"{原摘要}；证据写入失败: {原因文本}" if 原摘要
                else f"证据写入失败: {原因文本}")
            return False
        self._裁剪证据(时间戳)
        return True

    def _读尾部行(self, 行数上限: int) -> list[str]:
        """从文件尾部倒读最多 行数上限 行（大文件避免整体 O(n) 读取）。"""
        try:
            with open(self._证据文件, "rb") as 文件:
                文件.seek(0, os.SEEK_END)
                大小 = 文件.tell()
                if 大小 == 0:
                    return []
                块大小 = 65536
                尾部 = b""
                while 大小 > 0:
                    读取长度 = min(块大小, 大小)
                    大小 -= 读取长度
                    文件.seek(大小)
                    尾部 = 文件.read(读取长度) + 尾部
                    if 尾部.count(b"\n") >= 行数上限:
                        break
                行表 = 尾部.splitlines()
                return [行.decode("utf-8", "replace") for 行 in 行表[-行数上限:]]
        except OSError:
            return []

    def _裁剪证据(self, 时间戳: str | None = None) -> None:
        """按证据保留策略裁剪证据文件，失败证据行与当前任务行受保护。

        策略未启用（保留条数/TTL 均为 0 或缺省）时不裁剪，保持无限追加；
        只从文件尾部倒读窗口（保留条数+保护行软上限+1 行），不做全文件
        O(n) 重写；保护行（任何情况下不裁剪）：失败证据行（成功=False 或
        健康=False，字段缺失按成功/健康处理）与本轮刚写入的当前任务行
        （时间戳等于本次检查时间戳）；失败保护行超过软上限时裁剪最旧
        保护行（防失败风暴无界增长）；TTL 只对非保护行生效，条数只对非
        保护行计数并保留最近 N 条非保护行，因此文件总行数可能超过
        保留条数；读取/重写失败静默（不拖垮主进程）；时间戳无法解析的
        行保守保留。
        """
        策略 = self._证据保留策略
        if not 策略:
            return
        保留条数 = 策略.get("保留条数") or 0
        保留TTL秒 = 策略.get("保留TTL秒") or 0
        if not 保留条数 and not 保留TTL秒:
            return
        尾部上限 = 保留条数 + 失败保护行软上限 + 1
        行表 = self._读尾部行(尾部上限)
        if not 行表:
            return
        本次时间秒: float | None = None
        if 时间戳:
            try:
                本次时间秒 = time.mktime(time.strptime(时间戳, 时间格式))
            except (ValueError, TypeError):
                本次时间秒 = None  # 本次时间戳解析失败：不启用当前任务行保护
        # 记录行表: (文件原序号, 时间秒, 行文本, 是否保护行)
        记录行表: list[tuple[int, float, str, bool]] = []
        for 序号, 行 in enumerate(行表):
            try:
                记录 = json.loads(行)
                时间戳文本 = 记录.get("时间") or ""
                # 字段缺失时 成功/健康 按 True 处理（非失败行）
                成功 = 记录.get("成功", True)
                健康 = 记录.get("健康", True)
                秒 = (time.mktime(time.strptime(时间戳文本, 时间格式))
                      if 时间戳文本 else float("inf"))
            except (ValueError, TypeError, json.JSONDecodeError):
                秒 = float("inf")  # 无法解析的时间戳保守保留
                成功, 健康 = True, True
            是保护行 = False
            if 成功 is False or 健康 is False:
                是保护行 = True  # 失败证据行：软上限内不裁剪
            elif 秒 != float("inf") and 本次时间秒 is not None \
                    and 秒 == 本次时间秒:
                是保护行 = True  # 当前任务行：本轮刚写入
            记录行表.append((序号, 秒, 行, 是保护行))
        if 保留TTL秒:
            截止时间 = time.time() - 保留TTL秒
            记录行表 = [(序号, 秒, 行, 是保护行)
                        for 序号, 秒, 行, 是保护行 in 记录行表
                        if 是保护行 or 秒 == float("inf") or 秒 >= 截止时间]
        if 保留条数:
            非保护行表 = [(序号, 秒, 行) for 序号, 秒, 行, 是保护行 in 记录行表
                        if not 是保护行]
            if len(非保护行表) > 保留条数:
                保留序号集 = {序号 for 序号, _, _ in 非保护行表[-保留条数:]}
                记录行表 = [(序号, 秒, 行, 是保护行)
                            for 序号, 秒, 行, 是保护行 in 记录行表
                            if 是保护行 or 序号 in 保留序号集]
        # 失败保护行软上限：保护行过多（失败风暴）时裁剪最旧保护行
        保护行表 = [(序号, 秒, 行) for 序号, 秒, 行, 是保护行 in 记录行表 if 是保护行]
        if len(保护行表) > 失败保护行软上限:
            保留保护序号集 = {序号 for 序号, _, _ in 保护行表[-失败保护行软上限:]}
            记录行表 = [(序号, 秒, 行, 是保护行)
                        for 序号, 秒, 行, 是保护行 in 记录行表
                        if not 是保护行 or 序号 in 保留保护序号集]
        记录行表.sort(key=lambda 项: 项[0])
        try:
            self._证据文件.write_text(
                "\n".join(行 for _, _, 行, _ in 记录行表) + "\n",
                encoding="utf-8")
        except OSError as 错误:
            # 写失败记录到诊断（有界单条覆盖），不拖垮主进程
            with self._锁:
                self._状态["证据裁剪失败"] = {
                    "时间": time.strftime(时间格式),
                    "诊断": f"证据裁剪写失败: {错误}"}


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
    层键值（如 {"健康监督周期秒": 10}）。健康监督证据保留策略 按段级深合并
    （各层只覆盖自己提供的子字段，未提供的子字段继承上层值）；任何层提供
    的未知子键或非法值经值域校验报问题（fail-closed）。返回 配置读取结果：
    成功=False 表示配置错误（未知项/类型错误/非法值域），问题列表给出原因。
    """
    配置目录 = Path(项目配置目录) if 项目配置目录 \
        else 系统根 / "项目适配层" / "项目配置"
    项目默认配置: dict[str, Any] = {}
    默认路径 = 配置目录 / "默认配置.json"
    if 默认路径.is_file():
        项目默认配置 = 读取JSON配置(默认路径)
    环境配置 = (解析环境配置(环境名称, 配置目录)
               if 环境名称 else {})
    显式覆盖层 = 显式覆盖 if 显式覆盖 is not None else {}
    合并 = 合并配置(
        支持库默认=dict(健康监督配置默认值),
        项目默认=项目默认配置,
        环境配置=环境配置,
        显式覆盖=显式覆盖层,
    )
    if not 合并.成功:
        return 合并
    # 段级深合并 健康监督证据保留策略：各层只覆盖自己提供的子字段
    层级表 = [
        ("支持库默认配置", dict(健康监督配置默认值)),
        ("项目默认配置", 项目默认配置),
        ("当前环境配置", 环境配置),
        ("运行入口显式覆盖", 显式覆盖层),
    ]
    try:
        合并段, 子键来源表 = 段级深合并配置(层级表, "健康监督证据保留策略")
    except ValueError as 错误:
        # fail-closed：任何层 段名 非字典 → 配置错误，不静默接受
        return 配置读取结果(成功=False, 问题列表=[str(错误)])
    if not 合并段:
        # 没有任何层提供策略：默认值兜底（来源=支持库默认配置）
        合并段 = {"保留条数": 0, "保留TTL秒": 0}
        子键来源表 = {"保留条数": "支持库默认配置",
                    "保留TTL秒": "支持库默认配置"}
    # 用深合并段替换平铺合并结果；顶层键来源=最后提供该键的层级名
    合并.配置["健康监督证据保留策略"] = 合并段
    合并.来源表.setdefault("健康监督证据保留策略", "支持库默认配置")
    # 只提取健康监督段；未知 健康监督* 键经声明表校验报「未知配置项」
    健康配置 = {键: 值 for 键, 值 in 合并.配置.items()
                if 键.startswith("健康监督")}
    来源表 = {键: 合并.来源表[键] for 键 in 健康配置}
    for 子键名, 子键来源 in 子键来源表.items():
        来源表[f"健康监督证据保留策略.{子键名}"] = 子键来源
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
