"""网关任务接入测试：提交/轮询/取消/超时/失败码回带 全链路（假后端，独立进程真跑）。"""

from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path

from 运行核心.统一网关.网关核心 import 网关核心, 网关请求, 网关响应
from 运行核心.任务调度 import 任务系统 as 任务系统模块
from 运行核心.任务调度.任务接入 import 构造任务系统, 注册全部能力, 任务追踪键
from 公共契约.基础类型.逻辑类型 import 真, 假

终态 = {"成功", "失败", "已取消", "超时", "崩溃"}


class 假结果:
    def __init__(self, 成功: bool = 真, 值=None, 错误码: str = "", 错误说明: str = "") -> None:
        self.成功 = 成功
        self.值 = 值
        self.错误码 = 错误码
        self.错误说明 = 错误说明


class 假实现:
    def __init__(self, 参数: list) -> None:
        self.参数 = 参数


class 假注册表:
    def __init__(self, 能力表: dict) -> None:
        self.能力表 = dict(能力表)

    @property
    def 能力id列表(self) -> list:
        return list(self.能力表)

    def 获取(self, 能力id: str):
        return self.能力表.get(能力id)


class 假后端:
    """只实现网关与执行器真正用到的面：注册表 + 调用。"""

    能力表 = {
        "示例.快": 假实现([{"名称": "文本", "类型": "文本型", "必填": 真}]),
        "示例.慢": 假实现([]),
        "示例.失败": 假实现([]),
    }

    def __init__(self) -> None:
        self.注册表 = 假注册表(self.能力表)

    def 调用(self, 能力id: str, 参数: dict, *, 上下文=None, 超时秒: float = 10.0) -> 假结果:
        if 能力id == "示例.快":
            return 假结果(值={"回显": dict(参数), "上下文能力": 上下文.能力id if 上下文 else ""})
        if 能力id == "示例.慢":
            time.sleep(5)
            return 假结果(值={"睡醒": 真})
        if 能力id == "示例.失败":
            return 假结果(成功=假, 错误码="外部依赖不可用", 错误说明="假上游 503")
        return 假结果(成功=假, 错误码="能力不存在", 错误说明=能力id)


