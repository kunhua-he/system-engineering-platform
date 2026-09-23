"""工作包10 新机器恢复编排器测试：真实恢复、最小调用、期望校验、失败与幂等。

覆盖 P1-10 六项验收：成功恢复、恢复后最小调用真实取回结果、期望状态零差异、
快照缺文件部分失败、依赖锁损坏拒绝执行、重复恢复幂等。调用真实实现，禁止桩。
"""
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

系统根 = Path(__file__).resolve().parents[2]
if str(系统根) not in sys.path:
    sys.path.insert(0, str(系统根))

from 公共契约.基础类型.逻辑类型 import 真, 假
from 平台控制面.备份恢复.恢复编排器 import 新机器恢复编排器

from 公共契约.运行时.平台适配 import 清只读后删除树

#: ★ A 档泄漏收口（2026-09-23）：受管临时根在仓库内**固定排除目录** `工程缓存/` 下。
#: `dir=` 显式指向它 ⇒ 落点与**测试运行时**的 `TMPDIR` 解耦（平台跑测试时 `TMPDIR` 被指进
#: 仓库工作目录，裸 `mkdtemp()` 会把夹具造进仓库）。`工程缓存` 在
#: `开发工具/项目编译/工作区指纹.py` 的 `固定排除目录` 里 ⇒ 即便进程被 SIGKILL、
#: 清理没跑到，残留也进不了工作区指纹（`.gitignore` 保不住：指纹的未跟踪腿不用
#: `--exclude-standard`）。清理走平台唯一删树原语 `清只读后删除树`（本类用例常造
#: `0o555` 目录 / `0o444` 文件，plain `shutil.rmtree` 会被权限位挡住）。
受管临时根 = 系统根 / "工程缓存" / "测试临时"
受管临时根.mkdir(parents=True, exist_ok=True)

#: 模块级临时夹具登记：本模块的夹具**在模块级 helper 里**造（helper 拿不到 TestCase 实例，
#: 用不了 `self.addCleanup`）⇒ 走 unittest 的**模块级收尾钩子** `tearDownModule` 登记清理
#: （同样「用例失败也跑」）。拿得到用例实例的站点一律用 `self.addCleanup`。
_临时夹具登记: list[Path] = []


def tearDownModule() -> None:
    """模块收尾：清理本模块造在 `受管临时根` 下的全部夹具（**用例失败也跑**）。"""
    for 夹具 in _临时夹具登记:
        清只读后删除树(夹具, 忽略失败=真)
    _临时夹具登记.clear()


最小能力内容 = "print(1 + 1)\n"


def 摘要(内容: bytes) -> str:
    return hashlib.sha256(内容).hexdigest()


def 建造恢复输入(*, 快照含最小能力: bool = 真, 依赖锁损坏: bool = 假) -> dict:
    """建造一套真实输入：源码快照、内容寻址制品、依赖锁与备份目录。"""
    根 = Path(tempfile.mkdtemp(prefix="工作包10_", dir=受管临时根))
    _临时夹具登记.append(根)
    空目录 = 根 / "恢复目标"
    空目录.mkdir()
    源码快照 = 根 / "源码快照"
    源码快照.mkdir()
    if 快照含最小能力:
        (源码快照 / "最小能力.py").write_text(最小能力内容, encoding="utf-8")
    (源码快照 / "说明.txt").write_text("源码快照说明", encoding="utf-8")
    (源码快照 / "权威状态.json").write_text("快照权威状态", encoding="utf-8")
    制品目录 = 根 / "制品"
    制品目录.mkdir()
    制品内容 = "内容寻址制品数据".encode("utf-8")
    (制品目录 / f"{摘要(制品内容)}.bin").write_bytes(制品内容)
    (制品目录 / "产物.json").write_text('{"产物": "应用"}', encoding="utf-8")
    依赖锁路径 = 根 / "依赖锁定.json"
    if 依赖锁损坏:
        依赖锁路径.write_text("{这不是合法JSON", encoding="utf-8")
    else:
        依赖锁路径.write_text(json.dumps({
            "包列表": [{"名称": "支撑库", "版本": "1.0.0"},
                       {"名称": "工具库", "版本": "2.3.1"}],
        }, ensure_ascii=False, indent=2), encoding="utf-8")
    备份目录 = 根 / "备份"
    (备份目录 / "内容").mkdir(parents=True)
    权威内容 = "备份权威状态".encode("utf-8")
    (备份目录 / "内容" / "权威状态.json").write_bytes(权威内容)
    (备份目录 / "备份清单.json").write_text(json.dumps({
        "条目": [{"相对路径": "权威状态.json", "摘要": 摘要(权威内容)}],
    }, ensure_ascii=False), encoding="utf-8")
    return {"空目录路径": str(空目录), "源码快照目录": str(源码快照),
            "制品目录": str(制品目录), "依赖锁定文件路径": str(依赖锁路径),
            "备份目录": str(备份目录)}


