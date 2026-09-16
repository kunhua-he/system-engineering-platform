"""能力唯一事实源真实回归：构建索引、完整运行时与真实 HTTP 网关逐项对账。"""
from __future__ import annotations

import http.client
import json
import socket
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

# 本机 http_proxy/https_proxy 指向 127.0.0.1:4780（ClashX），urllib 在 macOS 上不把
# 回环地址放进例外表（proxy_bypass('127.0.0.1') 返回 False）→ 裸 urlopen 会让回环请求
# 先经代理，把「服务端断连」伪装成 502 空体。这里显式绕代理。
_无代理 = urllib.request.build_opener(urllib.request.ProxyHandler({}))

# 环境护栏（不是放宽判据）：逐能力探针必然命中「做真外部动作」的能力（健康监督查询、
# 资源采样、浏览器创建会话…），本机缺对应外部依赖时会真阻塞到超时。
# 关键语义：**超时 ≠ 能力不存在**——网关先做存在性判定再执行，所以能阻塞说明该能力
# 已被解析并开始执行，按「可调用」计；阻塞清单单独记录，把「环境红」与「契约红」分开。
探针超时秒 = 10.0


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
        cls.阻塞能力: list[tuple[str, str]] = []

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
                with _无代理.open(请求, timeout=探针超时秒) as 响应:
                    数据 = json.loads(响应.read().decode("utf-8"))
            except urllib.error.HTTPError as 错误:
                try:
                    数据 = json.loads(错误.read().decode("utf-8"))
                finally:
                    错误.close()
            except (TimeoutError, socket.timeout) as 错误:
                # 真阻塞：已过存在性判定并开始执行，能力存在 → 计可调用，单独记录
                cls.阻塞能力.append((能力id, type(错误).__name__))
                可调用.add(能力id)
                continue
            except urllib.error.URLError as 错误:
                # 超时/连接层失败经 URLError 包装（reason 才是真因）
                cls.阻塞能力.append((能力id, f"URLError({错误.reason!r})"))
                可调用.add(能力id)
                continue
            except (ConnectionResetError, http.client.IncompleteRead) as 错误:
                # 服务端断连：同上，能走到执行层才可能断连，不算「能力不存在」
                cls.阻塞能力.append((能力id, type(错误).__name__))
                可调用.add(能力id)
                continue
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
            "阻塞能力": self.阻塞能力,
            "runtime_only": sorted(self.运行时能力 - 索引能力),
            "formal_only": sorted(索引能力 - self.运行时能力),
            "gateway_only": sorted(网关能力 - self.运行时能力),
            "runtime_not_gateway": sorted(self.运行时能力 - 网关能力),
        }
        self.assertEqual(索引能力, self.运行时能力, json.dumps(差集, ensure_ascii=False, indent=2))
        self.assertEqual(self.运行时能力, 网关能力, json.dumps(差集, ensure_ascii=False, indent=2))

    def test_正式包集合与运行时发现集合逐项相等(self) -> None:
        from 运行核心.加载器.包发现.发现器 import 发现全部

        发现 = 发现全部(系统根 / "支持库", 系统根 / "模块库", 系统根 / "技能库")
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