class 网关任务接入测试(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._临时目录 = tempfile.TemporaryDirectory(prefix="任务接入测试_")
        cls.后端 = 假后端()
        cls.任务系统实例 = 构造任务系统(
            cls.后端, 存储目录=Path(cls._临时目录.name) / "任务")
        cls.网关 = 网关核心(cls.后端, 任务系统=cls.任务系统实例)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.任务系统实例.关闭全部()
        cls._临时目录.cleanup()

    def 处理(self, **字段) -> 网关响应:
        return self.网关.处理(网关请求(**字段))

    def 等到终态(self, 任务id: str, 超时秒: float = 15.0) -> dict:
        截止 = time.monotonic() + 超时秒
        while time.monotonic() < 截止:
            响应 = self.处理(操作="任务查询", 参数={"任务id": 任务id})
            self.assertTrue(响应.成功, 响应.错误说明)
            任务 = 响应.值
            if 任务.get("状态") in 终态:
                return 任务
            time.sleep(0.05)
        self.fail(f"任务 {任务id} 未在 {超时秒} 秒内进入终态")

    def test_每个正式能力都注册了执行器(self) -> None:
        self.assertEqual(
            sorted(self.任务系统实例.执行函数表),
            sorted(假后端.能力表),
        )

    def test_提交后轮询到成功且追踪键不下发能力(self) -> None:
        响应 = self.处理(操作="任务提交", 能力id="示例.快",
                          参数={"文本": "你好"}, 超时秒=30)
        self.assertTrue(响应.成功, 响应.错误说明)
        任务id = 响应.值["任务id"]
        任务 = self.等到终态(任务id)
        self.assertEqual(任务["状态"], "成功")
        self.assertEqual(任务["结果"]["回显"], {"文本": "你好"})
        self.assertEqual(任务["结果"]["上下文能力"], "示例.快")
        self.assertNotIn(任务追踪键, 任务["结果"]["回显"])

    def test_能力自身错误码原样回带(self) -> None:
        响应 = self.处理(操作="任务提交", 能力id="示例.失败", 参数={}, 超时秒=30)
        self.assertTrue(响应.成功, 响应.错误说明)
        任务 = self.等到终态(响应.值["任务id"])
        self.assertEqual(任务["状态"], "失败")
        self.assertEqual(任务["错误码"], "外部依赖不可用")
        self.assertEqual(任务["错误说明"], "假上游 503")

    def test_未知能力提交前就被拒绝(self) -> None:
        响应 = self.处理(操作="任务提交", 能力id="示例.不存在", 参数={}, 超时秒=30)
        self.assertFalse(响应.成功)
        self.assertEqual(响应.错误码, "能力不存在")

    def test_参数不合契约提交前就被拒绝(self) -> None:
        """兼容口径（哲学第 21 条）：未知字段被边界剔除后照常提交，只有强制参数不满足才拒。

        旧行为是「未知参数即 400」，已废止——上游多传一个字段不该让长任务提交失败。
        """
        未知参数 = self.处理(操作="任务提交", 能力id="示例.快",
                            参数={"文本": "你好", "不认识": 1}, 超时秒=30)
        self.assertTrue(未知参数.成功, 未知参数.错误说明)

        缺必填 = self.处理(操作="任务提交", 能力id="示例.快", 参数={}, 超时秒=30)
        self.assertFalse(缺必填.成功)
        self.assertEqual(缺必填.错误码, "参数不合法")
        self.assertIn("文本", 缺必填.错误说明)

        类型不符 = self.处理(操作="任务提交", 能力id="示例.快",
                            参数={"文本": 123}, 超时秒=30)
        self.assertFalse(类型不符.成功)
        self.assertEqual(类型不符.错误码, "参数不合法")

    def test_取消长任务进入已取消(self) -> None:
        响应 = self.处理(操作="任务提交", 能力id="示例.慢", 参数={}, 超时秒=60)
        self.assertTrue(响应.成功, 响应.错误说明)
        任务id = 响应.值["任务id"]
        取消 = self.处理(操作="任务取消", 参数={"任务id": 任务id})
        self.assertTrue(取消.成功, 取消.错误说明)
        任务 = self.等到终态(任务id)
        self.assertEqual(任务["状态"], "已取消")

    def test_超过任务超时秒判超时(self) -> None:
        响应 = self.处理(操作="任务提交", 能力id="示例.慢", 参数={}, 超时秒=0.4)
        self.assertTrue(响应.成功, 响应.错误说明)
        任务 = self.等到终态(响应.值["任务id"])
        self.assertEqual(任务["状态"], "超时")

    def test_取消尾部只经唯一节点回写状态(self) -> None:
        """结构性判据（K3 反向样本）：`任务系统.取消` 不许再手抄一份状态字段。

        批K 现场：取消尾部手抄了 状态/错误码/错误说明/完成时间/进度 五个字段，**漏了
        `结果`** —— 任务 `6e392e5e99fd485a` 的池快照已写「成功 + 结果齐全」，门面的
        运行库行却永久停在「状态=成功、结果=null、取消标记=true」（取消标记=真 正说明
        这段没走唯一节点：唯一节点会按状态推导该标记）。判据锚**唯一节点的调用**，不锚
        任何说明文字：把那五行手抄改回去，本条立刻变红。
        """
        源 = Path(任务系统模块.__file__).read_text(encoding="utf-8")
        self.assertIn("def 取消(", 源)
        取消段 = 源.split("def 取消(", 1)[1].split("def 查询诊断(", 1)[0]
        self.assertIn("self._应用独立状态已加锁(任务对象, 独立对象)", 取消段,
                      "取消尾部必须调唯一节点回写状态")
        self.assertNotIn("任务对象.状态 = 独立对象.状态", 取消段,
                         "取消尾部不许手抄状态字段（漏一个字段就是批K 那种缺陷）")

    def test_取消之后门面结果不得丢(self) -> None:
        """K3 行为判据：取消（含撞上成功收敛）之后，门面已收敛的 `结果` 不许被抹掉。"""
        响应 = self.处理(操作="任务提交", 能力id="示例.快",
                        参数={"文本": "竞态"}, 超时秒=30)
        self.assertTrue(响应.成功, 响应.错误说明)
        任务id = 响应.值["任务id"]
        任务 = self.等到终态(任务id)
        self.assertEqual(任务["状态"], "成功")
        取消 = self.处理(操作="任务取消", 参数={"任务id": 任务id})
        self.assertTrue(取消.成功, 取消.错误说明)
        之后 = self.处理(操作="任务查询", 参数={"任务id": 任务id}).值
        self.assertEqual(之后["状态"], "成功")
        self.assertEqual(之后["结果"]["回显"], {"文本": "竞态"},
                         "取消不得抹掉已收敛任务的结果（批K：漏 `结果` 的真根因）")

    def test_同步射程不含跨会话历史任务(self) -> None:
        """K2 判据：门面同步射程 = **本会话任务 ∩ 门面未终态**，不含跨会话历史任务。

        批K 现场：旧实现遍历 `任务表` 全长（重启后从运行库加载的历史任务全在里面），
        把只读查询放大成写风暴 —— 249 条逐条查、21 分钟烧 1:46 用户态，一轮遍历远超
        0.5 秒 ⇒ 刚收敛的任务 10.5 分钟轮不到（`任务查询` 一直回「运行中」）。

        判据用**坏快照**做探针（不靠 mock、不打生产成员）：给一条跨会话历史任务放一份
        坏 JSON 快照 —— 同步循环一旦查它，`json.loads` 抛错会走 `_同步循环` 的异常
        分支，**整条同步线程当场停摆**（`同步错误` 记下 `JSONDecodeError`）。故「同步
        错误里没有 JSONDecodeError」且「同步线程仍在跑」同时证明：射程里没有历史任务，
        且同步线程不会被别人的坏快照拖死。
        """
        局部目录 = tempfile.TemporaryDirectory(prefix="射程判据_")
        # 快照根**显式具名**：`实例.进程池.存储目录` 这种「经未知对象取值」的表达式
        # 在 `开发工具/测试写入边界门禁.py` 判据一里解析不出左端基 ⇒ 落「未解析」档
        # 计入违规（fail-closed）。写成 `Path(临时目录.name) / "任务"` 的具名派生后，
        # 左端基解析得到 `tempfile.TemporaryDirectory`（临时落点档）⇒ 判「放行」。
        # 本处只改**写法**，不改任何测试语义（同一个目录、同一个夹具）。
        快照根 = Path(局部目录.name) / "任务"
        实例 = 任务系统模块.任务系统(
            存储目录=快照根,
            运行库路径=str(Path(局部目录.name) / "底座运行.db"))
        注册全部能力(实例, 假后端())
        try:
            历史id = "跨会话历史任务id"
            坏快照 = 快照根 / f"{历史id}.json"
            with 实例.锁:
                实例.任务表[历史id] = 任务系统模块.任务(
                    任务id=历史id, 能力id="示例.快", 状态="运行中")
            坏快照.write_text("{坏 JSON", encoding="utf-8")

            响应 = self.处理(操作="任务提交", 能力id="示例.慢", 参数={}, 超时秒=60)
            self.assertTrue(响应.成功, 响应.错误说明)
            在跑id = 响应.值["任务id"]
            time.sleep(1.5)   # 让同步循环至少跑三轮（0.5 秒一轮）
            self.assertNotIn("JSONDecodeError", 实例.同步错误,
                             "同步循环查了跨会话历史任务的坏快照（射程没跟着改）")
            同步线程 = 实例.同步线程
            self.assertIsNotNone(同步线程, "同步线程必须已启动")
            self.assertTrue(同步线程.is_alive(),
                            "同步线程必须仍在跑（射程没跟着改就会被别人的坏快照打死）")
        finally:
            实例.关闭全部()
            局部目录.cleanup()

    def test_未接入任务系统时不产生任务(self) -> None:
        # 网关把内部 ConnectionError 统一映射为公开错误码「提供者不可用」，
        # 处理() 不向外抛异常；这里锁住「没接任务系统就不会递交任务」。
        裸网关 = 网关核心(假后端)
        响应 = 裸网关.处理(网关请求(操作="任务提交", 能力id="示例.快",
                                   参数={"文本": "你好"}, 超时秒=30))
        self.assertFalse(响应.成功)
        self.assertEqual(响应.错误码, "提供者不可用")


if __name__ == "__main__":
    unittest.main()
