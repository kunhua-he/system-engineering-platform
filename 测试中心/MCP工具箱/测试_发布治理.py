"""第二十六阶段 wp5 发布治理工具集测试。

真实路径：发布证据写入/读取、激活指针 CAS（陈旧令牌拒绝/正确切换/回滚切换）、
依赖裁决（真实 文件管理 模块通过/伪造依赖缺口）。
发布门禁较重：本包用轻量命令桩验证返回码透传与输出解析（如实标注），
完整门禁执行由主协调阶段收口负责。
"""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

from 公共契约.包声明 import 包声明

测试根目录 = Path(__file__).resolve().parents[2]
if str(测试根目录) not in sys.path:
    sys.path.insert(0, str(测试根目录))

模块路径 = 测试根目录 / "MCP工具箱" / "发布治理.py"
规格 = importlib.util.spec_from_file_location("系统工程平台发布治理", 模块路径)
assert 规格 and 规格.loader
发布治理 = importlib.util.module_from_spec(规格)
sys.modules[规格.name] = 发布治理  # 注册模块，dataclass 需要从 sys.modules 解析类型
规格.loader.exec_module(发布治理)

# 验证历史.jsonl 中真实存在的提交（历史迁移输入的最近成功记录）
真实验证提交 = "561583d03da2d9f4113eba48324f13bc99c94d7d"


def _写指针(环境目录: Path, *, 摘要: str = "旧制品摘要", 版本: int = 2, 令牌: int = 2) -> None:
    (环境目录 / "当前.json").write_text(json.dumps({
        "摘要sha256": 摘要[:16], "制品目录": f"平台客户端-{摘要[:16]}",
        "制品摘要": 摘要, "版本": 版本, "栅栏令牌": 令牌,
    }, ensure_ascii=False), encoding="utf-8")


def _读指针(环境目录: Path) -> dict:
    return json.loads((环境目录 / "当前.json").read_text(encoding="utf-8"))


