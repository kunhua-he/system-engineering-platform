"""工作包09 权威数据备份契约真实测试。

覆盖：声明契约字段与默认值、真实备份四类数据、校验备份通过、
篡改权威状态库/制品文件/证据内容后校验真实失败、按契约顺序恢复后
权威状态可重新打开读取原记录且制品摘要一致。
"""
import json
import shutil
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

系统根 = Path(__file__).resolve().parents[2]
if str(系统根) not in sys.path:
    sys.path.insert(0, str(系统根))
from 平台控制面.平台状态 import 平台状态
from 平台控制面.备份恢复.备份契约 import 权威数据备份契约
from 平台控制面.备份恢复.校验函数 import 校验权威状态, 校验证据账本


class Test权威数据备份契约(unittest.TestCase):
    """权威数据备份契约：四类数据备份/校验/恢复真实行为。"""

    def setUp(self):
        self.存储目录 = Path(tempfile.mkdtemp(prefix="备份契约_"))
        self.备份目录 = self.存储目录 / "备份"
        self.状态 = 平台状态(self.存储目录, 项目id="项目1", 所有者="维护者")
        self.状态.保存句柄(句柄id="句柄1", 句柄类型="资源", 资源id="资源1",
                          项目id="项目1", 所有者="维护者", 状态="有效", 版本="1")
        self.状态.追加证据(类型="测试", 主题="资源1", 内容={"动作": "创建"})
        self.状态.追加证据(类型="测试", 主题="资源1", 内容={"动作": "更新", "值": 2})
        self.状态.关闭()
        制品目录 = self.存储目录 / "制品"
        制品目录.mkdir(parents=True)
        (制品目录 / "包1_1.0.0.bin").write_bytes("制品内容1".encode("utf-8"))
        (制品目录 / "包2_2.0.0.bin").write_bytes("制品内容2".encode("utf-8"))
        self.契约 = 权威数据备份契约(self.存储目录)
        self.清单 = self.契约.执行备份(self.备份目录)
        self.快照目录 = Path(self.清单["快照目录"])

    def tearDown(self):
        shutil.rmtree(self.存储目录, ignore_errors=True)

    def test_声明契约返回三类数据且字段齐全(self):
        契约表 = 权威数据备份契约(self.存储目录).声明契约()
        self.assertEqual(set(契约表), {"权威状态", "包仓库", "证据账本"})
        for 类名, 配置 in 契约表.items():
            for 字段 in ("恢复点", "恢复时限秒", "保留周期", "恢复顺序", "校验方法"):
                self.assertIn(字段, 配置, f"{类名} 缺少 {字段}")
            self.assertTrue(callable(配置["校验方法"]), f"{类名} 校验方法必须真实可调用")
            self.assertNotEqual(配置["恢复点"], "")
        self.assertEqual([契约表[类]["恢复顺序"] for 类 in ("权威状态", "证据账本", "包仓库")],
                         [1, 2, 3], "恢复顺序必须是 状态→证据→仓库")
        self.assertEqual(契约表["权威状态"]["恢复时限秒"], 60)
        self.assertEqual(契约表["权威状态"]["保留周期"], 7)
        # 可配置：公共值 + 单类覆盖
        契约2 = 权威数据备份契约(self.存储目录).声明契约(
            {"恢复时限秒": 120, "保留周期": 30, "包仓库": {"恢复顺序": 9}})
        self.assertEqual(契约2["证据账本"]["恢复时限秒"], 120)
        self.assertEqual(契约2["证据账本"]["保留周期"], 30)
        self.assertEqual(契约2["包仓库"]["恢复顺序"], 9)

    def test_执行备份生成真实文件与完整清单(self):
        self.assertTrue(self.快照目录.is_dir(), "必须生成时间戳快照子目录")
        self.assertTrue(self.快照目录.name.startswith("快照_"))
        for 文件名 in ("权威状态.db", "证据账本.json", "备份清单.json"):
            self.assertTrue((self.快照目录 / 文件名).is_file(), f"缺少 {文件名}")
        self.assertTrue((self.快照目录 / "制品" / "包1_1.0.0.bin").is_file())
        文件清单 = self.清单["文件"]
        self.assertEqual(set(文件清单), {"权威状态", "包仓库", "证据账本"})
        for 类名, 备份项 in 文件清单.items():
            self.assertIn("文件", 备份项, f"{类名} 缺文件字段")
            self.assertGreater(备份项["大小"], 0, f"{类名} 大小必须大于 0")
            self.assertTrue(备份项["摘要"], f"{类名} 缺校验摘要")
        self.assertEqual(文件清单["证据账本"]["条数"], 2)
        # 备份的权威状态库真实可打开且 integrity_check ok
        连接 = sqlite3.connect(self.快照目录 / "权威状态.db")
        self.assertEqual(连接.execute("PRAGMA integrity_check").fetchone()[0], "ok")
        连接.close()

    def test_校验备份真实通过(self):
        成功, 原因 = self.契约.校验备份(self.备份目录)
        self.assertTrue(成功, 原因)
        self.assertIn("全部通过", 原因)

    def test_篡改权威状态库后校验失败(self):
        数据库 = self.快照目录 / "权威状态.db"
        内容 = bytearray(数据库.read_bytes())
        内容[16:20] = b"\xff\xff\xff\xff"  # 破坏 sqlite 文件头页大小字段
        数据库.write_bytes(bytes(内容))
        成功, 原因 = self.契约.校验备份(self.备份目录)
        self.assertFalse(成功, "篡改权威状态库必须校验失败")
        # 真实校验函数：篡改后 sqlite 无法通过 integrity_check
        成功2, 原因2 = 校验权威状态(self.快照目录, self.清单["文件"]["权威状态"])
        self.assertFalse(成功2, f"integrity_check 必须失败: {原因2}")

    def test_篡改制品文件后校验失败(self):
        (self.快照目录 / "制品" / "包1_1.0.0.bin").write_bytes("被篡改的内容".encode("utf-8"))
        成功, 原因 = self.契约.校验备份(self.备份目录)
        self.assertFalse(成功, "篡改制品文件必须校验失败")
        self.assertIn("包仓库", 原因)

    def test_按契约顺序恢复且原记录与制品摘要一致(self):
        目标目录 = self.存储目录 / "恢复目标"
        结果 = self.契约.恢复(self.备份目录, 目标目录)
        self.assertTrue(结果["成功"], str(结果["结果"]))
        self.assertEqual(结果["恢复顺序"], ["权威状态", "证据账本", "包仓库"])
        # 权威状态可重新打开并读取原记录
        新状态 = 平台状态(目标目录)
        try:
            句柄 = 新状态.读取句柄("句柄1")
            self.assertIsNotNone(句柄)
            self.assertEqual(句柄["资源id"], "资源1")
            self.assertEqual(句柄["状态"], "有效")
        finally:
            新状态.关闭()
        # 制品文件内容摘要一致
        self.assertEqual((目标目录 / "制品" / "包1_1.0.0.bin").read_bytes(), "制品内容1".encode("utf-8"))
        self.assertEqual((目标目录 / "制品" / "包2_2.0.0.bin").read_bytes(), "制品内容2".encode("utf-8"))

    def test_篡改证据内容后哈希重放失败(self):
        账本文件 = self.快照目录 / "证据账本.json"
        账本 = json.loads(账本文件.read_text(encoding="utf-8"))
        self.assertGreater(len(账本), 0)
        账本[0]["内容"] = {"动作": "被篡改"}
        账本文件.write_text(json.dumps(账本, ensure_ascii=False), encoding="utf-8")
        # 真实重放校验：直接调用校验函数（绕过清单摘要比对）
        成功, 原因 = 校验证据账本(self.快照目录, self.清单["文件"]["证据账本"])
        self.assertFalse(成功, "篡改证据内容后哈希重放必须失败")
        self.assertIn("哈希不符", 原因)
        # 整体校验备份同样失败
        成功2, 原因2 = self.契约.校验备份(self.备份目录)
        self.assertFalse(成功2)
        self.assertIn("证据账本", 原因2)


if __name__ == "__main__":
    unittest.main()
