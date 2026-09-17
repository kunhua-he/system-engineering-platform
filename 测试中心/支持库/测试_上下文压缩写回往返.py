"""B-01 回归：压缩写回键名错配导致「压缩一触发就静默清空整段会话历史」。

真实调用链与错配点（外部审计 B-01，本测试钉死）：
    上下文压缩.压缩会话(句柄, 会话id)
      → _从会话存储读取()  中文键 角色/内容[正文] → 英文键 role/content（读时转换，对的）
      → 压缩历史()          产出英文键 {"role","content"}
      → 会话存储.写入压缩结果()  原先只用中文键 消息.get("角色","助手") / 消息.get("内容",{})
         ⇒ 两个键全取不到 ⇒ 先 DELETE 掉整段原消息，再插入「角色全助手 + 内容全 {}」的壳行，
           而且返回「成功」：整段对话历史永久丢失且无任何报错。

本测试只断言一件事：**读 → 压 → 写 → 读 往返后内容不丢**。
反向验证：把 会话存储.写入压缩结果 里的 _归一角色/_归一内容 换回单侧中文键取值，
本测试必须变红（角色全同一 + 正文全空），未变红即回归失效。
"""
from __future__ import annotations

import json
import os
import tempfile
import unittest

from 支持库.后端.大语言模型支持库.会话存储 import (
    连接会话存储, 释放句柄, 创建会话, 追加消息, 读取历史, 写入压缩结果,
)
from 支持库.后端.大语言模型支持库.上下文压缩 import 压缩历史, 四阶段压缩, 估算消息token数
from 支持库.后端.大语言模型支持库.上下文压缩.实现.上下文压缩 import 压缩会话

正文前缀 = "第{}条真实正文-"


class 压缩写回往返用例(unittest.TestCase):
    """公共夹具：临时库（绝不碰真库）+ 12 条带正文的用户/助手交替消息。"""

    def setUp(self) -> None:
        self.临时目录 = tempfile.TemporaryDirectory(prefix="b01_压缩往返_")
        self.addCleanup(self.临时目录.cleanup)
        连接 = 连接会话存储(库路径=os.path.join(self.临时目录.name, "会话存储.db"))
        self.assertTrue(连接.成功, f"连接会话存储失败: {连接.错误说明}")
        self.句柄 = 连接.值["句柄"]
        self.addCleanup(释放句柄, self.句柄)
        会话 = 创建会话(句柄=self.句柄, 用户id="华哥", 模型名="测试模型", 标题="B-01回归")
        self.assertTrue(会话.成功, f"创建会话失败: {会话.错误说明}")
        self.会话id = 会话.值["会话id"]
        # 原文：{序号: (角色, 正文)}，正文带可辨识前缀，便于逐条对齐
        self.原文: dict[int, tuple[str, str]] = {}
        for 序号 in range(1, 13):
            角色 = "用户" if 序号 % 2 == 1 else "助手"
            正文 = f"{正文前缀.format(序号)}{'文' * 40}{序号}"
            self.原文[序号] = (角色, 正文)
            加 = 追加消息(句柄=self.句柄, 会话id=self.会话id, 角色=角色, 内容={"正文": 正文})
            self.assertTrue(加.成功, f"追加第 {序号} 条失败: {加.错误说明}")

    def _读回(self) -> list[dict]:
        读回 = 读取历史(句柄=self.句柄, 会话id=self.会话id)
        self.assertTrue(读回.成功, f"读取历史失败: {读回.错误说明}")
        return 读回.值["消息列表"]

    def _取正文(self, 行: dict) -> str:
        内容 = 行.get("内容")
        if isinstance(内容, dict):
            return str(内容.get("正文", ""))
        return str(内容 or "")


