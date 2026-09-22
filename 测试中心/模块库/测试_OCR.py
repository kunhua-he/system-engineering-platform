"""OCR 模块迁移测试（unittest）。

setUpClass 启动真实后端与本地回环网关并装配 HTTP连接器，模块公开能力
全部经真实 HTTP 网关调用；保留模块层参数校验、连接器级透传/错误码语义、
平台不可用降级与真实 tesseract 最小调用等既有用例。
覆盖：公开入口/注册对称、参数错误（模块层校验）、平台不可用（提供者不可用）、
中文结果对称与调用边界（取消令牌id 语义下支持库侧不传 callable）、
错误码透传、可用性检查组合、真实 tesseract 最小调用。
"""

from __future__ import annotations

import base64
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

系统根 = Path(__file__).resolve().parents[2]
if str(系统根) not in sys.path:
    sys.path.insert(0, str(系统根))

from 公共契约.基础类型.结果类型 import 结果
from 模块库.OCR import 注册能力
from 模块库.OCR import 可用性检查
from 模块库.OCR import 识别图片文件
from 模块库.OCR import 识别图片文字
from 后端核心.后端核心 import 后端核心
from 运行核心.统一网关.网关核心 import 网关核心
from 运行核心.统一网关.本地网关 import 本地网关服务器
from 运行核心.能力调用.HTTP连接器 import HTTP连接器

测试文本 = "OCR 12345"

def _工具可用() -> bool:
    import shutil as 壳工具
    return 壳工具.which("tesseract") is not None

class 假连接器:
    """测试注入的假 HTTP 连接器：记录调用并返回预设结果。"""

    def __init__(self, 预设结果):
        self.预设结果 = 预设结果
        self.调用历史: list[tuple[str, dict]] = []

    def 调用能力(self, 能力id, 参数=None, **关键字):
        self.调用历史.append((能力id, dict(参数 or {})))
        return self.预设结果

