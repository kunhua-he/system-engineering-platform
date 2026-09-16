"""LibreOffice 文档转换独立提供者：外部应用（soffice）并发安全受控调用。

只封装 LibreOffice 转换能力：doc/xls/ppt → 现代格式、任意格式 → pdf 等。

并发安全（根因：LibreOffice 桌面端按 `UserInstallation` **单实例**）：
- 同机多个 `--convert-to` 若共用默认档案，后到的调用会**静默 no-op**
  （退出码 0 但零产出，对外表现即「未产出文件」）；默认档案被占时还可能跑成
  Aqua GUI 事件循环（`--headless` 不生效）而卡死。
- 因此**每次尝试都用独立私有档案**
  `-env:UserInstallation=file://<本次尝试专属目录>`；档案根由本进程 mkdtemp
  落在系统临时目录（绝不进仓库/制品），进程退出时回收。
- 进程内用**有界并发闸门**限制同时在跑的 soffice 数（默认 4，可经
  `LIBREOFFICE_并发上限` 覆盖，1..16），超出则排队（排队上限 = 本次 超时秒，
  仍拿不到名额按 超时 如实返回）。
- 单次失败按**有限次指数退避重试**（默认 3 次）；越界、文件不存在等确定性
  失败不重试，超时不重试（不允许实际耗时超过调用方给定的 超时秒）。
- 产物先落本次尝试的**私有暂存目录**，判定「本次真产出且非空」后才发布到调用方
  目录：既不会被旧同名文件冒充成本次产物，也不会在失败时删掉调用方的既有文件。

安全约束：结构化参数列表（禁 shell=True）；独立进程组；启动/执行超时+
强制终止兜底；输出文件大小上限与输出目录隔离；临时目录/子进程/句柄全路径释放；
缺少 LibreOffice 返回 提供者不可用，不伪装成功。
"""

from __future__ import annotations

import atexit
import base64
import os
import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

from 公共契约.基础类型.结果类型 import 结果
from 公共契约.运行时 import 平台适配, 进程终止
from 公共契约.运行时.有界IO import 受限通信, 默认子进程输出上限字节

默认超时秒 = 60
默认最大输出字节 = 200 * 1024 * 1024
默认并发上限 = 4
最大并发上限 = 16
默认尝试次数 = 3
最大尝试次数 = 5
退避基数秒 = 1.0
并发上限环境变量 = "LIBREOFFICE_并发上限"
来源 = "LibreOffice提供者"

_提供者缓存: dict[str, str | None] = {}
_闸门锁 = threading.RLock()
_闸门: threading.BoundedSemaphore | None = None
_闸门容量: int | None = None
_档案根: Path | None = None


def _失败(错误码: str, 消息: str, *, 可重试: bool = False) -> 结果:
    return 结果.失败(错误码, 消息, 来源=来源, 可重试=可重试)


def 查找LibreOffice() -> str | None:
    """查找 soffice 可执行文件（缓存）。"""
    if "soffice" in _提供者缓存:
        return _提供者缓存["soffice"]
    候选列表 = [
        os.getenv("LIBREOFFICE_BIN") or os.getenv("SOFFICE_BIN"),
        "soffice", "libreoffice",
        "/Applications/LibreOffice.app/Contents/MacOS/soffice",
    ]
    路径 = next((c for c in 候选列表 if c and shutil.which(c)), None)
    _提供者缓存["soffice"] = 路径
    return 路径


def 检查提供者(超时秒: float = 30) -> 结果:
    """检查 LibreOffice 是否可用（真实独立进程探针：soffice --version）。

    探针失败（工具缺失/超时/退出码非0）→ 外部提供者不可用，
    不伪装成环境未构建。
    """
    from 支持库.适配层.系统探针 import 检查系统工具
    路径 = 查找LibreOffice()
    if not 路径:
        return _失败("外部提供者不可用", "LibreOffice 未找到（未安装或不在 PATH）")
    探针 = 检查系统工具("LibreOffice soffice", [路径], 超时秒=超时秒)
    if not 探针.成功:
        return _失败("外部提供者不可用",
                      f"LibreOffice 探针失败（{探针.错误码}）: {探针.诊断}")
    return 结果.成功结果({
        "LibreOffice": "可用",
        "版本": 探针.版本,
        "退出码": 探针.退出码,
        "标准错误摘要": 探针.标准错误摘要,
    })


def _终止进程组(进程: subprocess.Popen, 宽限秒: float = 1.0) -> None:
    """终止进程组（终止→宽限→强杀→复查）：唯一实现在 公共契约.运行时.进程终止。

    本处不再持有任何平台判断、信号号或 killpg 调用；保留同签名同名的薄委托，
    是因为既有测试与 终止回调 都以本名接入。
    """
    进程终止.强制结束子进程(进程, 宽限秒=宽限秒, 等待秒=宽限秒)


