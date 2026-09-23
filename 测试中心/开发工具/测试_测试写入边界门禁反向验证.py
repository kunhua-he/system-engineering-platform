"""反向验证：`测试写入边界门禁` 的两处判据盲点、接收者位缺陷、A 档收口与判据四（2026-09-23）。

**为什么要有这一件**：本门禁的判据面全是「静态解析 + 存量冻结」，判据自己**最容易**出的错
不是「判红太多」而是「**判据在 ≠ 判据覆盖**」—— 解析器少认一种形态，判据就整片放行而
输出仍然显示「零违规」。故每一处收口都配一条**反向样本**：喂进去必须被判到，
且**同一条样本在改前必须是放行**（否则这条测试证明不了判据变强了）。

| 用例组 | 钉住的事实 | 改前（盲）行为 |
|---|---|---|
| `Test盲点一dir实参` | `tempfile` 一族的落点**由 `dir=` 决定** | 不看 `dir=`，一律判「临时落点 ⇒ 放行」 |
| `Test盲点二运行时临时根` | 运行时临时根在仓库内**非**固定排除目录 ⇒ 不认（fail-closed） | 只问「在不在仓库外」，且问的是**门禁进程自己**的环境 |
| `Test接收者位缺陷` | 模块限定调用的目标在**位置实参位** | 取成模块名 `os`/`shutil` ⇒ 解析不出 ⇒ 未解析 |
| `Test夹具根写在setUp` | `dir=` 必须在**书写处**作用域解析 | 拿使用处的表解析 ⇒ 假判未解析 |
| `TestA档收口` | 落点钉进 `工程缓存/` 即判「受管写」；判据不空转 | 只判「临时落点」 |
| `Test判据四临时根未清` | `mkdtemp`/`mkstemp` 的**根**必须在清理面上被清 | **此前根本没有这一判据** ⇒ 建了不清全不报 |
| `Test判据四不误判已清` | 四条等效清理腿（addCleanup / 收尾钩子 / try-finally / 登记表）**都算清过** | 不适用（防的是判据自己把已清的判成违规） |
"""

from __future__ import annotations

import ast
import sys
import textwrap
import unittest
from pathlib import Path

仓库根 = Path(__file__).resolve().parents[2]
if str(仓库根) not in sys.path:
    sys.path.insert(0, str(仓库根))

from 公共契约.基础类型.逻辑类型 import 真
from 公共契约.运行时.平台适配 import 清只读后删除树
from 开发工具 import 测试写入边界门禁 as 门禁

#: 受管临时根（仓库内固定排除目录 `工程缓存/` 下）：本件自己的夹具落点，
#: 与测试运行时的 `TMPDIR` 解耦（见 `开发工具/测试写入边界门禁.py` 的判据一表）。
受管临时根 = 仓库根 / "工程缓存" / "测试临时"
受管临时根.mkdir(parents=True, exist_ok=True)

#: 片段统一抬头：`仓库根` / `受管临时根` 都按门禁能解析的形态给
#: （`Path(__file__)` 派生 + 仓库内受管字面量）。
_头 = """
import tempfile
from pathlib import Path

仓库根 = Path(__file__).resolve().parents[2]
受管临时根 = 仓库根 / "工程缓存" / "测试临时"


def test_用例():
"""


def _片段(正文: str, *, 带头: bool = True) -> str:
    """组装一段「像 `测试中心/**.py` 的测试源码」。

    只对**非空行**取公共缩进去缩进（空行与结尾的 `'''` 行不参与），
    避免手写缩进错位（反向验证实测过 `IndentationError`）。
    """
    源 = (_头 + 正文) if 带头 else 正文
    行 = [行 for 行 in 源.splitlines() if 行.strip()]
    return textwrap.dedent("\n".join(行)) + "\n"


def _扫片段(源: str) -> list[tuple[str, str, str]]:
    """把一段测试源码按门禁的扫描口径走一遍，回 `(动作, 结论, 目标表达式)` 逐处。"""
    树 = ast.parse(源)
    变量表: dict[str, ast.AST] = {}
    门禁._赋值收集(树, 变量表)
    实例属性, 实例定义域 = 门禁._全文件实例属性(树, 变量表)
    变量表.update(实例属性)
    出: list[tuple[str, str, str]] = []
    for 节点, 作用域表 in 门禁._带作用域(树, 变量表):
        if not isinstance(节点, ast.Call):
            continue
        动作, 目标们 = 门禁._写动作目标(节点, 作用域表)
        for 目标 in 目标们:
            结论, _ = 门禁.判目标(目标, 作用域表, 实例定义域=实例定义域)
            出.append((动作, 结论, 门禁._表达式文本(目标)))
    return 出


