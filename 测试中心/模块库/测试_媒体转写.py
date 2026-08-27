"""模块库.媒体转写 组合能力真实测试：经唯一能力调用服务装配 MLX Whisper 支持库能力。

覆盖：模型未配置如实返回（不伪造转写）、模型缺失语义、伪脚本模拟子进程
（崩溃/超时，经支持库真实链）、转写视频文件流程、参数错误（路径/令牌/配置）、
平台不可用（调用器未装配如实返回 提供者不可用）、注册能力 4 项与四者对称。
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

from 模块库.媒体转写 import 检查可用性, 获取模型版本, 转写音频文件, 转写视频文件

环境变量模型路径 = "MLXWhisper提供者_模型路径"
环境变量模型名 = "MLXWhisper提供者_模型名"
环境变量伪库行为 = "媒体转写测试_伪库行为"
环境变量名表 = [环境变量模型路径, 环境变量模型名, 环境变量伪库行为]


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


class 媒体转写装配(unittest.TestCase):
    """真实装配：注册 MLX Whisper 提供者能力并经唯一服务注入调用器。"""

    @classmethod
    def setUpClass(cls):
        from 公共契约.能力契约.调用器 import 设置惰性装配函数
        cls.原惰性装配 = 设置惰性装配函数.__globals__.get("_惰性装配函数")
        设置惰性装配函数(None)

    @classmethod
    def tearDownClass(cls):
        from 公共契约.能力契约.调用器 import 设置惰性装配函数
        设置惰性装配函数(cls.原惰性装配)

    def setUp(self):
        from 公共契约.能力契约.契约 import 能力注册表
        from 运行核心.能力调用.唯一能力调用 import 设置全局唯一服务, 唯一能力调用服务
        from 支持库.后端.转写支持库.转写 import 注册能力 as 注册转写能力

        注册表 = 能力注册表()
        注册转写能力(注册表)
        设置全局唯一服务(唯一能力调用服务(注册表))
        self.原环境 = {名: os.environ.get(名) for 名 in 环境变量名表}
        for 名 in 环境变量名表:
            os.environ.pop(名, None)
        self.临时目录 = Path(tempfile.mkdtemp(prefix="测试_媒体转写_"))
        self.视频路径 = 生成测试视频(self.临时目录)
        self.音频路径 = 生成测试音频(self.临时目录)
        if not self.视频路径 and not self.音频路径:
            # 未配置模型/模型缺失/参数错误/平台不可用语义不依赖真实媒体文件
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


class Test未配置模型如实返回(媒体转写装配):
    def test_检查可用性未配置(self):
        结果 = 检查可用性()
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


class Test模型缺失语义(媒体转写装配):
    def setUp(self):
        super().setUp()
        self.缺失配置 = {"模型路径": str(self.临时目录 / "不存在模型目录"), "模型名": ""}

    def test_检查可用性模型缺失(self):
        结果 = 检查可用性(配置=self.缺失配置)
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "模型缺失")

    def test_获取模型版本模型缺失(self):
        结果 = 获取模型版本(配置=self.缺失配置)
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


class Test参数错误(媒体转写装配):
    def test_空路径参数不合法(self):
        for 函数 in (转写音频文件, 转写视频文件):
            结果 = 函数("")
            self.assertFalse(结果.成功)
            self.assertEqual(结果.错误码, "参数不合法")
            结果 = 函数(None)
            self.assertFalse(结果.成功)
            self.assertEqual(结果.错误码, "参数不合法")

    def test_取消令牌id必须为文本(self):
        结果 = 转写音频文件(self.音频路径, 取消令牌id=123)
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "参数不合法")
        结果 = 转写视频文件(self.视频路径, 取消令牌id={"非序列化": True})
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "参数不合法")

    def test_取消令牌id文本放行(self):
        结果 = 转写音频文件(self.音频路径, 取消令牌id="令牌-甲")
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "未配置模型")

    def test_超时秒必须为正数(self):
        结果 = 检查可用性(超时秒=-1)
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "参数不合法")
        结果 = 获取模型版本(超时秒=-1)
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "参数不合法")
        结果 = 转写音频文件(self.音频路径, 超时秒=-1)
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "参数不合法")
        结果 = 转写视频文件(self.视频路径, 转写超时秒=-1)
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "参数不合法")

    def test_配置必须为对象(self):
        结果 = 检查可用性(配置="不是对象")
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "参数不合法")
        结果 = 转写音频文件(self.音频路径, 配置=[1, 2])
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "参数不合法")


class Test平台不可用(媒体转写装配):
    def test_调用器未装配如实返回(self):
        from 运行核心.能力调用.唯一能力调用 import 设置全局唯一服务
        设置全局唯一服务(None)
        结果 = 转写音频文件(self.音频路径)
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "提供者不可用")
        结果 = 检查可用性()
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "提供者不可用")


class Test伪脚本子进程语义(媒体转写装配):
    """伪 mlx_whisper 库经 PYTHONPATH 注入隔离子进程，驱动崩溃/超时（真实链）。"""

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
        self.音频文件 = self.临时目录 / "伪库音频.wav"
        self.音频文件.write_bytes(b"RIFF" + b"\x00" * 100)

    def tearDown(self):
        if self.原路径变量:
            os.environ["PYTHONPATH"] = self.原路径变量
        else:
            os.environ.pop("PYTHONPATH", None)
        super().tearDown()

    def test_伪库探针生效(self):
        结果 = 检查可用性(配置=self.模型配置)
        self.assertTrue(结果.成功, 结果.错误说明)
        self.assertEqual(结果.值["模型版本"], "9.9.测试伪库")

    def test_子进程崩溃映射进程崩溃(self):
        os.environ[环境变量伪库行为] = "崩溃"
        结果 = 转写音频文件(str(self.音频文件), 配置=self.模型配置)
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "进程崩溃")

    def test_子进程超时映射超时(self):
        os.environ[环境变量伪库行为] = "慢速"
        结果 = 转写音频文件(str(self.音频文件), 超时秒=1, 配置=self.模型配置)
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "超时")


class Test注册能力(unittest.TestCase):
    def test_模块注册四个能力且四者对称(self):
        class 假注册表:
            def __init__(self):
                self.条目 = []

            def 注册(self, 能力):
                self.条目.append(能力)

        注册表 = 假注册表()
        from 模块库.媒体转写 import 注册能力, __all__

        注册能力(注册表)
        能力id表 = [条目.能力id for 条目 in 注册表.条目]
        self.assertEqual(能力id表, [
            "媒体转写.转写视频文件",
            "媒体转写.转写音频文件",
            "媒体转写.检查可用性",
            "媒体转写.获取模型版本",
        ])
        self.assertEqual(set(__all__), {id.split(".")[-1] for id in 能力id表})
        for 条目 in 注册表.条目:
            self.assertEqual(条目.包id, "模块库.媒体转写")

    def test_公开入口导出检查可用性(self):
        from 模块库.媒体转写 import 检查可用性 as 入口函数
        self.assertTrue(callable(入口函数))


if __name__ == "__main__":
    unittest.main()