def _读取受限文本(文件路径: Path, 最大字节数: int) -> str:
    """读取文本文件但限制最大字节，超限截断并记录截断标记。"""
    大小 = 文件路径.stat().st_size
    if 大小 > 最大字节数:
        with open(文件路径, "rb") as 流:
            return 流.read(最大字节数).decode("utf-8", errors="replace") + "\n[已截断]"
    return 文件路径.read_text(encoding="utf-8", errors="replace")


# ── 并发安全构件：有界并发闸门 + 进程级私有档案根 ──────────────────

def _读取并发上限() -> int:
    """读取进程内并发转换上限（未配置 → 默认 4）。"""
    原值 = os.getenv(并发上限环境变量)
    if 原值 is None or not 原值.strip():
        return 默认并发上限
    try:
        值 = int(原值)
    except ValueError as 错误:
        raise ValueError(f"{并发上限环境变量} 必须是整数") from 错误
    if not 1 <= 值 <= 最大并发上限:
        raise ValueError(f"{并发上限环境变量} 必须在 1 到 {最大并发上限} 之间")
    return 值


def _取得闸门() -> threading.BoundedSemaphore:
    """取得进程内并发闸门；配置变化时重建（旧闸门上的在跑作业不受影响）。"""
    global _闸门, _闸门容量
    容量 = _读取并发上限()
    with _闸门锁:
        if _闸门 is None or _闸门容量 != 容量:
            _闸门 = threading.BoundedSemaphore(容量)
            _闸门容量 = 容量
        return _闸门


def _取得档案根() -> Path:
    """取得进程级私有档案根（mkdtemp，落在系统临时目录）。"""
    global _档案根
    with _闸门锁:
        if _档案根 is None or not _档案根.is_dir():
            _档案根 = Path(tempfile.mkdtemp(prefix="lo_profile_"))
        return _档案根


def _回收档案根() -> None:
    """进程退出时回收本进程的私有档案根（档案 + 暂存目录整体清理）。"""
    global _档案根
    with _闸门锁:
        根 = _档案根
        _档案根 = None
    if 根 is not None:
        shutil.rmtree(根, ignore_errors=True)


atexit.register(_回收档案根)


def _执行一次转换(soffice: str, 输入文件: Path, 目标格式: str, 目标名: str,
                暂存目录: Path, 档案目录: Path, *, 超时秒: float,
                输出上限字节: int) -> 结果:
    """单次真实转换：私有档案 + 暂存输出目录；产物留在 暂存目录。"""
    命令 = [
        soffice,
        f"-env:UserInstallation={档案目录.as_uri()}",
        "--headless", "--norestore",
        "--convert-to", 目标格式,
        "--outdir", str(暂存目录),
        str(输入文件),
    ]
    try:
        进程 = subprocess.Popen(
            命令,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            **平台适配.子进程组启动标志(),
        )
    except OSError as 错误:
        return _失败("转换失败", f"LibreOffice 调用失败: {错误}")
    try:
        标准输出, 错误输出, 已超时, 已超限 = 受限通信(
            进程, 超时秒=超时秒,
            输出上限字节=min(输出上限字节, 默认子进程输出上限字节),
            终止回调=lambda: _终止进程组(进程),
        )
    except (OSError, ValueError) as 错误:
        return _失败("转换失败", f"LibreOffice 调用失败: {错误}")
    finally:
        for 管道 in (进程.stdin, 进程.stdout, 进程.stderr):
            if 管道 is not None:
                try:
                    管道.close()
                except OSError:
                    pass
    if 已超时:
        return _失败("超时", f"LibreOffice 转换超时（> {超时秒} 秒）", 可重试=True)
    if 已超限:
        return _失败("超出限制", "LibreOffice 子进程输出超过上限")
    退出码 = 进程.returncode
    if 退出码 != 0:
        错误文本 = 错误输出.decode("utf-8", errors="replace")[-300:] if 错误输出 else ""
        return _失败("转换失败", f"LibreOffice 退出码 {退出码}: {错误文本}", 可重试=True)
    产物 = 暂存目录 / 目标名
    if not 产物.is_file():
        return _失败("转换失败", f"LibreOffice 未产出文件: {目标名}", 可重试=True)
    if 产物.stat().st_size <= 0:
        return _失败("转换失败", f"LibreOffice 未产出文件: {目标名}（文件为空）", 可重试=True)
    return 结果.成功结果({"产物": 产物})


