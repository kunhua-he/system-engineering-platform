"""第一批维修：MCP 与开发入口正式发布链回归。"""
from __future__ import annotations

import importlib
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

系统根 = Path(__file__).resolve().parents[2]
for 导入路径 in (系统根, 系统根 / "MCP工具箱"):
    if str(导入路径) not in sys.path:
        sys.path.insert(0, str(导入路径))

发布治理 = importlib.import_module("MCP工具箱.发布治理")
验证门禁 = importlib.import_module("MCP工具箱.验证门禁")
项目服务 = importlib.import_module("MCP工具箱.项目服务")
开发入口 = importlib.import_module("开发工具.开发入口")
查询模块 = importlib.import_module("开发工具.统一能力入口.Agent查询.查询入口")

提交 = "a" * 40
来源指纹 = "b" * 64


class 开发入口发布门禁透传测试(unittest.TestCase):
    def test_退出码零但状态阻断仍失败(self) -> None:
        结果 = 开发入口.执行发布检查(
            命令列表=["python3.14", "-c", "print('发布状态: 阻断')"])
        self.assertFalse(结果["成功"], 结果)
        self.assertEqual(结果["退出码"], 0)
        self.assertEqual(结果["发布状态"], "阻断")

    def test_状态通过但退出码非零仍失败且透传退出码(self) -> None:
        结果 = 开发入口.执行发布检查(
            命令列表=["python3.14", "-c", "import sys; print('发布状态: 通过'); sys.exit(7)"])
        self.assertFalse(结果["成功"], 结果)
        self.assertEqual(结果["退出码"], 7)
        self.assertEqual(结果["发布状态"], "通过")

    def test_只有退出码零且状态明确通过才成功(self) -> None:
        结果 = 开发入口.执行发布检查(
            命令列表=["python3.14", "-c", "print('发布状态: 通过')"])
        self.assertTrue(结果["成功"], 结果)
        self.assertEqual(结果["退出码"], 0)
        self.assertEqual(结果["发布状态"], "通过")


class 正式发布命令同源测试(unittest.TestCase):
    def test_工作包计划只生成精确unittest模块命令(self) -> None:
        计划 = 项目服务._验证计划(["MCP工具箱/项目服务.py"], "工作包")
        self.assertTrue(计划["建议命令"], 计划)
        for 命令 in 计划["建议命令"]:
            self.assertEqual(命令[:2], ["python3.14", "-m"])
            self.assertTrue(命令[2].startswith("测试中心."), 命令)
            self.assertNotIn("测试中心/运行测试.py", 命令)
            self.assertTrue(验证门禁.校验验证命令(命令)["成功"], 命令)

    def test_阶段收口只验证已编译制品不跑旧全量(self) -> None:
        制品 = "工程缓存/编译制品/候选甲"
        计划 = 项目服务._验证计划(["运行核心"], "阶段收口", 制品=制品)
        self.assertEqual(计划["建议命令"], [[
            "python3.14", "开发工具/HTML验证/验证器.py",
            "--制品", 制品, "--并发", "8",
        ]])
        self.assertFalse(计划["是否需要全量"])

    def test_计划与白名单使用同一正式发布命令源(self) -> None:
        制品 = "工程缓存/编译制品/候选甲"
        期望命令 = 验证门禁.正式发布命令表(制品)
        计划 = 项目服务._验证计划(["MCP工具箱/项目服务.py"], "正式发布", 制品=制品)
        self.assertEqual(计划["建议命令"], 期望命令)
        self.assertEqual(len(期望命令), 2)
        for 命令 in 期望命令:
            self.assertTrue(验证门禁.校验验证命令(命令)["成功"], 命令)

    def test_只放行受控HTML与唯一发布入口_普通任意命令仍拒绝(self) -> None:
        self.assertTrue(验证门禁.校验验证命令([
            "python3.14", "开发工具/HTML验证/验证器.py",
            "--制品", "工程缓存/编译制品/候选甲", "--并发", "8",
        ])["成功"])
        self.assertTrue(验证门禁.校验验证命令(
            ["python3.14", "开发工具/发布门禁/运行发布门禁.py"])["成功"])
        for 命令 in (
            ["python3.14", "-c", "print(1)"],
            ["python3.14", "开发工具/发布门禁/运行发布门禁.py", "--任意", "1"],
            ["python3.14", "开发工具/HTML验证/验证器.py", "--服务", "45081"],
        ):
            self.assertFalse(验证门禁.校验验证命令(命令)["成功"], 命令)


