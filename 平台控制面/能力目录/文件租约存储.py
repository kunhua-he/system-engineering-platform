"""文件租约存储：单 JSON 存储的原子读写与竞争互斥（唯一写入口）。

归属：文件租约是**多会话并发写同一文件**的平台级互斥，属平台治理面，落
`平台控制面.能力目录`。事实唯一落 `存储目录/文件租约.json`，与同包
`消费者契约注册表.py` 同一种做法（单 JSON 存储、按存储目录实例化，
**不建新表、不改任何既有存储结构**）。

**互斥保证（应用级唯一判定）**：认领 = 「独占区内以磁盘最新内容重读 → 判定活跃占用 →
唯一临时文件 + `os.replace` 原子替换」。三个条件缺一不可：

1. **同目录同实例**（`取实例`）：锁随实例创建，`取存储` 每次 new 一把新锁时，两个调用方
   各持一把互不相干的锁，"check-then-act" 就没有闸门——这是实测到并发双认领的病根；
2. **跨进程锁**（锁文件 `<存储目录>/.文件租约.lock` + `fcntl.flock(LOCK_EX)`）：进程内锁
   对另一个进程无效，跨进程只能靠 OS 级文件锁。锁文件被破坏（如被目录占位）时**如实报
   「锁不可用」并拒绝读写**，绝不假装拿到锁继续；
3. **锁内重读磁盘**：临界区里先 `读取()` 拿磁盘现状，再判、再写；`os.replace` 原子，读者
   永远看不到半写状态。

**写原子性**：临时文件名唯一化（`<存储文件名>.<pid>.<uuid>.临时`）并 `fsync` 后才
`os.replace`。固定临时名会让两个写者往同一个临时文件里交错写内容，再把交错结果 replace
成正式存储——实测 120/120 轮把 JSON 写坏（`Extra data: line N column 1`）。`os.replace`
失败时**重读磁盘判定**（写入其实已生效即算成功；另有他因则如实报写失败并回带磁盘实况），
不回落成笼统的「存储目录不可用」。

**残余风险（缺 DB 唯一索引）**：`平台控制面/平台状态/状态存储.py` 不在本批允许域，且该库
既有部分唯一索引 `索引_占用活跃` 是按**单列 能力id** 建的 —— 文件键写回那张表会让
「同一能力 id 只有一条活跃租约」的单列唯一语义失效，故本批不写回该表；跨进程互斥由上面
这三条应用级判定承担，不依赖数据库级唯一约束。
"""
from __future__ import annotations

import json
import os
import threading
import time
import uuid
from collections import OrderedDict
from pathlib import Path
from typing import Any

try:  # POSIX（macOS / Linux）：本平台主路径
    import fcntl
except ImportError:  # pragma: no cover - 非 POSIX 环境
    fcntl = None  # type: ignore[assignment]

存储文件名 = "文件租约.json"
锁文件名 = ".文件租约.lock"
活跃状态 = "活跃"
状态_已释放 = "已释放"
状态_已过期 = "已过期"
默认持有秒 = 300.0
最长持有秒 = 86400.0
# 跨进程锁最长等待秒：等不到即如实报「锁不可用」硬失败，绝不无锁继续（宁可失败也不双认领）。
最长等锁秒 = 120.0
等锁重试间隔秒 = 0.005
# 实例缓存上限：只淘汰「当前没被任何线程持有」的实例，淘汰一个正被持有的实例会让同一目录
# 出现两把线程锁（互斥会再次失效），所以持有中的实例一律留驻。
实例上限 = 256


def 文件键(路径: str) -> str:
    """文件租约键：`文件::<项目根相对路径>`（与 平台状态.占用租约 表 能力id 列同形）。"""
    return f"文件::{路径}"


def 时间文本(时间戳: object) -> str:
    """时间戳 → 人读文本（本地时区 `%Y-%m-%d %H:%M:%S`，平台统一口径）。"""
    try:
        return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(float(时间戳)))  # type: ignore[arg-type]
    except (TypeError, ValueError, OSError):
        return ""


def 是活跃(记录: object) -> bool:
    """记录是否活跃（非活跃 = 可被同一路径重新认领）。"""
    return isinstance(记录, dict) and 记录.get("状态") == 活跃状态


def _规范化(数据: object) -> str:
    """内容可比文本（判「磁盘上的就是本次要写的」用）；不可序列化即空串。"""
    try:
        return json.dumps(数据, ensure_ascii=False, sort_keys=True)
    except (TypeError, ValueError):
        return ""


