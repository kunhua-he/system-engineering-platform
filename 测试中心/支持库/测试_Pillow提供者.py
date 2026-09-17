"""Pillow 提供者测试：真实解码/像素统计/占位图 + 6 新能力（缩略图/EXIF转置/
透明合成/感知哈希/缩放/重编码）+ 损坏/伪装/超大/超时/崩溃/不可用/自举/零残留。
架构验证：主进程不加载 PIL；子进程覆盖启动/调用/超时/崩溃/重启/停止与残留清理；
提供者不可用走环境变量依赖注入；子进程自举清空 PYTHONPATH 仍成功。
"""
from __future__ import annotations

import base64
import json
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
import zlib
from pathlib import Path
from unittest import mock

if str(Path(__file__).resolve().parents[2]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from 公共契约.基础类型.逻辑类型 import 真, 假
from 公共契约.能力契约.契约 import 能力注册表
from 公共契约.版本规则.契约版本 import 契约版本
from 公共契约.运行时.平台适配 import 子进程组启动标志
from 支持库.后端.图像处理支持库.图像解码 import (
    解码图像, 像素统计, 生成占位图, 生成缩略图, 图像EXIF转置,
    透明背景合成, 计算感知哈希, 缩放图像, 重编码图像, 注册能力,
)
from 支持库.后端.图像处理支持库.图像解码.实现 import 提供者 as 提供者模块
from 支持库.后端.组件规范支持库.实现.组件规范 import 校验组件规范

提供者目录 = (
    Path(__file__).resolve().parents[2]
    / "支持库" / "后端" / "图像处理支持库" / "图像解码"
)

最小PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")
最小JPEG = base64.b64decode("/9j/4AAQSkZJRgABAQEAYABgAAD/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsLDBkSEw8UHRofHh0aHBwgJC4nICIsIxwcKDcpLDAxNDQ0Hyc5PTgyPC4zNDL/wAALCAABAAEBAREA/8QAFAABAAAAAAAAAAAAAAAAAAAACf/EABQQAQAAAAAAAAAAAAAAAAAAAAD/2gAIAQEAAD8AVN//2Q==")


def _大像素PNG(宽度: int, 高度: int) -> bytes:
    """手工构造只声明尺寸的 PNG（头完整、无数据），用于像素超限判定。"""
    头 = b"\x89PNG\r\n\x1a\n"
    IHDR数据 = struct.pack(">IIBBBBB", 宽度, 高度, 8, 2, 0, 0, 0)
    IHDR = (struct.pack(">I", len(IHDR数据)) + b"IHDR" + IHDR数据
            + struct.pack(">I", zlib.crc32(b"IHDR" + IHDR数据)))
    IEND = struct.pack(">I", 0) + b"IEND" + struct.pack(">I", zlib.crc32(b"IEND"))
    return 头 + IHDR + IEND


def _RGB_PNG(宽度: int, 高度: int, 像素函数) -> bytes:
    """手工构造 RGB PNG（每像素按 像素函数(x, y) → (红,绿,蓝)），不加载 PIL。"""
    头 = b"\x89PNG\r\n\x1a\n"
    IHDR数据 = struct.pack(">IIBBBBB", 宽度, 高度, 8, 2, 0, 0, 0)
    IHDR = (struct.pack(">I", len(IHDR数据)) + b"IHDR" + IHDR数据
            + struct.pack(">I", zlib.crc32(b"IHDR" + IHDR数据)))
    原始 = b"".join(b"\x00" + b"".join(bytes(像素函数(x, y)) for x in range(宽度))
                    for y in range(高度))
    压缩 = zlib.compress(原始)
    IDAT = (struct.pack(">I", len(压缩)) + b"IDAT" + 压缩
            + struct.pack(">I", zlib.crc32(b"IDAT" + 压缩)))
    IEND = struct.pack(">I", 0) + b"IEND" + struct.pack(">I", zlib.crc32(b"IEND"))
    return 头 + IHDR + IDAT + IEND


def _RGBA_PNG(宽度: int, 高度: int, 像素函数) -> bytes:
    """手工构造 RGBA PNG（每像素按 像素函数(x, y) → (红,绿,蓝,不透明度)）。"""
    头 = b"\x89PNG\r\n\x1a\n"
    IHDR数据 = struct.pack(">IIBBBBB", 宽度, 高度, 8, 6, 0, 0, 0)
    IHDR = (struct.pack(">I", len(IHDR数据)) + b"IHDR" + IHDR数据
            + struct.pack(">I", zlib.crc32(b"IHDR" + IHDR数据)))
    原始 = b"".join(b"\x00" + b"".join(bytes(像素函数(x, y)) for x in range(宽度))
                    for y in range(高度))
    压缩 = zlib.compress(原始)
    IDAT = (struct.pack(">I", len(压缩)) + b"IDAT" + 压缩
            + struct.pack(">I", zlib.crc32(b"IDAT" + 压缩)))
    IEND = struct.pack(">I", 0) + b"IEND" + struct.pack(">I", zlib.crc32(b"IEND"))
    return 头 + IHDR + IDAT + IEND


def _带EXIF方向JPEG(方向: int) -> bytes:
    """用独立子进程生成带指定 EXIF orientation 的 JPEG（主进程不加载 PIL）。"""
    代码 = "\n".join([
        "import io, sys",
        "from PIL import Image",
        "图像 = Image.new('RGB', (8, 4), (200, 30, 90))",
        "exif = Image.Exif()",
        f"exif[274] = {方向}",
        "输出 = io.BytesIO()",
        "图像.save(输出, 'JPEG', exif=exif)",
        "sys.stdout.buffer.write(输出.getvalue())",
    ])
    运行 = subprocess.run([sys.executable, "-c", 代码], capture_output=True, timeout=60)
    if 运行.returncode != 0:
        raise AssertionError(f"EXIF 样本生成失败: {运行.stderr.decode('utf-8', errors='replace')}")
    return 运行.stdout


class _假进程:
    """模拟子进程：返回超过输出上限的响应字节（测 超大输出 错误码）。"""

    returncode = 0
    pid = 99999

    def __init__(self):
        import io
        self.stdin = io.BytesIO()
        self.stdout = io.BytesIO(b"x" * (提供者模块.默认最大输出字节 + 1))
        self.stderr = io.BytesIO(b"")

    def poll(self):
        return 0


def _退出子进程(码: int) -> subprocess.Popen:
    return subprocess.Popen(
        [sys.executable, "-c", f"import os; os._exit({码})"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        # 平台差异收口：POSIX 走 start_new_session，Windows 走 CREATE_NEW_PROCESS_GROUP
        **子进程组启动标志(),
    )


def _关闭进程(进程: subprocess.Popen) -> None:
    try:
        进程.communicate(timeout=5)
    except subprocess.TimeoutExpired:
        pass
    for 流 in (进程.stdin, 进程.stdout, 进程.stderr):
        if 流:
            try:
                流.close()
            except (OSError, ValueError):
                pass


class TestPillow提供者(unittest.TestCase):
    def test_主进程不加载PIL(self):
        """主进程零加载 PIL：提供者源码不导入 PIL，且调用不向主进程引入 PIL。

        全量套件中其他库（如 reportlab 依赖链）可能已加载 PIL，故仅断言
        本提供者自身不导入、本调用不引入，避免测试环境相互污染。
        """
        实现路径 = (Path(__file__).resolve().parent.parent.parent / "支持库" / "后端"
                    / "图像处理支持库" / "图像解码" / "实现" / "提供者.py")
        实现源码 = 实现路径.read_text(encoding="utf-8")
        import ast
        导入表 = []
        for 节点 in ast.walk(ast.parse(实现源码)):
            if isinstance(节点, ast.Import):
                导入表.extend(别名.name for 别名 in 节点.names)
            elif isinstance(节点, ast.ImportFrom) and 节点.module:
                导入表.append(节点.module)
        self.assertNotIn("PIL", [名称.split(".")[0] for 名称 in 导入表],
                         f"主进程侧源码不得导入 PIL，实际导入: {导入表}")
        PIL先前已存在 = "PIL" in sys.modules
        解码图像(最小PNG)
        if not PIL先前已存在:
            self.assertNotIn("PIL", sys.modules)

    def test_解码图像PNG正常(self):
        结果 = 解码图像(最小PNG)
        self.assertTrue(结果.成功, 结果.错误说明)
        self.assertEqual(结果.值, {"格式": "PNG", "宽度": 1, "高度": 1, "模式": "RGBA"})

    def test_解码图像JPEG正常(self):
        结果 = 解码图像(最小JPEG)
        self.assertTrue(结果.成功, 结果.错误说明)
        self.assertEqual(结果.值["格式"], "JPEG")
        self.assertEqual(结果.值["宽度"], 1)

    def test_解码图像格式伪装返回格式未知(self):
        结果 = 解码图像("这不是图像内容，只是普通文本伪装成图像".encode("utf-8"))
        self.assertEqual(结果.错误码, "格式未知")

    def test_解码图像损坏返回文件损坏(self):
        结果 = 解码图像(最小PNG[:44])  # 头完整但 IDAT 数据截断
        self.assertEqual(结果.错误码, "文件损坏")

    def test_解码图像像素超大返回超大(self):
        结果 = 解码图像(_大像素PNG(8000, 8000))
        self.assertEqual(结果.错误码, "超大")

    def test_解码图像字节超大返回超大(self):
        结果 = 解码图像(b"\x89PNG" + b"x" * (提供者模块.输入字节上限 + 1))
        self.assertEqual(结果.错误码, "超大")

    def test_解码图像非法参数(self):
        self.assertEqual(解码图像(b"").错误码, "参数不合法")
        self.assertEqual(解码图像("文本").错误码, "参数不合法")

    def test_像素统计纯色精确(self):
        占位 = 生成占位图(4, 4, "纯色", 背景颜色="#123456")
        self.assertTrue(占位.成功, 占位.错误说明)
        结果 = 像素统计(base64.b64decode(占位.值["图像b64"]))
        self.assertTrue(结果.成功, 结果.错误说明)
        self.assertEqual(结果.值["宽度"], 4)
        self.assertEqual(结果.值["高度"], 4)
        self.assertEqual(结果.值["像素数"], 16)
        self.assertEqual(结果.值["平均颜色"], {"红": 18, "绿": 52, "蓝": 86})

    def test_像素统计超大返回超大(self):
        结果 = 像素统计(_大像素PNG(6000, 6000))
        self.assertEqual(结果.错误码, "超大")

    def test_生成占位图纯色可解码(self):
        结果 = 生成占位图(64, 32, "纯色", 背景颜色="#FF8800")
        self.assertTrue(结果.成功, 结果.错误说明)
        self.assertEqual(结果.值["格式"], "PNG")
        self.assertEqual((结果.值["宽度"], 结果.值["高度"]), (64, 32))
        图像字节 = base64.b64decode(结果.值["图像b64"])
        self.assertTrue(图像字节.startswith(b"\x89PNG"))
        解码 = 解码图像(图像字节)
        self.assertTrue(解码.成功, 解码.错误说明)
        self.assertEqual(解码.值["格式"], "PNG")

    def test_生成占位图渐变颜色区间(self):
        结果 = 生成占位图(64, 64, "渐变", 前景颜色="#FF0000", 背景颜色="#0000FF")
        self.assertTrue(结果.成功, 结果.错误说明)
        统计 = 像素统计(base64.b64decode(结果.值["图像b64"]))
        self.assertTrue(统计.成功, 统计.错误说明)
        平均 = 统计.值["平均颜色"]
        self.assertGreater(平均["红"], 100)
        self.assertGreater(平均["蓝"], 100)
        self.assertLess(平均["红"], 200)
        self.assertLess(平均["蓝"], 200)
        self.assertEqual(平均["绿"], 0)

    def test_生成占位图文本(self):
        结果 = 生成占位图(300, 150, "文本", 文本="TEST")
        self.assertTrue(结果.成功, 结果.错误说明)
        解码 = 解码图像(base64.b64decode(结果.值["图像b64"]))
        self.assertTrue(解码.成功, 解码.错误说明)
        self.assertEqual((解码.值["宽度"], 解码.值["高度"]), (300, 150))

    def test_生成占位图非法参数(self):
        self.assertEqual(生成占位图(8, 8, "动画").错误码, "参数不合法")
        self.assertEqual(生成占位图(0, 8, "纯色").错误码, "参数不合法")
        self.assertEqual(生成占位图(8, 8, "纯色", 背景颜色="red").错误码, "参数不合法")

    def test_生成占位图超大返回超大(self):
        结果 = 生成占位图(7000, 7000, "纯色")
        self.assertEqual(结果.错误码, "超大")

    def test_超时返回超时(self):
        def 挂起执行(请求, 超时秒=提供者模块.默认超时秒):
            进程 = 提供者模块._启动子进程()
            try:
                进程.communicate(timeout=0.5)  # 不发请求 → 子进程阻塞 → 真实超时
            except subprocess.TimeoutExpired:
                return 提供者模块._失败("超时", "模拟超时", 可重试=真)
            finally:
                提供者模块._终止进程组(进程)
                for 流 in (进程.stdin, 进程.stdout, 进程.stderr):
                    if 流:
                        流.close()
            return 提供者模块._失败("超时", "模拟超时", 可重试=真)
        with mock.patch.object(提供者模块, "执行任务", side_effect=挂起执行):
            结果 = 解码图像(最小PNG)
        self.assertEqual(结果.错误码, "超时")
        self.assertTrue(结果.可重试)

    def test_子进程崩溃返回提供者崩溃(self):
        with mock.patch.object(提供者模块, "_启动子进程", side_effect=lambda: _退出子进程(7)), \
                mock.patch.object(提供者模块, "_终止进程组", side_effect=_关闭进程):
            结果 = 解码图像(最小PNG)
        self.assertEqual(结果.错误码, "提供者崩溃")
        self.assertTrue(结果.可重试)

    def test_重启恢复(self):
        原始启动 = 提供者模块._启动子进程
        计数 = {"n": 0}

        def 先崩后正常():
            计数["n"] += 1
            return _退出子进程(9) if 计数["n"] == 1 else 原始启动()
        with mock.patch.object(提供者模块, "_启动子进程", side_effect=先崩后正常), \
                mock.patch.object(提供者模块, "_终止进程组", side_effect=_关闭进程):
            第一次 = 解码图像(最小PNG)
            第二次 = 解码图像(最小PNG)
        self.assertEqual(第一次.错误码, "提供者崩溃")
        self.assertTrue(第二次.成功, 第二次.错误说明)

    def test_提供者不可用(self):
        with mock.patch.dict(os.environ, {"Pillow提供者_禁用库": "PIL"}):
            结果 = 解码图像(最小PNG)
        self.assertEqual(结果.错误码, "提供者不可用")
        self.assertTrue(结果.可重试)

    def test_无残留与停止清理(self):
        for _ in range(3):
            解码图像(最小PNG)
        进程 = 提供者模块._启动子进程()
        self.assertIsNone(进程.poll())
        提供者模块.等待并收集([进程])
        for 流 in (进程.stdin, 进程.stdout, 进程.stderr):
            if 流:
                流.close()
        self.assertIsNotNone(进程.poll())

    def test_生成缩略图等比例与只缩不放大(self):
        源 = 生成占位图(200, 100, "纯色", 背景颜色="#336699")
        self.assertTrue(源.成功, 源.错误说明)
        字节 = base64.b64decode(源.值["图像b64"])
        缩 = 生成缩略图(字节, 100)
        self.assertTrue(缩.成功, 缩.错误说明)
        self.assertEqual((缩.值["宽度"], 缩.值["高度"]), (100, 50))
        self.assertEqual(缩.值["格式"], "PNG")
        放大 = 生成缩略图(字节, 500)  # 最大边长超过原图 → 不放大
        self.assertEqual((放大.值["宽度"], 放大.值["高度"]), (200, 100))
        jpeg缩 = 生成缩略图(最小JPEG, 100)
        self.assertTrue(jpeg缩.成功, jpeg缩.错误说明)
        self.assertEqual(jpeg缩.值["格式"], "JPEG")

    def test_生成缩略图非法参数与超时上限(self):
        self.assertEqual(生成缩略图(最小PNG, 0).错误码, "参数不合法")
        self.assertEqual(生成缩略图(最小PNG, "100").错误码, "参数不合法")
        self.assertEqual(生成缩略图(b"", 100).错误码, "参数不合法")
        self.assertEqual(生成缩略图(最小PNG, 100, 超时秒=61).错误码, "参数不合法")

    def test_图像EXIF转置方向样本(self):
        转正 = 图像EXIF转置(_带EXIF方向JPEG(1))
        self.assertTrue(转正.成功, 转正.错误说明)
        self.assertEqual((转正.值["宽度"], 转正.值["高度"]), (8, 4))
        self.assertEqual(转正.值["格式"], "JPEG")
        转90 = 图像EXIF转置(_带EXIF方向JPEG(6))
        self.assertTrue(转90.成功, 转90.错误说明)
        self.assertEqual((转90.值["宽度"], 转90.值["高度"]), (4, 8))
        无方向 = 图像EXIF转置(_RGB_PNG(6, 3, lambda x, y: (10, 20, 30)))
        self.assertTrue(无方向.成功, 无方向.错误说明)
        self.assertEqual((无方向.值["宽度"], 无方向.值["高度"]), (6, 3))

    def test_图像EXIF转置非法参数(self):
        self.assertEqual(图像EXIF转置(b"").错误码, "参数不合法")
        self.assertEqual(图像EXIF转置("文本").错误码, "参数不合法")

    def test_透明背景合成像素级(self):
        """半透明红 (255,0,0,128) + 不透明红 (255,0,0,255) 合成到 #FFFFFF。"""
        png = _RGBA_PNG(2, 1, lambda x, y: (255, 0, 0, 128 if x == 0 else 255))
        合 = 透明背景合成(png, "#FFFFFF")
        self.assertTrue(合.成功, 合.错误说明)
        self.assertEqual((合.值["宽度"], 合.值["高度"]), (2, 1))
        self.assertEqual(合.值["格式"], "PNG")
        统计 = 像素统计(base64.b64decode(合.值["图像b64"]))
        self.assertTrue(统计.成功, 统计.错误说明)
        self.assertEqual(统计.值["平均颜色"], {"红": 255, "绿": 64, "蓝": 64})

    def test_透明背景合成非法参数(self):
        self.assertEqual(透明背景合成(最小PNG, "red").错误码, "参数不合法")
        self.assertEqual(透明背景合成(b"", "#FFFFFF").错误码, "参数不合法")

    def test_计算感知哈希确定性与格式(self):
        渐变 = base64.b64decode(生成占位图(
            64, 64, "渐变", 前景颜色="#FF0000", 背景颜色="#0000FF").值["图像b64"])
        for 类型 in ("aHash", "dHash", "pHash"):
            第一次 = 计算感知哈希(渐变, 类型)
            self.assertTrue(第一次.成功, 第一次.错误说明)
            第二次 = 计算感知哈希(渐变, 类型)
            self.assertEqual(第一次.值["哈希"], 第二次.值["哈希"])
            self.assertEqual(第一次.值["哈希类型"], 类型)
            self.assertEqual(len(第一次.值["哈希"]), 16)
            int(第一次.值["哈希"], 16)  # 必须是合法十六进制

    def test_计算感知哈希差异性与类型区分(self):
        渐变 = base64.b64decode(生成占位图(
            64, 64, "渐变", 前景颜色="#FF0000", 背景颜色="#0000FF").值["图像b64"])
        纯色 = _RGB_PNG(64, 64, lambda x, y: (255, 0, 0))
        递减水平 = _RGB_PNG(64, 64, lambda x, y: ((63 - x) * 4, 0, 0))
        self.assertNotEqual(计算感知哈希(渐变, "aHash").值["哈希"],
                            计算感知哈希(纯色, "aHash").值["哈希"])
        self.assertNotEqual(计算感知哈希(递减水平, "dHash").值["哈希"],
                            计算感知哈希(纯色, "dHash").值["哈希"])
        self.assertNotEqual(计算感知哈希(渐变, "pHash").值["哈希"],
                            计算感知哈希(纯色, "pHash").值["哈希"])
        三类型 = {计算感知哈希(渐变, 类型).值["哈希"] for 类型 in ("aHash", "dHash", "pHash")}
        self.assertEqual(len(三类型), 3)

    def test_计算感知哈希非法参数(self):
        self.assertEqual(计算感知哈希(最小PNG, "xx").错误码, "参数不合法")
        self.assertEqual(计算感知哈希(b"", "aHash").错误码, "参数不合法")

    def test_缩放图像精确尺寸(self):
        源 = 生成占位图(200, 100, "纯色")
        字节 = base64.b64decode(源.值["图像b64"])
        宽 = 缩放图像(字节, 宽度=50)
        self.assertTrue(宽.成功, 宽.错误说明)
        self.assertEqual((宽.值["宽度"], 宽.值["高度"]), (50, 25))
        高 = 缩放图像(字节, 高度=80)
        self.assertTrue(高.成功, 高.错误说明)
        self.assertEqual((高.值["宽度"], 高.值["高度"]), (160, 80))
        双 = 缩放图像(字节, 宽度=60, 高度=40)
        self.assertTrue(双.成功, 双.错误说明)
        self.assertEqual((双.值["宽度"], 双.值["高度"]), (60, 40))
        self.assertEqual(双.值["格式"], "PNG")

    def test_缩放图像非法参数与超大(self):
        self.assertEqual(缩放图像(最小PNG).错误码, "参数不合法")
        self.assertEqual(缩放图像(最小PNG, 宽度="10").错误码, "参数不合法")
        self.assertEqual(缩放图像(最小PNG, 宽度=0, 高度=10).错误码, "参数不合法")
        self.assertEqual(缩放图像(b"", 宽度=10).错误码, "参数不合法")
        self.assertEqual(缩放图像(最小PNG, 宽度=7000, 高度=7000).错误码, "超大")

    def test_重编码图像像素级与质量差异(self):
        源 = 生成占位图(4, 4, "纯色", 背景颜色="#123456")
        字节 = base64.b64decode(源.值["图像b64"])
        期望 = {"红": 18, "绿": 52, "蓝": 86}
        png = 重编码图像(字节, "PNG")
        self.assertTrue(png.成功, png.错误说明)
        self.assertEqual(png.值["格式"], "PNG")
        统计 = 像素统计(base64.b64decode(png.值["图像b64"]))
        self.assertTrue(统计.成功, 统计.错误说明)
        self.assertEqual(统计.值["平均颜色"], 期望)
        for 格式 in ("JPEG", "WEBP"):
            重 = 重编码图像(字节, 格式, 100)
            self.assertTrue(重.成功, 重.错误说明)
            self.assertEqual(重.值["格式"], 格式)
            统计 = 像素统计(base64.b64decode(重.值["图像b64"]))
            self.assertTrue(统计.成功, 统计.错误说明)
            for 通道 in ("红", "绿", "蓝"):
                self.assertLessEqual(
                    abs(统计.值["平均颜色"][通道] - 期望[通道]), 2, 通道)
        渐变 = base64.b64decode(生成占位图(
            64, 64, "渐变", 前景颜色="#FF0000", 背景颜色="#0000FF").值["图像b64"])
        低质量 = 重编码图像(渐变, "JPEG", 1)
        高质量 = 重编码图像(渐变, "JPEG", 100)
        self.assertTrue(低质量.成功 and 高质量.成功)
        self.assertLess(len(base64.b64decode(低质量.值["图像b64"])),
                        len(base64.b64decode(高质量.值["图像b64"])))

    def test_重编码图像非法参数(self):
        self.assertEqual(重编码图像(最小PNG, "GIF").错误码, "参数不合法")
        self.assertEqual(重编码图像(最小PNG, "PNG", 0).错误码, "参数不合法")
        self.assertEqual(重编码图像(最小PNG, "PNG", 101).错误码, "参数不合法")
        self.assertEqual(重编码图像(b"", "PNG").错误码, "参数不合法")
        self.assertEqual(重编码图像(最小PNG, "PNG", 90, 超时秒=0).错误码, "参数不合法")

    def test_新能力超大像素(self):
        self.assertEqual(生成缩略图(_大像素PNG(8000, 8000), 100).错误码, "超大")
        self.assertEqual(图像EXIF转置(_大像素PNG(8000, 8000)).错误码, "超大")
        self.assertEqual(透明背景合成(_大像素PNG(8000, 8000), "#FFFFFF").错误码, "超大")
        self.assertEqual(计算感知哈希(_大像素PNG(8000, 8000), "aHash").错误码, "超大")
        self.assertEqual(重编码图像(_大像素PNG(8000, 8000), "PNG").错误码, "超大")

    def test_子进程输出超大返回超大(self):
        with mock.patch.object(提供者模块, "_启动子进程", return_value=_假进程()), \
                mock.patch.object(提供者模块, "_终止进程组"), \
                mock.patch.object(提供者模块, "_关闭流"):
            结果 = 解码图像(最小PNG)
        self.assertEqual(结果.错误码, "超大")

    def test_清空PYTHONPATH全链路调用成功(self):
        with mock.patch.dict(os.environ, {"PYTHONPATH": ""}):
            结果 = 解码图像(最小PNG)
        self.assertTrue(结果.成功, 结果.错误说明)
        self.assertEqual(结果.值["格式"], "PNG")

    def test_子进程入口清空PYTHONPATH最小调用成功(self):
        入口 = 提供者目录 / "实现" / "子进程入口.py"
        请求 = json.dumps({"操作": "解码图像",
                           "字节b64": base64.b64encode(最小PNG).decode("ascii")},
                          ensure_ascii=False) + "\n"
        环境 = dict(os.environ)
        环境["PYTHONPATH"] = ""
        运行 = subprocess.run([sys.executable, str(入口)], input=请求.encode("utf-8"),
                              capture_output=True, env=环境, timeout=60)
        self.assertEqual(运行.returncode, 0,
                         运行.stderr.decode("utf-8", errors="replace"))
        响应 = json.loads(运行.stdout.decode("utf-8"))
        self.assertTrue(响应["成功"], 响应)
        self.assertEqual(响应["值"]["格式"], "PNG")

    def test_子进程自举激活指针解析(self):
        临时 = Path(tempfile.mkdtemp(prefix="测试_Pillow自举_"))
        try:
            环境目录 = 临时 / "平台客户端环境"
            客户端目录 = 环境目录 / "平台客户端"
            实现目录 = (客户端目录 / "支持库" / "后端" / "图像处理支持库"
                        / "图像解码" / "实现")
            实现目录.mkdir(parents=True)
            (客户端目录 / "__init__.py").write_text("", encoding="utf-8")
            (环境目录 / "当前.json").write_text(json.dumps(
                {"摘要sha256": "0" * 16, "制品目录": "平台客户端-0000000000000000",
                 "制品摘要": "0" * 32, "版本": 1, "栅栏令牌": 1}),
                encoding="utf-8")
            源实现 = 提供者目录 / "实现"
            shutil.copy2(源实现 / "子进程入口.py", 实现目录 / "子进程入口.py")
            shutil.copy2(源实现 / "子进程解析.py", 实现目录 / "子进程解析.py")
            请求 = json.dumps({"操作": "解码图像",
                               "字节b64": base64.b64encode(最小PNG).decode("ascii")},
                              ensure_ascii=False) + "\n"
            环境 = dict(os.environ)
            环境["PYTHONPATH"] = ""
            环境["Pillow提供者_客户端环境目录"] = str(环境目录)
            运行 = subprocess.run([sys.executable, str(实现目录 / "子进程入口.py")],
                                  input=请求.encode("utf-8"), capture_output=True,
                                  env=环境, timeout=60)
            self.assertEqual(运行.returncode, 0,
                             运行.stderr.decode("utf-8", errors="replace"))
            响应 = json.loads(运行.stdout.decode("utf-8"))
            self.assertTrue(响应["成功"], 响应)
        finally:
            shutil.rmtree(临时, ignore_errors=True)

    def test_超时取消后无残留进程(self):
        捕获 = {}

        def 挂起执行(请求, 超时秒=提供者模块.默认超时秒):
            进程 = 提供者模块._启动子进程()
            捕获["进程"] = 进程
            try:
                进程.communicate(timeout=0.3)  # 不发请求 → 真实挂起 → 超时
            except subprocess.TimeoutExpired:
                return 提供者模块._失败("超时", "模拟超时", 可重试=真)
            finally:
                提供者模块._终止进程组(进程)
                for 流 in (进程.stdin, 进程.stdout, 进程.stderr):
                    if 流:
                        流.close()
            return 提供者模块._失败("超时", "模拟超时", 可重试=真)
        with mock.patch.object(提供者模块, "执行任务", side_effect=挂起执行):
            结果 = 解码图像(最小PNG)
        self.assertEqual(结果.错误码, "超时")
        self.assertIsNotNone(捕获["进程"].poll())  # 进程组已被强杀，无残留

    def test_注册能力与声明一致(self):
        注册表 = 能力注册表()
        注册能力(注册表)
        声明数据 = json.loads((提供者目录 / "包声明.json").read_text(encoding="utf-8"))
        定义数据 = json.loads((提供者目录 / "能力定义.json").read_text(encoding="utf-8"))
        声明能力表 = [能力["能力id"] for 能力 in 声明数据["能力"]]
        定义能力表 = [能力["能力id"] for 能力 in 定义数据["能力列表"]]
        self.assertEqual(len(定义能力表), 9)
        self.assertEqual(定义能力表, 声明能力表)
        for 能力id in 定义能力表:
            self.assertIsNotNone(注册表.获取(能力id), 能力id)

    def test_完整性摘要一致(self):
        摘要数据 = json.loads((提供者目录 / "完整性摘要.json").read_text(encoding="utf-8"))
        self.assertEqual(摘要数据["包id"], "支持库.后端.图像处理支持库.图像解码")
        self.assertEqual(摘要数据["摘要算法"], "sha256")
        self.assertTrue(摘要数据["文件清单"], "文件清单不得为空")
        清单路径 = {项["路径"] for 项 in 摘要数据["文件清单"]}
        self.assertIn("__init__.py", 清单路径)
        self.assertIn("能力定义.json", 清单路径)
        self.assertIn("实现/子进程入口.py", 清单路径)

    def test_九要素齐全(self):
        """S0 正式包九要素 + 平台权威校验器复核。

        依赖契约按平台判据**可选**：`组件规范支持库/实现/组件规范.py::校验组件规范`
        与 `组件合规/合规测试包.py::_场景依赖` 两处同源——**无文件 = 无内部依赖**；
        提交 24704a44（2026-09-15 华哥决定）已把空白内部依赖声明全部删除，本包
        `依赖契约/依赖契约.json` 因此**不该存在**。本用例不再把「文件必须存在」当合格线，
        改为「生产权威校验器通过 + 若存在则不得是空壳」，断言强度只增不减。
        """
        for 相对路径 in (
            "配置契约/配置契约.json", "权限契约/权限契约.json",
            "资源预算.json", "复用决策.json", "验证场景引用.json", "完整性摘要.json",
        ):
            self.assertTrue((提供者目录 / 相对路径).is_file(), f"缺少 {相对路径}")
        依赖契约 = 提供者目录 / "依赖契约" / "依赖契约.json"
        if 依赖契约.is_file():
            self.assertTrue(json.loads(依赖契约.read_text(encoding="utf-8")).get("依赖"),
                            "依赖契约存在即不得是空壳（空白内部依赖声明一律删）")
        规范结果 = 校验组件规范(提供者目录)
        self.assertTrue(规范结果.成功, f"九要素不合规: {规范结果.问题列表}")
        预算 = json.loads((提供者目录 / "资源预算.json").read_text(encoding="utf-8"))
        for 键 in ("内存上限", "线程上限", "子进程上限", "并发调用上限", "队列长度",
                   "文件句柄上限", "临时空间上限", "单次调用超时", "每分钟重启次数", "空闲回收时间"):
            self.assertIn(键, 预算, f"资源预算缺少 {键}")
        复用 = json.loads((提供者目录 / "复用决策.json").read_text(encoding="utf-8"))
        self.assertTrue(复用.get("搜索词") and 复用.get("候选能力id"))

    def test_聚合契约全要素与权限覆盖(self):
        """聚合契约 S0.1：契约版本 + 逐能力 版本/调用示例；权限逐能力覆盖。"""
        契约数据 = json.loads((提供者目录 / "能力契约" / "参数契约.json").read_text(encoding="utf-8"))
        # 契约版本从唯一事实源现读（公共契约/版本规则/契约版本.py），禁写死字面量：
        # 曾写死 "1.0.0"，平台契约版本收敛为唯一值 2.0.0 后就成假红。
        self.assertEqual(契约数据["契约版本"], 契约版本)
        能力表 = 契约数据["能力契约"]
        定义数据 = json.loads((提供者目录 / "能力定义.json").read_text(encoding="utf-8"))
        定义版本 = {能力["能力id"]: 能力["版本"] for 能力 in 定义数据["能力列表"]}
        # 数量不写死：与 能力定义.json（唯一事实源）对称，两侧任一漂移即红。
        self.assertEqual(len(能力表), len(定义数据["能力列表"]))
        权限数据 = json.loads((提供者目录 / "权限契约" / "权限契约.json").read_text(encoding="utf-8"))
        for 能力 in 能力表:
            # 逐能力迭代版本与 能力定义.json 对称（两源必须一致），同样不写死字面量。
            self.assertEqual(能力["版本"], 定义版本.get(能力["能力id"]), 能力["能力id"])
            self.assertIn("调用示例", 能力, 能力["能力id"])
            self.assertIsInstance(能力["调用示例"].get("参数"), dict)
            for 参数 in 能力["参数"]:
                self.assertNotEqual(参数["类型"], "任意", f"{能力['能力id']} 参数 {参数['名称']} 禁止任意类型")
                self.assertIn("必填", 参数)
                self.assertIn("默认值", 参数)
            self.assertIn(能力["能力id"], 权限数据, f"{能力['能力id']} 缺权限声明")
        self.assertEqual({能力["能力id"] for 能力 in 能力表},
                         {能力["能力id"] for 能力 in 定义数据["能力列表"]})


if __name__ == "__main__":
    unittest.main()
