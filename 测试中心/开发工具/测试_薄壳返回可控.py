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

    def test_字典超限深缩叶子且容器永不丢(self):
        # 2026-09-21 批 1（B1）改口径：字典**不再丢尾键**，改为递归缩字符串叶子 ——
        # 丢整键会让字段凭空消失，调用方连「少了什么」都不知道。
        原 = {"甲": "x" * 300, "乙": "y" * 300, "丙": "z" * 300}
        值, 说明 = 壳._裁剪值(原, 400, None)
        self.assertTrue(说明["已裁剪"])
        self.assertEqual(list(原), list(值), "容器永不丢：三个键必须都在，键序也不变")
        self.assertNotIn("丢弃说明", 说明, "缩叶子够装下时不得退到丢键")
        self.assertIn("截断说明", 说明)

    def test_说明随上限收缩但保底事实不丢(self):
        # 说明自己也占预算 ⇒ 上限小时说明必须更短，但**保底事实不得丢**；
        # 更不能像旧实现那样「说明不参与计算、裁完反而更超」。
        原 = {"甲": "x" * 300, "乙": "y" * 300, "丙": "z" * 300}
        大, 大说明 = 壳._裁剪值(原, 400, None)
        self.assertIn("截断说明", 大说明)
        self.assertIn("提示", 大说明, "上限够大时说明要完整")
        小, 小说明 = 壳._裁剪值(原, 200, None)
        self.assertIn("裁剪后字符数", 小说明, "保底事实不得丢")
        self.assertLess(len(json.dumps(小说明, ensure_ascii=False)),
                        len(json.dumps(大说明, ensure_ascii=False)), "上限更小 ⇒ 说明必须更短")

    def test_裁剪后含说明不超上限(self):
        # 硬承诺（批 1 新增判据）：值 + 裁剪说明的 JSON 字符数之和 ≤ 上限。
        # 旧实现里说明不参与计算 ⇒ 裁完反而更超（实测 52 > 50、20 > 5），注释却自称硬承诺。
        for 上限 in (50, 200, 600, 6000):
            值, 说明 = 壳._裁剪值({"甲": "x" * 5000, "乙": ["y" * 3000] * 20}, 上限, None)
            总 = len(json.dumps(值, ensure_ascii=False)) + len(json.dumps(说明, ensure_ascii=False))
            self.assertLessEqual(总, 上限, f"上限 {上限}：值+说明 = {总}，超限了")

    def test_键或条目太多才退到丢键且如实说明(self):
        值, 说明 = 壳._裁剪值({f"k{i}": "v" * 200 for i in range(200)}, 300, None)
        self.assertIn("丢弃说明", 说明, "退到最后手段必须如实说明")
        self.assertLessEqual(说明["裁剪后字符数"], 300)

    def test_列表超限先缩叶子_缩不动才截尾(self):
        值, 说明 = 壳._裁剪值(["x" * 50] * 20, 200, None)
        self.assertTrue(说明["已裁剪"])
        self.assertLessEqual(说明["裁剪后字符数"], 200)

    def test_长文本头尾各半截断并标出标记(self):
        值, 说明 = 壳._裁剪值("a" * 5000, 100, None)
        self.assertIn("truncated", 值, "截断处必须有标记（头尾各半，不是拦腰切）")
        self.assertTrue(值.startswith("a") and 值.endswith("a"), "头尾都要留")
        总 = len(json.dumps(值, ensure_ascii=False)) + len(json.dumps(说明, ensure_ascii=False))
        self.assertLessEqual(总, 100)

    def test_上限零表示不限(self):
        原 = {"a": "x" * 100000}
        值, 说明 = 壳._裁剪值(原, 0, None)
        self.assertEqual(原, 值)
        self.assertIsNone(说明)

    def test_不可序列化值不抛异常(self):
        # 上限小到装不下「值 + 说明」时**必须如实回带 `未能压到限内`**，不假装达标 ——
        # 旧实现的错正是「自称是硬承诺，实测裁完更超」。
        值, 说明 = 壳._裁剪值(object(), 10, None)
        self.assertTrue(说明["已裁剪"])
        self.assertIn("未能压到限内", 说明)

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
        self.assertEqual(["调用能力", "热接入", "健康检查", "能力详情"], list(壳.薄壳允许操作))

    def test_能力详情按能力id转发且不塞项目根(self):
        # A2c（2026-09-21 批 1）：让薄壳够得到权威落盘契约面。
        # 与「调用能力」的区别：它是网关操作（允许字段表 = {"能力id"}），不认 `项目根`，
        # 故不得被自动补位塞进 `参数`（塞了只是噪声，还会误导读者以为它接受该参数）。
        结果, 记录 = self._调({"操作": "能力详情", "能力id": "文件管理.读取文件",
                            "项目根": str(系统根)})
        self.assertTrue(结果["成功"], 结果)
        self.assertEqual("能力详情", 记录[0]["操作"])
        self.assertEqual("文件管理.读取文件", 记录[0]["能力id"])
        self.assertEqual({}, 记录[0]["参数"], "能力详情 不得被补位注入 项目根")

    def test_能力详情缺能力id仍被拒且不转发(self):
        结果, 记录 = self._调({"操作": "能力详情", "项目根": str(系统根)})
        self.assertFalse(结果["成功"])
        self.assertEqual([], 记录)


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


_值预算行 = "    值预算 = max(1, 上限字符 - 预算)\n"


class 深裁反向验证(unittest.TestCase):
    """反向验证：把「说明也占预算」退回旧口径（说明不参与上限计算），承诺判据必须变红。

    没有这层，「值 + 说明 ≤ 上限」这条承诺可能在**任何**实现下都绿 —— 等于没证明
    这道预算真的在起作用（旧实现正是这样：注释自称硬承诺，实测 52 > 50）。
    """

    def _缺陷态模块(self):
        源 = _薄壳源路径.read_text(encoding="utf-8")
        坏 = 源.replace(_值预算行, "    值预算 = 上限字符  # 反向样本：退回旧口径（说明不参与上限计算）\n")
        if 坏 == 源:
            raise AssertionError("值预算行未命中，反向样本失效（判据需更新）")
        命名空间: dict = {"__name__": "反向样本_深裁", "__file__": str(_薄壳源路径)}
        exec(compile(坏, str(_薄壳源路径), "exec"), 命名空间)  # noqa: S102
        return 命名空间

    def test_退回旧口径后承诺判据变红(self):
        入参 = {"甲": "x" * 5000, "乙": ["y" * 3000] * 20}
        上限 = 6000
        模块 = self._缺陷态模块()
        缺陷值, 缺陷说明 = 模块["_裁剪值"](入参, 上限, None)
        缺陷总 = (len(json.dumps(缺陷值, ensure_ascii=False))
                + len(json.dumps(缺陷说明, ensure_ascii=False)))
        self.assertGreater(缺陷总, 上限, "缺陷态下必须真的超限（这正是坏行为）")
        # 现行实现同一输入必须达标 —— 两者结论不同，样本才有效
        现值, 现说明 = 壳._裁剪值(入参, 上限, None)
        现行总 = (len(json.dumps(现值, ensure_ascii=False))
                + len(json.dumps(现说明, ensure_ascii=False)))
        self.assertLessEqual(现行总, 上限, "现行实现必须达标")
        self.assertNotEqual(缺陷总 > 上限, 现行总 > 上限,
                          "反向样本与现行实现的结论必须不同，否则样本失效")


if __name__ == "__main__":
    unittest.main(verbosity=1)