def _结论(源: str) -> list[str]:
    return [结论 for _, 结论, _ in _扫片段(源)]


class Test盲点一dir实参(unittest.TestCase):
    """`dir=` 必须核：落点由 `dir=` 决定，不由 `tempfile` 决定。"""

    def test_dir指仓库内相对路径判仓库内写(self) -> None:
        源 = _片段('''
            根 = Path(tempfile.mkdtemp(prefix="夹具_", dir="模块库"))
            (根 / "结果.json").write_text("{}", encoding="utf-8")
        ''')
        self.assertEqual(_结论(源), ["仓库内写"],
                         "`mkdtemp(dir='模块库')` 必须判「仓库内写」；"
                         "改前这条是「放行」（不看 dir= ⇒ 假绿）")

    def test_dir指受管目录判受管写(self) -> None:
        源 = _片段('''
            根 = Path(tempfile.mkdtemp(prefix="夹具_", dir=受管临时根))
            (根 / "结果.json").write_text("{}", encoding="utf-8")
        ''')
        self.assertEqual(_结论(源), ["受管写"])

    def test_dir指仓库外绝对路径仍放行(self) -> None:
        源 = _片段('''
            根 = Path(tempfile.mkdtemp(prefix="夹具_", dir="/tmp"))
            (根 / "结果.json").write_text("{}", encoding="utf-8")
        ''')
        self.assertEqual(_结论(源), ["放行"])

    def test_dir是函数形参解析不出判未解析(self) -> None:
        """`dir=str(输出目录.parent)` 形态（形参解析不出）⇒ fail-closed 判未解析。

        这正是 `测试中心/支持库/测试_文字文档.py` / `测试_演示文稿.py` 收口前的形态
        —— 它们已改为 `dir=受管临时根`（受管写）。
        """
        源 = _片段('''
            import tempfile
            from pathlib import Path

            def 转换(输出目录):
                根 = Path(tempfile.mkdtemp(prefix="夹具_", dir=str(输出目录.parent)))
                (根 / "结果.json").write_text("{}", encoding="utf-8")
        ''', 带头=False)
        self.assertEqual(_结论(源), ["未解析"])

    def test_三个位置实参形态的dir也要核(self) -> None:
        """`mkdtemp(后缀, 前缀, dir)` 的**第 3 位置实参**同样是落点。"""
        源 = _片段('''
            根 = Path(tempfile.mkdtemp(None, "夹具_", "模块库"))
            (根 / "结果.json").write_text("{}", encoding="utf-8")
        ''')
        self.assertEqual(_结论(源), ["仓库内写"])


class Test盲点二运行时临时根(unittest.TestCase):
    """无 `dir=` 时按**运行时临时根**判；且「不安全」必须 fail-closed 判未解析。"""

    def setUp(self) -> None:
        self.原缓存 = 门禁._运行时临时根缓存
        self.addCleanup(self._还原)

    def _还原(self) -> None:
        门禁._运行时临时根缓存 = self.原缓存

    def _片段无dir(self) -> str:
        return _片段('''
            根 = Path(tempfile.mkdtemp(prefix="夹具_"))
            (根 / "结果.json").write_text("{}", encoding="utf-8")
        ''')

    def test_临时根安全时放行(self) -> None:
        门禁._运行时临时根缓存 = True
        self.assertEqual(_结论(self._片段无dir()), ["放行"])

    def test_临时根不安全时判未解析(self) -> None:
        """临时根落在仓库内**非**固定排除目录（`TMPDIR=仓库根`）⇒ 不认（fail-closed）。

        改前这条**同样**判未解析 —— 但改前它读的是**门禁进程自己**的环境：门禁跑在
        `TMPDIR` 在仓库外的环境里就判放行，而**测试进程**的 `TMPDIR` 被指进仓库时
        落点照样进仓库。收口后判据只认「运行时临时根是否安全」这一个问题，
        并把「测试进程的临时根门禁侧读不到」如实印在判据行上（见 `运行时临时根说明`）。
        """
        门禁._运行时临时根缓存 = False
        self.assertEqual(_结论(self._片段无dir()), ["未解析"])

    def test_判据依据的临时根会如实打印(self) -> None:
        self.assertIn("门禁进程自己的", 门禁.运行时临时根说明())

    def test_固定排除目录取自工作区指纹单一事实源(self) -> None:
        from 开发工具.项目编译.工作区指纹 import 固定排除目录
        self.assertEqual(tuple(门禁._固定排除目录表()), tuple(固定排除目录))
        self.assertIn("工程缓存", 门禁._固定排除目录表(),
                      "`工程缓存` 必须在固定排除目录里 —— A 档落点的安全性靠它")


