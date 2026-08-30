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

from 运行核心.统一网关.流式HTTP import 流式HTTP服务器


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
            服务 = 流式HTTP服务器(端口=0, 凭证环境变量="流式测试凭证")
            服务.注册能力("流式.测试", lambda 参数: iter([{"片段": "完成"}]))
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


if __name__ == "__main__":
    unittest.main(verbosity=2)
