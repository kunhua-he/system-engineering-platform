"""退出码诚实口径测试（第一轮审计待办 #64 / #65 / #66）。

病根是同一条：工具把「真发现问题」只写进**打印**，`main` 恒 `return 0`
⇒ 调用方（定时任务 / CI / 决策者）读到的永远是「成功」，判据等于没有。

三段判据：

- **#64** `开发效率巡检.py`：`探索占 ≥50%`、`terminal 占 ≥60%`、`慢命令 ≥10 秒`
  三处原先只 append 归因字符串，不进返回值 ⇒ 现在必须进退出码：
  仅告警退 1、有 `⛔` 阻断退 2、全 `✓` 退 0。
- **#65** `提供者环境回收.py`：`回收()` 原先无条件 `return 0` ⇒ 现在：
  有「来源不明、保守跳过」退 1（真发现问题），只报不删（未做任何动作）退 2，
  扫干净且已清退 0。
- **#66** `安装或卸载队列常驻.py` `卸载()`：原先把 `执行()` 的返回码丢掉、
  照样打印「已卸载」、`return 0` ⇒ 现在拿返回码：未安装退 2、卸载失败退 1、
  真卸掉退 0（同文件 `安装()` 的正确姿势）。

反向验证口径（强规范「弄坏必变红」）：每个工具都把**当前源码做等价「修前」文本注入**
（把新增的非零分支改回原样）写成临时副本，真跑一遍断言它退 0 ——
若注入后仍退非零，说明测试判据根本读不到退出码（恒真），必须判红。

**只读**：所有反向现场都由本测试在 `tempfile` 里现造，不碰仓库文件、不调 `launchctl`。
"""
from __future__ import annotations

import importlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

系统根 = Path(__file__).resolve().parents[2]
if str(系统根) not in sys.path:
    sys.path.insert(0, str(系统根))

巡检脚本 = 系统根 / "开发工具/开发效率巡检.py"
回收脚本 = 系统根 / "开发工具/提供者环境回收.py"
卸载脚本 = 系统根 / "开发工具/直播逐字稿工具/安装或卸载队列常驻.py"


def 跑脚本(脚本: Path, 参数: list[str], 环境: dict | None = None) -> tuple[int, str]:
    """真跑脚本，返回 (退出码, 输出)。判据只认退出码，不认打印。"""
    环境副本 = dict(os.environ)
    环境副本.pop("PYTHONPATH", None)
    if 环境:
        环境副本.update(环境)
    完成 = subprocess.run([sys.executable, "-B", str(脚本), *参数],
                          cwd=str(系统根), capture_output=True, text=True,
                          env=环境副本, timeout=120)
    return 完成.returncode, 完成.stdout + 完成.stderr


def 写修前等价副本(源文件: Path, 替换表: list[tuple[str, str]], 目标: Path) -> Path:
    """把当前源码里「新加的非零退出分支」文本换回修前形态，写成临时副本。

    锚点必须真的存在，否则断言失败（防锚点被改后反向验证静默失效）。
    """
    文 = 源文件.read_text(encoding="utf-8")
    for 新, 旧 in 替换表:
        assert 新 in 文, f"反向注入锚点不存在（源码已变，反向验证失效）：{新!r}"
        文 = 文.replace(新, 旧, 1)
    目标.write_text(文, encoding="utf-8")
    return 目标


# --------------------------------------------------------------------------- #
#  一、开发效率巡检（#64）
# --------------------------------------------------------------------------- #
纪律齐全Kickoff = ("01:00:01 user     | kickoff: 写任务（允许修改 开发工具/示例.py）："
                    "修一条退出码口径。工具姿势：扫描用 rg；提交纪律：精确 pathspec；"
                    "pathspec 只 add 自己改的文件；命令环境：python3.14 + unset PYTHONPATH")


