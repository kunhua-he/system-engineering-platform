"""LibreOffice 文档转换提供者：固定、有界、可回收的 soffice 工作池。"""

from __future__ import annotations

import atexit
import base64
import hashlib
import os
import queue
import shutil
import subprocess
import tempfile
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from 公共契约.基础类型.结果类型 import 结果
from 公共契约.基础类型.逻辑类型 import 真
from 公共契约.运行时 import 平台适配, 进程终止
from 公共契约.运行时.有界IO import 受限通信

默认超时秒 = 60
默认最大输出字节 = 200 * 1024 * 1024
默认池大小 = 2
默认等待队列长度 = 100
默认排队超时秒 = 30.0
最大池大小 = 8
最大等待队列长度 = 1000
来源 = "LibreOffice提供者"

_提供者缓存: dict[str, str | None] = {}
_全局池锁 = threading.RLock()
_全局池: LibreOffice受管池 | None = None
_全局池配置: tuple[str, int, int, float] | None = None


def _失败(错误码: str, 消息: str, *, 可重试: bool = False,
        详情: dict[str, Any] | None = None) -> 结果:
    return 结果.失败(错误码, 消息, 来源=来源, 可重试=可重试, 详情=详情)


def 查找LibreOffice() -> str | None:
    """查找 soffice 可执行文件（缓存）。"""
    if "soffice" in _提供者缓存:
        return _提供者缓存["soffice"]
    候选列表 = [
        os.getenv("LIBREOFFICE_BIN") or os.getenv("SOFFICE_BIN"),
        "soffice", "libreoffice",
        "/Applications/LibreOffice.app/Contents/MacOS/soffice",
    ]
    路径 = next((候选 for 候选 in 候选列表 if 候选 and shutil.which(候选)), None)
    _提供者缓存["soffice"] = 路径
    return 路径


def 检查提供者(超时秒: float = 30) -> 结果:
    """以独立进程探针检查 LibreOffice 是否可用。"""
    from 支持库.适配层.系统探针 import 检查系统工具
    路径 = 查找LibreOffice()
    if not 路径:
        return _失败("外部提供者不可用", "LibreOffice 未找到（未安装或不在 PATH）")
    探针 = 检查系统工具("LibreOffice soffice", [路径], 超时秒=超时秒)
    if not 探针.成功:
        return _失败(
            "外部提供者不可用",
            f"LibreOffice 探针失败（{探针.错误码}）: {探针.诊断}",
        )
    return 结果.成功结果({
        "LibreOffice": "可用",
        "版本": 探针.版本,
        "退出码": 探针.退出码,
        "标准错误摘要": 探针.标准错误摘要,
    })


def _读取受限文本(文件路径: Path, 最大字节数: int) -> str:
    大小 = 文件路径.stat().st_size
    if 大小 > 最大字节数:
        with open(文件路径, "rb") as 流:
            return 流.read(最大字节数).decode("utf-8", errors="replace") + "\n[已截断]"
    return 文件路径.read_text(encoding="utf-8", errors="replace")


@dataclass
class _转换作业:
    输入文件: Path
    目标格式: str
    超时秒: float
    最大输出字节: int
    输出目录: Path | None
    开始事件: threading.Event = field(default_factory=threading.Event)
    完成事件: threading.Event = field(default_factory=threading.Event)
    取消事件: threading.Event = field(default_factory=threading.Event)
    结果值: 结果 | None = None
    进程: subprocess.Popen | None = None
    进程锁: threading.Lock = field(default_factory=threading.Lock)


@dataclass(frozen=True)
class _池成员:
    序号: int
    配置档目录: Path
    作业队列: queue.Queue
    线程: threading.Thread


