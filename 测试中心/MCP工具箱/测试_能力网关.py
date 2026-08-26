"""HTTP 能力网关测试：启动临时端口网关，验证 搜索/契约/执行 与错误场景。

网关对外是纯 HTTP（不依赖 MCP 协议）；本测试用标准库 urllib 直接请求，
模拟任意语言/工具的 HTTP 客户端调用。
"""

from __future__ import annotations

import json
import sys
import threading
import unittest
import urllib.request
import urllib.parse
from http.server import ThreadingHTTPServer
from pathlib import Path

系统根 = Path(__file__).resolve().parents[2]
if str(系统根) not in sys.path:
    sys.path.insert(0, str(系统根))

from MCP工具箱.能力网关 import 能力网关请求处理器, 启动网关


class 能力网关测试(unittest.TestCase):
    """启动一个临时端口网关，用 urllib 验证三个接口与错误场景。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.服务器 = ThreadingHTTPServer(("127.0.0.1", 0), 能力网关请求处理器)
        cls.端口 = cls.服务器.server_address[1]
        cls.线程 = threading.Thread(target=cls.服务器.serve_forever, daemon=True)
        cls.线程.start()
        cls.基址 = f"http://127.0.0.1:{cls.端口}"

    @classmethod
    def tearDownClass(cls) -> None:
        cls.服务器.shutdown()
        cls.服务器.server_close()

    def _GET(self, 路径: str) -> dict:
        try:
            with urllib.request.urlopen(f"{self.基址}{路径}", timeout=10) as 响应:
                return json.loads(响应.read().decode("utf-8"))
        except urllib.error.HTTPError as 错误:
            return json.loads(错误.read().decode("utf-8"))

    def _POST(self, body: dict) -> dict:
        请求 = urllib.request.Request(
            f"{self.基址}{self._编码URL('/能力/执行')}",
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(请求, timeout=30) as 响应:
                return json.loads(响应.read().decode("utf-8"))
        except urllib.error.HTTPError as 错误:
            return json.loads(错误.read().decode("utf-8"))

    def _编码URL(self, 路径: str, 查询: dict[str, str] | None = None) -> str:
        """把中文路径/参数编码成标准 UTF-8 百分号 URL。"""
        url = urllib.parse.quote(路径)
        if 查询:
            url += "?" + urllib.parse.urlencode(查询)
        return url

    def test_搜索能力返回结果(self) -> None:
        数据 = self._GET(self._编码URL("/能力/搜索", {"关键词": "读取文件"}))
        self.assertTrue(数据["成功"])
        self.assertGreater(数据["数量"], 0)
        能力表 = 数据["能力表"]
        self.assertTrue(any("文件系统支持库.文件操作.读取文件" == 能力["能力id"] for 能力 in 能力表))
        # 每条能力带 能力id/名称/包id/参数
        for 能力 in 能力表:
            self.assertIn("能力id", 能力)
            self.assertIn("名称", 能力)
            self.assertIn("参数", 能力)

    def test_搜索无关键词返回全部(self) -> None:
        数据 = self._GET(self._编码URL("/能力/搜索"))
        self.assertTrue(数据["成功"])
        self.assertGreater(数据["数量"], 0)

    def test_查看契约返回参数与返回(self) -> None:
        数据 = self._GET(self._编码URL("/能力/契约/文件系统支持库.文件操作.读取文件"))
        self.assertTrue(数据["成功"])
        契约 = 数据["契约"]
        self.assertTrue(契约["找到"])
        self.assertEqual(契约["能力id"], "文件系统支持库.文件操作.读取文件")
        # 参数含 文件路径（必填）与 编码
        参数表 = {参数["名称"]: 参数 for 参数 in 契约["参数"]}
        self.assertIn("文件路径", 参数表)
        self.assertTrue(参数表["文件路径"]["必填"])

    def test_查看不存在的能力返回错误(self) -> None:
        数据 = self._GET(self._编码URL("/能力/契约/不存在.能力"))
        self.assertFalse(数据["成功"])
        self.assertEqual(数据["错误码"], "能力不存在")

    def test_执行能力返回统一结果与证据链(self) -> None:
        数据 = self._POST({
            "能力id": "文件系统支持库.文件操作.读取文件",
            "参数": {"文件路径": "公共契约/能力契约/契约.py", "编码": "utf-8"},
        })
        self.assertTrue(数据["成功"])
        self.assertIn("值", 数据)
        self.assertIn("证据链", 数据)
        # 证据链含请求id
        self.assertIn("请求id", str(数据["证据链"]))

    def test_执行缺能力id返回参数不合法(self) -> None:
        数据 = self._POST({})
        self.assertFalse(数据["成功"])
        self.assertEqual(数据["错误码"], "参数不合法")

    def test_未定义路由返回404(self) -> None:
        数据 = self._GET(self._编码URL("/没有这个路由"))
        self.assertFalse(数据["成功"])
        self.assertEqual(数据["错误码"], "路由不存在")


if __name__ == "__main__":
    unittest.main()