class 发布证据测试(unittest.TestCase):
    def test_生成发布证据结构化追加(self) -> None:
        with tempfile.TemporaryDirectory() as 临时目录:
            结果1 = 发布治理.生成发布证据(
                "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "门禁验证", 0, "指纹A", 证据目录=临时目录)
            self.assertTrue(结果1.成功)
            self.assertEqual(结果1.数据["条目数"], 1)
            self.assertEqual(Path(结果1.数据["路径"]).name, "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.json")
            结果2 = 发布治理.生成发布证据(
                "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "激活指针切换", 0, "指纹B", 证据目录=临时目录)
            self.assertTrue(结果2.成功)
            self.assertEqual(结果2.数据["条目数"], 2)
            数据 = json.loads((Path(临时目录) / "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.json").read_text(encoding="utf-8"))
            self.assertEqual(数据["提交"], "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa")
            self.assertEqual(len(数据["条目"]), 2)
            self.assertEqual(数据["条目"][0]["名称"], "门禁验证")
            self.assertEqual(数据["条目"][1]["退出码"], 0)

    def test_非法提交拒绝且错误码为参数无效(self) -> None:
        with tempfile.TemporaryDirectory() as 临时目录:
            for 非法值 in ["abc123", "test", "../逃逸", "", "A" * 40, "a" * 39]:
                结果 = 发布治理.生成发布证据(
                    非法值, "门禁验证", 0, "指纹A", 证据目录=临时目录)
                self.assertFalse(结果.成功, f"{非法值!r} 应被拒绝")
                self.assertEqual(结果.错误码, 发布治理.参数无效, f"{非法值!r}")
                self.assertFalse((Path(临时目录) / f"{非法值}.json").exists())
            拒绝 = 发布治理.切换激活指针(
                "新摘要目标", 1, 环境目录参数=临时目录,
                提交="../逃逸", 证据目录参数=Path(临时目录) / "证据")
            self.assertFalse(拒绝.成功)
            self.assertEqual(拒绝.错误码, 发布治理.参数无效)

    def test_检查发布证据命中与无证据拒绝(self) -> None:
        with tempfile.TemporaryDirectory() as 临时目录:
            证据路径 = Path(临时目录) / "验证历史.jsonl"
            证据路径.write_text(json.dumps({
                "名称": "门禁验证", "退出码": 0, "提交": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                "工作区指纹": "指纹X", "时间": "t", "命令": [],
            }, ensure_ascii=False) + "\n" + json.dumps({
                "名称": "失败验证", "退出码": 1, "提交": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                "工作区指纹": "指纹Y", "时间": "t", "命令": [],
            }, ensure_ascii=False) + "\n", encoding="utf-8")
            命中 = 发布治理.检查发布证据("aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", 证据路径=证据路径)
            self.assertTrue(命中.成功)
            self.assertEqual(命中.数据["名称"], "门禁验证")
            self.assertEqual(命中.数据["退出码"], 0)
            self.assertEqual(命中.数据["指纹"], "指纹X")
            拒绝 = 发布治理.检查发布证据("不存在提交", 证据路径=证据路径)
            self.assertFalse(拒绝.成功)
            self.assertEqual(拒绝.错误码, 发布治理.无证据)

    def test_检查发布证据真实验证历史(self) -> None:
        命中 = 发布治理.检查发布证据(真实验证提交)
        self.assertTrue(命中.成功)
        self.assertEqual(命中.数据["退出码"], 0)
        self.assertTrue(命中.数据["名称"])
        self.assertTrue(命中.数据["指纹"])

    def test_检查发布证据失败记录不算证据(self) -> None:
        with tempfile.TemporaryDirectory() as 临时目录:
            证据路径 = Path(临时目录) / "验证历史.jsonl"
            证据路径.write_text(json.dumps({
                "名称": "失败验证", "退出码": 1, "提交": "bad123",
                "工作区指纹": "指纹Z", "时间": "t",
            }, ensure_ascii=False) + "\n", encoding="utf-8")
            拒绝 = 发布治理.检查发布证据("bad123", 证据路径=证据路径)
            self.assertFalse(拒绝.成功)
            self.assertEqual(拒绝.错误码, 发布治理.无证据)


class 激活指针测试(unittest.TestCase):
    def test_陈旧令牌拒绝(self) -> None:
        with tempfile.TemporaryDirectory() as 临时目录:
            环境 = Path(临时目录)
            _写指针(环境, 令牌=2)
            结果 = 发布治理.切换激活指针(
                "新摘要目标", 1, 环境目录参数=临时目录,
                提交="cccccccccccccccccccccccccccccccccccccccc", 证据目录参数=Path(临时目录) / "证据")
            self.assertFalse(结果.成功)
            self.assertEqual(结果.错误码, 发布治理.陈旧令牌)
            指针 = _读指针(环境)
            self.assertEqual(指针["栅栏令牌"], 2)
            self.assertEqual(指针["版本"], 2)

    def test_正确切换(self) -> None:
        with tempfile.TemporaryDirectory() as 临时目录:
            环境 = Path(临时目录)
            _写指针(环境, 令牌=2)
            结果 = 发布治理.切换激活指针(
                "新摘要目标", 2, 环境目录参数=临时目录,
                提交="cccccccccccccccccccccccccccccccccccccccc", 证据目录参数=Path(临时目录) / "证据")
            self.assertTrue(结果.成功)
            指针 = _读指针(环境)
            self.assertEqual(指针["摘要sha256"], "新摘要目标"[:16])
            self.assertEqual(指针["制品摘要"], "新摘要目标")
            self.assertEqual(指针["版本"], 3)
            self.assertEqual(指针["栅栏令牌"], 3)
            证据文件 = Path(临时目录) / "证据" / "cccccccccccccccccccccccccccccccccccccccc.json"
            self.assertTrue(证据文件.is_file())
            证据 = json.loads(证据文件.read_text(encoding="utf-8"))
            self.assertEqual(证据["条目"][0]["名称"], "激活指针切换: v2→v3")

    def test_回滚切换(self) -> None:
        with tempfile.TemporaryDirectory() as 临时目录:
            环境 = Path(临时目录)
            _写指针(环境, 摘要="原始摘要", 令牌=2)
            首次 = 发布治理.切换激活指针(
                "新摘要目标", 2, 环境目录参数=临时目录,
                提交="cccccccccccccccccccccccccccccccccccccccc", 证据目录参数=Path(临时目录) / "证据")
            self.assertTrue(首次.成功)
            回滚 = 发布治理.切换激活指针(
                "原始摘要", 3, 环境目录参数=临时目录,
                提交="cccccccccccccccccccccccccccccccccccccccc", 证据目录参数=Path(临时目录) / "证据")
            self.assertTrue(回滚.成功)
            指针 = _读指针(环境)
            self.assertEqual(指针["摘要sha256"], "原始摘要"[:16])
            self.assertEqual(指针["版本"], 4)
            self.assertEqual(指针["栅栏令牌"], 4)

    def test_指针缺失拒绝(self) -> None:
        with tempfile.TemporaryDirectory() as 临时目录:
            结果 = 发布治理.切换激活指针(
                "新摘要目标", 1, 环境目录参数=临时目录,
                提交="cccccccccccccccccccccccccccccccccccccccc", 证据目录参数=Path(临时目录) / "证据")
            self.assertFalse(结果.成功)
            self.assertEqual(结果.错误码, 发布治理.指针缺失)


class 依赖裁决测试(unittest.TestCase):
    def test_真实文件管理模块通过(self) -> None:
        结果 = 发布治理.依赖裁决("模块库.文件管理")
        self.assertTrue(结果.成功)
        self.assertEqual(结果.错误码, "")
        self.assertIn("裁决通过", 结果.消息)

    def test_伪造依赖缺口(self) -> None:
        伪造声明 = 包声明(
            包id="伪造.模块", 名称="伪造模块", 类型="模块", 版本="1.0.0",
            依赖=[{"能力": "不存在的.能力", "版本": ">=1.0.0"}],
        )
        结果 = 发布治理.校验依赖闭包(伪造声明)
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, 发布治理.裁决失败)
        self.assertGreater(len(结果.数据["缺口"]), 0)
        self.assertTrue(any("不存在的.能力" in 缺口 for 缺口 in 结果.数据["缺口"]))

    def test_不存在的包拒绝(self) -> None:
        结果 = 发布治理.依赖裁决("不存在的.包id")
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, 发布治理.裁决失败)


class 发布门禁桩测试(unittest.TestCase):
    def test_门禁桩返回码透传(self) -> None:
        # 桩：轻量命令透传，验证返回码/发布状态解析；完整门禁由阶段收口执行
        结果 = 发布治理.运行发布门禁(
            命令列表=["python3.14", "-c", "print('发布状态: 通过')"], 超时秒=30)
        self.assertTrue(结果.成功)
        self.assertEqual(结果.数据["退出码"], 0)
        self.assertEqual(结果.数据["发布状态"], "通过")
        self.assertIn("发布状态: 通过", 结果.数据["输出尾部"])

    def test_门禁桩失败透传(self) -> None:
        结果 = 发布治理.运行发布门禁(
            命令列表=["python3.14", "-c", "import sys; sys.exit(3)"], 超时秒=30)
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, 发布治理.门禁失败)
        self.assertEqual(结果.数据["退出码"], 3)
        self.assertEqual(结果.数据["发布状态"], "未知")

    def test_门禁脚本真实存在(self) -> None:
        self.assertTrue(发布治理.发布门禁脚本.is_file())
        self.assertIn("开发工具/发布门禁/运行发布门禁.py",
                      str(发布治理.发布门禁脚本))


if __name__ == "__main__":
    unittest.main()