class Test接收者位缺陷(unittest.TestCase):
    """模块限定调用的目标在位置实参位；纯方法调用取接收者。"""

    def test_模块限定调用取位置实参(self) -> None:
        源 = _片段('''
            import os
            import shutil

            临时根 = 仓库根 / "工程缓存"

            def test_用例():
                shutil.rmtree(临时根)
                os.mkdir(临时根)
                os.makedirs(临时根, exist_ok=True)
                os.unlink(临时根)
                os.rmdir(临时根)
        ''')
        目标 = [目标 for _, _, 目标 in _扫片段(源)]
        self.assertEqual(目标, ["临时根"] * 5,
                         "改前这 5 处的目标都被取成模块名 `os`/`shutil` ⇒ 解析不出 ⇒ 未解析")

    def test_模块限定rename只判目标不判源(self) -> None:
        源 = _片段('''
            import os

            源 = 仓库根 / "支持库"
            目标 = 仓库根 / "工程缓存"

            def test_用例():
                os.rename(源, 目标)
        ''')
        self.assertEqual([目标 for _, _, 目标 in _扫片段(源)], ["目标"],
                         "只判目标；把源也当写入目标会产出假红")

    def test_纯方法调用仍取接收者(self) -> None:
        源 = _片段('''
            夹具根 = Path(tempfile.mkdtemp(dir=受管临时根))
            夹具根.mkdir()
            夹具根.chmod(0o755)
        ''')
        self.assertEqual(_结论(源), ["受管写", "受管写"],
                         "`夹具根.mkdir()` / `.chmod()` 的目标就是接收者 `夹具根`")

    def test_列表方法不是文件写(self) -> None:
        """`sys.path.remove(x)` 是**列表**方法 ⇒ 不得被当写入目标（假红）。"""
        源 = _片段('''
            import sys

            适配层 = 仓库根 / "支持库" / "适配层"

            def test_用例():
                sys.path.remove(str(适配层))
        ''')
        self.assertEqual(_扫片段(源), [], "列表方法不得进写动作面")

    def test_同名局部变量优先按变量算(self) -> None:
        """局部名不是模块 ⇒ 仍按接收者位（否则目标取成空 ⇒ 整个写动作漏判）。"""
        源 = _片段('''
            夹具根 = Path(tempfile.mkdtemp(dir=受管临时根))
            根 = 夹具根 / "子"
            根.mkdir()
        ''')
        self.assertEqual(_结论(源), ["受管写"])


class Test夹具根写在setUp(unittest.TestCase):
    """`dir=` 必须在**书写处**作用域解析（`setUp` 的局部夹具根在用例里看不见）。"""

    def test_self绑定引用的setUp局部名可解析(self) -> None:
        源 = _片段('''
            import unittest

            class 用例(unittest.TestCase):
                def setUp(self):
                    夹具根 = 仓库根 / "工程缓存" / "测试夹具"
                    self.临时 = Path(tempfile.mkdtemp(prefix="夹具_", dir=夹具根))

                def test_用例(self):
                    (self.临时 / "结果.json").write_text("{}", encoding="utf-8")
        ''')
        self.assertEqual(_结论(源), ["受管写"],
                         "`夹具根` 是 `setUp` 的局部名，`dir=` 必须在 `setUp` 的作用域里解析；"
                         "拿用例方法的作用域解析会假判未解析（反向验证实测过）")

    def test_self绑定引用另一个self绑定可解析(self) -> None:
        源 = _片段('''
            import unittest

            class 用例(unittest.TestCase):
                def setUp(self):
                    夹具根 = 仓库根 / "工程缓存" / "测试夹具"
                    self.临时 = Path(tempfile.mkdtemp(prefix="夹具_", dir=夹具根))
                    self.根 = Path(self.临时.name).resolve()

                def test_用例(self):
                    (self.根 / "结果.json").write_text("{}", encoding="utf-8")
        ''')
        self.assertEqual(_结论(源), ["受管写"])


