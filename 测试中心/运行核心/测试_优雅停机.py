"""进程级优雅停机编排回归测试：四段顺序、真停机语义、有界排空、信号接线。

**为什么这些断言是真语义而不是占位**：本文件的每条用例都起**真 HTTP 服务**
（生产同一个 `有界线程HTTP服务器`）并造**真在途请求**（工作线程被真实占住），
再断言停机各段的真实后果 —— 关监听后新连接由内核拒绝、在途自然收尾、
到上限未被收尾的**逐条进截断清单**、复查窗口内收尾判为整体收敛。

`启动运行核心网关.py` 是 40007 常驻网关的唯一入口，本测试不重复起整装入口
（那是 `测试_停机编排接线.py` 的子进程真跑职责），只覆盖**编排本身**的语义。
"""

from __future__ import annotations

import signal
import socket
import sys
import tempfile
import threading
import time
import unittest
import urllib.parse
from http.client import HTTPConnection
from http.server import BaseHTTPRequestHandler
from pathlib import Path

系统根 = Path(__file__).resolve().parents[2]
if str(系统根) not in sys.path:
    sys.path.insert(0, str(系统根))

from 公共契约.基础类型.逻辑类型 import 真, 假
from 运行核心.统一网关.本地网关 import 有界线程HTTP服务器
from 运行核心.统一网关.停机编排 import (
    停机阶段_已停机, 停机阶段_排空在途, 停机阶段_持久化, 停机阶段_停止收新请求,
    停机阶段_整组回收, 停机阶段_运行中, 四段阶段表, 停机编排,
    安装停机信号处理, 信号安装状态, 已配置退出超时, 退出超时改造建议,
    launchd退出超时建议, 默认排空上限秒, 默认排空复查窗口秒,
)


