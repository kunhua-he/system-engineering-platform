"""运行器临时根接入测试：工作区隔离、环境变量传递、保留物与清理失败门禁。

全部为真实测试（禁止桩）：通过 subprocess 调用 测试中心/运行测试.py
以 --测试文件 --并行数 2 真实运行两个工作包文件，验证：
1. 并行运行结束后工作区临时根目录被清理，子进程环境变量真实可达；
2. 清单中标记保留的资源不被删除（迁移到 工程缓存/保留制品/）；
3. 清理失败必须阻断门禁（返回非0）并留下 工程缓存/清理失败证据/；
4. 失败与超时中断路径 teardown 仍执行。
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import unittest
import uuid
from pathlib import Path

系统根 = Path(__file__).resolve().parents[2]
运行测试脚本 = 系统根 / "测试中心" / "运行测试.py"
验证运行目录 = 系统根 / "工程缓存" / "验证运行"
清理失败证据目录 = 系统根 / "工程缓存" / "清理失败证据"
保留制品目录 = 系统根 / "工程缓存" / "保留制品"

乙源码 = '''"""自检乙：简单通过用例（工作包并行占位）。"""
import unittest


class 通过测试(unittest.TestCase):
    def test_通过(self) -> None:
        self.assertEqual(1 + 1, 2)


if __name__ == "__main__":
    unittest.main()
'''

甲源码 = '''"""自检甲：断言工作包子进程环境变量与临时根真实可达。"""
import os
import unittest
from pathlib import Path


class 环境变量可达测试(unittest.TestCase):
    def test_任务id与工作区标识可达(self) -> None:
        self.assertTrue(os.environ["系统底座_验证运行id"])
        self.assertTrue(os.environ["系统底座_任务id"])
        self.assertTrue(os.environ["系统底座_工作区标识"])
        self.assertTrue(os.environ["系统底座_资源清单路径"])
        self.assertTrue(os.environ["TMPDIR"])

    def test_临时根与清单目录已创建(self) -> None:
        self.assertTrue(Path(os.environ["TMPDIR"]).is_dir())
        self.assertTrue(Path(os.environ["系统底座_资源清单路径"]).parent.is_dir())

    def test_记录工作区路径(self) -> None:
        (Path(os.environ["自检记录目录"]) / "工作区路径.txt").write_text(
            os.environ["TMPDIR"], encoding="utf-8",
        )


if __name__ == "__main__":
    unittest.main()
'''

丙源码 = '''"""自检丙：登记保留与非保留资源，验证清理边界与保留物迁移。"""
import os
import unittest
from pathlib import Path

from MCP工具箱.测试资源 import 登记资源


class 保留资源测试(unittest.TestCase):
    def test_登记保留与非保留资源(self) -> None:
        临时根 = Path(os.environ["TMPDIR"])
        清单 = Path(os.environ["系统底座_资源清单路径"])
        保留文件 = 临时根 / "保留证据.json"
        保留文件.write_text("保留内容", encoding="utf-8")
        登记资源(清单, 资源路径=str(保留文件), 临时根目录=临时根, 保留=True)
        临时文件 = 临时根 / "临时文件.txt"
        临时文件.write_text("临时内容", encoding="utf-8")
        登记资源(清单, 资源路径=str(临时文件), 临时根目录=临时根, 资源类型="文件")
        (Path(os.environ["自检记录目录"]) / "任务id.txt").write_text(
            os.environ["系统底座_任务id"], encoding="utf-8",
        )
        (Path(os.environ["自检记录目录"]) / "工作区路径.txt").write_text(
            os.environ["TMPDIR"], encoding="utf-8",
        )


if __name__ == "__main__":
    unittest.main()
'''

丁源码 = '''"""自检丁：登记不可删除资源，验证清理失败阻断门禁并留证据。"""
import os
import stat
import unittest
from pathlib import Path

from MCP工具箱.测试资源 import 登记资源


class 不可删除资源测试(unittest.TestCase):
    def test_登记不可删除目录(self) -> None:
        临时根 = Path(os.environ["TMPDIR"])
        清单 = Path(os.environ["系统底座_资源清单路径"])
        只读目录 = 临时根 / "只读目录"
        只读目录.mkdir()
        占位文件 = 只读目录 / "占位.txt"
        占位文件.write_text("占位", encoding="utf-8")
        os.chmod(占位文件, 0o000)
        os.chmod(只读目录, 0o000)
        try:
            os.chflags(占位文件, stat.UF_IMMUTABLE)
        except (AttributeError, OSError):
            pass
        登记资源(清单, 资源路径=str(只读目录), 临时根目录=临时根, 资源类型="目录")
        (Path(os.environ["自检记录目录"]) / "任务id.txt").write_text(
            os.environ["系统底座_任务id"], encoding="utf-8",
        )
        (Path(os.environ["自检记录目录"]) / "工作区路径.txt").write_text(
            os.environ["TMPDIR"], encoding="utf-8",
        )


if __name__ == "__main__":
    unittest.main()
'''

己源码 = '''"""自检己：断言失败的工作包，验证失败路径 teardown 仍执行。"""
import os
import unittest
from pathlib import Path


class 失败路径测试(unittest.TestCase):
    def test_记录工作区路径(self) -> None:
        (Path(os.environ["自检记录目录"]) / "工作区路径.txt").write_text(
            os.environ["TMPDIR"], encoding="utf-8",
        )

    def test_必然失败(self) -> None:
        self.assertTrue(False, "自检故意失败")


if __name__ == "__main__":
    unittest.main()
'''

睡眠源码 = '''"""自检睡：超长睡眠用于触发超时终止。"""
import time
import unittest


class 睡眠测试(unittest.TestCase):
    def test_长睡(self) -> None:
        time.sleep(120)


if __name__ == "__main__":
    unittest.main()
'''


class 运行器工作区测试(unittest.TestCase):
    def setUp(self) -> None:
        self.自检目录 = Path(__file__).resolve().parent / f"运行器自检_{uuid.uuid4().hex[:8]}"
        self.自检目录.mkdir(parents=True, exist_ok=True)
        self.旧记录目录 = os.environ.get("自检记录目录")
        os.environ["自检记录目录"] = str(self.自检目录)
        self.乙文件 = self.写自检文件("测试_乙.py", 乙源码)

    def tearDown(self) -> None:
        if self.旧记录目录 is None:
            os.environ.pop("自检记录目录", None)
        else:
            os.environ["自检记录目录"] = self.旧记录目录
        shutil.rmtree(self.自检目录, ignore_errors=True)

    def 写自检文件(self, 文件名: str, 源码: str) -> Path:
        文件 = self.自检目录 / 文件名
        文件.write_text(源码, encoding="utf-8")
        return 文件

    def 读取记录(self, 文件名: str) -> str:
        路径 = self.自检目录 / 文件名
        self.assertTrue(路径.is_file(), f"缺少自检记录：{文件名}")
        return 路径.read_text(encoding="utf-8").strip()

    def 运行工作包(self, 文件表: list[Path]) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(运行测试脚本), "--测试文件",
             *(str(文件) for 文件 in 文件表), "--并行数", "2"],
            cwd=系统根, capture_output=True, text=True, timeout=180,
        )

    def test_并行运行后工作区被清理且环境变量可达(self) -> None:
        甲 = self.写自检文件("测试_甲.py", 甲源码)
        结果 = self.运行工作包([甲, self.乙文件])
        self.assertEqual(结果.returncode, 0, 结果.stdout + 结果.stderr)
        工作区路径 = Path(self.读取记录("工作区路径.txt"))
        self.assertFalse(工作区路径.exists(), "工作区临时根目录未被清理")
        self.assertFalse(工作区路径.parent.exists(), "运行根目录未被清理")

    def test_保留资源不被删除并迁移到保留制品(self) -> None:
        丙 = self.写自检文件("测试_丙.py", 丙源码)
        结果 = self.运行工作包([丙, self.乙文件])
        self.assertEqual(结果.returncode, 0, 结果.stdout + 结果.stderr)
        任务id = self.读取记录("任务id.txt")
        保留文件 = 保留制品目录 / 任务id / "保留证据.json"
        self.assertTrue(保留文件.is_file(), f"保留资源丢失：{保留文件}")
        self.assertEqual(保留文件.read_text(encoding="utf-8"), "保留内容")
        临时文件 = 保留制品目录 / 任务id / "临时文件.txt"
        self.assertFalse(临时文件.exists(), "非保留资源不应被迁移")
        工作区路径 = Path(self.读取记录("工作区路径.txt"))
        self.assertFalse(工作区路径.exists(), "有保留物的工作区未被清理")
        shutil.rmtree(保留制品目录 / 任务id, ignore_errors=True)

    def test_清理失败必须阻断门禁并留下证据(self) -> None:
        丁 = self.写自检文件("测试_丁.py", 丁源码)
        结果 = self.运行工作包([丁, self.乙文件])
        self.assertNotEqual(结果.returncode, 0, "清理失败必须让门禁失败")
        self.assertIn("清理失败", 结果.stderr, 结果.stdout + 结果.stderr)
        任务id = self.读取记录("任务id.txt")
        证据文件 = 清理失败证据目录 / f"{任务id}.json"
        self.assertTrue(证据文件.is_file(), f"缺少清理失败证据：{证据文件}")
        证据 = json.loads(证据文件.read_text(encoding="utf-8"))
        self.assertEqual(证据["运行id"], 任务id)
        self.assertTrue(证据["路径"])
        self.assertTrue(证据["失败原因"])
        工作区 = Path(self.读取记录("工作区路径.txt"))
        self._恢复删除权限(工作区)
        shutil.rmtree(工作区, ignore_errors=True)
        shutil.rmtree(验证运行目录 / 任务id, ignore_errors=True)
        证据文件.unlink(missing_ok=True)
        self.assertFalse((验证运行目录 / 任务id).exists(), "清理失败残留未自我清理")

    @staticmethod
    def _恢复删除权限(根: Path) -> None:
        """清除不可变标记并恢复权限，避免测试留下永久污染。"""
        if not 根.exists():
            return
        候选 = [根]
        候选.extend(根.glob("只读目录/*"))
        候选.append(根 / "只读目录")
        for 文件 in 候选:
            try:
                os.chflags(文件, 0)
            except (AttributeError, OSError):
                pass
            try:
                os.chmod(文件, 0o755)
            except OSError:
                pass

    def test_失败路径仍执行teardown(self) -> None:
        己 = self.写自检文件("测试_己.py", 己源码)
        结果 = self.运行工作包([己, self.乙文件])
        self.assertNotEqual(结果.returncode, 0, "失败工作包必须让门禁失败")
        工作区路径 = Path(self.读取记录("工作区路径.txt"))
        self.assertFalse(工作区路径.exists(), "失败路径 teardown 未清理工作区")

    def test_超时中断仍执行teardown并清理进程组(self) -> None:
        import 测试中心.运行测试 as 运行测试模块

        睡 = self.写自检文件("测试_睡.py", 睡眠源码)
        任务id = 运行测试模块._生成任务id()
        结果 = 运行测试模块._运行单文件子进程(str(睡), 任务id, 0, 超时秒=2)
        self.assertEqual(结果["退出码"], 124, 结果["标准输出"] + 结果["标准错误"])
        self.assertFalse(Path(结果["临时根目录"]).exists(), "超时路径 teardown 未清理工作区")
        shutil.rmtree(验证运行目录 / 任务id, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
