"""第二十五阶段wp6：进程/文件系统/临时资源能力补齐测试。

覆盖：文件系统头部读取真实调用、流式摘要大文件分块哈希（复用资源管理）、
临时资源登记清理、进程真实执行（超时/取消/进程组回收/输出上限/零残留）、
已有能力回归断言存在。
"""

from __future__ import annotations

import hashlib
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

if str(Path(__file__).resolve().parents[2]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from 支持库.适配层.本地进程适配器 import 本地进程适配器
from 支持库.后端.文件系统支持库.文件操作 import (
    创建目录, 复制文件, 判断存在, 读取二进制文件, 读取文件, 读取文件头部字节,
    清理全部临时资源, 登记临时资源, 删除文件, 获取大小, 获取修改时间,
    列出目录, 移动文件, 写入文件,
)
from 支持库.后端.系统核心支持库.资源管理 import 创建内容摘要


class Test文件系统补齐(unittest.TestCase):
    def setUp(self):
        self.临时目录 = Path(tempfile.mkdtemp(prefix="测试_进程文件补齐_"))

    def tearDown(self):
        shutil.rmtree(self.临时目录, ignore_errors=True)

    def test_读取文件头部字节真实调用(self):
        """头部读取：只读前 N 字节，不加载全文件；路径越界返回 路径越界。"""
        数据 = bytes(range(256)) * 128  # 32KB
        (self.临时目录 / "大文件.bin").write_bytes(数据)
        结果 = 读取文件头部字节(str(self.临时目录), "大文件.bin", 100)
        self.assertTrue(结果.成功, 结果.错误说明)
        self.assertEqual(结果.值, 数据[:100])
        越界 = 读取文件头部字节(str(self.临时目录), "../逃逸.bin", 10)
        self.assertFalse(越界.成功)
        self.assertEqual(越界.错误码, "路径越界")
        缺失 = 读取文件头部字节(str(self.临时目录), "不存在.bin", 10)
        self.assertFalse(缺失.成功)
        self.assertEqual(缺失.错误码, "文件不存在")

    def test_流式摘要大文件分块哈希(self):
        """流式摘要（复用 系统核心支持库.资源管理.创建内容摘要）：大文件分块哈希正确。"""
        大文件 = self.临时目录 / "分块摘要.bin"
        内容 = os.urandom(3 * 1024 * 1024 + 12345)  # 3MB+，多块读取
        大文件.write_bytes(内容)
        摘要 = 创建内容摘要(大文件)
        self.assertEqual(摘要, hashlib.sha256(内容).hexdigest())

    def test_临时资源登记与清理(self):
        """登记→创建→统一清理→路径消失；重复清理幂等。"""
        资源1 = self.临时目录 / "临时资源1"
        资源2 = self.临时目录 / "临时资源2.txt"
        资源1.mkdir()
        (资源1 / "内部.txt").write_text("x")
        资源2.write_text("y")
        self.assertTrue(登记临时资源(str(资源1)).成功)
        self.assertTrue(登记临时资源(str(资源2)).成功)
        self.assertTrue(清理全部临时资源().成功)
        self.assertFalse(资源1.exists())
        self.assertFalse(资源2.exists())
        self.assertTrue(清理全部临时资源().成功)

    def test_已有文件系统能力回归(self):
        """已有 11 项能力断言存在且可调用。"""
        文件 = self.临时目录 / "回归.txt"
        写入文件(str(文件), "内容")
        self.assertTrue(判断存在(str(文件)))
        self.assertEqual(读取文件(str(文件)).值, "内容")
        self.assertEqual(读取二进制文件(str(self.临时目录), "回归.txt", 1024).值, "内容".encode())
        子目录 = self.临时目录 / "子目录"
        创建目录(str(子目录))
        self.assertIn("回归.txt", 列出目录(str(self.临时目录)).值)
        复制目标 = self.临时目录 / "复制.txt"
        复制文件(str(文件), str(复制目标))
        移动目标 = self.临时目录 / "移动.txt"
        移动文件(str(复制目标), str(移动目标))
        self.assertEqual(获取大小(str(移动目标)).值, len("内容".encode()))
        self.assertGreater(获取修改时间(str(移动目标)).值, 0)
        删除文件(str(移动目标))
        self.assertFalse(判断存在(str(移动目标)))


class Test进程补齐(unittest.TestCase):
    def setUp(self):
        self.临时目录 = Path(tempfile.mkdtemp(prefix="测试_进程补齐_"))

    def tearDown(self):
        shutil.rmtree(self.临时目录, ignore_errors=True)
        """真实执行 python 子进程；输出超过上限→超出限制。"""
        适配器 = 本地进程适配器()
        结果 = 适配器.执行命令受控(
            [sys.executable, "-c", "print('进程输出')"],
            超时秒=10,
        )
        self.assertTrue(结果.成功, 结果.错误说明)
        self.assertIn("进程输出", 结果.值["输出"])
        self.assertEqual(结果.值["退出码"], 0)
        # 输出上限
        超限 = 适配器.执行命令受控(
            [sys.executable, "-c", "print('x' * 5000)"],
            超时秒=10,
            输出上限字节=100,
        )
        self.assertFalse(超限.成功)
        self.assertEqual(超限.错误码, "超出限制")

    def test_进程超时killpg回收与零残留(self):
        """长时间进程超时→killpg 回收→错误码 超时→零残留。"""
        适配器 = 本地进程适配器()
        结果 = 适配器.执行命令受控(
            [sys.executable, "-c", "import time; time.sleep(60)"],
            超时秒=1,
        )
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "超时")
        self.assertIsNone(适配器.运行进程)

    def test_取消运行(self):
        """启动长进程后取消→进程组终止。"""
        适配器 = 本地进程适配器()
        import subprocess
        进程 = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(60)"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            start_new_session=True,
        )
        适配器.运行进程 = 进程
        取消 = 适配器.取消运行()
        self.assertTrue(取消.成功)
        try:
            os.killpg(os.getpgid(进程.pid), 0)
            残留 = True
        except (OSError, ProcessLookupError):
            残留 = False
        self.assertFalse(残留, "进程组应被 killpg 回收，零残留")
        for 流 in (进程.stdin, 进程.stdout, 进程.stderr):
            if 流 is not None:
                流.close()

    def test_进程临时资源登记清理(self):
        """进程产生的临时资源登记→统一清理→消失。"""
        适配器 = 本地进程适配器()
        临时路径 = self.临时目录 / "进程临时"
        临时路径.mkdir()
        (临时路径 / "a.txt").write_text("x")
        适配器.登记临时资源(str(临时路径))
        self.assertTrue(适配器.清理临时资源().成功)
        self.assertFalse(临时路径.exists())
        self.assertTrue(适配器.清理临时资源().成功)

    def test_已有模拟能力回归(self):
        """原有模拟能力（检查可用/版本/生命周期）断言存在。"""
        适配器 = 本地进程适配器()
        self.assertTrue(适配器.检查可用().成功)
        self.assertEqual(适配器.获取版本().值, "模拟1.0.0")
        self.assertTrue(适配器.建立连接().成功)
        self.assertTrue(适配器.执行命令("echo").成功)
        self.assertTrue(适配器.关闭连接().成功)


if __name__ == "__main__":
    unittest.main()