class TestA档收口(unittest.TestCase):
    """A 档：落点钉进 `工程缓存/` 判「受管写」；「有裸 mkdtemp 却零清理词」的文件必须为零。"""

    #: A 档定义里的「清理词」（与 2026-09-23 A 档取证口径同源）。
    _清理词 = ("addCleanup", "rmtree", "清只读后删除树", "TemporaryDirectory")

    def test_全仓不再有裸mkdtemp且零清理词的文件(self) -> None:
        """A 档定义（`mkdtemp`/`mkstemp` 不带 `dir=` **且**文件里零清理词）必须为空。

        这是 A 档 93 处 / 39 文件的收口判据：`dir=` 钉进 `工程缓存/` + 补清理词，
        两条任一缺失都会被这条抓住。**不改判据、不下调基线**。
        """
        裸: list[str] = []
        for 文件 in 门禁._测试文件表(仓库根):
            树, _错误 = 门禁._读并解析(文件)
            if 树 is None:
                continue
            命中 = []
            for 节点 in ast.walk(树):
                if not (isinstance(节点, ast.Call) and 门禁._是临时落点构造器(节点.func)):
                    continue
                名 = (节点.func.attr if isinstance(节点.func, ast.Attribute)
                     else 节点.func.id)
                if 名 in ("mkdtemp", "mkstemp") and 门禁._取临时落点dir实参(节点) is None:
                    命中.append(节点.lineno)
            if not 命中:
                continue
            文 = 文件.read_text(encoding="utf-8")
            if not any(词 in 文 for 词 in self._清理词):
                裸.append(f"{文件.relative_to(仓库根)}:{命中}")
        self.assertEqual(裸, [], f"A 档未清空（裸 mkdtemp 且零清理词）：{裸[:5]}")

    def test_仓库内落点会被判红(self) -> None:
        """判据不空转：在**临时扫描根**里造一个仓库内落点，门禁必须判到。"""
        夹具 = Path(受管临时根) / "反向验证_仓库内落点"
        self.addCleanup(清只读后删除树, 夹具, 忽略失败=真)
        (夹具 / "测试中心").mkdir(parents=True, exist_ok=True)
        (夹具 / "测试中心" / "测试_坏.py").write_text(
            'import tempfile\n'
            'from pathlib import Path\n'
            '\n'
            '\n'
            'def test_坏():\n'
            '    根 = Path(tempfile.mkdtemp(dir="模块库"))\n'
            '    (根 / "结果.json").write_text("{}", encoding="utf-8")\n',
            encoding="utf-8")
        违规, 统计 = 门禁.扫描写入(夹具)
        仓库内 = [条 for 条 in 违规 if 条["缺口类型"] == 门禁.写仓库内相对路径]
        self.assertEqual(统计["仓库内写"], 1, "判据一必须真的判到那一处")
        self.assertEqual(len(仓库内), 1)
        self.assertEqual(仓库内[0]["目标"], "模块库")

    def test_受管落点不判红(self) -> None:
        """对照样本：同一形态改成 `dir=工程缓存/…` ⇒ 判受管写、零违规。"""
        夹具 = Path(受管临时根) / "反向验证_受管落点"
        self.addCleanup(清只读后删除树, 夹具, 忽略失败=真)
        (夹具 / "测试中心").mkdir(parents=True, exist_ok=True)
        (夹具 / "测试中心" / "测试_好.py").write_text(
            'import tempfile\n'
            'from pathlib import Path\n'
            '仓库根 = Path(__file__).resolve().parents[2]\n'
            '受管临时根 = 仓库根 / "工程缓存" / "测试临时"\n'
            '\n'
            '\n'
            'def test_好():\n'
            '    根 = Path(tempfile.mkdtemp(dir=受管临时根))\n'
            '    (根 / "结果.json").write_text("{}", encoding="utf-8")\n',
            encoding="utf-8")
        违规, 统计 = 门禁.扫描写入(夹具)
        self.assertEqual(统计["受管写"], 1)
        self.assertEqual(统计["仓库内写"], 0)
        self.assertEqual(统计["未解析"], 0)
        self.assertEqual(违规, [])


