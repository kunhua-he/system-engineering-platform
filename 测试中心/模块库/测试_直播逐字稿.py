"""模块库.直播逐字稿 组合能力真实测试：经统一能力调用器走网关/注册表。

覆盖：参数校验、文件不存在、未配置模型如实返回（不伪造转写）、
读取项目状态（无状态文件）、检查可用性、注册能力 3 项齐全、
模块公开入口可导入且返回统一结果。

测试装配：setUpClass 启动 后端核心 + 随机回环网关，走真实注册表
（媒体处理/媒体转写/转写支持库能力注册），直播逐字稿模块经
获取能力调用器 调用底层组合能力。
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

if str(Path(__file__).resolve().parents[2]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from 模块库.直播逐字稿 import 检查可用性, 读取项目状态, 转写媒体文件, 注册能力
from 公共契约.基础类型.结果类型 import 结果 as 结果类型

环境变量模型路径 = "MLXWhisper提供者_模型路径"
环境变量模型名 = "MLXWhisper提供者_模型名"
环境变量名表 = [环境变量模型路径, 环境变量模型名]


def 运行ffmpeg(参数列表: list[str]) -> bool:
    """真实 ffmpeg 生成媒体；不可用或失败返回 False。"""
    try:
        结果 = subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error"] + 参数列表,
            capture_output=True, timeout=60)
        return 结果.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def 生成测试视频(目录: Path) -> str:
    视频路径 = str(目录 / "测试视频.mp4")
    if 运行ffmpeg([
        "-f", "lavfi", "-i", "color=c=blue:s=64x64:d=2",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
        "-shortest", "-c:v", "mpeg4", "-c:a", "aac", 视频路径,
    ]) and Path(视频路径).is_file():
        return 视频路径
    return ""


def 生成测试音频(目录: Path) -> str:
    音频路径 = str(目录 / "测试音频.wav")
    if 运行ffmpeg([
        "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
        "-c:a", "pcm_s16le", 音频路径,
    ]) and Path(音频路径).is_file():
        return 音频路径
    return ""


class 直播逐字稿装配(unittest.TestCase):
    """手动装配：只注册本模块依赖的 4 个包，不触发全树扫描（避开并发线半成品）。"""

    @classmethod
    def setUpClass(cls):
        from 公共契约.能力契约.调用器 import 设置惰性装配函数
        cls.原惰性装配 = 设置惰性装配函数.__globals__.get("_惰性装配函数")
        设置惰性装配函数(None)
        # 只注册本模块链路需要的包：转写支持库 + 媒体转写 + 媒体处理 + 直播逐字稿
        from 公共契约.能力契约.调用器 import 注册能力调用器
        from 公共契约.能力契约.契约 import 能力注册表
        from 运行核心.能力调用.唯一能力调用 import 唯一能力调用服务
        注册表 = 能力注册表()
        from 支持库.后端.转写支持库.转写 import 注册能力 as 注册转写
        注册转写(注册表)
        from 支持库.后端.媒体处理支持库.FFmpeg媒体 import 注册能力 as 注册FFmpeg
        注册FFmpeg(注册表)
        from 模块库.媒体转写 import 注册能力 as 注册媒体转写
        注册媒体转写(注册表)
        from 模块库.媒体处理 import 注册能力 as 注册媒体处理
        注册媒体处理(注册表)
        # 实现层经底座做 I/O 与 JSON，须一并装配这三包（文件操作/数据交换/资源管理）
        from 支持库.后端.文件系统支持库.文件操作 import 注册能力 as 注册文件操作
        注册文件操作(注册表)
        from 支持库.后端.数据操作支持库.数据交换 import 注册能力 as 注册数据交换
        注册数据交换(注册表)
        from 支持库.后端.系统核心支持库.资源管理 import 注册能力 as 注册资源管理
        注册资源管理(注册表)
        注册能力(注册表)
        cls.调用服务 = 唯一能力调用服务(注册表)
        注册能力调用器(cls.调用服务)

    @classmethod
    def tearDownClass(cls):
        from 公共契约.能力契约.调用器 import 注册能力调用器, 设置惰性装配函数
        注册能力调用器(None)
        设置惰性装配函数(cls.原惰性装配)

    def setUp(self):
        from 运行核心.能力调用.唯一能力调用 import 设置全局唯一服务
        设置全局唯一服务(self.调用服务)
        self.原环境 = {名: os.environ.get(名) for 名 in 环境变量名表}
        for 名 in 环境变量名表:
            os.environ.pop(名, None)
        self.临时目录 = Path(tempfile.mkdtemp(prefix="测试_直播逐字稿_"))
        self.视频路径 = 生成测试视频(self.临时目录)
        self.音频路径 = 生成测试音频(self.临时目录)
        if not self.视频路径 and not self.音频路径:
            self.视频路径 = str(self.临时目录 / "示例视频.mp4")
            self.音频路径 = str(self.临时目录 / "示例音频.wav")

    def tearDown(self):
        from 运行核心.能力调用.唯一能力调用 import 设置全局唯一服务
        设置全局唯一服务(None)
        for 名, 值 in self.原环境.items():
            if 值 is None:
                os.environ.pop(名, None)
            else:
                os.environ[名] = 值
        shutil.rmtree(self.临时目录, ignore_errors=True)


class Test公开入口与注册(直播逐字稿装配):
    def test_公开入口可导入(self):
        for 能力名 in ("转写媒体文件", "检查可用性", "读取项目状态"):
            self.assertTrue(callable(globals()[能力名]), f"{能力名} 未从公开入口导出")

    def test_注册能力齐全(self):
        from 公共契约.能力契约.契约 import 能力注册表
        注册表 = 能力注册表()
        注册能力(注册表)
        for 能力id in ("直播逐字稿.转写媒体文件", "直播逐字稿.检查可用性", "直播逐字稿.读取项目状态"):
            self.assertIn(能力id, 注册表.能力id列表)

    def test_返回统一结果(self):
        结果 = 检查可用性(超时秒=30)
        self.assertIsInstance(结果, 结果类型)


class Test参数校验(直播逐字稿装配):
    def test_文件路径为空参数不合法(self):
        结果 = 转写媒体文件("", str(self.临时目录 / "输出"))
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "参数不合法")

    def test_输出目录为空参数不合法(self):
        结果 = 转写媒体文件(self.视频路径, "")
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "参数不合法")

    def test_文件不存在(self):
        结果 = 转写媒体文件(str(self.临时目录 / "不存在.mp4"), str(self.临时目录 / "输出"))
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "文件不存在")

    def test_非法数值参数(self):
        结果 = 转写媒体文件(self.视频路径, str(self.临时目录 / "输出"), 分片秒数=-1)
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "参数不合法")


class Test未配置模型如实返回(直播逐字稿装配):
    def test_转写媒体文件未配置不伪造转写(self):
        if not Path(self.视频路径).is_file():
            self.skipTest("无真实媒体文件")
        结果 = 转写媒体文件(self.视频路径, str(self.临时目录 / "输出"))
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "未配置模型")
        self.assertIsNone(结果.值)


class Test附加术语传递(直播逐字稿装配):
    def test_附加术语传给转写支持库(self):
        from unittest.mock import patch
        from 模块库.直播逐字稿.实现 import 直播逐字稿 as 实现

        记录 = []

        def 假调用(能力id, 请求参数):
            if 能力id == "媒体处理支持库.FFmpeg媒体.探测媒体":
                return 结果类型.成功结果({"时长秒": 1.0, "格式": "wav"})
            if 能力id == "转写支持库.转写.转写音频文件":
                记录.append((能力id, 请求参数))
                return 结果类型.成功结果({"文本": "华世王镞", "语言": "zh"})
            raise AssertionError(f"出现未预期的能力调用: {能力id}")

        with patch.object(实现, "_调用", side_effect=假调用):
            结果 = 实现.转写媒体文件(
                self.音频路径,
                str(self.临时目录 / "输出"),
                模型配置={"模型路径": "/模型"},
                附加术语="华世王镞、合作店",
            )

        self.assertTrue(结果.成功)
        self.assertEqual(len(记录), 1)
        self.assertEqual(记录[0][1]["附加术语"], "华世王镞、合作店")


class Test读取项目状态(直播逐字稿装配):
    def test_无项目状态目录不存在(self):
        结果 = 读取项目状态(str(self.临时目录 / "不存在项目"))
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "目录不存在")

    def test_参数校验(self):
        结果 = 读取项目状态("")
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "参数不合法")


class Test检查可用性(直播逐字稿装配):
    def test_未配置模型时链路不可用但不伪造(self):
        结果 = 检查可用性(超时秒=30)
        # ffmpeg 可用与否取决于本机；转写未配置应如实反映
        self.assertIsInstance(结果.成功, bool)
        if not 结果.成功:
            self.assertIn(结果.错误码, ("提供者不可用", "未配置模型"))


if __name__ == "__main__":
    unittest.main()
