"""超时执行器**线程侧**资源准入上限/熔断 与「准入后端＝平台原语」断言。

背景（外部审计报告①-4 / 未完成事项 §8.3 第 17 项，2026-09-18 收口）：
`运行核心/能力调用/超时执行.py` 原先只给**账本**加了硬上限（第 3.1 条，已实现），
**线程数本身仍无界** —— 每次带时限的调用都真起一条线程，挂死的实现只增不减，
进程里没有任何全局/每能力上限或熔断。缺的是**线程侧资源准入**，不是账本。

本文件守护两件事：

1. **线程侧有界准入/熔断真实成立**（不靠读注释，靠真起线程数）：`执行()` 在
   **建线程之前**先占「全局 + 每能力」容量槽位；满载 ⇒ 统一结果 `限流`
   （网关 `公开错误码状态映射` 里的公开码 → HTTP 429），**不排队、不起线程**；
   槽位归执行单元自己持有 ⇒ 挂死单元继续占位 ⇒ 后续调用被如实判 `限流`，
   这就是「线程数有界」的可观测形态。
2. **准入后端＝平台并发原语**（含冷启动路径，第 54 项）：准入优先走
   `支持库.后端.并发控制支持库` 的容量闸门（`等待秒=0` ⇒ 满载直接拒绝），
   探测不到才降级为内置标准库闸门，并把原因写进快照 `准入降级说明`。
   平台支持库已于 2026-09-18 可用 ⇒ 两个路径都必须断言：
   冷启动（暂存制品**含**该支持库）⇒ `准入后端` 是平台原语且降级说明为空；
   该支持库被裁掉时 ⇒ 降级不隐瞒（后端名带「降级」且说明非空），
   且降级后**有界语义逐条仍在**（同一条反向验证在降级后端下同样成立）。

反证方式（本文件的核心手法，非 mock）：把上限调成 1、并发 5 个真实挂死调用，
断言仍然只有 1 条执行线程、4 个请求被明确拒绝/限流 —— 无界实现下这里必然是
5 条线程、0 个拒绝，测试直接变红。

全程不用 `unittest.mock`（不 patch 被测对象、不伪造副作用）：用真线程、真容量
闸门、真子进程；冷启动场景由父进程真实增删暂存制品目录驱动。
"""

from __future__ import annotations

import concurrent.futures
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

