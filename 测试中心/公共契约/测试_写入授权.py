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
import json
import subprocess
import time
import unittest
from pathlib import Path

系统根 = Path(__file__).resolve().parents[2]
if str(系统根) not in sys.path:
    sys.path.insert(0, str(系统根))

import 公共契约.运行时.写入授权 as 写入授权模块
from 公共契约.基础类型.逻辑类型 import 真, 假
from 公共契约.运行时 import 仓库只读锁 as 锁
from 公共契约.运行时.平台适配 import 清只读后删除树
from 公共契约.运行时.写入授权 import 受管相对路径, 校验写入授权
from 支持库.后端.文件系统支持库.文件操作 import 写入文件, 登记临时资源, 清理全部临时资源
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
        self.addCleanup(清只读后删除树, self._临时, 忽略失败=真)

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

        # ① 无租约的写 ⇒ 必须报红（★ 2026-09-25：开工ID 已是变更类能力的必填入参，且判据比的是
        #    「该路径活跃租约的所有者 == 开工ID」；三拍全程用同一个 开工ID，只有租约状态在变 ——
        #    否则测的就成了「凭证对不对」而不是「租约在不在」。）
        结果一 = 写入文件(str(self.目标), "第一版\n", 开工ID="回归锁")
        self.assertFalse(结果一.成功, "无活跃写租约竟然写成功了（判据没接上）")
        self.assertEqual(结果一.错误.错误码, "越界")
        说明一 = str(结果一.错误.消息)
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
        结果二 = 写入文件(str(self.目标), "第二版\n", 开工ID="回归锁")
        self.assertTrue(结果二.成功, f"补了活跃租约仍被拒：{结果二.错误说明}")
        self.assertEqual(self.目标.read_text(encoding="utf-8"), "第二版\n")

        # ③ 还原（释放租约）⇒ 必须复红
        释放 = 释放文件租约(租约id清单=租约id清单, 原因="反向三拍还原",
                            项目根=str(self.假仓库))
        self.assertTrue(释放.成功, f"释放失败：{释放.错误码} {释放.错误说明}")
        结果三 = 写入文件(str(self.目标), "第三版\n", 开工ID="回归锁")
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
            self.assertTrue(结果.成功, f"{名义} 被误拒（假红）：{getattr(结果.错误, '消息', '')}")
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
        # ★ 2026-09-25：受管路径 + 开工ID 为空会**先**被第 3 出口「没有开工ID 凭证」拦下，
        #   走不到事实源那一支。本用例要测的是「事实源未注册 ⇒ fail-closed」，故必须传一个
        #   非空 开工ID，才落到第 4 出口的「拿不到写租约事实源」。
        通过, 说明 = 校验写入授权(str(self.目标), "回归锁")
        self.assertFalse(通过, "事实源没注册竟然放行了（fail-open）")
        self.assertIn("拿不到写租约事实源", 说明)

    def test_内核锁窗口不是后门(self) -> None:
        """`临时解锁` 是写腿唯一的开窗动作 ⇒ 无租约时它必须抛，而不是静默开窗。"""
        with self.assertRaises(PermissionError) as 上下文:
            with 锁.临时解锁(self.目标):
                pass
        self.assertIn("写入未授权", str(上下文.exception))
        # 非受管路径照旧开窗（否则平台自己的运行期写盘会被一起锁死）
        with 锁.临时解锁(受管临时根 / "窗口.txt"):
            pass


