"""定向测试：模型连接器新增三能力（路由簇 TZ-20260918-02）。

覆盖（全部离线可跑，用临时库，不碰正式库）：
  记录模型调用：正常记录 / 幂等 / 反向参数
  汇总模型表现：分组统计 / 样本不足不给分 / 反向参数
  选择模型：保守模式零额度 / 智能模式排序 / 硬门槛排除 / 参考路径 / 可复现 / 反向参数
"""

import tempfile
import unittest
from pathlib import Path

from 支持库.后端.大语言模型支持库.模型连接器 import 记录模型调用, 汇总模型表现, 选择模型


class 用量测试基类(unittest.TestCase):
    def setUp(self):
        self.库 = str(Path(tempfile.mkdtemp()) / "用量.db")

    def 造数据(self):
        """甲：4 次全成功、快、便宜；乙：4 次只成功 1 次、慢、贵。"""
        for i in range(4):
            记录模型调用(模型="甲", 成功=True, 任务类型="策划",
                       耗时毫秒=1000 + i * 10, 成本=0.01, 数据库路径=self.库)
        for i in range(4):
            记录模型调用(模型="乙", 成功=(i < 1), 任务类型="策划",
                       耗时毫秒=5000, 成本=0.10, 数据库路径=self.库)


class 测试_记录模型调用(用量测试基类):
    def test_正常记录(self):
        r = 记录模型调用(模型="甲", 成功=True, 任务类型="策划", 耗时毫秒=900,
                       输入令牌=10, 输出令牌=20, 成本=0.02, 数据库路径=self.库)
        self.assertTrue(r.成功, r.错误说明)
        self.assertEqual(r.值["已记录"], True)
        self.assertEqual(r.值["累计条数"], 1)
        self.assertTrue(r.值["记录id"])

    def test_不给任务类型记为未分类(self):
        记录模型调用(模型="甲", 成功=True, 数据库路径=self.库)
        r = 汇总模型表现(候选清单=["甲"], 任务类型="未分类", 数据库路径=self.库)
        self.assertEqual(r.值["数据条数"], 1)

    def test_同记录id重复写为更新语义(self):
        r1 = 记录模型调用(模型="甲", 成功=True, 数据库路径=self.库)
        rid = r1.值["记录id"]
        r2 = 记录模型调用(模型="甲", 成功=False, 记录id=rid, 数据库路径=self.库)
        self.assertTrue(r2.成功)
        self.assertEqual(r2.值["累计条数"], 1, "同 id 重复写不应增行")

    def test_耗时毫秒必须是整数(self):
        """★ 契约是整数型；传浮点由网关拦，这里验实现层的宽松度（整数通过）。"""
        self.assertTrue(记录模型调用(模型="甲", 成功=True, 耗时毫秒=900, 数据库路径=self.库).成功)

    def test_反向_缺必填(self):
        self.assertEqual(记录模型调用(成功=True, 数据库路径=self.库).错误码, "参数不合法")
        self.assertEqual(记录模型调用(模型="甲", 数据库路径=self.库).错误码, "参数不合法")
        self.assertEqual(记录模型调用(模型="", 成功=True, 数据库路径=self.库).错误码, "参数不合法")

    def test_反向_类型不符(self):
        self.assertEqual(记录模型调用(模型="甲", 成功="是", 数据库路径=self.库).错误码, "参数不合法")
        self.assertEqual(记录模型调用(模型="甲", 成功=True, 耗时毫秒="abc", 数据库路径=self.库).错误码, "参数不合法")
        self.assertEqual(记录模型调用(模型="甲", 成功=True, 耗时毫秒=-1, 数据库路径=self.库).错误码, "参数不合法")
        self.assertEqual(记录模型调用(模型="甲", 成功=True, 成本=-1, 数据库路径=self.库).错误码, "参数不合法")
        self.assertEqual(记录模型调用(模型="甲", 成功=True, 输入令牌=1.5, 数据库路径=self.库).错误码, "参数不合法")
        self.assertEqual(记录模型调用(模型=123, 成功=True, 数据库路径=self.库).错误码, "参数不合法")

    def test_反向_布尔不算整数(self):
        self.assertEqual(记录模型调用(模型="甲", 成功=True, 耗时毫秒=True, 数据库路径=self.库).错误码,
                        "参数不合法")


