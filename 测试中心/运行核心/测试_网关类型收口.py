"""网关类型收口验收：非正式类型名 fail-closed（B-1）与句柄类型收紧（B-2）。

走**真实 HTTP**（本地网关服务器 + 后端核心注册表），不 mock 校验层：
每个用例先证明「合法值真的成功」（非恒真前提），再证明非法值被 400 拦下。
全部调用生产实现 `运行核心/统一网关/{网关核心,本地网关}.py`。
"""
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

from 后端核心.后端核心 import 后端核心
from 公共契约.基础类型.结果类型 import 结果
from 运行核心.统一网关.本地网关 import 本地网关服务器
from 运行核心.统一网关.网关核心 import 网关核心

秒声明 = [{"名称": "等待秒", "类型": "双精度数型", "必填": False, "默认值": 0,
          "说明": "复刻 支持库/后端/并发控制支持库 存量写法；该包 2026-09-17 已回填正式名，"
                  "本域只兜住——声明必须落在 16 项正式类型表内"}]
别名秒声明 = [{"名称": "等待秒", "类型": "数值型", "必填": False, "默认值": 0,
              "说明": "`数值型` 曾登记为 `双精度数型` 的兼容别名；别名表 2026-09-17 撤除后，"
                      "这样声明的能力**必须**被 fail-closed 拒掉（本夹具专门守这条判据）"}]


def _回显(**参数):
    return 结果.成功结果({"收到": 参数})


def _读取错误JSON(错误: urllib.error.HTTPError) -> dict:
    return json.loads(错误.read().decode("utf-8"))


class 网关类型收口验收(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.后端 = 后端核心(系统根)
        启动结果 = cls.后端.启动()
        if not 启动结果.成功:
            raise RuntimeError(f"后端核心启动失败: {启动结果.错误说明}")
        cls.后端.注册能力("测试.数值秒回显", _回显, 参数=秒声明)
        cls.后端.注册能力("测试.别名秒回显", _回显, 参数=别名秒声明)
        cls.后端.注册能力("测试.自造名回显", _回显,
                          参数=[{"名称": "X", "类型": "字符串型", "必填": False}])
        cls.后端.注册能力("测试.句柄回显", _回显,
                          参数=[{"名称": "句柄", "类型": "句柄型", "必填": False}])
        cls.网关 = 本地网关服务器.创建测试服务器(网关核心实例=网关核心(cls.后端), 端口=0)
        成功, 说明 = cls.网关.启动()
        if not 成功:
            raise RuntimeError(说明)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.网关.优雅停止()
        cls.后端.优雅关闭()

    def 调用(self, 能力id: str, 参数: dict) -> dict:
        """真发一次 HTTP POST，返回 {'状态码', '体'}；4xx/5xx 也照实收下来。"""
        地址 = f"http://127.0.0.1:{self.网关.端口}/网关/调用"
        请求 = urllib.request.Request(
            urllib.parse.quote(地址, safe=":/@._-"),
            data=json.dumps({"能力id": 能力id, "参数": 参数}).encode("utf-8"),
            method="POST", headers={"Content-Type": "application/json"})
        try:
            响应 = urllib.request.urlopen(请求, timeout=5)
        except urllib.error.HTTPError as 错误:
            return {"状态码": 错误.code, "体": _读取错误JSON(错误)}
        return {"状态码": 响应.status, "体": json.loads(响应.read().decode("utf-8"))}

    # ---- B-1：非正式类型名收口 ----
    def test_未登记非正式类型名被明确拒绝(self) -> None:
        """`字符串型` 不在 16 项正式表内且无别名可归一 → 必须 400，说明点名「非正式类型名」。"""
        正常 = self.调用("测试.数值秒回显", {"等待秒": 0.5})
        self.assertEqual(正常["状态码"], 200, f"非恒真前提：合法调用必须真的通: {正常}")
        self.assertTrue(正常["体"]["成功"], 正常)
        越界 = self.调用("测试.自造名回显", {"X": "abc"})
        self.assertEqual(越界["状态码"], 400, f"非正式类型名必须被拦: {越界}")
        self.assertFalse(越界["体"]["成功"])
        self.assertEqual(越界["体"]["错误码"], "参数不合法")
        self.assertIn("非正式类型名", 越界["体"]["错误说明"])

    def test_已撤除别名数值型按非正式类型名被拒(self) -> None:
        """`数值型` 曾是 `双精度数型` 的兼容别名，别名表 2026-09-17 撤除 → 现在**必须 fail-closed**。

        本用例守护「撤除后不留空壳」这条判据：声明 `数值型` 的能力一律 400，
        且错误码/说明都落回 `非正式类型名`，不得被静默归一成任何正式名。
        同时保留原强度断言：换用正式名 `双精度数型` 后小数放行、整数/布尔/文本仍被拒，
        证明别名撤除**只收紧名字口径、不改变正式名强度**（别名还在时应有的行为全在这）。
        """
        小数 = self.调用("测试.数值秒回显", {"等待秒": 0.5})
        self.assertEqual(小数["状态码"], 200, f"正式名双精度数型的小数必须放行: {小数}")
        整数 = self.调用("测试.数值秒回显", {"等待秒": 2})
        self.assertEqual(整数["状态码"], 400, f"双精度数型只接受 float，整数应被拒: {整数}")
        self.assertIn("双精度数型", 整数["体"]["错误说明"])
        布尔 = self.调用("测试.数值秒回显", {"等待秒": True})
        self.assertEqual(布尔["状态码"], 400, f"布尔不是数值: {布尔}")
        文本 = self.调用("测试.数值秒回显", {"等待秒": "1.5"})
        self.assertEqual(文本["状态码"], 400, f"文本不是数值（无隐式转换）: {文本}")
        别名 = self.调用("测试.别名秒回显", {"等待秒": 0.5})
        self.assertEqual(别名["状态码"], 400, f"已撤除的别名 `数值型` 必须被拒: {别名}")
        self.assertFalse(别名["体"]["成功"], 别名)
        self.assertEqual(别名["体"]["错误码"], "参数不合法", 别名)
        self.assertIn("非正式类型名", 别名["体"]["错误说明"])
        self.assertIn("数值型", 别名["体"]["错误说明"])

    # ---- B-2：句柄类型收紧 ----
    def test_句柄型与公共六位口径同强度(self) -> None:
        """合法句柄放行；任意字符串/超界数字/布尔一律 400——此前 `isinstance(值, str)` 全放行。"""
        合法 = self.调用("测试.句柄回显", {"句柄": "123456"})
        self.assertEqual(合法["状态码"], 200, f"合法文本句柄必须放行: {合法}")
        self.assertTrue(合法["体"]["成功"], 合法)
        合法整数 = self.调用("测试.句柄回显", {"句柄": 123456})
        self.assertEqual(合法整数["状态码"], 200, f"合法整数句柄必须放行: {合法整数}")
        自造 = self.调用("测试.句柄回显", {"句柄": "abc"})
        self.assertEqual(自造["状态码"], 400, f"任意字符串句柄必须被拒: {自造}")
        self.assertEqual(自造["体"]["错误码"], "参数不合法")
        self.assertIn("句柄型", 自造["体"]["错误说明"])
        五位 = self.调用("测试.句柄回显", {"句柄": "12345"})
        self.assertEqual(五位["状态码"], 400, f"非六位数字句柄必须被拒: {五位}")
        布尔 = self.调用("测试.句柄回显", {"句柄": True})
        self.assertEqual(布尔["状态码"], 400, f"布尔不是句柄: {布尔}")


if __name__ == "__main__":
    unittest.main()