class LibreOffice受管池:
    """固定成员工作池；成员独占 UserInstallation 配置档和串行队列。"""

    def __init__(self, soffice路径: str, *, 池大小: int = 默认池大小,
                 等待队列长度: int = 默认等待队列长度,
                 排队超时秒: float = 默认排队超时秒):
        if not isinstance(soffice路径, str) or not soffice路径:
            raise ValueError("soffice路径必须是非空文本")
        if not isinstance(池大小, int) or isinstance(池大小, bool) or not 1 <= 池大小 <= 最大池大小:
            raise ValueError(f"池大小必须是 1 到 {最大池大小} 的整数")
        if (not isinstance(等待队列长度, int) or isinstance(等待队列长度, bool)
                or not 1 <= 等待队列长度 <= 最大等待队列长度):
            raise ValueError(f"等待队列长度必须是 1 到 {最大等待队列长度} 的整数")
        if (not isinstance(排队超时秒, (int, float)) or isinstance(排队超时秒, bool)
                or 排队超时秒 <= 0):
            raise ValueError("排队超时秒必须是正数")
        self.soffice路径 = soffice路径
        self.池大小 = 池大小
        self.等待队列长度 = 等待队列长度
        self.排队超时秒 = float(排队超时秒)
        self._根目录 = Path(tempfile.mkdtemp(prefix="lo_受管池_"))
        self._配置档根 = self._根目录 / "配置档"
        self._作业根 = self._根目录 / "作业"
        self._配置档根.mkdir(mode=0o700)
        self._作业根.mkdir(mode=0o700)
        self._关闭锁 = threading.RLock()
        self._已关闭 = False
        self._容量 = threading.BoundedSemaphore(池大小 + 等待队列长度)
        self._活动作业锁 = threading.Lock()
        self._活动作业: dict[int, _转换作业] = {}
        self._成员列表: list[_池成员] = []
        for 序号 in range(池大小):
            配置档目录 = Path(tempfile.mkdtemp(prefix=f"成员_{序号}_", dir=self._配置档根))
            作业队列: queue.Queue = queue.Queue(maxsize=等待队列长度)
            线程 = threading.Thread(
                target=self._成员循环,
                args=(序号, 配置档目录, 作业队列),
                name=f"LibreOffice池成员-{序号}",
                daemon=True,
            )
            成员 = _池成员(序号, 配置档目录, 作业队列, 线程)
            self._成员列表.append(成员)
            线程.start()

    def _选择成员序号(self, 资源键: str) -> int:
        摘要 = hashlib.blake2b(资源键.encode("utf-8"), digest_size=8).digest()
        return int.from_bytes(摘要, "big") % self.池大小

    def _限流结果(self, 消息: str) -> 结果:
        return _失败(
            "限流", 消息, 可重试=True,
            详情={
                "限制类型": "LibreOffice受管池",
                "池大小": self.池大小,
                "等待队列长度": self.等待队列长度,
                "建议": "稍后重试",
            },
        )

    def 执行(self, 输入路径: str, 目标格式: str, *, 资源键: str,
           超时秒: float, 最大输出字节: int,
           输出目录: str | None = None) -> 结果:
        with self._关闭锁:
            if self._已关闭:
                return _失败("提供者不可用", "LibreOffice 受管池已关闭", 可重试=True)
            if not self._容量.acquire(blocking=False):
                return self._限流结果("LibreOffice 等待队列已满")
            成员 = self._成员列表[self._选择成员序号(资源键)]
            作业 = _转换作业(
                输入文件=Path(输入路径),
                目标格式=目标格式,
                超时秒=float(超时秒),
                最大输出字节=最大输出字节,
                输出目录=Path(输出目录) if 输出目录 else None,
            )
            try:
                成员.作业队列.put_nowait(作业)
            except queue.Full:
                self._容量.release()
                return self._限流结果("资源键对应的 LibreOffice 成员等待队列已满")

        if not 作业.开始事件.wait(self.排队超时秒):
            作业.取消事件.set()
            return self._限流结果("LibreOffice 排队等待超时")
        if not 作业.完成事件.wait(float(超时秒) + 3.0):
            作业.取消事件.set()
            with 作业.进程锁:
                if 作业.进程 is not None:
                    进程终止.强制结束子进程(作业.进程, 宽限秒=1.0, 等待秒=1.0)
            return _失败("超时", "LibreOffice 受管作业未在时限内回收", 可重试=True)
        return 作业.结果值 or _失败("转换失败", "LibreOffice 作业未返回结果")

    def _成员循环(self, 序号: int, 配置档目录: Path, 作业队列: queue.Queue) -> None:
        while True:
            作业 = 作业队列.get()
            if 作业 is None:
                return
            try:
                with self._关闭锁:
                    if self._已关闭 or 作业.取消事件.is_set():
                        作业.结果值 = _失败(
                            "提供者不可用" if self._已关闭 else "限流",
                            "LibreOffice 受管池已关闭" if self._已关闭
                            else "LibreOffice 排队作业已取消",
                            可重试=True,
                        )
                        continue
                    # 与关闭使用同一锁序：作业要么先登记为活动并被关闭回收，
                    # 要么看到已关闭后不再启动，禁止在关闭快照之后偷跑新进程。
                    with self._活动作业锁:
                        self._活动作业[序号] = 作业
                作业.开始事件.set()
                作业.结果值 = self._执行作业(配置档目录, 作业)
            except BaseException as 错误:
                作业.结果值 = _失败("转换失败", f"LibreOffice 工作成员异常: {错误}")
            finally:
                with self._活动作业锁:
                    self._活动作业.pop(序号, None)
                作业.完成事件.set()
                self._容量.release()

    def _执行作业(self, 配置档目录: Path, 作业: _转换作业) -> 结果:
        作业临时目录 = Path(tempfile.mkdtemp(prefix="转换_", dir=self._作业根))
        输出根 = 作业.输出目录 or (作业临时目录 / "输出")
        输出根.mkdir(parents=True, exist_ok=True)
        进程: subprocess.Popen | None = None
        try:
            命令 = [
                self.soffice路径,
                f"-env:UserInstallation={配置档目录.as_uri()}",
                "--headless", "--convert-to", 作业.目标格式,
                "--outdir", str(输出根), str(作业.输入文件),
            ]
            进程 = subprocess.Popen(
                命令,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                **平台适配.子进程组启动标志(),
            )
            with 作业.进程锁:
                作业.进程 = 进程
            try:
                _标准输出, 错误输出, 已超时, 输出超限 = 受限通信(
                    进程, 超时秒=作业.超时秒,
                    输出上限字节=作业.最大输出字节,
                    终止回调=lambda: 进程终止.强制结束子进程(进程, 宽限秒=1.0, 等待秒=1.0),
                )
            except (OSError, ValueError) as 错误:
                return _失败("转换失败", f"LibreOffice 受限通信失败: {错误}")
            if 已超时:
                return _失败(
                    "超时", f"LibreOffice 转换超时（> {作业.超时秒} 秒）",
                    可重试=True,
                )
            if 输出超限:
                return _失败(
                    "超出限制", f"LibreOffice 进程输出超过上限 {作业.最大输出字节} 字节",
                )
            if 进程.returncode != 0:
                错误文本 = 错误输出.decode("utf-8", errors="replace")[-300:] if 错误输出 else ""
                return _失败("转换失败", f"LibreOffice 退出码 {进程.returncode}: {错误文本}")
            输出文件 = 输出根 / f"{作业.输入文件.stem}.{作业.目标格式}"
            if not 输出文件.is_file():
                return _失败("转换失败", f"LibreOffice 未产出文件: {输出文件.name}")
            大小 = 输出文件.stat().st_size
            if 大小 > 作业.最大输出字节:
                return _失败("超出限制", f"输出文件过大: {大小} 字节 > {作业.最大输出字节}")
            if 作业.目标格式 in ("txt", "csv", "html", "rtf", "odt", "ods", "odp", "xml"):
                return 结果.成功结果({
                    "文本": _读取受限文本(输出文件, 作业.最大输出字节),
                    "格式": 作业.目标格式,
                    "字节数": 大小,
                    "输出路径": str(输出文件),
                })
            return 结果.成功结果({
                "字节b64": base64.b64encode(输出文件.read_bytes()).decode("ascii"),
                "格式": 作业.目标格式,
                "字节数": 大小,
                "输出路径": str(输出文件),
            })
        except OSError as 错误:
            return _失败("转换失败", f"LibreOffice 调用失败: {错误}")
        finally:
            with 作业.进程锁:
                作业.进程 = None
            if 进程 is not None:
                for 管道 in (进程.stdin, 进程.stdout, 进程.stderr):
                    if 管道 is not None:
                        try:
                            管道.close()
                        except OSError:
                            pass
            平台适配.清只读后删除树(作业临时目录, 忽略失败=真)

    def 关闭(self) -> None:
        with self._关闭锁:
            if self._已关闭:
                return
            self._已关闭 = True
            with self._活动作业锁:
                活动作业列表 = list(self._活动作业.values())
            for 作业 in 活动作业列表:
                作业.取消事件.set()
                with 作业.进程锁:
                    if 作业.进程 is not None:
                        进程终止.强制结束子进程(作业.进程, 宽限秒=1.0, 等待秒=1.0)
            for 成员 in self._成员列表:
                while True:
                    try:
                        作业 = 成员.作业队列.get_nowait()
                    except queue.Empty:
                        break
                    if 作业 is not None:
                        作业.取消事件.set()
                        作业.开始事件.set()
                        作业.结果值 = _失败(
                            "提供者不可用", "LibreOffice 受管池关闭，排队作业已回收",
                            可重试=True,
                        )
                        作业.完成事件.set()
                        self._容量.release()
                成员.作业队列.put_nowait(None)
        for 成员 in self._成员列表:
            成员.线程.join(timeout=3.0)
        平台适配.清只读后删除树(self._根目录, 忽略失败=真)


