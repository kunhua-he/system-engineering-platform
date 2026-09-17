"""定向测试：对外契约变更判定（版本递增判据＝对外契约指纹变化——哲学 5.3 / 决策记录 0020）。

三档**真实包**对照（包 `平台控制面/提供者/注册表`，基线＝当前激活制品内同名包，非夹具）：
① 契约未变 → `内部优化` / 不要求版本递增；
② `/tmp` 副本改一个参数类型 → `契约变化` / 要求递增；
③ 同一副本版本号递增 → 放行（不要求递增）；
反向验证：② 的改动还原 → 回到 ①；版本号改回旧值 → 重新判「要求递增」。

另覆盖：能力级判定、新增/删除能力算契约变化、说明变化属内部优化、失败路径 fail-closed、
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

from 开发工具.契约编译 import 对外契约变更判定 as 判定模块
from 开发工具.契约编译.对外契约变更判定 import (
    判定对外契约变更,
    判定能力对外契约变更,
    判定并包装,
    是失败结果,
    读取包契约,
    契约指纹,
    检查契约兼容,
)

真实包相对路径 = "平台控制面/提供者/注册表"
目标能力id = "平台控制面.提供者.注册表.调用提供者"
参数旧类型 = "双精度数型"
参数新类型 = "双精度数形"
固定结构键 = {"变更类别", "变化明细", "是否要求版本递增", "兼容判定", "基线来源"}


def 读制品目录() -> Path:
    """独立按 当前.json → 制品目录 解析（不复用被测模块的私有实现）。"""
    仓库根 = 项目根 / "工程缓存/制品仓库/平台客户端制品"
    指针 = json.loads((仓库根 / "当前.json").read_text(encoding="utf-8"))
    return 仓库根 / 指针["路径"]


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
        self.assertIs(结果["是否要求版本递增"], False)
        self.assertIs(结果["兼容判定"]["指纹是否变化"], False)
        self.assertEqual(结果["兼容判定"]["结论"], "兼容")
        self.assertEqual(结果["兼容判定"]["对比能力数"], 4)
        # 基线来源必须点名激活制品与包路径（不新建存储）
        self.assertIn(self.制品目录.name, 结果["基线来源"])
        self.assertIn(真实包相对路径, 结果["基线来源"])

    def test_一档_第二个真实包也判内部优化(self) -> None:
        结果 = 判定对外契约变更("支持库/适配层/MCP协议提供者")
        self.assertEqual(结果["变更类别"], "内部优化")
        self.assertIs(结果["是否要求版本递增"], False)

    # ---- ② 改参数类型一个字 ----

    def test_二档_改参数类型一个字判契约变化并要求递增(self) -> None:
        副本 = self.造副本("二档")
        self.改副本定义(副本, [(参数旧类型, 参数新类型)])
        结果 = self.判定副本(副本)
        self.assertEqual(结果["变更类别"], "契约变化")
        self.assertIs(结果["是否要求版本递增"], True)
        self.assertIs(结果["兼容判定"]["指纹是否变化"], True)
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
        self.assertIs(结果["是否要求版本递增"], False)     # 但已由版本递增承载 → 放行
        self.assertEqual(结果["兼容判定"]["版本"],
                         {"基线版本": "1.0.0", "新增版本": "1.1.0",
                          "版本判定": "版本已递增", "是否递增": True})
        self.assertTrue(any("版本已递增合法" in 行 for 行 in 结果["变化明细"]), 结果["变化明细"])

    def test_三档_版本回退仍要求递增(self) -> None:
        副本 = self.造副本("三档回退")
        self.改副本定义(副本, [(参数旧类型, 参数新类型),
                              ('"版本": "1.0.0"', '"版本": "0.9.0"')])
        结果 = self.判定副本(副本)
        self.assertEqual(结果["变更类别"], "契约变化")
        self.assertIs(结果["是否要求版本递增"], True)
        self.assertEqual(结果["兼容判定"]["版本"]["版本判定"], "版本回退")

    # ---- 反向验证 ----

    def test_反向_还原参数类型改动必须回到内部优化(self) -> None:
        副本 = self.造副本("反向还原")
        原文 = (副本 / "能力定义.json").read_text(encoding="utf-8")
        self.改副本定义(副本, [(参数旧类型, 参数新类型)])
        改后 = self.判定副本(副本)
        self.assertEqual(改后["变更类别"], "契约变化")
        self.assertIs(改后["是否要求版本递增"], True)
        # 还原改动 → 判定必须回到 ①
        (副本 / "能力定义.json").write_text(原文, encoding="utf-8")
        还原后 = self.判定副本(副本)
        self.assertEqual(还原后["变更类别"], "内部优化")
        self.assertIs(还原后["是否要求版本递增"], False)
        self.assertEqual(还原后["兼容判定"]["基线指纹"], 改后["兼容判定"]["基线指纹"])
        self.assertEqual(还原后["兼容判定"]["新增指纹"], 还原后["兼容判定"]["基线指纹"])

    def test_反向_版本号改回旧值必须重新要求递增(self) -> None:
        副本 = self.造副本("反向版本")
        self.改副本定义(副本, [(参数旧类型, 参数新类型), ('"版本": "1.0.0"', '"版本": "1.1.0"')])
        self.assertIs(self.判定副本(副本)["是否要求版本递增"], False)
        self.改副本定义(副本, [('"版本": "1.1.0"', '"版本": "1.0.0"')])
        回退后 = self.判定副本(副本)
        self.assertEqual(回退后["变更类别"], "契约变化")
        self.assertIs(回退后["是否要求版本递增"], True)
        self.assertEqual(回退后["兼容判定"]["版本"]["版本判定"], "版本未递增")

    # ---- 能力级 ----

    def test_能力级_单能力契约未变判内部优化(self) -> None:
        结果 = 判定能力对外契约变更(真实包相对路径, 目标能力id)
        self.assertEqual(结果["变更类别"], "内部优化")
        self.assertIs(结果["是否要求版本递增"], False)
        self.assertEqual(结果["兼容判定"]["对比能力数"], 1)
        self.assertEqual(list(结果["兼容判定"]["基线指纹"]), [目标能力id])
        self.assertEqual(结果["兼容判定"]["基线指纹"][目标能力id], "ab533d8eb95b4cce")

    def test_能力级_改该能力参数判契约变化(self) -> None:
        副本 = self.造副本("能力级")
        self.改副本定义(副本, [(参数旧类型, 参数新类型)])
        结果 = self.判定副本(副本, 能力id=目标能力id)
        self.assertEqual(结果["变更类别"], "契约变化")
        self.assertIs(结果["是否要求版本递增"], True)
        self.assertEqual(结果["兼容判定"]["指纹变化能力"], [目标能力id])

    def test_能力级_改别包能力不影响本能力(self) -> None:
        副本 = self.造副本("能力级旁观")
        数据 = json.loads((副本 / "能力定义.json").read_text(encoding="utf-8"))
        被改 = "平台控制面.提供者.注册表.登记提供者"
        for 能力 in 数据["能力列表"]:
            if 能力["能力id"] == 被改:
                能力["参数"][0]["类型"] = "文本型甲"
        (副本 / "能力定义.json").write_text(json.dumps(数据, ensure_ascii=False, indent=1),
                                      encoding="utf-8")
        # 包级一定判契约变化（改了 登记提供者），能力级只看被问的那个能力
        self.assertEqual(self.判定副本(副本)["变更类别"], "契约变化")
        结果 = self.判定副本(副本, 能力id="平台控制面.提供者.注册表.查询提供者")
        self.assertEqual(结果["变更类别"], "内部优化")
        self.assertIs(结果["是否要求版本递增"], False)

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
        self.assertIs(结果["是否要求版本递增"], True)
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
        self.assertIs(结果["是否要求版本递增"], True)
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
        self.assertIs(结果["是否要求版本递增"], False)
        self.assertIs(结果["兼容判定"]["指纹是否变化"], False)

    def test_参数说明变化随指纹判契约变化(self) -> None:
        # 唯一口径是 契约指纹()：参数对象整体入指纹，故参数说明变化也判契约变化（不得人工放宽）
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
        self.assertEqual(结果["变更类别"], "契约变化")
        self.assertIs(结果["是否要求版本递增"], True)
        self.assertTrue(any("参数说明变化" in 行 for 行 in 结果["变化明细"]), 结果["变化明细"])

    # ---- 输出结构 / 判据来源 ----

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
        self.assertEqual(契约指纹.__module__, "平台控制面.能力目录.服务")
        self.assertEqual(检查契约兼容.__module__, "运行核心.加载器.版本系统.契约兼容")
        self.assertEqual(判定模块.判据来源,
                         {"指纹": "平台控制面.能力目录.服务.契约指纹",
                          "兼容": "运行核心.加载器.版本系统.契约兼容.检查契约兼容"})

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
        self.assertIs(信封["成功"], True)
        self.assertEqual(信封["错误码"], "")
        self.assertEqual(set(信封["值"]), 固定结构键)

    def test_判定并包装失败原样返回(self) -> None:
        原始 = 判定对外契约变更(self.临时根 / "没有这个包")
        信封 = 判定并包装(原始)
        self.assertEqual(信封, 原始)
        self.assertIs(信封["成功"], False)

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