class Test判据四临时根未清(unittest.TestCase):
    """判据四：`mkdtemp`/`mkstemp` 造出的**根**必须在清理面上被清（fail-closed）。

    「改前」行为 = **没有这一判据**（建了不清全不报）⇒ 本组每条反向样本在旧判据面下
    都是「零违规」，即「判据在 ≠ 判据覆盖」的典型形态。
    """

    def _扫(self, 正文: str) -> tuple[list[dict], dict]:
        """把一段测试源码丢进**临时扫描根**跑判据四（不碰真 `测试中心/`）。"""
        夹具 = Path(受管临时根) / "反向验证_判据四"
        self.addCleanup(清只读后删除树, 夹具, 忽略失败=真)
        (夹具 / "测试中心").mkdir(parents=True, exist_ok=True)
        (夹具 / "测试中心" / "测试_样本.py").write_text(_片段(正文, 带头=False), encoding="utf-8")
        return 门禁.扫描临时根未清(夹具)

    def test_建了不清必判红(self) -> None:
        """反例主体：裸 `mkdtemp` 且清理面上找不到根 ⇒ 必须判红。"""
        违规, 统计 = self._扫('''
            import tempfile
            import unittest
            from pathlib import Path


            class 用例(unittest.TestCase):
                def setUp(self):
                    self.临时 = Path(tempfile.mkdtemp())

                def test_用一个(self):
                    (self.临时 / "x.txt").write_text("x", encoding="utf-8")
        ''')
        self.assertEqual(统计["临时根数"], 1)
        self.assertEqual(统计["未清"], 1)
        self.assertEqual([条["缺口类型"] for 条 in 违规], [门禁.临时根未清])
        self.assertIn("建了没清", 违规[0]["详情"])

    def test_mkstemp同样判(self) -> None:
        """`mkstemp` 也是临时根（造的是文件，同样要清）。"""
        违规, 统计 = self._扫('''
            import tempfile
            import unittest


            class 用例(unittest.TestCase):
                def setUp(self):
                    self.句柄, self.路径 = tempfile.mkstemp()

                def test_用一个(self):
                    self.assertTrue(self.路径)
        ''')
        self.assertEqual(统计["临时根数"], 1)
        self.assertEqual(统计["未清"], 1)

    def test_根派生到子路径判根不可达(self) -> None:
        """`Path(mkdtemp(...)) / "x.json"`：根**没有名字** ⇒ fail-closed 判红。

        这正是 `测试_公开调用完整性门禁.py:515` 改前的形态（把**文件路径**交给
        `addCleanup(清只读后删除树, …)` —— 目录树原语对文件必然失败、`忽略失败=真` 只留痕
        ⇒ mkdtemp 造出的**根目录全程无人清**）。
        """
        违规, 统计 = self._扫('''
            import tempfile
            import unittest
            from pathlib import Path

            受管 = Path("/tmp")


            class 用例(unittest.TestCase):
                def setUp(self):
                    self.基线 = Path(tempfile.mkdtemp(dir=受管)) / "基线.json"
                    self.addCleanup(lambda: None, self.基线)

                def test_用一个(self):
                    self.assertTrue(self.基线)
        ''')
        self.assertEqual(统计["根不可达"], 1)
        self.assertEqual([条["缺口类型"] for 条 in 违规], [门禁.临时根未清])
        self.assertIn("临时根没有绑定给任何名字", 违规[0]["详情"])

    def test_helper返回根_调用点全清才放行(self) -> None:
        """helper 返回根：调用点**全清** ⇒ 放行；**部分清** ⇒ 判红（不许只看一处）。"""
        全清, 统全 = self._扫('''
            import tempfile
            import unittest
            from pathlib import Path

            受管 = Path("/tmp")


            def 造根():
                根 = Path(tempfile.mkdtemp(dir=受管))
                return 根


            class 用例(unittest.TestCase):
                def setUp(self):
                    self.根 = 造根()
                    self.addCleanup(lambda: None, self.根)

                def test_一个(self):
                    self.assertTrue(self.根)
        ''')
        self.assertEqual(全清, [], f"调用点全清不得判红：{全清}")
        self.assertEqual(统全["已清"], 1)

        部分清, 统分 = self._扫('''
            import tempfile
            import unittest
            from pathlib import Path

            受管 = Path("/tmp")


            def 造根():
                根 = Path(tempfile.mkdtemp(dir=受管))
                return 根


            class 用例(unittest.TestCase):
                def test_清了(self):
                    A = 造根()
                    self.addCleanup(lambda: None, A)
                    self.assertTrue(A)

                def test_没清(self):
                    B = 造根()
                    self.assertTrue(B)
        ''')
        self.assertEqual(统分["未清"], 1, "有一个调用点没清就必须判红")
        self.assertEqual(len(部分清), 1)
        self.assertIn("根没人清", 部分清[0]["详情"])

    def test_落点在系统临时目录也要清(self) -> None:
        """**判据四防的正是这一档**：落点在系统临时目录（判据一放行）但没人清。

        与判据一的分工：判据一问「落点在哪」（别造进仓库正式根），判据四问「清没清」。
        落点合法的夹具同样会长期堆积 ⇒ 两者互补，不是重复判据。
        """
        违规, 统计 = self._扫('''
            import tempfile
            import unittest
            from pathlib import Path


            class 用例(unittest.TestCase):
                def test_造了不清(self):
                    临时 = Path(tempfile.mkdtemp())
                    self.assertTrue(临时)
        ''')
        self.assertEqual([条["缺口类型"] for 条 in 违规], [门禁.临时根未清])


