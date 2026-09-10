"""网关安全边界负测：伪造身份 403 / 错误凭证 401 / 健康路径免凭证。

真实 HTTP 请求验证 本地网关 的身份与凭证收紧：
- 禁止客户端身份 默认收紧：请求体带 项目id/用户id/会话id/任务id → 403
- 显式 禁止客户端身份=False 的内部夹具才允许客户端身份
- 要求凭证 时错误/缺失凭证 → 401；健康路径在免凭证配置下可访问
"""

from __future__ import annotations

import json
import sys
import unittest
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

if str(Path(__file__).resolve().parents[2]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from 运行核心.统一网关.网关核心 import 网关核心
from 运行核心.统一网关.本地网关 import 本地网关服务器
from 公共契约.基础类型.结果类型 import 结果


class 测试后端:
    """最小后端：实现 健康检查 + 资源状态 供网关调用。"""

    def 健康检查(self):
        return 结果.成功结果({"状态": "正常"})

    def 资源状态(self, 句柄id, *, 项目id="", 所有者=""):
        return {"成功": True, "值": {"状态": "有效", "句柄": 句柄id}}


def _POST(网关, 请求体: dict, 凭证: str = "") -> tuple[int, dict]:
    """向网关发真实 POST，返回 (状态码, JSON)。

    凭证经 Authorization: Bearer 头传递（网关 提取访问凭证 同时支持
    Authorization Bearer 与 X-系统凭证；HTTP 头名必须 ASCII）。
    """
    端点 = f"http://127.0.0.1:{网关.端口}/网关/调用"
    请求 = urllib.request.Request(
        urllib.parse.quote(端点, safe=":/@._-"),
        data=json.dumps(请求体).encode(),
        method="POST",
        headers={"Content-Type": "application/json",
                 **({"Authorization": f"Bearer {凭证}"} if 凭证 else {})},
    )
    try:
        with urllib.request.urlopen(请求, timeout=5) as 响应:
            return 响应.status, json.loads(响应.read().decode())
    except urllib.error.HTTPError as 错误:
        try:
            return 错误.code, json.loads(错误.read().decode())
        finally:
            错误.close()


class 网关身份负测(unittest.TestCase):
    """禁止客户端身份 默认收紧：客户端身份字段被 403 拒绝。"""

    @classmethod
    def setUpClass(cls):
        cls.后端 = 测试后端()
        cls.网关 = 本地网关服务器(
            网关核心实例=网关核心(cls.后端), 端口=0,
            配置={"要求凭证": False, "禁止客户端身份": True},
        )
        成功, 消息 = cls.网关.启动()
        if not 成功:
            raise RuntimeError(f"网关启动失败: {消息}")

    @classmethod
    def tearDownClass(cls):
        cls.网关.优雅停止()

    def test_携带项目id被403拒绝(self):
        状态码, 返回 = _POST(self.网关, {
            "操作": "资源状态", "句柄": 1,
            "项目id": "项目甲", "用户id": "用户甲",
        })
        self.assertEqual(状态码, 403)
        self.assertEqual(返回["错误码"], "权限不足")

    def test_携带用户id被403拒绝(self):
        状态码, 返回 = _POST(self.网关, {
            "操作": "资源状态", "句柄": 1, "用户id": "用户甲",
        })
        self.assertEqual(状态码, 403)
        self.assertIn("身份必须由网关凭证注入", 返回["错误说明"])

    def test_不带身份字段的调用放行(self):
        # 无身份字段不触发禁止客户端身份；后端返回正常
        状态码, 返回 = _POST(self.网关, {"操作": "资源状态", "句柄": 1})
        self.assertEqual(状态码, 200)
        self.assertTrue(返回["成功"])

    def test_健康路径免凭证可访问(self):
        请求 = urllib.request.Request(
            urllib.parse.quote(f"http://127.0.0.1:{self.网关.端口}/健康", safe=":/@._-"))
        with urllib.request.urlopen(请求, timeout=5) as 响应:
            self.assertEqual(响应.status, 200)


class 网关内部夹具放行(unittest.TestCase):
    """显式 禁止客户端身份=False 的内部夹具允许客户端身份。"""

    @classmethod
    def setUpClass(cls):
        cls.后端 = 测试后端()
        cls.网关 = 本地网关服务器(
            网关核心实例=网关核心(cls.后端), 端口=0,
            配置={"要求凭证": False, "禁止客户端身份": False},
        )
        成功, 消息 = cls.网关.启动()
        if not 成功:
            raise RuntimeError(f"网关启动失败: {消息}")

    @classmethod
    def tearDownClass(cls):
        cls.网关.优雅停止()

    def test_内部夹具携带身份放行(self):
        状态码, 返回 = _POST(self.网关, {
            "操作": "资源状态", "句柄": 1,
            "项目id": "项目甲", "用户id": "用户甲",
        })
        self.assertEqual(状态码, 200)
        self.assertTrue(返回["成功"])


class 网关凭证负测(unittest.TestCase):
    """要求凭证 时错误/缺失凭证被 401 拒绝。"""

    凭证环境变量 = "系统库网关凭证_负测专用"

    @classmethod
    def setUpClass(cls):
        import os
        cls.原环境值 = os.environ.get(cls.凭证环境变量)
        os.environ[cls.凭证环境变量] = "测试凭证-abc123"
        cls.后端 = 测试后端()
        cls.网关 = 本地网关服务器(
            网关核心实例=网关核心(cls.后端), 端口=0,
            配置={"要求凭证": True, "凭证环境变量": cls.凭证环境变量},
        )
        成功, 消息 = cls.网关.启动()
        if not 成功:
            raise RuntimeError(f"网关启动失败: {消息}")

    @classmethod
    def tearDownClass(cls):
        import os
        if cls.原环境值 is None:
            os.environ.pop(cls.凭证环境变量, None)
        else:
            os.environ[cls.凭证环境变量] = cls.原环境值
        cls.网关.优雅停止()

    def test_缺失凭证被401拒绝(self):
        状态码, 返回 = _POST(self.网关, {"操作": "资源状态", "句柄": 1})
        self.assertEqual(状态码, 401)
        self.assertEqual(返回["错误码"], "权限不足")

    def test_伪造凭证被401拒绝(self):
        状态码, 返回 = _POST(self.网关, {"操作": "资源状态", "句柄": 1},
                             凭证="fake-credential-123")
        self.assertEqual(状态码, 401)
        self.assertEqual(返回["错误码"], "权限不足")


if __name__ == "__main__":
    unittest.main()
