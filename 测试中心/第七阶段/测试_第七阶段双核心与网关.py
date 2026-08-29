"""第七阶段：前后端双核心、统一网关与跨宿主运行闭环测试。"""

from __future__ import annotations

import json
import sys
import tempfile
import threading
import time
import unittest
import urllib.request
import urllib.parse
import urllib.error
from pathlib import Path

系统根 = Path(__file__).resolve().parents[2]
if str(系统根) not in sys.path:
    sys.path.insert(0, str(系统根))

from 后端核心.后端核心 import 后端核心
from 前端核心.前端核心 import 组件定义, 窗口定义, 页面定义, 前端核心
from 前端核心.渲染提供者 import HTML渲染提供者, 测试渲染提供者
from 运行核心.统一网关.网关核心 import 网关核心, 网关请求
from 运行核心.统一网关.流式语义 import 流式调用, 流式管理器
from 运行核心.统一网关.本地网关 import 本地网关服务器, 检查端口可用
from 运行核心.能力调用.运行上下文.上下文 import 运行上下文, 上下文管理器


from functools import lru_cache


@lru_cache(maxsize=1)
def 建缓存后端() -> 后端核心:
    """共享只读后端实例（装配 64 能力开销大，只读测试复用）。"""
    return 建后端()


def 建后端() -> 后端核心:
    后端 = 后端核心()
    后端.启动()

    def 加法能力(甲: int = 0, 乙: int = 0) -> dict:
        return {"和": 甲 + 乙}

    def 慢能力(秒: float = 0.05) -> dict:
        time.sleep(秒)
        return {"完成": True}

    后端.注册能力("示例.加法", 加法能力, 参数=[
        {"名称": "甲", "类型": "整数", "必填": False},
        {"名称": "乙", "类型": "整数", "必填": False},
    ], 返回="结果", 说明="整数加法（示例能力）")
    后端.注册能力("示例.慢操作", 慢能力)
    return 后端


class Test后端核心(unittest.TestCase):
    """场景1-3：启动/注册/调用。"""

    @classmethod
    def setUpClass(cls):
        cls.后端 = 建缓存后端()

    def test_后端核心启动(self):
        快照 = self.后端.状态快照()
        self.assertEqual(快照["状态"], "运行中")
        self.assertGreater(快照["能力数"], 50)  # 支持库装配 + 示例能力

    def test_后端能力注册(self):
        from 公共契约.基础类型.结果类型 import 结果 as _结果
        注册结果 = self.后端.注册能力("示例.注册测试", lambda: 1)
        self.assertTrue(注册结果.成功)
        self.assertIsNotNone(self.后端.注册表.获取("示例.注册测试"))

    def test_后端能力调用(self):
        结果 = self.后端.调用("示例.加法", {"甲": 3, "乙": 4})
        self.assertTrue(结果.成功)
        self.assertEqual(结果.值["和"], 7)

    def test_后端权限检查(self):
        后端 = 建后端()  # 独立实例，避免污染共享后端权限表
        结果 = 后端.调用("示例.加法", {"甲": 1, "乙": 2}, 上下文=运行上下文(用户id="访客"))
        self.assertTrue(结果.成功)  # 未设权限表时默认放行
        # 显式权限检查
        后端.设置权限("示例.加法", ["管理员"])
        结果2 = 后端.调用("示例.加法", {"甲": 1, "乙": 2}, 上下文=运行上下文(用户id="访客"))
        self.assertFalse(结果2.成功)
        self.assertEqual(结果2.错误码, "权限不足")
        # 授权用户放行
        结果3 = 后端.调用("示例.加法", {"甲": 1, "乙": 2}, 上下文=运行上下文(用户id="管理员"))
        self.assertTrue(结果3.成功)

    def test_后端优雅关闭(self):
        后端2 = 建后端()
        结果 = 后端2.优雅关闭()
        self.assertTrue(结果.成功)
        结果2 = 后端2.调用("示例.加法", {"甲": 1, "乙": 2})
        self.assertFalse(结果2.成功)  # 停止后调用失败


