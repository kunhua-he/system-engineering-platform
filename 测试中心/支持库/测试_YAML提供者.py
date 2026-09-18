"""YAML提供者（第三方 PyYAML 边界）测试：容忍式导入 / 中文错误码 / 可用时行为不变 / 入口可装配。

**本文件守护的缺陷（2026-09-19 修）**：提供者实现原为**严格导入**（缺 PyYAML 即抛
`ImportError`），于是干净机器（未装 PyYAML 的 Linux / Windows / 新 macOS）上本包在
「入口装配」阶段抛错，被 `运行核心/加载器/生命周期管理/管理器.py` 记成
「已跳过 支持库.适配层.YAML提供者｜入口装配｜装配失败」，装配冒烟的「无跳过包」断言失败。
修后的口径（与 `psycopg提供者` 同形）：

- 模块**导入不抛**，只记录可用性 → 缺依赖不再阻断装配；
- 依赖缺失只在**调用时**以中文错误码 `依赖不可用` 体现，**绝不静默降级**；
- PyYAML 可用时**原有行为逐字不变**（`yaml.YAMLError` 类型口径、解析/序列化结果）。

无 PyYAML 环境必须可跑：
- 缺依赖用例在**独立子进程**里屏蔽 `yaml`（`sys.modules` 置 `None` → 真实 `ImportError`），
  不 patch 生产符号，也不要求本机真卸包；
- 全量装配冒烟为**重**用例：本机 PyYAML 存在时用 meta_path 钩子在子进程内屏蔽，
  保证「干净机器」这条路径在**任何**机器上都真被执行过，而不是只在本机缺包时才跑。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

if str(Path(__file__).resolve().parents[2]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from 公共契约.基础类型.逻辑类型 import 真, 假
from 公共契约.能力契约.契约 import 能力实现, 能力注册表
from 支持库.适配层 import YAML提供者 as 包
from 支持库.适配层.YAML提供者 import (
    检查可用性,
    注册能力,
    解析YAML,
    序列化YAML,
    YAML依赖不可用,
    YAML解析错误,
)

系统根 = Path(__file__).resolve().parents[2]
提供者目录 = 系统根 / "支持库" / "适配层" / "YAML提供者"
包id = "支持库.适配层.YAML提供者"
期望接口 = {"解析YAML", "序列化YAML", "检查可用性", "YAML解析错误",
            "YAML依赖不可用", "注册能力"}

#: 子进程屏蔽 PyYAML 的公共前缀：`sys.modules['yaml']=None` 让 `import yaml` 抛
#: 真实的 `ModuleNotFoundError`（与真机未装包同一形态），不改任何生产符号。
_屏蔽YAML = (
    "import sys\n"
    "sys.modules['yaml'] = None\n"
)
_子进程环境 = {键: 值 for 键, 值 in os.environ.items() if 键 != "PYTHONPATH"}
_子进程环境["PYTHONDONTWRITEBYTECODE"] = "1"


def _跑_子进程(代码: str, *, 超时秒: int = 300) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-B", "-c", 代码],
        capture_output=True, env=_子进程环境, cwd=str(系统根), timeout=超时秒,
    )


def _取JSON(进程: subprocess.CompletedProcess) -> dict:
    assert 进程.returncode == 0, 进程.stderr.decode("utf-8", "replace")[-1500:]
    return json.loads(进程.stdout.decode("utf-8", "replace").strip().splitlines()[-1])


class TestYAML提供者(unittest.TestCase):
    # ---------- 一、可用时行为逐字不变（本机 PyYAML 路径） ----------

    def test_PyYAML可用时解析序列化往返不变(self) -> None:
        """依赖可用时：解析出真实数据、序列化保持中文与键序（既有行为不得因改造而变）。"""
        self.assertIs(检查可用性()["可用"], 真, "本机 PyYAML 应可用（缺依赖路径由专例覆盖）")
        数据 = 解析YAML("品牌: 华世王镞\n产品: 补水面膜\n库存: 12")
        self.assertEqual(数据, {"品牌": "华世王镞", "产品": "补水面膜", "库存": 12})
        文本 = 序列化YAML({"品牌": "华世王镞", "产品": "补水面膜", "库存": 12})
        self.assertIn("品牌: 华世王镞", 文本)
        self.assertNotIn("\\u", 文本, "allow_unicode=True：中文不得被转义")
        self.assertEqual(解析YAML(文本), 数据, "序列化 → 解析必须往返一致")

    def test_YAML解析错误在依赖可用时就是第三方类型(self) -> None:
        """类型口径不得因改造漂移：可用时 `YAML解析错误` 必须**就是** `yaml.YAMLError`。"""
        import yaml as 第三方
        self.assertIs(YAML解析错误, 第三方.YAMLError,
                      "可用时 YAML解析错误 必须是 yaml.YAMLError（调用方 except 口径依赖它）")
        with self.assertRaises(YAML解析错误):
            解析YAML("品牌: [未闭合")

    def test_探针成功路径带版本且幂等(self) -> None:
        """探针成功：可用=真、版本号形如 主.次、连续调用一致（能力定义：幂等/只读）。"""
        第一次 = 检查可用性()
        第二次 = 检查可用性()
        self.assertEqual(第一次, 第二次)
        self.assertIs(第一次["可用"], 真)
        self.assertRegex(str(第一次["版本"]), r"^\d+\.\d+", "版本必须是真实版本号")

    # ---------- 二、依赖缺失（子进程真实分支，不 patch 生产符号） ----------

    def test_依赖缺失时入口可导入且调用报中文错误码(self) -> None:
        """屏蔽 yaml 后：包级入口可导入（装配不阻断）、调用报 依赖不可用、绝不静默降级。"""
        代码 = _屏蔽YAML + (
            "import json, sys\n"
            "sys.path.insert(0, '.')\n"
            "from 支持库.适配层.YAML提供者 import 解析YAML, 序列化YAML, 检查可用性, YAML依赖不可用\n"
            "出 = {'入口可导入': True, '探针': 检查可用性()}\n"
            "try:\n"
            "    解析YAML('品牌: 华世王镞')\n"
            "    出['解析'] = '未抛异常（静默降级）'\n"
            "except YAML依赖不可用 as 错误:\n"
            "    出['解析'] = 'YAML依赖不可用'\n"
            "    出['解析说明'] = str(错误)\n"
            "except BaseException as 错误:\n"
            "    出['解析'] = type(错误).__name__\n"
            "try:\n"
            "    序列化YAML({'a': 1})\n"
            "    出['序列化'] = '未抛异常（静默降级）'\n"
            "except YAML依赖不可用 as 错误:\n"
            "    出['序列化'] = 'YAML依赖不可用'\n"
            "except BaseException as 错误:\n"
            "    出['序列化'] = type(错误).__name__\n"
            "print(json.dumps(出, ensure_ascii=False))\n"
        )
        数据 = _取JSON(_跑_子进程(代码))
        探针 = 数据["探针"]
        self.assertIs(探针["可用"], 假, "缺依赖时探针不得报告可用")
        self.assertEqual(探针["版本"], "", "缺依赖时版本必须为空（不编造）")
        self.assertIn("yaml", str(探针["说明"]), "探针说明必须点明缺的是哪个依赖")
        self.assertEqual(数据["解析"], "YAML依赖不可用",
                         "缺依赖时解析YAML必须抛 YAML依赖不可用，不得返回空值冒充成功")
        self.assertEqual(数据["序列化"], "YAML依赖不可用",
                         "缺依赖时序列化YAML必须抛 YAML依赖不可用，不得返回空文本冒充成功")
        self.assertIn("yaml", 数据.get("解析说明", ""), "失败说明必须留痕到导入失败原因")

    def test_依赖缺失时能力层返回依赖不可用错误码(self) -> None:
        """能力边界把「依赖缺失」翻成中文错误码 依赖不可用（三条能力一致），且探针可重试。"""
        代码 = _屏蔽YAML + (
            "import json, sys\n"
            "sys.path.insert(0, '.')\n"
            "from 公共契约.能力契约.契约 import 能力注册表\n"
            "from 支持库.适配层.YAML提供者 import 注册能力\n"
            "注册表 = 能力注册表()\n"
            "注册能力(注册表)\n"
            "出 = {'能力数': len(注册表.能力id列表), '各能力': {}}\n"
            "for 能力id, 参数 in [('适配层.YAML提供者.解析YAML', {'文本': '品牌: 华世王镞'}),\n"
            "                    ('适配层.YAML提供者.序列化YAML', {'数据': {'a': 1}}),\n"
            "                    ('适配层.YAML提供者.检查可用性', {})]:\n"
            "    结果 = 注册表.获取(能力id).实现函数(**参数)\n"
            "    出['各能力'][能力id] = {'成功': 结果.成功, '错误码': 结果.错误码,\n"
            "                            '可重试': 结果.可重试, '说明': 结果.错误说明}\n"
            "print(json.dumps(出, ensure_ascii=False))\n"
        )
        数据 = _取JSON(_跑_子进程(代码))
        self.assertEqual(数据["能力数"], 3, "包级入口必须注册齐三条能力")
        for 能力id, 结果 in 数据["各能力"].items():
            self.assertFalse(结果["成功"], f"{能力id} 缺依赖时不得假装成功")
            self.assertEqual(结果["错误码"], "依赖不可用",
                             f"{能力id} 缺依赖时必须报中文错误码 依赖不可用，实得 {结果['错误码']}")
            self.assertIs(结果["可重试"], 真,
                          f"{能力id} 依赖不可用属可重试（装好 PyYAML 即恢复）")
            self.assertTrue(结果["说明"].strip(), f"{能力id} 失败说明不得为空")

    # ---------- 三、装配不再被跳过（缺陷的直接反向断言） ----------

    def test_依赖缺失时入口装配成功且包不被跳过(self) -> None:
        """缺 PyYAML 时整机装配必须成功、0 跳过包、能力数等于完整口径（断言本包在册）。

        屏蔽手段用 `sys.meta_path` 钩子在**子进程**里拦 `yaml`：本机装了 PyYAML 也照样
        走得到「干净机器」这条路径（不依赖本机碰巧缺包，避免只在 CI 上才发现回归）。
        """
        代码 = (
            "import json, sys\n"
            "from pathlib import Path\n"
            "class _屏蔽yaml:\n"
            "    def find_spec(self, 全名, 路径=None, 目标=None):\n"
            "        if 全名 == 'yaml' or 全名.startswith('yaml.'):\n"
            "            raise ImportError('干净机器模拟：PyYAML 未安装')\n"
            "        return None\n"
            "sys.meta_path.insert(0, _屏蔽yaml())\n"
            "sys.path.insert(0, '.')\n"
            "from 后端核心.后端核心 import 后端核心\n"
            "后端 = 后端核心(Path('.'))\n"
            "装配 = 后端.启动()\n"
            "快照 = 后端.状态快照()\n"
            "print(json.dumps({'装配成功': 装配.成功, '错误码': 装配.错误码,\n"
            "                  '能力数': 快照.get('能力数'),\n"
            "                  '跳过包': 快照.get('装配跳过包') or [],\n"
            "                  '有YAML能力': '适配层.YAML提供者.解析YAML' in 后端.注册表.能力id列表},\n"
            "                 ensure_ascii=False))\n"
        )
        数据 = _取JSON(_跑_子进程(代码))
        self.assertIs(数据["装配成功"], 真, f"缺 PyYAML 时装配不得失败：{数据.get('错误码')}")
        self.assertEqual(数据["跳过包"], [],
                         "缺 PyYAML 不得把 YAML提供者 记成「入口装配｜装配失败」跳过："
                         + "；".join(数据["跳过包"]))
        self.assertGreater(数据["能力数"], 0, "能力数不得为 0")
        self.assertIs(数据["有YAML能力"], 真,
                      "缺 PyYAML 时 YAML提供者 的能力必须照常注册进注册表（装配不阻断的实证）")

    # ---------- 四、接口面与产物一致 ----------

    def test_包级接口面与能力定义三方一致(self) -> None:
        """`__all__`、注册表实际注册、包声明与能力定义的能力清单必须三方一致。"""
        self.assertEqual(set(包.__all__), 期望接口, "__all__ 与现行接口不一致（改接口必须同步本测试）")
        for 名称 in sorted(期望接口):
            self.assertTrue(callable(getattr(包, 名称, None)), f"包级入口缺失可调用对象: {名称}")
        注册表 = 能力注册表()
        注册能力(注册表)
        声明数据 = json.loads((提供者目录 / "包声明.json").read_text(encoding="utf-8"))
        定义数据 = json.loads((提供者目录 / "能力定义.json").read_text(encoding="utf-8"))
        声明能力表 = sorted(能力["能力id"] for 能力 in 声明数据["能力"])
        定义能力表 = sorted(能力["能力id"] for 能力 in 定义数据["能力列表"])
        self.assertEqual(声明数据["包id"], 包id)
        self.assertEqual(定义数据["包id"], 包id)
        self.assertEqual(声明数据["版本"], 定义数据["版本"], "包声明与能力定义的包版本必须一致")
        self.assertEqual(sorted(注册表.能力id列表), 声明能力表, "注册表实际注册必须与包声明一致")
        self.assertEqual(定义能力表, 声明能力表, "能力定义与包声明的能力清单必须一致")
        注册实现 = 注册表.获取("适配层.YAML提供者.检查可用性")
        self.assertIsInstance(注册实现, 能力实现)
        self.assertEqual(注册实现.包id, 包id)

    def test_依赖缺失错误码已在契约声明(self) -> None:
        """`依赖不可用` 必须写进三条能力的契约与说明书（声明面与实现面不得两张皮）。"""
        定义数据 = json.loads((提供者目录 / "能力定义.json").read_text(encoding="utf-8"))
        声明面 = {能力["能力id"]: 能力.get("错误码", []) for 能力 in 定义数据["能力列表"]}
        self.assertEqual(sorted(声明面), sorted([
            "适配层.YAML提供者.解析YAML", "适配层.YAML提供者.序列化YAML",
            "适配层.YAML提供者.检查可用性"]))
        for 能力id, 错误码 in 声明面.items():
            self.assertIn("依赖不可用", 错误码,
                          f"{能力id} 的契约必须声明 依赖不可用（实现确实会返回它）")
        说明书 = (提供者目录 / "说明" / "使用说明.md").read_text(encoding="utf-8")
        self.assertIn("依赖不可用", 说明书, "说明书必须载明 依赖不可用")

    def test_完整性摘要与真实文件闭合(self) -> None:
        """摘要经唯一生成器校验通过（含逐文件 sha256），防止改源不重算摘要。"""
        from 支持库.后端.组件规范支持库 import 校验完整性摘要

        通过, 问题 = 校验完整性摘要(提供者目录)
        self.assertTrue(通过, f"摘要漂移: {问题}")


if __name__ == "__main__":
    unittest.main()
