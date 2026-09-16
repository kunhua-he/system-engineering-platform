"""单文件互斥存储：单 JSON 存储的实例缓存 + 线程/跨进程互斥 + 原子替换（本包唯一并发底座）。

归属与分工：`平台控制面/能力目录` 下有两条「单 JSON 存储 + 读→判→写」的事实存储
（`文件租约存储.py` 的 `存储目录/文件租约.json`、`消费者契约注册表.py` 的
`存储目录/消费者契约.json`）。**并发机制只留这一份**：实例缓存、线程锁、跨进程 flock、
锁内重读磁盘、唯一临时名 + fsync + `os.replace` 全落本模块；子类只管自己的数据语义
（读出来怎么判、写完落什么字段），不另立第二套锁。

三条保证（口径与 `文件租约存储` 那次并发收口逐字一致，子类一律照此用）：

1. **同目录同实例**（`取实例`）：锁随实例创建，调用方每次 `new` 一把新锁时，两个调用方
   各持一把互不相干的锁，「读 → 判 → 写」就没有闸门——这是实测到并发双认领与并发
   丢更新的共同病根；实例缓存键 = (子类, 真实路径)，两个子类互不串实例；
2. **跨进程锁**（`<存储目录>/<锁文件名>` + `fcntl.flock(LOCK_EX)`）：进程内锁对另一个
   进程无效，跨进程只能靠 OS 级文件锁；等锁上限 `最长等锁秒`，等不到即记线程本地
   「锁问题」**拒绝读写**，绝不假装拿到锁继续；
3. **锁内重读磁盘**：`with 存储.独占():` 里先 `读取()` 拿磁盘现状再判再写；写侧
   `os.replace` 原子，读者永远看不到半写状态。

写侧原子性：临时文件名唯一化（`.<存储文件名>.tmp-<pid>-<uuid8>`）并 `fsync` 后才
`os.replace`。固定临时名会让两个写者往同一个临时文件里交错写内容，再把交错结果
replace 成正式存储——实测 120/120 轮把 JSON 写坏（`Extra data: line N column 1`）。

残余风险（缺 DB 唯一索引）：跨进程互斥由上面三条应用级判定承担，不依赖数据库级
唯一约束；`平台控制面/平台状态/状态存储.py` 的既有唯一索引不表达本包的文件键语义。
"""
from __future__ import annotations

import os
import threading
import time
import uuid
from collections import OrderedDict
from pathlib import Path
from typing import Any, Self

try:  # POSIX（macOS / Linux）：本平台主路径
    import fcntl
except ImportError:  # pragma: no cover - 非 POSIX 环境
    fcntl = None  # type: ignore[assignment]

# 跨进程锁最长等待秒：等不到即如实报「锁不可用」硬失败，绝不无锁继续（宁可失败也不双写/丢更新）。
最长等锁秒 = 120.0
等锁重试间隔秒 = 0.005
# 实例缓存上限：只淘汰「当前没被任何线程持有」的实例，淘汰一个正被持有的实例会让同一目录
# 出现两把线程锁（互斥会再次失效），所以持有中的实例一律留驻。
实例上限 = 256


def 清理临时文件(路径: Path) -> None:
    """尽力清掉本次临时文件（替换失败后不留垃圾）；清不掉如实放着，不吞成成功。"""
    try:
        if 路径.is_file() or 路径.is_symlink():
            路径.unlink()
    except OSError:
        pass


def 同步目录(目录: Path) -> None:
    """目录项 fsync（best-effort）：保证 replace 后的目录项也能落到磁盘。"""
    句柄 = -1
    try:
        句柄 = os.open(str(目录), os.O_RDONLY)
        os.fsync(句柄)
    except OSError:
        pass
    finally:
        if 句柄 >= 0:
            try:
                os.close(句柄)
            except OSError:
                pass


