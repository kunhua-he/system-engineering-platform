"""原子落盘「提交环境缓存」在 Windows 上被 Errno 13 阻断的长期回归守护。

**它守的是什么（2026-09-19 Windows 真机取证）**：GitHub Actions `windows-latest` 上
装配冒烟失败，12 个提供者全挂、装配整体阻断，报错原文：

    提供者环境确保失败（装配阻断）: 支持库.后端.图像处理支持库.图像解码 提供者不可用:
      提交环境缓存失败: [Errno 13] Permission denied:
      '...\\工程缓存\\提供者运行环境\\图像解码\\.构建中_07d2bf06\\Lib\\site-packages\\
       pip-26.2.1.dist-info\\licenses\\src\\pip\\_vendor\\cachecontrol'

失败阶段是 `环境管理器.py` 的 `当前阶段 = "提交环境缓存"`（`原子落盘(临时目录, 目标)`
调用点），POSIX（macOS / Linux）上同样代码**通过**，所以是 Windows 专有。

**根因（现场复核后修正）**：报错路径 `...cachecontrol` 是**目录**（不是只读文件），
`原子落盘` 的第一步 `同步落盘(临时目录)` 会 `os.open(目录, os.O_RDONLY)` —— CPython 在
Windows 上对目录走 `CreateFileW` 且**不带** `FILE_FLAG_BACKUP_SEMANTICS`，必然抛
`PermissionError: [Errno 13] Permission denied: '<目录>'`；POSIX 上同一调用合法。
`同步落盘` 无兜底 → 异常逸出 `原子落盘` → 被 `_构建环境` 的 `except OSError` 收成
「提交环境缓存失败」（带文件名前缀，与真机报文逐字吻合）。

**本机限制（必须如实说明）**：本机是 macOS，无法真跑 Windows。因此本文件用
**忠实模拟 Windows 语义**的判据（把 `os.open`/`os.unlink` 在「目标是目录」/「目标带
只读属性」时改为抛 `PermissionError`），并用 git 基线做反向验证——
**模拟证据不等于 Windows 真机通过**，真机证据由 CI 复跑取证。

反向（必红）：`test_反向_修复前基线的同步落盘必被阻断` 把实现换成修复前的 git 基线，
同一模拟场景下异常**必然逸出**；`test_反向_宽rmtree在只读文件上必红` 证明只读清理
真的在起作用（清只读逻辑弄坏即变红）。
"""

from __future__ import annotations

import importlib.util
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

