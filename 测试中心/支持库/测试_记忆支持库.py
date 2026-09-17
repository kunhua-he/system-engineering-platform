"""记忆支持库契约与统一调用边界测试。"""
from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from 公共契约.基础类型.结果类型 import 结果
from 支持库.后端.记忆支持库.实现 import 记忆


class 假调用器:
    def __init__(self) -> None:
        self.调用记录: list[tuple[str, dict]] = []

    def 调用能力(self, 能力id: str, 参数: dict, **_) -> 结果:
        self.调用记录.append((能力id, dict(参数)))
        if 能力id.endswith("连接向量模型"):
            return 结果.成功结果({"句柄": 123456})
        if 能力id.endswith("生成嵌入"):
            return 结果.成功结果({"向量": [0.1, 0.2, 0.3], "维度": 3})
        if 能力id.endswith("释放句柄"):
            return 结果.成功结果({"句柄": 123456, "状态": "已结束并已释放"})
        return 结果.失败("能力不存在", 能力id)


class 测试记忆支持库(unittest.TestCase):
    根目录 = Path(__file__).resolve().parents[2]
    包目录 = 根目录 / "支持库" / "后端" / "记忆支持库"

    def test_生成向量只经统一调用器并释放句柄(self) -> None:
        调用器 = 假调用器()
        with patch("公共契约.能力契约.调用器.获取能力调用器", return_value=调用器):
            向量 = 记忆._生成向量("测试文本")
        self.assertEqual(向量, [0.1, 0.2, 0.3])
        self.assertEqual(
            [记录[0] for 记录 in 调用器.调用记录],
            [
                "大语言模型支持库.模型连接器.连接向量模型",
                "大语言模型支持库.模型连接器.生成嵌入",
                "大语言模型支持库.模型连接器.释放句柄",
            ],
        )
        self.assertEqual(调用器.调用记录[1][1]["句柄"], 123456)
        self.assertEqual(调用器.调用记录[2][1]["句柄"], 123456)

    def test_包依赖声明覆盖向量连接生成和释放(self) -> None:
        声明 = json.loads((self.包目录 / "包声明.json").read_text(encoding="utf-8"))
        依赖契约 = json.loads(
            (self.包目录 / "依赖契约" / "依赖契约.json").read_text(encoding="utf-8")
        )
        预期 = {
            "大语言模型支持库.模型连接器.连接向量模型",
            "大语言模型支持库.模型连接器.生成嵌入",
            "大语言模型支持库.模型连接器.释放句柄",
        }
        self.assertEqual({项目["能力"] for 项目 in 声明["依赖"]}, 预期)
        self.assertEqual({项目["能力"] for 项目 in 依赖契约["依赖"]}, 预期)

    def test_写能力副作用不是只读(self) -> None:
        定义 = json.loads((self.包目录 / "能力定义.json").read_text(encoding="utf-8"))
        写能力 = {"写入记忆", "追加记忆", "完成记忆", "删除记忆"}
        for 能力 in 定义["能力列表"]:
            if 能力["中文名称"] in 写能力:
                self.assertNotEqual(能力["行为"]["副作用"], "只读")

    def test_项目维度参数已进契约与注册入口(self) -> None:
        """项目维度必须同时在 能力定义、能力契约、包声明、注册入口 四处到位。"""
        定义 = json.loads((self.包目录 / "能力定义.json").read_text(encoding="utf-8"))
        契约 = json.loads((self.包目录 / "能力契约" / "参数契约.json").read_text(encoding="utf-8"))
        声明 = json.loads((self.包目录 / "包声明.json").read_text(encoding="utf-8"))
        预期 = {
            "记忆支持库.写入记忆": {"项目"},
            "记忆支持库.追加记忆": {"项目"},
            "记忆支持库.搜索记忆": {"项目", "仅关键词"},
            "记忆支持库.最近记忆": {"项目"},
            "记忆支持库.列出记忆": {"项目"},
        }
        来源 = {
            "能力定义": {能力["能力id"]: {参数["名称"] for 参数 in 能力["参数"]}
                     for 能力 in 定义["能力列表"]},
            "能力契约": {条目["能力id"]: {参数["名称"] for 参数 in 条目["参数"]}
                     for 条目 in 契约["能力契约"]},
            "包声明": {能力["能力id"]: {参数["名称"] for 参数 in 能力["参数"]}
                    for 能力 in 声明["能力"]},
        }
        for 能力id, 参数名 in 预期.items():
            for 名称, 表 in 来源.items():
                self.assertTrue(参数名 <= 表[能力id],
                                f"{名称} 缺 {能力id} 的 {参数名 - 表[能力id]}")
        入口文本 = (self.包目录 / "__init__.py").read_text(encoding="utf-8")
        self.assertIn('"名称": "仅关键词", "类型": "逻辑型"', 入口文本)
        self.assertEqual(入口文本.count('"名称": "项目"'), 5)


