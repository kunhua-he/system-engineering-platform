"""核心快照模板测试：快照目录结构骨架（清单/摘要/激活指针）。

覆盖：临时目录生成结构齐全且校验通过/篡改文件校验失败/覆盖拒绝/
路径逃逸拒绝/真实核心契约目录临时生成（不碰真路径）。

禁止 mock 校验：全部用真实文件变更验证摘要变化。
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

系统根 = Path(__file__).resolve().parents[2]
if str(系统根) not in sys.path:
    sys.path.insert(0, str(系统根))

from 支持库.后端.组件规范支持库 import (
    激活指针文件名,
    生成快照清单模板,
    校验快照模板,
    清单文件名,
    摘要文件名,
)


def 建临时范围(工作目录: Path) -> list[str]:
    """在工作目录下建两个范围目录并写入正式文件。"""
    (工作目录 / "范围一" / "子目录").mkdir(parents=True)
    (工作目录 / "范围一" / "子目录" / "实现.py").write_text("值 = 1\n", encoding="utf-8")
    (工作目录 / "范围二").mkdir()
    (工作目录 / "范围二" / "契约.md").write_text("# 契约\n", encoding="utf-8")
    return ["范围一", "范围二"]


class Test生成快照模板(unittest.TestCase):
    """生成：临时目录结构齐全、清单字段完整、校验通过。"""

    def test_临时目录生成结构齐全且校验通过(self):
        工作目录 = Path(tempfile.mkdtemp(prefix="快照模板范围_"))
        目标目录 = Path(tempfile.mkdtemp(prefix="快照模板目标_"))
        范围目录表 = 建临时范围(工作目录)
        结果 = 生成快照清单模板(目标目录, 范围目录表, 工作目录=工作目录)
        self.assertTrue(结果["成功"], str(结果))
        self.assertEqual(结果["错误码"], "")
        清单路径 = 目标目录 / 清单文件名
        摘要路径 = 目标目录 / 摘要文件名
        激活路径 = 目标目录 / 激活指针文件名
        self.assertTrue(清单路径.is_file())
        self.assertTrue(摘要路径.is_file())
        self.assertTrue(激活路径.is_file())
        清单 = json.loads(清单路径.read_text(encoding="utf-8"))
        self.assertEqual(清单["范围"], 范围目录表)
        self.assertEqual(清单["文件数"], 2)
        self.assertEqual(清单["文件数"], len(清单["文件表"]))
        self.assertIn("时间", 清单)
        self.assertIn("范围一/子目录/实现.py", 清单["文件表"])
        self.assertEqual(len(清单["文件表"]["范围一/子目录/实现.py"]), 64)
        摘要文件 = json.loads(摘要路径.read_text(encoding="utf-8"))
        self.assertEqual(摘要文件["摘要"], 清单["摘要"])
        激活指针 = json.loads(激活路径.read_text(encoding="utf-8"))
        self.assertEqual(激活指针["目标摘要"], 清单["摘要"])
        self.assertTrue(激活指针["栅栏令牌"])
        self.assertEqual(激活指针["版本"], "1.0.0")
        通过, 消息 = 校验快照模板(目标目录)
        self.assertTrue(通过, 消息)

    def test_生成可指定版本与栅栏令牌(self):
        工作目录 = Path(tempfile.mkdtemp(prefix="快照模板范围_"))
        目标目录 = Path(tempfile.mkdtemp(prefix="快照模板目标_"))
        建临时范围(工作目录)
        结果 = 生成快照清单模板(目标目录, ["范围一", "范围二"],
                                工作目录=工作目录, 版本="2.1.0", 栅栏令牌="令牌1")
        self.assertTrue(结果["成功"], str(结果))
        激活指针 = json.loads((目标目录 / 激活指针文件名).read_text(encoding="utf-8"))
        self.assertEqual(激活指针["版本"], "2.1.0")
        self.assertEqual(激活指针["栅栏令牌"], "令牌1")


class Test校验快照模板(unittest.TestCase):
    """校验：三文件存在 / 清单与磁盘一致 / 聚合摘要匹配。"""

    def _生成(self) -> tuple[Path, Path]:
        工作目录 = Path(tempfile.mkdtemp(prefix="快照模板范围_"))
        目标目录 = Path(tempfile.mkdtemp(prefix="快照模板目标_"))
        建临时范围(工作目录)
        结果 = 生成快照清单模板(目标目录, ["范围一", "范围二"], 工作目录=工作目录)
        self.assertTrue(结果["成功"], str(结果))
        return 工作目录, 目标目录

    def test_篡改一个文件校验失败(self):
        _, 目标目录 = self._生成()
        (目标目录 / "范围一" / "子目录" / "实现.py").write_text(
            "值 = 999\n", encoding="utf-8")
        通过, 消息 = 校验快照模板(目标目录)
        self.assertFalse(通过)
        self.assertIn("清单不符", 消息)

    def test_缺文件校验失败(self):
        _, 目标目录 = self._生成()
        (目标目录 / 摘要文件名).unlink()
        通过, 消息 = 校验快照模板(目标目录)
        self.assertFalse(通过)
        self.assertIn("快照缺少", 消息)

    def test_新增文件校验失败(self):
        _, 目标目录 = self._生成()
        (目标目录 / "范围一" / "新增.py").write_text("x = 1\n", encoding="utf-8")
        通过, 消息 = 校验快照模板(目标目录)
        self.assertFalse(通过)

    def test_篡改摘要文件校验失败(self):
        _, 目标目录 = self._生成()
        (目标目录 / 摘要文件名).write_text(
            json.dumps({"摘要": "伪造"}), encoding="utf-8")
        通过, 消息 = 校验快照模板(目标目录)
        self.assertFalse(通过)


class Test防御(unittest.TestCase):
    """防御：已存在文件拒绝覆盖；路径逃逸拒绝。"""

    def test_已存在文件拒绝覆盖(self):
        工作目录 = Path(tempfile.mkdtemp(prefix="快照模板范围_"))
        目标目录 = Path(tempfile.mkdtemp(prefix="快照模板目标_"))
        建临时范围(工作目录)
        第一次 = 生成快照清单模板(目标目录, ["范围一", "范围二"], 工作目录=工作目录)
        self.assertTrue(第一次["成功"], str(第一次))
        第二次 = 生成快照清单模板(目标目录, ["范围一", "范围二"], 工作目录=工作目录)
        self.assertFalse(第二次["成功"])
        self.assertEqual(第二次["错误码"], "已存在")

    def test_预置文件拒绝覆盖(self):
        工作目录 = Path(tempfile.mkdtemp(prefix="快照模板范围_"))
        目标目录 = Path(tempfile.mkdtemp(prefix="快照模板目标_"))
        建临时范围(工作目录)
        (目标目录 / "旧文件.txt").write_text("旧\n", encoding="utf-8")
        结果 = 生成快照清单模板(目标目录, ["范围一", "范围二"], 工作目录=工作目录)
        self.assertFalse(结果["成功"])
        self.assertEqual(结果["错误码"], "已存在")
        self.assertTrue((目标目录 / "旧文件.txt").is_file(), "已有文件不得被覆盖")

    def test_路径逃逸拒绝(self):
        工作目录 = Path(tempfile.mkdtemp(prefix="快照模板范围_"))
        目标目录 = Path(tempfile.mkdtemp(prefix="快照模板目标_"))
        建临时范围(工作目录)
        结果 = 生成快照清单模板(目标目录, ["../外部逃逸"], 工作目录=工作目录)
        self.assertFalse(结果["成功"])
        self.assertEqual(结果["错误码"], "参数无效")
        self.assertTrue(not any(目标目录.iterdir()), "逃逸拒绝时不得写入目标目录")

    def test_绝对路径拒绝(self):
        工作目录 = Path(tempfile.mkdtemp(prefix="快照模板范围_"))
        目标目录 = Path(tempfile.mkdtemp(prefix="快照模板目标_"))
        建临时范围(工作目录)
        结果 = 生成快照清单模板(目标目录, ["/tmp/绝对路径"], 工作目录=工作目录)
        self.assertFalse(结果["成功"])
        self.assertEqual(结果["错误码"], "参数无效")

    def test_范围目录不存在拒绝(self):
        目标目录 = Path(tempfile.mkdtemp(prefix="快照模板目标_"))
        结果 = 生成快照清单模板(目标目录, ["不存在目录"], 工作目录=系统根)
        self.assertFalse(结果["成功"])
        self.assertEqual(结果["错误码"], "参数无效")


class Test真实核心契约目录(unittest.TestCase):
    """真实核心契约目录临时生成：不碰真路径，只读源目录。"""

    def test_核心契约目录临时生成且不碰真路径(self):
        候选路径 = [系统根 / "运行核心" / "公共契约", 系统根 / "公共契约"]
        真实目录 = next((路径 for 路径 in 候选路径 if 路径.is_dir()), None)
        self.assertIsNotNone(真实目录, f"找不到核心契约目录: {候选路径}")
        范围名称 = 真实目录.relative_to(系统根).as_posix()
        目标目录 = Path(tempfile.mkdtemp(prefix="快照模板真实_"))
        结果 = 生成快照清单模板(目标目录, [范围名称], 工作目录=系统根)
        self.assertTrue(结果["成功"], str(结果))
        self.assertGreater(结果["文件数"], 0)
        通过, 消息 = 校验快照模板(目标目录)
        self.assertTrue(通过, 消息)
        self.assertFalse((真实目录 / 清单文件名).exists(), "不得在真实目录写入清单")
        self.assertFalse((真实目录 / 摘要文件名).exists(), "不得在真实目录写入摘要")
        self.assertFalse((真实目录 / 激活指针文件名).exists(), "不得在真实目录写入激活指针")


if __name__ == "__main__":
    unittest.main()