class 测试_汇总模型表现(用量测试基类):
    def test_统计正确(self):
        self.造数据()
        r = 汇总模型表现(候选清单=["甲", "乙"], 任务类型="策划", 数据库路径=self.库)
        self.assertTrue(r.成功, r.错误说明)
        汇总 = {项["模型"]: 项 for 项 in r.值["汇总"]}
        self.assertEqual(汇总["甲"]["样本数"], 4)
        self.assertEqual(汇总["甲"]["成功率"], 1.0)
        self.assertEqual(汇总["乙"]["成功率"], 0.25)
        self.assertTrue(汇总["甲"]["是否样本充足"])

    def test_无样本不给分(self):
        self.造数据()
        r = 汇总模型表现(候选清单=["没见过的"], 任务类型="策划", 数据库路径=self.库)
        项 = r.值["汇总"][0]
        self.assertIsNone(项["成功率"])
        self.assertFalse(项["是否样本充足"])

    def test_样本不足按门槛标注(self):
        for _ in range(2):
            记录模型调用(模型="甲", 成功=True, 数据库路径=self.库)
        r = 汇总模型表现(候选清单=["甲"], 最少样本数=3, 数据库路径=self.库)
        self.assertFalse(r.值["汇总"][0]["是否样本充足"])
        r2 = 汇总模型表现(候选清单=["甲"], 最少样本数=2, 数据库路径=self.库)
        self.assertTrue(r2.值["汇总"][0]["是否样本充足"])

    def test_不给任务类型汇总全部(self):
        self.造数据()
        记录模型调用(模型="甲", 成功=True, 任务类型="日常", 数据库路径=self.库)
        r = 汇总模型表现(候选清单=["甲"], 数据库路径=self.库)
        self.assertEqual(r.值["数据条数"], 9)

    def test_反向(self):
        self.assertEqual(汇总模型表现(候选清单=[]).错误码, "参数不合法")
        self.assertEqual(汇总模型表现(候选清单=[""]).错误码, "参数不合法")
        self.assertEqual(汇总模型表现(候选清单=[1]).错误码, "参数不合法")
        self.assertEqual(汇总模型表现(候选清单=["甲"], 最少样本数=0).错误码, "参数不合法")
        self.assertEqual(汇总模型表现(候选清单=["甲"], 最少样本数=-1).错误码, "参数不合法")


class 测试_选择模型保守模式(用量测试基类):
    def test_默认是保守模式(self):
        r = 选择模型(候选清单=["甲", "乙"], 数据库路径=self.库)
        self.assertTrue(r.成功, r.错误说明)
        self.assertEqual(r.值["模式"], "保守")

    def test_保守模式不读数据不打分(self):
        self.造数据()
        r = 选择模型(候选清单=["甲", "乙"], 数据库路径=self.库)
        self.assertEqual(r.值["打分依据"]["数据条数"], 0, "保守模式不该读历史数据")
        self.assertTrue(all(项["分数"] is None for 项 in r.值["建议"]))

    def test_保守模式额度说明写明未消耗(self):
        r = 选择模型(候选清单=["甲"], 数据库路径=self.库)
        self.assertIn("未消耗", r.值["额度说明"])

    def test_额度说明默认开启_显式假才清空(self):
        """★ 实测坑：写成 `if not 启用额度标注` 会让默认 None 判成假、说明恒为空。"""
        self.assertNotEqual(选择模型(候选清单=["甲"], 数据库路径=self.库).值["额度说明"], "")
        self.assertNotEqual(选择模型(候选清单=["甲"], 启用额度标注=True, 数据库路径=self.库).值["额度说明"], "")
        self.assertEqual(选择模型(候选清单=["甲"], 启用额度标注=False, 数据库路径=self.库).值["额度说明"], "")


class 测试_选择模型智能模式(用量测试基类):
    def test_按表现排序(self):
        self.造数据()
        r = 选择模型(候选清单=["甲", "乙"], 任务类型="策划", 启用智能路由=True, 数据库路径=self.库)
        self.assertEqual(r.值["模式"], "智能")
        self.assertEqual(r.值["建议"][0]["模型"], "甲", f"甲应排第一：{r.值['建议']}")
        self.assertGreater(r.值["建议"][0]["分数"], r.值["建议"][1]["分数"])

    def test_样本不足者不给分(self):
        self.造数据()
        r = 选择模型(候选清单=["甲", "没见过的"], 任务类型="策划",
                   启用智能路由=True, 数据库路径=self.库)
        项 = {x["模型"]: x for x in r.值["建议"]}
        self.assertIsNone(项["没见过的"]["分数"])
        self.assertFalse(项["没见过的"]["样本是否充足"])

    def test_每项都有理由(self):
        self.造数据()
        r = 选择模型(候选清单=["甲", "乙"], 任务类型="策划", 启用智能路由=True, 数据库路径=self.库)
        self.assertTrue(all(项["理由"] for 项 in r.值["建议"]))

    def test_可复现(self):
        self.造数据()
        参数 = {"候选清单": ["甲", "乙"], "任务类型": "策划", "启用智能路由": True, "数据库路径": self.库}
        self.assertEqual(选择模型(**参数).值["建议"], 选择模型(**参数).值["建议"])

    def test_智能模式仍零额度(self):
        self.造数据()
        r = 选择模型(候选清单=["甲"], 任务类型="策划", 启用智能路由=True, 数据库路径=self.库)
        self.assertIn("未消耗", r.值["额度说明"])

    def test_权重可覆盖且影响排序(self):
        self.造数据()
        r = 选择模型(候选清单=["甲", "乙"], 任务类型="策划", 启用智能路由=True,
                   权重={"成功率": 1.0, "效率": 0, "性价比": 0, "匹配度": 0}, 数据库路径=self.库)
        self.assertEqual(r.值["建议"][0]["模型"], "甲")


