"""MLX Whisper 提供者测试：未配置如实返回 + 伪脚本模拟受管子进程语义。
无真实模型时只断言"未配置"语义，绝不伪造转写结果；受管语义用伪脚本模拟。"""
from __future__ import annotations

import os, subprocess, sys, tempfile, unittest
from pathlib import Path
from unittest import mock

if str(Path(__file__).resolve().parents[2]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from 公共契约.运行时.平台适配 import 子进程组启动标志
from 支持库.适配层.MLXWhisper提供者 import 检查转写可用性, 获取模型版本, 转写音频文件
from 支持库.适配层.MLXWhisper提供者.实现 import 提供者 as 提供者模块

环境变量模型路径 = 提供者模块.环境变量模型路径
环境变量模型名 = 提供者模块.环境变量模型名


def _伪脚本(代码: str) -> subprocess.Popen:
    return subprocess.Popen([sys.executable, "-c", 代码], stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, **子进程组启动标志())


def _挂起进程() -> subprocess.Popen:
    return _伪脚本("import time; time.sleep(2)")


def _成功进程() -> subprocess.Popen:
    return _伪脚本("import sys,json;sys.stdout.write(json.dumps({'成功': True, '值': {'文本': '协议文本', '语言': 'zh', '模型名': '伪模型'}, '错误码': '', '错误说明': ''}));sys.stdout.flush()")


def _崩溃进程() -> subprocess.Popen:
    return _伪脚本("import os; os._exit(7)")


def _大输出进程() -> subprocess.Popen:
    return _伪脚本("import sys; sys.stdout.write('x' * 5000)")


def _关闭进程(进程: subprocess.Popen) -> None:
    try:
        进程.wait(timeout=5)
    except subprocess.TimeoutExpired:
        pass
    提供者模块._关闭流(进程)


class TestMLXWhisper未配置语义(unittest.TestCase):
    def setUp(self):
        self.临时目录 = Path(tempfile.mkdtemp(prefix="测试_MLXWhisper提供者_"))
        self.音频 = self.临时目录 / "音频.wav"
        self.音频.write_bytes(b"RIFF")
        self.伪模型目录 = self.临时目录 / "伪模型"
        self.伪模型目录.mkdir()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.临时目录, ignore_errors=True)

    def test_未配置模型检查可用性如实返回未配置(self):
        结果 = 检查转写可用性()
        self.assertEqual((结果.错误码, 结果.成功), ("未配置模型", False))

    def test_未配置模型转写如实返回未配置且不启动子进程(self):
        with mock.patch.object(提供者模块, "_启动子进程") as 启动:
            结果 = 转写音频文件(str(self.音频))
            启动.assert_not_called()
        self.assertEqual(结果.错误码, "未配置模型")

    def test_未配置模型获取版本如实返回未配置(self):
        self.assertEqual(获取模型版本().错误码, "未配置模型")

    def test_未配置模型禁止伪装可用(self):
        self.assertFalse(检查转写可用性().成功)
        self.assertFalse(转写音频文件(str(self.音频)).成功)

    def test_配置伪模型路径返回模型缺失(self):
        配置 = {"模型路径": str(self.临时目录 / "不存在模型")}
        self.assertEqual(检查转写可用性(配置=配置).错误码, "模型缺失")
        self.assertEqual(获取模型版本(配置=配置).错误码, "模型缺失")
        self.assertEqual(转写音频文件(str(self.音频), 配置=配置).错误码, "模型缺失")

    def test_配置对象优先于环境变量(self):
        with mock.patch.dict(os.environ, {环境变量模型路径: "/环境路径", 环境变量模型名: "环境名"}):
            self.assertEqual(提供者模块.读取模型配置({"模型路径": "/对象路径"})["模型路径"], "/对象路径")
            self.assertEqual(提供者模块.读取模型配置({"模型路径": "/对象路径"})["模型名"], "环境名")
            self.assertEqual(提供者模块.读取模型配置()["模型路径"], "/环境路径")

    def test_转写参数校验(self):
        self.assertEqual(转写音频文件("").错误码, "参数不合法")
        self.assertEqual(转写音频文件(str(self.临时目录 / "不存在.wav"),
                                        配置={"模型路径": str(self.伪模型目录)}).错误码, "文件不存在")


class TestMLXWhisper受管子进程(unittest.TestCase):
    def test_超时返回超时并回收进程(self):
        进程 = _挂起进程()
        with mock.patch.object(提供者模块, "_启动子进程", return_value=进程):
            结果 = 提供者模块.执行任务({"操作": "检查可用性"}, 超时秒=0.3)
        _关闭进程(进程)
        self.assertEqual((结果.错误码, 结果.可重试, 进程.poll() is not None), ("超时", True, True))

    def test_取消判断为真返回取消(self):
        进程 = _挂起进程()
        with mock.patch.object(提供者模块, "_启动子进程", return_value=进程):
            结果 = 提供者模块.执行任务({"操作": "检查可用性"}, 超时秒=5, 取消判断=lambda: True)
        _关闭进程(进程)
        self.assertEqual(结果.错误码, "取消")

    def test_子进程崩溃返回进程崩溃(self):
        进程 = _崩溃进程()
        with mock.patch.object(提供者模块, "_启动子进程", return_value=进程), \
                mock.patch.object(提供者模块, "_终止进程组", side_effect=_关闭进程):
            结果 = 提供者模块.执行任务({"操作": "检查可用性"})
            self.assertEqual(结果.错误码, "进程崩溃")
            self.assertTrue(结果.可重试)

    def test_受管协议成功响应解析(self):
        进程 = _成功进程()
        with mock.patch.object(提供者模块, "_启动子进程", return_value=进程):
            结果 = 提供者模块.执行任务({"操作": "检查可用性"})
            self.assertTrue(结果.成功, 结果.错误说明)
            self.assertEqual(结果.值["文本"], "协议文本")

    def test_输出超过上限返回超出限制(self):
        进程 = _大输出进程()
        with mock.patch.object(提供者模块, "_启动子进程", return_value=进程):
            结果 = 提供者模块.执行任务({"操作": "检查可用性"}, 最大输出字节=1024)
        _关闭进程(进程)
        self.assertEqual(结果.错误码, "超出限制")

    def test_库禁用返回提供者不可用(self):
        临时根 = Path(tempfile.mkdtemp(prefix="测试_MLXWhisper禁用_"))
        (临时根 / "伪模型").mkdir()
        try:
            with mock.patch.dict(os.environ, {"MLXWhisper提供者_禁用库": "mlx_whisper"}):
                结果 = 检查转写可用性(配置={"模型路径": str(临时根 / "伪模型")})
        finally:
            import shutil
            shutil.rmtree(临时根, ignore_errors=True)
        self.assertEqual((结果.错误码, 结果.可重试), ("提供者不可用", True))

    def test_无残留进程与临时文件(self):
        临时根 = Path(tempfile.mkdtemp(prefix="测试_MLXWhisper残留_"))
        try:
            with mock.patch.dict(os.environ, {"MLXWhisper提供者_禁用库": "mlx_whisper"}):
                for _ in range(3):
                    检查转写可用性(配置={"模型路径": str(临时根)})
            进程 = 提供者模块._启动子进程()
            提供者模块.等待并收集([进程])
            _关闭进程(进程)
            self.assertIsNotNone(进程.poll())
            self.assertEqual(list(临时根.iterdir()), [])
        finally:
            import shutil
            shutil.rmtree(临时根, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
