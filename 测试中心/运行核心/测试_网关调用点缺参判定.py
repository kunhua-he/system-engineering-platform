"""调用点缺参判定：潜伏 `NameError` 的回归锁（开工ID 开工-20260923-045339-dbbb）。

## 缺陷（改前实测，本文件是它的回归锁）

`运行核心/统一网关/协议/调用点缺参判定.py::_是调用点缺参错误` 用了 `Path` 与
`_本文件路径`，但该模块**既没有 `from pathlib import Path`、也没有定义 `_本文件路径`**
—— 2026-09-19 拆分（`3630368e`「按职责拆到最细：网关核心 1338→99 行」）把函数搬出
`网关核心.py` 时，只搬了函数体，把它依赖的两行留在了旧文件（旧 `网关核心.py:30-31`：
`# 本文件路径：用于判「抛错帧是不是本网关这一层」（P1-6 结构判据）。` /
`_本文件路径 = Path(__file__).resolve()`）。

`运行核心/统一网关/核心处理/网关执行面.py:166` 在 `后端核心.调用` 的 `except TypeError`
兜底分支里调用它 ⇒ **该分支一旦被走到，必然 `NameError: name 'Path' is not defined`**。

为什么一直没报过错：进程内腿已把异常收口成统一结果
（`运行核心/能力调用/唯一能力调用.py` 的 `唯一能力调用服务.调用能力` 用 `except Exception`
兜住一切），`后端核心.调用` 不再向上抛 `TypeError`，网关这条兜底基本走不到。
**但走不到不等于不存在**：一旦走到，它把一次可辨识的「参数不合法」变成 `NameError`，
再由 `处理()` 的 `except Exception` 谎报成 500「内部错误」——正是「失败必须明确」要防的事。

## 本文件锁什么

1. 模块里被引用的全局符号真的在（改前 `Path` / `_本文件路径` 缺一即红）；
2. 深层抛错帧（实现在后端链路更下层）→ `参数不合法`（不是 `NameError`、不是「内部错误」）；
3. 抛错帧归本网关这一层 → **不降级成 400**（原样上抛）；
4. 没有 traceback 的 `TypeError` → 不猜（判「不是调用点缺参」）；
5. 端到端：经 `网关核心.处理` 的对外表现是 `参数不合法`。

判据不靠放宽断言：第 1 条喂「改前源码」必须报出缺符号（判据自己先自证不空转），
第 2/5 条改前是 `NameError`（实测红）。
"""

from __future__ import annotations

import builtins
import importlib
import sys
import unittest
from pathlib import Path

系统根 = Path(__file__).resolve().parents[2]
if str(系统根) not in sys.path:
    sys.path.insert(0, str(系统根))

from 运行核心.统一网关.网关核心 import 网关核心
from 运行核心.统一网关.协议.网关信封 import 网关请求, 网关响应
from 运行核心.统一网关.协议.参数别名表 import _应用参数别名
from 公共契约.基础类型.逻辑类型 import 假

模块名 = "运行核心.统一网关.协议.调用点缺参判定"
#: 按**模块对象**取符号，不 `from … import 名`：源码缺符号时要让用例在**调用/断言**上红，
#: 而不是在收集期 `ImportError` 上红 —— 前者才证明判据真看得见缺陷。
判定模块 = importlib.import_module(模块名)
能力id = "媒体处理支持库.FFmpeg媒体.探测媒体"

#: 改前源码（`Path` 未导入、`_本文件路径` 未定义）—— 只用于自证判据不空转。
改前源码 = '''
from __future__ import annotations
import inspect as _inspect


def _是调用点缺参错误(错误):
    最深 = 错误.__traceback__
    try:
        抛错文件 = Path(最深.tb_frame.f_code.co_filename).resolve()
    except (OSError, ValueError):
        return 假
    return 抛错文件 != _本文件路径
from 公共契约.基础类型.逻辑类型 import 真, 假
'''