class 慢服务夹具:
    """起一个真 HTTP 服务，并能把某个请求的工作线程**真实占住**。"""

    def __init__(self) -> None:
        self.进入慢 = threading.Event()
        self.放行慢 = threading.Event()
        夹具 = self

        class 处理器(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802 —— HTTP 方法名由基类约定
                # 路径用 ASCII：HTTP 请求行只接受 ascii，中文路径会被 http.client 拒绝
                if self.path.startswith("/slow"):
                    夹具.进入慢.set()
                    夹具.放行慢.wait(30.0)
                self.send_response(200)
                self.send_header("Content-Length", "2")
                self.end_headers()
                self.wfile.write(b"ok")

            def log_message(self, format: str, *args: object) -> None:  # noqa: A002 —— 基类签名
                return

        self.服务器 = 有界线程HTTP服务器(("127.0.0.1", 0), 处理器, 最大工作线程=8)
        self.端口 = int(self.服务器.server_address[1])
        self.线程 = threading.Thread(target=self.服务器.serve_forever, daemon=True)
        self.线程.start()

    # ---- 注入给 停机编排 的三个函数（与生产入口同口径：只用真实粒度）----

    def 关闭监听(self) -> tuple[bool, str]:
        self.服务器.shutdown()
        self.服务器.socket.close()
        return 真, f"监听 socket 已关闭，在途工作线程 {self.服务器.活动工作线程数} 条"

    def 有界排空(self, 上限秒: float) -> tuple[bool, str]:
        上限 = max(0.0, float(上限秒))
        截止 = time.monotonic() + 上限
        while self.服务器.活动工作线程数 > 0 and time.monotonic() < 截止:
            time.sleep(0.02)
        剩 = self.服务器.活动工作线程数
        return (假 if 剩 else 真), f"排空 {上限:.1f} 秒后剩 {剩} 条"

    def 在途快照(self) -> list[dict]:
        剩 = self.服务器.活动工作线程数
        return [{"路径": "（工作线程：在途请求）", "请求id": "", "已运行秒": 0.5}
                for _ in range(剩)]

    def 发请求(self, 路径: str, 超时: float = 10.0) -> int:
        连接 = HTTPConnection("127.0.0.1", self.端口, timeout=超时)
        连接.request("GET", urllib.parse.quote(路径, safe="/"))
        响应 = 连接.getresponse()
        状态码 = 响应.status
        响应.read()
        连接.close()
        return 状态码

    def 收尾(self) -> None:
        self.放行慢.set()
        try:
            self.服务器.shutdown()
        except Exception:  # noqa: BLE001 —— 夹具收尾失败不掩盖用例结论
            pass
        try:
            self.服务器.socket.close()
        except Exception:  # noqa: BLE001
            pass


def 造编排(夹具: 慢服务夹具, **覆盖: object) -> 停机编排:
    参数: dict[str, object] = {
        "名称": "夹具网关", "排空上限秒": 默认排空上限秒,
        "排空复查窗口秒": 默认排空复查窗口秒,
        "停收函数": 夹具.关闭监听, "排空函数": 夹具.有界排空,
        "在途快照函数": 夹具.在途快照, "取消在途流函数": lambda: "无流式通道",
    }
    参数.update(覆盖)
    return 停机编排(**参数)  # type: ignore[arg-type] —— 夹具按注入契约传参


class 四段状态机用例(unittest.TestCase):
    def test_四段顺序与报告结构_收尾链按登记顺序执行(self):
        执行记录: list[str] = []
        编排 = 停机编排(
            名称="顺序夹具",
            停收函数=lambda: (执行记录.append("停收") or (真, "已停收")),
            排空函数=lambda 上限: (执行记录.append(f"排空{上限:.0f}") or (真, "已排空")),
            在途快照函数=lambda: [],
            收尾链=[("丙", lambda: 执行记录.append("收尾丙")),
                    ("甲", lambda: 执行记录.append("收尾甲"))],
            持久化链=[("落库", lambda: 执行记录.append("落库"))],
            非终态任务函数=lambda: 3,
        )
        self.assertEqual(编排.状态, 停机阶段_运行中)
        报告 = 编排.执行()
        self.assertEqual(报告["阶段序列"], list(四段阶段表), "四段顺序即语义，不得乱序")
        self.assertTrue(报告["四段完整"])
        self.assertTrue(报告["成功"])
        # 收尾链顺序 = 登记顺序；排空上限取自 排空上限秒（有界）
        self.assertEqual(执行记录, ["停收", f"排空{默认排空上限秒:.0f}",
                                    "收尾丙", "收尾甲", "落库"])
        self.assertEqual(报告["持久化"]["非终态任务数"], 3)
        self.assertEqual(编排.状态, 停机阶段_已停机)

    def test_重复执行幂等且重复信号降级为立即收尾(self):
        上限表: list[float] = []
        编排 = 停机编排(名称="降级夹具",
                        停收函数=lambda: (真, "已停收"),
                        排空函数=lambda 上限: (上限表.append(上限) or (真, "已排空")),
                        在途快照函数=lambda: [])
        self.assertFalse(编排.请求停机("SIGTERM")["重复"])
        降级 = 编排.请求停机("SIGTERM")
        self.assertTrue(降级["重复"])
        self.assertTrue(降级["降级"], "第二次信号必须降级，不能当没看见")
        报告 = 编排.执行()
        self.assertEqual(上限表, [0.0], "降级后排空上限必须归零（不无限等）")
        self.assertTrue(报告["强制退出"])
        第二次报告 = 编排.执行()
        self.assertEqual(第二次报告["阶段序列"], 报告["阶段序列"], "已停机时幂等返回")
        self.assertTrue(编排.请求停机()["重复"])

    def test_退出码默认零_未收敛也不靠退出码表达(self):
        编排 = 停机编排(名称="退出码夹具",
                        停收函数=lambda: (假, "故意失败"),
                        排空函数=lambda 上限: (真, "已排空"),
                        在途快照函数=lambda: [])
        报告 = 编排.执行()
        self.assertFalse(报告["成功"])
        self.assertTrue(报告["未收敛原因"], "未收敛必须逐条给理由")
        self.assertEqual(编排._退出码(报告), 0,
                         "launchd SuccessfulExit:false 见非零立刻重启，优雅停机不该表现成崩溃")

    def test_段异常必须进报告不静默吞(self):
        def 会炸():
            raise RuntimeError("故意炸")

        编排 = 停机编排(名称="异常夹具", 停收函数=会炸,
                        排空函数=lambda 上限: (真, "已排空"),
                        在途快照函数=lambda: [])
        报告 = 编排.执行()
        self.assertFalse(报告["成功"])
        self.assertIn("异常", 报告["未收敛原因"][0])
        self.assertIn("RuntimeError", 报告["未收敛原因"][0])


class 真停机语义用例(unittest.TestCase):
    def setUp(self) -> None:
        self.夹具 = 慢服务夹具()
        self.addCleanup(self.夹具.收尾)

    def test_停收段真让新连接被拒(self):
        编排 = 造编排(self.夹具)
        self.assertEqual(self.夹具.发请求("/fast"), 200, "停机前服务必须可用")
        报告 = 编排.执行()
        第一节 = 报告["阶段明细"][0]
        self.assertEqual(第一节["阶段"], 停机阶段_停止收新请求)
        self.assertTrue(第一节["成功"], f"关监听失败：{第一节.get('错误说明')}")
        连接 = None
        try:
            连接 = socket.create_connection(("127.0.0.1", self.夹具.端口), timeout=2.0)
        except OSError:
            pass
        finally:
            if 连接 is not None:
                连接.close()
        self.assertIsNone(连接, "停机后新连接必须被内核拒绝（listen socket 已关闭）")

    def test_在途请求在停机中自然收尾(self):
        编排 = 造编排(self.夹具)
        结果: dict = {}

        def 打慢请求():
            结果["状态码"] = self.夹具.发请求("/slow", 超时=20.0)

        线程 = threading.Thread(target=打慢请求, daemon=True)
        线程.start()
        self.assertTrue(self.夹具.进入慢.wait(5.0), "未能造出在途请求")
        self.assertEqual(self.夹具.服务器.活动工作线程数, 1)
        手动放行 = threading.Timer(0.5, self.夹具.放行慢.set)
        手动放行.start()
        self.addCleanup(手动放行.cancel)
        报告 = 编排.执行()
        线程.join(10.0)
        排空段 = [项 for 项 in 报告["阶段明细"] if 项["阶段"] == 停机阶段_排空在途][0]
        self.assertTrue(排空段["成功"], f"在途请求未自然收尾：{排空段.get('错误说明')}")
        self.assertEqual(报告["排空"]["截断数"], 0)
        self.assertEqual(结果.get("状态码"), 200, "在途请求必须拿到完整响应，不得被腰斩")
        self.assertEqual(self.夹具.服务器.活动工作线程数, 0)

    def test_排空到上限未收尾逐条进截断清单且不静默(self):
        编排 = 造编排(self.夹具, 排空上限秒=0.0, 排空复查窗口秒=0.0)
        线程 = threading.Thread(target=lambda: self.夹具.发请求("/slow", 超时=20.0), daemon=True)
        线程.start()
        self.assertTrue(self.夹具.进入慢.wait(5.0), "未能造出在途请求")
        报告 = 编排.执行()
        排空段 = [项 for 项 in 报告["阶段明细"] if 项["阶段"] == 停机阶段_排空在途][0]
        self.assertFalse(排空段["成功"], "到上限仍未收尾必须如实报未收敛")
        self.assertEqual(报告["排空"]["截断数"], 1)
        条目 = 报告["排空"]["截断清单"][0]
        self.assertIn("已运行秒", 条目, "逐条记录必须带量纲")
        self.assertIn("截断", 排空段["说明"])
        self.assertTrue(any("被截断" in 行 for 行 in 报告["日志"]),
                        "截断必须进日志（可见，不静默）")
        self.夹具.放行慢.set()
        线程.join(5.0)

    def test_首轮超上限但复查窗口内收尾判为整体收敛(self):
        """2026-09-18 修复的缺陷：此前复查后已无在途，仍沿用首轮「未收敛」结论 →
        报告自相矛盾（说存在未收敛项，截断清单却是空的）。"""
        编排 = 造编排(self.夹具, 排空上限秒=0.0, 排空复查窗口秒=默认排空复查窗口秒)
        线程 = threading.Thread(target=lambda: self.夹具.发请求("/slow", 超时=20.0), daemon=True)
        线程.start()
        self.assertTrue(self.夹具.进入慢.wait(5.0), "未能造出在途请求")
        # 放行必须落在「首轮排空之后、复查窗口之内」：首轮上限 0 会立即返回，
        # 但停止收新请求段的 服务器.shutdown() 本身约 0.5 秒，放行太早会赶在
        # 首轮之前完成（那样测的就不是复查窗口了）。1.2 秒落在 0 秒之后、2 秒窗口之内。
        放行 = threading.Timer(1.2, self.夹具.放行慢.set)
        放行.start()
        self.addCleanup(放行.cancel)
        报告 = 编排.执行()
        排空段 = [项 for 项 in 报告["阶段明细"] if 项["阶段"] == 停机阶段_排空在途][0]
        self.assertEqual(报告["排空"]["截断数"], 0)
        self.assertTrue(排空段["成功"],
                        "复查窗口内已收尾 ⇒ 有界排空整体收敛，不得再报未收敛")
        self.assertIn("复查窗口", 排空段["说明"], "如实说明首轮曾超上限，不掩盖")
        self.assertTrue(报告["成功"], "四段都收敛 ⇒ 报告成功")
        self.assertTrue(any("复查窗口" in 行 for 行 in 报告["日志"]))
        线程.join(5.0)


class 信号接录用例(unittest.TestCase):
    def test_安装后信号归属可取证且进程内唯一(self):
        第一 = 停机编排(名称="第一网关", 停收函数=lambda: (真, "ok"),
                        排空函数=lambda 上限: (真, "ok"), 在途快照函数=lambda: [])
        第二 = 停机编排(名称="第二网关", 停收函数=lambda: (真, "ok"),
                        排空函数=lambda 上限: (真, "ok"), 在途快照函数=lambda: [])
        装好, 说明 = 安装停机信号处理(第一, 允许接管=真)
        self.assertTrue(装好, 说明)
        快照 = 信号安装状态()
        self.assertTrue(快照["已安装"], "信号安装状态必须能取证接线真生效")
        self.assertEqual(快照["归属"], "第一网关")
        self.assertIn("SIGTERM", 快照["安装结果"])
        self.assertIs(signal.getsignal(signal.SIGTERM), signal.getsignal(signal.SIGTERM))
        self.assertNotEqual(signal.getsignal(signal.SIGTERM), signal.SIG_DFL,
                            "SIGTERM 不得仍停在默认动作（默认动作 = 立即终止）")
        拒绝, 拒绝说明 = 安装停机信号处理(第二)
        self.assertFalse(拒绝, "进程内信号只允许一个停机编排持有（否则假绿）")
        self.assertIn("第一网关", 拒绝说明)
        接管, 接管说明 = 安装停机信号处理(第二, 允许接管=真)
        self.assertTrue(接管, 接管说明)
        self.assertEqual(信号安装状态()["归属"], "第二网关")
        # 还原：后续用例不继承本用例的信号归属
        self.assertTrue(安装停机信号处理(第一, 允许接管=真)[0])

    def test_非主线程安装必须拒绝(self):
        编排 = 停机编排(名称="副线程夹具", 停收函数=lambda: (真, "ok"),
                        排空函数=lambda 上限: (真, "ok"), 在途快照函数=lambda: [])
        结果: dict = {}
        线程 = threading.Thread(
            target=lambda: 结果.update(zip(("装好", "说明"),
                                          安装停机信号处理(编排, 允许接管=真))))
        线程.start()
        线程.join(5.0)
        self.assertFalse(结果.get("装好"), "非主线程装信号处理器不会生效，必须拒绝")
        self.assertIn("主线程", 结果.get("说明", ""))


class 退出超时建议用例(unittest.TestCase):
    def test_建议值由排空上限与收尾项数推导(self):
        self.assertEqual(launchd退出超时建议(), 
                         int(默认排空上限秒 + 3 * 10.0 + 默认排空复查窗口秒 + 8.0))
        self.assertGreater(launchd退出超时建议(), 默认排空上限秒,
                           "缺省 ExitTimeOut 只有 20 秒，与排空上限同量级 ⇒ 长请求必被 SIGKILL")

    def test_未声明ExitTimeOut的plist按未配置处理(self):
        路径 = Path(tempfile.mkdtemp()) / "无退出超时.plist"
        路径.write_text("<plist><dict><key>Label</key></dict></plist>", encoding="utf-8")
        self.assertFalse(已配置退出超时(str(路径)))
        声明后 = 路径.with_name("有退出超时.plist")
        声明后.write_text("<plist><dict><key>ExitTimeOut</key><integer>60</integer>"
                          "</dict></plist>", encoding="utf-8")
        self.assertTrue(已配置退出超时(str(声明后)))
        建议 = 退出超时改造建议(plist路径=str(路径))
        self.assertIn("建议秒", 建议)
        self.assertTrue(建议["命令"], "必须给出可直接粘贴的落地命令")
        self.assertFalse(已配置退出超时("/不存在的目录/不存在.plist"))


if __name__ == "__main__":
    unittest.main()
