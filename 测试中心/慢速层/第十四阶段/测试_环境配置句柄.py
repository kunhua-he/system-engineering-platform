""".env 句柄真实测试：多 key 隔离、无环境污染、关闭后不可读。"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from 支持库.适配层.密钥提供者.密钥提供者 import (
    打开环境配置,
    读取环境配置,
    关闭环境配置,
)


class 环境配置句柄测试(unittest.TestCase):
    def test_多密钥读取和关闭(self) -> None:
        with tempfile.TemporaryDirectory() as 临时根:
            路径 = Path(临时根) / ".env"
            路径.write_text(
                "# 同一服务商多个 key\n"
                "CNWUDI_DEEPSEEK_MAIN='key-main'\n"
                "CNWUDI_DEEPSEEK_BACKUP=key-backup\n"
                "export CNWUDI_GPT_MAIN=key-gpt\n",
                encoding="utf-8",
            )
            原值 = os.environ.get("CNWUDI_DEEPSEEK_MAIN")
            os.environ.pop("CNWUDI_DEEPSEEK_MAIN", None)
            try:
                成功, 句柄, 错误码 = 打开环境配置(str(路径))
                self.assertTrue(成功)
                self.assertEqual(错误码, "")
                self.assertIsNotNone(句柄)
                self.assertEqual(读取环境配置(句柄, "CNWUDI_DEEPSEEK_MAIN"), (True, "key-main", ""))
                self.assertEqual(读取环境配置(句柄, "CNWUDI_DEEPSEEK_BACKUP"), (True, "key-backup", ""))
                self.assertEqual(读取环境配置(句柄, "CNWUDI_GPT_MAIN"), (True, "key-gpt", ""))
                self.assertNotIn("CNWUDI_DEEPSEEK_MAIN", os.environ)
                self.assertEqual(关闭环境配置(句柄), (True, None, ""))
                self.assertEqual(读取环境配置(句柄, "CNWUDI_DEEPSEEK_MAIN"), (False, "", "HANDLE_CLOSED"))
            finally:
                if 原值 is not None:
                    os.environ["CNWUDI_DEEPSEEK_MAIN"] = 原值

    def test_非法文件明确失败(self) -> None:
        with tempfile.TemporaryDirectory() as 临时根:
            路径 = Path(临时根) / ".env"
            路径.write_text("不是变量行\n", encoding="utf-8")
            成功, 句柄, 错误码 = 打开环境配置(str(路径))
            self.assertFalse(成功)
            self.assertIsNone(句柄)
            self.assertEqual(错误码, "ENV_SYNTAX_INVALID:1")


if __name__ == "__main__":
    unittest.main()
