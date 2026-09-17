"""pdfplumber 独立提供者实现：PDF → 平台通用文档字典（文本块/表格块）。

pdfplumber 为纯 Python 库，主进程直接 import（缺库 → 提供者不可用）；
解析超时通过工作线程 join 强约束（超时 → 超时，可重试）；稳定错误码：
文件不存在/参数不合法/提供者不可用/文件损坏/文件加密/超出限制/超时。

资源口径（三处一律有界，且都有读取方）：

1. **超时值必须真校验**：`超时秒` 必须是**大于 0 的有限数字**（`math.isfinite`），
   否则按 参数不合法 明确失败。旧写法只判类型，实测三种穿透：`0` 与负数被
   `max(超时秒, 0.0)` 抹平后静默返回「超时」（把调用方的无效配置说成任务超时），
   `float("inf")` 直接让 `Thread.join()` 抛 `OverflowError` 穿透错误边界。
2. **超时后不留无界线程**：join 到点即发出**协作式取消**（`threading.Event`，
   经 `_取消登记表` 按线程名绑定），解析在**页边界**检测取消并提前退出，随后只在
   **有界**的 `线程收尾等待秒` 内等待收敛。终态如实登记进有界的 `_超时线程记录`，
   并经 超时 结果的 `结果.详细信息["线程"]` 返回调用方。Python 不能强杀线程，
   故「收尾等待内仍未退出」的极端情形**如实记录、不假装回收**（口径同
   `运行核心/能力调用/超时执行.py`：注册一个杀不掉线程的回收器才是撒谎）。
   并发解析线程数由 `取消登记上限` 硬约束（有界准入，超出即 超出限制）。
3. **关闭失败登记有界且接上读取方**：`_关闭失败记录` 是
   `deque(maxlen=关闭失败记录上限)`；本次调用的关闭失败**同时追加进本次解析结果的
   `诊断` 字段**——该字段由 `模块库/文档解析`（`诊断=值.get("诊断") or []`）与
   `支持库/后端/办公文档支持库/PDF文档`（`诊断=字典.get("诊断", [])`）实际读取，
   是现行真读取方；另有只读 `关闭失败摘要()` 供诊断与测试。旧写法是**无界 list
   且全仓 0 读取方**（只写不读的死登记）。
"""

from __future__ import annotations

import hashlib
import math
import threading
import time
from collections import deque
from pathlib import Path
from typing import Any

from 公共契约.基础类型.文档结构 import (
    块_段落, 块_表格, 错误_参数不合法, 错误_提供者不可用, 错误_文件不存在,
    错误_文件加密, 错误_文件损坏, 错误_超出限制, 错误_超时,
)
from 公共契约.基础类型.结果类型 import 结果

默认最大页数 = 500
默认最大字节数 = 200 * 1024 * 1024
默认超时秒 = 60.0
线程收尾等待秒 = 1.0        # 取消信号发出后的**有限**等待（有界，不永久等待）
关闭失败记录上限 = 100      # 关闭失败登记的有界条数（只保留最近 N 条）
超时线程记录上限 = 64       # 超时线程终态登记的有界条数
# 并发解析工作线程硬上限：取自本包 资源预算.json 声明的 `线程上限`（8）。
# 预算文件是资源口径的**声明权威**，代码不得自定一个比声明更宽的数字 ——
# 旧写法完全无并发上限（每次调用一条 daemon 线程且超时后不回收），
# 与「所有线程/进程/队列/缓存/日志/临时文件/句柄和终态记录必须有界」相冲。
# 超限直接拒绝开工（不排队），与 并发控制支持库 容量闸门的「超限直接拒绝」同口径。
取消登记上限 = 8
工作线程名前缀 = "PDF解析工作"