class Test判据四不误判已清(unittest.TestCase):
    """**不能把已清的判成违规** —— 四条等效清理腿逐条钉住（本组全是「必须放行」）。"""

    def _扫(self, 正文: str) -> tuple[list[dict], dict]:
        夹具 = Path(受管临时根) / "反向验证_判据四_已清"
        self.addCleanup(清只读后删除树, 夹具, 忽略失败=真)
        (夹具 / "测试中心").mkdir(parents=True, exist_ok=True)
        (夹具 / "测试中心" / "测试_样本.py").write_text(_片段(正文, 带头=False), encoding="utf-8")
        return 门禁.扫描临时根未清(夹具)

    def _断言已清(self, 正文: str, 说明: str) -> None:
        违规, 统计 = self._扫(正文)
        self.assertEqual(违规, [], f"{说明}：已清不得判红，实际 {违规}")
        self.assertEqual(统计["已清"], 1, 说明)

    def test_腿一_addCleanup清只读后删除树(self) -> None:
        """仓内既有口径（`测试中心/运行核心/环境夹具.py` 与本仓 88 处现成写法）。"""
        self._断言已清('''
            import tempfile
            import unittest
            from pathlib import Path

            from 公共契约.运行时.平台适配 import 清只读后删除树


            class 用例(unittest.TestCase):
                def setUp(self):
                    self.临时 = Path(tempfile.mkdtemp())
                    self.addCleanup(清只读后删除树, self.临时, 忽略失败=真)

                def test_一个(self):
                    self.assertTrue(self.临时)
        ''', "addCleanup(清只读后删除树, 根, 忽略失败=真) 必须算已清")

    def test_腿一_addCleanup_shutil_rmtree(self) -> None:
        """`addCleanup(shutil.rmtree, 根, True)` 形态（仓内既有写法，同样算清过）。"""
        self._断言已清('''
            import shutil
            import tempfile
            import unittest
            from pathlib import Path


            class 用例(unittest.TestCase):
                def setUp(self):
                    self.临时 = Path(tempfile.mkdtemp())
                    self.addCleanup(shutil.rmtree, self.临时, True)

                def test_一个(self):
                    self.assertTrue(self.临时)
        ''', "addCleanup(shutil.rmtree, 根, True) 必须算已清")

    def test_腿二_tearDown里清(self) -> None:
        self._断言已清('''
            import shutil
            import tempfile
            import unittest
            from pathlib import Path


            class 用例(unittest.TestCase):
                def setUp(self):
                    self.临时 = Path(tempfile.mkdtemp())

                def tearDown(self):
                    shutil.rmtree(self.临时, ignore_errors=True)

                def test_一个(self):
                    self.assertTrue(self.临时)
        ''', "tearDown 里 shutil.rmtree(根) 必须算已清")

    def test_腿二_tearDownModule里清(self) -> None:
        """模块级夹具根由 `tearDownModule` 清（`测试中心/平台控制面/测试_平台控制面.py` 形态）。"""
        self._断言已清('''
            import tempfile
            from pathlib import Path


            根 = Path(tempfile.mkdtemp())


            def tearDownModule():
                import shutil
                shutil.rmtree(根, ignore_errors=True)


            def test_一个():
                assert 根
        ''', "tearDownModule 里清模块级根必须算已清")

    def test_腿三_try_finally里清(self) -> None:
        """`try/finally` 清根（用例失败路径也跑，与 addCleanup 等效）。"""
        self._断言已清('''
            import shutil
            import tempfile
            import unittest
            from pathlib import Path


            class 用例(unittest.TestCase):
                def test_一个(self):
                    组件目录 = Path(tempfile.mkdtemp())
                    try:
                        self.assertTrue(组件目录)
                    finally:
                        shutil.rmtree(组件目录, ignore_errors=True)
        ''', "try/finally 里 rmtree(根) 必须算已清")

    def test_腿四_模块级登记表(self) -> None:
        """模块级登记表 + `tearDownModule` 消费（helper 拿不到用例实例时的仓内既有口径）。"""
        self._断言已清('''
            import tempfile
            import unittest
            from pathlib import Path

            from 公共契约.运行时.平台适配 import 清只读后删除树

            _临时夹具登记 = []


            def tearDownModule():
                for 夹具 in _临时夹具登记:
                    清只读后删除树(夹具, 忽略失败=真)
                _临时夹具登记.clear()


            def 造根():
                根 = Path(tempfile.mkdtemp())
                _临时夹具登记.append(根)
                return 根


            class 用例(unittest.TestCase):
                def test_一个(self):
                    根 = 造根()
                    self.assertTrue(根)
        ''', "helper 内登记模块级登记表（tearDownModule 消费）必须算已清（一处覆盖全部调用点）")

    def test_lambda里清根也算(self) -> None:
        """`addCleanup(lambda: __import__("shutil").rmtree(根, …))` 形态（仓内既有写法）。"""
        self._断言已清('''
            import tempfile
            import unittest
            from pathlib import Path


            class 用例(unittest.TestCase):
                def setUp(self):
                    self.目录 = Path(tempfile.mkdtemp())
                    self.addCleanup(
                        lambda: __import__("shutil").rmtree(self.目录, ignore_errors=True))

                def test_一个(self):
                    self.assertTrue(self.目录)
        ''', "addCleanup(lambda: …rmtree(根…)) 必须算已清")

    def test_清子路径不改判根已清(self) -> None:
        """**反假绿样本**：只清了**派生子路径**、根仍无人清 ⇒ 必须判红（不是已清）。

        本组其余样本钉的是「别把已清判成违规」；这一条钉反向 —— 判据不能被
        「文件里出现过清理词/清过别的路径」骗过。
        """
        违规, 统计 = self._扫('''
            import shutil
            import tempfile
            import unittest
            from pathlib import Path


            class 用例(unittest.TestCase):
                def setUp(self):
                    self.根 = Path(tempfile.mkdtemp())

                def test_只清了子路径(self):
                    shutil.rmtree(self.根 / "子目录", ignore_errors=True)
        ''')
        self.assertEqual(统计["未清"], 1, "只清派生路径不算清根")
        self.assertEqual([条["缺口类型"] for 条 in 违规], [门禁.临时根未清])

    def test_登记表空转不算清(self) -> None:
        """**反假绿样本（反向验证拍5 拍到的真 fail-open）**：登记表在 `tearDownModule` 里

        被 `for` 消费，但**循环体里什么都没做**（`for 夹具 in 表: pass`）——
        只认「表名出现在 tearDownModule 的 for 里」会把空转收尾算成已清。判据必须
        核**循环体真的对循环变量调了清理原语**。
        """
        违规, 统计 = self._扫('''
            import tempfile
            import unittest
            from pathlib import Path

            _临时夹具登记 = []


            def tearDownModule():
                for 夹具 in _临时夹具登记:
                    pass
                _临时夹具登记.clear()


            class 用例(unittest.TestCase):
                def setUp(self):
                    self.根 = Path(tempfile.mkdtemp())
                    _临时夹具登记.append(self.根)

                def test_一个(self):
                    self.assertTrue(self.根)
        ''')
        self.assertEqual(统计["未清"], 1, "空转的登记表消费不算清")
        self.assertEqual([条["缺口类型"] for 条 in 违规], [门禁.临时根未清])

    def test_同文件同名self根按类核(self) -> None:
        """**反假绿样本（反向验证拍1 拍到的真 fail-open）**：同文件两个类各有 `self.工作`

        —— A 类的清理登记**不能替 B 类顶包**（`测试_SwiftCompiler提供者.py` 就是这一形态：
        `Test编译源代码` 与 `Test签名` 各有一个 `self.工作`）。只按文件级收名字，
        删掉 A 的 `addCleanup` 后 B 的登记会顶上 ⇒ 弄坏不红。
        """
        违规, 统计 = self._扫('''
            import tempfile
            import unittest
            from pathlib import Path

            from 公共契约.运行时.平台适配 import 清只读后删除树


            class A(unittest.TestCase):
                def setUp(self):
                    self.工作 = Path(tempfile.mkdtemp())
                    self.addCleanup(清只读后删除树, self.工作, 忽略失败=真)

                def test_一个(self):
                    self.assertTrue(self.工作)


            class B(unittest.TestCase):
                def setUp(self):
                    self.工作 = Path(tempfile.mkdtemp())
                    # ★ B**没有**登记清理

                def test_一个(self):
                    self.assertTrue(self.工作)
        ''')
        self.assertEqual(统计["未清"], 1, "B类的 self.工作 不得被A类的登记顶包")
        self.assertEqual([条["缺口类型"] for 条 in 违规], [门禁.临时根未清])

    def test_根在子类_清理在基类算已清(self) -> None:
        """对照：根造在**子类**、清理写在**基类** `tearDown` 里 ⇒ 必须算已清（带基类链）。

        上一条把 `self.X` 证据按类收窄；不认基类链就会把这一形态（仓内常见：
        `清只读夹具.setUp` 造 `self.根`、子类用例用它）假判成违规。
        """
        违规, 统计 = self._扫('''
            import shutil
            import tempfile
            import unittest
            from pathlib import Path


            class 基类夹具(unittest.TestCase):
                def setUp(self):
                    self.根 = Path(tempfile.mkdtemp())

                def tearDown(self):
                    shutil.rmtree(self.根, ignore_errors=True)


            class 子类用例(基类夹具):
                def test_一个(self):
                    self.assertTrue(self.根)
        ''')
        self.assertEqual(违规, [], f"根在子类、清理在基类必须算已清：{违规}")
        self.assertEqual(统计["已清"], 1)


class Test判据四自证不空转(unittest.TestCase):
    """判据四在**真仓**上必须「判过了 N 处」（不是零违规的恒绿）。"""

    def test_真仓判过的处数与已清处数(self) -> None:
        违规, 统计 = 门禁.扫描临时根未清(仓库根)
        self.assertEqual(违规, [], f"真仓判据四应为零违规：{违规[:3]}")
        self.assertGreater(统计["临时根数"], 100,
                           "真仓临时根数必须远大于 0（否则判据空转）")
        self.assertEqual(统计["临时根数"], 统计["已清"] + 统计["未清"] + 统计["根不可达"],
                         "统计必须自洽：临时根数 = 已清 + 未清 + 根不可达")

    def test_扫描面为空判红(self) -> None:
        夹具 = Path(受管临时根) / "反向验证_判据四_空扫描面"
        self.addCleanup(清只读后删除树, 夹具, 忽略失败=真)
        夹具.mkdir(parents=True, exist_ok=True)
        违规, _ = 门禁.扫描临时根未清(夹具)
        self.assertEqual([条["缺口类型"] for 条 in 违规], [门禁.缺扫描面])


if __name__ == "__main__":
    unittest.main(verbosity=2)
