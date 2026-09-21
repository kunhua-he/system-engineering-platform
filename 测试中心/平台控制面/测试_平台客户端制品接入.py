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
from 平台控制面.包仓库 import 入库客户端制品
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


class Test能力面PEM逐字透传(测试基类):
    """#190 根因回归：能力包装层**不得改写**调用方给的 PEM。

    实测根因（2026-09-21，开工-20260921-200709-0425）：`平台控制面/包仓库/实现/能力入口.py`
    的 `入库客户端制品` 曾用 `_文本()` 归一 PEM，而 `_文本` 自述是「目录/摘要类参数归一」，
    会 `.strip()` ⇒ 公钥被 strip 成 112 字节，而信任记录里存的是**带尾部换行**的 113 字节
    （`生成或读取密钥` 从 `发布者公钥.pem` 原样读出）⇒ `平台客户端制品.py` 的
    `elif 信任记录["公钥"] != 公钥PEM` 必然成立，每次入库都报
    「发布者公钥与既有信任记录不一致」——而磁盘上两侧**逐字相同**。
    本组用例锁的就是「PEM 走能力面时逐字不变」。
    """

    def 能力面入库(self, *, 公钥PEM: str):
        return 入库客户端制品(
            制品目录=str(self.制品目录),
            构建输入={"来源": "测试-PEM逐字透传"},
            私钥PEM=self.私钥, 公钥PEM=公钥PEM,
            状态目录=str(self.根 / "状态"),
            制品根目录=str(self.根 / "制品仓库"),
            环境目录=str(self.根 / "制品仓库" / "平台客户端环境"),
            信任目录=str(self.根 / "制品仓库" / "平台客户端信任"),
        )

    def test_能力面登记的公钥与传入逐字一致(self):
        self.assertNotEqual(self.公钥, self.公钥.strip(),
                            "夹具前提：密钥文件的 PEM 必须带尾部换行，否则本用例失去意义")
        结果 = self.能力面入库(公钥PEM=self.公钥)
        self.assertTrue(结果.成功, f"PEM 逐字透传时必须入库成功: {结果.错误说明}")
        记录 = self.接入.状态.读取记录("信任", "发布者", "客户端构建发布者")
        self.assertIsNotNone(记录, "入库必须登记发布者信任记录")
        self.assertEqual(记录["公钥"], self.公钥,
                         "PEM 必须逐字透传（含尾部换行），能力包装层不得 strip")

    def test_反向验证_文本归一会strip而PEM归一不会(self):
        """反向样本（故意弄坏）：证明两个归一函数对真实 PEM 确实不同，判据不是死的。

        `_文本` 会 strip —— 这正是原缺陷的来源；`_PEM文本` 必须逐字保留。
        若哪天有人把 `_PEM文本` 改回 `_文本`，上面那条用例与本条同时变红。
        """
        from 平台控制面.包仓库.实现.能力入口 import _PEM文本, _文本

        self.assertEqual(_文本(" x \n"), "x", "`_文本` 会 strip（原缺陷来源）")
        self.assertEqual(_PEM文本(" x \n"), " x \n", "`_PEM文本` 必须逐字保留")
        self.assertNotEqual(_文本(self.公钥), _PEM文本(self.公钥),
                            "对带尾部换行的真实 PEM，两者必须不同；相同则说明判据是死的")
        self.assertEqual(_PEM文本(self.公钥), self.公钥, "PEM 归一必须是恒等")


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

    def test_源制品目录缺失时按已安装副本判定可继续(self):
        """D-17 ①（2026-09-16 改判）：源制品目录单边缺失/被写脏，不再永久拒绝安装。

        外部调用方真正读的是已安装副本（`环境目录/平台客户端`），它才是指针许诺的落点；
        源目录只是二次构建的中间产物。原判据只认源目录，源一坏就永久卡死（实测踩坑）。
        反向（同用例内）：**源与已安装都不符**时仍必须拒绝，且错误说明要给出修复出口。
        """
        摘要 = self.入库()
        self.安装(摘要)
        指针文件 = self.根 / "制品仓库" / "平台客户端环境" / "当前.json"
        数据 = json.loads(指针文件.read_text(encoding="utf-8"))
        数据["制品目录"] = "平台客户端-0000000000000000"
        指针文件.write_text(json.dumps(数据), encoding="utf-8")
        # 单边（源不存在，已安装副本完好）：可继续，安装重建源制品目录后成功
        诊断 = self.接入.诊断激活指针()
        self.assertTrue(诊断["可继续"], f"单边不符不该拒绝安装: {诊断}")
        self.assertTrue(诊断["已安装符合"], "已安装副本应与指针一致")
        self.assertFalse(诊断["源符合"], "源制品目录确实对不上（前提）")
        成功2, 消息2, _ = self.接入.安装到环境(摘要)
        self.assertTrue(成功2, f"单边不符时必须可继续安装: {消息2}")
        # 双边都不符：源目录与已安装副本都改脏 → 真陈旧 → 拒绝，且必须给可执行的修复出口
        源目录 = self.根 / "制品仓库" / "平台客户端制品" / self.制品名
        (源目录 / "平台客户端" / "__init__.py").write_text("X = 555\n", encoding="utf-8")
        环境副本 = self.根 / "制品仓库" / "平台客户端环境" / "平台客户端"
        (环境副本 / "平台客户端" / "__init__.py").write_text("X = 555\n", encoding="utf-8")
        诊断双边 = self.接入.诊断激活指针()
        self.assertTrue(诊断双边["陈旧"], f"双边都不符必须判陈旧: {诊断双边}")
        self.assertEqual(诊断双边["陈旧级别"], "源与已安装摘要均不符")
        成功3, 消息3, _ = self.接入.安装到环境(摘要)
        self.assertFalse(成功3, "源与已安装都不符时必须拒绝安装")
        self.assertIn("修复出口", 消息3, "拒绝必须可诊断（带修复出口），不能只有「永久拒绝」")

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


