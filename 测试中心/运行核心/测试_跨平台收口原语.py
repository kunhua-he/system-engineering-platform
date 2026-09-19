"""跨平台收口原语：四个新原语的**分支选择**与**调用点是否真的收口**的机器判据。

背景（第一轮《审计_平台判断越界_20260919》）：五处调用点里，
B1-1 / B1-2 / B1-3 / B2-1 是「平台判断决定行为分叉」，B3-1 是「异常文案裸读平台标志」。
按华哥 2026-09-16 裁决的**实质**口径（`开发文档/项目说明.md` §4 第 1065 行）：
「调用点不许写平台判断；必须加平台判断才能改通时，**补收口层，不许就地分叉**」。
四处调用点即使只经收口层取平台值，**分支动作**仍由调用点决定 —— 那是第二份实现。

本测试锁两件事，缺一不可：

① **原语本身的三平台分支选择正确**（macOS 真跑；Windows / Linux 用 `sys.platform` 打桩，
   与 `测试中心/运行核心/测试_平台准入.py` 同一合法姿势 —— 反向验证的目的就是模拟另一个
   平台，必须直接打桩最底层标志，经收口层就打不到）；
② **调用点真的改调了原语、且自己没有留下平台分支**（静态 AST 判据 + 行为级一致性判据）。

**为什么必须有 ②**：只测 ① 的话，「原语写好了但调用点仍在就地分叉」照样全绿 ——
那正是本次要治的缺陷形态（假绿）。

安全：本测试**只读 + 只打内存桩**，不写仓库任何文件，不起服务，不真装配。
"""

from __future__ import annotations

import ast
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

系统根 = Path(__file__).resolve().parents[2]
if str(系统根) not in sys.path:
    sys.path.insert(0, str(系统根))

from 公共契约.基础类型.逻辑类型 import 真, 假  # noqa: E402
from 公共契约.运行时 import 平台适配  # noqa: E402

#: 五处调用点（第一轮审计点名）与其**必须调用的收口层原语**
调用点表 = {
    "运行核心/任务调度/任务进程.py": "多进程启动上下文",
    "支持库/后端/系统核心支持库/进程管理/实现/进程管理.py": "拆分命令文本",
    "启动监督器/容量基线.py": "进程内存RSS字节",
    "公共契约/运行时/运行缓存.py": "平台稳定缓存根",
    "开发工具/重建依赖锁.py": "原始平台标志",
}

#: 调用点里**禁止**出现的平台分叉形态（第一轮审计 §七 判据 3 的同形收敛）
禁止形态表 = {
    "裸读 sys.platform": (ast.Attribute, "sys", "platform"),
    "裸读 os.name": (ast.Attribute, "os", "name"),
    "platform.system()": (ast.Attribute, "platform", "system"),
    "platform.machine()": (ast.Attribute, "platform", "machine"),
}

#: 调用点里**禁止**出现的收口层平台取值后自行分叉（应改调上表原语）
禁止取值后分叉 = ("是Windows", "是macOS", "是Linux", "是POSIX")

#: 每个调用点文件里**允许保留**的收口层取值调用（第一轮审计 §三 C-D 判为合法探测：
#: `sandbox-exec` 是 macOS 专有内核沙箱，能力不存在时 fail-closed 拒绝执行，
#: 是**契约里写明的语义**，不是行为分叉；第二轮若统一成
#: `平台专有能力可用()` 再从此表删除）
合法取值白名单 = {
    "支持库/后端/系统核心支持库/进程管理/实现/进程管理.py": {"是macOS"},
}


def _读源码(相对路径: str) -> str:
    return (系统根 / 相对路径).read_text(encoding="utf-8")


def _属性链(节点: ast.AST) -> str:
    """把 `a.b.c` 形式拼成点号串；其余形态返回空串。"""
    段: list[str] = []
    while isinstance(节点, ast.Attribute):
        段.append(节点.attr)
        节点 = 节点.value
    if isinstance(节点, ast.Name):
        段.append(节点.id)
        return ".".join(reversed(段))
    return ""


