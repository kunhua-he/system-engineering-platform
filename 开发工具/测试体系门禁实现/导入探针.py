"""导入探针：在独立子进程内真实导入一个测试文件并统计用例数。

「全量可导入性」是本测试体系里唯一能自动发现僵尸测试的检查（见
`开发文档/临时文档/20260915_底座专业审计/落点清单_02_测试体系.md` 问题 1 的 A3）。
探针按文件逐个启动全新解释器，因此：

- 导入副作用、`sys.modules` 污染、崩溃与 `SystemExit` 都不会影响门禁主进程；
- 一个文件的导入失败不会掩盖其它文件；
- 用例数由官方 `TestLoader.loadTestsFromModule` 收集，与 `AGENTS.md:135`
  「门禁：实际加载全部测试；零测试必须失败」同一口径。

入参（只由 `可导入性检查` 逐文件调用，不供日常手工使用）：

    python3.14 -B -P 开发工具/测试体系门禁实现/导入探针.py --根 <仓库根> --文件 <测试文件.py>

`-P` 让解释器不把脚本目录放进 `sys.path`，探针的兄弟模块因此不会遮蔽被测
模块的同名导入；`sys.path` 只由 `--根` 决定。

输出：标准输出**最后一行**为标记行，形如
    @@测试体系门禁探针@@{"成功": true, "用例数": 12, "测试类数": 1, ...}

退出码：0 导入并收集成功；1 导入或收集失败；2 入参错误（文件不在根之内）。
"""
from __future__ import annotations

import argparse
import importlib
import json
import sys
import time
import traceback
import unittest
from pathlib import Path

标记 = "@@测试体系门禁探针@@"


def 解析参数(参数: list[str] | None = None) -> argparse.Namespace:
    解析器 = argparse.ArgumentParser(
        prog="导入探针.py",
        description="测试体系门禁·导入探针：单文件真实导入与用例计数（不执行用例）",
    )
    解析器.add_argument("--根", default="", help="仓库根目录（默认：本探针上三级）")
    解析器.add_argument("--文件", required=True, help="待导入的测试文件路径")
    return 解析器.parse_args(参数)


def 计算模块名(根: Path, 文件: Path) -> str:
    """点号模块名；文件不在根之内时抛 ValueError（由调用方判为入参错误）。"""
    相对 = 文件.resolve().relative_to(根.resolve())
    return ".".join(相对.with_suffix("").parts)


def 统计测试类(模块: object) -> int:
    """模块内 TestCase 子类数量（含导入进来的，仅作诊断参考）。"""
    数量 = 0
    for 名字 in dir(模块):
        对象 = getattr(模块, 名字, None)
        if isinstance(对象, type) and issubclass(对象, unittest.TestCase) and 对象 is not unittest.TestCase:
            数量 += 1
    return 数量


def 异常追踪(错误: BaseException) -> str:
    """异常追踪尾部：保留最后 800 字符，用于门禁报告定位。"""
    return "".join(traceback.format_exception(type(错误), 错误, 错误.__traceback__))[-800:]


def 探测(根: Path, 文件: Path) -> dict:
    """真实导入 文件 并收集用例数；任何异常都转成结果字段，不向上抛。"""
    记录 = {
        "模块名": "", "文件": str(文件), "成功": False,
        "用例数": 0, "测试类数": 0,
        "异常类型": "", "异常消息": "", "追踪摘要": "", "耗时毫秒": 0,
    }
    try:
        记录["模块名"] = 计算模块名(根, 文件)
    except ValueError:
        记录["异常类型"] = "入参错误"
        记录["异常消息"] = f"{文件} 不在根目录 {根} 之内"
        return 记录
    if str(根) not in sys.path:
        sys.path.insert(0, str(根))
    开始 = time.perf_counter()
    try:
        模块 = importlib.import_module(记录["模块名"])  # 依赖门禁豁免：子进程探针按绝对路径加载测试模块
        套件 = unittest.TestLoader().loadTestsFromModule(模块)
        记录["用例数"] = 套件.countTestCases()
        记录["测试类数"] = 统计测试类(模块)
        记录["成功"] = True
    except BaseException as 错误:  # SystemExit/段错误外的异常一律计入失败，fail-closed
        记录["异常类型"] = type(错误).__name__
        记录["异常消息"] = (str(错误).splitlines() or [""])[0][:300]
        记录["追踪摘要"] = 异常追踪(错误)
    记录["耗时毫秒"] = int((time.perf_counter() - 开始) * 1000)
    return 记录


def 主程序(参数: list[str] | None = None) -> int:
    解析 = 解析参数(参数)
    根 = Path(解析.根).resolve() if 解析.根 else Path(__file__).resolve().parents[2]
    文件 = Path(解析.文件).resolve()
    记录 = 探测(根, 文件)
    print(标记 + json.dumps(记录, ensure_ascii=False))
    if 记录["异常类型"] == "入参错误":
        return 2
    return 0 if 记录["成功"] else 1


if __name__ == "__main__":
    raise SystemExit(主程序())
