"""模型连接器归一化能力：**错误分支**必须真返回失败结果（不是抛 NameError）。

背景（2026-09-23 潜伏缺陷复核）：
`支持库/后端/大语言模型支持库/模型连接器/实现/响应归一化.py` 的 2026-09-18 拆分
（提交 06729d76「模型连接器 1667 → 1449 行」）**只搬了函数体**，把全族唯一的失败结果
构造 `_失败`（现居 `实现/模型连接基元.py`）留在了旧文件。于是这两个**已注册能力**
（`大语言模型支持库.模型连接器.归一化对话响应` / `归一化流式分块`）的 6 处错误分支
全是 `NameError`：

    if not isinstance(原始数据, dict):
        return _失败("参数不合法", "原始数据必须是字典型")   # ← NameError

而这四条**正是契约明文要求的行为**（能力契约「空值」：*空或非字典/非逻辑型入参
返回 参数不合法*；「错误码」：`参数不合法` / `归一化失败`）。

为什么能潜伏：全仓没有任何用例走过这两个能力的**非正常形状入参**（本文件之前
`归一化对话响应` 在测试中心的出现次数为 0）。故本文件的核心是**覆盖错误分支**：
既验「入参形状不对」，也验「形状识别不了」，且都断言失败码与来源，而不是只断言
「不抛异常」——判据在 ≠ 判据覆盖。

运行（仓库根目录）：
    export PATH=/Library/Developer/CommandLineTools/usr/bin:$PATH; unset PYTHONPATH;
    python3.14 -m unittest 测试中心.支持库.测试_模型连接器归一化 -v
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

系统根 = Path(__file__).resolve().parents[2]
if str(系统根) not in sys.path:
    sys.path.insert(0, str(系统根))

from 公共契约.能力契约.契约 import 能力注册表
from 支持库.后端.大语言模型支持库.模型连接器 import 注册能力
from 支持库.后端.大语言模型支持库.模型连接器.实现.响应归一化 import (
    归一化对话响应,
    归一化流式分块,
)

能力id_对话响应 = "大语言模型支持库.模型连接器.归一化对话响应"
能力id_流式分块 = "大语言模型支持库.模型连接器.归一化流式分块"


def 已注册实现(能力id: str):
    """按生产真源（包的 `注册能力`）取注册表里的实现函数，不走第二份声明。"""
    注册表 = 能力注册表()
    注册能力(注册表)
    条目 = 注册表.获取(能力id)
    断言消息 = f"{能力id} 未注册（能力契约与注册表不一致）"
    if 条目 is None:
        raise AssertionError(断言消息)
    return 条目.实现函数


class 归一化对话响应错误分支(unittest.TestCase):
    def test_注册表里的实现就是本模块函数(self):
        """判据不空转：测的必须是已注册能力的那个实现对象。"""
        self.assertIs(归一化对话响应, 已注册实现(能力id_对话响应))
        self.assertIs(归一化流式分块, 已注册实现(能力id_流式分块))

    def test_原始数据非字典型返回参数不合法(self):
        for 坏值 in (None, "不是字典", 123, [1, 2]):
            结果 = 归一化对话响应(坏值)
            self.assertFalse(结果.成功, f"入参 {坏值!r} 竟判成功")
            self.assertEqual("参数不合法", 结果.错误.错误码)
            self.assertEqual("模型连接器", 结果.错误.来源)

    def test_包含思考非逻辑型返回参数不合法(self):
        for 坏值 in ("是", 1, None):
            结果 = 归一化对话响应({"choices": []}, 坏值)
            self.assertFalse(结果.成功, f"包含思考={坏值!r} 竟判成功")
            self.assertEqual("参数不合法", 结果.错误.错误码)

    def test_形状无法识别返回归一化失败(self):
        """`choices` 是字典（不是列表）时取 `[0]` 抛 KeyError —— 必须收口成归一化失败。"""
        结果 = 归一化对话响应({"choices": {"不是": "列表"}})
        self.assertFalse(结果.成功)
        self.assertEqual("归一化失败", 结果.错误.错误码)
        self.assertIn("响应形状无法识别", 结果.错误.消息)
        self.assertEqual("模型连接器", 结果.错误.来源)

    def test_四种协议正常形状仍走通(self):
        对话 = 归一化对话响应({"choices": [{"message": {"content": "甲", "reasoning_content": "想"},
                                       "finish_reason": "stop"}],
                          "usage": {"prompt_tokens": 3, "completion_tokens": 4}}, True)
        self.assertTrue(对话.成功, 对话)
        self.assertEqual("甲", 对话.值["内容"])
        self.assertEqual("想", 对话.值["思考"])
        self.assertEqual("stop", 对话.值["结束原因"])
        self.assertEqual(7, 对话.值["用量"]["总令牌数"])

        人类 = 归一化对话响应({"content": [{"type": "text", "text": "乙"},
                                      {"type": "thinking", "thinking": "思"}],
                          "stop_reason": "end_turn"}, True)
        self.assertEqual("乙", 人类.值["内容"])
        self.assertEqual("思", 人类.值["思考"])

        本地 = 归一化对话响应({"message": {"content": "丙", "reasoning_content": "虑"},
                          "done_reason": "stop"}, True)
        self.assertEqual("丙", 本地.值["内容"])
        self.assertEqual("虑", 本地.值["思考"])

        编码 = 归一化对话响应({"object": "response",
                          "output": [{"type": "message", "content": [{"type": "output_text", "text": "丁"}]},
                                     {"type": "reasoning", "summary": [{"text": "考"}]}],
                          "status": "completed"}, True)
        self.assertEqual("丁", 编码.值["内容"])
        self.assertEqual("考", 编码.值["思考"])


class 归一化流式分块错误分支(unittest.TestCase):
    def test_分块非字典型返回参数不合法(self):
        for 坏值 in (None, "不是字典", 456):
            结果 = 归一化流式分块(坏值)
            self.assertFalse(结果.成功, f"入参 {坏值!r} 竟判成功")
            self.assertEqual("参数不合法", 结果.错误.错误码)
            self.assertEqual("模型连接器", 结果.错误.来源)

    def test_包含思考非逻辑型返回参数不合法(self):
        结果 = 归一化流式分块({"choices": []}, "是")
        self.assertFalse(结果.成功)
        self.assertEqual("参数不合法", 结果.错误.错误码)

    def test_形状无法识别返回归一化失败(self):
        结果 = 归一化流式分块({"choices": {"不是": "列表"}})
        self.assertFalse(结果.成功)
        self.assertEqual("归一化失败", 结果.错误.错误码)
        self.assertIn("分块形状无法识别", 结果.错误.消息)

    def test_结构事件跳过与正文增量仍走通(self):
        跳过 = 归一化流式分块({"type": "ping"})
        self.assertTrue(跳过.成功, 跳过)
        self.assertEqual("跳过", 跳过.值["类型"])

        令牌 = 归一化流式分块({"choices": [{"delta": {"content": "戊"}}]})
        self.assertEqual("令牌", 令牌.值["类型"])
        self.assertEqual("戊", 令牌.值["内容"])

        思考 = 归一化流式分块({"choices": [{"delta": {"reasoning_content": "己"}}]}, True)
        self.assertEqual("思考中", 思考.值["类型"])
        self.assertEqual("己", 思考.值["内容"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