class 测试多进程启动上下文(unittest.TestCase):
    """B1-1：fork / spawn 的选择必须由收口层给出。"""

    def test_本机POSIX给fork且不需序列化(self) -> None:
        上下文, 需序列化 = 平台适配.多进程启动上下文()
        self.assertEqual(上下文.get_start_method(), "fork")
        self.assertEqual(需序列化, 假)

    def test_模拟Windows给spawn且需序列化(self) -> None:
        """``sys.platform`` 打桩成 win32：必须走 spawn（Windows 上 fork 不存在）。"""
        with mock.patch.object(sys, "platform", "win32"):
            上下文, 需序列化 = 平台适配.多进程启动上下文()
            self.assertFalse(平台适配.是POSIX())
            self.assertEqual(上下文.get_start_method(), "spawn")
            self.assertEqual(需序列化, 真)

    def test_受限构建无fork时退spawn(self) -> None:
        """自称 POSIX 却不提供 fork：**必须退 spawn**，不许抛出去把导入期打死。"""
        import multiprocessing

        def _假取上下文(方法: str):
            if 方法 == "fork":
                raise ValueError("fork 不可用（模拟受限构建）")
            return _真取上下文(方法)

        _真取上下文 = multiprocessing.get_context
        with mock.patch.object(multiprocessing, "get_context", _假取上下文):
            上下文, 需序列化 = 平台适配.多进程启动上下文()
        self.assertEqual(上下文.get_start_method(), "spawn")
        self.assertEqual(需序列化, 真)


class 测试拆分命令文本(unittest.TestCase):
    """B1-2：`shlex` 的 posix 口径是平台语义差异，必须收口。"""

    def test_POSIX保留posix语义(self) -> None:
        import shlex

        命令 = "echo 'a b' c"
        self.assertEqual(平台适配.拆分命令文本(命令), shlex.split(命令))
        self.assertEqual(平台适配.拆分命令文本("echo 'a b' c"), ["echo", "a b", "c"])

    def test_模拟Windows保住反斜杠路径(self) -> None:
        """**B-28 回归**：Windows 路径在 posix 口径下会被拆坏。

        实测（本机 python3.14）：`shlex.split(r"C:\\tools\\app.exe")[0]` →
        `C:toolsapp.exe` —— posix 语义把 `\\` 当**转义符并剥掉**，路径分隔符全丢，
        结果不再是合法路径。**注意**：审计件写作 `C:oolsapp.exe`（少一个 `t`）是笔误，
        真实退化形态是**丢分隔符**；两种写法都证明 posix 口径在 Windows 上不可用。
        """
        import shlex

        命令 = r"C:\tools\app.exe --flag"
        # 先证伪：posix 口径确实把路径拆坏（证明下面那条断言不是恒真）
        拆坏 = shlex.split(命令)
        self.assertEqual(拆坏[0], "C:toolsapp.exe")
        self.assertNotIn("\\", 拆坏[0], "posix 口径把路径分隔符全丢了")
        with mock.patch.object(sys, "platform", "win32"):
            结果 = 平台适配.拆分命令文本(命令)
        self.assertEqual(结果, [r"C:\tools\app.exe", "--flag"])
        self.assertIn("\\", 结果[0], "Windows 口径必须保住反斜杠路径")

    def test_模拟Windows剥成对引号(self) -> None:
        with mock.patch.object(sys, "platform", "win32"):
            self.assertEqual(
                平台适配.拆分命令文本('"C:\\Program Files\\app.exe" /x'),
                [r"C:\Program Files\app.exe", "/x"])

    def test_非法引号原样逸出(self) -> None:
        with self.assertRaises(ValueError):
            平台适配.拆分命令文本("echo '未闭合")


