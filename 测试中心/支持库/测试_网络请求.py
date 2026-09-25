"""网络请求：3xx 响应必须把响应头（含 Location）带出，供调用方经唯一入口逐跳跟随。

`发送请求` 是出站 HTTP 的唯一入口，自带 SSRF 校验（回环/内网/保留地址默认拒绝）。
它若在 3xx 时只回传状态码、丢掉响应头，调用方就拿不到 `Location`：只能
「关掉自动重定向 → 手工 urllib 读 Location → 再手工发下一跳」，而手工那一跳
**绕过了本能力的 SSRF 防线**。所以 3xx 的响应头必须原样带出，让逐跳跟随
始终经本能力进行（每一跳都重跑 SSRF 校验）。

本文件锁定：
- 禁止自动重定向时，失败结果携带 状态码=3xx 与完整响应头（含 Location）；
- 默认行为仍是自动跟随到终点 200（不被本次改动破坏）；
- SSRF 防线不因此松动（未开 允许回环 时回环地址仍被拒）。

另锁 `下载文件` 的**落盘契约**（2026-09-25 单腿铁律收口）：落盘只走平台唯一写入腿
（`资源管理.原子写入` → `文件系统支持库.文件操作.写入文件`），且 `开工ID` 一路透传到
那一跳；原先自建的 `.part 临时件 + os.replace` 已删。该组用例的落点用**假仓库**
（`工程缓存/测试临时/<名>/假仓库`，带 `.git/`），使落点是**受管**的 —— 否则落在
mkdtemp 恒非受管、判据恒放行，「凭证有没有透传到写腿」根本测不出来（夹具口径同
`测试中心/公共契约/测试_写入授权.py`）。
"""

from __future__ import annotations

import os
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

系统根 = Path(__file__).resolve().parents[2]
if str(系统根) not in sys.path:
    sys.path.insert(0, str(系统根))

from 公共契约.基础类型.逻辑类型 import 真  # noqa: E402
from 公共契约.运行时.平台适配 import 清只读后删除树  # noqa: E402
from 支持库.后端.网络通信支持库.请求 import 发送请求, 下载文件  # noqa: E402
from 平台控制面.能力目录 import 申请文件租约, 释放文件租约  # noqa: E402

受管临时根 = 系统根 / "工程缓存" / "测试临时"
受管临时根.mkdir(parents=True, exist_ok=True)


class _重定向上游:
    """/hop 返回 302 + Location: /dest；/dest 返回 200；其余 404。"""

    def __init__(self) -> None:
        self.路径记录: list[str] = []
        self.服务 = ThreadingHTTPServer(("127.0.0.1", 0), self._造处理器())
        self.端口 = self.服务.server_port
        self.线程 = threading.Thread(target=self.服务.serve_forever, daemon=True)
        self.线程.start()

    def _造处理器(self):
        路径记录 = self.路径记录

        class 处理器(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args) -> None:
                pass

            def do_GET(self) -> None:
                路径记录.append(self.path)
                if self.path == "/hop":
                    self.send_response(302)
                    self.send_header("Location", "/dest")
                    self.send_header("X-Redirect-Source", "localtest")
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                if self.path == "/dest":
                    正文 = "到达终点".encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "text/plain; charset=utf-8")
                    self.send_header("Content-Length", str(len(正文)))
                    self.end_headers()
                    self.wfile.write(正文)
                    return
                self.send_response(404)
                self.send_header("Content-Length", "0")
                self.end_headers()

        return 处理器

    def 关闭(self) -> None:
        self.服务.shutdown()
        self.服务.server_close()
        self.线程.join(timeout=2)

    def 地址(self, 路径: str) -> str:
        return f"http://127.0.0.1:{self.端口}{路径}"