class Test凭证须与租约所有者一致(写入授权夹具):
    """新判据（2026-09-25 底座权限面收口）：受管路径的活跃租约**所有者**必须 == 调用方传的 开工ID。

    缺陷本体：改前判据只问「这条路径**有没有人**占」，而活跃集是**全平台一本、跨会话共享**的
    ⇒ 甲认领了 X，乙（任一并发会话、任一持网关凭证的进程）写 X 照样通过 —— 那个判据是
    **路径级**的，「只读子代理」在并发面上仍然存在。三拍（缺一拍即假绿）：

      ① 传对所有者 ⇒ 通过；
      ② 传错所有者 ⇒ 拒，且说明必须点出「属**别的凭证**」（不许只回笼统的「越界」）；
      ③ 不传 开工ID ⇒ 拒（退回路径级旧腿＝保留「不传凭证也能写」，正是本次要收的洞）。
    """

    def setUp(self) -> None:
        super().setUp()
        认领 = 申请文件租约(修改路径=["目标.py"], 所有者="甲凭证", 任务="凭证一致三拍",
                            项目根=str(self.假仓库))
        self.assertTrue(认领.成功, f"前置：认领失败 {认领.错误码} {认领.错误说明}")
        租约id清单 = list(认领.值.get("租约id清单") or [])
        self.assertTrue(租约id清单, "前置：认领成功却没回租约id清单")
        self.addCleanup(lambda: 释放文件租约(租约id清单=租约id清单, 原因="凭证一致三拍收工",
                                             项目根=str(self.假仓库)))

    def test_传对所有者即通过(self) -> None:
        结果 = 写入文件(str(self.目标), "甲写的\n", 开工ID="甲凭证")
        self.assertTrue(结果.成功, f"传对所有者竟被拒：{getattr(结果.错误, '消息', '')}")
        self.assertEqual(self.目标.read_text(encoding="utf-8"), "甲写的\n")

    def test_传错所有者即拒绝且点明别的凭证(self) -> None:
        结果 = 写入文件(str(self.目标), "乙写的\n", 开工ID="乙凭证")
        self.assertFalse(结果.成功, "拿别的凭证竟然写成了（判据仍是路径级）")
        self.assertEqual(结果.错误.错误码, "越界")
        self.assertIn("别的凭证", str(结果.错误.消息),
                      "失败说明必须点出「属别的凭证」，否则调用方查不出是撞车还是没开工")
        self.assertEqual(self.目标.read_text(encoding="utf-8"), "原始内容\n",
                         "被拒的写竟然改了盘上内容")

    def test_不传开工ID即拒绝(self) -> None:
        结果 = 写入文件(str(self.目标), "无凭证\n")
        self.assertFalse(结果.成功, "不传 开工ID 竟然写成了（路径级旧腿没撤掉）")
        self.assertEqual(结果.错误.错误码, "越界")
        self.assertIn("没有开工ID", str(结果.错误.消息),
                      "失败说明必须点出「没传 开工ID」这一成因")


