"""写入通道：经底座能力精确替换落盘、摘要乐观锁、路径越界拒绝、异开工id 租约拒绝。

测试全程使用临时项目根与临时存储目录，不触碰真实仓库文件与真实 工程缓存/平台控制面。
落盘一走真实底座能力（`后端核心.调用` → `文件系统支持库.文本补丁.应用精确替换`），
不 mock：摘要算法、唯一匹配、原子写、差异统计都取真实实现。
"""

from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path

from MCP工具箱.文件补丁 import 应用文件补丁, 解析仓库内路径
from MCP工具箱.文件租约 import 申请文件租约

原文 = "第一行：补水面膜\n第二行：待替换的旧文本\n第三行：精华液\n"
新文 = "第一行：补水面膜\n第二行：已经替换过的新文本\n第三行：精华液\n"


def 文本摘要(文本: str) -> str:
    return hashlib.sha256(文本.encode("utf-8")).hexdigest()


class 文件补丁测试(unittest.TestCase):
    def setUp(self) -> None:
        self._临时 = tempfile.TemporaryDirectory()
        self.项目根 = Path(self._临时.name) / "项目根"
        self.存储目录 = Path(self._临时.name) / "平台控制面"
        (self.项目根 / "样例").mkdir(parents=True)
        self.文件 = self.项目根 / "样例" / "待补丁.txt"
        self.文件.write_text(原文, encoding="utf-8")

    def tearDown(self) -> None:
        self._临时.cleanup()

    def _调用(self, **覆盖):
        参数 = {
            "文件路径": "样例/待补丁.txt", "旧文本": "待替换的旧文本", "新文本": "已经替换过的新文本",
        }
        参数.update(覆盖)
        return 应用文件补丁(self.项目根, self.存储目录, **参数)

    def test_成功替换并落盘(self) -> None:
        结果 = self._调用()
        self.assertTrue(结果["成功"], str(结果))
        self.assertTrue(结果["值"]["已写入"])
        self.assertEqual(结果["文件路径"], "样例/待补丁.txt")
        self.assertEqual(self.文件.read_text(encoding="utf-8"), 新文)
        self.assertEqual(结果["值"]["新增行数"], 1)
        self.assertEqual(结果["值"]["删除行数"], 1)

    def test_预期文件摘要相符才写(self) -> None:
        结果 = self._调用(预期文件摘要=文本摘要(原文))
        self.assertTrue(结果["成功"], str(结果))
        self.assertEqual(self.文件.read_text(encoding="utf-8"), 新文)

    def test_摘要不符拒绝并回带磁盘当前摘要(self) -> None:
        结果 = self._调用(预期文件摘要="0" * 64)
        self.assertFalse(结果["成功"])
        self.assertEqual(结果["错误码"], "文件摘要不符")
        # 底座能力的 结果.详细信息 必须透传到 MCP 侧，调用方才能据此重读。
        self.assertEqual(结果["详情"]["当前文件摘要"], 文本摘要(原文))
        self.assertEqual(self.文件.read_text(encoding="utf-8"), 原文)

    def test_只读预览不落盘(self) -> None:
        结果 = self._调用(写入=False)
        self.assertTrue(结果["成功"], str(结果))
        self.assertFalse(结果["值"]["已写入"])
        self.assertIn("已经替换过的新文本", 结果["值"]["差异"])
        self.assertEqual(self.文件.read_text(encoding="utf-8"), 原文)

    def test_旧文本不唯一则拒绝(self) -> None:
        结果 = self._调用(旧文本="：")
        self.assertFalse(结果["成功"])
        self.assertEqual(self.文件.read_text(encoding="utf-8"), 原文)

    def test_路径越界拒绝(self) -> None:
        结果 = self._调用(文件路径="../跑到项目外.txt")
        self.assertFalse(结果["成功"])
        self.assertEqual(结果["错误码"], "路径越界")
        with self.assertRaises(ValueError):
            解析仓库内路径(self.项目根, "../跑到项目外.txt")

    def test_文件不存在(self) -> None:
        结果 = self._调用(文件路径="样例/无此文件.txt")
        self.assertFalse(结果["成功"])
        self.assertEqual(结果["错误码"], "文件不存在")

    def test_异开工id占租约拒绝(self) -> None:
        占用 = 申请文件租约(self.存储目录, ["样例/待补丁.txt"],
                            所有者="bbbb000000000002", 任务="包2改造")
        self.assertTrue(占用["成功"], str(占用))
        结果 = self._调用(开工id="aaaa000000000001")
        self.assertFalse(结果["成功"])
        self.assertEqual(结果["错误码"], "FILE_LEASE_CONFLICT")
        self.assertEqual(结果["占用者"], "bbbb000000000002")
        self.assertEqual(self.文件.read_text(encoding="utf-8"), 原文)

    def test_同开工id放行且预览不受租约限制(self) -> None:
        申请文件租约(self.存储目录, ["样例/待补丁.txt"],
                    所有者="aaaa000000000001", 任务="包1改造")
        写入 = self._调用(开工id="aaaa000000000001")
        self.assertTrue(写入["成功"], str(写入))
        self.assertEqual(self.文件.read_text(encoding="utf-8"), 新文)

        self.文件.write_text(原文, encoding="utf-8")
        预览 = self._调用(写入=False, 开工id="cccc000000000003")
        self.assertTrue(预览["成功"], "只读预览不该被他人租约挡住")
        self.assertEqual(self.文件.read_text(encoding="utf-8"), 原文)


if __name__ == "__main__":
    unittest.main()
