"""薄壳返回可控 + 精准搜索：定向测试（不依赖网关，纯本地逻辑）。

为什么单独写：薄壳原先没有任何测试模块，它长期偏离（写死 限制=20、不暴露 细节级别）
就是因为没人锁住它的对外形状。本文件锁两件事：
  ① 工具清单必须暴露「精准搜索三件套」（限制/细节级别/游标）与「返回控制两件套」（返回上限字符/值字段）；
  ② `_裁剪值` 的行为：投影优先、结构化裁剪、**必留说明**（绝不静默截断）。
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

系统根 = Path(__file__).resolve().parents[2]
薄壳目录 = 系统根 / "开发工具" / "薄壳"
for 路径 in (str(系统根), str(薄壳目录)):
    if 路径 not in sys.path:
        sys.path.insert(0, 路径)

import 薄壳服务 as 壳
import 工具清单 as 清单


def _取工具(协议名: str):
    for 工具 in 清单.三个工具定义:
        if 工具.name == 协议名:
            return 工具
    raise AssertionError(f"工具清单缺少 {协议名}")


class 工具形状测试(unittest.TestCase):
    def test_检索暴露精准三件套(self):
        属性 = _取工具("capability_search").inputSchema["properties"]
        for 名 in ("关键词", "限制", "细节级别", "游标", "项目根"):
            self.assertIn(名, 属性, f"检索工具未暴露 {名}")
        self.assertEqual(["名称", "名称+说明", "完整契约"], 属性["细节级别"]["enum"])
        self.assertEqual(壳.默认检索条数, 10, "默认检索条数应已从写死的 20 收到 10")

    def test_调用暴露返回控制两件套(self):
        属性 = _取工具("capability_call").inputSchema["properties"]
        for 名 in ("能力id", "参数", "返回上限字符", "值字段", "项目根"):
            self.assertIn(名, 属性, f"调用工具未暴露 {名}")
        self.assertEqual("array", 属性["值字段"]["type"])

    def test_项目根已由必填改为可省略(self):
        """2026-09-22 华哥：「理论上 mcp 是默认绑定根目录的」——顶层 `项目根` 不再必填。

        保住的判据：参数**仍然暴露**（要显式指向别的仓库时用得上），只是不进 required。
        """
        for 协议名 in ("capability_search", "capability_call"):
            架构 = _取工具(协议名).inputSchema
            self.assertIn("项目根", 架构["properties"], f"{协议名} 仍应暴露 项目根 供显式指定")
            self.assertNotIn("项目根", 架构.get("required") or [],
                             f"{协议名} 的 项目根 已由薄壳默认绑定，不得再声明为必填")

    def test_工具数仍是三个(self):
        self.assertEqual(3, len(清单.三个工具定义), "薄壳工具数不得增加（仍是薄壳）")


class 描述动态化测试(unittest.TestCase):
    """工具描述必须**随账本动态生成**（华哥 2026-09-22：「3 个工具的提示词，尽量是动态的」）。

    锁三件事：① 三个描述都带动态占位符；② 组装后面面都含真实账本数据；
    ③ 静态模板不被污染（工具面指纹只反映代码版本，不因账本变化而漂移）。
    """

    def test_三个描述都留了动态占位符(self):
        for 工具 in 清单.三个工具定义:
            self.assertIn(清单.动态段占位, 工具.description or "",
                          f"{工具.name} 的描述未留动态占位符（华哥要求三个都动态）")

    def test_只有转发工具注入动态段且占位符必被替换(self):
        """`tool_catalog` 不转发网关，给它注入动态段纯属白付 token（未完成事项.md 留档防回潮）。

        判据两件：① 占位符一律被替换（不留字面量 `{{常用传参}}`）；② 只有
        `capability_search` / `capability_call` 带常用传参段，且与 `工具动态段能力id` 一致。
        """
        面 = {工具.name: (工具.description or "") for 工具 in 清单.组装工具面()}
        模板 = {工具.name: (工具.description or "") for 工具 in 清单.三个工具定义}
        self.assertEqual(3, len(面))
        for 名, 描述 in 面.items():
            self.assertNotIn(清单.动态段占位, 描述, f"{名} 的占位符未被替换")
            # 用「与静态模板的长度差」判有没有注入 —— 两个分支的表头不同
            # （能力段写「本能力历史常用传参」，全局段写「全平台历史最高频传参」），
            # 拿某个词去 assertIn 会漏判。
            注入长 = len(描述) - (len(模板[名]) - len(清单.动态段占位))
            if 名 in 清单.工具动态段能力id:
                self.assertGreater(注入长, 0, f"{名} 应注入动态段（照抄传参）")
            else:
                self.assertEqual(0, 注入长, f"{名} 不转发网关，不得注入动态段（白付 token）")

    def test_动态段含账本真实数据(self):
        """已有 8687 次真实调用（实测），故 `执行命令` 必有记录 —— 空库时本测试会失败，
        那是如实信号（不是环境问题），不当成 flaky 重试。"""
        段 = 清单.常用传参段(能力id="系统核心支持库.进程管理.执行命令")
        # 表头 2026-09-22 按注入预算压短（「本能力历史常用传参（照抄即可）：」→「常用传参（照抄即可）：」），
        # 断言跟着改成不依赖旧文案的形式。
        self.assertIn("常用传参", 段)
        self.assertIn("历史", 段)

    def test_无记录的能力如实说明不编造(self):
        段 = 清单.常用传参段(能力id="绝对不存在的能力.xxx.yyy")
        self.assertIn("尚无历史调用", 段)
        self.assertNotIn("样例", 段, "没记录就不得编造样例")

    def test_静态模板不被污染(self):
        """动态注入若就地改写模块级常量，第二次调用会叠加 —— 必须每次从模板重算。"""
        前 = [工具.description for 工具 in 清单.三个工具定义]
        清单.组装工具面()
        后 = [工具.description for 工具 in 清单.三个工具定义]
        self.assertEqual(前, 后, "组装不得就地改写静态模板（否则指纹漂移、真假不分）")

    def test_回执带常用传参且失败不反噬(self):
        """华哥：「调用的时候，默认给他返回调用的传参」。
        接口必在；无记录/读不到时也得回一个**带说明**的对象，而不是抛异常。"""
        有 = 壳.常用传参条("系统核心支持库.进程管理.执行命令")
        self.assertIsInstance(有, dict)
        self.assertIn("说明", 有)
        无 = 壳.常用传参条("绝对不存在的能力.xxx.yyy")
        self.assertIsInstance(无, dict)
        self.assertFalse(无.get("有记录"))


class 注入面预算测试(unittest.TestCase):
    """华哥 2026-09-22 裁决：**所有注入提示词最高 2000 字符，超出的只能使用漂移值**。

    工具面是**每个请求都要重发**的注入面（不是一次性返回），超标比别处更贵：
    实测改前 302,915 字符 —— 三个工具描述各 ~100,357，真因是 `常用传参段(能力id="")`
    把账本「按能力分段」的 964 组全铺进描述、再 ×3 个工具；改后 3,543，本轮收到 1,966。

    判据口径：三个工具的 description + inputSchema 序列化字符数之和 ≤ 预算。
    超出部分的正确处置是**改漂移指针**，不是把预算调大。
    """

    预算 = 2000

    def _工具面体量(self, 面) -> dict:
        return {工具.name: len(工具.description or "") + len(json.dumps(工具.inputSchema, ensure_ascii=False))
                for 工具 in 面}

    def test_默认工具面不超注入预算(self):
        明细 = self._工具面体量(清单.组装工具面())
        总 = sum(明细.values())
        self.assertLessEqual(总, self.预算,
                             f"工具面 {总} 字符超出注入预算 {self.预算}：{明细}；"
                             "超出部分改漂移指针（口径见 开发文档/规范/项目细则.md）")

    def test_注入预算由构造保证(self):
        """预算判据必须是**构造保证**，不能是「这次账本里恰好没超长样例」。

        实测（2026-09-22 反向验证现场）：同一份**已还原、字节一致**的代码，基线绿，
        跑完两拍反向验证后变红 —— 中间变的只有账本（每次 MCP 调用都在写）。
        故断言「静态部分 + 2×动态段上限 ≤ 预算」：只要这条绿，实际工具面必绿。
        """
        静态 = sum(len(工具.description or "") - len(清单.动态段占位)
                  + len(json.dumps(工具.inputSchema, ensure_ascii=False))
                  for 工具 in 清单.三个工具定义)
        最坏 = 静态 + 2 * 清单.动态段字符上限
        self.assertLessEqual(最坏, self.预算,
                             f"最坏情况 {最坏} 超预算：静态 {静态} + 2×{清单.动态段字符上限}；"
                             "收 `动态段字符上限` 或精简静态文案/schema")

    def test_动态段长度由构造保证有界(self):
        """动态段从账本现算，长度随样例长短漂移（实测同一份代码量到 1,176 与 2,464）。

        所以「工具面 ≤ 2000」不能靠账本恰好没超长样例，必须由 `动态段字符上限` 构造保证：
        超限时保留前缀 + 漂移指针，而不是把整段铺进注入面。
        """
        for 能力id in ("", "系统核心支持库.进程管理.执行命令", "系统核心支持库.进程管理.启动进程"):
            段 = 清单.截断动态段(清单.常用传参段(能力id=能力id))
            self.assertLessEqual(len(段), 清单.动态段字符上限,
                                 f"能力id={能力id!r} 的动态段 {len(段)} 超上限 {清单.动态段字符上限}")
        超长 = "x" * 5000
        self.assertLessEqual(len(清单.截断动态段(超长)), 清单.动态段字符上限,
                             "超长输入必须被截到上限内")
        self.assertIn("常用参数组合", 清单.截断动态段(超长), "截断后必须带漂移指针，不能静默丢")


class 提示词与实现同源测试(unittest.TestCase):
    """工具描述是 Agent 唯一的「怎么调」依据，它与实现必须同源 —— 两处各存一份必然漂移。

    实测漂移过一次（2026-09-22）：实现已把默认上限从 6000 收到 2000，描述仍写着 6000。
    危害不是「数字不好看」，而是**调用方按描述规划返回体量**：以为有 6000 就不传 `值字段`，
    实际只给 2000、撞上值裁剪，白付一轮往返。故钉两条：
    ① 默认上限只能有一处事实源，描述由它插值生成；
    ② 长任务的异步腿必须在工具面可见（此前只在 `开工准备` 返回的通用纪律里，工具面看不到）。
    """

    def test_默认上限描述与实现同源(self):
        self.assertEqual(2000, 壳.默认返回上限字符,
                         "默认上限变更时，本测试的期望值须与描述插值同批更新")
        self.assertIs(清单.默认返回上限字符, 壳.默认返回上限字符,
                      "默认上限必须只有一处事实源（两处各存一份正是漂移根因）")
        描述 = _取工具("capability_call").description or ""
        self.assertIn(f"默认 {壳.默认返回上限字符} 字符", 描述,
                      "描述未按事实源插值（改回手抄数字必然再漂移）")
        self.assertNotIn("6000", 描述, "描述里残留旧默认值 6000：调用方会按 6000 规划体量")
        架构描述 = _取工具("capability_call").inputSchema["properties"]["返回上限字符"]["description"]
        self.assertIn(f"默认 {壳.默认返回上限字符}；", 架构描述,
                      "schema 里的默认值也必须与事实源同源")

    def test_描述必须提异步腿(self):
        """华哥 2026-09-22「mcp 有异步的命令，你可以用一用，当你没发现的时候，我觉得应该是底层的提示词缺失」
        → **2026-09-23 改判**（本判据钉的指导换了，改判理由留在此处防后人改回去）。

        2026-09-22 钉的是**句柄腿四步**（启动进程 → 查询进程状态 → 等待进程结束 → 释放句柄）。
        2026-09-23 两条实测把这条指导**推翻**：
        ① 华哥裁决「**获取句柄后，不允许等待**，行就行、不行就直接返回还在执行」
           ⇒ `等待进程结束` 不该再被要求（照它做就是干等）；
        ② 实测 `释放句柄` 会**杀掉**正在跑的子进程（带对照：`sleep 600` 释放即消失、
           `sleep 120` 不释放正常跑完）⇒ 照四步走「先释放、再取结果」**必然拿不到结果**。
        正解是**任务腿**：结果落 `工程缓存/运行数据/底座运行.db` 的 `任务` 表，
        查询**秒返回、不依赖调用方保持连接**。故改钉「异步腿 / 任务提交 / 任务查询」三个词。
        """
        描述 = _取工具("capability_call").description or ""
        for 关键词 in ("异步腿", "任务提交", "任务查询"):
            self.assertIn(关键词, 描述, f"capability_call 描述未提异步腿的「{关键词}」")


class 裁剪测试(unittest.TestCase):
    def test_小返回不动且不留噪声(self):
        值, 说明 = 壳._裁剪值({"a": 1}, 6000, None)
        self.assertEqual({"a": 1}, 值)
        self.assertIsNone(说明, "未裁剪时不得回带说明（避免每轮都灌噪声）")

    def test_字段投影优先于裁剪(self):
        # 大字段没被要，小字段被要 —— 不该因为大字段而丢掉小字段
        值, 说明 = 壳._裁剪值({"小": "x", "大": "y" * 5000}, 100, ["小"])
        self.assertEqual({"小": "x"}, 值)
        self.assertEqual(["小"], 说明["保留字段"])
        self.assertNotIn("已裁剪", 说明, "投影后已在限内，不算裁剪")

    def test_字段缺失如实回报(self):
        值, 说明 = 壳._裁剪值({"a": 1}, 6000, ["a", "不存在"])
        self.assertEqual({"a": 1}, 值)
        self.assertEqual(["不存在"], 说明["字段不存在"])

    def test_字典超限改回指针且不再丢键(self):
        # 2026-09-22 改口径（华哥：「丢弃干啥？直接全部收录到一个 db 里面啊」）：
        # 超限不再缩/丢，而是**落全量 + 回指针**。本判据从「缩叶子且容器永不丢」
        # 改为更强的「一个键都不丢 —— 因为原值整份在回执里」。
        原 = {"键1": "x" * 300, "键2": "y" * 300, "键3": "z" * 300}
        值, 说明 = 壳._裁剪值(原, 400, None)
        self.assertIsNone(说明)
        self.assertIn("取回", 值, "超限必须给取回腿（否则就是丢了内容）")
        self.assertNotIn("丢弃说明", 值, "不得再有丢内容的说法")
        行表 = Path(值["回执"]).read_text(encoding="utf-8").splitlines()
        记录 = json.loads("\n".join(行表[值["起始行"] - 1:值["结束行"]]))
        self.assertEqual(原["键1"][:20], 记录["值"]["键1"][:20])

    def test_字段环事实挂在指针旁不丢(self):
        # 旧口径下「说明随上限收缩但保底事实不丢」靠的是说明自己的预算管理；
        # 新口径下字段环事实（保留字段/字段不存在）与指针并排回带，主检查是它们仍在。
        值, 说明 = 壳._裁剪值({"小": "x", "大": "y" * 5000}, 100, ["小"])
        self.assertEqual({"小": "x"}, 值)
        self.assertEqual(["小"], 说明["保留字段"])
        self.assertNotIn("已裁剪", 说明, "投影后已在限内，不算裁剪")

    def test_指针回执比硬裁便宜得多(self):
        # 旧口径（2026-09-21）：「值 + 说明」的字符数之和 ≤ 上限（硬承诺）。
        # 2026-09-22 改口径后这条**不再成立也不该成立** —— 超限时回的是**指针**，
        # 指针本身就是「省上下文」的手段。新判据换成真要求：指针要显著轻于原值。
        原 = {"键1": "x" * 5000, "键2": ["y" * 3000] * 20}
        原字符数 = len(json.dumps(原, ensure_ascii=False))
        for 上限 in (50, 200, 600, 6000):
            值, _ = 壳._裁剪值(原, 上限, None)
            指针字符数 = len(json.dumps(值, ensure_ascii=False))
            self.assertLess(指针字符数, 原字符数,
                            f"上限 {上限}：指针 {指针字符数} 应远轻于原值 {原字符数}")
            self.assertLessEqual(指针字符数, 1200, f"上限 {上限}：指针不得自身就灌满上下文")

    def test_大字典改回指针而非丢键(self):
        值, 说明 = 壳._裁剪值({f"k{i}": "v" * 200 for i in range(200)}, 300, None)
        self.assertIsNone(说明)
        self.assertIn("起始行", 值, "条目太多不再丢键，而是整份落盘 + 回指针")
        self.assertGreater(值["结束行"], 值["起始行"],
                           "大字典的记录必须多行 —— 压成一行就只能全量读回或读不全")

    def test_列表超限改回指针(self):
        值, 说明 = 壳._裁剪值(["x" * 50] * 20, 200, None)
        self.assertIsNone(说明)
        self.assertIn("取回", 值)

    def test_长文本改回指针_不再拦腰截断(self):
        值, 说明 = 壳._裁剪值("a" * 5000, 100, None)
        self.assertIsNone(说明)
        self.assertIn("取回", 值, "超长文本整份在回执里，不再局部截断")
        self.assertLessEqual(len(json.dumps(值, ensure_ascii=False)), 1200)

    def test_上限零表示不限(self):
        原 = {"a": "x" * 100000}
        值, 说明 = 壳._裁剪值(原, 0, None)
        self.assertEqual(原, 值)
        self.assertIsNone(说明)

    def test_落盘不可用时不静默丢内容(self):
        # 落盘不可用时**必须如实说明拿了不全**，不得静默丢内容，也不得抛异常。
        # 直接停掉落盘函数来测这条分支（曾用 `object()` 触发，但那被 `default=str` 兜住了 ⇒ 测不到）。
        原 = 壳._落全量回执
        壳._落全量回执 = lambda _值: None
        try:
            值, 说明 = 壳._裁剪值({"键1": "x" * 5000}, 400, None)
        finally:
            壳._落全量回执 = 原
        self.assertIsNotNone(说明)
        self.assertTrue(说明["已裁剪"])
        self.assertIn("全量回执未落盘", 说明, "降级时必须如实说「全量没留下」")
        self.assertLessEqual(len(json.dumps(值, ensure_ascii=False)), 400)

    def test_唯一大键也不再压到限内而是回指针(self):
        # 旧口径：`{"记录表": [8 条记录]}` 这种「一个键装着一大块」必须能压到限内（实测曾回 2340 字符）。
        # 新口径：不再拿「压到限内」当目标 —— 回指针（省上下文）且内容不丢（可取回）。
        原 = {"记录表": [{"任务": f"任务{i}", "说明": "x" * 60} for i in range(8)]}
        for 上限 in (300, 600):
            值, _ = 壳._裁剪值(原, 上限, None)
            self.assertIn("取回", 值)
            self.assertLessEqual(len(json.dumps(值, ensure_ascii=False)), 1200,
                                 f"上限 {上限}：指针不许自己灌满上下文")

    def test_值字段非数组时不生效但如实说明(self):
        值, 说明 = 壳._裁剪值({"a": 1}, 6000, "不是数组")
        self.assertEqual({"a": 1}, 值)
        self.assertIn("值字段未生效", 说明)


class 非法参数测试(unittest.TestCase):
    def _桩转发(self, 记录表):
        def 假转发(请求体):
            记录表.append(请求体)
            return {"HTTP状态码": 200, "信封": {"成功": True, "值": {"ok": 1}}, "错误码": "", "错误说明": ""}
        return 假转发

    def test_非法细节级别被拒且不转发(self):
        记录: list = []
        原 = 壳.转发
        壳.转发 = self._桩转发(记录)
        try:
            结果 = 壳._查询能力({"关键词": "x", "细节级别": "瞎写", "项目根": str(系统根)})
        finally:
            壳.转发 = 原
        self.assertFalse(结果["成功"])
        self.assertEqual([], 记录, "非法参数不得发起转发")

    def test_细节级别与游标原样透传(self):
        记录: list = []
        原 = 壳.转发
        壳.转发 = self._桩转发(记录)
        try:
            壳._查询能力({"关键词": "x", "细节级别": "完整契约", "游标": "abc",
                        "限制": 7, "项目根": str(系统根)})
        finally:
            壳.转发 = 原
        参数 = 记录[0]["参数"]
        self.assertEqual("完整契约", 参数["细节级别"])
        self.assertEqual("abc", 参数["游标"])
        self.assertEqual(7, 参数["限制"])

    def test_未传细节级别不塞默认值(self):
        记录: list = []
        原 = 壳.转发
        壳.转发 = self._桩转发(记录)
        try:
            壳._查询能力({"关键词": "x", "项目根": str(系统根)})
        finally:
            壳.转发 = 原
        参数 = 记录[0]["参数"]
        self.assertNotIn("细节级别", 参数, "薄壳不得替能力塞默认档（那是改写调用语义）")
        self.assertNotIn("游标", 参数)
        self.assertEqual(壳.默认检索条数, 参数["限制"])

    def test_调用侧默认裁剪生效(self):
        记录: list = []
        def 大返回(请求体):
            return {"HTTP状态码": 200, "信封": {"成功": True, "值": {"大": "x" * 20000}},
                    "错误码": "", "错误说明": ""}
        原 = 壳.转发
        壳.转发 = 大返回
        try:
            结果 = 壳._调用能力({"能力id": "某能力", "参数": {}, "项目根": str(系统根)})
        finally:
            壳.转发 = 原
        # 2026-09-22 改口径：超限不再回「值裁剪」说明，而是**值里就是指针**（没丢内容）。
        self.assertNotIn(壳.值裁剪键, 结果, "落盘成功时不该再回裁剪说明（指针就是结论）")
        self.assertIn("取回", 结果["值"], "超限必须给取回腿")
        self.assertLess(len(json.dumps(结果["值"], ensure_ascii=False)), 20000)

    def test_非法返回上限被拒(self):
        结果 = 壳._调用能力({"能力id": "某能力", "返回上限字符": "不是数字", "项目根": str(系统根)})
        self.assertFalse(结果["成功"])


class 项目根自动补位测试(unittest.TestCase):
    """`参数` 里没给 `项目根` 时，薄壳自动补顶层那个（2026-09-21）。

    治的是「本该一次成功的调用被迫多次探索」：顶层 `项目根` 是本工具自己的身份校验参数，
    能力自己的 `项目根` 是能力入参，两者同名不同层 —— 此前必须手抄第二遍，实测连传 4 次
    错才开通工。补位安全的两条前提：① 平台把 `项目根` 一律定义为仓库根绝对路径（4 个声明
    它为必填的能力说明全一致）；② 网关对未知参数一律忽略，故对未声明它的能力注入也无害。
    """

    def _桩转发(self, 记录表):
        def 假转发(请求体):
            记录表.append(请求体)
            return {"HTTP状态码": 200, "信封": {"成功": True, "值": {"ok": 1}}, "错误码": "", "错误说明": ""}
        return 假转发

    def _调(self, 参数):
        记录: list = []
        原 = 壳.转发
        壳.转发 = self._桩转发(记录)
        try:
            结果 = 壳._调用能力(参数)
        finally:
            壳.转发 = 原
        return 结果, 记录

    def test_参数里没给项目根时自动补位(self):
        根 = str(系统根)
        结果, 记录 = self._调({"能力id": "开工编排.开工准备", "参数": {"任务": "x"}, "项目根": 根})
        self.assertTrue(结果["成功"], 结果)
        self.assertEqual(根, 记录[0]["参数"]["项目根"], "能力自己的 项目根 必须被自动补上")

    def test_调用方显式给了就以调用方为准(self):
        结果, 记录 = self._调({"能力id": "某能力", "参数": {"项目根": "/显式给的"},
                            "项目根": str(系统根)})
        self.assertTrue(结果["成功"], 结果)
        self.assertEqual("/显式给的", 记录[0]["参数"]["项目根"], "不得覆盖调用方显式值")

    def test_补位不污染调用方字典(self):
        入参 = {"任务": "x"}
        self._调({"能力id": "某能力", "参数": 入参, "项目根": str(系统根)})
        self.assertNotIn("项目根", 入参, "不得原地改调用方的 参数 对象")

    def test_顶层项目根不合法时仍被拒且不转发(self):
        # 2026-09-22 口径变更：`项目根` 由「必填」改为「可省略」（薄壳启动时默认绑定自身位置）。
        # 所以「不传」不再是不合法 —— 改为验证「**显式传一个无效根**仍被拒且不转发」，
        # 这比原断言更贴近新判据的本意（默认不等于免检；显式传错照样拒）。
        结果, 记录 = self._调({"能力id": "某能力", "参数": {}, "项目根": "/tmp"})
        self.assertFalse(结果["成功"])
        self.assertEqual([], 记录, "顶层项目根不合法不得发起转发")

    def test_其余入参原样透传不被改写(self):
        结果, 记录 = self._调({"能力id": "某能力", "参数": {"任务": "x", "额外": [1, 2]},
                            "项目根": str(系统根)})
        参数 = 记录[0]["参数"]
        self.assertEqual("x", 参数["任务"])
        self.assertEqual([1, 2], 参数["额外"], "除 项目根 补位外不得改写任何入参")


class 网关操作转发测试(unittest.TestCase):
    """薄壳转发 `热接入` / `健康检查` 两个网关操作（2026-09-21）。

    为什么：改完能力要让网关重新装配，官方口径是**热接入而不是重启**（决策记录 0008）。
    但 `热接入` 只是 `/网关/调用` 上的另一个 `操作`，薄壳此前把 `操作` 写死成 `调用能力`
    ⇒ Agent 拿不到它，只能回终端 `launchctl kickstart` + `curl` 轮询（本轮实测踩到）。
    本类锁三件事：① 这两个操作能一次调用转发出去；② 表外操作 **fail-closed 不转发**；
    ③ `调用能力` 的既有形状一字不变（默认操作、能力id 必填）。
    """

    def _调(self, 参数):
        记录: list = []

        def 假转发(请求体):
            记录.append(请求体)
            return {"HTTP状态码": 200, "信封": {"成功": True, "值": {"ok": 1}},
                    "错误码": "", "错误说明": ""}

        原 = 壳.转发
        壳.转发 = 假转发
        try:
            结果 = 壳._调用能力(参数)
        finally:
            壳.转发 = 原
        return 结果, 记录

    def test_热接入不带能力id也转发(self):
        结果, 记录 = self._调({"操作": "热接入", "项目根": str(系统根)})
        self.assertTrue(结果["成功"], 结果)
        self.assertEqual({"操作": "热接入"}, 记录[0], "热接入 的请求体只能是 操作 一个键")
        # 回包瘦身（2026-09-23）：`转发` 是纯复述请求的字段，已不再出现 ——
        # 「实际操作是哪个」由上面的 `记录[0]` 断言承重，不再靠回包自述。
        for 复述键 in ("转发", "HTTP状态码", "能力id", "耗时毫秒"):
            self.assertNotIn(复述键, 结果, f"{复述键} 是复述/后台记录字段，回包不该再带")

    def test_健康检查同样转发(self):
        结果, 记录 = self._调({"操作": "健康检查", "项目根": str(系统根)})
        self.assertTrue(结果["成功"], 结果)
        self.assertEqual({"操作": "健康检查"}, 记录[0])

    def test_表外操作被拒且不转发(self):
        # 两种输入都要拒：**带 能力id 的那种才真正考的是白名单** ——
        # 不带 能力id 时就算拆掉白名单也会因为「缺能力id」被拒（反向验证实测），
        # 只测那种输入等于用别的闸门冒充白名单。
        for 参数 in ({"操作": "重启网关", "项目根": str(系统根)},
                    {"操作": "重启网关", "能力id": "某能力", "参数": {},
                     "项目根": str(系统根)}):
            结果, 记录 = self._调(参数)
            self.assertFalse(结果["成功"], f"{参数} 应当被拒")
            self.assertEqual("参数不合法", 结果["错误码"])
            self.assertEqual([], 记录, "白名单 fail-closed：表外操作一个字节都不许转发")

    def test_热接入不接受参数(self):
        # 网关侧 允许字段表 把 热接入 声明为 set()：多带字段会被静默忽略，
        # 静默忽略会让调用方以为参数生效了 —— 故薄壳在边界直接拒绝，不装作接受。
        结果, 记录 = self._调({"操作": "热接入", "参数": {"a": 1}, "项目根": str(系统根)})
        self.assertFalse(结果["成功"])
        self.assertEqual("参数不合法", 结果["错误码"])
        self.assertEqual([], 记录)

    def test_默认操作仍是调用能力(self):
        结果, 记录 = self._调({"能力id": "某能力", "参数": {"任务": "x"}, "项目根": str(系统根)})
        self.assertTrue(结果["成功"], 结果)
        self.assertEqual("调用能力", 记录[0]["操作"])
        self.assertEqual("某能力", 记录[0]["能力id"])

    def test_调用能力仍要求能力id(self):
        结果, 记录 = self._调({"参数": {}, "项目根": str(系统根)})
        self.assertFalse(结果["成功"])
        self.assertEqual("参数不合法", 结果["错误码"])
        self.assertEqual([], 记录)

    def test_工具清单暴露操作白名单且不再把能力id列为必填(self):
        模式 = _取工具("capability_call").inputSchema
        self.assertEqual(list(壳.薄壳允许操作), 模式["properties"]["操作"]["enum"],
                         "工具清单的操作枚举必须与薄壳白名单同源，不得各写一份")
        self.assertEqual([], 模式["required"],
                         "能力id 与 项目根 都不再是 schema 必填：能力id 仅 操作=调用能力 时必填，"
                         "项目根 已由薄壳默认绑定（2026-09-22 华哥：「mcp 是默认绑定根目录的」）")
        self.assertEqual(["调用能力", "热接入", "健康检查", "能力详情",
                          "任务提交", "任务查询", "任务取消"], list(壳.薄壳允许操作))

    def test_能力详情按能力id转发且不塞项目根(self):
        # A2c（2026-09-21 批 1）：让薄壳够得到权威落盘契约面。
        # 与「调用能力」的区别：它是网关操作（允许字段表 = {"能力id"}），不认 `项目根`，
        # 故不得被自动补位塞进 `参数`（塞了只是噪声，还会误导读者以为它接受该参数）。
        结果, 记录 = self._调({"操作": "能力详情", "能力id": "文件管理.读取文件",
                            "项目根": str(系统根)})
        self.assertTrue(结果["成功"], 结果)
        self.assertEqual("能力详情", 记录[0]["操作"])
        self.assertEqual("文件管理.读取文件", 记录[0]["能力id"])
        self.assertEqual({}, 记录[0]["参数"], "能力详情 不得被补位注入 项目根")

    def test_能力详情缺能力id仍被拒且不转发(self):
        结果, 记录 = self._调({"操作": "能力详情", "项目根": str(系统根)})
        self.assertFalse(结果["成功"])
        self.assertEqual([], 记录)


class 任务腿转发测试(unittest.TestCase):
    """任务腿（`任务提交`/`任务查询`/`任务取消`）接进 MCP 面（2026-09-23）。

    为什么：华哥问「获取句柄后不允许等待，行就行、不行就直接返回还在执行」「结果放 DB、
    下次请求查 DB 行不行」。答案**本来就存在** —— 网关有 `任务提交/任务查询/任务取消`
    （`运行核心/统一网关/核心处理/网关执行面.py:194/238/256`），结果落
    `工程缓存/运行数据/底座运行.db` 的 `任务` 表；**只是薄壳白名单没放行** ⇒ MCP 面调不到，
    Agent 只能退回句柄腿（而 `释放句柄` 会**杀掉**在跑的子进程，等于拿不到结果）。

    ★ 本类最承重的一条：**任务查询/任务取消 不认 `能力id`，但必须带 `参数`（里面装 任务id）**
    —— 它们与「不接受参数」的热接入/健康检查**不是一类**。混成一类会各自出错：
    把 任务id 当噪声拒掉 ⇒ 整条任务腿堵死；把热接入的多余字段放行 ⇒ 静默吞掉。
    """

    def _调(self, 参数):
        记录: list = []

        def 假转发(请求体):
            记录.append(请求体)
            return {"HTTP状态码": 200, "信封": {"成功": True, "值": {"ok": 1}},
                    "错误码": "", "错误说明": ""}

        原 = 壳.转发
        壳.转发 = 假转发
        try:
            结果 = 壳._调用能力(参数)
        finally:
            壳.转发 = 原
        return 结果, 记录

    def test_任务查询不带能力id但必须转发参数(self):
        结果, 记录 = self._调({"操作": "任务查询", "参数": {"任务id": "t1"},
                            "项目根": str(系统根)})
        self.assertTrue(结果["成功"], 结果)
        self.assertEqual({"操作": "任务查询", "参数": {"任务id": "t1"}}, 记录[0],
                         "任务查询 不认能力id、但 参数（任务id）必须原样转发")

    def test_任务取消同样转发参数(self):
        结果, 记录 = self._调({"操作": "任务取消", "参数": {"任务id": "t1"},
                            "项目根": str(系统根)})
        self.assertTrue(结果["成功"], 结果)
        self.assertEqual({"操作": "任务取消", "参数": {"任务id": "t1"}}, 记录[0])

    def test_任务查询缺参数不崩且如实转发空参数(self):
        """缺 `任务id` 是**网关**该报的错（`缺少任务id`），薄壳不越权替它判 —— 只保证不崩。"""
        结果, 记录 = self._调({"操作": "任务查询", "项目根": str(系统根)})
        self.assertTrue(结果["成功"], 结果)
        self.assertEqual({"操作": "任务查询", "参数": {}}, 记录[0])

    def test_任务提交仍要求能力id(self):
        """`任务提交` 与另两条不同：它**要** 能力id（提交的是某个能力的调用）。"""
        结果, 记录 = self._调({"操作": "任务提交", "项目根": str(系统根)})
        self.assertFalse(结果["成功"])
        self.assertEqual("参数不合法", 结果["错误码"])
        self.assertEqual([], 记录, "缺能力id 时一个字节都不许转发")

    def test_任务提交带能力id与参数照转(self):
        结果, 记录 = self._调({"操作": "任务提交", "能力id": "某能力",
                            "参数": {"x": 1}, "项目根": str(系统根)})
        self.assertTrue(结果["成功"], 结果)
        self.assertEqual("任务提交", 记录[0]["操作"])
        self.assertEqual("某能力", 记录[0]["能力id"])
        self.assertEqual({"x": 1}, 记录[0]["参数"],
                         "项目根 只对 操作=调用能力 补位，不得混进任务提交的参数")

    def test_三类操作分类必须自洽(self):
        """白名单 ⊇ 两类「不需要能力id」的操作，且两类**互不重叠**、都不含 任务提交。"""
        self.assertTrue(set(壳.无能力id操作) <= set(壳.薄壳允许操作),
                        "不需要能力id的操作必须在白名单里，否则永远转发不出去")
        self.assertTrue(set(壳.无能力id但接受参数操作) <= set(壳.薄壳允许操作))
        self.assertEqual(set(), set(壳.无能力id操作) & set(壳.无能力id但接受参数操作),
                         "两类混在一起就必然有一类出错（拒参数 vs 必须带参数）")
        self.assertNotIn("任务提交", set(壳.无能力id操作) | set(壳.无能力id但接受参数操作),
                         "任务提交 要能力id，走正常那条路")

    def test_反向_拆掉任务腿分类则任务查询必被拒(self):
        """★ 反向验证：把 `无能力id但接受参数操作` 清空，任务查询 必须因「缺能力id」被拒 ——
        证明上面那几条转发用例真的在考这条分支，而不是被别的闸门放行。"""
        原 = 壳.无能力id但接受参数操作
        壳.无能力id但接受参数操作 = ()
        try:
            结果, 记录 = self._调({"操作": "任务查询", "参数": {"任务id": "t1"},
                                "项目根": str(系统根)})
        finally:
            壳.无能力id但接受参数操作 = 原
        self.assertFalse(结果["成功"], "拆掉分类后 任务查询 不该还能转发")
        self.assertEqual([], 记录)


_薄壳源路径 = 薄壳目录 / "薄壳服务.py"
_白名单闸门 = "    if 操作 not in 薄壳允许操作:\n"


class 白名单反向验证(unittest.TestCase):
    """反向验证：拆掉操作白名单闸门后，「表外操作被拒且不转发」必须变红。

    没有这层，那条用例可能在「任何操作都照转」的实现下照样绿 —— 等于没证明这道闸门在起作用。
    """

    def _缺陷态模块(self):
        源 = _薄壳源路径.read_text(encoding="utf-8")
        坏 = 源.replace(_白名单闸门, "    if False:\n")
        if 坏 == 源:
            raise AssertionError("操作白名单闸门片段未命中，反向样本失效（判据需更新）")
        命名空间: dict = {"__name__": "反向样本_薄壳", "__file__": str(_薄壳源路径)}
        exec(compile(坏, str(_薄壳源路径), "exec"), 命名空间)  # noqa: S102
        return 命名空间

    def test_拆掉白名单后表外操作会被转发出去(self):
        模块 = self._缺陷态模块()
        记录: list = []

        def 假转发(请求体):
            记录.append(请求体)
            return {"HTTP状态码": 200, "信封": {"成功": True, "值": {"ok": 1}},
                    "错误码": "", "错误说明": ""}

        模块["转发"] = 假转发
        # 反向样本必须**带 能力id**：不带时拆掉白名单也会因「缺能力id」被拒，
        # 那是另一道闸门在兜（实测踩过），会得到假绿样本。
        入参 = {"操作": "重启网关", "能力id": "某能力", "参数": {}, "项目根": str(系统根)}
        缺陷态 = 模块["_调用能力"](dict(入参))
        self.assertTrue(缺陷态["成功"], "缺陷态下必须真的把表外操作转发出去（这正是坏行为）")
        self.assertEqual("重启网关", 记录[0]["操作"])
        # 现行实现同一输入必须被拒 —— 两者结论不同，样本才有效
        记录.clear()
        原 = 壳.转发
        壳.转发 = 假转发
        try:
            现行态 = 壳._调用能力(dict(入参))
        finally:
            壳.转发 = 原
        self.assertNotEqual(缺陷态["成功"], 现行态["成功"],
                          "反向样本与现行实现的结论必须不同，否则样本失效")
        self.assertFalse(现行态["成功"])
        self.assertEqual([], 记录, "现行实现不得转发表外操作")


_值预算行 = "    值预算 = max(1, 上限字符 - 预算)\n"


def _跑(等待对象):
    """把薄壳的 async 入口跑完（`asyncio.run` 禁止在已有事件循环里调用，测试是同步环境）。"""
    return asyncio.run(等待对象)


class isError语义测试(unittest.TestCase):
    """L10（2026-09-21 批 2）：业务失败必须真的置 `isError=True`。

    为什么必须有这条（方案 §8.2 #6 点名的假绿风险）：2026-09-21 前，`自测_stdio客户端.py`
    只读 `结果.content[0].text`、**完全不读 `结果.isError`** —— 改了也没人知道。
    实测根因：薄壳当时只回 `list[TextContent]`，而 mcp SDK 对「返回 list」的正常路径
    固定 `isError=False`（`server/lowlevel/server.py`），只有 inputSchema 校验失败与
    handler 抛异常才置 True ⇒ `参数不合法` 这类业务失败在 MCP 链路上**完全不可见**，
    模型会反复重试同一错误（SEP-1303：输入校验失败必须走 Tool Execution Error）。
    """

    def test_业务失败置isError真(self):
        结果 = _跑(壳.调用工具("capability_call", {
            "操作": "重启网关",  # 表外操作，白名单 fail-closed 必拒
            "能力id": "某能力", "参数": {}, "项目根": str(系统根)}))
        self.assertTrue(getattr(结果, "isError", False), "业务失败必须置 isError=True")
        正文 = json.loads(结果.content[0].text)
        self.assertFalse(正文["成功"])
        self.assertEqual("参数不合法", 正文["错误码"])

    def test_业务成功置isError假(self):
        # 成功路径不得误报失败（否则客户端会把正常返回当错误处理）
        结果 = _跑(壳.调用工具("tool_catalog", {}))
        self.assertFalse(getattr(结果, "isError", True), "成功不得置 isError=True")

    def test_未知工具也置isError真(self):
        结果 = _跑(壳.调用工具("不存在的工具", {}))
        self.assertTrue(getattr(结果, "isError", False))


class 顶层schema拒未知参数测试(unittest.TestCase):
    """L9（2026-09-21 批 2）：工具顶层 schema 必须声明 `additionalProperties: false`。

    为什么真的有效（不是装饰）：mcp SDK 在 `server/lowlevel/server.py` 用
    `jsonschema.validate(instance=arguments, schema=tool.inputSchema)` 执行本 schema，
    故传错参数名会**当场报错**而不是被静默忽略 —— 这正是治「猜参数名」的机制。
    ⚠️ 只能加在顶层：`参数` 内部不得加（能力参数形状由能力契约定，加进去会把所有能力参数拒掉）。
    """

    def test_三个工具顶层都声明拒未知键(self):
        for 协议名 in ("capability_search", "capability_call", "tool_catalog"):
            模式 = _取工具(协议名).inputSchema
            self.assertIs(模式.get("additionalProperties"), False,
                          f"{协议名} 未声明 additionalProperties: false（Claude 会报 Invalid schema）")

    def test_参数内部不得加拒未知键(self):
        # 若给 `参数` 加了 additionalProperties，所有能力自己的参数都会被拒 —— 反向锁死。
        参数模式 = _取工具("capability_call").inputSchema["properties"]["参数"]
        self.assertNotIn("additionalProperties", 参数模式,
                          "`参数` 是能力自己参数的容器，不得限制其键集")


class 深裁反向验证(unittest.TestCase):
    """反向验证：把「说明也占预算」退回旧口径（说明不参与上限计算），承诺判据必须变红。

    没有这层，「值 + 说明 ≤ 上限」这条承诺可能在**任何**实现下都绿 —— 等于没证明
    这道预算真的在起作用（旧实现正是这样：注释自称硬承诺，实测 52 > 50）。
    """

    def _缺陷态模块(self):
        源 = _薄壳源路径.read_text(encoding="utf-8")
        坏 = 源.replace(_值预算行, "    值预算 = 上限字符  # 反向样本：退回旧口径（说明不参与上限计算）\n")
        if 坏 == 源:
            raise AssertionError("值预算行未命中，反向样本失效（判据需更新）")
        命名空间: dict = {"__name__": "反向样本_深裁", "__file__": str(_薄壳源路径)}
        exec(compile(坏, str(_薄壳源路径), "exec"), 命名空间)  # noqa: S102
        return 命名空间

    def test_降级路径下退回旧口径承诺判据变红(self):
        """★ 2026-09-22 改口径后本样本换了作用对象（不是删掉）：默认路径已改回「指针」，
        不再以「压到限内」为目标；但**降级路径**（全量落盘不可用）仍保留「值 + 说明 ≤ 上限」的硬承诺，
        故把两边落盘都停掉，逼它们走深裁再比 —— 这层回归网依然有效。
        """
        入参 = {"键1": "x" * 5000, "键2": ["y" * 3000] * 20}
        上限 = 6000
        模块 = self._缺陷态模块()
        模块["_落全量回执"] = lambda _值: None
        缺陷值, 缺陷说明 = 模块["_裁剪值"](入参, 上限, None)
        缺陷总 = (len(json.dumps(缺陷值, ensure_ascii=False))
                + len(json.dumps(缺陷说明, ensure_ascii=False)))
        self.assertGreater(缺陷总, 上限, "缺陷态下必须真的超限（这正是坏行为）")
        # 现行实现同一输入（同样降级）必须达标 —— 两者结论不同，样本才有效
        原落盘 = 壳._落全量回执
        壳._落全量回执 = lambda _值: None
        try:
            现值, 现说明 = 壳._裁剪值(入参, 上限, None)
        finally:
            壳._落全量回执 = 原落盘
        现行总 = (len(json.dumps(现值, ensure_ascii=False))
                + len(json.dumps(现说明, ensure_ascii=False)))
        self.assertLessEqual(现行总, 上限, "现行实现在降级路径上必须达标")
        self.assertNotEqual(缺陷总 > 上限, 现行总 > 上限,
                          "反向样本与现行实现的结论必须不同，否则样本失效")


class 兜底深缩反向验证(unittest.TestCase):
    """反向验证：退回「首键无条件保留后不再深缩」的旧口径，新判据必须变红。

    这条缺口是现场实测出来的（`{"记录表": [8 条记录]}` + 上限 300 回了 2340 字符），
    没有反向样本，新判据可能只是恰好绿。
    """

    def _缺陷态模块(self):
        源 = _薄壳源路径.read_text(encoding="utf-8")
        坏 = 源.replace(
            "        if 保留项 and _字符数(保留项) > 上限:",
            "        if False:  # 反向样本：退回旧口径（首键保留后不再深缩）",
        )
        if 坏 == 源:
            raise AssertionError("兜底深缩片段未命中，反向样本失效（判据需更新）")
        命名空间: dict = {"__name__": "反向样本_兜底深缩", "__file__": str(_薄壳源路径)}
        exec(compile(坏, str(_薄壳源路径), "exec"), 命名空间)  # noqa: S102
        return 命名空间

    def test_降级路径下退回旧口径唯一大键压不下去(self):
        """同 深裁反向验证：改口径后此样本在**降级路径**上做反向（默认路径已不以「压到限内」为目标）。"""
        入参 = {"记录表": [{"任务": f"任务{i}", "说明": "x" * 60} for i in range(8)]}
        上限 = 300
        模块 = self._缺陷态模块()
        模块["_落全量回执"] = lambda _值: None
        缺陷值, 缺陷说明 = 模块["_裁剪值"](入参, 上限, None)
        缺陷总 = (len(json.dumps(缺陷值, ensure_ascii=False))
                + len(json.dumps(缺陷说明, ensure_ascii=False)))
        self.assertGreater(缺陷总, 上限, "缺陷态下必须真的超限（这正是坏行为）")
        原落盘 = 壳._落全量回执
        壳._落全量回执 = lambda _值: None
        try:
            现值, 现说明 = 壳._裁剪值(入参, 上限, None)
        finally:
            壳._落全量回执 = 原落盘
        现行总 = (len(json.dumps(现值, ensure_ascii=False))
                + len(json.dumps(现说明, ensure_ascii=False)))
        self.assertLessEqual(现行总, 上限, "现行实现在降级路径上必须压到限内")
        self.assertNotEqual(缺陷总 > 上限, 现行总 > 上限,
                          "反向样本与现行实现的结论必须不同，否则样本失效")


class 全量回执库测试(unittest.TestCase):
    """裁剪不再丢内容（2026-09-22 华哥裁决）。

    「丢弃干啥？直接全部收录到一个 db 里面啊，然后用指针便宜可以查询。这个 db，7 天删一次就完事了。」

    ★ 顺带说明：源未超限时**不落盘**；源已超限时只回指针，故本类之外那些「裁剪」判据（丢键/截尾 /
    字窜截断）只在**降级路径**（落盘不可用）成立 —— 这是 2026-09-22 改口径时同批修正的一部分，
    留着它们是留**降级能力的回归网**，不是留旧主张。

    锁四件事（每件都是可反向验证的判据，不是描述）：
      ① 超限必落全量并回指针；
      ② 指针指的那一行就是**逐字原文**（能取回才算不丢）；
      ③ 不超限不落盘（不白占盘）；
      ④ 过期按天整件清理，且只删过期的。

    为什么用临时目录：本组会真写文件。写进仓库 `工程缓存/` 会把单测变成副作用源，
    故把 `薄壳服务._项目根` 指向临时目录（`回执库()` 实时解析该值，故可注入）。
    """

    def setUp(self):
        self._临时 = tempfile.TemporaryDirectory()
        self._原项目根 = 壳._项目根
        壳._项目根 = Path(self._临时.name)
        壳.进程内回执行.clear()

    def tearDown(self):
        壳._项目根 = self._原项目根
        壳.进程内回执行.clear()
        self._临时.cleanup()

    @staticmethod
    def _大值():
        return {"记录表": [{"编号": i, "正文": "内容" * 200} for i in range(12)]}

    def test_超限落全量并回指针(self):
        裁剪后, 说明 = 壳._裁剪值(self._大值(), 200, None)
        for 键 in ("回执", "取回", "起始行", "结束行", "sha256前10", "过期日期", "保留天数",
                 "原字符数"):
            self.assertIn(键, 裁剪后, f"超限时必须回指针键 {键}（不再丢内容）")
        self.assertIsNone(说明, "落盘成功时指针自己就是结论，不应再单独回裁剪说明")

    def test_指针区段就是逐字原文且可翻页(self):
        原值 = self._大值()
        裁剪后, _ = 壳._裁剪值(原值, 200, None)
        行表 = Path(裁剪后["回执"]).read_text(encoding="utf-8").splitlines()
        段 = "\n".join(行表[裁剪后["起始行"] - 1:裁剪后["结束行"]])
        self.assertEqual([], [行 for 行 in 段.splitlines() if 行.startswith("{") and 行.endswith("}")],
                         "区段必须是**一整条**记录（多行 JSON），不能切在记录边界上")
        记录 = json.loads(段)
        self.assertEqual(记录["值"], 原值, "指针区段必须与未裁剪的原始值逐字一致（能取回才算不丢）")
        self.assertEqual(记录["摘要"][:10], 裁剪后["sha256前10"])
        self.assertGreater(裁剪后["结束行"], 裁剪后["起始行"],
                           "记录必须是多行（可逐段翻页）；压成一行就只能全量读回或读不全")

    def test_回执落的是未投影原值(self):
        """实测缺口（2026-09-22）：落盘若放在「按 值字段 投影之后」，指针上那句「拿到的就是本次
        全量原文」当场变成假话 —— 被点掉的字段真没了。判据：点名只要大字段、且投影后仍超限时，
        回执里的记录仍须等于**未投影原值**。
        """
        原值 = {"小": "x", "大": "y" * 4000}
        裁剪后, 说明 = 壳._裁剪值(原值, 200, ["大"])
        self.assertIsNone(说明)
        self.assertEqual(["大"], 裁剪后["保留字段"], "字段环事实与指针并排回带，不得因落盘而丢")
        行表 = Path(裁剪后["回执"]).read_text(encoding="utf-8").splitlines()
        记录 = json.loads("\n".join(行表[裁剪后["起始行"] - 1:裁剪后["结束行"]]))
        self.assertEqual(原值, 记录["值"], "回执必须是未投影的原值（投影只决定这一次显示多少）")

    def test_取回提示指向真有能力行区间的那条腿(self):
        """实测踩过（2026-09-22）：首版提示指向 `文件管理.读取文件`，它**没有** 起始行/结束行 参数
        （网关回「该能力契约里没有这个参数，已被网关剔除」）—— 指针当场指一条走不通的腿。
        """
        裁剪后, _ = 壳._裁剪值(self._大值(), 200, None)
        self.assertIn("文件系统支持库.文件操作.读取文件", 裁剪后["取回"])
        self.assertIn("起始行", 裁剪后["取回"])
        self.assertNotIn("文件管理.读取文件", 裁剪后["取回"])

    def test_取回提示必须自带不限上限(self):
        """实测缺口（2026-09-22）：取回腿自己也要过薄壳这一关 —— 照指针原样调，5500 字符的原文
        当场被裁到 300（实测），等于又丢了一遍。故指针必须自带 `返回上限字符=0`。
        """
        裁剪后, _ = 壳._裁剪值(self._大值(), 200, None)
        # ★ 锚「调用形式」而不是「这几个字」：首版判据写成 assertIn("返回上限字符=0")，被同一句里
        #   的**说明文字**满足 ⇒ 缺陷态（把参数删掉）下依旧全绿 = 假绿。实测踩过，勿回退。
        self.assertIn("}, 返回上限字符=0)", 裁剪后["取回"],
                      "取回腿不带 0 就会被薄壳再裁一次 —— 指针必须自带这个参数")

    def test_不超限不落盘(self):
        小值 = {"a": 1}
        裁剪后, 说明 = 壳._裁剪值(小值, 5000, None)
        self.assertEqual(小值, 裁剪后)
        self.assertIsNone(说明)
        self.assertEqual([], list(壳.回执库().glob("*.jsonl")), "没超限不该产生回执件")

    def test_过期整件清理且不误删当天(self):
        库 = 壳.回执库()
        库.mkdir(parents=True, exist_ok=True)
        旧件 = 库 / "20260901_全量回执.jsonl"
        旧件.write_text('{"摘要": "旧", "时刻": "2026-09-01T00:00:00", "值": 1}\n', encoding="utf-8")
        os.environ[壳.回执时钟环境变量] = "2026-09-22T12:00:00"
        try:
            裁剪后, _ = 壳._裁剪值(self._大值(), 200, None)
        finally:
            os.environ.pop(壳.回执时钟环境变量, None)
        self.assertFalse(旧件.exists(), "超过保留天数的整件应被清理")
        self.assertTrue(Path(裁剪后["回执"]).exists(), "当天的件不得被误删")
        self.assertEqual(1, 裁剪后.get("已清理过期回执"), "清理个数应如实回带")


async def _跑多次工具目录(次数: int, 环境追加: dict) -> list[dict]:
    """把薄壳当真 stdio 子进程拉起，连调 N 次 tool_catalog（不转发网关，故不需要 40007）。"""
    from 支持库.适配层.MCP协议提供者 import (
        构造客户端会话, 构造标准输入输出参数, 标准输入输出客户端,
    )

    参数 = 构造标准输入输出参数(
        命令=sys.executable,
        参数表=[str(薄壳目录 / "薄壳服务.py")],
        环境={**os.environ, **环境追加},
        工作目录=str(系统根),
    )
    async with 标准输入输出客户端(参数) as (读取流, 写入流):
        async with 构造客户端会话(读取流, 写入流) as 会话:
            await 会话.initialize()
            出: list[dict] = []
            for _ in range(次数):
                结果 = await 会话.call_tool("tool_catalog", {})
                正文 = 结果.content[0].text if 结果.content else ""
                出.append(json.loads(正文))
                # 换壳自 2026-09-23 起是**异步**的（周期巡检，且要等「无在途请求」）⇒ 两次
                # 调用之间留一个空闲窗口，让巡检有机会在**没有在飞回包**时把壳换掉。
                # 不留窗口也不是缺陷（换壳只是被推迟到下一次真空闲），但这条判据要验「换过」。
                await asyncio.sleep(0.3)
    return 出


async def _不握手调工具目录(脚本: Path, 环境追加: dict | None = None) -> tuple[bool, str]:
    """**故意不 `initialize`** 直接 tools/call —— `os.execve` 换壳之后，客户端就是这个姿势。

    返回 `(是否拿到工具目录, 说明)`。拿到＝新壳能在无握手的情况下服务；拿不到＝说明里带出
    客户端收到的错误原文（现行 SDK 把服务端的一切异常都兜成 `Invalid request parameters`）。
    """
    from 支持库.适配层.MCP协议提供者 import (
        构造客户端会话, 构造标准输入输出参数, 标准输入输出客户端,
    )

    参数 = 构造标准输入输出参数(
        命令=sys.executable,
        参数表=[str(脚本)],
        环境={**os.environ, **(环境追加 or {})},
        工作目录=str(系统根),
    )
    async with 标准输入输出客户端(参数) as (读取流, 写入流):
        async with 构造客户端会话(读取流, 写入流) as 会话:
            try:
                结果 = await 会话.call_tool("tool_catalog", {})
            except Exception as 错误:  # noqa: BLE001 —— 缺陷态就是这个异常，要如实带回
                return False, f"{type(错误).__name__}: {错误}"
            正文 = 结果.content[0].text if 结果.content else ""
            return (True, 正文) if 正文.strip().startswith("{") else (False, 正文[:200])


async def _连改两次源码(目录: Path) -> list[dict]:
    """真 stdio：在**同一个子进程**上连改两次源码，每次改完再调一次 `tool_catalog`。

    判据用 `进程启动时刻` —— 它是新进程 import 时取的，换一次壳就更新一次。

    ★ 2026-09-23：这里原先**容忍一个竞态**（超时重试），因为换壳点当时在读路径上 ——
    SDK 读到请求就另起任务处理，读循环立刻回到读取点，而探针只看得见「有没有未读的请求」、
    看不见「有一条回包还没写」；换壳点正好落在这一刻时，那条回包随 `os.execve` 一起消失
    （客户端只能超时）。竞态已修（换壳移到周期任务，且补了「无在途请求」判据）⇒ 重试**已删**：
    本条现在是真判据 —— 任何一次调用超时都算红，不再靠重试掩盖。
    """
    from 支持库.适配层.MCP协议提供者 import (
        构造客户端会话, 构造标准输入输出参数, 标准输入输出客户端,
    )

    脚本 = 目录 / "薄壳服务.py"
    参数 = 构造标准输入输出参数(
        命令=sys.executable,
        参数表=[str(脚本)],
        环境={**os.environ, "PYTHONPATH": str(系统根)},  # 副本不在仓库里，平台包靠它才导得到
        工作目录=str(系统根),
    )
    出: list[dict] = []
    async with 标准输入输出客户端(参数) as (读取流, 写入流):
        async with 构造客户端会话(读取流, 写入流) as 会话:
            await 会话.initialize()
            for _ in range(3):
                # 不重试：换壳若吞了回包，这里就是超时红（真判据，不再掩盖竞态）。
                结果 = await asyncio.wait_for(会话.call_tool("tool_catalog", {}), 8)
                出.append(json.loads(结果.content[0].text))
                # 改一次源码：追加注释 ⇒ 指纹变、仍可编译 ⇒ 下一次调用前就该换壳
                脚本.write_text(脚本.read_text(encoding="utf-8") + f"\n# 第 {len(出)} 次改动\n",
                               encoding="utf-8")
                await asyncio.sleep(1.1)  # 给周期巡检一个空闲窗口：换壳是异步的，改完要等它巡到
    return 出


class 自换新壳测试(unittest.TestCase):
    """改了薄壳源码，旧壳要自己换新壳（2026-09-22 华哥口径「工具内部的事，不该是使用者的事」）。

    实测代价（2026-09-22）：回执库（落盘 + 回指针 + 7 天 TTL）/ 注入面收窄 / 工具面瘦身
    三批改动全部落地并提交之后，会话里跑着的旧壳仍在走老路径 —— 真实调用照样回
    `值裁剪.截断说明`（等于还在丢内容），`tool_catalog` 实测 `是否一致=假`、
    `进程启动时刻 21:46:37`，而唯一的出路是**人记得重启 MCP 客户端**。

    本组判据分三层：① 该不该换；② 探针能不能看见「已在途的消息」（换壳不得吞消息）；
    ③ 端到端（真 stdio 子进程：换壳后调用照样成功、且确实换了、且不套娃）。
    """

    def test_指纹一致时不换壳(self):
        需换, 原因 = 清单.需换新壳(清单.采集源文件指纹(), 环境={})
        self.assertFalse(需换, "盘上没变就不该换（换壳不是常态动作）")
        self.assertIn("盘上当前版本", 原因)

    def test_指纹不一致时要换壳并点名文件(self):
        指纹 = 清单.采集源文件指纹()
        指纹["薄壳服务.py"] = "0" * 64
        需换, 原因 = 清单.需换新壳(指纹, 环境={})
        self.assertTrue(需换, "盘上代码更新后必须换壳，否则改动永远不生效")
        self.assertIn("薄壳服务.py", 原因, "原因要点名是哪个文件变了")

    def test_盘上编译不过时拒绝换壳(self):
        """反向保护：换上一个起不来的壳比继续用旧壳更糟 —— 整个 MCP 当场失联。"""
        with tempfile.TemporaryDirectory() as 临时:
            锚 = Path(临时)
            (锚 / "工具清单.py").write_text("x = 1\n", encoding="utf-8")
            (锚 / "薄壳服务.py").write_text("def 坏(:\n", encoding="utf-8")
            需换, 原因 = 清单.需换新壳({"工具清单.py": "a", "薄壳服务.py": "b"},
                                  目录=锚, 环境={})
        self.assertFalse(需换, "盘上编译不过时必须继续用旧壳")
        self.assertIn("编译不过", 原因)

    def test_指纹读不到时不换壳(self):
        """读不到 ≠ 有新版：拿空指纹当「不一致」会换上一个来路不明的版本。"""
        with tempfile.TemporaryDirectory() as 临时:
            需换, 原因 = 清单.需换新壳({"工具清单.py": "a", "薄壳服务.py": "b"},
                                  目录=Path(临时), 环境={})
        self.assertFalse(需换)
        self.assertIn("读不到", 原因)

    def test_已换到盘上这一版不重复换(self):
        """防套娃的那一半：换到的目标指纹**就是**盘上这一版 ⇒ 不再换（换完还认为自己是旧壳会无限套娃）。"""
        盘上 = 清单.采集源文件指纹()
        需换, 原因 = 清单.需换新壳({名: "0" * 64 for 名 in 盘上},
                               环境={清单.换壳目标指纹环境变量: 清单.指纹串(盘上)})
        self.assertFalse(需换, "换完还认为自己是旧壳就会无限套娃")
        self.assertIn("防套娃", 原因)

    def test_盘上又变了要再换一次(self):
        """★ 2026-09-23 修掉的那一半：守卫原先是「换过一次」的布尔，换过壳就永久为真 ⇒
        「改了源码自换新壳」**每个客户端会话只能用一次**（第二次编辑被静默忽略，正是本功能
        要治的「改了不生效」），且换过壳的进程再也换不动 ⇒ 壳出问题只能靠杀进程或重启客户端。
        改成按目标指纹比对后：目标指纹 ≠ 盘上 ⇒ 必须允许再换。
        """
        盘上 = 清单.采集源文件指纹()
        需换, 原因 = 清单.需换新壳({名: "0" * 64 for 名 in 盘上},
                               环境={清单.换壳目标指纹环境变量: "上一代换到的是别的版本"})
        self.assertTrue(需换, "盘上又变了必须再换一次，否则改动永远不生效")
        self.assertIn("薄壳服务.py", 原因)

    def test_指纹串只认内容不认键序(self):
        """守卫比对的是**串形**，而 Python 字典的插入顺序是随机的（同内容不同序很常见）⇒
        串形必须只由内容决定，否则守卫会把「同一版」误判成「又变了」、每次读都换一次壳。
        """
        A = {"工具清单.py": "a", "薄壳服务.py": "b"}
        B = {"薄壳服务.py": "b", "工具清单.py": "a"}
        self.assertEqual(清单.指纹串(A), 清单.指纹串(B))
        self.assertNotEqual(清单.指纹串(A), 清单.指纹串({**A, "薄壳服务.py": "c"}))
        self.assertNotEqual(清单.指纹串(A), 清单.指纹串({**A, "多出来.py": "c"}),
                            "多一个文件也算变了（换壳判据按文件集比对）")

    def test_探针三态判定(self):
        """探针的分派（`空` / `在途` / `未知`）—— 三种行为各验一次。

        ★ 为什么这里用桩、不 import anyio：真 anyio 流的语义由**端到端判据**兜住
        （下一条）：若 `receive_nowait` 不再把「阻塞在 send 上的发送方」算作可取，或那个异常
        改了名，探针就会恒判「未知」⇒ 永不换壳 ⇒ 端到端那条的「至少一条 本进程已换壳=真」
        当场判红。故本测试只锁分派逻辑，不在薄壳的第三方边界之外再造一份真流依赖
        （编译口的 `第三方导入分布` 门禁也不认测试文件里新引第三方）。
        """
        # 名字必须是 WouldBlock：`_探在途` 按**类型名**判（薄壳不 import anyio，理由见实现注释）。
        WouldBlock = type("WouldBlock", (Exception,), {})

        class 桩流:
            def __init__(self, 行为: str) -> None:
                self.行为 = 行为

            def receive_nowait(self):
                if self.行为 == "在途":
                    return {"消息": 1}
                if self.行为 == "空":
                    raise WouldBlock()
                raise RuntimeError("流已关")

        self.assertEqual(("在途", {"消息": 1}), 壳._探在途(桩流("在途")),
                         "有在途消息时必须能取出来（否则换壳会吞掉它）")
        self.assertEqual(("空", None), 壳._探在途(桩流("空")),
                         "空流必须判「空」，否则永远换不了壳")
        self.assertEqual(("未知", None), 壳._探在途(桩流("坏")),
                         "探针出事必须判「未知」⇒ 不换壳（安全优先）")
        self.assertEqual(("未知", None), 壳._探在途(object()),
                         "流上没有 receive_nowait 时必须判「未知」⇒ 不换壳")

    def test_端到端_换壳不丢消息且确实换了(self):
        """真起子进程 + 真 stdio 一问一答：强制换壳后，三次调用都必须被正常服务。

        判据分三件（都来自实测教训，不是想当然）：
          ① **不丢消息**：三次 `tool_catalog` 全部 `成功=True` —— 首版就是在这里挂住
             （换壳吞了在途消息，客户端永远等不到回包）；
          ② **确实换了**：至少有一条回 `本进程已换壳=真`（否则这条腿等于没接线）；
          ③ **不套娃**：换壳后的 `进程号` 稳定（守卫挡住重复换壳）。
        """
        三条 = asyncio.run(_跑多次工具目录(3, 环境追加={清单.换壳强制环境变量: "1"}))
        self.assertTrue(all(条.get("成功") for 条 in 三条),
                        f"换壳不得丢消息（三条调用都要被服务）：{三条}")
        已换 = [条 for 条 in 三条 if 条.get("本进程已换壳") is True]
        self.assertTrue(已换, f"强制换壳下必须真的换过（否则判据全绿也没意义）：{三条}")
        self.assertEqual(1, len({条["进程号"] for 条 in 已换}),
                         "换壳后进程号必须稳定（重复换壳=每次调用换一个进程）")

    def test_端到端_连改两次源码要换两次壳(self):
        """★ 本功能原先**每个会话只能换一次**：守卫是「换过一次」的布尔，第二次真改动被静默忽略
        （正是本功能要治的「改了不生效」），换过壳的进程也再也换不动 ⇒ 壳出问题不可自愈。

        真起子进程 + 真 stdio：同一个壳上连改两次源码 ⇒ 必须换两次壳。
        判据＝三条回执的 `进程内指纹.薄壳服务.py` 各不相同 —— 进程内指纹是**新进程 import 时**
        对盘上源码取的快照，换一次壳就跟着改后那一版更新一次，故「三个互不相同」等价于
        「换了两次壳、且每次都真的加载了改后的源码」。
        （原先用 `进程启动时刻`，它只有**秒**精度：换壳自 2026-09-23 起是异步的，两次换壳可能落在
        同一秒 ⇒ 那个判据会假红，已换成按内容判的指纹。）
        进程号三条相同（execve 保留 PID ⇒ 「换了几次」看不出来，只能看内容）。
        """
        with tempfile.TemporaryDirectory() as 临时:
            目录 = Path(临时) / "薄壳"
            shutil.copytree(薄壳目录, 目录, ignore=shutil.ignore_patterns("__pycache__"))
            三条 = asyncio.run(_连改两次源码(目录))
        self.assertEqual(3, len(三条))
        指纹表 = [条["进程内指纹"]["薄壳服务.py"] for 条 in 三条]
        self.assertEqual(3, len(set(指纹表)),
                         f"连改两次源码必须换两次壳（每次换壳都要加载改后那一版）：{指纹表}")
        self.assertEqual(1, len({条["进程号"] for 条 in 三条}), "换壳不换进程号（execve 保留 PID）")

    def test_换壳后不重新握手也能服务(self):
        """换壳把 SDK 的握手状态一起换掉了，而握手只能由客户端发起 ⇒ 新壳必须**无握手也能服务**。

        实测 2026-09-23（本判据就是那次的账）：`os.execve` 换掉进程镜像的同时也换掉了会话里
        那份「已握手」，新壳停在 NotInitialized，此后**每一次**调用都被 SDK 判成
        `RuntimeError: Received request before initialization was complete`，再被会话循环兜成
        一句 `Invalid request parameters` —— 连无参的 `tool_catalog` 都调不动，整条 MCP 面被打死，
        而且**不可自愈**（防套娃守卫让换过壳的进程不再换）。

        上面那条端到端判据抓不到它：它的换壳恰好落在客户端 `initialize` **之前**，新壳顺手把握手
        也接了；只有「已握手 → 换壳 → 客户端不再握手」这条路才暴露得出来。
        """
        拿到, 说明 = asyncio.run(_不握手调工具目录(薄壳目录 / "薄壳服务.py"))
        self.assertTrue(拿到, f"未握手时也必须能服务（换壳后客户端不会重发 initialize）：{说明[:300]}")
        self.assertIn("薄壳工具数", 说明, "回执必须是**真**的工具目录，不能只判「没报错」")


class 换壳后不握手反向验证(unittest.TestCase):
    """反向验证：把 `stateless=True` 拆回 `False`，「不握手也能服务」必须变红。

    没有这层，上面那条用例可能在**任何**实现下都绿 —— 等于没证明 `stateless` 在起作用。
    缺陷态用**整份薄壳源码的副本**（真 stdio 子进程），只改这一个开关：工作区不受污染，
    且走的仍是生产那条启动路径（不是把薄壳重新实现一遍来冒充）。
    """

    _开关片段 = "构造初始化选项(服务名, 服务版本), stateless=True)"

    def _缺陷态脚本(self, 目录: Path) -> Path:
        源 = (薄壳目录 / "薄壳服务.py").read_text(encoding="utf-8")
        坏 = 源.replace(self._开关片段, "构造初始化选项(服务名, 服务版本), stateless=False)")
        if 坏 == 源:
            raise AssertionError("stateless 开关片段未命中，反向样本失效（判据需更新）")
        副本 = 目录 / "薄壳服务.py"
        副本.write_text(坏, encoding="utf-8")
        return 副本

    def test_拆掉stateless后不握手调用必失败(self):
        with tempfile.TemporaryDirectory() as 临时:
            目录 = Path(临时) / "薄壳"
            shutil.copytree(薄壳目录, 目录,
                            ignore=shutil.ignore_patterns("__pycache__"))
            缺陷态脚本 = self._缺陷态脚本(目录)
            # 副本不在仓库里，平台包要显式经 PYTHONPATH 才导得到（生产里由 __file__ 推导）。
            环境 = {"PYTHONPATH": str(系统根)}
            现行拿到, 现行说明 = asyncio.run(
                _不握手调工具目录(薄壳目录 / "薄壳服务.py", 环境))
            缺陷拿到, 缺陷说明 = asyncio.run(_不握手调工具目录(缺陷态脚本, 环境))
        self.assertTrue(现行拿到, f"现行态必须能无握手服务：{现行说明[:200]}")
        self.assertIn("薄壳工具数", 现行说明, "现行态要拿到真工具目录")
        self.assertFalse(缺陷拿到,
                         f"缺陷态必须失败（否则样本失效，这道闸门等于没接线）：{缺陷说明[:200]}")
        self.assertIn("Invalid request parameters", 缺陷说明,
                      f"缺陷态必须复现那条把整条 MCP 面打死的错误：{缺陷说明[:200]}")


async def _在飞时改源码(脚本: Path, 等待秒: float = 0.3) -> tuple[bool, str]:
    """真 stdio：发一条**慢请求**，在它还在飞的时候改源码（指纹变 ⇒ 需换为真），再等回包。

    返回 `(是否拿到回包, 说明)`。拿到＝换壳没有吞掉在飞的那条响应；拿不到＝说明里带出
    客户端收到的真实现象（换壳吞了回包 ⇒ 只能超时）。
    """
    from 支持库.适配层.MCP协议提供者 import (
        构造客户端会话, 构造标准输入输出参数, 标准输入输出客户端,
    )

    参数 = 构造标准输入输出参数(
        命令=sys.executable,
        参数表=[str(脚本)],
        环境={**os.environ, "PYTHONPATH": str(系统根)},  # 副本不在仓库里，平台包靠它才导得到
        工作目录=str(系统根),
    )
    async with 标准输入输出客户端(参数) as (读取流, 写入流):
        async with 构造客户端会话(读取流, 写入流) as 会话:
            await 会话.initialize()
            在飞 = asyncio.create_task(会话.call_tool("tool_catalog", {}))
            await asyncio.sleep(等待秒)  # 请求已被读进（在飞），响应还没写出来
            脚本.write_text(脚本.read_text(encoding="utf-8") + "\n# 在飞时改源码\n", encoding="utf-8")
            try:
                结果 = await asyncio.wait_for(在飞, 5)
            except (TimeoutError, asyncio.TimeoutError):
                return False, "TimeoutError: 客户端等不到回包（在飞的那条响应被换壳吞了）"
            except Exception as 错误:  # noqa: BLE001 —— 缺陷态就是这个异常，要如实带回
                return False, f"{type(错误).__name__}: {错误}"
            正文 = 结果.content[0].text if 结果.content else ""
            return (True, 正文) if 正文.strip().startswith("{") else (False, 正文[:200])


class 换壳窗口反向验证(unittest.TestCase):
    """反向验证：把「无在途请求」这一项去掉（让它恒真），在飞的那条回包必被换壳吃掉。

    为什么必须构造「在飞窗口」（2026-09-23 实测教训）：缺陷不是「总发生」而是「落在窗口里才发生」——
    SDK 读到请求就 `tg.start_soon` 另起任务处理，读循环立刻回到读取点，此时 anyio 流里是**空的**
    （探针判「空」），但客户端手里明明有一条没回的在飞请求。窗口＝「请求已读进」到「响应已写出」
    这段处理期。不把这段拉长，缺陷态与现行态在统计上分不开（实测窗口只有毫秒级）⇒ 判据会 flaky。
    故反向样本给**副本**注入一段处理延迟（夹具，不是被测项），把窗口撑到秒级可见。

    缺陷态用**整份薄壳源码的副本**（真 stdio 子进程），只改这一处判据：工作区不受污染，
    且走的仍是生产那条启动路径（不是把薄壳重新实现一遍来冒充）。
    """

    _延迟锚 = "    协议名 = 中文名到协议名.get(str(名称), str(名称))"
    _延迟注入 = "    await asyncio.sleep(1.5)  # 反向样本夹具：把「请求已读进→响应已写出」的窗口撑开\n"
    _判据锚 = "self._账本.为空()"

    def _副本(self, 目录: Path, 去判据: bool) -> Path:
        shutil.copytree(薄壳目录, 目录, ignore=shutil.ignore_patterns("__pycache__"))
        路径 = 目录 / "薄壳服务.py"
        源 = 路径.read_text(encoding="utf-8")
        if self._延迟锚 not in 源:
            raise AssertionError("处理延迟锚点未命中，反向样本夹具失效（判据需更新）")
        坏 = 源.replace(self._延迟锚, self._延迟注入 + self._延迟锚, 1)
        if 去判据:
            if self._判据锚 not in 坏:
                raise AssertionError("「无在途请求」判据锚点未命中，反向样本失效（判据需更新）")
            # 让它恒真：`if not self._账本.为空()` 变成 `if not True` ⇒ 这一项等于不存在。
            坏 = 坏.replace(self._判据锚, "True")
        路径.write_text(坏, encoding="utf-8")
        return 路径

    def test_去掉无在途请求判据后在飞回包被吞(self):
        """现行态（只注入延迟，判据照旧）不得丢回包；缺陷态（判据恒真）必须丢 ⇒ 客户端超时。"""
        with tempfile.TemporaryDirectory() as 临时:
            现行脚本 = self._副本(Path(临时) / "现行", 去判据=False)
            缺陷脚本 = self._副本(Path(临时) / "缺陷", 去判据=True)
            现行拿到, 现行说明 = asyncio.run(_在飞时改源码(现行脚本))
            缺陷拿到, 缺陷说明 = asyncio.run(_在飞时改源码(缺陷脚本))
        self.assertTrue(现行拿到, f"现行态：在飞时改源码也不得丢回包：{现行说明[:300]}")
        self.assertIn("薄壳工具数", 现行说明, "现行态要拿到真工具目录（不能只判「没报错」）")
        self.assertFalse(缺陷拿到,
                         f"缺陷态必须丢回包（否则样本失效，这道闸门等于没接线）：{缺陷说明[:200]}")
        self.assertIn("TimeoutError", 缺陷说明,
                      f"缺陷态必须复现「客户端只能超时、且看不出原因」那条现象：{缺陷说明[:200]}")


class 回包瘦身测试(unittest.TestCase):
    """回包只回必要字段（2026-09-23 华哥三次点名）。

    口径：`成功` 恒在；`值`/`错误码`/`错误说明`/`详情`/`句柄`/`慢调用提示`/`被忽略参数`
    非空才出现；`HTTP状态码`/`转发`/`能力id`/`耗时毫秒` 一律不再出现。

    判据出处是易语言口径（`项目说明.md` 12.4① 裁决来源链最后一环）：精准返回，不堆无用字段。
    本件给两态样本：应被删的（复述/空值）必须不在；应保留的（内容/句柄/失败原因）必须在。
    """

    def _包(self, 信封: dict, 转发级错误码: str = "") -> dict:
        from 薄壳服务 import _包装
        结果 = {"HTTP状态码": 200, "信封": 信封, "错误码": 转发级错误码, "错误说明": ""}
        return _包装("探针.示例.动作", 结果, {})

    def test_成功且无载荷只回成功一位(self):
        包 = self._包({"成功": True, "值": None})
        self.assertEqual({"成功": True}, 包, f"空值不该出现：{包}")

    def test_成功带载荷只回成功与值(self):
        包 = self._包({"成功": True, "值": {"a": 1}, "详情": {}, "句柄": None,
                       "慢调用提示": "", "被忽略参数": [], "耗时毫秒": 12})
        self.assertEqual({"成功": True, "值": {"a": 1}}, 包, f"应只剩 成功+值：{包}")

    def test_复述与后台记录字段永不出现(self):
        for 信封 in ({"成功": True, "值": 1}, {"成功": False, "错误码": "参数不合法", "错误说明": "x"}):
            with self.subTest(信封=信封):
                包 = self._包(信封)
                for 键 in ("HTTP状态码", "转发", "能力id", "耗时毫秒"):
                    self.assertNotIn(键, 包, f"{键} 不该出现在回包：{包}")

    def test_句柄有才出现(self):
        有 = self._包({"成功": True, "值": {"x": 1}, "句柄": 990038})
        self.assertEqual(990038, 有.get("句柄"), f"句柄必须回带：{有}")
        无 = self._包({"成功": True, "值": {"x": 1}})
        self.assertNotIn("句柄", 无)

    def test_失败回错误码与说明(self):
        包 = self._包({"成功": False, "错误码": "参数不合法", "错误说明": "缺必填"})
        self.assertEqual({"成功": False, "错误码": "参数不合法", "错误说明": "缺必填"}, 包)

    def test_网关级失败也回错误码(self):
        """信封为空（网关不可达）时，错误码来自转发级 —— 这是敢删 HTTP状态码的前提。"""
        包 = self._包({}, 转发级错误码="网关不可达")
        self.assertFalse(包["成功"])
        self.assertEqual("网关不可达", 包["错误码"])
        self.assertNotIn("HTTP状态码", 包)

    def test_被忽略参数有才出现(self):
        包 = self._包({"成功": True, "值": 1, "被忽略参数": [{"参数名": "路径"}]})
        self.assertIn("被忽略参数", 包, "参数名写错时必须可见，否则调用方永远查不出")
        无 = self._包({"成功": True, "值": 1, "被忽略参数": []})
        self.assertNotIn("被忽略参数", 无)


if __name__ == "__main__":
    unittest.main(verbosity=1)
