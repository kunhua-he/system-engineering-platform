"""模块库.直播逐字稿 实现.分片转写 单元测试：纯假调用器 + tempfile 目录。

不联网、不依赖真实模型、不写系统目录。
覆盖：分片区间切分、逐片截取与转写、分段绝对时间换算、断点续跑复用、截取/转写失败如实反映。
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
from 模块库.直播逐字稿.实现.缓存与续跑 import 准备缓存
from 模块库.直播逐字稿.实现.分片转写 import 分片区间表, 分片转写

截取能力id = "媒体处理支持库.FFmpeg媒体.截取音频"
转写能力id = "转写支持库.转写.转写音频文件"


def 装配底座():
    """装配底座三包（文件操作/数据交换/资源管理）：实现层的缓存目录与 JSON 落盘走底座。"""
    from 公共契约.能力契约.调用器 import 设置惰性装配函数, 注册能力调用器
    from 公共契约.能力契约.契约 import 能力注册表
    from 运行核心.能力调用.唯一能力调用 import 唯一能力调用服务, 设置全局唯一服务
    原惰性装配 = 设置惰性装配函数.__globals__.get("_惰性装配函数")
    设置惰性装配函数(None)
    注册表 = 能力注册表()
    from 支持库.后端.文件系统支持库.文件操作 import 注册能力 as 注册文件操作
    from 支持库.后端.数据操作支持库.数据交换 import 注册能力 as 注册数据交换
    from 支持库.后端.系统核心支持库.资源管理 import 注册能力 as 注册资源管理
    注册文件操作(注册表)
    注册数据交换(注册表)
    注册资源管理(注册表)
    服务 = 唯一能力调用服务(注册表)
    注册能力调用器(服务)
    设置全局唯一服务(服务)
    return 原惰性装配


def 卸载底座(原惰性装配) -> None:
    from 公共契约.能力契约.调用器 import 注册能力调用器, 设置惰性装配函数
    from 运行核心.能力调用.唯一能力调用 import 设置全局唯一服务
    注册能力调用器(None)
    设置全局唯一服务(None)
    设置惰性装配函数(原惰性装配)


class 假调用器:
    """截取返回落盘路径，转写返回含分段的文本；可指定哪几片失败。"""

    def __init__(self, 截取失败片: set[int] | None = None, 转写失败片: set[int] | None = None):
        self.截取失败片 = set(截取失败片 or ())
        self.转写失败片 = set(转写失败片 or ())
        self.截取记录: list[dict] = []
        self.转写记录: list[dict] = []

    def __call__(self, 能力id, 请求参数):
        if 能力id == 截取能力id:
            self.截取记录.append(dict(请求参数))
            序号 = len(self.截取记录)
            if 序号 in self.截取失败片:
                return 结果.失败("参数不合法", f"第{序号}片区间不合法", 来源="测试")
            目标 = Path(请求参数["输出路径"])
            目标.parent.mkdir(parents=True, exist_ok=True)
            目标.write_bytes(b"fake-audio")
            return 结果.成功结果({"字节b64": "", "格式": "mp3", "字节数": 4, "输出路径": str(目标)})
        self.转写记录.append(dict(请求参数))
        序号 = len(self.转写记录)
        if 序号 in self.转写失败片:
            return 结果.失败("转写失败", f"第{序号}片转写失败", 来源="测试")
        return 结果.成功结果({
            "文本": f"第{序号}片文本",
            "语言": "zh",
            "分段": [{"序号": 1, "开始秒": 0.5, "结束秒": 1.5, "文本": f"第{序号}片首句",
                    "平均对数概率": -0.2, "压缩比": 0.9, "无语音概率": 0.01}],
        })


class 测试用例基类(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.原惰性装配 = 装配底座()

    @classmethod
    def tearDownClass(cls):
        卸载底座(cls.原惰性装配)

    def setUp(self):
        self.临时 = tempfile.TemporaryDirectory(prefix="测试_分片转写_")
        self.缓存 = 准备缓存(str(Path(self.临时.name) / "缓存"))

    def tearDown(self):
        self.临时.cleanup()


class Test分片区间表(unittest.TestCase):
    def test_十秒音频按四秒切片(self):
        表 = 分片区间表(10.0, 4)
        self.assertEqual([(项["开始秒"], 项["结束秒"]) for 项 in 表],
                         [(0.0, 4.0), (4.0, 8.0), (8.0, 10.0)])

    def test_音频短于一片时只切一片(self):
        表 = 分片区间表(2.5, 300)
        self.assertEqual(len(表), 1)
        self.assertEqual((表[0]["开始秒"], 表[0]["结束秒"]), (0.0, 2.5))

    def test_时长正好整除不产生空片(self):
        表 = 分片区间表(8.0, 4)
        self.assertEqual([项["结束秒"] for 项 in 表], [4.0, 8.0])

    def test_序号连续(self):
        self.assertEqual([项["序号"] for 项 in 分片区间表(11.0, 4)], [1, 2, 3])


class Test分片转写(测试用例基类):
    def test_逐片截取转写并落盘且时间戳绝对化(self):
        调用 = 假调用器()
        结果字典 = 分片转写("源.mp4", self.缓存, 8.0, 4, 调用, 超时秒=30.0)
        self.assertEqual((结果字典["状态"], 结果字典["分片总数"], 结果字典["已完成"]), ("完成", 2, 2))
        self.assertEqual(len(调用.截取记录), 2)
        self.assertEqual(len(调用.转写记录), 2)
        self.assertEqual(调用.截取记录[0]["开始秒"], 0.0)
        self.assertEqual(调用.截取记录[1]["开始秒"], 4.0)
        self.assertTrue(调用.转写记录[0]["返回分段"])
        第一片, 第二片 = 结果字典["分片转写列表"]
        self.assertEqual((第一片["开始秒"], 第一片["结束秒"]), (0.0, 4.0))
        self.assertEqual((第二片["开始秒"], 第二片["结束秒"]), (4.0, 8.0))
        self.assertEqual(第一片["分段"][0]["开始秒"], 0.5, "首片相对时间不加偏移")
        self.assertEqual(第二片["分段"][0]["开始秒"], 4.5, "第二片时间戳必须换算成绝对时间")
        self.assertEqual(第二片["分段"][0]["结束秒"], 5.5)
        盘上 = json.loads((Path(self.缓存["分片转写"]) / "分片_0002.json").read_text(encoding="utf-8"))
        self.assertEqual((盘上["分片序号"], 盘上["分段"][0]["开始秒"]), (2, 4.5))
        self.assertTrue((Path(self.缓存["分片"]) / "分片_0001.mp3").is_file())

    def test_续跑复用已落盘分片不再转写(self):
        首次 = 分片转写("源.mp4", self.缓存, 8.0, 4, 假调用器(), 超时秒=30.0)
        self.assertEqual(首次["复用"], 0)
        再次调用 = 假调用器()
        二次 = 分片转写("源.mp4", self.缓存, 8.0, 4, 再次调用, 超时秒=30.0, 续跑=True)
        self.assertEqual(二次["状态"], "完成")
        self.assertEqual(二次["复用"], 2, "已落盘的分片必须直接复用")
        self.assertEqual(再次调用.转写记录, [], "复用分片不得再调转写")
        self.assertEqual(二次["分片转写列表"][1]["分段"][0]["开始秒"], 4.5)

    def test_关闭续跑时重新转写(self):
        分片转写("源.mp4", self.缓存, 8.0, 4, 假调用器(), 超时秒=30.0)
        再次调用 = 假调用器()
        分片转写("源.mp4", self.缓存, 8.0, 4, 再次调用, 超时秒=30.0, 续跑=False)
        self.assertEqual(len(再次调用.转写记录), 2)

    def test_整段旧产物不会被误复用(self):
        """整段模式留下的 分片_0001.json（0→时长）不得被分片模式当成本片结果复用。"""
        落盘 = Path(self.缓存["分片转写"]) / "分片_0001.json"
        落盘.parent.mkdir(parents=True, exist_ok=True)
        落盘.write_text(json.dumps({"分片序号": 1, "开始秒": 0.0, "结束秒": 600.0,
                                   "文本": "整段旧产物", "分段": [{"序号": 1, "开始秒": 0.0,
                                                            "结束秒": 1.0, "文本": "旧"}]},
                                 ensure_ascii=False), encoding="utf-8")
        调用 = 假调用器()
        结果字典 = 分片转写("源.mp4", self.缓存, 8.0, 4, 调用, 超时秒=30.0)
        self.assertEqual(结果字典["复用"], 0, "时间区间不吻合的旧产物必须重新转写")
        self.assertEqual(len(调用.转写记录), 2)
        self.assertEqual(结果字典["分片转写列表"][0]["文本"], "第1片文本")

    def test_截取失败如实反映且不转写该片(self):
        结果字典 = 分片转写("源.mp4", self.缓存, 8.0, 4, 假调用器(截取失败片={2}), 超时秒=30.0)
        self.assertEqual((结果字典["状态"], 结果字典["已完成"], 结果字典["分片总数"]), ("部分失败", 1, 2))
        self.assertIn("第2片截取失败", 结果字典["错误说明"])
        self.assertEqual([项["分片序号"] for 项 in 结果字典["分片转写列表"]], [1])

    def test_单片转写失败不影响其它片(self):
        结果字典 = 分片转写("源.mp4", self.缓存, 8.0, 4, 假调用器(转写失败片={1}), 超时秒=30.0)
        self.assertEqual((结果字典["状态"], 结果字典["已完成"]), ("部分失败", 1))
        self.assertIn("第1片转写失败", 结果字典["错误说明"])
        self.assertEqual(结果字典["分片转写列表"][0]["分片序号"], 2)

    def test_全部失败时列表为空(self):
        结果字典 = 分片转写("源.mp4", self.缓存, 8.0, 4, 假调用器(截取失败片={1, 2}), 超时秒=30.0)
        self.assertEqual(结果字典["分片转写列表"], [])
        self.assertEqual(结果字典["状态"], "部分失败")
        self.assertTrue(结果字典["错误说明"])


if __name__ == "__main__":
    unittest.main()
