"""第十四阶段 P1-02 调用Agent视图测试：稳定四操作全部真实行为。

- 搜索能力返回紧凑摘要（不含实现路径/源码/契约指纹）；
- 查看能力返回含能力id/参数/错误码集的结构化契约；
- 验证可用对已注册提供者返回可用，对未登记能力返回不可用及原因；
- 调用能力真实返回 42；未登记能力返回 CAPABILITY_NOT_FOUND + 建议操作；
- 四操作统一结果结构（成功/错误码/消息/可重试）。
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

系统根 = Path(__file__).resolve().parents[2]
if str(系统根) not in sys.path:
    sys.path.insert(0, str(系统根))

from 公共契约.基础类型.逻辑类型 import 真, 假
from 平台控制面.统一入口 import 统一能力服务
from 开发工具.统一能力入口.视图.调用Agent视图 import 调用Agent视图


def 完整预算() -> dict:
    return {"内存上限": 100, "线程上限": 4, "子进程上限": 1, "并发调用上限": 4,
            "队列长度": 10, "文件句柄上限": 50, "临时空间上限": 100,
            "单次调用超时": 5, "每分钟重启次数": 2, "空闲回收时间": 60}


class Test调用Agent视图(unittest.TestCase):
    """调用Agent视图：注册身份 → 引导授予 调用Agent → 切换角色 → 真实四操作。"""

    def setUp(self):
        self.目录 = Path(tempfile.mkdtemp(prefix="视图02测试_"))
        self.服务 = 统一能力服务(self.目录)
        self.视图 = 调用Agent视图(self.服务)
        self.令牌 = self.服务.授权.注册身份(身份id="调用Agent1")
        成功, 消息 = self.服务.授权.引导授予(
            身份id="调用Agent1", 角色="调用Agent", 授予者="系统引导")
        self.assertTrue(成功, 消息)
        成功, 消息 = self.服务.授权.切换角色(self.令牌, "调用Agent")
        self.assertTrue(成功, 消息)
        # 登记能力：契约（指纹）+ 契约详情（资源字段，普通用户视图同款约定）
        self.能力id = "计算.返回答案"
        契约 = {"能力id": self.能力id, "名称": "返回答案",
                "参数": [{"名称": "问题", "类型": "文本", "必填": 假, "说明": "任意问题"}],
                "返回": {"类型": "整数"}, "错误码": ["CALL_FAILED"],
                "副作用": "无", "资源类型": "计算", "宿主": "本地", "权限": "调用Agent"}
        详情 = {"名称": "返回答案",
                "参数": [{"名称": "问题", "类型": "文本", "必填": 假, "说明": "任意问题"}],
                "返回": {"类型": "整数", "说明": "固定答案42"},
                "错误码": ["CALL_FAILED"], "副作用": "无", "资源类型": "计算",
                "宿主": "本地", "权限": "调用Agent", "兼容范围": "1.x",
                "调用示例": "调用能力(能力id='计算.返回答案', 参数={'问题': '?'})"}
        成功, 消息 = self.服务.目录.登记能力(
            能力id=self.能力id, 契约=契约, 组件="计算", 领域="计算", 资源=详情)
        self.assertTrue(成功, 消息)
        # 注册真实提供者：真实返回 42（非桩）
        成功, 消息 = self.服务.注册提供者(
            能力id=self.能力id, 函数=lambda: 42, 预算=完整预算())
        self.assertTrue(成功, 消息)

    def test_搜索能力返回紧凑摘要(self):
        结果 = self.视图.搜索能力(令牌=self.令牌, 关键词="计算", 限制=10)
        self.assertTrue(结果["成功"])
        self.assertGreaterEqual(结果["数量"], 1)
        摘要 = 结果["结果表"][0]
        self.assertEqual(摘要["能力id"], self.能力id)
        for 键 in ("能力id", "中文名称", "一句话作用", "成熟度", "可用状态"):
            self.assertIn(键, 摘要, f"紧凑摘要必须含 {键}")
        self.assertEqual(摘要["成熟度"], "实验")
        self.assertEqual(摘要["可用状态"], "可用", "已注册提供者摘要状态必须为可用")
        # 紧凑：不得返回实现细节（契约指纹/源码/物理路径）
        正文 = json.dumps(结果, ensure_ascii=False)
        self.assertNotIn("契约指纹", 正文)
        self.assertNotIn("def ", 正文)
        self.assertNotIn(".py", 正文)

    def test_查看能力返回结构化契约(self):
        结果 = self.视图.查看能力(令牌=self.令牌, 能力id=self.能力id)
        self.assertTrue(结果["成功"])
        契约 = 结果["契约"]
        self.assertEqual(契约["能力id"], self.能力id)
        self.assertEqual(契约["版本"], "1")
        self.assertEqual(契约["参数"][0]["名称"], "问题")
        self.assertEqual(契约["参数"][0]["类型"], "文本")
        self.assertEqual(契约["参数"][0]["必填"], 假)
        self.assertEqual(契约["返回结构"]["类型"], "整数")
        self.assertIn("CALL_FAILED", 契约["错误码集"])
        self.assertIn("调用Agent", 契约["权限要求"])
        self.assertEqual(契约["宿主"], "本地")
        self.assertTrue(契约["调用示例"])

    def test_验证可用已注册可用_未登记不可用(self):
        结果 = self.视图.验证可用(令牌=self.令牌, 能力id=self.能力id)
        self.assertTrue(结果["成功"])
        self.assertEqual(结果["可用状态"], "可用")
        self.assertIn("已登记", 结果["原因"])
        # 未登记能力 → 不可用 + 原因
        结果2 = self.视图.验证可用(令牌=self.令牌, 能力id="不存在.能力")
        self.assertFalse(结果2["成功"])
        self.assertEqual(结果2["错误码"], "能力不存在")
        self.assertEqual(结果2["可用状态"], "不可用")
        self.assertIn("未登记", 结果2["原因"])
        self.assertTrue(结果2["建议操作"])
        # 登记但无提供者 → 不可用
        成功, _ = self.服务.目录.登记能力(
            能力id="无提供者.能力", 契约={"能力id": "无提供者.能力"}, 组件="x", 领域="x")
        self.assertTrue(成功)
        结果3 = self.视图.验证可用(令牌=self.令牌, 能力id="无提供者.能力")
        self.assertEqual(结果3["可用状态"], "不可用")
        self.assertIn("提供者", 结果3["原因"])
        # 普通用户令牌 → 需授权
        普通令牌 = self.服务.授权.注册身份(身份id="普通用户1")
        结果4 = self.视图.验证可用(令牌=普通令牌, 能力id=self.能力id)
        self.assertEqual(结果4["可用状态"], "需授权")

    def test_调用能力真实返回42(self):
        结果 = self.视图.调用能力(令牌=self.令牌, 能力id=self.能力id, 参数={})
        self.assertTrue(结果["成功"])
        self.assertEqual(结果["值"], 42, "必须真实返回提供者的结果")
        self.assertEqual(结果["错误码"], "")
        self.assertFalse(结果["可重试"])
        self.assertEqual(结果["错误说明"], "调用完成")
        # 未登记能力 → CAPABILITY_NOT_FOUND + 建议操作
        结果2 = self.视图.调用能力(令牌=self.令牌, 能力id="未登记.能力", 参数={})
        self.assertFalse(结果2["成功"])
        self.assertEqual(结果2["错误码"], "能力不存在")
        self.assertEqual(结果2["值"], None)
        self.assertTrue(结果2["错误说明"])
        self.assertTrue(结果2["建议操作"])
        # 空能力id → 结构化错误
        结果3 = self.视图.调用能力(令牌=self.令牌, 能力id="", 参数={})
        self.assertEqual(结果3["错误码"], "能力必填")

    def test_异常提供者失败文本不泄漏(self):
        """提供者抛异常 → 错误说明/消息必须为中文安全文案，不得泄漏异常文本。"""
        成功, _ = self.服务.目录.登记能力(
            能力id="异常.能力", 契约={"能力id": "异常.能力"}, 组件="x", 领域="x")
        self.assertTrue(成功)

        def 抛异常() -> None:
            raise RuntimeError("机密异常细节")

        self.服务.注册提供者(能力id="异常.能力", 函数=抛异常, 预算=完整预算())
        结果 = self.视图.调用能力(令牌=self.令牌, 能力id="异常.能力", 参数={})
        self.assertFalse(结果["成功"])
        # 注册表 对外稳定错误码本批汉化（决策 0003）：超时 → 调用超时，其余 → 调用失败
        self.assertIn(结果["错误码"], ("调用失败", "调用超时"))
        正文 = json.dumps(结果, ensure_ascii=False)
        self.assertNotIn("机密异常细节", 正文)
        self.assertNotIn("Traceback", 正文)

    def test_四操作统一结果结构(self):
        结果表 = [
            self.视图.搜索能力(令牌=self.令牌, 关键词="计算"),
            self.视图.查看能力(令牌=self.令牌, 能力id=self.能力id),
            self.视图.验证可用(令牌=self.令牌, 能力id=self.能力id),
            self.视图.调用能力(令牌=self.令牌, 能力id=self.能力id, 参数={}),
        ]
        for 结果 in 结果表:
            for 键 in ("成功", "错误码", "消息", "可重试"):
                self.assertIn(键, 结果, f"统一结果结构必须含 {键}")
            self.assertIn("建议操作", 结果, "统一结果结构必须含 建议操作")


if __name__ == "__main__":
    unittest.main()
