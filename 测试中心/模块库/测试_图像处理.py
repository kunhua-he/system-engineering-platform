"""模块库.图像处理 组合能力真实测试：经唯一能力调用服务装配支持库能力。

覆盖：真实 PNG/JPEG 分析往返、缩略图/EXIF转置/透明合成/感知哈希/缩放/
重编码、平台不可用（禁用库）、参数错误、受控根目录读取边界、注册能力 9 项。
"""

from __future__ import annotations

import base64
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

if str(Path(__file__).resolve().parents[2]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from 模块库.图像处理 import 分析图像文件, 生成占位图, 识别图像格式
from 模块库.图像处理 import 生成缩略图, 图像EXIF转置, 透明背景合成
from 模块库.图像处理 import 计算感知哈希, 缩放图像, 重编码图像
from 后端核心.后端核心 import 后端核心
from 运行核心.统一网关.网关核心 import 网关核心
from 运行核心.统一网关.本地网关 import 本地网关服务器
from 运行核心.能力调用.HTTP连接器 import HTTP连接器

最小PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")
最小JPEG = base64.b64decode("/9j/4AAQSkZJRgABAQEAYABgAAD/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsLDBkSEw8UHRofHh0aHBwgJC4nICIsIxwcKDcpLDAxNDQ0Hyc5PTgyPC4zNDL/wAALCAABAAEBAREA/8QAFAABAAAAAAAAAAAAAAAAAAAACf/EABQQAQAAAAAAAAAAAAAAAAAAAAD/2gAIAQEAAD8AVN//2Q==")


class 图像处理装配(unittest.TestCase):
    """真实装配：启动后端与随机回环网关，所有能力调用经 HTTP 连接器走真实网关。"""

    @classmethod
    def setUpClass(cls):
        """启动真实后端和随机回环网关，所有测试请求走 HTTP。"""
        cls.后端 = 后端核心()
        启动结果 = cls.后端.启动()
        if not 启动结果.成功:
            raise RuntimeError(f"后端核心启动失败: {启动结果.错误说明}")
        cls.网关 = 本地网关服务器(
            网关核心实例=网关核心(cls.后端), 地址="127.0.0.1", 端口=0,
            配置={"请求超时秒": 10, "要求凭证": False, "禁止客户端身份": False},
        )
        成功, 说明 = cls.网关.启动()
        if not 成功:
            cls.后端.优雅关闭()
            raise RuntimeError(f"网关启动失败: {说明}")
        from 模块库.图像处理 import 设置HTTP连接器
        设置HTTP连接器(HTTP连接器(网关地址="127.0.0.1", 网关端口=cls.网关.端口))

    @classmethod
    def tearDownClass(cls):
        from 模块库.图像处理 import 设置HTTP连接器
        设置HTTP连接器(None)
        cls.网关.优雅停止()
        cls.后端.优雅关闭()

    def setUp(self):
        from 公共契约.能力契约.契约 import 能力注册表
        from 运行核心.能力调用.唯一能力调用 import 设置全局唯一服务, 唯一能力调用服务
        from 支持库.后端.图像处理支持库.图像解码 import 注册能力 as 注册图像能力
        from 支持库.后端.文件系统支持库.文件操作 import 注册能力 as 注册文件系统能力

        注册表 = 能力注册表()
        注册图像能力(注册表)
        注册文件系统能力(注册表)
        设置全局唯一服务(唯一能力调用服务(注册表))

    def tearDown(self):
        from 运行核心.能力调用.唯一能力调用 import 设置全局唯一服务

        设置全局唯一服务(None)

    def test_平台不可用时返回提供者不可用(self):
        """卸载连接器后调用能力：模块返回 提供者不可用，不抛异常。"""
        from 模块库.图像处理 import 设置HTTP连接器

        设置HTTP连接器(None)
        try:
            结果 = 识别图像格式(最小PNG)
            self.assertFalse(结果.成功)
            self.assertEqual(结果.错误码, "提供者不可用")
        finally:
            设置HTTP连接器(HTTP连接器(网关地址="127.0.0.1", 网关端口=self.网关.端口))


class Test分析图像文件(图像处理装配):
    def setUp(self):
        super().setUp()
        self.临时目录 = Path(tempfile.mkdtemp(prefix="图像处理测试_"))

    def tearDown(self):
        super().tearDown()
        shutil.rmtree(self.临时目录, ignore_errors=True)

    def _写文件(self, 名称: str, 字节: bytes) -> str:
        路径 = self.临时目录 / 名称
        路径.write_bytes(字节)
        return 路径.name

    def test_真实PNG分析返回解码与像素统计(self):
        结果 = 分析图像文件(str(self.临时目录), self._写文件("真实.png", 最小PNG))
        self.assertTrue(结果.成功, 结果.错误说明)
        self.assertEqual(结果.值["格式"], "PNG")
        self.assertEqual((结果.值["宽度"], 结果.值["高度"]), (1, 1))
        self.assertEqual(结果.值["像素数"], 1)
        self.assertEqual(set(结果.值["平均颜色"]), {"红", "绿", "蓝"})

    def test_真实JPEG分析返回格式与尺寸(self):
        结果 = 分析图像文件(str(self.临时目录), self._写文件("真实.jpg", 最小JPEG))
        self.assertTrue(结果.成功, 结果.错误说明)
        self.assertEqual(结果.值["格式"], "JPEG")
        self.assertEqual((结果.值["宽度"], 结果.值["高度"]), (1, 1))
        self.assertEqual(结果.值["像素数"], 1)

    def test_已知纯色像素统计精确(self):
        占位 = 生成占位图(4, 4, "纯色", 背景颜色="#123456")
        self.assertTrue(占位.成功, 占位.错误说明)
        结果 = 分析图像文件(
            str(self.临时目录), self._写文件("纯色.png", base64.b64decode(占位.值["图像b64"])))
        self.assertTrue(结果.成功, 结果.错误说明)
        self.assertEqual(结果.值["平均颜色"], {"红": 18, "绿": 52, "蓝": 86})

    def test_文件不存在返回文件不存在(self):
        结果 = 分析图像文件(str(self.临时目录), "不存在.png")
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "文件不存在")

    def test_受控根目录不存在返回目录不存在(self):
        结果 = 分析图像文件(str(self.临时目录 / "不存在目录"), "真实.png")
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "目录不存在")

    def test_路径越界返回路径越界(self):
        结果 = 分析图像文件(str(self.临时目录), "../越界.png")
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "路径越界")

    def test_超过最大字节数返回文件超限(self):
        结果 = 分析图像文件(str(self.临时目录), self._写文件("超限.png", 最小PNG), 最大字节数=1)
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "文件超限")

    def test_非法路径参数不合法(self):
        for 受控根目录, 相对路径 in (("", "真实.png"), (None, "真实.png"),
                                     ("/tmp", ""), ("/tmp", None)):
            结果 = 分析图像文件(受控根目录, 相对路径)
            self.assertEqual(结果.错误码, "参数不合法")

    def test_损坏文件错误码透传(self):
        结果 = 分析图像文件(str(self.临时目录), self._写文件("损坏.png", 最小PNG[:44]))
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "文件损坏")

    def test_文本伪装文件格式未知(self):
        结果 = 分析图像文件(
            str(self.临时目录), self._写文件("伪装.png", "这不是图像内容".encode("utf-8")))
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "格式未知")

    def test_支持库缺失提供者不可用(self):
        with mock.patch.dict(os.environ, {"Pillow提供者_禁用库": "PIL"}):
            结果 = 分析图像文件(str(self.临时目录), self._写文件("真实.png", 最小PNG))
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "提供者不可用")
        self.assertTrue(结果.可重试)