_内建与约定名 = set(dir(builtins)) | {
    "__file__", "__name__", "__doc__", "__builtins__", "__spec__",
    "__package__", "__loader__", "__annotations__", "annotations",
}


def 未定义全局名(源: str, 文件名: str) -> set[str]:
    """`symtable` 名字解析：列出「被引用、却既非本模块定义也非内建」的全局名。

    这正是本缺陷的形态（`Path` / `_本文件路径`）—— `py_compile` 查不出来，
    只有做名字解析才看得见。作用域判据交给标准库 `symtable`，不自己另写一套。
    """
    import symtable

    顶层 = symtable.symtable(源, 文件名, "exec")
    已定义 = {符.get_name() for 符 in 顶层.get_symbols()
              if 符.is_assigned() or 符.is_imported() or 符.is_namespace()}
    未定义: set[str] = set()

    def 走(表) -> None:
        for 符 in 表.get_symbols():
            名 = 符.get_name()
            if (符.is_global() and 符.is_referenced()
                    and 名 not in 已定义 and 名 not in _内建与约定名):
                未定义.add(名)
        for 子 in 表.get_children():
            走(子)

    走(顶层)
    return 未定义


def 最深帧(错误: BaseException):
    """与生产判据同一口径：traceback 链的**最内层**（真正抛错的那一帧）。"""
    帧 = 错误.__traceback__
    while 帧 is not None and 帧.tb_next is not None:
        帧 = 帧.tb_next
    return 帧


class 假后端:
    """只实现网关真正用到的面（无 `注册表` ⇒ 能力参数校验不介入）。

    `行为` 在 `调用` 里被**调用**（而不是预先造好异常再 `raise`）——这样抛错帧
    真的落在行为函数体内，与生产链路的帧形态一致。
    """

    def __init__(self, 行为) -> None:
        self.行为 = 行为

    def 调用(self, 能力id: str, 参数: dict, *, 上下文=None, 超时秒=None):
        return self.行为(能力id, 参数)


def 建网关(行为) -> 网关核心:
    网关 = 网关核心(后端核心=假后端(行为), 幂等持久化=假)
    网关.停用幂等持久化()
    return 网关


def 深层缺参(能力id: str, 参数: dict):
    """模拟「实现少了必填位置参数」：抛错帧在本测试文件（网关层之外）。

    真实场景里这一帧在 后端核心 → 注册表 → 实现 的更下层；对网关而言同属「更下层」。
    """
    raise TypeError("探测媒体() missing 1 required positional argument: '文件路径'")


def 网关层抛错(能力id: str, 参数: dict):
    """在网关层内真抛 TypeError：抛错帧落在 `运行核心/统一网关/协议/参数别名表.py`。"""
    return _应用参数别名(能力id, None)


class Test模块符号齐备(unittest.TestCase):
    """① 静态锁：本模块不得再有「引用了未定义的全局符号」。"""

    def test_判据本身不空转_喂改前源码必报缺符号(self):
        """判据先自证：把改前源码喂进去，必须报出 `Path` 与 `_本文件路径`。

        否则这条锁是空转的（判据不灵 = 假绿），正是本仓反复强调的那类缺陷。
        """
        self.assertEqual(未定义全局名(改前源码, "改前.py"), {"Path", "_本文件路径"})

    def test_本模块无未定义全局符号(self):
        源 = Path(判定模块.__file__).read_text(encoding="utf-8")
        self.assertEqual(未定义全局名(源, "调用点缺参判定.py"), set())

    def test_缺的两件符号真在(self):
        """改前 `hasattr` 全假：`Path` 没导入、`_本文件路径` 没定义。"""
        self.assertTrue(hasattr(判定模块, "Path"), "模块缺 Path（改前 NameError 的直接成因）")
        self.assertTrue(hasattr(判定模块, "_本层目录"), "模块缺「本层」定义（改前 NameError 的另一成因）")