class Test陈旧指针可诊断可修复(测试基类):
    """D-17 ①：陈旧激活指针必须**可诊断 + 可修复**（修复出口：重建 / 重置）。

    每个用例都带反向断言：出口若写成恒真（不做校验就宣布修好），反向断言必须失败。
    """

    def 制造真陈旧(self, 摘要: str) -> None:
        """把指针摘要改成合法但不匹配的值，同时把已安装副本改脏 → 双边都不符。"""
        self.安装(摘要)
        指针文件 = self.根 / "制品仓库" / "平台客户端环境" / "当前.json"
        数据 = json.loads(指针文件.read_text(encoding="utf-8"))
        数据["摘要sha256"] = "0" * 16
        指针文件.write_text(json.dumps(数据), encoding="utf-8")
        环境副本 = self.根 / "制品仓库" / "平台客户端环境" / "平台客户端"
        (环境副本 / "平台客户端" / "__init__.py").write_text("X = 444\n", encoding="utf-8")

    def test_重置激活指针清回未安装态并可重装(self):
        """重置出口：清掉指针 → 稳定路径明确报「缺少激活指针」→ 重新安装成功。"""
        摘要 = self.入库()
        self.制造真陈旧(摘要)
        成功, 消息 = self.接入.重置激活指针()
        self.assertTrue(成功, 消息)
        self.assertIn("已备份", 消息)
        指针文件 = self.根 / "制品仓库" / "平台客户端环境" / "当前.json"
        self.assertFalse(指针文件.is_file(), "重置后 当前.json 必须不再存在（回到未安装态）")
        备份 = list((self.根 / "制品仓库" / "平台客户端环境").glob("当前.json.陈旧指针备份_*"))
        self.assertTrue(备份, "重置必须留备份留痕，不许直接把指针删掉")
        self.assertIsNone(self.接入.检查激活指针(), "重置后不该再报陈旧")
        可读, 校验消息, _ = self.接入.校验稳定路径()
        self.assertFalse(可读, "已安装副本仍被改脏时稳定路径仍须拒绝读取")
        self.assertIn("缺少激活指针", 校验消息)
        # 重装：走首次安装分支，覆盖恢复
        成功2, 消息2, _ = self.接入.安装到环境(摘要)
        self.assertTrue(成功2, f"重置后必须能重新安装: {消息2}")

    def test_重建激活指针按已安装副本恢复且指针真的变了(self):
        """重建出口：按已安装副本重算摘要写回指针 → 稳定路径恢复可读。

        反向：若重建不做校验、写回的还是旧值，`摘要sha256` 不会变、稳定路径也不会转绿。
        """
        摘要 = self.入库()
        self.安装(摘要)
        指针文件 = self.根 / "制品仓库" / "平台客户端环境" / "当前.json"
        数据 = json.loads(指针文件.read_text(encoding="utf-8"))
        数据["摘要sha256"] = "0" * 16           # 只把指针改错，已安装副本自始至终完好
        指针文件.write_text(json.dumps(数据), encoding="utf-8")
        self.assertIsNotNone(self.接入.检查激活指针(), "前提：指针确实陈旧")
        成功, 消息 = self.接入.重建激活指针()
        self.assertTrue(成功, 消息)
        self.assertIn("已按已安装副本重建", 消息)
        新指针 = json.loads(指针文件.read_text(encoding="utf-8"))
        self.assertNotEqual(新指针["摘要sha256"], "0" * 16, "重建必须真的改掉错误摘要")
        self.assertEqual(新指针["摘要sha256"], self.制品名[-16:])
        self.assertIsNone(self.接入.检查激活指针(), "重建后必须不再报陈旧")
        可读, 校验消息, 目标 = self.接入.校验稳定路径()
        self.assertTrue(可读, f"重建后稳定路径必须可读: {校验消息}")
        self.assertIsNotNone(目标)

    def test_重建拒绝半安装态(self):
        """反向：已安装副本不存在（半安装态）时重建必须拒绝，不许凭空造指针。"""
        摘要 = self.入库()
        self.安装(摘要)
        环境副本 = self.根 / "制品仓库" / "平台客户端环境" / "平台客户端"
        shutil.rmtree(环境副本)
        成功, 消息 = self.接入.重建激活指针()
        self.assertFalse(成功, "已安装副本不存在时重建必须拒绝")
        self.assertIn("已安装副本不存在", 消息)

    def test_运行时数据不进制品身份而内容改动仍检出(self):
        """D-17 ②：运行时数据（`工程缓存` 段）不参与制品身份；正式内容改动必须仍被检出。

        反向：把 `_是运行时数据` 写成「排除一切 .db/.log」（连夹具一起排）或干脆不排，
        本用例的两条断言必有一条失败——前者会让夹具变化检不出，后者会让写脏判陈旧。
        """
        摘要 = self.入库()
        self.安装(摘要)
        源目录 = self.根 / "制品仓库" / "平台客户端制品" / self.制品名
        基线源 = 计算目录摘要16(源目录)
        基线装 = 计算目录摘要16(self.根 / "制品仓库" / "平台客户端环境" / "平台客户端")
        # 现场两种写脏形态都造出来
        (源目录 / "工程缓存" / "平台控制面").mkdir(parents=True, exist_ok=True)
        (源目录 / "工程缓存" / "平台控制面" / "权威状态.db").write_bytes(b"\x00runtime")
        (源目录 / "平台客户端" / "工程缓存" / "模型日志").mkdir(parents=True, exist_ok=True)
        (源目录 / "平台客户端" / "工程缓存" / "模型日志" / "验证模型.log").write_text("x\n", encoding="utf-8")
        self.assertEqual(计算目录摘要16(源目录), 基线源, "运行时数据不得改变制品身份摘要")
        self.assertEqual(self.接入.检查激活指针(), None, "运行时数据写脏不得判陈旧")
        self.assertIsNone(self.接入.检查激活指针())
        可读, 校验消息, _ = self.接入.校验稳定路径()
        self.assertTrue(可读, f"运行时数据写脏后稳定路径必须仍可读: {校验消息}")
        # 反向：正式内容改动必须仍被检出——只脏源时是「单边」（按已安装副本判定，可继续修复），
        # 与运行时数据写脏的表现**必须不同**（前者改变身份摘要，后者不改变）。
        (源目录 / "平台客户端" / "__init__.py").write_text("X = 333\n", encoding="utf-8")
        self.assertNotEqual(计算目录摘要16(源目录), 基线源, "正式文件改动必须改变摘要")
        安装副本 = self.根 / "制品仓库" / "平台客户端环境" / "平台客户端"
        self.assertEqual(计算目录摘要16(安装副本), 基线装, "已安装副本未被改动（前提）")
        单边 = self.接入.诊断激活指针()
        self.assertTrue(单边["可继续"])
        self.assertEqual(单边["陈旧级别"], "源目录被写脏（已安装副本正常）",
                         "边写脏必须与运行时数据写脏区分开：前者是真内容改动")
        # 双边都脏 → 真陈旧，必须拒绝
        (安装副本 / "平台客户端" / "__init__.py").write_text("X = 333\n", encoding="utf-8")
        self.assertTrue(self.接入.诊断激活指针()["陈旧"])
        self.assertIsNotNone(self.接入.检查激活指针())


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


