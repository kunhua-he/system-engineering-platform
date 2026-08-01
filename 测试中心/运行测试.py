"""测试中心一键运行入口（标准验收命令）。

unittest discover 的 VALID_MODULE_NAME 只认 ASCII 标识符，无法加载
中文测试文件名（测试_*.py），且默认顶层目录会与系统根同名包冲突，
因此本脚本通过 load_tests 协议直接加载全部测试。

门禁（禁止零测试成功）：
- 实际加载全部测试，测试数量为零时必须失败
- 任一测试文件导入失败时失败
- 任一测试失败时返回非零
- 连续运行结果稳定

用法：
    python3.14 测试中心/运行测试.py
    python3.14 测试中心/运行测试.py --范围 慢速
    python3.14 测试中心/运行测试.py --范围 全部
"""

from __future__ import annotations

import hashlib
import json
import re
import os
import sys
import time
import unittest
import uuid
from pathlib import Path

系统根 = Path(__file__).resolve().parents[1]
# 无条件插到最前：系统根包名（公共契约/能力契约等）与测试中心下同名测试目录
# 冲突，若依赖 in 判断可能因 cwd/脚本目录已在 sys.path 而跳过插入，
# 导致 import 公共契约 命中测试目录而非真实包（cProfile -m 实测复现）。
sys.path.insert(0, str(系统根))

import 测试中心

缓存文件路径 = 系统根 / "工程缓存" / "验证缓存.json"
缓存结构版本 = "2.0.0"  # 缓存结构版本：损坏/缺字段/引擎变化时自动失效
顶层包目录表 = {
    目录.name for 目录 in 系统根.iterdir()
    if 目录.is_dir() and 目录.name not in ("测试中心", "工程缓存", "开发文档", "示例项目", ".git", "__pycache__")
}


def _文件摘要(文件: Path) -> str:
    """文件内容摘要（sha256 前 16 位）。"""
    return hashlib.sha256(文件.read_bytes()).hexdigest()[:16]


def _目录摘要(目录: Path) -> str:
    """目录内容摘要（全部文件，排除缓存）。"""
    摘要器 = hashlib.sha256()
    for 文件 in sorted(目录.rglob("*")):
        if 文件.is_file() and "pycache" not in str(文件) and "工程缓存" not in str(文件) \
                and "完整性摘要.json" != 文件.name:
            摘要器.update(str(文件.relative_to(目录)).encode("utf-8"))
            摘要器.update(文件.read_bytes())
    return 摘要器.hexdigest()[:16]


def 收集阶段文件(匹配表: list[str]) -> list[Path]:
    """按阶段匹配表收集测试文件。"""
    文件列表: list[Path] = []
    for 匹配 in 匹配表:
        for 路径 in sorted(测试中心.测试中心目录.rglob(f"**/{匹配}")):
            if 路径.is_file() and 路径.suffix == ".py" and 路径.name.startswith("测试_"):
                文件列表.append(路径)
            elif 路径.is_dir():
                文件列表.extend(路径.rglob("测试_*.py"))
    return sorted(文件列表)


def 阶段依赖目录表(测试文件列表: list[Path]) -> set[str]:
    """解析测试文件的 import 依赖 → 受影响系统顶层包目录。"""
    依赖表: set[str] = set()
    import模式 = re.compile(r"^\s*(?:from|import)\s+([一-龥\w.]+)")
    for 文件 in 测试文件列表:
        try:
            for 行 in 文件.read_text(encoding="utf-8").splitlines():
                匹配 = import模式.match(行)
                if 匹配:
                    顶层包 = 匹配.group(1).split(".")[0].strip()
                    if 顶层包 in 顶层包目录表:
                        依赖表.add(顶层包)
        except OSError:
            continue
    return 依赖表


def 阶段摘要(测试文件列表: list[Path], 依赖目录表: set[str]) -> str:
    """阶段缓存键：测试文件摘要 + 依赖目录摘要 + 验证引擎摘要 + Python 版本。"""
    摘要器 = hashlib.sha256()
    for 文件 in 测试文件列表:
        摘要器.update(str(文件).encode("utf-8"))
        摘要器.update(_文件摘要(文件).encode("utf-8"))
    for 目录名 in sorted(依赖目录表):
        摘要器.update(目录名.encode("utf-8"))
        摘要器.update(_目录摘要(系统根 / 目录名).encode("utf-8"))
    # 验证引擎（运行测试.py 自身 + 验证器/）变化 → 全部阶段缓存失效
    摘要器.update(_文件摘要(Path(__file__)).encode("utf-8"))
    if (系统根 / "验证器").is_dir():
        摘要器.update(_目录摘要(系统根 / "验证器").encode("utf-8"))
    摘要器.update(缓存结构版本.encode("utf-8"))
    摘要器.update(sys.version.split()[0].encode("utf-8"))
    return 摘要器.hexdigest()[:16]