class 测试读压写读往返不丢内容(压缩写回往返用例):

    def test_压缩会话往返后正文逐条对齐且角色不全同一(self) -> None:
        """核心回归：压缩触发后，保留区正文必须逐条与原文一致，角色必须出现多种。"""
        压缩 = 压缩会话(句柄=self.句柄, 会话id=self.会话id, 压缩阈值=200)
        self.assertTrue(压缩.成功, f"压缩会话失败: {压缩.错误说明}")
        self.assertTrue(压缩.值["已压缩"], f"阈值 200 未触发压缩: {压缩.值}")
        self.assertEqual(压缩.值["压缩次数"], 1)

        消息列表 = self._读回()
        self.assertTrue(消息列表, "压缩写回后消息表被清空")

        # ① 摘要消息（首条）正文不得为空，且必须收进了被压缩的早期正文
        首条正文 = self._取正文(消息列表[0])
        self.assertTrue(首条正文.strip(), "摘要消息正文为空（写回把内容写成了 {}）")
        self.assertIn("[历史摘要]", 首条正文)
        self.assertIn(正文前缀.format(1), 首条正文)

        # ② 保留区正文逐条对齐原文（默认保留最近 10 条 ⇒ 序号 3..12）
        保留区 = 消息列表[1:]
        self.assertEqual(len(保留区), 10, f"保留区条数应为本 10 条，实为 {len(保留区)}")
        for 行, 期望序号 in zip(保留区, range(3, 13)):
            期望角色, 期望正文 = self.原文[期望序号]
            self.assertEqual(self._取正文(行), 期望正文,
                             f"序号 {期望序号} 正文不丢才对：实际 {json.dumps(行.get('内容'), ensure_ascii=False)}")
            self.assertEqual(行["角色"], 期望角色, f"序号 {期望序号} 角色应为 {期望角色}")
            self.assertTrue(行.get("来源"), "来源不得为空")

        # ③ 角色不得全为同一个（B-01 病灶特征：全「助手」）
        角色集合 = {行["角色"] for 行 in 消息列表}
        self.assertGreater(len(角色集合), 1, f"角色全为同一个：{角色集合}")
        self.assertNotEqual(角色集合, {"助手"}, f"角色全回落为「助手」：{角色集合}")
        self.assertEqual(角色集合, {"系统", "用户", "助手"})

        # ④ 一条空内容都不许有
        空内容数 = sum(1 for 行 in 消息列表 if not self._取正文(行).strip())
        self.assertEqual(空内容数, 0, f"写回后仍有 {空内容数} 条空正文")

    def test_压缩会话未超阈值时不写回不丢数据(self) -> None:
        """未触发压缩时读回原文原样（防止「写回」误伤）。"""
        写回前 = self._读回()
        压缩 = 压缩会话(句柄=self.句柄, 会话id=self.会话id, 压缩阈值=100000)
        self.assertTrue(压缩.成功, f"压缩会话失败: {压缩.错误说明}")
        self.assertFalse(压缩.值["已压缩"])
        self.assertEqual(压缩.值["压缩次数"], None)
        写回后 = self._读回()
        self.assertEqual(len(写回后), len(写回前))
        for 行, 期望序号 in zip(写回后, range(1, 13)):
            期望角色, 期望正文 = self.原文[期望序号]
            self.assertEqual(行["角色"], 期望角色)
            self.assertEqual(self._取正文(行), 期望正文)


