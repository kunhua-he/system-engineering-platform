"""包发现黑盒测试：聚合壳跳过，带能力定义的真实子域必须保留。"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
import sys

系统根 = Path(__file__).resolve().parents[2]
if str(系统根) not in sys.path:
    sys.path.insert(0, str(系统根))

from 运行核心.加载器.包发现.发现器 import 扫描目录


class 测试聚合子域发现(unittest.TestCase):
    def test_聚合壳不注册但真实子域必须注册(self) -> None:
        with tempfile.TemporaryDirectory(prefix="聚合子域发现_") as 临时目录:
            根 = Path(临时目录) / "支持库"
            壳 = 根 / "后端" / "文件系统支持库"
            子域 = 壳 / "文件操作"
            子域.mkdir(parents=True)
            (壳 / "包声明.json").write_text(json.dumps({
                "包id": "支持库.后端.文件系统支持库", "名称": "文件系统支持库", "类型": "支持库", "版本": "1.0.0",
                "入口": "__init__.py", "依赖": [], "能力": [],
            }, ensure_ascii=False), encoding="utf-8")
            (子域 / "包声明.json").write_text(json.dumps({
                "包id": "支持库.后端.文件系统支持库.文件操作", "名称": "文件操作", "类型": "支持库", "版本": "1.0.0",
                "入口": "__init__.py", "依赖": [],
                "能力": [{"能力id": "文件系统支持库.文件操作.读取文件"}],
            }, ensure_ascii=False), encoding="utf-8")
            (子域 / "能力定义.json").write_text("{}", encoding="utf-8")
            结果 = 扫描目录(根, "支持库")
            包id表 = [声明.包id for 声明 in 结果]
            self.assertIn("支持库.后端.文件系统支持库.文件操作", 包id表)
            self.assertNotIn("支持库.后端.文件系统支持库", 包id表)


if __name__ == "__main__":
    unittest.main()
