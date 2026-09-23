"""装配系统接入环境缓存测试：默认路径调用批量入口、命中/重建/失败证据、fail-closed 保留。

装配系统（管理器.py）在支持库批次装配前，收集含 依赖锁.json 的第三方提供者目录，
经 批量确保环境（≤8 并行）真实确保环境就绪，随后保留 校验提供者环境 终检。
本测试对临时迷你系统根（支持库+模块库）构造装配场景，验证：
- 装配默认路径真实调用缓存批量入口（证据写 缓存证据.jsonl）
- 命中复用/输入变化重建/失败清理 三态真实发生
- 环境确保失败（构建/就绪）仍整体阻断；依赖锁内容为空/非法按单包级跳过
  （只跳过该包 + 失败证据照落），见「架构项A」口径

**构建路径不再换掉被测本体**（`测试伪装门禁` 规则1 P1 收口，2026-09-23）：
经生产自带注入口 `环境管理器.venv`（`:692`「兼容显式注入的环境创建器」）注入
`环境夹具.假venv模块`，真 `_构建环境` / 真 `校验环境` / 真 `强制校验.校验环境` 全照跑；
构建次数由**第三方边界实测**（`假venv.调用次数`）给出。见
`测试中心/运行核心/环境夹具.py`。
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

if str(Path(__file__).resolve().parents[2]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from 公共契约.基础类型.逻辑类型 import 真, 假
from 公共契约.能力契约.契约 import 能力注册表
from 运行核心.环境指纹 import 计算环境指纹
from 运行核心.加载器.生命周期管理.管理器 import 装配系统
from 测试中心.运行核心.环境夹具 import 注入假venv, 钉住运行缓存根


def 合法锁(提供者id: str, *, 版本: str = "1.2.0") -> dict:
    """构造通过 校验提供者环境 全部规则的合法依赖锁（环境指纹取当前运行环境）。"""
    指纹 = 计算环境指纹(含外部应用=假).详细信息
    系统名 = "macOS" if 指纹["os"] == "Darwin" else 指纹["os"]
    return {
        "包": [{"名称": "python-docx", "版本": 版本, "模块名": "docx"}],
        "提供者id": 提供者id,
        "直接依赖": [{"名称": "python-docx", "版本": 版本}],
        "依赖闭包": [
            {"名称": "python-docx", "版本": 版本, "来源": "PyPI", "许可证": "BSD"},
        ],
        "环境": {"Python": 指纹["python"], "操作系统": 系统名, "CPU": 指纹["架构"]},
        "生成时间": "",
        "说明": "测试用合法锁",
    }


class Test装配接入环境缓存(unittest.TestCase):
    """装配系统接入环境缓存的闭环测试（临时迷你系统根）。"""

    def setUp(self):
        self.临时 = Path(tempfile.mkdtemp())
        # ★ 运行缓存根钉到**本用例的临时根**（返回还原函数登记给 addCleanup，还原进用例前原值）：
        # 不钉的话，网关进程设的 `系统底座_工程缓存根`/`系统底座_提供者环境根` 会把缓存根
        # 改指真仓库，证据与依赖摘要目录全落错地方（见 环境夹具.钉住运行缓存根）。
        self.addCleanup(钉住运行缓存根(self.临时 / "工程缓存"))
        (self.临时 / "支持库").mkdir()
        (self.临时 / "模块库").mkdir()

    def tearDown(self):
        shutil.rmtree(self.临时, ignore_errors=True)

    def 新支持库提供者(self, 名称: str, 锁: dict | None, *, 入口: str = "入口.py") -> Path:
        """在迷你系统根 支持库 下构造一个第三方适配层提供者。"""
        目录 = self.临时 / "支持库" / 名称
        目录.mkdir()
        (目录 / "包声明.json").write_text(json.dumps({
            "包id": f"{名称}.包",
            "名称": 名称,
            "类型": "支持库",
            "版本": "1.0.0",
            "能力": [{"能力id": f"{名称}.能力", "名称": f"{名称}能力"}],
            "入口": 入口,
        }, ensure_ascii=False), encoding="utf-8")
        (目录 / 入口).write_text(
            "from 公共契约.能力契约.契约 import 能力实现\n\n"
            "def 注册能力(注册表):\n"
            f"    注册表.注册(能力实现(\n"
            f"        能力id={名称 + '.能力'!r}, 包id={名称 + '.包'!r},\n"
            f"        实现函数=lambda: {名称!r}))\n",
            encoding="utf-8",
        )
        if 锁 is not None:
            (目录 / "依赖锁.json").write_text(
                json.dumps(锁, ensure_ascii=False), encoding="utf-8")
        return 目录

    def 证据文件(self) -> Path:
        return self.临时 / "工程缓存" / "提供者运行环境" / "缓存证据.jsonl"

    def 证据行(self) -> list[dict]:
        文件 = self.证据文件()
        if not 文件.is_file():
            return []
        return [json.loads(行) for 行 in
                文件.read_text(encoding="utf-8").splitlines() if 行.strip()]

    def 注入构建(self, **参数):
        """经生产自带注入口注入假 venv（第三方边界）；真构建/真校验全照跑。

        替换旧的 `mock.patch(…环境管理器.校验环境)` + `mock.patch(…强制校验.校验环境)`
        + `mock.patch(…环境管理器._构建环境)`：那三处把被测逻辑整段换掉
        （`测试伪装门禁` 规则1 P1/P2），断言对象是夹具本身。
        """
        return 注入假venv(**参数)

    def test_装配默认路径调用缓存批量入口_命中与重建证据(self):
        """装配默认路径经 批量确保环境 确保环境：首次重建、再次命中，不重复构建。"""
        self.新支持库提供者("装配提供者", 合法锁("装配提供者"))
        with self.注入构建() as 假venv:
            结果一 = 装配系统(self.临时 / "支持库", self.临时 / "模块库")
        self.assertTrue(结果一.成功, str(结果一.问题列表))
        self.assertEqual(假venv.调用次数, 1)
        证据 = self.证据行()
        self.assertTrue(证据)
        self.assertEqual(证据[-1]["类型"], "重建")
        self.assertEqual(证据[-1]["提供者id"], "装配提供者")
        # 再次装配（输入未变）→ 缓存命中，不重建
        with self.注入构建() as 假venv二:
            结果二 = 装配系统(self.临时 / "支持库", self.临时 / "模块库")
        self.assertTrue(结果二.成功, str(结果二.问题列表))
        self.assertEqual(假venv二.调用次数, 0, "命中复用不得重建")
        证据二 = self.证据行()
        self.assertEqual([行["类型"] for 行 in 证据二], ["重建", "命中"])

    def test_输入变化新摘要重建(self):
        """依赖锁输入变化 → 装配走新摘要重建，旧目录保留，证据两条重建。"""
        self.新支持库提供者("装配提供者", 合法锁("装配提供者", 版本="1.2.0"))
        with self.注入构建():
            结果一 = 装配系统(self.临时 / "支持库", self.临时 / "模块库")
        self.assertTrue(结果一.成功, str(结果一.问题列表))
        提供者目录 = self.临时 / "支持库" / "装配提供者"
        摘要一 = None
        for 行 in self.证据行():
            if 行["类型"] == "重建":
                摘要一 = 行["摘要"]
        self.assertTrue(摘要一)
        目录一 = 提供者目录 / "依赖锁.json"
        目录一.write_text(
            json.dumps(合法锁("装配提供者", 版本="1.1.0"), ensure_ascii=False),
            encoding="utf-8")
        with self.注入构建():
            结果二 = 装配系统(self.临时 / "支持库", self.临时 / "模块库")
        self.assertTrue(结果二.成功, str(结果二.问题列表))
        证据二 = self.证据行()
        self.assertEqual([行["类型"] for 行 in 证据二], ["重建", "重建"])
        摘要集合 = {行["摘要"] for 行 in 证据二}
        self.assertEqual(len(摘要集合), 2, "输入变化必须产生新摘要")
        环境根 = self.临时 / "工程缓存" / "提供者运行环境" / "装配提供者"
        目录表 = [目录 for 目录 in 环境根.iterdir() if 目录.is_dir()]
        self.assertEqual(len(目录表), 2, "旧摘要目录保留，新摘要目录生成")

    def test_环境确保失败整体阻断与失败清理(self):
        """构建失败 → 装配整体阻断、失败证据、半成品清理（不留残留）。"""
        self.新支持库提供者("装配提供者", 合法锁("装配提供者"))
        with self.注入构建(抛错=OSError("模拟构建失败")):
            结果 = 装配系统(self.临时 / "支持库", self.临时 / "模块库")
        self.assertFalse(结果.成功)
        self.assertTrue(
            any("提供者环境确保失败（装配阻断）" in 问题 for 问题 in 结果.问题列表),
            str(结果.问题列表),
        )
        self.assertFalse(结果.生命周期记录)
        残留 = list((self.临时 / "工程缓存" / "提供者运行环境" / "装配提供者").glob(".构建中_*"))
        self.assertEqual(残留, [], "构建失败的半成品目录必须清理")
        证据 = self.证据行()
        self.assertEqual(证据[-1]["类型"], "失败")
        self.assertEqual(证据[-1]["错误码"], "提供者不可用")
        self.assertIn("模拟构建失败", 证据[-1]["错误说明"])

    def test_空锁只跳过该包并留失败证据(self):
        """空锁是单包自己的半成品问题：只跳过该包并告警，其余包照常装配。

        新规（架构项A，2026-09-15）：依赖锁内容为空/非法只跳过该包并告警，
        不再整体阻断；但坏锁的失败证据必须照落（缓存证据 类型=失败、错误码=依赖锁为空），
        审计链不因「跳过而非阻断」而丢；被跳过的包不得留下任何半装配能力。
        """
        self.新支持库提供者("半成品提供者", {
            "包": [], "直接依赖": [], "环境": {}, "依赖闭包": [],
        })
        self.新支持库提供者("正常提供者", 合法锁("正常提供者"))
        注册表 = 能力注册表()
        with self.注入构建():
            结果 = 装配系统(self.临时 / "支持库", self.临时 / "模块库", 注册表)
        self.assertTrue(结果.成功, str(结果.问题列表))
        self.assertEqual(结果.问题列表, [], "空锁不得整体阻断")
        self.assertEqual(len(结果.跳过包列表), 1, str(结果.跳过包列表))
        self.assertIn("半成品提供者.包", 结果.跳过包列表[0])
        self.assertIn("依赖锁为空", 结果.跳过包列表[0])
        # 被跳过的包零残留；其余包照常注册能力
        self.assertEqual(注册表.能力id列表, ["正常提供者.能力"])
        self.assertEqual(结果.声明能力数, 1)
        self.assertEqual(结果.已注册能力数, 1)
        # 坏锁仍按失败落证据（审计链不丢）
        失败行 = [行 for 行 in self.证据行() if 行["类型"] == "失败"]
        self.assertEqual(len(失败行), 1, str(self.证据行()))
        self.assertEqual(失败行[0]["错误码"], "依赖锁为空")
        self.assertEqual(失败行[0]["提供者id"], "半成品提供者")
        self.assertEqual(失败行[0]["摘要"], "")

    def test_仅外部应用提供者真实命中路径(self):
        """仅外部应用（非 pip 包）提供者 → 无构建真实命中系统解释器，装配成功。"""
        指纹 = 计算环境指纹(含外部应用=假).详细信息
        系统名 = "macOS" if 指纹["os"] == "Darwin" else 指纹["os"]
        self.新支持库提供者("装配提供者", {
            "包": [{"名称": "LibreOffice soffice", "版本": "7.6",
                    "模块名": "soffice", "来源": "外部应用"}],
            "直接依赖": [],
            "依赖闭包": [],
            "环境": {"Python": 指纹["python"], "操作系统": 系统名, "CPU": 指纹["架构"]},
            "生成时间": "",
        })
        with self.注入构建() as 假venv:
            结果 = 装配系统(self.临时 / "支持库", self.临时 / "模块库")
        self.assertTrue(结果.成功, str(结果.问题列表))
        self.assertEqual(假venv.调用次数, 0)
        证据 = self.证据行()
        self.assertEqual(证据[-1]["类型"], "命中")
        self.assertEqual(证据[-1]["摘要"], "")

    def test_无锁支持库不强制环境校验(self):
        """非第三方支持库（无 依赖锁.json）→ 不触发环境确保，也不写证据。"""
        self.新支持库提供者("普通支持库", None)
        结果 = 装配系统(self.临时 / "支持库", self.临时 / "模块库")
        self.assertTrue(结果.成功, str(结果.问题列表))
        self.assertFalse(self.证据文件().exists(), "无锁支持库不得写入缓存证据")


if __name__ == "__main__":
    unittest.main()