class 测试进程内存RSS字节(unittest.TestCase):
    """B1-3：RSS 取法（ps vs /proc）三分支显式判定，三态 fail-closed。"""

    def test_本机macOS真跑拿到正数(self) -> None:
        字节, 原因 = 平台适配.进程内存RSS字节(os.getpid())
        self.assertEqual(原因, "")
        self.assertGreater(字节, 0, "macOS 上 ps -o rss= 必须拿到真实读数")

    def test_读数与ps原始输出量纲一致(self) -> None:
        """字节 = ps 的 KB × 1024：量纲错了会让阈值差 1024 倍。

        **容差 2 MiB**：ps 与收口层是**两次独立采样**，进程 RSS 逐秒浮动几十 KB 是正常的
        （实测两次相差 32~48 KB），逐字相等是**恒不稳**的判据；而量纲错会差三个数量级
        （实测约 31.5 MB ≈ 31 MiB），2 MiB 容差必然抓住。
        """
        import subprocess

        原始 = subprocess.run(["/bin/ps", "-o", "rss=", "-p", str(os.getpid())],
                            capture_output=True, text=True, timeout=5)
        期望 = int(原始.stdout.strip()) * 1024
        字节, 原因 = 平台适配.进程内存RSS字节(os.getpid())
        self.assertEqual(原因, "")
        self.assertLess(abs(字节 - 期望), 2 * 1024 * 1024,
                        f"量纲不一致：收口层 {字节} 对 ps×1024 {期望}（差 1024 倍会让阈值失真）")

    def test_模拟Windows显名不支持且不是零读数(self) -> None:
        with mock.patch.object(sys, "platform", "win32"):
            字节, 原因 = 平台适配.进程内存RSS字节(os.getpid())
        self.assertEqual(字节, 0)
        self.assertTrue(原因, "平台不支持必须显名原因，不许静默返回 0 冒充读数")
        self.assertIn("Windows", 原因)

    def test_非法进程ID拒绝(self) -> None:
        for 非法 in (0, -1, 真, "123", None):
            with self.subTest(非法=非法):
                字节, 原因 = 平台适配.进程内存RSS字节(非法)
                self.assertEqual(字节, 0)
                self.assertIn("进程ID", 原因)

    def test_ps命令覆盖生效且失败原因分阶段点名(self) -> None:
        """ps 指到不存在的路径 → 原因必须点明「ps 命令不可用」（与「pid 查不到」区分）。"""
        字节, 原因 = 平台适配.进程内存RSS字节(os.getpid(), ps命令="/不存在/ps")
        self.assertEqual(字节, 0)
        self.assertIn("ps 命令不可用", 原因)
        # 不存在的 pid → 另一类原因（进程已消失），不是「命令不可用」
        字节2, 原因2 = 平台适配.进程内存RSS字节(99999999)
        self.assertEqual(字节2, 0)
        self.assertNotIn("ps 命令不可用", 原因2)


class 测试平台稳定缓存根(unittest.TestCase):
    """B2-1：平台级稳定缓存根是**唯一**一处平台缓存口径。"""

    def test_模拟macOS走LibraryCaches(self) -> None:
        with mock.patch.object(sys, "platform", "darwin"):
            根 = 平台适配.平台稳定缓存根(环境={"HOME": "/用户/测试"})
        self.assertEqual(根, Path("/用户/测试/Library/Caches/系统工程平台/运行缓存"))

    def test_模拟Windows走LOCALAPPDATA并逐级回落(self) -> None:
        with mock.patch.object(sys, "platform", "win32"):
            self.assertEqual(
                平台适配.平台稳定缓存根(环境={"LOCALAPPDATA": r"C:\本地"}),
                Path(r"C:\本地") / "系统工程平台" / "运行缓存")
            self.assertEqual(
                平台适配.平台稳定缓存根(环境={"TEMP": r"C:\临时"}),
                Path(r"C:\临时") / "系统工程平台" / "运行缓存")
            回落 = 平台适配.平台稳定缓存根(环境={})
            self.assertEqual(回落.name, "运行缓存")
            self.assertIn("AppData", str(回落))

    def test_模拟Linux优先XDG再回落home(self) -> None:
        with mock.patch.object(sys, "platform", "linux"):
            self.assertEqual(
                平台适配.平台稳定缓存根(环境={"XDG_CACHE_HOME": "/xdg"}),
                Path("/xdg") / "系统工程平台" / "运行缓存")
            self.assertEqual(
                平台适配.平台稳定缓存根(环境={"HOME": "/家"}),
                Path("/家") / ".cache" / "系统工程平台" / "运行缓存")

    def test_应用名可改且空值回落缺省(self) -> None:
        with mock.patch.object(sys, "platform", "darwin"):
            self.assertEqual(平台适配.平台稳定缓存根("别的应用", 环境={"HOME": "/家"}),
                             Path("/家/Library/Caches/别的应用/运行缓存"))
            self.assertEqual(平台适配.平台稳定缓存根("", 环境={"HOME": "/家"}),
                             Path("/家/Library/Caches/系统工程平台/运行缓存"))

    def test_只解析不创建目录(self) -> None:
        根 = 平台适配.平台稳定缓存根(环境={"HOME": "/绝对不存在的用户/测试"})
        self.assertFalse(根.exists(), "收口层只解析路径，不创建目录")


