"""运行环境管理器：为每个第三方提供者建立独立解释器环境。

原则：
- 正式目录只保存声明（依赖锁.json），生成环境进入可删除的工程缓存：
  工程缓存/提供者运行环境/<提供者id>/<环境摘要>/
- 环境摘要至少含：Python 版本/OS/CPU 架构/第三方精确版本/外部应用版本/
  依赖锁与 wheel 摘要/提供者源码与契约摘要。
- 使用隔离模式（PYTHONNOUSERSITE=1 + venv），sys.path 不含用户级/全局第三方。
- 临时目录构建 → 完整校验 → 原子改名；损坏环境自动废弃重建。
- 依赖下载只发生在构建期；代理必须由受管配置显式提供，运行时不得临时联网。
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
import threading
import venv
try:
    import fcntl
except ImportError:  # Windows 使用线程锁；正式支持平台的证据写入仍需进程锁
    fcntl = None
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from 公共契约.运行时.运行缓存 import 解析运行缓存根

工程缓存目录名 = "工程缓存"
提供者环境根名 = "提供者运行环境"
缓存证据文件名 = "缓存证据.jsonl"
远程镜像配置文件名 = "远程镜像配置.json"
默认最大并行 = 8
缓存证据保留条数 = 5000

from 运行核心.运行环境管理器.远程镜像 import (
    下载镜像制品, 获取镜像清单, 计算制品摘要, 镜像不可用, 镜像下载失败,
    镜像校验请求, 远程镜像校验器, 远程镜像配置,
    读取远程镜像配置, 原子落盘,
)

# 并行构建锁：同一提供者、同一制品仓库必须串行
_锁容器锁 = threading.Lock()
_提供者锁表: dict[str, threading.Lock] = {}
_制品锁表: dict[str, threading.Lock] = {}
# 缓存证据追加写锁（多线程安全）
_证据锁 = threading.Lock()
_标准venv模块 = venv


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


def _定位系统根(提供者目录: Path) -> Path:
    """定位系统根：含 支持库+模块库 的祖先目录；无则退回提供者目录自身。"""
    系统根 = Path(提供者目录).resolve()
    for 祖先 in 系统根.parents:
        if (祖先 / "支持库").is_dir() and (祖先 / "模块库").is_dir():
            return 祖先
    return 系统根


def _运行缓存根(提供者目录: Path) -> Path:
    """提供者环境、证据和镜像配置统一使用同一个运行缓存根解析器。"""
    return 解析运行缓存根(_定位系统根(提供者目录))


def _报告阶段(进度回调: Callable[[str], None] | None, 阶段: str) -> None:
    """报告有界构建阶段；生成启动器会开启标准输出，库调用方也可传回调。"""
    if 进度回调 is not None:
        进度回调(阶段)
    elif os.environ.get("系统底座_环境阶段输出") == "1":
        print(f"[提供者环境] {阶段}", flush=True)


def 环境目录(提供者目录: Path, 摘要: str) -> Path:
    """计算环境目录：工程缓存/提供者运行环境/<提供者id>/<摘要>/。"""
    return _运行缓存根(提供者目录) / 提供者环境根名 / 提供者目录.name / 摘要


def _输入哈希(提供者目录: Path) -> str:
    """输入证据：依赖锁.json 内容哈希（文件缺失按空内容计）。"""
    锁文件 = Path(提供者目录) / "依赖锁.json"
    if not 锁文件.is_file():
        return hashlib.sha256(b"").hexdigest()[:16]
    return hashlib.sha256(锁文件.read_bytes()).hexdigest()[:16]


def _系统版本详情() -> str:
    """系统版本指纹：macOS 用 sw_vers 输出，其他平台退回 platform 信息。"""
    try:
        结果 = subprocess.run(["sw_vers"], capture_output=True, timeout=10)
        if 结果.returncode == 0:
            return 结果.stdout.decode("utf-8", "ignore").strip()
    except (OSError, subprocess.TimeoutExpired):
        pass
    return f"{platform.system()} {platform.release()}"


def _裁剪缓存证据(证据文件: Path) -> None:
    """缓存证据环形裁剪：只保留最近 缓存证据保留条数 行（尾部倒读，O(窗口)）。"""
    try:
        with open(证据文件, "rb") as 文件:
            文件.seek(0, os.SEEK_END)
            大小 = 文件.tell()
            if 大小 == 0:
                return
            块大小 = 65536
            尾部 = b""
            while 大小 > 0:
                读取长度 = min(块大小, 大小)
                大小 -= 读取长度
                文件.seek(大小)
                尾部 = 文件.read(读取长度) + 尾部
                if 尾部.count(b"\n") >= 缓存证据保留条数:
                    break
        if 尾部.count(b"\n") < 缓存证据保留条数:
            return  # 未超过保留条数，不裁剪
        行表 = 尾部.splitlines()[-缓存证据保留条数:]
        内容 = "\n".join(行.decode("utf-8", "replace") for 行 in 行表) + "\n"
        临时路径 = 证据文件.with_name(
            f"{证据文件.name}.{os.getpid()}.{threading.get_ident()}.tmp")
        临时路径.write_text(内容, encoding="utf-8")
        临时路径.replace(证据文件)
    except OSError:
        return


def _记录证据(提供者目录: Path, 类型: str, 摘要: str, 输入哈希: str,
              *, 错误码: str = "", 错误说明: str = "") -> None:
    """追加一条缓存证据到 工程缓存/提供者运行环境/缓存证据.jsonl（线程安全）。

    类型：命中（复用现有环境/系统解释器回退）、重建（真实构建）、失败（构建失败）。
    """
    记录 = {
        "时间": datetime.now().isoformat(timespec="seconds"),
        "提供者id": Path(提供者目录).name,
        "摘要": 摘要,
        "类型": 类型,
        "输入哈希": 输入哈希,
        "系统版本": _系统版本详情(),
        "错误码": 错误码,
        "错误说明": 错误说明,
    }
    with _证据锁:
        证据文件 = _运行缓存根(提供者目录) / 提供者环境根名 / 缓存证据文件名
        证据文件.parent.mkdir(parents=True, exist_ok=True)
        锁文件 = 证据文件.with_suffix(".lock")
        with 锁文件.open("a+", encoding="utf-8") as 锁句柄:
            if fcntl is not None:
                fcntl.flock(锁句柄.fileno(), fcntl.LOCK_EX)
            try:
                with 证据文件.open("a", encoding="utf-8") as 写入:
                    写入.write(json.dumps(记录, ensure_ascii=False) + "\n")
                    写入.flush()
                    os.fsync(写入.fileno())
                _裁剪缓存证据(证据文件)
            finally:
                if fcntl is not None:
                    fcntl.flock(锁句柄.fileno(), fcntl.LOCK_UN)


def _制品仓库标识(依赖锁: dict) -> str:
    """制品仓库标识：锁内各包 索引地址+代理 组合；全默认 → 默认制品仓库。"""
    标识表 = set()
    for 包 in 依赖锁.get("包", []):
        索引 = 包.get("索引地址") or "默认索引"
        代理 = 包.get("代理") or ""
        标识表.add(f"{索引}|{代理}")
    return "|".join(sorted(标识表)) or "默认制品仓库"


def _提供者锁(提供者id: str) -> threading.Lock:
    with _锁容器锁:
        return _提供者锁表.setdefault(提供者id, threading.Lock())


def _制品仓库锁(标识: str) -> threading.Lock:
    with _锁容器锁:
        return _制品锁表.setdefault(标识, threading.Lock())


def 确保环境(提供者目录: Path, *, 超时秒: int = 300,
            远程镜像: 远程镜像配置 | None = None,
            进度回调: Callable[[str], None] | None = None) -> 环境结果:
    """确保提供者环境存在且有效；缺失/损坏则构建。

    缺少依赖锁 → 视为未声明第三方依赖，返回系统解释器；显式空锁仍然
    是提供者声明错误，必须阻断。这样与装配器“无锁支持库不触发环境校验”
    的边界一致，也不会把显式空依赖声明伪装成可运行环境。
    命中/重建/失败 均追加写入 缓存证据.jsonl（可审计）。
    远程镜像：可选加速来源（默认关闭）。未启用或未传入时完全走
    现有本地缓存路径（行为零变化）；启用后本地损坏/缺失时先尝试
    镜像恢复，镜像任一失败 → 记录失败证据并明确回退本地构建。
    """
    if isinstance(超时秒, bool) or not isinstance(超时秒, int) or not 1 <= 超时秒 <= 3600:
        return 环境结果(False, 错误码="参数不合法", 错误说明="环境构建超时秒必须在 1 到 3600 之间")
    _报告阶段(进度回调, "检查缓存")
    依赖锁 = 读取依赖锁(提供者目录)
    输入哈希 = _输入哈希(提供者目录)
    提供者id = 提供者目录.name
    # 没有依赖锁表示该提供者没有声明第三方依赖；装配器会在需要时
    # 由强制校验处理“必须有锁”的正式 Provider。这里不能把普通标准库
    # 支持库误判为损坏环境。
    if not (提供者目录 / "依赖锁.json").is_file():
        _记录证据(提供者目录, "命中", "", 输入哈希)
        _报告阶段(进度回调, "环境就绪")
        return 环境结果(True, 解释器路径=sys.executable,
                         错误说明="无第三方依赖，使用系统解释器")
    if not isinstance(依赖锁, dict):
        _记录证据(提供者目录, "失败", "", 输入哈希,
                   错误码="依赖锁无效", 错误说明="依赖锁顶层必须是对象，禁止装配提供者")
        return 环境结果(False, 错误码="依赖锁无效", 错误说明="依赖锁顶层必须是对象，禁止装配提供者")
    if not 依赖锁.get("包") and not 依赖锁.get("直接依赖"):
        _记录证据(提供者目录, "失败", "", 输入哈希,
                   错误码="依赖锁为空", 错误说明="包与直接依赖均为空，禁止装配提供者")
        return 环境结果(False, 错误码="依赖锁为空", 错误说明="包与直接依赖均为空，禁止装配提供者")
    if not 依赖锁:
        _记录证据(提供者目录, "命中", "", 输入哈希)
        return 环境结果(True, 解释器路径=sys.executable, 错误说明="无第三方依赖，使用系统解释器")
    # 全部为外部应用/系统工具（非 pip 包）→ 使用系统解释器，不构建 venv
    pip包表 = [包 for 包 in 依赖锁.get("包", []) if _是pip包(包)]
    if not pip包表:
        _记录证据(提供者目录, "命中", "", 输入哈希)
        return 环境结果(True, 解释器路径=sys.executable,
                         错误说明="仅外部应用/系统工具，使用系统解释器")
    摘要 = 计算环境摘要(依赖锁, 提供者id)
    目标 = 环境目录(提供者目录, 摘要)
    解释器 = 目标 / "bin" / "python3"
    校验结果 = 校验环境(解释器, 依赖锁)
    if 校验结果:
        _记录证据(提供者目录, "命中", 摘要, 输入哈希)
        _报告阶段(进度回调, "环境就绪")
        return 环境结果(True, 解释器路径=str(解释器), 环境摘要=摘要)
    # 损坏/缺失 → 可选远程镜像恢复；镜像命中即返回，失败则明确回退本地构建
    镜像配置 = 远程镜像
    if 镜像配置 is None:
        镜像配置 = 读取远程镜像配置(_运行缓存根(提供者目录) / 远程镜像配置文件名)
    _报告阶段(进度回调, "检查远程镜像")
    镜像结果 = _尝试镜像命中(提供者目录, 依赖锁, 目标, 解释器, 摘要, 镜像配置)
    if 镜像结果 is not None:
        if 镜像结果.成功:
            return 镜像结果
        # 镜像尝试失败（证据已记录）→ 明确回退本地构建
    # 临时构建 → 原子改名
    if 进度回调 is None:
        # 保持既有私有构建器替换点的六参数调用契约。
        结果 = _构建环境(提供者目录, 依赖锁, 目标, 解释器, 摘要, 超时秒)
    else:
        结果 = _构建环境(
            提供者目录, 依赖锁, 目标, 解释器, 摘要, 超时秒, 进度回调=进度回调)
    if 结果.成功:
        _记录证据(提供者目录, "重建", 摘要, 输入哈希)
        _报告阶段(进度回调, "环境就绪")
    else:
        _记录证据(提供者目录, "失败", 摘要, 输入哈希,
                   错误码=结果.错误码, 错误说明=结果.错误说明)
        _报告阶段(进度回调, f"构建失败: {结果.错误说明}")
    return 结果


def _尝试镜像命中(提供者目录: Path, 依赖锁: dict, 目标: Path,
                 解释器: Path, 摘要: str,
                 配置: 远程镜像配置) -> 环境结果 | None:
    """远程镜像恢复环境：清单 → 校验器 → 下载 → 防篡改 → 复校验 → 原子落盘。

    返回：
    - None：镜像未启用（调用方走原有本地构建路径，零变化）。
    - 环境结果(成功=True)：镜像命中（证据类型 镜像命中）。
    - 环境结果(成功=False)：镜像尝试失败（证据类型 失败，错误码为
      镜像不可用/镜像签名无效/镜像摘要不匹配/镜像下载失败 之一），
      调用方回退本地构建。
    """
    输入哈希 = _输入哈希(提供者目录)
    if 配置 is None or not 配置.启用:
        return None
    请求 = 镜像校验请求(
        依赖锁摘要=输入哈希,
        python版本=sys.version.split()[0],
        系统版本=_系统版本详情(),
        架构=platform.machine(),
    )
    清单结果 = 获取镜像清单(配置.镜像地址, 提供者目录.name, 摘要,
                          代理地址=配置.代理地址)
    if not 清单结果.成功:
        _记录证据(提供者目录, "失败", 摘要, 输入哈希,
                   错误码=镜像不可用, 错误说明=清单结果.错误说明)
        return 环境结果(False, 错误码=镜像不可用, 错误说明=清单结果.错误说明)
    校验结果 = 远程镜像校验器(请求, 清单结果.清单, 配置.信任指纹,
                                公钥PEM=配置.公钥PEM)
    if not 校验结果.允许命中:
        _记录证据(提供者目录, "失败", 摘要, 输入哈希,
                   错误码=校验结果.错误码, 错误说明=校验结果.错误说明)
        return 环境结果(False, 错误码=校验结果.错误码, 错误说明=校验结果.错误说明)
    临时目录 = 目标.parent / f".镜像中_{摘要[:8]}"
    if 临时目录.exists():
        shutil.rmtree(临时目录, ignore_errors=True)
    下载结果 = 下载镜像制品(配置.镜像地址, 提供者目录.name, 摘要, 临时目录,
                          代理地址=配置.代理地址, 镜像清单=清单结果.清单)
    if not 下载结果.成功:
        shutil.rmtree(临时目录, ignore_errors=True)
        _记录证据(提供者目录, "失败", 摘要, 输入哈希,
                   错误码=镜像下载失败, 错误说明=下载结果.错误说明)
        return 环境结果(False, 错误码=镜像下载失败, 错误说明=下载结果.错误说明)
    # 下载后防篡改比对：制品实际摘要与镜像清单声明必须一致
    实际制品摘要 = 计算制品摘要(临时目录)
    复校验 = 远程镜像校验器(请求, 清单结果.清单, 配置.信任指纹,
                            公钥PEM=配置.公钥PEM,
                            实际制品摘要=实际制品摘要)
    if not 复校验.允许命中:
        shutil.rmtree(临时目录, ignore_errors=True)
        _记录证据(提供者目录, "失败", 摘要, 输入哈希,
                   错误码=复校验.错误码, 错误说明=复校验.错误说明)
        return 环境结果(False, 错误码=复校验.错误码, 错误说明=复校验.错误说明)
    # 本地复校验：镜像环境必须通过与本地一致的环境校验才允许落盘
    if not 校验环境(临时目录 / "bin" / "python3", 依赖锁):
        shutil.rmtree(临时目录, ignore_errors=True)
        _记录证据(提供者目录, "失败", 摘要, 输入哈希,
                   错误码=镜像下载失败, 错误说明="镜像环境复校验失败，制品不可用")
        return 环境结果(False, 错误码=镜像下载失败, 错误说明="镜像环境复校验失败，制品不可用")
    # 原子落盘：fsync 落盘 → os.replace 改名；失败不落半成品，回退本地构建
    try:
        原子落盘(临时目录, 目标)
    except OSError as 错误:
        _记录证据(提供者目录, "失败", 摘要, 输入哈希,
                   错误码=镜像下载失败, 错误说明=f"镜像落盘失败: {错误}")
        return 环境结果(False, 错误码=镜像下载失败, 错误说明=f"镜像落盘失败: {错误}")
    _记录证据(提供者目录, "镜像命中", 摘要, 输入哈希)
    return 环境结果(True, 解释器路径=str(解释器), 环境摘要=摘要,
                     错误说明="经远程镜像恢复")


def _并行确保单环境(提供者目录: Path) -> 环境结果:
    """并行任务单元：先取提供者锁（同提供者串行），再取制品仓库锁（同制品串行）。"""
    依赖锁 = 读取依赖锁(提供者目录)
    with _提供者锁(提供者目录.name):
        with _制品仓库锁(_制品仓库标识(依赖锁)):
            return 确保环境(提供者目录)


def 并行确保环境(提供者目录列表: list[Path], *, 最大并行: int = 默认最大并行) -> list[环境结果]:
    """并行确保多个提供者环境（复用 确保环境 构建逻辑）。

    - 不同提供者且不同制品仓库 → 并行构建（最多 最大并行 个并行任务）。
    - 同一提供者、同一环境目录、同一制品仓库 → 锁串行。
    - 返回结果与输入顺序一致（环境结果 列表）。
    """
    目录表 = [Path(目录) for 目录 in 提供者目录列表]
    if not 目录表:
        return []
    并行数 = max(1, int(最大并行))
    with ThreadPoolExecutor(max_workers=并行数) as 池:
        return list(池.map(_并行确保单环境, 目录表))


def 批量确保环境(提供者目录列表: list[Path], 最大并行: int = 默认最大并行) -> list[环境结果]:
    """默认批量入口（供装配/脚本调用）；串行场景可直接调用 确保环境。"""
    return 并行确保环境(提供者目录列表, 最大并行=最大并行)


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
              解释器: Path, 摘要: str, 超时秒: int,
              *, 进度回调: Callable[[str], None] | None = None) -> 环境结果:
    """按有界阶段执行：创建 venv → 安装依赖 → 校验 → 原子改名。"""
    目标.parent.mkdir(parents=True, exist_ok=True)
    临时目录 = 目标.parent / f".构建中_{摘要[:8]}"
    if 临时目录.exists():
        shutil.rmtree(临时目录, ignore_errors=True)
    当前阶段 = "创建虚拟环境"
    try:
        _报告阶段(进度回调, 当前阶段)
        环境变量 = {**os.environ, "PYTHONNOUSERSITE": "1"}
        if venv is not _标准venv模块:
            # 兼容显式注入的环境创建器；正式标准库路径始终走下方有界子进程。
            venv.create(临时目录, with_pip=True)
            创建结果 = None
        else:
            创建结果 = subprocess.run(
                [sys.executable, "-m", "venv", str(临时目录)],
                capture_output=True, timeout=超时秒, env=环境变量,
            )
        if 创建结果 is not None and 创建结果.returncode != 0:
            shutil.rmtree(临时目录, ignore_errors=True)
            详情 = 创建结果.stderr.decode("utf-8", "ignore")[-300:]
            return 环境结果(
                False, 错误码="提供者不可用",
                错误说明=f"创建虚拟环境失败（退出码 {创建结果.returncode}）: {详情}",
            )
        临时解释器 = 临时目录 / "bin" / "python3"
        包表 = [包 for 包 in 依赖锁.get("包", []) if _是pip包(包)]
        for 序号, 包 in enumerate(包表, start=1):
            当前阶段 = f"安装依赖 {序号}/{len(包表)}: {包['名称']}=={包['版本']}"
            _报告阶段(进度回调, 当前阶段)
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
                    错误说明=f"{当前阶段}失败: {结果.stderr.decode('utf-8', 'ignore')[-300:]}",
                )
        当前阶段 = "校验环境"
        _报告阶段(进度回调, 当前阶段)
        if not 校验环境(临时解释器, 依赖锁):
            shutil.rmtree(临时目录, ignore_errors=True)
            return 环境结果(False, 错误码="提供者不可用", 错误说明="校验环境失败")
        当前阶段 = "提交环境缓存"
        _报告阶段(进度回调, 当前阶段)
        if 目标.exists():
            shutil.rmtree(目标, ignore_errors=True)
        os.replace(临时目录, 目标)
        return 环境结果(True, 解释器路径=str(解释器), 环境摘要=摘要)
    except subprocess.TimeoutExpired:
        shutil.rmtree(临时目录, ignore_errors=True)
        return 环境结果(
            False, 错误码="提供者不可用",
            错误说明=f"{当前阶段}超时（阶段上限 {超时秒} 秒）",
        )
    except OSError as 错误:
        shutil.rmtree(临时目录, ignore_errors=True)
        return 环境结果(
            False, 错误码="提供者不可用", 错误说明=f"{当前阶段}失败: {错误}")


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