def 写构造日志(根: Path, 批次: str, 行表: list[str]) -> Path:
    目录 = 根 / 批次
    目录.mkdir(parents=True, exist_ok=True)
    文件 = 目录 / "task-0.log"
    文件.write_text("\n".join(行表) + "\n", encoding="utf-8")
    return 文件


def 仅告警日志行表() -> list[str]:
    """三处阈值全中、且四条纪律标志齐（→ 无 ⛔ 阻断，只剩 ⚠ 告警）。

    计数口径按工具自己的分类：`grep` 命中 探索词 ⇒ 那几条 terminal 归「探索」。
    设计：terminal 7 条（其中 6 条含 `grep` ⇒ 探索）、read_file 1 条（探索）、
    patch 1 条（修改）⇒ 总 9：探索 7/9 = 77.8%（≥50%）、terminal 7/9 = 77.8%（≥60%）、
    慢命令 12.3s / 11.5s 两条（≥10 秒，且都 <15 秒以免多出 ⛔ 阻断）。
    """
    return [
        纪律齐全Kickoff,
        "01:00:02 tool     | -> terminal(grep -n 关键词 支持库/后端)",
        '01:00:03 result   | terminal ok 12.3s: {"output": "命中 3 行"}',
        "01:00:04 tool     | -> terminal(grep -n 关键词 运行核心)",
        '01:00:05 result   | terminal ok 0.4s: {"output": "命中 1 行"}',
        "01:00:06 tool     | -> terminal(grep -n 关键词 模块库)",
        '01:00:07 result   | terminal ok 0.5s: {"output": "命中 2 行"}',
        "01:00:08 tool     | -> terminal(grep -n 关键词 平台控制面)",
        '01:00:09 result   | terminal ok 0.3s: {"output": "命中 0 行"}',
        "01:00:10 tool     | -> terminal(grep -n 关键词 开发工具)",
        '01:00:11 result   | terminal ok 11.5s: {"output": "命中 9 行"}',
        "01:00:12 tool     | -> terminal(grep -n 关键词 测试中心)",
        '01:00:13 result   | terminal ok 0.6s: {"output": "命中 4 行"}',
        "01:00:14 tool     | -> read_file(开发工具/示例.py L1-120)",
        '01:00:15 result   | read_file ok 0.1s: {"content": "文本"}',
        "01:00:16 tool     | -> patch(开发工具/示例.py)",
        '01:00:17 result   | patch ok 0.1s: {"resolved_path": "/Users/x/示例.py"}',
        "01:00:30 final    | status=completed duration=900.0s",
        "01:00:30 final    | end status=completed",
    ]


def 全绿日志行表() -> list[str]:
    """干净现场：无告警、无阻断（归档任务且在跑，不进交付留痕）。"""
    return [
        纪律齐全Kickoff,
        "01:00:02 tool     | -> terminal(python3.14 -B -m 测试中心.开发工具.测试_依赖防火墙口径)",
        '01:00:03 result   | terminal ok 0.6s: {"output": "OK"}',
        "01:00:04 tool     | -> patch(开发工具/示例.py)",
        '01:00:05 result   | patch ok 0.1s: {"resolved_path": "/Users/x/示例.py"}',
    ]