class 测试调用点已收口(unittest.TestCase):
    """静态判据：五处调用点里不许再有平台分叉形态。"""

    def _收集禁止形态(self, 相对路径: str, *, 源码: str | None = None) -> list[str]:
        """扫一段源码（缺省读仓库文件；`源码` 出口供反向验证喂**故意带分叉**的样本）。"""
        文本 = _读源码(相对路径) if 源码 is None else 源码
        树 = ast.parse(文本)
        命中: list[str] = []
        for 节点 in ast.walk(树):
            if not isinstance(节点, ast.Attribute):
                continue
            链 = _属性链(节点)
            for 名称, 形态 in 禁止形态表.items():
                if 链 == ".".join((形态[1], 形态[2])):
                    命中.append(f"{名称}（{链}）")
            if 链.startswith("平台适配."):
                名 = 链.split(".", 1)[1]
                if 名 in 禁止取值后分叉 and 名 not in 合法取值白名单.get(相对路径, set()):
                    命中.append(f"取值后自行分叉（平台适配.{名}）")
        return sorted(set(命中))

    def test_调用点无平台判定与取值后分叉(self) -> None:
        for 相对路径 in 调用点表:
            with self.subTest(文件=相对路径):
                命中 = self._收集禁止形态(相对路径)
                self.assertEqual(命中, [], f"{相对路径} 仍有平台分叉形态：{命中}")

    def test_调用点确实引用了指定原语(self) -> None:
        for 相对路径, 原语 in 调用点表.items():
            with self.subTest(文件=相对路径, 原语=原语):
                self.assertIn(原语, _读源码(相对路径),
                              f"{相对路径} 未出现收口层原语 {原语}")

    def test_平台适配公开面含四个新原语(self) -> None:
        for 名 in ("多进程启动上下文", "拆分命令文本", "进程内存RSS字节", "平台稳定缓存根"):
            with self.subTest(原语=名):
                self.assertIn(名, 平台适配.__all__)
                self.assertTrue(callable(getattr(平台适配, 名)))