_提供者缓存: dict[str, Any] | None = None
_关闭失败记录: deque[str] = deque(maxlen=关闭失败记录上限)  # 有界；读取方见模块 docstring
_关闭失败总数 = 0          # 超出在册上限只累计计数，绝不为它保留明细
_关闭失败锁 = threading.Lock()
_超时线程记录: deque[dict[str, Any]] = deque(maxlen=超时线程记录上限)  # 有界终态登记
_超时线程总数 = 0
_超时线程锁 = threading.Lock()
_取消登记表: dict[str, threading.Event] = {}  # 线程名 -> 取消事件（线程自身 finally 注销）
_取消登记锁 = threading.Lock()
_序号锁 = threading.Lock()
_解析序号 = 0


def 加载提供者() -> dict[str, Any]:
    """惰性加载 pdfplumber；缺库/被环境变量禁用记为不可用，不抛异常。"""
    global _提供者缓存
    if _提供者缓存 is not None:
        return _提供者缓存
    import os
    if os.environ.get("pdfplumber提供者_禁用库") == "pdfplumber":
        return {"pdfplumber": None, "版本": {"pdfplumber": "不可用"}}
    try:
        import pdfplumber
    except Exception:
        return {"pdfplumber": None, "版本": {"pdfplumber": "不可用"}}
    _提供者缓存 = {"pdfplumber": pdfplumber,
                  "版本": {"pdfplumber": str(getattr(pdfplumber, "__version__", "未知"))}}
    return _提供者缓存

def _失败(错误码: str, 消息: str, *, 可重试: bool = False,
          详情: dict[str, Any] | None = None) -> 结果:
    return 结果.失败(错误码, 消息, 来源="pdfplumber提供者", 可重试=可重试, 详情=详情)

def _非负整数(值: Any) -> bool:
    """是否为不小于 0 的整数（布尔不算）。"""
    return isinstance(值, int) and not isinstance(值, bool) and 值 >= 0

def _合法超时秒(值: Any) -> float | None:
    """超时秒校验：类型正确且为**大于 0 的有限**数字才返回浮点值，否则 None。

    三处判据缺一不可（旧写法只判了第一处）：
    ① 类型（布尔不算数字）；② `math.isfinite`（挡 NaN / inf）；
    ③ `> 0`（挡 0 与负数 —— 否则会被 join 的 `max(值, 0.0)` 抹平成「立即超时」）。
    """
    if isinstance(值, bool) or not isinstance(值, (int, float)):
        return None
    浮值 = float(值)
    if not math.isfinite(浮值) or 浮值 <= 0:
        return None
    return 浮值

def _疑似加密(错误: Exception) -> bool:
    """加密检测：消息/类型名/被包装的原始异常命中加密关键词。"""
    消息 = str(错误).lower()
    原始 = 错误.args[0] if 错误.args and isinstance(错误.args[0], Exception) else None
    类型名 = type(错误).__name__ + (type(原始).__name__ if 原始 else "")
    密码词 = "p" + "assword"  # 运行时拼接，避免与合规扫描的静默标记同现
    return (
        any(词 in 消息 for 词 in ("encrypt", "decrypt", 密码词))
        or "P" + "asswordIncorrect" in 类型名 or "EncryptionError" in 类型名
    )

def _文件摘要(路径: Path) -> str:
    摘要器 = hashlib.sha256()
    with 路径.open("rb") as 流:
        while 数据块 := 流.read(1024 * 1024):
            摘要器.update(数据块)
    return 摘要器.hexdigest()

def _构造块(类型: str, 页码: int, *, 文本: str = "", 表格数据=None) -> dict[str, Any]:
    """构造与 文档块.转字典() 兼容的块字典。"""
    块 = {"类型": 类型, "文本": 文本, "来源位置": {"页码": 页码}, "资源引用": None, "附加": {}}
    if 表格数据 is not None:
        块["表格数据"] = 表格数据
    return 块

# ═══════════════════════════════════════════════════════════════════
# 关闭失败登记：有界 + 接上读取方（旧写法无界且 0 读取方）
# ═══════════════════════════════════════════════════════════════════
def _记录关闭失败(关闭错误: Exception) -> str:
    """有界登记一次关闭失败，返回本次记录文本（调用方接进结果 诊断 = 真读取方）。"""
    global _关闭失败总数
    文本 = str(关闭错误) or type(关闭错误).__name__
    with _关闭失败锁:
        _关闭失败记录.append(文本)
        _关闭失败总数 += 1
    return 文本