class 记账调用器:
    """记录每一次大模型能力调用；仅关键词模式必须一次都不调。"""

    def __init__(self) -> None:
        self.调用记录: list[str] = []

    def 调用能力(self, 能力id: str, 参数: dict, **_) -> 结果:
        self.调用记录.append(能力id)
        if 能力id.endswith("连接向量模型"):
            return 结果.成功结果({"句柄": 123456})
        if 能力id.endswith("生成嵌入"):
            return 结果.成功结果({"向量": [0.1, 0.2, 0.3]})
        if 能力id.endswith("释放句柄"):
            return 结果.成功结果({"句柄": 123456})
        return 结果.失败("能力不存在", 能力id)


class 测试记忆项目维度(unittest.TestCase):
    """项目维度隔离：各项目各查各的，不传项目仍查全部。"""

    def setUp(self) -> None:
        self.临时 = Path(tempfile.mkdtemp())
        self.库 = str(self.临时 / "记忆库.db")

    def _写入样例(self) -> None:
        记忆.写入记忆(项目="A项目", 名称="部署流程",
                      正文="A项目部署流程，先跑环境自检。", 标签=["部署"], 库路径=self.库)
        记忆.写入记忆(项目="B项目", 名称="部署流程",
                      正文="B项目部署流程，先跑场景体检。", 标签=["部署"], 库路径=self.库)
        记忆.写入记忆(名称="公共备忘", 正文="不归属项目。", 库路径=self.库)

    def test_同名记忆跨项目互不覆盖(self) -> None:
        A = 记忆.写入记忆(项目="A项目", 名称="部署流程", 正文="A正文。", 库路径=self.库)
        B = 记忆.写入记忆(项目="B项目", 名称="部署流程", 正文="B正文。", 库路径=self.库)
        self.assertTrue(A.成功 and B.成功)
        self.assertNotEqual(A.值["标识"], B.值["标识"])
        A查 = 记忆.搜索记忆(项目="A项目", 查询="部署流程", 仅关键词=True, 库路径=self.库)
        self.assertEqual([项["正文"] for 项 in A查.值["记忆列表"]], ["A正文。"])
        B查 = 记忆.搜索记忆(项目="B项目", 查询="部署流程", 仅关键词=True, 库路径=self.库)
        self.assertEqual([项["正文"] for 项 in B查.值["记忆列表"]], ["B正文。"])

    def test_不传项目标识与旧口径逐字一致(self) -> None:
        结果对象 = 记忆.写入记忆(名称="旧口径记忆", 正文="正文。", 库路径=self.库)
        self.assertEqual(结果对象.值["标识"], 记忆.生成标识("旧口径记忆"))

    def test_同项目内同名写入幂等(self) -> None:
        记忆.写入记忆(项目="A项目", 名称="幂等记忆", 正文="第一版。", 库路径=self.库)
        记忆.写入记忆(项目="A项目", 名称="幂等记忆", 正文="第二版。", 库路径=self.库)
        结果对象 = 记忆.列出记忆(项目="A项目", 库路径=self.库)
        self.assertEqual(结果对象.值["数量"], 1)
        self.assertEqual(结果对象.值["记忆列表"][0]["正文"], "第二版。")

    def test_按项目查询各查各的且不传项目查全部(self) -> None:
        self._写入样例()
        A = 记忆.最近记忆(项目="A项目", 库路径=self.库)
        self.assertEqual([项["项目"] for 项 in A.值["记忆列表"]], ["A项目"])
        B = 记忆.列出记忆(项目="B项目", 库路径=self.库)
        self.assertEqual([项["项目"] for 项 in B.值["记忆列表"]], ["B项目"])
        全部 = 记忆.列出记忆(库路径=self.库)
        self.assertEqual(全部.值["数量"], 3)
        self.assertEqual(sorted({项["项目"] for 项 in 全部.值["记忆列表"]}),
                         ["", "A项目", "B项目"])

    def test_仅关键词模式一次大模型都不调(self) -> None:
        self._写入样例()
        调用器 = 记账调用器()
        with patch("公共契约.能力契约.调用器.获取能力调用器", return_value=调用器):
            结果对象 = 记忆.搜索记忆(项目="A项目", 查询="部署",
                                    仅关键词=True, 库路径=self.库)
        self.assertEqual(调用器.调用记录, [])
        self.assertTrue(结果对象.成功)
        self.assertEqual(结果对象.值["数量"], 1)
        self.assertEqual(结果对象.值["记忆列表"][0]["分数"], 1.0)

    def test_仅关键词在标签上大小写不敏感匹配(self) -> None:
        记忆.写入记忆(名称="标签命中", 正文="正文与关键词无关。",
                      标签=["Deploy_Pipeline"], 库路径=self.库)
        结果对象 = 记忆.搜索记忆(查询="deploy_pipeline", 仅关键词=True, 库路径=self.库)
        self.assertEqual(结果对象.值["数量"], 1)
        self.assertEqual(结果对象.值["记忆列表"][0]["分数"], 1.0)

    def test_默认模式下大模型仍被调用(self) -> None:
        self._写入样例()
        调用器 = 记账调用器()
        with patch("公共契约.能力契约.调用器.获取能力调用器", return_value=调用器):
            记忆.搜索记忆(查询="部署", 库路径=self.库)
        self.assertIn("大语言模型支持库.模型连接器.连接向量模型", 调用器.调用记录)

    def test_项目内追加能命中同项目同名记忆(self) -> None:
        记忆.写入记忆(项目="A项目", 名称="追加目标", 正文="初版。", 库路径=self.库)
        追加 = 记忆.追加记忆(项目="A项目", 标题="追加目标", 细节="追加内容。", 库路径=self.库)
        self.assertTrue(追加.值["已追加"])
        结果对象 = 记忆.列出记忆(项目="A项目", 库路径=self.库)
        self.assertEqual(结果对象.值["数量"], 1)
        self.assertIn("追加内容。", 结果对象.值["记忆列表"][0]["正文"])


