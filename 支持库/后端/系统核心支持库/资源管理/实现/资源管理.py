"""资源管理支持库：原子资源操作（快照/写入/替换/交换/锁/释放）。

原子能力：创建内容摘要/创建不可变快照/创建唯一运行目录/原子写入/
原子替换/比较并交换/资源级跨进程短锁/安全释放资源。
全部使用标准库，无第三方依赖；文件操作均为原子（临时文件+rename）。

口径边界（什么原子、什么不原子，如实写明）：
- 「rename 原子」只保证单个写者不半写；**读-比-写 不是原子的**，
  所以 原子替换/比较并交换 走本模块的 资源短锁 串行化（锁内重读→比较→写回）。
- 资源短锁是 mkdir 原子的跨进程互斥；持有进程崩溃会留下锁目录，
  故锁内记录 进程号/主机/创建时间戳，等锁时按「持有者是否存活 → TTL」判定并回收残留。
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import socket
import tempfile
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable
from 公共契约.基础类型.结果类型 import 结果
from 公共契约.运行时.进程终止 import 进程存活

# 错误码唯一源 = `公共契约/错误结构/错误结构.py`（B-9 收口，哲学第 5 条：结果唯一即收口）：
# 与平台同义的码一律**导入**，本包不再复制字面量（复制点会与唯一源分叉、且让「改一处」失效）。
from 公共契约.错误结构 import (
    错误码_参数不合法,
    错误码_内部错误,
    错误码_版本冲突,
    错误码_超时,
)

# 本包自有码（不在平台规范集内）：仍各自持有，不与唯一源合并。
错误码_资源不存在 = "资源不存在"
错误码_资源被占用 = "资源被占用"
错误码_重复回滚 = "重复回滚"
_受管状态服务 = None


def 设置受管状态服务(服务) -> None:
    """由运行核心装配唯一资源句柄服务；支持库不反向依赖运行核心实现。"""
    global _受管状态服务
    _受管状态服务 = 服务


def _状态服务():
    if _受管状态服务 is None:
        raise RuntimeError("受管状态服务未装配")
    return _受管状态服务


def _执行受管状态(函数) -> 结果:
    try:
        return 结果.成功结果(函数(_状态服务()))
    except KeyError as 错误:
        return 结果.失败("句柄无效", str(错误), 来源="资源管理")
    except PermissionError as 错误:
        return 结果.失败("句柄已过期", str(错误), 来源="资源管理")
    except ValueError as 错误:
        return 结果.失败("参数不合法", str(错误), 来源="资源管理")
    except RuntimeError as 错误:
        错误码 = "版本冲突" if "版本" in str(错误) or "提交" in str(错误) else "资源操作失败"
        return 结果.失败(错误码, str(错误), 来源="资源管理")


def 创建受管状态(资源id: str, 初始状态: dict, 项目id: str = "", 用户id: str = "") -> 结果:
    return _执行受管状态(lambda 服务: 服务.创建受管状态(
        资源id=资源id, 初始状态=初始状态, 项目id=项目id, 所有者=用户id))


def 读取受管状态(句柄: int, 项目id: str = "", 用户id: str = "") -> 结果:
    return _执行受管状态(lambda 服务: 服务.读取受管状态(
        句柄, 项目id=项目id, 所有者=用户id))


def 更新受管状态(句柄: int, 新状态: dict, 期望版本: str = "",
             项目id: str = "", 用户id: str = "") -> 结果:
    return _执行受管状态(lambda 服务: 服务.更新受管状态(
        句柄, 新状态, 期望版本=期望版本, 项目id=项目id, 所有者=用户id)
    )


def 释放受管状态(句柄: int, 项目id: str = "", 用户id: str = "") -> 结果:
    return _执行受管状态(lambda 服务: 服务.释放受管状态(
        句柄, 项目id=项目id, 所有者=用户id))


def 创建内容摘要(文件路径: Path, 算法: str = "sha256") -> str:
    """创建内容摘要（分块读取，不加载全文件入内存）。"""
    文件路径 = Path(文件路径)
    if not 文件路径.is_file():
        raise FileNotFoundError(f"文件不存在: {文件路径}")
    摘要器 = hashlib.new(算法)
    with open(文件路径, "rb") as 输入:
        while 块 := 输入.read(1024 * 1024):
            摘要器.update(块)
    return 摘要器.hexdigest()


def 创建不可变快照(来源目录: Path, 快照目录: Path) -> str:
    """创建不可变快照（复制 + 快照摘要 + 只读标记）。"""
    来源目录 = Path(来源目录)
    快照目录 = Path(快照目录)
    if not 来源目录.is_dir():
        raise FileNotFoundError(f"来源目录不存在: {来源目录}")
    快照目录.mkdir(parents=True, exist_ok=True)
    for 文件 in 来源目录.rglob("*"):
        if 文件.is_file() and "pycache" not in str(文件) and "工程缓存" not in str(文件) \
                and 文件.name != "快照摘要.json":
            相对 = 文件.relative_to(来源目录)
            目标 = 快照目录 / 相对
            目标.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(文件, 目标)
    # 生成快照摘要（含全部文件，供一致性校验）
    摘要表 = {}
    for 文件 in sorted(快照目录.rglob("*")):
        if 文件.is_file() and 文件.name != "快照摘要.json":
            摘要表[str(文件.relative_to(快照目录))] = 创建内容摘要(文件)
    (快照目录 / "快照摘要.json").write_text(
        json.dumps({"快照id": uuid.uuid4().hex[:16], "文件摘要": 摘要表},
                   ensure_ascii=False, indent=2), encoding="utf-8")
    return 快照目录 / "快照摘要.json"


def 校验快照(快照目录: Path) -> tuple[bool, str]:
    """校验快照完整性：文件摘要逐项比对。"""
    快照目录 = Path(快照目录)
    摘要路径 = 快照目录 / "快照摘要.json"
    if not 摘要路径.is_file():
        return False, "缺少 快照摘要.json"
    try:
        摘要数据 = json.loads(摘要路径.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return False, "快照摘要.json 损坏"
    for 相对, 期望摘要 in 摘要数据.get("文件摘要", {}).items():
        文件 = 快照目录 / 相对
        if not 文件.is_file():
            return False, f"快照缺少文件: {相对}"
        if 创建内容摘要(文件) != 期望摘要:
            return False, f"快照文件被修改: {相对}"
    return True, "快照完整"


def 创建唯一运行目录(基础目录: Path, 前缀: str = "运行") -> Path:
    """创建唯一运行目录（临时目录语义，调用方负责释放）。"""
    基础目录 = Path(基础目录)
    基础目录.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(prefix=f"{前缀}_", dir=str(基础目录)))


def 原子写入(
    目标路径: Path,
    内容: str | bytes | None = None,
    保留权限: bool = True,
    内容字节: bytes | None = None,
) -> bool:
    """原子写入：临时文件 + fsync + rename。

    - 保留权限（默认真）：目标文件已存在时，写入后仍保持原权限位。
      权限位常承载安全语义（如 0o600 的密钥文件），默认放宽等于静默降级。
    - 内容 与 内容字节 二选一：文本走 内容，二进制走 内容字节。
    - 写入后同步父目录，保证 rename 落盘。
    """
    目标路径 = Path(目标路径)
    目标路径.parent.mkdir(parents=True, exist_ok=True)
    数据 = 内容字节 if 内容字节 is not None else 内容
    原权限 = None
    if 保留权限 and 目标路径.exists():
        try:
            import stat as _stat
            原权限 = _stat.S_IMODE(目标路径.stat().st_mode)
        except OSError:
            原权限 = None
    临时路径 = 目标路径.parent / f".{目标路径.name}.{uuid.uuid4().hex[:8]}.tmp"
    模式 = "wb" if isinstance(数据, (bytes, bytearray)) else "w"
    编码 = None if isinstance(数据, (bytes, bytearray)) else "utf-8"
    try:
        with open(临时路径, 模式, encoding=编码) as 输出:
            输出.write(数据)
            输出.flush()
            os.fsync(输出.fileno())
        if 原权限 is not None:
            try:
                os.chmod(临时路径, 原权限)
            except OSError:
                pass
        os.replace(临时路径, 目标路径)  # 原子替换
    finally:
        try:
            if 临时路径.exists():
                临时路径.unlink()
        except OSError:
            pass
    try:  # 同步父目录，确保 rename 落盘
        目录描述符 = os.open(str(目标路径.parent), os.O_RDONLY)
        try:
            os.fsync(目录描述符)
        finally:
            os.close(目录描述符)
    except OSError:
        pass
    return True


# ── 读-比-写 的跨进程互斥（B-31 修复）──────────────────────────────
# 「rename 原子」只保证单个写者不半写，**不保证**「读→比→写」整段原子：两个写者可以
# 都读完、都比中，再先后覆盖——后写者静默吃掉前写者的提交，而两边都报成功。
# 本模块已有 资源短锁（mkdir 原子）就是既有的跨进程互斥原语，这里复用它把整段串行化：
# 持锁 → 锁内重读 → 锁内比较 → 锁内写回。同一目标文件即同一把锁
# （锁目录取目标文件同目录下的 .资源锁，锁名取文件名）。
CAS锁目录名 = ".资源锁"
CAS锁超时秒 = 3.0


def _带错误码(错误码: str, 说明: str) -> str:
    """拼「错误码: 说明」，说明里已带同一错误码时不重复拼接。"""
    说明 = str(说明)
    return 说明 if 说明.startswith(错误码) else f"{错误码}: {说明}"


def _CAS短锁(目标路径: Path) -> 资源短锁:
    """按目标文件推导同一把锁：<目标父目录>/.资源锁/锁_<文件名>（同文件即同锁）。"""
    目标路径 = Path(目标路径)
    return 资源短锁(目标路径.parent / CAS锁目录名, 目标路径.name,
                    持有者=f"CAS:{os.getpid()}")


def 原子替换(目标路径: Path, 新内容: str | bytes, 期望版本: str = "") -> tuple[bool, str]:
    """原子替换：可选版本比较（CAS 语义的写路径）。

    B-31 修复：版本比较不再裸奔——写前持 资源短锁，锁内重读→比较→写回；
    取不到锁（他人在写）如实返回失败，不假装替换完成。
    """
    目标路径 = Path(目标路径)
    短锁 = _CAS短锁(目标路径)
    已获取, 锁说明 = 短锁.获取(CAS锁超时秒)
    if not 已获取:
        return False, _带错误码(错误码_资源被占用, 锁说明)
    try:
        if 期望版本 and 目标路径.is_file():
            try:
                现有 = json.loads(目标路径.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                return False, "现有文件损坏，无法比较版本"
            if str(现有.get("版本", "")) != str(期望版本):
                return False, f"{错误码_版本冲突}: 期望版本 {期望版本}，实际 {现有.get('版本', '')}"
        原子写入(目标路径, 新内容)
        return True, "原子替换完成"
    finally:
        短锁.释放()


def 比较并交换(目标路径: Path, 期望值: Any, 新值: Any) -> tuple[bool, str]:
    """比较并交换（CAS）：持 资源短锁 后 读取 → 比较 → 原子写回；并发冲突返回版本冲突。

    B-31 修复：原先「读-比-写」无锁，两个写者都能比中并先后覆盖（丢失更新）且都报成功。
    现在整段进锁：锁内重读、锁内比较、锁内写回，互斥语义与同仓
    运行核心/资源协调（「锁内再次比较」）一致。
    """
    目标路径 = Path(目标路径)
    短锁 = _CAS短锁(目标路径)
    已获取, 锁说明 = 短锁.获取(CAS锁超时秒)
    if not 已获取:
        return False, _带错误码(错误码_资源被占用, 锁说明)
    try:
        if not 目标路径.is_file():
            return False, f"{错误码_资源不存在}: 目标文件不存在"
        try:
            现有 = json.loads(目标路径.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return False, "目标文件损坏"
        if 现有.get("值") != 期望值:
            return False, f"{错误码_版本冲突}: 期望值 {期望值}，实际 {现有.get('值')}"
        现有["值"] = 新值
        现有["版本"] = str(int(现有.get("版本", 0)) + 1)
        原子写入(目标路径, json.dumps(现有, ensure_ascii=False, indent=2))
        return True, "CAS 提交成功"
    finally:
        短锁.释放()


# ── 短锁崩溃残留回收的参数（B-32b）──────────────────────────────
# 判定顺序是「先判活、后 TTL」：本机持有者进程还活着就**不回收**（TTL 不生效），
# 所以 TTL 只在「判不了活」时兜底——旧锁文件缺进程号、锁目录在别的机器上建的情形。
锁默认过期秒 = 300.0
锁默认存活探测 = True
锁最大回收次数 = 3


def _本机名() -> str:
    """本机主机名（判「持有者进程号是不是本机进程」用）。取不到返回空串，按「判不了活」处理。"""
    try:
        return socket.gethostname()
    except OSError:
        return ""


class 资源短锁:
    """资源级跨进程短锁：mkdir 原子创建 + 持有者信息 + 崩溃残留回收（B-32b）。

    为什么要有「回收」：锁目录由持有进程创建，进程崩溃时没人来删——旧实现会把资源
    永久锁成「资源被占用」，只能人工清理。这里按三级判定（判不出来的宁可不回收）：
      1. 持有者信息里有 进程号 且主机名是本机，该进程已不存在（进程终止.进程存活）
         → 判定崩溃残留，回收；
      2. 持有者信息缺失/不可解析/非本机（判不了活）→ 按 TTL 判定
         （创建时间戳，缺则取锁目录 mtime）；
      3. 持有者进程还活着 → **绝不回收，TTL 不生效**：活着就说明锁还有主，
         按 TTL 抢锁等于把互斥丢掉（那正是「永久死锁」的反向错误）。
    回收用 rename 原子挪走 + 复核挪走的内容确实是那把残留锁，期间换主就原样放回；
    抢锁仍是 mkdir 原子竞争，多个回收者中只有一个能 mkdir 成功。

    已知边界（如实说明）：「进程号存活」判不了 PID 复用——被复用的 PID 会让残留锁
    看起来仍有主（按情形 3 不回收），这是「宁可保守，不做猜测式抢占」的取舍。
    """

    def __init__(self, 锁目录: Path, 资源id: str, 持有者: str = "",
                 *, 过期秒: float | None = None, 存活探测: bool | None = None) -> None:
        self.锁路径 = Path(锁目录) / f"锁_{资源id}"
        self.持有者 = 持有者
        self.已持有 = False
        self.过期秒 = 锁默认过期秒 if 过期秒 is None else float(过期秒)
        self.存活探测 = 锁默认存活探测 if 存活探测 is None else bool(存活探测)

    # ── 内部：持有者信息 / 残留判定 / 回收 ──
    def _读持有信息(self) -> dict:
        文件 = self.锁路径 / "持有者.json"
        try:
            数据 = json.loads(文件.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return 数据 if isinstance(数据, dict) else {}

    def _判定残留(self) -> tuple[bool, str]:
        """判定锁是否崩溃残留（可回收）。判不了活一律不回收。"""
        信息 = self._读持有信息()
        进程号 = 信息.get("进程号")
        主机 = str(信息.get("主机", ""))
        if isinstance(进程号, int) and not isinstance(进程号, bool) and 主机 and 主机 == _本机名():
            if 进程存活(进程号):
                return False, f"持有者进程 {进程号} 仍存活，不回收"
            return True, f"持有者进程 {进程号} 已不存在（崩溃残留）"
        创建时间 = 信息.get("创建时间戳")
        if not isinstance(创建时间, (int, float)) or isinstance(创建时间, bool):
            try:
                创建时间 = self.锁路径.stat().st_mtime
            except OSError:
                return False, "锁目录不可读，暂不回收"
        年龄 = time.time() - float(创建时间)
        if self.过期秒 > 0 and 年龄 > self.过期秒:
            return True, (f"无本机持有者信息（进程号/主机缺失或非本机）且已超 TTL："
                          f"年龄 {年龄:.1f}s > {self.过期秒}s")
        return False, (f"无本机持有者信息但未超 TTL（年龄 {年龄:.1f}s / TTL {self.过期秒}s），不回收")

    def _回收残留(self) -> tuple[bool, str]:
        """原子挪走残留锁目录；挪走后复核内容，若期间换主则原样放回。"""
        挪走 = self.锁路径.parent / f".{self.锁路径.name}.残留.{uuid.uuid4().hex[:8]}"
        原信息 = self._读持有信息()
        try:
            os.rename(self.锁路径, 挪走)  # 同父目录 rename：原子
        except FileNotFoundError:
            return False, "锁已被他人回收（目录已不存在）"
        except OSError as 错误:
            return False, f"残留锁回收失败: {错误}"
        复核 = 挪走 / "持有者.json"
        try:
            新信息 = json.loads(复核.read_text(encoding="utf-8")) if 复核.is_file() else {}
        except (OSError, json.JSONDecodeError):
            新信息 = {}
        if 新信息 != 原信息:  # 期间换主：把锁放回，别删他人正在用的锁
            try:
                挪走.rename(self.锁路径)
            except OSError:
                pass
            return False, "残留锁复核不一致（期间换主），已放回不回收"
        shutil.rmtree(挪走, ignore_errors=True)
        return True, "已回收崩溃残留锁"

    def 获取(self, 超时秒: float = 3.0) -> tuple[bool, str]:
        """获取锁（mkdir 原子创建，轮询等待）；超时返回明确错误。

        B-32b 修复：等待期间发现锁是崩溃残留（持有进程已不存在，或判不了活且超 TTL）
        就原子回收并立即重试——一把死锁不再需要人工清理。
        """
        self.锁路径.parent.mkdir(parents=True, exist_ok=True)
        截止 = time.monotonic() + 超时秒
        回收次数 = 0
        判定说明 = ""
        while True:
            try:
                self.锁路径.mkdir()
                (self.锁路径 / "持有者.json").write_text(
                    json.dumps({"持有者": self.持有者, "进程号": os.getpid(),
                                "主机": _本机名(),
                                "时间": time.strftime("%Y-%m-%d %H:%M:%S"),
                                "创建时间戳": time.time()}, ensure_ascii=False),
                    encoding="utf-8")
                self.已持有 = True
                if 回收次数:
                    return True, f"锁已获取（回收崩溃残留锁 {回收次数} 次）"
                return True, "锁已获取"
            except FileExistsError:
                if self.存活探测 and 回收次数 < 锁最大回收次数:
                    可回收, 判定说明 = self._判定残留()
                    if 可回收:
                        回收成功, 回收说明 = self._回收残留()
                        if 回收成功:
                            回收次数 += 1
                            continue  # 抢锁（mkdir 原子，多个回收者只有一个赢）
                        判定说明 = 回收说明
                if time.monotonic() > 截止:
                    补充 = f"；{判定说明}" if 判定说明 else ""
                    return False, (f"{错误码_资源被占用}: 锁被其他持有者占用"
                                   f"（{self.锁路径.name}{补充}）")
                time.sleep(0.01)

    def 释放(self) -> tuple[bool, str]:
        """释放锁。仅当锁内的持有者信息仍属于本进程时才删——锁被他人回收/接管后
        不许再删他人的锁（否则会把别人的互斥删掉）。"""
        if not self.已持有:
            return False, "锁未持有（释放幂等）"
        self.已持有 = False
        信息 = self._读持有信息()
        进程号 = 信息.get("进程号")
        if isinstance(进程号, int) and not isinstance(进程号, bool) and 进程号 != os.getpid():
            return False, (f"锁已被他人接管（持有者 {信息.get('持有者', '')}/进程 {进程号}），"
                           f"拒绝删除他人锁")
        try:
            shutil.rmtree(self.锁路径)
            return True, "锁已释放"
        except FileNotFoundError:
            return True, "锁已释放（目录不存在）"

    def 持有者是谁(self) -> str:
        return str(self._读持有信息().get("持有者", ""))


def 执行资源短锁(锁目录: str | None = None, 资源id: str | None = None, 持有者: str = "") -> 结果:
    """公开HTTP原子探针：获取短锁、读取持有者并释放，返回可传输结果。"""
    if not isinstance(锁目录, str) or not 锁目录:
        return 结果.失败("参数不合法", "锁目录必须是非空文本", 来源="资源管理")
    if not isinstance(资源id, str) or not 资源id:
        return 结果.失败("参数不合法", "资源id必须是非空文本", 来源="资源管理")
    短锁 = 资源短锁(Path(锁目录), 资源id, 持有者)
    已获取, 说明 = 短锁.获取()
    if not 已获取:
        return 结果.失败(错误码_资源被占用, 说明, 来源="资源管理")
    当前持有者 = 短锁.持有者是谁()
    已释放, 释放说明 = 短锁.释放()
    return 结果.成功结果({"已获取": True, "已释放": 已释放, "持有者": 当前持有者,
                      "锁路径": str(短锁.锁路径), "说明": 释放说明})


def 安全释放资源(路径: Path) -> tuple[bool, str]:
    """安全释放资源：文件删除或目录递归删除；不存在视为幂等成功。"""
    路径 = Path(路径)
    if not 路径.exists():
        return True, "资源不存在（释放幂等）"
    try:
        if 路径.is_dir():
            shutil.rmtree(路径)
        else:
            路径.unlink()
        return True, f"已释放: {路径}"
    except OSError as 错误:
        return False, f"释放失败: {错误}"


def 生成资源包声明() -> dict:
    """资源管理支持库包声明（供装配/验证使用）。"""
    return {
        "包id": "资源管理", "名称": "资源管理", "类型": "支持库",
        "版本": "1.0.0", "说明": "原子资源操作（快照/写入/替换/交换/锁/释放）",
        "入口": "实现/系统核心支持库.资源管理.py",
        "能力": [
            {"能力id": "系统核心支持库.资源管理.创建内容摘要", "说明": "创建文件内容摘要", "参数": [{"名称": "文件路径"}]},
            {"能力id": "系统核心支持库.资源管理.创建不可变快照", "说明": "创建不可变快照", "参数": [{"名称": "来源目录"}]},
            {"能力id": "系统核心支持库.资源管理.创建唯一运行目录", "说明": "创建唯一运行目录", "参数": [{"名称": "基础目录"}]},
            {"能力id": "系统核心支持库.资源管理.原子写入", "说明": "原子写入文件", "参数": [{"名称": "目标路径"}]},
            {"能力id": "系统核心支持库.资源管理.原子替换", "说明": "原子替换（可选版本比较）", "参数": [{"名称": "目标路径"}]},
            {"能力id": "系统核心支持库.资源管理.比较并交换", "说明": "CAS 提交", "参数": [{"名称": "目标路径"}]},
            {"能力id": "系统核心支持库.资源管理.资源短锁", "说明": "资源级跨进程短锁", "参数": [{"名称": "锁目录"}]},
            {"能力id": "系统核心支持库.资源管理.安全释放", "说明": "安全释放资源", "参数": [{"名称": "路径"}]},
        ],
    }


# ═══════════════════════════════════════════════
# 审计账本：OpenClaw audit-event-store 模式化落地
# 底座 0 加密 0 限制：完整记录调用者传入的一切字段（主体原文/内容由调用者决定）；
# 上限+批修剪（默认10万行/1024批）。隐私/脱敏/合规由 V3 业务端按需自理。
# ═══════════════════════════════════════════════
_审计账本: dict[str, list[dict]] = {}  # 账本名 -> 事件列表
_审计锁 = threading.Lock()
审计默认上限 = 100000
审计默认修剪批 = 1024
审计默认保留天 = 30
def 创建审计账本(*, 账本名: str = None, 上限: int = None, 保留天: int = None) -> 结果:
    """创建审计账本。默认上限10万、保留30天；同名复用。"""
    try:
        名 = str(账本名 or "").strip()
        if not 名:
            return 结果.失败(错误码_参数不合法, "账本名不能为空", 来源="资源管理")
        上限值 = int(上限 or 审计默认上限)
        if 上限值 <= 0:
            return 结果.失败(错误码_参数不合法, "上限必须为正整数", 来源="资源管理")
        保留值 = int(保留天 or 审计默认保留天)
        with _审计锁:
            if 名 not in _审计账本:
                _审计账本[名] = []
            return 结果.成功结果({"账本名": 名, "上限": 上限值, "保留天": 保留值,
                                 "事件数": len(_审计账本[名])})
    except Exception as 异常:
        return 结果.失败("创建失败", str(异常), 来源="资源管理")


def 记审计事件(*, 账本名: str = None, 事件类型: str = None, 主体: str = None,
               对象: str = None, 结果码: str = None, 耗时毫秒: int = None,
               通道: str = None, 方向: str = None, 元数据: dict = None) -> 结果:
    """记录一条审计事件（默认开启）。底座0限制：记录调用者传入的一切字段（原文），
    脱敏/合规由业务端在调用前自理；上限修剪可配（默认10万/1024批）。"""
    try:
        名 = str(账本名 or "").strip()
        if not 名:
            return 结果.失败(错误码_参数不合法, "账本名不能为空", 来源="资源管理")
        类型 = str(事件类型 or "通用").strip()
        if not 类型:
            return 结果.失败(错误码_参数不合法, "事件类型不能为空", 来源="资源管理")
        import time as _时间
        事件 = {
            "序号": int(_时间.time() * 1000),  # 毫秒时间戳作全局递增近似
            "时间": _时间.strftime("%Y-%m-%d %H:%M:%S", _时间.localtime()),
            "事件类型": 类型,
            "主体": str(主体 or "匿名"),
            "对象": str(对象 or ""),
            "结果码": str(结果码 or "OK"),
        }
        if 耗时毫秒 is not None:
            事件["耗时毫秒"] = int(耗时毫秒)
        if 通道:
            事件["通道"] = str(通道)
        if 方向:
            事件["方向"] = str(方向)
        if 元数据:
            # 完整记录调用者传入的元数据（底座0限制，脱敏由业务端自理）
            事件["元数据"] = {str(k): str(v) for k, v in 元数据.items()}
        with _审计锁:
            if 名 not in _审计账本:
                _审计账本[名] = []
            账本 = _审计账本[名]
            账本.append(事件)
            # 超上限批量修剪（OpenClaw：10万行上限/1024批修剪）
            if len(账本) > 审计默认上限:
                del 账本[:审计默认修剪批]
            return 结果.成功结果({"记录": True, "账本名": 名, "事件数": len(账本)})
    except Exception as 异常:
        return 结果.失败("记录失败", str(异常), 来源="资源管理")


def 查审计事件(*, 账本名: str = None, 事件类型: str = None, 主体: str = None,
                对象: str = None, 条数: int = None) -> 结果:
    """按条件查询审计事件（只读元数据，不含内容）。"""
    try:
        名 = str(账本名 or "").strip()
        if not 名:
            return 结果.失败(错误码_参数不合法, "账本名不能为空", 来源="资源管理")
        上限 = max(1, min(int(条数 or 50), 500))
        with _审计锁:
            if 名 not in _审计账本:
                return 结果.失败("账本不存在", f"审计账本 {名} 未创建", 来源="资源管理")
            账本 = _审计账本[名]
            # 倒序取最近 N 条
            命中 = list(reversed(账本))
            if 事件类型:
                命中 = [e for e in 命中 if e.get("事件类型") == 事件类型]
            if 主体:
                命中 = [e for e in 命中 if e.get("主体") == str(主体)]
            if 对象:
                命中 = [e for e in 命中 if e.get("对象") == str(对象)]
            return 结果.成功结果({"账本名": 名, "命中": len(命中),
                                 "事件列表": 命中[:上限], "共": len(账本)})
    except Exception as 异常:
        return 结果.失败("查询失败", str(异常), 来源="资源管理")


def 清空审计账本(*, 账本名: str = None) -> 结果:
    """清空审计账本（谨慎操作，需账本名精确）。"""
    try:
        名 = str(账本名 or "").strip()
        if not 名:
            return 结果.失败(错误码_参数不合法, "账本名不能为空", 来源="资源管理")
        with _审计锁:
            if 名 not in _审计账本:
                return 结果.失败("账本不存在", f"审计账本 {名} 未创建", 来源="资源管理")
            数 = len(_审计账本[名])
            _审计账本[名] = []
            return 结果.成功结果({"清空": True, "账本名": 名, "已清": 数})
    except Exception as 异常:
        return 结果.失败("清空失败", str(异常), 来源="资源管理")


# ═══════════════════════════════════════════════
# 配置变更指纹：OpenClaw config-journal-snapshot 模式化落地
# 改前快照指纹 + 改后对比；记录 谁/何时/改了什么/前后指纹（0加密，脱敏业务端自理）。
# ═══════════════════════════════════════════════
_配置指纹账本: dict[str, dict] = {}
_配置指纹锁 = threading.Lock()


def _配置指纹(配置: dict) -> str:
    """配置快照指纹：稳定序列化 + sha256。"""
    try:
        规范化 = json.dumps(配置, ensure_ascii=False, sort_keys=True, default=str)
        return hashlib.sha256(规范化.encode("utf-8")).hexdigest()[:16]
    except Exception:
        return "无法指纹"


def 登记配置快照(*, 配置名: str = None, 配置: dict = None, 操作人: str = None) -> 结果:
    """登记配置当前快照指纹（改前调用：记录基线）。"""
    try:
        名 = str(配置名 or "").strip()
        if not 名:
            return 结果.失败(错误码_参数不合法, "配置名不能为空", 来源="资源管理")
        if not isinstance(配置, dict):
            return 结果.失败(错误码_参数不合法, "配置必须是字典", 来源="资源管理")
        import time as _时间
        指纹 = _配置指纹(配置)
        with _配置指纹锁:
            _配置指纹账本[名] = {
                "指纹": 指纹,
                "改前指纹": None,
                "操作人": str(操作人 or ""),
                "时间": _时间.strftime("%Y-%m-%d %H:%M:%S", _时间.localtime()),
                "变更记录": [],
            }
            return 结果.成功结果({"配置名": 名, "指纹": 指纹, "基线": True})
    except Exception as 异常:
        return 结果.失败("登记失败", str(异常), 来源="资源管理")


def 对比配置指纹(*, 配置名: str = None, 新配置: dict = None, 操作人: str = None) -> 结果:
    """对比新配置与基线指纹。变则记 journal（改前指纹/新指纹/操作人），不变返回一致。"""
    try:
        名 = str(配置名 or "").strip()
        if not 名:
            return 结果.失败(错误码_参数不合法, "配置名不能为空", 来源="资源管理")
        if not isinstance(新配置, dict):
            return 结果.失败(错误码_参数不合法, "新配置必须是字典", 来源="资源管理")
        import time as _时间
        新指纹 = _配置指纹(新配置)
        with _配置指纹锁:
            if 名 not in _配置指纹账本:
                # 无基线：直接登记为新基线（幂等首登）
                _配置指纹账本[名] = {
                    "指纹": 新指纹, "改前指纹": None,
                    "操作人": str(操作人 or ""),
                    "时间": _时间.strftime("%Y-%m-%d %H:%M:%S", _时间.localtime()),
                    "变更记录": [],
                }
                return 结果.成功结果({"配置名": 名, "变更": False, "首登基线": True, "指纹": 新指纹})
            条目 = _配置指纹账本[名]
            if 条目["指纹"] == 新指纹:
                return 结果.成功结果({"配置名": 名, "变更": False, "指纹": 新指纹})
            # 有变更：记 journal
            条目["变更记录"].append({
                "改前指纹": 条目["指纹"],
                "新指纹": 新指纹,
                "操作人": str(操作人 or "未知"),
                "时间": _时间.strftime("%Y-%m-%d %H:%M:%S", _时间.localtime()),
            })
            条目["改前指纹"] = 条目["指纹"]
            条目["指纹"] = 新指纹
            条目["操作人"] = str(操作人 or "")
            条目["时间"] = _时间.strftime("%Y-%m-%d %H:%M:%S", _时间.localtime())
            return 结果.成功结果({
                "配置名": 名, "变更": True,
                "改前指纹": 条目["改前指纹"], "新指纹": 新指纹,
                "操作人": str(操作人 or "未知"),
                "变更序号": len(条目["变更记录"]),
            })
    except Exception as 异常:
        return 结果.失败("对比失败", str(异常), 来源="资源管理")


def 查配置指纹(*, 配置名: str = None) -> 结果:
    """查询配置指纹与变更记录。"""
    try:
        名 = str(配置名 or "").strip()
        if not 名:
            return 结果.失败(错误码_参数不合法, "配置名不能为空", 来源="资源管理")
        with _配置指纹锁:
            if 名 not in _配置指纹账本:
                return 结果.失败("配置不存在", f"配置指纹 {名} 未登记", 来源="资源管理")
            条目 = _配置指纹账本[名]
            return 结果.成功结果({
                "配置名": 名, "当前指纹": 条目["指纹"],
                "改前指纹": 条目["改前指纹"],
                "当前操作人": 条目["操作人"], "当前时间": 条目["时间"],
                "变更次数": len(条目["变更记录"]),
                "变更记录": list(reversed(条目["变更记录"])),
            })
    except Exception as 异常:
        return 结果.失败("查询失败", str(异常), 来源="资源管理")



# ═══════════════════════════════════════════════
# 逆序回滚：DeepSeek webhook 建链逆序回滚模式化落地
# 创建链（workspace→agent→attach→title→submit）任一步失败按逆序释放已建资源。
# 0加密0限制：回滚动作由调用者提供的函数执行，底座只做编排。
# ═══════════════════════════════════════════════
_回滚事务表: dict[str, dict] = {}
_回滚锁 = threading.Lock()
# 回滚事务账本上限（B-32a：原实现无界，长跑进程会一直涨）。
# 超上限只修剪**已回滚**的最老事务（dict 保序 = 登记顺序），进行中/回滚中的一律保留
# ——那才是还没回滚、必须记住的账；宁可不修剪也不丢未回滚事务。
回滚事务上限 = 1000


def _修剪回滚事务表(保留: str = "") -> int:
    """超上限时修剪已回滚的最老事务（调用方必须已持 _回滚锁）；返回修剪条数。"""
    if len(_回滚事务表) <= 回滚事务上限:
        return 0
    修剪数 = 0
    for 事务 in list(_回滚事务表.keys()):
        if len(_回滚事务表) <= 回滚事务上限:
            break
        if 事务 == 保留:
            continue
        条目 = _回滚事务表[事务]
        if 条目.get("已回滚") or 条目.get("状态") == "已回滚":
            del _回滚事务表[事务]
            修剪数 += 1
    return 修剪数


def 登记回滚步骤(*, 事务id: str = None, 步骤名: str = None,
                 回滚动作: dict = None) -> 结果:
    """登记一个可回滚步骤（成功创建资源后调用）。回滚动作 = {"类型": "回滚", "参数": {...}}。"""
    try:
        事务 = str(事务id or "").strip()
        if not 事务:
            return 结果.失败(错误码_参数不合法, "事务id不能为空", 来源="资源管理")
        步骤 = str(步骤名 or "").strip()
        if not 步骤:
            return 结果.失败(错误码_参数不合法, "步骤名不能为空", 来源="资源管理")
        if not isinstance(回滚动作, dict) or not 回滚动作:
            return 结果.失败(错误码_参数不合法, "回滚动作必须是字典", 来源="资源管理")
        with _回滚锁:
            if 事务 not in _回滚事务表:
                _回滚事务表[事务] = {"步骤列表": [], "状态": "进行中", "已回滚": False}
            条目 = _回滚事务表[事务]
            条目["步骤列表"].append({"步骤名": 步骤, "回滚动作": 回滚动作})
            return 结果.成功结果({"事务id": 事务, "步骤数": len(条目["步骤列表"]),
                                 "已登记": 步骤, "已修剪事务数": _修剪回滚事务表(保留=事务)})
    except Exception as 异常:
        return 结果.失败("登记失败", str(异常), 来源="资源管理")


def _取回滚函数(回滚器) -> tuple[Any, str]:
    """从 回滚器 中取可调用的回滚函数，取不到时返回 (None, 原因)。

    接受两种形态：直接给可调用对象；或给 {"函数名": <可调用对象>, "参数模板": {...}}。
    「函数名」只认可调用对象本身（字符串函数名无登记表可解析，等同不可用），
    避免把「登记了个名字」当成「已经真的回滚了」。
    """
    if callable(回滚器):
        return 回滚器, ""
    if isinstance(回滚器, dict):
        for 键 in ("函数名", "函数", "回滚函数", "可调用"):
            值 = 回滚器.get(键)
            if callable(值):
                return 值, ""
        return None, "回滚器未提供可调用的回滚函数（须给可调用对象或 {\"函数名\": 可调用对象}）"
    return None, "回滚器缺失或不可用（须为可调用对象或含可调用函数名的字典）"


def 执行逆序回滚(*, 事务id: str = None, 回滚器: dict = None) -> 结果:
    """按逆序真实调用回滚器执行全部已登记步骤的回滚动作。
    回滚器 = 可调用对象，或 {"函数名": <可调用对象>, "参数模板": {...}}。

    调用约定：回滚函数(回滚动作=本步骤的 回滚动作, **参数模板)。
    每步的「已执行」取回滚函数的真实返回值（结果对象取 成功 字段，布尔原样取用），
    抛出异常或回滚器不可用都记为该步未执行并继续后续步骤，不中断整体回滚。

    B-32a 修复（幂等拒绝）：回滚动作按约定是**破坏性**释放（删资源/拆链），同一事务
    只能真正回滚一次。状态为「回滚中」或「已回滚」时直接拒绝并在错误码里说清
    （错误码 重复回滚），不再把整套动作重放一遍。并发双调用同样被这一步挡住：
    「回滚中」是在出锁前就置好的，第二个调用进不来。
    需要重试点就另开新事务id（登记+回滚），不复用已回滚事务。
    """
    try:
        事务 = str(事务id or "").strip()
        if not 事务:
            return 结果.失败(错误码_参数不合法, "事务id不能为空", 来源="资源管理")
        with _回滚锁:
            if 事务 not in _回滚事务表:
                return 结果.失败("事务不存在", f"事务 {事务} 未登记步骤", 来源="资源管理")
            条目 = _回滚事务表[事务]
            if 条目.get("已回滚") or 条目.get("状态") in ("回滚中", "已回滚"):
                return 结果.失败(
                    错误码_重复回滚,
                    f"事务 {事务} 当前状态「{条目.get('状态', '')}」，拒绝重复回滚"
                    f"（回滚动作是破坏性释放，重复执行会二次删已回收资源；"
                    f"需要重试请另开新事务id）",
                    来源="资源管理")
            步骤们 = list(条目["步骤列表"])  # 拷贝
            条目["状态"] = "回滚中"
        回滚函数, 取函数错误 = _取回滚函数(回滚器)
        参数模板 = 回滚器.get("参数模板") if isinstance(回滚器, dict) else {}
        参数模板 = dict(参数模板) if isinstance(参数模板, dict) else {}
        # 逆序执行
        回滚结果列表 = []
        for 步骤 in reversed(步骤们):
            动作 = 步骤["回滚动作"]
            步骤结果 = {"步骤名": 步骤["步骤名"], "动作": 动作, "已执行": False, "说明": ""}
            if 回滚函数 is None:
                步骤结果["说明"] = 取函数错误
                回滚结果列表.append(步骤结果)
                continue
            try:
                返回值 = 回滚函数(回滚动作=动作, **参数模板)
            except Exception as 异常:  # 单步失败不得中断整体回滚
                步骤结果["说明"] = f"回滚函数异常: {异常}"
                回滚结果列表.append(步骤结果)
                continue
            步骤结果["已执行"] = (bool(getattr(返回值, "成功"))
                              if hasattr(返回值, "成功") else bool(返回值))
            if not 步骤结果["已执行"]:
                步骤结果["说明"] = str(
                    getattr(返回值, "错误说明", "") or getattr(返回值, "错误码", "") or 返回值)
            回滚结果列表.append(步骤结果)
        失败数 = sum(1 for 项 in 回滚结果列表 if not 项["已执行"])
        with _回滚锁:
            条目["状态"] = "已回滚"
            条目["已回滚"] = True
            条目["回滚数"] = len(回滚结果列表)
            条目["失败数"] = 失败数
            条目["完成时间"] = time.strftime("%Y-%m-%d %H:%M:%S")
        return 结果.成功结果({
            "事务id": 事务, "回滚数": len(回滚结果列表), "失败数": 失败数,
            "回滚列表": 回滚结果列表, "状态": "已回滚",
            "说明": f"按登记逆序执行 {len(回滚结果列表)} 步，失败 {失败数} 步"
                    f"（已执行 取回滚函数真实返回值）",
        })
    except Exception as 异常:
        return 结果.失败("回滚失败", str(异常), 来源="资源管理")


def 查询回滚事务(*, 事务id: str = None) -> 结果:
    """查询事务回滚状态。"""
    try:
        事务 = str(事务id or "").strip()
        if not 事务:
            return 结果.失败(错误码_参数不合法, "事务id不能为空", 来源="资源管理")
        with _回滚锁:
            if 事务 not in _回滚事务表:
                return 结果.失败("事务不存在", f"事务 {事务} 不存在", 来源="资源管理")
            条目 = _回滚事务表[事务]
            return 结果.成功结果({
                "事务id": 事务, "状态": 条目["状态"], "已回滚": 条目["已回滚"],
                "步骤数": len(条目["步骤列表"]),
                "步骤列表": [{"步骤名": s["步骤名"]} for s in 条目["步骤列表"]],
                "回滚数": 条目.get("回滚数", 0), "失败数": 条目.get("失败数", 0),
                "完成时间": 条目.get("完成时间", ""),
            })
    except Exception as 异常:
        return 结果.失败("查询失败", str(异常), 来源="资源管理")
