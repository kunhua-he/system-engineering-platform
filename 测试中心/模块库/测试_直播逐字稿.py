"""模块库.直播逐字稿 组合能力真实测试：经统一能力调用器走网关/注册表。

覆盖：参数校验、文件不存在、未配置模型如实返回（不伪造转写）、
读取项目状态（无状态文件）、检查可用性、注册能力按 能力定义.json 现读清单齐全、
主流程能力 全自动精校 的失败路径如实返回、模块公开入口可导入且返回统一结果。

测试装配：setUpClass 启动 后端核心 + 随机回环网关，走真实注册表
（媒体处理/媒体转写/转写支持库能力注册），直播逐字稿模块经
获取能力调用器 调用底层组合能力。

能力清单以 模块库/直播逐字稿/能力定义.json 为唯一事实源（现读，不写死元组：
写死元组曾漏掉主流程能力 全自动精校，导致它零覆盖）。
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

if str(Path(__file__).resolve().parents[2]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from 模块库.直播逐字稿 import 全自动精校, 检查可用性, 读取项目状态, 转写媒体文件, 注册能力
from 公共契约.基础类型.结果类型 import 结果 as 结果类型

环境变量模型路径 = "MLXWhisper提供者_模型路径"
环境变量模型名 = "MLXWhisper提供者_模型名"
环境变量名表 = [环境变量模型路径, 环境变量模型名]

能力定义文件 = Path(__file__).resolve().parents[2] / "模块库" / "直播逐字稿" / "能力定义.json"


def 读能力定义() -> dict:
    """现读本包 能力定义.json（能力清单的唯一事实源）。"""
    return json.loads(能力定义文件.read_text(encoding="utf-8"))


def 能力id清单() -> list[str]:
    """能力定义.json 声明的全部能力 id（升序；写死元组会漏新能力）。"""
    return sorted(str(条目.get("能力id") or "") for 条目 in 读能力定义().get("能力列表") or [])


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
    def test_能力定义清单非空且无重号(self):
        清单 = 能力id清单()
        self.assertTrue(清单, "能力定义.json 里必须声明能力")
        self.assertEqual(len(清单), len(set(清单)), "能力 id 不得重复")
        self.assertNotIn("", 清单, "能力 id 不得为空")
        for 能力id in 清单:
            self.assertTrue(能力id.startswith("直播逐字稿."), f"能力 id 命名不合包内口径: {能力id}")

    def test_公开入口可导入(self):
        for 能力id in 能力id清单():
            能力名 = 能力id.rsplit(".", 1)[-1]
            self.assertTrue(callable(globals().get(能力名)), f"{能力id} 未从公开入口导出")

    def test_注册能力齐全(self):
        from 公共契约.能力契约.契约 import 能力注册表
        注册表 = 能力注册表()
        注册能力(注册表)
        for 能力id in 能力id清单():
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
                return 结果类型.成功结果({"文本": "示例品牌", "语言": "zh"})
            raise AssertionError(f"出现未预期的能力调用: {能力id}")

        with patch.object(实现, "_调用", side_effect=假调用):
            结果 = 实现.转写媒体文件(
                self.音频路径,
                str(self.临时目录 / "输出"),
                模型配置={"模型路径": "/模型"},
                附加术语="示例品牌、示例门店",
            )

        self.assertTrue(结果.成功)
        self.assertEqual(len(记录), 1)
        self.assertEqual(记录[0][1]["附加术语"], "示例品牌、示例门店")


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


class Test全自动精校失败路径(直播逐字稿装配):
    """主流程能力 全自动精校 的失败路径：走 阶段0 入参校验与分片失败口径，不依赖真模型。

    真模型成功路径需要 MLX Whisper 模型与真实长音频，不在定向测试里跑；这里只钉死
    「失败必须如实报错误码、值必须为空」，防止 未配置模型/坏入参 被伪造成成功。
    """

    def test_源文件不存在(self):
        结果 = 全自动精校(str(self.临时目录 / "不存在.mp4"), str(self.临时目录 / "导出_1.txt"),
                        str(self.临时目录 / "缓存_1"), 1)
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "文件不存在")
        self.assertIsNone(结果.值)

    def test_源文件路径必须绝对路径(self):
        结果 = 全自动精校("相对/路径.mp4", str(self.临时目录 / "导出_2.txt"),
                        str(self.临时目录 / "缓存_2"), 1)
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "参数不合法")

    def test_不支持的媒体格式(self):
        笔记 = self.临时目录 / "笔记.txt"
        笔记.write_text("不是媒体\n", encoding="utf-8")
        结果 = 全自动精校(str(笔记), str(self.临时目录 / "导出_3.txt"),
                        str(self.临时目录 / "缓存_3"), 1)
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "不支持的媒体格式")

    def test_分片失败如实返回转写失败(self):
        """底稿为空/分片失败口径：有真实音频但未配置模型 → 转写失败，不伪造已精校。"""
        if not Path(self.音频路径).is_file():
            self.skipTest("无真实音频文件（ffmpeg 不可用或无夹具）")
        结果 = 全自动精校(self.音频路径, str(self.临时目录 / "导出_4.txt"),
                        str(self.临时目录 / "缓存_4"), 1)
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "转写失败")
        self.assertIn("未配置模型", 结果.错误说明)


class Test注册参数口径(直播逐字稿装配):
    """注册参数与 能力契约/参数契约.json 逐条相同，且 `注册能力` 体内可静态解析。

    「丢参」缺陷（2026-09-18）的回归护盾，两拍都钉死：
      第一拍（3893e0dd）：入口只抽「名称+类型」→ `必填` 被丢弃 → 网关
        `运行核心/统一网关/协议/类型规格.py` 判据 `项.get("必填") is 真` 判假 → 必填校验
        静默失效，少传参数落进实现体抛 TypeError，用户拿 HTTP 500 而非 400。
      第二拍（本次）：入口改成 `_参数声明(能力id, 参数名)` **函数内推导** → 参数表对
        `开发工具/契约编译/漂移检测.读取注册口径` 的 AST 读取器不可判定，本包 4 条能力
        全落「参数口径未解析」—— 门禁看不见就等于没有。
    改法：契约逐条镜像成 `注册能力` **函数体内**的字面量（`_参数契约表`），
    `参数=_参数契约表[能力id]` 按下标取。
    """

    def test_注册参数逐条镜像契约JSON不丢必填默认值(self):
        """真注册表里的参数项必须逐字等于契约原值（含 必填/默认值）。"""
        import json

        from 公共契约.能力契约.契约 import 能力注册表 as 注册表类

        契约 = json.loads(
            (Path(__file__).resolve().parents[2]
             / "模块库" / "直播逐字稿" / "能力契约" / "参数契约.json").read_text(encoding="utf-8"))
        契约参数表 = {条["能力id"]: [dict(参数) for 参数 in 条["参数"]]
                  for 条 in 契约["能力契约"]}
        注册表 = 注册表类()
        注册能力(注册表)
        self.assertEqual(sorted(注册表.能力id列表), sorted(契约参数表))
        for 能力id, 契约参数 in 契约参数表.items():
            在线实现 = 注册表.获取(能力id)
            self.assertIsNotNone(在线实现, f"{能力id} 未注册")
            assert 在线实现 is not None
            在线参数 = 在线实现.参数
            self.assertEqual([参数["名称"] for 参数 in 在线参数],
                             [参数["名称"] for 参数 in 契约参数],
                             f"{能力id} 注册参数名序与契约不一致")
            for 在线, 期望 in zip(在线参数, 契约参数):
                self.assertIn("必填", 在线, f"{能力id}.{期望['名称']} 注册项丢了 必填")
                self.assertIn("默认值", 在线, f"{能力id}.{期望['名称']} 注册项丢了 默认值")
                self.assertEqual(在线["必填"], 期望["必填"],
                                 f"{能力id}.{期望['名称']} 必填 与契约不一致")
                self.assertEqual(在线["默认值"], 期望["默认值"],
                                 f"{能力id}.{期望['名称']} 默认值 与契约不一致")
                # 契约没声明的键不得补（补出来的默认值就是第二套事实源）
                self.assertEqual(set(在线) - {"名称", "类型", "必填", "默认值"}, set(),
                                 f"{能力id}.{期望['名称']} 注册项多出契约未声明的键")

    def test_注册参数表在注册能力函数体内可静态解析(self):
        """`_参数契约表` 必须是 `注册能力` **函数体内的字面量**，且含 必填。

        改回「函数内推导」（旧形态）或挪到模块顶层，本用例即红：AST 读取器只收
        `注册能力` 函数体内的 `ast.List/ast.Dict` 字面量赋值（看 `_扫描注册语句`）。
        """
        import ast
        import inspect

        import 模块库.直播逐字稿 as 模块入口

        树 = ast.parse(inspect.getsource(模块入口.注册能力))
        # 用与漂移检测同一支 AST 静态求值：解不出即判「不可静态判定」，本用例红。
        from 开发工具.契约编译.漂移检测 import _静态字面量, 常量种子绑定, 未解析哨兵

        函数体 = 树.body[0].body if isinstance(树.body[0], ast.FunctionDef) else 树.body
        # 种子绑定与生产读取器同源（`常量种子绑定` 从 `_常量导入源` 派生）：
        # 本用例只解析 注册能力 的**函数体**，模块级 import 不在这棵树里，
        # 不播种子则中文 `真`/`假` 会落「未解析」（与生产侧同一坑，勿各写一份）。
        绑定: dict = dict(常量种子绑定())
        for 节点 in 函数体:
            if isinstance(节点, ast.Assign) and isinstance(节点.targets[0], ast.Name):
                绑定[节点.targets[0].id] = 节点.value
        self.assertIn("_参数契约表", 绑定, "`_参数契约表` 未写在 注册能力 函数体内")
        self.assertIn("_注册参数名序", 绑定, "`_注册参数名序` 未写在 注册能力 函数体内")
        契约表 = _静态字面量(绑定["_参数契约表"], 绑定)
        self.assertIsNot(契约表, 未解析哨兵,
                         "_参数契约表 静态解析不出（AST 门禁看不见 → 参数口径判未解析）")
        assert isinstance(契约表, dict)
        self.assertEqual(sorted(契约表), sorted([
            "直播逐字稿.转写媒体文件", "直播逐字稿.检查可用性",
            "直播逐字稿.读取项目状态", "直播逐字稿.全自动精校"]))
        for 能力id, 参数列表 in 契约表.items():
            self.assertTrue(参数列表, f"{能力id} 参数表为空")
            self.assertTrue(all("必填" in 参数 for 参数 in 参数列表),
                            f"{能力id} 参数表有项不含 必填（AST 门禁读不到必填口径）")
            self.assertTrue(all("默认值" in 参数 for 参数 in 参数列表),
                            f"{能力id} 参数表有项不含 默认值")

    def test_漂移检测读到的参数口径与契约一致(self):
        """端到端：哨门禁 `读取注册口径` 抽出的参数必须含 必填/默认值 且等于契约。"""
        import json

        from 开发工具.契约编译.漂移检测 import 读取契约口径, 读取注册口径

        包目录 = Path(__file__).resolve().parents[2] / "模块库" / "直播逐字稿"
        注册 = 读取注册口径(包目录 / "__init__.py")
        契约 = 读取契约口径(包目录 / "能力契约" / "参数契约.json")
        self.assertEqual(sorted(注册), sorted(契约))
        for 能力id, 契约项 in 契约.items():
            注册参数 = 注册[能力id]["参数"]
            self.assertIsNotNone(
                注册参数, f"{能力id} 参数口径未解析（注册处不是函数体内字面量）")
            assert 注册参数 is not None
            self.assertEqual([项["名称"] for 项 in 注册参数],
                             [项["名称"] for 项 in 契约项["参数"]], f"{能力id} 名序不一致")
            for 注册项, 契约项参数 in zip(注册参数, 契约项["参数"]):
                self.assertIn("必填", 注册项, f"{能力id}.{注册项['名称']} 必填 读不到")
                self.assertIn("默认值", 注册项, f"{能力id}.{注册项['名称']} 默认值 读不到")
                self.assertEqual(注册项["必填"], 契约项参数["必填"])
                self.assertEqual(注册项["类型"], 契约项参数["类型"])
                self.assertEqual(注册项["默认值"], 契约项参数.get("默认值"))
        # 契约 JSON 未被本次改动带上（注册侧只是镜像，原值不动）
        self.assertEqual(
            契约["直播逐字稿.转写媒体文件"]["参数"][2]["默认值"], 300)
        self.assertEqual(
            契约["直播逐字稿.全自动精校"]["参数"][8]["默认值"], 3600.0)
        json.loads((包目录 / "能力契约" / "参数契约.json").read_text(encoding="utf-8"))

    def test_网关按注册参数拦下缺必填参数(self):
        """真注册表 → 网关唯一校验点：缺必填即 400 文案，不落进实现体抛 TypeError。"""
        from 公共契约.能力契约.契约 import 能力注册表 as 注册表类
        from 运行核心.统一网关.协议.类型规格 import 校验能力参数

        注册表 = 注册表类()
        注册能力(注册表)
        精校实现 = 注册表.获取("直播逐字稿.全自动精校")
        self.assertIsNotNone(精校实现)
        assert 精校实现 is not None
        缺少必填 = 校验能力参数("直播逐字稿.全自动精校", 精校实现.参数, {})
        self.assertTrue(缺少必填.startswith(
            "参数不合法：能力 直播逐字稿.全自动精校 缺少必填参数 源文件路径"),
            f"缺必填文案前缀变了：{缺少必填}（实现会追加「（本能力参数…）」清单，故只钉前缀，不钉全串）")
        全给 = 校验能力参数(
            "直播逐字稿.全自动精校", 精校实现.参数,
            {"源文件路径": "/abs/录制.mp4", "导出路径": "/abs/出稿.md",
             "缓存目录": "/abs/缓存", "模式": 1, "分片秒数": 300,
             "附加术语": "", "超时秒": 3600.0, "输出结构": "", "附加要求": ""})
        self.assertEqual(全给, "", f"参数齐全却被判不合法: {全给}")

    def test_名序闸门对错名序抛错(self):
        """装配期闸门必须真的拦：注册名序 ≠ 契约名序即 raise（不静默漏参）。"""
        import 模块库.直播逐字稿 as 模块入口

        契约表 = {"直播逐字稿.检查可用性": [
            {"名称": "超时秒"}, {"名称": "配置"}]}
        with self.assertRaises(ValueError):
            模块入口._校验参数名序(契约表, {"直播逐字稿.检查可用性": ["配置", "超时秒"]})
        with self.assertRaises(ValueError):
            模块入口._校验参数名序(契约表, {})   # 有契约但注册处未声明名序
        # 正确名序不抛（反向对照：闸门不是恒抛）
        self.assertIsNone(
            模块入口._校验参数名序(契约表, {"直播逐字稿.检查可用性": ["超时秒", "配置"]}))


if __name__ == "__main__":
    unittest.main()
