"""第十四阶段 P1-15 真实密钥提供者边界测试。

环境变量 / macOS 钥匙串提供者真实读取；脱敏、泄漏检查、提取引用真实
执行；密钥值不写入任何文件，不出现在测试输出与证据中。钥匙串调用
如实记录真实结果，禁止假装成功。
"""
import io
import os
import sys
import tempfile
import unittest
from pathlib import Path

系统根 = Path(__file__).resolve().parents[3]
if str(系统根) not in sys.path:
    sys.path.insert(0, str(系统根))

from 支持库.适配层.密钥提供者.密钥提供者 import (
    错误码_密钥缺失, 错误码_钥匙串不可用, 错误码_引用不合法, 密钥提供者)

测试环境变量键 = "工作包15_测试_API密钥"
测试环境变量值 = "工作包15_密钥值_9f3a2b7c1d"


class Test密钥提供者(unittest.TestCase):
    """真实密钥提供者边界：7 个真实场景。"""

    def setUp(self):
        os.environ[测试环境变量键] = 测试环境变量值
        self.提供者 = 密钥提供者()
        成功, 值, 错误码 = self.提供者.读取(f"环境变量:{测试环境变量键}")
        self.assertTrue(成功, "环境变量预读取必须成功")
        self.assertEqual(值, 测试环境变量值)
        self.assertEqual(错误码, "")

    def tearDown(self):
        os.environ.pop(测试环境变量键, None)

    def test_环境变量提供者真实读取(self):
        成功, 值, 错误码 = self.提供者.读取(f"环境变量:{测试环境变量键}")
        self.assertTrue(成功)
        self.assertEqual(值, 测试环境变量值, "必须读到环境变量真实值")
        self.assertEqual(错误码, "")

    def test_环境变量缺失返回明确错误码(self):
        os.environ.pop(测试环境变量键, None)  # 确保不存在
        成功, 值, 错误码 = 密钥提供者().读取(f"环境变量:{测试环境变量键}")
        self.assertFalse(成功)
        self.assertEqual(值, "")
        self.assertEqual(错误码, 错误码_密钥缺失, "缺失必须返回明确错误码而非崩溃")

    def test_钥匙串提供者真实调用security命令(self):
        import shutil
        security路径 = shutil.which("security")
        # 几乎肯定不存在的账户：强制真实子进程调用 security
        成功, 值, 错误码 = self.提供者.读取(
            "钥匙串:系统底座工作包15测试账户_不存在:系统底座工作包15测试服务")
        if security路径:
            # security 命令存在：必须真实调用过且结果可解释
            if 成功:
                self.assertTrue(值, "钥匙串真实读取必须非空")
                self.assertEqual(错误码, "")
            else:
                self.assertEqual(错误码, 错误码_钥匙串不可用,
                                 "真实调用失败必须记录 KEYCHAIN_UNAVAILABLE")
            print(f"钥匙串调用证据：security存在=True 成功={成功} 错误码={错误码}")
        else:
            self.assertEqual(错误码, 错误码_钥匙串不可用,
                             "无 security 命令必须记录 KEYCHAIN_UNAVAILABLE")
            print("钥匙串调用证据：security存在=False 错误码=KEYCHAIN_UNAVAILABLE")

    def test_非法引用返回明确错误码(self):
        成功, 值, 错误码 = self.提供者.读取("数据库:密码")
        self.assertFalse(成功)
        self.assertEqual(错误码, 错误码_引用不合法)

    def test_脱敏把密钥值替换为掩码(self):
        日志 = f"连接凭证为 {测试环境变量值} 请勿外泄"
        脱敏后 = self.提供者.脱敏(日志)
        self.assertNotIn(测试环境变量值, 脱敏后, "脱敏后不得残留密钥值")
        self.assertEqual(脱敏后, "连接凭证为 *** 请勿外泄", "真实查找替换")

    def test_泄漏检查返回泄漏项对干净文本返回空(self):
        文本集合 = {
            "日志": f"请求成功 令牌 {测试环境变量值}",
            "说明书": "产品使用说明：输入账号密码",
            "Agent数据": f"配置项 secret={测试环境变量值}",
            "制品文本": "构建产物描述，无敏感信息",
        }
        泄漏项 = self.提供者.泄漏检查(文本集合)
        self.assertIn("日志", 泄漏项, "含密钥的日志必须列为泄漏项")
        self.assertIn("Agent数据", 泄漏项, "含密钥的Agent数据必须列为泄漏项")
        self.assertNotIn("说明书", 泄漏项)
        self.assertNotIn("制品文本", 泄漏项)
        干净集合 = {"日志": "普通日志", "说明书": "普通说明"}
        self.assertEqual(self.提供者.泄漏检查(干净集合), [], "无密钥文本返回空")

    def test_提取引用提取环境变量与钥匙串引用(self):
        配置文本 = (
            "服务配置：{环境变量:API密钥} 与 {钥匙串:账户甲:服务乙}，"
            "以及 {环境变量:数据库密码}；普通文本{不是引用} 忽略。"
        )
        引用列表 = self.提供者.提取引用(配置文本)
        self.assertIn("环境变量:API密钥", 引用列表)
        self.assertIn("环境变量:数据库密码", 引用列表)
        self.assertIn("钥匙串:账户甲:服务乙", 引用列表)
        self.assertNotIn("不是引用", 引用列表)
        self.assertNotIn(测试环境变量值, str(引用列表), "提取引用不得泄漏密钥值")

    def test_密钥不出现在测试输出与证据中(self):
        缓冲区 = io.StringIO()
        原输出 = sys.stdout
        sys.stdout = 缓冲区
        try:
            print("日志：调用成功", self.提供者.脱敏(f"凭证 {测试环境变量值} 已使用"))
        finally:
            sys.stdout = 原输出
        self.assertNotIn(测试环境变量值, 缓冲区.getvalue(), "测试输出不得含密钥值")
        self.assertIn("***", 缓冲区.getvalue())
        # 证据：脱敏后的说明书文本写入临时文件，内容不得含密钥值
        证据目录 = Path(tempfile.mkdtemp(prefix="工作包15证据_"))
        证据文件 = 证据目录 / "说明书.txt"
        证据文件.write_text(
            self.提供者.脱敏(f"说明书含配置 {测试环境变量值} 说明"), encoding="utf-8")
        证据内容 = 证据文件.read_text(encoding="utf-8")
        self.assertNotIn(测试环境变量值, 证据内容, "证据文件不得含密钥值")
        self.assertEqual(证据内容, "说明书含配置 *** 说明")


if __name__ == "__main__":
    unittest.main()
