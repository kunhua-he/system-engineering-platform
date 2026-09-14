"""工作包三：平台客户端制品接入正式包仓库体系（入库/签名/信任/安装/激活/校验）。

覆盖：入库成功（摘要/签名/信任元数据齐全）、重复安装幂等、篡改拒绝、
半成品拒绝、陈旧指针拒绝、激活指针 CAS（旧令牌切换失败）、V3 稳定路径可读，
以及反向破坏真实失败（篡改后安装/校验/稳定路径必须拒绝，非恒真）。

全部调用生产实现（平台控制面/包仓库/平台客户端制品.py + 包仓库 +
发布管理 + 可信仓库元数据）；测试使用独立临时包仓库目录，不污染真实
工程缓存/制品仓库 激活指针。
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

from 客户端.构建平台客户端 import 计算制品摘要
from 平台控制面.包仓库.平台客户端制品 import 平台客户端制品接入, 计算目录摘要16

默认内容表 = {
    "平台客户端/__init__.py": '"""平台客户端入口"""\nX = 1\n',
    "平台客户端/公共契约/说明.json": '{"客户端": "平台客户端", "版本": "1"}\n',
}


def 构造制品(根: Path, *, 内容表: dict[str, str] | None = None) -> Path:
    """按生产摘要算法构造 平台客户端-<摘要16> 制品目录并返回其路径。"""
    内容表 = 内容表 or dict(默认内容表)
    构建 = 根 / "构建" / "平台客户端"
    for 相对, 内容 in 内容表.items():
        目标 = 构建 / 相对
        目标.parent.mkdir(parents=True, exist_ok=True)
        目标.write_text(内容, encoding="utf-8")
    摘要 = 计算制品摘要(构建)
    制品名 = f"平台客户端-{摘要[:16]}"
    制品目录 = 根 / "制品仓库" / "平台客户端制品" / 制品名
    制品目录.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(构建, 制品目录)
    (制品目录 / "制品摘要.json").write_text(
        json.dumps({"客户端": "平台客户端", "摘要sha256": 摘要}, ensure_ascii=False),
        encoding="utf-8")
    return 制品目录


class 测试基类(unittest.TestCase):
    """独立临时包仓库；入库/安装的真实生产链路。"""

    def setUp(self) -> None:
        self.根 = Path(tempfile.mkdtemp(prefix="平台客户端制品测试_"))
        self.接入 = 平台客户端制品接入(
            状态目录=self.根 / "状态",
            制品根目录=self.根 / "制品仓库",
            客户端制品目录=self.根 / "制品仓库" / "平台客户端制品",
            环境目录=self.根 / "制品仓库" / "平台客户端环境",
            信任目录=self.根 / "制品仓库" / "平台客户端信任")
        self.私钥, self.公钥 = 平台客户端制品接入.生成或读取密钥(self.根 / "密钥")
        self.制品目录 = 构造制品(self.根)
        self.制品名 = self.制品目录.name

    def tearDown(self) -> None:
        shutil.rmtree(self.根, ignore_errors=True)

    def 入库(self) -> str:
        成功, 消息, 摘要 = self.接入.入库(
            制品目录=self.制品目录, 私钥PEM=self.私钥, 公钥PEM=self.公钥)
        self.assertTrue(成功, 消息)
        return 摘要

    def 安装(self, 摘要: str) -> Path:
        成功, 消息, 目标 = self.接入.安装到环境(摘要)
        self.assertTrue(成功, 消息)
        self.assertIsNotNone(目标)
        return 目标


class Test入库与信任元数据(测试基类):
    """入库成功：内容寻址 + 物料清单 + 签名 + 根信任/目标/快照齐全。"""

    def test_入库成功摘要签名信任元数据齐全(self):
        摘要 = self.入库()
        # 制品摘要（32 位）登记到包仓库内容寻址目录
        制品目录 = self.根 / "制品仓库" / 摘要
        self.assertTrue(制品目录.is_dir(), "制品必须登记到包仓库内容寻址目录")
        self.assertTrue((制品目录 / "物料清单.json").is_file(), "必须生成物料清单(SBOM)")
        清单 = json.loads((制品目录 / "物料清单.json").read_text(encoding="utf-8"))
        self.assertEqual(清单["包id"], "平台客户端")
        self.assertTrue(清单["文件清单"], "物料清单必须含文件清单")
        for 相对, 摘要信息 in 清单["文件清单"].items():
            self.assertTrue((制品目录 / 相对).is_file(), f"清单文件缺失: {相对}")
        # 签名：制品记录已签名且校验通过
        记录 = self.接入.状态.读取记录("制品", "制品摘要", 摘要)
        self.assertEqual(记录["签名者"], "客户端构建发布者")
        self.assertEqual(记录["状态"], "已签名")
        有效, 消息 = self.接入.校验制品(摘要)
        self.assertTrue(有效, f"签名+磁盘校验必须通过: {消息}")
        # 信任元数据：根信任/目标/快照
        元数据目录 = self.根 / "制品仓库" / "平台客户端信任" / "元数据"
        self.assertTrue((元数据目录 / "根信任.json").is_file())
        self.assertTrue((元数据目录 / f"目标_平台客户端_{self.制品名[-16:]}.json").is_file())
        快照表 = sorted(元数据目录.glob("快照_*.json"))
        self.assertTrue(快照表, "必须生成仓库快照")
        快照 = json.loads(快照表[-1].read_text(encoding="utf-8"))
        self.assertEqual(快照["目标表"].get(f"平台客户端@{self.制品名[-16:]}"), 摘要)

    def test_重复入库同摘要幂等不重复复制(self):
        摘要 = self.入库()
        成功, 消息, 摘要2 = self.接入.入库(
            制品目录=self.制品目录, 私钥PEM=self.私钥, 公钥PEM=self.公钥)
        self.assertTrue(成功, f"重复入库必须幂等成功: {消息}")
        self.assertEqual(摘要, 摘要2)
        记录数 = len(self.接入.状态.查询记录("制品", "包id=?", ("平台客户端",)))
        self.assertEqual(记录数, 1, "重复入库不得产生重复记录")
        制品目录 = self.根 / "制品仓库" / 摘要
        文件数 = len([文件 for 文件 in 制品目录.rglob("*") if 文件.is_file()])
        self.assertEqual(文件数, 4, "内容寻址目录不得被重复复制产生多余文件")


class Test安装与幂等(测试基类):
    """原子安装 + 发布管理激活 + 重复安装幂等。"""

    def test_安装成功并激活指针(self):
        摘要 = self.入库()
        目标 = self.安装(摘要)
        环境指针 = json.loads((self.根 / "制品仓库" / "平台客户端环境" / "当前.json").read_text(encoding="utf-8"))
        self.assertEqual(环境指针["摘要sha256"], self.制品名[-16:])
        self.assertEqual(环境指针["制品目录"], self.制品名)
        self.assertEqual(环境指针["制品摘要"], 摘要)
        self.assertEqual(环境指针["版本"], 1)
        self.assertEqual(环境指针["栅栏令牌"], 1)
        激活 = self.接入.发布.当前激活("平台客户端")
        self.assertEqual(激活["目标"], 摘要)
        self.assertEqual(激活["版本"], 1)
        self.assertTrue((目标 / "平台客户端" / "__init__.py").is_file())

    def test_重复安装同摘要幂等不重复复制(self):
        摘要 = self.入库()
        目标 = self.安装(摘要)
        目标文件数 = len([文件 for 文件 in (目标 / "平台客户端").rglob("*") if 文件.is_file()])
        成功, 消息, _ = self.接入.安装到环境(摘要)
        self.assertTrue(成功, f"重复安装必须幂等成功: {消息}")
        self.assertIn("幂等", 消息)
        再次文件数 = len([文件 for 文件 in (目标 / "平台客户端").rglob("*") if 文件.is_file()])
        self.assertEqual(再次文件数, 目标文件数, "幂等安装不得重复复制")
        指针 = self.接入.发布.当前激活("平台客户端")
        self.assertEqual(指针["版本"], 1, "幂等安装不得推进激活版本")

    def test_新制品安装推进版本且激活指针CAS生效(self):
        摘要1 = self.入库()
        self.安装(摘要1)
        # 新内容 → 新摘要 → 新版本入库安装
        制品2 = 构造制品(self.根, 内容表={
            "平台客户端/__init__.py": '"""平台客户端入口"""\nX = 2\n',
            "平台客户端/公共契约/说明.json": '{"客户端": "平台客户端", "版本": "2"}\n'})
        成功, _, 摘要2 = self.接入.入库(
            制品目录=制品2, 私钥PEM=self.私钥, 公钥PEM=self.公钥)
        self.assertTrue(成功)
        self.assertNotEqual(摘要1, 摘要2)
        目标 = self.安装(摘要2)
        self.assertTrue((目标 / "平台客户端" / "__init__.py").read_text(encoding="utf-8").find("X = 2") >= 0)
        指针 = self.接入.发布.当前激活("平台客户端")
        self.assertEqual(指针["目标"], 摘要2, "激活指针必须切到新制品")
        self.assertEqual(指针["版本"], 2)
        # 陈旧监督器用旧令牌（版本1令牌1）切换 → CAS 拒绝
        成功旧, 消息旧 = self.接入.发布.切换激活指针(
            指针id="平台客户端", 目标="伪造目标", 期望版本=1, 期望令牌=1)
        self.assertFalse(成功旧, "旧令牌切换必须被拒")
        self.assertIn("陈旧", 消息旧)
        指针 = self.接入.发布.当前激活("平台客户端")
        self.assertEqual(指针["目标"], 摘要2, "陈旧监督器不得覆盖激活指针")


class Test拒绝路径(测试基类):
    """篡改拒绝 / 半成品拒绝 / 未入库拒绝 / 陈旧指针拒绝（反向破坏真实失败）。"""

    def test_篡改制品文件后安装被拒且校验失败(self):
        摘要 = self.入库()
        有效, _ = self.接入.校验制品(摘要)
        self.assertTrue(有效, "未篡改时校验必须成功（反向：非恒真前提）")
        # 篡改包仓库制品目录内正式文件
        制品目录 = self.根 / "制品仓库" / 摘要
        (制品目录 / "平台客户端" / "__init__.py").write_text("X = 999\n", encoding="utf-8")
        有效2, 消息2 = self.接入.校验制品(摘要)
        self.assertFalse(有效2, "篡改后签名校验必须失败")
        self.assertTrue(("篡改" in 消息2) or ("不符" in 消息2), 消息2)
        成功, 消息3, _ = self.接入.安装到环境(摘要)
        self.assertFalse(成功, "篡改后安装必须被拒")
        self.assertTrue(("篡改" in 消息3) or ("不符" in 消息3) or ("被拒" in 消息3), 消息3)

    def test_半成品缺文件拒绝安装(self):
        摘要 = self.入库()
        # 删除制品目录一个正式文件（摘要缺失/文件缺失 → 半成品）
        (self.根 / "制品仓库" / 摘要 / "平台客户端" / "公共契约" / "说明.json").unlink()
        成功, 消息, _ = self.接入.安装到环境(摘要)
        self.assertFalse(成功, "缺文件的半成品制品必须拒绝安装")
        self.assertTrue(("缺失" in 消息) or ("篡改" in 消息) or ("被拒" in 消息), 消息)

    def test_缺少物料清单的半成品拒绝安装(self):
        摘要 = self.入库()
        (self.根 / "制品仓库" / 摘要 / "物料清单.json").unlink()
        成功, 消息, _ = self.接入.安装到环境(摘要)
        self.assertFalse(成功, "缺少物料清单的半成品必须拒绝安装")
        self.assertIn("物料清单", 消息)

    def test_未入库摘要拒绝安装(self):
        成功, 消息, _ = self.接入.安装到环境("0" * 32)
        self.assertFalse(成功, "未入库（摘要缺失）必须拒绝安装")
        self.assertIn("未入库", 消息)

    def test_陈旧指针指向不存在制品拒绝(self):
        摘要 = self.入库()
        self.安装(摘要)
        指针文件 = self.根 / "制品仓库" / "平台客户端环境" / "当前.json"
        数据 = json.loads(指针文件.read_text(encoding="utf-8"))
        数据["制品目录"] = "平台客户端-0000000000000000"
        指针文件.write_text(json.dumps(数据), encoding="utf-8")
        成功, 消息, _ = self.接入.校验稳定路径()
        self.assertFalse(成功, "陈旧指针（制品不存在）必须拒绝")
        self.assertIn("陈旧", 消息)
        # 陈旧指针存在时新安装也被拒（可诊断）
        成功2, 消息2, _ = self.接入.安装到环境(摘要)
        self.assertFalse(成功2)
        self.assertIn("陈旧", 消息2)

    def test_陈旧指针指向摘要不符制品拒绝(self):
        摘要 = self.入库()
        self.安装(摘要)
        指向目录 = self.根 / "制品仓库" / "平台客户端制品" / self.制品名
        (指向目录 / "平台客户端" / "__init__.py").write_text("X = 777\n", encoding="utf-8")
        成功, 消息, _ = self.接入.校验稳定路径()
        self.assertFalse(成功, "陈旧指针（制品摘要不符）必须拒绝")
        self.assertIn("陈旧", 消息)

    def test_反向破坏非恒真(self):
        """篡改/半成品/陈旧指针全部真实失败：若实现恒真，成功断言也会失败。"""
        摘要 = self.入库()
        self.安装(摘要)
        # 场景一：篡改包仓库制品 → 安装必须失败
        制品目录 = self.根 / "制品仓库" / 摘要
        (制品目录 / "平台客户端" / "__init__.py").write_text("X = 888\n", encoding="utf-8")
        self.assertFalse(self.接入.安装到环境(摘要)[0], "篡改后安装失败必须真实成立")
        # 场景二：删除已安装目录文件 → 稳定路径必须拒绝
        环境副本 = self.根 / "制品仓库" / "平台客户端环境" / "平台客户端"
        (环境副本 / "平台客户端" / "__init__.py").write_text("X = 666\n", encoding="utf-8")
        成功, 消息, _ = self.接入.校验稳定路径()
        self.assertFalse(成功, "已安装目录被改后稳定路径必须拒绝")
        self.assertIn("不符", 消息)


class TestV3稳定路径(测试基类):
    """V3 只能通过已安装稳定路径读取（模拟引导读取）。"""

    def test_V3稳定路径可读(self):
        摘要 = self.入库()
        目标 = self.安装(摘要)
        成功, 消息, 路径 = self.接入.校验稳定路径()
        self.assertTrue(成功, f"稳定路径必须可读: {消息}")
        self.assertEqual(路径, 目标)
        # 模拟 V3 引导读取：读 当前.json → 绑定 环境目录/平台客户端
        指针 = json.loads((self.根 / "制品仓库" / "平台客户端环境" / "当前.json").read_text(encoding="utf-8"))
        self.assertEqual(指针["摘要sha256"], 计算目录摘要16(目标))
        入口 = 目标 / "平台客户端" / "__init__.py"
        self.assertTrue(入口.is_file(), "V3 入口模块必须存在")
        内容 = 入口.read_text(encoding="utf-8")
        self.assertIn("平台客户端", 内容, "已安装制品必须是重写前缀后的客户端内容")
        # 稳定路径摘要 == 指针摘要（引导按摘要校验后读取）
        self.assertEqual(计算目录摘要16(目标), 指针["摘要sha256"])

    def test_未安装时稳定路径拒绝(self):
        成功, 消息, _ = self.接入.校验稳定路径()
        self.assertFalse(成功)
        self.assertIn("当前.json", 消息)


if __name__ == "__main__":
    unittest.main()