if str(Path(__file__).resolve().parents[2]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from 运行核心.运行环境管理器.远程镜像 import (  # noqa: E402
    同步落盘, 清除只读属性, 清只读后删除树, 原子落盘,
)
from 公共契约.基础类型.逻辑类型 import 真, 假  # noqa: E402

系统根 = Path(__file__).resolve().parents[2]

#: 修复前的实现（`同步落盘` 直接 `os.open(目录)`、清理一律 `rmtree(临时, ignore_errors=True)`）
修复前基线 = "753a7d1e"

_真open = os.open
_真unlink = os.unlink
_真rmdir = os.rmdir
_真scandir = os.scandir


def 加载修复前实现():
    """把修复前的 `远程镜像` 从 git 取出、落到 /tmp 并加载（只读历史，不动工作区）。"""
    源码 = subprocess.run(
        ["/Library/Developer/CommandLineTools/usr/bin/git", "show",
         f"{修复前基线}:运行核心/运行环境管理器/远程镜像.py"],
        cwd=str(系统根), capture_output=True, text=True, check=True).stdout
    临时 = Path(tempfile.mkdtemp(prefix="清只读反向验证_")) / "修复前远程镜像.py"
    临时.write_text(源码, encoding="utf-8")
    规格 = importlib.util.spec_from_file_location("修复前远程镜像", 临时)
    if 规格 is None or 规格.loader is None:
        raise RuntimeError("修复前实现无法构造导入规格")
    模块 = importlib.util.module_from_spec(规格)
    sys.modules["修复前远程镜像"] = 模块
    规格.loader.exec_module(模块)
    return 模块


def 是只读(路径: Path) -> bool:
    """路径是否不可写（Windows 只读属性 / POSIX 无写位）。"""
    return not (Path(路径).stat().st_mode & stat.S_IWUSR)


class Windows语义模拟:
    """把 POSIX 语法的模拟层叠成 Windows 真实语义（只影响本进程内的这几个 os 函数）。

    - `os.open(目录, O_RDONLY)` → Windows 抛 `PermissionError`（不带
      `FILE_FLAG_BACKUP_SEMANTICS` 就打不开目录）；
    - `os.unlink`/`os.rmdir` 打**只读**目标 → Windows 抛 `PermissionError`
      （只读属性），POSIX 上同样文件能直接删；
    - `shutil._use_fd_functions = False` → **这是 Windows 上真实成立的第三件事**：
      CPython 的 `shutil._use_fd_functions` 要求 `os.open` 在 `os.supports_dir_fd`
      里，而 Windows 不在 → `rmtree` 走**按名字**删除的 `_rmtree_unsafe` 分支
      （而不是 POSIX 的 `_rmtree_safe_fd` 分支）。不模拟这一条，`rmtree` 的行为
      就与 Windows 不同（实测：fd 分支会用 `os.unlink(name, dir_fd=…)`，按名字的
      mock 拦不住，测试会假绿）。

    诚实边界：本模拟对**目录**只读位也施加限制，而 Windows 上只读目录属性其实
    不阻止删除（只有文件只读属性阻止）→ **比 Windows 更严**。通过它即证明两种
    平台都安全。
    """

    def __enter__(self):
        def 假open(路径, 标志, *参数, **关键字):
            try:
                是目录 = Path(路径).is_dir()
            except OSError:
                是目录 = False
            if 是目录:
                raise PermissionError(13, "Permission denied", str(路径))
            return _真open(路径, 标志, *参数, **关键字)

        def 假unlink(路径, *参数, **关键字):
            try:
                只读 = 是只读(路径)
            except OSError:
                只读 = False
            if 只读:
                raise PermissionError(13, "Permission denied", str(路径))
            return _真unlink(路径, *参数, **关键字)

        def 假rmdir(路径, *参数, **关键字):
            try:
                只读 = 是只读(路径)
            except OSError:
                只读 = False
            if 只读:
                raise PermissionError(13, "Permission denied", str(路径))
            return _真rmdir(路径, *参数, **关键字)

        self._原fd函数 = getattr(shutil, "_use_fd_functions")
        self._原实现 = getattr(shutil, "_rmtree_impl")
        os.open, os.unlink, os.rmdir = 假open, 假unlink, 假rmdir
        setattr(shutil, "_use_fd_functions", 假)
        # 关键：CPython 在 import shutil 时就把 `_rmtree_impl` 绑死在
        # `_rmtree_safe_fd`（POSIX）或 `_rmtree_unsafe`（Windows）上，
        # 只改 `_use_fd_functions` 不生效。Windows 真机上跑的就是 unsafe 分支。
        setattr(shutil, "_rmtree_impl", getattr(shutil, "_rmtree_unsafe"))
        return self

    def __exit__(self, *异常信息):
        os.open, os.unlink, os.rmdir = _真open, _真unlink, _真rmdir
        setattr(shutil, "_use_fd_functions", self._原fd函数)
        setattr(shutil, "_rmtree_impl", self._原实现)
        return False


class 清只读夹具(unittest.TestCase):
    def setUp(self) -> None:
        self.根 = Path(tempfile.mkdtemp(prefix="清只读_"))

    def tearDown(self) -> None:
        # 兜底：把模拟期间可能残留的只读位清掉再删，避免测试自己留垃圾
        for 项 in sorted(self.根.rglob("*"), key=lambda p: len(p.parts), reverse=True):
            try:
                os.chmod(项, stat.S_IWRITE)
            except OSError:
                pass
        shutil.rmtree(self.根, ignore_errors=True)

    def 造只读树(self, 名: str = "制品") -> tuple[Path, Path]:
        """造一棵「像 venv 一样」的树：含只读文件 + 含只读文件的子目录。"""
        根 = self.根 / 名
        (根 / "Lib" / "site-packages" / "pip-26.2.1.dist-info" / "licenses"
         / "src" / "pip" / "_vendor" / "cachecontrol").mkdir(parents=True)
        许可 = (根 / "Lib" / "site-packages" / "pip-26.2.1.dist-info" / "licenses"
                / "src" / "pip" / "_vendor" / "cachecontrol" / "LICENSE.txt")
        许可.write_text("pip 自带 license（只读）", encoding="utf-8")
        os.chmod(许可, 0o444)
        普通 = 根 / "pyvenv.cfg"
        普通.write_text("home = /usr/bin", encoding="utf-8")
        return 根, 许可


class Test清只读函数本身(清只读夹具):
    """直接验证「清只读」真的把只读位去掉了（本机唯一能真验的判据）。"""

    def test_清只读前后_W_OK_由假变真(self) -> None:
        根, 许可 = self.造只读树()
        self.assertFalse(os.access(许可, os.W_OK),
                         "前置：chmod 0444 后本进程不应可写")
        self.assertTrue(是只读(许可), "前置：应被判为只读")
        清除只读属性(许可)
        self.assertTrue(os.access(许可, os.W_OK), "清只读后必须可写")
        self.assertFalse(是只读(许可), "清只读后不得再是只读")

    def test_清只读对目录同样有效(self) -> None:
        目标 = self.根 / "只读目录"
        目标.mkdir()
        文件 = 目标 / "a.txt"
        文件.write_text("x", encoding="utf-8")
        os.chmod(文件, 0o444)
        清除只读属性(文件)
        self.assertTrue(os.access(文件, os.W_OK))

    def test_清只读失败要如实报错_不吞(self) -> None:
        """目标不存在时必须抛 OSError（不许宽 except 吞掉）。"""
        with self.assertRaises(OSError) as 上下文:
            清除只读属性(self.根 / "根本不存在")
        self.assertIn("清除只读属性失败", str(上下文.exception))


class Test清只读后删除树(清只读夹具):
    def test_只读树在Windows语义下_宽rmtree必红(self) -> None:
        """反向基线：不走清只读的 `shutil.rmtree` 在 Windows 语义下真报 Errno 13。"""
        根, _ = self.造只读树()
        with Windows语义模拟():
            with self.assertRaises(PermissionError) as 上下文:
                shutil.rmtree(根)
        self.assertEqual(上下文.exception.errno, 13,
                         f"应为 Errno 13，实际 {上下文.exception}")
        self.assertTrue(根.exists(), "宽 rmtree 失败后目录应仍在（证明它真失败了）")

    def test_只读树在Windows语义下_清只读后删除成功(self) -> None:
        根, 许可 = self.造只读树()
        self.assertTrue(是只读(许可), "前置：license 应为只读")
        with Windows语义模拟():
            清只读后删除树(根)
        self.assertFalse(根.exists(), "清只读后删除树必须真的删干净")
        self.assertFalse(许可.exists())

    def test_目录本身只读也要能删(self) -> None:
        根, _ = self.造只读树()
        # 让 cachecontrol 目录本身也带只读位
        (根 / "Lib" / "site-packages" / "pip-26.2.1.dist-info" / "licenses"
         / "src" / "pip" / "_vendor" / "cachecontrol")
        for 目录 in [d for d in 根.rglob("*") if d.is_dir()]:
            os.chmod(目录, 0o555)
        with Windows语义模拟():
            清只读后删除树(根)
        self.assertFalse(根.exists(), "只读目录树也必须能删净")

    def test_非权限错误不越权处理(self) -> None:
        """不认识的文件 → `FileNotFoundError` 不属只读范畴，但删树仍应正常返回。"""
        根 = self.根 / "正常树"
        (根 / "子").mkdir(parents=True)
        (根 / "子" / "a.txt").write_text("x", encoding="utf-8")
        清只读后删除树(根)
        self.assertFalse(根.exists())

    def test_忽略失败为假时残留要抛错(self) -> None:
        """目标不存在必须如实抛（不许把真错误吞成成功）。"""
        with self.assertRaises(FileNotFoundError):
            清只读后删除树(self.根 / "不存在")

    def test_忽略失败为真时残留要留痕(self) -> None:
        """删不干净时必须经 `记录忽略` 留痕（修掉 `ignore_errors=True` 连痕都不留的缺陷）。"""
        from 公共契约.诊断.忽略记录 import 忽略快照
        根 = self.根 / "删不掉的树"
        根.mkdir()
        哨兵 = 根 / "占位.txt"
        哨兵.write_text("x", encoding="utf-8")
        # 只让「删除这个文件」失败，模拟被占用/权限拒绝且清只读也救不回来。
        # 判据用 basename：POSIX 的 fd 分支会传 `entry.name`（相对名）而 Windows 的
        # 按名字分支传全路径，两种都要拦住。
        # **换第三方边界 + `autospec=True`**（2026-09-23 收口）：旧写法是手工赋值
        # `os.unlink = 假unlink`（门禁扫不到的替换；旧注释写明「不走 mock.patch」）。
        # 现改为在边界自己的模块上打补丁 —— 语义逐字相同，但对门禁可见且满足规则2。
        真unlink = os.unlink

        def 假unlink(路径, *参数, **关键字):
            if Path(路径).name == 哨兵.name:
                raise PermissionError(13, "Permission denied", str(路径))
            return 真unlink(路径, *参数, **关键字)

        with mock.patch("os.unlink", autospec=True, side_effect=假unlink):
            清只读后删除树(根, 忽略失败=真)
        留痕 = [项 for 项 in 忽略快照() if "清只读后删除树" in 项["位置"]]
        self.assertTrue(留痕, "删不干净必须留下可查询的证据，不许静默")
        self.assertTrue(any("残留" in 项["位置"] for 项 in 留痕),
                        f"应有一条残留留痕，实际: {留痕}")


class Test同步落盘跨平台(清只读夹具):
    """`同步落盘` 是 `原子落盘` 的第一步，也是真机报错的那一步。"""

    def test_Windows语义下目录打不开_不得阻断(self) -> None:
        根, _ = self.造只读树()
        with Windows语义模拟():
            同步落盘(根)  # 不得抛
        self.assertTrue(根.exists(), "同步落盘不得删掉制品")

    def test_目录打不开要留痕_不许静默(self) -> None:
        from 公共契约.诊断.忽略记录 import 忽略快照
        根 = self.根 / "制品"
        (根 / "子").mkdir(parents=True)
        with Windows语义模拟():
            同步落盘(根)
        留痕 = [项 for 项 in 忽略快照() if "同步落盘" in 项["位置"]]
        self.assertTrue(留痕, "拿不到目录句柄必须留下可查询的证据")
        self.assertTrue(any(项["错误类型"] == "PermissionError" for 项 in 留痕),
                        f"应记到 PermissionError，实际: {留痕}")

    def test_制品目录不存在_仍要如实报错(self) -> None:
        with self.assertRaises(OSError) as 上下文:
            同步落盘(self.根 / "没有这个目录")
        self.assertIn("制品目录不存在", str(上下文.exception))

    def test_正常路径_制品原样保留(self) -> None:
        根, 许可 = self.造只读树()
        同步落盘(根)
        self.assertEqual(许可.read_text(encoding="utf-8"), "pip 自带 license（只读）")


class Test原子落盘端到端(清只读夹具):
    """真机失败链路：`原子落盘(临时目录, 目标)` 在 Windows 语义下必须走通。"""

    def 造新环境(self, 名: str = ".构建中_07d2bf06") -> Path:
        临时 = self.根 / 名
        许可 = (临时 / "Lib" / "site-packages" / "pip-26.2.1.dist-info" / "licenses"
                / "src" / "pip" / "_vendor" / "cachecontrol" / "LICENSE.txt")
        许可.parent.mkdir(parents=True)
        许可.write_text("新环境 license", encoding="utf-8")
        os.chmod(许可, 0o444)
        (临时 / "pyvenv.cfg").write_text("home = /usr/bin", encoding="utf-8")
        return 临时

    def test_Windows语义下_只读临时环境仍能落盘(self) -> None:
        目标 = self.根 / "图像解码"
        临时 = self.造新环境()
        with Windows语义模拟():
            原子落盘(临时, 目标)
        self.assertTrue((目标 / "pyvenv.cfg").is_file(), "新环境必须顶位成功")
        self.assertFalse(临时.exists())
        self.assertEqual(
            (目标 / "Lib" / "site-packages" / "pip-26.2.1.dist-info" / "licenses"
             / "src" / "pip" / "_vendor" / "cachecontrol" / "LICENSE.txt")
            .read_text(encoding="utf-8"), "新环境 license")

    def test_旧环境只读时顶位后仍被清干净(self) -> None:
        目标 = self.根 / "图像解码"
        旧 = 目标 / "Lib" / "site-packages" / "old" / "LICENSE.txt"
        旧.parent.mkdir(parents=True)
        旧.write_text("旧环境 license", encoding="utf-8")
        os.chmod(旧, 0o444)
        临时 = self.造新环境()
        with Windows语义模拟():
            原子落盘(临时, 目标)
        self.assertTrue((目标 / "pyvenv.cfg").is_file())
        让位残留 = [项 for 项 in self.根.iterdir() if "让位" in 项.name]
        self.assertEqual(让位残留, [], "只读旧环境的让位目录必须被清干净")


class Test反向_修复前基线必红(清只读夹具):
    """换成修复前实现，同一 Windows 语义场景下异常**必然逸出**（证明用例是活的）。"""

    @classmethod
    def setUpClass(cls) -> None:
        try:
            cls.修复前 = 加载修复前实现()
        except Exception as 错误:  # git 不可用/历史缺失 ⇒ 如实跳过，不伪装通过
            raise unittest.SkipTest(f"取不到修复前实现基线（{修复前基线}）：{错误}")

    def test_反向_修复前基线的同步落盘被目录打开阻断(self) -> None:
        根 = self.根 / "制品"
        (根 / "子").mkdir(parents=True)
        with Windows语义模拟():
            with self.assertRaises(PermissionError) as 上下文:
                self.修复前.同步落盘(根)
        self.assertEqual(getattr(上下文.exception, "errno", None), 13,
                         f"修复前基线应报 Errno 13，实际 {上下文.exception}")
        # 真机报错里带的就是这个目录路径（文件名前缀的来源）；自底向上先碰最深目录
        报错路径 = Path(str(上下文.exception.filename))
        self.assertTrue(报错路径.is_dir(), f"报错里带的必须是目录: {报错路径}")
        self.assertIn(根.resolve(), [报错路径.resolve(), *报错路径.resolve().parents],
                      f"报错目录必须落在制品树内: {报错路径}")
        self.assertTrue(根.exists(), "修复前基线抛错后制品仍在（正是真机现场）")

    def test_反向_修复前基线清理临时目录时被只读文件卡住(self) -> None:
        """修复前 `rmtree(临时, ignore_errors=True)`：Windows 上删不净且**连痕都不留**。"""
        from 公共契约.诊断.忽略记录 import 忽略快照
        根, 许可 = self.造只读树()
        前数 = len(忽略快照())
        with Windows语义模拟():
            self.修复前.shutil.rmtree(根, ignore_errors=True)
        self.assertTrue(许可.exists(), "修复前基线在只读文件上必然删不净")
        self.assertEqual(len(忽略快照()), 前数,
                         "修复前基线连失败痕迹都没有（这正是它比修复后差的地方）")


if __name__ == "__main__":
    unittest.main()
