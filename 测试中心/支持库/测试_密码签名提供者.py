"""密码签名提供者能力测试：真实密钥对→签名→验证往返，不 mock 第三方。

- 真实生成密钥对/签名/验证/指纹/摘要；版本探测返回真实 cryptography
  版本号作为子进程加载证据；篡改签名验证失败；指纹稳定；
- 真实 AES 对称加解密往返（GCM 默认 / CBC 可显式初始向量），篡改密文、
  错误密钥、附加数据不一致与非法密钥长度全部返回稳定错误码；
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

from 支持库.适配层.密码签名提供者 import (
    公钥指纹,
    内容摘要,
    对称加密,
    对称解密,
    生成密钥对,
    签名,
    验证签名,
)
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


class Test密码签名对称加解密(unittest.TestCase):
    """AES 对称加解密（同一提供者内新增能力）：真实往返，不 mock 第三方。"""

    明文 = "华哥的对称加解密原子能力：同一明文，AES 往返一致。".encode("utf-8")
    密钥32 = bytes(range(32))
    密钥16 = bytes(range(16))
    向量12 = bytes(range(12))
    向量16 = bytes(range(16))

    def 往返(self, 模式: str, 密钥: bytes, 额外: dict) -> str:
        加密结果 = 对称加密(_b64(self.明文), _b64(密钥), 模式, **额外)
        self.assertTrue(加密结果.成功, 加密结果.错误说明)
        解密结果 = 对称解密(加密结果.值, _b64(密钥), 模式, **额外)
        self.assertTrue(解密结果.成功, 解密结果.错误说明)
        self.assertEqual(base64.b64decode(解密结果.值), self.明文)
        return 加密结果.值

    def test_往返gcm默认模式(self):
        密文 = self.往返("AES-GCM", self.密钥32, {})
        # 随机数 12 字节 + 密文 + 认证标签 16 字节
        self.assertEqual(len(base64.b64decode(密文)), len(self.明文) + 12 + 16)

    def test_往返gcm显式初始向量与附加数据(self):
        self.往返("AES-GCM", self.密钥32,
                 {"初始向量b64": _b64(self.向量12),
                  "附加数据b64": _b64("平台附加认证数据".encode("utf-8"))})

    def test_往返cbc显式初始向量是纯密文(self):
        # 显式给向量：向量由调用方保管，密文包不带前缀（数据库固定向量用法）
        密文 = self.往返("AES-CBC", self.密钥32, {"初始向量b64": _b64(self.向量16)})
        字节数 = len(base64.b64decode(密文))
        self.assertEqual(字节数 % 16, 0)
        self.assertEqual(字节数, (len(self.明文) // 16 + 1) * 16)

    def test_往返cbc不传初始向量时向量写入密文包(self):
        密文 = self.往返("AES-CBC", self.密钥16, {})
        字节数 = len(base64.b64decode(密文))
        self.assertEqual(字节数 % 16, 0)
        self.assertEqual(字节数, 16 + (len(self.明文) // 16 + 1) * 16)

    def test_同明文两次gcm加密密文不同(self):
        第一次 = 对称加密(_b64(self.明文), _b64(self.密钥32))
        第二次 = 对称加密(_b64(self.明文), _b64(self.密钥32))
        self.assertTrue(第一次.成功 and 第二次.成功)
        self.assertNotEqual(第一次.值, 第二次.值)  # 随机数不同 → 密文不同

    def test_篡改密文与错误密钥返回解密失败(self):
        密文 = base64.b64decode(对称加密(_b64(self.明文), _b64(self.密钥32)).值)
        篡改包 = bytearray(密文)
        篡改包[20] ^= 0xFF
        篡改结果 = 对称解密(_b64(bytes(篡改包)), _b64(self.密钥32))
        self.assertFalse(篡改结果.成功)
        self.assertEqual(篡改结果.错误码, "解密失败")
        错钥结果 = 对称解密(_b64(密文), _b64(bytes(range(1, 33))))
        self.assertFalse(错钥结果.成功)
        self.assertEqual(错钥结果.错误码, "解密失败")

    def test_附加数据不一致返回解密失败(self):
        附加 = "原始附加数据".encode("utf-8")
        密文 = 对称加密(_b64(self.明文), _b64(self.密钥32), "AES-GCM",
                      _b64(self.向量12), _b64(附加)).值
        一致 = 对称解密(密文, _b64(self.密钥32), "AES-GCM",
                      _b64(self.向量12), _b64(附加))
        self.assertTrue(一致.成功, 一致.错误说明)
        不一致 = 对称解密(密文, _b64(self.密钥32), "AES-GCM",
                        _b64(self.向量12), _b64("被换掉的附加数据".encode("utf-8")))
        self.assertFalse(不一致.成功)
        self.assertEqual(不一致.错误码, "解密失败")

    def test_参数不合法(self):
        self.assertEqual(对称加密(_b64(self.明文), _b64(b"abc")).错误码, "参数不合法")
        self.assertEqual(对称加密(_b64(self.明文), "不是base64!!").错误码, "参数不合法")
        self.assertEqual(对称加密("", _b64(self.密钥32)).错误码, "参数不合法")
        self.assertEqual(对称加密(_b64(self.明文), _b64(self.密钥32), "AES-CTR").错误码, "参数不合法")
        self.assertEqual(
            对称加密(_b64(self.明文), _b64(self.密钥32), "AES-CBC",
                   _b64(self.向量16), _b64("cbc不支持附加数据".encode("utf-8"))).错误码,
            "参数不合法")
        self.assertEqual(对称解密(_b64(b"x"), _b64(self.密钥32)).错误码, "参数不合法")

    def test_主进程不加载cryptography(self):
        self.assertNotIn("cryptography", vars(提供者模块))
        对称加密(_b64(self.明文), _b64(self.密钥32))
        对称解密(_b64(self.明文), _b64(self.密钥32))
        self.assertNotIn("cryptography", vars(提供者模块))

    def test_缺环境注入对称能力提供者不可用(self):
        密文 = 对称加密(_b64(self.明文), _b64(self.密钥32)).值
        with mock.patch.dict(os.environ, {"密码签名提供者_禁用库": "cryptography"}):
            加密结果 = 对称加密(_b64(self.明文), _b64(self.密钥32))
            解密结果 = 对称解密(密文, _b64(self.密钥32))
        for 结果 in (加密结果, 解密结果):
            self.assertFalse(结果.成功)
            self.assertEqual(结果.错误码, "提供者不可用")
            self.assertTrue(结果.可重试)

    def test_注册能力含对称能力(self):
        from 公共契约.能力契约.契约 import 能力注册表

        注册表 = 能力注册表()
        __import__("支持库.适配层.密码签名提供者", fromlist=["注册能力"]).注册能力(注册表)
        for 能力id in ("密码签名.对称加密", "密码签名.对称解密"):
            self.assertIn(能力id, 注册表.能力id列表)


if __name__ == "__main__":
    unittest.main()
