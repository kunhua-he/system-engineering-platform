"""路径安全唯一腿加严回归（S4·T3，2026-09-23）。

判据来源：`开发文档/分析/路径安全实现处与分歧实测_20260923.md`（8 处实现 / 15 用例 / 6 处分歧）。
本用例钉住两件事：
  ① 加严后的逐条读数（15 用例）；
  ② **只许加严**：加严前放行的用例不得在加严后仍然放行（反向即回归）。
"""

from __future__ import annotations

import unittest

from 支持库.后端.系统核心支持库.路径安全.实现.路径安全 import 校验路径

根 = "/tmp/路径安全回归根"

#: 用例 → 加严后期望（真 = 通过）
期望表: dict[str, bool] = {
    # 加严新增拒绝的四类：盘符（盘符相对 / 盘符绝对）、反斜杠归一后的 `..` 段、`~` 家目录、段内 `.`
    "C:foo": False,
    "C:/foo": False,
    "a\\..\\b": False,
    "~/x": False,
    "a/./b": False,
    # 原有判据（不得因加严而放宽）
    ".": False,
    "..%2fx": False,
    "%2e%2e/x": False,
    "a/..%2f/b": False,
    "a/../b": False,
    "..": False,
    "%252e%252e/x": True,
    "正常/路径.py": True,
    "a/b.py": True,
    "a//b": True,
}

#: 加严前放行、加严后必须拒绝的用例（只许加严的反向证据面）。
加严前放行表: tuple[str, ...] = ("C:foo", "C:/foo", "a\\..\\b", "~/x", "a/./b")


def _判定(相对路径: str) -> bool:
    """按能力返回结构取 通过 布尔；能力失败（参数不合法）同样算拒。"""
    结果 = 校验路径(根, 相对路径)
    if not getattr(结果, "成功", True):
        return False
    值 = 结果.值 if isinstance(结果.值, dict) else {}
    return bool(值.get("通过"))


class 路径安全加严回归(unittest.TestCase):
    def test_十五用例逐条与加严口径一致(self) -> None:
        for 用例, 期望 in 期望表.items():
            with self.subTest(用例=用例):
                self.assertEqual(_判定(用例), 期望, f"{用例!r} 判定与加严口径不符")

    def test_只许加严_加严前放行的现在必须拒(self) -> None:
        for 用例 in 加严前放行表:
            with self.subTest(用例=用例):
                self.assertFalse(_判定(用例), f"{用例!r} 仍被放行 ⇒ 加严未生效")

    def test_原有正常路径不得被误伤(self) -> None:
        for 用例 in ("正常/路径.py", "a/b.py", "a//b", "%252e%252e/x"):
            with self.subTest(用例=用例):
                self.assertTrue(_判定(用例), f"{用例!r} 被加严误伤")

    def test_拒绝原因可读且区分四类(self) -> None:
        期望原因 = {
            "C:foo": "盘符",
            "~/x": "家目录",
            "a\\..\\b": "..",
            "a/./b": "目录段",
        }
        for 用例, 关键词 in 期望原因.items():
            with self.subTest(用例=用例):
                值 = 校验路径(根, 用例).值
                原因 = 值.get("原因") if isinstance(值, dict) else ""
                self.assertIn(关键词, 原因 or "", f"{用例!r} 的拒绝原因未说明 {关键词}")


if __name__ == "__main__":
    unittest.main()
