"""系统提供者健康监督配置化测试：配置覆盖（显式生效）/非法配置 fail-closed/
默认值（未提供→默认）/来源追踪/重启恢复（停止→重建→启动）/失败阈值/
探针超时传递/证据保留策略（条数+TTL）。

风格与 测试_健康监督.py 一致：sys.path 注入系统根、unittest 用例。
配置读取用临时配置目录（不污染真实 项目适配层/项目配置）；可控探针函数
为测试注入合法用法，生产代码不 mock。
"""

from __future__ import annotations

import json
import sys
import tempfile
import time
import unittest
from pathlib import Path

if str(Path(__file__).resolve().parents[2]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from 启动监督器.健康监督 import (
    从配置创建健康监督,
    读取健康监督配置,
    时间格式,
    系统提供者健康监督,
)
from 支持库.适配层.系统探针 import 探针结果


def _成功探针函数(调用记录: list | None = None):
    """可控探针：成功返回，记录调用（测试注入，生产代码不用）。"""
    def 探针(名称: str, 命令列表: list[str], *, 超时秒: float = 5.0,
             版本参数: str = "--version") -> 探针结果:
        if 调用记录 is not None:
            调用记录.append((名称, 命令列表, 版本参数, 超时秒))
        return 探针结果(True, 退出码=0, 版本="9.9.9",
                        诊断=f"{名称} 探针成功")
    return 探针


def _失败探针函数() -> None:
    """可控探针：失败返回「退出码非零」（测试注入，生产代码不用）。"""
    def 探针(名称: str, 命令列表: list[str], *, 超时秒: float = 5.0,
             版本参数: str = "--version") -> 探针结果:
        return 探针结果(False, 错误码="退出码非零", 退出码=1,
                        标准错误摘要="模拟失败输出",
                        诊断=f"{名称} 退出码 1")
    return 探针


def _临时证据文件() -> Path:
    """临时目录下的健康证据文件（每个用例独立）。"""
    return Path(tempfile.mkdtemp()) / "健康证据.jsonl"


class Test健康配置覆盖(unittest.TestCase):
    """配置覆盖：显式值生效 + 来源追踪（默认→项目→环境→显式）。"""

    def test_未提供配置保持默认(self):
        结果 = 读取健康监督配置()
        self.assertTrue(结果.成功, 结果.问题列表)
        self.assertEqual(结果.配置["健康监督周期秒"], 60.0)
        self.assertEqual(结果.配置["健康监督探针超时秒"], 5.0)
        self.assertEqual(结果.配置["健康监督失败阈值"], 1)
        self.assertEqual(
            结果.配置["健康监督证据保留策略"],
            {"保留条数": 0, "保留TTL秒": 0})
        for 键 in 结果.配置:
            self.assertEqual(结果.来源表[键], "支持库默认配置")

    def test_显式覆盖生效与来源追踪(self):
        结果 = 读取健康监督配置(显式覆盖={
            "健康监督周期秒": 10, "健康监督探针超时秒": 3,
            "健康监督失败阈值": 2, "健康监督证据保留策略": {"保留条数": 5},
        })
        self.assertTrue(结果.成功, 结果.问题列表)
        self.assertEqual(结果.配置["健康监督周期秒"], 10)
        self.assertEqual(结果.配置["健康监督探针超时秒"], 3)
        self.assertEqual(结果.配置["健康监督失败阈值"], 2)
        # 段级深合并：显式只覆盖 保留条数，保留TTL秒 继承默认层
        self.assertEqual(结果.配置["健康监督证据保留策略"],
                         {"保留条数": 5, "保留TTL秒": 0})
        for 键 in 结果.配置:
            self.assertEqual(结果.来源表[键], "运行入口显式覆盖")
        self.assertEqual(结果.来源表["健康监督证据保留策略.保留条数"],
                         "运行入口显式覆盖")
        self.assertEqual(结果.来源表["健康监督证据保留策略.保留TTL秒"],
                         "支持库默认配置")

    def test_项目默认配置生效(self):
        with tempfile.TemporaryDirectory() as 目录:
            配置目录 = Path(目录)
            (配置目录 / "默认配置.json").write_text(
                json.dumps({"健康监督周期秒": 30}, ensure_ascii=False),
                encoding="utf-8")
            结果 = 读取健康监督配置(项目配置目录=配置目录)
            self.assertTrue(结果.成功, 结果.问题列表)
            self.assertEqual(结果.配置["健康监督周期秒"], 30)
            self.assertEqual(结果.来源表["健康监督周期秒"], "项目默认配置")
            self.assertEqual(结果.来源表["健康监督探针超时秒"],
                             "支持库默认配置")

    def test_环境配置覆盖项目默认(self):
        with tempfile.TemporaryDirectory() as 目录:
            配置目录 = Path(目录)
            (配置目录 / "默认配置.json").write_text(
                json.dumps({"健康监督周期秒": 30}, ensure_ascii=False),
                encoding="utf-8")
            (配置目录 / "开发配置.json").write_text(
                json.dumps({"健康监督周期秒": 10}, ensure_ascii=False),
                encoding="utf-8")
            结果 = 读取健康监督配置(项目配置目录=配置目录, 环境名称="开发")
            self.assertTrue(结果.成功, 结果.问题列表)
            self.assertEqual(结果.配置["健康监督周期秒"], 10)
            self.assertEqual(结果.来源表["健康监督周期秒"], "当前环境配置")

    def test_环境配置只覆盖部分键其余保持默认(self):
        with tempfile.TemporaryDirectory() as 目录:
            配置目录 = Path(目录)
            (配置目录 / "默认配置.json").write_text(
                json.dumps({"健康监督周期秒": 30, "健康监督失败阈值": 3},
                           ensure_ascii=False),
                encoding="utf-8")
            (配置目录 / "开发配置.json").write_text(
                json.dumps({"健康监督周期秒": 10}, ensure_ascii=False),
                encoding="utf-8")
            结果 = 读取健康监督配置(项目配置目录=配置目录, 环境名称="开发")
            self.assertTrue(结果.成功, 结果.问题列表)
            self.assertEqual(结果.配置["健康监督周期秒"], 10)
            self.assertEqual(结果.配置["健康监督失败阈值"], 3)

    def test_段级深合并项目层继承默认子字段(self):
        with tempfile.TemporaryDirectory() as 目录:
            配置目录 = Path(目录)
            (配置目录 / "默认配置.json").write_text(
                json.dumps(
                    {"健康监督证据保留策略": {"保留条数": 10}},
                    ensure_ascii=False),
                encoding="utf-8")
            结果 = 读取健康监督配置(项目配置目录=配置目录)
            self.assertTrue(结果.成功, 结果.问题列表)
            self.assertEqual(结果.配置["健康监督证据保留策略"],
                             {"保留条数": 10, "保留TTL秒": 0})
            self.assertEqual(
                结果.来源表["健康监督证据保留策略.保留条数"],
                "项目默认配置")
            self.assertEqual(
                结果.来源表["健康监督证据保留策略.保留TTL秒"],
                "支持库默认配置")

    def test_段级深合并环境层覆盖项目层单个子字段(self):
        with tempfile.TemporaryDirectory() as 目录:
            配置目录 = Path(目录)
            (配置目录 / "默认配置.json").write_text(
                json.dumps({"健康监督证据保留策略": {
                    "保留条数": 10, "保留TTL秒": 3600}},
                    ensure_ascii=False),
                encoding="utf-8")
            (配置目录 / "开发配置.json").write_text(
                json.dumps({"健康监督证据保留策略": {"保留TTL秒": 7200}},
                           ensure_ascii=False),
                encoding="utf-8")
            结果 = 读取健康监督配置(项目配置目录=配置目录, 环境名称="开发")
            self.assertTrue(结果.成功, 结果.问题列表)
            self.assertEqual(结果.配置["健康监督证据保留策略"],
                             {"保留条数": 10, "保留TTL秒": 7200})
            self.assertEqual(
                结果.来源表["健康监督证据保留策略.保留TTL秒"],
                "当前环境配置")
            self.assertEqual(
                结果.来源表["健康监督证据保留策略.保留条数"],
                "项目默认配置")

    def test_段级深合并显式只覆盖一个子字段(self):
        with tempfile.TemporaryDirectory() as 目录:
            配置目录 = Path(目录)
            (配置目录 / "默认配置.json").write_text(
                json.dumps({"健康监督证据保留策略": {
                    "保留条数": 10, "保留TTL秒": 3600}},
                    ensure_ascii=False),
                encoding="utf-8")
            结果 = 读取健康监督配置(
                项目配置目录=配置目录,
                显式覆盖={"健康监督证据保留策略": {"保留条数": 5}})
            self.assertTrue(结果.成功, 结果.问题列表)
            self.assertEqual(结果.配置["健康监督证据保留策略"],
                             {"保留条数": 5, "保留TTL秒": 3600})


class Test健康配置非法值(unittest.TestCase):
    """fail-closed：非法值（非数字/负数/过小）必须失败，不静默接受。"""

    def test_非法值fail_closed(self):
        for 覆盖 in (
            {"健康监督周期秒": "60"},        # 非数字
            {"健康监督周期秒": -5},          # 负数
            {"健康监督周期秒": 0.5},         # 过小（<1 秒）
            {"健康监督周期秒": True},        # 布尔不是数字
            {"健康监督探针超时秒": 0},       # 超时 <= 0
            {"健康监督探针超时秒": -1},
            {"健康监督失败阈值": 0},         # 阈值必须 >= 1
            {"健康监督失败阈值": 2.5},       # 阈值必须整数
            {"健康监督证据保留策略": "不限"},  # 策略必须是字典
            {"健康监督证据保留策略": {"保留条数": -1}},
            {"健康监督证据保留策略": {"保留TTL秒": -3}},
        ):
            结果 = 读取健康监督配置(显式覆盖=覆盖)
            self.assertFalse(结果.成功, f"应拒绝非法配置: {覆盖}")
            self.assertTrue(结果.问题列表, f"非法配置应给出问题: {覆盖}")

    def test_未知配置项fail_closed(self):
        结果 = 读取健康监督配置(显式覆盖={"健康监督周期": 10})
        self.assertFalse(结果.成功)
        self.assertTrue(any("未知配置项" in 问题 for 问题 in 结果.问题列表),
                        结果.问题列表)

    def test_证据保留策略未知子键fail_closed(self):
        结果 = 读取健康监督配置(显式覆盖={
            "健康监督证据保留策略": {"保留条数": 5, "未知键": 1}})
        self.assertFalse(结果.成功)
        self.assertTrue(any("未知" in 问题 for 问题 in 结果.问题列表),
                        结果.问题列表)

    def test_从配置创建配置错误抛异常(self):
        for 覆盖 in ({"健康监督周期秒": 0}, {"健康监督周期秒": "60"}):
            with self.assertRaises(ValueError):
                从配置创建健康监督(显式覆盖=覆盖)

    def test_段级深合并非法子值fail_closed(self):
        # 项目层提供非法子值 → 深合并后值域校验失败，读取失败
        with tempfile.TemporaryDirectory() as 目录:
            配置目录 = Path(目录)
            (配置目录 / "默认配置.json").write_text(
                json.dumps(
                    {"健康监督证据保留策略": {"保留条数": -1}},
                    ensure_ascii=False),
                encoding="utf-8")
            结果 = 读取健康监督配置(项目配置目录=配置目录)
            self.assertFalse(结果.成功, "项目层非法子值应读取失败")
            self.assertTrue(结果.问题列表, "非法子值应给出问题")
        # 环境层提供非法子值 → 同样 fail-closed
        with tempfile.TemporaryDirectory() as 目录:
            配置目录 = Path(目录)
            (配置目录 / "开发配置.json").write_text(
                json.dumps(
                    {"健康监督证据保留策略": {"保留TTL秒": "abc"}},
                    ensure_ascii=False),
                encoding="utf-8")
            结果 = 读取健康监督配置(项目配置目录=配置目录, 环境名称="开发")
            self.assertFalse(结果.成功, "环境层非法子值应读取失败")
            self.assertTrue(结果.问题列表, "非法子值应给出问题")

    def test_从配置创建成功(self):
        监督 = 从配置创建健康监督(
            显式覆盖={"健康监督周期秒": 10, "健康监督探针超时秒": 3,
                     "健康监督失败阈值": 2,
                     "健康监督证据保留策略": {"保留条数": 5}},
            证据文件=_临时证据文件())
        self.assertEqual(监督._周期秒, 10.0)
        self.assertEqual(监督._探针超时秒, 3.0)
        self.assertEqual(监督._失败阈值, 2)
        self.assertEqual(监督._证据保留策略, {"保留条数": 5, "保留TTL秒": 0})


class Test健康配置生效行为(unittest.TestCase):
    """配置驱动行为：失败阈值/探针超时/证据保留策略真实生效。"""

    def test_失败阈值连续失败达阈值才标记不可用(self):
        监督 = 系统提供者健康监督(
            周期秒=0.5, 探针函数=_失败探针函数(),
            证据文件=_临时证据文件(), 失败阈值=2)
        结果1 = 监督.执行一次周期检查()
        状态1 = 结果1["提供者"]["LibreOffice"]
        self.assertTrue(状态1["健康"])  # 第 1 次失败未达阈值：保持可用观察中
        self.assertEqual(状态1["连续失败次数"], 1)
        self.assertEqual(状态1["错误码"], "退出码非零")
        结果2 = 监督.执行一次周期检查()
        状态2 = 结果2["提供者"]["LibreOffice"]
        self.assertFalse(状态2["健康"])  # 第 2 次失败达阈值：标记不可用
        self.assertEqual(状态2["连续失败次数"], 2)
        self.assertEqual(状态2["错误码"], "退出码非零")

    def test_默认失败阈值1一次失败即不可用(self):
        监督 = 系统提供者健康监督(
            周期秒=0.5, 探针函数=_失败探针函数(),
            证据文件=_临时证据文件())
        状态 = 监督.执行一次周期检查()["提供者"]["LibreOffice"]
        self.assertFalse(状态["健康"])
        self.assertEqual(状态["错误码"], "退出码非零")

    def test_探针成功后连续失败计数重置(self):
        状态开关 = {"失败": True}

        def 探针(名称: str, 命令列表: list[str], *, 超时秒: float = 5.0,
                 版本参数: str = "--version") -> 探针结果:
            if 状态开关["失败"]:
                状态开关["失败"] = False
                return 探针结果(False, 错误码="退出码非零", 退出码=1,
                                诊断="首次失败")
            return 探针结果(True, 退出码=0, 版本="1.0")
        监督 = 系统提供者健康监督(
            周期秒=0.5, 探针函数=探针, 证据文件=_临时证据文件(),
            失败阈值=3)
        监督.执行一次周期检查()  # 失败 1 次
        监督.执行一次周期检查()  # 成功：计数重置
        监督.执行一次周期检查()  # 成功
        状态 = 监督.查询健康状态()["提供者"]["LibreOffice"]
        self.assertTrue(状态["健康"])
        self.assertEqual(状态["连续失败次数"], 0)

    def test_探针超时秒传入探针函数(self):
        调用记录: list = []
        监督 = 系统提供者健康监督(
            周期秒=0.5, 探针函数=_成功探针函数(调用记录),
            证据文件=_临时证据文件(), 探针超时秒=3.0)
        监督.执行一次周期检查()
        self.assertTrue(调用记录)
        self.assertTrue(all(记录[3] == 3.0 for 记录 in 调用记录),
                        f"探针超时应为 3.0: {调用记录}")

    def test_证据保留条数裁剪(self):
        证据文件 = _临时证据文件()
        旧时间 = time.strftime(时间格式,
                               time.localtime(time.time() - 86400))
        预写行 = [
            json.dumps({"时间": 旧时间, "提供者": f"旧成功{i}",
                        "健康": True}, ensure_ascii=False)
            for i in range(3)
        ]
        证据文件.write_text("\n".join(预写行) + "\n", encoding="utf-8")
        监督 = 系统提供者健康监督(
            周期秒=0.5, 探针函数=_成功探针函数(),
            证据文件=证据文件, 证据保留策略={"保留条数": 2})
        监督.执行一次周期检查()
        行表 = 证据文件.read_text(encoding="utf-8").strip().splitlines()
        # 保护语义：本轮写入行受当前任务保护，非保护行保留最近 2 条
        self.assertEqual(len(行表), 4, "2 条本轮保护行 + 最近 2 条非保护行")

    def test_证据保留TTL裁剪旧记录(self):
        证据文件 = _临时证据文件()
        旧时间 = time.strftime(时间格式,
                               time.localtime(time.time() - 86400))
        证据文件.write_text(
            json.dumps({"时间": 旧时间, "提供者": "旧", "健康": True},
                       ensure_ascii=False) + "\n",
            encoding="utf-8")
        监督 = 系统提供者健康监督(
            周期秒=0.5, 探针函数=_成功探针函数(),
            证据文件=证据文件, 证据保留策略={"保留TTL秒": 3600})
        监督.执行一次周期检查()
        记录表 = [json.loads(行) for 行 in
                  证据文件.read_text(encoding="utf-8").strip().splitlines()]
        self.assertFalse(any(记录["提供者"] == "旧" for 记录 in 记录表),
                         "超过 TTL 的旧记录应被裁剪")
        self.assertEqual(len(记录表), 2, "本次两条新记录保留")

    def test_证据保留策略缺省不裁剪(self):
        证据文件 = _临时证据文件()
        监督 = 系统提供者健康监督(
            周期秒=0.5, 探针函数=_成功探针函数(),
            证据文件=证据文件)
        for _ in range(3):
            监督.执行一次周期检查()
        行表 = 证据文件.read_text(encoding="utf-8").strip().splitlines()
        self.assertEqual(len(行表), 6, "未配置保留策略时保持无限追加")

    def test_裁剪保护失败行不被TTL裁剪(self):
        证据文件 = _临时证据文件()
        旧时间 = time.strftime(时间格式,
                               time.localtime(time.time() - 86400))
        预写行 = [
            json.dumps({"时间": 旧时间, "提供者": "旧失败1",
                        "健康": False}, ensure_ascii=False),
            json.dumps({"时间": 旧时间, "提供者": "旧失败2",
                        "健康": False}, ensure_ascii=False),
            json.dumps({"时间": 旧时间, "提供者": "旧成功1",
                        "健康": True}, ensure_ascii=False),
            json.dumps({"时间": 旧时间, "提供者": "旧成功2",
                        "健康": True}, ensure_ascii=False),
        ]
        证据文件.write_text("\n".join(预写行) + "\n", encoding="utf-8")
        监督 = 系统提供者健康监督(
            周期秒=0.5, 探针函数=_成功探针函数(),
            证据文件=证据文件, 证据保留策略={"保留TTL秒": 3600})
        监督.执行一次周期检查()
        记录表 = [json.loads(行) for 行 in
                  证据文件.read_text(encoding="utf-8").strip().splitlines()]
        提供者表 = [记录["提供者"] for 记录 in 记录表]
        self.assertIn("旧失败1", 提供者表, "失败行受保护不被 TTL 裁剪")
        self.assertIn("旧失败2", 提供者表)
        self.assertNotIn("旧成功1", 提供者表, "成功旧行超过 TTL 应被裁剪")
        self.assertNotIn("旧成功2", 提供者表)
        self.assertEqual(len(记录表), 4, "2 条失败保护行 + 本次 2 条新记录")

    def test_裁剪保护失败行不被条数裁剪(self):
        证据文件 = _临时证据文件()
        旧时间 = time.strftime(时间格式,
                               time.localtime(time.time() - 86400))
        预写行 = [
            json.dumps({"时间": 旧时间, "提供者": f"旧失败{i}",
                        "健康": False}, ensure_ascii=False)
            for i in range(3)
        ]
        证据文件.write_text("\n".join(预写行) + "\n", encoding="utf-8")
        监督 = 系统提供者健康监督(
            周期秒=0.5, 探针函数=_成功探针函数(),
            证据文件=证据文件, 证据保留策略={"保留条数": 2})
        监督.执行一次周期检查()  # 2 条成功行
        监督.执行一次周期检查()  # 2 条成功行
        记录表 = [json.loads(行) for 行 in
                  证据文件.read_text(encoding="utf-8").strip().splitlines()]
        失败行数 = sum(1 for 记录 in 记录表 if 记录.get("健康") is False)
        成功行数 = sum(1 for 记录 in 记录表 if 记录.get("健康") is True)
        self.assertEqual(失败行数, 3, "失败行受保护不被条数裁剪")
        self.assertEqual(成功行数, 4, "非保护成功行保留最近 2 条 + 本轮 2 条保护行")
        self.assertEqual(len(记录表), 7)

    def test_裁剪保护当前任务行保留(self):
        证据文件 = _临时证据文件()
        监督 = 系统提供者健康监督(
            周期秒=0.5, 探针函数=_成功探针函数(),
            证据文件=证据文件, 证据保留策略={"保留TTL秒": 1})
        结果 = 监督.执行一次周期检查()
        记录表 = [json.loads(行) for 行 in
                  证据文件.read_text(encoding="utf-8").strip().splitlines()]
        self.assertEqual(len(记录表), 2, "本轮写入行受当前任务保护不被 TTL 裁剪")
        self.assertTrue(
            all(记录["时间"] == 结果["最后检查时间"]
                for 记录 in 记录表),
            "本轮行时间戳应等于最近检查时间戳")


class Test健康配置重启恢复(unittest.TestCase):
    """生命周期：运行中改周期必须 停止→重建→启动，不得直接改线程周期。"""

    def test_停止重建启动后周期生效(self):
        调用记录A: list = []
        监督A = 系统提供者健康监督(
            周期秒=60, 探针函数=_成功探针函数(调用记录A),
            证据文件=_临时证据文件())
        self.assertTrue(监督A.启动周期检查())
        time.sleep(0.15)
        self.assertTrue(监督A.停止周期检查())
        self.assertFalse(监督A._线程.is_alive())
        # 重建新实例（配置周期 1 秒）并启动：新周期立即生效
        调用记录B: list = []
        监督B = 从配置创建健康监督(
            显式覆盖={"健康监督周期秒": 1},
            探针函数=_成功探针函数(调用记录B),
            证据文件=_临时证据文件())
        self.assertEqual(监督B._周期秒, 1.0)
        self.assertTrue(监督B.启动周期检查())
        time.sleep(1.5)
        self.assertTrue(监督B.停止周期检查())
        self.assertGreaterEqual(
            len(调用记录B), 1, "重建后 1 秒周期应已生效（至少 1 次探针）")

    def test_重启后配置来源与深合并一致(self):
        证据文件 = _临时证据文件()
        显式覆盖 = {"健康监督证据保留策略": {"保留条数": 5}}
        # 同一显式覆盖两次读取：来源表与深合并结果一致
        结果1 = 读取健康监督配置(显式覆盖=显式覆盖)
        结果2 = 读取健康监督配置(显式覆盖=显式覆盖)
        self.assertTrue(结果1.成功, 结果1.问题列表)
        self.assertTrue(结果2.成功, 结果2.问题列表)
        self.assertEqual(结果1.配置["健康监督证据保留策略"],
                         {"保留条数": 5, "保留TTL秒": 0})
        self.assertEqual(结果2.配置, 结果1.配置)
        self.assertEqual(结果2.来源表, 结果1.来源表)
        self.assertEqual(结果1.来源表["健康监督证据保留策略"],
                         "运行入口显式覆盖")
        self.assertEqual(结果1.来源表["健康监督证据保留策略.保留条数"],
                         "运行入口显式覆盖")
        self.assertEqual(结果1.来源表["健康监督证据保留策略.保留TTL秒"],
                         "支持库默认配置")
        # 停止→重建（同一显式覆盖）：同一证据文件继续追加不重写，旧行仍在
        监督A = 从配置创建健康监督(显式覆盖=显式覆盖,
                                   证据文件=证据文件)
        监督A.执行一次周期检查()
        监督A.停止周期检查()
        监督B = 从配置创建健康监督(显式覆盖=显式覆盖,
                                   证据文件=证据文件)
        监督B.执行一次周期检查()
        监督B.停止周期检查()
        行表 = 证据文件.read_text(encoding="utf-8").strip().splitlines()
        self.assertEqual(len(行表), 4, "重建后同一证据文件继续追加，旧行仍在")


if __name__ == "__main__":
    unittest.main()
