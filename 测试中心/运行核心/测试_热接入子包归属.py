"""热接入一致性门禁：非聚合库的独立子包能力归属黑盒测试。

背景：`支持库.后端.代码解析支持库` 既是真实包，又新增了独立成包的子包
`支持库.后端.代码解析支持库.语法索引`。发现器禁止同一能力 id 在两份声明里
重复，因此子包能力只能由子包自己的声明登记；父包重新热接入时不得把子包能力
算成“注册未声明”。

覆盖：独立子包能力不计入父包 / 未独立成包的子域仍算父包 / 父包自注册未声明仍被拦下
      / 声明未注册仍被拦下。
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

系统根 = Path(__file__).resolve().parents[2]
if str(系统根) not in sys.path:
    sys.path.insert(0, str(系统根))

from 公共契约.包声明.声明 import 加载声明文件  # noqa: E402
from 公共契约.能力契约.契约 import 能力实现, 能力注册表  # noqa: E402
from 后端核心.后端核心 import 后端核心  # noqa: E402

父包id = "支持库.后端.代码解析支持库"
子包id = "支持库.后端.代码解析支持库.语法索引"
父能力 = "代码解析支持库.解析代码字节"
子能力 = "代码解析支持库.语法索引.解析Python语法"


def 写包(根目录: Path, 相对路径: str, 包id: str, 能力id列表: list[str]) -> Path:
    目录 = 根目录 / 相对路径
    目录.mkdir(parents=True, exist_ok=True)
    声明路径 = 目录 / "包声明.json"
    声明路径.write_text(json.dumps({
        "包id": 包id, "名称": 包id.rsplit(".", 1)[-1], "类型": "支持库",
        "版本": "1.0.0", "说明": "热接入子包归属测试用", "入口": "__init__.py",
        "依赖": [],
        "能力": [{"能力id": 能力id, "名称": 能力id.rsplit(".", 1)[-1],
                  "版本": "1.0.0", "说明": "测试", "参数": [],
                  "返回": "结果型", "错误码": []} for 能力id in 能力id列表],
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    return 声明路径


class 测试热接入子包归属(unittest.TestCase):
    def setUp(self) -> None:
        self.临时 = tempfile.TemporaryDirectory(prefix="热接入子包归属_")
        self.系统根 = Path(self.临时.name)
        self.后端根 = self.系统根 / "支持库" / "后端"
        self.后端根.mkdir(parents=True)
        self.核心 = 后端核心(系统根目录=self.系统根,
                             运行缓存根目录=self.系统根 / "运行缓存")

    def tearDown(self) -> None:
        self.临时.cleanup()

    def 注册(self, 注册表: 能力注册表, 能力id: str, 包id: str) -> None:
        注册表.注册(能力实现(能力id=能力id, 包id=包id, 实现函数=lambda: None))

    def test_独立子包能力不计入父包注册未声明(self) -> None:
        父声明路径 = 写包(self.后端根, "代码解析支持库", 父包id, [父能力])
        写包(self.后端根, "代码解析支持库/语法索引", 子包id, [子能力])
        注册表 = 能力注册表()
        self.注册(注册表, 父能力, 父包id)
        self.注册(注册表, 子能力, 子包id)
        问题 = self.核心._校验热接入包(
            加载声明文件(父声明路径), 注册表, {父包id, 子包id})
        self.assertEqual(问题, [])

    def test_未独立成包的子域仍算父包未声明(self) -> None:
        父声明路径 = 写包(self.后端根, "代码解析支持库", 父包id, [父能力])
        注册表 = 能力注册表()
        self.注册(注册表, 父能力, 父包id)
        self.注册(注册表, 子能力, 子包id)
        问题 = self.核心._校验热接入包(加载声明文件(父声明路径), 注册表, {父包id})
        self.assertTrue(any("注册未声明" in 条 and 子能力 in 条 for 条 in 问题), 问题)

    def test_父包自注册未声明仍被拦下(self) -> None:
        父声明路径 = 写包(self.后端根, "代码解析支持库", 父包id, [父能力])
        注册表 = 能力注册表()
        self.注册(注册表, 父能力, 父包id)
        self.注册(注册表, "代码解析支持库.心跳", 父包id)
        问题 = self.核心._校验热接入包(
            加载声明文件(父声明路径), 注册表, {父包id})
        self.assertTrue(any("注册未声明" in 条 and "心跳" in 条 for 条 in 问题), 问题)

    def test_声明未注册仍被拦下(self) -> None:
        父声明路径 = 写包(self.后端根, "代码解析支持库", 父包id,
                          [父能力, "代码解析支持库.解析代码文件"])
        注册表 = 能力注册表()
        self.注册(注册表, 父能力, 父包id)
        问题 = self.核心._校验热接入包(
            加载声明文件(父声明路径), 注册表, {父包id})
        self.assertTrue(any("声明未注册" in 条 for 条 in 问题), 问题)


if __name__ == "__main__":
    unittest.main()
