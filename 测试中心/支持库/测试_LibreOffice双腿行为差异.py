"""LibreOffice 双腿（适配层固定工作池 × 后端闸门+重试）行为差异定向测试。

本文件钉的不是「函数存在」，而是两侧**真实并发/限流/重试/清理行为**的差异（C 档硬要求）：

- 后端腿 `支持库/后端/文档转换支持库/LibreOffice转换`：进程内并发闸门 +
  有限次指数退避重试 + 暂存目录判定非空后发布（`copyfile` + `os.replace`）。
- 适配层腿 `支持库/适配层/LibreOffice提供者`：固定成员工作池 + 每成员串行队列 +
  排队超时，**无重试**。

两侧的 `soffice` 一律用假程序注入（不依赖本机是否安装 LibreOffice，也不出网）。
「差异登记」类断言（test_两侧实现可返回错误码的越界登记）在任一侧修好或新增越界时
都会打红，迫使同步更新登记 —— 这是刻意设计，不是脆弱断言。
"""

from __future__ import annotations

import json
import os
import re
import shutil
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

系统根 = Path(__file__).resolve().parents[2]
if str(系统根) not in sys.path:
    sys.path.insert(0, str(系统根))

后端实现路径 = 系统根 / "支持库" / "后端" / "文档转换支持库" / "LibreOffice转换" / "实现" / "文档转换.py"
适配实现路径 = 系统根 / "支持库" / "适配层" / "LibreOffice提供者" / "实现" / "文档转换.py"
后端包目录 = 后端实现路径.parents[1]
适配包目录 = 适配实现路径.parents[1]

假程序源码 = r'''#!/usr/bin/env python3
import json, os, sys, time
from pathlib import Path

参数 = sys.argv[1:]
输出目录 = Path(参数[参数.index("--outdir") + 1])
目标格式 = 参数[参数.index("--convert-to") + 1]
输入路径 = Path(参数[-1])
日志路径 = os.environ.get("FAKE_LO_LOG", "")
计数路径 = os.environ.get("FAKE_LO_COUNTER", "")


def 记录(事件):
    if not 日志路径:
        return
    句柄 = os.open(日志路径, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    try:
        os.write(句柄, (json.dumps({"事件": 事件, "pid": os.getpid()},
                                  ensure_ascii=False) + "\n").encode("utf-8"))
    finally:
        os.close(句柄)


本次 = 0
if 计数路径:
    句柄 = os.open(计数路径, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        原文 = os.read(句柄, 64).decode("utf-8") or "0"
        本次 = int(原文 or "0") + 1
        os.lseek(句柄, 0, 0)
        os.truncate(句柄, 0)
        os.write(句柄, str(本次).encode("utf-8"))
    finally:
        os.close(句柄)

记录("开始")
time.sleep(float(os.environ.get("FAKE_LO_DELAY", "0")))
失败到第几次 = int(os.environ.get("FAKE_LO_FAIL_UNTIL", "0"))
if 失败到第几次 and 本次 <= 失败到第几次:
    记录("失败退出")
    sys.exit(7)
退出码 = int(os.environ.get("FAKE_LO_EXIT_CODE", "0"))
if 退出码:
    记录("失败退出")
    sys.exit(退出码)
输出目录.mkdir(parents=True, exist_ok=True)
产物 = 输出目录 / f"{输入路径.stem}.{目标格式}"
if os.environ.get("FAKE_LO_EMPTY"):
    产物.write_bytes(b"")
else:
    产物.write_text(输入路径.read_text(encoding="utf-8"), encoding="utf-8")
记录("结束")
'''