def _读取整数配置(名称: str, 默认值: int, 最大值: int) -> int:
    原值 = os.getenv(名称)
    if 原值 is None:
        return 默认值
    try:
        值 = int(原值)
    except ValueError as 错误:
        raise ValueError(f"{名称} 必须是整数") from 错误
    if not 1 <= 值 <= 最大值:
        raise ValueError(f"{名称} 必须在 1 到 {最大值} 之间")
    return 值


def _读取排队超时配置() -> float:
    原值 = os.getenv("LIBREOFFICE_QUEUE_WAIT_SECONDS")
    if 原值 is None:
        return 默认排队超时秒
    try:
        值 = float(原值)
    except ValueError as 错误:
        raise ValueError("LIBREOFFICE_QUEUE_WAIT_SECONDS 必须是数字") from 错误
    if not 0 < 值 <= 300:
        raise ValueError("LIBREOFFICE_QUEUE_WAIT_SECONDS 必须大于 0 且不超过 300")
    return 值


def _取得受管池(soffice路径: str) -> LibreOffice受管池:
    global _全局池, _全局池配置
    配置 = (
        soffice路径,
        _读取整数配置("LIBREOFFICE_POOL_SIZE", 默认池大小, 最大池大小),
        _读取整数配置("LIBREOFFICE_QUEUE_SIZE", 默认等待队列长度, 最大等待队列长度),
        _读取排队超时配置(),
    )
    with _全局池锁:
        if _全局池 is not None and _全局池配置 != 配置:
            _全局池.关闭()
            _全局池 = None
            _全局池配置 = None
        if _全局池 is None:
            _全局池 = LibreOffice受管池(
                soffice路径,
                池大小=配置[1],
                等待队列长度=配置[2],
                排队超时秒=配置[3],
            )
            _全局池配置 = 配置
        return _全局池