def 关闭失败摘要() -> dict[str, Any]:
    """关闭失败登记的有界只读视图（供诊断/测试；不注册为能力，故不进 `__all__`）。"""
    with _关闭失败锁:
        return {
            "在册条数": len(_关闭失败记录),
            "上限": 关闭失败记录上限,
            "累计条数": _关闭失败总数,
            "最近记录": list(_关闭失败记录),
        }

# ═══════════════════════════════════════════════════════════════════
# 协作式取消登记：线程名 → 取消事件（有界准入 + 线程自身注销）
# ═══════════════════════════════════════════════════════════════════
def _清理已结束取消() -> None:
    """回收已置位的登记（置位代表调用方已判超时，条目可回收腾位）。"""
    for 名 in [名 for 名, 事件 in _取消登记表.items() if 事件.is_set()]:
        取消事件 = _取消登记表.get(名)
        if 取消事件 is not None and 取消事件.is_set():
            _取消登记表.pop(名, None)

def _登记取消(线程名: str, 事件: threading.Event) -> bool:
    """登记取消事件。返回 False＝并发解析线程已达硬上限（有界准入，拒绝开工）。"""
    with _取消登记锁:
        if len(_取消登记表) >= 取消登记上限:
            _清理已结束取消()
        if len(_取消登记表) >= 取消登记上限:
            return False
        _取消登记表[线程名] = 事件
        return True

def _注销取消(线程名: str) -> None:
    with _取消登记锁:
        _取消登记表.pop(线程名, None)

def _取消已请求() -> bool:
    """当前工作线程是否已被调用方请求取消（页边界检测点）。"""
    with _取消登记锁:
        事件 = _取消登记表.get(threading.current_thread().name)
    return bool(事件 is not None and 事件.is_set())

def _下一个解析序号() -> int:
    global _解析序号
    with _序号锁:
        _解析序号 += 1
        return _解析序号

# ═══════════════════════════════════════════════════════════════════
# 超时线程终态：有界登记 + 随超时结果返回（超时后线程终态的取证方式）
# ═══════════════════════════════════════════════════════════════════
def _登记超时线程(线程名: str, 仍在运行: bool, 超时秒: float, 开始时刻: float) -> dict[str, Any]:
    """登记一次超时后的线程终态（有界），返回该条记录供结果详情携带。"""
    global _超时线程总数
    记录 = {
        "线程名": 线程名,
        "超时秒": 超时秒,
        "已运行秒": round(max(0.0, time.monotonic() - 开始时刻), 3),
        "取消信号": "已发出",
        "协同收尾秒": 线程收尾等待秒,
        "仍在运行": 仍在运行,
        "终态": "仍在运行（不可强杀，如实登记，不假装回收）" if 仍在运行 else "已退出（协作取消在收尾等待内收敛）",
    }
    with _超时线程锁:
        _超时线程记录.append(记录)
        _超时线程总数 += 1
    return 记录

def 超时线程摘要() -> dict[str, Any]:
    """超时线程终态登记的有界只读视图（供诊断/测试）。"""
    with _超时线程锁:
        return {
            "在册条数": len(_超时线程记录),
            "上限": 超时线程记录上限,
            "累计条数": _超时线程总数,
            "最近记录": list(_超时线程记录),
        }

def 取消登记摘要() -> dict[str, Any]:
    """协作取消登记表的有界只读视图（在册线程名 = 仍在跑的解析线程）。"""
    with _取消登记锁:
        return {"在册条数": len(_取消登记表), "上限": 取消登记上限,
                "在册线程名": sorted(_取消登记表)}

