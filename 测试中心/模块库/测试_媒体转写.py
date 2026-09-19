"""模块库.媒体转写 组合能力真实测试：经 HTTP 网关调用 MLX Whisper 支持库能力。

覆盖：模型未配置如实返回（不伪造转写）、模型缺失语义、伪脚本模拟子进程
（崩溃/超时，经支持库真实链）、转写视频文件流程、参数错误（路径/令牌/配置）、
平台不可用（HTTP 连接器未装配如实返回 提供者不可用）、注册能力 4 项与四者对称。

测试装配：setUpClass 启动 后端核心 + 随机回环网关，所有测试请求走 HTTP；
保留原有 mock/进程内装配用例（惰性装配关闭与全局服务注入仅为旧通道残留，无害）。
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
from 后端核心.后端核心 import 后端核心
from 运行核心.统一网关.网关核心 import 网关核心
from 运行核心.统一网关.本地网关 import 本地网关服务器
from 运行核心.能力调用.HTTP连接器 import HTTP连接器

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
    """真实装配：启动后端核心与本地网关，模块能力经 HTTP 连接器走统一网关。"""

    @classmethod
    def setUpClass(cls):
        from 公共契约.能力契约.调用器 import 设置惰性装配函数
        cls.原惰性装配 = 设置惰性装配函数.__globals__.get("_惰性装配函数")
        设置惰性装配函数(None)
        cls.后端 = 后端核心()
        启动结果 = cls.后端.启动()
        if not 启动结果.成功:
            raise RuntimeError(f"后端核心启动失败: {启动结果.错误说明}")
        cls.网关 = 本地网关服务器(
            网关核心实例=网关核心(cls.后端), 地址="127.0.0.1", 端口=0,
            # 请求超时秒 取平台口径 1800（运行核心/启动运行核心网关.py:44；本地网关默认同值）：
            # 10 会把能力契约声明的 超时秒=60/300 判成「超时时间超出允许范围」而全红。
            配置={"请求超时秒": 1800, "要求凭证": False, "禁止客户端身份": False},
        )
        成功, 说明 = cls.网关.启动()
        if not 成功:
            cls.后端.优雅关闭()
            raise RuntimeError(f"网关启动失败: {说明}")
        from 模块库.媒体转写 import 设置HTTP连接器
        设置HTTP连接器(HTTP连接器(网关地址="127.0.0.1", 网关端口=cls.网关.端口))

    @classmethod
    def tearDownClass(cls):
        from 模块库.媒体转写 import 设置HTTP连接器
        设置HTTP连接器(None)
        cls.网关.优雅停止()
        cls.后端.优雅关闭()
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
        结果 = 转写音频文件(self.音频路径, 取消令牌id="令牌1")
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
        """平台不可用（HTTP 连接器未装配）如实返回 提供者不可用，不抛异常。"""
        from 模块库.媒体转写 import 设置HTTP连接器
        设置HTTP连接器(None)
        try:
            结果 = 转写音频文件(self.音频路径)
            self.assertFalse(结果.成功)
            self.assertEqual(结果.错误码, "提供者不可用")
            结果 = 检查可用性()
            self.assertFalse(结果.成功)
            self.assertEqual(结果.错误码, "提供者不可用")
        finally:
            设置HTTP连接器(HTTP连接器(网关地址="127.0.0.1", 网关端口=self.网关.端口))

    def test_平台不可用时返回提供者不可用(self):
        """卸载 HTTP 连接器后调用能力：模块返回 提供者不可用，不抛异常。"""
        from 模块库.媒体转写 import 设置HTTP连接器
        设置HTTP连接器(None)
        try:
            结果 = 获取模型版本()
            self.assertFalse(结果.成功)
            self.assertEqual(结果.错误码, "提供者不可用")
            结果 = 转写视频文件(self.视频路径)
            self.assertFalse(结果.成功)
            self.assertEqual(结果.错误码, "提供者不可用")
        finally:
            设置HTTP连接器(HTTP连接器(网关地址="127.0.0.1", 网关端口=self.网关.端口))


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
        self.assertEqual(set(__all__), {id.split(".")[-1] for id in 能力id表} | {"设置HTTP连接器"})
        for 条目 in 注册表.条目:
            self.assertEqual(条目.包id, "模块库.媒体转写")

    def test_公开入口导出检查可用性(self):
        from 模块库.媒体转写 import 检查可用性 as 入口函数
        self.assertTrue(callable(入口函数))


class Test注册参数口径(unittest.TestCase):
    """注册参数必须**整条**来自 能力契约/参数契约.json（含 必填/默认值）。

    为什么单独立一档：AST 门禁（`开发工具/契约编译/漂移检测.读取注册口径`）只认
    `注册能力` **函数体内字面量**，能证明「注册侧声明了 必填」；但「装配后注册表里的
    参数声明真的带着 必填」只能运行时验。网关唯一校验点
    `运行核心/统一网关/协议/类型规格.py` 的判据是 `项.get("必填") is 真` —— 少一个键
    就是必填校验静默失效（少传参数落进实现体抛 TypeError，用户拿 500 而非 400）。
    """

    @staticmethod
    def _注册参数表() -> dict:
        class 假注册表:
            def __init__(self):
                self.条目 = []

            def 注册(self, 能力):
                self.条目.append(能力)

        注册表 = 假注册表()
        from 模块库.媒体转写 import 注册能力

        注册能力(注册表)
        return {条目.能力id: 条目.参数 for 条目 in 注册表.条目}

    def test_注册参数与契约口径逐条相同(self):
        """注册参数按**注册口径四键**（名称/类型/必填/默认值）与契约逐条相同。

        为什么不是「整条含 说明」：契约的 `说明` 不进注册口径 —— 漂移检测的
        `_参数项` 只归一这四键，网关只读 名称/类型/必填。所以镜像是**四键口径镜像**
        （与全仓已落地的 31 包同形），多出来的键反而会造出「注册声明了契约没声明的东西」。
        反过来，少任一键就是缺陷：缺 `必填` → 网关 `项.get("必填") is 真` 判假 →
        必填校验静默失效（用户拿 500 不拿 400）。
        """
        import json
        from pathlib import Path
        契约路径 = (Path(__file__).resolve().parents[2] / "模块库" / "媒体转写"
                 / "能力契约" / "参数契约.json")
        契约 = json.loads(契约路径.read_text(encoding="utf-8"))
        契约表 = {条目["能力id"]: 条目.get("参数", []) for 条目 in 契约["能力契约"]}
        注册表 = self._注册参数表()
        self.assertEqual(sorted(注册表), sorted(契约表))
        允许键集 = {"名称", "类型", "必填", "默认值"}
        for 能力id, 契约参数 in 契约表.items():
            self.assertEqual([项["名称"] for 项 in 注册表[能力id]],
                             [项["名称"] for 项 in 契约参数], f"{能力id} 参数名序不一致")
            for 注册项, 契约项 in zip(注册表[能力id], 契约参数):
                self.assertEqual(set(注册项) - 允许键集, set(),
                                 f"{能力id}.{注册项['名称']} 注册参数出现口径外的键")
                for 键 in ("名称", "类型", "必填", "默认值"):
                    self.assertIn(键, 注册项, f"{能力id}.{注册项['名称']} 漏声明 {键}")
                    self.assertEqual(注册项[键], 契约项[键],
                                     f"{能力id}.{注册项['名称']} 的 {键} 与契约不一致")

    def test_必填项按网关判据可见(self):
        """网关判据 `项.get("必填") is 真` 必须能把契约的必填项识别出来。"""
        from 公共契约.基础类型.逻辑类型 import 真
        注册表 = self._注册参数表()
        必填项 = {能力id: [项["名称"] for 项 in 参数表 if 项.get("必填") is 真]
                for 能力id, 参数表 in 注册表.items()}
        self.assertEqual(必填项["媒体转写.转写视频文件"], ["文件路径"])
        self.assertEqual(必填项["媒体转写.转写音频文件"], ["文件路径"])
        self.assertEqual(必填项["媒体转写.检查可用性"], [])
        self.assertEqual(必填项["媒体转写.获取模型版本"], [])

    def test_默认值与契约一致(self):
        注册表 = self._注册参数表()
        取值 = {(能力id, 项["名称"]): 项.get("默认值")
              for 能力id, 参数表 in 注册表.items() for 项 in 参数表}
        self.assertEqual(取值[("媒体转写.转写音频文件", "超时秒")], 300)
        self.assertEqual(取值[("媒体转写.转写视频文件", "转写超时秒")], 300)
        self.assertEqual(取值[("媒体转写.转写音频文件", "取消令牌id")], "")
        self.assertIsNone(取值[("媒体转写.转写音频文件", "配置")])
        self.assertIsNone(取值[("媒体转写.转写音频文件", "文件路径")])


if __name__ == "__main__":
    unittest.main()