def 读取缓存() -> dict:
    if not 缓存文件路径.is_file():
        return {}
    try:
        return json.loads(缓存文件路径.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def 写入缓存(缓存: dict) -> None:
    缓存文件路径.parent.mkdir(parents=True, exist_ok=True)
    缓存文件路径.write_text(json.dumps(缓存, ensure_ascii=False, indent=2), encoding="utf-8")


def 判断零测试(套件: unittest.TestSuite) -> bool:
    """零测试门禁：套件没有任何测试用例时返回 True（应失败）。"""
    return 套件.countTestCases() == 0


def 判断导入失败(结果: unittest.TestResult) -> bool:
    """导入失败门禁：失败用例中存在导入失败（FunctionTestCase）时返回 True。"""
    for 失败 in 结果.failures:
        测试, 追踪 = 失败
        if type(测试).__name__ == "FunctionTestCase":
            return True
    return False


def 判断存在跳过(结果: unittest.TestResult) -> bool:
    """跳过门禁：任何未执行场景都不得计入验证成功。"""
    if not 结果.skipped:
        return False
    for 测试, 原因 in 结果.skipped:
        print(f"跳过门禁失败：{测试} 未执行，原因：{原因}")
    return True


def 审计工程缓存正式实现引用() -> list[str]:
    """正式测试不得把工程缓存中的候选代码当作生产实现。

    本文件自身包含门禁标记定义，必须排除自身（审计逻辑不属于引用）。
    """
    违规文件: list[str] = []
    标记表 = (
        "工程缓存.第十四阶段",
        '"工程缓存" / "第十四阶段"',
        "'工程缓存' / '第十四阶段'",
    )
    for 文件 in sorted(测试中心.测试中心目录.rglob("*.py")):
        if 文件.resolve() == Path(__file__).resolve():
            continue
        try:
            文本 = 文件.read_text(encoding="utf-8")
        except OSError:
            continue
        if any(标记 in 文本 for 标记 in 标记表):
            违规文件.append(str(文件.relative_to(系统根)))
    return 违规文件


def 主函数(套件: unittest.TestSuite | None = None, 范围: str = "常规") -> int:
    """按固定阶段顺序执行全部测试；前一阶段失败必须停止。"""
    加载器 = unittest.TestLoader()
    if 套件 is not None:
        # 注入套件模式（测试门禁自测用）：单套件执行
        if 判断零测试(套件):
            print("零测试门禁失败：未发现任何测试用例（测试数量为零不允许返回成功）")
            return 1
        结果 = unittest.TextTestRunner(verbosity=2).run(套件)
        if not 结果.wasSuccessful() or 判断导入失败(结果) or 判断存在跳过(结果):
            return 1
        print(f"门禁通过：共 {套件.countTestCases()} 个测试全部成功")
        return 0
    缓存实现引用 = 审计工程缓存正式实现引用()
    if 缓存实现引用:
        print("正式实现门禁失败：测试引用了工程缓存中的第十四阶段候选实现")
        for 路径 in 缓存实现引用[:20]:
            print(f"- {路径}")
        if len(缓存实现引用) > 20:
            print(f"- 其余 {len(缓存实现引用) - 20} 个文件省略")
        return 1
    # 标准验收：固定阶段顺序（静态契约→组件合规→反向破坏→项目装配→
    # 真实进程→网关→浏览器→发布门禁），前一阶段失败必须停止
    常规阶段顺序表 = [
        ("静态契约", ["测试_零测试门禁.py", "公共契约", "加载器", "支持库", "模块库"]),
        ("组件合规", ["测试_静态契约.py", "测试_组件合规.py"]),
        ("结构迁移", ["结构迁移"]),
        ("权威状态", ["权威状态"]),
        ("资源并发", ["资源并发"]),
        ("平台控制面", ["平台控制面"]),
        ("反向破坏", ["测试_反向破坏.py"]),
        ("项目装配", ["示例项目", "项目适配", "第三阶段", "第四阶段", "第十阶段", "第十一阶段"]),
        ("真实进程", ["第五阶段", "第六阶段"]),
        ("网关", ["第七阶段"]),
        ("浏览器", ["第八阶段"]),
        ("发布门禁", ["测试_门禁.py", "发布门禁"]),
    ]
    慢速阶段顺序表 = [("慢速层", ["慢速层"])]
    if 范围 == "常规":
        阶段顺序表 = 常规阶段顺序表
    elif 范围 == "慢速":
        阶段顺序表 = 慢速阶段顺序表
    elif 范围 == "全部":
        阶段顺序表 = 常规阶段顺序表 + 慢速阶段顺序表
    else:
        print(f"用法错误：未知验证范围 {范围!r}")
        return 2
    if 范围 in ("慢速", "全部"):
        # 发布门禁可能由慢速综合审计反向调用。令牌必须同时匹配直接父进程，
        # 门禁才可复用当前正在执行的慢速验证事务，避免门禁与慢速层递归。
        os.environ["系统底座_慢速验证事务"] = uuid.uuid4().hex
        os.environ["系统底座_慢速验证进程"] = str(os.getpid())
    总测试数 = 0
    阶段序号 = 0
    复用阶段数 = 0
    缓存 = 读取缓存()
    开始时间 = time.monotonic()
    for 阶段名, 匹配表 in 阶段顺序表:
        阶段序号 += 1
        阶段文件 = 收集阶段文件(匹配表)
        if not 阶段文件:
            print(f"阶段门禁失败：{阶段名} 阶段未发现任何测试文件")
            return 1
        # 增量验证：缓存键 = 测试文件 + 依赖目录摘要；无变化复用已验证证据
        依赖目录表 = 阶段依赖目录表(阶段文件)
        摘要 = 阶段摘要(阶段文件, 依赖目录表)
        缓存项 = 缓存.get(阶段名)
        if 阶段名 != "慢速层" and 缓存项 and 缓存项.get("摘要") == 摘要 and 缓存项.get("成功") \
                and 缓存项.get("测试数") and 缓存项.get("结构版本") == 缓存结构版本:
            print(f"--- 阶段：{阶段名}（缓存命中，复用 {缓存项.get('测试数')} 个测试已验证证据）---")
            总测试数 += 缓存项.get("测试数", 0)
            复用阶段数 += 1
            continue
        阶段套件 = unittest.TestSuite()
        阶段序号_当前 = 阶段序号
        for 匹配 in 匹配表:
            for 路径 in sorted(测试中心.测试中心目录.rglob(f"**/{匹配}")):
                if 路径.is_file() and 路径.suffix == ".py" and 路径.name.startswith("测试_"):
                    模块 = 测试中心.加载测试模块(路径, 阶段序号_当前)
                    if 模块 is not None:
                        阶段套件.addTests(加载器.loadTestsFromModule(模块))
                elif 路径.is_dir():
                    for 文件 in sorted(路径.rglob("测试_*.py")):
                        模块 = 测试中心.加载测试模块(文件, 阶段序号_当前)
                        if 模块 is not None:
                            阶段套件.addTests(加载器.loadTestsFromModule(模块))
        if 判断零测试(阶段套件):
            print(f"阶段门禁失败：{阶段名} 阶段未发现任何测试用例")
            return 1
        print(f"--- 阶段：{阶段名}（{阶段套件.countTestCases()} 个测试）---")
        阶段结果 = unittest.TextTestRunner(verbosity=1).run(阶段套件)
        if not 阶段结果.wasSuccessful():
            print(f"阶段门禁失败：{阶段名} 阶段存在失败，停止后续阶段")
            return 1
        if 判断导入失败(阶段结果):
            print(f"阶段门禁失败：{阶段名} 阶段存在导入失败，停止后续阶段")
            return 1
        if 判断存在跳过(阶段结果):
            print(f"阶段门禁失败：{阶段名} 阶段存在未执行场景，停止后续阶段")
            return 1
        总测试数 += 阶段套件.countTestCases()
        缓存[阶段名] = {
            "摘要": 摘要, "成功": True, "测试数": 阶段套件.countTestCases(),
            "结构版本": 缓存结构版本,
            "时间": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        写入缓存(缓存)
    总耗时 = time.monotonic() - 开始时间
    print(f"门禁通过：共 {总测试数} 个测试全部成功（复用 {复用阶段数} 个阶段缓存，总耗时 {总耗时:.2f} 秒）")
    return 0


if __name__ == "__main__":
    import argparse

    参数解析器 = argparse.ArgumentParser(description="系统工程底座唯一验证入口")
    参数解析器.add_argument("--范围", choices=("常规", "慢速", "全部"), default="常规")
    参数 = 参数解析器.parse_args()
    raise SystemExit(主函数(范围=参数.范围))
