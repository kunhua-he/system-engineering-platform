"""隔离工作区和测试临时资源安全边界与资源清理门禁测试。

覆盖：文件/目录安全清理、保留资源与越界登记拒绝、真实子进程进程组终止、
清理失败证据保留（只读目录）、保留资源与失败证据并存、端口登记与释放、
线程结束验证、句柄关闭验证。全部真实执行，禁止桩。
"""

from __future__ import annotations

import contextlib
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import uuid
from pathlib import Path

系统根 = Path(__file__).resolve().parents[2]
if str(系统根) not in sys.path:
    sys.path.insert(0, str(系统根))

from MCP工具箱.测试资源 import 登记资源, 清理资源


@contextlib.contextmanager
def _临时测试根():
    """受控临时根：必须位于 工程缓存/测试临时/ 下（测试资源安全边界）。"""
    根 = 系统根 / "工程缓存" / "测试临时" / uuid.uuid4().hex[:12]
    根.mkdir(parents=True, exist_ok=True)
    try:
        yield 根
    finally:
        shutil.rmtree(根, ignore_errors=True)


class 工作区与清理测试(unittest.TestCase):
    def test_只清理登记的临时资源(self) -> None:
        with _临时测试根() as 临时目录:
            根 = Path(临时目录)
            资源 = 根 / "临时.txt"
            资源.write_text("临时", encoding="utf-8")
            清单 = 根 / "清单.jsonl"
            登记资源(清单, 资源路径=str(资源), 临时根目录=根)
            结果 = 清理资源(清单, 临时根目录=根)
            self.assertTrue(结果["成功"])
            self.assertEqual(结果["清理数"], 1)
            self.assertEqual(结果["失败表"], [])
            self.assertFalse(资源.exists())

    def test_保留资源不删除且禁止越界登记(self) -> None:
        with _临时测试根() as 临时目录:
            根 = Path(临时目录)
            资源 = 根 / "证据.json"
            资源.write_text("证据", encoding="utf-8")
            清单 = 根 / "清单.jsonl"
            登记资源(清单, 资源路径=str(资源), 临时根目录=根, 保留=True)
            结果 = 清理资源(清单, 临时根目录=根)
            self.assertTrue(结果["成功"])
            self.assertEqual(结果["保留数"], 1, "保留资源必须计入保留数")
            self.assertEqual(结果["清理数"], 0)
            self.assertTrue(资源.exists())
        with self.assertRaises(ValueError):
            登记资源(Path(tempfile.mkdtemp()) / "越界清单.jsonl",
                      资源路径="/tmp/越界资源.txt", 临时根目录=Path(tempfile.mkdtemp()))

    def test_登记并清理真实子进程(self) -> None:
        with _临时测试根() as 临时目录:
            根 = Path(临时目录)
            子进程 = subprocess.Popen(["sleep", "300"], start_new_session=True)
            try:
                self.assertIsNone(子进程.poll(), "子进程必须先真实运行")
                清单 = 根 / "清单.jsonl"
                登记资源(清单, 资源路径=f"子进程:{子进程.pid}", 临时根目录=根,
                          资源类型="子进程", 附加信息={"pid": 子进程.pid})
                结果 = 清理资源(清单, 临时根目录=根)
                self.assertTrue(结果["成功"], 结果["失败表"])
                self.assertEqual(结果["清理数"], 1)
                # 等待 Popen 回收已终止的子进程（回收僵尸），再 ps 验证进程消失
                截止 = time.monotonic() + 5
                while 子进程.poll() is None and time.monotonic() < 截止:
                    time.sleep(0.05)
                self.assertIsNotNone(子进程.poll(), "子进程必须已被终止")
                检查 = subprocess.run(["ps", "-p", str(子进程.pid)],
                                      capture_output=True, text=True)
                self.assertNotEqual(检查.returncode, 0, "ps 必须报告进程不存在")
            finally:
                if 子进程.poll() is None:
                    子进程.kill()
                    子进程.wait()

    def test_清理失败保留证据并返回失败(self) -> None:
        with _临时测试根() as 临时目录:
            根 = Path(临时目录)
            失败目录 = 根 / "只读目录"
            失败目录.mkdir()
            (失败目录 / "内容.txt").write_text("内容", encoding="utf-8")
            os.chmod(失败目录, 0o400)
            try:
                清单 = 根 / "清单.jsonl"
                登记资源(清单, 资源路径=str(失败目录), 临时根目录=根, 资源类型="目录")
                结果 = 清理资源(清单, 临时根目录=根)
                self.assertFalse(结果["成功"], "只读目录清理必须失败")
                self.assertTrue(结果["失败表"], "失败表必须非空")
                self.assertEqual(结果["失败表"][0]["类型"], "目录")
                self.assertTrue(结果["失败表"][0]["原因"], "失败原因必须真实捕获")
                证据路径 = 根 / "清理失败.json"
                self.assertTrue(证据路径.is_file(), "清理失败证据必须存在")
                证据 = json.loads(证据路径.read_text(encoding="utf-8"))
                self.assertTrue(证据["失败"])
                self.assertIn("时间", 证据["失败"][0])
            finally:
                os.chmod(失败目录, 0o700)
                shutil.rmtree(失败目录, ignore_errors=True)

    def test_保留资源与清理失败证据并存(self) -> None:
        with _临时测试根() as 临时目录:
            根 = Path(临时目录)
            保留文件 = 根 / "证据.json"
            保留文件.write_text("证据", encoding="utf-8")
            失败目录 = 根 / "只读目录"
            失败目录.mkdir()
            (失败目录 / "内容.txt").write_text("内容", encoding="utf-8")
            os.chmod(失败目录, 0o400)
            try:
                清单 = 根 / "清单.jsonl"
                登记资源(清单, 资源路径=str(保留文件), 临时根目录=根, 保留=True)
                登记资源(清单, 资源路径=str(失败目录), 临时根目录=根, 资源类型="目录")
                结果 = 清理资源(清单, 临时根目录=根)
                self.assertFalse(结果["成功"])
                self.assertEqual(结果["保留数"], 1)
                self.assertTrue(结果["失败表"])
                self.assertTrue(保留文件.exists(), "保留资源必须仍然存在")
                self.assertFalse((根 / "清单.jsonl").exists(), "清单文件清理后必须删除")
                self.assertTrue((根 / "清理失败.json").is_file(),
                                "失败证据必须保留在临时根目录")
            finally:
                os.chmod(失败目录, 0o700)
                shutil.rmtree(失败目录, ignore_errors=True)

    def test_端口登记与释放(self) -> None:
        with _临时测试根() as 临时目录:
            根 = Path(临时目录)
            监听 = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            监听.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            监听.bind(("127.0.0.1", 0))
            监听.listen(1)
            端口号 = int(监听.getsockname()[1])
            try:
                清单 = 根 / "清单.jsonl"
                登记资源(清单, 资源路径=f"端口:{端口号}", 临时根目录=根,
                          资源类型="端口", 附加信息={"端口": 端口号, "占用pid": os.getpid()})
                监听.close()  # 占用进程是当前进程，先释放本进程句柄
                结果 = 清理资源(清单, 临时根目录=根)
                self.assertTrue(结果["成功"], 结果["失败表"])
                self.assertEqual(结果["清理数"], 1)
                # 端口已释放：可重新绑定并监听
                验证 = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                try:
                    验证.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                    验证.bind(("127.0.0.1", 端口号))
                    验证.listen(1)
                finally:
                    验证.close()
            finally:
                监听.close()

    def test_线程登记清理验证已结束(self) -> None:
        with _临时测试根() as 临时目录:
            根 = Path(临时目录)
            工作线程 = threading.Thread(target=lambda: time.sleep(0.3))
            工作线程.start()
            清单 = 根 / "清单.jsonl"
            登记资源(清单, 资源路径=f"线程:{工作线程.name}", 临时根目录=根,
                      资源类型="线程", 附加信息=工作线程)
            工作线程.join()
            结果 = 清理资源(清单, 临时根目录=根)
            self.assertTrue(结果["成功"], 结果["失败表"])
            self.assertEqual(结果["清理数"], 1)

    def test_线程仍存活清理失败(self) -> None:
        with _临时测试根() as 临时目录:
            根 = Path(临时目录)
            放行 = threading.Event()
            工作线程 = threading.Thread(target=放行.wait)
            工作线程.start()
            try:
                清单 = 根 / "清单.jsonl"
                登记资源(清单, 资源路径=f"线程:{工作线程.name}", 临时根目录=根,
                          资源类型="线程", 附加信息=工作线程)
                结果 = 清理资源(清单, 临时根目录=根)
                self.assertFalse(结果["成功"], "存活线程清理必须失败")
                self.assertTrue(结果["失败表"])
                self.assertIn("仍存活", 结果["失败表"][0]["原因"])
                self.assertTrue((根 / "清理失败.json").is_file())
            finally:
                放行.set()
                工作线程.join()

    def test_句柄登记清理验证已关闭(self) -> None:
        with _临时测试根() as 临时目录:
            根 = Path(临时目录)
            句柄文件 = 根 / "句柄目标.txt"
            句柄文件.write_text("数据", encoding="utf-8")
            句柄 = open(句柄文件, encoding="utf-8")
            try:
                清单 = 根 / "清单.jsonl"
                登记资源(清单, 资源路径=f"句柄:{句柄文件.name}", 临时根目录=根,
                          资源类型="句柄", 附加信息=句柄)
                句柄.close()
                结果 = 清理资源(清单, 临时根目录=根)
                self.assertTrue(结果["成功"], 结果["失败表"])
                self.assertEqual(结果["清理数"], 1)
            finally:
                if not 句柄.closed:
                    句柄.close()

    def test_句柄未关闭清理失败(self) -> None:
        with _临时测试根() as 临时目录:
            根 = Path(临时目录)
            句柄文件 = 根 / "句柄目标.txt"
            句柄文件.write_text("数据", encoding="utf-8")
            句柄 = open(句柄文件, encoding="utf-8")
            try:
                清单 = 根 / "清单.jsonl"
                登记资源(清单, 资源路径=f"句柄:{句柄文件.name}", 临时根目录=根,
                          资源类型="句柄", 附加信息=句柄)
                结果 = 清理资源(清单, 临时根目录=根)
                self.assertFalse(结果["成功"], "未关闭句柄清理必须失败")
                self.assertTrue(结果["失败表"])
                self.assertIn("未关闭", 结果["失败表"][0]["原因"])
            finally:
                句柄.close()


if __name__ == "__main__":
    unittest.main()
