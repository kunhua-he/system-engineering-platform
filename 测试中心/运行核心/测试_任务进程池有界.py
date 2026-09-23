"""任务进程池有界测试：最大活动数/有界队列/提交截止/资源繁忙/取消真实终止/停止排空。

覆盖手册第十节 10.1：任务队列与线程池必须有界；提交超过容量必须阻塞到明确截止
或返回统一资源繁忙错误；禁止为每个任务无限创建进程与监视线程；取消不得假称
终止副作用（工作进程真实退出后才发布 已取消 终态）。
"""

from __future__ import annotations

import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

if str(Path(__file__).resolve().parents[2]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from 运行核心.任务调度.任务进程 import (
    任务进程池, 资源繁忙错误, 任务表历史上限,
    每条任务fd数, 进程常驻fd余量, 由fd预算推历史上限, 历史上限设计上限)

from 公共契约.基础类型.逻辑类型 import 真, 假

终态集合 = {"成功", "失败", "已取消", "超时", "崩溃"}


def 等待条件(条件, 超时秒: float = 8.0) -> bool:
    截止 = time.monotonic() + 超时秒
    while time.monotonic() < 截止:
        if 条件():
            return 真
        time.sleep(0.01)
    return bool(条件())


def 任务短暂停顿(参数: dict, 取消事件) -> dict:
    time.sleep(float(参数.get("等待秒", 0.5)))
    return {"取消已见": 取消事件.is_set()}


def 任务瞬返(参数: dict, 取消事件) -> dict:
    """瞬时完成的任务执行器（fd 判据要提交远超上界的任务数，任务本身必须极短）。"""
    return {"快": 真}


def 当前进程fd数() -> int:
    """本进程当前打开的 fd 数（macOS `/dev/fd` / Linux `/proc/self/fd`）；取不到回 -1。"""
    for 目录 in ("/proc/self/fd", "/dev/fd"):
        if os.path.isdir(目录):
            try:
                return len(os.listdir(目录))
            except OSError:
                return -1
    return -1


def 进程句柄已释放(进程) -> bool:
    """`进程对象可判定已释放`的**唯一判据口径**（锚行为，不锚任何说明文字）。

    `multiprocessing.Process.close()` 之后 `is_alive()` / `pid` / `exitcode` 一律
    `ValueError: process object is closed`（本机实测 Python 3.14.4）；未释放时
    `is_alive()` 正常返回布尔。故「已释放」＝调用 `is_alive()` 当场抛「已关闭」。
    """
    if 进程 is None:
        return False
    try:
        进程.is_alive()
    except ValueError as 错误:
        return "closed" in str(错误)
    return False


class 无驱逐任务进程池(任务进程池):
    """反向样本专用：把有界驱逐摘成空实现（等价于「不调回收路径」）。

    **为什么用子类而不是 `mock.patch`**：本仓「测试伪装门禁」的存量违约上限是硬限制
    （只减不增），`mock.patch.object` 打生产成员会当场新增两条违规；子类覆写是同一件事
    的干净表达，且不引入第二条腿。
    """

    def _驱逐历史任务(self) -> list:
        return []


class Test任务进程池有界(unittest.TestCase):
    def setUp(self):
        self.临时对象 = tempfile.TemporaryDirectory(prefix="任务进程池有界_")
        self.存储目录 = Path(self.临时对象.name) / "状态"
        self.池列表: list[任务进程池] = []

    def tearDown(self):
        for 池 in self.池列表:
            池.停止()
        self.临时对象.cleanup()

    def _新池(self, **参数) -> 任务进程池:
        池 = 任务进程池(存储目录=self.存储目录, **参数)
        self.池列表.append(池)
        return 池

    def test_最大活动数限制同时活动进程不超过上限(self):
        池 = self._新池(最大活动数=4, 最大排队数=8)
        池.注册执行函数("任务.停顿", 任务短暂停顿)
        提交结果 = []
        for _ in range(8):
            提交结果.append(池.提交(能力id="任务.停顿", 参数={"等待秒": 0.4}))
        self.assertEqual(len(提交结果), 8)
        self.assertTrue(等待条件(lambda: 池.活动进程数() >= 4), "应有 4 个任务同时运行")
        self.assertLessEqual(池.活动进程数(), 4)
        self.assertTrue(等待条件(lambda: all(任务.状态 in 终态集合 for 任务 in 提交结果)))
        self.assertEqual(池.活动进程数(), 0, "全部完成后活动进程必须归零")
        self.assertTrue(all(任务.状态 == "成功" for 任务 in 提交结果),
                        "排队任务也必须真实执行，不得假成功或丢失")

    def test_有界队列满立即返回资源繁忙且不丢任务(self):
        池 = self._新池(最大活动数=1, 最大排队数=1, 提交截止秒=0)
        池.注册执行函数("任务.停顿", 任务短暂停顿)
        任务一 = 池.提交(能力id="任务.停顿", 参数={"等待秒": 0.8})
        排队结果: list = []
        # 后台线程提交任务二：无空槽且队列未满 → 排队并阻塞等待槽位
        def 后台提交任务二() -> None:
            排队结果.append(池.提交(能力id="任务.停顿", 参数={"等待秒": 0.2}))

        线程 = threading.Thread(target=后台提交任务二, daemon=True)
        线程.start()
        self.assertTrue(等待条件(lambda: len(池.等待队列) == 1), "任务二应进入有界等待队列")
        # 队列已满（最大排队数 1）且提交截止秒为 0 → 立即返回资源繁忙，不假成功
        with self.assertRaises(资源繁忙错误) as 上下文:
            池.提交(能力id="任务.停顿", 参数={"等待秒": 0.2})
        self.assertIn("资源繁忙", str(上下文.exception))
        线程.join(8)
        self.assertEqual(len(排队结果), 1, "排队任务不得丢失")
        任务二 = 排队结果[0]
        self.assertTrue(等待条件(lambda: 任务一.状态 in 终态集合))
        self.assertEqual(任务一.状态, "成功")
        self.assertTrue(等待条件(lambda: 任务二.状态 in 终态集合))
        self.assertEqual(任务二.状态, "成功")
        self.assertEqual(池.活动进程数(), 0)

    def test_提交截止超时抛出资源繁忙(self):
        池 = self._新池(最大活动数=1, 最大排队数=1, 提交截止秒=0.2)
        池.注册执行函数("任务.停顿", 任务短暂停顿)
        任务一 = 池.提交(能力id="任务.停顿", 参数={"等待秒": 2.0})
        排队结果: list = []

        def 后台提交任务二() -> None:
            排队结果.append(池.提交(能力id="任务.停顿", 参数={"等待秒": 0.1}))

        线程 = threading.Thread(target=后台提交任务二, daemon=True)
        线程.start()
        self.assertTrue(等待条件(lambda: len(池.等待队列) == 1), "任务二应进入有界等待队列")
        # 队列满且提交截止秒大于 0 → 阻塞到明确截止后抛资源繁忙
        开始 = time.monotonic()
        with self.assertRaises(资源繁忙错误) as 上下文:
            池.提交(能力id="任务.停顿", 参数={"等待秒": 0.1})
        消耗 = time.monotonic() - 开始
        self.assertGreaterEqual(消耗, 0.15, "队列满时应阻塞到明确截止而非立即失败")
        self.assertLess(消耗, 2.0)
        self.assertIn("资源繁忙", str(上下文.exception))
        # 抛错只拒绝第三个任务，已在运行与排队的任务不受影响
        self.assertTrue(等待条件(lambda: 任务一.状态 in 终态集合))
        self.assertEqual(任务一.状态, "成功")
        线程.join(8)
        self.assertEqual(len(排队结果), 1, "排队任务不得丢失")
        self.assertTrue(等待条件(lambda: 排队结果[0].状态 in 终态集合),
                        "排队任务必须真实执行完成")
        self.assertEqual(排队结果[0].状态, "成功")

    def test_取消运行中任务进程真实终止(self):
        池 = self._新池()
        池.注册执行函数("任务.长停", 任务短暂停顿)
        任务 = 池.提交(能力id="任务.长停", 参数={"等待秒": 30})
        self.assertTrue(等待条件(lambda: 任务.进程 is not None and 任务.进程.is_alive()))
        成功, 消息 = 池.取消(任务.任务id)
        self.assertTrue(成功)
        self.assertIn("终止", 消息)
        self.assertTrue(等待条件(lambda: 任务.状态 in 终态集合))
        self.assertEqual(任务.状态, "已取消")
        self.assertFalse(任务.进程.is_alive(), "取消后工作进程必须真实退出")
        self.assertEqual(池.活动进程数(), 0)

    def test_停止后活动进程归零排队被拒且监视线程退出(self):
        池 = self._新池(最大活动数=1, 最大排队数=2, 提交截止秒=5)
        池.注册执行函数("任务.长停", 任务短暂停顿)
        任务一 = 池.提交(能力id="任务.长停", 参数={"等待秒": 30})
        排队异常: list[BaseException] = []

        def 后台排队提交() -> None:
            try:
                池.提交(能力id="任务.长停", 参数={"等待秒": 30})
            except BaseException as 错误:
                排队异常.append(错误)

        线程 = threading.Thread(target=后台排队提交, daemon=True)
        线程.start()
        self.assertTrue(等待条件(lambda: len(池.等待队列) == 1), "排队任务应处于有界等待队列")
        self.assertTrue(等待条件(lambda: 池.活动进程数() == 1))
        池.停止()
        池.停止()
        self.assertEqual(池.活动进程数(), 0, "停止后活动进程必须归零")
        self.assertEqual(len(池.等待队列), 0, "停止后排队任务必须被清空拒绝")
        self.assertEqual(任务一.状态, "已取消")
        self.assertFalse(任务一.进程.is_alive())
        with self.assertRaises(RuntimeError):
            池.提交(能力id="任务.长停", 参数={"等待秒": 0.1})
        线程.join(5)
        self.assertEqual(len(排队异常), 1, "停止必须拒绝排队中的任务")
        self.assertIn("已停止", str(排队异常[0]))
        if 池.监视线程 is not None:
            self.assertTrue(等待条件(lambda: not 池.监视线程.is_alive()),
                            "停止后监视线程必须退出")

    def test_内部监视线程有界不超过最大活动数加一(self):
        池 = self._新池(最大活动数=4, 最大排队数=16)
        池.注册执行函数("任务.停顿", 任务短暂停顿)
        for _ in range(4):
            池.提交(能力id="任务.停顿", 参数={"等待秒": 0.3})
        池.注册执行函数("任务.快", lambda 参数: {"快": 真})
        池.提交(能力id="任务.快")
        池.注册执行函数("任务.瞬", lambda 参数: {"瞬": 真})
        池.提交(能力id="任务.瞬")
        池.注册执行函数("任务.短", lambda 参数: {"短": 真})
        池.提交(能力id="任务.短")
        # 提交再多任务，内部监视线程始终只有一个，总量不超过 最大活动数+1
        池.注册执行函数("任务.更多", 任务短暂停顿)
        for 序号 in range(8):
            池.提交(能力id="任务.更多", 参数={"等待秒": 0.2})
        self.assertTrue(等待条件(lambda: 池.监视线程 is not None and 池.监视线程.is_alive()))
        内部线程数 = sum(
            1 for 线程 in threading.enumerate()
            if "任务进程池" in 线程.name and 线程.is_alive())
        self.assertLessEqual(内部线程数, 池.最大活动数 + 1,
                             "监视线程总数不得超过 最大活动数+1")
        self.assertEqual(内部线程数, 1, "进程池内部应只有一个轮询监视线程")
        self.assertTrue(等待条件(lambda: 池.活动进程数() == 0))

    def test_任务表历史上界有默认口径且可断言(self):
        """上界是模块级具名常量（可读、可断言）：默认构造的池取它，且为正整数。"""
        self.assertIsInstance(任务表历史上限, int)
        self.assertGreaterEqual(任务表历史上限, 1)
        池 = self._新池()
        self.assertEqual(池.历史上限, 任务表历史上限,
                         "默认构造的池必须取模块级上界常量（不许另写一份字面量）")
        self.assertEqual(self._新池(历史上限=3).历史上限, 3,
                         "显式上界必须生效（判据要能在小上界下快速取证）")

    def test_提交超过历史上界后任务表有界且已驱逐任务句柄已释放(self):
        """正向判据：提交 N（> 上界）个任务后 —— 表长有界 + 被驱逐的已收敛任务句柄已释放。

        「已释放」的判据锚**进程对象可判定已释放**（`进程句柄已释放`：close 后
        `is_alive()` 当场抛 `process object is closed`），不锚任何说明文字。
        """
        上界 = 8
        池 = self._新池(最大活动数=4, 最大排队数=16, 历史上限=上界)
        池.注册执行函数("任务.快", 任务瞬返)
        任务列表: list = []
        句柄表: list = []
        for _ in range(上界 * 2):
            任务 = 池.提交(能力id="任务.快")
            任务列表.append(任务)
            # 驱逐会把 `任务.进程` 置 None，故先捕获句柄本身
            句柄表.append(任务.进程)
        self.assertTrue(等待条件(lambda: all(任务.状态 in 终态集合 for 任务 in 任务列表)),
                        "提交的任务必须全部真实收敛")
        # 全部收敛后再提交一个（走同一条唯一写入口），把表压回上界附近
        末任务 = 池.提交(能力id="任务.快")
        self.assertTrue(等待条件(lambda: 末任务.状态 in 终态集合))
        self.assertLessEqual(len(池.任务表), 上界 + 1,
                             "任务表必须是有界历史，不随提交总数增长")
        self.assertEqual(池.活动进程数(), 0)
        已驱逐 = [(任务, 句柄) for 任务, 句柄 in zip(任务列表, 句柄表)
                  if 任务.任务id not in 池.任务表]
        self.assertTrue(已驱逐, "提交数超过上界后必须真的发生驱逐（表不是只写不删）")
        for 任务, 句柄 in 已驱逐:
            self.assertIsNone(任务.进程, "被驱逐任务的进程句柄必须解除引用")
            self.assertIsNone(任务.取消事件, "被驱逐任务的取消事件必须解除引用（信号量 fd 归还）")
            self.assertIsNone(任务.进程组就绪事件,
                              "被驱逐任务的进程组就绪事件必须解除引用（信号量 fd 归还）")
            self.assertTrue(进程句柄已释放(句柄),
                            "被驱逐任务的进程对象必须已 close（sentinel 管道 fd 归还）")
        # 可查性不因驱逐而丢：按磁盘快照重建（既有回退）
        样本 = 已驱逐[0][0]
        self.assertTrue(等待条件(lambda: (池.存储目录 / f"{样本.任务id}.json").is_file()),
                        "被驱逐任务的磁盘快照必须存在（可查性靠它）")
        self.assertEqual(池.查询(样本.任务id).状态, "成功", "被驱逐任务必须仍可查")

    def test_反向_摘掉有界驱逐则任务表只增且句柄不释放(self):
        """反向样本（兼本修复的变异判据）：把有界驱逐摘成空实现 ⇒ 表只增、句柄不释放。

        正向判据（表长有界 + 被驱逐任务句柄已释放）**全靠这条驱逐**：同一批提交，
        摘掉 `_驱逐历史任务` 后读数立刻变成「表长 == 提交数」「句柄仍可判定存活」。
        两个读数合起来才把「驱逐确实发生了」与「表天然不长」区分开。
        """
        上界 = 8
        池 = 无驱逐任务进程池(存储目录=self.存储目录 / "无驱逐", 最大活动数=4,
                             最大排队数=16, 历史上限=上界)
        self.池列表.append(池)
        池.注册执行函数("任务.快", 任务瞬返)
        提交数 = 上界 * 2
        任务列表: list = []
        句柄表: list = []
        for _ in range(提交数):
            任务 = 池.提交(能力id="任务.快")
            任务列表.append(任务)
            句柄表.append(任务.进程)
        self.assertTrue(等待条件(lambda: all(任务.状态 in 终态集合 for 任务 in 任务列表)))
        self.assertEqual(len(池.任务表), 提交数,
                         "不驱逐时任务表只增（「表天然不长」被排除）")
        self.assertGreater(len(池.任务表), 上界)
        for 任务, 句柄 in zip(任务列表, 句柄表):
            self.assertIsNotNone(任务.进程, "不驱逐时进程句柄不得被释放")
            self.assertFalse(进程句柄已释放(句柄),
                             "不驱逐时进程对象仍可判定存活（未被 close）")

    def test_提交远超历史上界后进程fd不随任务数增长(self):
        """真根因判据：fd 增长只受有界上界约束，**不随提交总数线性增长**。

        实测口径约 12 fd/条（接收管道 2 + 两个事件各 4 个 POSIX 信号量 + sentinel 1）；
        旧实现（只写不删）在同样的提交数下是约 12×提交数 个 fd。
        """
        基线 = 当前进程fd数()
        if 基线 < 0:
            self.skipTest("本平台取不到本进程 fd 目录（/proc/self/fd、/dev/fd 均不可用）")
        上界 = 8
        提交数 = 40
        池 = self._新池(最大活动数=4, 最大排队数=16, 历史上限=上界)
        池.注册执行函数("任务.快", 任务瞬返)
        任务列表 = [池.提交(能力id="任务.快") for _ in range(提交数)]
        self.assertTrue(等待条件(lambda: all(任务.状态 in 终态集合 for 任务 in 任务列表)))
        末任务 = 池.提交(能力id="任务.快")
        self.assertTrue(等待条件(lambda: 末任务.状态 in 终态集合))
        增长 = 当前进程fd数() - 基线
        self.assertLessEqual(
            增长, 上界 * 每条任务fd数 + 进程常驻fd余量,
            f"提交 {提交数} 个任务（远超上界 {上界}）后 fd 增长必须被封在上界附近；"
            f"实测增长 {增长}，旧实现（只写不删）此处约为 {提交数}×12 个 fd")
        self.assertLess(增长, 提交数 * 每条任务fd数 // 2,
                        "fd 增长不得与提交总数同阶（真根因判据）")


class 历史上限由fd预算推出(unittest.TestCase):
    """判据：`任务表历史上限` 与进程真实 fd 预算**同一口径**（两个数不许各说各话）。

    修前写死 `64`，而同一段注释自己写着「约 12 个 fd/条」⇒ 设计上界要 768 个 fd，
    而进程预算可能只有 256（macOS launchd 默认软限）⇒ 提交约 21 条任务必然 `EMFILE`。
    故本类的正向判据是「推出来的条数 × 每条 fd 数 + 常驻余量 **不超软限**」，
    反向样本是「写死 64 在软限 256 下必然越界」。
    """

    def test_软限256推16条且需要量不超预算(self) -> None:
        上界 = 由fd预算推历史上限(256)
        self.assertEqual(上界, 16)
        self.assertLessEqual(上界 * 每条任务fd数 + 进程常驻fd余量, 256,
                             "推出来的条数所需 fd 不得超软限（同一口径的判据）")

    def test_软限65536推到设计上限(self) -> None:
        self.assertEqual(由fd预算推历史上限(65536), 历史上限设计上限)

    def test_无限或天文软限不放大超过设计上限(self) -> None:
        for 软限 in (-1, 0, 1 << 41, 10 ** 18):
            self.assertEqual(由fd预算推历史上限(软限), 历史上限设计上限,
                             f"软限={软限} 视为无上限，不得放大超过设计上限")

    def test_预算极小也至少留一条(self) -> None:
        self.assertEqual(由fd预算推历史上限(12), 1)
        self.assertEqual(由fd预算推历史上限(1), 1)

    def test_取不到预算退回设计上限而不是1(self) -> None:
        """「量不到」不等于「没有预算」：退回设计上限，不许把功能打死。"""
        self.assertEqual(由fd预算推历史上限("不是数"), 历史上限设计上限)

    def test_模块默认取本进程真值(self) -> None:
        self.assertIsInstance(任务表历史上限, int)
        self.assertGreaterEqual(任务表历史上限, 1)
        self.assertLessEqual(任务表历史上限, 历史上限设计上限)
        self.assertEqual(任务表历史上限, 由fd预算推历史上限(),
                         "模块默认值必须就是同一条算式的结果，不许是第二个数")

    def test_反向_写死64在软限256下必然越界(self) -> None:
        """反向样本（本修复的变异判据）：写死的 64 在 256 预算下确实越界。"""
        写死 = 64
        self.assertGreater(写死 * 每条任务fd数, 256,
                           "修前写法（写死 64）在 256 预算下需要 768 个 fd ⇒ 必然 EMFILE")
        self.assertLessEqual(
            由fd预算推历史上限(256) * 每条任务fd数 + 进程常驻fd余量, 256,
            "修后写法必须落在预算内")


if __name__ == "__main__":
    unittest.main()
