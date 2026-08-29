import json
import threading
import time
import unittest
import urllib.request
import urllib.error
import urllib.parse

from 支持库.后端.HTTP服务支持库 import HTTP服务


class TestHTTP服务支持库(unittest.TestCase):
    def setUp(self):
        self.服务 = HTTP服务(并发上限=2)
        self.服务.注册能力("回显", lambda 参数: 参数.get("值"))
        self.端口 = self.服务.启动()

    def tearDown(self):
        self.服务.停止()

    def 请求(self, 路径, 数据=None):
        请求 = urllib.request.Request(f"http://127.0.0.1:{self.端口}{urllib.parse.quote(路径)}",
                                      data=(json.dumps(数据).encode() if 数据 is not None else None),
                                      method="POST" if 数据 is not None else "GET",
                                      headers={"Content-Type": "application/json"} if 数据 is not None else {})
        try:
            with urllib.request.urlopen(请求, timeout=2) as 响应:
                return 响应.status, json.loads(响应.read())
        except urllib.error.HTTPError as 错误:
            return 错误.code, json.loads(错误.read())

    def test_健康与能力调用(self):
        状态, 数据 = self.请求("/健康")
        self.assertEqual(状态, 200); self.assertTrue(数据["成功"])
        状态, 数据 = self.请求("/调用", {"能力id": "回显", "参数": {"值": 7}})
        self.assertEqual((状态, 数据["值"]), (200, 7))

    def test_未知能力与异常受控(self):
        状态, 数据 = self.请求("/调用", {"能力id": "不存在", "参数": {}})
        self.assertEqual((状态, 数据["错误码"]), (400, "能力不存在"))
        self.服务.注册能力("坏", lambda 参数: 1 / 0)
        状态, 数据 = self.请求("/调用", {"能力id": "坏", "参数": {}})
        self.assertEqual((状态, 数据["错误码"]), (500, "提供者异常"))

    def test_停止后端口可重绑(self):
        端口 = self.端口
        self.服务.停止()
        self.assertFalse(self.服务.已启动)
        self.服务.端口 = 端口
        self.服务.启动()
        self.assertEqual(self.服务.实际端口, 端口)

    def test_请求体上限(self):
        self.服务.请求体上限 = 8
        状态, 数据 = self.请求("/调用", {"能力id": "回显", "参数": {"值": "过长"}})
        self.assertEqual((状态, 数据["错误码"]), (413, "请求过大"))

    def test_停止与并发请求重叠不泄漏许可(self):
        """停机期间正在执行的请求仍释放其所属服务器的并发许可。"""
        进入 = threading.Event()
        放行 = threading.Event()

        def 慢能力(参数):
            进入.set()
            放行.wait(1)
            return "完成"

        self.服务.注册能力("慢", 慢能力)
        结果盒 = []

        def 请求线程():
            结果盒.append(self.请求("/调用", {"能力id": "慢", "参数": {}}))

        线程 = threading.Thread(target=请求线程, daemon=True)
        线程.start()
        self.assertTrue(进入.wait(1))
        self.服务.停止()
        放行.set()
        线程.join(2)
        self.assertFalse(线程.is_alive())
        self.assertEqual(结果盒[0][0], 200)

    def test_畸形ContentLength返回参数错误(self):
        请求 = urllib.request.Request(
            f"http://127.0.0.1:{self.端口}{urllib.parse.quote('/调用')}", data=b"{}", method="POST",
            headers={"Content-Type": "application/json", "Content-Length": "abc"},
        )
        with self.assertRaises(urllib.error.HTTPError) as 上下文:
            urllib.request.urlopen(请求, timeout=2)
        self.assertEqual(上下文.exception.code, 400)
        数据 = json.loads(上下文.exception.read())
        self.assertEqual(数据["错误码"], "参数不合法")

    def test_旧能力调用路由拒绝(self):
        状态, 数据 = self.请求("/能力/调用", {"能力id": "回显", "参数": {"值": 1}})
        self.assertEqual(状态, 404)
        self.assertEqual(数据["错误码"], "路径不存在")


if __name__ == "__main__":
    unittest.main(verbosity=2)