class Test生成占位图(图像处理装配):
    def test_纯色占位图(self):
        结果 = 生成占位图(64, 32, "纯色", 背景颜色="#FF8800")
        self.assertTrue(结果.成功, 结果.错误说明)
        self.assertEqual(结果.值["格式"], "PNG")
        self.assertEqual((结果.值["宽度"], 结果.值["高度"]), (64, 32))
        self.assertTrue(base64.b64decode(结果.值["图像b64"]).startswith(b"\x89PNG"))

    def test_渐变占位图(self):
        结果 = 生成占位图(64, 64, "渐变", 前景颜色="#FF0000", 背景颜色="#0000FF")
        self.assertTrue(结果.成功, 结果.错误说明)
        self.assertEqual((结果.值["宽度"], 结果.值["高度"]), (64, 64))

    def test_文本占位图(self):
        结果 = 生成占位图(300, 150, "文本", 文本="测试占位")
        self.assertTrue(结果.成功, 结果.错误说明)
        识别 = 识别图像格式(base64.b64decode(结果.值["图像b64"]))
        self.assertTrue(识别.成功, 识别.错误说明)
        self.assertEqual((识别.值["宽度"], 识别.值["高度"]), (300, 150))

    def test_非法参数透传(self):
        self.assertEqual(生成占位图(8, 8, "动画").错误码, "参数不合法")
        self.assertEqual(生成占位图(0, 8, "纯色").错误码, "参数不合法")
        self.assertEqual(生成占位图(8, 8, "纯色", 背景颜色="red").错误码, "参数不合法")

    def test_支持库缺失提供者不可用(self):
        with mock.patch.dict(os.environ, {"Pillow提供者_禁用库": "PIL"}):
            结果 = 生成占位图(64, 32, "纯色")
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "提供者不可用")


