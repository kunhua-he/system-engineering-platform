"""第八阶段生产化能力的细颗粒反向测试。

测试只使用临时目录、临时端口和受控子进程。断言关注真实 HTTP 响应、
事件终态、进程退出、持久化文件、计数回收、事务副作用和门禁退出语义。
"""

from __future__ import annotations

import json
import socket
import os
import socket
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

系统根 = Path(__file__).resolve().parents[2]
if str(系统根) not in sys.path:
    sys.path.insert(0, str(系统根))

from 前端核心.前端核心 import 前端核心, 组件定义, 窗口定义, 页面定义
from 前端核心.浏览器交互 import 浏览器交互提供者
from 后端核心.后端核心 import 后端核心
from 运行核心.运行诊断.安全审计.安全审计 import 安全审计
from 运行核心.任务调度.任务进程 import 任务进程池
from 平台控制面.发布管理.发布事务.事务恢复 import 事务恢复
from 运行核心.资源协调.有状态排空.排空管理 import 排空管理器
from 运行核心.统一网关.安全边界 import 安全配置, 凭证管理器, 请求限制器, 脱敏参数, 脱敏错误信息
from 运行核心.统一网关.本地网关 import 本地网关服务器, 检查端口可用
from 运行核心.统一网关.流式HTTP import HTTP流式管理器, HTTP流式通道, 流式HTTP服务器
from 运行核心.统一网关.网关核心 import 网关核心
from 运行核心.统一网关.限流器 import 限流器


终态集合 = {"成功", "失败", "已取消", "超时", "崩溃"}


def 等待条件(条件, 超时秒: float = 2.0) -> bool:
    截止 = time.monotonic() + 超时秒
    while time.monotonic() < 截止:
        if 条件():
            return True
        time.sleep(0.01)
    return bool(条件())


def 在线程内调用(函数, 超时秒: float = 0.3) -> tuple[bool, object | None]:
    结果盒: list[object] = []

    def 执行() -> None:
        结果盒.append(函数())

    线程 = threading.Thread(target=执行, daemon=True)
    线程.start()
    线程.join(超时秒)
    return not 线程.is_alive(), 结果盒[0] if 结果盒 else None


def 构建后端() -> 后端核心:
    后端 = 后端核心()
    启动结果 = 后端.启动()
    if not 启动结果.成功:
        raise AssertionError(启动结果.错误说明)
    后端.注册能力(
        "第八阶段.相加", lambda 甲=0, 乙=0: {"和": 甲 + 乙},
        参数=[{"名称": "甲", "类型": "整数", "必填": False},
              {"名称": "乙", "类型": "整数", "必填": False}],
    )
    后端.注册能力("第八阶段.异常", lambda: (_ for _ in ()).throw(RuntimeError("内部密钥 sk-secret-value")))
    return 后端


def 任务返回进程id(参数: dict) -> dict:
    return {"进程id": os.getpid(), "参数": 参数}


def 任务短暂停顿(参数: dict, 取消事件) -> dict:
    time.sleep(float(参数.get("等待秒", 0.15)))
    return {"取消已见": 取消事件.is_set()}


def 任务主动崩溃(参数: dict) -> None:
    os._exit(int(参数.get("退出码", 7)))