class TestOCR模块(unittest.TestCase):
    """OCR 模块迁移测试：装配 HTTP连接器后经真实网关调用边界验证。"""

    @classmethod
    def setUpClass(cls):
        """启动真实后端与随机回环网关，所有测试请求走 HTTP。"""
        cls.后端 = 后端核心()
        启动结果 = cls.后端.启动()
        if not 启动结果.成功:
            raise RuntimeError(f"后端核心启动失败: {启动结果.错误说明}")
        cls.网关 = 本地网关服务器(
            网关核心实例=网关核心(cls.后端), 地址="127.0.0.1", 端口=0,
            配置={"请求超时秒": 1800, "要求凭证": False, "禁止客户端身份": False},
        )
        成功, 说明 = cls.网关.启动()
        if not 成功:
            cls.后端.优雅关闭()
            raise RuntimeError(f"网关启动失败: {说明}")

    @classmethod
    def tearDownClass(cls):
        cls.网关.优雅停止()
        cls.后端.优雅关闭()

    def setUp(self):
        from 支持库.适配层.Pillow提供者 import 生成占位图

        self.临时目录 = tempfile.mkdtemp(prefix="测试_OCR模块_")
        占位 = 生成占位图(宽度=900, 高度=200, 占位类型="文本",
                       背景颜色="#FFFFFF", 前景颜色="#000000", 文本=测试文本)
        self.assertTrue(占位.成功, f"生成占位图失败: {占位.错误说明}")
        self.图片字节 = base64.b64decode(占位.值["图像b64"])
        self.图片路径 = str(Path(self.临时目录) / "测试.png")
        Path(self.图片路径).write_bytes(self.图片字节)

    def tearDown(self):
        shutil.rmtree(self.临时目录, ignore_errors=True)

    # ── 公开入口与注册对称 ──────────────────────────────

    def test_公开入口可导入与注册能力齐全(self):
        for 能力名 in ["识别图片文字", "识别图片文件", "可用性检查"]:
            self.assertTrue(callable(globals()[能力名]), f"{能力名} 未从公开入口导出")
        from 公共契约.能力契约.契约 import 能力注册表 as 注册表类

        注册表 = 注册表类()
        注册能力(注册表)
        for 能力id in ["OCR.识别图片文字", "OCR.识别图片文件", "OCR.可用性检查"]:
            self.assertIn(能力id, 注册表.能力id列表)

    # ── 注册参数口径（2026-09-18 两拍缺陷的回归护盾）────────

    def test_注册参数逐条镜像契约JSON不丢必填默认值(self):
        """注册参数项必须逐字等于 能力契约/参数契约.json 的原值（含 必填/默认值）。

        这是「丢参」缺陷的正面判据：入口一旦只抽 名称+类型（第一拍形态）或改回
        函数内推导（第二拍形态），本用例即红。
        """
        import json

        from 公共契约.能力契约.契约 import 能力注册表 as 注册表类

        契约 = json.loads(
            (Path(__file__).resolve().parents[2]
             / "模块库" / "OCR" / "能力契约" / "参数契约.json").read_text(encoding="utf-8"))
        契约参数表 = {条["能力id"]: [dict(参数) for 参数 in 条["参数"]]
                  for 条 in 契约["能力契约"]}
        注册表 = 注册表类()
        注册能力(注册表)
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
        """`_参数契约表` 必须是 `注册能力` **函数体内的字面量**，且含 必填 键。

        为什么要有它：`开发工具/契约编译/漂移检测` 的 AST 读取器只收 `注册能力`
        函数体内的 `ast.List/ast.Dict` 字面量赋值。参数表一旦改成「函数内推导」
        （`_参数声明(能力id, …)`）或「运行时读 JSON」，本包三条能力的参数口径就
        全判「未解析」——门禁看不见 = 等于没有（判据是 AST 能否解出含 必填 的整条参数）。
        """
        import ast
        import inspect

        import 模块库.OCR as 模块入口

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
        # 2026-09-23 判据唯一化③：本包原先那份「镜像 vs 名序」同文件自比
        # （`_注册参数名序` + `_校验参数名序()`）已删除——两份输入同一次手写产生，
        # 一起写错即恒绿。名序/返回口径的唯一判据在装配期闸门
        # （`运行核心/加载器/生命周期管理/管理器.装配系统` → `能力注册表.校验声明一致`）。
        self.assertNotIn("_注册参数名序", 绑定,
                         "自比拷贝 `_注册参数名序` 已随判据唯一化删除，不得回潮")
        契约表 = _静态字面量(绑定["_参数契约表"], 绑定)
        self.assertIsNot(契约表, 未解析哨兵,
                         "_参数契约表 静态解析不出（AST 门禁看不见 → 参数口径判未解析）")
        assert isinstance(契约表, dict)
        self.assertEqual(sorted(契约表),
                         sorted(["OCR.可用性检查", "OCR.识别图片文字", "OCR.识别图片文件"]))
        for 能力id, 参数列表 in 契约表.items():
            self.assertTrue(参数列表, f"{能力id} 参数表为空")
            self.assertTrue(all("必填" in 参数 for 参数 in 参数列表),
                            f"{能力id} 参数表有项不含 必填（AST 门禁读不到必填口径）")
            self.assertTrue(all("默认值" in 参数 for 参数 in 参数列表),
                            f"{能力id} 参数表有项不含 默认值")

    def test_网关按注册参数拦下缺必填参数(self):
        """真注册表 → 网关唯一校验点：缺必填即 400 文案，不落进实现体抛 TypeError。

        这是「500 改回 400」的回归护盾：注册项一旦丢 必填，网关 `项.get("必填") is 真`
        判假、必填校验静默失效，用户拿到的是 HTTP 500 而不是干净的 400。
        """
        from 公共契约.能力契约.契约 import 能力注册表 as 注册表类
        from 运行核心.统一网关.协议.类型规格 import 校验能力参数

        注册表 = 注册表类()
        注册能力(注册表)
        图片文件实现 = 注册表.获取("OCR.识别图片文件")
        self.assertIsNotNone(图片文件实现)
        assert 图片文件实现 is not None
        缺少必填 = 校验能力参数("OCR.识别图片文件", 图片文件实现.参数, {})
        self.assertTrue(缺少必填.startswith(
            "参数不合法：能力 OCR.识别图片文件 缺少必填参数 图片路径"),
            f"缺必填文案前缀变了：{缺少必填}（实现会追加「（本能力参数…）」清单，故只钉前缀，不钉全串）")
        全给 = 校验能力参数(
            "OCR.识别图片文件", 图片文件实现.参数,
            {"图片路径": self.图片路径, "语言": "eng", "词级数据": False, "超时秒": 60.0})
        self.assertEqual(全给, "", f"参数齐全却被判不合法: {全给}")

    # ── 参数错误（模块层校验，不触达支持库）─────────────

    def test_路径字节同时给参数不合法(self):
        结果 = 识别图片文字(图片路径=self.图片路径, 图片字节=self.图片字节)
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "参数不合法")

    def test_路径字节都缺参数不合法(self):
        结果 = 识别图片文字()
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "参数不合法")

    def test_识别图片文件空路径参数不合法(self):
        结果 = 识别图片文件(图片路径="")
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "参数不合法")

    # ── 平台不可用 ──────────────────────────────────────

    def test_平台不可用提供者不可用(self):
        """卸载调用器后调用能力：模块返回 提供者不可用，不抛异常。

        2026-09-19（开工-20260919-193541-2a8e）：模块实现改走
        `获取能力调用器()`，不再有 `_获取连接器` 桩可 mock；改按真实装配卸载 +
        停用惰性钩子（同 测试_唯一注册表调用器.py 姿势）。
        """
        原惰性装配 = _停用惰性装配()
        try:
            结果 = 识别图片文字(图片路径=self.图片路径)
            self.assertFalse(结果.成功)
            self.assertEqual(结果.错误码, "提供者不可用")
        finally:
            _恢复惰性装配(原惰性装配)

    def test_平台不可用时返回提供者不可用(self):
        """卸载调用器后调用能力：模块返回 提供者不可用，不抛异常。

        2026-09-19（开工-20260919-193541-2a8e）：模块不再自持连接器；要测
        「不可用」须同时停用惰性装配钩子，否则下次获取会把调用器装回来。
        """
        原惰性装配 = _停用惰性装配()
        try:
            结果 = 识别图片文字(图片路径=self.图片路径)
            self.assertFalse(结果.成功)
            self.assertEqual(结果.错误码, "提供者不可用")
        finally:
            _恢复惰性装配(原惰性装配)

    # ── 中文结果对称与调用边界 ─────────────────────────

    def test_中文结果对称经连接器透传(self):
        from 模块库.OCR.实现 import OCR as 模块实现

        中文结果 = 结果.成功结果({"文本": "中文识别结果"})
        连接器 = 假连接器(中文结果)
        设置假连接器(模块实现, 连接器)
        try:
            返回值 = 模块实现.识别图片文字(图片路径=self.图片路径)
        finally:
            设置假连接器(模块实现, None)
        self.assertTrue(返回值.成功)
        self.assertEqual(返回值.值, {"文本": "中文识别结果"})
        能力id, 请求参数 = 连接器.调用历史[0]
        self.assertEqual(能力id, "OCR识别支持库.OCR识别.识别图片")
        self.assertEqual(请求参数["图片路径"], self.图片路径)
        self.assertNotIn(
            "取消事件", 请求参数,
            "取消令牌id 语义下支持库侧不得传 callable；且 取消事件 是资源引用型"
            "（threading.Event），JSON 表达不了，HTTP 请求参数里连键都不能有")

    def test_取消令牌id透传且支持库侧无callable(self):
        from 模块库.OCR.实现 import OCR as 模块实现

        连接器 = 假连接器(结果.成功结果({"文本": "识别结果"}))
        设置假连接器(模块实现, 连接器)
        try:
            模块实现.识别图片文字(图片路径=self.图片路径, 取消令牌id="令牌1")
        finally:
            设置假连接器(模块实现, None)
        能力id, 请求参数 = 连接器.调用历史[0]
        self.assertEqual(能力id, "OCR识别支持库.OCR识别.识别图片")
        self.assertNotIn("取消事件", 请求参数)

    def test_错误码透传(self):
        from 模块库.OCR.实现 import OCR as 模块实现

        连接器 = 假连接器(结果.失败("超时", "执行超时", 可重试=True))
        设置假连接器(模块实现, 连接器)
        try:
            调用结果 = 模块实现.识别图片文字(图片路径=self.图片路径)
        finally:
            设置假连接器(模块实现, None)
        self.assertFalse(调用结果.成功)
        self.assertEqual(调用结果.错误码, "超时")
        self.assertTrue(调用结果.可重试)

    def test_可用性检查组合两个支持库能力(self):
        from 模块库.OCR.实现 import OCR as 模块实现

        连接器 = 假连接器(结果.成功结果({
            "tesseract": "tesseract", "版本": "5.3.0", "满足最低版本": True,
        }))
        设置假连接器(模块实现, 连接器)
        try:
            检查结果 = 模块实现.可用性检查()
        finally:
            设置假连接器(模块实现, None)
        self.assertTrue(检查结果.成功)
        self.assertEqual(检查结果.值["tesseract"], "tesseract")
        调用能力id表 = [历史[0] for 历史 in 连接器.调用历史]
        self.assertEqual(调用能力id表, ["OCR识别支持库.OCR识别.版本探针", "OCR识别支持库.OCR识别.语言包列表"])

    # ── 真实 tesseract 最小调用（经 HTTP 网关）───────────

    @unittest.skipUnless(_工具可用(), "本机未配置 tesseract，如实跳过")
    def test_真实识别路径入口(self):
        结果 = 识别图片文字(图片路径=self.图片路径)
        self.assertTrue(结果.成功, f"识别失败: {结果.错误码} {结果.错误说明}")
        self.assertIn("12345", 结果.值["文本"])

    @unittest.skipUnless(_工具可用(), "本机未配置 tesseract，如实跳过")
    def test_真实识别字节入口(self):
        结果 = 识别图片文字(图片字节=self.图片字节)
        self.assertTrue(结果.成功, f"识别失败: {结果.错误码} {结果.错误说明}")
        self.assertIn("OCR", 结果.值["文本"])

    @unittest.skipUnless(_工具可用(), "本机未配置 tesseract，如实跳过")
    def test_真实词级数据(self):
        结果 = 识别图片文字(图片路径=self.图片路径, 词级数据=True)
        self.assertTrue(结果.成功, f"词级识别失败: {结果.错误码} {结果.错误说明}")
        词列表 = 结果.值["词列表"]
        self.assertGreater(len(词列表), 0)
        词文本 = [词["文本"] for 词 in 词列表]
        self.assertTrue(any("12345" in 词 for 词 in 词文本), f"未识别出目标词: {词文本}")

    @unittest.skipUnless(_工具可用(), "本机未配置 tesseract，如实跳过")
    def test_真实识别图片文件入口(self):
        结果 = 识别图片文件(图片路径=self.图片路径)
        self.assertTrue(结果.成功, f"识别失败: {结果.错误码} {结果.错误说明}")
        self.assertIn("12345", 结果.值["文本"])

    @unittest.skipUnless(_工具可用(), "本机未配置 tesseract，如实跳过")
    def test_真实可用性检查(self):
        结果 = 可用性检查()
        self.assertTrue(结果.成功, f"可用性检查失败: {结果.错误码} {结果.错误说明}")
        值 = 结果.值
        self.assertTrue(值["版本"])
        self.assertTrue(值["满足最低版本"])
        self.assertIn("eng", 值["语言列表"])
        self.assertGreater(值["语言数量"], 0)

    @unittest.skipUnless(_工具可用(), "本机未配置 tesseract，如实跳过")
    def test_真实语言包缺失语义(self):
        结果 = 识别图片文字(图片路径=self.图片路径, 语言="xx_不存在")
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "语言包缺失")

    @unittest.skipUnless(_工具可用(), "本机未配置 tesseract，如实跳过")
    def test_真实文件不存在(self):
        结果 = 识别图片文字(图片路径="/不存在的路径/图片.png")
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "文件不存在")


