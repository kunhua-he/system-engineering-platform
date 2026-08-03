"""运行环境管理器：为每个第三方提供者建立独立解释器环境。

原则：
- 正式目录只保存声明（依赖锁.json），生成环境进入可删除的工程缓存：
  工程缓存/提供者运行环境/<提供者id>/<环境摘要>/
- 环境摘要至少含：Python 版本/OS/CPU 架构/第三方精确版本/外部应用版本/
  依赖锁与 wheel 摘要/提供者源码与契约摘要。
- 使用隔离模式（PYTHONNOUSERSITE=1 + venv），sys.path 不含用户级/全局第三方。
- 临时目录构建 → 完整校验 → 原子改名；损坏环境自动废弃重建。
- 依赖下载只发生在构建期（可走 127.0.0.1:4780 代理）；运行时不得临时联网。
- 启动/健康/调用/超时/取消/停止/崩溃重启/强杀/残留清理由 独立进程 统一管理，
  本管理器只负责"提供正确的解释器路径 + 环境摘要校验"。
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import venv
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

工程缓存目录名 = "工程缓存"
提供者环境根名 = "提供者运行环境"
代理地址 = "http://127.0.0.1:4780"


@dataclass
class 环境结果:
    """环境生成/校验结果。"""

    成功: bool
    解释器路径: str = ""
    环境摘要: str = ""
    错误码: str = ""
    错误说明: str = ""

    def 转字典(self) -> dict[str, Any]:
        return {
            "成功": self.成功, "解释器路径": self.解释器路径,
            "环境摘要": self.环境摘要, "错误码": self.错误码,
            "错误说明": self.错误说明,
        }


def 计算环境摘要(依赖锁: dict, 提供者id: str) -> str:
    """计算环境摘要：第三方精确版本 + 锁文件哈希 + 平台指纹。"""
    指纹 = {
        "python": sys.version.split()[0],
        "os": platform.system(),
        "os版本": platform.release(),
        "架构": platform.machine(),
        "提供者id": 提供者id,
        "依赖锁摘要": hashlib.sha256(
            json.dumps(依赖锁, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()[:16],
    }
    return hashlib.sha256(
        json.dumps(指纹, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()[:16]


def 读取依赖锁(提供者目录: Path) -> dict:
    """读取提供者目录下的 依赖锁.json。"""
    锁文件 = 提供者目录 / "依赖锁.json"
    if not 锁文件.is_file():
        return {}
    return json.loads(锁文件.read_text(encoding="utf-8"))


def 环境目录(提供者目录: Path, 摘要: str) -> Path:
    """计算环境目录：工程缓存/提供者运行环境/<提供者id>/<摘要>/。"""
    系统根 = 提供者目录.resolve()
    for _祖先 in 系统根.parents:
        if (_祖先 / "支持库").is_dir() and (_祖先 / "模块库").is_dir():
            系统根 = _祖先
            break
    return 系统根 / 工程缓存目录名 / 提供者环境根名 / 提供者目录.name / 摘要


def 确保环境(提供者目录: Path, *, 超时秒: int = 300) -> 环境结果:
    """确保提供者环境存在且有效；缺失/损坏则构建。

    依赖锁为空 → 无需独立环境（纯标准库提供者），返回系统解释器。
    """
    依赖锁 = 读取依赖锁(提供者目录)
    if not 依赖锁:
        return 环境结果(True, 解释器路径=sys.executable, 错误说明="无第三方依赖，使用系统解释器")
    # 全部为外部应用/系统工具（非 pip 包）→ 使用系统解释器，不构建 venv
    pip包表 = [包 for 包 in 依赖锁.get("包", []) if _是pip包(包)]
    if not pip包表:
        return 环境结果(True, 解释器路径=sys.executable,
                        错误说明="仅外部应用/系统工具，使用系统解释器")
    摘要 = 计算环境摘要(依赖锁, 提供者目录.name)
    目标 = 环境目录(提供者目录, 摘要)
    解释器 = 目标 / "bin" / "python3"
    校验结果 = 校验环境(解释器, 依赖锁)
    if 校验结果:
        return 环境结果(True, 解释器路径=str(解释器), 环境摘要=摘要)
    # 损坏/缺失 → 临时构建 → 原子改名
    return _构建环境(提供者目录, 依赖锁, 目标, 解释器, 摘要, 超时秒)


def 校验环境(解释器: Path, 依赖锁: dict) -> bool:
    """校验已生成环境：解释器存在 + 锁中每个 pip 包可导入。

    外部应用/系统工具（来源 非 PyPI）不做 import 校验：它们不是
    Python 包，以系统解释器运行，由提供者自身负责存在性检查。
    """
    if not 解释器.is_file():
        return False
    包表 = [包 for 包 in 依赖锁.get("包", []) if _是pip包(包)]
    if not 包表:
        return True
    检查列表 = " && ".join(
        f"{str(解释器)} -c 'import {包['模块名']}'" for 包 in 包表
    )
    try:
        结果 = subprocess.run(
            ["bash", "-c", 检查列表],
            capture_output=True, timeout=60, env={**os.environ, "PYTHONNOUSERSITE": "1"},
        )
        return 结果.returncode == 0
    except Exception:
        return False


def _是pip包(包: dict) -> bool:
    """是否为 pip 可安装的 Python 发行包（外部应用/系统工具返回 False）。"""
    来源 = str(包.get("来源", "") or "").lower()
    return "外部应用" not in 来源 and "系统工具" not in 来源 and "pip" not in 来源


def _构建环境(提供者目录: Path, 依赖锁: dict, 目标: Path,
              解释器: Path, 摘要: str, 超时秒: int) -> 环境结果:
    """临时目录构建 venv → 安装依赖 → 校验 → 原子改名。"""
    目标.parent.mkdir(parents=True, exist_ok=True)
    临时目录 = 目标.parent / f".构建中_{摘要[:8]}"
    if 临时目录.exists():
        shutil.rmtree(临时目录, ignore_errors=True)
    try:
        venv.create(临时目录, with_pip=True)
        临时解释器 = 临时目录 / "bin" / "python3"
        环境变量 = {**os.environ, "PYTHONNOUSERSITE": "1"}
        包表 = [包 for 包 in 依赖锁.get("包", []) if _是pip包(包)]
        for 包 in 包表:
            安装参数 = [
                str(临时解释器), "-m", "pip", "install", "--quiet",
                "--disable-pip-version-check",
            ]
            if 包.get("索引地址"):
                安装参数 += ["--index-url", 包["索引地址"]]
            if 包.get("代理"):
                安装参数 += ["--proxy", 包["代理"]]
            安装参数.append(f"{包['名称']}=={包['版本']}")
            结果 = subprocess.run(安装参数, capture_output=True, timeout=超时秒, env=环境变量)
            if 结果.returncode != 0:
                shutil.rmtree(临时目录, ignore_errors=True)
                return 环境结果(
                    False, 错误码="提供者不可用",
                    错误说明=f"依赖安装失败: {包['名称']}=={包['版本']}: {结果.stderr.decode('utf-8', 'ignore')[-300:]}",
                )
        # 完整校验后原子改名
        if not 校验环境(临时解释器, 依赖锁):
            shutil.rmtree(临时目录, ignore_errors=True)
            return 环境结果(False, 错误码="提供者不可用", 错误说明="环境校验失败")
        if 目标.exists():
            shutil.rmtree(目标, ignore_errors=True)
        os.replace(临时目录, 目标)
        return 环境结果(True, 解释器路径=str(解释器), 环境摘要=摘要)
    except (subprocess.TimeoutExpired, OSError) as 错误:
        shutil.rmtree(临时目录, ignore_errors=True)
        return 环境结果(False, 错误码="提供者不可用", 错误说明=f"环境构建失败: {错误}")


def 废弃环境(提供者目录: Path) -> 环境结果:
    """废弃（删除）提供者全部生成环境。"""
    依赖锁 = 读取依赖锁(提供者目录)
    摘要 = 计算环境摘要(依赖锁, 提供者目录.name) if 依赖锁 else ""
    目标 = 环境目录(提供者目录, 摘要) if 摘要 else None
    if 目标 and 目标.exists():
        shutil.rmtree(目标, ignore_errors=True)
    return 环境结果(True, 错误说明="已废弃环境")


def 环境摘要信息(提供者目录: Path) -> dict[str, Any]:
    """返回环境摘要信息（供门禁/项目锁使用）。"""
    依赖锁 = 读取依赖锁(提供者目录)
    if not 依赖锁:
        return {"独立环境": False, "依赖": []}
    摘要 = 计算环境摘要(依赖锁, 提供者目录.name)
    目标 = 环境目录(提供者目录, 摘要)
    return {
        "独立环境": True,
        "环境摘要": 摘要,
        "解释器": str(目标 / "bin" / "python3"),
        "已构建": (目标 / "bin" / "python3").is_file(),
        "依赖": 依赖锁.get("包", []),
    }