class 双腿行为差异基类(unittest.TestCase):
    def setUp(self):
        self.临时根 = Path(tempfile.mkdtemp(prefix="测试_lo_双腿_"))
        self.假程序 = self.临时根 / "假soffice"
        self.假程序.write_text(假程序源码, encoding="utf-8")
        self.假程序.chmod(0o700)
        self.日志 = self.临时根 / "调用.jsonl"
        self.计数 = self.临时根 / "计数.txt"
        self.池列表 = []
        self._清后端提供者缓存()

    def tearDown(self):
        for 池 in self.池列表:
            try:
                池.关闭()
            except Exception:
                pass
        self._清后端提供者缓存()
        shutil.rmtree(self.临时根, ignore_errors=True)

    @staticmethod
    def _清后端提供者缓存():
        """清后端腿的 soffice 路径缓存（**状态复位，不是打桩**）。

        后端腿 `查找LibreOffice()` 的候选列表首位就是 `LIBREOFFICE_BIN`/`SOFFICE_BIN`
        环境变量，那是生产侧自己声明的注入口；但它命中 `_提供者缓存` 后**不再读环境变量**
        ⇒ 必须先清缓存，本次注入才生效、本次的临时路径也不会残留给后续用例。
        旧写法直接 `patch.object(后端, "_提供者缓存", …)` 把整段查找逻辑（含环境变量
        与 PATH 回退）跳过了，等于测一个不存在的实现（`测试伪装门禁` 规则 1 判红）。
        """
        from 支持库.后端.文档转换支持库.LibreOffice转换.实现 import 文档转换 as 后端
        后端._提供者缓存.clear()

    def _输入(self, 名称, 内容="双腿行为差异测试内容"):
        路径 = self.临时根 / 名称
        路径.write_text(内容, encoding="utf-8")
        return 路径

    def _读取日志(self):
        if not self.日志.exists():
            return []
        return [json.loads(行) for 行 in
                self.日志.read_text(encoding="utf-8").splitlines() if 行]

    def _开始次数(self):
        return len([项 for 项 in self._读取日志() if 项["事件"] == "开始"])

    def _等待日志数(self, 数量, 超时秒=3.0):
        截止 = time.monotonic() + 超时秒
        while time.monotonic() < 截止:
            if self._开始次数() >= 数量:
                return
            time.sleep(0.01)
        self.fail(f"日志未在时限内达到 {数量} 条开始事件")

    def _新建池(self, *, 池大小, 队列长度, 排队超时秒=2.0):
        from 支持库.适配层.LibreOffice提供者.实现.文档转换 import LibreOffice受管池
        池 = LibreOffice受管池(str(self.假程序), 池大小=池大小,
                          等待队列长度=队列长度, 排队超时秒=排队超时秒)
        self.池列表.append(池)
        return 池


class 测试重试语义差异(双腿行为差异基类):
    """差异点 1：后端腿有「有限次指数退避重试」，适配层腿一次失败即返回。"""

    def test_后端腿_前两次失败后第三次成功_共尝试3次(self):
        from 支持库.后端.文档转换支持库.LibreOffice转换.实现 import 文档转换 as 后端
        输入 = self._输入("重试.docx")
        输出目录 = self.临时根 / "后端输出"
        try:
            with mock.patch.dict(os.environ, {
                    "LIBREOFFICE_BIN": str(self.假程序),
                    "FAKE_LO_LOG": str(self.日志), "FAKE_LO_COUNTER": str(self.计数),
                    "FAKE_LO_FAIL_UNTIL": "2", "LIBREOFFICE_并发上限": "2",
                }):
                结果 = 后端.转换办公文件(str(输入), "txt", 超时秒=30,
                                     最大输出字节=1024, 输出目录=str(输出目录))
        finally:
            后端._回收档案根()
        self.assertTrue(结果.成功, 结果.错误说明)
        # 前两次 转换失败 被有限次退避重试吃掉，第三次成功 → 真实尝试 3 次
        self.assertEqual(self._开始次数(), 3)
        self.assertTrue((输出目录 / "重试.txt").is_file())

    def test_适配层腿_一次失败即返回转换失败_不重试(self):
        from 支持库.适配层.LibreOffice提供者.实现 import 文档转换 as 适配
        输入 = self._输入("不重试.docx")
        池 = self._新建池(池大小=1, 队列长度=2)
        with mock.patch.dict(os.environ, {
                "FAKE_LO_LOG": str(self.日志), "FAKE_LO_COUNTER": str(self.计数),
                "FAKE_LO_FAIL_UNTIL": "99"}):
            结果 = 池.执行(str(输入), "txt", 资源键="不重试资源",
                          超时秒=30, 最大输出字节=1024)
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "转换失败")
        self.assertEqual(self._开始次数(), 1, "适配层腿不得重试")


