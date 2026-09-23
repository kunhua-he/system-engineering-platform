"""编译口单写者守卫回归：并发写者必须被**拒启**，陈旧锁必须能夺且**如实报**。

## 修前现场（2026-09-23 实测）

同一时段有**两个编译口在跑**：两个写者同改派生件，谁最后写赢，另一方的
「已生成·复跑绿」就不可信（它核验到的可能是对方刚写进去的值）。
原先怀疑的「节点脚本走 stdin ⇒ 管道死锁」已被实测**证伪**（`执行命令` 是 argv 直启，
全仓搜不到喂 stdin 的实现），故守卫只防「并发写者无守卫」这一件事。

## 本测试钉住的判据（真实子进程 / 真实文件 / 真实函数调用取证，不读源码字面）

1. **锁落点**：锁文件在 `工程缓存/` 下（`.gitignore` 与工作区指纹排除表都盖住它），
   `git check-ignore` 认它是忽略件 —— 落点错了会让工作区指纹恒判「含未提交变更」；
2. **锁内容**：至少含 `pid` / `启动时刻` / `仓库根`（便于人核是谁在跑）；
3. **活锁 ⇒ 拒启**：同树已有活锁时，真起一个编译口子进程必须**退出码非 0 + 如实报**
   「同树已有编译口在跑（PID …，启动于 …）」，**不是挂死、也不是静默并发跑**；
4. **陈旧锁可夺**：锁里 PID 不存在、或启动时刻超阈值 ⇒ 可夺，且输出**如实报**
   「夺了陈旧锁（原 PID …）」，不许静默夺；
5. **fail-closed**：锁文件形状非法 / 缺字段 / 时刻解析不出 ⇒ **拒启**（判不出来不放行）；
6. **`--只读` 不占锁**：只跑核验命令、不写派生件 ⇒ 多读者无害（取舍理由见编译口注释块）；
7. **释放只删自己那把**：锁里 pid 不是本进程时，释放**不得**动它（否则等于亲手开并发窗口）。

★ 本测试只在**临时根**上造锁（`占单写者锁(临时根)` 的锁落在 `<临时根>/工程缓存/` 下），
故不会碰、也不会删掉真仓库那把锁 —— 它可能正被外层编译口持有（本测试自己就常跑在
外层编译口的步骤5 里）。唯一的例外是第 3 条：它要真起子进程，用真仓库那把锁取证。

跑法：python3.14 -m unittest 测试中心.开发工具.测试编译口单写者守卫
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

仓库根 = Path(__file__).resolve().parents[2]
if str(仓库根) not in sys.path:
    sys.path.insert(0, str(仓库根))

from 开发工具.开发编译口 import 编译口

from 公共契约.运行时.平台适配 import 清只读后删除树
from 公共契约.基础类型.逻辑类型 import 真

#: ★ A 档泄漏收口（2026-09-23）：受管临时根在仓库内**固定排除目录** `工程缓存/` 下。
#: `dir=` 显式指向它 ⇒ 落点与**测试运行时**的 `TMPDIR` 解耦（平台跑测试时 `TMPDIR` 被指进
#: 仓库工作目录，裸 `mkdtemp()` 会把夹具造进仓库）。`工程缓存` 在
#: `开发工具/项目编译/工作区指纹.py` 的 `固定排除目录` 里 ⇒ 即便进程被 SIGKILL、
#: 清理没跑到，残留也进不了工作区指纹（`.gitignore` 保不住：指纹的未跟踪腿不用
#: `--exclude-standard`）。清理走平台唯一删树原语 `清只读后删除树`（本类用例常造
#: `0o555` 目录 / `0o444` 文件，plain `shutil.rmtree` 会被权限位挡住）。
受管临时根 = 仓库根 / "工程缓存" / "测试临时"
受管临时根.mkdir(parents=True, exist_ok=True)

#: 模块级临时夹具登记：本模块的夹具**在模块级 helper 里**造（helper 拿不到 TestCase 实例，
#: 用不了 `self.addCleanup`）⇒ 走 unittest 的**模块级收尾钩子** `tearDownModule` 登记清理
#: （同样「用例失败也跑」）。拿得到用例实例的站点一律用 `self.addCleanup`。
_临时夹具登记: list[Path] = []


def tearDownModule() -> None:
    """模块收尾：清理本模块造在 `受管临时根` 下的全部夹具（**用例失败也跑**）。"""
    for 夹具 in _临时夹具登记:
        清只读后删除树(夹具, 忽略失败=真)
    _临时夹具登记.clear()


锁路径 = 仓库根 / 编译口.锁相对路径

#: 本机 git（命令环境纪律：`/usr/bin/git` 是 Xcode shim，本仓一律用 CommandLineTools 那个）。
#: 换机/换平台没有它就退回 PATH 里的 git —— 否则判据在别的机器上直接报错，而不是给出结论。
GIT = "/Library/Developer/CommandLineTools/usr/bin/git"
if not Path(GIT).is_file():
    GIT = "git"


def _临时根() -> Path:
    """临时根（用完由 `_清临时根` 删）。锁落在 `<临时根>/工程缓存/` 下，与真仓库无关。"""
    根 = Path(tempfile.mkdtemp(prefix="编译口单写者守卫_", dir=受管临时根))
    _临时夹具登记.append(根)
    return 根


def _清临时根(根: Path) -> None:
    锁 = 根 / 编译口.锁相对路径
    锁.unlink(missing_ok=True)
    try:
        锁.parent.rmdir()
        根.rmdir()
    except OSError:
        pass


def _写锁(根: Path, *, pid: int, 启动时间戳: float, 仓库根文本: str | None = None) -> Path:
    """直接在临时根下写一把锁（模拟残留 / 伪造现场）。"""
    锁 = 根 / 编译口.锁相对路径
    锁.parent.mkdir(parents=True, exist_ok=True)
    锁.write_text(json.dumps({
        "pid": pid,
        "启动时刻": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(启动时间戳)),
        "启动时间戳": 启动时间戳,
        "仓库根": 仓库根文本 if 仓库根文本 is not None else str(根),
    }, ensure_ascii=False), encoding="utf-8")
    return 锁


class 锁落点与内容(unittest.TestCase):
    """判据 1/2：落点必须在 `工程缓存/` 下，内容必须够人核。"""

    def test_锁落在工程缓存下(self) -> None:
        self.assertTrue(编译口.锁相对路径.startswith("工程缓存/"),
                        f"锁必须落在 工程缓存/ 下（该目录被工作区指纹排除），实得 {编译口.锁相对路径}")

    def test_锁文件是git忽略件(self) -> None:
        """真实判据：本仓 `.gitignore` 的规则盖住它 —— 它才不会把工作区判成「含未提交变更」。

        调用形态（2026-09-23 实测收口，改的就是这里）：**必须带 `--no-index`**。
        `git check-ignore` 默认**会查索引**（`git check-ignore -h`：`--no-index  ignore index when
        checking`），路径一旦被 `git add` 过（哪怕是 `-f`）就返回 1「没被忽略」—— 那时红的是
        「锁文件进了暂存区」，不是「忽略规则没了」，判据指错了方向。三拍实测（临时仓同路径）：
        未跟踪=0 / `git add -f` 后=1 / 带 `--no-index`=0。
        另：git 走本仓指定的绝对路径，不赌 PATH 里碰巧是哪个。
        """
        完成 = subprocess.run(
            [GIT, "check-ignore", "--no-index", "-v", 编译口.锁相对路径],
            cwd=str(仓库根), capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(完成.returncode, 0,
                         f"锁文件必须被 git 忽略（否则工作区指纹恒判含未提交变更）：{编译口.锁相对路径}")
        # 反向保护：命中的必须是**随代码走的**本仓 `.gitignore`（相对路径），
        # 不是本机全局 excludes（`~/.config/git/ignore` 会报绝对路径）或 `.git/info/exclude`
        # —— 那些只在本机成立，换台机器就漏，等于判据在本地自欺。
        来源 = (完成.stdout or "").split(":", 1)[0]
        self.assertTrue(来源.endswith(".gitignore") and not 来源.startswith("/"),
                        f"忽略规则必须出自本仓 .gitignore（随代码走，换机也成立），实得来源 {来源!r}："
                        f"{完成.stdout!r}")

    def test_占锁后内容含pid启动时刻与仓库根(self) -> None:
        根 = _临时根()
        try:
            句柄 = 编译口.占单写者锁(根)
            锁 = 根 / 编译口.锁相对路径
            self.assertTrue(锁.is_file(), f"占锁后锁文件必须存在：{锁}")
            数据 = json.loads(锁.read_text(encoding="utf-8"))
            self.assertEqual(数据.get("pid"), os.getpid(), "锁内容必须含本进程 pid")
            self.assertTrue(str(数据.get("启动时刻") or ""), "锁内容必须含启动时刻")
            self.assertEqual(数据.get("仓库根"), str(根), "锁内容必须含仓库根绝对路径")
            self.assertEqual(句柄["夺锁说明"], "", "新占的锁不是夺来的，夺锁说明必须为空")
            编译口.释放单写者锁(句柄)
            self.assertFalse(锁.is_file(), "释放后锁文件必须消失")
        finally:
            _清临时根(根)


class 活锁必须拒启(unittest.TestCase):
    """判据 3：**起两个编译口**，第二个必须被拒启（不是挂死、不是静默并发跑）。"""

    def setUp(self) -> None:
        # 自己占一把真仓库的锁；占不到（外层编译口已持有，例如本测试正跑在它的步骤5 里）
        # 同样是「锁被占」的合法现场，照样取证 —— 只是这把锁不由本测试释放。
        self.自己占的: dict | None = None
        try:
            self.自己占的 = 编译口.占单写者锁(仓库根)
        except 编译口.锁被占:
            self.自己占的 = None

    def tearDown(self) -> None:
        if self.自己占的 is not None:
            编译口.释放单写者锁(self.自己占的)

    def test_第二个编译口被拒启并如实报原话(self) -> None:
        环境 = {**os.environ, 编译口.编译口嵌套标记: ""}   # 显式清掉嵌套标记：本条要的就是「第二个写者」
        开始 = time.monotonic()
        完成 = subprocess.run(
            [sys.executable, "-m", "开发工具.开发编译口.编译口", "--文件", "README.md"],
            cwd=str(仓库根), capture_output=True, text=True, timeout=60, env=环境,
        )
        耗时 = time.monotonic() - 开始
        出 = (完成.stdout or "") + (完成.stderr or "")
        self.assertNotEqual(完成.returncode, 0,
                            f"第二个编译口必须拒启（非 0），实得 {完成.returncode}；输出：\n{出}")
        self.assertIn("同树已有编译口在跑（PID ", 出, f"必须如实报是谁在跑：\n{出}")
        self.assertIn("启动于 ", 出, f"必须如实报启动时刻：\n{出}")
        self.assertIn("五态结论：未核验", 出, f"拒启按未核验记（不占通过位）：\n{出}")
        self.assertLess(耗时, 30, f"拒启必须是「立刻拒」，不是挂死（实测耗时 {耗时:.1f}s）")
        # 反向保护：拒启的进程不得真去跑主流程（跑了就等于并发写者没被挡住）。
        self.assertNotIn("═══ 开发编译口", 出, "拒启时不得进入主流程（那是并发写）")


class 陈旧锁可夺但必须如实报(unittest.TestCase):
    """判据 4：PID 不存在 / 启动超阈值 ⇒ 可夺，且输出如实报「夺了陈旧锁（原 PID …）」。"""

    def test_pid不存在视为陈旧可夺(self) -> None:
        根 = _临时根()
        try:
            _写锁(根, pid=999_999, 启动时间戳=time.time())
            收集: list[str] = []
            句柄, 拒启 = 编译口.起单写者守卫(True, 根, 打印=收集.append)
            self.assertFalse(拒启, f"陈旧锁不该拒启：{收集}")
            self.assertIsNotNone(句柄)
            assert 句柄 is not None
            self.assertIn("原 PID 999999 已不存在", 句柄["夺锁说明"], "夺锁理由必须点名原 PID")
            文本 = "\n".join(收集)
            self.assertIn("夺了陈旧锁（原 PID 999999 已不存在）", 文本,
                          f"夺陈旧锁必须如实报，不许静默夺：\n{文本}")
            编译口.释放单写者锁(句柄)
        finally:
            _清临时根(根)

    def test_启动超阈值视为陈旧可夺(self) -> None:
        根 = _临时根()
        try:
            # 用**活 PID**（本进程）但把启动时刻推到阈值之外 —— 只有时长这一条能判它陈旧。
            _写锁(根, pid=os.getpid(), 启动时间戳=time.time() - 编译口.锁陈旧秒 - 60)
            收集: list[str] = []
            句柄, 拒启 = 编译口.起单写者守卫(True, 根, 打印=收集.append)
            self.assertFalse(拒启, f"超阈值锁不该拒启：{收集}")
            assert 句柄 is not None
            self.assertIn("原 PID ", 句柄["夺锁说明"], "夺锁理由必须点名原 PID")
            self.assertIn(">阈值", 句柄["夺锁说明"], "夺锁理由必须带出阈值判据")
            self.assertIn("夺了陈旧锁（原 PID ", "\n".join(收集))
            编译口.释放单写者锁(句柄)
        finally:
            _清临时根(根)

    def test_反向保护_活锁不许被夺(self) -> None:
        """★ 反向保护：阈值内的活锁**不许**夺 —— 夺了就是把并发窗口亲手打开。"""
        根 = _临时根()
        try:
            _写锁(根, pid=os.getpid(), 启动时间戳=time.time())
            with self.assertRaises(编译口.锁被占):
                编译口.占单写者锁(根)
        finally:
            _清临时根(根)


class 判不出来一律拒启(unittest.TestCase):
    """判据 5：fail-closed —— 探测不出有没有别人在跑，就不许静默放行。"""

    def _拒启取证(self, 根: Path) -> str:
        收集: list[str] = []
        句柄, 拒启 = 编译口.起单写者守卫(True, 根, 打印=收集.append)
        self.assertTrue(拒启, f"判不出来必须拒启：{收集}")
        self.assertIsNone(句柄, "拒启时不得返回锁句柄")
        文本 = "\n".join(收集)
        self.assertIn("拒启", 文本, f"拒启必须如实报：\n{文本}")
        self.assertIn("五态结论：未核验", 文本, f"拒启按未核验记：\n{文本}")
        return 文本

    def test_锁文件是坏json必须拒启(self) -> None:
        根 = _临时根()
        try:
            锁 = 根 / 编译口.锁相对路径
            锁.parent.mkdir(parents=True, exist_ok=True)
            锁.write_text("{坏 json", encoding="utf-8")
            self.assertIn("锁文件读不出", self._拒启取证(根))
        finally:
            _清临时根(根)

    def test_锁文件缺字段必须拒启(self) -> None:
        根 = _临时根()
        try:
            锁 = 根 / 编译口.锁相对路径
            锁.parent.mkdir(parents=True, exist_ok=True)
            锁.write_text(json.dumps({"pid": os.getpid()}, ensure_ascii=False), encoding="utf-8")
            self.assertIn("锁文件缺字段", self._拒启取证(根))
        finally:
            _清临时根(根)

    def test_启动时刻解析不出必须拒启(self) -> None:
        根 = _临时根()
        try:
            锁 = 根 / 编译口.锁相对路径
            锁.parent.mkdir(parents=True, exist_ok=True)
            锁.write_text(json.dumps({"pid": os.getpid(), "启动时刻": "昨天下午",
                                   "仓库根": str(根)}, ensure_ascii=False), encoding="utf-8")
            self.assertIn("启动时刻解析不出", self._拒启取证(根))
        finally:
            _清临时根(根)


class 只读与嵌套不占锁(unittest.TestCase):
    """判据 6：只有会写盘的运行模式才占锁（取舍理由见编译口 `锁相对路径` 注释块）。"""

    def test_只读不占锁且如实说明(self) -> None:
        根 = _临时根()
        try:
            收集: list[str] = []
            句柄, 拒启 = 编译口.起单写者守卫(False, 根, 打印=收集.append)
            self.assertFalse(拒启)
            self.assertIsNone(句柄, "`--只读` 不写派生件 ⇒ 不占锁")
            self.assertFalse((根 / 编译口.锁相对路径).is_file(), "只读不得留下锁文件")
            self.assertIn("不占锁", "\n".join(收集), "不占锁要如实说明，不静默跳过")
        finally:
            清 = 根 / 编译口.锁相对路径
            清.unlink(missing_ok=True)
            try:
                根.rmdir()
            except OSError:
                pass

    def test_只读在锁被占时仍不冲突(self) -> None:
        """只读与「已有写者」并存：它不该去抢锁，也不该拒启（多读者无害）。"""
        根 = _临时根()
        try:
            持有 = 编译口.占单写者锁(根)
            收集: list[str] = []
            句柄, 拒启 = 编译口.起单写者守卫(False, 根, 打印=收集.append)
            self.assertFalse(拒启, f"只读不该被写者的锁拒启：{收集}")
            self.assertIsNone(句柄)
            self.assertTrue((根 / 编译口.锁相对路径).is_file(), "只读不得动写者的锁")
            编译口.释放单写者锁(持有)
        finally:
            _清临时根(根)


class 释放只删自己那把(unittest.TestCase):
    """判据 7：锁里 pid 不是本进程时，释放不得动它。"""

    def test_别人的锁不许被释放(self) -> None:
        根 = _临时根()
        try:
            _写锁(根, pid=os.getpid() + 1, 启动时间戳=time.time())
            锁 = 根 / 编译口.锁相对路径
            编译口.释放单写者锁({"路径": 锁, "pid": os.getpid()})
            self.assertTrue(锁.is_file(), "释放不得删掉别人的锁（那是亲手打开并发窗口）")
        finally:
            _清临时根(根)

    def test_读不出的锁留给下一轮按陈旧处理(self) -> None:
        根 = _临时根()
        try:
            锁 = 根 / 编译口.锁相对路径
            锁.parent.mkdir(parents=True, exist_ok=True)
            锁.write_text("{坏 json", encoding="utf-8")
            编译口.释放单写者锁({"路径": 锁, "pid": os.getpid()})
            self.assertTrue(锁.is_file(), "读不出就不删，留给下一轮按陈旧锁夺并如实报")
        finally:
            _清临时根(根)


class 接线到开发循环(unittest.TestCase):
    """守卫件本身必须被编译口点名（13.1：有实现却不在必经路径上 = 半个强制）。"""

    def test_编译口点名本测试模块(self) -> None:
        影响面 = {"受影响包": [], "反向依赖闭包": [],
                  "非包文件": ["开发工具/开发编译口/编译口.py"]}
        点名 = 编译口.点名模块(影响面)
        self.assertIn("测试中心.开发工具.测试_编译口未核验与门禁清单", 点名)
        self.assertIn("测试中心.开发工具.测试编译口单写者守卫", 点名,
                      "改了编译口必须点名本测试，否则守卫躺红无人知")


if __name__ == "__main__":
    unittest.main()