def _发布产物(产物: Path, 目标文件: Path) -> None:
    """把暂存产物发布到调用方目录：同目录临时名 + os.replace，避免半截文件。"""
    目标文件.parent.mkdir(parents=True, exist_ok=True)
    临时名 = 目标文件.with_name(
        f".{目标文件.name}.{os.getpid()}.{threading.get_ident()}.part")
    try:
        shutil.copyfile(产物, 临时名)
        os.replace(临时名, 目标文件)
    except BaseException:
        try:
            临时名.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def 转换办公文件(输入路径: str, 目标格式: str, *, 超时秒: float = 默认超时秒,
              最大输出字节: int = 默认最大输出字节, 输出目录: str | None = None) -> 结果:
    """LibreOffice 转换：doc/xls/ppt → 目标格式；返回 文本内容或字节b64。

    并发安全：每次尝试独立私有档案（`-env:UserInstallation`）、进程内有界并发
    闸门、有限次指数退避重试；产物先落私有暂存目录、判定非空后才发布。
    拿不到产物一律如实返回 转换失败，不伪造成功。
    """
    if not isinstance(输入路径, str) or not 输入路径.strip():
        return _失败("参数不合法", "输入路径必须是非空文本")
    if not isinstance(目标格式, str) or not 目标格式.strip():
        return _失败("参数不合法", "目标格式必须是非空文本")
    soffice = 查找LibreOffice()
    if not soffice:
        return _失败("提供者不可用", "LibreOffice 未安装（提供者不可用）")
    输入文件 = Path(输入路径)
    if not 输入文件.is_file():
        return _失败("文件不存在", f"输入文件不存在: {输入路径}")
    目标格式_clean = 目标格式.lower().lstrip(".")
    if not isinstance(超时秒, (int, float)) or isinstance(超时秒, bool) or 超时秒 <= 0:
        return _失败("参数不合法", "超时秒必须是正数")
    if not isinstance(最大输出字节, int) or 最大输出字节 <= 0:
        return _失败("参数不合法", "最大输出字节必须是正整数")
    try:
        闸门 = _取得闸门()
        档案根 = _取得档案根()
    except (OSError, ValueError) as 错误:
        return _失败("提供者不可用", f"LibreOffice 并发配置不可用: {错误}")
    # 临时输出目录（隔离）
    自建目录 = 输出目录 is None
    输出根 = Path(输出目录) if 输出目录 else Path(tempfile.mkdtemp(prefix="lo_out_"))
    目标名 = f"{输入文件.stem}.{目标格式_clean}"
    目标文件 = 输出根 / 目标名
    上次失败: 结果 | None = None
    try:
        for 第几次 in range(1, 默认尝试次数 + 1):
            档案目录 = Path(tempfile.mkdtemp(prefix="lo_profile_", dir=档案根))
            暂存目录 = Path(tempfile.mkdtemp(prefix="lo_stage_", dir=档案根))
            try:
                if not 闸门.acquire(timeout=float(超时秒)):
                    return _失败(
                        "超时",
                        f"LibreOffice 并发等待超时（> {超时秒} 秒，"
                        f"进程内在跑上限 {_闸门容量}）",
                        可重试=True,
                    )
                try:
                    单次 = _执行一次转换(
                        soffice, 输入文件, 目标格式_clean, 目标名,
                        暂存目录, 档案目录,
                        超时秒=float(超时秒),
                        输出上限字节=min(最大输出字节, 默认子进程输出上限字节),
                    )
                finally:
                    闸门.release()
                # 产物判定与发布必须在暂存目录被回收之前完成
                if 单次.成功:
                    产物 = 单次.值["产物"] if isinstance(单次.值, dict) else None
                    if not isinstance(产物, Path):
                        return _失败("转换失败", "LibreOffice 内部结果缺少产物路径")
                    大小 = 产物.stat().st_size
                    if 大小 > 最大输出字节:
                        return _失败("超出限制", f"输出文件过大: {大小} 字节 > {最大输出字节}")
                    try:
                        _发布产物(产物, 目标文件)
                    except OSError as 错误:
                        return _失败("转换失败", f"LibreOffice 产物发布失败: {错误}")
                    if 目标格式_clean in ("txt", "csv", "html", "rtf", "odt", "ods", "odp", "xml"):
                        文本 = _读取受限文本(目标文件, 最大输出字节)
                        return 结果.成功结果({"文本": 文本, "格式": 目标格式_clean,
                                              "字节数": 大小, "输出路径": str(目标文件)})
                    字节 = 目标文件.read_bytes()
                    return 结果.成功结果({"字节b64": base64.b64encode(字节).decode("ascii"),
                                         "格式": 目标格式_clean, "字节数": 大小,
                                         "输出路径": str(目标文件)})
                上次失败 = 单次
            finally:
                shutil.rmtree(档案目录, ignore_errors=True)
                shutil.rmtree(暂存目录, ignore_errors=True)
            if 单次.错误码 != "转换失败" or 第几次 >= 默认尝试次数:
                return 单次
            time.sleep(退避基数秒 * (2 ** (第几次 - 1)))
        return 上次失败 or _失败("转换失败", "LibreOffice 转换失败")
    except OSError as 错误:
        return _失败("转换失败", f"LibreOffice 调用失败: {错误}")
    finally:
        if 自建目录:
            shutil.rmtree(输出根, ignore_errors=True)
