"""反向断言测试：「公开能力必须有登记」——没登记的公开能力必须真报红（fail-closed）。

背景（`开发文档/未完成事项.md` 第 30 条）：消费者契约注册表**机制齐备但登记表为空**，
而漂移门禁只问「已登记的契约有没有漂移」，**没登记的能力根本不参与对比** →
登记表 0 份时对真实包恒放行。本测试固定三件事：

1. **现场事实**：反向断言跑在真实仓库上必须真的枚举出跨包消费者关系（不是 0 条自证）；
2. **删条即报红**：删掉一条已登记条目后，缺登记清单必须真实多出一条（不是恒定的假绿）；
3. **空表必报红**：空注册表（0 份登记）时断言必须判定阻断，**绝不放行**；
   附加：基线外新增关系、基线损坏两种情况都必须判红（基线读不成不许静默放过）。
"""
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

系统根 = Path(__file__).resolve().parents[2]
if str(系统根) not in sys.path:
    sys.path.insert(0, str(系统根))

from 平台控制面.能力目录.实现.能力入口 import 默认存储目录, 判定消费者登记完整性
from 平台控制面.能力目录.消费者契约注册表 import 消费者契约注册表
from 平台控制面.能力目录.消费者登记判定 import (
    枚举正式包,
    枚举消费者关系,
    判定登记完整性,
    判定登记完整性带基线,
    生成基线,
)


class Test消费者登记完整性反向断言(unittest.TestCase):
    """反向断言：公开能力必须有登记。"""

    @classmethod
    def setUpClass(cls):
        cls.根 = 系统根
        cls.包表 = 枚举正式包(cls.根)
        cls.关系 = 枚举消费者关系(cls.根, cls.包表)
        cls.真实存储 = Path(默认存储目录) / "消费者契约.json"

    def test_现场枚举出真实跨包消费者关系且不是自证空集(self):
        """枚举面必须来自真实仓库：关系非空、提供包非空、能力都能解析到提供者。"""
        self.assertTrue(self.包表, "正式包枚举为空，扫描面未知")
        self.assertTrue(self.关系, "跨包消费者关系枚举为空 —— 判据成了自证")
        self.assertTrue({项["提供包"] for 项 in self.关系 if 项["提供包"]},
                        "没有任何提供者，说明依赖没有解析到能力定义")

    def test_空注册表必须判阻断而不是放行(self):
        """0 份登记 → 每条关系都必须进缺登记清单，断言必须判阻断（fail-closed）。"""
        空目录 = Path(tempfile.mkdtemp(prefix="反向断言空_"))
        try:
            事实 = 判定登记完整性(
                self.根, 注册表=消费者契约注册表.取实例(空目录),
                存储目录=str(空目录), 包表=self.包表)
        finally:
            shutil.rmtree(空目录, ignore_errors=True)
        self.assertEqual(事实["已登记关系数"], 0)
        self.assertEqual(事实["未登记关系数"], 事实["总关系数"])
        self.assertFalse(事实["通过"], "空注册表必须判不通过（放行就是恒放行）")
        self.assertTrue(事实["判定说明"], "判定说明不能为空")

    def test_删掉一条已登记条目后缺登记清单真实多一条(self):
        """真删一条登记 → 缺登记数必须 +1（证明判据真读存储，不是抄现场常量）。"""
        if not self.真实存储.is_file():
            self.skipTest("现场没有注册表存储，跳过删除复核（其余用例已覆盖空表路径）")
        副本 = Path(tempfile.mkdtemp(prefix="反向断言删条_"))
        try:
            shutil.copy2(self.真实存储, 副本 / "消费者契约.json")
            注册表 = 消费者契约注册表.取实例(副本)
            存储 = json.loads((副本 / "消费者契约.json").read_text(encoding="utf-8"))
            能力id, 消费者表 = next((键, 值) for 键, 值 in 存储.items() if 值)
            消费者id = next(iter(消费者表))
            删前 = 判定登记完整性(self.根, 注册表=注册表, 存储目录=str(副本),
                              包表=self.包表)
            删除 = 注册表.删除契约(消费者id, 能力id)
            self.assertTrue(删除["成功"], 删除["消息"])
            删后 = 判定登记完整性(self.根, 注册表=注册表, 存储目录=str(副本),
                              包表=self.包表)
        finally:
            shutil.rmtree(副本, ignore_errors=True)
        self.assertEqual(删后["未登记关系数"], 删前["未登记关系数"] + 1,
                         "删掉一条已登记契约后缺登记数必须真实增加")
        self.assertFalse(删后["通过"])
        新缺 = [项 for 项 in 删后["未登记清单"]
               if 项["能力id"] == 能力id and 项["消费者id"] == 消费者id]
        self.assertTrue(新缺, "被删的那条关系必须出现在缺登记清单里")

    def test_基线外新增关系与基线损坏都必须判红(self):
        """基线只承载存量：基线外新增判红；基线读不成一律全量判红。"""
        空目录 = Path(tempfile.mkdtemp(prefix="反向断言基线_"))
        try:
            空注册表 = 消费者契约注册表.取实例(空目录)
            基线 = 生成基线(self.根, 注册表=空注册表, 存储目录=str(空目录),
                          包表=self.包表)
            self.assertTrue(基线["关系基线"], "基线必须由现场关系生成，不能是空清单")
            # 基线外新增：把第一条挪出基线，它就成了「新增」，必须判红
            基线["关系基线"] = 基线["关系基线"][1:]
            基线文件 = 空目录 / "消费者关系基线.json"
            基线文件.write_text(json.dumps(基线, ensure_ascii=False), encoding="utf-8")
            判 = 判定登记完整性带基线(self.根, 参考目录=空目录, 注册表=空注册表,
                                 存储目录=str(空目录), 包表=self.包表)
            self.assertFalse(判["通过"], "基线外新增关系缺登记必须判红")
            self.assertEqual(判["新增缺登记数"], 1)
            # 基线损坏：必须全量判红，不许静默放过
            坏目录 = Path(tempfile.mkdtemp(prefix="反向断言坏基线_"))
            try:
                (坏目录 / "消费者关系基线.json").write_text("{半截", encoding="utf-8")
                判坏 = 判定登记完整性带基线(self.根, 参考目录=坏目录, 注册表=空注册表,
                                       存储目录=str(空目录), 包表=self.包表)
            finally:
                shutil.rmtree(坏目录, ignore_errors=True)
            self.assertFalse(判坏["通过"], "基线读不成必须判红（fail-closed）")
        finally:
            shutil.rmtree(空目录, ignore_errors=True)

    def test_能力入口返回结论值而失败即失败(self):
        """能力入口按既有口径回带 是否阻断；三个参数可留空并各有缺省。"""
        结果 = 判定消费者登记完整性()
        self.assertTrue(结果.成功, 结果.错误说明)
        值 = 结果.值
        for 键 in ("是否阻断", "总关系数", "已登记关系数", "缺登记关系数",
                  "缺登记清单", "缺字段能力", "未覆盖提供包清单", "判定说明"):
            self.assertIn(键, 值, f"返回缺少 {键}")
        self.assertEqual(值["总关系数"], len(self.关系))


if __name__ == "__main__":
    unittest.main()
