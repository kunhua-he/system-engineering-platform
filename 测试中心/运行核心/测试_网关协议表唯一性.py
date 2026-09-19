"""网关协议表唯一性回归：协议表只能有一份字面量定义者，且差异码不得再丢。

缺陷溯源（审计 I-2 / I-3，2026-09-19 收口）：`运行核心/统一网关/协议表.py` 曾是
`网关核心.py` 四张协议表的**第二份副本**。该文件全仓零 `.py` import（无人引用），
而 `网关核心.py` 才是所有调用方与门禁实际读的那一份 —— 副本因此长期无人校对，
`公开错误说明表` 与正本分叉 5 条（正本 348 键，副本只有 343 键）：副本缺
`内容已变更`/`内容指纹不可用`/`根目录不存在`/`文档不可读`/`文档数超出上限`。

为什么危险（不是「多一个没人用的文件」那么轻）：两份同名表并存时，改协议的人
按文件名直觉可能去改副本，改完门禁与网关照旧读正本 → 改动**静默不生效**。

因此本测试守三条判据，任一条被破坏即红：
1. 副本文件不得复活（有人「补回来」= 分叉风险立刻回归）；
2. 四张表的**模块级字面量赋值者**全仓唯一，分别落在 `参数别名表.py` / `操作协议表.py` /
   `错误说明表.py`（2026-09-19 网关核心按职责拆开后各自独立成文件；门禁
   `公开调用完整性门禁`/`错误码文案派生`/`运行发布门禁` 都按「文件路径 +
   模块级变量名」做 AST 读**字面量赋值**，把表搬走写成再导出读不到 → 判据面塌缩）；
3. 那次分叉丢掉的 5 个码必须在唯一正本内（防止「删了副本顺手也删掉码」）。
"""
from __future__ import annotations

import ast
import sys
import unittest
from pathlib import Path

系统根 = Path(__file__).resolve().parents[2]
if str(系统根) not in sys.path:
    sys.path.insert(0, str(系统根))

# 应被删除的重复副本（回归禁区）
副本路径 = 系统根 / "运行核心" / "统一网关" / "协议表.py"
# 四张协议表的唯一正本（**按表分派**）：2026-09-19 网关核心按职责拆开后，
# 四张表**全部**迁到各自职责文件；都是「模块级字面量赋值」，门禁按「路径 + 变量名」读得到。
表正本表 = {
    "能力参数别名表": "运行核心/统一网关/协议/参数别名表.py",
    "允许操作表": "运行核心/统一网关/协议/操作协议表.py",
    "操作权限表": "运行核心/统一网关/协议/操作协议表.py",
    "公开错误说明表": "运行核心/统一网关/协议/错误说明表.py",
}
表名集 = tuple(表正本表)
# 旧址（表搬走后不得再留字面量赋值，防「双份表」静默分叉）
旧址路径 = "运行核心/统一网关/网关核心.py"
# 副本曾丢失的 5 个码（分叉实证）
分叉丢失码 = ("内容已变更", "内容指纹不可用", "根目录不存在", "文档不可读", "文档数超出上限")

排除目录段 = frozenset({
    "工程缓存", "开发文档", "__pycache__", ".git", ".venv", "node_modules",
    "参考资料", "dist", "build", ".egg-info",
})


def _静态字面量定义者(变量名: str) -> list[str]:
    """全仓 AST 扫描：谁是该变量的**模块级字面量赋值**者（按相对路径，升序）。"""
    命中: list[str] = []
    for 文件 in sorted(系统根.rglob("*.py")):
        if any(段 in 文件.parts for 段 in 排除目录段):
            continue
        try:
            语法树 = ast.parse(文件.read_text(encoding="utf-8"))
        except (OSError, SyntaxError, UnicodeDecodeError):
            continue
        for 节点 in 语法树.body:
            if not isinstance(节点, ast.Assign):
                continue
            if any(isinstance(目标, ast.Name) and 目标.id == 变量名
                   for 目标 in 节点.targets):
                命中.append(文件.relative_to(系统根).as_posix())
                break
    return 命中


