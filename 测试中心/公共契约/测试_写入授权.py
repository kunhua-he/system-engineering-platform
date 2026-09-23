"""写入授权判据的回归锁（华哥 2026-09-23「只读子代理」缺口）。

## 本文件锁什么

写入腿此前只判「是不是经 MCP 来的」，**不判路径有没有被授权** ⇒ 只要带上网关凭证，
任何路径都能写，「只读子代理」在平台上根本不存在（现场取证：四路只读子代理全部越界落盘）。
本文件锁的就是那道新判据：`公共契约/运行时/写入授权.校验写入授权`。

## 一条判据、三拍反向验证（三拍缺一不可）

    ① 无租约的写 ⇒ 必须报红（错误码 `越界`，且盘上内容不变）；
    ② 补上活跃写租约 ⇒ **同一动作**必须转绿；
    ③ 还原（释放租约）⇒ 必须复红。

为什么必须三拍：只测①，把「受管」判定写成恒假、或把事实源整个不接，本文件照样全绿；
只测②，判据把**非受管路径**也拒掉（假红）也看不出来。故另配两条反向用例：
非受管必须放行（防假红）、事实源未注册必须拒（防「证不出就当可以」）。

## 夹具策略

夹具在 `工程缓存/测试临时/` 下造一个**假仓库**（带 `.git/`），于是：

  · `仓库只读锁.推断仓库根` 命中的是假仓库（最近的 `.git`），相对路径算得出来；
  · 写的是**假仓库里的文件**，真仓库一个字节都不动；
  · 租约走**真租约表**（`申请文件租约` 的默认存储目录）—— 那正是生产走的那条腿，
    桩掉它就测不出「事实源真的接上了」；租约由 `addCleanup` 释放。
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

系统根 = Path(__file__).resolve().parents[2]
if str(系统根) not in sys.path:
    sys.path.insert(0, str(系统根))

import 公共契约.运行时.写入授权 as 写入授权模块
from 公共契约.基础类型.逻辑类型 import 真, 假
from 公共契约.运行时 import 仓库只读锁 as 锁
from 公共契约.运行时.写入授权 import 受管相对路径, 校验写入授权
from 支持库.后端.文件系统支持库.文件操作 import 写入文件
from 平台控制面.能力目录 import 申请文件租约, 释放文件租约

受管仓库根 = 系统根
受管临时根 = 受管仓库根 / "工程缓存" / "测试临时"
受管临时根.mkdir(parents=True, exist_ok=True)


class 写入授权夹具(unittest.TestCase):
    #: 夹具凭证：写入腿的第一判据是 `MCP身份准入`（只认网关凭证 / 修 MCP 白名单），
    #: 本文件要测的是**第二判据**，故夹具假装自己是网关（同 `测试_仓库只读锁` 的夹具口径）。
    夹具凭证 = "写入授权-回归锁"

    def setUp(self) -> None:
        self._临时 = tempfile.mkdtemp(prefix="写入授权_", dir=受管临时根)
        self.假仓库 = Path(self._临时) / "假仓库"
        (self.假仓库 / ".git").mkdir(parents=True, exist_ok=True)
        self.目标 = self.假仓库 / "目标.py"
        self.目标.write_text("原始内容\n", encoding="utf-8")
        self._设凭证(self.夹具凭证)
        self.addCleanup(self._清理)

    def _清理(self) -> None:
        shutil.rmtree(self._临时, ignore_errors=True)

    def _设凭证(self, 值: str | None) -> None:
        旧 = os.environ.get("系统库网关凭证")
        if 值 is None:
            os.environ.pop("系统库网关凭证", None)
        else:
            os.environ["系统库网关凭证"] = 值

        def _还原() -> None:
            if 旧 is None:
                os.environ.pop("系统库网关凭证", None)
            else:
                os.environ["系统库网关凭证"] = 旧

        self.addCleanup(_还原)


class Test写入授权反向三拍(写入授权夹具):
    def test_无租约报红_补租约转绿_还原复红(self) -> None:
        """三拍走**同一动作**（向同一路径写），只有租约状态在变。"""
        相对 = "目标.py"

        # ① 无租约的写 ⇒ 必须报红
        结果一 = 写入文件(str(self.目标), "第一版\n")
        self.assertFalse(结果一.成功, "无活跃写租约竟然写成功了（判据没接上）")
        self.assertEqual(结果一.错误.错误码, "越界")
        说明一 = str(结果一.错误.错误说明)
        self.assertIn("开工编排.开工即占", 说明一, "失败说明必须给可照抄的合规调用")
        self.assertIn(相对, 说明一, "失败说明必须指出是哪一条路径")
        self.assertEqual(self.目标.read_text(encoding="utf-8"), "原始内容\n",
                         "被拒的写竟然改了盘上内容")

        # ② 补租约 ⇒ 必须转绿
        认领 = 申请文件租约(修改路径=[相对], 所有者="回归锁", 任务="反向三拍",
                            项目根=str(self.假仓库))
        self.assertTrue(认领.成功, f"补租约失败：{认领.错误码} {认领.错误说明}")
        租约id清单 = list(认领.值.get("租约id清单") or [])
        self.assertTrue(租约id清单, "认领成功却没回租约id清单")
        self.addCleanup(
            lambda: 释放文件租约(租约id清单=租约id清单, 原因="回归锁收工",
                                 项目根=str(self.假仓库)))
        结果二 = 写入文件(str(self.目标), "第二版\n")
        self.assertTrue(结果二.成功, f"补了活跃租约仍被拒：{结果二.错误.错误说明}")
        self.assertEqual(self.目标.read_text(encoding="utf-8"), "第二版\n")

        # ③ 还原（释放租约）⇒ 必须复红
        释放 = 释放文件租约(租约id清单=租约id清单, 原因="反向三拍还原",
                            项目根=str(self.假仓库))
        self.assertTrue(释放.成功, f"释放失败：{释放.错误码} {释放.错误说明}")
        结果三 = 写入文件(str(self.目标), "第三版\n")
        self.assertFalse(结果三.成功, "释放租约后竟然还能写（判据只在补租约那一步生效）")
        self.assertEqual(结果三.错误.错误码, "越界")
        self.assertEqual(self.目标.read_text(encoding="utf-8"), "第二版\n",
                         "被拒的写竟然改了盘上内容")


class Test非受管放行(写入授权夹具):
    """反向用例一：**防假红** —— 判据不能把「本来就没有租约可言」的路径也拦下。"""

    def test_豁免区与仓库外必须照旧能写(self) -> None:
        仓库外 = Path(tempfile.mkdtemp(prefix="写入授权_仓外_"))
        self.addCleanup(shutil.rmtree, 仓库外, ignore_errors=True)
        受检表 = (
            (受管临时根 / "豁免内.txt", "豁免前缀（工程缓存/）"),
            (仓库外 / "仓外.txt", "仓库外（无受管面）"),
        )
        for 路径, 名义 in 受检表:
            受管, _相对, 理由 = 受管相对路径(str(路径))
            self.assertFalse(受管, f"{名义} 不该被判受管（理由：{理由}）")
            结果 = 写入文件(str(路径), "非受管内容\n")
            self.assertTrue(结果.成功, f"{名义} 被误拒（假红）：{结果.错误.错误说明}")
            self.assertEqual(路径.read_text(encoding="utf-8"), "非受管内容\n")

    def test_平台自管生成物不受判据约束(self) -> None:
        """装配/证据机器的固定名产物（流水、声明、锁定）不应把平台自己判红。"""
        for 相对 in 写入授权模块.平台生成物:
            受管, _相对, 理由 = 受管相对路径(str(受管仓库根 / 相对))
            self.assertFalse(受管, f"{相对} 不该被判受管（理由：{理由}）")


class Test判据的边界(写入授权夹具):
    """反向用例二：**防「证不出就当可以」** —— 事实源不可用时必须 fail-closed。"""

    def test_事实源未注册即拒绝(self) -> None:
        原读取器 = 写入授权模块.写租约事实源
        self.addCleanup(写入授权模块.设写租约事实源, 原读取器)
        写入授权模块.设写租约事实源(None)
        通过, 说明 = 校验写入授权(str(self.目标))
        self.assertFalse(通过, "事实源没注册竟然放行了（fail-open）")
        self.assertIn("没注册写租约事实源", 说明)

    def test_内核锁窗口不是后门(self) -> None:
        """`临时解锁` 是写腿唯一的开窗动作 ⇒ 无租约时它必须抛，而不是静默开窗。"""
        with self.assertRaises(PermissionError) as 上下文:
            with 锁.临时解锁(self.目标):
                pass
        self.assertIn("写入未授权", str(上下文.exception))
        # 非受管路径照旧开窗（否则平台自己的运行期写盘会被一起锁死）
        with 锁.临时解锁(受管临时根 / "窗口.txt"):
            pass