class 测试背压模型差异(双腿行为差异基类):
    """差异点 2：适配层是「固定池 + 队列满即限流」，后端是「闸门 + 按调用方超时排队」。"""

    def test_适配层腿_队列满返回结构化限流且真实并发不超过池大小(self):
        池 = self._新建池(池大小=1, 队列长度=1)
        输入列表 = [self._输入(f"背压{序号}.docx") for 序号 in range(3)]
        结果表 = []
        with mock.patch.dict(os.environ, {
                "FAKE_LO_LOG": str(self.日志), "FAKE_LO_DELAY": "0.6"}):
            线程一 = threading.Thread(target=lambda: 结果表.append(池.执行(
                str(输入列表[0]), "txt", 资源键="同一资源", 超时秒=5, 最大输出字节=1024)))
            线程一.start()
            self._等待日志数(1)
            线程二 = threading.Thread(target=lambda: 结果表.append(池.执行(
                str(输入列表[1]), "txt", 资源键="同一资源", 超时秒=5, 最大输出字节=1024)))
            线程二.start()
            time.sleep(0.05)
            第三个 = 池.执行(str(输入列表[2]), "txt", 资源键="同一资源",
                          超时秒=5, 最大输出字节=1024)
            线程一.join(); 线程二.join()
        self.assertFalse(第三个.成功)
        self.assertEqual(第三个.错误码, "限流")
        self.assertTrue(第三个.可重试)
        # 真实并发峰值 = 池大小（固定硬上限），不是「最多 4 个」
        当前 = 峰值 = 0
        for 项 in self._读取日志():
            当前 += 1 if 项["事件"] == "开始" else -1
            峰值 = max(峰值, 当前)
        self.assertEqual(峰值, 1)
        self.assertTrue(all(项.成功 for 项 in 结果表))

    def test_后端腿_闸门满时排队而不是限流且并发不超过并发上限(self):
        from 支持库.后端.文档转换支持库.LibreOffice转换.实现 import 文档转换 as 后端
        输入列表 = [self._输入(f"闸门{序号}.docx") for 序号 in range(6)]
        结果表 = []
        try:
            with mock.patch.dict(os.environ, {
                    "LIBREOFFICE_BIN": str(self.假程序),
                    "FAKE_LO_LOG": str(self.日志), "FAKE_LO_DELAY": "0.12",
                    "LIBREOFFICE_并发上限": "1"}):
                线程列表 = [threading.Thread(target=lambda 路径=路径: 结果表.append(
                    后端.转换办公文件(str(路径), "txt", 超时秒=30, 最大输出字节=1024)))
                    for 路径 in 输入列表]
                for 线程 in 线程列表:
                    线程.start()
                for 线程 in 线程列表:
                    线程.join()
        finally:
            后端._回收档案根()
        self.assertEqual(len(结果表), 6)
        self.assertTrue(all(项.成功 for 项 in 结果表), [项.错误码 for 项 in 结果表])
        # 后端腿没有「等待队列已满」这一类；闸门满时按调用方 超时秒 排队等待
        self.assertNotIn("限流", {项.错误码 for 项 in 结果表})
        当前 = 峰值 = 0
        for 项 in self._读取日志():
            当前 += 1 if 项["事件"] == "开始" else -1
            峰值 = max(峰值, 当前)
        self.assertEqual(峰值, 1)


class 测试失败路径与清理(双腿行为差异基类):
    """差异点 3：失败路径不得静默 —— 调用方既有产物不得被删或被半截覆盖；临时目录清零。"""

    def test_后端腿_三次全失败也不动调用方既有产物(self):
        from 支持库.后端.文档转换支持库.LibreOffice转换.实现 import 文档转换 as 后端
        输入 = self._输入("既有.docx")
        输出目录 = self.临时根 / "既有输出"
        输出目录.mkdir()
        既有 = 输出目录 / "既有.txt"
        既有.write_text("调用方旧内容", encoding="utf-8")
        try:
            with mock.patch.dict(os.environ, {
                    "LIBREOFFICE_BIN": str(self.假程序),
                    "FAKE_LO_LOG": str(self.日志), "FAKE_LO_EXIT_CODE": "7",
                    "LIBREOFFICE_并发上限": "1"}):
                结果 = 后端.转换办公文件(str(输入), "txt", 超时秒=30,
                                     最大输出字节=1024, 输出目录=str(输出目录))
        finally:
            后端._回收档案根()
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "转换失败")
        self.assertEqual(既有.read_text(encoding="utf-8"), "调用方旧内容")
        self.assertEqual(sorted(p.name for p in 输出目录.iterdir()), ["既有.txt"])
        # 环境变量残留：不得把内部档案/暂存目录留给调用方
        self.assertEqual(list(self.临时根.glob("lo_profile_*")), [])
        self.assertEqual(list(self.临时根.glob("lo_stage_*")), [])

    def test_适配层腿_作业失败后清空作业目录且关闭后删池根(self):
        from 支持库.适配层.LibreOffice提供者.实现 import 文档转换 as 适配
        输入 = self._输入("异常.docx")
        池 = self._新建池(池大小=1, 队列长度=1)
        with mock.patch.dict(os.environ, {
                "FAKE_LO_LOG": str(self.日志), "FAKE_LO_EXIT_CODE": "7"}):
            结果 = 池.执行(str(输入), "txt", 资源键="异常资源",
                          超时秒=30, 最大输出字节=1024)
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "转换失败")
        self.assertEqual(list((池._根目录 / "作业").iterdir()), [])
        根目录 = 池._根目录
        池.关闭()
        self.assertFalse(根目录.exists())


