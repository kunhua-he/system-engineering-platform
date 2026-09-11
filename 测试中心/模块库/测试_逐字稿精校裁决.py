"""逐字稿精校裁决测试：并发顺序、重试、句柄借用不释放、提示词渲染。"""
from __future__ import annotations

import sys
import threading
import time
import unittest
from pathlib import Path

项目根 = Path(__file__).resolve().parents[2]
if str(项目根) not in sys.path:
    sys.path.insert(0, str(项目根))

from 公共契约.基础类型.结果类型 import 结果
from 模块库.直播逐字稿.实现.精校裁决 import 上游瞬时错误, 渲染提示词, 裁决窗口列表


class 假调用能力:
    """记录调用过程的假调用能力，可指定前几次对话失败、或前几次报句柄不存在。"""

    def __init__(self, 失败次数: int = 0, 句柄失效次数: int = 0):
        self.调用记录: list[tuple[str, dict]] = []
        self.失败次数 = 失败次数
        self.句柄失效次数 = 句柄失效次数
        self.对话计数 = 0
        self.连接次数 = 0
        self.锁 = threading.Lock()

    def __call__(self, 能力id: str, 参数: dict):
        with self.锁:
            self.调用记录.append((能力id, 参数))
        if 能力id.endswith("连接LLM"):
            with self.锁:
                self.连接次数 += 1
                本次 = self.连接次数
            return 结果.成功结果({"句柄": 1000 + 本次, "模型": "假模型"})
        if 能力id.endswith("释放句柄"):
            return 结果.成功结果({"句柄": 参数.get("句柄"), "已释放": True})
        if 能力id.endswith("生成对话"):
            with self.锁:
                self.对话计数 += 1
                序号 = self.对话计数
                # 句柄失效场景：第 1 轮（第一次连接出来的句柄）的对话全报不存在
                当前句柄 = 参数.get("句柄")
            if self.句柄失效次数 and 当前句柄 == 1001 and 序号 <= self.句柄失效次数:
                return 结果.失败("句柄不存在", f"句柄不存在: {当前句柄}", 来源="测试")
            if 序号 <= self.失败次数:
                return 结果.失败("提供者不可用", "假失败", 来源="测试")
            # 从消息里取时间范围，回显成"回复"，便于校验顺序
            文本 = ""
            for 消息 in 参数.get("消息列表") or []:
                文本 = str(消息.get("content") or "")
            范围 = ""
            for 行 in 文本.splitlines():
                if 行.startswith("【时间范围】"):
                    范围 = 行.replace("【时间范围】", "").strip()
            time.sleep(0.01)   # 让并发真有交错机会
            return 结果.成功结果({"回复": f"段{范围}", "用量": {}})
        return 结果.失败("未知能力", 能力id, 来源="测试")


def 造窗(序号: int) -> dict:
    return {"窗口id": 序号, "开始秒": float(序号), "结束秒": float(序号) + 1,
            "底稿文本": f"窗{序号}底稿", "疑难说明": "", "证据文本": ""}


