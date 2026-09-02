"""能力唯一事实源真实回归：构建索引、完整运行时与真实 HTTP 网关逐项对账。"""
from __future__ import annotations

import json
import sys
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import quote

系统根 = Path(__file__).resolve().parents[2]
if str(系统根) not in sys.path:
    sys.path.insert(0, str(系统根))

from 后端核心.后端核心 import 后端核心
from 开发工具.项目编译.正式包索引 import 构建索引
from 运行核心.统一网关.本地网关 import 本地网关服务器
from 运行核心.统一网关.网关核心 import 网关核心


class 测试能力唯一事实源(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.索引 = 构建索引(系统根)
        cls.后端 = 后端核心(系统根)
        启动 = cls.后端.启动()
        assert 启动.成功, 启动.错误说明
        cls.运行时能力 = set(cls.后端.注册表.能力id列表)
        cls.服务器 = 本地网关服务器.创建测试服务器(
            网关核心实例=网关核心(cls.后端), 端口=0)
        成功, 消息 = cls.服务器.启动()
        assert 成功, 消息
        cls.网关地址 = (
            f"http://127.0.0.1:{cls.服务器.端口}"
            + quote("/网关/调用", safe="/")
        )

    @classmethod
    def tearDownClass(cls) -> None:
        cls.服务器.优雅停止()
        cls.后端.优雅关闭()

    @classmethod
    def _网关可调用集合(cls) -> set[str]:
        可调用: set[str] = set()
        for 能力id in sorted(cls.运行时能力):
            请求 = urllib.request.Request(
                cls.网关地址,
                data=json.dumps({
                    "操作": "调用能力",
                    "能力id": 能力id,
                    "参数": {"__事实源探针__": True},
                }, ensure_ascii=False).encode("utf-8"),
                headers={"Content-Type": "application/json"},
            )
            try:
                with urllib.request.urlopen(请求, timeout=10) as 响应:
                    数据 = json.loads(响应.read().decode("utf-8"))
            except urllib.error.HTTPError as 错误:
                数据 = json.loads(错误.read().decode("utf-8"))
            if 数据.get("错误码") != "能力不存在":
                可调用.add(能力id)
        return 可调用

    def test_构建索引运行时注册表与网关可调用集合逐项相等(self) -> None:
        索引能力 = set(self.索引["能力所有者"])
        网关能力 = self._网关可调用集合()
        差集 = {
            "索引数量": len(索引能力),
            "运行时数量": len(self.运行时能力),
            "网关数量": len(网关能力),
            "runtime_only": sorted(self.运行时能力 - 索引能力),
            "formal_only": sorted(索引能力 - self.运行时能力),
            "gateway_only": sorted(网关能力 - self.运行时能力),
            "runtime_not_gateway": sorted(self.运行时能力 - 网关能力),
        }
        self.assertEqual(索引能力, self.运行时能力, json.dumps(差集, ensure_ascii=False, indent=2))
        self.assertEqual(self.运行时能力, 网关能力, json.dumps(差集, ensure_ascii=False, indent=2))

    def test_正式包集合与运行时发现集合逐项相等(self) -> None:
        from 运行核心.加载器.包发现.发现器 import 发现全部

        发现 = 发现全部(系统根 / "支持库", 系统根 / "模块库")
        运行包 = {声明.包id for 声明 in 发现.声明列表}
        正式包 = set(self.索引["支持库"]) | set(self.索引["模块库"])
        差集 = {
            "运行独有": sorted(运行包 - 正式包),
            "正式独有": sorted(正式包 - 运行包),
        }
        self.assertEqual(运行包, 正式包, json.dumps(差集, ensure_ascii=False, indent=2))

    def test_能力owner与运行时注册owner逐项相等且全局无重复(self) -> None:
        self.assertFalse(self.索引["能力冲突"], self.索引["能力冲突"])
        索引owner = self.索引["能力所有者"]
        运行时owner = {
            能力id: self.后端.注册表.获取(能力id).包id
            for 能力id in self.后端.注册表.能力id列表
        }
        self.assertEqual(索引owner, 运行时owner)


if __name__ == "__main__":
    unittest.main()
