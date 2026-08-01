"""第十四阶段 P2-20 稳定平台完整示例 测试：一条真实链路 8 个场景。

共享一次完整执行（工作包20 示例模块内部全部调用生产实现：统一能力服务、
需求登记、能力目录、包仓库、发布管理、提供者注册表、密码适配），
逐阶段验证 登记/确认/搜索/装配/工作包/构建/签名/安装/调用/升级/回滚/证据，
最后汇总只读审计阻断清单（无阻断时清单为空）。
"""
from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

系统根 = Path(__file__).resolve().parents[3]
if str(系统根) not in sys.path:
    sys.path.insert(0, str(系统根))

from 示例项目.稳定平台完整示例.稳定平台完整示例 import (
    包id, 能力id, 需求目标, 稳定平台完整示例)

阶段类型表 = ["登记", "确认", "搜索", "装配", "工作包", "构建",
            "签名", "安装", "调用", "升级", "回滚"]


class 测试完整示例链路(unittest.TestCase):
    """工作包20：真实链路逐阶段验证 + 证据可追溯 + 阻断清单汇总。"""

    @classmethod
    def setUpClass(cls):
        cls._临时 = tempfile.TemporaryDirectory(prefix="工作包20_测试_")
        cls.示例 = 稳定平台完整示例(Path(cls._临时.name) / "存储")
        cls.结果 = cls.示例.执行()
        cls.服务 = cls.示例.服务

    @classmethod
    def tearDownClass(cls):
        cls._临时.cleanup()

    def test_01_需求草案登记与确认全流程(self):
        """测试1：自然语言需求草案 → 登记快照 → 确认，需求状态=已确认。"""
        需求id = self.结果["需求id"]
        记录 = self.服务.状态.读取记录("需求", "需求id", 需求id)
        self.assertIsNotNone(记录, "需求记录必须真实落库")
        self.assertEqual(记录["确认状态"], "已确认")
        self.assertEqual(记录["状态"], "已确认")
        快照 = json.loads(记录["快照"])
        self.assertEqual(快照["目标"], 需求目标)
        self.assertEqual(快照["需求id"], 需求id)
        # 幂等确认
        成功, 消息 = self.服务.需求.确认需求(需求id=需求id)
        self.assertTrue(成功, 消息)
        self.assertIn("幂等", 消息)

    def test_02_搜索与装配计划返回候选能力(self):
        """测试2：搜索能力 真实返回候选；装配计划 包含候选能力与波次。"""
        搜索 = self.服务.执行操作(令牌=self.示例.令牌, 操作="搜索能力",
                             参数={"关键词": "文本"})
        self.assertTrue(搜索["成功"])
        self.assertGreater(搜索["数量"], 0)
        self.assertIn(能力id, [项["能力id"] for 项 in 搜索["结果表"]])
        计划 = self.结果["计划"]
        self.assertEqual(计划["需求id"], self.结果["需求id"])
        self.assertGreater(len(计划["工作包表"]), 0)
        计划能力id表 = [项["能力占用"] for 项 in 计划["工作包表"]]
        self.assertIn([能力id], 计划能力id表, "计划必须包含候选能力")
        self.assertIn("1", 计划["波次"], "计划必须给出并行波次")

    def test_03_并行工作包拆分真实落库(self):
        """测试3：计划能力条目拆为工作包，数量>0 且真实写入工作包表。"""
        工作包表 = self.结果["工作包表"]
        self.assertGreater(len(工作包表), 0)
        落库表 = self.服务.状态.查询记录("工作包", "需求id=?", (self.结果["需求id"],))
        self.assertEqual(len(落库表), len(工作包表))
        self.assertEqual(len(落库表), len(self.结果["计划"]["工作包表"]))
        self.assertTrue(落库表[0]["工作包id"])
        self.assertEqual(落库表[0]["验收命令"], "python3.14 主.py")

    def test_04_构建签名安装完整真实落盘(self):
        """测试4：制品真实落盘、签名验证通过（磁盘重算）、安装目录存在。"""
        服务 = self.服务
        v1摘要 = self.结果["v1摘要"]
        制品目录 = 服务.仓库.制品根目录 / v1摘要
        self.assertTrue((制品目录 / "主.py").is_file(), "制品必须真实落盘")
        self.assertTrue((制品目录 / "物料清单.json").is_file())
        # 签名验证：重新读取制品目录实际文件逐一计算摘要
        有效, 消息 = 服务.仓库.校验签名(制品摘要=v1摘要)
        self.assertTrue(有效, 消息)
        # 安装目录真实存在且内容一致
        安装文件 = self.示例.目录 / "已激活" / 包id / "主.py"
        self.assertTrue(安装文件.is_file(), "安装目录必须真实存在")
        self.assertIn("return 1", 安装文件.read_text(encoding="utf-8"))
        制品 = 服务.状态.读取记录("制品", "制品摘要", v1摘要)
        self.assertEqual(制品["状态"], "已安装")
        self.assertEqual(制品["签名者"], self.示例.身份id)

    def test_05_调用真实返回提供者结果(self):
        """测试5：调用能力 真实执行提供者，返回实际统计结果。"""
        调用 = self.结果["调用结果"]
        self.assertEqual(调用, {"字数": 7, "行数": 2})
        # 再次真实调用验证可重复性
        再次 = self.服务.执行操作(令牌=self.示例.令牌, 操作="调用能力",
                            参数={"能力id": 能力id, "参数": {"文本": "一"}})
        self.assertTrue(再次["成功"])
        self.assertEqual(再次["结果"], {"字数": 1, "行数": 1})

    def test_06_升级与回滚真实指针切换CAS生效(self):
        """测试6：激活指针先切新版后回滚到旧版，版本/栅栏令牌单调递增。"""
        服务 = self.服务
        升级后 = self.结果["升级后指针"]
        self.assertEqual(升级后["目标"], self.结果["v2摘要"])
        self.assertEqual(升级后["版本"], 2)
        self.assertEqual(升级后["栅栏令牌"], 2)
        self.assertEqual(升级后["状态"], "激活")
        回滚后 = self.结果["回滚后指针"]
        self.assertEqual(回滚后["目标"], self.结果["v1摘要"])
        self.assertEqual(回滚后["版本"], 3)
        self.assertEqual(回滚后["栅栏令牌"], 3)
        # CAS：用陈旧版本/令牌切换必须被拒，指针不被覆盖
        成功, 消息 = 服务.发布.切换激活指针(
            指针id=包id, 目标="陈旧目标", 期望版本=2, 期望令牌=2)
        self.assertFalse(成功, f"陈旧栅栏令牌切换必须被拒: {消息}")
        指针 = 服务.发布.当前激活(包id)
        self.assertEqual(指针["目标"], self.结果["v1摘要"], "陈旧切换不得覆盖指针")

    def test_07_证据查询完整链路逐条可追溯(self):
        """测试7：查询证据(主题=包id) 覆盖全部阶段，逐条真实存在且哈希可追溯。"""
        证据表 = self.结果["证据"]
        类型集合 = {项["类型"] for 项 in 证据表}
        for 阶段 in ("登记", "确认", "构建", "签名", "安装", "调用", "升级", "回滚"):
            self.assertIn(阶段, 类型集合, f"证据链缺少阶段: {阶段}")
        for 项 in 证据表:
            self.assertTrue(项["证据id"], "每条证据必须有证据id")
            self.assertEqual(项["主题"], 包id)
            self.assertEqual(项["结果"], "成功")
            self.assertTrue(项["时间"], "每条证据必须有时间戳")
            # 哈希可追溯：sha256(内容正文) 前16位必须匹配
            正文 = json.dumps(项["内容"], ensure_ascii=False)
            期望哈希 = hashlib.sha256(正文.encode("utf-8")).hexdigest()[:16]
            self.assertEqual(项["哈希"], 期望哈希, "证据哈希必须可追溯")

    def test_08_阻断清单汇总(self):
        """测试8：只读审计汇总——任何阶段缺失即阻断，无阻断则清单为空。"""
        证据表 = self.服务.状态.查询证据(主题=包id, 限制=100)
        证据类型 = {项["类型"] for 项 in 证据表}
        阻断清单 = [阶段 for 阶段 in 阶段类型表 if 阶段 not in 证据类型]
        self.assertEqual(阻断清单, [],
                         f"生产阻断清单（S2 串行修复）: {阻断清单}")
        self.assertGreaterEqual(len(证据表), len(阶段类型表),
                                "证据链必须覆盖全部 11 个阶段")


if __name__ == "__main__":
    unittest.main(verbosity=2)
