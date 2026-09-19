"""验证场景体检「扫描面为 0 判红」回归（哲学 1.4 空集不是通过）。

修前缺口（审计件 `开发文档/分析/审计_空转与死代码_20260919.md` B-3a）：
`开发工具/验证场景体检.py` 只要「不合格 0 个」就打印「全部通过」并退 0，
于是**一个含场景的包目录都没扫到**时同样报通过 —— 而它是编译口门禁清单的阻断项
（`开发工具/开发编译口/编译口.py:47`），「没看」被当成「看了没事」整块放行。

同一文件里另有两条同型（本测试一并钉住）：
- `--制品` 指向存在的空目录 ⇒ 累加口径下被「源码侧 136 个」洗白 ⇒ 曾报通过；
- `--制品`/`--根` 指向不存在的目录 ⇒ 只打印「跳过」⇒ 曾报通过；
- `状态码一致性预检` 0 个期望失败用例 ⇒ 曾打「状态码与网关映射表全部一致」对勾。

口径（本测试钉住的三条）：
1. 正常路径（真仓库 136 包 / 0 不合格）**必须仍退 0**，不许矫枉过正；
2. 任一目标扫描面为 0、或指定目录不存在 ⇒ **退 1** 且输出明确中文判红说明；
3. 判红时**不得**出现「全部通过」字样（「没看」与「通过」不许共用一词）。

跑法：python3.14 -m unittest 测试中心.开发工具.测试_验证场景体检扫描面判红
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

仓库根 = Path(__file__).resolve().parents[2]
体检脚本 = 仓库根 / "开发工具" / "验证场景体检.py"


def 跑体检(*参数: str, 超时秒: int = 240) -> tuple[int, str]:
    """以子进程真跑入口，返回（退出码, stdout+stderr）。只读，不改仓库任何文件。"""
    完成 = subprocess.run(
        [sys.executable, str(体检脚本), *参数],
        cwd=str(仓库根), capture_output=True, text=True, timeout=超时秒,
    )
    return 完成.returncode, (完成.stdout or "") + (完成.stderr or "")


def 造最小合法包(包目录: Path) -> None:
    """造一个能被验证器解析链吃下的场景包（引用 + 场景正文两层都合法）。

    判据不猜：格式照 `开发工具/HTML验证/场景加载._解析场景引用` 与
    `单步场景.验证步骤.从字典`（正向步骤必须带实断言）。
    """
    (包目录 / "验证场景").mkdir(parents=True, exist_ok=True)
    (包目录 / "验证场景引用.json").write_text(
        json.dumps({"契约版本": "验证场景/v1",
                    "验证场景引用": [{"场景文件": "验证场景/正向HTTP场景.json"}]},
                   ensure_ascii=False, indent=2),
        encoding="utf-8")
    (包目录 / "验证场景" / "正向HTTP场景.json").write_text(
        json.dumps({"契约版本": "验证场景/v1", "验证场景": [{
            "场景id": "夹具.最小正向链",
            "前置步骤": [],
            "目标步骤": [{
                "步骤id": "取文本",
                "能力id": "夹具.取文本",
                "参数": {"文本": "夹具"},
                "预期": {"成功": True, "状态码": 200,
                          "返回断言": {"必需字段": ["文本"]}},
            }],
            "清理步骤": [],
        }]}, ensure_ascii=False, indent=2),
        encoding="utf-8")


class 扫描面判红(unittest.TestCase):
    """空集不是通过：扫描面为 0 / 目录不存在 / 单目标空转，一律判红。"""

    def test_正常路径仍绿不矫枉过正(self) -> None:
        """真仓库（136 包 / 0 不合格）必须退 0 且报「全部通过」——修法不得误伤正常态。"""
        码, 出 = 跑体检()
        self.assertEqual(码, 0, f"正常路径应退 0，实得 {码}；输出：\n{出}")
        self.assertIn("全部通过", 出, 出)
        self.assertIn("扫描面", 出, 出)

    def test_最小合法夹具判绿(self) -> None:
        """单目标用法（只扫源码）扫到 1 个合法包、0 不合格 ⇒ 退 0。"""
        with tempfile.TemporaryDirectory(prefix="体检夹具_绿_") as 临时:
            造最小合法包(Path(临时) / "夹具包")
            码, 出 = 跑体检("--根", 临时)
        self.assertEqual(码, 0, f"扫到 1 个合法包应退 0，实得 {码}；输出：\n{出}")
        self.assertIn("全部通过", 出, 出)

    def test_根下零场景包判红(self) -> None:
        """--根 指向空目录（一个含场景包都没有）⇒ 退 1 + 「扫描面为 0」中文说明。"""
        with tempfile.TemporaryDirectory(prefix="体检夹具_空_") as 临时:
            (Path(临时) / "测试中心").mkdir()
            (Path(临时) / "开发工具").mkdir()
            码, 出 = 跑体检("--根", 临时)
        self.assertEqual(码, 1, f"扫描面为 0 应退 1，实得 {码}；输出：\n{出}")
        self.assertIn("扫描面为 0", 出, 出)
        self.assertNotIn("全部通过", 出, "判红时不得出现「全部通过」（没看 ≠ 通过）")

    def test_制品目标空转判红(self) -> None:
        """★同型缺口：源码侧扫到包、但 --制品 存在且 0 个场景包 ⇒ 也必须判红。

        修前这里是累加口径（源码 136 + 制品 0 = 「扫描面 136 个」）⇒ 单目标空转
        被总量洗白、整轮报通过。
        """
        with tempfile.TemporaryDirectory(prefix="体检夹具_空制品_") as 临时:
            码, 出 = 跑体检("--制品", 临时)
        self.assertEqual(码, 1, f"制品目标扫描面为 0 应退 1，实得 {码}；输出：\n{出}")
        self.assertIn("扫描面为 0", 出, 出)
        self.assertIn("制品", 出, 出)
        self.assertNotIn("全部通过", 出, "判红时不得出现「全部通过」")

    def test_制品目录不存在判红(self) -> None:
        """--制品 指向不存在的目录 ⇒ 退 1，不许只打印「跳过」再退 0。"""
        with tempfile.TemporaryDirectory(prefix="体检夹具_无制品_") as 临时:
            不存在 = str(Path(临时) / "并不存在的制品")
            码, 出 = 跑体检("--制品", 不存在)
        self.assertEqual(码, 1, f"目录不存在应退 1，实得 {码}；输出：\n{出}")
        self.assertIn("目录不存在", 出, 出)
        self.assertNotIn("全部通过", 出, "判红时不得出现「全部通过」")

    def test_状态码零对象不打全部一致(self) -> None:
        """包目录扫到了但没有期望失败用例 ⇒ 报「无对象可判」，**不得**打「全部一致」。"""
        with tempfile.TemporaryDirectory(prefix="体检夹具_零负向_") as 临时:
            造最小合法包(Path(临时) / "夹具包")
            码, 出 = 跑体检("--根", 临时)
        self.assertEqual(码, 0, f"有包无负向用例应退 0，实得 {码}；输出：\n{出}")
        self.assertIn("无对象可判", 出, 出)
        self.assertNotIn("状态码与网关映射表全部一致", 出,
                         "0 个对象不能证明任何一致性，不许打「全部一致」")


if __name__ == "__main__":
    unittest.main()
