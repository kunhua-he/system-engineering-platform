"""通用能力反馈接口定向 HTTP 回归。"""
from __future__ import annotations

import json
import os
import tempfile
import urllib.error
import urllib.request
from urllib.parse import quote
import unittest
from pathlib import Path
from unittest import mock

from 运行核心.统一网关.本地网关 import 本地网关服务器
from 运行核心.统一网关.网关核心 import 网关核心


class 假注册表:
    能力id列表 = ["样例.相加"]


class 假后端:
    注册表 = 假注册表()


def 请求(地址: str, 方法: str = "GET", 数据: dict | None = None,
        头部: dict[str, str] | None = None) -> tuple[int, dict]:
    正文 = None if 数据 is None else json.dumps(数据, ensure_ascii=False).encode("utf-8")
    请求对象 = urllib.request.Request(
        地址.replace("/平台/能力反馈", "/" + quote("平台/能力反馈")).replace("/状态", "/" + quote("状态")), data=正文, method=方法,
        headers={"Content-Type": "application/json", **(头部 or {})},
    )
    try:
        with urllib.request.urlopen(请求对象, timeout=5) as 响应:
            return 响应.status, json.loads(响应.read().decode("utf-8"))
    except urllib.error.HTTPError as 错误:
        try:
            return 错误.code, json.loads(错误.read().decode("utf-8"))
        finally:
            错误.close()


class Test能力反馈接口(unittest.TestCase):
    def setUp(self):
        self.临时 = tempfile.TemporaryDirectory(prefix="能力反馈HTTP_")
        self.根 = Path(self.临时.name)
        self.旧环境 = dict(os.environ)
        os.environ["测试反馈网关凭证"] = "gateway-test-credential"
        os.environ["测试反馈处理凭证"] = "platform-processor-secret"
        self.网关 = 本地网关服务器(
            网关核心实例=网关核心(后端核心=假后端()),
            地址="127.0.0.1", 端口=0,
            配置={
                "凭证环境变量": "测试反馈网关凭证",
                "反馈处理凭证环境变量": "测试反馈处理凭证",
                "反馈状态目录": str(self.根 / "平台状态"),
            },
        )
        成功, 消息 = self.网关.启动()
        self.assertTrue(成功, 消息)
        self.地址 = f"http://127.0.0.1:{self.网关.端口}"
        self.普通头 = {"X-System-Credential": "gateway-test-credential"}

    def tearDown(self):
        self.网关.优雅停止()
        os.environ.clear()
        os.environ.update(self.旧环境)
        self.临时.cleanup()

    def 反馈(self, 数据: dict) -> tuple[int, dict]:
        return 请求(self.地址 + "/平台/能力反馈", "POST", 数据, self.普通头)

    def 基础反馈(self) -> dict:
        return {
            "来源系统": "测试调用方", "来源版本": "1.0.0", "请求id": "请求-001",
            "能力id": "样例.相加", "契约版本": "1.0.0", "错误码": "提供者不可用",
            "错误说明": "测试失败", "HTTP状态码": 503,
            "请求摘要": {"参数": {"密码": "secret", "路径": "/tmp/a"}},
            "响应摘要": {"Authorization": "Bearer abcdefghijkl"}, "复现标识": "复现-001",
            "优先级": "高",
        }

    def test_未授权登记被拒(self):
        状态, 返回 = 请求(self.地址 + "/平台/能力反馈", "POST", self.基础反馈())
        self.assertEqual(状态, 401)
        self.assertEqual(返回["错误码"], "权限不足")

    def test_登记去重脱敏查询和非法能力(self):
        状态, 返回 = self.反馈(self.基础反馈())
        self.assertEqual(状态, 200)
        self.assertTrue(返回["成功"])
        反馈id = 返回["值"]["反馈id"]
        状态, 重复 = self.反馈(self.基础反馈())
        self.assertEqual(状态, 200)
        self.assertTrue(重复["值"]["是否重复"])
        self.assertEqual(重复["值"]["反馈id"], 反馈id)
        状态, 查询 = 请求(self.地址 + "/平台/能力反馈/" + 反馈id, "GET", None, self.普通头)
        self.assertEqual(状态, 200)
        记录 = 查询["值"]["记录表"][0]
        self.assertEqual(记录["请求摘要"]["参数"]["密码"], "[已脱敏]")
        self.assertEqual(记录["响应摘要"]["Authorization"], "[已脱敏]")
        错误反馈 = self.基础反馈()
        错误反馈.update({"请求id": "请求-002", "能力id": "不存在.能力", "复现标识": "复现-002"})
        状态, 返回 = self.反馈(错误反馈)
        self.assertEqual(状态, 404)
        self.assertEqual(返回["错误码"], "能力不存在")

    def test_缺字段和摘要超限被拒(self):
        数据 = self.基础反馈()
        del 数据["错误说明"]
        状态, 返回 = self.反馈(数据)
        self.assertEqual(状态, 400)
        self.assertEqual(返回["错误码"], "参数不合法")
        数据 = self.基础反馈()
        数据.update({"请求id": "请求-003", "复现标识": "复现-003", "请求摘要": {"超大": "填充" * 20000}})
        状态, 返回 = self.反馈(数据)
        self.assertEqual(状态, 400)
        self.assertEqual(返回["错误码"], "参数不合法")

    def test_状态迁移必须使用平台处理凭证并记录(self):
        _, 登记 = self.反馈(self.基础反馈())
        反馈id = 登记["值"]["反馈id"]
        状态, 返回 = 请求(
            self.地址 + f"/平台/能力反馈/{反馈id}/状态", "POST",
            {"状态": "已确认", "处理者": "平台Agent", "原因": "已接收"}, self.普通头)
        self.assertEqual(状态, 403)
        self.assertEqual(返回["错误码"], "权限不足")
        头部 = {**self.普通头, "X-Platform-Feedback-Credential": "platform-processor-secret"}
        状态, 返回 = 请求(
            self.地址 + f"/平台/能力反馈/{反馈id}/状态", "POST",
            {"状态": "已确认", "处理者": "平台Agent", "原因": "已接收"}, 头部)
        self.assertEqual(状态, 200)
        self.assertEqual(返回["值"]["状态"], "已确认")
        状态, 返回 = 请求(
            self.地址 + f"/平台/能力反馈/{反馈id}/状态", "POST",
            {"状态": "已修复", "处理者": "平台Agent", "原因": "直接越级"}, 头部)
        self.assertEqual(状态, 409)
        self.assertEqual(返回["错误码"], "状态迁移不允许")

    def test_服务重启后反馈仍可读(self):
        _, 登记 = self.反馈(self.基础反馈())
        反馈id = 登记["值"]["反馈id"]
        状态目录 = self.根 / "平台状态"
        self.网关.优雅停止()
        self.网关 = 本地网关服务器(
            网关核心实例=网关核心(后端核心=假后端()), 地址="127.0.0.1", 端口=0,
            配置={"凭证环境变量": "测试反馈网关凭证",
                  "反馈处理凭证环境变量": "测试反馈处理凭证",
                  "反馈状态目录": str(状态目录)},
        )
        成功, 消息 = self.网关.启动()
        self.assertTrue(成功, 消息)
        self.地址 = f"http://127.0.0.1:{self.网关.端口}"
        状态, 查询 = 请求(self.地址 + f"/平台/能力反馈/{反馈id}", "GET", None, self.普通头)
        self.assertEqual(状态, 200)
        self.assertEqual(查询["值"]["记录表"][0]["反馈id"], 反馈id)


if __name__ == "__main__":
    unittest.main()