def 关闭受管池() -> None:
    """关闭进程工作池并清理所有服务端配置档和临时目录。"""
    global _全局池, _全局池配置
    with _全局池锁:
        池 = _全局池
        _全局池 = None
        _全局池配置 = None
    if 池 is not None:
        池.关闭()


def 转换办公文件(输入路径: str, 目标格式: str, *, 超时秒: float = 默认超时秒,
              最大输出字节: int = 默认最大输出字节,
              输出目录: str | None = None) -> 结果:
    """通过受管有界池执行转换；公开结果不包含内部 UserInstallation。"""
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
    目标格式净值 = 目标格式.lower().lstrip(".")
    if not isinstance(超时秒, (int, float)) or isinstance(超时秒, bool) or 超时秒 <= 0:
        return _失败("参数不合法", "超时秒必须是正数")
    if not isinstance(最大输出字节, int) or isinstance(最大输出字节, bool) or 最大输出字节 <= 0:
        return _失败("参数不合法", "最大输出字节必须是正整数")
    if 输出目录 is not None and (not isinstance(输出目录, str) or not 输出目录.strip()):
        return _失败("参数不合法", "输出目录必须是非空文本或空值")
    try:
        池 = _取得受管池(soffice)
    except (OSError, ValueError) as 错误:
        return _失败("提供者配置错误", f"LibreOffice 受管池配置无效: {错误}")
    if 输出目录:
        目标资源 = str((Path(输出目录).resolve() / f"{输入文件.stem}.{目标格式净值}"))
    else:
        目标资源 = str(输入文件.resolve())
    return 池.执行(
        str(输入文件), 目标格式净值,
        资源键=目标资源,
        超时秒=float(超时秒),
        最大输出字节=最大输出字节,
        输出目录=输出目录,
    )


atexit.register(关闭受管池)