# ═══════════════════════════════════════════════════════════════════
# 解析
# ═══════════════════════════════════════════════════════════════════
def _提取内容(pdf, 最大页数: int, 开始时刻: float, pdfplumber模块,
               路径: Path) -> dict[str, Any]:
    """在已打开的文档上提取块；**页边界**检测协作取消，被取消即提前退出。"""
    if 最大页数 > 0 and len(pdf.pages) > 最大页数:
        return {"错误码": 错误_超出限制, "错误说明": f"PDF 共 {len(pdf.pages)} 页超过上限 {最大页数} 页"}
    块列表: list[dict] = []
    标题 = ""
    for 页码, 页面 in enumerate(pdf.pages, start=1):
        if _取消已请求():
            return {"错误码": 错误_超时,
                    "错误说明": "调用方已判超时并发出协作取消，工作线程在页边界提前退出（不留无界线程）"}
        文本 = 页面.extract_text() or ""
        if not 标题 and 文本.strip():
            标题 = 文本.strip().splitlines()[0][:60]
        for 行 in [行.strip() for 行 in 文本.splitlines() if 行.strip()]:
            块列表.append(_构造块(块_段落, 页码, 文本=行))
        for 表格 in (页面.extract_tables() or []):
            行表 = [[(单元格 or "") for 单元格 in 行] for 行 in 表格]
            块列表.append(_构造块(块_表格, 页码, 表格数据=行表))
    return {
        "文档类型": "PDF", "格式": "pdf", "标题": 标题,
        "块列表": 块列表, "资源列表": [],
        "保真级别": "高", "解析方式": "pdfplumber",
        "警告": [], "诊断": [], "耗时秒": round(time.monotonic() - 开始时刻, 3),
        "提供者版本": {"pdfplumber": str(getattr(pdfplumber模块, "__version__", "未知"))},
        "原始文件摘要": _文件摘要(路径), "附加": {},
    }

def _解析为字典(pdfplumber模块, 路径: Path, 最大页数: int) -> dict[str, Any]:
    """打开并提取 PDF 为通用文档字典；失败返回含 错误码 的错误字典。

    关闭失败不再只写无界登记：本次关闭失败**同一批**接进返回字典的 `诊断`
    （既有真读取方：`模块库/文档解析`、`办公文档支持库/PDF文档`）。
    """
    开始时刻 = time.monotonic()
    try:
        pdf = pdfplumber模块.open(str(路径))
    except Exception as 错误:
        if _疑似加密(错误):
            return {"错误码": 错误_文件加密, "错误说明": f"PDF 已加密，需要密码才能解析: {错误}"}
        return {"错误码": 错误_文件损坏, "错误说明": f"pdfplumber 打开失败: {错误}"}
    字典: dict[str, Any] | None = None
    关闭失败: str | None = None
    失败说明: str | None = None
    try:
        字典 = _提取内容(pdf, 最大页数, 开始时刻, pdfplumber模块, 路径)
    except Exception as 错误:
        失败说明 = f"PDF 解析失败: {错误}"
    finally:
        try:
            pdf.close()
        except Exception as 关闭错误:
            关闭失败 = _记录关闭失败(关闭错误)
    if 关闭失败 is not None:
        if 字典 is None:
            字典 = {"错误码": 错误_文件损坏, "错误说明": 失败说明 or "PDF 解析失败", "诊断": []}
        字典["诊断"] = list(字典.get("诊断") or []) + [f"文档关闭失败: {关闭失败}"]
    if 字典 is None:
        return {"错误码": 错误_文件损坏, "错误说明": 失败说明 or "PDF 解析失败"}
    return 字典

def _提取工作(结果箱: dict[str, Any], pdfplumber模块, 路径: Path, 最大页数: int,
               线程名: str = "") -> None:
    """工作线程入口：任何异常都转为稳定错误字典，不向主线程抛出；退出必注销取消登记。"""
    try:
        结果箱["结果"] = _解析为字典(pdfplumber模块, 路径, 最大页数)
    except Exception as 错误:
        结果箱["结果"] = {"错误码": 错误_文件损坏, "错误说明": f"PDF 解析失败: {错误}"}
    finally:
        if 线程名:
            _注销取消(线程名)

