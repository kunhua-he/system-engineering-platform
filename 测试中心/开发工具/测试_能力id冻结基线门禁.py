"""能力 id 冻结基线门禁单测：三档反向验证 + fail-closed 各形态 + 正向对照。

**为什么用夹具根**：判据「id 只增不改」要真验，必须有人真的把某条能力 id 从
``能力定义.json`` 里删掉；在真实仓库里删 id 就是「改各包能力定义」——越界。
故破坏全部落在 ``tempfile`` 夹具根（真实 包声明.json + 能力定义.json 两件套、
真实判据链），基线也写成夹具自己的文件。真实仓库只做「默认路径跑绿」与
「临时改名真基线验 fail-closed（改完立刻改回）」两件事。

直跑：``python3.14 -m unittest 测试中心.开发工具.测试_能力id冻结基线门禁``
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

if str(Path(__file__).resolve().parents[2]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

仓库根 = Path(__file__).resolve().parents[2]
门禁 = 仓库根 / "开发工具" / "能力id冻结基线门禁.py"
真基线 = 仓库根 / "开发文档" / "项目证据" / "能力id冻结基线.json"

能力1 = "夹具.包1.能力一"
能力2 = "夹具.包2.能力二"


def 写(路径: Path, 文本: str) -> None:
    路径.parent.mkdir(parents=True, exist_ok=True)
    路径.write_text(文本, encoding="utf-8")


def 写包(包目录: Path, 包id: str, 能力们: list[dict]) -> None:
    写(包目录 / "包声明.json", json.dumps(
        {"包id": 包id, "名称": 包目录.name, "类型": "支持库",
         "能力": [{"能力id": 条["能力id"], "名称": 条["能力id"].split(".")[-1]}
                for 条 in 能力们]}, ensure_ascii=False, indent=1))
    写(包目录 / "能力定义.json", json.dumps(
        {"包id": 包id, "版本": "1.0.0", "能力列表": 能力们}, ensure_ascii=False, indent=1))


def 能力条(能力id: str, 版本: str = "1.0.0", 参数: list | None = None) -> dict:
    return {"能力id": 能力id, "版本": 版本, "参数": 参数 or [],
            "返回": {"类型": "结果型", "值结构": {"值": "文本"}}, "错误码": ["参数不合法"]}


class 冻结门禁夹具(unittest.TestCase):
    def setUp(self) -> None:
        self.临时 = Path(tempfile.mkdtemp(prefix="能力id冻结单测_"))
        self.夹具 = self.临时 / "夹具根"
        self.示例包1 = self.夹具 / "支持库" / "后端" / "夹具包1"
        写包(self.示例包1, "支持库.后端.夹具包1", [能力条(能力1)])
        写包(self.夹具 / "支持库" / "后端" / "夹具包2", "支持库.后端.夹具包2", [能力条(能力2)])
        self.基线 = self.临时 / "夹具基线.json"
        结果 = subprocess.run(
            [sys.executable, str(门禁), str(self.夹具), "--冻结", "--基线", str(self.基线)],
            cwd=str(仓库根), capture_output=True, text=True)
        self.assertEqual(0, 结果.returncode, 结果.stdout + 结果.stderr)
        self.assertEqual(2, len(json.loads(self.基线.read_text(encoding="utf-8"))["条目"]))

    def tearDown(self) -> None:
        shutil.rmtree(self.临时, ignore_errors=True)

    def 跑(self) -> tuple[int, str]:
        结果 = subprocess.run(
            [sys.executable, str(门禁), str(self.夹具), "--基线", str(self.基线)],
            cwd=str(仓库根), capture_output=True, text=True)
        return 结果.returncode, 结果.stdout + 结果.stderr

    # ---- 三档完成判据 ----
    def test_基线态跑绿(self) -> None:
        码, 出 = self.跑()
        self.assertEqual(0, 码, 出)
        self.assertIn("通过", 出)

    def test_删一条基线里的id必红(self) -> None:
        """① 把能力1从 能力定义.json + 包声明.json 同步摘除 → 必红。"""
        写包(self.示例包1, "支持库.后端.夹具包1", [])
        码, 出 = self.跑()
        self.assertEqual(1, 码, 出)
        self.assertIn("能力id消失", 出)
        self.assertIn(能力1, 出)

    def test_改id名必红(self) -> None:
        """改名的老 id 消失 → 必红；新 id 同时作为「新增」报到（只增方向合法）。"""
        写包(self.示例包1, "支持库.后端.夹具包1", [能力条("夹具.包1.能力一改名")])
        码, 出 = self.跑()
        self.assertEqual(1, 码, 出)
        self.assertIn(能力1, 出)
        self.assertIn("新增能力id", 出)

    def test_基线文件缺失必红_fail_closed(self) -> None:
        """② 基线文件删掉 → 必红（fail-closed，不许静默放行）。"""
        self.基线.unlink()
        码, 出 = self.跑()
        self.assertEqual(1, 码, 出)
        self.assertIn("基线文件缺失", 出)
        self.assertIn("fail-closed", 出)

    def test_基线不可读必红_fail_closed(self) -> None:
        self.基线.write_text("{ 这不是 JSON", encoding="utf-8")
        码, 出 = self.跑()
        self.assertEqual(1, 码, 出)
        self.assertIn("基线文件不可读", 出)

    def test_基线条目为空必红_fail_closed(self) -> None:
        """空基线不是通过：形状非法同样判红。"""
        self.基线.write_text(json.dumps({"版本": 1, "条目": {}}, ensure_ascii=False),
                        encoding="utf-8")
        码, 出 = self.跑()
        self.assertEqual(1, 码, 出)
        self.assertIn("形状非法", 出)

    def test_扫描面为空必红_fail_closed(self) -> None:
        """空集不是通过：根下 0 条能力 id 一律判红。"""
        空根 = self.临时 / "空根"
        (空根 / "支持库").mkdir(parents=True, exist_ok=True)
        结果 = subprocess.run(
            [sys.executable, str(门禁), str(空根), "--基线", str(self.基线)],
            cwd=str(仓库根), capture_output=True, text=True)
        self.assertEqual(1, 结果.returncode, 结果.stdout + 结果.stderr)
        self.assertIn("扫描面为空", 结果.stdout + 结果.stderr)

    def test_恢复必绿(self) -> None:
        """③ 恢复基线 → 绿（先真破坏一次，再复原）。"""
        备份 = self.基线.read_text(encoding="utf-8")
        self.基线.unlink()
        码, _ = self.跑()
        self.assertEqual(1, 码)
        self.基线.write_text(备份, encoding="utf-8")
        码, 出 = self.跑()
        self.assertEqual(0, 码, 出)
        self.assertIn("通过", 出)

    # ---- 正向对照：防门禁退化成恒红 ----
    def test_契约变更允许但留痕(self) -> None:
        """已存 id 的内容指纹变化**不拦**，但要报到（契约变更合法，须留痕）。"""
        写包(self.示例包1, "支持库.后端.夹具包1",
            [能力条(能力1, 版本="1.1.0", 参数=[{"名称": "编码", "类型": "文本型"}])])
        码, 出 = self.跑()
        self.assertEqual(0, 码, 出)
        self.assertIn("内容指纹变化", 出)

    def test_新增id允许只报(self) -> None:
        """「只增」是合法方向：新增 id 不拦，只报。"""
        写包(self.示例包1, "支持库.后端.夹具包1", [能力条(能力1), 能力条("夹具.包1.能力三")])
        码, 出 = self.跑()
        self.assertEqual(0, 码, 出)
        self.assertIn("新增能力id", 出)
        self.assertIn("夹具.包1.能力三", 出)


class 真实仓库口径(unittest.TestCase):
    """真实仓库默认路径：必须绿；基线缺失必须红；基线本身不得被测试破坏。"""

    def test_默认路径跑绿(self) -> None:
        结果 = subprocess.run([sys.executable, str(门禁)], cwd=str(仓库根),
                             capture_output=True, text=True)
        出 = 结果.stdout + 结果.stderr
        self.assertEqual(0, 结果.returncode, 出)
        self.assertIn("通过", 出)
        基线 = json.loads(真基线.read_text(encoding="utf-8"))
        self.assertEqual("装配口径", 基线["口径"])
        self.assertEqual(基线["能力数"], len(基线["条目"]))
        # 装配口径既是 679 条这一事实的落盘参照（口径裁定见 能力面与拆分清单 §1.1）
        self.assertGreater(len(基线["条目"]), 600)

    def test_真基线缺失必须fail_closed(self) -> None:
        """真基线缺失 ⇒ fail-closed 判红（用**临时空目录**，不碰真基线）。

        2026-09-19（开工-20260919-193541-2a8e）改法：原实现把**仓库真基线**
        rename 成 `.单测备份`，靠 `finally` 还原。实测真跑级超时被 kill 时
        `finally` 不执行 → 真基线永久卡在备份名 → 发布门禁连锁判红
        （「基线文件缺失」）。测试**不得破坏共享状态**（哲学 12.1）：改为把
        `--基线` 指向一个**不存在的临时路径**，同样触发 fail-closed 分支，
        且对仓库零副作用（无需还原、中断也安全）。
        """
        不存在的基线 = Path(tempfile.mkdtemp(prefix="冻结基线空目录_")) / "不存在的基线.json"
        self.assertFalse(不存在的基线.exists())
        结果 = subprocess.run(
            [sys.executable, str(门禁), str(仓库根), "--基线", str(不存在的基线)],
            cwd=str(仓库根), capture_output=True, text=True)
        出 = 结果.stdout + 结果.stderr
        self.assertEqual(1, 结果.returncode, 出)
        self.assertIn("基线文件缺失", 出)
        # 真基线全程未被触碰
        self.assertTrue(真基线.is_file(), "真基线不得被测试触碰")

    def test_真基线口径与装配注册表一致(self) -> None:
        """口径纪律：基线 id 集必须是**装配口径**（与 正式包索引.能力所有者 相等）。

        这条断言的意义：防止有人用 `包声明.json` rglob 累加口径（845 虚高）重冻基线，
        把「聚合父包重复登记」当能力面锁进基线。
        """
        if str(仓库根) not in sys.path:
            sys.path.insert(0, str(仓库根))
        from 开发工具.项目编译.正式包索引 import 构建索引
        所有者 = set(构建索引(仓库根).get("能力所有者") or {})
        基线 = set(json.loads(真基线.read_text(encoding="utf-8"))["条目"])
        self.assertEqual(所有者, 基线,
                         f"基线 id 集与装配口径不一致：装配多 {sorted(所有者 - 基线)[:5]}；"
                         f"基线多 {sorted(基线 - 所有者)[:5]}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
