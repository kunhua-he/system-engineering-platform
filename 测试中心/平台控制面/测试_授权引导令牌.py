"""受信引导凭证回归：一次性引导令牌 + 「无令牌路径」边界**如实钉住**。

## 背景（危险的一处）

`平台控制面/授权/核心.py` 的 `引导授予` 自称「唯一受信提权路径」，但旧实现里
`授予者 == "系统引导"` 是**调用方自己填的字符串**（公开能力
`平台控制面.授权.引导授予` 的参数契约里就有 `授予者` 字段）—— 可伪造。
真正的凭证只有**一次性引导令牌文件**。

## 本文件钉什么

1. 令牌文件在 → 缺令牌**必须拒**（不许静默放行）；
2. 令牌不符 → 拒；
3. 令牌匹配 → 放行，且文件**用后即焚**（一次性：同令牌第二次必须失败）；
4. 无令牌文件而携带令牌 → 拒；
5. `授予者 != "系统引导"` → 拒；角色不在可授予角色表 → 拒；
6. ★ **无令牌文件 + 无令牌 + 授予者=系统引导 → 仍放行**：这是模块 docstring 里
   **如实声明为「未关闭」**的已知边界（远端经该能力也走得到，因为该能力的参数契约
   里没有 `引导令牌` 字段）。本判据把它**钉死**：谁悄悄收紧或悄悄放宽，这里必红，
   逼其同步改声明。**它不是安全保证，是「已知且已声明」的回归锁。**

## 夹具口径

令牌文件**不经测试手写**，一律走生产腿 `授权服务.发放引导令牌()`（写 0600、
拒绝重复发放、平台已初始化即拒）—— 测试手写令牌文件等于绕开被侧的实现，
而且会把 `X.write_text` 这类写动作留在测试里。临时根造在 `工程缓存/测试临时` 下，
用平台唯一删树原语 `清只读后删除树` 经 `addCleanup` 清（同 测试_工作包05 口径）。
"""

from __future__ import annotations

import importlib
import sys
import tempfile
import unittest
from pathlib import Path

系统根 = Path(__file__).resolve().parents[2]
if str(系统根) not in sys.path:
    sys.path.insert(0, str(系统根))

from 公共契约.基础类型.逻辑类型 import 真
from 公共契约.运行时.平台适配 import 清只读后删除树
from 平台控制面.授权 import 取共享授权服务

#: 受管临时根在仓库内固定排除目录 `工程缓存/` 下（同 测试_补修阻断.py 口径）。
受管临时根 = 系统根 / "工程缓存" / "测试临时"
受管临时根.mkdir(parents=True, exist_ok=True)

可授予角色 = "调用Agent"
不可授予角色 = "普通用户"


class 受信引导凭证(unittest.TestCase):
    def setUp(self) -> None:
        目录 = Path(tempfile.mkdtemp(prefix="引导令牌测试_", dir=受管临时根))
        self.addCleanup(清只读后删除树, 目录, 忽略失败=真)
        self.服务 = 取共享授权服务(str(目录))

    def _发放令牌(self) -> str:
        """走生产腿发放一次性引导令牌（不手写文件）。"""
        成功, 消息, 令牌 = self.服务.发放引导令牌()
        self.assertTrue(成功, f"构造前提失效：发放引导令牌失败：{消息}")
        self.assertTrue(令牌, "构造前提失效：发放成功但没拿到令牌明文")
        return 令牌

    def test_1_令牌文件在_缺令牌必须拒(self) -> None:
        self._发放令牌()
        令牌文件 = Path(self.服务.引导令牌文件())
        self.assertTrue(令牌文件.is_file(), "构造前提失效：发放后令牌文件不在")
        成功, 消息 = self.服务.引导授予(身份id="甲", 角色=可授予角色, 授予者="系统引导")
        self.assertFalse(成功, f"令牌文件在、却没带令牌也放行了：{消息}")
        self.assertIn("引导令牌", 消息)
        self.assertTrue(令牌文件.is_file(), "被拒时不该焚毁令牌文件")

    def test_2_令牌不符必须拒(self) -> None:
        self._发放令牌()
        成功, 消息 = self.服务.引导授予(身份id="甲", 角色=可授予角色,
                                    授予者="系统引导", 引导令牌="假令牌")
        self.assertFalse(成功, f"令牌不符也放行了：{消息}")
        self.assertIn("不匹配", 消息)
        self.assertTrue(Path(self.服务.引导令牌文件()).is_file(), "被拒时不该焚毁令牌文件")

    def test_3_令牌匹配放行且用后即焚(self) -> None:
        令牌 = self._发放令牌()
        成功, 消息 = self.服务.引导授予(身份id="甲", 角色=可授予角色,
                                    授予者="系统引导", 引导令牌=令牌)
        self.assertTrue(成功, f"令牌匹配却被拒：{消息}")
        self.assertIn(可授予角色, self.服务.已授予角色("甲"), "放行了但没落授予记录")
        self.assertFalse(Path(self.服务.引导令牌文件()).is_file(), "令牌文件应「用后即焚」")

    def test_4_无令牌文件而携带令牌必须拒(self) -> None:
        成功, 消息 = self.服务.引导授予(身份id="甲", 角色=可授予角色,
                                    授予者="系统引导", 引导令牌="凭空令牌")
        self.assertFalse(成功, f"无令牌文件却认了令牌：{消息}")
        self.assertIn("不存在", 消息)

    def test_5_授予者不是系统引导必须拒(self) -> None:
        成功, 消息 = self.服务.引导授予(身份id="甲", 角色=可授予角色, 授予者="自己")
        self.assertFalse(成功, f"非系统引导也放行了：{消息}")
        self.assertIn("系统引导", 消息)

    def test_6_角色不在可授予表必须拒(self) -> None:
        成功, 消息 = self.服务.引导授予(身份id="甲", 角色=不可授予角色, 授予者="系统引导")
        self.assertFalse(成功, f"不可授予角色也放行了：{消息}")
        self.assertIn("不可授予", 消息)

    def test_7_边界钉住_无令牌路径仍放行且声明在位(self) -> None:
        """★ 已知未关闭边界：钉死现状 + 钉死声明，防「悄悄收紧/放宽」与「代码声明脱钩」。"""
        成功, 消息 = self.服务.引导授予(身份id="甲", 角色=可授予角色, 授予者="系统引导")
        self.assertTrue(
            成功,
            "无令牌路径被收紧了 —— 若是有意收口，必须同步改 `平台控制面/授权/核心.py` "
            f"模块 docstring 的「兼容边界」声明并更新本判据。实测：{消息}")
        self.assertIn("未配置引导令牌文件", 消息)
        模块 = importlib.import_module("平台控制面.授权.核心")
        self.assertIn("未关闭", 模块.__doc__ or "",
                      "核心.py 的「兼容边界」声明不见了或与代码脱钩（无令牌路径仍放行）")


if __name__ == "__main__":
    unittest.main()
