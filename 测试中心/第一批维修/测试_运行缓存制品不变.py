"""P1-38：运行缓存统一解析与不可变制品回归测试。"""
from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

系统根 = Path(__file__).resolve().parents[2]
if str(系统根) not in sys.path:
    sys.path.insert(0, str(系统根))

from 公共契约.运行时.运行缓存 import 运行缓存环境变量, 解析运行缓存根
from 后端核心.后端核心 import 后端核心
from 开发工具.项目编译.项目编译器 import _生成启动器
from 运行核心.运行环境管理器 import 环境管理器 as 环境模块


def 全文件摘要(根: Path) -> dict[str, str]:
    """包含隐藏文件和运行副产物；任何新增或字节变化都会改变结果。"""
    return {
        文件.relative_to(根).as_posix(): hashlib.sha256(文件.read_bytes()).hexdigest()
        for 文件 in sorted(根.rglob("*")) if 文件.is_file()
    }


class 测试统一运行缓存根(unittest.TestCase):
    def setUp(self) -> None:
        self.临时根 = Path(tempfile.mkdtemp(prefix="运行缓存制品不变_"))
        self.用户目录 = self.临时根 / "用户"
        self.用户目录.mkdir()
        self.外部缓存 = self.临时根 / "受管运行缓存"

    def tearDown(self) -> None:
        shutil.rmtree(self.临时根, ignore_errors=True)

    def _建制品(self, 名称: str) -> tuple[Path, Path]:
        制品 = self.临时根 / 名称
        提供者 = 制品 / "平台客户端" / "支持库" / "适配层" / "样例提供者"
        提供者.mkdir(parents=True)
        (制品 / "平台客户端" / "模块库").mkdir(parents=True)
        (制品 / "运行入口").mkdir()
        (制品 / "运行入口" / "启动.py").write_text("# 不可变启动器\n", encoding="utf-8")
        (提供者 / "__init__.py").write_text("# 标记\n", encoding="utf-8")
        return 制品, 提供者

    def test_两个不同平台客户端制品解析到同一外部稳定缓存(self) -> None:
        制品甲, 提供者甲 = self._建制品("平台客户端制品-a1")
        制品乙, 提供者乙 = self._建制品("平台客户端制品-b2")
        环境 = {"HOME": str(self.用户目录)}

        with mock.patch.dict(os.environ, 环境, clear=True):
            缓存甲 = 解析运行缓存根(制品甲 / "平台客户端")
            缓存乙 = 解析运行缓存根(制品乙 / "平台客户端")
            环境目录甲 = 环境模块.环境目录(提供者甲, "相同环境摘要")
            环境目录乙 = 环境模块.环境目录(提供者乙, "相同环境摘要")

        self.assertEqual(缓存甲, 缓存乙)
        self.assertEqual(环境目录甲, 环境目录乙)
        self.assertFalse(缓存甲.is_relative_to(制品甲.resolve()))
        self.assertFalse(缓存乙.is_relative_to(制品乙.resolve()))

    def test_显式环境覆盖优先且源码开发保持工程缓存语义(self) -> None:
        源码根 = self.临时根 / "源码工程"
        源码根.mkdir()
        覆盖 = self.临时根 / "显式缓存"

        self.assertEqual(
            解析运行缓存根(
                源码根, 环境={运行缓存环境变量: str(覆盖), "HOME": str(self.用户目录)}),
            覆盖.resolve(),
        )
        self.assertEqual(
            解析运行缓存根(源码根, 环境={"HOME": str(self.用户目录)}),
            (源码根 / "工程缓存").resolve(),
        )

    def test_提供者环境根可与本轮运行状态缓存分离(self) -> None:
        制品, 提供者 = self._建制品("平台客户端制品-分离缓存")
        运行状态根 = self.临时根 / "本轮运行状态"
        共享环境根 = self.临时根 / "共享提供者缓存"
        with mock.patch.dict(os.environ, {
            运行缓存环境变量: str(运行状态根),
            "系统底座_提供者环境根": str(共享环境根),
        }, clear=False):
            环境路径 = 环境模块.环境目录(提供者, "摘要")
            self.assertTrue(环境路径.is_relative_to(共享环境根.resolve()))
            self.assertEqual(解析运行缓存根(制品 / "平台客户端"), 运行状态根.resolve())

    def test_后端状态库与提供者环境缓存都走外部缓存根(self) -> None:
        制品, 提供者 = self._建制品("平台客户端制品-状态")
        系统包根 = 制品 / "平台客户端"
        with mock.patch.dict(os.environ, {运行缓存环境变量: str(self.外部缓存)}, clear=False):
            后端 = 后端核心(系统根目录=系统包根)
            try:
                结果 = 环境模块.确保环境(提供者)
                环境路径 = 环境模块.环境目录(提供者, "相同摘要")
                状态库 = 后端.资源句柄服务.权威状态.数据库路径
            finally:
                后端.资源句柄服务.关闭服务()

        self.assertTrue(结果.成功)
        self.assertTrue(环境路径.resolve().is_relative_to(self.外部缓存.resolve()))
        self.assertTrue(状态库.resolve().is_relative_to(self.外部缓存.resolve()))
        self.assertTrue(状态库.is_file())
        self.assertFalse((制品 / "工程缓存").exists())
        self.assertFalse((系统包根 / "工程缓存").exists())

    def test_运行环境与后端初始化前后制品全文件摘要完全不变(self) -> None:
        制品, 提供者 = self._建制品("平台客户端制品-不可变")
        系统包根 = 制品 / "平台客户端"
        运行前 = 全文件摘要(制品)

        with mock.patch.dict(os.environ, {运行缓存环境变量: str(self.外部缓存)}, clear=False):
            后端 = 后端核心(系统根目录=系统包根)
            try:
                结果 = 环境模块.确保环境(提供者)
            finally:
                后端.资源句柄服务.关闭服务()

        self.assertTrue(结果.成功)
        self.assertEqual(运行前, 全文件摘要(制品))

    def test_生成启动器显式设置制品外缓存并开启阶段输出(self) -> None:
        启动器 = _生成启动器("系统工程平台客户端", 包前缀="平台客户端")
        self.assertIn("解析运行缓存根", 启动器)
        self.assertIn("制品运行=True", 启动器)
        self.assertIn(f'os.environ["{运行缓存环境变量}"]', 启动器)
        self.assertIn("运行缓存根目录=运行缓存根", 启动器)
        self.assertIn('os.environ.setdefault("系统底座_环境阶段输出", "1")', 启动器)

    def test_环境创建阶段有进度且超时返回明确阶段错误(self) -> None:
        _, 提供者 = self._建制品("平台客户端制品-超时")
        (提供者 / "依赖锁.json").write_text(
            '{"包":[{"名称":"不存在包","版本":"1.0.0","模块名":"不存在模块"}]}',
            encoding="utf-8",
        )
        阶段表: list[str] = []
        with mock.patch.dict(os.environ, {运行缓存环境变量: str(self.外部缓存)}, clear=False), \
             mock.patch.object(环境模块, "校验环境", return_value=False), \
             mock.patch.object(环境模块, "_尝试镜像命中", return_value=None), \
             mock.patch.object(
                 环境模块.subprocess, "run",
                 side_effect=subprocess.TimeoutExpired([sys.executable, "-m", "venv"], 1),
             ):
            结果 = 环境模块.确保环境(提供者, 超时秒=1, 进度回调=阶段表.append)

        self.assertFalse(结果.成功)
        self.assertIn("创建虚拟环境", 结果.错误说明)
        self.assertIn("检查缓存", 阶段表)
        self.assertIn("创建虚拟环境", 阶段表)


if __name__ == "__main__":
    unittest.main()