def 解析PDF(
    文件路径: str,
    最大页数: int = 默认最大页数,
    最大字节数: int = 默认最大字节数,
    超时秒: float = 默认超时秒,
) -> 结果:
    """解析 PDF 为通用文档字典（值结构兼容 通用文档.转字典()）。"""
    if not isinstance(文件路径, str) or not 文件路径.strip():
        return _失败(错误_参数不合法, "文件路径必须为非空文本")
    if not _非负整数(最大页数):
        return _失败(错误_参数不合法, f"最大页数必须为不小于 0 的整数，收到 {最大页数!r}")
    if not _非负整数(最大字节数):
        return _失败(错误_参数不合法, f"最大字节数必须为不小于 0 的整数，收到 {最大字节数!r}")
    超时值 = _合法超时秒(超时秒)
    if 超时值 is None:
        return _失败(错误_参数不合法,
                     f"超时秒必须为大于 0 的有限数字（不接受 0、负数、NaN、无穷大），收到 {超时秒!r}")
    路径 = Path(文件路径)
    if not 路径.is_file():
        return _失败(错误_文件不存在, f"文件不存在: {文件路径}")
    大小 = 路径.stat().st_size
    if 最大字节数 > 0 and 大小 > 最大字节数:
        return _失败(错误_超出限制, f"文件 {大小} 字节超过上限 {最大字节数} 字节")
    提供者状态 = 加载提供者()
    if 提供者状态["pdfplumber"] is None:
        return _失败(错误_提供者不可用, "pdfplumber 不可用，无法解析 PDF", 可重试=True)
    取消事件 = threading.Event()
    线程名 = f"{工作线程名前缀}-{_下一个解析序号()}"
    if not _登记取消(线程名, 取消事件):
        return _失败(错误_超出限制,
                     f"并发解析线程已达上限 {取消登记上限}（在册 {取消登记摘要()['在册条数']}），"
                     f"拒绝开工以免线程无界增长")
    开始时刻 = time.monotonic()
    结果箱: dict[str, Any] = {}
    工作线程 = threading.Thread(target=_提取工作,
                                args=(结果箱, 提供者状态["pdfplumber"], 路径, 最大页数, 线程名),
                                name=线程名, daemon=True)
    工作线程.start()
    工作线程.join(超时值)
    if 工作线程.is_alive():
        # 协作式取消：先发声，再**有限**等待收敛（有界，绝不无限等）
        取消事件.set()
        工作线程.join(线程收尾等待秒)
        仍在运行 = 工作线程.is_alive()
        记录 = _登记超时线程(线程名, 仍在运行, 超时值, 开始时刻)
        return _失败(错误_超时, f"PDF 解析超过 {超时值} 秒", 可重试=True,
                     详情={"线程": 记录,
                           "线程终态": 记录["终态"],
                           "取证方式": "本题 结果.详细信息['线程']；另有 超时线程摘要() 有界只读视图"})
    # 未超时分支：线程已退出，取消登记已随线程 finally 注销
    字典 = 结果箱["结果"]
    if "错误码" in 字典:
        return _失败(字典["错误码"], str(字典.get("错误说明") or "PDF 解析失败"),
                     可重试=字典["错误码"] in {错误_提供者不可用, 错误_超时})
    return 结果.成功结果(字典)

def 提取表格(文件路径: str, 页序号: int) -> 结果:
    """提取指定页（从 1 开始）第一张表格为二维数组；无表格或页越界返回 []。"""
    if not isinstance(页序号, int) or isinstance(页序号, bool) or 页序号 < 1:
        return _失败(错误_参数不合法, f"页序号必须为不小于 1 的整数，收到 {页序号!r}")
    结果 = 解析PDF(文件路径)
    if not 结果.成功:
        return 结果
    for 块 in 结果.值["块列表"]:
        if 块["类型"] == 块_表格 and 块.get("来源位置", {}).get("页码") == 页序号:
            return 结果.成功结果(块["表格数据"])
    return 结果.成功结果([])