def _读正本表(变量名: str):
    """读该表的**当前正本**（按 `表正本表` 分派；迁址后不再固定读网关核心.py）。"""
    语法树 = ast.parse((系统根 / 表正本表[变量名]).read_text(encoding="utf-8"))
    for 节点 in 语法树.body:
        if isinstance(节点, ast.Assign) and any(
                isinstance(目标, ast.Name) and 目标.id == 变量名
                for 目标 in 节点.targets):
            return ast.literal_eval(节点.value)
    raise AssertionError(f"{表正本表[变量名]} 内找不到模块级字面量赋值 {变量名}")


class 网关协议表唯一性(unittest.TestCase):
    def test_重复副本文件不得复活(self) -> None:
        self.assertFalse(
            副本路径.exists(),
            f"重复副本 {副本路径.relative_to(系统根)} 又出现了：它与 {表正本表['公开错误说明表']} 是同名"
            "两份协议表，无人 import 因而无人校对，必然再次分叉。协议表只留正本一份，"
            "要加码/改文案请直接改正本。")

    def test_四张表的字面量定义者全仓唯一(self) -> None:
        for 表名 in 表名集:
            with self.subTest(表=表名):
                期望 = [表正本表[表名]]
                定义者 = _静态字面量定义者(表名)
                self.assertEqual(
                    定义者, 期望,
                    f"{表名} 的模块级字面量赋值者应只有 {期望[0]} 一处，"
                    f"实测 {定义者}。多出来的那份即重复腿；删成再导出也不行 —— "
                    "门禁按「文件路径 + 模块级变量名」读字面量赋值，读不到即判据塌缩。")

    def test_搬走的表在旧址不得再留字面量(self) -> None:
        """表已迁到独立文件后，旧址不得再有它的模块级字面量赋值（防双份分叉）。"""
        for 表名, 正本 in 表正本表.items():
            if 正本 == 旧址路径:
                continue
            with self.subTest(表=表名):
                定义者 = _静态字面量定义者(表名)
                self.assertNotIn(
                    旧址路径, 定义者,
                    f"{表名} 已迁到 {正本}，旧址 {旧址路径} 不得再有字面量赋值"
                    f"（实测 {定义者}）—— 两份同名表必然分叉，且改错那份会静默不生效。")

    def test_分叉丢失的五个码都在正本内(self) -> None:
        说明表 = _读正本表("公开错误说明表")
        self.assertIsInstance(说明表, dict)
        缺失 = [码 for 码 in 分叉丢失码 if 码 not in 说明表]
        self.assertEqual(
            缺失, [],
            f"公开错误说明表 缺这些码：{缺失}。它们是 2026-09-19 那次副本分叉的"
            "实证差异（正本有、副本无）；码缺登会让 HTTP 落默认 500 且错误说明"
            "回落「请求处理失败」，等于对调用方隐藏真实原因。")

    def test_正本表非空且与状态映射不矛盾(self) -> None:
        """非恒真前提：先证明正本真读得到，再谈唯一性，避免「都读不到也算一致」。"""
        self.assertGreater(len(_读正本表("公开错误说明表")), 300)
        self.assertEqual(len(_读正本表("允许操作表")), 13)

    def test_迁址后新落点真是字面量赋值者(self) -> None:
        """新落点必须是**字面量赋值**（不是再导出）——否则门禁读到 None 会静默塌缩。"""
        定义者 = _静态字面量定义者("公开错误说明表")
        self.assertEqual(
            定义者, ["运行核心/统一网关/协议/错误说明表.py"],
            f"公开错误说明表 的字面量赋值者应是新落点，实测 {定义者}。"
            "写成再导出会让门禁 AST 读取器拿到 None → 判据静默塌缩（假绿）。")


if __name__ == "__main__":
    unittest.main()
