"""轻代码编辑器内部 HTTP 控制面回归。

验证编辑器保留工程控制能力，但旧公开路径、无令牌请求与旧固定内部标记均被拒绝。

口径变更（实现已改，测试按新契约对齐）：内部路径的保护从**固定内部标记**
`X-Internal-Call: 1` 换成**每次启动随机生成的动态会话令牌**（请求头 `X-IDE-Token`），
令牌只注入本进程服务出去的页面（`const 会话令牌='…'`）。测试从首页取本次令牌，
并反向断言旧的固定标记已失效。
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
import unittest
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

系统根 = Path(__file__).resolve().parents[2]

# 本机 http_proxy/https_proxy 指向 127.0.0.1:4780（ClashX），而 urllib 在 macOS 上
# 不把 127.0.0.1 放进例外表（proxy_bypass 返回 False）。裸 urlopen 会让回环请求先经
# 代理，把「服务端静默断连」伪装成 502 空体，误导定位。这里显式绕代理解析器（连接器口径）。
_无代理 = urllib.request.build_opener(urllib.request.ProxyHandler({}))


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

            def 请求(路径: str, 头部: dict[str, str] | None = None):
                请求对象 = urllib.request.Request(
                    地址 + urllib.parse.quote(路径),
                    data=json.dumps({"操作": "读取工程"}).encode(),
                    headers={"Content-Type": "application/json", **(头部 or {})},
                    method="POST",
                )
                try:
                    with _无代理.open(请求对象, timeout=5) as 响应:
                        return 响应.status, 响应.read()
                except urllib.error.HTTPError as 错误:
                    try:
                        return 错误.code, 错误.read()
                    finally:
                        错误.close()

            # 动态令牌只随本次启动注入首页：按新契约从注入页取（不再猜固定标记）
            首页 = _无代理.open(地址 + "/", timeout=5).read().decode("utf-8")
            匹配 = re.search(r"const 会话令牌='([^']+)';", 首页)
            self.assertIsNotNone(匹配, "IDE 首页必须注入本次启动的动态会话令牌")
            令牌 = 匹配.group(1) if 匹配 else ""
            self.assertTrue(令牌 and 令牌 != "__IDE会话令牌__", "令牌占位符必须已被注入")

            self.assertEqual(请求("/工程/请求")[0], 404)
            self.assertEqual(请求("/内部/工程请求")[0], 403)
            # 反向断言：旧固定内部标记 X-Internal-Call: 1 已失效，不得再放行
            self.assertEqual(请求("/内部/工程请求", {"X-Internal-Call": "1"})[0], 403)
            状态, 内容 = 请求("/内部/工程请求", {"X-IDE-Token": 令牌})
            self.assertEqual(状态, 200)
            self.assertTrue(json.loads(内容)["成功"])
        finally:
            进程.terminate()
            try:
                进程.wait(timeout=3)
            except subprocess.TimeoutExpired:
                进程.kill()
                进程.wait(timeout=3)
            for 流 in (进程.stdout, 进程.stderr):
                if 流 is not None:
                    流.close()
            import shutil
            shutil.rmtree(临时根, ignore_errors=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