class 正式发布证据与只读状态测试(unittest.TestCase):
    def _写正式证据(self, 证据目录: Path, 制品摘要: str = "c" * 32) -> tuple[str, dict]:
        工作区指纹 = 发布治理.当前工作区指纹()
        结果 = 发布治理.生成发布证据(
            提交, "正式发布门禁", 0, 工作区指纹,
            证据目录=证据目录,
            证据类型=发布治理.正式发布证据类型,
            命令=list(验证门禁.唯一发布命令),
            制品摘要=制品摘要,
            来源指纹=来源指纹,
            能力覆盖=["文件.读取", "文本.分割"],
            场景覆盖={"总数": 2, "通过数": 2, "失败数": 0},
            真实结果={"成功": True, "状态": "通过"},
            状态="通过",
        )
        self.assertTrue(结果.成功, 结果)
        return 工作区指纹, 结果.数据

    def test_正式证据绑定专用类型命令制品提交指纹覆盖与状态(self) -> None:
        with tempfile.TemporaryDirectory() as 临时:
            目录 = Path(临时)
            工作区指纹, _ = self._写正式证据(目录)
            状态 = 发布治理.读取正式发布状态(
                证据目录=目录, 提交=提交, 工作区指纹=工作区指纹)
            self.assertTrue(状态.成功, 状态)
            for 键 in ("制品摘要", "场景覆盖", "真实结果", "提交", "工作区指纹", "能力覆盖"):
                self.assertIn(键, 状态.数据)
            self.assertEqual(状态.数据["类型"], 发布治理.正式发布证据类型)
            self.assertEqual(状态.数据["命令"], list(验证门禁.唯一发布命令))
            self.assertEqual(状态.数据["状态"], "通过")

    def test_普通工作包成功不得冒充正式发布(self) -> None:
        with tempfile.TemporaryDirectory() as 临时:
            目录 = Path(临时)
            工作区指纹 = 发布治理.当前工作区指纹()
            普通 = 发布治理.生成发布证据(
                提交, "工作包测试成功", 0, 工作区指纹, 证据目录=目录)
            self.assertTrue(普通.成功, 普通)
            状态 = 发布治理.读取正式发布状态(
                证据目录=目录, 提交=提交, 工作区指纹=工作区指纹)
            self.assertFalse(状态.成功, 状态)

    def test_开发入口与查询入口只读同一事实源(self) -> None:
        with tempfile.TemporaryDirectory() as 临时:
            目录 = Path(临时)
            工作区指纹, _ = self._写正式证据(目录)
            修改前 = sorted((项.name, 项.read_bytes()) for 项 in 目录.iterdir())
            开发状态 = 开发入口.查看验证状态(
                证据目录参数=目录, 提交=提交, 工作区指纹=工作区指纹)
            查询状态 = 查询模块.查询入口().查看验证状态(
                证据目录参数=目录, 提交=提交, 工作区指纹=工作区指纹)
            修改后 = sorted((项.name, 项.read_bytes()) for 项 in 目录.iterdir())
            self.assertEqual(修改前, 修改后, "查看验证状态必须只读")
            self.assertTrue(开发状态["成功"], 开发状态)
            self.assertTrue(查询状态.成功, 查询状态)
            self.assertEqual(开发状态["数据"], 查询状态.数据)