class 测试调用点行为一致(unittest.TestCase):
    """行为判据：调用点的结果必须**就是**收口层原语的结果（防「写了但没调」）。

    时间敏感的读数一律用**受控桩**（收口层返回固定值）+ **容差**两条：进程 RSS 逐秒
    浮动几十 KB，拿「两次独立真采样」逐字比较是**恒不稳**的判据（实测差 48 KB 即失败），
    那不是缺陷而是判据本身错。真采样另有独立用例（`测试进程内存RSS字节` 的量纲用例
    用同一时刻的 ps 输出对账）。
    """

    def test_容量基线采样就是收口层读数(self) -> None:
        """容量基线的 MB 必须**逐字**来自收口层字节（受控桩：固定 3355443200 字节 = 3200 MB）。"""
        import 启动监督器.容量基线 as 容量模块

        固定字节 = 3355443200  # = 3200 MiB，非整 MB 便于抓取整错误

        def _固定读数(进程ID, *, ps命令=None):
            return 固定字节, ""

        with mock.patch.object(平台适配, "进程内存RSS字节", _固定读数):
            结果 = 容量模块.采样内存RSS(None)
        self.assertEqual(结果, {"成功": 真, "值MB": 3200.0, "错误码": "", "错误说明": ""},
                         "容量基线必须逐字转用收口层读数（除以 1048576），不得自发第二套换算")

    def test_容量基线真跑与收口层同量纲(self) -> None:
        """真跑：容量基线的 MB ≈ 收口层字节 / 1048576（容差 2 MB，吸收采样间隙的波动）。"""
        import 启动监督器.容量基线 as 容量模块

        结果 = 容量模块.采样内存RSS(None)
        self.assertTrue(结果["成功"], 结果)
        字节, 原因 = 平台适配.进程内存RSS字节(os.getpid())
        self.assertEqual(原因, "")
        self.assertLess(abs(结果["值MB"] - 字节 / 1048576), 2.0,
                        f"两者不同量纲或不同取法：{结果['值MB']} 对 {字节 / 1048576}")

    def test_容量基线在模拟Windows如实报失败不谎报成功(self) -> None:
        """收口前 Windows 会落进错误的 /proc 分支报「平台不支持」；收口后仍须失败，
        但失败必须来自收口层的显名原因，且**绝不许出现 0 MB 冒充读数**。"""
        import 启动监督器.容量基线 as 容量模块

        with mock.patch.object(sys, "platform", "win32"):
            结果 = 容量模块.采样内存RSS(None)
        self.assertEqual(结果["成功"], 假)
        self.assertEqual(结果["错误码"], "内存采样失败")
        self.assertEqual(结果["值MB"], -1.0, "采样失败必须报 -1，不许报 0")
        self.assertIn("Windows", 结果["错误说明"])

    def test_运行缓存根就是收口层结果(self) -> None:
        from 公共契约.运行时.运行缓存 import _平台稳定缓存根

        环境 = {"HOME": "/家", "LOCALAPPDATA": "/本地", "XDG_CACHE_HOME": "/xdg"}
        for 标志 in ("darwin", "win32", "linux", "freebsd"):
            with self.subTest(平台标志=标志):
                with mock.patch.object(sys, "platform", 标志):
                    self.assertEqual(_平台稳定缓存根(环境),
                                     平台适配.平台稳定缓存根(环境=环境))

    def test_任务进程池上下文就是收口层上下文(self) -> None:
        from 运行核心.任务调度.任务进程 import 任务进程池

        池 = 任务进程池(存储目录=Path("/tmp") / "跨平台收口原语测试")
        期望上下文, 期望需序列化 = 平台适配.多进程启动上下文()
        self.assertEqual(池.进程上下文.get_start_method(), 期望上下文.get_start_method())
        self.assertEqual(池.需序列化执行器, 期望需序列化)
        self.assertFalse(hasattr(池, "_选择进程上下文"),
                         "就地分叉的 _选择进程上下文 必须已被删除（改调收口层）")