class 测试裁决窗口列表(unittest.TestCase):

    def test_并发后段落顺序与窗口顺序一致(self):
        窗口列表 = [造窗(i) for i in range(1, 7)]
        假 = 假调用能力()
        出 = 裁决窗口列表(窗口列表, "提示词", 假, {"模型": "假模型", "部署形态": "云端",
                                            "url": "http://x", "api_key": "k"}, 并发数=3)
        self.assertEqual(len(出["段落列表"]), 6)
        for 序号, 段落 in enumerate(出["段落列表"], start=1):
            self.assertEqual(段落["状态"], "完成")
            self.assertEqual(段落["区间id"], 序号, "并发后段落必须仍按窗口顺序排列")
            # 该段落的文本必须来自它自己那个窗口的请求（证明并发没有串台）
            self.assertIn(str(段落["开始秒"]), 段落["精校文本"])
            self.assertIn(str(段落["结束秒"]), 段落["精校文本"])

    def test_并发数1时走串行且同样完成(self):
        窗口列表 = [造窗(i) for i in range(1, 4)]
        假 = 假调用能力()
        出 = 裁决窗口列表(窗口列表, "提示词", 假, {"模型": "假模型", "部署形态": "云端",
                                            "url": "http://x", "api_key": "k"}, 并发数=1)
        self.assertEqual([段["状态"] for 段 in 出["段落列表"]], ["完成"] * 3)

    def test_单窗失败按重试次数补跑(self):
        假 = 假调用能力(失败次数=1)   # 第 1 次对话失败，重试即成功
        出 = 裁决窗口列表([造窗(1)], "提示词", 假,
                     {"模型": "假模型", "部署形态": "云端", "url": "http://x", "api_key": "k"},
                     重试次数=1, 并发数=1)
        self.assertEqual(出["段落列表"][0]["状态"], "完成")

    def test_借用外部句柄不连接也不释放(self):
        假 = 假调用能力()
        裁决窗口列表([造窗(1)], "提示词", 假, None, 外部句柄=12345, 并发数=1)
        能力序列 = [能力id for 能力id, _ in 假.调用记录]
        self.assertNotIn("大语言模型支持库.模型连接器.连接LLM", 能力序列)
        self.assertNotIn("大语言模型支持库.模型连接器.释放句柄", 能力序列,
                        "消费者借出的句柄，底座不得释放")
        self.assertTrue(all(参数.get("句柄") == 12345
                        for 能力id, 参数 in 假.调用记录
                        if 能力id.endswith("生成对话")))

    def test_句柄被回收后自动重连只补失败窗口(self):
        """句柄默认 30 分钟空闲即被回收；失效时应用模型配置重连一次并补跑失败窗口。"""
        窗口列表 = [造窗(i) for i in range(1, 4)]
        假 = 假调用能力(句柄失效次数=3)   # 第一轮三个窗口全报"句柄不存在"
        出 = 裁决窗口列表(窗口列表, "提示词", 假,
                     {"模型": "假模型", "部署形态": "云端", "url": "http://x", "api_key": "k"},
                     重试次数=0, 并发数=1)
        self.assertEqual([段["状态"] for 段 in 出["段落列表"]], ["完成"] * 3,
                        "重连后所有失败窗口都应补跑成功")
        self.assertGreaterEqual(假.连接次数, 2, "应当重新连接拿新句柄")
        self.assertFalse(出["借用句柄"], "重连出来的句柄由底座释放")

    def test_上游瞬时错误可识别且重试自愈(self):
        """503/超时属上游瞬时过载：应识别出来并重试，不该直接判整场失败。"""
        self.assertTrue(上游瞬时错误({"错误说明": "前置精校失败: 模型 HTTP 返回 503"}))
        self.assertTrue(上游瞬时错误({"错误说明": "模型调用失败: LLM HTTP调用失败: timed out"}))
        self.assertFalse(上游瞬时错误({"错误说明": "模式缺少裁决提示词"}))
        假 = 假调用能力(失败次数=1)
        出 = 裁决窗口列表([造窗(1)], "提示词", 假,
                     {"模型": "假模型", "部署形态": "云端", "url": "http://x", "api_key": "k"},
                     重试次数=2, 并发数=1)
        self.assertEqual(出["段落列表"][0]["状态"], "完成", "瞬时错误重试后应完成")

    def test_自带配置时连接后必释放(self):
        假 = 假调用能力()
        裁决窗口列表([造窗(1)], "提示词", 假,
                 {"模型": "假模型", "部署形态": "云端", "url": "http://x", "api_key": "k"}, 并发数=1)
        能力序列 = [能力id for 能力id, _ in 假.调用记录]
        self.assertIn("大语言模型支持库.模型连接器.连接LLM", 能力序列)
        self.assertIn("大语言模型支持库.模型连接器.释放句柄", 能力序列)


class 测试渲染提示词(unittest.TestCase):

    def test_输出结构为空时回退通用分节(self):
        出 = 渲染提示词("按【分节结构】{输出结构}组织。")
        self.assertIn("按内容自然分节", 出)
        self.assertNotIn("{输出结构}", 出)

    def test_附加要求注入调用方口径(self):
        出 = 渲染提示词("规则。{附加要求}\n输出正文。", 附加要求="「斑」不能写成「班」")
        self.assertIn("【调用方要求】", 出)
        self.assertIn("「斑」不能写成「班」", 出)

    def test_附加要求为空时不留占位与空行(self):
        出 = 渲染提示词("规则。{附加要求}\n输出正文。")
        self.assertNotIn("{附加要求}", 出)
        self.assertNotIn("【调用方要求】", 出)
        self.assertNotIn("\n\n\n", 出)


if __name__ == "__main__":
    unittest.main()