class Test制品根指针目标纳入回收保留(测试基类):
    """#214：回收的保留判据必须同时保护「最新制品」指针（制品根 `当前.json`）的目标。

    现场（2026-09-21 实测）：连续三次 `构建平台客户端制品(安装=真)` 都打印「构建完成」，
    随后 `平台客户端制品/` 只剩那份 2026-09-19 的已安装件，而 `平台客户端制品/当前.json`
    指向一个**已不存在**的目录 —— 悬空指针。根因：回收的保留判据只读**环境激活指针**
    （「当前装着谁」），而构建链写的是**制品根指针**（「最近构建出来的是谁」）——
    两份指针是两件事，但都是活引用，后者的目标原先无人保护。
    修法：保留集取两份指针目标的并集（唯一装配点 `环境回收面._保留判据`）。
    """

    def _制品根(self) -> Path:
        return self.根 / "制品仓库" / "平台客户端制品"

    def _制品根指针文件(self) -> Path:
        return self._制品根() / "当前.json"

    def _写制品根指针(self, 制品目录: Path, 内容寻址摘要: str = "") -> None:
        """按唯一 schema 写制品根指针（模拟构建脚本 `客户端/构建平台客户端.py` 那一笔）。

        **两种写法都按现场真值**（实测 `工程缓存/制品仓库/平台客户端制品/当前.json`）：
        构建脚本写的是 `{摘要sha256: <16 位身份摘要>, 制品目录: 平台客户端-<16>, 制品摘要: ""}`
        —— `制品摘要` 字段**是空的**；只有环境激活指针才写 32 位内容寻址摘要
        （`{摘要sha256: <16>, 制品摘要: <32>}`）。两个字段是**两种不同的摘要**
        （16 位身份摘要 ≠ 32 位内容寻址摘要的前 16 位），不能互相推。
        """
        from 平台控制面.包仓库.激活指针 import 写激活指针
        身份摘要 = 计算制品摘要(制品目录)
        self.assertEqual(制品目录.name, f"平台客户端-{身份摘要}",
                         "夹具前提：身份目录名后缀就是 计算制品摘要（16 位权威口径）")
        写激活指针(self._制品根指针文件(), {
            "摘要sha256": 身份摘要, "制品目录": 制品目录.name,
            "制品摘要": 内容寻址摘要, "版本": 0, "栅栏令牌": 0})

    def _造并入库(self, 标记: str) -> tuple[Path, str]:
        """造一份内容不同的新制品并入库（不安装）：返回 (制品目录, 32 位内容寻址摘要)。"""
        新制品 = 构造制品(self.根, 内容表={
            "平台客户端/__init__.py": f'"""平台客户端入口"""\nX = {标记}\n',
            "平台客户端/公共契约/说明.json": f'{{"客户端": "平台客户端", "版本": "{标记}"}}\n',
        })
        成功, 消息, 摘要 = self.接入.入库(
            制品目录=新制品, 私钥PEM=self.私钥, 公钥PEM=self.公钥)
        self.assertTrue(成功, f"第二份制品必须入库成功: {消息}")
        return 新制品, 摘要

    def test_制品根指针的身份目录不被回收(self):
        """正样本：制品根指针指向的身份目录（已入库、未安装）必须留在场。

        改前这一条必红：它既不是环境激活指针的当前件，也没进 `额外保留摘要表`
        （那是「本次正在操作的件」，只在入库/安装那一瞬间有效）。
        """
        摘要 = self.入库()
        self.安装(摘要)
        新制品, _ = self._造并入库("2")
        新身份 = self._制品根() / 新制品.name
        self.assertTrue(新身份.is_dir(), "夹具：新制品的身份目录必须在")
        self._写制品根指针(新制品)  # 现场写法：制品摘要 为空

        结果 = self.接入.回收过期制品(触发点="测试")
        self.assertTrue(新身份.is_dir(),
                        f"制品根指针指向的身份目录被回收了（#214 悬空指针）: {结果.摘要文本()}")

    def test_未入库的构建产物也受制品根指针保护(self):
        """#214 的现场形态：构建成功但**入库/安装失败**（产物没入库）。

        这种产物没有 `制品` 表记录 ⇒ 摘要→身份目录名 换算不出来，只能靠指针里的
        `制品目录` 字段直接保护。改前它必被回收（现场三次构建的产物就是这么没的）。
        本用例同时做反向：删掉指针 → 同一份产物必须立刻被回收。
        """
        摘要 = self.入库()
        self.安装(摘要)
        产物 = 构造制品(self.根, 内容表={
            "平台客户端/__init__.py": '"""平台客户端入口"""\nX = 3\n',
            "平台客户端/公共契约/说明.json": '{"客户端": "平台客户端", "版本": "3"}\n',
        })
        产物身份 = self._制品根() / 产物.name
        self.assertTrue(产物身份.is_dir(), "夹具：构建产物的身份目录必须在")
        self._写制品根指针(产物)

        self.接入.回收过期制品(触发点="测试")
        self.assertTrue(产物身份.is_dir(),
                        "未入库的构建产物被回收了 —— 这正是 #214 的悬空指针现场")

        self._制品根指针文件().unlink()  # ← 故意弄坏：没有指针保护
        self.接入.回收过期制品(触发点="测试")
        self.assertFalse(产物身份.is_dir(),
                         "没有指针保护时它必须被回收（否则本用例没证明判据承重）")

    def test_指针带内容寻址摘要时寻址目录也受保护(self):
        """指针的 `制品摘要` 填了 32 位内容寻址摘要时，内容寻址目录一并受保护。

        判据必须对**两种现场写法**都成立：构建脚本写的制品根指针 `制品摘要` 是空的
        （保护到身份目录），环境激活指针写的是 32 位内容寻址摘要（保护到寻址目录）。
        本用例把后者也钉住 —— 否则「把 32 位摘要喂进保留集」这一步没有证据。
        """
        摘要 = self.入库()
        self.安装(摘要)
        新制品, 新寻址摘要 = self._造并入库("4")
        self.assertEqual(len(新寻址摘要), 32, "内容寻址摘要必须是 32 位（制品保留.内容寻址名长度）")
        新寻址 = self.根 / "制品仓库" / 新寻址摘要
        self.assertTrue(新寻址.is_dir(), "夹具：新制品的内容寻址目录必须在")
        self._写制品根指针(新制品, 内容寻址摘要=新寻址摘要)

        结果 = self.接入.回收过期制品(触发点="测试")
        self.assertTrue(新寻址.is_dir(),
                        f"指针带 32 位摘要时内容寻址目录必须留存: {结果.摘要文本()}")


if __name__ == "__main__":
    unittest.main()
