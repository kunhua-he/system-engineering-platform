"""通用能力反馈接口定向 HTTP 回归。

装配口径（2026-09-17 对齐实现）：反馈路由已**完全经唯一能力调用入口**解析，
不再经 `后端核心`；因此测试必须真实装配能力调用器（含反馈三能力 + 被反馈的能力id，
能力存在判定是 fail-closed 的，注册表里没有的能力id 一律按 `能力不存在` 拒绝）。
"""
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

# 本机 http_proxy/https_proxy 指向 127.0.0.1:4780（ClashX），urllib 在 macOS 上不把
# 回环地址放进例外表（proxy_bypass('127.0.0.1') 返回 False）。裸 urlopen 会让回环请求
# 先经代理，把「服务端静默断连」伪装成 502 + 空体，把真因藏起来。这里显式绕代理。
_无代理 = urllib.request.build_opener(urllib.request.ProxyHandler({}))


class 假注册表:
    能力id列表 = ["样例.相加"]


class 假后端:
    注册表 = 假注册表()


def _样例相加(左: int = 0, 右: int = 0):
    """测试替身能力：只用于反馈登记时的「能力存在」判定，测试中不会被真调用。"""
    from 公共契约.基础类型.结果类型 import 结果
    return 结果.成功结果({"和": 左 + 右})


def 装配反馈能力底座():
    """真实装配唯一能力调用入口（反馈路由的唯一解析通道）。

    注册反馈三能力（登记/查询/迁移）供调用，并注册被反馈的能力 id `样例.相加`
    —— 生产侧「能力存在判定」经唯一调用入口取注册表且 fail-closed，缺它就登不上。
    """
    from 公共契约.能力契约.契约 import 能力实现, 能力注册表
    from 公共契约.能力契约.调用器 import 设置惰性装配函数
    from 运行核心.能力调用.唯一能力调用 import 设置全局唯一服务, 唯一能力调用服务
    from 平台控制面.能力反馈 import 注册能力 as 注册反馈能力

    设置惰性装配函数(None)
    注册表 = 能力注册表()
    注册反馈能力(注册表)
    注册表.注册(能力实现(
        能力id="样例.相加", 包id="测试.样例", 实现函数=_样例相加,
        参数=[{"名称": "左", "类型": "整数型"}, {"名称": "右", "类型": "整数型"}],
        返回="结果", 说明="测试替身：仅供反馈登记校验能力存在",
        版本="1.0.0", 提供者id="测试.样例", 提供者版本="1.0.0",
    ))
    服务 = 唯一能力调用服务(注册表)
    设置全局唯一服务(服务)
    return 服务


def 请求(地址: str, 方法: str = "GET", 数据: dict | None = None,
        头部: dict[str, str] | None = None) -> tuple[int, dict]:
    正文 = None if 数据 is None else json.dumps(数据, ensure_ascii=False).encode("utf-8")
    请求对象 = urllib.request.Request(
        地址.replace("/平台/能力反馈", "/" + quote("平台/能力反馈")).replace("/状态", "/" + quote("状态")), data=正文, method=方法,
        headers={"Content-Type": "application/json", **(头部 or {})},
    )
    try:
        with _无代理.open(请求对象, timeout=5) as 响应:
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
        装配反馈能力底座()
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

    def test_调用器未装配时反馈路由回统一信封不静默断连(self):
        """真缺陷回归：网关反馈路由的异常路径必须回统一 JSON 信封。

        修复前：反馈路由经 `获取能力调用器()` 解析，未装配时抛
        `能力调用器状态异常：[E未装配]` → 异常逃出 do_POST → 服务端一个字节都不回：
        直连是 `RemoteDisconnected`，过本机 ClashX 代理被伪装成 `502 + Content-Length: 0`，
        真因被两层掩盖。修复后统一回 500 信封（错误码 内部错误）。
        """
        from 运行核心.能力调用.唯一能力调用 import 设置全局唯一服务
        设置全局唯一服务(None)   # 销毁：调用器回到 未装配
        try:
            状态, 返回 = self.反馈(self.基础反馈())
        finally:
            装配反馈能力底座()
        self.assertEqual(状态, 500, "未装配必须回信封而不是断连")
        self.assertFalse(返回["成功"])
        self.assertEqual(返回["错误码"], "内部错误")
        self.assertIn("E未装配", 返回["错误说明"], "信封必须带上真因，便于定位")
        self.assertEqual(返回["操作"], "能力反馈登记")


if __name__ == "__main__":
    unittest.main()