class Test前端核心(unittest.TestCase):
    """场景4-9：窗口/页面/状态/事件/渲染。"""

    def setUp(self):
        self.前端 = 前端核心(渲染提供者=测试渲染提供者())
        self.窗口 = 窗口定义(
            窗口id="测试窗口", 标题="测试",
            页面列表=[页面定义(
                "主页", "/", "测试页",
                [组件定义("输入", "输入框", {"默认值": "a"}, ["输入"]),
                 组件定义("按钮", "按钮", {"文本": "点我"}, ["点击"]),
                 组件定义("结果", "状态区", {}, [])],
            )],
            后端能力依赖=["示例.加法"],
        )
        self.前端.注册窗口(self.窗口)

    def test_前端核心启动(self):
        快照 = self.前端.状态快照()
        self.assertEqual(快照["窗口数"], 1)

    def test_窗口创建与打开关闭(self):
        打开 = self.前端.打开窗口("测试窗口")
        self.assertTrue(打开["成功"])
        self.assertEqual(self.窗口.状态, "已打开")
        关闭 = self.前端.关闭窗口("测试窗口")
        self.assertTrue(关闭["成功"])
        self.assertEqual(self.窗口.状态, "已关闭")

    def test_页面装配(self):
        self.assertEqual(len(self.窗口.页面列表), 1)
        self.assertEqual(self.窗口.页面列表[0].路由, "/")
        self.assertEqual(len(self.窗口.页面列表[0].组件列表), 3)

    def test_状态变化(self):
        变化记录 = []
        self.前端.绑定事件("状态变化", lambda 数据: 变化记录.append(数据))
        self.前端.设置状态("输入", "新值")
        self.assertEqual(self.前端.获取状态("输入"), "新值")
        self.assertEqual(变化记录[0]["键"], "输入")

    def test_事件绑定与触发(self):
        触发记录 = []
        self.前端.绑定事件("点击", lambda 数据: 触发记录.append(数据))
        self.前端.触发事件("点击", {"组件": "按钮"})
        self.assertEqual(len(触发记录), 1)

    def test_测试渲染提供者(self):
        self.前端.设置状态("输入", "abc")
        渲染结果 = self.前端.渲染("测试窗口")
        self.assertTrue(渲染结果["成功"])
        self.assertIn("测试", 渲染结果["文本"])
        self.assertIn("abc", 渲染结果["文本"])

    def test_HTML渲染提供者(self):
        前端 = 前端核心(渲染提供者=HTML渲染提供者())
        前端.注册窗口(self.窗口)
        渲染结果 = 前端.渲染("测试窗口")
        self.assertTrue(渲染结果["成功"])
        self.assertIn("<html", 渲染结果["html"])
        self.assertIn("测试页", 渲染结果["html"])


