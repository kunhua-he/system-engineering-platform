"""P1-10：LibreOffice 受管有界工作池回归测试。"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import threading
import time
import unittest
import urllib.parse
import urllib.request
from pathlib import Path
from unittest import mock

系统根 = Path(__file__).resolve().parents[2]
if str(系统根) not in sys.path:
    sys.path.insert(0, str(系统根))

from 公共契约.运行时.进程终止 import 进程存活


假程序源码 = r'''#!/usr/bin/env python3
import json
import os
import sys
import time
from pathlib import Path

参数 = sys.argv[1:]
配置档 = next((项.split("=", 1)[1] for 项 in 参数 if 项.startswith("-env:UserInstallation=")), "")
输出目录 = Path(参数[参数.index("--outdir") + 1])
目标格式 = 参数[参数.index("--convert-to") + 1]
输入路径 = Path(参数[-1])
日志路径 = os.environ.get("FAKE_LO_LOG", "")

def 记录(事件):
    if not 日志路径:
        return
    内容 = json.dumps({"事件": 事件, "pid": os.getpid(), "配置档": 配置档,
                       "输入": str(输入路径)}, ensure_ascii=False) + "\n"
    句柄 = os.open(日志路径, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    try:
        os.write(句柄, 内容.encode("utf-8"))
    finally:
        os.close(句柄)

记录("开始")
time.sleep(float(os.environ.get("FAKE_LO_DELAY", "0")))
退出码 = int(os.environ.get("FAKE_LO_EXIT_CODE", "0"))
if 退出码:
    sys.exit(退出码)
输出目录.mkdir(parents=True, exist_ok=True)
输出路径 = 输出目录 / f"{输入路径.stem}.{目标格式}"
输出路径.write_text(输入路径.read_text(encoding="utf-8"), encoding="utf-8")
记录("结束")
'''


class 测试LibreOffice受管池(unittest.TestCase):
    def setUp(self):
        self.临时根 = Path(tempfile.mkdtemp(prefix="测试_lo_pool_"))
        self.假程序 = self.临时根 / "假soffice"
        self.假程序.write_text(假程序源码, encoding="utf-8")
        self.假程序.chmod(0o700)
        self.日志 = self.临时根 / "调用.jsonl"
        self.池列表 = []

    def tearDown(self):
        for 池 in self.池列表:
            池.关闭()
        shutil.rmtree(self.临时根, ignore_errors=True)

    def _新建池(self, *, 池大小=2, 队列长度=8, 排队超时秒=1.0):
        from 支持库.适配层.LibreOffice提供者.实现.文档转换 import LibreOffice受管池
        池 = LibreOffice受管池(
            str(self.假程序), 池大小=池大小, 等待队列长度=队列长度,
            排队超时秒=排队超时秒,
        )
        self.池列表.append(池)
        return 池

    def _输入(self, 名称, 内容="受管池转换内容"):
        路径 = self.临时根 / 名称
        路径.write_text(内容, encoding="utf-8")
        return 路径

    def _读取日志(self):
        if not self.日志.exists():
            return []
        return [json.loads(行) for 行 in self.日志.read_text(encoding="utf-8").splitlines() if 行]

    def _等待日志数(self, 数量, 超时秒=2.0):
        截止 = time.monotonic() + 超时秒
        while time.monotonic() < 截止:
            if len(self._读取日志()) >= 数量:
                return
            time.sleep(0.01)
        self.fail(f"日志未在时限内达到 {数量} 条")

    def test_每个池成员使用服务端生成的独立配置档且关闭后清理(self):
        池 = self._新建池(池大小=2)
        键一 = "资源一"
        键二 = next(f"资源{序号}" for 序号 in range(2, 100)
                  if 池._选择成员序号(f"资源{序号}") != 池._选择成员序号(键一))
        输入一 = self._输入("一.docx")
        输入二 = self._输入("二.docx")
        结果表 = []
        with mock.patch.dict(os.environ, {"FAKE_LO_LOG": str(self.日志), "FAKE_LO_DELAY": "0.1"}):
            线程一 = threading.Thread(target=lambda: 结果表.append(池.执行(
                str(输入一), "txt", 资源键=键一, 超时秒=2, 最大输出字节=1024)))
            线程二 = threading.Thread(target=lambda: 结果表.append(池.执行(
                str(输入二), "txt", 资源键=键二, 超时秒=2, 最大输出字节=1024)))
            线程一.start(); 线程二.start(); 线程一.join(); 线程二.join()
        self.assertTrue(all(项.成功 for 项 in 结果表), [项.错误说明 for 项 in 结果表])
        配置档列表 = [项["配置档"] for 项 in self._读取日志() if 项["事件"] == "开始"]
        self.assertEqual(len(set(配置档列表)), 2)
        self.assertTrue(all(项.startswith("file://") for 项 in 配置档列表))
        配置档路径 = [Path(urllib.request.url2pathname(urllib.parse.urlparse(项).path))
                 for 项 in 配置档列表]
        self.assertTrue(all(项.is_dir() for 项 in 配置档路径))
        根目录 = 池._根目录
        池.关闭()
        self.assertFalse(根目录.exists())
        self.assertTrue(all(not 项.exists() for 项 in 配置档路径))

    def test_活动子进程不超过固定池大小(self):
        池 = self._新建池(池大小=2, 队列长度=10, 排队超时秒=2.0)
        键一 = "资源一"
        键二 = next(f"资源{序号}" for 序号 in range(2, 100)
                  if 池._选择成员序号(f"资源{序号}") != 池._选择成员序号(键一))
        输入列表 = [self._输入(f"并发{序号}.docx") for 序号 in range(8)]
        结果表 = []
        with mock.patch.dict(os.environ, {"FAKE_LO_LOG": str(self.日志), "FAKE_LO_DELAY": "0.12"}):
            线程列表 = [threading.Thread(target=lambda 路径=路径, 序号=序号: 结果表.append(
                池.执行(str(路径), "txt", 资源键=键一 if 序号 % 2 == 0 else 键二,
                       超时秒=2, 最大输出字节=1024)))
                for 序号, 路径 in enumerate(输入列表)]
            for 线程 in 线程列表: 线程.start()
            for 线程 in 线程列表: 线程.join()
        self.assertEqual(len(结果表), 8)
        self.assertTrue(all(项.成功 for 项 in 结果表), [项.错误码 for 项 in 结果表])
        当前 = 0
        峰值 = 0
        for 项 in self._读取日志():
            当前 += 1 if 项["事件"] == "开始" else -1
            峰值 = max(峰值, 当前)
        self.assertLessEqual(峰值, 2)
        self.assertEqual(峰值, 2)

    def test_等待队列满返回结构化限流(self):
        池 = self._新建池(池大小=1, 队列长度=1, 排队超时秒=2)
        输入一 = self._输入("占用.docx")
        输入二 = self._输入("排队.docx")
        输入三 = self._输入("限流.docx")
        结果表 = []
        with mock.patch.dict(os.environ, {"FAKE_LO_LOG": str(self.日志), "FAKE_LO_DELAY": "0.5"}):
            线程一 = threading.Thread(target=lambda: 结果表.append(
                池.执行(str(输入一), "txt", 资源键="同一资源", 超时秒=2, 最大输出字节=1024)))
            线程一.start()
            self._等待日志数(1)
            线程二 = threading.Thread(target=lambda: 结果表.append(
                池.执行(str(输入二), "txt", 资源键="同一资源", 超时秒=2, 最大输出字节=1024)))
            线程二.start()
            time.sleep(0.05)
            限流结果 = 池.执行(str(输入三), "txt", 资源键="同一资源",
                             超时秒=2, 最大输出字节=1024)
            线程一.join(); 线程二.join()
        self.assertFalse(限流结果.成功)
        self.assertEqual(限流结果.错误码, "限流")
        self.assertTrue(限流结果.可重试)
        self.assertEqual(限流结果.详细信息["池大小"], 1)
        self.assertEqual(限流结果.详细信息["等待队列长度"], 1)
        self.assertNotIn("配置档", json.dumps(限流结果.转字典(), ensure_ascii=False))

    def test_超时强杀进程组并清理作业临时目录(self):
        池 = self._新建池(池大小=1)
        输入 = self._输入("超时.docx")
        with mock.patch.dict(os.environ, {"FAKE_LO_LOG": str(self.日志), "FAKE_LO_DELAY": "30"}):
            结果 = 池.执行(str(输入), "txt", 资源键="超时资源",
                         超时秒=0.4, 最大输出字节=1024)
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "超时")
        日志 = self._读取日志()
        self.assertEqual(len(日志), 1)
        子进程pid = 日志[0]["pid"]
        截止 = time.monotonic() + 2
        while time.monotonic() < 截止:
            # 探活一律走收口层：Windows 上裸用 os.kill(pid, 0) 会真把目标进程结束掉
            # （os.kill 对非控制台信号走 TerminateProcess），不能用来当「探活」
            if not 进程存活(子进程pid):
                break
            time.sleep(0.02)
        else:
            self.fail("超时后子进程仍存活")
        self.assertEqual(list((池._根目录 / "作业").iterdir()), [])

    def test_关闭回收进行中的进程组配置档和临时目录(self):
        池 = self._新建池(池大小=1, 队列长度=2)
        输入 = self._输入("关闭中.docx")
        结果表 = []
        with mock.patch.dict(os.environ, {"FAKE_LO_LOG": str(self.日志), "FAKE_LO_DELAY": "30"}):
            线程 = threading.Thread(target=lambda: 结果表.append(
                池.执行(str(输入), "txt", 资源键="关闭资源",
                       超时秒=60, 最大输出字节=1024)))
            线程.start()
            self._等待日志数(1)
            子进程pid = self._读取日志()[0]["pid"]
            根目录 = 池._根目录
            池.关闭()
            线程.join(timeout=3)
        self.assertFalse(线程.is_alive())
        self.assertFalse(根目录.exists())
        # 探活走收口层（Windows 上 os.kill(pid, 0) 会真杀进程，不可用作探活）
        self.assertFalse(进程存活(子进程pid), "关闭后子进程仍存活")

    def test_子进程异常退出后清理作业临时目录(self):
        池 = self._新建池(池大小=1)
        输入 = self._输入("异常.docx")
        with mock.patch.dict(os.environ, {"FAKE_LO_LOG": str(self.日志),
                                          "FAKE_LO_EXIT_CODE": "7"}):
            结果 = 池.执行(str(输入), "txt", 资源键="异常资源",
                         超时秒=2, 最大输出字节=1024)
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "转换失败")
        self.assertEqual(list((池._根目录 / "作业").iterdir()), [])

    def test_公开转换结果不泄漏内部配置档(self):
        from 支持库.适配层.LibreOffice提供者 import 转换办公文件
        from 支持库.适配层.LibreOffice提供者.实现 import 文档转换 as 模块
        输入 = self._输入("公开契约.docx")
        # **真实状态注入**：走生产自带的提供者解析路径 `LIBREOFFICE_BIN`
        # （`查找LibreOffice` 的第一候选，经 `shutil.which` 真实解析），不再
        # `mock.patch.object(模块, "_提供者缓存", …)` —— 那被 `测试伪装门禁` 规则1
        # 判为「patch 被测对象本体·本体成员」（P1）。`_提供者缓存` 是纯备忘（查一次
        # 存一次），清空只让它重查一次、语义无副作用；不清会把上一用例的路径盖住环境变量。
        模块._提供者缓存.clear()
        with mock.patch.dict(os.environ, {
                "LIBREOFFICE_BIN": str(self.假程序),
                "FAKE_LO_LOG": str(self.日志), "LIBREOFFICE_POOL_SIZE": "1",
                "LIBREOFFICE_QUEUE_SIZE": "1", "FAKE_LO_DELAY": "0",
        }):
            try:
                结果 = 转换办公文件(str(输入), "txt", 超时秒=2, 最大输出字节=1024)
            finally:
                模块.关闭受管池()
                模块._提供者缓存.clear()
        self.assertTrue(结果.成功, 结果.错误说明)
        公开文本 = json.dumps(结果.转字典(), ensure_ascii=False)
        self.assertNotIn("UserInstallation", 公开文本)
        self.assertNotIn("配置档", 公开文本)
        self.assertNotIn("profile", 公开文本.lower())


if __name__ == "__main__":
    unittest.main()