class 测试写入压缩结果双键归一(unittest.TestCase):
    """写侧单点回归：英文键消息必须能落库（上游 压缩历史 产出的就是英文键）。"""

    def setUp(self) -> None:
        self.临时目录 = tempfile.TemporaryDirectory(prefix="b01_双键_")
        self.addCleanup(self.临时目录.cleanup)
        连接 = 连接会话存储(库路径=os.path.join(self.临时目录.name, "会话存储.db"))
        self.assertTrue(连接.成功, 连接.错误说明)
        self.句柄 = 连接.值["句柄"]
        self.addCleanup(释放句柄, self.句柄)
        会话 = 创建会话(句柄=self.句柄, 用户id="华哥", 标题="B-01双键")
        self.assertTrue(会话.成功, 会话.错误说明)
        self.会话id = 会话.值["会话id"]

    def _读回(self) -> list[dict]:
        读回 = 读取历史(句柄=self.句柄, 会话id=self.会话id)
        self.assertTrue(读回.成功, 读回.错误说明)
        return 读回.值["消息列表"]

    def test_英文键消息落库后角色与正文都对(self) -> None:
        """上游 压缩历史 真实产出口径：{"role","content"}。"""
        写回 = 写入压缩结果(句柄=self.句柄, 会话id=self.会话id, 压缩后消息列表=[
            {"role": "system", "content": "[历史摘要] 早期内容"},
            {"role": "user", "content": "用户正文"},
            {"role": "assistant", "content": "助手正文"},
        ])
        self.assertTrue(写回.成功, f"写入压缩结果失败: {写回.错误说明}")
        self.assertEqual(写回.值["写入消息数"], 3)
        消息列表 = self._读回()
        self.assertEqual([行["角色"] for 行 in 消息列表], ["系统", "用户", "助手"])
        self.assertEqual([行["内容"] for 行 in 消息列表],
                         [{"正文": "[历史摘要] 早期内容"}, {"正文": "用户正文"}, {"正文": "助手正文"}])
        self.assertEqual([行["序号"] for 行 in 消息列表], [1, 2, 3])
        # 读取侧口径（上下文压缩._从会话存储读取）必须还能取回正文
        self.assertEqual([行["内容"].get("正文") for 行 in 消息列表],
                         ["[历史摘要] 早期内容", "用户正文", "助手正文"])

    def test_中文键消息落库不回归(self) -> None:
        """本库既有对外口径（验证场景.json：角色=压缩摘要 + 内容={正文}）必须照旧可用。"""
        写回 = 写入压缩结果(句柄=self.句柄, 会话id=self.会话id, 压缩后消息列表=[
            {"角色": "压缩摘要", "内容": {"正文": "摘要"}},
            {"角色": "用户", "内容": {"正文": "用户正文"}},
        ])
        self.assertTrue(写回.成功, f"写入压缩结果失败: {写回.错误说明}")
        消息列表 = self._读回()
        self.assertEqual([行["角色"] for 行 in 消息列表], ["压缩摘要", "用户"])
        self.assertEqual([行["内容"] for 行 in 消息列表],
                         [{"正文": "摘要"}, {"正文": "用户正文"}])
        self.assertEqual([行["来源"] for 行 in 消息列表], ["压缩摘要", "用户"])

    def test_中文键优先且内容取非字典型时包成正文(self) -> None:
        """双键同时缺失/内容为纯文本时不得落成空壳：取不到内容才回落 {}。"""
        写回 = 写入压缩结果(句柄=self.句柄, 会话id=self.会话id, 压缩后消息列表=[
            {"角色": "用户", "内容": "纯文本内容"},
            {"角色": "助手"},
        ])
        self.assertTrue(写回.成功, f"写入压缩结果失败: {写回.错误说明}")
        消息列表 = self._读回()
        self.assertEqual(消息列表[0]["内容"], {"正文": "纯文本内容"})
        self.assertEqual(消息列表[1]["内容"], {})
        self.assertEqual([行["角色"] for 行 in 消息列表], ["用户", "助手"])


class 测试中文键消息不丢内容(unittest.TestCase):
    """B-01 同类（同域内）：会话存储口径的「角色/内容[正文]」消息进上下文压缩入口不得丢正文。

    病灶：只认英文键 content 时，中文键消息被判定为「空消息」，在四阶段压缩的无模型剪枝
    阶段整批剪掉（保留消息 0、摘要空），且 压缩历史 会产出只有角色名的空壳摘要。
    """

    英文键列表 = [{"role": "user" if i % 2 else "assistant", "content": f"第{i}条正文{'文' * 30}"}
                  for i in range(1, 13)]
    中文键列表 = [{"角色": "用户" if i % 2 else "助手", "内容": {"正文": f"第{i}条正文{'文' * 30}"}}
                  for i in range(1, 13)]

    def test_压缩历史认中文键并产出含正文的摘要(self) -> None:
        中文 = 压缩历史(消息列表=self.中文键列表, 压缩阈值=200)
        self.assertTrue(中文.成功, 中文.错误说明)
        self.assertTrue(中文.值["已压缩"])
        摘要 = 中文.值["摘要"]
        self.assertIn("第1条正文", 摘要, f"中文键早期正文未进摘要：{摘要!r}")
        self.assertIn("第2条正文", 摘要)
        self.assertNotEqual(摘要.strip(), "user: \nassistant:", "摘要只剩角色名、正文全空")
        self.assertEqual(len(中文.值["消息列表"]), 11)
        self.assertEqual(中文.值["消息列表"][0]["role"], "system")

    def test_四阶段压缩中文键不被当成空消息剪掉(self) -> None:
        中文 = 四阶段压缩(消息列表=self.中文键列表, 可用额度token=100000)
        self.assertTrue(中文.成功, 中文.错误说明)
        self.assertEqual(len(中文.值["保留消息"]), len(self.中文键列表),
                         "中文键消息被误判为空消息整批剪掉（静默清空）")
        self.assertEqual(中文.值["已压缩条数"], 0)

    def test_估算消息token数中英键口径一致(self) -> None:
        英 = 估算消息token数(self.英文键列表)
        中 = 估算消息token数(self.中文键列表)
        self.assertTrue(英.成功 and 中.成功)
        self.assertEqual(中.值["token数"], 英.值["token数"], "中文键正文没被计入 token")
        self.assertGreater(中.值["token数"], 0)


if __name__ == "__main__":
    unittest.main()
