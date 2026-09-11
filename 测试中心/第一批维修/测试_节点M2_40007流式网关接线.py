"""M2：40007 同一 HTTP 网关的真实 SSE 流式接线测试。"""
from __future__ import annotations

import json
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request
import unittest
from pathlib import Path
from unittest.mock import patch

系统根 = Path(__file__).resolve().parents[2]
if str(系统根) not in sys.path:
    sys.path.insert(0, str(系统根))

from 运行核心.统一网关.本地网关 import 本地网关服务器
from 运行核心.统一网关.网关核心 import 网关核心


class 假审计:
    def __init__(self) -> None:
        self.记录表 = []

    def 记录(self, **参数):
        self.记录表.append(dict(参数))


class M2流式网关测试(unittest.TestCase):
    def setUp(self) -> None:
        self.审计 = 假审计()
        self.服务 = 本地网关服务器.创建测试服务器(
            网关核心实例=网关核心(审计实例=self.审计),
            端口=0,
            配置={"请求大小上限": 4 * 1024 * 1024},
        )
        成功, 消息 = self.服务.启动()
        self.assertTrue(成功, 消息)
        self.地址 = f"http://127.0.0.1:{self.服务.端口}"

    def tearDown(self) -> None:
        self.服务.优雅停止()

    def _请求(self, 数据: dict, 路径: str = "/网关/流式"):
        请求 = urllib.request.Request(
            self.地址 + urllib.parse.quote(路径),
            data=json.dumps(数据, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(请求, timeout=5) as 响应:
                return 响应.status, 响应.headers, 响应.read().decode("utf-8")
        except urllib.error.HTTPError as 错误:
            try:
                return 错误.code, 错误.headers, 错误.read().decode("utf-8")
            finally:
                错误.close()

    def test_同一40007服务返回真实SSE增量和完成事件(self) -> None:
        def 假流式生成对话(**参数):
            self.assertEqual(参数["句柄"], 123)
            self.assertEqual(参数["消息列表"], [{"role": "user", "content": "你好"}])
            self.assertIs(参数["流式输出"], True)
            yield {"类型": "增量", "文本": "你"}
            yield {"类型": "增量", "文本": "好"}
            yield {"类型": "完成", "完成原因": "stop"}

        with patch(
            "支持库.后端.大语言模型支持库.模型连接器.流式生成对话",
            side_effect=假流式生成对话,
        ) as 模型调用:
            状态, 头, 内容 = self._请求({
                "能力id": "大语言模型支持库.模型连接器.生成对话",
                "请求id": "m2-chat-1",
                "参数": {
                    "句柄": 123,
                    "消息列表": [{"role": "user", "content": "你好"}],
                    "流式输出": True,
                },
            })
        self.assertEqual(状态, 200)
        self.assertIn("text/event-stream", head_value(头, "Content-Type"))
        self.assertIn("event: 首个事件", 内容)
        self.assertIn("event: 增量事件", 内容)
        self.assertIn("event: 完成事件", 内容)
        self.assertIn('"文本":"你"', 内容)
        self.assertIn('"完成原因":"stop"', 内容)
        self.assertLess(内容.index("你"), 内容.index("好"))
        self.assertEqual(模型调用.call_count, 1)

    def test_上游错误按失败终态返回且不调用普通生成(self) -> None:
        def 假流式生成对话(**_参数):
            yield {"类型": "错误", "错误码": "上游错误", "错误说明": "夹具失败"}

        with patch(
            "支持库.后端.大语言模型支持库.模型连接器.流式生成对话",
            side_effect=假流式生成对话,
        ):
            状态, _头, 内容 = self._请求({
                "能力id": "大语言模型支持库.模型连接器.生成对话",
                "请求id": "m2-error-1",
                "参数": {"句柄": 123, "消息列表": [{"role": "user", "content": "x"}], "流式输出": True},
            })
        self.assertEqual(状态, 200)
        self.assertIn("失败事件", 内容)
        self.assertIn("上游错误", 内容)
        self.assertIn("夹具失败", 内容)

    def test_流式参数非真时在HTTP边界拒绝(self) -> None:
        状态, _头, 内容 = self._请求({
            "能力id": "大语言模型支持库.模型连接器.生成对话",
            "参数": {"句柄": 123, "消息列表": [{"role": "user", "content": "x"}], "流式输出": False},
        })
        self.assertEqual(状态, 400)
        self.assertIn("参数不合法", 内容)

    def test_生成参数经HTTP透传到流式连接器(self) -> None:
        """流式入口不再丢弃 温度/最大令牌数/工具/响应格式，HTTP 层原样转交。"""
        工具 = [{"type": "function", "function": {"name": "查库存"}}]
        收到 = {}

        def 假流式生成对话(**参数):
            收到.update(参数)
            yield {"类型": "完成", "完成原因": "stop"}

        with patch(
            "支持库.后端.大语言模型支持库.模型连接器.流式生成对话",
            side_effect=假流式生成对话,
        ):
            状态, _头, 内容 = self._请求({
                "能力id": "大语言模型支持库.模型连接器.生成对话",
                "请求id": "m2-params-1",
                "参数": {
                    "句柄": 123,
                    "消息列表": [{"role": "user", "content": "带参"}],
                    "流式输出": True,
                    "温度": 0.3,
                    "最大令牌数": 64,
                    "工具": 工具,
                    "响应格式": {"type": "json_object"},
                },
            })
        self.assertEqual(状态, 200)
        self.assertIn("完成事件", 内容)
        self.assertEqual(收到.get("温度"), 0.3)
        self.assertEqual(收到.get("最大令牌数"), 64)
        self.assertEqual(收到.get("工具"), 工具)
        self.assertEqual(收到.get("响应格式"), {"type": "json_object"})

    def test_不传生成参数时不向下游传这四个键(self) -> None:
        收到 = {}

        def 假流式生成对话(**参数):
            收到.update(参数)
            yield {"类型": "完成", "完成原因": "stop"}

        with patch(
            "支持库.后端.大语言模型支持库.模型连接器.流式生成对话",
            side_effect=假流式生成对话,
        ):
            状态, _头, _内容 = self._请求({
                "能力id": "大语言模型支持库.模型连接器.生成对话",
                "请求id": "m2-params-2",
                "参数": {"句柄": 123, "消息列表": [{"role": "user", "content": "默认"}], "流式输出": True},
            })
        self.assertEqual(状态, 200)
        for 键 in ("温度", "最大令牌数", "工具", "响应格式"):
            self.assertIsNone(收到.get(键), f"未传 {键} 却传了下游值 {收到.get(键)!r}")

    def test_客户端身份不能伪造(self) -> None:
        状态, _头, 内容 = self._请求({
            "能力id": "大语言模型支持库.模型连接器.生成对话",
            "用户id": "伪造用户",
            "参数": {"句柄": 123, "消息列表": [{"role": "user", "content": "x"}], "流式输出": True},
        })
        self.assertEqual(状态, 403)
        self.assertIn("身份必须由网关凭证注入", 内容)
    def test_不存在流式请求的取消返回结构化404(self) -> None:
        状态, _头, 内容 = self._请求({"请求id": "不存在"}, "/网关/流式/取消")
        self.assertEqual(状态, 404)
        self.assertIn("句柄无效", 内容)


def head_value(头, 名称: str) -> str:
    return str(头.get(名称, ""))


if __name__ == "__main__":
    unittest.main(verbosity=2)