class Test识别图像格式(图像处理装配):
    def test_按内容识别JPEG不受后缀影响(self):
        结果 = 识别图像格式(最小JPEG)
        self.assertTrue(结果.成功, 结果.错误说明)
        self.assertEqual(结果.值["格式"], "JPEG")

    def test_纯文本伪装返回格式未知(self):
        结果 = 识别图像格式("伪装成图像的内容".encode("utf-8"))
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "格式未知")

    def test_损坏字节文件损坏透传(self):
        结果 = 识别图像格式(最小PNG[:44])
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "文件损坏")

    def test_字节参数非法参数不合法(self):
        结果 = 识别图像格式("文本字节")
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "参数不合法")

    def test_支持库缺失提供者不可用(self):
        with mock.patch.dict(os.environ, {"Pillow提供者_禁用库": "PIL"}):
            结果 = 识别图像格式(最小PNG)
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "提供者不可用")


class Test生成缩略图(图像处理装配):
    def setUp(self):
        super().setUp()
        占位 = 生成占位图(64, 32, "纯色")
        self.字节 = base64.b64decode(占位.值["图像b64"])

    def test_等比例缩略只缩不放大(self):
        结果 = 生成缩略图(self.字节, 最大边长=16)
        self.assertTrue(结果.成功, 结果.错误说明)
        self.assertEqual((结果.值["宽度"], 结果.值["高度"]), (16, 8))

    def test_最大边长大于原图不放大(self):
        结果 = 生成缩略图(self.字节, 最大边长=128)
        self.assertTrue(结果.成功, 结果.错误说明)
        self.assertEqual((结果.值["宽度"], 结果.值["高度"]), (64, 32))

    def test_非法最大边长参数不合法(self):
        结果 = 生成缩略图(self.字节, 最大边长=0)
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "参数不合法")

    def test_支持库缺失提供者不可用(self):
        with mock.patch.dict(os.environ, {"Pillow提供者_禁用库": "PIL"}):
            结果 = 生成缩略图(self.字节, 最大边长=16)
        self.assertEqual(结果.错误码, "提供者不可用")


class Test图像EXIF转置(图像处理装配):
    def setUp(self):
        super().setUp()
        占位 = 生成占位图(64, 32, "纯色")
        self.字节 = base64.b64decode(占位.值["图像b64"])

    def test_无EXIF方向原样返回(self):
        结果 = 图像EXIF转置(self.字节)
        self.assertTrue(结果.成功, 结果.错误说明)
        self.assertEqual((结果.值["宽度"], 结果.值["高度"]), (64, 32))

    def test_支持库缺失提供者不可用(self):
        with mock.patch.dict(os.environ, {"Pillow提供者_禁用库": "PIL"}):
            结果 = 图像EXIF转置(self.字节)
        self.assertEqual(结果.错误码, "提供者不可用")


class Test透明背景合成(图像处理装配):
    def setUp(self):
        super().setUp()
        占位 = 生成占位图(64, 32, "纯色", 背景颜色="#FF0000")
        self.字节 = base64.b64decode(占位.值["图像b64"])

    def test_合成返回RGB图像宽高不变(self):
        结果 = 透明背景合成(self.字节, 背景颜色="#FFFFFF")
        self.assertTrue(结果.成功, 结果.错误说明)
        self.assertEqual((结果.值["宽度"], 结果.值["高度"]), (64, 32))

    def test_非法背景颜色参数不合法(self):
        结果 = 透明背景合成(self.字节, 背景颜色="不是颜色")
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "参数不合法")

    def test_支持库缺失提供者不可用(self):
        with mock.patch.dict(os.environ, {"Pillow提供者_禁用库": "PIL"}):
            结果 = 透明背景合成(self.字节)
        self.assertEqual(结果.错误码, "提供者不可用")