class 测试网络请求重定向契约(unittest.TestCase):
    def test_禁止跟随重定向时回传状态码与完整响应头(self) -> None:
        上游 = _重定向上游()
        try:
            结果 = 发送请求(地址=上游.地址("/hop"), 允许回环=True, 跟随重定向=False)

            self.assertFalse(结果.成功, "3xx 不得包装成成功结果")
            self.assertEqual(结果.错误码, "HTTP错误")
            详情 = 结果.详细信息
            self.assertEqual(详情.get("状态码"), 302)
            响应头 = {str(键).lower(): 值 for 键, 值 in (详情.get("响应头") or {}).items()}
            self.assertEqual(响应头.get("location"), "/dest", "3xx 必须带出 Location")
            self.assertEqual(响应头.get("x-redirect-source"), "localtest", "3xx 响应头应完整带出")
        finally:
            上游.关闭()

    def test_默认自动跟随重定向到终点(self) -> None:
        上游 = _重定向上游()
        try:
            结果 = 发送请求(地址=上游.地址("/hop"), 允许回环=True)

            self.assertTrue(结果.成功, f"默认应自动跟随: {结果.错误说明}")
            assert isinstance(结果.值, dict)
            self.assertEqual(结果.值["状态码"], 200)
            self.assertIn("到达终点", 结果.值["响应文本"])
            self.assertEqual(上游.路径记录, ["/hop", "/dest"], "默认应自动跳转到终点")
        finally:
            上游.关闭()

    def test_回环地址未放行时仍被SSRF拒绝(self) -> None:
        上游 = _重定向上游()
        try:
            结果 = 发送请求(地址=上游.地址("/hop"))

            self.assertFalse(结果.成功, "未开 允许回环 时回环地址必须被拒")
            self.assertEqual(结果.错误码, "参数不合法")
            self.assertIn("SSRF", 结果.错误说明)
        finally:
            上游.关闭()


class _下载上游:
    """二进制正文上游（含 0x00..0xff，逐字节比对才有意义）；记录被访问的路径。"""

    def __init__(self) -> None:
        self.正文 = bytes(range(256)) * 4
        self.路径记录: list[str] = []
        self.服务 = ThreadingHTTPServer(("127.0.0.1", 0), self._造处理器())
        self.端口 = self.服务.server_port
        self.线程 = threading.Thread(target=self.服务.serve_forever, daemon=True)
        self.线程.start()

    def _造处理器(self):
        路径记录 = self.路径记录
        正文 = self.正文

        class 处理器(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args) -> None:
                pass

            def do_GET(self) -> None:
                路径记录.append(self.path)
                if self.path != "/blob.bin":
                    self.send_response(404)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                self.send_response(200)
                self.send_header("Content-Type", "application/octet-stream")
                self.send_header("Content-Length", str(len(正文)))
                self.end_headers()
                self.wfile.write(正文)

        return 处理器

    def 关闭(self) -> None:
        self.服务.shutdown()
        self.服务.server_close()
        self.线程.join(timeout=2)

    def 地址(self) -> str:
        return f"http://127.0.0.1:{self.端口}/blob.bin"


