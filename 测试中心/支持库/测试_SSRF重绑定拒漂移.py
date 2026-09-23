"""SSRF「两次解析必须拒漂移（DNS 重绑定）」负路径断言（开工ID：20260918-负路径5类断言）。

对应外部审计报告①-8 第 ④ 类：`支持库/后端/网络通信支持库/请求/实现/网络请求.py`
的修复口径是「校验解析出的 IP **绑定**到实际连接」—— 校验阶段解析一次并逐个复核，
连接阶段只连这些已复核的 IP（IP 字面量），主机名不再交给系统解析器，所以**第二次
解析不存在**，DNS 重绑定没有生效窗口。

判定口径（不靠超时快慢，靠**受害服务是否真的被访问**）：
- 注入 `socket.getaddrinfo`：被登记的攻击者主机名**第 1 次**返回合法公网 IP、
  **第 2 次**返回内网/回环地址（经典 DNS 重绑定）；
- 断言受害服务收到 **0 次**请求、受害内容**不落盘** —— 请求不得打到内网。

为什么不用 `unittest.mock`：本用例要替换的是**系统解析器本身**（stdlib 边界），
用直接赋值 + `try/finally` 还原比打桩更贴近真实（也让「是不是真的没连内网」由
受害服务的真实访问记录回答）。整个文件不 patch 任何生产对象。

反向（必红）：把实现换成修复前的 git 基线（无 IP 绑定），同一场景下受害服务
**必然被访问**。
"""

from __future__ import annotations

import importlib.util
import os
import socket
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

