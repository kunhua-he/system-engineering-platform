"""浏览器宿主支持库定向回归：真实摘要闭合与页面输入安全边界。"""

from __future__ import annotations

import json
import sys
import unittest
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

系统根 = Path(__file__).resolve().parents[2]
if str(系统根) not in sys.path:
    sys.path.insert(0, str(系统根))


class Test浏览器宿主(unittest.TestCase):
    def test_完整性摘要与当前源码一致(self) -> None:
        from 开发工具.组件规范.完整性摘要 import 校验完整性摘要

        通过, 问题 = 校验完整性摘要(系统根 / "支持库" / "前端" / "浏览器宿主")
        self.assertTrue(通过, 问题)

    def test_页面标题说明转义且调用走中文路由(self) -> None:
        from 支持库.前端.浏览器宿主 import 启动网页服务

        服务, 地址 = 启动网页服务(
            标题='</title><script>window.标题注入=1</script>',
            页面说明='<img src=x onerror=window.说明注入=1>',
            端口=0,
        )
        try:
            with urllib.request.urlopen(地址 + "/", timeout=2) as 响应:
                页面 = 响应.read().decode("utf-8")
            self.assertNotIn("<script>window.标题注入=1</script>", 页面)
            self.assertNotIn("<img src=x onerror=window.说明注入=1>", 页面)

            请求 = urllib.request.Request(
                地址 + urllib.parse.quote("/api/调用"),
                data=json.dumps({"文本": "测试"}).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(请求, timeout=2) as 响应:
                结果 = json.loads(响应.read().decode("utf-8"))
            self.assertTrue(结果["成功"])
            self.assertEqual(结果["值"], "测试")
        finally:
            服务.shutdown()
            服务.server_close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
