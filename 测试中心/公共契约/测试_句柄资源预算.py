"""句柄资源预算测试：绑定资源和回收证据必须有界。"""

from __future__ import annotations

import unittest

from 公共契约.句柄体系 import (
    句柄绑定资源上限,
    回收证据上限,
    句柄体系,
    句柄类型_资源,
)


class 句柄资源预算测试(unittest.TestCase):
    def test_绑定资源超过上限拒绝(self) -> None:
        体系 = 句柄体系()
        对象 = 体系.创建句柄(句柄类型=句柄类型_资源, 资源id="资源")
        for 索引 in range(句柄绑定资源上限):
            成功, 消息 = 体系.登记资源(
                对象.句柄id, 资源类型="连接", 清理函数=lambda: None,
            )
            self.assertTrue(成功, (索引, 消息))
        成功, 消息 = 体系.登记资源(
            对象.句柄id, 资源类型="连接", 清理函数=lambda: None,
        )
        self.assertFalse(成功)
        self.assertIn("超过上限", 消息)

    def test_回收证据表最多保留上限(self) -> None:
        体系 = 句柄体系()
        体系.回收证据表.extend(
            {"句柄id": 索引, "资源id": "资源", "类型": "资源"}
            for 索引 in range(回收证据上限 + 10)
        )
        self.assertEqual(len(体系.回收证据表), 回收证据上限)
        self.assertEqual(体系.回收证据表[0]["句柄id"], 10)


if __name__ == "__main__":
    unittest.main()