class 测试零字节产物判定差异(双腿行为差异基类):
    """差异点 5（决定性）：soffice 退出码 0 但产出空文件时两侧判定相反。

    这是平台自己的历史踩坑（提交 f7c34942）：LibreOffice 桌面端按 UserInstallation
    单实例，共用默认档案时后到的 `--convert-to` **静默 no-op**（退出码 0 但零产出）。
    后端腿把「文件存在且非空」作为成功判据；适配层腿只判 `.is_file()`。
    """

    def test_后端腿_零字节产物判为转换失败(self):
        from 支持库.后端.文档转换支持库.LibreOffice转换.实现 import 文档转换 as 后端
        输入 = self._输入("空产物.docx")
        try:
            with mock.patch.dict(os.environ, {
                    "LIBREOFFICE_BIN": str(self.假程序),
                    "FAKE_LO_LOG": str(self.日志), "FAKE_LO_EMPTY": "1",
                    "LIBREOFFICE_并发上限": "1"}):
                结果 = 后端.转换办公文件(str(输入), "txt", 超时秒=30, 最大输出字节=1024)
        finally:
            后端._回收档案根()
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "转换失败")
        self.assertIn("空", 结果.错误说明)

    def test_适配层腿_零字节产物当前被判为成功_差异登记(self):
        from 支持库.适配层.LibreOffice提供者.实现 import 文档转换 as 适配
        输入 = self._输入("空产物.docx")
        池 = self._新建池(池大小=1, 队列长度=1)
        with mock.patch.dict(os.environ, {
                "FAKE_LO_LOG": str(self.日志), "FAKE_LO_EMPTY": "1"}):
            结果 = 池.执行(str(输入), "txt", 资源键="空产物资源",
                          超时秒=30, 最大输出字节=1024)
        # 现状登记：适配层腿把「退出码 0 + 零字节文件」判为成功（字节数=0）。
        # 这是本档认定的**行为缺口**（后端腿更严）；一旦适配层腿补上非空判定，
        # 本断言会打红，属刻意设计 —— 迫使同步更新差异登记与迁移结论。
        self.assertTrue(结果.成功, 结果.错误说明)
        self.assertEqual(结果.值["字节数"], 0)


class 测试错误码越界登记(unittest.TestCase):
    """差异点 4（登记式断言）：实现可返回的错误码必须 ⊆ 自身能力定义声明的集合。

    这里是**差异登记**：断言两侧越界集合的已知值。任一侧修好（越界减少）或新增越界
    都会打红，迫使同步更新本登记 —— 这正是本档要「钉住」的事实。
    """

    @staticmethod
    def _实现可返回错误码(模块路径: Path) -> set:
        原文 = 模块路径.read_text(encoding="utf-8")
        return set(re.findall(r'_失败\(\s*"([^"]+)"', 原文)) | \
            set(re.findall(r'\.失败\(\s*"([^"]+)"', 原文))

    @staticmethod
    def _声明错误码(包目录: Path) -> set:
        定义 = json.loads((包目录 / "能力定义.json").read_text(encoding="utf-8"))
        集合 = set()
        for 能力 in 定义["能力列表"]:
            集合 |= set(能力.get("错误码") or [])
        return 集合

    def test_后端腿实现可返回错误码的越界登记(self):
        越界 = self._实现可返回错误码(后端实现路径) - self._声明错误码(后端包目录)
        # 越界集已清零（2026-09-22 实测）：原登记值 {"外部提供者不可用"} 已由
        # 能力定义.json 补齐声明消解。若将来实现新增未声明错误码，本断言立即打红。
        self.assertEqual(越界, set())

    def test_适配层腿实现可返回错误码的越界登记(self):
        越界 = self._实现可返回错误码(适配实现路径) - self._声明错误码(适配包目录)
        # 越界集已清零（2026-09-22 实测）：原登记的三条（"外部提供者不可用" / "限流" /
        # "提供者配置错误"）均已由能力定义.json 补齐声明消解 —— 这正是本档要钉住的事实：
        # 生产侧补声明后此处必须同步收敛，否则登记会永久停留在旧快照。
        self.assertEqual(越界, set())

    def test_两侧声明错误码集合一致(self):
        self.assertEqual(self._声明错误码(后端包目录), self._声明错误码(适配包目录))


if __name__ == "__main__":
    unittest.main()