class Test平台编译机写者不受判据约束(写入授权夹具):
    """第三出口（2026-09-24 补）：**写者是平台自己的编译机** ⇒ 非受管。

    为什么必须补（主会话实测）：`受管相对路径` 原先只按**路径**豁免，而平台派生件
    （各包 `完整性摘要.json`、`支持库/适配层/依赖登记.json`、`开发文档/规范/*.md` 的
    三行元信息头）既不在豁免前缀里、也不在 `平台生成物` 那 5 条固定名里，而它们的
    **唯一写者编译口又不持任何租约** ⇒ 全仓 `静态编译` 结构性多出 3 条阻断红
    （`摘要闭合` / `依赖分两段` / `规范元信息头` 的生成步骤，退出码 1）。

    判据两层（强度在第二层）：环境标记（快筛，**可伪造**）+ **进程祖先链**（伪造不了）。
    故本类的反向用例里，`test_锁pid不在祖先链即照旧判受管` 才是真正的强度判据 ——
    调用方即使拿到锁里的 pid、也把环境标记设成它，仍然过不了，因为它**无法让自己的
    父进程变成那个编译口**。
    """

    def setUp(self) -> None:
        super().setUp()
        self._原锁相对路径 = 写入授权模块.编译机锁相对路径
        # 锁相对路径是**绝对路径**（`Path(仓库根) / 绝对路径` 取绝对路径那一支），
        # 故夹具不必动真仓库的 `工程缓存/编译口单写者锁.json`。
        #
        # ★ 2026-09-24（批E）：`self.锁` 必须**从可解析的受管临时根派生**，不许写成
        #   `Path(写入授权模块.编译机锁相对路径)` —— 那样左端基是「模块属性的值」，
        #   `测试写入边界门禁` 判据一静态解析不出 ⇒ 落进「未解析（fail-closed）」档、
        #   计入违规（实测：该门禁现场处数 357 > 存量基线 356 ⇒ 判红）。
        #   夹具写的就是临时目录，让**静态读得出**它落在受管临时根下，是判据一要求的形状。
        self.锁根 = Path(self._临时)
        self.锁 = self.锁根 / "编译机锁.json"
        写入授权模块.编译机锁相对路径 = str(self.锁)
        self.addCleanup(self._还原)

    def _还原(self) -> None:
        写入授权模块.编译机锁相对路径 = self._原锁相对路径
        os.environ.pop(写入授权模块.编译机PID环境变量名, None)

    def _写锁(self, pid: int) -> None:
        self.锁.write_text(json.dumps({"pid": pid}), encoding="utf-8")

    def test_正拍_标记与锁pid一致且在自己祖先链里才放行(self) -> None:
        self._写锁(os.getpid())
        os.environ[写入授权模块.编译机PID环境变量名] = str(os.getpid())
        受管, _相对, 理由 = 受管相对路径(str(self.目标))
        self.assertFalse(受管, f"编译机写者该被判非受管（理由：{理由}）")
        self.assertIn("编译机", 理由)
        结果 = 写入文件(str(self.目标), "派生内容\n")
        self.assertTrue(结果.成功, f"编译机写者被误拒：{getattr(结果.错误, '消息', '')}")

    def test_反拍_标记缺失即照旧判受管(self) -> None:
        self._写锁(os.getpid())
        os.environ.pop(写入授权模块.编译机PID环境变量名, None)
        受管, _相对, _理由 = 受管相对路径(str(self.目标))
        self.assertTrue(受管, "没有环境标记竟然放行（等于给了一条可伪造的旁路）")

    def test_反拍_标记与锁里pid不一致即照旧判受管(self) -> None:
        self._写锁(os.getpid() + 1)
        os.environ[写入授权模块.编译机PID环境变量名] = str(os.getpid())
        受管, _相对, _理由 = 受管相对路径(str(self.目标))
        self.assertTrue(受管, "标记与锁里 pid 不一致竟然放行")

    def test_反拍_锁pid不在祖先链即照旧判受管(self) -> None:
        """★ 强度判据：伪造环境标记够不着 —— 祖先关系不是调用方能选的东西。"""
        他 = subprocess.Popen(["sleep", "20"])      # 我的**后代**，不在祖先链里
        try:
            time.sleep(0.3)
            self._写锁(他.pid)
            os.environ[写入授权模块.编译机PID环境变量名] = str(他.pid)
            受管, _相对, _理由 = 受管相对路径(str(self.目标))
            self.assertTrue(受管, "锁 pid 不在祖先链里竟然放行（判据被伪造了）")
        finally:
            # 显式 kill + wait：只 kill 不 wait 会让子进程在解释器退出时仍被判「still running」，
            # 报 `ResourceWarning` —— 噪声会被别的门禁当成异常读。
            他.kill()
            他.wait(timeout=10)

    def test_反拍_锁文件缺失即照旧判受管(self) -> None:
        os.environ[写入授权模块.编译机PID环境变量名] = str(os.getpid())
        受管, _相对, _理由 = 受管相对路径(str(self.目标))
        self.assertTrue(受管, "锁文件不在竟然放行（fail-open）")


