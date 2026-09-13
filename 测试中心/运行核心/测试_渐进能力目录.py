"""统一网关渐进发现测试：目录轻量、包清单简洁、能力正文按需展开。"""

from __future__ import annotations

import json
import os
import unittest
import urllib.request
import urllib.error
from urllib.parse import quote
from pathlib import Path

from 后端核心.后端核心 import 后端核心
from 运行核心.统一网关.本地网关 import 本地网关服务器
from 运行核心.统一网关.网关核心 import 网关核心


系统根 = Path(__file__).resolve().parents[2]

桶名表 = ("支持库", "模块库", "技能库", "其他库")


def 摊平目录(目录: dict) -> list[dict]:
    """把目录四桶摊平成条目表：支持库按领域二级分组，其余三桶是平铺列表。"""
    条目表 = [条目 for 领域块 in 目录["支持库"] for 条目 in 领域块["包"]]
    for 桶 in 桶名表[1:]:
        条目表 += 目录[桶]
    return 条目表


class 渐进能力目录测试(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._原网关凭证 = os.environ.get("系统库网关凭证")
        os.environ["系统库网关凭证"] = "test"
        try:
            cls.后端 = 后端核心(系统根)
            启动 = cls.后端.启动()
            assert 启动.成功, 启动.错误说明
            cls.服务器 = 本地网关服务器(
                网关核心实例=网关核心(cls.后端), 端口=0,
                配置={"要求凭证": False, "禁止客户端身份": False},
            )
            成功, 消息 = cls.服务器.启动()
            assert 成功, 消息
            cls.地址 = f"http://127.0.0.1:{cls.服务器.端口}" + quote("/网关/调用", safe="/")
        except Exception:
            if cls._原网关凭证 is None:
                os.environ.pop("系统库网关凭证", None)
            else:
                os.environ["系统库网关凭证"] = cls._原网关凭证
            raise

    @classmethod
    def tearDownClass(cls) -> None:
        cls.服务器.优雅停止()
        cls.后端.优雅关闭()
        if cls._原网关凭证 is None:
            os.environ.pop("系统库网关凭证", None)
        else:
            os.environ["系统库网关凭证"] = cls._原网关凭证

    def 请求(self, 操作: str, 参数: dict | None = None) -> dict:
        请求 = urllib.request.Request(
            self.地址,
            data=json.dumps({"操作": 操作, "参数": 参数 or {}}, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(请求, timeout=10) as 响应:
            return json.loads(响应.read().decode("utf-8"))

    def test_首次目录只返回包级通用信息(self) -> None:
        响应 = self.请求("能力目录")
        self.assertTrue(响应["成功"])
        目录 = 响应["值"]
        self.assertEqual(目录["包数"], 20)
        self.assertGreaterEqual(目录["总包数"], 目录["包数"])
        self.assertEqual(目录["偏移"], 0)
        self.assertEqual(目录["下一偏移"], min(20, 目录["总包数"]))
        self.assertFalse(目录["是否完成"])
        self.assertEqual(目录["使用顺序"], ["选择包", "查看包详情", "查看能力详情", "调用能力"])
        # 四桶恒存在（默认值填充），消费者无需判键是否存在。
        for 桶 in 桶名表:
            self.assertIn(桶, 目录)
        条目表 = 摊平目录(目录)
        self.assertEqual(len(条目表), 20)
        self.assertEqual(len(条目表), 目录["包数"])
        for 条目 in 条目表:
            self.assertEqual(set(条目), {"包id", "名称", "简介", "能力数"})
            self.assertLessEqual(len(条目["简介"]), 60)

    def test_目录支持分页直到完成(self) -> None:
        偏移 = 0
        全部包id: list[str] = []
        总包数 = None
        while True:
            页面 = self.请求("能力目录", {"偏移": 偏移, "限制": 7})["值"]
            当前批 = [条目["包id"] for 条目 in 摊平目录(页面)]
            self.assertLessEqual(len(当前批), 7)
            全部包id.extend(当前批)
            总包数 = 页面["总包数"]
            if 页面["是否完成"]:
                self.assertIsNone(页面["下一偏移"])
                break
            self.assertEqual(页面["下一偏移"], 偏移 + len(当前批))
            偏移 = 页面["下一偏移"]
        self.assertEqual(len(全部包id), 总包数)
        self.assertEqual(len(set(全部包id)), 总包数)

    def test_分页走查不遗漏任何已注册包(self) -> None:
        """分桶必须完备：四桶摊平总数 == 包数，且分页走查覆盖全部已注册包。

        原实现只认 支持库./模块库. 两个前缀，技能库. 前缀的包被计入 包数
        却不落桶 → 该包在目录里永不可见、分页走查也永远走不到它。
        """
        注册包表 = {
            self.后端.注册表.获取(能力id).包id
            for 能力id in self.后端.注册表.能力id列表
        }
        偏移 = 0
        走查包id: list[str] = []
        while True:
            页面 = self.请求("能力目录", {"偏移": 偏移, "限制": 7})["值"]
            条目表 = 摊平目录(页面)
            self.assertEqual(len(条目表), 页面["包数"])
            走查包id.extend(条目["包id"] for 条目 in 条目表)
            if 页面["是否完成"]:
                break
            偏移 = 页面["下一偏移"]
        self.assertEqual(set(走查包id), 注册包表)
        self.assertEqual(sorted(走查包id), sorted(注册包表))

    def test_技能库作为第三根正式包根可见(self) -> None:
        """技能库与支持库、模块库平级，必须能被渐进发现走到并展开命令目录。"""
        页面 = self.请求("能力目录", {"关键词": "技能库"})["值"]
        包id表 = [条目["包id"] for 条目 in 摊平目录(页面)]
        self.assertIn("技能库.后端.技能库", 包id表)
        详情 = self.请求("包详情", {"包id": "技能库.后端.技能库"})["值"]
        self.assertEqual(详情["包id"], "技能库.后端.技能库")
        self.assertGreater(len(详情["命令"]), 0)

    def test_包详情只返回命令目录(self) -> None:
        响应 = self.请求("包详情", {"包id": "模块库.文档读取"})
        self.assertTrue(响应["成功"])
        详情 = 响应["值"]
        self.assertEqual(详情["包id"], "模块库.文档读取")
        self.assertGreater(len(详情["命令"]), 0)
        for 命令 in 详情["命令"]:
            self.assertEqual(set(命令), {"能力id", "名称", "简介"})
            self.assertLessEqual(len(命令["简介"]), 60)
            self.assertNotIn("参数", 命令)

    def test_能力详情按需返回完整正文和调用方式(self) -> None:
        响应 = self.请求("能力详情", {"能力id": "文档读取.结构化读取"})
        self.assertTrue(响应["成功"])
        正文 = 响应["值"]
        self.assertEqual(正文["包id"], "模块库.文档读取")
        self.assertTrue(正文["参数"])
        self.assertIn("返回", 正文)
        self.assertIn("错误码", 正文)
        self.assertIn("依赖", 正文)
        self.assertIn("配置契约", 正文)
        self.assertIn("资源预算", 正文)
        self.assertEqual(正文["调用方式"]["目标"], "文档读取.结构化读取")

    def test_搜索结果仍然保持紧凑(self) -> None:
        响应 = self.请求("能力搜索", {"关键词": "读取正文"})
        self.assertTrue(响应["成功"])
        self.assertTrue(响应["值"])
        for 条目 in 响应["值"]:
            self.assertEqual(set(条目), {"能力id", "包id", "简介"})
            self.assertLessEqual(len(条目["简介"]), 60)

    def test_空搜索也不会展开全部能力(self) -> None:
        响应 = self.请求("能力搜索")
        self.assertTrue(响应["成功"])
        self.assertEqual(len(响应["值"]), 20)

    def test_目录数值参数类型错误不静默回退(self) -> None:
        """分页偏移/限制传文本或逻辑值时，网关必须直接拒绝。"""
        for 参数 in ({"偏移": "0"}, {"限制": True}):
            请求 = urllib.request.Request(
                self.地址,
                data=json.dumps({"操作": "能力目录", "参数": 参数}).encode("utf-8"),
                headers={"Content-Type": "application/json"},
            )
            with self.assertRaises(urllib.error.HTTPError) as 上下文:
                urllib.request.urlopen(请求, timeout=10)
            self.assertEqual(上下文.exception.code, 400)
            try:
                响应 = json.loads(上下文.exception.read().decode("utf-8"))
            finally:
                上下文.exception.close()
            self.assertFalse(响应["成功"])
            self.assertEqual(响应["错误码"], "参数不合法")


if __name__ == "__main__":
    unittest.main()
