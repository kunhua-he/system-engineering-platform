"""第十三阶段：HTTP 真实提供者测试（真实本地服务 + 真实 urllib 请求）。

真实场景：200+JSON / POST 数据回显 / 非200状态码 / 请求超时（服务端延迟>
客户端超时）/ 响应大小超上限截断 / 连接释放（含客户端断开后服务端释放）/
有限重试边界 / 停止后端口可重新绑定 / 停止优雅不等待慢请求。

运行：unset PYTHONPATH && python3.14 测试中心/第十三阶段/测试_HTTP提供者.py
"""

import json
import sys
import threading
import time
import unittest
from pathlib import Path

系统根 = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(系统根))  # 无条件置顶，防同名测试目录遮蔽真实包

from 平台控制面.提供者.HTTP提供者 import HTTP提供者


def 测试处理器(路径, 方法, 请求体):
    """真实处理器：/健康 JSON 回显、/延迟 慢响应、/大响应 超大响应、/慢 超慢。"""
    if 路径 == "/健康":
        数据 = json.dumps({"状态": "正常", "方法": 方法,
                          "收到": 请求体.decode("utf-8", "replace")}).encode("utf-8")
        return 200, 数据, {"Content-Type": "application/json"}
    if 路径 == "/延迟":
        time.sleep(1.5)
        return 200, "延迟完成", {}
    if 路径 == "/大响应":
        return 200, "大".encode("utf-8") * (256 * 1024), {}  # 512KB
    if 路径 == "/慢":
        time.sleep(3)
        return 200, "慢完成", {}
    return 500, "内部错误", {}


class TestHTTP提供者真实场景(unittest.TestCase):
    """HTTP 真实提供者：9 个真实场景，全部真实起服务、真实请求。"""

    def setUp(self):
        self.提供者 = HTTP提供者(重试次数=2, 重试退避基数=0.05)

    def tearDown(self):
        self.提供者.停止()

    def test_真实请求返回200和JSON(self):
        """场景1：随机端口起真实服务 → 真实请求返回 200 与 JSON。"""
        端口 = self.提供者.启动(测试处理器)
        self.assertGreater(端口, 0, "随机端口应大于 0")
        结果 = self.提供者.请求("/健康")
        self.assertTrue(结果["成功"], 结果["错误"])
        self.assertEqual(结果["状态码"], 200)
        self.assertEqual(json.loads(结果["响应"].decode("utf-8"))["状态"], "正常")
        self.assertFalse(结果["截断"])
        self.assertEqual(结果["重试次数"], 0)

    def test_POST携带数据并回显(self):
        """场景2：POST 真实携带请求体，服务端回显方法与数据。"""
        self.提供者.启动(测试处理器)
        结果 = self.提供者.请求("/健康", 方法="POST", 数据="真实数据体".encode("utf-8"))
        self.assertEqual(结果["状态码"], 200)
        回显 = json.loads(结果["响应"].decode("utf-8"))
        self.assertEqual(回显["方法"], "POST")
        self.assertEqual(回显["收到"], "真实数据体")

    def test_非200状态码原样返回(self):
        """场景3：处理器返回 500 → 客户端拿到 500 与错误体，不抛异常。"""
        self.提供者.启动(测试处理器)
        结果 = self.提供者.请求("/错误")
        self.assertFalse(结果["成功"])
        self.assertEqual(结果["状态码"], 500)
        self.assertIn("内部错误", 结果["响应"].decode("utf-8"))

    def test_请求超时路径(self):
        """场景4：服务端延迟 1.5s > 客户端超时 0.5s → 客户端真实超时。"""
        self.提供者.启动(测试处理器)
        开始 = time.monotonic()
        结果 = self.提供者.请求("/延迟", 超时秒=0.5)
        耗时 = time.monotonic() - 开始
        self.assertFalse(结果["成功"])
        self.assertIn("超时", 结果["错误"])
        self.assertLess(耗时, 1.2, "客户端应在超时阈值附近返回，而非等满服务端延迟")

    def test_响应大小超上限被截断(self):
        """场景5：512KB 响应、上限 1KB → 截断返回，不视为失败。"""
        self.提供者.启动(测试处理器)
        结果 = self.提供者.请求("/大响应", 响应上限=1024)
        self.assertTrue(结果["成功"], "截断不视为失败")
        self.assertTrue(结果["截断"])
        self.assertLessEqual(len(结果["响应"]), 1024)

    def test_连接释放(self):
        """场景6：正常请求完成后连接归零；客户端断开后服务端连接最终释放。"""
        self.提供者.启动(测试处理器)
        结果 = self.提供者.请求("/健康")
        self.assertTrue(结果["成功"])
        截止 = time.monotonic() + 2
        while self.提供者.活动连接数 > 0 and time.monotonic() < 截止:
            time.sleep(0.02)
        self.assertEqual(self.提供者.活动连接数, 0, "正常请求完成后服务端连接应已释放")
        结果 = self.提供者.请求("/延迟", 超时秒=0.5)  # 客户端超时断开
        self.assertFalse(结果["成功"])
        截止 = time.monotonic() + 3
        while self.提供者.活动连接数 > 0 and time.monotonic() < 截止:
            time.sleep(0.05)
        self.assertEqual(self.提供者.活动连接数, 0, "客户端断开后服务端连接应最终释放")

    def test_有限重试边界(self):
        """场景7：服务已停止 → 连接拒绝 → 有限重试 2 次后失败，不无限重试。"""
        端口 = self.提供者.启动(测试处理器)
        self.提供者.停止()
        结果 = self.提供者.请求("/健康")
        self.assertFalse(结果["成功"])
        self.assertEqual(结果["重试次数"], 2, "重试次数不得超过上限")
        self.assertIn("重试", 结果["错误"])

    def test_停止后端口可重新绑定(self):
        """场景8：停止释放端口 → 同一端口立即可重新绑定并服务。"""
        端口 = self.提供者.启动(测试处理器)
        self.提供者.停止()
        self.提供者.启动(测试处理器, 端口=端口)
        self.assertEqual(self.提供者.端口, 端口)
        结果 = self.提供者.请求("/健康")
        self.assertTrue(结果["成功"])
        self.assertEqual(结果["状态码"], 200)

    def test_停止优雅不等待慢请求(self):
        """场景9：进行中有慢请求时停止 → 快速返回，不阻塞等待。"""
        self.提供者.启动(测试处理器)
        慢结果 = {}

        def 后台慢请求():
            慢结果["值"] = self.提供者.请求("/慢", 超时秒=10)

        线程 = threading.Thread(target=后台慢请求, daemon=True)
        线程.start()
        time.sleep(0.3)  # 等服务端进入慢响应
        开始 = time.monotonic()
        self.提供者.停止()
        self.assertLess(time.monotonic() - 开始, 1.0, "停止应快速返回，不阻塞等待慢请求")
        线程.join(timeout=2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
