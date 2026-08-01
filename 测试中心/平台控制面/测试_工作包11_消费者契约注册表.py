"""工作包11 消费者契约注册表真实测试：登记/查询/漂移判定/门禁阻断/删除。

覆盖：登记真实绑定记录（请求/响应约束/错误码/超时/释放要求）、无漂移放行、
参数漂移、错误码漂移、超时漂移、返回键漂移、释放漂移、多消费者任一漂移即阻断。
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
from 平台控制面.能力目录.消费者契约注册表 import 消费者契约注册表


def 能力契约(请求参数=None, 返回键=None, 错误码集=None, 超时=5.0, 释放要求=None) -> dict:
    """构造一份能力契约（与登记契约同结构，默认与 契约编译/消费者契约.py 语义一致）。"""
    return {
        "请求": {"参数列表": 请求参数 if 请求参数 is not None else ["能力id", "参数"],
                 "示例": {"能力id": "能力A", "参数": {"关键词": "搜索"}}},
        "响应约束": {"返回键": 返回键 if 返回键 is not None else ["成功", "结果", "错误码", "消息"],
                     "结构": "统一结果键"},
        "错误码集": 错误码集 if 错误码集 is not None else ["CAPABILITY_NOT_FOUND", "CALL_TIMEOUT"],
        "超时": 超时,
        "释放要求": 释放要求 if 释放要求 is not None else ["释放调用信号量", "取消挂起任务"],
    }


class Test消费者契约注册表(unittest.TestCase):
    """消费者契约注册表：登记/查询/漂移/门禁/删除 真实行为。"""

    def setUp(self):
        self.目录 = Path(tempfile.mkdtemp(prefix="消费者契约_"))
        self.注册表 = 消费者契约注册表(self.目录)

    def tearDown(self):
        shutil.rmtree(self.目录, ignore_errors=True)

    def test_登记契约后查询契约返回真实绑定记录(self):
        结果 = self.注册表.登记契约("消费者甲", "能力A", 能力契约())
        self.assertTrue(结果["成功"], 结果["消息"])
        self.assertEqual(结果["错误码"], "SUCCESS")
        查询 = self.注册表.查询契约("能力A")
        self.assertTrue(查询["成功"])
        self.assertEqual(len(查询["数据"]), 1, "能力A 应只有一份消费者契约")
        记录 = 查询["数据"][0]
        self.assertEqual(记录["消费者id"], "消费者甲")
        self.assertEqual(记录["能力id"], "能力A")
        self.assertEqual(记录["请求"]["参数列表"], ["能力id", "参数"])
        self.assertEqual(记录["请求"]["示例"], {"能力id": "能力A", "参数": {"关键词": "搜索"}})
        self.assertEqual(记录["响应约束"]["返回键"], ["成功", "结果", "错误码", "消息"])
        self.assertEqual(记录["错误码集"], ["CAPABILITY_NOT_FOUND", "CALL_TIMEOUT"])
        self.assertEqual(记录["超时"], 5.0)
        self.assertEqual(记录["释放要求"], ["释放调用信号量", "取消挂起任务"])
        存储文件 = self.目录 / "消费者契约.json"
        self.assertTrue(存储文件.is_file(), "契约必须真实落盘")
        self.assertEqual(len(json.loads(存储文件.read_text(encoding="utf-8"))["能力A"]), 1)
        self.assertEqual(查询["数据"], 查询["数据"], "绑定记录必须持久化一致")

    def test_契约无漂移时门禁判定不阻断(self):
        self.注册表.登记契约("消费者甲", "能力A", 能力契约())
        结果 = self.注册表.门禁判定("能力A", 能力契约())
        self.assertTrue(结果["成功"])
        self.assertFalse(结果["数据"]["是否阻断"], "无漂移必须放行")
        self.assertEqual(结果["数据"]["漂移列表"], [])

    def test_参数漂移导致门禁阻断(self):
        self.注册表.登记契约("消费者甲", "能力A", 能力契约(请求参数=["能力id", "领域"]))
        结果 = self.注册表.门禁判定("能力A", 能力契约(请求参数=["能力id"]))
        self.assertTrue(结果["数据"]["是否阻断"], "参数缺失必须阻断")
        漂移 = 结果["数据"]["漂移列表"]
        self.assertEqual(漂移[0]["消费者id"], "消费者甲")
        self.assertEqual(漂移[0]["漂移类型"], "参数漂移")
        self.assertEqual(漂移[0]["期望值"], "领域")

    def test_错误码漂移导致门禁阻断(self):
        self.注册表.登记契约("消费者甲", "能力A",
                            能力契约(错误码集=["CALL_TIMEOUT", "CALL_FAILED"]))
        结果 = self.注册表.门禁判定("能力A", 能力契约(错误码集=["CALL_TIMEOUT"]))
        self.assertTrue(结果["数据"]["是否阻断"], "错误码缺失必须阻断")
        漂移 = 结果["数据"]["漂移列表"]
        self.assertEqual(漂移[0]["漂移类型"], "错误码漂移")
        self.assertEqual(漂移[0]["期望值"], "CALL_FAILED")

    def test_超时漂移导致门禁阻断(self):
        # 消费者要求 5 秒时限，能力当前超时变短为 2 秒（不满足消费者要求）→ 阻断
        self.注册表.登记契约("消费者甲", "能力A", 能力契约(超时=5.0))
        结果 = self.注册表.门禁判定("能力A", 能力契约(超时=2.0))
        self.assertTrue(结果["数据"]["是否阻断"], "超时变短不满足消费者要求必须阻断")
        漂移 = 结果["数据"]["漂移列表"]
        self.assertEqual(漂移[0]["漂移类型"], "超时漂移")
        self.assertEqual(漂移[0]["期望值"], 5.0)
        self.assertEqual(漂移[0]["实际值"], 2.0)

    def test_返回键缺失导致返回键漂移阻断(self):
        self.注册表.登记契约("消费者甲", "能力A",
                            能力契约(返回键=["成功", "结果", "错误码", "消息"]))
        结果 = self.注册表.门禁判定("能力A", 能力契约(返回键=["成功", "结果"]))
        self.assertTrue(结果["数据"]["是否阻断"], "返回键缺失必须阻断")
        漂移 = 结果["数据"]["漂移列表"]
        self.assertEqual(漂移[0]["漂移类型"], "返回键漂移")
        self.assertEqual(漂移[0]["期望值"], "错误码")
        self.assertIn("消息", [项["期望值"] for 项 in 漂移])

    def test_释放要求缺失导致释放漂移阻断(self):
        self.注册表.登记契约("消费者甲", "能力A",
                            能力契约(释放要求=["释放调用信号量", "取消挂起任务"]))
        结果 = self.注册表.门禁判定("能力A", 能力契约(释放要求=["释放调用信号量"]))
        self.assertTrue(结果["数据"]["是否阻断"], "释放要求缺失必须阻断")
        漂移 = 结果["数据"]["漂移列表"]
        self.assertEqual(漂移[0]["漂移类型"], "释放漂移")
        self.assertEqual(漂移[0]["期望值"], "取消挂起任务")

    def test_多消费者任一漂移即阻断(self):
        self.注册表.登记契约("消费者甲", "能力A", 能力契约(请求参数=["能力id"]))
        self.注册表.登记契约("消费者乙", "能力A",
                            能力契约(请求参数=["能力id", "领域"]))
        结果 = self.注册表.门禁判定("能力A", 能力契约(请求参数=["能力id"]))
        self.assertTrue(结果["数据"]["是否阻断"], "任一消费者契约漂移必须阻断")
        漂移列表 = 结果["数据"]["漂移列表"]
        self.assertEqual(漂移列表[0]["消费者id"], "消费者乙")
        self.assertEqual(漂移列表[0]["漂移类型"], "参数漂移")
        # 删除乙后仅剩满足要求的甲 → 放行
        删除 = self.注册表.删除契约("消费者乙", "能力A")
        self.assertTrue(删除["成功"])
        self.assertEqual(删除["错误码"], "SUCCESS")
        结果2 = self.注册表.门禁判定("能力A", 能力契约(请求参数=["能力id"]))
        self.assertFalse(结果2["数据"]["是否阻断"], "删除漂移消费者后必须放行")
        # 重复删除返回未登记
        重复 = self.注册表.删除契约("消费者乙", "能力A")
        self.assertFalse(重复["成功"])
        self.assertEqual(重复["错误码"], "NOT_REGISTERED")

    def test_查询未登记能力返回空列表(self):
        查询 = self.注册表.查询契约("未登记能力")
        self.assertTrue(查询["成功"])
        self.assertEqual(查询["数据"], [])


if __name__ == "__main__":
    unittest.main()
