"""系统提供者健康监督测试：周期调用/失败只标记不可用/健康状态查询/
诊断证据写入/真实 LibreOffice 与 textutil 探针成功。

风格与 测试_系统探针.py 一致：sys.path 注入系统根、unittest 用例。
周期/失败/证据用可控探针函数（测试内注入探针函数为合法用法，
生产代码不 mock）；真实探针走真实独立子进程；临时目录做证据文件。
"""

from __future__ import annotations

import json
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

if str(Path(__file__).resolve().parents[2]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from 公共契约.基础类型.逻辑类型 import 真, 假
from 启动监督器.健康监督 import (
    macOS版本,
    查找LibreOffice命令,
    查找textutil命令,
    默认探针清单,
    系统提供者健康监督,
)
from 支持库.适配层.系统探针 import 探针结果


def _成功探针函数(调用记录: list | None = None):
    """可控探针：成功返回，记录调用（测试注入，生产代码不用）。"""
    def 探针(名称: str, 命令列表: list[str], *, 超时秒: float = 5.0,
            版本参数: str = "--version") -> 探针结果:
        if 调用记录 is not None:
            调用记录.append((名称, 命令列表, 版本参数))
        return 探针结果(真, 退出码=0, 版本="9.9.9",
                        诊断=f"{名称} 探针成功")
    return 探针


def _失败探针函数() -> None:
    """可控探针：失败返回「退出码非零」（测试注入，生产代码不用）。"""
    def 探针(名称: str, 命令列表: list[str], *, 超时秒: float = 5.0,
            版本参数: str = "--version") -> 探针结果:
        return 探针结果(假, 错误码="退出码非零", 退出码=1,
                        标准错误摘要="模拟失败输出",
                        诊断=f"{名称} 退出码 1")
    return 探针


def _超时探针函数() -> None:
    """可控探针：超时失败（暂态、可重试）（测试注入，生产代码不用）。"""
    def 探针(名称: str, 命令列表: list[str], *, 超时秒: float = 5.0,
            版本参数: str = "--version") -> 探针结果:
        return 探针结果(假, 错误码="探针超时", 可重试=真,
                        诊断=f"{名称} 探针超时")
    return 探针


def _工具缺失探针函数() -> None:
    """可控探针：工具缺失失败（测试注入，生产代码不用）。"""
    def 探针(名称: str, 命令列表: list[str], *, 超时秒: float = 5.0,
            版本参数: str = "--version") -> 探针结果:
        return 探针结果(假, 错误码="工具缺失",
                        诊断=f"{名称} 未找到")
    return 探针


def _临时证据文件() -> Path:
    """临时目录下的健康证据文件（每个用例独立）。"""
    return Path(tempfile.mkdtemp()) / "健康证据.jsonl"


class Test健康监督周期调用(unittest.TestCase):
    """短周期 + 可控探针函数：周期调用真实发生。"""

    def test_短周期循环调用探针(self):
        调用记录: list = []
        证据文件 = _临时证据文件()
        监督 = 系统提供者健康监督(
            周期秒=0.1, 探针函数=_成功探针函数(调用记录),
            证据文件=证据文件)
        self.assertTrue(监督.启动周期检查())
        self.assertFalse(监督.启动周期检查())  # 已运行不再重复启动
        time.sleep(0.35)
        self.assertTrue(监督.停止周期检查())
        提供者表 = set(记录[0] for 记录 in 调用记录)
        self.assertGreaterEqual(len(调用记录), 2, "短周期内应至少探针 2 次")
        self.assertIn("LibreOffice", 提供者表)
        self.assertIn("textutil", 提供者表)

    def test_周期默认60秒可配置(self):
        监督 = 系统提供者健康监督()
        self.assertEqual(监督._周期秒, 60.0)
        监督2 = 系统提供者健康监督(周期秒=5)
        self.assertEqual(监督2._周期秒, 5.0)


class Test健康监督失败语义(unittest.TestCase):
    """探针失败只标记不可用，主进程不崩溃。"""

    def test_探针失败只标记不可用(self):
        监督 = 系统提供者健康监督(
            周期秒=0.5, 探针函数=_失败探针函数(),
            证据文件=_临时证据文件())
        # 不 raise/崩溃，返回检查完成结果
        结果 = 监督.执行一次周期检查()
        self.assertFalse(结果["成功"], "探针失败时整体健康检查必须失败")
        self.assertEqual(结果["健康提供者数"], 0)
        状态表 = 结果["提供者"]
        for 提供者名 in ("LibreOffice", "textutil"):
            状态 = 状态表[提供者名]
            self.assertFalse(状态["健康"])
            self.assertEqual(状态["错误码"], "退出码非零")
            self.assertFalse(状态["成功"])
            self.assertFalse(状态["可重试"])
            self.assertIn("退出码非零", 状态["诊断"])

    def test_探针函数抛异常主进程不崩溃(self):
        def 炸裂探针(名称: str, 命令列表: list[str], **_: object) -> None:
            raise RuntimeError("模拟探针内部故障")
        监督 = 系统提供者健康监督(
            周期秒=0.5, 探针函数=炸裂探针,
            证据文件=_临时证据文件())
        结果 = 监督.执行一次周期检查()
        self.assertFalse(结果["成功"], "探针异常时整体健康检查必须失败")
        self.assertEqual(结果["健康提供者数"], 0)
        self.assertEqual(
            结果["提供者"]["LibreOffice"]["错误码"], "探针异常")
        self.assertFalse(结果["提供者"]["LibreOffice"]["成功"])
        self.assertEqual(结果["提供者"]["LibreOffice"]["可重试"], 假)

    def test_失败后主进程继续运行(self):
        调用记录: list = []
        监督 = 系统提供者健康监督(
            周期秒=0.5, 探针函数=_成功探针函数(调用记录),
            证据文件=_临时证据文件())
        失败监督 = 系统提供者健康监督(
            周期秒=0.5, 探针函数=_失败探针函数(),
            证据文件=_临时证据文件())
        失败监督.执行一次周期检查()
        # 失败后同进程继续正常探针与查询
        结果 = 监督.执行一次周期检查()
        self.assertEqual(结果["健康提供者数"], 2)
        self.assertTrue(监督.查询健康状态()["提供者"]["LibreOffice"]["健康"])

    def test_探针超时分类可重试(self):
        监督 = 系统提供者健康监督(
            周期秒=0.5, 探针函数=_超时探针函数(),
            证据文件=_临时证据文件())
        结果 = 监督.执行一次周期检查()
        self.assertFalse(结果["成功"], "探针超时时整体健康检查必须失败")
        self.assertEqual(结果["健康提供者数"], 0)
        for 提供者名 in ("LibreOffice", "textutil"):
            状态 = 结果["提供者"][提供者名]
            self.assertFalse(状态["健康"])
            self.assertEqual(状态["错误码"], "探针超时")
            self.assertTrue(状态["可重试"])
            self.assertFalse(状态["成功"])

    def test_工具缺失分类(self):
        监督 = 系统提供者健康监督(
            周期秒=0.5, 探针函数=_工具缺失探针函数(),
            证据文件=_临时证据文件())
        结果 = 监督.执行一次周期检查()
        self.assertFalse(结果["成功"], "工具缺失时整体健康检查必须失败")
        self.assertEqual(结果["健康提供者数"], 0)
        for 提供者名 in ("LibreOffice", "textutil"):
            状态 = 结果["提供者"][提供者名]
            self.assertFalse(状态["健康"])
            self.assertEqual(状态["错误码"], "工具缺失")
            self.assertFalse(状态["可重试"])

    def test_失败阈值观察期错误码保留(self):
        监督 = 系统提供者健康监督(
            周期秒=0.5, 失败阈值=2, 探针函数=_失败探针函数(),
            证据文件=_临时证据文件())
        结果 = 监督.执行一次周期检查()
        # 第 1 次失败：未达阈值保持可用观察中，但错误码保留分类不清空
        self.assertEqual(结果["健康提供者数"], 2)
        for 提供者名 in ("LibreOffice", "textutil"):
            状态 = 结果["提供者"][提供者名]
            self.assertTrue(状态["健康"])
            self.assertEqual(状态["错误码"], "退出码非零")
            self.assertIn("未达不可用阈值", 状态["诊断"])
        # 第 2 次失败：达阈值标记不可用，错误码仍保留分类
        第二次 = 监督.执行一次周期检查()
        self.assertEqual(第二次["健康提供者数"], 0)
        for 提供者名 in ("LibreOffice", "textutil"):
            状态 = 第二次["提供者"][提供者名]
            self.assertFalse(状态["健康"])
            self.assertEqual(状态["错误码"], "退出码非零")


class Test健康监督查询(unittest.TestCase):
    """健康状态查询：提供者/健康/版本/最后检查时间/标准错误摘要。"""

    def test_查询健康状态字段(self):
        监督 = 系统提供者健康监督(
            周期秒=0.5, 探针函数=_成功探针函数(),
            证据文件=_临时证据文件())
        检查前 = 监督.查询健康状态()
        self.assertFalse(检查前["成功"])
        self.assertEqual(检查前["提供者数"], 0)  # 未检查前无提供者状态
        监督.执行一次周期检查()
        状态 = 监督.查询健康状态()
        self.assertEqual(状态["提供者数"], 2)
        self.assertEqual(状态["健康提供者数"], 2)
        self.assertTrue(状态["最后检查时间"])
        for 提供者名 in ("LibreOffice", "textutil"):
            项 = 状态["提供者"][提供者名]
            self.assertEqual(项["提供者"], 提供者名)
            self.assertTrue(项["健康"])
            self.assertEqual(项["最后检查时间"], 状态["最后检查时间"])
            self.assertEqual(项["标准错误摘要"], "")
            self.assertEqual(项["退出码"], 0)
            self.assertEqual(项["错误码"], "")
            self.assertTrue(项["成功"])
            self.assertFalse(项["可重试"])
            self.assertEqual(项["来源"], "周期探针检查")
            self.assertFalse(项["证据写入失败"])
        self.assertEqual(状态["提供者"]["LibreOffice"]["版本"], "9.9.9")
        self.assertEqual(状态["提供者"]["textutil"]["版本"], macOS版本())

    def test_查询健康状态含标准错误摘要(self):
        监督 = 系统提供者健康监督(
            周期秒=0.5, 探针函数=_失败探针函数(),
            证据文件=_临时证据文件())
        监督.执行一次周期检查()
        项 = 监督.查询健康状态()["提供者"]["LibreOffice"]
        self.assertFalse(项["健康"])
        self.assertEqual(项["标准错误摘要"], "模拟失败输出")
        self.assertEqual(项["错误码"], "退出码非零")
        self.assertEqual(项["错误摘要"], "LibreOffice 退出码 1")


class Test健康监督诊断证据(unittest.TestCase):
    """每次探针结果写入 健康证据.jsonl（时间/提供者/健康/退出码/版本/标准错误摘要）。"""

    def test_证据写入字段齐全(self):
        证据文件 = _临时证据文件()
        监督 = 系统提供者健康监督(
            周期秒=0.5, 探针函数=_成功探针函数(),
            证据文件=证据文件)
        监督.执行一次周期检查()
        self.assertTrue(证据文件.is_file())
        行表 = 证据文件.read_text(encoding="utf-8").strip().splitlines()
        self.assertEqual(len(行表), 2)  # LibreOffice + textutil 各一行
        for 行 in 行表:
            记录 = json.loads(行)
            for 字段 in ("时间", "提供者", "健康", "错误码", "退出码", "版本",
                         "标准错误摘要", "诊断", "成功", "耗时秒",
                         "错误摘要", "可重试", "来源"):
                self.assertIn(字段, 记录, f"证据缺少字段: {字段}")
            self.assertTrue(记录["时间"])
            self.assertTrue(记录["健康"])
            self.assertEqual(记录["退出码"], 0)
            self.assertTrue(记录["成功"])
            self.assertEqual(记录["耗时秒"], 0.0)
            self.assertEqual(记录["错误摘要"], "")
            self.assertFalse(记录["可重试"])
            self.assertEqual(记录["来源"], "周期探针检查")
        # LibreOffice 版本取探针版本；textutil 无独立版本号取 macOS 版本
        记录表 = [json.loads(行) for 行 in 行表]
        self.assertEqual(
            next(记录 for 记录 in 记录表
                 if 记录["提供者"] == "LibreOffice")["版本"], "9.9.9")
        self.assertEqual(
            next(记录 for 记录 in 记录表
                 if 记录["提供者"] == "textutil")["版本"], macOS版本())

    def test_失败证据写入健康false(self):
        证据文件 = _临时证据文件()
        监督 = 系统提供者健康监督(
            周期秒=0.5, 探针函数=_失败探针函数(),
            证据文件=证据文件)
        监督.执行一次周期检查()
        记录表 = [json.loads(行) for 行 in
                  证据文件.read_text(encoding="utf-8").strip().splitlines()]
        self.assertTrue(all(记录["健康"] is 假 for 记录 in 记录表))
        self.assertTrue(all(记录["标准错误摘要"] == "模拟失败输出"
                            for 记录 in 记录表))

    def test_证据文件不可写主进程不崩溃(self):
        """证据路径不可写 → 静默跳过，探针与查询不受影响。"""
        证据文件 = Path("/dev/null/不存在子目录") / "健康证据.jsonl"
        监督 = 系统提供者健康监督(
            周期秒=0.5, 探针函数=_成功探针函数(),
            证据文件=证据文件)
        结果 = 监督.执行一次周期检查()
        self.assertFalse(结果["成功"])
        self.assertEqual(结果["健康提供者数"], 2)

    def test_证据写入失败阻断成功(self):
        """证据文件路径不可写 → 结果不能报告成功。"""
        证据文件 = Path("/dev/null/不存在子目录") / "健康证据.jsonl"
        监督 = 系统提供者健康监督(
            周期秒=0.5, 探针函数=_成功探针函数(),
            证据文件=证据文件)
        结果 = 监督.执行一次周期检查()
        self.assertFalse(结果["成功"])
        self.assertEqual(结果["健康提供者数"], 2)
        self.assertGreaterEqual(结果["证据写入失败提供者数"], 1)
        for 提供者名 in ("LibreOffice", "textutil"):
            状态 = 结果["提供者"][提供者名]
            self.assertTrue(状态["健康"])
            self.assertTrue(状态["成功"])
            self.assertEqual(状态["错误码"], "")
            self.assertTrue(状态["证据写入失败"])
            self.assertIn("证据写入失败", 状态["错误摘要"])
        # 健康/错误码/成功 不受影响：不得因证据写入失败把提供者标记不可用
        self.assertEqual(结果["证据写入失败提供者数"], 2)

    def test_证据行与查询状态一致性(self):
        """同一次检查后，证据行与查询状态项的探针字段一致。"""
        证据文件 = _临时证据文件()
        监督 = 系统提供者健康监督(
            周期秒=0.5, 探针函数=_失败探针函数(),
            证据文件=证据文件)
        监督.执行一次周期检查()
        查询状态表 = 监督.查询健康状态()["提供者"]
        记录表 = [json.loads(行) for 行 in
                  证据文件.read_text(encoding="utf-8").strip().splitlines()]
        self.assertEqual(len(记录表), len(查询状态表))
        for 记录 in 记录表:
            状态项 = 查询状态表[记录["提供者"]]
            for 字段 in ("成功", "退出码", "错误码", "错误摘要", "可重试",
                         "耗时秒", "版本"):
                self.assertEqual(
                    记录[字段], 状态项[字段],
                    f"{记录['提供者']} 证据与状态字段不一致: {字段}")
            self.assertEqual(记录["来源"], "周期探针检查")
            self.assertEqual(状态项["来源"], "周期探针检查")


class Test健康监督真实探针(unittest.TestCase):
    """真实 LibreOffice/textutil 独立子进程探针成功（环境缺失时跳过）。"""

    def test_真实LibreOffice探针成功(self):
        if not 查找LibreOffice命令():
            self.skipTest("LibreOffice 不可用")
        监督 = 系统提供者健康监督(证据文件=_临时证据文件())
        结果 = 监督.执行一次周期检查()
        项 = 结果["提供者"]["LibreOffice"]
        self.assertTrue(项["健康"], 项["诊断"])
        self.assertEqual(项["退出码"], 0)
        self.assertRegex(项["版本"], r"^\d+(?:\.\d+)+$")

    def test_真实textutil探针成功(self):
        if not 查找textutil命令():
            self.skipTest("textutil 不可用")
        监督 = 系统提供者健康监督(证据文件=_临时证据文件())
        结果 = 监督.执行一次周期检查()
        项 = 结果["提供者"]["textutil"]
        self.assertTrue(项["健康"], 项["诊断"])
        self.assertEqual(项["退出码"], 0)
        self.assertEqual(项["版本"], macOS版本())

    def test_默认探针清单配置(self):
        提供者表 = [定义["提供者"] for 定义 in 默认探针清单]
        self.assertEqual(提供者表, ["LibreOffice", "textutil"])
        self.assertEqual(默认探针清单[0]["版本参数"], "--version")
        self.assertEqual(默认探针清单[1]["版本参数"], "-help")


if __name__ == "__main__":
    unittest.main()