def _清理临时文件(路径: Path) -> None:
    """尽力清掉本次临时文件（替换失败后不留垃圾）；清不掉如实放着，不吞成成功。"""
    try:
        if 路径.is_file() or 路径.is_symlink():
            路径.unlink()
    except OSError:
        pass


def _同步目录(目录: Path) -> None:
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

    def __init__(self, 存储: "文件租约存储") -> None:
        self._存储 = 存储
        self._深度 = 0

    def __enter__(self) -> "文件租约存储":
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


class 文件租约存储:
    """文件租约存储；心跳单位为秒（浮点），键为 `文件::<路径>`。

    实例一律经 `取实例` 取（同目录同实例，见模块头注释第 1 条）。
    """

    实例表: "OrderedDict[str, 文件租约存储]" = OrderedDict()
    类型锁 = threading.Lock()

    def __init__(self, 存储目录: Path | str) -> None:
        self.存储目录 = Path(存储目录)
        self.存储文件 = self.存储目录 / 存储文件名
        self.锁文件 = self.存储目录 / 锁文件名
        self.线程锁 = threading.RLock()
        self.本地 = threading.local()
        self.持有中 = 0
        self._锁句柄 = -1

    # ── 实例获取（同目录同实例） ──────────────────────────────
    @classmethod
    def 取实例(cls, 存储目录: Path | str) -> "文件租约存储":
        """按存储目录取**同一实例**（类级缓存，按真实路径归一）。

        每次 new 实例 = 每次 new 一把线程锁 = 互斥闸门不存在（并发双认领实测病根），
        故实例必须按目录复用；`fcntl.flock` 作为跨实例/跨进程的第二道防线另算。
        """
        目录 = Path(存储目录).expanduser()
        try:
            键 = os.path.realpath(str(目录))
        except OSError:  # 极端环境（路径不可解析）下退化为绝对路径文本，仍保证同串同实例
            键 = os.path.abspath(str(目录))
        with cls.类型锁:
            已有 = cls.实例表.get(键)
            if 已有 is not None:
                cls.实例表.move_to_end(键)
                return 已有
            新实例 = cls(目录)
            cls.实例表[键] = 新实例
            while len(cls.实例表) > 实例上限:
                可淘汰 = next((k for k, v in cls.实例表.items()
                             if k != 键 and v.持有中 == 0), "")
                if not 可淘汰:
                    break
                del cls.实例表[可淘汰]
            return 新实例

    # ── 跨进程锁 ──────────────────────────────────────────────
    def 加跨进程锁(self) -> None:
        """锁文件 + `flock(LOCK_EX)`；失败或超时一律记线程本地「锁问题」，绝不静默放行。"""
        self.本地.锁问题 = ""
        try:
            self.存储目录.mkdir(parents=True, exist_ok=True)
        except OSError as 错误:
            self.本地.锁问题 = f"文件租约存储跨进程锁不可用（存储目录建不出来）: {错误}"
            return
        句柄 = -1
        try:
            句柄 = os.open(str(self.锁文件), os.O_RDWR | os.O_CREAT, 0o644)
        except OSError as 错误:
            self.本地.锁问题 = f"文件租约存储跨进程锁不可用（锁文件打不开）: {错误}"
            return
        if fcntl is None:  # pragma: no cover - 非 POSIX 环境
            try:
                os.close(句柄)
            except OSError:
                pass
            self.本地.锁问题 = (
                "文件租约存储跨进程锁不可用（当前平台无 fcntl，拒绝无锁读写）")
            return
        操作 = fcntl.LOCK_EX | fcntl.LOCK_NB
        截止 = time.time() + 最长等锁秒
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
                        f"文件租约存储跨进程锁申请失败（等待 {最长等锁秒} 秒仍未拿到，"
                        f"拒绝无锁读写）: {错误}")
                    return
                time.sleep(等锁重试间隔秒)
        self._锁句柄 = 句柄
        with 文件租约存储.类型锁:
            self.持有中 += 1

    def 解跨进程锁(self) -> None:
        """释放跨进程锁并清掉本次「锁问题」（下一次读写重新判定，不残留旧结论）。"""
        with 文件租约存储.类型锁:
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

    # ── 存储基础 ──────────────────────────────────────────────
    def 读取(self) -> tuple[dict, str]:
        """读取存储；文件缺失视为空库；**损坏即报错**（不按空库继续，避免静默丢租约）。

        本方法在 `独占()` 内调用即等于「锁内以磁盘最新内容重读」。锁没拿到（锁文件被破坏、
        等锁超时）时一律如实报「锁不可用」，不假装读到空库、也不继续判占用。
        """
        锁问题 = str(getattr(self.本地, "锁问题", "") or "")
        if 锁问题:
            return {}, 锁问题
        if not self.存储文件.is_file():
            return {}, ""
        try:
            正文 = self.存储文件.read_text(encoding="utf-8")
        except OSError as 错误:
            return {}, f"文件租约存储不可读: {错误}"
        except UnicodeDecodeError as 错误:
            return {}, f"文件租约存储编码损坏: {错误}"
        try:
            数据 = json.loads(正文)
        except json.JSONDecodeError as 错误:
            return {}, f"文件租约存储损坏（拒绝按空库继续）: {错误}"
        return (数据 if isinstance(数据, dict) else {}), ""

    def 临时文件名(self) -> Path:
        """本次写入的临时文件路径：`.<存储文件名>.tmp-<pid>-<uuid8>`（每次都唯一）。

        固定临时名是并发写坏存储的第二个病根：两个写者写同一个临时文件，交错内容经
        `os.replace` 成为正式存储。唯一化后各写各的临时文件，`os.replace` 只做原子换名。
        命名口径与同包 `消费者契约注册表._原子写入文本` 一致（同仓单一口径，不另立一套）。
        """
        return self.存储文件.parent / (
            f".{self.存储文件.name}.tmp-{os.getpid()}-{uuid.uuid4().hex[:8]}")

    def 写入(self, 数据: dict) -> str:
        """临时文件（唯一名、fsync）+ `os.replace` 原子替换；返回问题说明（成功为空串）。

        `os.replace` 失败时**重读磁盘判定**：磁盘上已是本次要写的内容 → 视为写入生效；
        磁盘另有实况 → 如实报「原子替换失败」并回带磁盘实况。不回落成笼统的
        「存储目录不可用」，也不静默成功。
        """
        锁问题 = str(getattr(self.本地, "锁问题", "") or "")
        if 锁问题:
            return 锁问题
        正文 = json.dumps(数据, ensure_ascii=False, indent=2, sort_keys=True)
        临时文件 = self.临时文件名()
        try:
            self.存储文件.parent.mkdir(parents=True, exist_ok=True)
            with open(临时文件, "w", encoding="utf-8") as 文件流:
                文件流.write(正文)
                文件流.flush()
                os.fsync(文件流.fileno())
            os.replace(临时文件, self.存储文件)
            _同步目录(self.存储文件.parent)
        except OSError as 错误:
            _清理临时文件(临时文件)
            现有, 读问题 = self.读取()
            if 读问题:
                return f"文件租约存储原子替换失败（重读磁盘判定：{读问题}）: {错误}"
            if _规范化(现有) == _规范化(数据):
                return ""
            return (f"文件租约存储原子替换失败（已重读磁盘判定：磁盘内容与本次写入不一致，"
                    f"磁盘实有 {len(现有)} 条记录）: {错误}")
        return ""

    @staticmethod
    def 按租约id找键(存储: dict, 租约id: str) -> str:
        for 键, 记录 in 存储.items():
            if isinstance(记录, dict) and str(记录.get("租约id") or "") == 租约id:
                return 键
        return ""

    @staticmethod
    def 新租约(路径: str, 所有者: str, 任务: str, 持有秒: float,
               存储标签: str, 现在: float | None = None) -> dict:
        """构造一条活跃租约记录（字段与 平台状态.占用租约 表列族同名同义）。"""
        时刻 = time.time() if 现在 is None else 现在
        return {
            "租约id": uuid.uuid4().hex[:16], "键": 文件键(路径), "路径": 路径,
            "所有者": 所有者, "任务": 任务, "存储标签": 存储标签,
            "心跳": 时刻, "申请时间": 时间文本(时刻),
            "过期时间": 时刻 + 持有秒, "状态": 活跃状态,
            "释放时间": "", "释放原因": "",
        }

    @staticmethod
    def 对外记录(记录: dict) -> dict:
        """对外读数：浮点心跳照给，另附人读时间字段（不改变内部字段名）。"""
        对外 = dict(记录)
        对外["心跳时间"] = 时间文本(记录.get("心跳"))
        对外["过期时间读数"] = 时间文本(记录.get("过期时间"))
        return 对外
