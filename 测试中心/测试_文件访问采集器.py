"""文件访问采集器定向测试：覆盖安装、事件采集、去重、截断、弱依赖与网络标记。

引用 测试中心/文件访问采集器.py。
测试目标文件放在 测试中心 下的临时目录（不在采集器默认排除目录表内）；
TMPDIR 内的临时写入用于验证"临时目录读写全部排除"。
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest
import uuid
from pathlib import Path

系统根 = Path(__file__).resolve().parents[1]
if str(系统根) not in sys.path:
    sys.path.insert(0, str(系统根))

import 测试中心.文件访问采集器 as 采集器模块
from 测试中心.文件访问采集器 import (
    安装采集器,
    文件访问采集器,
    静态扫描弱依赖,
    规范化pyc路径,
)

测试中心目录 = Path(__file__).resolve().parent


class 采集器测试基类(unittest.TestCase):
    """共享隔离环境：非排除临时根（测试中心下）+ 单例采集器清空。"""

    def setUp(self) -> None:
        self.非排除根 = 测试中心目录 / f"__采集器测试临时_{uuid.uuid4().hex[:8]}__"
        self.非排除根.mkdir(parents=True, exist_ok=False)
        self.采集器 = 安装采集器()
        self.采集器.清空记录()

    def tearDown(self) -> None:
        self.采集器.清空记录()
        shutil.rmtree(self.非排除根, ignore_errors=True)

    def _建文件(self, 名称: str, 内容: str = "内容") -> Path:
        文件 = self.非排除根 / 名称
        文件.write_text(内容, encoding="utf-8")
        return 文件


class Test文件访问采集(采集器测试基类):
    """真实 hook 采集：安装后真实 open 读文件、写临时文件排除、listdir 记目录。"""

    def test_安装后open读文件进入依赖清单且pyc规范化(self):
        目标文件 = self._建文件("源码_甲.py")
        self.采集器.清空记录()
        with 目标文件.open("r", encoding="utf-8") as 文件对象:
            self.assertEqual(文件对象.read(), "内容")
        # 模拟 pyc 读取事件：__pycache__/X.cpython-*.pyc 规范化为源 X.py
        self.采集器._处理审计事件(
            "open", ("/缓存根/__pycache__/源码_甲.cpython-314.pyc", "rb", 0),
        )
        清单 = self.采集器.提取依赖清单()
        self.assertIn(str(目标文件.resolve()), 清单["读文件列表"])
        self.assertIn("/缓存根/源码_甲.py", 清单["读文件列表"])
        self.assertFalse(any(
            "__pycache__" in 路径 or ".cpython-" in 路径 or 路径.endswith(".pyc")
            for 路径 in 清单["读文件列表"]
        ))

    def test_open写临时文件不计入依赖(self):
        临时写目录 = Path(tempfile.mkdtemp(prefix="采集器写测试-"))
        try:
            临时写文件 = 临时写目录 / "临时输出.txt"
            临时写文件.write_text("输出", encoding="utf-8")
            清单 = self.采集器.提取依赖清单()
            self.assertNotIn(str(临时写文件), 清单["读文件列表"])
            self.assertNotIn(str(临时写目录), 清单["目录列表"])
            self.assertFalse(清单["弱依赖标记"])  # TMPDIR 内写入被排除 → 无弱依赖
        finally:
            shutil.rmtree(临时写目录, ignore_errors=True)

    def test_os_listdir记录目录(self):
        目标目录 = self.非排除根 / "目标目录"
        目标目录.mkdir()
        self.采集器.清空记录()
        self.assertEqual(os.listdir(目标目录), [])
        清单 = self.采集器.提取依赖清单()
        self.assertIn(str(目标目录.resolve()), 清单["目录列表"])

    def test_同一文件读两次只记一次(self):
        目标文件 = self._建文件("只读一次.py")
        self.采集器.清空记录()
        with 目标文件.open("r", encoding="utf-8"):
            pass
        with 目标文件.open("r", encoding="utf-8"):
            pass
        清单 = self.采集器.提取依赖清单()
        命中数 = sum(
            1 for 路径 in 清单["读文件列表"] if 路径 == str(目标文件.resolve())
        )
        self.assertEqual(命中数, 1)

    def test_网络事件标记(self):
        self.采集器._处理审计事件("socket.connect", (None, ("127.0.0.1", 8080)))
        清单 = self.采集器.提取依赖清单()
        self.assertTrue(清单["网络标记"])
        # socket.__new__ 同样触发网络标记
        self.采集器._处理审计事件("socket.__new__", (None, 2, 1, 0))
        self.assertTrue(self.采集器.提取依赖清单()["网络标记"])

    def test_提取依赖清单结构正确(self):
        清单 = self.采集器.提取依赖清单()
        self.assertEqual(
            set(清单),
            {"读文件列表", "目录列表", "弱依赖标记", "截断标记", "网络标记"},
        )
        self.assertIsInstance(清单["读文件列表"], list)
        self.assertIsInstance(清单["目录列表"], list)
        self.assertFalse(清单["弱依赖标记"])
        self.assertFalse(清单["截断标记"])
        self.assertFalse(清单["网络标记"])

    def test_防重复安装不叠加(self):
        实例1 = 安装采集器()
        实例2 = 安装采集器()
        self.assertIs(实例1, 实例2)
        目标文件 = self._建文件("防重复.py")
        实例1.清空记录()
        with 目标文件.open("r", encoding="utf-8"):
            pass
        清单 = 实例2.提取依赖清单()
        self.assertEqual(len(清单["读文件列表"]), 1)


class Test模拟事件处理(采集器测试基类):
    """直接构造审计事件参数验证内部处理：fd 忽略、flags 解码、截断、scandir。"""

    def test_fd型open事件忽略(self):
        self.采集器._处理审计事件("open", (123456, "r", 0))
        清单 = self.采集器.提取依赖清单()
        self.assertEqual(清单["读文件列表"], [])
        self.assertEqual(清单["目录列表"], [])

    def test_os_open以flags解码读写(self):
        目标文件 = self._建文件("os_open_目标.py")
        self.采集器.清空记录()
        # os.open(path, O_RDONLY) → mode=None, flags 低位 0 → 读
        self.采集器._处理审计事件("open", (str(目标文件), None, 0))
        # os.open(path, O_WRONLY) → mode=None, flags 低位 1 → 写
        self.采集器._处理审计事件("open", (str(目标文件), None, 1))
        # os.open(path, O_RDWR) → mode=None, flags 低位 2 → 读写
        self.采集器._处理审计事件("open", (str(目标文件), None, 2))
        清单 = self.采集器.提取依赖清单()
        self.assertIn(str(目标文件.resolve()), 清单["读文件列表"])
        # 已存在且被写 → 弱依赖标记
        self.assertTrue(清单["弱依赖标记"])

    def test_记录数超限截断标记(self):
        小采集器 = 文件访问采集器(排除目录表=[], 最大记录数=3)
        for 序号 in range(5):
            小采集器._处理审计事件(
                "open", (f"/虚构/源文件_{序号}.py", "r", 0),
            )
        清单 = 小采集器.提取依赖清单()
        self.assertTrue(清单["截断标记"])
        self.assertEqual(len(清单["读文件列表"]), 3)

    def test_os_scandir事件记录目录且fd型忽略(self):
        self.采集器._处理审计事件("os.scandir", ("/虚构/扫描目录",))
        self.采集器._处理审计事件("os.scandir", (3,))  # fd 型忽略
        清单 = self.采集器.提取依赖清单()
        self.assertIn("/虚构/扫描目录", 清单["目录列表"])
        self.assertEqual(len(清单["目录列表"]), 1)


class Test规范化与静态扫描(unittest.TestCase):
    """pyc 规范化纯函数与弱依赖静态扫描。"""

    def test_pyc规范化(self):
        self.assertEqual(
            规范化pyc路径("/甲/乙/__pycache__/丙.cpython-314.pyc"),
            "/甲/乙/丙.py",
        )
        self.assertEqual(
            规范化pyc路径("/甲/乙/__pycache__/丙.cpython-314-pypy.pyc"),
            "/甲/乙/丙.py",
        )
        self.assertEqual(
            规范化pyc路径("/甲/乙/普通.py"),
            "/甲/乙/普通.py",
        )

    def test_静态扫描弱依赖(self):
        源码 = (
            "import os\n"
            "if os.path.exists('配置.json'):\n"
            "    print(os.path.getsize('配置.json'))\n"
            "if 路径.is_file() and 路径.is_dir():\n"
            "    pass\n"
            "os.stat('状态文件')\n"
        )
        命中 = 静态扫描弱依赖(源码)
        self.assertIn("exists()", 命中)
        self.assertIn("getsize()", 命中)
        self.assertIn("is_file()", 命中)
        self.assertIn("is_dir()", 命中)
        self.assertIn("stat()", 命中)

    def test_静态扫描无命中时返回空(self):
        self.assertEqual(静态扫描弱依赖("x = 1 + 2"), [])


if __name__ == "__main__":
    unittest.main()
