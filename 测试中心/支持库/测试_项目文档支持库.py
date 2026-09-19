"""项目文档支持库 定向回归测试：切块 / 规范校验 / 索引库 / 项目登记 四条原子能力。

口径（AGENTS.md 分级验证）：本文件属「工作包」级定向入口，只验真实返回值，
不打桩成功；库文件一律落在临时目录，不碰运行数据根。
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

根 = "/Users/hekunhua/Documents/Agent/PHP/系统工程平台"
if 根 not in sys.path:
    sys.path.insert(0, 根)
os.environ.pop("PYTHONPATH", None)

from 支持库.后端.项目文档支持库 import (  # noqa: E402
    切块,
    校验规范,
    建索引库,
    写入索引,
    查询索引,
    登记项目,
    查询项目,
    解析清单,
    改清单条目,
    校验清单,
)

体例判据 = str(Path(根) / "开发文档/规范/Markdown 文档体例判据.json")

合规正文 = """# 示例文档

> 最后更新：2026-09-17
> 口径：实测
> 维护者：示例模块

## 第一章

正文段落一。

```python
# 围栏内的井号不是标题
print("hello")
```

## 第二章

正文段落二。
"""


class 临时库用例(unittest.TestCase):
    """提供一次性临时库文件路径的基类。"""

    def setUp(self) -> None:
        self._目录 = tempfile.TemporaryDirectory()
        self.库文件 = str(Path(self._目录.name) / "项目文档库.db")

    def tearDown(self) -> None:
        self._目录.cleanup()


class 测试切块(unittest.TestCase):
    """切块：行号正确、围栏内井号不算标题、异常输入明确失败。"""

    def test_标题与段落切块行号正确(self):
        结果对象 = 切块(正文="# 标题1\n\n第一段\n\n## 小标题2\n\n第二段\n")
        self.assertTrue(结果对象.成功, 结果对象.错误说明)
        块列表 = 结果对象.值["块列表"]
        标题块 = [b for b in 块列表 if b["块类型"] == "标题"]
        self.assertEqual([b["块文本"] for b in 标题块], ["# 标题1", "## 小标题2"])
        self.assertEqual([(b["起始行"], b["结束行"]) for b in 标题块], [(1, 1), (5, 5)])

    def test_围栏内井号不算标题(self):
        结果对象 = 切块(正文="# 真标题\n\n```bash\n# 这是注释不是标题\n```\n")
        self.assertTrue(结果对象.成功, 结果对象.错误说明)
        标题块 = [b for b in 结果对象.值["块列表"] if b["块类型"] == "标题"]
        self.assertEqual(len(标题块), 1)
        self.assertEqual(标题块[0]["块文本"], "# 真标题")
        代码块 = [b for b in 结果对象.值["块列表"] if b["块类型"] == "代码"]
        self.assertEqual(len(代码块), 1)
        self.assertEqual((代码块[0]["起始行"], 代码块[0]["结束行"]), (3, 5))

    def test_未闭合围栏如实产出代码块(self):
        结果对象 = 切块(正文="# 标题\n\n```python\n未闭合\n")
        self.assertTrue(结果对象.成功, 结果对象.错误说明)
        代码块 = [b for b in 结果对象.值["块列表"] if b["块类型"] == "代码"]
        self.assertEqual(len(代码块), 1)
        self.assertEqual(代码块[0]["结束行"], 4)

    def test_空正文明确失败(self):
        self.assertEqual(切块(正文=None).错误码, "参数不合法")
        self.assertEqual(切块(正文="   ").错误码, "参数不合法")


class 测试规范校验(unittest.TestCase):
    """校验规范：合规放行、不合规报红、判据缺失明确失败。"""

    def test_合规正文通过(self):
        结果对象 = 校验规范(正文=合规正文, 判据文件=体例判据)
        self.assertTrue(结果对象.成功, 结果对象.错误说明)
        self.assertTrue(结果对象.值["通过"], 结果对象.值["违规范条目"])
        self.assertEqual(结果对象.值["驳回项数"], 0)

    def test_双H1被阻断(self):
        正文 = 合规正文 + "\n# 第二个一级标题\n"
        结果对象 = 校验规范(正文=正文, 判据文件=体例判据)
        self.assertTrue(结果对象.成功, 结果对象.错误说明)
        self.assertFalse(结果对象.值["通过"])
        条目标识 = [e["判据id"] for e in 结果对象.值["违规范条目"]]
        self.assertIn("单H1", 条目标识)
        self.assertEqual(结果对象.值["驳回项数"], 1)

    def test_未闭合围栏被阻断_反向验证(self):
        正文 = 合规正文 + "\n```python\n开了不闭合\n"
        结果对象 = 校验规范(正文=正文, 判据文件=体例判据)
        self.assertTrue(结果对象.成功, 结果对象.错误说明)
        self.assertFalse(结果对象.值["通过"])
        self.assertIn("围栏配对", [e["判据id"] for e in 结果对象.值["违规范条目"]])

    def test_元信息头缺失_仅权威文档口径生效(self):
        正文 = "# 无元信息头的文档\n\n正文。\n"
        普通口径 = 校验规范(正文=正文, 判据文件=体例判据)
        self.assertTrue(普通口径.值["通过"], "普通文档不校验元信息头")
        权威口径 = 校验规范(正文=正文, 判据文件=体例判据, 是否权威文档=True)
        self.assertFalse(权威口径.值["通过"])
        self.assertIn("元信息头", [e["判据id"] for e in 权威口径.值["违规范条目"]])

    def test_口径取值域_合法值通过(self):
        """口径行以「实测」/「历史快照」开头 → 通过（体例规范 3.0 固定句式）。"""
        for 值 in ("实测", "历史快照"):
            正文 = (f"# 文档\n\n> 最后更新：2026-09-20\n"
                    f"> 口径：{值}（其后可跟一句括号补充）\n> 维护者：某职责\n")
            结果对象 = 校验规范(正文=正文, 判据文件=体例判据, 是否权威文档=True)
            self.assertTrue(结果对象.值["通过"], f"「{值}」应通过：{结果对象.值['违规范条目']}")

    def test_口径取值域_长解释与缺行被阻断_反向验证(self):
        """反例：把口径改写成小标题式长解释、或干脆不写口径行 → 必须被阻断。"""
        长解释 = ("# 文档\n\n> 最后更新：2026-09-20\n"
                  "> 口径：**只写不变式与取证命令，不写会漂的具体数字**（包数/能力数…）\n> 维护者：某职责\n")
        结果对象 = 校验规范(正文=长解释, 判据文件=体例判据, 是否权威文档=True)
        self.assertFalse(结果对象.值["通过"])
        self.assertIn("口径取值域", [e["判据id"] for e in 结果对象.值["违规范条目"]])
        缺行 = "# 文档\n\n> 最后更新：2026-09-20\n> 维护者：某职责\n"
        结果对象2 = 校验规范(正文=缺行, 判据文件=体例判据, 是否权威文档=True)
        self.assertFalse(结果对象2.值["通过"])
        self.assertIn("口径取值域", [e["判据id"] for e in 结果对象2.值["违规范条目"]])

    def test_口径取值域_不误伤正文提及口径(self):
        """边界：正文（非引用行）里出现「口径」二字不得被当成元信息行（2026-09-20 实测踩坑）。"""
        正文 = ("# 文档\n\n> 最后更新：2026-09-20 · 某批（已闭合条目按口径直接删除）\n"
                "> 口径：实测\n> 维护者：某职责\n")
        结果对象 = 校验规范(正文=正文, 判据文件=体例判据, 是否权威文档=True)
        self.assertTrue(结果对象.值["通过"], 结果对象.值["违规范条目"])

    def test_判据文件不存在时明确失败(self):
        结果对象 = 校验规范(正文=合规正文, 判据文件="/tmp/不存在的判据_20260917.json")
        self.assertFalse(结果对象.成功)
        self.assertEqual(结果对象.错误码, "判据文件不存在")

    def test_判据文件与体例规范同源(self):
        """判据文件声明的唯一真源必须真实存在（防判据与规范漂移）。"""
        数据 = json.loads(Path(体例判据).read_text(encoding="utf-8"))
        真源 = Path(根) / 数据["唯一真源"]
        self.assertTrue(真源.is_file(), f"判据文件声明的唯一真源不存在: {真源}")
        规范正文 = 真源.read_text(encoding="utf-8")
        for 判据 in 数据["判据"]:
            所在节 = 判据.get("对应规范节", "")
            节标题 = 所在节.split(" ")[-1] if 所在节 else ""
            self.assertTrue(
                节标题 and 节标题 in 规范正文,
                f"判据 {判据['判据id']} 引用的规范节「{所在节}」在规范正文里找不到",
            )


class 测试索引库(临时库用例):
    """索引库：建表幂等、写入覆盖更新、查询命中与空命中、项目隔离。"""

    def _写(self, 项目名: str, 路径: str, 正文: str):
        切块结果 = 切块(正文=正文)
        self.assertTrue(切块结果.成功, 切块结果.错误说明)
        return 写入索引(
            项目名=项目名, 文档相对路径=路径,
            块列表=切块结果.值["块列表"], 库文件=self.库文件,
        )

    def test_建索引库幂等且表齐(self):
        第一次 = 建索引库(库文件=self.库文件)
        self.assertTrue(第一次.成功, 第一次.错误说明)
        第二次 = 建索引库(库文件=self.库文件)
        self.assertTrue(第二次.成功, 第二次.错误说明)
        for 表名 in ("项目登记", "文档索引", "块索引"):
            self.assertIn(表名, 第二次.值["表清单"])

    def test_相对路径库文件被拒绝(self):
        结果对象 = 建索引库(库文件="相对路径.db")
        self.assertFalse(结果对象.成功)
        self.assertEqual(结果对象.错误码, "参数不合法")

    def test_写入后查询命中并带行号(self):
        写入结果 = self._写("示例项目", "开发文档/示例.md", 合规正文)
        self.assertTrue(写入结果.成功, 写入结果.错误说明)
        self.assertEqual(写入结果.值["标题"], "示例文档")
        查询结果 = 查询索引(项目名="示例项目", 关键词="正文段落二", 库文件=self.库文件)
        self.assertTrue(查询结果.成功, 查询结果.错误说明)
        self.assertEqual(查询结果.值["命中数"], 1)
        命中 = 查询结果.值["命中列表"][0]
        self.assertEqual(命中["文档相对路径"], "开发文档/示例.md")
        真实行 = 合规正文.split("\n")[命中["起始行"] - 1]
        self.assertIn("正文段落二", 真实行)

    def test_覆盖更新不产生重复块(self):
        self._写("示例项目", "开发文档/示例.md", 合规正文)
        第一次 = 查询索引(项目名="示例项目", 关键词="正文", 库文件=self.库文件).值["命中数"]
        self._写("示例项目", "开发文档/示例.md", 合规正文)
        第二次 = 查询索引(项目名="示例项目", 关键词="正文", 库文件=self.库文件).值["命中数"]
        self.assertEqual(第一次, 第二次)

    def test_查不到返回空列表而不是报错(self):
        结果对象 = 查询索引(项目名="不存在的项目", 关键词="任意词", 库文件=self.库文件)
        self.assertTrue(结果对象.成功)
        self.assertEqual(结果对象.值["命中列表"], [])
        self.assertEqual(结果对象.值["命中数"], 0)

    def test_项目之间互相隔离(self):
        self._写("示例项目1", "开发文档/示例文档1.md", "# 示例文档1\n\n> 最后更新：2026-09-17\n> 口径：实测\n> 维护者：示例模块1\n\n独有关键词1\n")
        self._写("示例项目2", "开发文档/示例文档2.md", "# 示例文档2\n\n> 最后更新：2026-09-17\n> 口径：实测\n> 维护者：示例模块2\n\n独有关键词2\n")
        查1 = 查询索引(项目名="示例项目1", 关键词="独有关键词", 库文件=self.库文件)
        查2 = 查询索引(项目名="示例项目2", 关键词="独有关键词", 库文件=self.库文件)
        self.assertEqual([h["文档相对路径"] for h in 查1.值["命中列表"]], ["开发文档/示例文档1.md"])
        self.assertEqual([h["文档相对路径"] for h in 查2.值["命中列表"]], ["开发文档/示例文档2.md"])


class 测试项目登记(临时库用例):
    """项目登记：新增与覆盖更新幂等、查询可回读、未登记返回空。"""

    def test_登记后查询可回读(self):
        登记结果 = 登记项目(
            项目名="示例项目", 项目根目录=根,
            文档根相对路径="开发文档",
            规范文件="开发文档/规范/Markdown 文档体例规范.md",
            库文件=self.库文件,
        )
        self.assertTrue(登记结果.成功, 登记结果.错误说明)
        self.assertTrue(登记结果.值["是否新增"])
        查询结果 = 查询项目(项目名="示例项目", 库文件=self.库文件)
        self.assertTrue(查询结果.成功, 查询结果.错误说明)
        self.assertEqual(查询结果.值["数量"], 1)
        self.assertEqual(查询结果.值["项目表"][0]["文档根相对路径"], "开发文档")

    def test_重复登记为覆盖更新且不新增第二条(self):
        参数 = dict(项目名="示例项目", 项目根目录=根, 库文件=self.库文件)
        第一次 = 登记项目(**参数)
        第二次 = 登记项目(**参数)
        self.assertTrue(第一次.值["是否新增"])
        self.assertFalse(第二次.值["是否新增"])
        self.assertEqual(查询项目(库文件=self.库文件).值["数量"], 1)

    def test_未登记项目返回空(self):
        结果对象 = 查询项目(项目名="从没登记过的项目", 库文件=self.库文件)
        self.assertTrue(结果对象.成功)
        self.assertEqual(结果对象.值["数量"], 0)

    def test_项目名缺失明确失败(self):
        结果对象 = 登记项目(项目名="", 项目根目录=根, 库文件=self.库文件)
        self.assertFalse(结果对象.成功)
        self.assertEqual(结果对象.错误码, "参数不合法")


清单样例 = """# 示例清单

