"""模块库.直播逐字稿.实现.排版合成 纯计算测试：8 个模式的排版结构与统一数字形式。

全部用内联字符串数据，不依赖模型、网络、文件；只断言真实返回的字符串结构。
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

if str(Path(__file__).resolve().parents[2]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from 模块库.直播逐字稿.实现.排版合成 import 合成全文, 统一数字形式

模式一 = {"模式": 1, "名称": "直播逐字稿", "段落前缀": "【主讲】", "保留时间戳": True}
模式二 = {"模式": 2, "名称": "方案逐字稿", "段落前缀": "", "保留时间戳": False}
模式三 = {"模式": 3, "名称": "会议逐字稿", "段落前缀": "", "保留时间戳": False}
模式四 = {"模式": 4, "名称": "课程培训逐字稿", "段落前缀": "", "保留时间戳": False}
模式五 = {"模式": 5, "名称": "访谈问答逐字稿", "段落前缀": "", "保留时间戳": False}
模式六 = {"模式": 6, "名称": "手卡口播稿", "段落前缀": "", "保留时间戳": False}
模式七 = {"模式": 7, "名称": "1:1 还原稿", "段落前缀": "", "保留时间戳": True}
模式八 = {"模式": 8, "名称": "知识问答库", "段落前缀": "", "保留时间戳": False}

段落样例 = [
    {"区间id": 1, "开始秒": 10.2, "结束秒": 14.8, "精校文本": "欢迎来到直播间。今天讲三个重点。"},
    {"区间id": 2, "开始秒": 615.0, "结束秒": 640.0, "精校文本": "第二个重点：门店动销。"},
]
元信息样例 = {"源文件": "/媒体/九月十日直播.mp4", "模式": 1, "模式名称": "直播逐字稿",
              "时长秒": 2380.0, "语言": "zh"}


class Test排版合成结构(unittest.TestCase):
    def test_模式1带时间戳与主讲前缀(self):
        输出 = 合成全文(模式一, 段落样例, 元信息样例)
        self.assertIn("[00:10.2] 【主讲】欢迎来到直播间。", 输出)
        self.assertIn("[10:15.0] 【主讲】第二个重点：门店动销。", 输出)

    def test_模式2每段带议题标题(self):
        输出 = 合成全文(模式二, 段落样例, 元信息样例)
        self.assertIn("## 欢迎来到直播间", 输出)
        self.assertIn("## 第二个重点：门店动销", 输出)

    def test_模式3同一议题不重复出标题(self):
        段落 = [{"开始秒": 0.0, "精校文本": "同一个议题。先讲背景。"},
                {"开始秒": 30.0, "精校文本": "同一个议题。再讲结论。"}]
        输出 = 合成全文(模式三, 段落, 元信息样例)
        self.assertEqual(输出.count("## "), 1)
        self.assertIn("先讲背景。", 输出)
        self.assertIn("再讲结论。", 输出)

    def test_模式4按十分钟分章(self):
        输出 = 合成全文(模式四, 段落样例, 元信息样例)
        self.assertIn("## 第1章", 输出)
        self.assertIn("## 第2章", 输出)

    def test_模式5问答原样输出(self):
        段落 = [{"区间id": 1, "开始秒": 0.0, "结束秒": 3.0, "精校文本": "【问】多少钱？【答】1288元。"}]
        输出 = 合成全文(模式五, 段落, 元信息样例)
        self.assertIn("【问】多少钱？【答】1288元。", 输出)

    def test_模式6一句一行(self):
        输出 = 合成全文(模式六, 段落样例, 元信息样例)
        行列表 = [行 for 行 in 输出.splitlines() if 行.strip()]
        self.assertIn("欢迎来到直播间。", 行列表)
        self.assertIn("今天讲三个重点。", 行列表)
        self.assertIn("第二个重点：门店动销。", 行列表)

    def test_模式7逐句带时间戳(self):
        输出 = 合成全文(模式七, 段落样例, 元信息样例)
        self.assertIn("[00:10] 欢迎来到直播间。", 输出)
        self.assertIn("[10:15] 第二个重点：门店动销。", 输出)
        self.assertNotIn("[00:10.2]", 输出)

    def test_模式8问题标题递增(self):
        输出 = 合成全文(模式八, 段落样例, 元信息样例)
        self.assertIn("## 问题1", 输出)
        self.assertIn("## 问题2", 输出)

    def test_段落之间空行分隔(self):
        输出 = 合成全文(模式一, 段落样例, 元信息样例)
        self.assertIn("欢迎来到直播间。今天讲三个重点。\n\n[10:15.0]", 输出)

    def test_空段落只返回头部(self):
        输出 = 合成全文(模式一, [], 元信息样例)
        self.assertTrue(输出.startswith("# 九月十日直播 逐字稿\n"))
        self.assertIn("> 模式：直播逐字稿｜时长：39:40｜生成时间：未记录", 输出)
        self.assertNotIn("【主讲】", 输出)

    def test_生成时间缺失写未记录提供时原样写入(self):
        缺失 = 合成全文(模式一, [], 元信息样例)
        self.assertIn("生成时间：未记录", 缺失)
        提供 = dict(元信息样例, 生成时间="2026-09-10 21:00:00")
        self.assertIn("生成时间：2026-09-10 21:00:00", 合成全文(模式一, [], 提供))

    def test_死循环区间文末注明(self):
        元信息 = dict(元信息样例, 死循环区间=[{"开始秒": 600.0, "结束秒": 900.0, "重复次数": 18}])
        输出 = 合成全文(模式一, 段落样例, 元信息)
        self.assertTrue(输出.endswith("> 注：10:00-15:00 为直播间音乐/无声段（原识别为重复内容），已略过。"))

    def test_非法输入返回安全结果(self):
        self.assertEqual(合成全文(None, 段落样例, 元信息样例), "")
        self.assertEqual(合成全文("直播逐字稿", 段落样例, 元信息样例), "")
        self.assertIn("时长：00:00", 合成全文({"模式": 1}, None, None))

    def test_忽略非法段落元素(self):
        输出 = 合成全文(模式一, [None, "文本", {}, {"开始秒": 1.0, "精校文本": "只有这一段。"}], 元信息样例)
        self.assertIn("[00:01.0] 【主讲】只有这一段。", 输出)
        self.assertEqual(输出.count("【主讲】"), 1)


class Test统一数字形式(unittest.TestCase):
    def test_五十到一百转阿拉伯数字(self):
        self.assertEqual(统一数字形式("五十到一百"), "50到100")

    def test_一千家转阿拉伯数字(self):
        self.assertEqual(统一数字形式("一千家"), "1000家")

    def test_口语尾数与零位(self):
        self.assertEqual(统一数字形式("三千八"), "3800")
        self.assertEqual(统一数字形式("一百零二"), "102")
        self.assertEqual(统一数字形式("两万五"), "25000")

    def test_保留原句其它字符(self):
        self.assertEqual(统一数字形式("本月目标五十到一百家，已签约三千八。"),
                         "本月目标50到100家，已签约3800。")

    def test_已含阿拉伯数字不重复处理(self):
        self.assertEqual(统一数字形式("2026年3月完成1288单"), "2026年3月完成1288单")

    def test_不误伤常用词(self):
        self.assertEqual(统一数字形式("统一口径一起做就一定能成"), "统一口径一起做就一定能成")

    def test_非文本输入返回空串(self):
        self.assertEqual(统一数字形式(None), "")
        self.assertEqual(统一数字形式(""), "")


if __name__ == "__main__":
    unittest.main()