def _停用惰性装配():
    """停用惰性装配钩子并卸下调用器，返回原钩子（供「调用器不可用」用例使用）。

    2026-09-19（开工-20260919-193541-2a8e）：模块不再自持 `设置HTTP连接器`，
    只经 `获取能力调用器()` 取注入调用器。卸载调用器后若不**同时**停用惰性装配
    钩子，下一次获取会触发惰性装配把调用器装回来 —— 用例就测不到「不可用」分支。
    """
    from 公共契约.能力契约.调用器 import 设置惰性装配函数, 注册能力调用器
    原惰性装配 = 设置惰性装配函数.__globals__.get("_惰性装配函数")
    设置惰性装配函数(None)
    注册能力调用器(None)
    return 原惰性装配


def _恢复惰性装配(原惰性装配) -> None:
    """还原惰性装配钩子并重新装配（后续用例不受影响）。"""
    from 公共契约.能力契约.调用器 import 设置惰性装配函数
    from 运行核心.能力调用.唯一能力调用 import 创建并绑定
    设置惰性装配函数(原惰性装配)
    创建并绑定()


def 设置假连接器(模块实现, 连接器) -> None:
    """把假连接器注入模块实现的唯一调用通道（None 表示卸下）。

    2026-09-19（开工-20260919-193541-2a8e）：模块实现经
    `获取能力调用器()` 取调用器，不再自持 `设置HTTP连接器`（该入口已按
    「断第二条腿」删除）。本辅助经 `注册能力调用器` 注入假连接器，用于验证
    参数透传、错误码透传与可用性检查的组合调用。
    """
    from 公共契约.能力契约.调用器 import 注册能力调用器
    注册能力调用器(连接器)

if __name__ == "__main__":
    unittest.main()
