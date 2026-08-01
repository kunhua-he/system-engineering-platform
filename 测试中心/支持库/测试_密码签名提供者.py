"""密码签名提供者能力测试：真实密钥对→签名→验证往返，不 mock 第三方。

- 真实生成密钥对/签名/验证/指纹/摘要；版本探测返回真实 cryptography
  版本号作为子进程加载证据；篡改签名验证失败；指纹稳定；
- 缺环境注入（环境变量禁用 cryptography）→ 提供者不可用，主进程
  内容摘要不受影响；本包代码绝不 import cryptography。
生命周期（超时/崩溃/重启/残留）见 测试_密码签名提供者_生命周期.py。
"""

from __future__ import annotations

import base64
import hashlib
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

if str(Path(__file__).resolve().parents[2]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from 支持库.适配层.密码签名提供者 import 公钥指纹, 内容摘要, 生成密钥对, 签名, 验证签名
from 支持库.适配层.密码签名提供者.实现 import 提供者管理器 as 提供者模块


def _b64(数据: bytes) -> str:
    return base64.b64encode(数据).decode("ascii")


def _生成密钥() -> tuple[str, str]:
    结果 = 生成密钥对()
    assert 结果.成功, 结果.错误说明
    return 结果.值["私钥PEM"], 结果.值["公钥PEM"]


class Test密码签名提供者能力(unittest.TestCase):
    def test_主进程不加载cryptography(self):
        self.assertNotIn("cryptography", vars(提供者模块))
        私钥PEM, 公钥PEM = _生成密钥()
        签名(私钥PEM, _b64("数据".encode()))
        验证签名(公钥PEM, _b64("数据".encode()), "00" * 64)
        self.assertNotIn("cryptography", vars(提供者模块))

    def test_密钥签名验证往返(self):
        私钥PEM, 公钥PEM = _生成密钥()
        self.assertTrue(私钥PEM.startswith("-----BEGIN") and 公钥PEM.startswith("-----BEGIN"))
        数据 = "平台隔离签名往返".encode("utf-8")
        签名结果 = 签名(私钥PEM, _b64(数据))
        self.assertTrue(签名结果.成功, 签名结果.错误说明)
        self.assertEqual(len(签名结果.值), 128)  # Ed25519 签名 = 64 字节 hex
        验证结果 = 验证签名(公钥PEM, _b64(数据), 签名结果.值)
        self.assertTrue(验证结果.成功 and 验证结果.值, 验证结果.错误说明)

    def test_篡改签名验证失败(self):
        私钥PEM, 公钥PEM = _生成密钥()
        数据 = "被签名的原文".encode("utf-8")
        签名值 = 签名(私钥PEM, _b64(数据)).值
        self.assertFalse(验证签名(公钥PEM, _b64(数据 + "被篡改".encode()), 签名值).值)
        self.assertFalse(验证签名(公钥PEM, _b64(数据), "00" * 64).值)

    def test_指纹稳定(self):
        _, 公钥PEM = _生成密钥()
        指纹 = 公钥指纹(公钥PEM).值
        self.assertEqual(指纹, 公钥指纹(公钥PEM).值)
        self.assertEqual(指纹, hashlib.sha256(公钥PEM.encode()).hexdigest()[:16])
        _, 另一公钥 = _生成密钥()
        self.assertNotEqual(指纹, 公钥指纹(另一公钥).值)

    def test_内容摘要(self):
        数据 = "摘要原文".encode("utf-8")
        结果 = 内容摘要(_b64(数据))
        self.assertTrue(结果.成功, 结果.错误说明)
        self.assertEqual(结果.值, hashlib.sha256(数据).hexdigest())
        self.assertEqual(len(结果.值), 64)
        self.assertEqual(内容摘要("不是base64!!").错误码, "参数不合法")

    def test_参数不合法(self):
        私钥PEM, 公钥PEM = _生成密钥()
        self.assertEqual(签名("坏私钥PEM", _b64(b"x")).错误码, "参数不合法")
        self.assertEqual(签名(私钥PEM, "坏base64==").错误码, "参数不合法")
        self.assertEqual(验证签名("坏公钥PEM", _b64(b"x"), "00" * 64).错误码, "参数不合法")
        self.assertEqual(验证签名(公钥PEM, _b64(b"x"), "不是hex").错误码, "参数不合法")
        self.assertEqual(公钥指纹("").错误码, "参数不合法")
        指纹 = 公钥指纹("坏公钥PEM")
        self.assertTrue(指纹.成功)
        self.assertEqual(len(指纹.值), 16)

    def test_缺环境注入提供者不可用(self):
        私钥PEM, 公钥PEM = _生成密钥()
        with mock.patch.dict(os.environ, {"密码签名提供者_禁用库": "cryptography"}):
            生成结果 = 生成密钥对()
            签名结果 = 签名(私钥PEM, _b64(b"x"))
            指纹结果 = 公钥指纹(公钥PEM)
            摘要结果 = 内容摘要(_b64(b"x"))  # 纯标准库，主进程执行
        for 结果 in (生成结果, 签名结果, 指纹结果):
            self.assertFalse(结果.成功)
            self.assertEqual(结果.错误码, "提供者不可用")
            self.assertTrue(结果.可重试)
        self.assertTrue(摘要结果.成功, 摘要结果.错误说明)

    def test_检查提供者版本真实证据(self):
        结果 = 提供者模块.检查提供者版本()
        self.assertTrue(结果.成功, 结果.错误说明)
        self.assertRegex(str((结果.值 or {}).get("cryptography", "")), r"^\d+\.\d+")


if __name__ == "__main__":
    unittest.main()
