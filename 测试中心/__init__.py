"""测试中心包入口：load_tests 协议。

unittest discover 的 VALID_MODULE_NAME 只认 ASCII 标识符，无法直接
加载中文测试文件名（测试_*.py）。本包通过官方 load_tests 协议手动
加载全部测试文件，保证任务书命令可用：

    python3.14 -m unittest discover -s 测试中心 -p '测试_*.py' -v

导入失败必须失败（禁止当作跳过），资源未清理视为失败。
"""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

测试中心目录 = Path(__file__).resolve().parent
系统根目录 = 测试中心目录.parent
sys.path.insert(0, str(系统根目录))  # 无条件置顶，防同名测试目录遮蔽真实包


def 加载测试模块(文件路径: Path, 序号: int):
    """加载单个中文测试文件；失败抛出原异常（不静默跳过）。"""
    模块名 = f"系统级测试_{序号}_{文件路径.stem}"
    sys.modules.pop(模块名, None)
    规格 = importlib.util.spec_from_file_location(模块名, 文件路径)
    if 规格 is None or 规格.loader is None:
        raise ImportError(f"无法创建测试模块规格: {文件路径}")
    模块 = importlib.util.module_from_spec(规格)
    sys.modules[模块名] = 模块
    规格.loader.exec_module(模块)
    return 模块


def load_tests(loader: unittest.TestLoader, 已有测试, 模式: str):
    """加载测试中心下全部 测试_*.py 文件。"""
    套件 = unittest.TestSuite()
    文件列表 = sorted(测试中心目录.rglob("测试_*.py"))
    for 序号, 文件路径 in enumerate(文件列表):
        try:
            模块 = 加载测试模块(文件路径, 序号)
        except Exception as 错误:
            import traceback as _追踪
            print(f"!! 导入失败 {文件路径.name}: {错误}", file=sys.stderr)
            _追踪.print_exc()
            失败用例 = unittest.FunctionTestCase(
                lambda 错误=错误: (_ for _ in ()).throw(AssertionError(f"测试导入失败: {文件路径.name}: {错误}"))
            )
            套件.addTest(失败用例)
            continue
        套件.addTests(loader.loadTestsFromModule(模块))
    return 套件


if __name__ == "__main__":
    加载器 = unittest.TestLoader()
    结果 = unittest.TextTestRunner(verbosity=2).run(load_tests(加载器, None, None))
    raise SystemExit(0 if 结果.wasSuccessful() else 1)
