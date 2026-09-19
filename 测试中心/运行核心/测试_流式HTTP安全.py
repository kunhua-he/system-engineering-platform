"""流式 HTTP 凭证、统一入口和审计边界回归。"""
from __future__ import annotations

import json
import os
import sys
import unittest
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from unittest.mock import patch

系统根 = Path(__file__).resolve().parents[2]
if str(系统根) not in sys.path:
    sys.path.insert(0, str(系统根))

from 运行核心.统一网关.传输.流式HTTP import HTTP流式通道, 流式HTTP服务器
from 公共契约.基础类型.结果类型 import 结果


class 假流式调用器:
    def 调用能力(self, 能力id: str, 参数: dict, **_) -> 结果:
        return 结果.成功结果(iter([{"片段": "完成"}]))


class Test流式HTTPS安全(unittest.TestCase):
    def 请求(self, 地址: str, 路径: str, 数据: dict, 凭证: str = ""):
        请求 = urllib.request.Request(
            地址 + urllib.parse.quote(路径),
            data=json.dumps(数据).encode("utf-8"),
            headers={"Content-Type": "application/json", **(
                {"Authorization": f"Bearer {凭证}"} if 凭证 else {})},
            method="POST",
        )
        try:
            with urllib.request.urlopen(请求, timeout=3) as 响应:
                return 响应.status, 响应.read().decode("utf-8")
        except urllib.error.HTTPError as 错误:
            try:
                return 错误.code, 错误.read().decode("utf-8")
            finally:
                错误.close()

    def test_生产默认缺凭证时启动阻断(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            服务 = 流式HTTP服务器(端口=0)
            成功, 消息 = 服务.启动()
        self.assertFalse(成功)
        self.assertIn("缺失凭证", 消息)

    def test_无凭证401_有凭证可建立流并写审计(self) -> None:
        with patch.dict(os.environ, {"流式测试凭证": "stream-test-token"}, clear=False):
            服务 = 流式HTTP服务器(
                端口=0, 凭证环境变量="流式测试凭证", 调用器=假流式调用器(),
            )
            成功, 消息 = 服务.启动()
            self.assertTrue(成功, 消息)
            地址 = f"http://127.0.0.1:{服务.端口}"
            try:
                状态, 内容 = self.请求(地址, "/网关/流式", {"能力id": "流式.测试"})
                self.assertEqual(状态, 401)
                self.assertIn("权限不足", 内容)
                状态, 内容 = self.请求(
                    地址, "/网关/流式", {"能力id": "流式.测试", "请求id": "安全测试"}, "stream-test-token")
                self.assertEqual(状态, 200)
                self.assertIn("首个事件", 内容)
                self.assertIn("完成事件", 内容)
                审计 = 服务.审计快照()
                self.assertTrue(any(not 项["成功"] and 项["错误码"] == "权限不足" for 项 in 审计))
                self.assertTrue(any(项["成功"] and 项["请求id"] == "安全测试" for 项 in 审计))
                self.assertTrue(all("凭证" not in 项 for 项 in 审计))
            finally:
                self.assertTrue(服务.优雅停止())
    def test_单事件payload超限转失败终态(self) -> None:
        通道 = HTTP流式通道(
            能力id="流式.测试", 单事件上限字节=1024, 累计事件上限字节=4096,
        )
        事件 = 通道.追加事件("中间事件", "x" * 5000)
        self.assertEqual(事件["事件类型"], "失败事件")
        self.assertTrue(通道.结束)
        self.assertEqual(事件["数据"]["错误码"], "事件负载超限")

    def test_累计payload超限清空旧队列并停止生产(self) -> None:
        通道 = HTTP流式通道(
            能力id="流式.测试", 单事件上限字节=4096, 累计事件上限字节=5000,
        )
        通道.追加事件("中间事件", "a" * 1500)
        终态 = 通道.追加事件("中间事件", "b" * 3500)
        self.assertEqual(终态["事件类型"], "失败事件")
        self.assertTrue(通道.结束)
        self.assertLessEqual(通道.累计事件字节数, 通道.累计事件上限字节)
        self.assertEqual(通道.事件队列[-1]["数据"]["错误码"], "事件负载超限")


if __name__ == "__main__":
    unittest.main(verbosity=2)
