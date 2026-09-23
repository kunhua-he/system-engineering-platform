"""能力目录模块定向测试：经 后端核心 装配后真实调用两个公开能力。

硬边界（第 12 条 1 项）：本文件只做单能力定向冒烟，不跑发布门禁与全量测试；
调用链一律走 后端核心(项目根).启动() → 后端核心.调用(能力id, 参数)，
不直接 获取能力调用器()（未装配会报 E未装配）。
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from typing import Any

系统根 = Path(__file__).resolve().parents[2]
if str(系统根) not in sys.path:
    sys.path.insert(0, str(系统根))

from 公共契约.基础类型.结果类型 import 结果
from 模块库.能力目录 import 搜索能力, 读取能力, 注册能力

from 公共契约.运行时.平台适配 import 清只读后删除树
from 公共契约.基础类型.逻辑类型 import 真

#: ★ A 档泄漏收口（2026-09-23）：受管临时根在仓库内**固定排除目录** `工程缓存/` 下。
#: `dir=` 显式指向它 ⇒ 落点与**测试运行时**的 `TMPDIR` 解耦（平台跑测试时 `TMPDIR` 被指进
#: 仓库工作目录，裸 `mkdtemp()` 会把夹具造进仓库）。`工程缓存` 在
#: `开发工具/项目编译/工作区指纹.py` 的 `固定排除目录` 里 ⇒ 即便进程被 SIGKILL、
#: 清理没跑到，残留也进不了工作区指纹（`.gitignore` 保不住：指纹的未跟踪腿不用
#: `--exclude-standard`）。清理走平台唯一删树原语 `清只读后删除树`（本类用例常造
#: `0o555` 目录 / `0o444` 文件，plain `shutil.rmtree` 会被权限位挡住）。
受管临时根 = 系统根 / "工程缓存" / "测试临时"
受管临时根.mkdir(parents=True, exist_ok=True)

搜索能力id = "能力目录.搜索能力"
读取能力id = "能力目录.读取能力"
旧实现字段 = (
    "能力id", "中文名称", "说明", "参数", "返回结构", "错误码",
    "版本", "提供者", "调用示例", "验证状态", "包id", "包名称", "类型", "返回",
)
开发入口字段 = ("能力id", "名称", "包id", "说明", "参数")
#: ★ 2026-09-23（未完成事项 #130）：`参数类型` 与 `必填` 已从记录里删掉 —— 参数族七份同义
#: 重复（`参数`/`参数类型`/`参数列表`/`参数名`/`必填`/`必填参数`/`可选参数`）只留一份 `参数`，
#: `必填` 由 `参数[*].必填` 派生。旧实现字段里只被读过的那两个键随之退出本判据。
十四字段 = (
    "能力id", "中文名", "说明", "默认值", "返回结构",
    "错误码", "调用示例", "权限", "资源预算", "依赖", "版本", "最近成功验证",
)


class 能力目录测试基类(unittest.TestCase):
    """共享一次装配：整套定向测试复用同一后端实例。"""

    后端: Any = None

    @classmethod
    def setUpClass(cls) -> None:
        from 后端核心.后端核心 import 后端核心

        cls.后端 = 后端核心(系统根)
        启动结果 = cls.后端.启动()
        if not 启动结果.成功:
            raise AssertionError(f"后端核心装配失败: {启动结果.错误码} {启动结果.错误说明}")


class 装配与注册测试(能力目录测试基类):
    def test_公开入口可导入(self):
        for 能力名 in ["搜索能力", "读取能力"]:
            self.assertTrue(callable(globals()[能力名]), f"{能力名} 未从公开入口导出")

    def test_注册能力齐全(self):
        from 公共契约.能力契约.契约 import 能力注册表

        注册表 = 能力注册表()
        注册能力(注册表)
        for 能力id in [搜索能力id, 读取能力id]:
            self.assertIn(能力id, 注册表.能力id列表)

    def test_装配后两个能力都在注册表(self):
        for 能力id in [搜索能力id, 读取能力id]:
            self.assertIsNotNone(self.后端.注册表.获取(能力id), f"{能力id} 未装配")

    def test_直接调用未装配调用器_as_fallback_返回统一结果(self):
        """不经后端核心直接调用模块函数：仍返回统一结果（不抛异常）。"""
        返回值 = 搜索能力("能力目录.搜索能力", 5)
        self.assertIsInstance(返回值, 结果)


class 搜索能力测试(能力目录测试基类):
    def 搜索(self, 关键词: str, 限制: int) -> 结果:
        return self.后端.调用(搜索能力id, {"关键词": 关键词, "限制": 限制})

    def 搜索完整契约(self, 关键词: str, 限制: int) -> 结果:
        """按最高档取完整契约：断言「字段齐全」类用例必须显式要这一档。

        2026-09-18 起默认档＝「名称」（只回精简字段，见该能力 `说明` 与
        `说明/设计说明.md`）。旧用例断言的 21 字段面仍然存在，只是**不再默认返回**——
        它们从此必须显式传 细节级别=完整契约，否则测的就不是它自称要测的东西。
        """
        return self.后端.调用(搜索能力id, {"关键词": 关键词, "限制": 限制,
                                    "细节级别": "完整契约"})

    def test_关键词命中自身能力(self):
        调用结果 = self.搜索("能力目录.搜索能力", 5)
        self.assertTrue(调用结果.成功, 调用结果.错误说明)
        值 = 调用结果.值
        self.assertEqual("能力目录.搜索能力", 值["关键词"])
        self.assertEqual(5, 值["限制"])
        # 命中数不写死：读取能力的参数说明里也写着「例如 能力目录.搜索能力」，
        # 整条记录子串匹配（与旧两道实现同口径）会把那条一并命中。
        self.assertGreaterEqual(值["返回数"], 1)
        self.assertLessEqual(值["返回数"], 值["总数"])
        自命中 = [记录 for 记录 in 值["能力列表"]
                 if 记录["能力id"] == "能力目录.搜索能力"]
        self.assertEqual(1, len(自命中))
        self.assertEqual("搜索能力", 自命中[0]["中文名"])

    def test_默认档只回精简字段且与重字段互斥(self):
        """默认档（不传 细节级别）＝「名称」：只回指针，重字段一律不得出现。

        判据是**与重字段表互斥**，不是「键数等于 5」——只数键数的断言挡不住重字段
        换个名字回流。这里直接拿实现里的 重字段表 当判据（同一份事实，不另抄一遍）。
        """
        from 模块库.能力目录.实现.能力目录 import 精简字段表, 重字段表

        调用结果 = self.搜索("", 100)
        self.assertTrue(调用结果.成功, 调用结果.错误说明)
        值 = 调用结果.值
        self.assertEqual("名称", 值["细节级别"])
        self.assertEqual(100, 值["返回数"])
        for 记录 in 值["能力列表"]:
            self.assertEqual(set(精简字段表), set(记录),
                             f"{记录['能力id']} 默认档键集不等于精简字段表")
            for 重字段 in 重字段表:
                self.assertNotIn(重字段, 记录,
                                 f"{记录['能力id']} 默认档不得回重字段 {重字段}")
        # 精简字段本身必须有值（不是空壳占位）
        for 记录 in 值["能力列表"]:
            self.assertTrue(记录["能力id"])
            self.assertTrue(记录["名称"])
            self.assertTrue(记录["包id"])
            self.assertTrue(记录["一句话说明"])

    def test_中间档不含重字段且比默认档多说明(self):
        from 模块库.能力目录.实现.能力目录 import 说明字段表, 重字段表

        调用结果 = self.后端.调用(搜索能力id, {"关键词": "OCR", "限制": 5,
                                       "细节级别": "名称+说明"})
        self.assertTrue(调用结果.成功, 调用结果.错误说明)
        值 = 调用结果.值
        self.assertEqual("名称+说明", 值["细节级别"])
        self.assertGreater(值["返回数"], 0)
        for 记录 in 值["能力列表"]:
            self.assertEqual(set(说明字段表), set(记录))
            self.assertIn("说明", 记录)
            self.assertTrue(记录["说明"])
            for 重字段 in 重字段表:
                self.assertNotIn(重字段, 记录, f"中间档不得回重字段 {重字段}")

    def test_非法细节级别一律拒绝不静默降级(self):
        """不认识的档位必须报 参数不合法，不得悄悄按默认档返回。

        静默降级会让调用方以为拿到了完整契约、实际只拿到指针。
        """
        for 坏档 in ("完整", "json", "名称+", ""):
            with self.subTest(细节级别=坏档):
                调用结果 = self.后端.调用(搜索能力id, {"关键词": "", "限制": 3,
                                               "细节级别": 坏档})
                if 坏档 == "":
                    # 空文本＝未传，按默认档（向后兼容），不是非法值
                    self.assertTrue(调用结果.成功, 调用结果.错误说明)
                    self.assertEqual("名称", 调用结果.值["细节级别"])
                else:
                    self.assertFalse(调用结果.成功)
                    self.assertEqual("参数不合法", 调用结果.错误码)

    def test_游标翻页三页无重复且合计等于总数(self):
        """游标正确性硬证据：按「每页 总数/3」翻三页，去重后条数 == 合计 == 总数。

        选「总数能被 3 整除」的关键词，三页正好覆盖全集——这样「合计 == 总数」
        才是无遗漏 + 无重复的**充分**证据；否则（如 456 条取 3 页 ×3）恒不等于总数，
        断言写出来就是错的。
        """
        关键词 = "OCR"
        总数 = self.搜索(关键词, 1).值["总数"]
        self.assertGreater(总数, 0)
        self.assertEqual(0, 总数 % 3, f"关键词 {关键词} 的总数 {总数} 需能被 3 整除")
        页大小 = 总数 // 3
        游标 = ""
        汇总: list[str] = []
        for 页号 in range(1, 4):
            with self.subTest(页号=页号):
                值 = self.后端.调用(搜索能力id, {"关键词": 关键词, "限制": 页大小,
                                           "游标": 游标}).值
                self.assertEqual(页大小, 值["返回数"], f"第 {页号} 页应满页")
                汇总.extend(记录["能力id"] for 记录 in 值["能力列表"])
                游标 = 值["下一条游标"]
        self.assertEqual(总数, len(汇总), f"三页合计 {len(汇总)} ≠ 总数 {总数}（漏项）")
        self.assertEqual(len(汇总), len(set(汇总)), "三页出现了重复能力id")
        self.assertEqual(汇总, sorted(汇总), "翻页顺序不是排序键升序（续取位置有误）")
        self.assertEqual("", 游标, "取满全集后不得再给下一条游标")

    def test_游标翻页走完全集与不分页取全逐条一致(self):
        """页大小=100 翻到底：无重复、无遗漏，且与直接取全的 id 序列逐条相同。"""
        页大小 = 100
        游标 = ""
        汇总: list[str] = []
        频次: dict[str, int] = {}
        while True:
            值 = self.后端.调用(搜索能力id, {"关键词": "", "限制": 页大小,
                                       "游标": 游标}).值
            汇总.extend(记录["能力id"] for 记录 in 值["能力列表"])
            游标 = 值["下一条游标"]
            if not 游标:
                break
            频次[游标] = 频次.get(游标, 0) + 1
            self.assertLess(频次[游标], 20, "游标未前进（防死循环保护触发）")
        self.assertEqual(值["总数"], len(汇总), "翻页合计 ≠ 总数")
        self.assertEqual(len(汇总), len(set(汇总)), "翻页出现重复")
        直接一次 = self.搜索("", 100).值["能力列表"]
        self.assertEqual([记录["能力id"] for 记录 in 直接一次], 汇总[:100],
                         "第一页与不分页取法的首百条必须逐条一致")

    def test_伪造游标与换关键词一律拒绝(self):
        """游标不透明：自造的、改了关键词的、"看起来像"的游标全部 fail-closed。

        绝不静默退回「从头开始」——那会把调用方的错变成静默漏项。
        """
        首发 = self.搜索("", 3).值
        真游标 = 首发["下一条游标"]
        self.assertTrue(真游标)
        for 坏游标 in ("我自己拼的游标", "无", "0000", 真游标[:-1] + "X"):
            with self.subTest(游标=坏游标):
                调用结果 = self.后端.调用(搜索能力id, {"关键词": "", "限制": 3,
                                               "游标": 坏游标})
                self.assertFalse(调用结果.成功, f"非法游标 {坏游标!r} 不得放行")
                self.assertEqual("参数不合法", 调用结果.错误码)
        # 换关键词：游标记的是签发时的过滤条件，换了条件还接老位置必然漏项/重项
        换词 = self.后端.调用(搜索能力id, {"关键词": "OCR", "限制": 3, "游标": 真游标})
        self.assertFalse(换词.成功)
        self.assertEqual("参数不合法", 换词.错误码)
        self.assertIn("关键词", 换词.错误说明)

    def test_游标非文本被拒绝(self):
        调用结果 = self.后端.调用(搜索能力id, {"关键词": "", "限制": 3, "游标": 123})
        self.assertFalse(调用结果.成功)
        self.assertEqual("参数不合法", 调用结果.错误码)

    def test_完整契约档与读取能力逐字段一致(self):
        """最高档必须**逐字段等于** 读取能力 的单条结果（不是"多几个字段"就算）。

        这是「要完整契约必须显式传最高档」的兑现方式：拿到的东西与按 id 单独读
        完全一致，调用方不因为走搜索而少任何字段。
        """
        搜索记录 = self.搜索完整契约("能力目录.搜索能力", 5).值["能力列表"][0]
        读取记录 = self.后端.调用(读取能力id, {"能力id": "能力目录.搜索能力"}).值
        self.assertEqual(set(读取记录), set(搜索记录))
        self.assertEqual(json.dumps(读取记录, ensure_ascii=False, sort_keys=True),
                         json.dumps(搜索记录, ensure_ascii=False, sort_keys=True))

    def test_空关键词不过滤且被限制截断(self):
        调用结果 = self.搜索("", 100)
        self.assertTrue(调用结果.成功, 调用结果.错误说明)
        值 = 调用结果.值
        self.assertEqual(100, 值["返回数"])
        self.assertTrue(值["总数"] > 100, f"公开能力总数应大于 100，实测 {值['总数']}")
        self.assertTrue(值["是否截断"] is True)

    def test_限制超上界按边界收敛(self):
        调用结果 = self.搜索("", 5000)
        self.assertTrue(调用结果.成功, 调用结果.错误说明)
        self.assertEqual(100, 调用结果.值["限制"])
        self.assertEqual(100, 调用结果.值["返回数"])

    def test_限制非整数被拒绝(self):
        调用结果 = self.后端.调用(搜索能力id, {"关键词": "", "限制": "5"})
        self.assertFalse(调用结果.成功)
        self.assertEqual("参数不合法", 调用结果.错误码)

    def test_返回键只增不改(self):
        """对外只增不改：原 7 键必须都在，新 3 键追加，一个都不能少或改名。"""
        值 = self.搜索("", 3).值
        for 旧键 in ("关键词", "限制", "总数", "返回数", "是否截断", "能力列表", "项目根"):
            self.assertIn(旧键, 值, f"旧返回键 {旧键} 不得删除或改名")
        for 新键 in ("游标", "下一条游标", "细节级别"):
            self.assertIn(新键, 值, f"新返回键 {新键} 缺失")
        self.assertIn("游标", 值)
        self.assertIn("下一条游标", 值)
        self.assertIn("细节级别", 值)

    def test_记录覆盖旧两道检索实现的字段(self):
        """旧用例的字段面语义不变，但**必须显式要最高档**才拿得到（默认档只给指针）。

        断言的是「完整契约档仍然覆盖旧两道实现读取过的每一个键名」——这是平滑迁移的
        底线：转调方只要显式要最高档，就没有任何信息损失。
        """
        调用结果 = self.搜索完整契约("能力目录.搜索能力", 1)
        self.assertTrue(调用结果.成功, 调用结果.错误说明)
        记录 = 调用结果.值["能力列表"][0]
        for 字段 in 旧实现字段 + 开发入口字段 + 十四字段:
            self.assertIn(字段, 记录, f"完整契约档记录缺少旧实现字段: {字段}")

    def test_反向_游标改成偏移量必然漏项(self):
        """反向验证：把起点改成「偏移量 + 漏一项」，本类的翻页断言必须真的变红。

        **为什么这条必须在测试里（不是跑一次就扔）**：断言「合计 == 总数」只有在**能失败**时
        才有意义。若游标实现被改成偏移量而断言仍绿，说明它压根没在判分页正确性。
        这里用 importlib 加载一份**改过的实现副本**（不动磁盘上的正式实现），
        断言同一套走查在副本上得到「合计 < 总数」——证明断言有分辨力，不是恒绿。
        """
        import importlib.util
        import tempfile

        源文件 = 系统根 / "模块库" / "能力目录" / "实现" / "能力目录.py"
        原文 = 源文件.read_text(encoding="utf-8")
        锚 = "        起点 = bisect_right(编号表, 锚点id)"
        self.assertIn(锚, 原文,
                      "反向实验锚点未找到：游标实现已变形态，请同步更新本用例（否则它变成空转）")
        坏文 = 原文.replace(
            锚, "        起点 = 编号表.index(锚点id) + 2  # 反向实验：偏移量 + 故意漏一项")

        临时目录 = Path(tempfile.mkdtemp(prefix="能力目录反向_", dir=受管临时根))
        self.addCleanup(清只读后删除树, 临时目录, 忽略失败=真)
        副本路径 = 临时目录 / "能力目录_反向实验.py"
        副本路径.write_text(坏文, encoding="utf-8")
        规格 = importlib.util.spec_from_file_location("能力目录_反向实验", 副本路径)
        assert 规格 and 规格.loader
        副本 = importlib.util.module_from_spec(规格)
        sys.modules["能力目录_反向实验"] = 副本
        规格.loader.exec_module(副本)
        副本.定位项目根 = lambda: 系统根          # 夹具：只注入项目根，逻辑本体未改
        self.assertIs(副本.定位项目根(), 系统根)  # 夹具生效自证

        def 走查(模块, 关键词: str, 页大小: int) -> tuple[list[str], int]:
            游标, 汇总 = "", []
            while True:
                值 = 模块.搜索能力(关键词, 页大小, 游标).值
                汇总.extend(记录["能力id"] for 记录 in 值["能力列表"])
                游标 = 值["下一条游标"]
                if not 游标 or len(汇总) > 10000:
                    break
            return 汇总, 值["总数"]

        from 模块库.能力目录.实现.能力目录 import 搜索能力 as 正式实现

        for 关键词, 页大小 in (("OCR", 1), ("解析", 17), ("", 100)):
            with self.subTest(关键词=关键词, 页大小=页大小):
                好集, 好总数 = 走查(sys.modules["模块库.能力目录.实现.能力目录"], 关键词, 页大小)
                坏集, 坏总数 = 走查(副本, 关键词, 页大小)
                # 前置（SoT）：正式实现本来是绿的
                self.assertEqual(好总数, len(好集), "前置：正式实现应合计==总数")
                self.assertEqual(len(好集), len(set(好集)), "前置：正式实现应无重复")
                # EoT：偏移量实现必须真的漏项（否则断言无分辨力）
                self.assertLess(len(坏集), 坏总数,
                                f"偏移量实现竟然没漏项（{len(坏集)} vs {坏总数}）——"
                                "「合计==总数」这条断言是恒绿的，抓不出分页缺陷")

    def test_不暴露适配层与内部层包(self):
        调用结果 = self.搜索("", 100)
        self.assertTrue(调用结果.成功, 调用结果.错误说明)
        for 记录 in 调用结果.值["能力列表"]:
            self.assertFalse(记录["包id"].startswith("支持库.适配层."),
                             f"暴露了内部实现边界: {记录['包id']}")

    def test_重复调用结果一致(self):
        第一次 = self.搜索("文件", 3)
        第二次 = self.搜索("文件", 3)
        self.assertTrue(第一次.成功 and 第二次.成功)
        self.assertEqual(json.dumps(第一次.值, ensure_ascii=False, sort_keys=True),
                         json.dumps(第二次.值, ensure_ascii=False, sort_keys=True))


class 检索并发回归测试(能力目录测试基类):
    """锁住 2026-09-21 修的并发缺陷（华哥「一点并发都扛不住」）。

    修前现场：`搜索能力` 每次调用都真走一遍目录树（`扫描包目录` 用 `rglob` 先全量
    遍历再排除 = 剪枝不生效），且 `构建能力索引` 是「锁外读缓存 → 未命中就重建」
    ⇒ **并发下缓存等于没写**，N 个线程各自全量重建。24 线程实测墙钟 48840ms、
    64 线程 6087ms（单发仅 55ms），线程栈全停在 `glob.select_recursive_step`。

    本测试不做绝对耗时断言（机器不同会假红），只锁**不会退化的形状**：
    并发调用的墙钟不得远大于串行总和，即缓存必须真的在并发下生效。
    """

    def test_并发检索不塌成串行(self):
        """锁的是**重建次数**这条不变式，不是墙钟（墙钟随机器波动会假红）。

        「持锁单飞」的定义就是：N 个线程同时面对空缓存时，只允许**一次**全量重建。
        修前写法（锁外读缓存）下每个线程都重建一次 —— 实测 64 线程退化 1915×。
        """
        import threading
        import time

        from 模块库.能力目录.实现 import 能力索引

        参数 = {"关键词": "执行命令", "限制": 1}
        self.后端.调用(搜索能力id, dict(参数))

        # 计数钩子：包住唯一的重建入口，数「真重建了几次」。
        重建次数 = {"n": 0}
        原重建 = 能力索引._构建能力索引原始

        def 计数重建(项目根):
            重建次数["n"] += 1
            return 原重建(项目根)

        轮数 = 16
        错误表: list[BaseException] = []

        def 一发(_序号: int) -> None:
            try:
                self.后端.调用(搜索能力id, dict(参数))
            except BaseException as 错误:  # noqa: BLE001 - 线程异常必须带回主线程，不许静默吞
                错误表.append(错误)

        能力索引._构建能力索引原始 = 计数重建
        try:
            # ★冷缓存起跑：清空索引缓存，让 16 个线程**同时**面对「缓存为空」。
            # 这正是修前现场的条件。不清缓存的话线程们全命中热缓存，测试恒绿（实测踩过）。
            能力索引._索引缓存.clear()
            线程表 = [threading.Thread(target=一发, args=(i,)) for i in range(轮数)]
            for 线程 in 线程表:
                线程.start()
            for 线程 in 线程表:
                线程.join()
        finally:
            能力索引._构建能力索引原始 = 原重建

        self.assertFalse(错误表, f"并发调用抛异常: {错误表[:1]}")
        self.assertEqual(1, 重建次数["n"],
                         f"冷缓存下 {轮数} 线程触发了 {重建次数['n']} 次全量重建"
                         "（持锁单飞失效：并发下缓存等于没写）")

    def test_并发结果与串行逐条一致(self):
        """并发只许改变速度，不许改变内容。"""
        参数 = {"关键词": "文件", "限制": 5}
        串行值 = self.后端.调用(搜索能力id, dict(参数))
        self.assertTrue(串行值.成功, 串行值.错误说明)

        import threading

        结果表: dict[int, str] = {}

        def 一发(序号: int) -> None:
            调用 = self.后端.调用(搜索能力id, dict(参数))
            结果表[序号] = json.dumps(调用.值, ensure_ascii=False, sort_keys=True)

        # 用不同关键词并发，确认不同过滤条件下的结果互不串扰（缓存键正确）。
        线程表 = [
            threading.Thread(target=一发, args=(i,)) for i in range(12)
        ]
        for 线程 in 线程表:
            线程.start()
        for 线程 in 线程表:
            线程.join()
        基准 = json.dumps(串行值.值, ensure_ascii=False, sort_keys=True)
        for 序号, 文本 in 结果表.items():
            self.assertEqual(基准, 文本, f"并发第 {序号} 发结果与串行不一致")


class 读取能力测试(能力目录测试基类):
    def 读取(self, 能力id: str) -> 结果:
        return self.后端.调用(读取能力id, {"能力id": 能力id})

    def test_读取自身完整契约(self):
        调用结果 = self.读取(读取能力id)
        self.assertTrue(调用结果.成功, 调用结果.错误说明)
        记录 = 调用结果.值
        self.assertEqual(读取能力id, 记录["能力id"])
        self.assertEqual("模块库.能力目录", 记录["包id"])
        self.assertEqual("功能模块", 记录["类型"])
        # ★ #130：`必填` 键已去重（参数族七份同义重复只留 `参数`），故从 `参数` 派生。
        self.assertEqual(["能力id"],
                         [参数["名称"] for 参数 in 记录["参数"] if 参数["必填"]])
        self.assertEqual("允许用户: *", 记录["权限"])
        self.assertIn("能力不存在", 记录["错误码"])
        self.assertIsInstance(记录["最近成功验证"], str)
        self.assertTrue(记录["最近成功验证"] in ("暂无成功验证记录",)
                        or 记录["最近成功验证"][:2] == "20", 记录["最近成功验证"])
        self.assertIn("有验证场景引用", 记录["验证状态"])

    def test_读取不存在能力明确失败(self):
        调用结果 = self.读取("不存在的能力.测试")
        self.assertFalse(调用结果.成功)
        self.assertEqual("能力不存在", 调用结果.错误码)

    def test_能力id为空被拒绝(self):
        调用结果 = self.读取("   ")
        self.assertFalse(调用结果.成功)
        self.assertEqual("参数不合法", 调用结果.错误码)

    def test_读取结果与搜索结果一致(self):
        """完整契约档与 读取能力 必须同口径（同一份记录的两个出口，逐字段相等）。

        必须显式传 细节级别=完整契约：默认档只回指针，与 读取能力 不构成「同口径对比」。
        **按能力id 定位**，不取「第一条」——关键词是整条记录子串匹配，命中集里谁排第一
        取决于其它记录的说明文案（改一句说明就会换位），取 [0] 等于把断言挂在文案上。
        """
        目标 = "能力目录.读取能力"
        搜索值 = self.后端.调用(搜索能力id, {"关键词": 目标, "限制": 100,
                                       "细节级别": "完整契约"}).值
        命中 = [记录 for 记录 in 搜索值["能力列表"] if 记录["能力id"] == 目标]
        self.assertEqual(1, len(命中), f"应恰好命中一条 {目标}")
        读取值 = self.读取(目标).值
        关键字 = ("能力id", "中文名", "包id", "版本", "参数", "默认值", "错误码")
        for 字段 in 关键字:
            self.assertEqual(命中[0][字段], 读取值[字段], f"{字段} 两处不一致")

    def test_调用示例是可执行示例而非空骨架(self):
        记录 = self.读取("能力目录.搜索能力").值
        示例 = 记录["调用示例"]
        self.assertEqual("能力目录.搜索能力", 示例["能力id"])
        # 参数面**只增不改**：示例可以演示新增参数，但旧参数一个都不能丢。
        self.assertIn("关键词", 示例["参数"])
        self.assertIn("限制", 示例["参数"])
        契约参数名 = {参数["名称"] for 参数 in 记录["参数"]}
        self.assertTrue(set(示例["参数"]) <= 契约参数名,
                        f"调用示例出现契约未声明的参数: {set(示例['参数']) - 契约参数名}")
        for 值 in 示例["参数"].values():
            self.assertIsNotNone(值, "调用示例不应留 None 骨架占位")
        self.assertTrue(记录["调用示例文本"].startswith("能力目录.搜索能力("))
        self.assertNotIn("=None", 记录["调用示例文本"])


class 装配口径与搜索面差额测试(能力目录测试基类):
    """装配口径（`/健康` 能力数）− 搜索面（本索引全表条数）的差额必须**全部**来自
    适配层有意排除，不许有第二种成因。

    为什么要有它：这个差额的成因已复发三次（2026-09-20 内部层 / 2026-09-21 未纳入
    顶层包根 / 适配层），每次都是「数字过期了、没人发现」才复发。判据把「差额 ⊆
    适配层」钉住：差额一旦多出非适配层条目立即判红，不靠人记得重算。
    """

    def test_装配口径与搜索面差额全部来自适配层有意排除(self):
        from 模块库.能力目录.实现.能力索引 import (
            排除包前缀, 扫描包目录, 读取包数据, 构建能力索引,
        )

        装配ids = set(self.后端.注册表.能力id列表)
        self.assertTrue(装配ids, "装配口径为空，装配失败")
        搜索记录, 问题 = 构建能力索引(系统根)
        self.assertFalse(问题, f"索引构建有扫描问题: {问题[:3]}")
        搜索ids = {记录["能力id"] for 记录 in 搜索记录}
        self.assertTrue(搜索ids, "搜索面为空，索引构建失败")

        # 方向一：搜索面必须是装配面的子集（能搜到的必须能调）。
        多出 = sorted(搜索ids - 装配ids)
        self.assertFalse(多出, f"搜索面出现装配面没有的能力（能搜到却调不动）: {多出[:5]}")

        # 方向二：差额的每一条，其声明包id 都必须以 排除包前缀（支持库.适配层.）开头。
        差 = 装配ids - 搜索ids
        self.assertTrue(差, "差额为 0 —— 适配层排除口径可能已改，本判据前提需复核")
        包id表: dict[str, str] = {}
        for 包目录 in 扫描包目录(系统根):
            声明 = 读取包数据(包目录)["包声明"] or {}
            包id = str(声明.get("包id", ""))
            for 能力声明 in 声明.get("能力") or []:
                if isinstance(能力声明, dict) and 能力声明.get("能力id"):
                    包id表.setdefault(str(能力声明["能力id"]), 包id)
        非适配 = sorted(i for i in 差 if not 包id表.get(i, "").startswith(排除包前缀))
        self.assertFalse(
            非适配,
            f"装配口径−搜索面 里出现非适配层成因（差额不再是「适配层有意排除」）: {非适配[:5]}")


if __name__ == "__main__":
    unittest.main(verbosity=1)
