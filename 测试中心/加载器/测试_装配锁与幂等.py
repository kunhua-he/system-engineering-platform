"""C1 包发现与确定性装配：包声明发现、装配锁校验与幂等测试。

覆盖：包发现只来自正式 包声明.json；缺失依赖/循环依赖/多提供者冲突
失败；重复装配严格幂等；版本漂移/提供者漂移冲突失败；装配失败无半
装配残留（注册表恢复）；装配顺序严格按拓扑（提供者在先）。
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

系统根 = Path(__file__).resolve().parents[2]
if str(系统根) not in sys.path:
    sys.path.insert(0, str(系统根))

from 公共契约.能力契约.契约 import 能力注册表, 能力实现
from 运行核心.加载器.包发现.发现器 import 发现全部
from 运行核心.加载器.依赖解析.装配锁 import 构建装配锁
from 运行核心.加载器.生命周期管理.管理器 import 装配系统, 恢复注册表


def 写临时包(
    临时根: Path,
    包目录名: str,
    声明: dict,
    入口源码: str | None = None,
) -> Path:
    """写一份临时包：包声明.json + 入口.py（入口默认注册声明能力）。"""
    包目录 = 临时根 / 包目录名
    包目录.mkdir(parents=True, exist_ok=True)
    (包目录 / "包声明.json").write_text(
        json.dumps(声明, ensure_ascii=False, indent=2), encoding="utf-8")
    if 入口源码 is None:
        能力id = 声明["能力"][0]["能力id"] if 声明.get("能力") else "无.能力"
        入口源码 = (
            "from 公共契约.能力契约.契约 import 能力实现\n"
            "def 注册能力(注册表):\n"
            f"    注册表.注册(能力实现(\n"
            f"        能力id={能力id!r}, 包id={声明['包id']!r},\n"
            f"        实现函数=lambda: {声明['包id']!r}))\n"
        )
    (包目录 / "入口.py").write_text(入口源码, encoding="utf-8")
    return 包目录


class Test包发现来自正式声明(unittest.TestCase):
    """包发现必须从正式包声明（包声明.json）发现，不靠目录名或硬编码。"""

    def setUp(self):
        self.临时 = Path(tempfile.mkdtemp(prefix="C1_发现_"))
        (self.临时 / "支持库").mkdir()
        (self.临时 / "模块库").mkdir()

    def tearDown(self):
        shutil.rmtree(self.临时, ignore_errors=True)

    def test_只发现含包声明的包(self):
        写临时包(self.临时 / "支持库", "甲", {
            "包id": "发现.甲", "名称": "甲", "类型": "支持库", "版本": "1.0.0",
            "入口": "入口.py", "能力": [{"能力id": "发现.甲能力"}],
        })
        # 只有入口文件、没有 包声明.json 的目录不得被当作包发现
        (self.临时 / "支持库" / "乙").mkdir()
        (self.临时 / "支持库" / "乙" / "入口.py").write_text(
            "def 注册能力(注册表):\n    pass\n", encoding="utf-8")
        发现 = 发现全部(self.临时 / "支持库", self.临时 / "模块库")
        self.assertTrue(发现.成功, str(发现.问题列表))
        self.assertEqual([声明.包id for 声明 in 发现.声明列表], ["发现.甲"])

    def test_装配只注册声明包的能力(self):
        写临时包(self.临时 / "支持库", "甲", {
            "包id": "装配.甲", "名称": "甲", "类型": "支持库", "版本": "1.0.0",
            "入口": "入口.py", "能力": [{"能力id": "装配.甲能力"}],
        })
        结果 = 装配系统(self.临时 / "支持库", self.临时 / "模块库")
        self.assertTrue(结果.成功, str(结果.问题列表))
        self.assertEqual(结果.声明能力数, 1)
        self.assertEqual(结果.已注册能力数, 1)


class Test装配前锁校验失败(unittest.TestCase):
    """缺失依赖/循环依赖/多提供者冲突/既有注册表能力锁冲突必须失败且零残留。"""

    def setUp(self):
        self.临时 = Path(tempfile.mkdtemp(prefix="C1_失败_"))
        (self.临时 / "支持库").mkdir()
        (self.临时 / "模块库").mkdir()

    def tearDown(self):
        shutil.rmtree(self.临时, ignore_errors=True)

    def test_缺失依赖失败且注册表无残留(self):
        注册表 = 能力注册表()
        写临时包(self.临时 / "模块库", "坏模块", {
            "包id": "失败.坏模块", "名称": "坏模块", "类型": "基础模块", "版本": "1.0.0",
            "入口": "入口.py", "能力": [], "依赖": [{"能力": "不存在.能力"}],
        })
        结果 = 装配系统(self.临时 / "支持库", self.临时 / "模块库", 注册表)
        self.assertFalse(结果.成功)
        self.assertTrue(
            any("无提供者" in 问题 or "缺失" in 问题 for 问题 in 结果.问题列表),
            str(结果.问题列表),
        )
        self.assertEqual(注册表.能力id列表, [], "缺失依赖失败不得留下半装配能力")

    def test_循环依赖失败且注册表无残留(self):
        注册表 = 能力注册表()
        写临时包(self.临时 / "模块库", "甲", {
            "包id": "循环.甲", "名称": "甲", "类型": "基础模块", "版本": "1.0.0",
            "入口": "入口.py", "能力": [{"能力id": "循环.甲能力"}],
            "依赖": [{"能力": "循环.乙能力"}],
        })
        写临时包(self.临时 / "模块库", "乙", {
            "包id": "循环.乙", "名称": "乙", "类型": "基础模块", "版本": "1.0.0",
            "入口": "入口.py", "能力": [{"能力id": "循环.乙能力"}],
            "依赖": [{"能力": "循环.甲能力"}],
        })
        结果 = 装配系统(self.临时 / "支持库", self.临时 / "模块库", 注册表)
        self.assertFalse(结果.成功)
        self.assertTrue(any("依赖循环" in 问题 for 问题 in 结果.问题列表), str(结果.问题列表))
        self.assertEqual(注册表.能力id列表, [], "循环依赖失败不得留下半装配能力")

    def test_多提供者冲突失败且注册表无残留(self):
        注册表 = 能力注册表()
        声明甲 = {"包id": "冲突.甲", "名称": "甲", "类型": "支持库", "版本": "1.0.0",
                  "入口": "入口.py", "能力": [{"能力id": "撞.能力"}]}
        声明乙 = {"包id": "冲突.乙", "名称": "乙", "类型": "支持库", "版本": "1.0.0",
                  "入口": "入口.py", "能力": [{"能力id": "撞.能力"}]}
        写临时包(self.临时 / "支持库", "甲", 声明甲)
        写临时包(self.临时 / "支持库", "乙", 声明乙)
        结果 = 装配系统(self.临时 / "支持库", self.临时 / "模块库", 注册表)
        self.assertFalse(结果.成功)
        self.assertTrue(
            any("多提供者冲突" in 问题 or "能力 id 重复" in 问题 for 问题 in 结果.问题列表),
            str(结果.问题列表),
        )
        self.assertEqual(注册表.能力id列表, [], "多提供者冲突失败不得留下半装配能力")

    def test_既有注册表提供者不一致装配前失败(self):
        """能力锁校验：注册表已由其他包注册的能力，与声明提供方不一致必须装配前失败。"""
        注册表 = 能力注册表()
        注册表.注册(能力实现(能力id="撞.能力", 包id="旧包", 实现函数=lambda: "旧"))
        写临时包(self.临时 / "支持库", "甲", {
            "包id": "锁冲突.甲", "名称": "甲", "类型": "支持库", "版本": "1.0.0",
            "入口": "入口.py", "能力": [{"能力id": "撞.能力"}],
        })
        结果 = 装配系统(self.临时 / "支持库", self.临时 / "模块库", 注册表)
        self.assertFalse(结果.成功)
        self.assertTrue(any("能力锁冲突" in 问题 for 问题 in 结果.问题列表), str(结果.问题列表))
        self.assertEqual(注册表.能力id列表, ["撞.能力"])
        self.assertEqual(注册表.获取("撞.能力").包id, "旧包", "既有注册能力不得被覆盖")


class Test重复装配幂等与漂移(unittest.TestCase):
    """同一注册表重复装配严格幂等；版本漂移必须冲突失败。"""

    def setUp(self):
        self.临时 = Path(tempfile.mkdtemp(prefix="C1_幂等_"))
        (self.临时 / "支持库").mkdir()
        (self.临时 / "模块库").mkdir()
        声明甲 = {"包id": "幂等.甲", "名称": "甲", "类型": "支持库", "版本": "1.0.0",
                  "入口": "入口.py", "能力": [{"能力id": "幂等.甲能力"}]}
        声明乙 = {"包id": "幂等.乙", "名称": "乙", "类型": "基础模块", "版本": "1.0.0",
                  "入口": "入口.py", "能力": [{"能力id": "幂等.乙能力"}],
                  "依赖": [{"能力": "幂等.甲能力"}]}
        写临时包(self.临时 / "支持库", "甲", 声明甲)
        写临时包(self.临时 / "模块库", "乙", 声明乙)
        self.注册表 = 能力注册表()

    def tearDown(self):
        shutil.rmtree(self.临时, ignore_errors=True)

    def test_同一注册表重复装配严格幂等(self):
        结果一 = 装配系统(self.临时 / "支持库", self.临时 / "模块库", self.注册表)
        self.assertTrue(结果一.成功, str(结果一.问题列表))
        结果二 = 装配系统(self.临时 / "支持库", self.临时 / "模块库", self.注册表)
        self.assertTrue(结果二.成功, str(结果二.问题列表))
        self.assertEqual(结果一.顺序列表, 结果二.顺序列表)
        self.assertEqual(结果一.已注册能力数, 结果二.已注册能力数)
        # 能力id列表按 id 排序：乙 排在 甲 前
        self.assertEqual(self.注册表.能力id列表, ["幂等.乙能力", "幂等.甲能力"])
        self.assertEqual(
            self.注册表.获取("幂等.甲能力").包id, "幂等.甲")

    def test_全新注册表装配结果一致(self):
        结果一 = 装配系统(self.临时 / "支持库", self.临时 / "模块库")
        结果二 = 装配系统(self.临时 / "支持库", self.临时 / "模块库")
        self.assertTrue(结果一.成功 and 结果二.成功)
        self.assertEqual(结果一.顺序列表, 结果二.顺序列表)
        self.assertEqual(结果一.已注册能力数, 结果二.已注册能力数)

    def test_版本漂移冲突失败且注册表保持旧版本(self):
        结果一 = 装配系统(self.临时 / "支持库", self.临时 / "模块库", self.注册表)
        self.assertTrue(结果一.成功, str(结果一.问题列表))
        声明路径 = self.临时 / "支持库" / "甲" / "包声明.json"
        数据 = json.loads(声明路径.read_text(encoding="utf-8"))
        数据["版本"] = "1.1.0"
        声明路径.write_text(json.dumps(数据, ensure_ascii=False, indent=2), encoding="utf-8")
        结果二 = 装配系统(self.临时 / "支持库", self.临时 / "模块库", self.注册表)
        self.assertFalse(结果二.成功)
        self.assertTrue(any("装配锁漂移" in 问题 and "版本漂移" in 问题 for 问题 in 结果二.问题列表),
                        str(结果二.问题列表))
        self.assertEqual(self.注册表.能力id列表, ["幂等.乙能力", "幂等.甲能力"],
                         "漂移冲突失败后注册表必须保持已装配版本，不得半覆盖")

    def test_提供者漂移冲突失败(self):
        结果一 = 装配系统(self.临时 / "支持库", self.临时 / "模块库", self.注册表)
        self.assertTrue(结果一.成功, str(结果一.问题列表))
        # 同一能力改由另一个包提供：改声明包id后重新装配，提供者锁漂移必须冲突失败
        声明路径 = self.临时 / "支持库" / "甲" / "包声明.json"
        数据 = json.loads(声明路径.read_text(encoding="utf-8"))
        数据["包id"] = "幂等.丙"
        声明路径.write_text(json.dumps(数据, ensure_ascii=False, indent=2), encoding="utf-8")
        结果二 = 装配系统(self.临时 / "支持库", self.临时 / "模块库", self.注册表)
        self.assertFalse(结果二.成功)
        self.assertTrue(any("装配锁漂移" in 问题 and "提供者漂移" in 问题 for 问题 in 结果二.问题列表),
                        str(结果二.问题列表))


class Test装配顺序与失败回滚(unittest.TestCase):
    """装配顺序严格按拓扑（提供者在先）；装配失败恢复注册表不留半装配。"""

    def setUp(self):
        self.临时 = Path(tempfile.mkdtemp(prefix="C1_回滚_"))
        (self.临时 / "支持库").mkdir()
        (self.临时 / "模块库").mkdir()

    def tearDown(self):
        shutil.rmtree(self.临时, ignore_errors=True)

    def test_支持库间依赖按拓扑顺序装配(self):
        """乙 依赖 甲.能力 且注册时校验依赖已在注册表；字母序乙在前也必须先装甲。"""
        写临时包(self.临时 / "支持库", "甲", {
            "包id": "顺序.甲", "名称": "甲", "类型": "支持库", "版本": "1.0.0",
            "入口": "入口.py", "能力": [{"能力id": "顺序.甲能力"}],
        })
        乙入口 = (
            "from 公共契约.能力契约.契约 import 能力实现\n"
            "def 注册能力(注册表):\n"
            "    if 注册表.获取('顺序.甲能力') is None:\n"
            "        raise RuntimeError('依赖 顺序.甲能力 未装配')\n"
            "    注册表.注册(能力实现(\n"
            "        能力id='顺序.乙能力', 包id='顺序.乙',\n"
            "        实现函数=lambda: '顺序.乙'))\n"
        )
        写临时包(self.临时 / "支持库", "乙", {
            "包id": "顺序.乙", "名称": "乙", "类型": "支持库", "版本": "1.0.0",
            "入口": "入口.py", "能力": [{"能力id": "顺序.乙能力"}],
            "依赖": [{"能力": "顺序.甲能力"}],
        }, 乙入口)
        结果 = 装配系统(self.临时 / "支持库", self.临时 / "模块库")
        self.assertTrue(结果.成功, str(结果.问题列表))
        self.assertEqual(结果.顺序列表, ["顺序.甲", "顺序.乙"], "装配顺序必须提供者在先")

    def test_装配失败恢复注册表无半装配残留(self):
        """甲先注册成功、乙安装失败：注册表必须恢复，既有能力保留。"""
        注册表 = 能力注册表()
        注册表.注册(能力实现(能力id="既有.能力", 包id="既有包", 实现函数=lambda: "旧"))
        写临时包(self.临时 / "支持库", "甲", {
            "包id": "回滚.甲", "名称": "甲", "类型": "支持库", "版本": "1.0.0",
            "入口": "入口.py", "能力": [{"能力id": "回滚.甲能力"}],
        })
        写临时包(self.临时 / "支持库", "乙", {
            "包id": "回滚.乙", "名称": "乙", "类型": "支持库", "版本": "1.0.0",
            "入口": "不存在的入口.py", "能力": [{"能力id": "回滚.乙能力"}],
            "依赖": [{"能力": "回滚.甲能力"}],
        })
        结果 = 装配系统(self.临时 / "支持库", self.临时 / "模块库", 注册表)
        self.assertFalse(结果.成功)
        self.assertTrue(any("装配失败" in 问题 for 问题 in 结果.问题列表), str(结果.问题列表))
        回滚记录 = [记录 for 记录 in 结果.生命周期记录 if 记录.操作名称 == "回滚"]
        self.assertTrue(回滚记录, "装配失败后应产生回滚记录")
        self.assertEqual(注册表.能力id列表, ["既有.能力"], "失败后注册表必须恢复，不得残留半装配能力")
        self.assertEqual(注册表.获取("既有.能力").包id, "既有包")
        self.assertIsNone(注册表.获取("回滚.甲能力"))


class Test装配锁单元(unittest.TestCase):
    """装配锁构建与差异检测。"""

    def test_构建装配锁与读取状态(self):
        from 公共契约.包声明.声明 import 从字典构建
        from 运行核心.加载器.提供者选择.选择器 import 选择全部提供者
        声明甲 = 从字典构建({"包id": "锁.甲", "名称": "甲", "类型": "支持库", "版本": "1.0.0",
                            "能力": [{"能力id": "锁.甲能力"}]})
        提供者表 = 选择全部提供者([声明甲])
        锁 = 构建装配锁([声明甲], 提供者表, ["锁.甲"])
        self.assertEqual(锁.版本锁, {"锁.甲": "1.0.0"})
        self.assertEqual(锁.能力锁, {"锁.甲能力": "锁.甲"})
        self.assertEqual(锁.提供者锁, {"锁.甲能力": "1.0.0"})
        self.assertEqual(锁.顺序列表, ("锁.甲",))
        self.assertEqual(锁.差异说明(构建装配锁([声明甲], 提供者表, ["锁.甲"])), [])

    def test_差异说明检出漂移(self):
        from 运行核心.加载器.依赖解析.装配锁 import 装配锁
        旧锁 = 装配锁(
            顺序列表=("甲", "乙"),
            版本锁={"甲": "1.0.0", "乙": "1.0.0"},
            能力锁={"甲.能力": "甲", "乙.能力": "乙"},
            提供者锁={"甲.能力": "1.0.0", "乙.能力": "1.0.0"},
        )
        新锁 = 装配锁(
            顺序列表=("乙", "甲"),
            版本锁={"甲": "1.1.0", "乙": "1.0.0"},
            能力锁={"甲.能力": "乙", "乙.能力": "乙"},
            提供者锁={"甲.能力": "1.0.0", "乙.能力": "1.0.0"},
        )
        差异 = 旧锁.差异说明(新锁)
        合并 = "；".join(差异)
        self.assertIn("版本漂移", 合并)
        self.assertIn("提供者漂移", 合并)
        self.assertIn("装配顺序漂移", 合并)

    def test_恢复注册表快照(self):
        注册表 = 能力注册表()
        旧实现 = 能力实现(能力id="旧.能力", 包id="旧包", 实现函数=lambda: "旧")
        注册表.注册(旧实现)
        快照 = {"旧.能力": 旧实现}
        注册表.注册(能力实现(能力id="新.能力", 包id="新包", 实现函数=lambda: "新"))
        恢复注册表(注册表, 快照)
        self.assertEqual(注册表.能力id列表, ["旧.能力"])


if __name__ == "__main__":
    unittest.main()
