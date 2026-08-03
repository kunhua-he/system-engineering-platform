"""镜像清单真实签名与公钥验证测试（Ed25519，真实密钥对，不 mock 第三方）。

覆盖：
- 真实 Ed25519 签名往返：签名清单 → 验证清单签名 通过（经 支持库.适配层
  密码签名提供者公开入口）。
- 篡改阻断：签名被改 / 清单正文被改 / 公钥被替换 → 全部拒绝（镜像签名无效）。
- 信任升级：校验器改为 公钥验证 + 信任指纹 双保险；公钥缺失/签名缺失
  fail-closed；指纹不匹配仍拒绝。
- 密钥角色边界：本测试在测试内生成临时密钥对（发布角色语义），
  运行核心不持有私钥、不修改信任目录。
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

if str(Path(__file__).resolve().parents[2]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from 运行核心.运行环境管理器.远程镜像 import (
    签名清单,
    验证清单签名,
    镜像签名无效,
    镜像摘要不匹配,
    远程镜像校验器,
    镜像校验请求,
)
from 支持库.适配层.密码签名提供者 import 签名, 验证签名

测试指纹 = "测试信任指纹-7f3a"


def _生成密钥对() -> tuple[str, str]:
    from 支持库.适配层.密码签名提供者 import 生成密钥对
    结果 = 生成密钥对()
    assert 结果.成功, 结果.错误说明
    return 结果.值["私钥PEM"], 结果.值["公钥PEM"]


def 样例清单(**覆盖) -> dict:
    """未签名的镜像清单样例（六字段齐全）。"""
    清单 = {
        "制品摘要": "制品摘要-aaaa",
        "依赖锁摘要": "锁摘要-1111",
        "python版本": "3.14.0",
        "系统版本": "测试系统 26.1",
        "架构": "arm64",
        "信任指纹": 测试指纹,
    }
    清单.update(覆盖)
    return 清单


class Test镜像清单签名验证(unittest.TestCase):
    """签名清单 / 验证清单签名：真实 Ed25519 往返与全部篡改阻断。"""

    def setUp(self):
        self.私钥PEM, self.公钥PEM = _生成密钥对()

    def test_真实Ed25519签名往返(self):
        """签名清单 → 验证通过；签名=128位hex（Ed25519 64字节）。"""
        清单 = 样例清单()
        结果 = 签名清单(清单, self.私钥PEM)
        self.assertTrue(结果.成功, 结果.错误说明)
        签名清单结果 = 结果.值
        self.assertIn("签名", 签名清单结果)
        self.assertEqual(len(签名清单结果["签名"]), 128)
        验证 = 验证清单签名(签名清单结果, self.公钥PEM)
        self.assertTrue(验证.成功 and 验证.值, 验证.错误说明)
        # 签名不改变清单正文（稳定序列化排除 签名 键）
        self.assertEqual(签名清单结果["制品摘要"], "制品摘要-aaaa")

    def test_签名正文为稳定序列化跨键序一致(self):
        """字段顺序/空白差异不影响序列化与签名结果（确定性签名）。"""
        清单一 = 样例清单()
        清单二 = 样例清单()
        # 打乱键序
        乱序键 = list(清单二.keys())
        乱序键.reverse()
        清单二 = {键: 清单二[键] for 键 in 乱序键}
        签名一 = 签名清单(清单一, self.私钥PEM).值
        签名二 = 签名清单(清单二, self.私钥PEM).值
        self.assertEqual(签名一["签名"], 签名二["签名"])

    def test_签名被篡改拒绝(self):
        """签名值被改 → 验证失败（镜像签名无效）。"""
        签名清单结果 = 签名清单(样例清单(), self.私钥PEM).值
        签名清单结果["签名"] = "00" * 128
        验证 = 验证清单签名(签名清单结果, self.公钥PEM)
        self.assertFalse(验证.成功)
        self.assertEqual(验证.错误码, 镜像签名无效)

    def test_清单被篡改拒绝(self):
        """签名后改清单正文（架构被改）→ 验证失败（镜像签名无效）。"""
        签名清单结果 = 签名清单(样例清单(), self.私钥PEM).值
        签名清单结果["架构"] = "x86_64"
        验证 = 验证清单签名(签名清单结果, self.公钥PEM)
        self.assertFalse(验证.成功)
        self.assertEqual(验证.错误码, 镜像签名无效)

    def test_公钥被替换拒绝(self):
        """用另一对密钥的公钥验证 → 失败（签名与公钥不匹配）。"""
        其他私钥, 其他公钥 = _生成密钥对()
        签名清单结果 = 签名清单(样例清单(), self.私钥PEM).值
        self.assertFalse(验证清单签名(签名清单结果, 其他公钥).成功)
        # 反向：他人签名、我方公钥验证 → 同样拒绝
        他人清单 = 签名清单(样例清单(), 其他私钥).值
        验证 = 验证清单签名(他人清单, self.公钥PEM)
        self.assertFalse(验证.成功)
        self.assertEqual(验证.错误码, 镜像签名无效)

    def test_签名缺失拒绝(self):
        """清单无签名字段 → 拒绝（镜像签名无效）。"""
        验证 = 验证清单签名(样例清单(), self.公钥PEM)
        self.assertFalse(验证.成功)
        self.assertEqual(验证.错误码, 镜像签名无效)
        self.assertIn("缺少签名", 验证.错误说明)

    def test_公钥缺失拒绝(self):
        """公钥PEM 为空 → 拒绝（镜像签名无效，fail-closed）。"""
        签名清单结果 = 签名清单(样例清单(), self.私钥PEM).值
        验证 = 验证清单签名(签名清单结果, "")
        self.assertFalse(验证.成功)
        self.assertEqual(验证.错误码, 镜像签名无效)

    def test_私钥不合法签名失败(self):
        """发布侧私钥非法 → 签名失败（镜像签名无效）。"""
        结果 = 签名清单(样例清单(), "坏私钥PEM")
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, 镜像签名无效)

    def test_真实签名直接经提供者往返(self):
        """签名清单 输出可直接用 验证签名 提供者入口再验（真实 Ed25519）。"""
        import base64
        from 运行核心.运行环境管理器.远程镜像 import _清单稳定序列化
        签名清单结果 = 签名清单(样例清单(), self.私钥PEM).值
        正文b64 = base64.b64encode(
            _清单稳定序列化(签名清单结果)).decode("ascii")
        直接验证 = 验证签名(self.公钥PEM, 正文b64, 签名清单结果["签名"])
        self.assertTrue(直接验证.成功 and 直接验证.值, 直接验证.错误说明)
        篡改验证 = 验证签名(self.公钥PEM, 正文b64 + "=", 签名清单结果["签名"])
        self.assertFalse(篡改验证.值)


class Test镜像校验器签名信任(unittest.TestCase):
    """校验器信任升级：公钥验证 + 信任指纹 双保险。"""

    def setUp(self):
        self.私钥PEM, self.公钥PEM = _生成密钥对()
        self.请求 = 镜像校验请求(
            依赖锁摘要="锁摘要-1111",
            python版本="3.14.0",
            系统版本="测试系统 26.1",
            架构="arm64",
        )

    def 签名清单(self, **覆盖) -> dict:
        清单 = 样例清单(**覆盖)
        结果 = 签名清单(清单, self.私钥PEM)
        self.assertTrue(结果.成功, 结果.错误说明)
        return 结果.值

    def test_签名有效全部匹配允许命中(self):
        结果 = 远程镜像校验器(self.请求, self.签名清单(), 测试指纹,
                               公钥PEM=self.公钥PEM)
        self.assertTrue(结果.允许命中)
        self.assertEqual(结果.制品摘要, "制品摘要-aaaa")

    def test_签名被篡改校验器拒绝(self):
        清单 = self.签名清单()
        清单["签名"] = "00" * 128
        结果 = 远程镜像校验器(self.请求, 清单, 测试指纹, 公钥PEM=self.公钥PEM)
        self.assertFalse(结果.允许命中)
        self.assertEqual(结果.错误码, 镜像签名无效)

    def test_清单被篡改校验器拒绝(self):
        清单 = self.签名清单()
        清单["依赖锁摘要"] = "伪造锁摘要-ffff"
        结果 = 远程镜像校验器(self.请求, 清单, 测试指纹, 公钥PEM=self.公钥PEM)
        self.assertFalse(结果.允许命中)
        self.assertEqual(结果.错误码, 镜像签名无效)

    def test_公钥被替换校验器拒绝(self):
        他人公钥 = _生成密钥对()[1]
        结果 = 远程镜像校验器(self.请求, self.签名清单(), 测试指纹,
                               公钥PEM=他人公钥)
        self.assertFalse(结果.允许命中)
        self.assertEqual(结果.错误码, 镜像签名无效)

    def test_公钥缺失校验器拒绝(self):
        """未配置公钥 → 拒绝（信任指纹不再是唯一信任依据）。"""
        结果 = 远程镜像校验器(self.请求, self.签名清单(), 测试指纹)
        self.assertFalse(结果.允许命中)
        self.assertEqual(结果.错误码, 镜像签名无效)

    def test_签名缺失校验器拒绝(self):
        结果 = 远程镜像校验器(self.请求, 样例清单(), 测试指纹,
                               公钥PEM=self.公钥PEM)
        self.assertFalse(结果.允许命中)
        self.assertEqual(结果.错误码, 镜像签名无效)

    def test_指纹双保险签名有效指纹不符拒绝(self):
        """签名验证通过但信任指纹不符 → 仍拒绝（双保险）。"""
        结果 = 远程镜像校验器(self.请求, self.签名清单(), "伪造指纹-ffff",
                               公钥PEM=self.公钥PEM)
        self.assertFalse(结果.允许命中)
        self.assertEqual(结果.错误码, 镜像摘要不匹配)
        self.assertIn("信任指纹不匹配", 结果.错误说明)

    def test_指纹双保险指纹匹配签名无效拒绝(self):
        """信任指纹一致但签名无效 → 拒绝（签名是强制信任依据）。"""
        清单 = self.签名清单()
        清单["签名"] = "00" * 128
        结果 = 远程镜像校验器(self.请求, 清单, 测试指纹, 公钥PEM=self.公钥PEM)
        self.assertFalse(结果.允许命中)
        self.assertEqual(结果.错误码, 镜像签名无效)

    def test_下载后制品摘要不符仍拒绝(self):
        """签名+指纹均通过，但下载内容与声明不符 → 拒绝（防篡改）。"""
        结果 = 远程镜像校验器(self.请求, self.签名清单(), 测试指纹,
                               公钥PEM=self.公钥PEM,
                               实际制品摘要="伪造制品摘要-ffff")
        self.assertFalse(结果.允许命中)
        self.assertEqual(结果.错误码, 镜像摘要不匹配)


if __name__ == "__main__":
    unittest.main()
