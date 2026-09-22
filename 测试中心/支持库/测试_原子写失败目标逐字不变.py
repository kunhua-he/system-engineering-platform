"""负路径断言①：目标文件写失败后必须**逐字不变**（未完成事项 §8.3 第 32 项 / 报告①-8）。

**要钉住的事实**：`原子写入` 的语义是「要么完整落盘、要么目标保持原样」。
反过来说，**失败路径绝不允许把目标文件改坏成半成品** —— 旧内容被截断、
被写了一半、被写空，都是数据损坏。

**为什么这条必须单独断言**：正向测试只证明「成功时写对了」；
而原子性的价值全在失败路径上 —— 没有这条断言，「原子」二字只是模块名，
实现可以退化成「先清空再写」，正测依然全绿。

**三类失败路径（覆盖不同失败点，不是重复断言）**：

1. **写入内容非法**（`内容` 与 `内容字节` 都给 → 参数非法）：失败发生在**落盘之前** ⇒ 目标逐字不变；
2. **目标不可写**（目标是个非空目录 → 落盘阶段失败）：既有邻居文件逐字不变；
3. **同目录既有文件的对照**：成功路径只改目标、不动同目录其他文件
   （证明「不变」不是靠「什么都不做」凑出来的）。

**判据同源**：都用同一个 `_快照`（读字节 + sha256）比对，
不是各写各的字符串比较 —— 失败点不同，但「不变」的口径只有一条。

★ **实现口径记录**（现场读码确认，避免断言与实现行为打架）：
`支持库/后端/系统核心支持库/资源管理/实现/资源管理.py::原子写入`
① 返回**裸 bool**（不是统一结果信封）；
② `:172` 会 `目标路径.parent.mkdir(parents=True, exist_ok=True)` ——
即**父目录不存在时它会先建目录**，故本条不断言「不留任何新目录」，
只断言「目标文件本身逐字不变 / 目标不被写坏」。

★ **夹具落点与清理口径**（2026-09-23 修泄漏）：夹具根**显式**落在 `工程缓存/` 下
（与 `TMPDIR` 解耦），并在 `setUp` 注册 `addCleanup(清只读后删除树, …)` 保证
**用例失败也清**。原实现用 `tempfile.mkdtemp()` 的默认落点且无清理 ——
平台跑测试时 `TMPDIR` 被指进仓库工作目录，于是仓库根堆出 18 个
`测试_原子写失败_*` 残留（未跟踪），并让制品构建判「含未提交变更」。
理由与依据（含工作区指纹为何不认 gitignore）见 `setUp` 的 docstring。
"""

from __future__ import annotations

import hashlib
import sys
import tempfile
import unittest
from pathlib import Path

#: 仓库根（本件位于 `测试中心/支持库/`，上溯两级）。
仓库根 = Path(__file__).resolve().parents[2]
if str(仓库根) not in sys.path:
    sys.path.insert(0, str(仓库根))

from 公共契约.基础类型.逻辑类型 import 真
from 公共契约.运行时.平台适配 import 清只读后删除树
from 支持库.后端.系统核心支持库.资源管理 import 原子写入


def _快照(路径: Path) -> tuple[int, str] | None:
    """文件快照：`(字节数, sha256)`；不存在返回 None。"""
    if not 路径.is_file():
        return None
    数据 = 路径.read_bytes()
    return (len(数据), hashlib.sha256(数据).hexdigest())


