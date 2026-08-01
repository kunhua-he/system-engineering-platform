"""第九阶段：反向破坏验证测试（反向破坏阶段）。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

系统根 = Path(__file__).resolve().parents[2]
if str(系统根) not in sys.path:
    sys.path.insert(0, str(系统根))

from 开发工具.复用审计.反向破坏.破坏验证 import 破坏验证器, 破坏场景表
from 运行核心.能力调用.控制调用.证据链 import 证据链, 版本锁定
from 运行核心.能力调用.控制调用.控制面 import 面分离器


class Test反向破坏(unittest.TestCase):
    """反向破坏：13 种破坏全部被拒绝。"""

    def test_破坏场景表完整(self):
        self.assertEqual(len(破坏场景表), 13)
        self.assertIn("提供者崩溃", 破坏场景表)
        self.assertIn("激活路由指向不存在版本", 破坏场景表)

    def test_13种破坏全部验证失败(self):
        报告 = 破坏验证器().执行()
        # 每个破坏场景都必须让验证器失败
        self.assertEqual(报告.通过数, 13,
                         [f"{证据.场景名}: 验证结果={证据.验证结果} {证据.详情}"
                          for 证据 in 报告.证据列表 if not 证据.验证结果])
        # 恒真检查：不允许全部失败仍通过
        self.assertTrue(报告.恒真检查)

    def test_发布阻断证明(self):
        报告 = 破坏验证器().执行()
        阻断场景 = [证据.场景名 for 证据 in 报告.证据列表 if 证据.发布阻断]
        self.assertIn("完整性摘要篡改", 阻断场景)
        self.assertIn("实现文件删除", 阻断场景)

    def test_旧版本恢复证明(self):
        报告 = 破坏验证器().执行()
        恢复场景 = [证据.场景名 for 证据 in 报告.证据列表 if 证据.旧版本恢复]
        self.assertIn("新版本健康失败", 恢复场景)
        self.assertIn("提供者崩溃", 恢复场景)

    def test_失败证据保留证明(self):
        报告 = 破坏验证器().执行()
        证据场景 = [证据.场景名 for 证据 in 报告.证据列表 if 证据.证据保留]
        self.assertGreaterEqual(len(证据场景), 8)

    def test_资源全部释放证明(self):
        报告 = 破坏验证器().执行()
        释放场景 = [证据.场景名 for 证据 in 报告.证据列表 if 证据.资源释放]
        self.assertIn("客户端断开", 释放场景)


if __name__ == "__main__":
    unittest.main()