class _独占区:
    """`独占()` 的上下文：先线程锁（同线程可重入），最外层临界区再叠加跨进程 flock。

    深度只在最外层 0→1 加 flock、1→0 解 flock：同线程重入若重复加 flock，同一进程内
    两个不同 fd 的 `flock(LOCK_EX)` 会互相阻塞，等于自己把自己锁死。
    """

    __slots__ = ("_存储", "_深度")

    def __init__(self, 存储: "单文件互斥存储") -> None:
        self._存储 = 存储
        self._深度 = 0

    def __enter__(self) -> "单文件互斥存储":
        存储 = self._存储
        存储.线程锁.acquire()
        self._深度 = int(getattr(存储.本地, "深度", 0))
        if self._深度 == 0:
            存储.加跨进程锁()
        存储.本地.深度 = self._深度 + 1
        return 存储

    def __exit__(self, *异常: Any) -> bool:
        存储 = self._存储
        存储.本地.深度 = self._深度
        if self._深度 == 0:
            存储.解跨进程锁()
        存储.线程锁.release()
        return False


class 单文件互斥存储:
    """单 JSON 文件存储的并发底座；子类给「存储标签 / 存储文件名 / 锁文件名」即可。

    实例一律经 `取实例` 取（同目录同实例，见模块头注释第 1 条）；子类自己的对外语义
    （读取怎么判、写入写什么）仍留在子类里，本基座只管互斥与落盘原子性。
    """

    存储标签 = "单文件互斥存储"
    存储文件名 = "存储.json"
    锁文件名 = ".存储.lock"
    最长等锁秒 = 最长等锁秒
    等锁重试间隔秒 = 等锁重试间隔秒
    实例上限 = 实例上限

    # 实例表键 = (子类, 真实路径)：两个子类操作同一目录时各取各的实例，互不串（串实例
    # 会让一个存储读到另一个的存储文件，属事实错乱）。
    实例表: OrderedDict[tuple[type, str], Self] = OrderedDict()
    类型锁 = threading.Lock()

    def __init__(self, 存储目录: Path | str) -> None:
        self.存储目录 = Path(存储目录)
        self.存储文件 = self.存储目录 / self.存储文件名
        self.锁文件 = self.存储目录 / self.锁文件名
        self.线程锁 = threading.RLock()
        self.本地 = threading.local()
        self.持有中 = 0
        self._锁句柄 = -1

    # ── 实例获取（同目录同实例） ──────────────────────────────
    @classmethod
    def 取实例(cls, 存储目录: Path | str) -> Self:
        """按存储目录取**同一实例**（类级缓存，按真实路径归一，按子类分表）。

        每次 new 实例 = 每次 new 一把线程锁 = 互斥闸门不存在（并发双写实测病根），
        故实例必须按目录复用；`fcntl.flock` 作为跨实例/跨进程的第二道防线另算。
        """
        目录 = Path(存储目录).expanduser()
        try:
            键 = os.path.realpath(str(目录))
        except OSError:  # 极端环境（路径不可解析）下退化为绝对路径文本，仍保证同串同实例
            键 = os.path.abspath(str(目录))
        复合键 = (cls, 键)
        with cls.类型锁:
            已有 = cls.实例表.get(复合键)
            if 已有 is not None:
                cls.实例表.move_to_end(复合键)
                return 已有
            新实例 = cls(目录)
            cls.实例表[复合键] = 新实例
            while len(cls.实例表) > cls.实例上限:
                可淘汰 = next((k for k, v in cls.实例表.items()
                             if k != 复合键 and v.持有中 == 0), None)
                if 可淘汰 is None:
                    break
                del cls.实例表[可淘汰]
            return 新实例

    # ── 跨进程锁 ──────────────────────────────────────────────
    def 锁问题(self) -> str:
        """本线程本次临界区的「锁问题」原文（没进过独占区即空串）。"""
        return str(getattr(self.本地, "锁问题", "") or "")

    def 加跨进程锁(self) -> None:
        """锁文件 + `flock(LOCK_EX)`；失败或超时一律记线程本地「锁问题」，绝不静默放行。"""
        标签 = self.存储标签
        self.本地.锁问题 = ""
        try:
            self.存储目录.mkdir(parents=True, exist_ok=True)
        except OSError as 错误:
            self.本地.锁问题 = f"{标签}跨进程锁不可用（存储目录建不出来）: {错误}"
            return
        句柄 = -1
        try:
            句柄 = os.open(str(self.锁文件), os.O_RDWR | os.O_CREAT, 0o644)
        except OSError as 错误:
            self.本地.锁问题 = f"{标签}跨进程锁不可用（锁文件打不开）: {错误}"
            return
        if fcntl is None:  # pragma: no cover - 非 POSIX 环境
            try:
                os.close(句柄)
            except OSError:
                pass
            self.本地.锁问题 = f"{标签}跨进程锁不可用（当前平台无 fcntl，拒绝无锁读写）"
            return
        操作 = fcntl.LOCK_EX | fcntl.LOCK_NB
        截止 = time.time() + self.最长等锁秒
        while True:
            try:
                fcntl.flock(句柄, 操作)
                break
            except OSError as 错误:
                if time.time() >= 截止:
                    try:
                        os.close(句柄)
                    except OSError:
                        pass
                    self.本地.锁问题 = (
                        f"{标签}跨进程锁申请失败（等待 {self.最长等锁秒} 秒仍未拿到，"
                        f"拒绝无锁读写）: {错误}")
                    return
                time.sleep(self.等锁重试间隔秒)
        self._锁句柄 = 句柄
        with type(self).类型锁:
            self.持有中 += 1

    def 解跨进程锁(self) -> None:
        """释放跨进程锁并清掉本次「锁问题」（下一次读写重新判定，不残留旧结论）。"""
        with type(self).类型锁:
            self.持有中 = max(0, self.持有中 - 1)
        句柄, self._锁句柄 = self._锁句柄, -1
        if 句柄 >= 0 and fcntl is not None:
            try:
                fcntl.flock(句柄, fcntl.LOCK_UN)
            except OSError:
                pass
        if 句柄 >= 0:
            try:
                os.close(句柄)
            except OSError:
                pass
        self.本地.锁问题 = ""

    def 独占(self):
        """独占区上下文（`with 存储.独占():`）：线程锁 + 跨进程 flock，锁内一律重读磁盘。"""
        return _独占区(self)

    # ── 落盘基础 ──────────────────────────────────────────────
    def 临时文件名(self) -> Path:
        """本次写入的临时文件路径：`.<存储文件名>.tmp-<pid>-<uuid8>`（每次都唯一）。

        固定临时名是并发写坏存储的第二个病根：两个写者写同一个临时文件，交错内容经
        `os.replace` 成为正式存储。唯一化后各写各的临时文件，`os.replace` 只做原子换名。
        """
        return self.存储文件.parent / (
            f".{self.存储文件.name}.tmp-{os.getpid()}-{uuid.uuid4().hex[:8]}")

    def 原子写文本(self, 正文: str, 权限: int = 0o600) -> None:
        """唯一临时名 + fsync + `os.replace` 原子替换；失败一律抛 `OSError` 交给调用方判定。

        锁不可用（`锁问题` 非空）时**拒绝落盘**：无锁写入正是丢更新的入口，宁可失败。
        """
        锁问题 = self.锁问题()
        if 锁问题:
            raise OSError(锁问题)
        临时 = self.临时文件名()
        描述符 = -1
        try:
            self.存储文件.parent.mkdir(parents=True, exist_ok=True)
            描述符 = os.open(临时, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 权限)
            视图 = memoryview(正文.encode("utf-8"))
            while 视图:
                已写 = os.write(描述符, 视图)
                视图 = 视图[已写:]
            os.fsync(描述符)
            os.close(描述符)
            描述符 = -1
            os.replace(临时, self.存储文件)
        except BaseException:
            # 写入或替换失败：清掉临时文件，既有存储在别处，逐字节不受影响
            if 描述符 >= 0:
                try:
                    os.close(描述符)
                except OSError:
                    pass
            清理临时文件(临时)
            raise
        同步目录(self.存储文件.parent)


__all__ = [
    "单文件互斥存储", "清理临时文件", "同步目录",
    "最长等锁秒", "等锁重试间隔秒", "实例上限",
]