class Test本地网关(unittest.TestCase):
    """场景10-15 + 29-30：HTTP 网关全功能。"""

    @classmethod
    def setUpClass(cls):
        cls.后端 = 建缓存后端()
        cls.网关核心实例 = 网关核心(cls.后端)
        cls.服务器 = 本地网关服务器(
            网关核心实例=cls.网关核心实例, 端口=0,
            配置={"请求超时秒": 3},
        )
        成功, 消息 = cls.服务器.启动()
        assert 成功, 消息
        cls.地址 = f"http://127.0.0.1:{cls.服务器.端口}"

    @classmethod
    def tearDownClass(cls):
        cls.服务器.优雅停止()

    def _发送(self, 路径: str, 数据: dict) -> tuple[int, dict]:
        from urllib.parse import quote
        编码路径 = quote(路径, safe="/")
        请求 = urllib.request.Request(
            self.地址 + 编码路径,
            data=json.dumps(数据, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(请求, timeout=5) as 响应:
                return 响应.status, json.loads(响应.read().decode("utf-8"))
        except urllib.error.HTTPError as 错误:
            return 错误.code, json.loads(错误.read().decode("utf-8"))

    def test_网关启动与健康检查(self):
        from urllib.parse import quote
        with urllib.request.urlopen(self.地址 + quote("/健康"), timeout=5) as 响应:
            数据 = json.loads(响应.read().decode("utf-8"))
        self.assertTrue(数据["成功"])
        self.assertEqual(数据["值"]["状态"], "健康")

    def test_网关能力调用(self):
        状态码, 响应 = self._发送("/网关/调用", {"能力id": "示例.加法", "参数": {"甲": 2, "乙": 3}})
        self.assertEqual(状态码, 200)
        self.assertTrue(响应["成功"])
        self.assertEqual(响应["值"]["和"], 5)
        self.assertTrue(响应["请求id"])

    def test_网关缺能力id原地拒绝(self):
        """调用者只提交能力id和参数，缺能力id必须在 HTTP 边界拒绝。"""
        状态码, 响应 = self._发送("/网关/调用", {"参数": {"甲": 4}})
        self.assertEqual(状态码, 400)
        self.assertFalse(响应["成功"])
        self.assertEqual(响应["错误码"], "参数不合法")

    def test_网关未知能力失败(self):
        状态码, 响应 = self._发送("/网关/调用", {"能力id": "不存在.能力", "参数": {}})
        self.assertFalse(响应["成功"])
        self.assertEqual(响应["错误码"], "能力不存在")

    def test_网关缺少声明必填参数原地拒绝(self):
        """声明必填参数缺失时，不能等实现函数才发现。"""
        调用记录 = []

        def 必填能力(值):
            调用记录.append(值)
            return {"值": 值}

        后端 = 建后端()
        后端.注册能力(
            "示例.必填", 必填能力,
            参数=[{"名称": "值", "类型": "整数型", "必填": True}],
        )
        服务器 = 本地网关服务器(
            网关核心实例=网关核心(后端), 端口=0,
            配置={"请求超时秒": 3},
        )
        成功, 消息 = 服务器.启动()
        self.assertTrue(成功, 消息)
        try:
            地址 = f"http://127.0.0.1:{服务器.端口}"
            请求 = urllib.request.Request(
                urllib.parse.quote(地址 + "/网关/调用", safe=":/@._-"),
                data=json.dumps({"能力id": "示例.必填", "参数": {}}).encode("utf-8"),
                headers={"Content-Type": "application/json"},
            )
            with self.assertRaises(urllib.error.HTTPError) as 上下文:
                urllib.request.urlopen(请求, timeout=5)
            self.assertEqual(上下文.exception.code, 400)
            响应 = json.loads(上下文.exception.read().decode("utf-8"))
            self.assertFalse(响应["成功"])
            self.assertEqual(响应["错误码"], "参数不合法")
            self.assertIn("缺少必填参数 值", 响应["错误说明"])
            self.assertEqual(调用记录, [])
        finally:
            服务器.优雅停止()

    def test_网关拒绝能力参数基础类型漂移(self):
        """逻辑/文本/列表/字典参数类型错误时，不能进入能力实现。"""
        调用记录 = []

        def 文本能力(值):
            调用记录.append(("文本", 值))
            return 值

        def 逻辑能力(开启):
            调用记录.append(("逻辑", 开启))
            return 开启

        def 列表能力(项目):
            调用记录.append(("列表", 项目))
            return 项目

        def 字典能力(配置):
            调用记录.append(("字典", 配置))
            return 配置

        后端 = 建后端()
        for 能力id, 函数, 名称, 类型 in (
            ("示例.文本类型", 文本能力, "值", "文本型"),
            ("示例.逻辑类型", 逻辑能力, "开启", "逻辑型"),
            ("示例.列表类型", 列表能力, "项目", "列表型"),
            ("示例.字典类型", 字典能力, "配置", "字典型"),
        ):
            后端.注册能力(
                能力id, 函数,
                参数=[{"名称": 名称, "类型": 类型, "必填": True}],
            )
        服务器 = 本地网关服务器(
            网关核心实例=网关核心(后端), 端口=0,
            配置={"请求超时秒": 3},
        )
        成功, 消息 = 服务器.启动()
        self.assertTrue(成功, 消息)
        try:
            错误请求 = (
                ("示例.文本类型", {"值": 123}),
                ("示例.逻辑类型", {"开启": "false"}),
                ("示例.列表类型", {"项目": {"不是": "列表"}}),
                ("示例.字典类型", {"配置": ["不是字典"]}),
            )
            def 发送(端口: int, 路径: str, 数据: dict) -> tuple[int, dict]:
                请求 = urllib.request.Request(
                    urllib.parse.quote(f"http://127.0.0.1:{端口}{路径}", safe=":/@._-"),
                    data=json.dumps(数据).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                )
                try:
                    with urllib.request.urlopen(请求, timeout=5) as 响应:
                        return 响应.status, json.loads(响应.read().decode("utf-8"))
                except urllib.error.HTTPError as 错误:
                    return 错误.code, json.loads(错误.read().decode("utf-8"))

            for 能力id, 参数 in 错误请求:
                状态码, 响应 = 发送(服务器.端口, "/网关/调用", {
                    "能力id": 能力id, "参数": 参数,
                })
                self.assertEqual(状态码, 400, 能力id)
                self.assertFalse(响应["成功"], 能力id)
                self.assertEqual(响应["错误码"], "参数不合法", 能力id)
            self.assertEqual(调用记录, [])
        finally:
            服务器.优雅停止()

    def test_网关参数错误(self):
        状态码, 响应 = self._发送("/网关/调用", {"能力id": "", "参数": {}})
        self.assertFalse(响应["成功"])
        self.assertEqual(响应["错误码"], "参数不合法")

    def test_网关未知路径失败(self):
        状态码, 响应 = self._发送("/不存在的路径", {})
        self.assertEqual(状态码, 404)
        self.assertEqual(响应["错误码"], "未知路径")

    def test_网关端口占用失败(self):
        占用服务器 = 本地网关服务器(网关核心实例=self.网关核心实例, 端口=self.服务器.端口)
        成功, 消息 = 占用服务器.启动()
        self.assertFalse(成功)
        self.assertIn("端口占用", 消息)
        self.assertFalse(检查端口可用(self.服务器.端口))

    def test_网关优雅停止(self):
        # 使用独立服务器验证优雅停止（不碰共享服务器）
        独立服务器 = 本地网关服务器(网关核心实例=self.网关核心实例, 端口=0)
        成功, _ = 独立服务器.启动()
        self.assertTrue(成功)
        from urllib.parse import quote
        with urllib.request.urlopen(f"http://127.0.0.1:{独立服务器.端口}" + quote("/健康"), timeout=5) as 响应:
            self.assertEqual(响应.status, 200)
        成功, 消息 = 独立服务器.优雅停止()
        self.assertTrue(成功, 消息)
        # 停止后连接失败
        with self.assertRaises(Exception):
            urllib.request.urlopen(f"http://127.0.0.1:{独立服务器.端口}" + quote("/健康"), timeout=2)


class Test异步任务(unittest.TestCase):
    """场景16-18：任务提交/查询/取消。"""

    def test_任务提交与查询(self):
        from 运行核心.任务调度.任务系统 import 任务系统
        临时目录 = Path(tempfile.mkdtemp(prefix="第七阶段任务_"))
        系统 = 任务系统(临时目录)
        系统.注册执行函数("示例.加法", lambda 参数, 取消: {"和": 参数.get("甲", 0) + 参数.get("乙", 0)})
        任务对象 = 系统.提交(能力id="示例.加法", 参数={"甲": 5, "乙": 6})
        self.assertTrue(任务对象.任务id)
        # 等待完成
        截止 = time.time() + 3
        while 系统.查询状态(任务对象.任务id) not in ("成功", "失败") and time.time() < 截止:
            time.sleep(0.02)
        self.assertEqual(系统.查询状态(任务对象.任务id), "成功")
        self.assertEqual(系统.查询(任务对象.任务id).结果["和"], 11)

    def test_未知任务id明确失败(self):
        from 运行核心.任务调度.任务系统 import 任务系统
        系统 = 任务系统(Path(tempfile.mkdtemp(prefix="第七阶段任务_") + "/"))
        with self.assertRaises(KeyError):
            系统.查询("不存在的任务id")

    def test_任务取消(self):
        from 运行核心.任务调度.任务系统 import 任务系统
        系统 = 任务系统(Path(tempfile.mkdtemp(prefix="第七阶段任务_") + "/"))

        def 慢任务(参数, 取消):
            time.sleep(0.1)
            if 取消.is_set():
                return None
            return {"完成": True}

        系统.注册执行函数("示例.慢任务", 慢任务)
        任务对象 = 系统.提交(能力id="示例.慢任务")
        取消结果, _ = 系统.取消(任务对象.任务id)
        self.assertTrue(取消结果)
        # 重复取消幂等
        取消结果2, _ = 系统.取消(任务对象.任务id)
        self.assertTrue(取消结果2)
        截止 = time.time() + 2
        while 系统.查询状态(任务对象.任务id) not in ("已取消", "取消中", "失败") and time.time() < 截止:
            time.sleep(0.02)
        self.assertIn(系统.查询状态(任务对象.任务id), ("已取消", "取消中", "失败"))

    def test_任务诊断(self):
        from 运行核心.任务调度.任务系统 import 任务系统
        系统 = 任务系统(Path(tempfile.mkdtemp(prefix="第七阶段任务_") + "/"))
        任务对象 = 系统.提交(能力id="未注册.能力")
        截止 = time.time() + 3
        while 系统.查询状态(任务对象.任务id) not in ("成功", "失败") and time.time() < 截止:
            time.sleep(0.02)
        诊断 = 系统.查询诊断(任务对象.任务id)
        self.assertEqual(诊断["状态"], "失败")
        self.assertEqual(诊断["错误码"], "能力不存在")


class Test流式语义(unittest.TestCase):
    """场景19-20：流式调用 + 客户端断开清理。"""

    def test_流式调用(self):
        管理器 = 流式管理器()

        def 事件生成():
            yield {"片段": "第1段"}
            yield {"片段": "第2段"}
            yield {"片段": "第3段"}

        调用 = 管理器.开始("示例.流式", 事件生成)
        self.assertEqual(调用.状态, "已完成")
        事件表 = [事件["事件类型"] for 事件 in 调用.全部事件()]
        self.assertIn("首个事件", 事件表)
        self.assertIn("中间事件", 事件表)
        self.assertIn("完成事件", 事件表)
        self.assertEqual(len([事件 for 事件 in 事件表 if 事件 == "中间事件"]), 3)

    def test_流式失败事件(self):
        管理器 = 流式管理器()

        def 坏生成():
            yield {"片段": "a"}
            raise RuntimeError("生成失败")

        调用 = 管理器.开始("示例.流式失败", 坏生成)
        self.assertEqual(调用.状态, "已失败")
        self.assertEqual(调用.错误码, "内部错误")

    def test_客户端断开清理(self):
        管理器 = 流式管理器()

        def 有限生成():
            for 序号 in range(100):
                yield {"片段": f"第{序号}段"}

        调用 = 管理器.开始("示例.有限流", 有限生成)
        管理器.断开(调用.调用id)
        self.assertEqual(调用.状态, "已断开")
        self.assertEqual(调用.事件列表, [])  # 资源已释放
        self.assertNotIn(调用.调用id, 管理器.调用表)  # 引用已释放

    def test_流式取消(self):
        管理器 = 流式管理器()
        调用 = 流式调用(调用id="流1", 能力id="示例.流")
        管理器.调用表[调用.调用id] = 调用
        取消结果 = 管理器.取消(调用.调用id)
        self.assertTrue(取消结果)
        self.assertEqual(调用.状态, "已取消")
        # 重复取消幂等（终态）
        self.assertFalse(管理器.取消(调用.调用id))


class Test跨核心链路(unittest.TestCase):
    """场景21-22：前后端跨核心成功链路 + 前端显示后端错误。"""

    @classmethod
    def setUpClass(cls):
        cls.后端 = 建缓存后端()

    def test_前后端跨核心成功链路(self):
        后端 = self.后端
        前端 = 前端核心(渲染提供者=测试渲染提供者())
        窗口 = 窗口定义(
            "跨核窗口", "跨核心示例",
            [页面定义("页", "/", "计算", [组件定义("结果", "状态区", {}, [])])],
            后端能力依赖=["示例.加法"],
        )
        前端.注册窗口(窗口)
        前端.设置调用入口(lambda 能力id, 参数: 网关核心(后端).处理(
            网关请求(操作="调用能力", 能力id=能力id, 参数=参数,
                     项目id="跨核项目", 用户id="跨核用户"),
        ).转字典())
        前端.打开窗口("跨核窗口")
        结果 = 前端.调用后端能力("示例.加法", {"甲": 10, "乙": 32})
        self.assertTrue(结果.get("成功"))
        前端.设置状态("结果", f"和 = {结果['值']['和']}")
        self.assertEqual(前端.获取状态("结果"), "和 = 42")
        渲染 = 前端.渲染("跨核窗口")
        self.assertIn("和 = 42", 渲染["文本"])  # 前端页面显示成功结果

    def test_前端显示后端错误(self):
        后端 = 建后端()
        前端 = 前端核心()
        前端.设置调用入口(lambda 能力id, 参数: 网关核心(后端).处理(
            网关请求(操作="调用能力", 能力id=能力id, 参数=参数),
        ).转字典())
        结果 = 前端.调用后端能力("不存在的.能力", {})
        self.assertFalse(结果.get("成功"))
        self.assertEqual(结果.get("错误码"), "能力不存在")
        前端.设置状态("错误区", f"{结果['错误码']}: {结果['错误说明']}")
        self.assertIn("能力不存在", 前端.获取状态("错误区"))  # 前端得到明确状态而非空白


class Test有状态排空(unittest.TestCase):
    """场景24：真实有状态排空。"""

    def test_正常排空(self):
        from 运行核心.资源协调.有状态排空.排空管理 import 排空管理器
        排空 = 排空管理器(排空超时秒=2)
        self.assertTrue(排空.开始请求())
        排空.记录连接(2)
        排空.结束请求()
        排空.释放连接(2)
        结果 = 排空.排空()
        self.assertTrue(结果.成功)
        self.assertIn("活动请求归零", 结果.步骤列表)
        self.assertFalse(结果.强制终止)

    def test_停止接收新请求(self):
        from 运行核心.资源协调.有状态排空.排空管理 import 排空管理器
        排空 = 排空管理器()
        排空.停止接收新请求 = True
        self.assertFalse(排空.开始请求())

    def test_排空超时记录未完成任务(self):
        from 运行核心.资源协调.有状态排空.排空管理 import 排空管理器
        排空 = 排空管理器(排空超时秒=0.2, 允许强制终止=True)
        排空.开始请求()  # 不结束 → 永不归零
        结果 = 排空.排空()
        self.assertTrue(结果.强制终止)
        self.assertTrue(结果.未完成任务)
        self.assertIn("排空超时", 结果.诊断记录)


class Test统一上下文(unittest.TestCase):
    """场景25：跨进程/跨层上下文传递。"""

    def test_上下文继承不丢失(self):
        上下文 = 运行上下文(请求id="请求1", 项目id="项目A", 用户id="用户1")
        子上下文 = 上下文.继承(能力id="示例.加法")
        self.assertEqual(子上下文.请求id, "请求1")
        self.assertEqual(子上下文.项目id, "项目A")
        self.assertEqual(子上下文.能力id, "示例.加法")
        self.assertEqual(子上下文.父请求id, "请求1")

    def test_上下文序列化跨进程(self):
        管理器 = 上下文管理器()
        上下文 = 管理器.进入(运行上下文(请求id="跨进程1", 用户id="用户X"))
        序列化 = 管理器.序列化当前()
        管理器2 = 上下文管理器()
        恢复 = 管理器2.反序列化进入(序列化)
        self.assertEqual(恢复.请求id, "跨进程1")
        self.assertEqual(恢复.用户id, "用户X")

    def test_上下文事件字段继承(self):
        上下文 = 运行上下文(请求id="事件1", 项目id="项目Y", 能力id="示例.加法", 包版本="1.0.0")
        事件字段 = 上下文.事件字段()
        self.assertEqual(事件字段["追踪id"], "事件1")
        self.assertEqual(事件字段["版本"], "1.0.0")


class Test发布事务一致性(unittest.TestCase):
    """场景26-28：一致性校验 + 事务回滚。"""

    def test_包仓库与版本注册表一致(self):
        from 平台控制面.包仓库.版本仓库 import 包仓库
        from 运行核心.加载器.版本系统.版本注册表 import 版本注册表
        from 平台控制面.发布管理.发布事务.发布事务 import 发布事务管理器
        临时目录 = Path(tempfile.mkdtemp(prefix="第七阶段事务_"))
        仓库 = 包仓库(临时目录 / "仓库")
        注册表 = 版本注册表(临时目录 / "版本")
        事务管理器 = 发布事务管理器(临时目录 / "事务")
        # 注册但未安装 → 一致性问题
        注册表.注册版本("事务.包", "1.0.0", 声明字典={"包id": "事务.包", "版本": "1.0.0"})
        注册表.获取版本("事务.包", "1.0.0").发布状态 = "已激活"
        注册表.保存()
        问题 = 事务管理器.一致性检查(包仓库=仓库, 版本注册表=注册表)
        self.assertTrue(问题)
        self.assertTrue(any("已激活但包未安装" in 问题 for 问题 in 问题))

    def test_发布事务失败回滚(self):
        from 平台控制面.发布管理.发布事务.发布事务 import 发布事务管理器
        临时目录 = Path(tempfile.mkdtemp(prefix="第七阶段事务回滚_"))
        管理器 = 发布事务管理器(临时目录)
        事务 = 管理器.开始("事务.包", "1.0.0")
        管理器.记录步骤(事务, "安装", True, "安装成功")
        管理器.记录步骤(事务, "注册", False, "注册失败（版本冲突）")
        管理器.提交(事务)
        self.assertEqual(事务.状态, "失败")
        管理器.回滚(事务, "注册阶段失败，回滚安装")
        self.assertEqual(事务.状态, "已回滚")
        # 事务可查询
        查询 = 管理器.查询(事务.事务id)
        self.assertIsNotNone(查询)
        self.assertEqual(len(查询.步骤列表), 3)

    def test_激活版本存在性校验(self):
        from 运行核心.加载器.版本系统.热切换 import 热切换管理器
        from 运行核心.加载器.版本系统.版本注册表 import 版本注册表
        注册表 = 版本注册表(Path(tempfile.mkdtemp(prefix="第七阶段激活_") + "/"))
        注册表.注册版本("激活.包", "1.0.0", 声明字典={"包id": "激活.包", "版本": "1.0.0"})
        切换 = 热切换管理器(注册表)
        切换.设置激活("激活.能力", "9.9.9")  # 指向未安装版本
        问题 = []
        from 平台控制面.发布管理.发布事务.发布事务 import 发布事务管理器
        问题 = 发布事务管理器(Path(tempfile.mkdtemp(prefix="第七阶段激活检查_") + "/")).一致性检查(
            版本注册表=注册表, 热切换=切换,
        )
        self.assertTrue(any("激活映射指向未安装版本" in 问题 for 问题 in 问题))


if __name__ == "__main__":
    unittest.main()
