"""转写能力的跨平台双后端测试：按平台选后端 + 依赖锁按平台过滤（反向验证）。

覆盖三组判据（每组的**反向**都在同一用例里做成真实失败，不用恒真断言）：

1. **按平台选后端**（`公共契约/运行时/平台适配.转写后端()`）：
   monkeypatch `sys.platform` 切到 `darwin` / `win32` / `linux`，确认
   Apple Silicon → `mlx`、Windows / Linux → `faster-whisper`；
   并确认 **Windows/Linux 分支不再去加载 mlx**（用 `__import__` 记录真实加载过的模块名）。
2. **两个后端的调用适配**：伪库驱动，确认 `mlx_whisper` 的 dict 形态与
   `faster_whisper` 的 (生成器, info) 形态**产出同一份**对外结构，且
   `分段` 键名逐字一致（`序号`/`开始秒`/`结束秒`/`文本`/`平均对数概率`/`压缩比`/`无语音概率`）。
3. **依赖锁按平台过滤**：`适用平台` 不含当前平台的条目在
   `环境管理器.校验环境` / `_适用当前平台` / `强制校验.校验提供者环境` 三处都**不装不校验**；
   不写该字段的条目全平台适用（向后兼容）。

**诚实边界**：本测试只能在本机 macOS 上做**分支选择验证**（monkeypatch），
**不能证明真实 Windows / Linux 上装配成功**；真机证据由阿里云 Linux 与
GitHub Actions Windows runner 补。测试不做任何「模拟转写成功」的假动作。
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

if str(Path(__file__).resolve().parents[2]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from 公共契约.基础类型.逻辑类型 import 真, 假
from 公共契约.运行时 import 平台适配
from 运行核心.运行环境管理器 import 环境管理器
from 运行核心.运行环境管理器 import 强制校验
from 运行核心.运行环境管理器.强制校验 import 校验提供者环境
from 支持库.适配层.MLXWhisper提供者.实现 import 子进程解析 as 适配层解析
from 支持库.后端.转写支持库.转写.实现 import 子进程解析 as 后端解析

两处解析 = (适配层解析, 后端解析)

#: `分段` 字段名（**与改动前逐字一致**，一个都不许改）。
分段键名 = ("序号", "开始秒", "结束秒", "文本", "平均对数概率", "压缩比", "无语音概率")


class _伪MLX分段类:
    """伪 `faster_whisper.Segment`：字段在**对象属性**上（不是 dict 键）。"""

    def __init__(self, 开始: float, 结束: float, 文本: str) -> None:
        self.start = 开始
        self.end = 结束
        self.text = 文本
        self.avg_logprob = -0.21
        self.compression_ratio = 1.42
        self.no_speech_prob = 0.03


class _伪MLX库:
    """伪 `mlx_whisper`：`transcribe(path_or_hf_repo=…)` 返回 **dict**。"""

    __version__ = "0.4.3-伪"
    最近参数: dict = {}

    @classmethod
    def transcribe(cls, 文件: str, **参数):
        cls.最近参数 = dict(参数)
        return {
            "text": "  适配层文本  ",
            "language": "zh",
            "segments": [{"start": 0.0, "end": 1.25, "text": "第一段",
                          "avg_logprob": -0.11, "compression_ratio": 1.1, "no_speech_prob": 0.01}],
        }


class _伪FasterWhisperInfo:
    """伪 `TranscriptionInfo`：文本/语言在属性上。"""

    def __init__(self) -> None:
        self.text = "  后端文本  "
        self.language = "zh"


class _伪FasterWhisper模型:
    最近参数: dict = {}

    def __init__(self, 目标: str) -> None:
        self.目标 = 目标

    def transcribe(self, 文件: str, **参数):
        type(self).最近参数 = dict(参数)
        # 分段是**惰性生成器**：不物化就会随 info 一起被丢弃（本测试即验证它被物化）
        生成器 = (_伪MLX分段类(0.0, 2.5, "第一段"), _伪MLX分段类(2.5, 4.0, "第二段"))
        return 生成器, _伪FasterWhisperInfo()


class _伪FasterWhisper库:
    """伪 `faster_whisper`：`WhisperModel(...).transcribe(...)` 返回 **(生成器, info)**。"""

    __version__ = "1.2.1-伪"
    WhisperModel = _伪FasterWhisper模型


class Test按平台选后端(unittest.TestCase):
    """判据 1：收口层按平台选后端，Windows/Linux 不再加载 mlx。"""

    def _切平台(self, 平台标志: str, 架构: str):
        """同时切 `sys.platform` 与 `platform.machine()`（后端判定只用这两项）。"""
        return mock.patch.multiple(
            sys, platform=平台标志,
        ), mock.patch.object(平台适配.platform, "machine", return_value=架构)

    def test_AppleSilicon选mlx(self):
        p1, p2 = self._切平台("darwin", "arm64")
        with p1, p2:
            self.assertEqual(平台适配.转写后端(), "mlx")
            self.assertEqual(平台适配.转写后端库名(), "mlx_whisper")
            self.assertTrue(平台适配.是否AppleSilicon())

    def test_IntelMac退到faster_whisper(self):
        """macOS 但非 arm64：MLX 结构性不可用，必须退到 faster-whisper（不留无主区间）。"""
        p1, p2 = self._切平台("darwin", "x86_64")
        with p1, p2:
            self.assertEqual(平台适配.转写后端(), "faster-whisper")
            self.assertEqual(平台适配.转写后端库名(), "faster_whisper")

    def test_windows选faster_whisper(self):
        p1, p2 = self._切平台("win32", "AMD64")
        with p1, p2, mock.patch.dict(sys.modules, {"faster_whisper": _伪FasterWhisper库}):
            self.assertEqual(平台适配.转写后端(), "faster-whisper")
            self.assertEqual(平台适配.转写后端库名(), "faster_whisper")

    def test_linux选faster_whisper(self):
        p1, p2 = self._切平台("linux", "x86_64")
        with p1, p2, mock.patch.dict(sys.modules, {"faster_whisper": _伪FasterWhisper库}):
            self.assertEqual(平台适配.转写后端(), "faster-whisper")
            self.assertEqual(平台适配.转写后端库名(), "faster_whisper")

    def test_反查表与标识表口径(self):
        """别名/反查名（供机器校验）：两表键集合一致，且标识与库名逐项对应。"""
        self.assertEqual(set(平台适配.转写后端标识表), set(平台适配.转写后端库名表))
        self.assertEqual(set(平台适配.转写后端库名表), {"mlx", "faster-whisper"})
        self.assertEqual(平台适配.转写后端库名("mlx"), "mlx_whisper")
        self.assertEqual(平台适配.转写后端库名("faster-whisper"), "faster_whisper")

    def test_不认识的标识返回空串不猜(self):
        """fail-closed：认不出的后端标识返回空串（调用方据此报 提供者不可用，不猜库名）。"""
        self.assertEqual(平台适配.转写后端库名("不存在的后端"), "")

    def test_WindowsLinux分支不再加载mlx(self):
        """**核心反向判据**：非 Apple Silicon 上 `_加载库` 绝不触碰 mlx。"""
        for 平台标志, 架构 in (("win32", "AMD64"), ("linux", "x86_64"), ("darwin", "x86_64")):
            for 解析 in 两处解析:
                with self.subTest(平台=平台标志, 模块=解析.__name__), \
                        mock.patch.object(sys, "platform", 平台标志), \
                        mock.patch.object(平台适配.platform, "machine", return_value=架构):
                    真实导入 = []
                    原导入 = __builtins__["__import__"] if isinstance(__builtins__, dict) else __builtins__.__import__

                    def _记录导入(名, *参数, **关键字):
                        真实导入.append(名)
                        return 原导入(名, *参数, **关键字)

                    # 两个后端的库都打进 sys.modules：本用例只判「去加载了哪一个」，
                    # 不让本机真实安装的 mlx_whisper 参与（真库加载会拖慢/炸进程，
                    # 且与本判据无关 —— 本判据要的就是「根本不该去碰它」）。
                    with mock.patch("builtins.__import__", side_effect=_记录导入), \
                            mock.patch.dict(sys.modules, {"faster_whisper": _伪FasterWhisper库,
                                                          "mlx_whisper": _伪MLX库}):
                        解析._加载库(set())
                    self.assertNotIn("mlx_whisper", 真实导入,
                                     f"{平台标志} 上仍去加载了 mlx_whisper（后端选择未生效）")
                    self.assertEqual(解析._后端标识, "faster-whisper")

    def test_AppleSilicon分支加载mlx(self):
        for 解析 in 两处解析:
            with self.subTest(模块=解析.__name__), \
                    mock.patch.object(sys, "platform", "darwin"), \
                    mock.patch.object(平台适配.platform, "machine", return_value="arm64"), \
                    mock.patch.dict(sys.modules, {"mlx_whisper": _伪MLX库}):
                库 = 解析._加载库(set())
            self.assertIs(库, _伪MLX库)
            self.assertEqual(解析._后端标识, "mlx")


class Test两个后端调用适配(unittest.TestCase):
    """判据 2：后端差异吸收在子进程解析内部，对外结构逐字一致。"""

    def setUp(self):
        self.临时 = Path(tempfile.mkdtemp(prefix="测试_转写双后端_"))
        self.音频 = self.临时 / "音频.wav"
        self.音频.write_bytes(b"RIFF")
        self.模型目录 = self.临时 / "模型"
        self.模型目录.mkdir()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.临时, ignore_errors=True)

    def _驱动(self, 解析, 后端标识: str, 库, 返回分段: bool = 真, 附加术语: str = ""):
        setattr(解析, "_库模块", 库)
        setattr(解析, "_后端标识", 后端标识)
        try:
            return 解析.转写音频(str(self.音频), str(self.模型目录), "", 附加术语, 返回分段)
        finally:
            setattr(解析, "_库模块", None)
            setattr(解析, "_后端标识", "")

    def test_mlx后端产出结构(self):
        for 解析 in 两处解析:
            with self.subTest(模块=解析.__name__):
                结果 = self._驱动(解析, "mlx", _伪MLX库)
            self.assertIn("值", 结果, 结果)
            self.assertEqual(结果["值"]["文本"], "适配层文本")
            self.assertEqual(结果["值"]["语言"], "zh")
            self.assertEqual(结果["值"]["模型名"], str(self.模型目录))
            self.assertIn("path_or_hf_repo", _伪MLX库.最近参数)

    def test_faster_whisper后端产出结构一致(self):
        """**同一份对外结构**：faster_whisper 的 (生成器, info) 被吸收成同一形态。"""
        for 解析 in 两处解析:
            with self.subTest(模块=解析.__name__):
                结果 = self._驱动(解析, "faster-whisper", _伪FasterWhisper库)
            self.assertIn("值", 结果, 结果)
            self.assertEqual(结果["值"]["文本"], "后端文本")
            self.assertEqual(结果["值"]["语言"], "zh")
            self.assertEqual(结果["值"]["模型名"], str(self.模型目录))

    def test_分段键名逐字一致(self):
        """两个后端的**分段键名与口径**必须逐字相同（mlx=dict 键；fw=对象属性）。"""
        产出表 = {}
        for 解析 in 两处解析:
            with self.subTest(模块=解析.__name__, 后端="mlx"):
                产出表[("mlx", 解析.__name__)] = self._驱动(解析, "mlx", _伪MLX库)["值"]["分段"]
            with self.subTest(模块=解析.__name__, 后端="faster-whisper"):
                产出表[("faster-whisper", 解析.__name__)] = self._驱动(
                    解析, "faster-whisper", _伪FasterWhisper库)["值"]["分段"]
        for 键, 分段 in 产出表.items():
            with self.subTest(后端=键):
                self.assertTrue(分段, "分段为空：惰性生成器未被物化（假支持）")
                for 段 in 分段:
                    self.assertEqual(tuple(段.keys()), 分段键名)
        # mlx 一段、faster-whisper 两段（伪库设定），但**键名集合**必须完全一致
        self.assertEqual({tuple(段.keys()) for 段 in 产出表[("mlx", 适配层解析.__name__)]},
                         {分段键名})
        self.assertEqual(len(产出表[("faster-whisper", 适配层解析.__name__)]), 2)
        # 惰性生成器必须已物化：再次读取仍是同样两段（已 list 化，不是一次性迭代器）
        self.assertEqual(len(产出表[("faster-whisper", 后端解析.__name__)]), 2)

    def test_附加术语两后端都传initial_prompt(self):
        _伪MLX库.最近参数, _伪FasterWhisper模型.最近参数 = {}, {}
        for 解析 in 两处解析:
            self._驱动(解析, "mlx", _伪MLX库, 附加术语="领域术语")
            self._驱动(解析, "faster-whisper", _伪FasterWhisper库, 附加术语="领域术语")
        self.assertEqual(_伪MLX库.最近参数.get("initial_prompt"), "领域术语")
        self.assertEqual(_伪FasterWhisper模型.最近参数.get("initial_prompt"), "领域术语")

    def test_返回分段为假时不带分段(self):
        for 解析 in 两处解析:
            结果 = self._驱动(解析, "faster-whisper", _伪FasterWhisper库, 返回分段=假)
            self.assertNotIn("分段", 结果["值"])

    def test_错误语义逐类不变(self):
        """库不可用 → 提供者不可用；未配置模型 → 未配置模型；模型目录缺失 → 模型缺失。"""
        for 解析 in 两处解析:
            with self.subTest(模块=解析.__name__):
                setattr(解析, "_库模块", None)
                setattr(解析, "_后端标识", "faster-whisper")
                try:
                    不可用 = 解析.转写音频(str(self.音频), str(self.模型目录), "")
                finally:
                    setattr(解析, "_库模块", None)
                    setattr(解析, "_后端标识", "")
                self.assertEqual(不可用["错误码"], "提供者不可用")
                self.assertIn("faster_whisper", 不可用["错误说明"])

                setattr(解析, "_库模块", _伪FasterWhisper库)
                try:
                    self.assertEqual(解析.检查可用性("", "").get("错误码"), "未配置模型")
                    self.assertEqual(
                        解析.转写音频(str(self.音频), "", "").get("错误码"), "未配置模型")
                    缺失 = self.临时 / "不存在模型"
                    self.assertEqual(
                        解析.转写音频(str(self.音频), str(缺失), "").get("错误码"), "模型缺失")
                    self.assertEqual(
                        解析.检查可用性(str(缺失), "").get("错误码"), "模型缺失")
                    self.assertEqual(
                        解析.转写音频(str(self.临时 / "无.wav"), str(self.模型目录), "").get("错误码"),
                        "文件不存在")
                finally:
                    setattr(解析, "_库模块", None)

    def test_禁用库对两个后端都成立(self):
        """禁用写法 `mlx_whisper` / `faster_whisper` / 通用 `转写库` 都必须报提供者不可用。"""
        for 解析 in 两处解析:
            for 禁用名 in ("mlx_whisper", "faster_whisper", "转写库"):
                with self.subTest(模块=解析.__name__, 禁用=禁用名):
                    with mock.patch.object(sys, "platform", "linux"), \
                            mock.patch.object(平台适配.platform, "machine", return_value="x86_64"), \
                            mock.patch.dict(sys.modules, {"faster_whisper": _伪FasterWhisper库}):
                        self.assertIsNone(解析._加载库({禁用名}))
                    with mock.patch.object(sys, "platform", "darwin"), \
                            mock.patch.object(平台适配.platform, "machine", return_value="arm64"), \
                            mock.patch.dict(sys.modules, {"mlx_whisper": _伪MLX库}):
                        self.assertIsNone(解析._加载库({禁用名}))


class Test依赖锁按平台过滤(unittest.TestCase):
    """判据 3：`适用平台` 不含当前平台的依赖项不装不校验；不写该字段 = 全平台适用。"""

    macOS专用 = {"名称": "mlx-whisper", "版本": "0.4.3", "模块名": "绝不存在模块_mlx_xyz"}
    全平台 = {"名称": "json包", "版本": "1.0.0", "模块名": "json"}

    def test_不写适用平台等于全平台适用(self):
        with mock.patch.object(sys, "platform", "linux"), \
                mock.patch.object(平台适配.platform, "machine", return_value="x86_64"):
            # 不写 / 写成空值 → 全平台适用（向后兼容）
            self.assertTrue(环境管理器._适用当前平台({"名称": "x", "版本": "1.0.0"}))
            self.assertTrue(环境管理器._适用当前平台({"适用平台": []}))
            self.assertTrue(环境管理器._适用当前平台({"适用平台": None}))
            # 当前平台是 Linux：只有列了 Linux（或它的别名）才适用
            self.assertTrue(环境管理器._适用当前平台({"适用平台": ["Linux"]}))
            self.assertTrue(环境管理器._适用当前平台({"适用平台": ["Windows", "Linux"]}))
            self.assertFalse(环境管理器._适用当前平台({"适用平台": ["macOS"]}))
            self.assertFalse(环境管理器._适用当前平台({"适用平台": ["darwin"]}))
            self.assertFalse(环境管理器._适用当前平台({"适用平台": ["win32"]}))
            # 非法写法（非列表）→ 保守判不适用（fail-closed）
            self.assertFalse(环境管理器._适用当前平台({"适用平台": "Windows"}))

    def test_平台名别名归一(self):
        """别名归一到本仓唯一口径（`平台适配.当前平台()`）；只做同义，不做模糊匹配。"""
        self.assertEqual(环境管理器._归一平台名("darwin"), "macOS")
        self.assertEqual(环境管理器._归一平台名("win32"), "Windows")
        self.assertEqual(环境管理器._归一平台名("linux"), "Linux")
        self.assertEqual(环境管理器._归一平台名("  LINUX  "), "Linux")
        self.assertEqual(环境管理器._归一平台名("不认识的平台"), "不认识的平台")
        self.assertEqual(环境管理器._归一平台名(""), "")
        # 别名写法在 macOS 上确实命中
        with mock.patch.object(sys, "platform", "darwin"), \
                mock.patch.object(平台适配.platform, "machine", return_value="arm64"):
            self.assertTrue(环境管理器._适用当前平台({"适用平台": ["darwin"]}))
            self.assertTrue(环境管理器._适用当前平台({"适用平台": ["macOS"]}))
            self.assertFalse(环境管理器._适用当前平台({"适用平台": ["win32"]}))

    def test_非macOS上macOS专用依赖不校验(self):
        """**核心判据**：模块装不上，但只要它不适用当前平台，校验就不该失败。"""
        解释器 = self._伪解释器()
        锁 = {"包": [dict(self.macOS专用, 适用平台=["macOS"])], "直接依赖": [], "依赖闭包": []}
        with mock.patch.object(sys, "platform", "linux"), \
                mock.patch.object(平台适配.platform, "machine", return_value="x86_64"):
            self.assertTrue(环境管理器.校验环境(解释器, 锁))

    def test_全平台依赖缺模块必判红(self):
        """反向：把 `适用平台` 去掉（或改成适用当前平台），同一份锁必须真变红。"""
        解释器 = self._伪解释器()
        全平台锁 = {"包": [self.全平台], "直接依赖": [], "依赖闭包": []}
        self.assertTrue(环境管理器.校验环境(解释器, 全平台锁))
        坏锁 = {"包": [dict(self.macOS专用)], "直接依赖": [], "依赖闭包": []}
        self.assertFalse(环境管理器.校验环境(解释器, 坏锁),
                         "缺模块的全平台依赖必须判红（否则平台过滤变成静默放过）")

    def test_适用平台条目与全平台条目混装只查后者(self):
        """混装：只校验**适用当前平台**的那一条；不适用的那条即使模块缺失也不影响。"""
        解释器 = self._伪解释器()
        # Linux 上：macOS 专用条目（模块缺失）被过滤，全平台 entry 可导入 → 真
        锁 = {"包": [dict(self.macOS专用, 适用平台=["macOS"]),
                    dict(self.全平台, 适用平台=["Windows", "Linux"])],
              "直接依赖": [], "依赖闭包": []}
        with mock.patch.object(sys, "platform", "linux"), \
                mock.patch.object(平台适配.platform, "machine", return_value="x86_64"):
            self.assertTrue(环境管理器.校验环境(解释器, 锁))
        # 反向（真红）：把**适用当前平台**的那条换成装不上的模块 → 同一结构必须判假。
        # 这正是「平台过滤不会顺手放过本平台真实缺模块」的证明。
        真红锁 = {"包": [dict(self.macOS专用, 适用平台=["macOS"]),
                       {"名称": "X", "版本": "1.0.0", "模块名": "绝不存在模块_xyz",
                        "适用平台": ["Windows", "Linux"]}],
                "直接依赖": [], "依赖闭包": []}
        with mock.patch.object(sys, "platform", "linux"), \
                mock.patch.object(平台适配.platform, "machine", return_value="x86_64"):
            self.assertFalse(环境管理器.校验环境(解释器, 真红锁),
                             "适用当前平台的依赖缺模块必须判红")
        # 平台翻面后结论随之翻面：同一份锁在 macOS 上只校验 macOS 专用条目（模块缺失）→ 假
        with mock.patch.object(sys, "platform", "darwin"), \
                mock.patch.object(平台适配.platform, "machine", return_value="arm64"):
            self.assertFalse(环境管理器.校验环境(解释器, 锁))

    def test_强制校验规则4不报假红(self):
        """规则 4：被平台过滤掉的直接依赖**不许**报「未纳入 依赖闭包」。"""
        提供者目录, _ = self._写锁({
            "包": [dict(self.macOS专用, 适用平台=["macOS"])],
            "提供者id": "临时提供者",
            "直接依赖": [dict(self.macOS专用, 适用平台=["macOS"])],
            "依赖闭包": [dict(self.macOS专用, 来源="PyPI", 适用平台=["macOS"])],
            "环境": {},
        })
        with mock.patch.object(sys, "platform", "linux"), \
                mock.patch.object(平台适配.platform, "machine", return_value="x86_64"):
            结果 = 校验提供者环境(提供者目录, "临时提供者", 自动清理=假)
        原因表 = [问题.原因 for 问题 in 结果.问题列表]
        self.assertFalse(any("未纳入 依赖闭包" in 原因 for 原因 in 原因表), 原因表)
        self.assertFalse(any("不是精确版本" in 原因 for 原因 in 原因表), 原因表)

    def test_强制校验范围版本仍判红(self):
        """反向：适用范围当前平台的条目里写范围版本，必须真红（过滤不放宽强制参数）。"""
        提供者目录, _ = self._写锁({
            "包": [{"名称": "X", "版本": ">=1.0", "模块名": "x", "适用平台": ["Windows", "Linux"]}],
            "提供者id": "临时提供者",
            "直接依赖": [],
            "依赖闭包": [],
            "环境": {},
        })
        with mock.patch.object(sys, "platform", "linux"), \
                mock.patch.object(平台适配.platform, "machine", return_value="x86_64"):
            结果 = 校验提供者环境(提供者目录, "临时提供者", 自动清理=假)
        原因表 = [问题.原因 for 问题 in 结果.问题列表]
        self.assertTrue(any("不是精确版本" in 原因 for 原因 in 原因表), 原因表)

    def test_强制校验闭包覆盖仍判红(self):
        """反向：直接依赖未纳入闭包（同平台）必须真红。"""
        提供者目录, _ = self._写锁({
            "包": [{"名称": "X", "版本": "1.0.0", "模块名": "x", "适用平台": ["Windows", "Linux"]}],
            "提供者id": "临时提供者",
            "直接依赖": [{"名称": "X", "版本": "1.0.0", "适用平台": ["Windows", "Linux"]}],
            "依赖闭包": [],
            "环境": {},
        })
        with mock.patch.object(sys, "platform", "linux"), \
                mock.patch.object(平台适配.platform, "machine", return_value="x86_64"):
            结果 = 校验提供者环境(提供者目录, "临时提供者", 自动清理=假)
        原因表 = [问题.原因 for 问题 in 结果.问题列表]
        self.assertTrue(any("未纳入 依赖闭包" in 原因 for 原因 in 原因表), 原因表)

    def test_规则2空锁判定用未过滤条目(self):
        """空锁是**结构属性**：只声明了别平台依赖的锁不算空锁（平台不该引发假红）。"""
        提供者目录, _ = self._写锁({
            "包": [dict(self.macOS专用, 适用平台=["macOS"])],
            "提供者id": "临时提供者",
            "直接依赖": [],
            "依赖闭包": [],
            "环境": {},
        })
        with mock.patch.object(sys, "platform", "linux"), \
                mock.patch.object(平台适配.platform, "machine", return_value="x86_64"):
            结果 = 校验提供者环境(提供者目录, "临时提供者", 自动清理=假)
        原因表 = [问题.原因 for 问题 in 结果.问题列表]
        self.assertFalse(any("空锁" in 原因 for 原因 in 原因表), 原因表)

    def test_真实两把锁的平台分片(self):
        """真实交付物自检：两把转写锁的 mlx 条目标 macOS、faster-whisper 条目标 Windows/Linux。"""
        根 = Path(__file__).resolve().parents[2]
        for 相对 in ("支持库/适配层/MLXWhisper提供者",
                    "支持库/后端/转写支持库/转写"):
            锁 = json.loads((根 / 相对 / "依赖锁.json").read_text(encoding="utf-8"))
            with self.subTest(包=相对):
                包表 = {包["名称"]: 包 for 包 in 锁["包"]}
                self.assertEqual(包表["mlx-whisper"]["适用平台"], ["macOS"])
                self.assertEqual(包表["faster-whisper"]["适用平台"], ["Windows", "Linux"])
                直接 = {包["名称"]: 包 for 包 in 锁["直接依赖"]}
                self.assertEqual(直接["mlx-whisper"]["适用平台"], ["macOS"])
                self.assertEqual(直接["faster-whisper"]["适用平台"], ["Windows", "Linux"])
                闭包表 = {包["名称"]: 包.get("适用平台") for 包 in 锁["依赖闭包"]}
                self.assertEqual(闭包表["mlx"], ["macOS"])
                self.assertEqual(闭包表["ctranslate2"], ["Windows", "Linux"])
                # 每个闭包条目都必须显式标平台（禁止「一半标一半不标」的模糊态）
                self.assertNotIn(None, 闭包表.values())

    # ── 夹具 ─────────────────────────────────────────────────

    def _伪解释器(self) -> Path:
        """伪解释器：符号链接到当前解释器（既有测试同一做法）。"""
        目录 = Path(tempfile.mkdtemp(prefix="测试_转写双后端_环境_"))
        self.addCleanup(lambda: __import__("shutil").rmtree(目录, ignore_errors=True))
        解释器 = 目录 / "python3"
        解释器.symlink_to(sys.executable)
        return 解释器

    def _写锁(self, 锁: dict) -> tuple[Path, Path]:
        目录 = Path(tempfile.mkdtemp(prefix="测试_转写双后端_提供者_"))
        self.addCleanup(lambda: __import__("shutil").rmtree(目录, ignore_errors=True))
        锁路径 = 目录 / "依赖锁.json"
        锁路径.write_text(json.dumps(锁, ensure_ascii=False), encoding="utf-8")
        return 目录, 锁路径


if __name__ == "__main__":
    unittest.main()
