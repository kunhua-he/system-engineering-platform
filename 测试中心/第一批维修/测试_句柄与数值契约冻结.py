"""统一契约门禁：句柄类型与场景数值字面量不得漂移。

覆盖面（HEAD `1c69ea5d` 实测，只读统计）：
- 候选 JSON（支持库/模块库/技能库，排除 `__pycache__` 与 `工程缓存`）：1345 个
- 场景字面量扫描面（路径含「验证场景」）：183 个文件 / 608664 字节
- 更宽的 `能力契约/参数契约.json` 的 `调用示例` 块不在本用例范围：
  实测另有 138 处 int 字面量声明为浮点型（数据口径待议），放开即红，
  故本用例用「候选/参与文件数量下限」锁住现有扫描面，不静默收窄。
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

系统根 = Path(__file__).resolve().parents[2]


class 测试句柄与数值契约冻结(unittest.TestCase):
    def test_句柄参数统一为整数型(self) -> None:
        违规 = []
        for 根名 in ("支持库", "模块库", "技能库"):
            for 文件 in (系统根 / 根名).rglob("能力契约/参数契约.json"):
                数据 = json.loads(文件.read_text(encoding="utf-8"))
                for 能力 in 数据.get("能力契约", []):
                    for 参数 in 能力.get("参数", []):
                        名称 = str(参数.get("名称") or "")
                        if (名称.endswith("句柄") or 名称.endswith("句柄id")) and 参数.get("类型") != "整数型":
                            违规.append((能力.get("能力id"), 名称, 参数.get("类型")))
        self.assertEqual(违规, [])

    def test_浮点参数场景字面量不能写成整数(self) -> None:
        类型表 = {}
        for 根名 in ("支持库", "模块库", "技能库"):
            for 文件 in (系统根 / 根名).rglob("能力契约/参数契约.json"):
                数据 = json.loads(文件.read_text(encoding="utf-8"))
                for 能力 in 数据.get("能力契约", []):
                    类型表[能力.get("能力id")] = {
                        参数.get("名称"): 参数.get("类型") for 参数 in 能力.get("参数", [])
                    }
        违规 = []
        def 扫描(值, 文件):
            if isinstance(值, dict):
                能力id, 参数 = 值.get("能力id"), 值.get("参数")
                if 能力id in 类型表 and isinstance(参数, dict):
                    for 名称, 参数值 in 参数.items():
                        if 类型表[能力id].get(名称) in {"单精度数型", "双精度数型"} and type(参数值) is int:
                            违规.append((文件, 能力id, 名称, 参数值))
                for 子值 in 值.values():
                    扫描(子值, 文件)
            elif isinstance(值, list):
                for 子值 in 值:
                    扫描(子值, 文件)
        解析失败列表 = []
        候选文件数 = 0
        参与文件数 = 0
        for 根名 in ("支持库", "模块库", "技能库"):
            for 文件 in (系统根 / 根名).rglob("*.json"):
                相对路径 = 文件.relative_to(系统根).as_posix()
                if "__pycache__" in 相对路径 or "工程缓存" in 相对路径:
                    continue
                候选文件数 += 1
                if "验证场景" not in 相对路径:
                    continue
                try:
                    扫描(json.loads(文件.read_text(encoding="utf-8")), 相对路径)
                except (json.JSONDecodeError, UnicodeDecodeError) as 错误:
                    # 静默跳过等于扫描器自身假绿：坏文件必须计入并阻断
                    解析失败列表.append(
                        (相对路径, f"{type(错误).__name__}: {错误}")
                    )
                    continue
                参与文件数 += 1
        # 扫描面下限守卫：范围塌成 0（或文件被整体搬走）时空断言毫无意义
        self.assertGreaterEqual(候选文件数, 1000, f"候选 JSON 面异常收缩: {候选文件数}")
        self.assertGreaterEqual(参与文件数, 100, f"场景字面量扫描面异常收缩: {参与文件数}")
        self.assertEqual(解析失败列表, [], "场景文件必须可解析，禁止静默跳过")
        self.assertEqual(违规, [])


if __name__ == "__main__":
    unittest.main()
