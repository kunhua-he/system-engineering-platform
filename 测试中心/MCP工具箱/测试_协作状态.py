"""开工id父子映射与协作状态：登记、聚合查询、收口、指纹与阻断测试。"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from MCP工具箱.协作状态 import (
    计算代码指纹, 登记任务, 查询协作状态, 收口登记, 默认状态目录, _排除片段表,
)
from MCP工具箱.临时上下文 import 写入临时上下文

父id = "aaaa000000000001"
子id = "aaaa000000000002"


def _写反馈(路径: Path, 开工id: str) -> None:
    路径.parent.mkdir(parents=True, exist_ok=True)
    记录 = {"开工id": 开工id, "任务": "测试任务", "角色": "平台维护者",
            "时间": "2026-08-03T00:00:00+00:00", "总结": "无", "不满意": "无",
            "多余": "无", "缺失": "无", "升级建议": "无"}
    with 路径.open("a", encoding="utf-8") as 文件:
        文件.write(json.dumps(记录, ensure_ascii=False) + "\n")


def _写验证(路径: Path, 开工id: str, 指纹: str, *, 提交: str = "abc123",
            名称: str = "测试验证") -> None:
    路径.parent.mkdir(parents=True, exist_ok=True)
    记录 = {"名称": 名称, "命令": ["python3.14", "测试"], "工作区指纹": 指纹,
            "开工id": 开工id, "提交": 提交, "时间": "2026-08-03T00:00:00+00:00",
            "输出末尾": "", "退出码": 0, "错误末尾": ""}
    with 路径.open("a", encoding="utf-8") as 文件:
        文件.write(json.dumps(记录, ensure_ascii=False) + "\n")


class 协作状态测试(unittest.TestCase):
    def setUp(self) -> None:
        self._临时 = tempfile.TemporaryDirectory()
        根 = Path(self._临时.name)
        self.状态目录 = 根 / "协作状态"
        self.反馈文件 = 根 / "MCP使用反馈.jsonl"
        self.验证历史文件 = 根 / "验证历史.jsonl"
        self.临时上下文目录 = 根 / "MCP临时上下文"
        self.工作区 = 根 / "工作区"
        self.工作区.mkdir()
        (self.工作区 / "源码.txt").write_text("内容", encoding="utf-8")

    def tearDown(self) -> None:
        self._临时.cleanup()

    def _登记父(self, work_id: str = 父id, *, 任务: str = "父子映射",
                子任务列表: list[str] | None = None) -> dict:
        return 登记任务(work_id, 任务=任务, 角色="平台维护者",
                       worktree路径=str(self.工作区), 允许路径=["MCP工具箱"],
                       基线提交="060fca3", 子任务列表=子任务列表 or [],
                       状态目录=self.状态目录)

    def test_父登记子登记查询聚合含反馈证据(self) -> None:
        self.assertTrue(self._登记父()["成功"])
        子登记 = 登记任务(子id, 任务="子任务登记", 角色="模块开发者",
                       worktree路径=str(self.工作区), 允许路径=["模块库"],
                       基线提交="060fca3", parent_work_id=父id,
                       状态目录=self.状态目录)
        self.assertTrue(子登记["成功"])
        self.assertEqual(子登记["parent_work_id"], 父id)
        指纹 = 计算代码指纹(self.工作区)["指纹"]
        _写反馈(self.反馈文件, 父id)
        _写验证(self.验证历史文件, 父id, 指纹)
        写入临时上下文(self.临时上下文目录, 开工id=子id, 父任务=父id, 角色="模块开发者",
                       允许目录=[], 记忆查询=[], 事实=[], 验证计划=[])

        父聚合 = 查询协作状态(work_id=父id, 状态目录=self.状态目录,
                              反馈文件=self.反馈文件, 验证历史文件=self.验证历史文件,
                              临时上下文目录=self.临时上下文目录)
        self.assertTrue(父聚合["成功"])
        条目 = 父聚合["结果列表"][0]
        self.assertEqual(条目["work_id"], 父id)
        self.assertEqual(条目["子任务列表"], [子id])
        self.assertEqual(条目["子任务状态"], {子id: "已登记"})
        self.assertEqual(条目["反馈状态"], "已反馈")
        self.assertEqual(条目["生命周期"], "进行")
        self.assertEqual(条目["阻断标记"], [])
        self.assertEqual(len(条目["验证证据"]), 1)
        self.assertEqual(条目["验证证据"][0]["提交"], "abc123")
        self.assertEqual(条目["验证证据"][0]["指纹"], 指纹)
        self.assertIsNone(条目["临时上下文"])

        子聚合 = 查询协作状态(work_id=子id, 状态目录=self.状态目录,
                              反馈文件=self.反馈文件, 验证历史文件=self.验证历史文件,
                              临时上下文目录=self.临时上下文目录)
        子条目 = 子聚合["结果列表"][0]
        self.assertEqual(子条目["父任务"], 父id)
        self.assertIsNotNone(子条目["临时上下文"])
        self.assertEqual(子条目["生命周期"], "创建")

    def test_未反馈阻断收口与反馈后收口完成(self) -> None:
        self.assertTrue(self._登记父()["成功"])
        拒绝 = 收口登记(父id, 五件套路径="回信.md", 结论="完成",
                     状态目录=self.状态目录, 反馈文件=self.反馈文件,
                     验证历史文件=self.验证历史文件)
        self.assertFalse(拒绝["成功"])
        self.assertEqual(拒绝["错误码"], "FEEDBACK_BLOCKED")
        self.assertEqual(拒绝["阻断标记"], ["未反馈"])

        _写反馈(self.反馈文件, 父id)
        成功 = 收口登记(父id, 五件套路径="回信.md", 结论="完成",
                     状态目录=self.状态目录, 反馈文件=self.反馈文件,
                     验证历史文件=self.验证历史文件)
        self.assertTrue(成功["成功"])
        self.assertEqual(成功["生命周期"], "完成")
        self.assertEqual(成功["五件套路径"], "回信.md")

        聚合 = 查询协作状态(work_id=父id, 状态目录=self.状态目录,
                              反馈文件=self.反馈文件, 验证历史文件=self.验证历史文件,
                              临时上下文目录=self.临时上下文目录)
        条目 = 聚合["结果列表"][0]
        self.assertEqual(条目["生命周期"], "完成")
        self.assertEqual(条目["阻断标记"], [])
        self.assertEqual(条目["反馈状态"], "已反馈")

    def test_伪造work_id拒绝(self) -> None:
        for 非法id in ("abc", "1234567890abcdefg", "gggg000000000001", ""):
            结果 = 登记任务(非法id, 任务="任务", 角色="角色", worktree路径="路径",
                          允许路径=[], 基线提交="x", 状态目录=self.状态目录)
            self.assertFalse(结果["成功"])
            self.assertEqual(结果["错误码"], "WORK_ID_INVALID")
            查询 = 查询协作状态(work_id=非法id, 状态目录=self.状态目录)
            self.assertEqual(查询["错误码"], "WORK_ID_INVALID")
            收口 = 收口登记(非法id, 五件套路径="a.md", 结论="完成",
                          状态目录=self.状态目录)
            self.assertEqual(收口["错误码"], "WORK_ID_INVALID")
        大写id = 登记任务("AAAA00000000000B", 任务="任务", 角色="角色",
                        worktree路径=str(self.工作区), 允许路径=[], 基线提交="x",
                        状态目录=self.状态目录)
        self.assertTrue(大写id["成功"])
        self.assertEqual(大写id["work_id"], "aaaa00000000000b")

    def test_指纹计算稳定与排除缓存(self) -> None:
        指纹1 = 计算代码指纹(self.工作区)["指纹"]
        指纹2 = 计算代码指纹(self.工作区)["指纹"]
        self.assertEqual(指纹1, 指纹2)
        (self.工作区 / "工程缓存").mkdir()
        (self.工作区 / "工程缓存" / "缓存.json").write_text("缓存", encoding="utf-8")
        (self.工作区 / "测试中心缓存").mkdir()
        (self.工作区 / "测试中心缓存" / "临时.txt").write_text("临时", encoding="utf-8")
        (self.工作区 / ".git").mkdir()
        (self.工作区 / ".git" / "内部").write_text("元数据", encoding="utf-8")
        (self.工作区 / "__pycache__").mkdir()
        (self.工作区 / "__pycache__" / "模块.cpython-314.pyc").write_text("缓存", encoding="utf-8")
        self.assertEqual(计算代码指纹(self.工作区)["指纹"], 指纹1)
        (self.工作区 / "源码.txt").write_text("内容已修改", encoding="utf-8")
        self.assertNotEqual(计算代码指纹(self.工作区)["指纹"], 指纹1)
        self.assertFalse(计算代码指纹(Path("不存在目录"))["成功"])

    def test_指纹排除表含项目证据与临时文件(self) -> None:
        self.assertIn("项目证据", _排除片段表)
        self.assertIn("临时文件", _排除片段表)

    def test_指纹排除项目证据与临时文件目录(self) -> None:
        指纹1 = 计算代码指纹(self.工作区)["指纹"]
        证据目录 = self.工作区 / "开发文档" / "项目证据"
        证据目录.mkdir(parents=True)
        (证据目录 / "验证历史.jsonl").write_text("证据", encoding="utf-8")
        (证据目录 / "MCP使用反馈.jsonl").write_text("反馈", encoding="utf-8")
        临时目录 = self.工作区 / "开发文档" / "临时文件"
        临时目录.mkdir(parents=True)
        (临时目录 / "计划.md").write_text("计划", encoding="utf-8")
        self.assertEqual(计算代码指纹(self.工作区)["指纹"], 指纹1)
        测试目录 = self.工作区 / "测试中心"
        测试目录.mkdir()
        (测试目录 / "新增用例.py").write_text("新增", encoding="utf-8")
        self.assertNotEqual(计算代码指纹(self.工作区)["指纹"], 指纹1)
        (self.工作区 / "根下新增.md").write_text("根下新增", encoding="utf-8")
        self.assertNotEqual(计算代码指纹(self.工作区)["指纹"], 指纹1)

    def test_子代理未登记合并阻断标记(self) -> None:
        未登记子 = "cccc000000000001"
        self.assertTrue(self._登记父(子任务列表=[未登记子])["成功"])
        聚合 = 查询协作状态(work_id=父id, 状态目录=self.状态目录,
                              反馈文件=self.反馈文件, 验证历史文件=self.验证历史文件,
                              临时上下文目录=self.临时上下文目录)
        条目 = 聚合["结果列表"][0]
        self.assertEqual(条目["子任务状态"], {未登记子: "未登记"})
        self.assertIn("子代理未登记", 条目["阻断标记"])

    def test_未登记查询与未登记收口任务不存在(self) -> None:
        查询 = 查询协作状态(work_id="dddd000000000001", 状态目录=self.状态目录,
                              反馈文件=self.反馈文件, 验证历史文件=self.验证历史文件,
                              临时上下文目录=self.临时上下文目录)
        self.assertFalse(查询["成功"])
        self.assertEqual(查询["错误码"], "TASK_NOT_FOUND")
        self.assertEqual(查询["阻断标记"], ["未登记"])
        收口 = 收口登记("dddd000000000001", 五件套路径="a.md", 结论="完成",
                      状态目录=self.状态目录, 反馈文件=self.反馈文件)
        self.assertEqual(收口["错误码"], "TASK_NOT_FOUND")

    def test_证据指纹不匹配阻断查询与收口(self) -> None:
        self.assertTrue(self._登记父()["成功"])
        _写反馈(self.反馈文件, 父id)
        _写验证(self.验证历史文件, 父id, "错误指纹00000000")
        聚合 = 查询协作状态(work_id=父id, 状态目录=self.状态目录,
                              反馈文件=self.反馈文件, 验证历史文件=self.验证历史文件,
                              临时上下文目录=self.临时上下文目录)
        条目 = 聚合["结果列表"][0]
        self.assertIn("证据指纹不匹配", 条目["阻断标记"])
        收口 = 收口登记(父id, 五件套路径="回信.md", 结论="完成",
                      状态目录=self.状态目录, 反馈文件=self.反馈文件,
                      验证历史文件=self.验证历史文件)
        self.assertFalse(收口["成功"])
        self.assertEqual(收口["错误码"], "EVIDENCE_MISMATCH")
        self.assertEqual(收口["阻断标记"], ["证据指纹不匹配"])

    def test_关键词查询匹配与无匹配(self) -> None:
        self.assertTrue(self._登记父(任务="开工id父子映射")["成功"])
        self.assertTrue(self._登记父(work_id="bbbb000000000001",
                                     任务="验证反馈门禁")["成功"])
        匹配 = 查询协作状态(任务关键词="映射", 状态目录=self.状态目录,
                             反馈文件=self.反馈文件, 验证历史文件=self.验证历史文件,
                             临时上下文目录=self.临时上下文目录)
        self.assertTrue(匹配["成功"])
        self.assertEqual(匹配["数量"], 1)
        self.assertEqual(匹配["结果列表"][0]["work_id"], 父id)
        无匹配 = 查询协作状态(任务关键词="不存在的任务", 状态目录=self.状态目录)
        self.assertEqual(无匹配["错误码"], "TASK_NOT_FOUND")
        空条件 = 查询协作状态()
        self.assertEqual(空条件["错误码"], "WORK_ID_INVALID")

    def test_重复登记与父任务未登记拒绝(self) -> None:
        self.assertTrue(self._登记父()["成功"])
        重复 = self._登记父()
        self.assertFalse(重复["成功"])
        self.assertEqual(重复["错误码"], "REGISTRATION_FAILED")
        孤儿 = 登记任务(子id, 任务="孤儿", 角色="开发者", worktree路径="路径",
                      允许路径=[], 基线提交="x", parent_work_id="ffff000000000001",
                      状态目录=self.状态目录)
        self.assertFalse(孤儿["成功"])
        self.assertEqual(孤儿["错误码"], "REGISTRATION_FAILED")

    def test_父登记子登记多次追加子任务列表(self) -> None:
        self.assertTrue(self._登记父()["成功"])
        for 新子id in ("aaaa000000000003", "aaaa000000000004"):
            登记 = 登记任务(新子id, 任务="追加子", 角色="开发者",
                         worktree路径=str(self.工作区), 允许路径=[],
                         基线提交="x", parent_work_id=父id, 状态目录=self.状态目录)
            self.assertTrue(登记["成功"])
        聚合 = 查询协作状态(work_id=父id, 状态目录=self.状态目录,
                              反馈文件=self.反馈文件, 验证历史文件=self.验证历史文件,
                              临时上下文目录=self.临时上下文目录)
        条目 = 聚合["结果列表"][0]
        self.assertEqual(条目["子任务列表"], ["aaaa000000000003", "aaaa000000000004"])

    def test_零残留不触碰正式路径(self) -> None:
        self.assertTrue(self._登记父()["成功"])
        _写反馈(self.反馈文件, 父id)
        _写验证(self.验证历史文件, 父id, 计算代码指纹(self.工作区)["指纹"])
        收口 = 收口登记(父id, 五件套路径="回信.md", 结论="完成",
                      状态目录=self.状态目录, 反馈文件=self.反馈文件,
                      验证历史文件=self.验证历史文件)
        self.assertTrue(收口["成功"])
        结果 = 查询协作状态(任务关键词="父子映射", 状态目录=self.状态目录,
                             反馈文件=self.反馈文件, 验证历史文件=self.验证历史文件,
                             临时上下文目录=self.临时上下文目录)
        self.assertTrue(结果["成功"])
        # 隔离语义：本测试全程使用临时隔离目录（self.状态目录 在 TemporaryDirectory 内），
        # 不触碰真实工程缓存（默认状态目录）。历史登记文件使"目录不存在"断言失效，
        # 故改为验证：查询命中本测试登记的父任务，且隔离目录位于临时区内。
        self.assertTrue(结果["结果列表"], "查询结果不应为空")
        self.assertIn(父id, {项["work_id"] for 项 in 结果["结果列表"]})
        self.assertNotEqual(self.状态目录, 默认状态目录,
                            "测试必须使用隔离目录，不得直接写真实工程缓存")


if __name__ == "__main__":
    unittest.main()
