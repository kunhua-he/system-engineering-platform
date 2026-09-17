"""测试支持库：契约一致性、命令白名单准入、结果判定与验证计划真实调用测试。

真实调用口径：
- 一律经包级中文入口（`支持库.后端.测试支持库`）调用三个能力；
- 结果判定用**真实执行输出**：临时目录里真跑一次 `python3.14 -m unittest`，
  把真实 退出码/标准输出 回传给 `测试支持库.验证结果判定` 判定；
- 临时目录一律放系统临时根，不在仓库内落任何文件。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from 公共契约.基础类型.逻辑类型 import 真, 假
from 公共契约.能力契约.契约 import 能力注册表
from 支持库.后端.测试支持库 import 注册能力, 验证命令白名单, 验证计划, 验证结果判定

根目录 = Path(__file__).resolve().parents[2]
包目录 = 根目录 / "支持库" / "后端" / "测试支持库"

三条能力id = {
    "测试支持库.验证计划",
    "测试支持库.验证命令白名单",
    "测试支持库.验证结果判定",
}

实际测试模块 = "测试中心.支持库.测试_测试支持库"

零测试样例源码 = (
    "import unittest\n\n\nclass 空(unittest.TestCase):\n"
    '    """没有任何 test_ 方法的空测试类。"""\n\n'
    "    def 辅助(self) -> None:\n        pass\n"
)
有测试样例源码 = (
    "import unittest\n\n\nclass 有(unittest.TestCase):\n"
    "    def test_A(self) -> None:\n        self.assertTrue(True)\n\n"
    "    def test_B(self) -> None:\n        self.assertEqual(1 + 1, 2)\n"
)


def 真跑(工作目录: Path, 模块名: str) -> tuple[int, str]:
    """在当前解释器里真跑一个 unittest 模块，返回 (退出码, 标准输出+标准错误)。"""
    环境 = dict(os.environ)
    环境.pop("PYTHONPATH", None)
    环境["PYTHONDONTWRITEBYTECODE"] = "1"
    完成 = subprocess.run(
        [sys.executable, "-m", "unittest", 模块名],
        cwd=str(工作目录), capture_output=True, text=True, timeout=120, env=环境,
    )
    return 完成.returncode, f"{完成.stdout}\n{完成.stderr}"


class 测试测试支持库(unittest.TestCase):
    """三条原子能力的契约、边界与真实判定。"""

    def setUp(self) -> None:
        self.临时根 = Path(tempfile.mkdtemp(prefix="测试支持库_"))

    def tearDown(self) -> None:
        import shutil

        shutil.rmtree(self.临时根, ignore_errors=True)

    # ── 契约与装配 ────────────────────────────────────────────────────

    def test_包声明契约权限与验证场景口径一致(self) -> None:
        声明 = json.loads((包目录 / "包声明.json").read_text(encoding="utf-8"))
        self.assertEqual(声明["类型"], "支持库")
        self.assertEqual(声明["包id"], "支持库.后端.测试支持库")
        self.assertEqual({能力["能力id"] for 能力 in 声明["能力"]}, 三条能力id)
        self.assertTrue(声明["依赖"] == [])

        契约 = json.loads((包目录 / "能力契约" / "参数契约.json").read_text(encoding="utf-8"))
        self.assertEqual({条目["能力id"] for 条目 in 契约["能力契约"]}, 三条能力id)
        for 条目 in 契约["能力契约"]:
            self.assertTrue(条目["错误码"], f"{条目['能力id']} 错误码为空")
            self.assertEqual(条目["提供者"]["默认"], "支持库.后端.测试支持库")

        权限 = json.loads((包目录 / "权限契约" / "权限契约.json").read_text(encoding="utf-8"))
        self.assertEqual(set(权限), 三条能力id)

        引用 = json.loads((包目录 / "验证场景引用.json").read_text(encoding="utf-8"))
        self.assertEqual(引用["契约版本"], "验证场景/v1")
        self.assertEqual(引用["验证场景引用"], [{"场景文件": "验证场景.json"}])

        场景 = json.loads((包目录 / "验证场景.json").read_text(encoding="utf-8"))
        self.assertTrue(场景["验证场景"])
        for 条目 in 场景["验证场景"]:
            self.assertEqual(
                set(条目), {"场景id", "前置步骤", "目标步骤", "清理步骤"},
                f"场景 {条目.get('场景id')} 不是恰好四键",
            )
            self.assertTrue(条目["目标步骤"])

    def test_注册能力注册三条且能力数据与契约对称(self) -> None:
        注册表 = 能力注册表()
        注册能力(注册表)
        self.assertEqual(set(注册表.能力id列表), 三条能力id)
        搜索数据 = json.loads(
            (包目录 / "能力数据" / "能力搜索数据.json").read_text(encoding="utf-8")
        )
        契约 = json.loads((包目录 / "能力契约" / "参数契约.json").read_text(encoding="utf-8"))
        契约参数表 = {
            条目["能力id"]: [参数["名称"] for 参数 in 条目["参数"]]
            for 条目 in 契约["能力契约"]
        }
        for 条目 in 搜索数据:
            self.assertEqual(条目["参数"], 契约参数表[条目["能力id"]])

    # ── 验证计划 ──────────────────────────────────────────────────────

    def test_验证计划扫出精确模块命令且只读(self) -> None:
        样例目录 = self.临时根 / "测试中心" / "样例域"
        样例目录.mkdir(parents=True)
        (样例目录 / "测试_样例.py").write_text("import unittest\n", encoding="utf-8")
        结果 = 验证计划(
            目标路径="测试中心/样例域", 仓库根目录=str(self.临时根), 级别="工作包",
        )
        self.assertTrue(结果.成功, 结果.错误说明)
        self.assertEqual(结果.值["测试模块列表"], ["测试中心.样例域.测试_样例"])
        self.assertEqual(
            结果.值["命令列表"], [["python3.14", "-m", "测试中心.样例域.测试_样例"]]
        )
        self.assertEqual(结果.值["命令数"], 1)
        self.assertIs(结果.值["只读"], 真)

    def test_验证计划支持点分模块名与关键词过滤(self) -> None:
        样例目录 = self.临时根 / "测试中心" / "样例域"
        样例目录.mkdir(parents=True)
        (样例目录 / "测试_A.py").write_text("import unittest\n", encoding="utf-8")
        (样例目录 / "测试_B.py").write_text("import unittest\n", encoding="utf-8")
        单文件 = 验证计划(
            目标路径="测试中心.样例域.测试_A", 仓库根目录=str(self.临时根),
        )
        self.assertEqual(单文件.值["命令数"], 1)
        带关键词 = 验证计划(
            目标路径="测试中心/样例域", 仓库根目录=str(self.临时根), 关键词="测试_B",
        )
        self.assertEqual(带关键词.值["测试模块列表"], ["测试中心.样例域.测试_B"])

    def test_验证计划阶段收口缺制品拒绝生成命令(self) -> None:
        样例目录 = self.临时根 / "测试中心" / "样例域"
        样例目录.mkdir(parents=True)
        (样例目录 / "测试_样例.py").write_text("import unittest\n", encoding="utf-8")
        结果 = 验证计划(
            目标路径="测试中心/样例域", 仓库根目录=str(self.临时根), 级别="阶段收口",
        )
        self.assertTrue(结果.成功)
        self.assertEqual(结果.值["命令数"], 0)
        self.assertIn("拒绝生成验证命令", 结果.值["说明"])

    def test_验证计划正式发布出黑盒与唯一发布命令(self) -> None:
        制品 = self.临时根 / "工程缓存" / "制品"
        制品.mkdir(parents=True)
        结果 = 验证计划(
            目标路径="测试中心", 仓库根目录=str(self.临时根),
            级别="正式发布", 制品目录="工程缓存/制品",
        )
        self.assertTrue(结果.成功, 结果.错误说明)
        self.assertEqual(结果.值["命令列表"][0][2], "开发工具.HTML验证.验证器")
        self.assertEqual(
            结果.值["命令列表"][1], ["python3.14", "开发工具/发布门禁/运行发布门禁.py"]
        )

    def test_验证计划能扫到本包自己的测试模块(self) -> None:
        结果 = 验证计划(目标路径="支持库/后端/测试支持库", 级别="工作包")
        self.assertTrue(结果.成功, 结果.错误说明)
        self.assertIn(实际测试模块, 结果.值["测试模块列表"])

    def test_验证计划参数不合法与目标不存在(self) -> None:
        空目标 = 验证计划(目标路径="")
        self.assertFalse(空目标.成功)
        self.assertEqual(空目标.错误码, "参数不合法")

        坏级别 = 验证计划(目标路径="测试中心", 级别="随便")
        self.assertFalse(坏级别.成功)
        self.assertEqual(坏级别.错误码, "参数不合法")

        不存在 = 验证计划(目标路径="不存在的目录/子目录")
        self.assertFalse(不存在.成功)
        self.assertEqual(不存在.错误码, "目标不存在")

        坏根 = 验证计划(目标路径="测试中心", 仓库根目录=str(self.临时根 / "没有这个根"))
        self.assertFalse(坏根.成功)
        self.assertEqual(坏根.错误码, "目录不存在")

    # ── 验证命令白名单 ────────────────────────────────────────────────

    def test_白名单允许三种受控形态(self) -> None:
        模块 = 验证命令白名单(
            命令=["python3.14", "-m", 实际测试模块], 校验存在=假,
        )
        self.assertTrue(模块.成功, 模块.错误说明)
        self.assertIs(模块.值["允许"], 真)
        self.assertEqual(模块.值["形态"], "unittest")

        黑盒 = 验证命令白名单(
            命令=["python3.14", "-m", "开发工具.HTML验证.验证器",
                 "--制品", "工程缓存/制品", "--并发", "32"],
            校验存在=假,
        )
        self.assertIs(黑盒.值["允许"], 真)
        self.assertEqual(黑盒.值["形态"], "HTML验证")

        发布 = 验证命令白名单(
            命令=["python3.14", "开发工具/发布门禁/运行发布门禁.py"], 校验存在=假,
        )
        self.assertIs(发布.值["允许"], 真)
        self.assertEqual(发布.值["形态"], "正式发布")

    def test_白名单拒绝非法命令并给错误码(self) -> None:
        拒绝样例 = [
            ["python3.14", "/tmp/随手脚本.py"],
            ["python3.14", "-m", f"{实际测试模块};rm -rf /"],
            ["python3.14", "-m", 实际测试模块, "--额外参数", "x"],
            ["python3.14", "-m", "测试中心.支持库.随便一个模块"],
            ["python3.14", "开发工具/随便跑.py"],
            ["/usr/bin/python3.14", "-m", 实际测试模块],
            ["python3.14", "-m", "../逃逸/测试_坏"],
            [],
        ]
        for 命令 in 拒绝样例:
            结果 = 验证命令白名单(命令=命令, 校验存在=假)
            self.assertTrue(结果.成功, f"{命令} 不应抛失败")
            self.assertIs(结果.值["允许"], 假, f"{命令} 应被拒绝")
            self.assertEqual(结果.值["错误码"], "命令拒绝", f"{命令} 错误码不对")
            self.assertEqual(结果.值["形态"], "拒绝")

    def test_白名单存在性校验默认开启(self) -> None:
        样例目录 = self.临时根 / "测试中心" / "样例域"
        样例目录.mkdir(parents=True)
        (样例目录 / "测试_样例.py").write_text("import unittest\n", encoding="utf-8")
        存在 = 验证命令白名单(
            命令=["python3.14", "-m", "测试中心.样例域.测试_样例"],
            仓库根目录=str(self.临时根),
        )
        self.assertIs(存在.值["允许"], 真)
        self.assertIs(存在.值["存在性校验"], 真)

        缺失 = 验证命令白名单(
            命令=["python3.14", "-m", "测试中心.样例域.测试_不存在"],
            仓库根目录=str(self.临时根),
        )
        self.assertIs(缺失.值["允许"], 假)
        self.assertIn("不存在", 缺失.值["消息"])

        坏根 = 验证命令白名单(
            命令=["python3.14", "-m", "测试中心.样例域.测试_样例"],
            仓库根目录=str(self.临时根 / "没有这个根"),
        )
        self.assertFalse(坏根.成功)
        self.assertEqual(坏根.错误码, "参数不合法")

    def test_白名单命令不是列表即参数不合法(self) -> None:
        结果 = 验证命令白名单(命令="python3.14 -m unittest")
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "参数不合法")

    # ── 验证结果判定（真实执行输出） ──────────────────────────────────

    def test_判定真实零测试输出必须阻断(self) -> None:
        (self.临时根 / "测试_空.py").write_text(零测试样例源码, encoding="utf-8")
        真实退出码, 真实输出 = 真跑(self.临时根, "测试_空")
        self.assertIn("Ran 0 tests", 真实输出)
        # 真实运行器对空模块给非零退出码 → 验证失败
        非零 = 验证结果判定(退出码=真实退出码, 标准输出=真实输出)
        self.assertEqual(非零.值["判定"], "阻断")
        self.assertEqual(非零.值["阻断码"], "验证失败")
        # 退出码为零但零测试（假绿）→ 必须判零测试阻断
        假绿 = 验证结果判定(
            退出码=0, 标准输出=真实输出, 命令=["python3.14", "-m", 实际测试模块],
        )
        self.assertEqual(假绿.值["判定"], "阻断")
        self.assertEqual(假绿.值["阻断码"], "零测试")
        self.assertIn("零测试", 假绿.值["检出"])

    def test_判定真实通过输出判通过(self) -> None:
        (self.临时根 / "测试_有.py").write_text(有测试样例源码, encoding="utf-8")
        真实退出码, 真实输出 = 真跑(self.临时根, "测试_有")
        self.assertEqual(真实退出码, 0, 真实输出)
        结果 = 验证结果判定(
            退出码=真实退出码, 标准输出=真实输出,
            命令=["python3.14", "-m", 实际测试模块],
        )
        self.assertTrue(结果.成功, 结果.错误说明)
        self.assertEqual(结果.值["判定"], "通过")
        self.assertEqual(结果.值["阻断码"], "")
        self.assertIs(结果.值["真实执行证据"], 真)

    def test_判定零测试成功与缺证据均阻断(self) -> None:
        零测试 = 验证结果判定(
            退出码=0, 标准输出="Ran 0 tests in 0.000s\n\nOK\n",
            命令=["python3.14", "-m", 实际测试模块],
        )
        self.assertEqual(零测试.值["阻断码"], "零测试")

        无证据 = 验证结果判定(退出码=0, 标准输出="", 命令=["python3.14", "-m", 实际测试模块])
        self.assertEqual(无证据.值["阻断码"], "零测试")
        self.assertIs(无证据.值["真实执行证据"], 假)

    def test_判定导入失败当跳过与未解释跳过阻断(self) -> None:
        导入失败 = 验证结果判定(
            退出码=0,
            标准输出="Ran 2 tests in 0.010s\n\nOK (skipped=1)\n",
            标准错误="skipped '测试_坏模块': ModuleNotFoundError: No module named '不存在的库'",
            命令=["python3.14", "-m", 实际测试模块],
        )
        self.assertEqual(导入失败.值["判定"], "阻断")
        self.assertEqual(导入失败.值["阻断码"], "导入失败当跳过")

        未解释 = 验证结果判定(
            退出码=0,
            标准输出="Ran 2 tests in 0.010s\n\nOK (skipped=1)\nSKIPPED [1] 测试_样例.py:12\n",
            命令=["python3.14", "-m", 实际测试模块],
        )
        self.assertEqual(未解释.值["阻断码"], "未解释跳过")

        结构缺原因 = 验证结果判定(
            退出码=0, 标准输出="Ran 2 tests in 0.010s\n\nOK (skipped=1)\n",
            命令=["python3.14", "-m", 实际测试模块],
            跳过列表=[{"用例": "test_需要外部依赖", "原因": "   "}],
        )
        self.assertEqual(结构缺原因.值["阻断码"], "未解释跳过")

        已解释 = 验证结果判定(
            退出码=0,
            标准输出="Ran 2 tests in 0.010s\n\nOK (skipped=1)\n"
                     "SKIPPED [1] 测试_样例.py:12: 原因：本机未安装 Tesseract",
            命令=["python3.14", "-m", 实际测试模块],
        )
        self.assertEqual(已解释.值["判定"], "通过")

    def test_判定缓存假绿阻断(self) -> None:
        结果 = 验证结果判定(
            退出码=0, 标准输出="命中缓存，复用上次结果，未真实执行\n",
            命令=["python3.14", "-m", 实际测试模块],
        )
        self.assertEqual(结果.值["判定"], "阻断")
        self.assertEqual(结果.值["阻断码"], "缓存假绿")
        self.assertIs(结果.值["真实执行证据"], 假)

    def test_判定收集错误与参数不合法(self) -> None:
        收集错误 = 验证结果判定(退出码=0, 标准输出="ERROR: 测试中心/支持库/测试_坏.py\n")
        self.assertEqual(收集错误.值["阻断码"], "验证失败")

        逻辑退出码 = 验证结果判定(退出码=真, 标准输出="Ran 1 test\nOK")
        self.assertFalse(逻辑退出码.成功)
        self.assertEqual(逻辑退出码.错误码, "参数不合法")

        命令非列表 = 验证结果判定(退出码=0, 标准输出="Ran 1 test\nOK", 命令="python3.14")
        self.assertFalse(命令非列表.成功)
        self.assertEqual(命令非列表.错误码, "参数不合法")


if __name__ == "__main__":
    unittest.main()
