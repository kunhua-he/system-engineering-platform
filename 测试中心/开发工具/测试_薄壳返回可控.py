"""薄壳返回可控 + 精准搜索：定向测试（不依赖网关，纯本地逻辑）。

为什么单独写：薄壳原先没有任何测试模块，它长期偏离（写死 限制=20、不暴露 细节级别）
就是因为没人锁住它的对外形状。本文件锁两件事：
  ① 工具清单必须暴露「精准搜索三件套」（限制/细节级别/游标）与「返回控制两件套」（返回上限字符/值字段）；
  ② `_裁剪值` 的行为：投影优先、结构化裁剪、**必留说明**（绝不静默截断）。
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

系统根 = Path(__file__).resolve().parents[2]
薄壳目录 = 系统根 / "开发工具" / "薄壳"
for 路径 in (str(系统根), str(薄壳目录)):
    if 路径 not in sys.path:
        sys.path.insert(0, 路径)

import 薄壳服务 as 壳
import 工具清单 as 清单


def _取工具(协议名: str):
    for 工具 in 清单.三个工具定义:
        if 工具.name == 协议名:
            return 工具
    raise AssertionError(f"工具清单缺少 {协议名}")


class 工具形状测试(unittest.TestCase):
    def test_检索暴露精准三件套(self):
        属性 = _取工具("capability_search").inputSchema["properties"]
        for 名 in ("关键词", "限制", "细节级别", "游标", "项目根"):
            self.assertIn(名, 属性, f"检索工具未暴露 {名}")
        self.assertEqual(["名称", "名称+说明", "完整契约"], 属性["细节级别"]["enum"])
        self.assertEqual(壳.默认检索条数, 10, "默认检索条数应已从写死的 20 收到 10")

    def test_调用暴露返回控制两件套(self):
        属性 = _取工具("capability_call").inputSchema["properties"]
        for 名 in ("能力id", "参数", "返回上限字符", "值字段", "项目根"):
            self.assertIn(名, 属性, f"调用工具未暴露 {名}")
        self.assertEqual("array", 属性["值字段"]["type"])

    def test_工具数仍是三个(self):
        self.assertEqual(3, len(清单.三个工具定义), "薄壳工具数不得增加（仍是薄壳）")


class 裁剪测试(unittest.TestCase):
    def test_小返回不动且不留噪声(self):
        值, 说明 = 壳._裁剪值({"a": 1}, 6000, None)
        self.assertEqual({"a": 1}, 值)
        self.assertIsNone(说明, "未裁剪时不得回带说明（避免每轮都灌噪声）")

    def test_字段投影优先于裁剪(self):
        # 大字段没被要，小字段被要 —— 不该因为大字段而丢掉小字段
        值, 说明 = 壳._裁剪值({"小": "x", "大": "y" * 5000}, 100, ["小"])
        self.assertEqual({"小": "x"}, 值)
        self.assertEqual(["小"], 说明["保留字段"])
        self.assertNotIn("已裁剪", 说明, "投影后已在限内，不算裁剪")

    def test_字段缺失如实回报(self):
        值, 说明 = 壳._裁剪值({"a": 1}, 6000, ["a", "不存在"])
        self.assertEqual({"a": 1}, 值)
        self.assertEqual(["不存在"], 说明["字段不存在"])

    def test_字典超限丢尾键并列出丢弃项(self):
        值, 说明 = 壳._裁剪值({"甲": "x" * 100, "乙": "y" * 100, "丙": "z" * 100}, 200, None)
        self.assertTrue(说明["已裁剪"])
        self.assertIn("丢弃字段", 说明)
        self.assertTrue(说明["丢弃字段"], "必须列出丢了哪些键")
        self.assertLessEqual(说明["裁剪后字符数"], 200)
        self.assertIn("提示", 说明, "必须告诉调用方怎么拿全")

    def test_列表超限截尾并报数量(self):
        值, 说明 = 壳._裁剪值(["x" * 50] * 20, 200, None)
        self.assertTrue(说明["已裁剪"])
        self.assertIn("列表截断", 说明)
        self.assertLess(len(值), 20)

    def test_长文本截断(self):
        值, 说明 = 壳._裁剪值("a" * 5000, 100, None)
        self.assertEqual(100, len(值))
        self.assertIn("文本截断", 说明)

    def test_上限零表示不限(self):
        原 = {"a": "x" * 100000}
        值, 说明 = 壳._裁剪值(原, 0, None)
        self.assertEqual(原, 值)
        self.assertIsNone(说明)

    def test_不可序列化值不抛异常(self):
        值, 说明 = 壳._裁剪值(object(), 10, None)
        self.assertTrue(说明["已裁剪"])

    def test_值字段非数组时不生效但如实说明(self):
        值, 说明 = 壳._裁剪值({"a": 1}, 6000, "不是数组")
        self.assertEqual({"a": 1}, 值)
        self.assertIn("值字段未生效", 说明)


class 非法参数测试(unittest.TestCase):
    def _桩转发(self, 记录表):
        def 假转发(请求体):
            记录表.append(请求体)
            return {"HTTP状态码": 200, "信封": {"成功": True, "值": {"ok": 1}}, "错误码": "", "错误说明": ""}
        return 假转发

    def test_非法细节级别被拒且不转发(self):
        记录: list = []
        原 = 壳.转发
        壳.转发 = self._桩转发(记录)
        try:
            结果 = 壳._查询能力({"关键词": "x", "细节级别": "瞎写", "项目根": str(系统根)})
        finally:
            壳.转发 = 原
        self.assertFalse(结果["成功"])
        self.assertEqual([], 记录, "非法参数不得发起转发")

    def test_细节级别与游标原样透传(self):
        记录: list = []
        原 = 壳.转发
        壳.转发 = self._桩转发(记录)
        try:
            壳._查询能力({"关键词": "x", "细节级别": "完整契约", "游标": "abc",
                        "限制": 7, "项目根": str(系统根)})
        finally:
            壳.转发 = 原
        参数 = 记录[0]["参数"]
        self.assertEqual("完整契约", 参数["细节级别"])
        self.assertEqual("abc", 参数["游标"])
        self.assertEqual(7, 参数["限制"])

    def test_未传细节级别不塞默认值(self):
        记录: list = []
        原 = 壳.转发
        壳.转发 = self._桩转发(记录)
        try:
            壳._查询能力({"关键词": "x", "项目根": str(系统根)})
        finally:
            壳.转发 = 原
        参数 = 记录[0]["参数"]
        self.assertNotIn("细节级别", 参数, "薄壳不得替能力塞默认档（那是改写调用语义）")
        self.assertNotIn("游标", 参数)
        self.assertEqual(壳.默认检索条数, 参数["限制"])

    def test_调用侧默认裁剪生效(self):
        记录: list = []
        def 大返回(请求体):
            return {"HTTP状态码": 200, "信封": {"成功": True, "值": {"大": "x" * 20000}},
                    "错误码": "", "错误说明": ""}
        原 = 壳.转发
        壳.转发 = 大返回
        try:
            结果 = 壳._调用能力({"能力id": "某能力", "参数": {}, "项目根": str(系统根)})
        finally:
            壳.转发 = 原
        self.assertIn(壳.值裁剪键, 结果, "超限必须回带裁剪说明")
        self.assertTrue(结果[壳.值裁剪键]["已裁剪"])
        self.assertLess(len(json.dumps(结果["值"], ensure_ascii=False)), 20000)

    def test_非法返回上限被拒(self):
        结果 = 壳._调用能力({"能力id": "某能力", "返回上限字符": "不是数字", "项目根": str(系统根)})
        self.assertFalse(结果["成功"])


class 项目根自动补位测试(unittest.TestCase):
    """`参数` 里没给 `项目根` 时，薄壳自动补顶层那个（2026-09-21）。

    治的是「本该一次成功的调用被迫多次探索」：顶层 `项目根` 是本工具自己的身份校验参数，
    能力自己的 `项目根` 是能力入参，两者同名不同层 —— 此前必须手抄第二遍，实测连传 4 次
    错才开通工。补位安全的两条前提：① 平台把 `项目根` 一律定义为仓库根绝对路径（4 个声明
    它为必填的能力说明全一致）；② 网关对未知参数一律忽略，故对未声明它的能力注入也无害。
    """

    def _桩转发(self, 记录表):
        def 假转发(请求体):
            记录表.append(请求体)
            return {"HTTP状态码": 200, "信封": {"成功": True, "值": {"ok": 1}}, "错误码": "", "错误说明": ""}
        return 假转发

    def _调(self, 参数):
        记录: list = []
        原 = 壳.转发
        壳.转发 = self._桩转发(记录)
        try:
            结果 = 壳._调用能力(参数)
        finally:
            壳.转发 = 原
        return 结果, 记录

    def test_参数里没给项目根时自动补位(self):
        根 = str(系统根)
        结果, 记录 = self._调({"能力id": "开工编排.开工准备", "参数": {"任务": "x"}, "项目根": 根})
        self.assertTrue(结果["成功"], 结果)
        self.assertEqual(根, 记录[0]["参数"]["项目根"], "能力自己的 项目根 必须被自动补上")

    def test_调用方显式给了就以调用方为准(self):
        结果, 记录 = self._调({"能力id": "某能力", "参数": {"项目根": "/显式给的"},
                            "项目根": str(系统根)})
        self.assertTrue(结果["成功"], 结果)
        self.assertEqual("/显式给的", 记录[0]["参数"]["项目根"], "不得覆盖调用方显式值")

    def test_补位不污染调用方字典(self):
        入参 = {"任务": "x"}
        self._调({"能力id": "某能力", "参数": 入参, "项目根": str(系统根)})
        self.assertNotIn("项目根", 入参, "不得原地改调用方的 参数 对象")

    def test_顶层项目根不合法时仍被拒且不转发(self):
        结果, 记录 = self._调({"能力id": "某能力", "参数": {}})
        self.assertFalse(结果["成功"])
        self.assertEqual([], 记录, "顶层项目根不合法不得发起转发")

    def test_其余入参原样透传不被改写(self):
        结果, 记录 = self._调({"能力id": "某能力", "参数": {"任务": "x", "额外": [1, 2]},
                            "项目根": str(系统根)})
        参数 = 记录[0]["参数"]
        self.assertEqual("x", 参数["任务"])
        self.assertEqual([1, 2], 参数["额外"], "除 项目根 补位外不得改写任何入参")


class 网关操作转发测试(unittest.TestCase):
    """薄壳转发 `热接入` / `健康检查` 两个网关操作（2026-09-21）。

    为什么：改完能力要让网关重新装配，官方口径是**热接入而不是重启**（决策记录 0008）。
    但 `热接入` 只是 `/网关/调用` 上的另一个 `操作`，薄壳此前把 `操作` 写死成 `调用能力`
    ⇒ Agent 拿不到它，只能回终端 `launchctl kickstart` + `curl` 轮询（本轮实测踩到）。
    本类锁三件事：① 这两个操作能一次调用转发出去；② 表外操作 **fail-closed 不转发**；
    ③ `调用能力` 的既有形状一字不变（默认操作、能力id 必填）。
    """

    def _调(self, 参数):
        记录: list = []

        def 假转发(请求体):
            记录.append(请求体)
            return {"HTTP状态码": 200, "信封": {"成功": True, "值": {"ok": 1}},
                    "错误码": "", "错误说明": ""}

        原 = 壳.转发
        壳.转发 = 假转发
        try:
            结果 = 壳._调用能力(参数)
        finally:
            壳.转发 = 原
        return 结果, 记录

    def test_热接入不带能力id也转发(self):
        结果, 记录 = self._调({"操作": "热接入", "项目根": str(系统根)})
        self.assertTrue(结果["成功"], 结果)
        self.assertEqual({"操作": "热接入"}, 记录[0], "热接入 的请求体只能是 操作 一个键")
        self.assertIn("操作=热接入", 结果["转发"], "回执必须写明实际操作，便于核对")

    def test_健康检查同样转发(self):
        结果, 记录 = self._调({"操作": "健康检查", "项目根": str(系统根)})
        self.assertTrue(结果["成功"], 结果)
        self.assertEqual({"操作": "健康检查"}, 记录[0])

    def test_表外操作被拒且不转发(self):
        # 两种输入都要拒：**带 能力id 的那种才真正考的是白名单** ——
        # 不带 能力id 时就算拆掉白名单也会因为「缺能力id」被拒（反向验证实测），
        # 只测那种输入等于用别的闸门冒充白名单。
        for 参数 in ({"操作": "重启网关", "项目根": str(系统根)},
                    {"操作": "重启网关", "能力id": "某能力", "参数": {},
                     "项目根": str(系统根)}):
            结果, 记录 = self._调(参数)
            self.assertFalse(结果["成功"], f"{参数} 应当被拒")
            self.assertEqual("参数不合法", 结果["错误码"])
            self.assertEqual([], 记录, "白名单 fail-closed：表外操作一个字节都不许转发")

    def test_热接入不接受参数(self):
        # 网关侧 允许字段表 把 热接入 声明为 set()：多带字段会被静默忽略，
        # 静默忽略会让调用方以为参数生效了 —— 故薄壳在边界直接拒绝，不装作接受。
        结果, 记录 = self._调({"操作": "热接入", "参数": {"a": 1}, "项目根": str(系统根)})
        self.assertFalse(结果["成功"])
        self.assertEqual("参数不合法", 结果["错误码"])
        self.assertEqual([], 记录)

    def test_默认操作仍是调用能力(self):
        结果, 记录 = self._调({"能力id": "某能力", "参数": {"任务": "x"}, "项目根": str(系统根)})
        self.assertTrue(结果["成功"], 结果)
        self.assertEqual("调用能力", 记录[0]["操作"])
        self.assertEqual("某能力", 记录[0]["能力id"])

    def test_调用能力仍要求能力id(self):
        结果, 记录 = self._调({"参数": {}, "项目根": str(系统根)})
        self.assertFalse(结果["成功"])
        self.assertEqual("参数不合法", 结果["错误码"])
        self.assertEqual([], 记录)

    def test_工具清单暴露操作白名单且不再把能力id列为必填(self):
        模式 = _取工具("capability_call").inputSchema
        self.assertEqual(list(壳.薄壳允许操作), 模式["properties"]["操作"]["enum"],
                         "工具清单的操作枚举必须与薄壳白名单同源，不得各写一份")
        self.assertEqual(["项目根"], 模式["required"],
                         "能力id 只在 操作=调用能力 时必填，故不得留在 schema 必填里")
        self.assertEqual(["调用能力", "热接入", "健康检查"], list(壳.薄壳允许操作))


_薄壳源路径 = 薄壳目录 / "薄壳服务.py"
_白名单闸门 = "    if 操作 not in 薄壳允许操作:\n"


class 白名单反向验证(unittest.TestCase):
    """反向验证：拆掉操作白名单闸门后，「表外操作被拒且不转发」必须变红。

    没有这层，那条用例可能在「任何操作都照转」的实现下照样绿 —— 等于没证明这道闸门在起作用。
    """

    def _缺陷态模块(self):
        源 = _薄壳源路径.read_text(encoding="utf-8")
        坏 = 源.replace(_白名单闸门, "    if False:\n")
        if 坏 == 源:
            raise AssertionError("操作白名单闸门片段未命中，反向样本失效（判据需更新）")
        命名空间: dict = {"__name__": "反向样本_薄壳", "__file__": str(_薄壳源路径)}
        exec(compile(坏, str(_薄壳源路径), "exec"), 命名空间)  # noqa: S102
        return 命名空间

    def test_拆掉白名单后表外操作会被转发出去(self):
        模块 = self._缺陷态模块()
        记录: list = []

        def 假转发(请求体):
            记录.append(请求体)
            return {"HTTP状态码": 200, "信封": {"成功": True, "值": {"ok": 1}},
                    "错误码": "", "错误说明": ""}

        模块["转发"] = 假转发
        # 反向样本必须**带 能力id**：不带时拆掉白名单也会因「缺能力id」被拒，
        # 那是另一道闸门在兜（实测踩过），会得到假绿样本。
        入参 = {"操作": "重启网关", "能力id": "某能力", "参数": {}, "项目根": str(系统根)}
        缺陷态 = 模块["_调用能力"](dict(入参))
        self.assertTrue(缺陷态["成功"], "缺陷态下必须真的把表外操作转发出去（这正是坏行为）")
        self.assertEqual("重启网关", 记录[0]["操作"])
        # 现行实现同一输入必须被拒 —— 两者结论不同，样本才有效
        记录.clear()
        原 = 壳.转发
        壳.转发 = 假转发
        try:
            现行态 = 壳._调用能力(dict(入参))
        finally:
            壳.转发 = 原
        self.assertNotEqual(缺陷态["成功"], 现行态["成功"],
                          "反向样本与现行实现的结论必须不同，否则样本失效")
        self.assertFalse(现行态["成功"])
        self.assertEqual([], 记录, "现行实现不得转发表外操作")


if __name__ == "__main__":
    unittest.main(verbosity=1)