if str(Path(__file__).resolve().parents[2]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from 运行核心.能力调用 import 超时执行 as 超时模块
from 运行核心.能力调用.超时执行 import (
    线程名前缀,
    线程准入快照,
    超时执行器,
    准入拒绝明细上限,
    重置准入后端,
)
from 公共契约.基础类型.逻辑类型 import 真, 假

系统根 = Path(__file__).resolve().parents[2]
平台原语后端名 = "支持库.后端.并发控制支持库.容量闸门（等待秒=0，满载直接拒绝）"

#: 冷启动子进程脚本：只经生产导入路径观测准入后端（不 import 测试中心）。
#: sys.path 顺序与生产 `测试中心/运行核心/冷启动脚本.py::_装配路径` 一致：
#: 暂存根（制品）在前，仓库根兜底（暂存制品里没有的包，如 公共契约，穿透到仓库）。
冷启动脚本 = r'''
import json
import pathlib
import sys
import time

暂存根 = pathlib.Path(sys.argv[1])
仓库根 = pathlib.Path(sys.argv[2])
sys.path.insert(0, str(仓库根))
sys.path.insert(0, str(暂存根))

输出 = {}
import 运行核心.能力调用.超时执行 as 模块

try:  # 闸门库可能已被制品裁剪（降级场景）——探测失败本身就是要观测的事实
    import 支持库.后端.并发控制支持库 as 闸门库
    输出["闸门库文件"] = str(getattr(闸门库, "__file__", "") or "")
except BaseException as 错误:
    输出["闸门库文件"] = ""
    输出["闸门库错误"] = f"{type(错误).__name__}: {错误}"

模块.重置准入后端()
执行器 = 模块.超时执行器(全局执行线程上限=1, 每能力执行线程上限=1)
快照 = 执行器.状态快照()
输出["准入后端"] = 快照["准入后端"]
输出["准入降级说明"] = 快照["准入降级说明"]
输出["全局执行线程上限"] = 快照["全局执行线程上限"]


def 挂死():
    time.sleep(3.0)
    return "不该返回"


结果一, 残留一 = 执行器.执行(挂死, 能力id="测试.冷启动挂死", 超时秒=0.1)
结果二, 残留二 = 执行器.执行(挂死, 能力id="测试.冷启动挂死", 超时秒=0.1)
输出["首次残留"] = 残留一 is not None
输出["二次错误码"] = str(getattr(结果二, "错误码", "") or "")
输出["二次残留"] = 残留二 is not None
快照 = 执行器.状态快照()
输出["全局执行线程占用"] = 快照["全局执行线程占用"]
输出["累计准入拒绝数"] = 快照["累计准入拒绝数"]
print(json.dumps(输出, ensure_ascii=False))
'''


def 等待条件(条件, 超时秒: float = 8.0) -> bool:
    截止 = time.monotonic() + 超时秒
    while time.monotonic() < 截止:
        if 条件():
            return 真
        time.sleep(0.01)
    return bool(条件())


def 本前缀活线程数() -> int:
    """本模块执行线程的**真实**存活数（按线程名计数，不读内部计数）。"""
    return sum(1 for 线程 in threading.enumerate()
               if 线程.is_alive() and 线程.name.startswith(线程名前缀))


def 挂死(等待秒: float = 3.0):
    """返回一个真实长时间不返回的调用（模拟挂死实现）。"""
    def 调用():
        time.sleep(等待秒)
        return "挂死实现迟到返回"
    return 调用


class Test线程侧有界准入(unittest.TestCase):
    """线程侧上限/熔断：上限 1 并发 5 ⇒ 只 1 条线程、其余明确拒绝。

    隔离注意：测试之间共用**进程级共享闸门后端**（平台容量闸门表），而被准入的
    挂死单元会一直占着槽位直到它自己跑完。因此每个用例在 `setUp` 里必须确认
    「上一条用例的执行线程已全部退出」，否则占用会跨用例漂移，把本文件自己的
    断言变成抖动源（实测：不等待时「上限 1 并发 5」会读到 2 条线程）。
    """

    def setUp(self) -> None:
        self.assertTrue(
            等待条件(lambda: 本前缀活线程数() == 0, 10.0),
            f"上一条用例的执行线程未退出（存活 {本前缀活线程数()} 条），"
            f"共享闸门占用会跨用例漂移",
        )

    def test_反向验证_上限一并发五_只起一条线程其余被拒而非全部开线程(self) -> None:
        """把上限调为 1、并发 5 个请求：必须有请求被拒（或排队），不得全部开线程。

        无界实现的形态是 5 条线程 + 0 拒绝 + 5 条残留，本断言直接把它打成红。
        """
        执行器 = 超时执行器(全局执行线程上限=1, 每能力执行线程上限=1,
                            残留账本上限=8)

        def 一发(_序号: int) -> tuple:
            开始 = time.monotonic()
            结果, 残留 = 执行器.执行(挂死(3.0), 能力id="测试.并发挂死", 超时秒=0.15)
            return (str(getattr(结果, "错误码", "") or ""), 残留 is not None,
                    round(time.monotonic() - 开始, 3))

        总开始 = time.monotonic()
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as 池:
            出 = list(池.map(一发, range(5)))
        总耗时 = time.monotonic() - 总开始

        限流数 = sum(1 for 错误码, _残留, _耗时 in 出 if 错误码 == "限流")
        残留数 = sum(1 for _错误码, 有残留, _耗时 in 出 if 有残留)
        占用线程数 = 本前缀活线程数()

        # ① 起线程数被真实卡在 1：不是「账本有上限」而是「线程有上限」
        self.assertEqual(占用线程数, 1, f"执行线程应被卡在全局上限 1，实测 {占用线程数} 条")
        self.assertEqual(残留数, 1, "只有被准入的那一次会走到超时残留")
        # ② 其余 4 个是**明确拒绝**，不是静默排队、不是「超时/内部错误」冒充
        self.assertEqual(限流数, 4, f"应恰好 4 次满载拒绝，实测 {限流数}；出参 {出}")
        self.assertTrue(all(错误码 in ("限流", "") for 错误码, _r, _t in 出))
        # ③ 拒绝是立刻发生的（不排队等挂死单元跑完）：5 次调用总耗时远小于挂死时长
        self.assertLess(总耗时, 1.5,
                        f"满载拒绝不得静默排队（总耗时 {总耗时:.3f}s，挂死实现需 3s）")
        self.assertLess(max(耗时 for _码, _r, 耗时 in 出), 1.0)
        # ④ 必须在**执行器还活着**时读快照：超时单元跑完会自行释放槽位与线程
        快照 = 执行器.状态快照()
        self.assertEqual(快照["全局执行线程上限"], 1)
        self.assertEqual(快照["每能力执行线程上限"], 1)
        self.assertEqual(快照["全局执行线程占用"], 1, "被准入单元仍在跑 ⇒ 占用如实为 1")
        self.assertEqual(快照["累计准入拒绝数"], 4)
        # 留痕有界：明细最多 准入拒绝明细上限 条，累计值另计（不隐藏、不无界）
        self.assertLessEqual(len(快照["准入拒绝明细"]), 准入拒绝明细上限)
        self.assertGreater(len(快照["准入拒绝明细"]), 0, "满载拒绝必须留痕")
        维度 = {项["维度"] for 项 in 快照["准入拒绝明细"]}
        self.assertTrue(维度 <= {"全局", "每能力"}, f"拒绝维度必须明确，实测 {维度}")
        # ⑤ 挂死单元跑完后，线程与槽位都必须自行归零（不靠外力回收）
        self.assertTrue(等待条件(lambda: 本前缀活线程数() == 0, 8.0),
                        "挂死实现跑完后执行线程必须归零")
        self.assertEqual(执行器.状态快照()["全局执行线程占用"], 0,
                         "执行单元退出必须归还槽位，不得留占死槽")

    def test_挂死单元持续占位_饱和判限流而非超时(self) -> None:
        """槽位归执行单元所有：挂死单元不释放 ⇒ 后续调用被如实判「限流」。"""
        执行器 = 超时执行器(全局执行线程上限=1, 每能力执行线程上限=1)
        结果一, 残留一 = 执行器.执行(挂死(3.0), 能力id="测试.占位", 超时秒=0.1)
        self.assertIsNone(结果一, "到点未完成 ⇒ 按超时回报，不冒充结果")
        self.assertIsNotNone(残留一)

        结果二, 残留二 = 执行器.执行(lambda: "快", 能力id="测试.占位", 超时秒=5.0)
        self.assertIsNone(残留二)
        self.assertEqual(str(结果二.错误码), "限流",
                         "挂死单元仍占槽位 ⇒ 后续调用必须限流，而不是排队等它")
        self.assertFalse(结果二.成功)
        self.assertTrue(结果二.可重试, "限流必须标可重试（调用方按退避重试处理）")
        self.assertEqual(结果二.来源, "超时执行器.线程准入")
        self.assertIn("不排队", str(结果二.错误说明))
        准入门 = 结果二.详细信息["准入门"]
        self.assertEqual(准入门["能力id"], "测试.占位")
        self.assertEqual(准入门["上限"], 1)
        self.assertEqual(执行器.状态快照()["全局执行线程占用"], 1)

    def test_每能力饱和只拒本能力_不牵连其他能力(self) -> None:
        """每能力上限独立生效：一个失控能力不得吃光全局预算、连带打挂无关能力。"""
        执行器 = 超时执行器(全局执行线程上限=4, 每能力执行线程上限=1)
        执行器.执行(挂死(3.0), 能力id="测试.失控能力", 超时秒=0.1)  # 占满自身闸门

        被拒, _ = 执行器.执行(lambda: "不该跑", 能力id="测试.失控能力", 超时秒=5.0)
        self.assertEqual(str(被拒.错误码), "限流")
        self.assertEqual(被拒.详细信息["准入门"]["维度"], "每能力")

        放行, 残留 = 执行器.执行(lambda: "无关能力正常", 能力id="测试.无关能力", 超时秒=5.0)
        self.assertIsNone(残留)
        self.assertEqual(放行, "无关能力正常", "无关能力不得被别的能力饱和牵连")
        快照 = 执行器.状态快照()
        self.assertEqual(快照["累计准入拒绝数"], 1, "无关能力这一次不应计入拒绝")
        # 无关能力已正常返回 ⇒ 它的槽位已归还；此刻在册占用只剩那条挂死单元
        self.assertEqual(快照["全局执行线程占用"], 1)

    def test_上限非法值回落平台默认_不静默变成零上限(self) -> None:
        """配置非法（None/布尔/0/负数/非整数）一律回落默认上界，不关掉准入。"""
        for 非法 in (None, 0, -3, 真, 假, 3.5, "64"):
            执行器 = 超时执行器(全局执行线程上限=非法, 每能力执行线程上限=非法)  # type: ignore[arg-type]
            快照 = 执行器.状态快照()
            self.assertEqual(快照["全局执行线程上限"], 超时模块.默认全局执行线程上限,
                             f"非法值 {非法!r} 必须回落默认上界")
            self.assertEqual(快照["每能力执行线程上限"], 超时模块.默认每能力执行线程上限)
            self.assertGreater(快照["全局执行线程上限"], 0)

    def test_每能力闸门登记有上限_超限走兜底不无界增长(self) -> None:
        """闸门名按能力id 生成 ⇒ 必须给**登记数量**加上限，否则无界从线程搬到闸门表。"""
        原始上限 = 超时模块.每能力闸门数上限
        超时模块.每能力闸门数上限 = 2
        try:
            执行器 = 超时执行器(全局执行线程上限=64, 每能力执行线程上限=4)
            for 名字 in ("甲", "乙", "丙"):
                值, 残留 = 执行器.执行((lambda 名称: lambda: 名称)(名字),
                                     能力id=f"测试.能力{名字}", 超时秒=5.0)
                self.assertIsNone(残留)
                self.assertEqual(值, 名字, "登记超限只影响闸门复用，不得影响调用本身")
            快照 = 执行器.状态快照()
            self.assertEqual(快照["已登记能力闸门数"], 2, "闸门登记数必须被上限卡住")
            self.assertEqual(快照["走兜底闸门次数"], 1, "超限的第 3 个能力id 必须走兜底闸门")
            self.assertEqual(快照["累计准入拒绝数"], 0, "登记超限不是拒绝，更不是失败")
        finally:
            超时模块.每能力闸门数上限 = 原始上限

    def test_准入自身抛异常也不留占死槽(self) -> None:
        """反向验证：每能力那一步抛错时，已占的全局槽位必须归还（否则预算被占死）。

        红对照手法（非 mock 断言、是**真故障注入**）：把后端 `尝试占用` 换成
        「第 2 次调用（＝每能力闸门那次）抛 RuntimeError」的真实现包装。修复前
        该异常从 `_准入` 直穿到调用方，**已占的全局槽位永不归还** —— 实测全局
        占用量停在 1 且无任何留痕，有效全局上限被静默削减成 上限-1（护栏
        fail-open）；修复后占用必须回到 0。
        """
        重置准入后端()
        执行器 = 超时执行器(全局执行线程上限=4, 每能力执行线程上限=4)
        后端, _说明 = 超时模块._解析准入后端()
        原始尝试占用 = 后端.尝试占用
        调用序 = {"次": 0}

        def 注入异常(闸门名, 上限):
            调用序["次"] += 1
            if 调用序["次"] == 2:   # 第 1 次＝全局闸门；第 2 次＝每能力闸门
                raise RuntimeError("注入：每能力闸门占用异常")
            return 原始尝试占用(闸门名, 上限)

        后端.尝试占用 = 注入异常
        try:
            with self.assertRaises(RuntimeError, msg="准入后端异常必须原样抛出，不许吞掉"):
                执行器.执行(lambda: "不该跑到", 能力id="测试.准入异常", 超时秒=5.0)
        finally:
            后端.尝试占用 = 原始尝试占用

        self.assertEqual(调用序["次"], 2, "注入点必须正好落在每能力闸门占用那一步")
        占用, 查说明 = 执行器._查占用(执行器.全局闸门名)
        self.assertEqual((占用, 查说明), (0, ""),
                         f"异常路径必须归还已占全局槽位，实测占用 {占用}（>0 = 预算被占死）")
        self.assertEqual(本前缀活线程数(), 0, "准入就失败了 ⇒ 一条执行线程都不该起来")
        # 修复后不变量：任何一次准入失败都不削减有效上限 —— 并发 4 个上限内调用全部放行
        self.assertEqual(执行器.状态快照()["全局执行线程占用"], 0)
        放行值 = [执行器.执行((lambda n: lambda: n)(i), 能力id=f"测试.异常后{i}",
                              超时秒=5.0)[0] for i in range(4)]
        self.assertEqual(放行值, [0, 1, 2, 3], "异常之后全局预算必须仍是完整的 4 格")
        self.assertEqual(执行器.状态快照()["累计准入拒绝数"], 0,
                         "有效上限被削减时会误判限流；零拒绝＝上限未被吃")
        self.assertTrue(等待条件(lambda: 本前缀活线程数() == 0, 8.0))
        self.assertEqual(执行器.状态快照()["全局执行线程占用"], 0)

    def test_线程有界不放宽账本硬上限(self) -> None:
        """线程侧有界是**新增**边界：账本硬上限这条既有不变式必须原样成立。"""
        执行器 = 超时执行器(残留账本上限=2, 全局执行线程上限=64, 每能力执行线程上限=1)
        for 序号 in range(5):
            结果, 残留 = 执行器.执行(挂死(2.0), 能力id=f"测试.账本{序号}", 超时秒=0.05)
            self.assertIsNone(结果)
            self.assertIsNotNone(残留)
        快照 = 执行器.状态快照()
        self.assertLessEqual(快照["账本条目数"], 快照["账本硬上限"],
                             "账本条目数 ≤ 硬上限必须恒成立")
        self.assertEqual(快照["账本条目数"], 2)
        self.assertEqual(快照["因上限丢弃残留数"], 3, "丢弃的是明细，不是事实")
        self.assertEqual(快照["真实残留规模下界"], 5)
        self.assertTrue(快照["账本已达硬上限"])
        # 5 条挂死线程各自占着自己的槽位 —— 线程侧上界与账本上界是两个独立口径
        self.assertEqual(快照["全局执行线程占用"], 5)
        self.assertEqual(快照["累计超时次数"], 5)
        self.assertTrue(等待条件(lambda: 本前缀活线程数() == 0, 10.0),
                        "挂死实现跑完后执行线程应自行归零")
        self.assertEqual(执行器.状态快照()["全局执行线程占用"], 0,
                         "5 个单元全部退出后槽位必须全部归还")


class Test准入后端平台原语(unittest.TestCase):
    """第 54 项：准入后端必须是平台原语，降级必须如实暴露（不隐瞒）。"""

    def test_进程内准入后端恒为平台原语(self) -> None:
        """平台支持库可用 ⇒ 线程准入必须走它的容量闸门，且无降级说明。"""
        重置准入后端()
        执行器 = 超时执行器()
        快照 = 执行器.状态快照()
        self.assertEqual(快照["准入后端"], 平台原语后端名,
                         "有平台并发原语时不得走内置降级闸门")
        self.assertEqual(快照["准入降级说明"], "", "未降级 ⇒ 降级说明必须为空")
        # 快照暴露的闸门占用必须是平台原语读出来的真值（不是内部计数自报）
        self.assertIsNotNone(快照["全局执行线程占用"])
        self.assertEqual(快照["全局执行线程占用"], 0)
        self.assertEqual(快照["准入查询说明"], "")
        self.assertEqual(平台原语后端名, 线程准入快照()["准入后端"],
                         "进程级 线程准入快照 与实例快照必须同一后端口径")

    def test_平台原语路径下容量闸门可被直接观测(self) -> None:
        """准入占位走的是真平台闸门：占用值可从支持库查询得到（非自报计数）。"""
        from 支持库.后端.并发控制支持库 import 查询容量闸门
        执行器 = 超时执行器(全局执行线程上限=2, 每能力执行线程上限=2)
        执行器.执行(挂死(3.0), 能力id="测试.平台闸门", 超时秒=0.1)
        查询 = 查询容量闸门(闸门名=执行器.全局闸门名)
        self.assertTrue(查询.成功, f"平台容量闸门必须可查询：{查询.错误说明}")
        值 = 查询.值 or {}
        self.assertEqual(值.get("上限"), 2)
        self.assertEqual(值.get("占用"), 1, "平台闸门占用必须等于真实在跑的 1 个执行单元")


class Test冷启动准入后端(unittest.TestCase):
    """冷启动路径（暂存制品）也必须断言准入后端＝平台原语（第 54 项）。"""

    子进程超时秒 = 120

    def setUp(self) -> None:
        self.临时根 = Path(tempfile.mkdtemp(prefix="超时执行线程准入_"))
        self.暂存根 = self.临时根 / "暂存根"
        self.工作目录 = self.临时根 / "工作目录"
        self.工作目录.mkdir(parents=True)
        self.放置暂存制品()

    def tearDown(self) -> None:
        shutil.rmtree(self.临时根, ignore_errors=True)

    def 放置暂存制品(self, 含并发控制: bool = 真) -> None:
        """把支持库按生产制品方式放进暂存根（只放并发控制支持库，其余穿透仓库）。"""
        支持库根 = 系统根 / "支持库"
        shutil.rmtree(self.暂存根, ignore_errors=True)
        (self.暂存根 / "支持库" / "后端").mkdir(parents=True)
        shutil.copy2(支持库根 / "__init__.py", self.暂存根 / "支持库" / "__init__.py")
        shutil.copy2(支持库根 / "后端" / "__init__.py",
                     self.暂存根 / "支持库" / "后端" / "__init__.py")
        if 含并发控制:
            shutil.copytree(
                支持库根 / "后端" / "并发控制支持库",
                self.暂存根 / "支持库" / "后端" / "并发控制支持库",
                ignore=shutil.ignore_patterns("__pycache__"),
            )

    def 运行冷启动(self) -> dict:
        环境 = {键: 值 for 键, 值 in os.environ.items()
                if 键 not in ("PYTHONPATH", "PYTHONHOME")}
        环境["PYTHONIOENCODING"] = "utf-8"
        进程 = subprocess.run(
            [sys.executable, "-c", 冷启动脚本, str(self.暂存根), str(系统根)],
            capture_output=True, env=环境, cwd=str(self.工作目录),
            timeout=self.子进程超时秒, text=True, encoding="utf-8",
        )
        self.assertEqual(进程.returncode, 0,
                         f"冷启动子进程退出码 {进程.returncode}：{进程.stderr[-1200:]}")
        return json.loads(进程.stdout)

    def test_冷启动准入后端是平台原语且无降级(self) -> None:
        """全新进程 + 暂存制品：`准入后端` 必须是平台容量闸门，降级说明为空。"""
        输出 = self.运行冷启动()
        self.assertEqual(输出["准入后端"], 平台原语后端名,
                         f"冷启动必须有平台原语准入，实测 {输出['准入后端']}；"
                         f"降级说明 {输出['准入降级说明']}")
        self.assertEqual(输出["准入降级说明"], "")
        # 走的是暂存制品，不是仓库孪生包（否则本测试对制品不成立）
        self.assertIn(str(self.暂存根), 输出["闸门库文件"],
                      f"闸门库必须来自暂存制品：{输出['闸门库文件']}")
        # 平台原语路径下，有界准入在同一条链路上真实生效
        self.assertTrue(输出["首次残留"], "首次挂死调用必须按超时残留回报")
        self.assertEqual(输出["二次错误码"], "限流")
        self.assertFalse(输出["二次残留"], "满载拒绝不得起线程 ⇒ 不可能有残留")
        self.assertEqual(输出["全局执行线程占用"], 1)
        self.assertEqual(输出["累计准入拒绝数"], 1)

    def test_并发控制支持库被裁掉时降级不隐瞒且语义仍在(self) -> None:
        """制品裁剪场景：取不到平台闸门 ⇒ 降级后端名与原因如实暴露，有界语义照旧。

        这是**反向**断言：不隐瞒降级、也不因降级而失去有界准入（否则可选包
        缺失会把「线程有界」这条核心不变式反向打掉，比无界更糟）。
        """
        self.放置暂存制品(含并发控制=假)
        输出 = self.运行冷启动()
        self.assertNotEqual(输出["准入后端"], 平台原语后端名,
                            "支持库已被裁掉，不可能仍是平台原语后端")
        self.assertIn("降级", 输出["准入后端"])
        self.assertTrue(输出["准入降级说明"].strip(), "降级原因必须写进快照，不许隐瞒")
        self.assertIn("并发控制支持库", 输出["准入降级说明"])
        # 降级后「有界 + 明确拒绝」逐条仍在
        self.assertTrue(输出["首次残留"])
        self.assertEqual(输出["二次错误码"], "限流")
        self.assertFalse(输出["二次残留"])
        self.assertEqual(输出["全局执行线程占用"], 1)
        self.assertEqual(输出["累计准入拒绝数"], 1)


if __name__ == "__main__":
    unittest.main()
