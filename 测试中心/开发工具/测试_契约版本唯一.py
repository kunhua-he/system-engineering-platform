"""契约版本唯一门禁 + 组件各自迭代版本守卫（哲学第 5 条 1 项）。

两条不变量：
1. **契约只有一套**：全平台 `能力契约/参数契约.json` 的 `契约版本` 恒等于
   `公共契约/版本规则/契约版本.py` 的事实源；
2. **组件各自迭代**：每个支持库/模块的包声明与能力都带自己的迭代版本（合法 `主.次.修`），
   不许被谁统一抹平成同一个号——支持库和模块本来就该按自身迭代展示。

只读校验。跑法：
    unset PYTHONPATH && python3.14 -m 测试中心.开发工具.测试_契约版本唯一

不在范围内（各有自己的轴，别混进来）：依赖约束 `>=1.0.0`（是范围不是版本）、
计数类 栅栏令牌/资源版本、机制版本 状态结构版本/编译器版本/HTML 验证器版本、
环境依赖最低版本（Tesseract `>=5.0.0`）、验证场景轴的 `场景契约版本`。
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

系统根 = Path(__file__).resolve().parents[2]
if str(系统根) not in sys.path:
    sys.path.insert(0, str(系统根))

from 公共契约.版本规则.契约版本 import 契约版本

包根目录 = ("支持库", "模块库", "技能库")
跳过片段 = ("__pycache__", "工程缓存", "示例项目", "验证场景")
语义版本正则 = r"^\d+\.\d+\.\d+$"


def 遍历(文件名: str):
    for 顶层 in 包根目录:
        根 = 系统根 / 顶层
        if not 根.is_dir():
            continue
        for 文件 in sorted(根.rglob(文件名)):
            if any(片段 in 文件.parts for 片段 in 跳过片段):
                continue
            yield 文件


class 契约版本唯一门禁(unittest.TestCase):
    def test_事实源合法(self):
        self.assertRegex(契约版本, 语义版本正则, "契约版本必须是 主.次.修 形态")

    def test_全平台契约版本唯一(self):
        违规 = []
        for 文件 in 遍历("参数契约.json"):
            数据 = json.loads(文件.read_text(encoding="utf-8"))
            值 = 数据.get("契约版本")
            if 值 != 契约版本:
                违规.append(f"{文件.relative_to(系统根)} :: 契约版本 = {值!r}")
        self.assertEqual([], 违规[:20], f"发现 {len(违规)} 处契约版本不唯一：{违规[:20]}")

    def test_组件各自带迭代版本(self):
        违规 = []
        for 文件 in 遍历("包声明.json"):
            数据 = json.loads(文件.read_text(encoding="utf-8"))
            值 = 数据.get("版本")
            if not isinstance(值, str) or not __import__("re").match(语义版本正则, 值):
                违规.append(f"{文件.relative_to(系统根)} :: 包版本 = {值!r}")
        for 文件 in 遍历("能力定义.json"):
            数据 = json.loads(文件.read_text(encoding="utf-8"))
            if not isinstance(数据.get("版本"), str):
                违规.append(f"{文件.relative_to(系统根)} :: 包级版本缺失")
            for 能力 in 数据.get("能力列表", []):
                值 = 能力.get("版本")
                if not isinstance(值, str) or not __import__("re").match(语义版本正则, 值):
                    违规.append(f"{文件.relative_to(系统根)} :: {能力.get('能力id')} 版本 = {值!r}")
        self.assertEqual([], 违规[:20], f"发现 {len(违规)} 处包/能力版本不合法：{违规[:20]}")

    def test_依赖约束是范围不是版本(self):
        """依赖声明里的版本必须是运算符约束（强制参数），不许写成精确版本号。"""
        违规 = []
        for 顶层 in 包根目录:
            根 = 系统根 / 顶层
            if not 根.is_dir():
                continue
            for 文件 in sorted(根.rglob("能力定义.json")):
                if any(片段 in 文件.parts for 片段 in 跳过片段):
                    continue
                数据 = json.loads(文件.read_text(encoding="utf-8"))
                for 依赖 in 数据.get("依赖", []) or []:
                    值 = str(依赖.get("版本", ""))
                    if 值 and 值[0] not in "><=~^":
                        违规.append(f"{文件.relative_to(系统根)} :: 依赖 {依赖.get('能力')} 版本 = {值!r}")
        self.assertEqual([], 违规[:20], f"依赖约束写法不合法（应为 >=x.y.z）：{违规[:20]}")


if __name__ == "__main__":
    unittest.main()
