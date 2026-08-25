"""统一网关渐进发现测试：目录轻量、包清单简洁、能力正文按需展开。"""

from __future__ import annotations

import json
import unittest
import urllib.request
from urllib.parse import quote
from pathlib import Path

from 后端核心.后端核心 import 后端核心
from 运行核心.统一网关.本地网关 import 本地网关服务器
from 运行核心.统一网关.网关核心 import 网关核心


系统根 = Path(__file__).resolve().parents[2]


class 渐进能力目录测试(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.后端 = 后端核心(系统根)
        启动 = cls.后端.启动()
        assert 启动.成功, 启动.错误说明
        cls.服务器 = 本地网关服务器(网关核心实例=网关核心(cls.后端), 端口=0)
        成功, 消息 = cls.服务器.启动()
        assert 成功, 消息
        cls.地址 = f"http://127.0.0.1:{cls.服务器.端口}" + quote("/网关/请求", safe="/")

    @classmethod
    def tearDownClass(cls) -> None:
        cls.服务器.优雅停止()
        cls.后端.优雅关闭()

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
        self.assertEqual(目录["总包数"], 51)
        self.assertEqual(目录["偏移"], 0)
        self.assertEqual(目录["下一偏移"], 20)
        self.assertFalse(目录["是否完成"])
        self.assertEqual(目录["使用顺序"], ["选择包", "查看包详情", "查看能力详情", "调用能力"])
        条目表 = [条目 for 领域 in 目录["支持库"] for 条目 in 领域["包"]] + 目录["模块库"]
        self.assertEqual(len(条目表), 20)
        for 条目 in 条目表:
            self.assertEqual(set(条目), {"包id", "名称", "简介", "能力数"})
            self.assertLessEqual(len(条目["简介"]), 60)

    def test_目录支持分页直到完成(self) -> None:
        第一页 = self.请求("能力目录", {"限制": 7})["值"]
        第二页 = self.请求("能力目录", {"偏移": 第一页["下一偏移"], "限制": 7})["值"]
        第一批 = [条目["包id"] for 领域 in 第一页["支持库"] for 条目 in 领域["包"]] + [条目["包id"] for 条目 in 第一页["模块库"]]
        第二批 = [条目["包id"] for 领域 in 第二页["支持库"] for 条目 in 领域["包"]] + [条目["包id"] for 条目 in 第二页["模块库"]]
        self.assertEqual(len(第一批), 7)
        self.assertEqual(len(第二批), 7)
        self.assertTrue(set(第一批).isdisjoint(第二批))

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


if __name__ == "__main__":
    unittest.main()