| 编号 | 事项 | 状态 |
|---|---|---|
| 0001 | 第一件事 | 待办 |
| 0002 | 第二件事 | 已办 |
"""


class 测试解析清单(unittest.TestCase):
    """解析清单：表头/分隔行识别、行号与列值、非表格文本如实报告。"""

    def test_表头与条目识别且行号正确(self):
        结果对象 = 解析清单(正文=清单样例)
        self.assertTrue(结果对象.成功, 结果对象.错误说明)
        self.assertEqual(结果对象.值["表头"], ["编号", "事项", "状态"])
        self.assertEqual(结果对象.值["条目数"], 2)
        条目列表 = 结果对象.值["条目列表"]
        self.assertEqual([项["行号"] for 项 in 条目列表], [5, 6])
        self.assertEqual(条目列表[0]["列值"], ["0001", "第一件事", "待办"])
        self.assertEqual(条目列表[1]["原始行"], "| 0002 | 第二件事 | 已办 |")

    def test_分隔行不被当成条目(self):
        结果对象 = 解析清单(正文="| 编号 | 事项 |\n| --- | --- |\n| 0001 | A |\n")
        self.assertEqual(结果对象.值["条目数"], 1)

    def test_对齐分隔行也识别为分隔行(self):
        # 分隔行带对齐标记（:---:）时同样是分隔行，不是条目；识别错会整表认不出来
        结果对象 = 解析清单(正文="| 编号 | 事项 |\n|:---:|:---|\n| 0001 | A |\n")
        self.assertEqual(结果对象.值["表头"], ["编号", "事项"])
        self.assertEqual(结果对象.值["条目数"], 1)

    def test_缺分隔行的表格不认成清单(self):
        结果对象 = 解析清单(正文="| 编号 | 事项 |\n| 0001 | A |\n")
        self.assertEqual(结果对象.值["条目数"], 0)
        self.assertIn("未识别到", 结果对象.值["提示"])

    def test_非表格文本如实报告零条(self):
        结果对象 = 解析清单(正文="# 只有标题\n\n一段普通文字，没有表格。\n")
        self.assertTrue(结果对象.成功, 结果对象.错误说明)
        self.assertEqual(结果对象.值["条目数"], 0)
        self.assertEqual(结果对象.值["表头"], [])
        self.assertIn("未识别到", 结果对象.值["提示"])

    def test_空正文明确失败(self):
        结果对象 = 解析清单(正文="   ")
        self.assertFalse(结果对象.成功)
        self.assertEqual(结果对象.错误码, "参数不合法")


class 测试改清单条目(unittest.TestCase):
    """改清单条目：增/删/改各一例、编号不复用、定位找不到即失败。"""

    def test_增条目到尾部且正文可再解析(self):
        结果对象 = 改清单条目(正文=清单样例, 操作="增", 条目="0003 | 第三件事 | 待办")
        self.assertTrue(结果对象.成功, 结果对象.错误说明)
        self.assertEqual(结果对象.值["条目数"], 3)
        self.assertIn("| 0003 | 第三件事 | 待办 |", 结果对象.值["新正文"])
        再解析 = 解析清单(正文=结果对象.值["新正文"])
        self.assertEqual([项["列值"][0] for 项 in 再解析.值["条目列表"]],
                         ["0001", "0002", "0003"])

    def test_增条目插到指定编号之后(self):
        结果对象 = 改清单条目(正文=清单样例, 操作="增",
                         条目=["0009", "插队事项", "待办"], 插入位置="0001")
        self.assertTrue(结果对象.成功, 结果对象.错误说明)
        再解析 = 解析清单(正文=结果对象.值["新正文"])
        self.assertEqual([项["列值"][0] for 项 in 再解析.值["条目列表"]],
                         ["0001", "0009", "0002"])

    def test_删条目(self):
        结果对象 = 改清单条目(正文=清单样例, 操作="删", 定位="0001")
        self.assertTrue(结果对象.成功, 结果对象.错误说明)
        self.assertEqual(结果对象.值["条目数"], 1)
        self.assertNotIn("第一件事", 结果对象.值["新正文"])

    def test_改条目保留原编号(self):
        结果对象 = 改清单条目(正文=清单样例, 操作="改", 定位="0002",
                         条目="0002 | 第二件事（已改） | 已办")
        self.assertTrue(结果对象.成功, 结果对象.错误说明)
        self.assertIn("| 0002 | 第二件事（已改） | 已办 |", 结果对象.值["新正文"])
        self.assertEqual(结果对象.值["条目数"], 2)

    def test_增条目缺编号拒绝自动生成(self):
        结果对象 = 改清单条目(正文=清单样例, 操作="增", 条目="|  | 没编号 | 待办 |")
        self.assertFalse(结果对象.成功)
        self.assertEqual(结果对象.错误码, "参数不合法")
        self.assertIn("编号", 结果对象.错误说明)

    def test_增条目用已存在编号被拒(self):
        结果对象 = 改清单条目(正文=清单样例, 操作="增", 条目="0001 | 撞号 | 待办")
        self.assertFalse(结果对象.成功)
        self.assertIn("不复用", 结果对象.错误说明)

    def test_定位找不到即失败(self):
        结果对象 = 改清单条目(正文=清单样例, 操作="删", 定位="9999")
        self.assertFalse(结果对象.成功)
        self.assertEqual(结果对象.错误码, "参数不合法")
        插入失败 = 改清单条目(正文=清单样例, 操作="增", 条目="0010 | A | B",
                          插入位置="9999")
        self.assertFalse(插入失败.成功)

    def test_操作非法即失败(self):
        结果对象 = 改清单条目(正文=清单样例, 操作="排序", 条目="0003 | A | B")
        self.assertFalse(结果对象.成功)
        self.assertEqual(结果对象.错误码, "参数不合法")


class 测试校验清单(unittest.TestCase):
    """校验清单：通过/重复编号/缺列/格式/必填列/非表格文本。"""

    def test_合规清单通过(self):
        结果对象 = 校验清单(正文=清单样例, 必填列="事项,状态")
        self.assertTrue(结果对象.成功, 结果对象.错误说明)
        self.assertTrue(结果对象.值["通过"])
        self.assertEqual(结果对象.值["问题列表"], [])

    def test_重复编号被报出(self):
        结果对象 = 校验清单(正文="| 编号 | 事项 |\n| --- | --- |\n| 0001 | A |\n| 0001 | B |\n")
        self.assertFalse(结果对象.值["通过"])
        self.assertEqual([项["问题id"] for 项 in 结果对象.值["问题列表"]], ["编号重复"])
        self.assertEqual(结果对象.值["问题列表"][0]["行号"], 4)

    def test_缺列被报出(self):
        结果对象 = 校验清单(正文="| 编号 | 事项 | 状态 |\n| --- | --- | --- |\n| 0001 | 只有两列 |\n")
        self.assertFalse(结果对象.值["通过"])
        self.assertIn("缺列", [项["问题id"] for 项 in 结果对象.值["问题列表"]])

    def test_编号格式与必填列问题同时报出(self):
        结果对象 = 校验清单(正文="| 编号 | 事项 |\n| --- | --- |\n| 1 | A |\n| 0002 |  |\n",
                        必填列=["事项"], 编号模式=r"^\d{4}$")
        编号问题 = [项 for 项 in 结果对象.值["问题列表"] if 项["问题id"] == "编号格式不符"]
        必填问题 = [项 for 项 in 结果对象.值["问题列表"] if 项["问题id"] == "必填列为空"]
        self.assertEqual([项["行号"] for 项 in 编号问题], [3])
        self.assertEqual([项["行号"] for 项 in 必填问题], [4])

    def test_不给编号模式时不判格式(self):
        结果对象 = 校验清单(正文="| 编号 | 事项 |\n| --- | --- |\n| 1 | A |\n")
        self.assertTrue(结果对象.值["通过"], 结果对象.值["问题列表"])

    def test_编号列缺失时退化并报出(self):
        结果对象 = 校验清单(正文="| 序号 | 事项 |\n| --- | --- |\n| 0001 | A |\n")
        self.assertIn("编号列缺失", [项["问题id"] for 项 in 结果对象.值["问题列表"]])

    def test_非表格文本判不通过(self):
        结果对象 = 校验清单(正文="这不是表格。\n")
        self.assertTrue(结果对象.成功)
        self.assertFalse(结果对象.值["通过"])
        self.assertEqual(结果对象.值["问题列表"][0]["问题id"], "非表格正文")

    def test_空正文明确失败(self):
        结果对象 = 校验清单(正文="")
        self.assertFalse(结果对象.成功)
        self.assertEqual(结果对象.错误码, "参数不合法")


if __name__ == "__main__":
    unittest.main(verbosity=2)
