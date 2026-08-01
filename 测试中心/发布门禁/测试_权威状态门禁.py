"""权威状态七项发布门禁回归。"""

import unittest

from 开发工具.发布门禁.权威状态门禁 import 执行权威状态门禁


class Test权威状态门禁(unittest.TestCase):

    def test_七项生产场景全部执行并通过(self):
        结果表 = 执行权威状态门禁()

        self.assertEqual(len(结果表), 7)
        self.assertEqual(
            [名称 for 名称, 通过, _ in 结果表 if not 通过],
            [],
            {名称: 详情 for 名称, _, 详情 in 结果表},
        )


if __name__ == "__main__":
    unittest.main()