class Test抛错帧归属(unittest.TestCase):
    """②③④ 判据本身：深层 → 参数问题；本层 → 不降级；无帧 → 不猜。"""

    def test_深层抛错帧判是调用点缺参(self):
        错误 = None
        try:
            深层缺参(能力id, {})
        except TypeError as 异常:
            错误 = 异常
        self.assertTrue(判定模块._是调用点缺参错误(错误))

    def test_本层抛错帧不降级成400(self):
        """本网关自己的代码抛 TypeError（网关契约写错）⇒ 必须原样上抛，不谎报 400。

        取一个真会抛 TypeError 的网关侧函数（`_应用参数别名` 传非映射值 ⇒ `dict(None)`），
        其抛错帧在 `运行核心/统一网关/协议/参数别名表.py`。
        """
        错误 = None
        try:
            _应用参数别名("示例.包.能力", None)
        except TypeError as 异常:
            错误 = 异常
        self.assertIsNotNone(错误, "构造前提失效：_应用参数别名 未按预期抛 TypeError")
        帧 = 最深帧(错误)
        抛错帧文件 = Path(帧.tb_frame.f_code.co_filename).resolve()
        self.assertTrue(抛错帧文件.is_relative_to(判定模块._本层目录),
                        f"构造前提失效：抛错帧不在网关层内 {抛错帧文件}")
        self.assertFalse(判定模块._是调用点缺参错误(错误), "本层抛错被降级成了 400（谎报）")

    def test_本层目录就是统一网关层(self):
        本层目录 = 判定模块._本层目录
        self.assertEqual(本层目录.name, "统一网关")
        self.assertTrue((本层目录 / "核心处理" / "网关执行面.py").is_file(),
                        "「本层」必须覆盖发起 后端核心.调用 的 网关执行面.py")
        self.assertTrue(Path(__file__).resolve().is_relative_to(系统根))

    def test_无traceback的TypeError判否(self):
        """异常对象没有 traceback（从未 raise 过）⇒ 不猜，判「不是调用点缺参」。"""
        self.assertFalse(判定模块._是调用点缺参错误(
            TypeError("x() missing 1 required positional argument: 'a'")))


class Test网关链路端到端(unittest.TestCase):
    """⑤ 走真实网关：改前是 NameError（`_执行` 逸出）/「内部错误」（对外），改后 `参数不合法`。"""

    def test_经_执行回参数不合法_不再NameError(self):
        网关 = 建网关(深层缺参)
        请求 = 网关请求(操作="调用能力", 能力id=能力id, 参数={})
        响应 = 网关响应(请求id="回归", 操作="调用能力")
        网关._执行(请求, 响应)          # 改前：此处逸出 NameError: name 'Path' is not defined
        self.assertFalse(响应.成功)
        self.assertEqual(响应.错误码, "参数不合法")
        self.assertIn("缺少必填项", 响应.错误说明)
        self.assertIn("missing 1 required positional argument", 响应.错误说明)

    def test_经_处理对外就是参数不合法_不是内部错误(self):
        网关 = 建网关(深层缺参)
        响应 = 网关.处理(网关请求(操作="调用能力", 能力id=能力id, 参数={}, 权限范围=["全部"]))
        self.assertFalse(响应.成功)
        self.assertNotEqual(响应.错误码, "内部错误", f"仍谎报成内部错误: {响应.错误说明}")
        self.assertEqual(响应.错误码, "参数不合法")

    def test_本层TypeError照旧逸出到内部错误(self):
        """网关侧代码抛 TypeError（非调用点缺参）⇒ 不吞、不降级，对外如实 500 内部错误。"""
        网关 = 建网关(网关层抛错)
        响应 = 网关.处理(网关请求(操作="调用能力", 能力id=能力id, 参数={}, 权限范围=["全部"]))
        self.assertFalse(响应.成功)
        self.assertEqual(响应.错误码, "内部错误")


if __name__ == "__main__":
    unittest.main()