class 测试下载文件落盘契约(unittest.TestCase):
    """落盘只走平台唯一写入腿，且 `开工ID` 一路透传到那一跳。

    受管落点用**假仓库**：真仓库一个字节都不动，而 `仓库只读锁.推断仓库根` 命中的是
    假仓库（最近的 `.git/`）⇒ 那条路径是**受管**的，`校验写入授权` 才真会问
    「该路径活跃写租约的 `所有者` 是不是你」。
    """

    凭证 = "下载落盘-回归锁"
    其它凭证 = "下载落盘-别的凭证"
    相对 = "下载探针.bin"

    def setUp(self) -> None:
        self._临时 = tempfile.mkdtemp(prefix="下载落盘_", dir=受管临时根)
        self.假仓库 = Path(self._临时) / "假仓库"
        (self.假仓库 / ".git").mkdir(parents=True, exist_ok=True)
        self.保存路径 = self.假仓库 / self.相对
        self._设凭证(self.凭证)
        self.addCleanup(清只读后删除树, self._临时, 忽略失败=真)
        self.上游 = _下载上游()
        self.addCleanup(self.上游.关闭)

    def _设凭证(self, 值: str | None) -> None:
        """租约腿（`解锁供写入`）只认网关凭证；本组用例测的是**第二判据**，故夹具假装自己是网关。"""
        旧 = os.environ.get("系统库网关凭证")
        if 值 is None:
            os.environ.pop("系统库网关凭证", None)
        else:
            os.environ["系统库网关凭证"] = 值

        def _还原() -> None:
            if 旧 is None:
                os.environ.pop("系统库网关凭证", None)
            else:
                os.environ["系统库网关凭证"] = 旧

        self.addCleanup(_还原)

    def _认领(self) -> None:
        认领 = 申请文件租约(修改路径=[self.相对], 所有者=self.凭证, 任务="下载落盘回归",
                            项目根=str(self.假仓库))
        self.assertTrue(认领.成功, f"认领失败：{认领.错误码} {认领.错误说明}")
        租约id清单 = list(认领.值.get("租约id清单") or [])
        self.assertTrue(租约id清单, "认领成功却没回租约id清单")
        self.addCleanup(
            lambda: 释放文件租约(租约id清单=租约id清单, 原因="下载落盘回归收工",
                                 项目根=str(self.假仓库)))

    def test_受管落点带本凭证成功_开工ID真的到了写腿(self) -> None:
        """正拍：受管落点 + `所有者==开工ID` 的活跃租约 ⇒ 必须落盘成功。

        这一拍同时钉住「`开工ID` 透传到写腿」：实现若把凭证丢了（传空串/None），
        写腿会按「受管路径没有本凭证的活跃写租约」回 `越界` ⇒ 本用例必红。
        """
        self._认领()
        结果 = 下载文件(地址=self.上游.地址(), 保存路径=str(self.保存路径),
                        允许回环=True, 开工ID=self.凭证)

        self.assertTrue(结果.成功, f"受管落点带本凭证应能落盘：{结果.错误说明}")
        self.assertEqual(结果.值["文件路径"], str(self.保存路径))
        self.assertEqual(结果.值["字节数"], len(self.上游.正文))
        self.assertEqual(self.保存路径.read_bytes(), self.上游.正文, "落盘内容必须逐字节一致")
        self.assertEqual(list(self.假仓库.glob("*.part")), [],
                         "自建的 `.part` 临时件已删（落盘只走平台写腿）")

    def test_受管落点无凭证_先被拒且不发起请求(self) -> None:
        self._认领()
        结果 = 下载文件(地址=self.上游.地址(), 保存路径=str(self.保存路径), 允许回环=True)

        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "越界")
        self.assertIn("没有开工ID 凭证", 结果.错误说明)
        self.assertEqual(self.上游.路径记录, [], "没被授权的落点不得发起请求")
        self.assertFalse(self.保存路径.exists(), "被拒的下载不得落盘")

    def test_受管落点凭证不是所有者_被拒(self) -> None:
        self._认领()
        结果 = 下载文件(地址=self.上游.地址(), 保存路径=str(self.保存路径),
                        允许回环=True, 开工ID=self.其它凭证)

        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "越界")
        self.assertIn("别的凭证", 结果.错误说明)
        self.assertEqual(self.上游.路径记录, [], "凭证不符时同样不得发起请求")
        self.assertFalse(self.保存路径.exists())

    def test_非受管落点无凭证照旧成功(self) -> None:
        """反向边界（防假红）：仓库外落点本就没有租约可言，判据必须放行。"""
        落点 = Path(self._临时) / "仓外.bin"
        结果 = 下载文件(地址=self.上游.地址(), 保存路径=str(落点), 允许回环=True)

        self.assertTrue(结果.成功, f"仓库外落点应照旧能下：{结果.错误说明}")
        self.assertEqual(落点.read_bytes(), self.上游.正文)


if __name__ == "__main__":
    unittest.main()
