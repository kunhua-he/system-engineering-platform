"""第十四阶段 P1-16 容量与资源基线真实测试。

真实采样：40 个句柄打开后句柄数真实增加、线程数等于当前真实线程数、
临时文件写入后占用真实增长、ps 不可用返回错误码不崩溃；超限处理真实
执行拒绝/排空等待/优雅释放/证据追加（历史不覆盖）；连续超限 3 次熔断
后该执行单元全部调用被拒。所有临时文件与句柄用完即清理。
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

系统根 = Path(__file__).resolve().parents[3]
if str(系统根) not in sys.path:
    sys.path.insert(0, str(系统根))
from 启动监督器.容量基线 import 必需基线字段, 容量基线


def 全大基线() -> dict:
    """足够大的合法基线：默认不触发超限。"""
    return {字段: 10 ** 9 for 字段 in 必需基线字段}


class 测试容量基线(unittest.TestCase):
    def setUp(self):
        self._临时 = tempfile.TemporaryDirectory(prefix="工作包16_")
        self._目录 = self._临时.name
        self._证据文件 = Path(self._目录) / "证据.jsonl"
        self.容量 = 容量基线(证据文件=self._证据文件, 临时目录=self._目录,
                           熔断阈值=3, 排空超时秒=5.0)

    def tearDown(self):
        self._临时.cleanup()

    def test_声明基线_合法通过非法拒绝(self):
        通过, 消息 = self.容量.声明基线(全大基线())
        self.assertTrue(通过, 消息)
        缺字段 = {键: 值 for 键, 值 in 全大基线().items() if 键 != "线程上限"}
        通过, 消息 = self.容量.声明基线(缺字段)
        self.assertFalse(通过, "缺字段必须拒绝")
        self.assertIn("缺少必需字段", 消息)
        for 非法 in ({"内存上限MB": -1}, {"线程上限": 0}, {"队列长度上限": "十"}):
            基线 = 全大基线()
            基线.update(非法)
            通过, 消息 = self.容量.声明基线(基线)
            self.assertFalse(通过, f"非法值必须拒绝: {非法}")
            self.assertIn("非法", 消息)

    def test_实测采样_句柄真实增加线程数真实(self):
        前 = self.容量.实测采样()
        self.assertTrue(前["成功"], 前["错误说明"])
        self.assertEqual(前["线程数"], len(threading.enumerate()),
                         "线程数必须等于当前真实线程数")
        已开: list[int] = []
        try:
            for _ in range(40):
                已开.append(os.open("/dev/null", os.O_RDONLY))
            后 = self.容量.实测采样()
        finally:
            for 句柄 in 已开:
                os.close(句柄)
        self.assertTrue(后["成功"], 后["错误说明"])
        self.assertGreaterEqual(后["文件句柄数"] - 前["文件句柄数"], 40,
                                "打开 40 个句柄后句柄采样必须真实增加")

    def test_对比基线_线程上限一而当前线程多返回超限列表(self):
        基线 = 全大基线()
        基线["线程上限"] = 1
        通过, 消息 = self.容量.声明基线(基线)
        self.assertTrue(通过, 消息)
        事件 = threading.Event()

        def 驻留():
            事件.wait(5)

        线程 = threading.Thread(target=驻留)
        线程.start()
        try:
            self.assertGreaterEqual(len(threading.enumerate()), 2, "驻留线程必须使线程数≥2")
            超限项 = self.容量.对比基线()
        finally:
            事件.set()
            线程.join(timeout=5)
        self.assertTrue(超限项, "线程上限=1 而当前线程≥2 必须返回超限项")
        线程项 = [项 for 项 in 超限项 if 项["字段"] == "线程数"]
        self.assertTrue(线程项, "超限项必须包含线程数")
        self.assertGreater(线程项[0]["实测值"], 线程项[0]["声明值"])

    def test_超限处理_拒绝排空证据追加且历史不覆盖(self):
        self.容量.声明基线(全大基线())
        释放标志: list[bool] = []
        self.容量.注册释放回调("单元甲", lambda 单元id: 释放标志.append(True))

        def 活动任务():
            self.容量.登记活动任务("单元甲", 1)
            time.sleep(0.4)
            self.容量.登记活动任务("单元甲", -1)

        线程 = threading.Thread(target=活动任务)
        线程.start()
        self.assertTrue(self.容量.尝试接收("单元甲")["成功"], "停止接收前必须可接收")
        开始 = time.time()
        结果 = self.容量.超限处理("单元甲")
        耗时 = time.time() - 开始
        self.assertTrue(结果["停止接收"])
        self.assertTrue(结果["排空"]["完成"], f"活动任务必须真实排空: {结果}")
        self.assertGreaterEqual(耗时, 0.3, "排空必须真实等待活动任务结束")
        self.assertEqual(释放标志, [True], "优雅释放回调必须被真实调用")
        被拒 = self.容量.尝试接收("单元甲")
        self.assertFalse(被拒["成功"], "停止接收后必须拒绝新任务")
        self.assertGreaterEqual(被拒["拒绝计数"], 1, "拒绝必须真实计数")
        线程.join(timeout=5)
        self.assertFalse(线程.is_alive(), "活动任务线程必须已结束")
        行表 = self._证据文件.read_text(encoding="utf-8").strip().splitlines()
        self.assertEqual(len(行表), 1, "第一次超限处理只应有一条证据")
        第一条 = json.loads(行表[0])
        self.assertEqual(第一条["执行单元"], "单元甲")
        self.assertIn("请求优雅释放", 第一条["处理步骤"])
        self.assertEqual(第一条["连续超限"], 1)
        self.容量.超限处理("单元乙")
        行表 = self._证据文件.read_text(encoding="utf-8").strip().splitlines()
        self.assertEqual(len(行表), 2, "证据必须追加而非覆盖历史")
        self.assertEqual(json.loads(行表[1])["执行单元"], "单元乙")

    def test_连续超限三次熔断后续调用被拒(self):
        self.容量.声明基线(全大基线())
        for _ in range(3):
            结果 = self.容量.超限处理("单元熔")
        self.assertEqual(结果["结果"], "熔断", "连续超限 3 次后必须熔断")
        熔断状态 = self.容量.熔断状态("单元熔")
        self.assertTrue(熔断状态["熔断"])
        self.assertIn("熔断阈值", 熔断状态["原因"])
        接收 = self.容量.尝试接收("单元熔")
        self.assertFalse(接收["成功"], "熔断后调用必须被拒")
        self.assertIn("熔断", 接收["原因"])
        再次处理 = self.容量.超限处理("单元熔")
        self.assertEqual(再次处理["结果"], "熔断", "熔断后超限处理直接返回熔断")
        self.容量.解除熔断("单元熔")
        self.assertFalse(self.容量.熔断状态("单元熔")["熔断"], "解除熔断后必须恢复")
        self.assertTrue(self.容量.尝试接收("单元熔")["成功"], "解除熔断后必须可接收")

    def test_临时空间采样真实求和(self):
        self.容量.声明基线(全大基线())
        前 = self.容量.实测采样()
        写入字节 = 5 * 1024 * 1024
        with open(os.path.join(self._目录, "大文件.bin"), "wb") as 文件:
            文件.write(b"x" * 写入字节)
        后 = self.容量.实测采样()
        self.assertGreaterEqual(后["临时空间字节"] - 前["临时空间字节"], 写入字节,
                                "写入 5MB 后临时空间占用必须真实增长")

    @unittest.skipUnless(sys.platform == "darwin", "macOS 专用：验证 ps 不可用错误码")
    def test_采样失败_ps不可用返回错误码不崩溃(self):
        容量 = 容量基线(证据文件=self._证据文件, 临时目录=self._目录, ps命令="/不存在/ps")
        采样 = 容量.实测采样()
        self.assertFalse(采样["成功"], "ps 不可用时采样必须返回失败")
        self.assertIn("内存采样失败", 采样["错误码"])
        self.assertIn("ps 不可用", 采样["错误说明"])
        容量.声明基线(全大基线())
        超限项 = 容量.对比基线()
        self.assertTrue(超限项, "内存采样失败必须如实标记为超限项而非崩溃")
        内存项 = [项 for 项 in 超限项 if 项["字段"] == "内存MB"]
        self.assertTrue(内存项)
        self.assertTrue(内存项[0]["采样失败"])
        self.assertGreaterEqual(容量.实测采样()["线程数"], 1, "其他采样项不受影响")


if __name__ == "__main__":
    unittest.main(verbosity=2)
