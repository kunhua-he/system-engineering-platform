"""模块库.直播逐字稿 实现.复核调度 单元测试：纯假数据 + 假调用器。

不联网、不依赖真实模型、不装配平台网关；临时文件只写 tempfile 目录。
覆盖：聚类边界（单段/合并/等于阈值不合并/多段/空输入/id 连续）、
复核区间成功写盘与调用参数、底层失败如实反映且不伪造文本、参数校验。
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

项目根 = Path(__file__).resolve().parents[2]
if str(项目根) not in sys.path:
    sys.path.insert(0, str(项目根))

from 公共契约.基础类型.结果类型 import 结果
from 模块库.直播逐字稿.实现.复核调度 import 聚类区间, 复核区间

转写能力id = "转写支持库.转写.转写音频文件"


class 假调用器:
    """记录调用参数并按脚本返回统一结果；可指定整轮失败或某几轮失败。"""

    def __init__(self, 失败轮: set[int] | None = None, 全部失败: bool = False):
        self.调用记录: list[tuple[str, dict]] = []
        self.失败轮 = set(失败轮 or ())
        self.全部失败 = bool(全部失败)

    def __call__(self, 能力id, 请求参数):
        self.调用记录.append((能力id, 请求参数))
        序号 = len(self.调用记录)
        if self.全部失败 or 序号 in self.失败轮:
            return 结果.失败("转写失败", f"第{序号}轮底层转写失败", 来源="测试")
        return 结果.成功结果({"文本": f"第{序号}轮识别文本",
                             "分段": [{"序号": 1, "开始秒": 0.0, "结束秒": 1.0}]})

    @property
    def 附加术语列表(self) -> list[str]:
        return [记录[1].get("附加术语", "") for 记录 in self.调用记录]


class Test聚类区间(unittest.TestCase):
    def test_单段不需要合并(self):
        区间 = 聚类区间([{"开始秒": 10.2, "结束秒": 14.8}])["区间"]
        self.assertEqual(区间, [{"区间id": 1, "开始秒": 10.2, "结束秒": 14.8, "疑难数": 1}])

    def test_两段间隔小于阈值合并(self):
        区间 = 聚类区间([{"开始秒": 10.0, "结束秒": 20.0},
                        {"开始秒": 50.0, "结束秒": 60.0}], 间隔秒=60)["区间"]
        self.assertEqual(len(区间), 1)
        self.assertEqual((区间[0]["开始秒"], 区间[0]["结束秒"], 区间[0]["疑难数"]), (10.0, 60.0, 2))

    def test_间隔刚好等于阈值不合并(self):
        区间 = 聚类区间([{"开始秒": 0.0, "结束秒": 10.0},
                        {"开始秒": 70.0, "结束秒": 80.0}], 间隔秒=60)["区间"]
        self.assertEqual(len(区间), 2, "间隔恰好等于阈值必须算两段")
        self.assertEqual([项["区间id"] for 项 in 区间], [1, 2])

    def test_多段聚成一段(self):
        疑难段 = [{"开始秒": float(序号), "结束秒": float(序号) + 0.5} for 序号 in range(5)]
        区间 = 聚类区间(疑难段, 间隔秒=60)["区间"]
        self.assertEqual(len(区间), 1)
        self.assertEqual((区间[0]["疑难数"], 区间[0]["结束秒"]), (5, 4.5))

    def test_空输入返回空区间(self):
        self.assertEqual(聚类区间([], 间隔秒=60), {"区间": []})
        self.assertEqual(聚类区间(None, 间隔秒=60), {"区间": []})

    def test_区间id连续(self):
        疑难段 = [{"开始秒": 0.0, "结束秒": 1.0}, {"开始秒": 500.0, "结束秒": 501.0},
                 {"开始秒": 1000.0, "结束秒": 1001.0}]
        区间 = 聚类区间(疑难段, 间隔秒=60)["区间"]
        self.assertEqual([项["区间id"] for 项 in 区间], [1, 2, 3])
        self.assertEqual([项["开始秒"] for 项 in 区间], [0.0, 500.0, 1000.0])

    def test_坏条目与乱序不影响聚类(self):
        疑难段 = [{"开始秒": 100.0, "结束秒": 101.0}, {"开始秒": "坏值", "结束秒": None},
                 {"开始秒": 0.0, "结束秒": 1.0}, "不是字典"]
        self.assertEqual([项["开始秒"] for 项 in 聚类区间(疑难段, 间隔秒=60)["区间"]], [0.0, 100.0])


class Test复核区间(unittest.TestCase):
    def setUp(self):
        self.临时目录 = tempfile.TemporaryDirectory(prefix="测试_复核调度_")
        self.复核目录 = str(Path(self.临时目录.name) / "06_复核")
        self.区间 = {"区间id": 1, "开始秒": 10.2, "结束秒": 14.8, "疑难数": 3}

    def tearDown(self):
        self.临时目录.cleanup()

    def test_复核区间成功写盘(self):
        调用 = 假调用器()
        结果字典 = 复核区间("媒体文件.bin", self.区间, self.复核目录, 调用,
                            轮数=3, 模型配置={"模型名": "假模型"}, 超时秒=12.5)
        self.assertEqual(结果字典["状态"], "完成")
        self.assertEqual(结果字典["错误说明"], "")
        self.assertEqual(len(结果字典["轮次"]), 3)
        路径 = Path(self.复核目录) / "复核_0001.json"
        self.assertTrue(路径.is_file(), "未落盘 复核_0001.json")
        self.assertEqual(结果字典["写入路径"], str(路径))
        数据 = json.loads(路径.read_text(encoding="utf-8"))
        self.assertEqual((数据["区间id"], len(数据["轮次"])), (1, 3))
        self.assertEqual(数据["轮次"][0]["文本"], "第1轮识别文本")
        # 调用参数与每轮术语提示
        self.assertEqual(len(调用.调用记录), 3)
        for 能力id, 参数 in 调用.调用记录:
            self.assertEqual(能力id, 转写能力id)
            self.assertEqual((参数["文件路径"], 参数["超时秒"]), ("媒体文件.bin", 12.5))
            self.assertEqual(参数["配置"], {"模型名": "假模型"})
            self.assertTrue(参数["返回分段"])
        self.assertEqual(len(set(调用.附加术语列表)), 3, "三轮附加术语提示必须不同")

    def test_复核区间底层失败如实反映不伪造文本(self):
        调用 = 假调用器(全部失败=True)
        结果字典 = 复核区间("媒体文件.bin", self.区间, self.复核目录, 调用, 轮数=3)
        self.assertEqual(结果字典["状态"], "部分失败")
        self.assertEqual(结果字典["错误码"], "转写失败")
        self.assertIn("底层转写失败", 结果字典["错误说明"])
        for 条目 in 结果字典["轮次"]:
            self.assertEqual((条目["成功"], 条目["文本"], 条目["分段"]), (False, "", []))
        原文 = (Path(self.复核目录) / "复核_0001.json").read_text(encoding="utf-8")
        self.assertNotIn("识别文本", 原文)

    def test_复核区间部分轮次失败保留成功轮(self):
        结果字典 = 复核区间("媒体文件.bin", self.区间, self.复核目录, 假调用器(失败轮={2}), 轮数=3)
        self.assertEqual(结果字典["状态"], "部分失败")
        self.assertIn("第2轮", 结果字典["错误说明"])
        文本表 = {条目["轮"]: (条目["成功"], 条目["文本"]) for 条目 in 结果字典["轮次"]}
        self.assertEqual(文本表[1], (True, "第1轮识别文本"))
        self.assertEqual(文本表[2], (False, ""))
        self.assertEqual(文本表[3], (True, "第3轮识别文本"))

    def test_复核区间参数不合法(self):
        调用 = 假调用器()
        用例表 = [("", self.区间, self.复核目录), ("媒体文件.bin", self.区间, ""),
                 ("媒体文件.bin", {"开始秒": 0.0}, self.复核目录)]
        for 源, 区间, 目录 in 用例表:
            结果字典 = 复核区间(源, 区间, 目录, 调用)
            self.assertEqual((结果字典["状态"], 结果字典["错误码"], 结果字典["轮次"]),
                             ("失败", "参数不合法", []))
        self.assertEqual(复核区间("媒体文件.bin", self.区间, self.复核目录, 调用, 轮数=0)["错误码"],
                         "参数不合法")
        self.assertEqual(调用.调用记录, [], "参数不合法时不得调用底层能力")

    def test_复核区间调用异常不外泄(self):
        def 抛异常调用器(能力id, 请求参数):
            raise RuntimeError("底层崩溃")

        结果字典 = 复核区间("媒体文件.bin", self.区间, self.复核目录, 抛异常调用器, 轮数=2)
        self.assertEqual((结果字典["状态"], 结果字典["错误码"]), ("部分失败", "调用异常"))
        self.assertIn("底层崩溃", 结果字典["错误说明"])


if __name__ == "__main__":
    unittest.main()