class Test计算感知哈希(图像处理装配):
    def setUp(self):
        super().setUp()
        纯色 = 生成占位图(64, 32, "纯色", 背景颜色="#123456")
        渐变 = 生成占位图(64, 32, "渐变", 前景颜色="#FF0000", 背景颜色="#0000FF")
        self.纯色字节 = base64.b64decode(纯色.值["图像b64"])
        self.渐变字节 = base64.b64decode(渐变.值["图像b64"])

    def test_同输入同哈希确定性(self):
        结果甲 = 计算感知哈希(self.纯色字节, 哈希类型="pHash")
        结果乙 = 计算感知哈希(self.纯色字节, 哈希类型="pHash")
        self.assertTrue(结果甲.成功, 结果甲.错误说明)
        self.assertEqual(结果甲.值, 结果乙.值)
        self.assertEqual(结果甲.值["哈希类型"], "pHash")
        self.assertEqual(len(结果甲.值["哈希"]), 16)

    def test_不同图像哈希不同(self):
        纯色哈希 = 计算感知哈希(self.纯色字节, 哈希类型="aHash")
        渐变哈希 = 计算感知哈希(self.渐变字节, 哈希类型="aHash")
        self.assertTrue(纯色哈希.成功 and 渐变哈希.成功)
        self.assertNotEqual(纯色哈希.值["哈希"], 渐变哈希.值["哈希"])

    def test_非法哈希类型参数不合法(self):
        结果 = 计算感知哈希(self.纯色字节, 哈希类型="未知算法")
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "参数不合法")

    def test_支持库缺失提供者不可用(self):
        with mock.patch.dict(os.environ, {"Pillow提供者_禁用库": "PIL"}):
            结果 = 计算感知哈希(self.纯色字节)
        self.assertEqual(结果.错误码, "提供者不可用")


class Test缩放图像(图像处理装配):
    def setUp(self):
        super().setUp()
        占位 = 生成占位图(100, 50, "纯色")
        self.字节 = base64.b64decode(占位.值["图像b64"])

    def test_指定宽度按纵横比推算高度(self):
        结果 = 缩放图像(self.字节, 宽度=50)
        self.assertTrue(结果.成功, 结果.错误说明)
        self.assertEqual((结果.值["宽度"], 结果.值["高度"]), (50, 25))

    def test_指定高度按纵横比推算宽度(self):
        结果 = 缩放图像(self.字节, 高度=10)
        self.assertTrue(结果.成功, 结果.错误说明)
        self.assertEqual((结果.值["宽度"], 结果.值["高度"]), (20, 10))

    def test_宽高都空参数不合法(self):
        结果 = 缩放图像(self.字节)
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "参数不合法")

    def test_支持库缺失提供者不可用(self):
        with mock.patch.dict(os.environ, {"Pillow提供者_禁用库": "PIL"}):
            结果 = 缩放图像(self.字节, 宽度=50)
        self.assertEqual(结果.错误码, "提供者不可用")


class Test重编码图像(图像处理装配):
    def setUp(self):
        super().setUp()
        占位 = 生成占位图(64, 32, "纯色")
        self.字节 = base64.b64decode(占位.值["图像b64"])

    def test_PNG重编码为JPEG(self):
        结果 = 重编码图像(self.字节, 格式="JPEG", 质量=80)
        self.assertTrue(结果.成功, 结果.错误说明)
        self.assertEqual(结果.值["格式"], "JPEG")
        self.assertTrue(base64.b64decode(结果.值["图像b64"]).startswith(b"\xff\xd8"))

    def test_PNG重编码为PNG无损(self):
        结果 = 重编码图像(self.字节, 格式="PNG", 质量=90)
        self.assertTrue(结果.成功, 结果.错误说明)
        self.assertEqual(结果.值["格式"], "PNG")
        self.assertEqual((结果.值["宽度"], 结果.值["高度"]), (64, 32))

    def test_非法格式参数不合法(self):
        结果 = 重编码图像(self.字节, 格式="BMP")
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "参数不合法")

    def test_非法质量参数不合法(self):
        结果 = 重编码图像(self.字节, 格式="JPEG", 质量=101)
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "参数不合法")

    def test_支持库缺失提供者不可用(self):
        with mock.patch.dict(os.environ, {"Pillow提供者_禁用库": "PIL"}):
            结果 = 重编码图像(self.字节, 格式="JPEG")
        self.assertEqual(结果.错误码, "提供者不可用")


class Test注册能力(图像处理装配):
    def test_模块注册九个能力(self):
        class 假注册表:
            def __init__(self):
                self.条目 = []

            def 注册(self, 能力):
                self.条目.append(能力)

        注册表 = 假注册表()
        from 模块库.图像处理 import 注册能力

        注册能力(注册表)
        self.assertEqual(len(注册表.条目), 9)
        self.assertEqual([条目.能力id for 条目 in 注册表.条目],
                         ["图像处理.分析图像文件", "图像处理.生成占位图", "图像处理.识别图像格式",
                          "图像处理.生成缩略图", "图像处理.图像EXIF转置", "图像处理.透明背景合成",
                          "图像处理.计算感知哈希", "图像处理.缩放图像", "图像处理.重编码图像"])
        for 条目 in 注册表.条目:
            self.assertEqual(条目.包id, "模块库.图像处理")


if __name__ == "__main__":
    unittest.main()