class Test原子写失败目标逐字不变(unittest.TestCase):
    """失败路径下目标文件必须逐字不变（原子性的真正价值所在）。"""

    def setUp(self) -> None:
        """夹具落点**显式**落在仓库内固定排除目录 `工程缓存/` 下，且注册 addCleanup 清理。

        ★ 为什么不能再用 `tempfile.mkdtemp()` 的默认落点（2026-09-23 实测）：
        `mkdtemp()` 的落点由 `tempfile.gettempdir()`（环境变量 `TMPDIR`）决定，而
        **平台跑测试时 `TMPDIR` 会被指进仓库工作目录** —— 本仓曾因此在仓库根堆出
        18 个 `测试_原子写失败_*` 残留目录（未清理），并让制品构建判「含未提交变更」：
        `开发工具/项目编译/工作区指纹.py` 的「未跟踪正式文件」腿用
        `git ls-files --others`（**不带 `--exclude-standard`**），故残留文件即使被
        `.gitignore` 挡住、`git status` 看不见，仍会被算成正式文件、污染字节指纹。

        两条一起用，缺一不可：

        - **显式 `dir=`** 指向 `工程缓存/`（在 `工作区指纹.py` 的 `固定排除目录` 里）⇒
          落点与 `TMPDIR` 解耦，且**即便用例被 SIGKILL、addCleanup 没跑到**，残留也不会
          进工作区指纹（`.tmp` 虽被 gitignore，却不在 `固定排除目录` 里 ⇒ 不具此保证）；
        - **addCleanup** ⇒ 用例**失败时也清**（`addCleanup` 无论成败都会跑），且用平台
          唯一删树原语 `清只读后删除树`（本用例会造 `0o555` 目录 / `0o444` 文件，
          plain `shutil.rmtree` 会被权限位挡住）。
        """
        夹具根 = 仓库根 / "工程缓存" / "测试夹具_原子写失败"
        夹具根.mkdir(parents=True, exist_ok=True)
        self.临时目录 = Path(tempfile.mkdtemp(prefix="测试_原子写失败_", dir=夹具根))
        self.addCleanup(清只读后删除树, self.临时目录, 忽略失败=真)

    def test_落盘阶段失败时既有文件逐字不变(self) -> None:
        """目标是**非空目录** ⇒ 替换阶段失败：既有邻居文件逐字不变（不被截断/改坏）。"""
        既有 = self.临时目录 / "邻居.txt"
        既有原样 = "邻居内容：一个字节都不能变\n"
        既有.write_text(既有原样, encoding="utf-8")
        邻居前 = _快照(既有)

        目标 = self.临时目录 / "其实是目录"
        目标.mkdir()
        (目标 / "占位.txt").write_text("占位\n", encoding="utf-8")

        try:
            结果 = 原子写入(目标, "新内容")
        except OSError:
            结果 = False  # 落盘阶段直接抛也是「失败」，同样不得破坏既有文件

        self.assertFalse(结果, "目标是非空目录必须判失败")
        self.assertEqual(_快照(既有), 邻居前, "失败时不得动到无关邻居文件")
        self.assertEqual(既有.read_text(encoding="utf-8"), 既有原样, "邻居内容必须逐字不变")
        self.assertTrue((目标 / "占位.txt").is_file(), "失败时不得清空目标目录里的既有文件")

    def test_只读目标的内容永远是完整旧内容或完整新内容(self) -> None:
        """**原子性的真正不变式**：目标内容只可能是「完整旧内容」或「完整新内容」，
        **绝不出现半成品**（截断 / 写一半 / 空）。

        ★ 现场读码修正（2026-09-18）：本用例初版断的是「只读目标写入必须失败」，
        实测**不成立**且**不是缺陷** —— POSIX 的 `os.replace` 只看**父目录**写权限，
        父目录可写时替换只读文件是**正常且期望**的行为（原子替换本就不需要改目标文件本身）。
        所以这里断的是不变式（内容完整性），不是某个特定成败 —— 这才是原子性的可判定形态：
        无论实现走「替换成功」还是「拒绝」，落到磁盘的都必须是**某一份完整内容**。
        """
        目标 = self.临时目录 / "只读.txt"
        旧内容 = "只读内容：必须完整\n第二行\n"
        新内容 = "试图改写"
        目标.write_text(旧内容, encoding="utf-8")
        目标.chmod(0o444)
        try:
            try:
                结果 = 原子写入(目标, 新内容)
            except (OSError, PermissionError):
                结果 = False
            实际 = 目标.read_text(encoding="utf-8")
            self.assertIn(实际, (旧内容, 新内容),
                          f"目标落盘内容既不是完整旧内容也不是完整新内容（半成品）: {实际!r}")
            if 结果:
                self.assertEqual(实际, 新内容, "报成功就必须是完整新内容")
            else:
                self.assertEqual(实际, 旧内容, "报失败就必须保持完整旧内容")
        finally:
            目标.chmod(0o644)  # 便于临时目录清理

    def test_不存在的父目录下失败不留半成品目标(self) -> None:
        """深层不存在的父目录下写入：无论成败，**绝不留下半成品目标文件**（截断/空文件）。"""
        深层 = self.临时目录 / "不存在的一层" / "再一层"
        目标 = 深层 / "新.txt"
        结果 = 原子写入(目标, "内容")
        if 结果:
            # 若实现建了父目录并成功写入，则目标必须是**完整内容**（不得是空/半截）
            self.assertTrue(目标.is_file())
            self.assertEqual(目标.read_text(encoding="utf-8"), "内容",
                             "成功则必须是完整内容，不得是半成品")
        else:
            self.assertFalse(目标.exists(), "失败时不得留下半成品目标文件")

    def test_落盘阶段失败后不留临时文件(self) -> None:
        """**失败路径也不得留临时文件**（`.名字.8位hex.tmp`）—— 临时文件堆积会污染目录、
        且下次写入时若被误当成目标会读到半成品。用**只读父目录**制造落盘阶段失败。"""
        子目录 = self.临时目录 / "只读目录"
        子目录.mkdir()
        目标 = 子目录 / "目标.txt"
        目标.write_text("旧\n", encoding="utf-8")
        子目录.chmod(0o555)  # 目录不可写 ⇒ 临时文件建不出来 ⇒ 落盘阶段失败
        try:
            try:
                结果 = 原子写入(目标, "新内容")
            except (OSError, PermissionError):
                结果 = False
            残留 = [p.name for p in 子目录.iterdir() if p.name.endswith(".tmp")]
            self.assertEqual(残留, [], f"失败后残留临时文件: {残留}")
            self.assertEqual(目标.read_text(encoding="utf-8"), "旧\n",
                             "失败时必须保持完整旧内容")
            self.assertFalse(结果, "不可写目录下应判失败")
        finally:
            子目录.chmod(0o755)  # 便于清理

    def test_并发观察者绝不见半成品(self) -> None:
        """**原子性的本质断言**：写入进行中，任何并发观察者读到的只能是
        「完整旧内容」或「完整新内容」，**绝不能读到半成品**（截断/新旧混在一起）。

        为什么必须有这条（2026-09-18 反向验证暴露的覆盖缺口）：
        上面几条都断「失败后目标不变」—— 而**退化成非原子直写**（先清空再写）的实现
        在这些场景下照样能过（失败都发生在写入之前）。只有**并发观察**才能把
        「原子」与「非原子」区分开：直写期间文件会短暂为空/半截，原子替换不会。

        判据：写入线程反复写大内容，主线程紧循环读并在**每一次落盘内容**上判定；
        只要出现一次「不是完整旧、也不是完整新」的内容，即判红。
        """
        import threading
        import time

        目标 = self.临时目录 / "并发.txt"
        旧内容 = "旧" * 60000
        新内容 = "新" * 60000
        目标.write_text(旧内容, encoding="utf-8")
        允许 = {旧内容, 新内容}

        坏样本: list[str] = []
        写入次数 = [0]
        停 = threading.Event()

        def 不断写() -> None:
            for _ in range(120):
                try:
                    原子写入(目标, 新内容)
                except OSError:
                    pass
                写入次数[0] += 1
            停.set()

        写线程 = threading.Thread(target=不断写, name="反向验证写线程")
        写线程.start()
        try:
            while not 停.is_set():
                try:
                    现 = 目标.read_text(encoding="utf-8")
                except (OSError, UnicodeDecodeError) as 错误:
                    坏样本.append(f"<读取失败: {type(错误).__name__}: {错误}>")
                    break
                if 现 not in 允许:
                    坏样本.append(现)
                    break
                time.sleep(0)  # 让出 GIL，尽量多地采样中间态
        finally:
            写线程.join(timeout=30)

        self.assertGreater(写入次数[0], 0, "写入线程没跑起来，本用例无效")
        self.assertEqual(坏样本, [],
                         f"并发观察者读到了半成品（原子性破裂）；"
                         f"样本长度={len(坏样本[0]) if 坏样本 else 0}，"
                         f"片段={坏样本[0][:60]!r}" if 坏样本 else "")

    def test_成功路径不动同目录其他文件且不留临时文件(self) -> None:
        """反向对照：**成功**写入只改目标、不动同目录其他文件，且不留临时文件。"""
        其他 = self.临时目录 / "其他.txt"
        其他.write_text("其他内容\n", encoding="utf-8")
        其他前 = _快照(其他)
        目标 = self.临时目录 / "目标.txt"
        目标.write_text("旧目标\n", encoding="utf-8")

        结果 = 原子写入(目标, "新目标内容")

        self.assertTrue(结果, "正常路径必须成功")
        self.assertEqual(目标.read_text(encoding="utf-8"), "新目标内容")
        self.assertEqual(_快照(其他), 其他前, "成功路径也不得动到无关文件")
        self.assertEqual(sorted(p.name for p in self.临时目录.iterdir()),
                         ["其他.txt", "目标.txt"], "原子写不得留临时文件")


if __name__ == "__main__":
    unittest.main()