class Test成功恢复(unittest.TestCase):
    """测试1：编排恢复在全新空目录成功，各步骤真实结果，复制文件摘要与来源一致。"""

    def setUp(self):
        self.输入 = 建造恢复输入()
        self.编排器 = 新机器恢复编排器()
        self.结果 = self.编排器.编排恢复(self.输入)
        self.恢复目录 = Path(self.输入["空目录路径"])

    def test_恢复成功且各步骤返回真实结果(self):
        self.assertEqual(self.结果["状态"], "已恢复")
        self.assertEqual(self.结果["失败原因"], [])
        self.assertEqual(self.结果["步骤结果"]["校验依赖锁定"]["包数"], 2)
        for 步骤 in ("复制源码快照", "复制制品", "写入依赖锁定", "恢复备份", "真实性校验"):
            self.assertTrue(self.结果["步骤结果"][步骤]["成功"], f"{步骤} 必须成功")
        self.assertTrue(self.结果["步骤结果"]["真实性校验"]["全部一致"])

    def test_复制文件摘要与来源一致(self):
        for 相对, 来源 in self.编排器.来源路径表.items():
            self.assertEqual(摘要((self.恢复目录 / 相对).read_bytes()),
                             摘要(来源.read_bytes()), f"恢复文件摘要必须与来源一致: {相对}")

    def test_备份权威状态覆盖同名文件且制品仓库就位(self):
        权威 = (self.恢复目录 / "权威状态.json").read_text(encoding="utf-8")
        self.assertEqual(权威, "备份权威状态", "备份恢复的权威状态必须覆盖快照同名文件")
        self.assertTrue((self.恢复目录 / "制品仓库" / "产物.json").is_file())
        self.assertTrue((self.恢复目录 / "项目依赖锁定.json").is_file())


class Test恢复后最小调用(unittest.TestCase):
    """测试2：恢复后最小调用真实执行并返回结果。"""

    def test_最小调用真实返回结果(self):
        输入 = 建造恢复输入()
        恢复目录 = Path(输入["空目录路径"])
        编排器 = 新机器恢复编排器()
        结果 = 编排器.编排恢复(输入)
        self.assertEqual(结果["状态"], "已恢复")
        输出 = 编排器.恢复后最小调用(恢复目录)
        self.assertEqual(输出, "2", "必须真实运行最小能力样板并取回输出")


class Test期望状态校验(unittest.TestCase):
    """测试3：恢复后期望状态校验返回零差异。"""

    def test_期望状态零差异(self):
        输入 = 建造恢复输入()
        编排器 = 新机器恢复编排器()
        编排器.编排恢复(输入)
        差异 = 编排器.期望状态校验(Path(输入["空目录路径"]))
        self.assertEqual(差异["差异数"], 0)
        self.assertEqual(差异["缺失"], [])
        self.assertEqual(差异["多余"], [])
        self.assertEqual(差异["摘要不一致"], [])


class Test快照缺文件部分失败(unittest.TestCase):
    """测试4：源码快照缺少最小能力样板时恢复部分失败并给出原因。"""

    def test_缺最小能力样板部分失败(self):
        输入 = 建造恢复输入(快照含最小能力=假)
        结果 = 新机器恢复编排器().编排恢复(输入)
        self.assertEqual(结果["状态"], "部分失败")
        self.assertTrue(any("最小能力样板文件" in 原因 for 原因 in 结果["失败原因"]),
                        f"失败原因必须指明缺失文件: {结果['失败原因']}")
        self.assertFalse(结果["步骤结果"]["复制源码快照"]["成功"])


class Test依赖锁损坏拒绝执行(unittest.TestCase):
    """测试5：依赖锁定文件 JSON 非法时恢复拒绝执行且不产生副作用。"""

    def test_依赖锁损坏拒绝执行(self):
        输入 = 建造恢复输入(依赖锁损坏=真)
        with self.assertRaises(ValueError):
            新机器恢复编排器().编排恢复(输入)
        空目录 = Path(输入["空目录路径"])
        self.assertEqual(list(空目录.iterdir()), [], "拒绝执行不得在目标目录留下任何文件")


class Test重复恢复幂等(unittest.TestCase):
    """测试6：同输入恢复两次结果一致，不残留中间状态。"""

    def test_两次恢复结果一致(self):
        输入 = 建造恢复输入()
        恢复目录 = Path(输入["空目录路径"])
        编排器 = 新机器恢复编排器()
        第一次 = 编排器.编排恢复(输入)
        编排器.恢复后最小调用(恢复目录)
        第二次 = 编排器.编排恢复(输入)
        self.assertEqual(第二次, 第一次, "同输入恢复两次结果必须一致")
        self.assertEqual(第二次["状态"], "已恢复")
        差异 = 编排器.期望状态校验(恢复目录)
        self.assertEqual(差异["差异数"], 0, "重复恢复不得残留中间状态")


if __name__ == "__main__":
    unittest.main()