def 发送网关请求(地址: str, 数据: dict) -> tuple[int, dict]:
    请求 = urllib.request.Request(
        地址 + "/%E7%BD%91%E5%85%B3/%E8%B0%83%E7%94%A8",
        data=json.dumps(数据, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(请求, timeout=2) as 响应:
            return 响应.status, json.loads(响应.read().decode("utf-8"))
    except urllib.error.HTTPError as 错误:
        with 错误:
            return 错误.code, json.loads(错误.read().decode("utf-8"))


def 发送流式请求(地址: str, 数据: dict) -> tuple[int, str, list[dict]]:
    请求 = urllib.request.Request(
        地址 + "/%E7%BD%91%E5%85%B3/%E6%B5%81%E5%BC%8F",
        data=json.dumps(数据, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(请求, timeout=2) as 响应:
            事件列表 = []
            for 原始行 in 响应:
                行 = 原始行.decode("utf-8").strip()
                if 行.startswith("data: "):
                    事件列表.append(json.loads(行[6:]))
            return 响应.status, 响应.headers.get_content_type(), 事件列表
    except urllib.error.HTTPError as 错误:
        with 错误:
            return 错误.code, 错误.headers.get_content_type(), [
                json.loads(错误.read().decode("utf-8"))
            ]


def 构建浏览器请求():
    窗口 = 窗口定义(
        "第八阶段窗口",
        "第八阶段真实交互",
        [页面定义("主页", "/", "计算", [
            组件定义("输入框", "输入框", {"默认值": "1"}, ["输入"]),
            组件定义("调用按钮", "按钮", {
                "文本": "执行", "能力id": "第八阶段.相加",
                "参数": {"甲": 1, "乙": 2}, "回调": "结果区",
            }, ["点击"]),
            组件定义("加载状态", "状态区", {"默认值": "等待"}),
            组件定义("页面状态", "状态区", {"默认值": "等待"}),
            组件定义("结果区", "状态区", {"默认值": ""}),
            组件定义("错误区", "状态区", {"默认值": ""}),
        ])],
    )
    前端 = 前端核心(浏览器交互提供者("http://127.0.0.1:1"))
    前端.注册窗口(窗口)
    前端.打开窗口(窗口.窗口id)
    return 前端, 窗口


class Test真实HTTP浏览器链路(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.后端 = 构建后端()
        cls.服务器 = 本地网关服务器(网关核心实例=网关核心(cls.后端), 端口=0)
        成功, 消息 = cls.服务器.启动()
        assert 成功, 消息
        cls.地址 = f"http://127.0.0.1:{cls.服务器.端口}"

    @classmethod
    def tearDownClass(cls):
        cls.服务器.优雅停止()
        cls.后端.优雅关闭()

    def test_真实HTTP能力调用产生业务结果(self):
        状态码, 数据 = 发送网关请求(self.地址, {
            "操作": "调用能力", "能力id": "第八阶段.相加", "参数": {"甲": 20, "乙": 22},
        })
        self.assertEqual(状态码, 200)
        self.assertTrue(数据["成功"])
        self.assertEqual(数据["值"]["和"], 42)
        self.assertTrue(数据["请求id"])

    def test_真实HTTP未知能力返回稳定错误(self):
        _, 数据 = 发送网关请求(self.地址, {"操作": "调用能力", "能力id": "不存在.能力"})
        self.assertFalse(数据["成功"])
        self.assertEqual(数据["错误码"], "能力不存在")

    def test_浏览器页面调用真实网关地址(self):
        前端, 窗口 = 构建浏览器请求()
        前端.渲染提供者 = 浏览器交互提供者(self.地址)
        页面 = 前端.渲染(窗口.窗口id)
        self.assertTrue(页面["成功"])
        self.assertIn(json.dumps(self.地址), 页面["html"])
        _, 数据 = 发送网关请求(self.地址, {
            "操作": "调用能力", "能力id": "第八阶段.相加", "参数": {"甲": 1, "乙": 2},
        })
        self.assertEqual(数据["值"]["和"], 3)

    def test_浏览器动态值不会突破脚本边界(self):
        前端, 窗口 = 构建浏览器请求()
        前端.设置状态("恶意", "</script><script>window.已注入=1</script>")
        页面 = 前端.渲染(窗口.窗口id)["html"]
        self.assertNotIn("</script><script>window.已注入=1</script>", 页面)


class TestHTTP流式(unittest.TestCase):
    def test_首个事件携带上下文(self):
        通道 = HTTP流式通道(请求id="请求一", 任务id="任务一", 能力id="能力一")
        事件 = 通道.首次事件()
        self.assertEqual(事件["事件类型"], "首个事件")
        self.assertEqual((事件["请求id"], 事件["任务id"], 事件["事件序号"]), ("请求一", "任务一", 1))

    def test_中间事件顺序严格递增(self):
        通道 = HTTP流式通道()
        通道.首次事件()
        通道.追加事件("中间事件", 1)
        通道.追加事件("中间事件", 2)
        self.assertEqual([项["事件序号"] for 项 in 通道.事件队列], [1, 2, 3])

    def test_完成事件不会自锁(self):
        通道 = HTTP流式通道()
        已返回, 事件 = 在线程内调用(lambda: 通道.完成("完成"))
        self.assertTrue(已返回, "完成事件发生自锁")
        self.assertEqual(事件["事件类型"], "完成事件")
        self.assertTrue(通道.结束)

    def test_失败事件不会自锁(self):
        通道 = HTTP流式通道()
        已返回, 事件 = 在线程内调用(lambda: 通道.失败("测试错误", "失败"))
        self.assertTrue(已返回, "失败事件发生自锁")
        self.assertEqual(事件["数据"]["错误码"], "测试错误")

    def test_取消事件不会自锁且幂等(self):
        通道 = HTTP流式通道()
        已返回, 事件 = 在线程内调用(通道.取消)
        self.assertTrue(已返回, "取消事件发生自锁")
        self.assertEqual(事件["事件类型"], "取消事件")
        self.assertEqual(通道.取消(), {})

    def test_管理器产生首中完三类事件(self):
        管理器 = HTTP流式管理器()
        通道 = 管理器.开始(能力id="流式.正常", 事件生成函数=lambda: iter([1, 2]))
        self.assertTrue(等待条件(lambda: 通道.结束, 0.5), "流式调用未进入完成终态")
        self.assertEqual([项["事件类型"] for 项 in 通道.事件队列],
                         ["首个事件", "中间事件", "中间事件", "完成事件"])
        self.assertTrue(等待条件(lambda: not 管理器.通道表), "终态通道未自动清理注册引用")

    def test_生成器异常产生失败终态(self):
        def 坏生成器():
            yield 1
            raise RuntimeError("受控失败")

        通道 = HTTP流式管理器().开始(能力id="流式.失败", 事件生成函数=坏生成器)
        self.assertTrue(等待条件(lambda: 通道.结束, 0.5), "异常流未进入失败终态")
        self.assertEqual(通道.事件队列[-1]["事件类型"], "失败事件")

    def test_结束回调异常仍自动清理通道(self):
        def 坏回调(_原因):
            raise RuntimeError("回调故障")

        管理器 = HTTP流式管理器()
        通道 = 管理器.开始(能力id="流式.回调故障", 事件生成函数=lambda: iter(()), 结束回调=坏回调)
        self.assertTrue(等待条件(lambda: 通道.结束, 0.5))
        self.assertTrue(等待条件(lambda: not 管理器.通道表), "结束回调异常导致通道残留")

    def test_客户端断开清除队列与注册引用(self):
        管理器 = HTTP流式管理器()
        门 = threading.Event()

        def 慢生成器():
            门.wait(0.3)
            yield 1

        通道 = 管理器.开始(能力id="流式.断开", 事件生成函数=慢生成器)
        管理器.断开(通道.请求id)
        门.set()
        self.assertTrue(通道.断开)
        self.assertTrue(通道.结束)
        self.assertEqual(通道.事件队列, [])
        self.assertIsNone(管理器.查询(通道.请求id))


class Test真实HTTP事件流(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.服务器 = 流式HTTP服务器(端口=0, 要求凭证=False)
        cls.服务器.注册能力("流式.正常", lambda 参数: iter([
            {"片段": 参数.get("前", "甲")}, {"片段": 参数.get("后", "乙")},
        ]))

        def 失败生成器(参数):
            yield {"片段": 参数.get("片段", "开始")}
            raise RuntimeError("受控提供者失败")

        cls.服务器.注册能力("流式.失败", 失败生成器)
        成功, 说明 = cls.服务器.启动()
        assert 成功, 说明
        cls.地址 = f"http://127.0.0.1:{cls.服务器.端口}"

    @classmethod
    def tearDownClass(cls):
        cls.服务器.优雅停止()

    def test_真实SSE响应类型与事件顺序(self):
        状态码, 类型, 事件列表 = 发送流式请求(self.地址, {
            "能力id": "流式.正常", "参数": {"前": "一", "后": "二"},
            "请求id": "真实请求", "任务id": "真实任务",
        })
        self.assertEqual((状态码, 类型), (200, "text/event-stream"))
        self.assertEqual([事件["事件类型"] for 事件 in 事件列表],
                         ["首个事件", "中间事件", "中间事件", "完成事件"])
        self.assertEqual([事件["事件序号"] for 事件 in 事件列表], [1, 2, 3, 4])
        self.assertEqual(事件列表[1]["数据"], {"片段": "一"})
        self.assertEqual(事件列表[2]["数据"], {"片段": "二"})

    def test_真实SSE上下文贯穿全部事件(self):
        _, _, 事件列表 = 发送流式请求(self.地址, {
            "能力id": "流式.正常", "请求id": "贯穿请求", "任务id": "贯穿任务",
        })
        self.assertTrue(事件列表)
        self.assertEqual({事件["请求id"] for 事件 in 事件列表}, {"贯穿请求"})
        self.assertEqual({事件["任务id"] for 事件 in 事件列表}, {"贯穿任务"})

    def test_真实SSE提供者异常形成唯一失败终态(self):
        状态码, _, 事件列表 = 发送流式请求(self.地址, {
            "能力id": "流式.失败", "参数": {"片段": "已发送"},
        })
        self.assertEqual(状态码, 200)
        终态列表 = [事件 for 事件 in 事件列表 if 事件["事件类型"] in {
            "完成事件", "失败事件", "取消事件", "超时事件",
        }]
        self.assertEqual(len(终态列表), 1)
        self.assertEqual(终态列表[0]["事件类型"], "失败事件")
        self.assertEqual(终态列表[0]["数据"]["错误码"], "提供者崩溃")

    def test_真实SSE未知能力返回404而非空事件流(self):
        状态码, 类型, 数据列表 = 发送流式请求(self.地址, {"能力id": "流式.不存在"})
        self.assertEqual((状态码, 类型), (404, "application/json"))
        self.assertEqual(数据列表, [{"成功": False, "错误码": "能力不存在"}])

    def test_真实SSE完成后服务端释放通道引用(self):
        _, _, 事件列表 = 发送流式请求(self.地址, {"能力id": "流式.正常"})
        self.assertEqual(事件列表[-1]["事件类型"], "完成事件")
        self.assertTrue(等待条件(lambda: not self.服务器.管理器.通道表),
                        "HTTP 响应完成后服务端仍残留流式通道")

    def _原始请求(self, 方法, 路径, 正文, 类型="application/json"):
        请求 = urllib.request.Request(
            self.地址 + 路径, data=正文, method=方法,
            headers={"Content-Type": 类型},
        )
        try:
            with urllib.request.urlopen(请求, timeout=2) as 响应:
                return 响应.status, 响应.headers.get_content_type(), json.loads(响应.read())
        except urllib.error.HTTPError as 错误:
            with 错误:
                return 错误.code, 错误.headers.get_content_type(), json.loads(错误.read())

    def test_畸形JSON拒绝且不启动能力(self):
        状态码, 类型, 数据 = self._原始请求("POST", "/%E7%BD%91%E5%85%B3/%E6%B5%81%E5%BC%8F", "{坏".encode())
        self.assertEqual((状态码, 类型), (400, "application/json"))
        self.assertEqual(数据["错误码"], "参数不合法")
        self.assertFalse(self.服务器.管理器.通道表)

    def test_非有限数和超大配额拒绝(self):
        路径 = "/%E7%BD%91%E5%85%B3/%E6%B5%81%E5%BC%8F"
        for 字段值 in ("NaN", "Infinity", "-Infinity"):
            正文 = (f'{{"能力id":"流式.正常","最大持续秒":{字段值}}}').encode()
            状态码, _, 数据 = self._原始请求("POST", 路径, 正文)
            self.assertEqual(状态码, 400)
            self.assertEqual(数据["错误码"], "参数不合法")
        状态码, _, 数据 = self._原始请求(
            "POST", 路径, '{"能力id":"流式.正常","最大事件数":10001}'.encode())
        self.assertEqual((状态码, 数据["错误码"]), (400, "参数不合法"))

    def test_GET返回JSON方法错误而非HTML(self):
        状态码, 类型, 数据 = self._原始请求("GET", "/%E7%BD%91%E5%85%B3/%E6%B5%81%E5%BC%8F", None)
        self.assertEqual((状态码, 类型), (405, "application/json"))
        self.assertEqual(数据["错误码"], "方法不允许")

    def test_真实客户端断开在无新事件时也清理通道(self):
        门 = threading.Event()

        def 长时间等待生成器(_参数):
            yield {"片段": "首事件"}
            门.wait(5)

        能力id = "流式.真实断开清理"
        self.服务器.注册能力(能力id, 长时间等待生成器)
        请求id = "真实断开请求"
        正文 = json.dumps({"能力id": 能力id, "请求id": 请求id}).encode("utf-8")
        套接字 = socket.create_connection(("127.0.0.1", self.服务器.端口), timeout=2)
        套接字.sendall(
            b"POST /%E7%BD%91%E5%85%B3/%E6%B5%81%E5%BC%8F HTTP/1.1\r\n"
            b"Host: 127.0.0.1\r\nContent-Type: application/json\r\n"
            b"Connection: close\r\nContent-Length: " + str(len(正文)).encode() + b"\r\n\r\n" + 正文
        )
        套接字.recv(4096)  # 读取响应头及首事件（首事件可能与响应头合并返回）
        套接字.shutdown(socket.SHUT_RDWR)
        套接字.close()
        try:
            self.assertTrue(
                等待条件(lambda: self.服务器.管理器.查询(请求id) is None, 1.0),
                "客户端断开后无新事件时通道仍残留",
            )
        finally:
            门.set()


class Test独立任务进程(unittest.TestCase):
    def setUp(self):
        self.临时对象 = tempfile.TemporaryDirectory(prefix="第八阶段任务_")
        self.临时目录 = Path(self.临时对象.name)
        self.进程池列表: list[任务进程池] = []

    def tearDown(self):
        for 进程池 in self.进程池列表:
            进程池.关闭全部()
        self.临时对象.cleanup()

    def _新池(self) -> 任务进程池:
        池 = 任务进程池(存储目录=self.临时目录 / "状态")
        self.进程池列表.append(池)
        return 池

    def test_真实子进程返回JSON结果(self):
        池 = self._新池()
        池.注册执行函数("任务.进程", 任务返回进程id)
        任务 = 池.提交(能力id="任务.进程", 参数={"甲": 1})
        self.assertTrue(等待条件(lambda: 任务.状态 in 终态集合))
        self.assertEqual(任务.状态, "成功")
        self.assertNotEqual(任务.结果["进程id"], os.getpid())

    def test_任务成功后进程退出并落盘(self):
        池 = self._新池()
        池.注册执行函数("任务.落盘", 任务返回进程id)
        任务 = 池.提交(能力id="任务.落盘")
        self.assertTrue(等待条件(lambda: 任务.状态 in 终态集合))
        self.assertTrue(等待条件(lambda: (self.临时目录 / '状态' / f'{任务.任务id}.json').is_file()))
        self.assertIsNotNone(任务.进程)
        self.assertFalse(任务.进程.is_alive())

    def test_任务超时进入终态且进程退出(self):
        池 = self._新池()
        池.注册执行函数("任务.超时", 任务短暂停顿)
        任务 = 池.提交(能力id="任务.超时", 参数={"等待秒": 0.2}, 超时秒=0.03)
        self.assertTrue(等待条件(lambda: 任务.状态 in 终态集合))
        self.assertEqual(任务.状态, "超时")
        self.assertTrue(等待条件(lambda: not 任务.进程.is_alive()))

    def test_任务取消进入已取消且进程退出(self):
        池 = self._新池()
        池.注册执行函数("任务.取消", 任务短暂停顿)
        任务 = 池.提交(能力id="任务.取消", 参数={"等待秒": 0.2}, 超时秒=1)
        成功, _ = 池.取消(任务.任务id)
        self.assertTrue(成功)
        self.assertTrue(等待条件(lambda: 任务.状态 in 终态集合))
        self.assertEqual(任务.状态, "已取消")
        self.assertTrue(等待条件(lambda: not 任务.进程.is_alive()))

    def test_工作器崩溃记录退出状态(self):
        池 = self._新池()
        池.注册执行函数("任务.崩溃", 任务主动崩溃)
        任务 = 池.提交(能力id="任务.崩溃", 参数={"退出码": 7})
        self.assertTrue(等待条件(lambda: 任务.状态 in 终态集合))
        self.assertEqual(任务.状态, "崩溃")
        self.assertIn("退出", 任务.错误说明)

    def test_持久化任务可由新进程池恢复(self):
        池 = self._新池()
        池.注册执行函数("任务.恢复", lambda 参数: {"恢复": True})
        任务 = 池.提交(能力id="任务.恢复")
        self.assertTrue(等待条件(lambda: 任务.状态 in 终态集合))
        状态文件 = self.临时目录 / "状态" / f"{任务.任务id}.json"

        def 最终结果已落盘() -> bool:
            try:
                return json.loads(状态文件.read_text(encoding="utf-8")).get("结果") == {"恢复": True}
            except (FileNotFoundError, json.JSONDecodeError, OSError):
                return False

        self.assertTrue(等待条件(最终结果已落盘), "任务终态结果未完成原子落盘")
        新池 = self._新池()
        self.assertEqual(新池.查询(任务.任务id).结果, {"恢复": True})


class Test自动计数与排空(unittest.TestCase):
    def test_正常调用自动回收请求计数(self):
        后端 = 构建后端()
        后端.启用自动排空()
        self.assertTrue(后端.调用("第八阶段.相加", {"甲": 1, "乙": 2}).成功)
        self.assertEqual(后端.排空.活动总数(), 0)

    def test_异常调用自动回收请求计数(self):
        后端 = 构建后端()
        后端.启用自动排空()
        self.assertFalse(后端.调用("第八阶段.异常").成功)
        self.assertEqual(后端.排空.活动总数(), 0)
        self.assertEqual(后端.状态.活动请求数, 0)

    def test_排空开始后真实拒绝新请求(self):
        后端 = 构建后端()
        后端.启用自动排空()
        后端.排空.停止接收新请求 = True
        结果 = 后端.调用("第八阶段.相加", {"甲": 1, "乙": 2})
        self.assertFalse(结果.成功)
        self.assertIn("排空中", 结果.错误说明)

    def test_重复释放不会产生负计数(self):
        排空 = 排空管理器()
        排空.结束请求(); 排空.结束任务(); 排空.释放连接(); 排空.释放句柄()
        self.assertEqual(排空.活动总数(), 0)

    def test_正常排空要求四类资源归零(self):
        排空 = 排空管理器(排空超时秒=0.5)
        排空.开始请求(); 排空.开始任务(); 排空.记录连接(); 排空.记录句柄()
        排空.结束请求(); 排空.结束任务(); 排空.释放连接(); 排空.释放句柄()
        结果 = 排空.排空()
        self.assertTrue(结果.成功)
        self.assertEqual(排空.活动总数(), 0)

    def test_排空超时不得把未释放资源标成成功(self):
        排空 = 排空管理器(排空超时秒=0.03, 允许强制终止=True)
        排空.开始请求(); 排空.记录连接()
        结果 = 排空.排空()
        self.assertFalse(结果.成功, "资源仍存在时不得报告排空成功")
        self.assertGreater(排空.活动总数(), 0)
        self.assertTrue(结果.诊断记录)


class Test事务崩溃恢复(unittest.TestCase):
    def setUp(self):
        self.临时对象 = tempfile.TemporaryDirectory(prefix="第八阶段事务_")
        self.目录 = Path(self.临时对象.name)

    def tearDown(self):
        self.临时对象.cleanup()

    def test_准备阶段崩溃执行真实回滚副作用(self):
        标记 = self.目录 / "已回滚"
        恢复器 = 事务恢复(self.目录)
        恢复器.注册回滚函数("删除临时状态", lambda 记录: 标记.write_text(记录.操作id, encoding="utf-8"))
        操作id = 恢复器.记录准备(操作名="安装", 回滚函数名="删除临时状态")
        结果 = 恢复器.恢复()
        self.assertEqual(结果[0]["处理"], "回滚")
        self.assertEqual(标记.read_text(encoding="utf-8"), 操作id)
        self.assertEqual(恢复器.查询(操作id).阶段, "回滚")

    def test_提交阶段崩溃继续完成(self):
        恢复器 = 事务恢复(self.目录)
        操作id = 恢复器.记录准备(操作名="激活")
        恢复器.记录提交(操作id)
        新实例 = 事务恢复(self.目录)
        结果 = 新实例.恢复()
        self.assertEqual(结果[0]["处理"], "继续完成")
        self.assertEqual(新实例.查询(操作id).阶段, "完成")

    def test_未完成事务会阻断新发布(self):
        恢复器 = 事务恢复(self.目录)
        恢复器.记录准备(操作名="卸载")
        self.assertTrue(恢复器.拒绝半成品())

    def test_损坏日志不会伪造完成记录(self):
        (self.目录 / "操作日志.jsonl").write_text("{损坏\n", encoding="utf-8")
        恢复器 = 事务恢复(self.目录)
        self.assertEqual(恢复器.操作表, {})
        self.assertEqual(恢复器.扫描未完成(), [])


class Test安全限流与审计(unittest.TestCase):
    def test_凭证从环境变量加载且清除内存值(self):
        名称 = "第八阶段测试凭证"
        os.environ[名称] = "strong-test-secret"
        try:
            管理器 = 凭证管理器(名称)
            self.assertTrue(管理器.加载()[0])
            self.assertTrue(管理器.校验("strong-test-secret")[0])
            管理器.清除()
            self.assertFalse(管理器.校验("strong-test-secret")[0])
        finally:
            os.environ.pop(名称, None)

    def test_缺失凭证明确定性失败(self):
        名称 = "确定不存在的第八阶段凭证"
        os.environ.pop(名称, None)
        成功, 消息 = 凭证管理器(名称).加载()
        self.assertFalse(成功)
        self.assertIn(名称, 消息)

    def test_请求大小边界真实拒绝超限(self):
        限制 = 请求限制器(安全配置(请求大小上限=8))
        self.assertTrue(限制.校验大小(8)[0])
        self.assertFalse(限制.校验大小(9)[0])

    def test_路径白名单拒绝穿越路径(self):
        限制 = 请求限制器()
        self.assertTrue(限制.校验路径("/健康")[0])
        self.assertFalse(限制.校验路径("/../私有")[0])

    def test_监听地址拒绝全部网卡(self):
        限制 = 请求限制器()
        self.assertFalse(限制.校验监听地址("0.0.0.0")[0])
        self.assertTrue(限制.校验监听地址("127.0.0.1")[0])

    def test_错误与参数不可逆脱敏(self):
        原文 = "sk-abcdefghijklmnopqrstuvwxyz123456"
        self.assertNotIn(原文, 脱敏错误信息(f"连接失败 {原文}"))
        参数 = 脱敏参数({"令牌": 原文, "普通": "值"}, {"令牌"})
        self.assertEqual(参数, {"令牌": "已脱敏", "普通": "值"})

    def test_请求并发维度限流并可回收(self):
        限流 = 限流器(最大并发请求=1)
        self.assertTrue(限流.进入请求()[0])
        self.assertFalse(限流.进入请求()[0])
        限流.离开请求()
        self.assertTrue(限流.进入请求()[0])
        限流.离开请求()

    def test_用户维度频率限流(self):
        限流 = 限流器(单用户频率=1, 单能力频率=10)
        self.assertTrue(限流.进入请求(用户id="用户甲")[0]); 限流.离开请求()
        self.assertFalse(限流.进入请求(用户id="用户甲")[0])

    def test_能力维度频率限流(self):
        限流 = 限流器(单用户频率=10, 单能力频率=1)
        self.assertTrue(限流.进入请求(能力id="能力甲")[0]); 限流.离开请求()
        self.assertFalse(限流.进入请求(能力id="能力甲")[0])

    def test_任务维度限流(self):
        限流 = 限流器(最大任务数=1)
        self.assertTrue(限流.进入任务()[0])
        self.assertFalse(限流.进入任务()[0])
        限流.离开任务()
        self.assertEqual(限流.状态快照()["任务数"], 0)

    def test_提供者流式连接维度限流(self):
        限流 = 限流器(最大流式连接=1)
        self.assertTrue(限流.进入流式()[0])
        self.assertFalse(限流.进入流式()[0])
        限流.离开流式()
        self.assertEqual(限流.状态快照()["流式连接数"], 0)

    def test_审计真实写入并按失败维度查询(self):
        with tempfile.TemporaryDirectory(prefix="第八阶段审计_") as 目录:
            审计器 = 安全审计(Path(目录))
            审计id = 审计器.记录(操作="调用", 用户id="用户甲", 能力id="能力甲",
                              成功=False, 失败原因="权限不足", 权限拒绝=True)
            self.assertTrue(审计id)
            原始行 = 审计器.审计文件.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(原始行), 1)
            self.assertEqual(审计器.查询(权限拒绝=True)[0]["审计id"], 审计id)

    def test_审计统计反映真实副作用(self):
        with tempfile.TemporaryDirectory(prefix="第八阶段审计统计_") as 目录:
            审计器 = 安全审计(Path(目录))
            审计器.记录(操作="通过", 成功=True)
            审计器.记录(操作="拒绝", 成功=False, 被限流=True, 触发回滚=True)
            self.assertEqual(审计器.统计()["总记录数"], 2)
            self.assertEqual(审计器.统计()["被限流数"], 1)
            self.assertEqual(审计器.统计()["触发回滚数"], 1)


class Test资源门禁与性能(unittest.TestCase):
    def test_网关停止后端口真实释放(self):
        后端 = 构建后端()
        服务器 = 本地网关服务器(网关核心实例=网关核心(后端), 端口=0)
        self.assertTrue(服务器.启动()[0])
        端口 = 服务器.端口
        self.assertFalse(检查端口可用(端口))
        服务器.优雅停止()
        self.assertTrue(等待条件(lambda: 检查端口可用(端口)))

    def test_关闭全部真实终止残留子进程(self):
        with tempfile.TemporaryDirectory(prefix="第八阶段进程清理_") as 目录:
            池 = 任务进程池(存储目录=Path(目录) / "状态")
            池.注册执行函数("任务.长", 任务短暂停顿)
            任务 = 池.提交(能力id="任务.长", 参数={"等待秒": 5})
            self.assertIsNotNone(任务.进程)
            池.关闭全部()
            self.assertTrue(等待条件(lambda: not 任务.进程.is_alive()))

    def test_门禁反向篡改锁与摘要必须阻断(self):
        from 开发工具.发布门禁.运行发布门禁 import _校验依赖锁与反向篡改, _校验文件清单摘要
        with tempfile.TemporaryDirectory(prefix="第八阶段门禁篡改_") as 目录:
            包目录 = Path(目录)
            (包目录 / "能力契约").mkdir()
            (包目录 / "实现").mkdir()
            (包目录 / "包声明.json").write_text(
                json.dumps({"包id": "篡改.包", "版本": "1.0.0", "类型": "支持库"}, ensure_ascii=False),
                encoding="utf-8",
            )
            实现文件 = 包目录 / "实现" / "能力.py"
            实现文件.write_text("值 = 1\n", encoding="utf-8")
            文件清单 = []
            for 文件 in sorted(包目录.rglob("*")):
                if 文件.is_file() and 文件.name != "完整性摘要.json":
                    import hashlib
                    文件清单.append({
                        "路径": 文件.relative_to(包目录).as_posix(),
                        "sha256": hashlib.sha256(文件.read_bytes()).hexdigest(),
                    })
            (包目录 / "完整性摘要.json").write_text(json.dumps({
                "包id": "篡改.包", "版本": "1.0.0", "文件清单": 文件清单,
            }, ensure_ascii=False), encoding="utf-8")

            摘要成功, _ = _校验文件清单摘要(包目录)
            self.assertTrue(摘要成功, "篡改前的真实文件清单应通过")
            实现文件.write_text("值 = 2\n", encoding="utf-8")
            摘要成功, 摘要证据 = _校验文件清单摘要(包目录)
            self.assertFalse(摘要成功)
            self.assertIn("文件摘要不一致", 摘要证据)

        锁一致, _, 锁篡改阻断, 锁篡改证据 = _校验依赖锁与反向篡改()
        self.assertTrue(锁一致, "基线依赖锁必须先真实通过")
        self.assertTrue(锁篡改阻断, 锁篡改证据)

    def test_浏览器渲染性能分层(self):
        前端, 窗口 = 构建浏览器请求()
        开始 = time.perf_counter()
        for _ in range(20):
            前端.渲染(窗口.窗口id)
        self.assertLess(time.perf_counter() - 开始, 0.2)

    def test_安全限流性能分层(self):
        限流 = 限流器(单用户频率=10000, 单能力频率=10000)
        开始 = time.perf_counter()
        for 序号 in range(1000):
            通过, _ = 限流.进入请求(用户id=f"用户{序号}", 能力id=f"能力{序号}")
            self.assertTrue(通过)
            限流.离开请求()
        self.assertLess(time.perf_counter() - 开始, 0.2)

    def test_事务持久化性能分层(self):
        with tempfile.TemporaryDirectory(prefix="第八阶段性能事务_") as 目录:
            恢复器 = 事务恢复(Path(目录))
            开始 = time.perf_counter()
            for 序号 in range(20):
                操作id = 恢复器.记录准备(操作名=f"操作{序号}")
                恢复器.记录提交(操作id)
                恢复器.记录完成(操作id)
            self.assertLess(time.perf_counter() - 开始, 0.3)
            self.assertEqual(len(恢复器.扫描未完成()), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
