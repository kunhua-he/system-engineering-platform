"""缓存读写定向测试：覆盖 验证缓存 的读取、写入、损坏容错与 阶段缓存可复用 判定语义。

引用 测试中心/运行测试.py 的 读取缓存/写入缓存/阶段缓存可复用。
所有缓存读写均使用临时目录隔离（tempfile.mkdtemp + tearDown 清理），
禁止触碰真实 工程缓存/验证缓存。
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

系统根 = Path(__file__).resolve().parents[1]
if str(系统根) not in sys.path:
    sys.path.insert(0, str(系统根))

import 测试中心.运行测试 as 运行测试


def 构造缓存项(
    *,
    摘要: str = "源码摘要",
    成功: bool = True,
    测试数: int = 3,
    结构版本: str | None = None,
    环境摘要: str = "环境摘要",
    时间戳: float = 1000.0,
) -> dict:
    """构造一个完整的缓存项（未指定结构版本时使用当前缓存结构版本）。"""
    return {
        "摘要": 摘要,
        "成功": 成功,
        "测试数": 测试数,
        "结构版本": 结构版本 if 结构版本 is not None else 运行测试.缓存结构版本,
        "环境摘要": 环境摘要,
        "时间戳": 时间戳,
    }


class Test读取缓存(unittest.TestCase):
    """读取缓存：目录聚合读取、损坏容错、临时目录隔离。"""

    def setUp(self) -> None:
        self.临时目录 = Path(tempfile.mkdtemp(prefix="测试缓存读写-"))
        self.补丁 = patch.object(运行测试, "验证缓存目录", self.临时目录)
        self.补丁.start()
        self.addCleanup(self.补丁.stop)

    def tearDown(self) -> None:
        shutil.rmtree(self.临时目录, ignore_errors=True)

    def test_缓存目录不存在时读取返回空字典(self) -> None:
        临时空目录 = Path(tempfile.mkdtemp(prefix="测试缓存读写-空-"))
        try:
            with patch.object(运行测试, "验证缓存目录", 临时空目录):
                self.assertEqual(运行测试.读取缓存(), {})
        finally:
            shutil.rmtree(临时空目录, ignore_errors=True)

    def test_写入后能读回(self) -> None:
        缓存 = {"静态契约": 构造缓存项()}
        运行测试.写入缓存(缓存)
        self.assertEqual(运行测试.读取缓存(), 缓存)

    def test_损坏JSON文件读取时跳过且不抛异常(self) -> None:
        (self.临时目录 / "静态契约.json").write_text("{损坏的JSON", encoding="utf-8")
        self.assertEqual(运行测试.读取缓存(), {})

    def test_损坏JSON不影响其他阶段缓存读取(self) -> None:
        运行测试.写入缓存({"静态契约": 构造缓存项()})
        (self.临时目录 / "组件合规.json").write_text("{损坏的JSON", encoding="utf-8")
        缓存 = 运行测试.读取缓存()
        self.assertEqual(set(缓存), {"静态契约"})
        self.assertEqual(缓存["静态契约"]["测试数"], 3)


class Test写入缓存(unittest.TestCase):
    """写入缓存：按阶段独立文件、原子写无临时残留。"""

    def setUp(self) -> None:
        self.临时目录 = Path(tempfile.mkdtemp(prefix="测试缓存读写-"))
        self.补丁 = patch.object(运行测试, "验证缓存目录", self.临时目录)
        self.补丁.start()
        self.addCleanup(self.补丁.stop)

    def tearDown(self) -> None:
        shutil.rmtree(self.临时目录, ignore_errors=True)

    def test_按阶段生成独立缓存文件(self) -> None:
        运行测试.写入缓存({
            "静态契约": 构造缓存项(),
            "项目装配": 构造缓存项(摘要="装配摘要"),
        })
        阶段文件表 = sorted(路径.name for 路径 in self.临时目录.glob("*.json"))
        self.assertEqual(阶段文件表, ["静态契约.json", "项目装配.json"])

    def test_写入后无临时文件残留(self) -> None:
        运行测试.写入缓存({"静态契约": 构造缓存项()})
        残留表 = list(self.临时目录.glob("*.tmp"))
        self.assertEqual(残留表, [])

    def test_同阶段覆盖写入后读回最新内容(self) -> None:
        运行测试.写入缓存({"静态契约": 构造缓存项(测试数=3)})
        运行测试.写入缓存({"静态契约": 构造缓存项(测试数=9)})
        缓存 = 运行测试.读取缓存()
        self.assertEqual(缓存["静态契约"]["测试数"], 9)


class Test阶段缓存可复用(unittest.TestCase):
    """阶段缓存可复用 判定语义（纯逻辑，不触碰文件）。"""

    def test_有效缓存项对敏感与非敏感阶段均可复用(self) -> None:
        缓存项 = 构造缓存项()
        self.assertTrue(运行测试.阶段缓存可复用(
            "真实进程", 缓存项, "源码摘要", "环境摘要", 当前时间=1001,
        ))
        self.assertTrue(运行测试.阶段缓存可复用(
            "静态契约", 缓存项, "源码摘要", "环境摘要", 当前时间=1001,
        ))

    def test_摘要不匹配时不可复用(self) -> None:
        self.assertFalse(运行测试.阶段缓存可复用(
            "静态契约", 构造缓存项(), "新摘要", "环境摘要",
        ))

    def test_摘要缺失时不可复用(self) -> None:
        缓存项 = 构造缓存项()
        del 缓存项["摘要"]
        self.assertFalse(运行测试.阶段缓存可复用(
            "静态契约", 缓存项, "源码摘要", "环境摘要",
        ))

    def test_成功缺失或为假时不可复用(self) -> None:
        缺成功 = 构造缓存项()
        del 缺成功["成功"]
        self.assertFalse(运行测试.阶段缓存可复用(
            "静态契约", 缺成功, "源码摘要", "环境摘要",
        ))
        self.assertFalse(运行测试.阶段缓存可复用(
            "静态契约", 构造缓存项(成功=False), "源码摘要", "环境摘要",
        ))

    def test_测试数缺失或为零时不可复用(self) -> None:
        缺测试数 = 构造缓存项()
        del 缺测试数["测试数"]
        self.assertFalse(运行测试.阶段缓存可复用(
            "静态契约", 缺测试数, "源码摘要", "环境摘要",
        ))
        self.assertFalse(运行测试.阶段缓存可复用(
            "静态契约", 构造缓存项(测试数=0), "源码摘要", "环境摘要",
        ))

    def test_结构版本缺失或不符时不可复用(self) -> None:
        缺版本 = 构造缓存项()
        del 缺版本["结构版本"]
        self.assertFalse(运行测试.阶段缓存可复用(
            "静态契约", 缺版本, "源码摘要", "环境摘要",
        ))
        self.assertFalse(运行测试.阶段缓存可复用(
            "静态契约", 构造缓存项(结构版本="9.9.9"), "源码摘要", "环境摘要",
        ))

    def test_环境摘要变化时敏感阶段不可复用(self) -> None:
        self.assertFalse(运行测试.阶段缓存可复用(
            "真实进程", 构造缓存项(), "源码摘要", "变化后的环境", 当前时间=1001,
        ))

    def test_环境摘要变化时非敏感阶段也不可复用(self) -> None:
        """修复后语义：环境摘要对所有阶段生效，非敏感阶段同样校验。"""
        self.assertFalse(运行测试.阶段缓存可复用(
            "静态契约", 构造缓存项(), "源码摘要", "变化后的环境", 当前时间=1001,
        ))

    def test_环境摘要缺失时跳过比对不失效(self) -> None:
        """旧式缓存项不带环境摘要：跳过比对，其余字段满足即可复用。"""
        缓存项 = 构造缓存项()
        del 缓存项["环境摘要"]
        self.assertTrue(运行测试.阶段缓存可复用(
            "静态契约", 缓存项, "源码摘要", "任意环境", 当前时间=1001,
        ))

    def test_敏感阶段时间戳过期时不可复用(self) -> None:
        过期时间 = 1000 + 运行测试.运行证据有效秒 + 1
        self.assertFalse(运行测试.阶段缓存可复用(
            "真实进程", 构造缓存项(), "源码摘要", "环境摘要",
            当前时间=过期时间,
        ))

    def test_慢速层强制慢速时不可复用(self) -> None:
        self.assertFalse(运行测试.阶段缓存可复用(
            "慢速层", 构造缓存项(), "源码摘要", "环境摘要",
            强制慢速=True, 当前时间=1001,
        ))

    def test_缓存项为空时不可复用(self) -> None:
        self.assertFalse(运行测试.阶段缓存可复用(
            "静态契约", None, "源码摘要", "环境摘要",
        ))
        self.assertFalse(运行测试.阶段缓存可复用(
            "静态契约", {}, "源码摘要", "环境摘要",
        ))


if __name__ == "__main__":
    unittest.main()