def 造果(**覆盖) -> dict:
    """造一份 `汇总()` 形态的指标（只喂 `归因()` 需要的键），逐条验阈值。"""
    果 = {
        "占比": {"探索": 0.0, "修改": 100.0, "验证": 0.0, "其他": 0.0},
        "黑洞": {"terminal读文件": 0, "一次性python": 0, "命令超时": 0, "全仓grep": 0,
                 "慢命令(>10秒)": 0, "重复搜索同目标": 0, "sleep等后台": 0, "单命令超15秒": 0},
        "工具": {"terminal": 0, "patch": 100},
        "总调用": 100,
        "反复读": {},
        "重复检索": {},
        "超时": 0,
        "纪律": {"已送达": 1, "未送达": 0, "缺项表": []},
        "慢命令明细": [],
    }
    果["占比"]["探索"] = 覆盖.get("探索", 0.0)
    果["工具"]["terminal"] = 覆盖.get("terminal", 0)
    果["总调用"] = 覆盖.get("总调用", 100)
    慢条数 = 覆盖.get("慢命令", 0)
    果["黑洞"]["慢命令(>10秒)"] = 慢条数
    果["慢命令明细"] = [{"工具": "terminal", "秒": 12.3}] * 慢条数
    if 覆盖.get("纪律未送达"):
        果["纪律"] = {"已送达": 0, "未送达": 覆盖["纪律未送达"],
                      "缺项表": [{"路": "task-0.log", "缺": ["工具姿势", "提交纪律"]}]}
    if 覆盖.get("sleep"):
        果["黑洞"]["sleep等后台"] = 覆盖["sleep"]
    return 果