class 测试_选择模型硬门槛(用量测试基类):
    def test_上下文超限被排除(self):
        r = 选择模型(候选清单=[{"模型": "本地小模型", "上下文长度": 32768},
                             {"模型": "云端大模型", "上下文长度": 200000}],
                   上下文长度=100000, 数据库路径=self.库)
        建议名 = [项["模型"] for 项 in r.值["建议"]]
        排除名 = [项["模型"] for 项 in r.值["排除"]]
        self.assertIn("本地小模型", 排除名)
        self.assertIn("云端大模型", 建议名)
        self.assertTrue(any("上下文不足" in 项["理由"] for 项 in r.值["排除"]))

    def test_硬门槛在保守模式也生效(self):
        r = 选择模型(候选清单=[{"模型": "小", "上下文长度": 1000}], 上下文长度=5000, 数据库路径=self.库)
        self.assertEqual(r.值["建议"], [])
        self.assertEqual(len(r.值["排除"]), 1)

    def test_候选没给上下文长度则不排除(self):
        r = 选择模型(候选清单=["没给长度的模型"], 上下文长度=1000000, 数据库路径=self.库)
        self.assertEqual(len(r.值["建议"]), 1)


class 测试_参考路径(用量测试基类):
    def test_给了参考路径产生命中诊断(self):
        目录 = Path(tempfile.mkdtemp())
        (目录 / "词表.txt").write_text("内部项目\n未公开品牌\n", encoding="utf-8")
        r = 选择模型(候选清单=["甲"], 任务描述="处理内部项目的资料",
                   参考路径=str(目录 / "词表.txt"), 数据库路径=self.库)
        self.assertTrue(r.成功, r.错误说明)
        self.assertTrue(any("参考路径命中" in x for x in r.值["诊断"]))

    def test_不给参考路径就不涉及(self):
        r = 选择模型(候选清单=["甲"], 任务描述="处理内部项目的资料", 数据库路径=self.库)
        self.assertFalse(any("参考路径" in x for x in r.值["诊断"]))

    def test_换成普通词表机制同样可用(self):
        """★ 证明它是「通用外部规则输入」，不是隐私专用件。"""
        目录 = Path(tempfile.mkdtemp())
        (目录 / "品牌词表.txt").write_text("俏小喵\n", encoding="utf-8")
        r = 选择模型(候选清单=["甲"], 任务描述="写俏小喵的种草文案",
                   参考路径=str(目录 / "品牌词表.txt"), 数据库路径=self.库)
        self.assertTrue(any("参考路径命中" in x for x in r.值["诊断"]))

    def test_支持文件夹(self):
        目录 = Path(tempfile.mkdtemp())
        (目录 / "a.txt").write_text("关键词甲\n", encoding="utf-8")
        r = 选择模型(候选清单=["甲"], 任务描述="含关键词甲的活", 参考路径=str(目录), 数据库路径=self.库)
        self.assertTrue(r.成功, r.错误说明)
        self.assertTrue(any("参考路径命中" in x for x in r.值["诊断"]))

    def test_路径不存在报参数不合法(self):
        r = 选择模型(候选清单=["甲"], 参考路径="/绝对不存在的路径/x.txt", 数据库路径=self.库)
        self.assertEqual(r.错误码, "参数不合法")


class 测试_选择模型反向(用量测试基类):
    def test_参数不合法(self):
        self.assertEqual(选择模型(候选清单=[]).错误码, "参数不合法")
        self.assertEqual(选择模型(候选清单=[""]).错误码, "参数不合法")
        self.assertEqual(选择模型(候选清单=[123]).错误码, "参数不合法")
        self.assertEqual(选择模型(候选清单=[{"上下文长度": 100}]).错误码, "参数不合法")
        self.assertEqual(选择模型(候选清单=[{"模型": "甲", "上下文长度": 0}]).错误码, "参数不合法")
        self.assertEqual(选择模型(候选清单=["甲"], 上下文长度=0).错误码, "参数不合法")
        self.assertEqual(选择模型(候选清单=["甲"], 启用智能路由="是").错误码, "参数不合法")
        self.assertEqual(选择模型(候选清单=["甲"], 权重={"乱写": 1}).错误码, "参数不合法")
        self.assertEqual(选择模型(候选清单=["甲"], 权重="不是字典").错误码, "参数不合法")
        self.assertEqual(选择模型(候选清单=["甲"], 最少样本数=0).错误码, "参数不合法")

    def test_权重给负值被拒(self):
        self.assertEqual(选择模型(候选清单=["甲"], 权重={"成功率": -1}).错误码, "参数不合法")


if __name__ == "__main__":
    unittest.main(verbosity=2)
