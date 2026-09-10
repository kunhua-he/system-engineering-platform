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
from 模块库.直播逐字稿.实现.精校裁决 import 渲染提示词, 裁决窗口列表


class 假调用能力:
    """记录调用过程的假调用能力，可指定第几次对话失败。"""

    def __init__(self, 失败次数: int = 0):
        self.调用记录: list[tuple[str, dict]] = []
        self.失败次数 = 失败次数
        self.对话计数 = 0
        self.锁 = threading.Lock()

    def __call__(self, 能力id: str, 参数: dict):
        with self.锁:
            self.调用记录.append((能力id, 参数))
        if 能力id.endswith("连接LLM"):
            return 结果.成功结果({"句柄": 999, "模型": "假模型"})
        if 能力id.endswith("释放句柄"):
            return 结果.成功结果({"句柄": 参数.get("句柄"), "已释放": True})
        if 能力id.endswith("生成对话"):
            with self.锁:
                self.对话计数 += 1
                序号 = self.对话计数
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