class 测试反向验证(unittest.TestCase):
    """反向验证三拍：**故意弄坏 → 判据必红 → 还原 → 判据归绿**。

    姿势与 `测试中心/运行核心/测试_冷启动准入后端平台原语.py` 一致：把「正向断言体」
    抽成独立方法，喂一份**故意弄坏**的实现时它必须抛 `AssertionError`（报红）并点名坏态，
    撤掉桩（还原）后同一断言体必须不再抛（归绿）。

    **只打内存桩，不改仓库任何文件** —— 弄坏的是「原语行为」，判据必须立刻察觉；
    这证明上面那些绿不是恒绿。
    """

    @staticmethod
    def _断言上下文与序列化一致(标识: str) -> tuple[str, bool]:
        """正向判据①：**启动方式与「是否需序列化」必须自洽**。

        自洽口径（唯一）：`spawn` 的子进程是全新解释器 ⇒ 执行器必须显式序列化（真）；
        `fork` 继承父进程内存 ⇒ 不需要（假）。两者矛盾即为坏态。
        """
        from 运行核心.任务调度.任务进程 import 任务进程池

        池 = 任务进程池(存储目录=Path("/tmp") / f"跨平台收口原语-{标识}")
        方式 = str(池.进程上下文.get_start_method())
        需序列化 = bool(池.需序列化执行器)
        if 方式 == "spawn" and not 需序列化:
            raise AssertionError(
                f"坏态：启动方式为 spawn 却声明「执行器无需序列化」（{标识}）"
                "—— spawn 是全新解释器，不序列化必然拿不到执行器")
        if 方式 == "fork" and 需序列化:
            raise AssertionError(
                f"坏态：启动方式为 fork 却声明「执行器必须序列化」（{标识}）")
        return 方式, 需序列化

    @staticmethod
    def _断言RSS量纲与ps一致() -> int:
        """正向判据②：**收口层读数的量纲必须与 `ps -o rss=` 的 KB × 1024 一致**。

        容差 1 MiB：ps 与收口层是**两次独立采样**，进程 RSS 逐秒浮动几十 KB 是正常的
        （逐字比较会恒不稳）；而量纲错（把 KB 当字节）会差**三个数量级**（实测约 31.5 MB），
        1 MiB 的容差既能吸收正常浮动、又必然抓住量纲错。
        """
        import subprocess

        原始 = subprocess.run(["/bin/ps", "-o", "rss=", "-p", str(os.getpid())],
                            capture_output=True, text=True, timeout=5)
        期望 = int(原始.stdout.strip()) * 1024
        字节, 原因 = 平台适配.进程内存RSS字节(os.getpid())
        if 原因:
            raise AssertionError(f"坏态：本机 macOS 采样不该失败，实际原因：{原因}")
        容差 = 1024 * 1024
        if abs(字节 - 期望) > 容差:
            raise AssertionError(
                f"坏态：RSS 量纲与 ps 原始输出不一致（收口层 {字节} 对 ps×1024 {期望}，"
                f"差 {abs(字节 - 期望)} 字节 > 容差 {容差}）"
                "—— 差 1024 倍会让硬熔断阈值在不同平台含义不同")
        return 期望

    @staticmethod
    def _断言三平台缓存根互不相同() -> list[str]:
        """正向判据③：**三个平台必须给出三个不同的稳定缓存根**（且各走各的环境变量）。"""
        结果: list[str] = []
        with mock.patch.object(sys, "platform", "darwin"):
            结果.append(str(平台适配.平台稳定缓存根(环境={"HOME": "/家"})))
        with mock.patch.object(sys, "platform", "win32"):
            结果.append(str(平台适配.平台稳定缓存根(环境={"LOCALAPPDATA": "/本地"})))
        with mock.patch.object(sys, "platform", "linux"):
            结果.append(str(平台适配.平台稳定缓存根(环境={"XDG_CACHE_HOME": "/xdg"})))
        if len(set(结果)) != 3:
            raise AssertionError(f"坏态：平台稳定缓存根未按平台分叉，实测 {结果}")
        return 结果

    def test_正向三拍_启动方式与序列化自洽(self) -> None:
        self._断言上下文与序列化一致("正向")  # 不抛 ⇒ 绿

    def test_反向_弄坏多进程启动上下文则判据报红(self) -> None:
        """故意弄坏：POSIX 也返回 spawn 却声明「无需序列化」→ 判据必红；还原后归绿。"""
        import multiprocessing

        def _坏上下文():
            return multiprocessing.get_context("spawn"), 假  # 故意：谎报无需序列化

        with mock.patch.object(平台适配, "多进程启动上下文", _坏上下文), \
                mock.patch("运行核心.任务调度.任务进程.平台适配.多进程启动上下文", _坏上下文):
            with self.assertRaises(AssertionError) as 捕获:
                self._断言上下文与序列化一致("反向-坏上下文")
        文本 = str(捕获.exception)
        self.assertIn("坏态", 文本)
        self.assertIn("spawn", 文本)
        self.assertIn("无需序列化", 文本, "报红文本必须点名坏在哪一条，不能只报「不相等」")
        # 还原（撤桩）⇒ 同一断言体归绿
        self._断言上下文与序列化一致("还原")

    def test_反向_弄坏RSS量纲则判据报红(self) -> None:
        """故意弄坏：把 KB 当字节返回（少乘 1024）→ 判据必红；还原后归绿。"""
        import subprocess

        原始 = subprocess.run(["/bin/ps", "-o", "rss=", "-p", str(os.getpid())],
                            capture_output=True, text=True, timeout=5)
        千字节 = int(原始.stdout.strip())
        self.assertNotEqual(千字节, 千字节 * 1024, "证伪前提：坏读数确实不等于正确读数")

        def _坏读数(进程ID, *, ps命令=None):
            return 千字节, ""  # 故意：把 KB 当字节

        with mock.patch.object(平台适配, "进程内存RSS字节", _坏读数):
            with self.assertRaises(AssertionError) as 捕获:
                self._断言RSS量纲与ps一致()
        文本 = str(捕获.exception)
        self.assertIn("坏态", 文本)
        self.assertIn("量纲", 文本)
        self.assertIn("1024", 文本)
        # 还原 ⇒ 归绿：同一断言体不再抛（返回值是当次 ps 期望值，容差口径内即证量纲对）
        还原期望 = self._断言RSS量纲与ps一致()
        self.assertLess(abs(还原期望 - 千字节 * 1024), 8 * 1024 * 1024,
                        "还原后应与 ps 同量纲（容差 8 MiB 只吸收两次采样之间的正常浮动）")

    def test_反向_弄坏缓存根则判据报红(self) -> None:
        """故意弄坏：三平台返回同一个根 → 判据必红；还原后归绿。"""
        def _坏缓存根(应用名="系统工程平台", 环境=None):
            return Path("/一律同一个根/运行缓存")  # 故意：忽略平台与主目录

        with mock.patch.object(平台适配, "平台稳定缓存根", _坏缓存根):
            with self.assertRaises(AssertionError) as 捕获:
                self._断言三平台缓存根互不相同()
        文本 = str(捕获.exception)
        self.assertIn("坏态", 文本)
        self.assertIn("未按平台分叉", 文本)
        # 还原 ⇒ 归绿
        self.assertEqual(len(self._断言三平台缓存根互不相同()), 3)

    def test_反向_调用点判据抓得住就地分叉源码(self) -> None:
        """故意弄坏：把「就地分叉」的源码喂给**同一套静态判据** → 必须报出命中。

        这是 §「调用点已收口」那组「全部为空」的**反证前提**：若判据抓不住分叉形态，
        那些空断言就是假绿。样本是**真实调用点文件原文**改写成旧形态（含裸 `sys.platform`、
        `platform.system()`、取值后自行分叉三种），逐条比对命中集合。
        本用例只解析**字符串**，不碰仓库文件。
        """
        原文 = _读源码("运行核心/任务调度/任务进程.py")
        坏源码 = 原文.replace(
            "        self.进程上下文, self.需序列化执行器 = 平台适配.多进程启动上下文()",
            "        if 平台适配.是POSIX():\n"
            "            self.进程上下文, self.需序列化执行器 = None, 假\n"
            "        else:\n"
            "            self.进程上下文, self.需序列化执行器 = None, 真")
        self.assertNotEqual(坏源码, 原文, "证伪前提：替换必须真的改到源码")
        测试判据 = 测试调用点已收口("test_调用点无平台判定与取值后分叉")
        命中 = 测试判据._收集禁止形态("运行核心/任务调度/任务进程.py", 源码=坏源码)
        self.assertEqual(命中, ["取值后自行分叉（平台适配.是POSIX）"],
                         "静态判据必须抓得住「就地分叉」")
        # 还原（真源码）⇒ 同一判据归零
        self.assertEqual(
            测试判据._收集禁止形态("运行核心/任务调度/任务进程.py"), [])

    def test_反向_裸平台判定与三平台缓存根判据都能报红(self) -> None:
        """补两条**判据自身的反证**：裸读 `sys.platform` / `platform.system()` 必须被抓。"""
        测试判据 = 测试调用点已收口("test_调用点无平台判定与取值后分叉")
        样本 = "\n".join((
            "import platform, sys",
            "def 坏():",
            "    if sys.platform == 'win32':",
            "        return 'win'",
            "    return platform.system()",
        ))
        命中 = 测试判据._收集禁止形态("运行核心/任务调度/任务进程.py", 源码=样本)
        self.assertIn("裸读 sys.platform（sys.platform）", 命中)
        self.assertIn("platform.system()（platform.system）", 命中)


if __name__ == "__main__":
    unittest.main(verbosity=2)
