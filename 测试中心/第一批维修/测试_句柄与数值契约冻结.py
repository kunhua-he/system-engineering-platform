"""统一契约门禁：句柄类型与场景数值字面量不得漂移。"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

系统根 = Path(__file__).resolve().parents[2]


class 测试句柄与数值契约冻结(unittest.TestCase):
    def test_句柄参数统一为整数型(self) -> None:
        违规 = []
        for 根名 in ("支持库", "模块库"):
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
        for 根名 in ("支持库", "模块库"):
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
        for 根名 in ("支持库", "模块库"):
            for 文件 in (系统根 / 根名).rglob("*.json"):
                if "验证场景" not in 文件.as_posix():
                    continue
                try:
                    扫描(json.loads(文件.read_text(encoding="utf-8")), 文件.relative_to(系统根).as_posix())
                except json.JSONDecodeError:
                    pass
        self.assertEqual(违规, [])


if __name__ == "__main__":
    unittest.main()