class 激活指针前置校验测试(unittest.TestCase):
    def setUp(self) -> None:
        self.临时 = tempfile.TemporaryDirectory()
        self.接入列表 = []
        self.根 = Path(self.临时.name)
        self.制品根 = self.根 / "制品仓库"
        self.状态目录 = self.根 / "状态"
        self.环境目录 = self.根 / "环境"
        self.信任目录 = self.根 / "信任"
        self.证据目录 = self.根 / "证据"
        self.环境目录.mkdir(parents=True)
        self.旧指针 = {
            "摘要sha256": "0" * 16, "制品目录": "平台客户端-" + "0" * 16,
            "制品摘要": "0" * 32, "版本": 2, "栅栏令牌": 2,
        }
        (self.环境目录 / "当前.json").write_text(
            json.dumps(self.旧指针, ensure_ascii=False), encoding="utf-8")
        self.制品摘要 = self._建真实签名制品()
        self.工作区指纹 = 发布治理.当前工作区指纹()
        正式 = 发布治理.生成发布证据(
            提交, "正式发布门禁", 0, self.工作区指纹,
            证据目录=self.证据目录,
            证据类型=发布治理.正式发布证据类型,
            命令=list(验证门禁.唯一发布命令),
            制品摘要=self.制品摘要, 来源指纹=来源指纹,
            能力覆盖=["示例.能力"],
            场景覆盖={"总数": 1, "通过数": 1, "失败数": 0},
            真实结果={"成功": True, "状态": "通过"}, 状态="通过",
        )
        self.assertTrue(正式.成功, 正式)

    def tearDown(self) -> None:
        for 接入 in self.接入列表:
            接入.关闭()
        self.临时.cleanup()

    def _建真实签名制品(self) -> str:
        from 平台控制面.包仓库.平台客户端制品 import 平台客户端制品接入, 计算目录摘要16
        候选 = self.根 / "候选"
        候选.mkdir()
        (候选 / "运行.py").write_text("print('ok')\n", encoding="utf-8")
        摘要16 = 计算目录摘要16(候选)
        正式候选 = self.根 / f"平台客户端-{摘要16}"
        候选.rename(正式候选)
        接入 = 平台客户端制品接入(
            状态目录=self.状态目录, 制品根目录=self.制品根,
            客户端制品目录=self.根 / "客户端制品", 环境目录=self.环境目录,
            信任目录=self.信任目录,
        )
        self.接入列表.append(接入)
        私钥, 公钥 = 接入.生成或读取密钥(self.根 / "密钥")
        成功, 消息, 摘要 = 接入.入库(
            制品目录=正式候选,
            构建输入={"来源": "第一批维修测试", "来源工作区指纹": 来源指纹},
            私钥PEM=私钥, 公钥PEM=公钥,
        )
        self.assertTrue(成功, 消息)
        return 摘要

    def _切换(self, **覆盖):
        参数 = {
            "环境目录参数": self.环境目录,
            "提交": 提交,
            "证据目录参数": self.证据目录,
            "制品根目录参数": self.制品根,
            "状态目录参数": self.状态目录,
            "信任目录参数": self.信任目录,
            "来源指纹": 来源指纹,
            "工作区指纹": self.工作区指纹,
        }
        参数.update(覆盖)
        return 发布治理.切换激活指针(self.制品摘要, 2, **参数)

    def test_摘要格式与制品存在必须先校验(self) -> None:
        坏摘要 = 发布治理.切换激活指针(
            "不是摘要", 2, 环境目录参数=self.环境目录,
            提交=提交, 证据目录参数=self.证据目录)
        self.assertFalse(坏摘要.成功)
        不存在 = 发布治理.切换激活指针(
            "f" * 32, 2, 环境目录参数=self.环境目录,
            提交=提交, 证据目录参数=self.证据目录,
            制品根目录参数=self.制品根)
        self.assertFalse(不存在.成功)
        self.assertEqual(json.loads((self.环境目录 / "当前.json").read_text(encoding="utf-8")), self.旧指针)

    def test_缺物料清单或签名信任失败均不得切换(self) -> None:
        清单 = self.制品根 / self.制品摘要 / "物料清单.json"
        备份 = 清单.read_bytes()
        清单.unlink()
        缺清单 = self._切换()
        self.assertFalse(缺清单.成功)
        清单.write_bytes(备份)
        (self.制品根 / self.制品摘要 / "运行.py").write_text("tampered\n", encoding="utf-8")
        篡改 = self._切换()
        self.assertFalse(篡改.成功)
        self.assertIn("签名", 篡改.消息)
        self.assertEqual(json.loads((self.环境目录 / "当前.json").read_text(encoding="utf-8")), self.旧指针)

    def test_缺正式发布证据或来源指纹不符不得切换(self) -> None:
        无证据目录 = self.根 / "无证据"
        无证据 = self._切换(证据目录参数=无证据目录)
        self.assertFalse(无证据.成功)
        来源不符 = self._切换(来源指纹="d" * 64)
        self.assertFalse(来源不符.成功)
        self.assertEqual(json.loads((self.环境目录 / "当前.json").read_text(encoding="utf-8")), self.旧指针)

    def test_激活证据写入失败绝不切换(self) -> None:
        不可写路径 = self.根 / "证据文件位置却是目录"
        不可写路径.mkdir()
        失败 = self._切换(激活证据路径参数=不可写路径)
        self.assertFalse(失败.成功)
        self.assertEqual(失败.错误码, "证据写入失败")
        self.assertEqual(json.loads((self.环境目录 / "当前.json").read_text(encoding="utf-8")), self.旧指针)

    def test_全部前置条件成立才切换(self) -> None:
        成功 = self._切换()
        self.assertTrue(成功.成功, 成功)
        新指针 = json.loads((self.环境目录 / "当前.json").read_text(encoding="utf-8"))
        self.assertEqual(新指针["制品摘要"], self.制品摘要)
        self.assertEqual(new_token := 新指针["栅栏令牌"], 3)
        self.assertEqual(new_token, 新指针["版本"])


if __name__ == "__main__":
    unittest.main()