if str(Path(__file__).resolve().parents[2]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from 支持库.后端.网络通信支持库.请求 import 发送请求, 下载文件  # noqa: E402

系统根 = Path(__file__).resolve().parents[2]
from 公共契约.运行时.平台适配 import 清只读后删除树
from 公共契约.基础类型.逻辑类型 import 真


#: ★ A 档泄漏收口（2026-09-23）：受管临时根在仓库内**固定排除目录** `工程缓存/` 下。
#: `dir=` 显式指向它 ⇒ 落点与**测试运行时**的 `TMPDIR` 解耦（平台跑测试时 `TMPDIR` 被指进
#: 仓库工作目录，裸 `mkdtemp()` 会把夹具造进仓库）。`工程缓存` 在
#: `开发工具/项目编译/工作区指纹.py` 的 `固定排除目录` 里 ⇒ 即便进程被 SIGKILL、
#: 清理没跑到，残留也进不了工作区指纹（`.gitignore` 保不住：指纹的未跟踪腿不用
#: `--exclude-standard`）。清理走平台唯一删树原语 `清只读后删除树`（本类用例常造
#: `0o555` 目录 / `0o444` 文件，plain `shutil.rmtree` 会被权限位挡住）。
受管临时根 = 系统根 / "工程缓存" / "测试临时"
受管临时根.mkdir(parents=True, exist_ok=True)

#: 模块级临时夹具登记：本模块的夹具**在模块级 helper 里**造（helper 拿不到 TestCase 实例，
#: 用不了 `self.addCleanup`）⇒ 走 unittest 的**模块级收尾钩子** `tearDownModule` 登记清理
#: （同样「用例失败也跑」）。拿得到用例实例的站点一律用 `self.addCleanup`。
_临时夹具登记: list[Path] = []


def tearDownModule() -> None:
    """模块收尾：清理本模块造在 `受管临时根` 下的全部夹具（**用例失败也跑**）。"""
    for 夹具 in _临时夹具登记:
        清只读后删除树(夹具, 忽略失败=真)
    _临时夹具登记.clear()

#: 修复前的实现（校验一次、连接时 urllib 再解析一次 ⇒ 重绑定可生效）。
修复前基线 = "a95e48de^"

攻击者主机名 = "attacker-rebind.example"   # 必须是 ASCII：HTTP Location 头按 latin-1 编码
第一次解析IP = "1.1.1.1"                   # 合法公网地址：校验阶段放行
真getaddrinfo = socket.getaddrinfo
真getproxies = urllib.request.getproxies


def 本机局域网地址() -> str:
    """本机在局域网里的地址（受害服务用它模拟「内网可达服务」）。"""
    套接字 = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        套接字.connect(("8.8.8.8", 80))
        return 套接字.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        套接字.close()


第二次解析IP = 本机局域网地址()

#: 修复前实现的惰性缓存：只有一个反向用例，首次取用时加载一次即可。
_修复前缓存 = None


def 加载修复前实现():
    源码 = subprocess.run(
        ["git", "show", f"{修复前基线}:支持库/后端/网络通信支持库/请求/实现/网络请求.py"],
        cwd=str(系统根), capture_output=True, text=True, check=True).stdout
    夹具根 = Path(tempfile.mkdtemp(prefix="SSRF反向验证_", dir=受管临时根))
    _临时夹具登记.append(夹具根)
    临时 = 夹具根 / "修复前网络请求.py"
    临时.write_text(源码, encoding="utf-8")
    规格 = importlib.util.spec_from_file_location("修复前网络请求", 临时)
    if 规格 is None or 规格.loader is None:
        raise RuntimeError("修复前实现无法构造导入规格")
    模块 = importlib.util.module_from_spec(规格)
    sys.modules["修复前网络请求"] = 模块
    规格.loader.exec_module(模块)
    return 模块


class 受害服务:
    """被访问到即记录路径（监听 0.0.0.0，模拟内网可达服务）。"""

    def __init__(self, 正文: str, 重定向到: str = "") -> None:
        self.路径记录: list[str] = []
        正文字节 = 正文.encode("utf-8")
        路径记录 = self.路径记录
        重定向目标 = 重定向到

        class 处理器(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *参数) -> None:  # 静音
                pass

            def do_GET(self) -> None:
                路径记录.append(self.path)
                if 重定向目标:
                    self.send_response(302)
                    self.send_header("Location", 重定向目标)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                self.send_response(200)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Content-Length", str(len(正文字节)))
                self.end_headers()
                self.wfile.write(正文字节)

        self.服务 = ThreadingHTTPServer(("0.0.0.0", 0), 处理器)
        self.端口 = self.服务.server_port
        self.线程 = threading.Thread(target=self.服务.serve_forever, daemon=True)
        self.线程.start()

    def 关闭(self) -> None:
        self.服务.shutdown()
        self.服务.server_close()
        self.线程.join(timeout=2)


class SSRF绑定夹具(unittest.TestCase):
    解析登记表: dict[str, list[str]] = {}
    解析次数表: dict[str, int] = {}

    @classmethod
    def setUpClass(cls) -> None:
        socket.getaddrinfo = cls._假解析
        urllib.request.getproxies = lambda: {}   # 强制直连，否则系统代理会绕开绑定

    @classmethod
    def tearDownClass(cls) -> None:
        socket.getaddrinfo = 真getaddrinfo
        urllib.request.getproxies = 真getproxies

    @classmethod
    def _假解析(cls, 主机, 端口, *参数, **关键字):
        """登记过的主机名：第 1 次返回公网 IP，之后返回内网 IP；其它主机真实解析。"""
        文本主机 = str(主机)
        if 文本主机 in cls.解析登记表:
            cls.解析次数表[文本主机] = cls.解析次数表.get(文本主机, 0) + 1
            序列 = cls.解析登记表[文本主机]
            IP = 序列[min(cls.解析次数表[文本主机] - 1, len(序列) - 1)]
            族 = socket.AF_INET6 if ":" in IP else socket.AF_INET
            return [(族, socket.SOCK_STREAM, 6, "", (IP, 端口))]
        return 真getaddrinfo(主机, 端口, *参数, **关键字)

    def setUp(self) -> None:
        self.解析登记表.clear()
        self.解析次数表.clear()
        self._关掉: list[受害服务] = []

    def tearDown(self) -> None:
        for 服务 in self._关掉:
            服务.关闭()

    def 登记攻击者(self) -> None:
        self.解析登记表[攻击者主机名] = [第一次解析IP, 第二次解析IP]
        self.解析次数表[攻击者主机名] = 0

    def 起受害服务(self, 正文: str, 重定向到: str = "") -> 受害服务:
        服务 = 受害服务(正文, 重定向到)
        self._关掉.append(服务)
        return 服务


class TestSSRF拒漂移(SSRF绑定夹具):
    def test_发送请求_重绑定后不得打到内网(self) -> None:
        受害 = self.起受害服务("受害服务机密正文")
        self.登记攻击者()

        结果 = 发送请求(地址=f"http://{攻击者主机名}:{受害.端口}/机密", 超时秒=1.5)

        访问次数 = len(受害.路径记录)
        self.assertEqual(访问次数, 0,
                         f"DNS 重绑定绕道成立：校验解析 {第一次解析IP}，"
                         f"实际连到了 {第二次解析IP} 的受害服务（访问路径 {受害.路径记录}）")
        self.assertFalse(结果.成功, "打到内网的路径必须 fail-closed 拒绝")
        self.assertIn("SSRF防护", str(结果.错误说明), f"错误说明: {结果.错误说明}")
        self.assertIn(第二次解析IP, str(结果.错误说明),
                      "拒绝原因应点名被复核否决的内网地址（可区分结构）")

    def test_下载文件_重绑定后不得落盘(self) -> None:
        受害 = self.起受害服务("下载受害者机密文件")
        落盘根 = tempfile.mkdtemp(prefix="SSRF落盘_", dir=受管临时根)
        保存路径 = str(Path(落盘根) / "机密.bin")
        self.addCleanup(清只读后删除树, 落盘根, 忽略失败=真)
        self.登记攻击者()

        结果 = 下载文件(地址=f"http://{攻击者主机名}:{受害.端口}/机密.bin",
                        保存路径=保存路径, 超时秒=1.5)

        self.assertEqual(len(受害.路径记录), 0, "下载路径同样不得打到内网")
        self.assertFalse(os.path.exists(保存路径), "受害内容不得落盘")
        self.assertFalse(结果.成功)

    def test_重定向逐跳_重绑定后不得打到内网(self) -> None:
        受害 = self.起受害服务("重定向后拿到的机密正文")
        首跳 = self.起受害服务("", 重定向到=f"http://{攻击者主机名}:{受害.端口}/secret")
        self.登记攻击者()

        结果 = 发送请求(地址=f"http://127.0.0.1:{首跳.端口}/跳", 允许回环=True, 超时秒=1.5)

        # 首跳是合法回环：必须真被访问（证明链路本身通，不是「全都连不上」的假绿）
        self.assertEqual(len(首跳.路径记录), 1, "首跳（合法回环）应被正常访问")
        self.assertEqual(len(受害.路径记录), 0,
                         "逐跳路径 DNS 重绑定绕道成立：重定向后的解析 IP 未被绑定")
        self.assertFalse(结果.成功)

    def test_正常回环链路仍可成功_绑定未破坏合法路径(self) -> None:
        """反向边界：绑定不得把正常链路一起拒了（否则「全拒」也能让上面几条变绿）。"""
        上游 = self.起受害服务("合法回环正文")
        结果 = 发送请求(地址=f"http://127.0.0.1:{上游.端口}/ok", 允许回环=True, 超时秒=3.0)

        self.assertTrue(结果.成功, f"合法回环地址应仍可访问: {结果.错误说明}")
        self.assertEqual(结果.值.get("状态码"), 200)
        self.assertIn("合法回环正文", 结果.值.get("响应文本", ""))
        self.assertEqual(上游.路径记录, ["/ok"])


class Test反向_修复前实现必红(SSRF绑定夹具):
    """反向验证：换成修复前实现，同一场景下受害服务必然被访问（证明用例是「活」的）。"""

    def _修复前实现(self):
        """惰性加载并缓存；加载失败在**用例内**跳过（不在 setUpClass 跳过）。

        为什么不在 setUpClass：本类的 setUpClass 已经改写了进程级 `socket.getaddrinfo`，
        若在 setUpClass 抛 SkipTest，`tearDownClass` 不会执行，补丁会泄漏到后续用例。
        """
        global _修复前缓存
        if _修复前缓存 is None:
            try:
                _修复前缓存 = 加载修复前实现()
            except Exception as 错误:
                self.skipTest(f"取不到修复前实现基线（{修复前基线}）：{错误}")
        return _修复前缓存

    def test_反向_修复前实现_重绑定即打到内网(self) -> None:
        修复前 = self._修复前实现()
        受害 = self.起受害服务("受害服务机密正文")
        self.登记攻击者()

        结果 = 修复前.发送请求(
            地址=f"http://{攻击者主机名}:{受害.端口}/机密", 超时秒=1.5)

        self.assertGreaterEqual(len(受害.路径记录), 1,
                                "修复前实现（连接时二次解析）应被打到内网；"
                                "若这里为 0，说明反向验证失效（用例不再能变红）")
        self.assertTrue(结果.成功)


if __name__ == "__main__":
    unittest.main()
