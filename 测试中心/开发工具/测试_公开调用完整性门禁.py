"""公开调用完整性门禁测试：六环一致合法样本零违规；缺口/同义/重复各检出。

覆盖：合法样本零违规、声明缺口（未列能力/能力定义缺失）、注册缺口、
说明书缺口（缺失/未含能力名）、搜索缺口（缺失/未含能力id）、公开调用缺口
（声明未导出）、验证场景缺口（缺失/未覆盖）、重复提供者、跨包同名不违规、
无声明目录跳过、循环注册映射提取、真实扫描现有包如实输出；
A-1：JSON 不可读与内容缺失分两态出条目（含异常类型、不误诊断、不静默跳过）。
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

if str(Path(__file__).resolve().parents[2]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from 开发工具.公开调用完整性门禁 import (
    找包目录, 提取导出名, 提取注册映射, 运行门禁, 检查错误码登记,
)

仓库根 = Path(__file__).resolve().parents[2]


def 写(路径: Path, 内容: str) -> None:
    路径.parent.mkdir(parents=True, exist_ok=True)
    路径.write_text(内容, encoding="utf-8")


def 合法包(根: Path, 包名: str = "示例包", 包id: str = "支持库.后端.示例包",
         能力id: str = "示例.测试能力", 能力名: str = "测试能力",
         公开根: str = "支持库/后端") -> Path:
    """构造六环完整合法包，返回包目录。"""
    包目录 = 根 / 公开根 / 包名
    写(包目录 / "包声明.json", json.dumps({"包id": 包id, "能力": [{"能力id": 能力id, "名称": 能力名}]}, ensure_ascii=False))
    写(包目录 / "能力定义.json", json.dumps({"包id": 包id, "能力列表": [{"能力id": 能力id}]}, ensure_ascii=False))
    写(包目录 / "能力数据" / "能力搜索数据.json", json.dumps([{"能力id": 能力id, "名称": 能力名}], ensure_ascii=False))
    写(包目录 / "说明" / "使用说明.md", f"# {包名}\n{能力名} 能力说明")
    写(包目录 / "验证场景引用.json", json.dumps({"验证场景引用": [{"场景id": "支持库.资产验证", "目标": 包id, "范围": "资产"}]}, ensure_ascii=False))
    写(包目录 / "__init__.py",
       f"""from {包id.replace('.', '.')}.实现.实现 import {能力名}

__all__ = ["{能力名}"]


def 注册能力(注册表) -> None:
    from 公共契约.能力契约.契约 import 能力实现
    注册表.注册(能力实现(能力id="{能力id}", 实现函数={能力名}, 参数=[], 返回="结果", 说明=""))
