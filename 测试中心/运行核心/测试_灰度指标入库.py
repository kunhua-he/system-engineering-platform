"""灰度指标入库验收：运行库为唯一落点、旧 JSONL 只读兼容 + 一次性搬迁、状态可恢复。

判据（华哥 2026-09-15 定盘「运行态一律入库、不搞双写」）：
- 观测落 `灰度观测` 域，聚合从库重算；
- 灰度比例/回滚原因落 `灰度状态` 域，换实例可恢复；
- 旧 `灰度指标.jsonl` / `灰度状态.json` **字节数不变**（不再被写）；
- 运行库不可用时 `同步错误` 非空（可见，不静默）。
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

系统根 = Path(__file__).resolve().parents[2]
if str(系统根) not in sys.path:
    sys.path.insert(0, str(系统根))

from 运行核心.加载器.版本系统.灰度指标 import 灰度指标库


class 灰度指标入库测试(unittest.TestCase):
    def setUp(self) -> None:
        self.临时 = tempfile.TemporaryDirectory()
        self.根 = Path(self.临时.name)
        self.运行库 = self.根 / "运行数据" / "底座运行.db"
        self.运行库.parent.mkdir(parents=True, exist_ok=True)
        self.旧目录 = self.根 / "旧灰度"
        self.旧目录.mkdir(parents=True, exist_ok=True)
        self._旧环境 = os.environ.get("系统库运行库")
        os.environ["系统库运行库"] = str(self.运行库)
        # 初始化运行库（建六个域表）
        from 公共契约.能力契约.调用器 import 获取能力调用器
        import 运行核心.能力调用.唯一能力调用  # noqa: F401  惰性装配钩子
        结果对象 = 获取能力调用器().调用能力(
            "数据库连接支持库.SQLite数据库.初始化运行数据库",
            {"数据库路径": str(self.运行库), "超时秒": 10.0})
        self.assertTrue(getattr(结果对象, "成功", False), getattr(结果对象, "错误说明", ""))

    def tearDown(self) -> None:
        if self._旧环境 is None:
            os.environ.pop("系统库运行库", None)
        else:
            os.environ["系统库运行库"] = self._旧环境
        self.临时.cleanup()

    def _库行数(self, 表: str) -> int:
        with sqlite3.connect(self.运行库) as 连接:
            return 连接.execute(f'select count(*) from "{表}"').fetchone()[0]

    def test_观测落库并可聚合(self) -> None:
        库 = 灰度指标库(self.旧目录)
        self.assertEqual(库.同步错误, "")
        for i in range(5):
            库.观测(能力id="门禁.能力", 版本="1.0.0", 成功=i != 0, 耗时毫秒=10.0 * (i + 1))
        self.assertEqual(self._库行数("灰度观测"), 5)
        指标 = 库.聚合(能力id="门禁.能力", 版本="1.0.0")
        self.assertEqual((指标.请求总数, 指标.成功数, 指标.失败数), (5, 4, 1))
        self.assertGreater(指标.最大耗时毫秒, 0)

    def test_状态落库且跨实例可恢复(self) -> None:
        库 = 灰度指标库(self.旧目录)
        库.设置灰度比例("门禁.能力", "1.0.0", 0.25)
        库.触发回滚("门禁.能力", "1.0.0", "失败率超限")
        新库 = 灰度指标库(self.旧目录)
        键状态 = 新库.状态表.get("门禁.能力@1.0.0", {})
        self.assertEqual(键状态.get("当前灰度比例"), 0.25)
        self.assertEqual(键状态.get("触发回滚原因"), "失败率超限")
        self.assertEqual(self._库行数("灰度状态"), 1)

    def test_旧文件不再被写且会一次性搬迁(self) -> None:
        旧指标 = self.旧目录 / "灰度指标.jsonl"
        旧指标.write_text("\n".join(json.dumps({
            "时间": "2026-09-14 20:00:00", "能力id": "旧.能力", "版本": "1.0.0",
            "成功": True, "耗时毫秒": 5.0, "超时": False}) for _ in range(3)) + "\n", encoding="utf-8")
        旧状态 = self.旧目录 / "灰度状态.json"
        旧状态.write_text(json.dumps({"旧.能力@1.0.0": {"当前灰度比例": 0.5, "观察窗口秒": 300}},
                                     ensure_ascii=False), encoding="utf-8")
        before = (旧指标.stat().st_size, 旧状态.stat().st_size)
        库 = 灰度指标库(self.旧目录)
        self.assertEqual(库.搬迁观测数, 3)                      # 旧观测搬进运行库
        self.assertEqual(self._库行数("灰度观测"), 3)
        self.assertEqual(库.状态表.get("旧.能力@1.0.0", {}).get("当前灰度比例"), 0.5)
        库.观测(能力id="新.能力", 版本="1.0.0", 成功=True, 耗时毫秒=1.0)
        self.assertEqual(self._库行数("灰度观测"), 4)
        self.assertEqual((旧指标.stat().st_size, 旧状态.stat().st_size), before)  # 旧文件字节不变

    def test_超阈值问题按样本门槛返回(self) -> None:
        库 = 灰度指标库(self.旧目录)
        问题: list[str] = []
        for i in range(6):
            问题 = 库.观测(能力id="门禁.能力", 版本="1.0.0", 成功=i < 3, 耗时毫秒=1.0)
        self.assertTrue(any("失败率" in p for p in 问题), 问题)   # 6 次里 3 失败 > 5%

    def test_运行库不可用时同步错误可见(self) -> None:
        os.environ["系统库运行库"] = "/不存在目录/不可写/运行.db"
        库 = 灰度指标库(self.旧目录)
        self.assertEqual(self._库行数("灰度观测"), 0)
        self.assertTrue(库.同步错误, "运行库不可用时必须留下同步错误，不许静默")


if __name__ == "__main__":
    unittest.main()
