"""底座运行库回归：六个域表初始化、写入查询闭环、并发写入、参数口径、验收标识护栏。

华哥定盘（`开发文档/临时文档/57_底座收口总清单_审计.md` 第四节）：运行态一律入库，
库文件统一放 `工程缓存/运行数据/`，且一律经唯一 SQLite 支持库访问（禁止各包自己连库）。

本测试只碰临时目录里的库文件，不写仓库内任何数据；末两项只以 `mode=ro` 读正式库。

域清单（2026-09-15 审计删域）：`会话`/`检查点索引`/`缓存索引`/`发布` 四张恒空表已从
`提供者.运行库表定义` 删除（写入侧分别在各自专用库、以及平台控制面权威状态库），
保留 `灰度状态`（已接线，0 行只是尚未发生灰度发布）。
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

if str(Path(__file__).resolve().parents[2]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from 支持库.后端.数据库连接支持库.SQLite数据库 import (
    初始化运行数据库, 写入运行态, 查询运行态,
)

六个域 = ["任务", "作业", "协作状态", "能力占用", "灰度观测", "灰度状态"]
删掉的四个域 = ["会话", "检查点索引", "缓存索引", "发布"]


def 取成功值(用例: unittest.TestCase, 结果对象: Any) -> dict[str, Any]:
    """断言调用成功并取回字典型值（值可能为 None，必须先断言再取）。"""
    用例.assertTrue(结果对象.成功, 结果对象.错误说明)
    值 = 结果对象.值
    用例.assertIsInstance(值, dict)
    return dict(值)


class 运行数据库回归(unittest.TestCase):
    def setUp(self):
        self.临时目录 = tempfile.TemporaryDirectory()
        self.库路径 = str(Path(self.临时目录.name) / "底座运行.db")

    def tearDown(self):
        self.临时目录.cleanup()

    def test_初始化建出六个域表且幂等(self):
        第一次 = 取成功值(self, 初始化运行数据库(self.库路径))
        self.assertEqual(sorted(第一次["表清单"]), sorted(六个域))
        第二次 = 取成功值(self, 初始化运行数据库(self.库路径))
        self.assertEqual(sorted(第二次["表清单"]), sorted(六个域), "重复初始化必须幂等")
        for 域 in 删掉的四个域:
            self.assertNotIn(域, 第一次["表清单"], f"{域} 的写入侧不在本库，不得再出现在运行库域清单")

    def test_删掉的四个域按未知域报参数不合法(self):
        """删域必须真正生效：写入/查询被删域都要当场报「域必须是」，不能静默建表。"""
        初始化运行数据库(self.库路径)
        for 域 in 删掉的四个域:
            写入 = 写入运行态(self.库路径, 域, {"id": f"占位-{域}"})
            self.assertFalse(写入.成功, f"{域} 已删域，写入必须失败")
            self.assertEqual(写入.错误码, "参数不合法")
            self.assertIn("域必须是", 写入.错误说明)
            查询 = 查询运行态(self.库路径, 域)
            self.assertFalse(查询.成功, f"{域} 已删域，查询必须失败")
            self.assertEqual(查询.错误码, "参数不合法")

    def test_写入后可按域查询(self):
        初始化运行数据库(self.库路径)
        写入 = 取成功值(self, 写入运行态(self.库路径, "任务", {
            "任务id": "任务-1", "能力id": "直播逐字稿.全自动精校", "请求id": "请求-1",
            "状态": "运行中",
        }))
        self.assertTrue(写入["已写入"])
        self.assertEqual(写入["域"], "任务")
        查询 = 取成功值(self, 查询运行态(self.库路径, "任务", 限制=10))
        self.assertEqual(查询["总数"], 1)
        行列表 = 查询["行列表"]
        self.assertIsInstance(行列表, list)
        self.assertEqual(行列表[0]["状态"], "运行中")
        self.assertIn("任务-1", json.dumps(行列表[0], ensure_ascii=False))

    def test_未知域报参数不合法(self):
        初始化运行数据库(self.库路径)
        写入 = 写入运行态(self.库路径, "不存在的域", {"x": 1})
        self.assertFalse(写入.成功)
        self.assertEqual(写入.错误码, "参数不合法")
        self.assertIn("域必须是", 写入.错误说明)
        查询 = 查询运行态(self.库路径, "不存在的域")
        self.assertFalse(查询.成功)
        self.assertEqual(查询.错误码, "参数不合法")

    def test_空路径报参数不合法(self):
        初始化 = 初始化运行数据库("")
        self.assertFalse(初始化.成功)
        self.assertEqual(初始化.错误码, "参数不合法")
        写入 = 写入运行态(self.库路径, "任务", {})
        self.assertFalse(写入.成功)
        self.assertEqual(写入.错误码, "参数不合法")

    def test_并发写入不丢记录(self):
        初始化运行数据库(self.库路径)

        def 写(序号: int) -> bool:
            return 写入运行态(self.库路径, "作业", {
                "作业id": f"作业-{序号}", "工具": "run_release_gate", "状态": "运行中",
            }).成功

        with ThreadPoolExecutor(max_workers=8) as 池:
            结果 = list(池.map(写, range(12)))
        self.assertTrue(all(结果), "并发写入不得有失败")
        查询 = 取成功值(self, 查询运行态(self.库路径, "作业", 限制=50))
        self.assertEqual(查询["总数"], 12, "并发写入不得丢记录")

    def test_运行库不落仓库内(self):
        """库文件由调用方显式给定路径；本测试用的必须是临时目录。"""
        self.assertTrue(self.库路径.startswith(tempfile.gettempdir()))


    def test_逻辑与数值字段落真实类型(self):
        """逻辑型必须 INTEGER（0/1）、数值型必须 REAL —— TEXT 存 "0"/"0.25" 会让统计口径算错。"""
        import sqlite3 as _sqlite3
        类型库 = str(Path(self.临时目录.name) / "类型校验.db")
        取成功值(self, 初始化运行数据库(类型库))
        连接对象 = _sqlite3.connect(类型库)
        try:
            列类型 = {行[1]: (行[2] or "").upper() for 行 in
                    连接对象.execute('PRAGMA table_info("灰度观测")')}
            状态列 = {行[1]: (行[2] or "").upper() for 行 in
                    连接对象.execute('PRAGMA table_info("灰度状态")')}
        finally:
            连接对象.close()
        self.assertEqual(列类型.get("成功"), "INTEGER")
        self.assertEqual(列类型.get("超时"), "INTEGER")
        self.assertEqual(列类型.get("耗时毫秒"), "REAL")
        self.assertEqual(状态列.get("灰度比例"), "REAL")


    def test_拒绝验收测试标识行(self):
        """写入侧护栏：正式运行库不得写入验收/测试标识行。

        起因（2026-09-15 审计）：一次性验收命令直接把 `验收-灰度-1` 写进了**正式库**，
        而 `灰度指标.聚合()` 是「从库重算」，假行会污染按表统计的灰度结论。
        """
        初始化运行数据库(self.库路径)
        拒绝样例 = [
            ("灰度观测", {"观测id": "验收-灰度-1", "时间": "2026-09-15 11:00:00",
                          "能力id": "验收.能力", "版本": "1.0.0", "成功": True,
                          "耗时毫秒": 12.5, "超时": False}),
            ("灰度观测", {"观测id": "临时-1", "能力id": "验收.能力", "版本": "1.0.0",
                          "成功": True, "耗时毫秒": 1.0, "超时": False}),
            ("任务", {"任务id": "测试-回归", "能力id": "直播逐字稿.全自动精校"}),
        ]
        for 域, 记录 in 拒绝样例:
            写入 = 写入运行态(self.库路径, 域, 记录)
            self.assertFalse(写入.成功, f"测试标识行必须被拒绝：{记录}")
            self.assertEqual(写入.错误码, "参数不合法")
            self.assertIn("不得写入验收/测试标识", 写入.错误说明)
        查询 = 取成功值(self, 查询运行态(self.库路径, "灰度观测", 限制=10))
        self.assertEqual(查询["总数"], 0, "被拒行不得落库")
        # 护栏不得误伤真实运行态
        正常 = 写入运行态(self.库路径, "灰度观测", {
            "观测id": "2026-09-15 11:00:00-ab12cd34", "时间": "2026-09-15 11:00:00",
            "能力id": "直播逐字稿.全自动精校", "版本": "1.0.0", "成功": True,
            "耗时毫秒": 12.5, "超时": False})
        self.assertTrue(正常.成功, 正常.错误说明)

    def test_正式库不含验收标识行(self):
        """防复发巡检：正式 `底座运行.db` 只读打开，不得含验收/测试标识行。"""
        import sqlite3 as _sqlite3
        正式库 = Path(__file__).resolve().parents[2] / "工程缓存" / "运行数据" / "底座运行.db"
        if not 正式库.is_file():
            self.skipTest("正式库不存在（全新工作区），跳过只读巡检")
        命中: list[str] = []
        连接对象 = _sqlite3.connect(f"file:{正式库}?mode=ro", uri=True)
        try:
            表集合 = [行[0] for 行 in 连接对象.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")]
            for 域 in sorted(表集合):
                列集合 = {行[1] for 行 in 连接对象.execute(f'PRAGMA table_info("{域}")')}
                条件 = ['"id" LIKE \'验收-%\'', '"id" LIKE \'测试-%\'']
                if "能力id" in 列集合:
                    条件.append('"能力id" LIKE \'验收%\'')
                for 行 in 连接对象.execute(
                        f'SELECT "id" FROM "{域}" WHERE {" OR ".join(条件)}'):
                    命中.append(f"{域}:{行[0]}")
        finally:
            连接对象.close()
        self.assertEqual(命中, [], f"正式库不得含验收/测试标识行：{命中}")


if __name__ == "__main__":
    unittest.main()