""")
    return 包目录


class Test公开调用完整性门禁(unittest.TestCase):
    def setUp(self):
        self.临时 = Path(tempfile.mkdtemp())

    def test_合法样本零违规(self):
        合法包(self.临时)
        self.assertEqual(运行门禁(self.临时), [])

    def test_无声明目录跳过(self):
        (self.临时 / "支持库" / "适配层" / "基础组件").mkdir(parents=True)
        self.assertEqual(找包目录(self.临时), [])

    def test_模板与适配层Provider不进入正式扫描(self):
        合法包(self.临时, 包名="_模板", 包id="模块库._模板", 公开根="模块库")
        合法包(self.临时, 包名="提供者", 包id="支持库.适配层.提供者", 公开根="支持库/适配层")
        self.assertEqual(找包目录(self.临时), [])

    def test_声明未列能力检出(self):
        包目录 = 合法包(self.临时)
        写(包目录 / "包声明.json", json.dumps({"包id": "支持库.适配层.示例包"}, ensure_ascii=False))
        违规 = 运行门禁(self.临时)
        self.assertEqual(违规[0]["缺口类型"], "声明-包声明.json未列能力")
        self.assertEqual(违规[0]["包"], "支持库.适配层.示例包")

    def test_缺能力定义检出(self):
        包目录 = 合法包(self.临时)
        (包目录 / "能力定义.json").unlink()
        违规 = 运行门禁(self.临时)
        self.assertEqual(len(违规), 1)
        self.assertEqual(违规[0]["缺口类型"], "声明-能力定义.json缺失")

    def test_入口未注册检出(self):
        包目录 = 合法包(self.临时)
        (包目录 / "能力数据" / "能力搜索数据.json").unlink()
        (包目录 / "能力数据").rmdir()
        写(包目录 / "__init__.py", '"""占位"""\n')
        类型表 = [条["缺口类型"] for 条 in 运行门禁(self.临时)]
        self.assertIn("注册-入口未注册能力", 类型表)

    def test_缺说明书检出(self):
        包目录 = 合法包(self.临时)
        (包目录 / "说明" / "使用说明.md").unlink()
        违规 = 运行门禁(self.临时)
        self.assertEqual(len(违规), 1)
        self.assertEqual(违规[0]["缺口类型"], "说明书-使用说明.md缺失")

    def test_说明书未含能力名检出(self):
        包目录 = 合法包(self.临时)
        写(包目录 / "说明" / "使用说明.md", "# 标题\n不含任何能力内容")
        违规 = 运行门禁(self.临时)
        self.assertEqual(len(违规), 1)
        self.assertEqual(违规[0]["缺口类型"], "说明书-未含能力名")
        self.assertEqual(违规[0]["能力id"], "示例.测试能力")

    def test_缺搜索数据检出(self):
        包目录 = 合法包(self.临时)
        (包目录 / "能力数据" / "能力搜索数据.json").unlink()
        违规 = 运行门禁(self.临时)
        self.assertEqual(len(违规), 1)
        self.assertEqual(违规[0]["缺口类型"], "搜索-能力搜索数据.json缺失")

    def test_搜索未含能力检出(self):
        包目录 = 合法包(self.临时)
        写(包目录 / "能力数据" / "能力搜索数据.json", json.dumps([{"能力id": "别的.能力"}], ensure_ascii=False))
        违规 = 运行门禁(self.临时)
        self.assertEqual(len(违规), 1)
        self.assertEqual(违规[0]["缺口类型"], "搜索-未含能力id")

    def test_包声明不可读与未列能力分开出条目(self):
        """A-1：JSON 坏掉报「不可读:异常类型」，不得误诊断成「未列能力」。"""
        包目录 = 合法包(self.临时)
        写(包目录 / "包声明.json", "{ 这不是 JSON")
        违规 = 运行门禁(self.临时)
        类型表 = [条["缺口类型"] for 条 in 违规]
        self.assertEqual(类型表, ["声明-包声明.json不可读:JSONDecodeError"])
        self.assertNotIn("声明-包声明.json未列能力", 类型表)

    def test_搜索数据不可读与缺失分开出条目(self):
        """A-1：文件在但解析失败 → 「不可读」，与「缺失」不得共用缺口类型。"""
        包目录 = 合法包(self.临时)
        写(包目录 / "能力数据" / "能力搜索数据.json", "[[[")
        违规 = 运行门禁(self.临时)
        self.assertEqual([条["缺口类型"] for 条 in 违规],
                         ["搜索-能力搜索数据.json不可读:JSONDecodeError"])

    def test_验证场景文件不可读不静默跳过(self):
        """A-1：引用场景文件读不成必须出条目（静默跳过会连带误报未覆盖能力）。"""
        包目录 = 合法包(self.临时)
        写(包目录 / "验证场景引用.json", json.dumps(
            {"验证场景引用": [{"场景id": "x", "目标": "支持库.后端.示例包", "场景文件": "场景/场景1.json"}]},
            ensure_ascii=False))
        违规 = 运行门禁(self.临时)
        self.assertEqual([条["缺口类型"] for 条 in 违规], ["验证场景-场景文件缺失"])

    def test_声明未导出检出(self):
        包目录 = 合法包(self.临时)
        写(包目录 / "__init__.py", '"""占位"""\n__all__ = ["未导出的名字"]\n')
        违规 = 运行门禁(self.临时)
        self.assertEqual(len(违规), 1)
        self.assertEqual(违规[0]["缺口类型"], "公开调用-声明未导出")

    def test_验证场景缺失检出(self):
        包目录 = 合法包(self.临时)
        (包目录 / "验证场景引用.json").unlink()
        违规 = 运行门禁(self.临时)
        self.assertEqual(len(违规), 1)
        self.assertEqual(违规[0]["缺口类型"], "验证场景-验证场景引用.json缺失")

    def test_验证场景未覆盖能力检出(self):
        包目录 = 合法包(self.临时)
        写(包目录 / "验证场景引用.json", json.dumps({"验证场景引用": [{"场景id": "x", "目标": "别的.包", "范围": "资产"}]}, ensure_ascii=False))
        违规 = 运行门禁(self.临时)
        self.assertEqual(len(违规), 1)
        self.assertEqual(违规[0]["缺口类型"], "验证场景-未覆盖能力")

    def test_重复提供者检出(self):
        合法包(self.临时, 包名="丙包", 包id="支持库.后端.丙包", 能力id="重复.能力", 能力名="丙能力")
        合法包(self.临时, 包名="丁包", 包id="模块库.丁包", 能力id="重复.能力", 能力名="丁能力", 公开根="模块库")
        类型表 = [条["缺口类型"] for 条 in 运行门禁(self.临时)]
        self.assertIn("重复提供者-同能力id多包", 类型表)

    def test_跨包同名不违规(self):
        """华哥裁决：能力 id 唯一即可，中文名重复是合法的（门面/多后端/通用名）。"""
        合法包(self.临时, 包名="示例包1", 包id="支持库.后端.示例包1", 能力id="示例包1.测试能力", 能力名="测试能力")
        合法包(self.临时, 包名="示例包2", 包id="支持库.后端.示例包2", 能力id="示例包2.测试能力", 能力名="测试能力")
        self.assertEqual(运行门禁(self.临时), [])

    def test_适配层Provider重复能力不形成公开owner冲突(self):
        合法包(self.临时, 包名="正式包", 包id="支持库.后端.正式包", 能力id="重复.能力", 能力名="正式能力")
        合法包(self.临时, 包名="Provider1", 包id="支持库.适配层.Provider1", 能力id="重复.能力", 能力名="Provider能力", 公开根="支持库/适配层")
        合法包(self.临时, 包名="Provider2", 包id="支持库.适配层.Provider2", 能力id="重复.能力", 能力名="Provider能力", 公开根="支持库/适配层")
        类型表 = [条["缺口类型"] for 条 in 运行门禁(self.临时)]
        self.assertNotIn("重复提供者-同能力id多包", 类型表)

    def test_正式包显式把适配层Provider声明为公开owner时阻断(self):
        包目录 = 合法包(self.临时)
        声明路径 = 包目录 / "包声明.json"
        声明 = json.loads(声明路径.read_text(encoding="utf-8"))
        声明["公开所有者"] = "支持库.适配层.示例提供者"
        声明路径.write_text(json.dumps(声明, ensure_ascii=False), encoding="utf-8")
        类型表 = [条["缺口类型"] for 条 in 运行门禁(self.临时)]
        self.assertIn("提供者-适配层Provider不得成为公开owner", 类型表)

    def test_循环注册映射提取(self):
        源码 = '''from 模块库.OCR.实现.OCR import 识别图片文字

__all__ = ["识别图片文字"]


def 注册能力(注册表) -> None:
    from 公共契约.能力契约.契约 import 能力实现
    for 能力id, 函数, 参数名 in [
        ("OCR.识别图片文字", 识别图片文字, ["图片路径"]),
    ]:
        注册表.注册(能力实现(能力id=能力id, 实现函数=函数, 参数=[], 返回="结果", 说明=""))
'''
        映射 = 提取注册映射(源码)
        导出 = 提取导出名(源码)
        self.assertEqual(映射.get("OCR.识别图片文字"), "识别图片文字")
        self.assertIn("识别图片文字", 导出)

    def test_真实扫描如实输出(self):
        """真实仓库的公开调用缺口必须如实输出，既不假绿也不误报。

        修红线已闭合（2026-09-17 实测）：原先残留的 2 个实现侧自造码各按真因收口 ——
        `写回压缩结果失败`（大语言模型支持库.上下文压缩）登记进网关两张表
        （`运行核心/统一网关/本地网关.py` 的 `公开错误码状态映射` + `网关核心.py`
        的 `公开错误说明表`，提交 841baefc）；`已存在文件`（组件规范支持库.
        技能模板生成器）在实现侧改回包内已声明的 `已存在`（包装层 `统一失败码表`
        同步收敛，见 `实现/包装辅助.py`）。故本断言随现状改为「零缺口 + 退出码 0」：
        门禁一旦漏检（假绿）或误报（假红），本用例与同模块的检出用例都会红。
        """
        违规 = 运行门禁(仓库根)
        self.assertEqual(违规, [], f"真实仓库公开调用缺口必须为空: {违规}")
        结果 = subprocess.run([sys.executable, "开发工具/公开调用完整性门禁.py"],
                            cwd=仓库根, capture_output=True, text=True)
        self.assertIn("公开调用完整性门禁通过", 结果.stdout)
        self.assertEqual(结果.returncode, 0, "零缺口时退出码必须是 0，不得恒红")

    def test_真实仓库实现侧登记环可跑且扫到码(self):
        """判据四在真仓库上必须真跑到码（扫到 0 种码 = 判据哑火，等于恒绿）。"""
        from 开发工具.公开调用完整性门禁 import 收集实现侧错误码

        码表, 不可解析, 扫描数 = 收集实现侧错误码(仓库根)
        self.assertGreater(扫描数, 100, f"实现侧扫描面过小: {扫描数}")
        self.assertEqual(不可解析, [], f"真实仓库实现侧源码必须全部可解析: {不可解析}")
        self.assertGreater(len(码表), 100, f"实现侧产码扫到过少，判据形同虚设: {len(码表)}")


class Test实现侧错误码判据(unittest.TestCase):
    """C-15：实现侧产生的码 ⊆ 状态映射码；扫不到 / 不可解析 / 真缺 三态分开出条目。"""

    def setUp(self):
        self.临时 = Path(tempfile.mkdtemp())
        self.示例包 = self.临时 / "支持库" / "后端" / "示例包"
        写(self.示例包 / "实现" / "示例.py", 'def 好():\n    return 1\n')
        写(self.临时 / "运行核心" / "统一网关" / "本地网关.py",
           '公开错误码状态映射 = {"已登记码": 400}\n')
        写(self.临时 / "运行核心" / "统一网关" / "网关核心.py",
           '公开错误说明表 = {"已登记码": "已登记"}\n')

    def test_实现侧自造码未登记检出(self):
        """`.失败("自造码")` 与 `错误码="自造码"` 两条信封渠道都必须被扫到并判红。"""
        写(self.示例包 / "实现" / "示例.py",
           'def 好():\n    结果.失败("自造码", "说明")\n    响应(错误码="另一个自造码")\n')
        违规 = 检查错误码登记(self.临时)
        self.assertEqual([条["缺口类型"] for 条 in 违规],
                         ["错误码-实现侧产生码未登记状态映射"] * 2)
        self.assertEqual(sorted(条["错误码"] for 条 in 违规), ["另一个自造码", "自造码"])

    def test_已登记的实现侧码不出条目(self):
        """反向验证：已登记码不得被误报（判据是「未登记」，不是「实现侧写了码就报」）。"""
        写(self.示例包 / "实现" / "示例.py", 'def 好():\n    结果.失败("已登记码", "说明")\n')
        self.assertEqual(检查错误码登记(self.临时), [])

    def test_行为声明字典不算实现侧产码(self):
        """反向验证：`{"错误码": "统一"}` 是行为声明/值字段，不是产码，不得报红。"""
        写(self.示例包 / "实现" / "示例.py",
           '默认行为 = {"错误码": "统一", "可重试性": "超时可重试"}\n'
           'def 好():\n    return {"成功": True, "错误码": "内部异常"}\n')
        self.assertEqual(检查错误码登记(self.临时), [])

    def test_实现侧源码不可解析出条目(self):
        """同 A-1/A-2 口径：源码坏掉不许静默跳过（跳过 = 把「未知」说成「没有码」）。"""
        写(self.示例包 / "实现" / "坏.py", "def 坏(:\n    return 1\n")
        违规 = 检查错误码登记(self.临时)
        self.assertEqual([条["缺口类型"] for 条 in 违规],
                         ["错误码-实现侧源码不可解析:SyntaxError"])
        self.assertIn("坏.py", 违规[0]["路径"])

    def test_实现侧扫描面为空出条目(self):
        """扫描面为空 = 这份仓库切片里一个实现侧文件都没有，判据什么都没看 → 必须判红。"""
        空根 = Path(tempfile.mkdtemp())
        写(空根 / "运行核心" / "统一网关" / "本地网关.py",
           '公开错误码状态映射 = {"已登记码": 400}\n')
        写(空根 / "运行核心" / "统一网关" / "网关核心.py",
           '公开错误说明表 = {"已登记码": "已登记"}\n')
        违规 = 检查错误码登记(空根)
        self.assertEqual([条["缺口类型"] for 条 in 违规], ["错误码-实现侧扫描面为空"])


if __name__ == "__main__":
    unittest.main()
