"""项目文档支持库 · 集合级判据定向回归测试。

覆盖新增两条能力：`扫描文档集合` / `校验集合判据`，共 4 种集合判据类型。

口径（AGENTS.md 分级验证）：属「工作包」级定向入口，只验真实返回值，不打桩成功；
临时文档一律落在临时目录，不碰仓库真文件。

**每条判据都必须有反向样本**（哲学 12.5「样本＝接口义务」）：正向通过 1 条 + 故意弄坏必报红 1 条。
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

from 支持库.后端.项目文档支持库 import 扫描文档集合, 校验集合判据  # noqa: E402
from 支持库.后端.项目文档支持库.实现.集合扫描 import _归一豁免, _被豁免  # noqa: E402

方案判据文件 = str(Path(根) / "开发文档/规范/方案文档生命周期判据.json")


class 临时文档树(unittest.TestCase):
    """提供一次性临时文档树，供集合判据真跑。"""

    def setUp(self) -> None:
        self._目录 = tempfile.TemporaryDirectory(prefix="集合判据用例_")
        self.根 = Path(self._目录.name)

    def tearDown(self) -> None:
        self._目录.cleanup()

    def 写文档(self, 相对路径: str, 正文: str) -> Path:
        目标 = self.根 / 相对路径
        目标.parent.mkdir(parents=True, exist_ok=True)
        目标.write_text(正文, encoding="utf-8")
        return 目标

    def 写判据(self, 判据列表: list[dict], **额外) -> str:
        数据 = {"判据版本": "1.0.0", "唯一真源": "（用例）", "文件名模式": "*.md", "判据": 判据列表}
        数据.update(额外)
        路径 = self.根 / "判据.json"
        路径.write_text(json.dumps(数据, ensure_ascii=False), encoding="utf-8")
        return str(路径)


class 测试扫描文档集合(临时文档树):
    """扫描：数量/字段/豁免/上限/参数校验。"""

    def test_扫描出全部文档且字段齐全(self):
        self.写文档("示例文档.md", "# 示例文档\n\n正文\n")
        self.写文档("子目录/另一份.md", "# 另一份\n")
        结果 = 扫描文档集合(根目录=str(self.根), 文件名模式="*.md")
        self.assertTrue(结果.成功, 结果.错误说明)
        值 = 结果.值
        self.assertEqual(值["文档数"], 2)
        首 = 值["文档列表"][0]
        for 字段 in ("相对路径", "行数", "字节数", "修改时间", "可解析文本"):
            self.assertIn(字段, 首)
        # 稳定排序按路径字符串；中文排序下「子目录/…」在前，据实断言
        self.assertEqual({x["相对路径"] for x in 值["文档列表"]}, {"示例文档.md", "子目录/另一份.md"})

    def test_读正文开关生效(self):
        self.写文档("示例文档.md", "# 示例文档\n")
        不读 = 扫描文档集合(根目录=str(self.根))
        读 = 扫描文档集合(根目录=str(self.根), 是否读正文=True)
        self.assertNotIn("正文", 不读.值["文档列表"][0])
        self.assertEqual(读.值["文档列表"][0]["正文"], "# 示例文档\n")

    def test_豁免目录按片段逐段比较_子串不误伤(self):
        self.写文档("归档/示例文档.md", "# 示例文档\n")
        self.写文档("归档说明/另一份.md", "# 另一份\n")
        结果 = 扫描文档集合(根目录=str(self.根), 豁免目录=["归档"])
        self.assertTrue(结果.成功)
        路径表 = [x["相对路径"] for x in 结果.值["文档列表"]]
        self.assertNotIn("归档/示例文档.md", 路径表)      # 豁免生效
        self.assertIn("归档说明/另一份.md", 路径表)      # 同名前缀不被误伤

    def test_豁免写相对仓库根的全路径也能生效(self):
        """★ 反向验证过的真 bug：不剥首段时 `外层/归档` 永远匹配不上，豁免静默失效。"""
        self.写文档("归档/示例文档.md", "# 示例文档\n")
        self.写文档("保留/另一份.md", "# 另一份\n")
        结果 = 扫描文档集合(根目录=str(self.根), 豁免目录=[f"{self.根.name}/归档"])
        self.assertTrue(结果.成功)
        路径表 = [x["相对路径"] for x in 结果.值["文档列表"]]
        self.assertNotIn("归档/示例文档.md", 路径表)

    def test_豁免归一剥首段(self):
        表 = _归一豁免(["开发文档/归档", "工程缓存"], 根名="开发文档")
        self.assertIn(("归档",), 表)
        self.assertIn(("工程缓存",), 表)

    def test_豁免逐段比较_不做子串匹配(self):
        表 = _归一豁免(["归档"], 根名="")
        self.assertTrue(_被豁免(("归档", "示例文档.md"), 表))
        self.assertFalse(_被豁免(("归档说明", "示例文档.md"), 表))

    def test_超出上限明确失败不静默截断(self):
        for 序号 in range(3):
            self.写文档(f"方案{序号}.md", "# 标题\n")
        结果 = 扫描文档集合(根目录=str(self.根), 最大文档数=2)
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "文档数超出上限")

    def test_参数非法明确失败(self):
        for 参, 期望码 in [
            (dict(根目录=""), "参数不合法"),
            (dict(根目录="/不存在的目录_xyz"), "根目录不存在"),
            (dict(根目录=str(self.根), 文件名模式=""), "参数不合法"),
        ]:
            结果 = 扫描文档集合(**参)
            self.assertFalse(结果.成功, 参)
            self.assertEqual(结果.错误码, 期望码, 参)


class 测试集合唯一判据(临时文档树):
    """集合唯一：全仓命中文档数必须等于期望。"""

    判据 = {"判据id": "编排唯一", "严重级": "阻断", "说明": "只允许一份自称入口",
            "类型": "集合唯一",
            "参数": {"模式": "^# .*唯一入口", "期望": 1, "跳过围栏": True}}

    def test_正向_恰好一份通过(self):
        self.写文档("入口方案.md", "# 执行编排（唯一入口）\n")
        self.写文档("子方案.md", "# 子方案\n")
        结果 = 校验集合判据(根目录=str(self.根), 判据文件=self.写判据([self.判据]))
        self.assertTrue(结果.值["通过"], 结果.值["违规条目"])
        self.assertEqual(结果.值["文档数"], 2)

    def test_反向_两份并存必须报红(self):
        self.写文档("入口方案.md", "# 执行编排（唯一入口）\n")
        self.写文档("子方案.md", "# 子方案（唯一入口）\n")
        结果 = 校验集合判据(根目录=str(self.根), 判据文件=self.写判据([self.判据]))
        self.assertFalse(结果.值["通过"])
        self.assertEqual(结果.值["驳回项数"], 2)
        文件集 = {x["文件"] for x in 结果.值["违规条目"]}
        self.assertEqual(文件集, {"入口方案.md", "子方案.md"})

    def test_反向_一份都没有也要报红(self):
        self.写文档("子方案.md", "# 子方案\n")
        结果 = 校验集合判据(根目录=str(self.根), 判据文件=self.写判据([self.判据]))
        self.assertFalse(结果.值["通过"])

    def test_围栏内的自称不算(self):
        self.写文档("入口方案.md", "# 执行编排（唯一入口）\n\n```\n# 假入口（唯一入口）\n```\n")
        结果 = 校验集合判据(根目录=str(self.根), 判据文件=self.写判据([self.判据]))
        self.assertTrue(结果.值["通过"], 结果.值["违规条目"])


class 测试状态枚举判据(临时文档树):
    """状态枚举：状态行取值必须落在五态内。"""

    判据 = {"判据id": "状态声明合法", "严重级": "阻断", "说明": "取值须在五态内",
            "类型": "状态枚举",
            "参数": {"行前缀": "> 状态：", "取值枚举": ["起草", "生效", "已完结", "已取代", "已废弃"]}}

    def test_正向_五态取值都通过(self):
        for 序号, 态 in enumerate(["起草", "生效", "已完结", "已取代", "已废弃"]):
            self.写文档(f"方案{序号}.md", f"# 方案{序号}\n\n> 状态：**{态}（2026-09-18）**\n")
        结果 = 校验集合判据(根目录=str(self.根), 判据文件=self.写判据([self.判据]))
        self.assertTrue(结果.值["通过"], 结果.值["违规条目"])

    def test_反向_非法取值必须报红(self):
        """★ 这是本轮实证的判据缺陷：只查「有没有状态行」时，写 `已删除` 也能骗过。"""
        self.写文档("示例文档.md", "# 示例文档\n\n> 状态：已删除\n")
        结果 = 校验集合判据(根目录=str(self.根), 判据文件=self.写判据([self.判据]))
        self.assertFalse(结果.值["通过"])
        self.assertEqual(结果.值["违规条目"][0]["文件"], "示例文档.md")

    def test_反向_必须存在时缺状态行报红(self):
        """`必须存在` 为真（规范要求每份方案都要有状态声明）时，缺状态行必须报红。"""
        判据 = dict(self.判据, 参数={**self.判据["参数"], "必须存在": True})
        self.写文档("示例文档.md", "# 示例文档\n\n正文\n")
        结果 = 校验集合判据(根目录=str(self.根), 判据文件=self.写判据([判据]))
        self.assertFalse(结果.值["通过"])
        self.assertIn("缺状态声明", 结果.值["违规条目"][0]["说明"])

    def test_无状态行的文档不产生违规(self):
        # 不写状态行的文档：行前缀不命中 → 本条不报（「必须写状态」是另一条判据的事）
        self.写文档("示例文档.md", "# 示例文档\n\n> 状态：**生效**\n")
        结果 = 校验集合判据(根目录=str(self.根), 判据文件=self.写判据([self.判据]))
        self.assertTrue(结果.值["通过"])


class 测试引用可达判据(临时文档树):
    """引用可达：本地链接目标必须存在。"""

    判据 = {"判据id": "引用可达", "严重级": "建议", "说明": "链接目标须存在",
            "类型": "引用可达", "参数": {}}

    def test_正向_目标存在通过(self):
        self.写文档("示例文档.md", "# 示例文档\n\n见 [另一份](另一份.md)\n")
        self.写文档("另一份.md", "# 另一份\n")
        结果 = 校验集合判据(根目录=str(self.根), 判据文件=self.写判据([self.判据]))
        违 = [x for x in 结果.值["违规条目"] if x["判据id"] == "引用可达"]
        self.assertEqual(违, [])

    def test_反向_悬空引用必须报出(self):
        self.写文档("示例文档.md", "# 示例文档\n\n见 [不存在](不存在.md)\n")
        结果 = 校验集合判据(根目录=str(self.根), 判据文件=self.写判据([self.判据]))
        违 = [x for x in 结果.值["违规条目"] if x["判据id"] == "引用可达"]
        self.assertEqual(len(违), 1)
        self.assertEqual(违[0]["行号"], 3)

    def test_行内代码里的链接示例不算(self):
        """★ 本轮实证的误报：规范文档里写 `` `[X](Y)` `` 当示例，被当成真链接。"""
        self.写文档("示例文档.md", "# 示例文档\n\n| 列 | `[X](Y)` 的写法 |\n")
        结果 = 校验集合判据(根目录=str(self.根), 判据文件=self.写判据([self.判据]))
        违 = [x for x in 结果.值["违规条目"] if x["判据id"] == "引用可达"]
        self.assertEqual(违, [])

    def test_围栏内链接不算(self):
        self.写文档("示例文档.md", "# 示例文档\n\n```\n[不存在](不存在.md)\n```\n")
        结果 = 校验集合判据(根目录=str(self.根), 判据文件=self.写判据([self.判据]))
        违 = [x for x in 结果.值["违规条目"] if x["判据id"] == "引用可达"]
        self.assertEqual(违, [])

    def test_外链与锚点跳过(self):
        self.写文档("示例文档.md", "# 示例文档\n\n[外](https://example.com)\n[锚](#章节)\n[邮件](mailto:a@b.c)\n")
        结果 = 校验集合判据(根目录=str(self.根), 判据文件=self.写判据([self.判据]))
        违 = [x for x in 结果.值["违规条目"] if x["判据id"] == "引用可达"]
        self.assertEqual(违, [])


class 测试跨文档配对判据(临时文档树):
    """跨文档配对：文档命中触发模式时，登记文件须含该文档名。"""

    def setUp(self) -> None:
        super().setUp()
        self.登记 = self.根 / "债务清单.md"
        self.判据 = {"判据id": "隐形债", "严重级": "阻断", "说明": "含待办须登记",
                    "类型": "跨文档配对",
                    "参数": {"触发模式": "待修|待办", "登记文件": str(self.登记), "跳过围栏": True}}

    def test_正向_已登记通过(self):
        self.写文档("子方案.md", "# 子方案\n\n本条待修。\n")
        self.登记.write_text("# 债务清单\n\n| 子方案.md | 待修 |\n", encoding="utf-8")
        结果 = 校验集合判据(根目录=str(self.根), 判据文件=self.写判据([self.判据]))
        self.assertTrue(结果.值["通过"], 结果.值["违规条目"])

    def test_反向_未登记必须报红(self):
        self.写文档("子方案.md", "# 子方案\n\n本条待修。\n")
        self.登记.write_text("# 债务清单\n\n（空）\n", encoding="utf-8")
        结果 = 校验集合判据(根目录=str(self.根), 判据文件=self.写判据([self.判据]))
        self.assertFalse(结果.值["通过"])
        self.assertEqual(结果.值["违规条目"][0]["文件"], "子方案.md")

    def test_不含触发词的文档不参与配对(self):
        self.写文档("子方案.md", "# 子方案\n\n一切正常。\n")
        self.登记.write_text("# 债务清单\n", encoding="utf-8")
        结果 = 校验集合判据(根目录=str(self.根), 判据文件=self.写判据([self.判据]))
        self.assertTrue(结果.值["通过"])

    def test_登记文件不存在时报红(self):
        self.写文档("子方案.md", "# 子方案\n\n本条待修。\n")
        结果 = 校验集合判据(根目录=str(self.根), 判据文件=self.写判据([self.判据]))
        self.assertFalse(结果.值["通过"])


class 测试判据文件与真源(临时文档树):
    """判据文件不可读必须明确失败；未实现的判据类型不得假装通过。"""

    def test_判据文件不存在明确失败(self):
        结果 = 校验集合判据(根目录=str(self.根), 判据文件="/不存在/判据.json")
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "判据文件不存在")

    def test_根目录不存在明确失败(self):
        结果 = 校验集合判据(根目录="/不存在的目录_xyz", 判据文件=self.写判据([]))
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "根目录不存在")

    def test_未实现判据类型不假装通过(self):
        self.写文档("示例文档.md", "# 示例文档\n")
        判据 = self.写判据([{"判据id": "假类型", "严重级": "阻断", "说明": "不存在",
                           "类型": "根本没实现", "参数": {}}])
        结果 = 校验集合判据(根目录=str(self.根), 判据文件=判据)
        self.assertFalse(结果.值["通过"])
        self.assertIn("未实现的判据类型", 结果.值["违规条目"][0]["说明"])

    def test_真判据文件可读且真源指向规范(self):
        结果 = 校验集合判据(根目录=f"{根}/开发文档/方案", 判据文件=方案判据文件)
        self.assertTrue(结果.成功, 结果.错误说明)
        self.assertEqual(结果.值["唯一真源"], "开发文档/规范/方案文档生命周期规范.md")

    def test_真判据在真仓库上通过(self):
        """端到端：本仓 开发文档/方案 现状必须通过（三拍的第一拍——破坏前是绿的）。"""
        结果 = 校验集合判据(根目录=f"{根}/开发文档/方案", 判据文件=方案判据文件)
        self.assertTrue(结果.值["通过"], 结果.值["违规条目"])


if __name__ == "__main__":
    unittest.main()
