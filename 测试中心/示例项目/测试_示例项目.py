"""示例项目：最小运行样板真实执行测试。"""

from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path

系统根 = Path(__file__).resolve().parents[2]
if str(系统根) not in sys.path:
    sys.path.insert(0, str(系统根))


class Test示例项目(unittest.TestCase):
    def test_示例项目运行成功(self):
        进程 = subprocess.run(
            [sys.executable, str(系统根 / "示例项目" / "示例项目.py")],
            cwd=str(系统根), capture_output=True, text=True, timeout=180,
        )
        self.assertEqual(进程.returncode, 0, (进程.stdout + process.stderr) if False else (进程.stdout + 进程.stderr)[-800:])
        self.assertIn("示例项目运行成功", 进程.stdout)

    def test_装配链路输出(self):
        进程 = subprocess.run(
            [sys.executable, str(系统根 / "示例项目" / "示例项目.py")],
            cwd=str(系统根), capture_output=True, text=True, timeout=180,
        )
        self.assertIn("[1] 装配成功", 进程.stdout)
        self.assertIn("[5] 模块组合调用", 进程.stdout)


if __name__ == "__main__":
    unittest.main()
