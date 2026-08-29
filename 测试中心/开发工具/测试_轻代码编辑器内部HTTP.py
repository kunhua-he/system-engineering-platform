"""轻代码编辑器内部 HTTP 控制面回归。

验证编辑器保留工程控制能力，但旧公开路径和无内部标记请求均被拒绝。
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

系统根 = Path(__file__).resolve().parents[2]


class Test轻代码编辑器内部HTTP(unittest.TestCase):
    def test_旧路径拒绝_内部路径受标记保护(self) -> None:
        临时根 = Path(tempfile.mkdtemp(prefix="编辑器内部HTTP_"))
        文件 = 临时根 / "页面.json"
        脚本 = """
import sys, threading, webbrowser
from pathlib import Path
webbrowser.open = lambda 地址: True
sys.path.insert(0, sys.argv[1])
from 开发工具.轻代码前端编辑器.启动编辑器 import 主函数
线程 = threading.Thread(target=lambda: 主函数(0, Path(sys.argv[2])), daemon=True)
线程.start()
线程.join()
"""
        进程 = subprocess.Popen(
            [sys.executable, "-u", "-c", 脚本, str(系统根), str(文件)],
            cwd=str(系统根), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True,
        )
        try:
            self.assertIsNotNone(进程.stdout)
            首行 = 进程.stdout.readline().strip()
            self.assertIn("轻代码前端 IDE：http://127.0.0.1:", 首行)
            地址 = 首行.split("；", 1)[0].split("：", 1)[1]

            def 请求(路径: str, 标记: bool = False):
                请求对象 = urllib.request.Request(
                    地址 + urllib.parse.quote(路径),
                    data=json.dumps({"操作": "读取工程"}).encode(),
                    headers={"Content-Type": "application/json", **(
                        {"X-Internal-Call": "1"} if 标记 else {})},
                    method="POST",
                )
                try:
                    with urllib.request.urlopen(请求对象, timeout=2) as 响应:
                        return 响应.status, 响应.read()
                except urllib.error.HTTPError as 错误:
                    return 错误.code, 错误.read()

            self.assertEqual(请求("/工程/请求")[0], 404)
            self.assertEqual(请求("/内部/工程请求")[0], 403)
            状态, 内容 = 请求("/内部/工程请求", 标记=True)
            self.assertEqual(状态, 200)
            self.assertTrue(json.loads(内容)["成功"])
        finally:
            进程.terminate()
            try:
                进程.wait(timeout=3)
            except subprocess.TimeoutExpired:
                进程.kill()
                进程.wait(timeout=3)
            import shutil
            shutil.rmtree(临时根, ignore_errors=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
