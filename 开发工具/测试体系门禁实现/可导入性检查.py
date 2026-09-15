"""全量可导入性检查：逐文件真实导入，并顺带把用例数交给零测试检查。

对本仓 193 个 `测试_*.py`（HEAD `1c69ea5d` 实测基数）逐个在独立子进程里
`import`：`-B` 不写字节码、`-P` 不把脚本目录放进 `sys.path`、`PYTHONPATH`
清空，模块解析只认 `--根`，因此扫描的是仓库现场而不是解释器环境。
任一文件导入失败即违规。

约定：

- **不执行任何用例**：本检查只做导入与收集，所以它不是测试入口；
- 连字符等无法点号导入的文件由 `发现` 标记跳过，不进入本检查（单独报出）；
- 子进程超时、无标记输出、探针无法启动一律判为导入失败（fail-closed）。

本模块不打印、不退出。
"""
from __future__ import annotations

import concurrent.futures
import json
import os
import subprocess
import sys
from pathlib import Path

from . import 发现

探测标记 = "@@测试体系门禁探针@@"
探针路径 = Path(__file__).resolve().parent / "导入探针.py"
默认并发 = 4
默认超时秒 = 120
输出尾部长度 = 400


def 构造子进程环境() -> dict[str, str]:
    """清空 PYTHONPATH 并禁止写字节码：环境变量不得改变被测面的解析结果。"""
    环境 = {键: 值 for 键, 值 in os.environ.items() if 键 != "PYTHONPATH"}
    环境["PYTHONDONTWRITEBYTECODE"] = "1"
    return 环境


def 解析标记(标准输出: str) -> dict | None:
    """取最后一条标记行并解析；无标记行返回 None。"""
    for 行 in reversed((标准输出 or "").splitlines()):
        if 行.startswith(探测标记):
            try:
                数据 = json.loads(行[len(探测标记):])
            except json.JSONDecodeError:
                return None
            return 数据 if isinstance(数据, dict) else None
    return None


def _尾部(文本: str) -> str:
    return (文本 or "").strip()[-输出尾部长度:]


def 探测一个文件(根: Path, 资产: 发现.测试资产, *, 解释器: str, 超时秒: int,
                 环境: dict[str, str]) -> dict:
    """单文件探测：结果字段与「探针标记」JSON 对齐，并补上探针自身的失败态。"""
    结果 = {
        "相对路径": 资产.相对路径, "模块名": 资产.模块名, "导入成功": False,
        "用例数": 0, "测试类数": 0,
        "异常类型": "", "异常消息": "", "追踪摘要": "", "耗时毫秒": 0, "退出码": None,
    }
    命令 = [解释器, "-B", "-P", str(探针路径), "--根", str(根), "--文件", str(资产.文件)]
    try:
        完成 = subprocess.run(命令, capture_output=True, text=True, timeout=超时秒,
                              env=环境, cwd=str(根))
    except subprocess.TimeoutExpired:
        结果["异常类型"] = "超时"
        结果["异常消息"] = f"导入超过 {超时秒} 秒未结束（子进程已被回收）"
        return 结果
    except OSError as 错误:
        结果["异常类型"] = "探针无法启动"
        结果["异常消息"] = str(错误)[:300]
        return 结果
    结果["退出码"] = 完成.returncode
    记录 = 解析标记(完成.stdout)
    if 记录 is None:
        结果["异常类型"] = "探针无标记输出"
        结果["异常消息"] = _尾部(f"{完成.stderr}\n{完成.stdout}")
        return 结果
    for 键 in ("模块名", "用例数", "测试类数", "异常类型", "异常消息", "追踪摘要", "耗时毫秒"):
        if 键 in 记录:
            结果[键] = 记录[键]
    结果["导入成功"] = bool(记录.get("成功")) and 完成.returncode == 0
    if 结果["导入成功"]:
        结果["异常类型"] = ""
        结果["异常消息"] = ""
    elif not 结果["异常类型"]:
        结果["异常类型"] = "导入失败"
        结果["异常消息"] = f"探针退出码 {完成.returncode} 但未给出异常信息"
    return 结果


def 检查可导入性(根: Path, 资产列表: list[发现.测试资产], *, 并发: int = 默认并发,
                 超时秒: int = 默认超时秒, 解释器: str | None = None) -> list[dict]:
    """逐个真实导入；返回按相对路径排序的探测结果（跳过项不在其中）。"""
    待探测 = [资产 for 资产 in 资产列表 if not 资产.跳过原因]
    if not 待探测:
        return []
    解释器 = 解释器 or sys.executable
    环境 = 构造子进程环境()
    线程数 = max(1, min(int(并发), len(待探测)))

    def _探测(资产: 发现.测试资产) -> dict:
        return 探测一个文件(根, 资产, 解释器=解释器, 超时秒=超时秒, 环境=环境)

    with concurrent.futures.ThreadPoolExecutor(max_workers=线程数) as 线程池:
        结果 = list(线程池.map(_探测, 待探测))
    return sorted(结果, key=lambda 项: 项["相对路径"])


def 导入失败违规(探测结果: list[dict]) -> list[dict]:
    """导入失败 → 违规（僵尸测试就是这一类，`测试_psycopg提供者.py` 是现存唯一）。"""
    违规: list[dict] = []
    for 项 in 探测结果:
        if 项["导入成功"]:
            continue
        违规.append({
            "类型": "导入失败",
            "文件": 项["相对路径"],
            "行号": None,
            "细节": f"{项['异常类型']}: {项['异常消息']}",
            "追踪摘要": 项["追踪摘要"],
        })
    return 违规