class 巡检归因退出码测试(unittest.TestCase):
    """三处阈值必须进退出码；只打印不算判据。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.模块 = importlib.import_module("开发工具.开发效率巡检")
        cls.快照根 = 系统根 / "工程缓存/运行数据/开发效率巡检"

    def 折码(self, **覆盖) -> tuple[int, list[str]]:
        归因表 = self.模块.归因(造果(**覆盖))
        return self.模块.归因退出码(归因表)[0], 归因表

    # ---- 正向：三处阈值各自单独成立时都必须退 1（不是 0）----
    def test_探索占比达50必须退非零(self) -> None:
        码, 表 = self.折码(探索=50.0)
        self.assertEqual(码, 1, f"探索占 50% 必须进退出码：{表}")
        self.assertTrue(any("探索占" in x for x in 表), 表)

    def test_终端占比达60必须退非零(self) -> None:
        码, 表 = self.折码(terminal=60, 总调用=100)
        self.assertEqual(码, 1, f"terminal 占 60% 必须进退出码：{表}")
        self.assertTrue(any("terminal 占工具调用" in x for x in 表), 表)

    def test_慢命令达10秒必须退非零(self) -> None:
        码, 表 = self.折码(慢命令=1)
        self.assertEqual(码, 1, f"慢命令 ≥10 秒必须进退出码：{表}")
        self.assertTrue(any("慢命令（单条 ≥10 秒）" in x for x in 表), 表)

    def test_阈值未达时不许假红(self) -> None:
        码, 表 = self.折码(探索=49.9, terminal=59, 慢命令=0)
        self.assertEqual(码, 0, f"阈值内必须退 0（不许加严成假红）：{表}")

    def test_阻断比告警更重(self) -> None:
        码, _ = self.折码(探索=50.0, 纪律未送达=1)
        self.assertEqual(码, 2, "有 ⛔ 阻断时必须退 2（严重度不得被告警掩盖）")

    def test_纯函数口径与真跑一致_仅告警现场退1(self) -> None:
        """真跑脚本：三处阈值全中、无阻断 ⇒ 退出码 1，且打印里三处告警都在。"""
        with tempfile.TemporaryDirectory(prefix="巡检仅告警_") as 临时:
            根 = Path(临时)
            写构造日志(根, "deleg_仅告警", 仅告警日志行表())
            码, 输出 = 跑脚本(巡检脚本, ["--目录", str(根)])
        for 关键 in ("⚠ 探索占", "⚠ terminal 占工具调用", "⚠ 慢命令（单条 ≥10 秒）"):
            self.assertIn(关键, 输出, 输出)
        self.assertEqual(码, 1, f"三处阈值命中必须非零退出码：\n{输出}")

    def test_真跑_干净现场退0(self) -> None:
        前 = set(self.快照根.glob("*.json"))
        with tempfile.TemporaryDirectory(prefix="巡检全绿_") as 临时:
            根 = Path(临时)
            写构造日志(根, "deleg_全绿", 全绿日志行表())
            码, 输出 = 跑脚本(巡检脚本, ["--目录", str(根)])
        self.assertEqual(码, 0, f"干净现场必须退 0：\n{输出}")
        self.assertIn("归因判级：⛔ 0 条 / ⚠ 0 条 / ✓ 1 条 → 退出码 0", 输出, 输出)
        # 巡检真跑会落自己的快照，测试把它清掉（不留测试垃圾）。
        for 新 in set(self.快照根.glob("*.json")) - 前:
            新.unlink(missing_ok=True)

    def test_真跑_有阻断现场退2(self) -> None:
        前 = set(self.快照根.glob("*.json"))
        行表 = ["01:00:01 user     | kickoff: 写任务（允许修改 开发工具/示例.py）—— 缺纪律条款",
                "01:00:02 tool     | -> patch(开发工具/示例.py)",
                '01:00:03 result   | patch ok 0.1s: {"resolved_path": "/Users/x/示例.py"}',
                "01:00:04 final    | status=completed duration=30.0s",
                "01:00:04 final    | end status=completed"]
        with tempfile.TemporaryDirectory(prefix="巡检阻断_") as 临时:
            根 = Path(临时)
            写构造日志(根, "deleg_阻断", 行表)
            码, 输出 = 跑脚本(巡检脚本, ["--目录", str(根)])
        self.assertIn("⛔ 任务信纪律未送达", 输出, 输出)
        self.assertEqual(码, 2, f"有 ⛔ 阻断必须退 2：\n{输出}")
        for 新 in set(self.快照根.glob("*.json")) - 前:
            新.unlink(missing_ok=True)

    def test_反向_修前等价副本必须假绿(self) -> None:
        """把 `return 码` 换回 `return 0`（= 修前形态）后，同一现场必须退 0。"""
        前 = set(self.快照根.glob("*.json"))
        with tempfile.TemporaryDirectory(prefix="巡检反证_") as 临时:
            根 = Path(临时)
            修前 = 写修前等价副本(巡检脚本, [("    return 码", "    return 0")],
                                 根 / "巡检_修前等价.py")
            现场 = 根 / "现场"
            写构造日志(现场, "deleg_仅告警", 仅告警日志行表())
            码_修前, 输出 = 跑脚本(修前, ["--目录", str(现场)])
            码_修后, _ = 跑脚本(巡检脚本, ["--目录", str(现场)])
        self.assertEqual(码_修前, 0, f"修前形态必须复现假绿（否则反向验证读不到退出码）：\n{输出}")
        self.assertEqual(码_修后, 1, "修后同一现场必须非零，反向验证才算成立")
        for 新 in set(self.快照根.glob("*.json")) - 前:
            新.unlink(missing_ok=True)


# --------------------------------------------------------------------------- #
#  二、提供者环境回收（#65）
# --------------------------------------------------------------------------- #
def 建假环境根(根: Path, 回收源: Path, 名字: str) -> tuple[Path, dict]:
    """建一个自足假仓库根（只有 `工程缓存/提供者运行环境` 与提供者真身）。

    软链 `运行核心`/`公共契约`/`支持库`/`模块库` 到真仓库：回收脚本要 import
    平台的 `环境管理器`（摘要算法是唯一判据，不许在测试里另写一套）。
    注意 `找提供者目录` 用 `系统根.rglob`，而 rglob **不跟随符号链接目录**，
    所以提供者真身必须放在假根自己的真目录 `假提供者库/` 里。
    """
    假根 = 根 / 名字
    (假根 / "开发工具").mkdir(parents=True)
    脚本 = 假根 / "开发工具" / "回收.py"
    shutil.copy2(回收源, 脚本)
    for 层名 in ("运行核心", "公共契约", "支持库", "模块库"):
        (假根 / 层名).symlink_to(系统根 / 层名)
    from 运行核心.运行环境管理器.环境管理器 import 计算环境摘要
    摘要表 = {}
    for 名, 锁 in {"真实A提供者": {"依赖": ["A==1.0"]},
                   "未生成C提供者": {"依赖": ["C==2.0"]}}.items():
        真身 = 假根 / "假提供者库" / 名
        真身.mkdir(parents=True)
        (真身 / "依赖锁.json").write_text(
            __import__("json").dumps(锁, ensure_ascii=False), encoding="utf-8")
        摘要表[名] = 计算环境摘要(锁, 名)
    环境根 = 假根 / "工程缓存/提供者运行环境"
    for 名, 子表 in {"真实A提供者": [摘要表["真实A提供者"], "旧摘要_aaaaaaaa"],
                    "未生成C提供者": ["别的摘要_bbbbbbbb"],
                    "来源不明B提供者": ["任意摘要_cccccccc"]}.items():
        for 子 in 子表:
            目录 = 环境根 / 名 / 子
            目录.mkdir(parents=True)
            (目录 / "占位.txt").write_text("占位", encoding="utf-8")
    return 脚本, 摘要表


class 提供者环境回收退出码测试(unittest.TestCase):
    """`回收()` 不许再无条件退 0：跳过非空要报，未做动作也要报。"""

    def setUp(self) -> None:
        self.临时 = Path(tempfile.mkdtemp(prefix="回收退出码_"))
        self.addCleanup(shutil.rmtree, self.临时, ignore_errors=True)
        self.脚本, self.摘要表 = 建假环境根(self.临时, 回收脚本, "假仓库根")

    def test_默认只报不删退2(self) -> None:
        码, 输出 = 跑脚本(self.脚本, [])
        self.assertIn("【只报不删】", 输出, 输出)
        self.assertEqual(码, 2, f"未做任何动作必须退 2（原实现退 0）：\n{输出}")

    def test_跳过非空退1(self) -> None:
        码, 输出 = 跑脚本(self.脚本, ["--执行"])
        self.assertIn("保守跳过 2 个", 输出, 输出)
        self.assertEqual(码, 1, f"有来源不明目录必须退 1（原实现退 0）：\n{输出}")

    def test_扫干净且已清退0(self) -> None:
        环境根 = self.脚本.parents[1] / "工程缓存/提供者运行环境"
        shutil.rmtree(环境根 / "未生成C提供者")
        shutil.rmtree(环境根 / "来源不明B提供者")
        shutil.rmtree(环境根 / "真实A提供者" / "旧摘要_aaaaaaaa")
        码, 输出 = 跑脚本(self.脚本, ["--执行"])
        self.assertNotIn("保守跳过", 输出, 输出)
        self.assertEqual(码, 0, f"干净现场必须退 0（不许假红）：\n{输出}")

    def test_反向_修前等价副本必须假绿(self) -> None:
        """修前 `回收()` 尾部**只有一个常量** `return 0`（`:117`），任何现场都读不到差别。

        反向验证两拍（同一假现场、只换尾部返回值）：

        1. **探针拍**：把尾部三态（`return 2` / `return 1` / `return 0`）整体换成同一个
           常量 `return 6`，接好控制流后真跑 —— 两个场景都必须拿到 6，
           说明「尾部返回单一常量」的形态确实不可判别（修前正是这种形态）；
        2. **现场拍（现状）**：原始脚本同一现场分别拿到 2 与 1 —— 取值互不相同，
           证明返回值真的由现场决定。
        """
        with tempfile.TemporaryDirectory(prefix="回收反证_") as 临时:
            临时根 = Path(临时)
            文 = 回收脚本.read_text(encoding="utf-8")
            锚点 = "        return 2\n    if 跳过:\n        return 1\n    return 0"
            self.assertIn(锚点, 文, "回收脚本尾部三态返回不再是预期形态，探针口径需复核")
            self.assertEqual(文.count("    return 0\n"), 2,
                             "回收脚本 `return 0` 不再是 2 处，探针口径需复核")
            场景脚本, _ = 建假环境根(临时根, 回收脚本, "假根")
            探针 = 临时根 / "假根" / "开发工具/回收_探针.py"
            探针.write_text(
                文.replace(锚点, "        return 6\n    if 跳过:\n        return 6\n    return 6", 1),
                encoding="utf-8")
            码_探针_只报, 输出探针 = 跑脚本(探针, [])
            码_探针_执行, 输出探针执行 = 跑脚本(探针, ["--执行"])
            码_修后_只报, 输出修后 = 跑脚本(场景脚本, [])
            码_修后_执行, _ = 跑脚本(场景脚本, ["--执行"])
        self.assertIn("【只报不删】", 输出探针, 输出探针)
        self.assertIn("保守跳过 2 个", 输出探针执行, 输出探针执行)
        self.assertIn("保守跳过 2 个", 输出修后, 输出修后)
        self.assertEqual((码_探针_只报, 码_探针_执行), (6, 6),
                         "尾部换成单一常量后必须两场景同值 —— 这就是修前恒 0 的形态")
        self.assertEqual((码_修后_只报, 码_修后_执行), (2, 1),
                         "修后同一现场必须分别是 2（未做动作）与 1（有跳过）")


# --------------------------------------------------------------------------- #
#  三、队列常驻安装 / 卸载（#66）
# --------------------------------------------------------------------------- #
class 卸载退出码测试(unittest.TestCase):
    """`卸载()` 不许丢掉 `执行()` 的返回码后报成功。"""

    def setUp(self) -> None:
        self.临时 = Path(tempfile.mkdtemp(prefix="卸载退出码_"))
        self.addCleanup(shutil.rmtree, self.临时, ignore_errors=True)
        self.环境 = {"HOME": str(self.临时)}
        self.标签 = "平台临时测试-退出码核验"

    def _定义文件(self) -> Path:
        return self.临时 / "Library" / "LaunchAgents" / f"{self.标签}.plist"

    def test_未安装退2(self) -> None:
        码, 输出 = 跑脚本(卸载脚本, ["卸载", "--标签", self.标签], self.环境)
        self.assertIn("未安装", 输出, 输出)
        self.assertEqual(码, 2, f"没有东西可卸必须退 2（原实现报「已卸载」退 0）：\n{输出}")

    def test_定义文件在场但未装载必须报失败(self) -> None:
        定义 = self._定义文件()
        定义.parent.mkdir(parents=True, exist_ok=True)
        定义.write_text(f"<plist><dict><key>Label</key><string>{self.标签}</string>"
                        "</dict></plist>\n", encoding="utf-8")
        码, 输出 = 跑脚本(卸载脚本, ["卸载", "--标签", self.标签], self.环境)
        self.assertEqual(码, 1, f"定义文件在场却退不出服务必须退 1：\n{输出}")
        self.assertIn("卸载失败", 输出, 输出)
        self.assertTrue(定义.is_file(),
                        "卸载失败时不许把定义文件删掉（原实现静默删除后报成功）")

    def test_反向_修前等价副本必须假绿(self) -> None:
        修前 = 写修前等价副本(卸载脚本, [
            ("    if 码 != 0 and not 目标.is_file():", "    if False:"),
            ("    if 码 != 0:\n        # 定义文件在场却退不出服务", "    if False:\n        # 定义文件在场却退不出服务"),
        ], self.临时 / "卸载_修前等价.py")
        码_修前, 输出修前 = 跑脚本(修前, ["卸载", "--标签", self.标签], self.环境)
        码_修后, _ = 跑脚本(卸载脚本, ["卸载", "--标签", self.标签], self.环境)
        self.assertIn("已卸载", 输出修前, 输出修前)
        self.assertEqual(码_修前, 0, "修前形态必须假绿（报「已卸载」退 0）")
        self.assertEqual(码_修后, 2, "修后同一现场必须非零，反向验证才算成立")


if __name__ == "__main__":
    unittest.main()