class Test自管临时资源出口(写入授权夹具):
    """第四出口（2026-09-24 批R R-31 补）：**平台自管的临时资源** ⇒ 非受管。

    缺陷本体（现场实测）：`文件系统支持库.文件操作.清理全部临时资源` 的解锁窗口写的是
    `临时解锁(*[Path(项) for 项 in 待清理])`，而 `待清理` 是**平台自己登记的**临时资源
    —— 与 `压缩文件` 那条腿的派生件同族（R-24 B 类）。判据本体在本文件（受管路径必须被
    一条活跃写租约覆盖），登记表却住 `支持库/后端/文件系统支持库/文件操作/实现`
    ⇒ 判据侧看不见它，那些名字调用方**永远认领不到租约** ⇒ 窗口结构性 fail-closed、
    `PermissionError` 从能力里逃出去（不是 `结果.失败`）。

    修法＝**注入口**（不新增第二套判据）：判据仍只住本文件，事实由 `设自管临时资源读取器`
    从支持库侧注入（形状与 `设写租约事实源` 逐字同形：`None` 即注销、未注册即空集）。
    本类钉三拍，缺一拍就证不出「豁免真的来自注入口」：

      ① 登记腿自带授权闸：**无租约**时登记一条受管路径必须被拒
         —— 否则注入口就是越权口子：先登记任意受管路径、再让清理腿删掉；
      ② 正拍：持租约登记 ⇒ **释放租约之后**清理腿仍必须真删掉它（修好的就是这一拍）；
      ③ 反拍：摘掉读取器（`设自管临时资源读取器(None)`）⇒ 同一条腿必须复红。

    为什么③能同时钉住②：两拍的设置逐字相同（都是「登记完就释放租约」），差别只在
    注入口在不在。若②其实是「还攥着租约」在放行，③就不可能复红 ⇒ 两拍互为反证。
    """

    def setUp(self) -> None:
        super().setUp()
        self._原读取器 = 写入授权模块.自管临时资源读取器
        self.addCleanup(写入授权模块.设自管临时资源读取器, self._原读取器)
        # 兜底：用例中途抛错时登记表里可能留下条目，恢复读取器后按前缀再清一次（幂等）。
        self.addCleanup(self._兜底清登记表)

    def _兜底清登记表(self) -> None:
        写入授权模块.设自管临时资源读取器(self._原读取器)
        清理全部临时资源(路径前缀=str(self.目标))

    def _认领(self) -> list:
        认领 = 申请文件租约(修改路径=["目标.py"], 所有者="回归锁-自管临时资源",
                            任务="第四出口三拍", 项目根=str(self.假仓库))
        self.assertTrue(认领.成功, f"认领失败：{认领.错误码} {认领.错误说明}")
        租约id清单 = list(认领.值.get("租约id清单") or [])
        self.assertTrue(租约id清单, "认领成功却没回租约id清单")
        return 租约id清单

    def _释放(self, 租约id清单: list) -> None:
        释放 = 释放文件租约(租约id清单=租约id清单, 原因="第四出口三拍收工",
                            项目根=str(self.假仓库))
        self.assertTrue(释放.成功, f"释放失败：{释放.错误码} {释放.错误说明}")

    def test_无租约时登记受管路径必须被拒(self) -> None:
        """① 登记腿的闸：没有活跃写租约 ⇒ 不许把受管路径登记进豁免事实源。"""
        登记 = 登记临时资源(str(self.目标), 开工ID="回归锁-自管临时资源")
        self.assertFalse(登记.成功, "无租约竟然能登记受管路径（注入口成了越权口子）")
        self.assertEqual(登记.错误.错误码, "越界")
        self.assertIn("开工编排.开工即占", str(登记.错误.消息),
                      "失败说明必须给可照抄的合规调用")

    def test_释放租约后清理腿仍能删掉自管临时资源(self) -> None:
        """② 正拍：豁免来自**注入口**，不是「还攥着租约」。"""
        租约id清单 = self._认领()
        登记 = 登记临时资源(str(self.目标), 开工ID="回归锁-自管临时资源")
        self.assertTrue(登记.成功, f"持租约登记被拒：{登记.错误码} {登记.错误说明}")
        self._释放(租约id清单)
        清理 = 清理全部临时资源(路径前缀=str(self.目标))
        self.assertTrue(清理.成功,
                        f"平台自管临时资源被清理腿拒了：{清理.错误码} {清理.错误说明}")
        self.assertFalse(self.目标.exists(), "清理腿报成功却没删掉文件")

    def test_摘掉注入口后同一条腿复红(self) -> None:
        """③ 反拍：注入口摘掉 ⇒ 清理腿必须回到 fail-closed（`PermissionError`）。"""
        租约id清单 = self._认领()
        self.目标.write_text("第二版\n", encoding="utf-8")
        登记 = 登记临时资源(str(self.目标), 开工ID="回归锁-自管临时资源")
        self.assertTrue(登记.成功, f"持租约登记被拒：{登记.错误码} {登记.错误说明}")
        self._释放(租约id清单)
        写入授权模块.设自管临时资源读取器(None)
        with self.assertRaises(PermissionError) as 上下文:
            with 锁.临时解锁(self.目标):
                pass
        self.assertIn("写入未授权", str(上下文.exception))
