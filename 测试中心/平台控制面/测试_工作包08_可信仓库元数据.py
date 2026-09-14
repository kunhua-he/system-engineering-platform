"""工作包08 可信仓库四类元数据真实测试（真实 Ed25519 签名）。

覆盖：根信任初始化/真实验签、目标制品校验与替换阻断、快照版本回退阻断、
过期冻结阻断、错误公钥签名无效、根信任旧根+新根共同签名轮换。
"""
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

系统根 = Path(__file__).resolve().parents[2]
if str(系统根) not in sys.path:
    sys.path.insert(0, str(系统根))
from 支持库.适配层 import 生成密钥对, 验证签名, 内容摘要
from 平台控制面.包仓库.可信仓库元数据 import 可信仓库元数据


def 签名正文(元数据: dict) -> bytes:
    """与实现一致的签名正文：去掉全部签名字段后的规范化 JSON。"""
    干净 = {键: 值 for 键, 值 in 元数据.items() if not 键.endswith("签名")}
    return json.dumps(干净, ensure_ascii=False, sort_keys=True).encode("utf-8")


class Test可信仓库元数据(unittest.TestCase):
    """可信仓库四类元数据：根信任/目标/快照/新鲜度。"""

    def setUp(self):
        self.目录 = Path(tempfile.mkdtemp(prefix="可信元数据_"))

    def tearDown(self):
        shutil.rmtree(self.目录, ignore_errors=True)

    def test_初始化后根信任存在且真实Ed25519验签通过(self):
        仓库 = 可信仓库元数据(self.目录)
        根信任 = 仓库.初始化()
        self.assertEqual(根信任["类型"], "根信任")
        self.assertEqual(根信任["元数据版本"], 1)
        self.assertTrue((self.目录 / "元数据" / "根信任.json").is_file(), "根信任元数据必须落盘")
        self.assertTrue((self.目录 / "根私钥.pem").is_file(), "根私钥必须离线保存")
        # 真实 Ed25519：手工验签（绕过服务方法）
        self.assertTrue(验证签名(根信任["公钥"], 签名正文(根信任), 根信任["签名"]),
                        "根信任必须真实 Ed25519 验签通过")
        # 服务校验也通过
        成功, 原因 = 仓库.校验元数据("根信任", 根信任)
        self.assertTrue(成功, 原因)
        # 根信任元数据正文不得包含任何私钥
        self.assertNotIn("-----BEGIN PRIVATE KEY-----", json.dumps(根信任, ensure_ascii=False))

    def test_发布目标校验通过_替换攻击被阻断(self):
        仓库 = 可信仓库元数据(self.目录)
        仓库.初始化()
        内容 = "正式制品内容".encode("utf-8")
        目标 = 仓库.发布目标("可信包", "1.0.0", 内容摘要(内容), 制品内容=内容)
        self.assertEqual(目标["签名者"], "根信任")
        成功, 原因 = 仓库.校验元数据("目标", 目标)
        self.assertTrue(成功, f"真实签名目标必须校验通过: {原因}")
        # 替换攻击：篡改目标制品摘要 → 重算比对失败
        篡改 = dict(目标)
        篡改["制品摘要"] = 内容摘要("恶意替换内容".encode("utf-8"))
        成功2, 原因2 = 仓库.校验元数据("目标", 篡改)
        self.assertFalse(成功2, "替换攻击必须被阻断")
        self.assertIn("目标被替换", 原因2)
        # 篡改磁盘制品内容同样被发现
        篡改内容 = dict(目标)
        (self.目录 / "制品" / "可信包_1.0.0.bin").write_bytes("被篡改的制品".encode("utf-8"))
        成功3, 原因3 = 仓库.校验元数据("目标", 篡改内容)
        self.assertFalse(成功3)
        self.assertIn("目标被替换", 原因3)

    def test_生成快照校验通过_版本回退被阻断(self):
        仓库 = 可信仓库元数据(self.目录)
        仓库.初始化()
        仓库.发布目标("包1", "1", 内容摘要("内容1".encode("utf-8")), 制品内容="内容1".encode("utf-8"))
        快照1 = 仓库.生成快照()
        快照2 = 仓库.生成快照()
        self.assertEqual(快照2["元数据版本"], 快照1["元数据版本"] + 1, "快照版本必须单调递增")
        self.assertIn("包1@1", 快照2["目标表"])
        成功, 原因 = 仓库.校验元数据("快照", 快照2)
        self.assertTrue(成功, f"最新快照必须校验通过: {原因}")
        # 回退攻击：把快照版本改小 → 版本回退阻断（先于验签）
        回退 = dict(快照2)
        回退["元数据版本"] = 快照1["元数据版本"]
        成功2, 原因2 = 仓库.校验元数据("快照", 回退)
        self.assertFalse(成功2, "版本回退必须被阻断")
        self.assertIn("版本回退", 原因2)
        # 快照内目标摘要与磁盘目标不一致 → 快照回退阻断
        篡改快照 = dict(快照2)
        篡改快照["目标表"] = {"包1@1": 内容摘要("别的摘要".encode("utf-8"))}
        成功3, 原因3 = 仓库.校验元数据("快照", 篡改快照)
        self.assertFalse(成功3)
        self.assertIn("快照回退", 原因3)

    def test_过期元数据冻结阻断(self):
        仓库 = 可信仓库元数据(self.目录, 有效期秒=-1)
        仓库.初始化()
        目标 = 仓库.发布目标("冻包", "1", 内容摘要(b"x"), 制品内容=b"x")
        self.assertLess(float(目标["过期时间"]), __import__("time").time(), "过期时间必须在过去")
        成功, 原因 = 仓库.校验元数据("目标", 目标)
        self.assertFalse(成功, "过期元数据必须拒绝使用")
        self.assertIn("过期", 原因)

    def test_错误公钥验证失败_签名无效(self):
        仓库1 = 可信仓库元数据(self.目录 / "仓库1")
        仓库1.初始化()
        目标 = 仓库1.发布目标("包2", "1", 内容摘要(b"x"), 制品内容=b"x")
        仓库2 = 可信仓库元数据(self.目录 / "仓库2")
        仓库2.初始化()
        成功, 原因 = 仓库2.校验元数据("目标", 目标)
        self.assertFalse(成功, "错误根公钥必须验签失败")
        self.assertIn("签名无效", 原因)

    def test_根信任轮换_旧根新根共同签名通过(self):
        仓库 = 可信仓库元数据(self.目录)
        仓库.初始化()
        新私钥, 新公钥 = 生成密钥对()
        新根 = 仓库.轮换根信任(新私钥, 新公钥, 旧根私钥=仓库.当前根私钥)
        self.assertEqual(int(新根["元数据版本"]), 2, "轮换后根信任版本必须递增")
        self.assertIn("旧根签名", 新根)
        self.assertIn("新根签名", 新根)
        # 旧根签名由旧根私钥签出、新根签名由新根私钥签出（真实双重验签）
        self.assertTrue(验证签名(仓库.当前根公钥, 签名正文(新根), 新根["新根签名"]))
        成功, 原因 = 仓库.校验元数据("根信任", 新根)
        self.assertTrue(成功, f"旧根+新根共同签名轮换必须校验通过: {原因}")
        # 轮换后发布与校验仍一致（新根已接管）
        目标 = 仓库.发布目标("新根包", "1", 内容摘要(b"y"), 制品内容=b"y")
        成功2, 原因2 = 仓库.校验元数据("目标", 目标)
        self.assertTrue(成功2, f"轮换后新根签名目标必须通过: {原因2}")
        # 根信任回退攻击：轮换元数据版本改小 → 版本倒退阻断
        回退 = dict(新根)
        回退["元数据版本"] = 1
        成功3, 原因3 = 仓库.校验元数据("根信任", 回退)
        self.assertFalse(成功3)
        self.assertIn("版本倒退", 原因3)


if __name__ == "__main__":
    unittest.main()