class 测试记忆老库迁移(unittest.TestCase):
    """老库（无 项目 列）打开即自动迁移：不丢数据、幂等。"""

    def setUp(self) -> None:
        self.临时 = Path(tempfile.mkdtemp())
        self.库 = str(self.临时 / "老记忆库.db")
        连接 = sqlite3.connect(self.库)
        with 连接:
            连接.execute("""
                CREATE TABLE 项目记忆(
                  标识 TEXT PRIMARY KEY, 名称 TEXT NOT NULL, 记忆类型 TEXT NOT NULL,
                  深度 TEXT NOT NULL, 状态 TEXT NOT NULL, 标签 TEXT NOT NULL,
                  智能体 TEXT NOT NULL, 正文 TEXT NOT NULL, 创建时间 TEXT NOT NULL,
                  更新时间 REAL NOT NULL);
            """)
            连接.execute(
                "INSERT INTO 项目记忆 VALUES (?,?,?,?,?,?,?,?,?,?)",
                ("老记忆", "老记忆", "参考", "standard", "已保存", "[]", "",
                 "迁移前写入的老正文。", "2026-01-01T00:00:00+08:00", 1.0))
        连接.close()

    def _列名(self) -> list[str]:
        连接 = sqlite3.connect(self.库)
        try:
            return [行[1] for 行 in 连接.execute("PRAGMA table_info(项目记忆)")]
        finally:
            连接.close()

    def test_老库自动补列且老数据不丢(self) -> None:
        self.assertNotIn("项目", self._列名())
        结果对象 = 记忆.最近记忆(库路径=self.库)
        self.assertTrue(结果对象.成功)
        self.assertIn("项目", self._列名())
        老行 = [项 for 项 in 结果对象.值["记忆列表"] if 项["标识"] == "老记忆"]
        self.assertEqual(len(老行), 1)
        self.assertEqual(老行[0]["项目"], "")
        self.assertEqual(老行[0]["正文"], "迁移前写入的老正文。")

    def test_迁移幂等重复打开不出错(self) -> None:
        for _ in range(3):
            结果对象 = 记忆.最近记忆(库路径=self.库)
            self.assertTrue(结果对象.成功, 结果对象.错误说明)
        self.assertEqual(self._列名().count("项目"), 1)

    def test_迁移后按项目写入与查询可用(self) -> None:
        记忆.写入记忆(项目="新项目", 名称="迁移后记忆", 正文="新正文。", 库路径=self.库)
        结果对象 = 记忆.列出记忆(项目="新项目", 库路径=self.库)
        self.assertEqual(结果对象.值["数量"], 1)
        self.assertEqual(结果对象.值["记忆列表"][0]["正文"], "新正文。")
        全部 = 记忆.列出记忆(库路径=self.库)
        self.assertEqual(全部.值["数量"], 2)


if __name__ == "__main__":
    unittest.main()
