"""模块库.媒体转写 组合 FFmpeg 与 MLX Whisper 支持库公开入口的真实测试。

覆盖：模型未配置如实返回（不伪造转写）、模型缺失语义、伪脚本模拟子进程
（崩溃/超时/取消，经支持库）、视频转写流程（真实 ffmpeg 提取音频 + 转写
段未配置）、提取段失败错误码透传、参数校验、零残留。
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

from unittest import mock

from 公共契约.基础类型.结果类型 import 结果
from 模块库.媒体转写 import (
    检查转写可用性,
    获取模型版本,
    转写视频文件,
    转写音频文件,
)

环境变量模型路径 = "MLXWhisper提供者_模型路径"
环境变量模型名 = "MLXWhisper提供者_模型名"
环境变量禁用库 = "MLXWhisper提供者_禁用库"
环境变量伪库行为 = "媒体转写测试_伪库行为"
环境变量名表 = [环境变量模型路径, 环境变量模型名, 环境变量禁用库, 环境变量伪库行为]


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


class 基础环境(unittest.TestCase):
    def setUp(self):
        self.原环境 = {名: os.environ.get(名) for 名 in 环境变量名表}
        for 名 in 环境变量名表:
            os.environ.pop(名, None)
        self.临时目录 = Path(tempfile.mkdtemp(prefix="测试_媒体转写_"))
        self.转写残留前 = {目录 for 目录 in Path(tempfile.gettempdir()).glob("媒体转写_*") if 目录.is_dir()}
        self.视频路径 = 生成测试视频(self.临时目录)
        self.音频路径 = 生成测试音频(self.临时目录)
        if not self.视频路径 or not self.音频路径:
            self.skipTest("本机 ffmpeg 不可用，跳过真实媒体用例")

    def tearDown(self):
        for 名, 值 in self.原环境.items():
            if 值 is None:
                os.environ.pop(名, None)
            else:
                os.environ[名] = 值
        shutil.rmtree(self.临时目录, ignore_errors=True)
        残留后 = {目录 for 目录 in Path(tempfile.gettempdir()).glob("媒体转写_*") if 目录.is_dir()}
        self.assertEqual(残留后 - self.转写残留前, set(), "媒体转写模块残留了临时目录")


class Test未配置模型如实返回(基础环境):
    def test_检查可用性未配置(self):
        结果 = 检查转写可用性()
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "未配置模型")

    def test_获取模型版本未配置(self):
        结果 = 获取模型版本()
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "未配置模型")

    def test_转写音频文件未配置不伪造转写(self):
        结果 = 转写音频文件(self.音频路径)
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "未配置模型")
        self.assertIsNone(结果.值)

    def test_转写视频文件未配置不伪造转写(self):
        结果 = 转写视频文件(self.视频路径)
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "未配置模型")
        self.assertIsNone(结果.值)


class Test模型缺失语义(基础环境):
    def setUp(self):
        super().setUp()
        self.缺失配置 = {"模型路径": str(self.临时目录 / "不存在模型目录"), "模型名": ""}

    def test_检查可用性模型缺失(self):
        结果 = 检查转写可用性(配置=self.缺失配置)
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "模型缺失")

    def test_转写音频文件模型缺失(self):
        结果 = 转写音频文件(self.音频路径, 配置=self.缺失配置)
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "模型缺失")

    def test_转写视频文件模型缺失(self):
        结果 = 转写视频文件(self.视频路径, 配置=self.缺失配置)
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "模型缺失")


class Test伪脚本子进程语义(基础环境):
    """伪 mlx_whisper 库经 PYTHONPATH 注入隔离子进程，驱动崩溃/超时/取消。"""

    def setUp(self):
        super().setUp()
        伪库目录 = self.临时目录 / "伪库"
        伪库目录.mkdir()
        (伪库目录 / "mlx_whisper.py").write_text(
            "import os, time\n"
            "__version__ = '9.9.测试伪库'\n"
            "def transcribe(文件路径, path_or_hf_repo=None):\n"
            "    行为 = os.environ.get('媒体转写测试_伪库行为', '')\n"
            "    if 行为 == '崩溃':\n"
            "        os._exit(1)\n"
            "    if 行为 == '慢速':\n"
            "        time.sleep(300)\n"
            "    return {'text': '伪库转写文本', 'language': 'zh'}\n",
            encoding="utf-8")
        self.原路径变量 = os.environ.get("PYTHONPATH", "")
        os.environ["PYTHONPATH"] = str(伪库目录) + (os.pathsep + self.原路径变量 if self.原路径变量 else "")
        模型目录 = self.临时目录 / "模型目录"
        模型目录.mkdir()
        self.模型配置 = {"模型路径": str(模型目录), "模型名": "伪模型"}

    def tearDown(self):
        if self.原路径变量:
            os.environ["PYTHONPATH"] = self.原路径变量
        else:
            os.environ.pop("PYTHONPATH", None)
        super().tearDown()

    def test_伪库探针生效(self):
        结果 = 检查转写可用性(配置=self.模型配置)
        self.assertTrue(结果.成功, 结果.错误说明)
        self.assertEqual(结果.值["模型版本"], "9.9.测试伪库")

    def test_子进程崩溃映射进程崩溃(self):
        os.environ[环境变量伪库行为] = "崩溃"
        结果 = 转写音频文件(self.音频路径, 配置=self.模型配置)
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "进程崩溃")

    def test_子进程超时映射超时(self):
        os.environ[环境变量伪库行为] = "慢速"
        结果 = 转写音频文件(self.音频路径, 超时秒=1, 配置=self.模型配置)
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "超时")

    def test_取消判断映射取消(self):
        os.environ[环境变量伪库行为] = "慢速"
        结果 = 转写音频文件(self.音频路径, 超时秒=30,
                          取消判断=lambda: True, 配置=self.模型配置)
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "取消")


class Test转写视频流程(基础环境):
    def test_提取段失败错误码透传(self):
        失败结果 = 结果.失败("无音轨", "媒体不包含音频流", 来源="FFmpeg提供者")
        with mock.patch(
            "模块库.媒体转写.实现.媒体转写._提取音频",
            return_value=失败结果,
        ):
            转写结果 = 转写视频文件(self.视频路径)
        self.assertFalse(转写结果.成功)
        self.assertEqual(转写结果.错误码, "无音轨")

    def test_参数不合法(self):
        结果 = 转写视频文件("")
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "参数不合法")

    def test_视频转写流程提取段真实执行(self):
        结果 = 转写视频文件(self.视频路径)
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "未配置模型")
        self.assertTrue(Path(self.视频路径).is_file())


if __name__ == "__main__":
    unittest.main()
