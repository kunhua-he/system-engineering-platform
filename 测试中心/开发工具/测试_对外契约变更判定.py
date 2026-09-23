"""定向测试：对外契约变更判定（版本递增判据＝对外契约**面**指纹变化——哲学 5.3 / 决策记录 0020）。

三档**真实包**对照（包 `平台控制面/提供者/注册表`，基线＝当前激活制品内同名包，非夹具）：
① 契约未变 → `内部优化` / 不要求版本递增；
② `/tmp` 副本改一个参数类型 → `契约变化` / 要求递增；
③ 同一副本版本号递增 → 放行（不要求递增）。
反向验证：② 的改动还原 → 回到 ①；版本号改回旧值 → 重新判「要求递增」。

**口径修正（2026-09-17 父会话裁决）**：对外契约面剔除说明文案（`参数.说明` / `返回.值结构`）——
只改说明文案 → `内部优化` / 不要求递增；原始指纹与契约面指纹**两个值同时输出**，
明细里区分「文档性变化（不要求递增）」与「契约面变化（要求递增）」。
规范化＝**同一个** `契约指纹()` ＋ `规范化契约面()` 输入，**不另写第二套指纹算法**（用例含反向反证：
喂「未规范化输入」（原始指纹表当契约面指纹表）时只改说明必须判「契约变化」——
不用 mock 改被测对象，见 `test_反向_未规范化输入下只改说明必变回契约变化`）。

另覆盖：能力级判定、新增/删除能力算契约变化、契约面六维（参数名/类型/必填/默认值/返回类型/错误码）
各一例、硬保守（`上限` 约束键与「非文档形态的值结构」都不剔除）、失败路径 fail-closed、
输出结构固定五键、判据复用唯一事实源（对象同一性）、信封包装。

边界：本测试**不修改仓库既有文件**，全部改动落在 /tmp 副本；不重编译制品、不跑发布门禁。
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

项目根 = Path(__file__).resolve().parents[2]
if str(项目根) not in sys.path:
    sys.path.insert(0, str(项目根))

from 公共契约.基础类型.逻辑类型 import 真, 假
from 开发工具.契约编译 import 对外契约变更判定 as 判定模块
from 开发工具.契约编译.对外契约变更判定 import (
    判定对外契约变更,
    判定能力对外契约变更,
    判定并包装,
    是失败结果,
    读取包契约,
    契约指纹,
    契约面指纹,
    规范化契约面,
    检查契约兼容,
)

真实包相对路径 = "平台控制面/提供者/注册表"
目标能力id = "平台控制面.提供者.注册表.调用提供者"
参数旧类型 = "双精度数型"
参数新类型 = "双精度数形"
固定结构键 = {"变更类别", "变化明细", "是否要求版本递增", "兼容判定", "基线来源"}


def 读制品目录() -> Path:
    """独立按 当前.json 解析激活制品目录（不复用被测模块的私有实现）。

    指针键随版本演进：旧版只有 `路径`，现行版有 `制品目录`（另有 `摘要sha256`）。
    本函数按「制品目录 → 路径 → 平台客户端-<摘要sha256>」逐个尝试，**不写死单键** ——
    写死单键会在指针换键时把「测试陈旧」误报成「产品坏了」（2026-09-22 实测踩到：
    `指针["路径"]` 直接 KeyError，而产品侧早已有同形回退）。
    """
    仓库根 = 项目根 / "工程缓存/制品仓库/平台客户端制品"
    指针 = json.loads((仓库根 / "当前.json").read_text(encoding="utf-8"))
    名 = str(指针.get("制品目录") or 指针.get("路径") or "")
    if not 名:
        摘要 = str(指针.get("摘要sha256") or "")
        assert 摘要, f"激活制品指针既无 制品目录/路径 也无 摘要sha256：{指针}"
        名 = f"平台客户端-{摘要}"
    return 仓库根 / 名


class 对外契约变更判定测试(unittest.TestCase):
    """真实包三档对照 + 反向验证 + 失败路径。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.真实包 = 项目根 / 真实包相对路径
        cls.制品目录 = 读制品目录()
        cls.基线包 = cls.制品目录 / "平台客户端" / 真实包相对路径
        assert cls.真实包.is_dir(), cls.真实包
        assert cls.基线包.is_dir(), cls.基线包
        cls.临时根 = Path(tempfile.mkdtemp(prefix="对外契约变更判定_", dir="/tmp"))

    @classmethod
    def tearDownClass(cls) -> None:
        shutil.rmtree(cls.临时根, ignore_errors=True)

    # ---- 副本工具（只动 /tmp）----

    def 造副本(self, 名字: str) -> Path:
        副本 = self.临时根 / 名字 / 真实包相对路径
        if 副本.exists():
            shutil.rmtree(副本)
        副本.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(self.真实包, 副本)
        # ★ 副本要能改，必须先解掉**复制过来的内核只读标志**：`copytree` 默认走 `copy2`，
        #   会把源文件的 `st_flags`（整仓只读锁的 `uchg`）一起复制 ⇒ 紧接着的
        #   `改副本定义()` 写盘会被内核以 `Operation not permitted` 拒。
        #   按目标位置对齐（目标在 /tmp ⇒ 副本解除锁）—— 唯一实现在锁模块里。
        from 公共契约.运行时.仓库只读锁 import 对齐目标锁态
        对齐目标锁态(副本)
        return 副本

    def 改副本定义(self, 副本: Path, 替换: list[tuple[str, str]]) -> None:
        定义文件 = 副本 / "能力定义.json"
        文本 = 定义文件.read_text(encoding="utf-8")
        for 旧, 新 in 替换:
            self.assertIn(旧, 文本, f"副本里找不到待替换片段：{旧}")
            文本 = 文本.replace(旧, 新, 1)
        定义文件.write_text(文本, encoding="utf-8")

    def 判定副本(self, 副本: Path, **选项):
        return 判定对外契约变更(副本, 基线包目录=self.基线包, **选项)

    # ---- ① 契约未变 ----

    def test_一档_真实包契约未变判内部优化且不要求递增(self) -> None:
        结果 = 判定对外契约变更(真实包相对路径)
        self.assertNotIn("成功", 结果, f"不应是失败信封：{结果}")
        self.assertEqual(结果["变更类别"], "内部优化")
        self.assertIs(结果["是否要求版本递增"], 假)
        self.assertIs(结果["兼容判定"]["指纹是否变化"], 假)
        self.assertEqual(结果["兼容判定"]["结论"], "兼容")
        self.assertEqual(结果["兼容判定"]["对比能力数"], 4)
        # 基线来源必须点名激活制品与包路径（不新建存储）
        self.assertIn(self.制品目录.name, 结果["基线来源"])
        self.assertIn(真实包相对路径, 结果["基线来源"])

    def test_一档_第二个真实包也判内部优化(self) -> None:
        结果 = 判定对外契约变更("支持库/适配层/MCP协议提供者")
        self.assertEqual(结果["变更类别"], "内部优化")
        self.assertIs(结果["是否要求版本递增"], 假)

    # ---- ② 改参数类型一个字 ----

    def test_二档_改参数类型一个字判契约变化并要求递增(self) -> None:
        副本 = self.造副本("二档")
        self.改副本定义(副本, [(参数旧类型, 参数新类型)])
        结果 = self.判定副本(副本)
        self.assertEqual(结果["变更类别"], "契约变化")
        self.assertIs(结果["是否要求版本递增"], 真)
        self.assertIs(结果["兼容判定"]["指纹是否变化"], 真)
        self.assertEqual(结果["兼容判定"]["指纹变化能力"], [目标能力id])
        self.assertTrue(any("参数类型变化" in 行 and 参数新类型 in 行 for 行 in 结果["变化明细"]),
                       结果["变化明细"])
        self.assertTrue(any("必须递增版本" in 行 for 行 in 结果["变化明细"]), 结果["变化明细"])
        # 指纹确实是逐能力独立值，且与既有事实源一致
        新读数 = 读取包契约(副本)
        self.assertEqual(结果["兼容判定"]["新增指纹"][目标能力id],
                         契约指纹(新读数.能力表[目标能力id]))
        self.assertEqual(结果["兼容判定"]["新增指纹"][目标能力id],
                         "9a94479851d3ca3d")  # 改类型后的真实指纹（基线 ab533d8eb95b4cce）

    # ---- ③ 版本递增后放行 ----

    def test_三档_版本递增后放行且不要求递增(self) -> None:
        副本 = self.造副本("三档")
        self.改副本定义(副本, [(参数旧类型, 参数新类型), ('"版本": "1.0.0"', '"版本": "1.1.0"')])
        结果 = self.判定副本(副本)
        self.assertEqual(结果["变更类别"], "契约变化")   # 契约确实变了
        self.assertIs(结果["是否要求版本递增"], 假)     # 但已由版本递增承载 → 放行
        self.assertEqual(结果["兼容判定"]["版本"],
                         {"基线版本": "1.0.0", "新增版本": "1.1.0",
                          "版本判定": "版本已递增", "是否递增": 真})
        self.assertTrue(any("版本已递增合法" in 行 for 行 in 结果["变化明细"]), 结果["变化明细"])

    def test_三档_版本回退仍要求递增(self) -> None:
        副本 = self.造副本("三档回退")
        self.改副本定义(副本, [(参数旧类型, 参数新类型),
                              ('"版本": "1.0.0"', '"版本": "0.9.0"')])
        结果 = self.判定副本(副本)
        self.assertEqual(结果["变更类别"], "契约变化")
        self.assertIs(结果["是否要求版本递增"], 真)
        self.assertEqual(结果["兼容判定"]["版本"]["版本判定"], "版本回退")

    # ---- 反向验证 ----

    def test_反向_还原参数类型改动必须回到内部优化(self) -> None:
        副本 = self.造副本("反向还原")
        原文 = (副本 / "能力定义.json").read_text(encoding="utf-8")
        self.改副本定义(副本, [(参数旧类型, 参数新类型)])
        改后 = self.判定副本(副本)
        self.assertEqual(改后["变更类别"], "契约变化")
        self.assertIs(改后["是否要求版本递增"], 真)
        # 还原改动 → 判定必须回到 ①
        (副本 / "能力定义.json").write_text(原文, encoding="utf-8")
        还原后 = self.判定副本(副本)
        self.assertEqual(还原后["变更类别"], "内部优化")
        self.assertIs(还原后["是否要求版本递增"], 假)
        self.assertEqual(还原后["兼容判定"]["基线指纹"], 改后["兼容判定"]["基线指纹"])
        self.assertEqual(还原后["兼容判定"]["新增指纹"], 还原后["兼容判定"]["基线指纹"])

    def test_反向_版本号改回旧值必须重新要求递增(self) -> None:
        副本 = self.造副本("反向版本")
        self.改副本定义(副本, [(参数旧类型, 参数新类型), ('"版本": "1.0.0"', '"版本": "1.1.0"')])
        self.assertIs(self.判定副本(副本)["是否要求版本递增"], 假)
        self.改副本定义(副本, [('"版本": "1.1.0"', '"版本": "1.0.0"')])
        回退后 = self.判定副本(副本)
        self.assertEqual(回退后["变更类别"], "契约变化")
        self.assertIs(回退后["是否要求版本递增"], 真)
        self.assertEqual(回退后["兼容判定"]["版本"]["版本判定"], "版本未递增")

    # ---- 能力级 ----

    def test_能力级_单能力契约未变判内部优化(self) -> None:
        结果 = 判定能力对外契约变更(真实包相对路径, 目标能力id)
        self.assertEqual(结果["变更类别"], "内部优化")
        self.assertIs(结果["是否要求版本递增"], 假)
        self.assertEqual(结果["兼容判定"]["对比能力数"], 1)
        self.assertEqual(list(结果["兼容判定"]["基线指纹"]), [目标能力id])
        self.assertEqual(结果["兼容判定"]["基线指纹"][目标能力id], "ab533d8eb95b4cce")

    def test_能力级_改该能力参数判契约变化(self) -> None:
        副本 = self.造副本("能力级")
        self.改副本定义(副本, [(参数旧类型, 参数新类型)])
        结果 = self.判定副本(副本, 能力id=目标能力id)
        self.assertEqual(结果["变更类别"], "契约变化")
        self.assertIs(结果["是否要求版本递增"], 真)
        self.assertEqual(结果["兼容判定"]["指纹变化能力"], [目标能力id])

    def test_能力级_改别包能力不影响本能力(self) -> None:
        副本 = self.造副本("能力级旁观")
        数据 = json.loads((副本 / "能力定义.json").read_text(encoding="utf-8"))
        被改 = "平台控制面.提供者.注册表.登记提供者"
        for 能力 in 数据["能力列表"]:
            if 能力["能力id"] == 被改:
                能力["参数"][0]["类型"] = "文本型A"
        (副本 / "能力定义.json").write_text(json.dumps(数据, ensure_ascii=False, indent=1),
                                      encoding="utf-8")
        # 包级一定判契约变化（改了 登记提供者），能力级只看被问的那个能力
        self.assertEqual(self.判定副本(副本)["变更类别"], "契约变化")
        结果 = self.判定副本(副本, 能力id="平台控制面.提供者.注册表.查询提供者")
        self.assertEqual(结果["变更类别"], "内部优化")
        self.assertIs(结果["是否要求版本递增"], 假)

    def test_能力级_基线无此能力时fail_closed(self) -> None:
        结果 = 判定能力对外契约变更(真实包相对路径, "平台控制面.提供者.注册表.不存在的能力")
        self.assertTrue(是失败结果(结果), 结果)
        self.assertEqual(结果["错误码"], "基线能力不存在")
        self.assertIsNone(结果["值"])

    # ---- 新增/删除能力 ----

    def test_包级_删除一个能力算契约变化并要求递增(self) -> None:
        副本 = self.造副本("删能力")
        数据 = json.loads((副本 / "能力定义.json").read_text(encoding="utf-8"))
        数据["能力列表"] = [项 for 项 in 数据["能力列表"] if 项["能力id"] != 目标能力id]
        (副本 / "能力定义.json").write_text(json.dumps(数据, ensure_ascii=False, indent=1),
                                      encoding="utf-8")
        结果 = self.判定副本(副本)
        self.assertEqual(结果["变更类别"], "契约变化")
        self.assertIs(结果["是否要求版本递增"], 真)
        self.assertEqual(结果["兼容判定"]["删除能力"], [目标能力id])

    def test_包级_新增一个能力算契约变化并要求递增(self) -> None:
        副本 = self.造副本("加能力")
        数据 = json.loads((副本 / "能力定义.json").read_text(encoding="utf-8"))
        新能力 = json.loads(json.dumps(数据["能力列表"][0], ensure_ascii=False))
        新能力["能力id"] = 新能力["能力id"] + ".实验分支"
        新能力["中文名称"] = "实验分支"
        数据["能力列表"].append(新能力)
        (副本 / "能力定义.json").write_text(json.dumps(数据, ensure_ascii=False, indent=1),
                                      encoding="utf-8")
        结果 = self.判定副本(副本)
        self.assertEqual(结果["变更类别"], "契约变化")
        self.assertIs(结果["是否要求版本递增"], 真)
        self.assertEqual(结果["兼容判定"]["新增能力"], [新能力["能力id"]])
        self.assertEqual(结果["兼容判定"]["结论"], "兼容")   # 兼容层判向后兼容，指纹层仍判新增对外面

    # ---- 说明变化属内部优化（指纹不含说明）----

    def test_包说明变化属内部优化(self) -> None:
        副本 = self.造副本("说明变化")
        数据 = json.loads((副本 / "能力定义.json").read_text(encoding="utf-8"))
        数据["说明"] = 数据["说明"] + "（内部措辞调整）"
        (副本 / "能力定义.json").write_text(json.dumps(数据, ensure_ascii=False, indent=1),
                                      encoding="utf-8")
        结果 = self.判定副本(副本)
        self.assertEqual(结果["变更类别"], "内部优化")
        self.assertIs(结果["是否要求版本递增"], 假)
        self.assertIs(结果["兼容判定"]["指纹是否变化"], 假)

    def test_参数说明变化判文档性变化属内部优化(self) -> None:
        """口径修正（父会话裁决，2026-09-17）：「说明文案不算契约变化」——原断言「说明变化判契约变化」
        随之改为「文档性变化 / 不要求递增」。**覆盖不减**：原始指纹变化仍被完整断言（说明照样被
        原始指纹抓到），只是判据改走契约面指纹；契约面指纹仍由**同一个** 契约指纹() 产出。"""
        副本 = self.造副本("参数说明")
        数据 = json.loads((副本 / "能力定义.json").read_text(encoding="utf-8"))
        for 能力 in 数据["能力列表"]:
            if 能力["能力id"] == 目标能力id:
                for 参数 in 能力["参数"]:
                    if 参数["名称"] == "超时秒":
                        参数["说明"] = 参数["说明"] + "（措辞调整）"
        (副本 / "能力定义.json").write_text(json.dumps(数据, ensure_ascii=False, indent=1),
                                      encoding="utf-8")
        结果 = self.判定副本(副本)
        兼容 = 结果["兼容判定"]
        self.assertEqual(结果["变更类别"], "内部优化")
        self.assertIs(结果["是否要求版本递增"], 假)
        self.assertEqual(兼容["指纹变化能力"], [目标能力id])        # 原始指纹照样抓到变化
        self.assertIs(兼容["原始指纹是否变化"], 真)
        self.assertEqual(兼容["文档性变化能力"], [目标能力id])
        self.assertEqual(兼容["契约面变化能力"], [])
        self.assertIs(兼容["指纹是否变化"], 假)                  # 判据＝契约面指纹
        self.assertEqual(兼容["新增契约面指纹"], 兼容["基线契约面指纹"])
        self.assertNotEqual(兼容["新增指纹"], 兼容["基线指纹"])
        self.assertTrue(any("文档性变化（不要求递增" in 行 for 行 in 结果["变化明细"]), 结果["变化明细"])
        self.assertTrue(any("参数说明变化" in 行 for 行 in 结果["变化明细"]), 结果["变化明细"])

    def test_返回值结构文案变化也判内部优化(self) -> None:
        """`返回.值结构` 是纯文档字段（决策记录 0019 第 3 项：值结构只作文档性描述）。"""
        副本 = self.造副本("值结构文档")
        数据 = json.loads((副本 / "能力定义.json").read_text(encoding="utf-8"))
        改前 = None
        for 能力 in 数据["能力列表"]:
            if 能力["能力id"] == 目标能力id:
                值结构 = 能力["返回"].get("值结构")
                self.assertIsInstance(值结构, dict, f"真实包该能力应带 值结构：{能力['返回']}")
                键 = sorted(值结构)[0]
                改前 = 值结构[键]
                值结构[键] = 值结构[键] + "（措辞调整）"
        self.assertIsNotNone(改前)
        (副本 / "能力定义.json").write_text(json.dumps(数据, ensure_ascii=False, indent=1),
                                      encoding="utf-8")
        结果 = self.判定副本(副本)
        self.assertEqual(结果["变更类别"], "内部优化")
        self.assertIs(结果["是否要求版本递增"], 假)
        self.assertEqual(结果["兼容判定"]["文档性变化能力"], [目标能力id])
        self.assertEqual(结果["兼容判定"]["结论"], "兼容")
        self.assertTrue(any("返回值结构变化" in 行 for 行 in 结果["变化明细"]), 结果["变化明细"])

    # ---- 契约面变化：逐维各一例，全部必须「契约变化 / 要求递增」----

    def 造改副本(self, 名字: str, 改动) -> Path:
        """造副本，按 `改动(数据)` 就地改 能力定义.json（改动函数自己去改目标能力）。"""
        副本 = self.造副本(名字)
        数据 = json.loads((副本 / "能力定义.json").read_text(encoding="utf-8"))
        改动(数据)
        (副本 / "能力定义.json").write_text(json.dumps(数据, ensure_ascii=False, indent=1),
                                      encoding="utf-8")
        return 副本

    def _目标能力(self, 数据: dict) -> dict:
        for 能力 in 数据["能力列表"]:
            if 能力["能力id"] == 目标能力id:
                return 能力
        raise AssertionError(f"副本内找不到目标能力：{目标能力id}")

    def _目标参数(self, 数据: dict, 名称: str) -> dict:
        for 参数 in self._目标能力(数据)["参数"]:
            if 参数.get("名称") == 名称:
                return 参数
        raise AssertionError(f"副本内找不到目标参数：{名称}")

    def _断言契约面变化(self, 副本: Path) -> None:
        """契约面变化的口径：契约变化 / 要求递增 / 契约面指纹变化能力点名被改能力。"""
        结果 = self.判定副本(副本)
        兼容 = 结果["兼容判定"]
        self.assertEqual(结果["变更类别"], "契约变化", 结果["变化明细"])
        self.assertIs(结果["是否要求版本递增"], 真, 结果["变化明细"])
        self.assertEqual(兼容["契约面变化能力"], [目标能力id], 兼容)
        self.assertIs(兼容["指纹是否变化"], 真)
        self.assertNotEqual(兼容["新增契约面指纹"], 兼容["基线契约面指纹"])
        self.assertTrue(any("契约面变化（要求递增" in 行 for 行 in 结果["变化明细"]), 结果["变化明细"])

    def test_契约面_参数名变化判契约变化(self) -> None:
        def 改(数据):
            参数 = self._目标参数(数据, "存储目录")
            参数["名称"] = "存储目录A"

        self._断言契约面变化(self.造改副本("面_参数名", 改))

    def test_契约面_参数类型变化判契约变化(self) -> None:
        def 改(数据):
            参数 = self._目标参数(数据, "超时秒")
            self.assertEqual(参数["类型"], 参数旧类型, 参数)
            参数["类型"] = 参数新类型

        self._断言契约面变化(self.造改副本("面_参数类型", 改))

    def test_契约面_参数必填变化判契约变化(self) -> None:
        def 改(数据):
            参数 = self._目标参数(数据, "超时秒")
            self.assertIs(参数["必填"], 假, 参数)
            参数["必填"] = 真

        self._断言契约面变化(self.造改副本("面_必填", 改))

    def test_契约面_参数默认值变化判契约变化(self) -> None:
        def 改(数据):
            参数 = self._目标参数(数据, "超时秒")
            self.assertEqual(参数["默认值"], 0.0, 参数)
            参数["默认值"] = 1.0

        self._断言契约面变化(self.造改副本("面_默认值", 改))

    def test_契约面_返回类型变化判契约变化(self) -> None:
        def 改(数据):
            返回 = self._目标能力(数据)["返回"]
            self.assertEqual(返回["类型"], "结果型", 返回)
            返回["类型"] = "结果型A"

        self._断言契约面变化(self.造改副本("面_返回类型", 改))

    def test_契约面_错误码集合变化判契约变化(self) -> None:
        def 改(数据):
            能力 = self._目标能力(数据)
            能力["错误码"] = list(能力["错误码"]) + ["新错误码A"]

        self._断言契约面变化(self.造改副本("面_错误码", 改))

    def test_契约面_参数新增约束键判契约变化_存疑一律保留(self) -> None:
        """硬保守：`上限` 不是文案（是输入约束）→ 留在契约面内，必须判契约变化。"""
        def 改(数据):
            参数 = self._目标参数(数据, "超时秒")
            self.assertNotIn("上限", 参数, 参数)
            参数["上限"] = 100

        self._断言契约面变化(self.造改副本("面_约束键", 改))

    def test_契约面_值结构改成非文档形态仍判契约变化(self) -> None:
        """硬保守第二道闸：键在文档表里，但**值不是文档形态**（列表）→ 保留在契约面内。"""
        def 改(数据):
            self._目标能力(数据)["返回"]["值结构"] = ["不是文档形态"]

        self._断言契约面变化(self.造改副本("面_值结构非文档", 改))

    # ---- 规范化本身：同一指纹函数 + 规范化输入（不得另写第二套算法）----

    def test_规范化_剔除纯文档字段后仍走同一个契约指纹(self) -> None:
        读数 = 读取包契约(self.基线包)
        契约 = 读数.能力表[目标能力id]
        契约面 = 判定模块.规范化契约面(契约)
        # ① 剔除确实生效（原始契约里的说明/值结构在契约面里没了）
        self.assertTrue(all("说明" not in 参数 for 参数 in 契约面["参数"]), 契约面["参数"])
        self.assertNotIn("值结构", 契约面["返回"], 契约面["返回"])
        # ② 每个参数的名字/类型/必填/默认值逐字保留（0020 的面积不动）
        self.assertEqual(
            [(参数.get("名称"), 参数.get("类型"), 参数.get("必填"), 参数.get("默认值"))
             for 参数 in 契约面["参数"]],
            [(参数.get("名称"), 参数.get("类型"), 参数.get("必填"), 参数.get("默认值"))
             for 参数 in 契约["参数"]])
        # ③ 契约面指纹＝**同一个**契约指纹() 吃规范化输入（不是另写的哈希）
        self.assertIs(判定模块.契约指纹, 契约指纹)
        self.assertEqual(判定模块.契约面指纹(契约), 契约指纹(契约面))
        self.assertNotEqual(判定模块.契约面指纹(契约), 契约指纹(契约))   # 说明/值结构原本参与了原始指纹
        # ④ 不修改入参
        self.assertTrue(any("说明" in 参数 for 参数 in 契约["参数"]))
        self.assertIn("值结构", 契约["返回"])
        # ⑤ 剔除字段清单写进输出，供门禁对账
        self.assertEqual(判定模块.文档字段清单, ("参数.说明", "返回.值结构"))
        结果 = self.判定副本(self.造副本("口径输出"))
        self.assertEqual(结果["兼容判定"]["指纹口径"]["剔除字段"], ["参数.说明", "返回.值结构"])

    def test_反向_未规范化输入下只改说明必变回契约变化(self) -> None:
        """反向：规范化在承重——喂「未规范化输入」，同一副本必判契约变化。

        等价反证（**不用 mock 改被测对象**）：规范化关掉后 `契约面指纹 ≡ 原始指纹`，所以把
        **原始指纹表**直接当契约面指纹表喂给生产判据用的同一个分类口径 `_分类变化`
        （它是生产实现，不是测试侧另写的判据），就是「关掉规范化」的等价输入——这一输入下
        契约面变化非空 ⇒ 必判「契约变化 / 要求递增」。规范化在位的生产链路对**同一个副本**
        判「内部优化 / 不要求递增」，两者结论相反 ⇒ 翻转由规范化这一步决定，
        判据没有被写松（判据仍只看指纹）。
        """
        def 改(数据):
            参数 = self._目标参数(数据, "超时秒")
            参数["说明"] = 参数["说明"] + "（措辞调整）"

        副本 = self.造改副本("反向未规范化", 改)
        基线读数 = 读取包契约(self.基线包)
        新读数 = 读取包契约(副本)
        基线契约 = 基线读数.能力表[目标能力id]
        新契约 = 新读数.能力表[目标能力id]
        # ① 未规范化输入：说明确实进了原始指纹 → 关掉规范化时判据必然看到变化
        self.assertNotEqual(契约指纹(基线契约), 契约指纹(新契约))
        # ② 规范化输入：契约面指纹逐字相同
        self.assertEqual(契约面指纹(基线契约), 契约面指纹(新契约))
        # ③ 未规范化输入喂进生产分类口径 → 契约面变化非空（等价「关掉规范化」的旧行为）
        基线原始, 新原始 = 基线读数.指纹表(), 新读数.指纹表()
        原始变化, 契约面变化, 文档性变化 = 判定模块._分类变化(
            [目标能力id], 基线原始, 新原始, 基线原始, 新原始)
        self.assertEqual(原始变化, [目标能力id])
        self.assertEqual(契约面变化, [目标能力id])
        self.assertEqual(文档性变化, [])
        # ④ 生产链路（规范化在位）对同一副本判「内部优化 / 不要求递增」，并点名文档性变化
        结果 = self.判定副本(副本)
        self.assertEqual(结果["变更类别"], "内部优化", 结果["变化明细"])
        self.assertIs(结果["是否要求版本递增"], 假)
        self.assertEqual(结果["兼容判定"]["契约面变化能力"], [])
        self.assertEqual(结果["兼容判定"]["文档性变化能力"], [目标能力id])
        self.assertEqual(结果["兼容判定"]["结论"], "兼容")

    def test_输出结构固定五键(self) -> None:
        for 结果 in (判定对外契约变更(真实包相对路径),
                   判定能力对外契约变更(真实包相对路径, 目标能力id)):
            self.assertEqual(set(结果), 固定结构键, 结果)
            self.assertIn(结果["变更类别"], ("内部优化", "契约变化"))
            self.assertIsInstance(结果["变化明细"], list)
            self.assertIsInstance(结果["是否要求版本递增"], bool)
            self.assertIsInstance(结果["兼容判定"], dict)
            self.assertIsInstance(结果["基线来源"], str)

    def test_判据复用唯一事实源不另写第二套(self) -> None:
        self.assertIs(契约指纹, 判定模块.契约指纹)
        self.assertIs(检查契约兼容, 判定模块.检查契约兼容)
        # 指纹的唯一实现 2026-09-17 下移到公共契约层（越层依赖收口的同一批改动）：
        # 判定模块取的是公共契约的唯一实现，**不是** 平台控制面 那边的同名再导出。
        self.assertEqual(契约指纹.__module__, "公共契约.能力契约.契约指纹")
        self.assertEqual(检查契约兼容.__module__, "运行核心.加载器.版本系统.契约兼容")
        self.assertEqual(判定模块.判据来源,
                         {"指纹": "公共契约.能力契约.契约指纹",
                          "兼容": "运行核心.加载器.版本系统.契约兼容.检查契约兼容"})

    def test_平台控制面再导出与公共契约唯一实现是同一个对象(self) -> None:
        """兼容硬约束：公开导出名 `平台控制面.能力目录.契约指纹` 必须仍在，且**是同一个函数**。

        再导出不是第二套实现（函数对象同一性可机器验证）：改这里等于换实现，必须判红。
        """
        from 平台控制面.能力目录 import 契约指纹 as 能力目录再导出
        from 公共契约.能力契约 import 契约指纹 as 公共契约模块

        self.assertIs(能力目录再导出, 公共契约模块.契约指纹)
        self.assertIs(能力目录再导出, 判定模块.契约指纹)
        self.assertIs(能力目录再导出, 契约指纹)
        # 再调一次，值也必须逐字一致（同一对象 + 同一算法只有一种结果）
        契约 = {"能力id": "A.B", "名称": "B", "参数": [{"名称": "入参", "类型": "文本型"}],
              "返回": {"类型": "结果型"}, "错误码": ["参数不合法"], "副作用": "无",
              "资源类型": "无", "宿主": "无", "权限": ["*"]}
        self.assertEqual(能力目录再导出(契约), 契约指纹(契约))

    def test_规范化不引入第二套指纹算法(self) -> None:
        """规范化只做「剔除字段 + 交给同一个函数」，源码里不许出现自己算哈希的痕迹。"""
        import ast

        源码 = Path(判定模块.__file__).read_text(encoding="utf-8")
        树 = ast.parse(源码)
        导入模块表 = {
            别名.name.split(".")[0]
            for 节点 in ast.walk(树) if isinstance(节点, (ast.Import, ast.ImportFrom))
            for 别名 in (节点.names if isinstance(节点, ast.Import) else [ast.alias(name=节点.module or "")])
        }
        self.assertNotIn("hashlib", 导入模块表, "规范化层不许引入哈希实现（只能是同一函数＋规范化输入）")
        self.assertNotIn("hmac", 导入模块表)
        调用名表 = {节点.func.attr for 节点 in ast.walk(树)
                 if isinstance(节点, ast.Call) and isinstance(节点.func, ast.Attribute)}
        self.assertNotIn("sha256", 调用名表, "本模块不许自己算 sha256")
        读数 = 读取包契约(self.基线包)
        契约 = 读数.能力表[目标能力id]
        self.assertEqual(契约面指纹(契约), 契约指纹(规范化契约面(契约)))
        self.assertEqual(判定模块.契约面指纹.__module__, 判定模块.__name__)

    def test_输出里原始指纹与契约面指纹同时保留(self) -> None:
        结果 = 判定能力对外契约变更(真实包相对路径, 目标能力id)
        兼容 = 结果["兼容判定"]
        for 键 in ("基线指纹", "新增指纹", "基线契约面指纹", "新增契约面指纹",
                  "指纹变化能力", "契约面变化能力", "文档性变化能力"):
            self.assertIn(键, 兼容, 兼容)
        self.assertEqual(set(兼容["基线指纹"]), set(兼容["基线契约面指纹"]))
        self.assertEqual(set(兼容["新增指纹"]), set(兼容["新增契约面指纹"]))
        self.assertEqual(兼容["基线指纹"][目标能力id], "ab533d8eb95b4cce")          # 原始指纹（含说明）
        self.assertEqual(兼容["基线契约面指纹"][目标能力id], 契约面指纹(
            读取包契约(self.基线包).能力表[目标能力id]))
        self.assertNotEqual(兼容["基线契约面指纹"][目标能力id], 兼容["基线指纹"][目标能力id])
        self.assertEqual(兼容["指纹口径"]["剔除字段"], ["参数.说明", "返回.值结构"])
        self.assertIn("同一", 兼容["指纹口径"]["契约面指纹"])

    def test_归一化契约只含对外契约七维加能力id与对外名(self) -> None:
        读数 = 读取包契约(self.基线包)
        契约 = 读数.能力表[目标能力id]
        self.assertEqual(set(契约), {"能力id", "名称", "参数", "返回", "错误码",
                                    "副作用", "资源类型", "宿主", "权限"})
        self.assertEqual(契约["名称"], "调用提供者")
        self.assertEqual(契约["权限"], ["*"])          # 来自 权限契约/权限契约.json
        self.assertTrue(契约["副作用"])                 # 来自 能力条目 行为.副作用

    # ---- 失败路径 fail-closed ----

    def test_新包目录不存在(self) -> None:
        结果 = 判定对外契约变更(self.临时根 / "根本没有这个包")
        self.assertTrue(是失败结果(结果), 结果)
        self.assertEqual(结果["错误码"], "新包目录不存在")
        self.assertIsNone(结果["值"])
        self.assertEqual(set(结果), {"成功", "值", "错误码", "错误说明"})

    def test_基线包缺失时fail_closed(self) -> None:
        # 制品目录形态的基线里没有同名包（候选不存在）→ 必须报错，不得当无变化放行
        空制品目录 = self.临时根 / "空制品目录"
        空制品目录.mkdir(parents=True, exist_ok=True)
        结果 = 判定对外契约变更(真实包相对路径, 基线包目录=空制品目录)
        self.assertTrue(是失败结果(结果), 结果)
        self.assertEqual(结果["错误码"], "基线包缺失")
        self.assertIn("fail-closed", 结果["错误说明"])

    def test_基线包目录不是包时fail_closed(self) -> None:
        副本 = self.造副本("基线非包")
        结果 = 判定对外契约变更(副本, 基线包目录=self.临时根 / "不存在的基线")
        self.assertTrue(是失败结果(结果), 结果)
        self.assertEqual(结果["错误码"], "基线包缺失")
        self.assertIn("基线包目录", 结果["错误说明"])

    def test_两端都读不到契约时fail_closed(self) -> None:
        空包 = self.临时根 / "空包"
        空包.mkdir(parents=True, exist_ok=True)
        结果 = 判定对外契约变更(空包, 基线包目录=空包)
        self.assertTrue(是失败结果(结果), 结果)
        self.assertEqual(结果["错误码"], "契约文件缺失")
        self.assertIn("fail-closed", 结果["错误说明"])

    def test_激活制品指针缺失时fail_closed(self) -> None:
        空仓库 = self.临时根 / "空仓库"
        空仓库.mkdir(parents=True, exist_ok=True)
        结果 = 判定对外契约变更(真实包相对路径, 制品仓库根=空仓库)
        self.assertTrue(是失败结果(结果), 结果)
        self.assertEqual(结果["错误码"], "基线制品指针缺失")

    def test_包目录不在项目根内且未给基线包目录时fail_closed(self) -> None:
        副本 = self.造副本("越界")
        结果 = 判定对外契约变更(副本)
        self.assertTrue(是失败结果(结果), 结果)
        self.assertEqual(结果["错误码"], "基线包缺失")
        self.assertIn("基线包目录", 结果["错误说明"])

    def test_契约结构性非法时fail_closed(self) -> None:
        副本 = self.造副本("坏结构")
        (副本 / "能力定义.json").write_text('{"能力列表": {"不是": "列表"}}', encoding="utf-8")
        结果 = self.判定副本(副本)
        self.assertTrue(是失败结果(结果), 结果)
        self.assertEqual(结果["错误码"], "契约结构非法")

    def test_能力id为空判参数不合法(self) -> None:
        结果 = 判定对外契约变更(真实包相对路径, 能力id="   ")
        self.assertTrue(是失败结果(结果), 结果)
        self.assertEqual(结果["错误码"], "参数不合法")

    # ---- 信封包装 ----

    def test_判定并包装成功包成信封(self) -> None:
        信封 = 判定并包装(判定对外契约变更(真实包相对路径))
        self.assertIs(信封["成功"], 真)
        self.assertEqual(信封["错误码"], "")
        self.assertEqual(set(信封["值"]), 固定结构键)

    def test_判定并包装失败原样返回(self) -> None:
        原始 = 判定对外契约变更(self.临时根 / "没有这个包")
        信封 = 判定并包装(原始)
        self.assertEqual(信封, 原始)
        self.assertIs(信封["成功"], 假)

    # ---- 验收：不可对既有文件产生写入 ----

    def test_判定过程不写仓库文件(self) -> None:
        定义文件 = self.真实包 / "能力定义.json"
        契约文件 = self.真实包 / "能力契约/参数契约.json"
        前 = (定义文件.stat().st_mtime_ns, 契约文件.stat().st_mtime_ns,
              定义文件.read_bytes(), 契约文件.read_bytes())
        判定对外契约变更(真实包相对路径)
        判定能力对外契约变更(真实包相对路径, 目标能力id)
        后 = (定义文件.stat().st_mtime_ns, 契约文件.stat().st_mtime_ns,
              定义文件.read_bytes(), 契约文件.read_bytes())
        self.assertEqual(前, 后)


if __name__ == "__main__":
    unittest.main(verbosity=2)
