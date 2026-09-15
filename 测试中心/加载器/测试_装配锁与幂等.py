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
    # 生产结构对称：正式包必须含聚合契约；适配层提供者必须含依赖锁（含环境指纹）
    契约 = {
        "契约版本": "1.0.0",
        "能力契约": [{
            "能力id": 声明["能力"][0]["能力id"] if 声明.get("能力") else "无.能力",
            "版本": 声明.get("版本", "1.0.0"), "说明": 声明.get("名称", "临时包"),
            "参数": [], "返回": {"类型": "dict", "说明": "统一结果"},
            "错误码": [], "调用示例": "{}",
        }],
    }
    (包目录 / "能力契约").mkdir(parents=True, exist_ok=True)
    (包目录 / "能力契约" / "参数契约.json").write_text(
        json.dumps(契约, ensure_ascii=False), encoding="utf-8")
    if "适配层" in str(声明.get("包id", "")):
        from 运行核心.环境指纹 import 计算环境指纹
        指纹 = 计算环境指纹(含外部应用=False).详细信息
        系统名 = "macOS" if 指纹["os"] == "Darwin" else 指纹["os"]
        (包目录 / "依赖锁.json").write_text(json.dumps({
            "包": [{"名称": "临时测试工具", "版本": "1.0.0",
                    "模块名": "临时测试工具", "来源": "外部应用"}],
            "提供者id": 声明.get("名称", "临时包"), "直接依赖": [], "依赖闭包": [],
            "环境": {"Python": 指纹["python"], "操作系统": 系统名, "CPU": 指纹["架构"]},
        }, ensure_ascii=False), encoding="utf-8")
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
        写临时包(self.临时 / "支持库", "模块1", {
            "包id": "发现.模块1", "名称": "模块1", "类型": "支持库", "版本": "1.0.0",
            "入口": "入口.py", "能力": [{"能力id": "发现.模块1能力"}],
        })
        # 只有入口文件、没有 包声明.json 的目录不得被当作包发现
        (self.临时 / "支持库" / "模块2").mkdir()
        (self.临时 / "支持库" / "模块2" / "入口.py").write_text(
            "def 注册能力(注册表):\n    pass\n", encoding="utf-8")
        发现 = 发现全部(self.临时 / "支持库", self.临时 / "模块库")
        self.assertTrue(发现.成功, str(发现.问题列表))
        self.assertEqual([声明.包id for 声明 in 发现.声明列表], ["发现.模块1"])

    def test_装配只注册声明包的能力(self):
        写临时包(self.临时 / "支持库", "模块1", {
            "包id": "装配.模块1", "名称": "模块1", "类型": "支持库", "版本": "1.0.0",
            "入口": "入口.py", "能力": [{"能力id": "装配.模块1能力"}],
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
        写临时包(self.临时 / "模块库", "模块1", {
            "包id": "循环.模块1", "名称": "模块1", "类型": "基础模块", "版本": "1.0.0",
            "入口": "入口.py", "能力": [{"能力id": "循环.模块1能力"}],
            "依赖": [{"能力": "循环.模块2能力"}],
        })
        写临时包(self.临时 / "模块库", "模块2", {
            "包id": "循环.模块2", "名称": "模块2", "类型": "基础模块", "版本": "1.0.0",
            "入口": "入口.py", "能力": [{"能力id": "循环.模块2能力"}],
            "依赖": [{"能力": "循环.模块1能力"}],
        })
        结果 = 装配系统(self.临时 / "支持库", self.临时 / "模块库", 注册表)
        self.assertFalse(结果.成功)
        self.assertTrue(any("依赖循环" in 问题 for 问题 in 结果.问题列表), str(结果.问题列表))
        self.assertEqual(注册表.能力id列表, [], "循环依赖失败不得留下半装配能力")

    def test_多提供者冲突失败且注册表无残留(self):
        注册表 = 能力注册表()
        声明1 = {"包id": "冲突.模块1", "名称": "模块1", "类型": "支持库", "版本": "1.0.0",
                  "入口": "入口.py", "能力": [{"能力id": "撞.能力"}]}
        声明2 = {"包id": "冲突.模块2", "名称": "模块2", "类型": "支持库", "版本": "1.0.0",
                  "入口": "入口.py", "能力": [{"能力id": "撞.能力"}]}
        写临时包(self.临时 / "支持库", "模块1", 声明1)
        写临时包(self.临时 / "支持库", "模块2", 声明2)
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
        写临时包(self.临时 / "支持库", "模块1", {
            "包id": "锁冲突.模块1", "名称": "模块1", "类型": "支持库", "版本": "1.0.0",
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
        声明1 = {"包id": "幂等.模块1", "名称": "模块1", "类型": "支持库", "版本": "1.0.0",
                  "入口": "入口.py", "能力": [{"能力id": "幂等.模块1能力"}]}
        声明2 = {"包id": "幂等.模块2", "名称": "模块2", "类型": "基础模块", "版本": "1.0.0",
                  "入口": "入口.py", "能力": [{"能力id": "幂等.模块2能力"}],
                  "依赖": [{"能力": "幂等.模块1能力"}]}
        写临时包(self.临时 / "支持库", "模块1", 声明1)
        写临时包(self.临时 / "模块库", "模块2", 声明2)
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
        # 能力id列表按 id 排序（`契约.能力id列表` 实现为 sorted(_实现表)）：
        # '1'(U+0031) < '2'(U+0032)，故 模块1 在 模块2 前。
        # 2026-09-15 修正：原断言写成 ["幂等.模块2能力", "幂等.模块1能力"]，与其自身注释
        # "按 id 排序"矛盾，属历史遗留写反（改动前后均失败，与本轮无关）。
        self.assertEqual(self.注册表.能力id列表, ["幂等.模块1能力", "幂等.模块2能力"])
        self.assertEqual(
            self.注册表.获取("幂等.模块1能力").包id, "幂等.模块1")

    def test_全新注册表装配结果一致(self):
        结果一 = 装配系统(self.临时 / "支持库", self.临时 / "模块库")
        结果二 = 装配系统(self.临时 / "支持库", self.临时 / "模块库")
        self.assertTrue(结果一.成功 and 结果二.成功)
        self.assertEqual(结果一.顺序列表, 结果二.顺序列表)
        self.assertEqual(结果一.已注册能力数, 结果二.已注册能力数)

    def test_版本漂移冲突失败且注册表保持旧版本(self):
        结果一 = 装配系统(self.临时 / "支持库", self.临时 / "模块库", self.注册表)
        self.assertTrue(结果一.成功, str(结果一.问题列表))
        声明路径 = self.临时 / "支持库" / "模块1" / "包声明.json"
        数据 = json.loads(声明路径.read_text(encoding="utf-8"))
        数据["版本"] = "1.1.0"
        声明路径.write_text(json.dumps(数据, ensure_ascii=False, indent=2), encoding="utf-8")
        结果二 = 装配系统(self.临时 / "支持库", self.临时 / "模块库", self.注册表)
        self.assertFalse(结果二.成功)
        self.assertTrue(any("装配锁漂移" in 问题 and "版本漂移" in 问题 for 问题 in 结果二.问题列表),
                        str(结果二.问题列表))
        self.assertEqual(self.注册表.能力id列表, ["幂等.模块1能力", "幂等.模块2能力"],
                         "漂移冲突失败后注册表必须保持已装配版本，不得半覆盖")

    def test_提供者漂移冲突失败(self):
        结果一 = 装配系统(self.临时 / "支持库", self.临时 / "模块库", self.注册表)
        self.assertTrue(结果一.成功, str(结果一.问题列表))
        # 同一能力改由另一个包提供：改声明包id后重新装配，提供者锁漂移必须冲突失败
        声明路径 = self.临时 / "支持库" / "模块1" / "包声明.json"
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
        """模块2 依赖 模块1的能力 且注册时校验依赖已在注册表；字母序模块2在前也必须先装模块1。"""
        写临时包(self.临时 / "支持库", "模块1", {
            "包id": "顺序.模块1", "名称": "模块1", "类型": "支持库", "版本": "1.0.0",
            "入口": "入口.py", "能力": [{"能力id": "顺序.模块1能力"}],
        })
        模块2入口 = (
            "from 公共契约.能力契约.契约 import 能力实现\n"
            "def 注册能力(注册表):\n"
            "    if 注册表.获取('顺序.模块1能力') is None:\n"
            "        raise RuntimeError('依赖 顺序.模块1能力 未装配')\n"
            "    注册表.注册(能力实现(\n"
            "        能力id='顺序.模块2能力', 包id='顺序.模块2',\n"
            "        实现函数=lambda: '顺序.模块2'))\n"
        )
        写临时包(self.临时 / "支持库", "模块2", {
            "包id": "顺序.模块2", "名称": "模块2", "类型": "支持库", "版本": "1.0.0",
            "入口": "入口.py", "能力": [{"能力id": "顺序.模块2能力"}],
            "依赖": [{"能力": "顺序.模块1能力"}],
        }, 模块2入口)
        结果 = 装配系统(self.临时 / "支持库", self.临时 / "模块库")
        self.assertTrue(结果.成功, str(结果.问题列表))
        self.assertEqual(结果.顺序列表, ["顺序.模块1", "顺序.模块2"], "装配顺序必须提供者在先")

    def test_装配失败恢复注册表无半装配残留(self):
        """模块1先注册成功、模块2安装失败：注册表必须恢复，既有能力保留。"""
        注册表 = 能力注册表()
        注册表.注册(能力实现(能力id="既有.能力", 包id="既有包", 实现函数=lambda: "旧"))
        写临时包(self.临时 / "支持库", "模块1", {
            "包id": "回滚.模块1", "名称": "模块1", "类型": "支持库", "版本": "1.0.0",
            "入口": "入口.py", "能力": [{"能力id": "回滚.模块1能力"}],
        })
        写临时包(self.临时 / "支持库", "模块2", {
            "包id": "回滚.模块2", "名称": "模块2", "类型": "支持库", "版本": "1.0.0",
            "入口": "不存在的入口.py", "能力": [{"能力id": "回滚.模块2能力"}],
            "依赖": [{"能力": "回滚.模块1能力"}],
        })
        结果 = 装配系统(self.临时 / "支持库", self.临时 / "模块库", 注册表)
        self.assertFalse(结果.成功)
        self.assertTrue(any("装配失败" in 问题 for 问题 in 结果.问题列表), str(结果.问题列表))
        回滚记录 = [记录 for 记录 in 结果.生命周期记录 if 记录.操作名称 == "回滚"]
        self.assertTrue(回滚记录, "装配失败后应产生回滚记录")
        self.assertEqual(注册表.能力id列表, ["既有.能力"], "失败后注册表必须恢复，不得残留半装配能力")
        self.assertEqual(注册表.获取("既有.能力").包id, "既有包")
        self.assertIsNone(注册表.获取("回滚.模块1能力"))


class Test装配锁单元(unittest.TestCase):
    """装配锁构建与差异检测。"""

    def test_构建装配锁与读取状态(self):
        from 公共契约.包声明.声明 import 从字典构建
        from 运行核心.加载器.提供者选择.选择器 import 选择全部提供者
        声明1 = 从字典构建({"包id": "锁.模块1", "名称": "模块1", "类型": "支持库", "版本": "1.0.0",
                            "能力": [{"能力id": "锁.模块1能力"}]})
        提供者表 = 选择全部提供者([声明1])
        锁 = 构建装配锁([声明1], 提供者表, ["锁.模块1"])
        self.assertEqual(锁.版本锁, {"锁.模块1": "1.0.0"})
        self.assertEqual(锁.能力锁, {"锁.模块1能力": "锁.模块1"})
        self.assertEqual(锁.提供者锁, {"锁.模块1能力": "1.0.0"})
        self.assertEqual(锁.顺序列表, ("锁.模块1",))
        self.assertEqual(锁.差异说明(构建装配锁([声明1], 提供者表, ["锁.模块1"])), [])

    def test_差异说明检出漂移(self):
        from 运行核心.加载器.依赖解析.装配锁 import 装配锁
        旧锁 = 装配锁(
            顺序列表=("模块1", "模块2"),
            版本锁={"模块1": "1.0.0", "模块2": "1.0.0"},
            能力锁={"模块1.能力": "模块1", "模块2.能力": "模块2"},
            提供者锁={"模块1.能力": "1.0.0", "模块2.能力": "1.0.0"},
        )
        新锁 = 装配锁(
            顺序列表=("模块2", "模块1"),
            版本锁={"模块1": "1.1.0", "模块2": "1.0.0"},
            能力锁={"模块1.能力": "模块2", "模块2.能力": "模块2"},
            提供者锁={"模块1.能力": "1.0.0", "模块2.能力": "1.0.0"},
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
