"""技能库实现：技能包结构校验、受控脚本执行、技能索引扫描。

迁移自 V3（薄壳化 1-9 受控脚本沙箱 / 1-10 技能包结构校验）：
- `模块库/开发工具/脚本执行器.py`（401 行）
- `模块库/开发工具/技能包校验器.py`

与 V3 版的关键差别：**全部参数化**，不绑任何具体项目——
- 「技能根目录」由调用方传入（V3 传自己的 `模块库/Skills`，其他项目传自己的目录）；
- 「禁止导入前缀」由调用方传入（V3 传自己的应用层顶层目录集合），
  底座内置的硬禁止项（绕过解释器、shell 执行、动态加载、第三方库）始终生效。

安全边界（全部 fail-closed）：
- 固定解释器：只使用本进程解释器，调用方不可指定解释器或命令，只能给技能标识。
- 结构化 stdin/stdout：参数经 stdin JSON 传入，结果从 stdout JSON 解析。
- 超时与进程组回收：进程组启动标志与强制终止都走收口层
  （`公共契约/运行时/平台适配.子进程组启动标志()` +
  `公共契约/运行时/进程终止.强制结束子进程()`），超时连孙进程一并回收。
- 输出上限：stdout 超限立即终止并返回 输出超限。
- 环境变量白名单：只透传白名单内变量；调用方传白名单外变量直接拒绝。
- 路径范围校验：技能目录、入口脚本、工作目录必须位于技能根目录内。
- 资源预算：RLIMIT_CPU / RLIMIT_FSIZE。
- 导入审计（AST）：禁止 shell=True、eval/exec/compile、__import__/importlib 动态加载、
  subprocess/os 命令执行、第三方库；调用方可用「禁止导入前缀」追加项目级禁入项。
- 可调能力白名单（默认空 = 行为与历史版本完全一致，技能脚本只能纯标准库）：非空时把
  合成模块 `技能底座能力` 注入子进程并**只对它一个模块名放行导入**，技能脚本经它走
  唯一网关 HTTP（`POST /网关/调用`，操作=调用能力）调用白名单内的底座能力；
  白名单外一律拒绝，不放第三方、不放进程派生、不放项目模块导入。
"""

from __future__ import annotations

import ast
import contextlib
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

from 公共契约.基础类型.结果类型 import 结果
from 公共契约.运行时 import 平台适配, 有界IO, 进程终止
from 公共契约.基础类型.逻辑类型 import 真, 假

来源标识 = "技能库"

# ── 常量 ──────────────────────────────────────────────────────────

技能包必需文件 = ("SKILL.md", "契约.json", "工作流.json", "依赖.json", "验证声明.json")

环境变量白名单 = frozenset({
    "PATH", "LANG", "LC_ALL", "HOME", "USER", "TMPDIR", "TZ",
    "PYTHONUTF8", "PYTHONDONTWRITEBYTECODE",
})

标准库模块集合 = frozenset(sys.stdlib_module_names)

# 硬禁止：任何技能脚本都不得触达（与具体项目无关）
硬禁止导入模块 = frozenset({
    "subprocess", "pty", "ctypes", "multiprocessing", "importlib",
    "socket", "http", "urllib", "requests", "ftplib", "telnetlib",
    "shutil", "glob", "tempfile",
})

硬禁止调用标记 = ("shell=True", "eval", "exec", "compile", "__import__")

# 硬禁止：即便 os 属标准库可导入，其命令执行/进程派生子接口也不得调用
硬禁止调用链 = frozenset({
    "os.system", "os.popen", "os.fork", "os.forkpty", "os.posix_spawn",
    "os.spawnl", "os.spawnle", "os.spawnlp", "os.spawnlpe",
    "os.spawnv", "os.spawnve", "os.spawnvp", "os.spawnvpe",
    "os.execv", "os.execl", "os.execle", "os.execlp", "os.execlpe",
    "os.execvp", "os.execvpe", "os.startfile", "pty.spawn",
})

固定解释器 = sys.executable

默认超时秒 = 30
默认输出上限 = 1_048_576
默认脚本大小上限 = 1_048_576


# ── 可调能力白名单（技能脚本唯一的底座能力调用腿） ────────────────────
# 默认空 = 行为与历史版本完全一致：技能脚本只能纯标准库。
# 非空时才把下面的合成模块写进临时目录、注入子进程，并对该模块名放行导入。
# 凭证只经环境变量传递，绝不写进代码、日志或返回结构。
合成模块名 = "技能底座能力"
合成模块目录前缀 = "技能底座能力注入-"
默认网关地址 = "http://127.0.0.1:40007"
网关地址环境变量 = "技能库_网关地址"
网关凭证环境变量 = "系统库网关凭证"
默认网关超时秒 = 20.0

合成模块模板 = '''"""技能底座能力：平台为本次受控执行注入的唯一底座能力调用腿（合成模块）。

技能脚本只能用本模块的 调用底座能力()；请求交给唯一网关 POST /网关/调用（操作=调用能力）。
可调能力白名单在注入时冻结在 可用能力白名单 里：白名单外的能力 id 一律拒绝，
不改走别的通道、不降级。凭证从环境变量读取，不落盘、不回传、不打印。
"""

import http.client
import json
import os
from urllib.parse import quote as _路径编码
from urllib.parse import urlsplit as _拆地址

可用能力白名单 = __注入白名单__
网关地址 = "__注入网关地址__"
凭证变量名 = "__注入凭证变量名__"
默认超时秒 = __注入超时秒__


def 查询白名单() -> list:
    """返回本次运行的可调能力白名单（只读副本）。"""
    return list(可用能力白名单)


def 调用底座能力(能力id, 参数=None, 超时秒=None) -> dict:
    """经唯一网关调用白名单内的底座能力。

    返回 {"成功", "值", "错误码", "错误说明", "状态码", "请求id"}；
    失败如实返回，不抛异常、不静默降级。
    """
    名称 = str(能力id or "").strip()
    if not 名称:
        return _失败("能力id不合法", "能力id 不能为空")
    if 名称 not in 可用能力白名单:
        return _失败("能力不在白名单", "能力 %s 不在本次可调能力白名单内（白名单: %s）" % (名称, 可用能力白名单))
    凭证 = str(os.environ.get(凭证变量名) or "")
    if not 凭证:
        return _失败("网关凭证缺失", "环境变量 %s 未设置，无法经唯一网关调用" % 凭证变量名)
    if not 凭证.isascii():
        return _失败("网关凭证非ASCII", "网关凭证含非 ASCII 字符，HTTP 请求头无法传输")
    载荷 = json.dumps(
        {"操作": "调用能力", "能力id": 名称, "参数": 参数 if isinstance(参数, dict) else {}},
        ensure_ascii=False,
    ).encode("utf-8")
    地址 = _拆地址(网关地址)
    if 地址.scheme != "http" or not 地址.hostname:
        return _失败("网关地址不合法", "只支持 http://主机:端口 形式的网关地址: %s" % 网关地址)
    连接 = None
    try:
        连接 = http.client.HTTPConnection(地址.hostname, 地址.port or 80, timeout=float(超时秒 or 默认超时秒))
        连接.request(
            "POST",
            "/" + _路径编码("网关/调用"),
            body=载荷,
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "Authorization": "Bearer " + 凭证,
            },
        )
        响应 = 连接.getresponse()
        状态码 = int(响应.status)
        正文 = 响应.read().decode("utf-8", "replace")
    except Exception as 错误:
        return _失败("网关不可达", "%s: %s" % (type(错误).__name__, 错误))
    finally:
        if 连接 is not None:
            try:
                连接.close()
            except Exception:
                pass
    try:
        信封 = json.loads(正文)
    except ValueError:
        return _失败("网关返回格式错误", "HTTP %s 返回不是合法 JSON: %s" % (状态码, 正文[:200]))
    if not isinstance(信封, dict):
        return _失败("网关返回格式错误", "HTTP %s 返回不是信封对象" % 状态码)
    返回 = {
        "成功": bool(信封.get("成功")),
        "值": 信封.get("值"),
        "错误码": str(信封.get("错误码") or ""),
        "错误说明": str(信封.get("错误说明") or ""),
        "状态码": 状态码,
        "请求id": str(信封.get("请求id") or ""),
    }
    return 返回


def _失败(错误码, 错误说明) -> dict:
    返回 = {"成功": False, "值": None, "错误码": 错误码, "错误说明": 错误说明, "状态码": 0, "请求id": ""}
    return 返回
'''


class 能力注入:
    """可调能力白名单的合成模块注入物：临时目录 + 子进程环境附加；用完必须 清理()。"""

    def __init__(self, 目录: Path, 白名单: tuple[str, ...], 环境附加: dict) -> None:
        self.目录 = 目录
        self.模块名 = 合成模块名
        self.白名单 = 白名单
        self.环境附加 = 环境附加

    def 清理(self) -> None:
        平台适配.清只读后删除树(self.目录, 忽略失败=真)


# ── 权限等级（哲学第 9 条 5 项：相对安全，用户可选的收紧手段） ────────

权限等级_纯标准库 = 1
权限等级_白名单能力 = 2
权限等级说明 = {
    权限等级_纯标准库: "纯标准库：不注入网关凭证，技能脚本只能使用标准库",
    权限等级_白名单能力: "白名单能力：注入网关凭证与合成模块，脚本只能调白名单内能力",
}


def 判定权限等级(权限等级, 白名单: tuple[str, ...]) -> tuple[int, str]:
    """归一 权限等级，返回 (生效等级, 错误说明)。

    口径（第 9 条 5 项）：这是**可选的收紧手段**，不是绝对安全边界。
      1 = 纯标准库：即使给了白名单也不注入网关凭证（用户主动收紧）
      2 = 白名单能力：要求白名单非空，否则明确报参数不合法（不静默降级）
      None（默认）= 自动：白名单非空 → 2，空 → 1，**与历史行为完全一致**（零回归）
    """
    if 权限等级 is None:
        return (权限等级_白名单能力 if 白名单 else 权限等级_纯标准库), ""
    if isinstance(权限等级, bool) or not isinstance(权限等级, int):
        return 0, f"权限等级 必须是整数型，收到 {type(权限等级).__name__}"
    if 权限等级 not in 权限等级说明:
        return 0, (f"权限等级 只支持 {权限等级_纯标准库}（纯标准库）"
                   f"或 {权限等级_白名单能力}（白名单能力）")
    if 权限等级 == 权限等级_白名单能力 and not 白名单:
        return 0, "权限等级 2（白名单能力）要求 可调能力白名单 非空；不静默降级为纯标准库"
    return 权限等级, ""


def 校验可调能力白名单(可调能力白名单) -> tuple[tuple[str, ...], str]:
    """归一化可调能力白名单；返回 (白名单, 错误说明)。空输入 → ((), "")，行为零变化。"""
    if 可调能力白名单 is None:
        return (), ""
    if isinstance(可调能力白名单, (str, bytes)) or not isinstance(可调能力白名单, (list, tuple)):
        return (), f"可调能力白名单 必须是列表型，收到 {type(可调能力白名单).__name__}"
    项列表: list[str] = []
    for 项 in 可调能力白名单:
        if not isinstance(项, str) or not 项.strip():
            return (), f"可调能力白名单 的元素必须是非空文本型能力 id，收到 {项!r}"
        项列表.append(项.strip())
    return tuple(sorted(set(项列表))), ""


def 解析网关地址() -> str:
    """网关地址：环境变量可覆盖（运维），否则用平台唯一对外端口默认值。"""
    return (os.environ.get(网关地址环境变量) or "").strip() or 默认网关地址


def 组装合成模块源码(白名单: tuple[str, ...], 网关地址: str,
                    凭证变量名: str, 超时秒: float) -> str:
    """把冻结好的白名单与网关参数写进合成模块源码（占位符替换，不用格式化以防注入）。"""
    return (
        合成模块模板
        .replace("__注入白名单__", repr(list(白名单)))
        .replace("__注入网关地址__", str(网关地址))
        .replace("__注入凭证变量名__", str(凭证变量名))
        .replace("__注入超时秒__", repr(float(超时秒)))
    )


def 创建能力注入(白名单: tuple[str, ...], 凭证: str, 超时秒: int = 默认超时秒) -> 能力注入:
    """写合成模块到临时目录并准备子进程环境附加；失败必须由调用方保证 清理()。"""
    目录 = Path(tempfile.mkdtemp(prefix=合成模块目录前缀))
    网关超时秒 = max(1.0, min(float(超时秒), 默认网关超时秒))
    try:
        (目录 / f"{合成模块名}.py").write_text(
            组装合成模块源码(白名单, 解析网关地址(), 网关凭证环境变量, 网关超时秒),
            encoding="utf-8",
        )
    except OSError:
        平台适配.清只读后删除树(目录, 忽略失败=真)
        raise
    return 能力注入(目录, 白名单, {网关凭证环境变量: str(凭证)})


# ── 环境与资源 ────────────────────────────────────────────────────

def 构造白名单环境(技能根目录: Path, 调用方环境: dict | None = None, *,
                注入路径: tuple[str, ...] = (), 注入环境: dict | None = None) -> dict:
    """只透传白名单内环境变量；调用方传入白名单外变量时抛 ValueError。

    注入路径/注入环境 只由本模块内部（可调能力白名单的合成模块与凭证注入）传入：
    调用方到不了这两个参数，走 `环境变量` 的键仍逐键过白名单（fail-closed）。
    """
    环境 = {键: 值 for 键, 值 in os.environ.items() if 键 in 环境变量白名单}
    # 注入目录排在技能根目录之前：技能包内若出现同名文件，也不能顶替平台注入的合成模块。
    环境["PYTHONPATH"] = os.pathsep.join([*[str(路径) for 路径 in 注入路径], str(技能根目录)])
    环境["PYTHONUTF8"] = "1"
    环境["PYTHONDONTWRITEBYTECODE"] = "1"
    for 键, 值 in (调用方环境 or {}).items():
        if 键 not in 环境变量白名单:
            raise ValueError(f"非法环境变量（不在白名单）: {键}")
        环境[键] = str(值)
    for 键, 值 in (注入环境 or {}).items():
        环境[str(键)] = str(值)
    return 环境


def 设置资源预算(预算: dict):
    """构造 preexec_fn：在子进程内施加 CPU 与文件大小资源上限。

    ``resource`` 是 **POSIX 专有** 模块（Windows 上根本不存在，顶层导入会让 import 本模块即崩），
    故改为在真正取用它的 `应用()` 内惰性导入，并在构造期先经 `平台适配.要求POSIX能力`
    **显式报不支持**——非 POSIX 平台不会静默降级成「技能脚本没有 CPU/文件大小上限」。
    报错放在构造期（父进程内）而非 `应用()` 内：preexec_fn 里的异常会被包装成
    SubprocessError，真实原因（平台不支持）会失真。

    保留原有降级语义：`应用()` 内 setrlimit 被内核拒绝（权限不足/该平台内核不支持该项）时
    仍不阻断技能执行——那是「上限没生效」的既有降级，与「平台根本没有 resource 能力」两回事，
    后者已在构造期显式报错。
    """
    平台适配.要求POSIX能力("resource 资源预算（CPU秒 / 文件大小上限）")

    def 应用() -> None:
        from resource import RLIMIT_CPU, RLIMIT_FSIZE, setrlimit  # 惰性导入：POSIX 专有
        try:
            cpu = int(预算.get("CPU秒", 默认超时秒))
            setrlimit(RLIMIT_CPU, (cpu, cpu))
            大小 = int(预算.get("文件大小", 默认脚本大小上限))
            setrlimit(RLIMIT_FSIZE, (大小, 大小))
        except (ValueError, OSError, AttributeError):
            pass

    return 应用


def 进程组终止(进程: subprocess.Popen) -> None:
    """向进程组发强杀信号并等待回收；子进程与孙进程一并清理（跨平台收口在收口层）。"""
    进程终止.强制结束子进程(进程, 宽限秒=5.0, 等待秒=5.0)


class _管道收集器:
    """受控脚本子进程 stdout/stderr 的**唯一后台读者**：阻塞式 `受限读取` + 交接缓冲。

    为什么不用 `select` 轮询：Windows 的 `select` 只接受 socket，对管道 fd 直接抛
    `OSError`，旧实现把它吞成「本轮无可读」→ 在 Windows 上永远收不到脚本输出，
    脚本明明成功却按「输出 JSON 非法」报错。范式与本仓
    `运行核心/加载器/提供者隔离/独立进程.py` 同源（同一 `公共契约.运行时.有界IO.受限读取`
    唯一实现）：后台线程读内核 → 回调累积到 `_缓冲` → 事件通知等待侧；
    主循环退化为「等事件 + 切片超时判超时」，**不含任何平台判断**。

    `_缓冲` 在超限后**继续排空但不再累积**（防管道回压导致子进程写阻塞）。
    """

    __slots__ = ("_缓冲", "_事件", "_条件", "_结束", "_超限", "_流", "_已核超限", "_上限字节")

    def __init__(self, 流: Any, 上限字节: int = 默认输出上限) -> None:
        self._缓冲 = bytearray()
        self._事件 = threading.Event()
        self._条件 = threading.Condition()
        self._结束 = False
        self._超限 = False
        self._已核超限 = False
        self._流 = 流
        # 上限必须来自**调用方**（`运行受控脚本` 的 输出上限）：写死成默认值会在调用方
        # 放宽上限时把多出来的字节静默丢掉（截断），是比「不读」更隐蔽的错。
        self._上限字节 = max(1, int(上限字节))

    def 启动(self) -> threading.Thread:
        线程 = threading.Thread(target=self._消费, daemon=True, name="技能库-管道收集")
        线程.start()
        return 线程

    def _消费(self) -> None:
        try:
            有界IO.受限读取(self._流, 上限字节=self._上限字节, 数据回调=self._收块,
                          超限回调=self._置超限)
        except (OSError, ValueError):
            pass
        finally:
            with self._条件:
                self._结束 = True
                self._条件.notify_all()
            self._事件.set()

    def _收块(self, 块: bytes) -> None:
        with self._条件:
            self._缓冲.extend(块)
            self._条件.notify_all()
        self._事件.set()

    def _置超限(self) -> None:
        with self._条件:
            self._超限 = True
            self._条件.notify_all()
        self._事件.set()

    def 取(self) -> tuple[bytes, bool, bool]:
        """非阻塞取走当前已累积字节，返回（片段、是否已结束、是否首次判定超限）。

        取走后清空缓冲：字节只能被搬走一次（与旧 `os.read` 从管道搬走同语义）。
        超限只在**首次**置位时返回真，避免调用方重复生成「输出超限」结论。
        """
        with self._条件:
            片段 = bytes(self._缓冲)
            self._缓冲.clear()
            结束 = self._结束
            首次超限 = self._超限 and not self._已核超限
            if 首次超限:
                self._已核超限 = True
        if not 片段:
            self._事件.clear()
        return 片段, 结束, 首次超限

    def 等(self, 超时秒: float) -> None:
        """等新数据 / EOF / 超限，最多 `超时秒`（超时正常返回，由调用方判总超时）。"""
        self._事件.wait(max(0.01, 超时秒))

    def 已结束(self) -> bool:
        """后台读线程是否已 EOF（管道读完）；配合「进程已退出」判收口。"""
        with self._条件:
            return self._结束


# ── 脚本源码审计（AST） ────────────────────────────────────────────

def _属性链名(节点: ast.AST) -> str:
    片段: list[str] = []
    当前 = 节点
    while isinstance(当前, ast.Attribute):
        片段.append(当前.attr)
        当前 = 当前.value
    if isinstance(当前, ast.Name):
        片段.append(当前.id)
    return ".".join(reversed(片段))


def _收集导入别名(树: ast.AST) -> dict[str, str]:
    别名: dict[str, str] = {}
    for 节点 in ast.walk(树):
        if isinstance(节点, ast.Import):
            for 项 in 节点.names:
                别名[项.asname or 项.name.split(".")[0]] = 项.name
        elif isinstance(节点, ast.ImportFrom) and 节点.module:
            别名[节点.module.split(".")[0]] = 节点.module
            for 项 in 节点.names:
                # from os import system → 别名[system] = os.system（供调用链比对）
                别名.setdefault(项.asname or 项.name, f"{节点.module}.{项.name}")
    return 别名


def _解析调用真名(节点: ast.AST, 别名: dict[str, str]) -> str:
    """把调用表达式解析成尽可能完整的点分真名，用于禁入调用链比对。"""
    if isinstance(节点, ast.Name):
        return 别名.get(节点.id, 节点.id)
    if isinstance(节点, ast.Attribute):
        链 = _属性链名(节点)
        根, _, 尾 = 链.partition(".")
        真根 = 别名.get(根, 根)
        return f"{真根}.{尾}" if 尾 else 真根
    return ""


def _审计导入(模块名: str, 禁止导入前缀: tuple[str, ...],
             允许导入模块: frozenset[str] = frozenset()) -> list[str]:
    """审计单个导入：标准库与本次注入的合成模块放行，硬禁止、调用方禁入前缀、其余非标准库一律拦截。"""
    顶层 = (模块名 or "").split(".")[0]
    违规: list[str] = []
    if 顶层 in 硬禁止导入模块:
        违规.append(f"禁止导入模块: {模块名}")
    elif any(模块名 == 前缀 or 模块名.startswith(前缀 + ".") for 前缀 in 禁止导入前缀):
        违规.append(f"禁止导入项目模块: {模块名}")
    elif 顶层 and 顶层 not in 标准库模块集合 and 顶层 not in 允许导入模块:
        违规.append(f"禁止导入非标准库模块: {模块名}")
    return 违规


def 审计脚本源码(脚本源码: str, 禁止导入前缀: tuple[str, ...] = (),
             允许导入模块: frozenset[str] = frozenset()) -> list[str]:
    """静态审计技能脚本：返回违规说明列表（空列表 = 通过）。

    `允许导入模块` 只有「可调能力白名单非空」这一种来源，且只含平台注入的合成模块名；
    默认空集 = 历史行为（技能脚本只能纯标准库）。
    """
    try:
        树 = ast.parse(脚本源码)
    except SyntaxError as 错误:
        return [f"脚本语法错误: {错误}"]
    违规: list[str] = []
    别名 = _收集导入别名(树)
    for 节点 in ast.walk(树):
        if isinstance(节点, (ast.Import, ast.ImportFrom)):
            模块名 = 节点.module if isinstance(节点, ast.ImportFrom) else None
            if isinstance(节点, ast.Import):
                for 项 in 节点.names:
                    违规.extend(_审计导入(项.name, 禁止导入前缀, 允许导入模块))
            elif 模块名:
                违规.extend(_审计导入(模块名, 禁止导入前缀, 允许导入模块))
        elif isinstance(节点, ast.Call):
            调用真名 = _解析调用真名(节点.func, 别名)
            if isinstance(节点.func, ast.Name) and 节点.func.id in 硬禁止调用标记:
                违规.append(f"禁止调用: {节点.func.id}")
            elif 调用真名 in 硬禁止调用链:
                违规.append(f"禁止调用: {调用真名}")
            if isinstance(节点.func, ast.Attribute):
                链 = _属性链名(节点.func)
                根 = 链.split(".")[0]
                根真名 = 别名.get(根, 根)
                if 根真名 in 硬禁止导入模块:
                    违规.append(f"禁止调用: {链}")
                for 关键字 in 节点.keywords:
                    if 关键字.arg == "shell" and isinstance(关键字.value, ast.Constant) and 关键字.value.value is 真:
                        违规.append("禁止 shell=True")
    return sorted(set(违规))


# ── 技能包解析 ────────────────────────────────────────────────────

def 校验技能包结构(技能目录: Path) -> list[str]:
    """校验六件套是否齐全；返回缺失项列表（空 = 完整）。"""
    目录 = Path(技能目录)
    if not 目录.is_dir():
        return ["技能目录不存在"]
    缺失 = [名 for 名 in 技能包必需文件 if not (目录 / 名).is_file()]
    if not (目录 / "scripts").is_dir():
        缺失.append("scripts/")
    return 缺失


def 解析技能包(技能根目录: Path, 能力标识: str) -> Path:
    """只按技能索引白名单解析技能包，并核对索引与契约能力标识一致。"""
    根 = Path(技能根目录).resolve()
    索引路径 = 根 / "索引.json"
    try:
        索引 = json.loads(索引路径.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as 错误:
        raise ValueError(f"技能索引不可用: {错误}") from 错误
    命中 = [
        项 for 项 in (索引.get("能力列表") or [])
        if isinstance(项, dict) and 项.get("能力标识") == 能力标识
    ]
    if not 命中:
        raise ValueError(f"能力标识 {能力标识} 未登记技能索引")
    if len(命中) > 1:
        raise ValueError(f"能力标识 {能力标识} 在技能索引中重复登记")
    相对路径 = str(命中[0].get("路径") or "").strip()
    if not 相对路径:
        raise ValueError(f"能力标识 {能力标识} 的索引路径为空")
    技能目录 = (根 / 相对路径).resolve()
    try:
        技能目录.relative_to(根)
    except ValueError as 错误:
        raise ValueError(f"能力标识 {能力标识} 的索引路径逃逸") from 错误
    try:
        契约 = json.loads((技能目录 / "契约.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as 错误:
        raise ValueError(f"能力标识 {能力标识} 的契约不可用: {错误}") from 错误
    if 契约.get("能力标识") != 能力标识:
        raise ValueError(f"能力标识 {能力标识} 的索引与契约不一致")
    return 技能目录


def 解析入口脚本(技能目录: Path, 入口脚本名: str) -> Path:
    """解析 scripts/ 下的入口脚本并做路径范围校验；越界抛 ValueError。"""
    scripts目录 = (Path(技能目录) / "scripts").resolve()
    if not scripts目录.is_dir():
        raise ValueError("技能包缺少 scripts/ 目录")
    脚本路径 = (scripts目录 / 入口脚本名).resolve()
    if scripts目录 not in 脚本路径.parents and 脚本路径.parent != scripts目录:
        raise ValueError(f"脚本路径逃逸: {入口脚本名}")
    return 脚本路径


# ── 受控运行 ──────────────────────────────────────────────────────

def 运行受控脚本(
    脚本路径: Path | str,
    参数: dict | None = None,
    *,
    技能根目录: Path | str,
    超时秒: int = 默认超时秒,
    输出上限: int = 默认输出上限,
    环境变量: dict | None = None,
    资源预算: dict | None = None,
    能力注入: 能力注入 | None = None,
) -> dict:
    """受控运行单个脚本，返回 {"成功": bool, ...}；违规输入一律 fail-closed。

    `能力注入` 非空时：合成模块目录进 PYTHONPATH 首位、网关凭证进子进程环境；
    默认 None = 与历史版本完全一致（子进程只见白名单环境变量与技能根目录）。
    """
    脚本路径 = Path(脚本路径).resolve()
    根 = Path(技能根目录).resolve()
    if 脚本路径 != 根 and 根 not in 脚本路径.parents:
        return {"成功": 假, "错误码": "脚本路径逃逸", "错误信息": f"脚本不在技能根目录内: {脚本路径}"}
    try:
        环境 = 构造白名单环境(
            根,
            环境变量,
            注入路径=(str(能力注入.目录),) if 能力注入 else (),
            注入环境=能力注入.环境附加 if 能力注入 else None,
        )
    except ValueError as 错误:
        return {"成功": 假, "错误码": "非法环境变量", "错误信息": str(错误)}
    预算 = dict(资源预算 or {})
    预算.setdefault("CPU秒", 超时秒)
    预算.setdefault("文件大小", max(输出上限, 默认脚本大小上限))
    try:
        进程 = subprocess.Popen(
            [固定解释器, str(脚本路径)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=str(根),
            env=环境,
            **平台适配.子进程组启动标志(),
            preexec_fn=设置资源预算(预算),
        )
    except OSError as 错误:
        return {"成功": 假, "错误码": "启动失败", "错误信息": str(错误)}
    开始 = time.monotonic()
    输出 = bytearray()
    错误输出 = bytearray()
    # stdout/stderr 的唯一读者：后台线程 + 有界IO.受限读取（不 select 轮询管道 fd）。
    # 必须在写 stdin 之前起线程，避免子进程先输出把管道写满、父进程同时写 stdin 死锁。
    收集器 = [(_管道收集器(流, 输出上限), 容器)
            for 流, 容器 in ((进程.stdout, 输出), (进程.stderr, 错误输出)) if 流 is not None]
    try:
        for 收集, _容器 in 收集器:
            收集.启动()
    except (OSError, ValueError, RuntimeError):
        pass
    try:
        进程.stdin.write(json.dumps({"参数": 参数 or {}}, ensure_ascii=False).encode("utf-8"))
        进程.stdin.close()
    except (BrokenPipeError, OSError):
        pass
    结果: dict | None = None
    while True:
        if time.monotonic() - 开始 > 超时秒:
            进程组终止(进程)
            结果 = {
                "成功": 假,
                "错误码": "超时",
                "错误信息": f"脚本执行超过 {超时秒} 秒",
                "标准错误": 错误输出.decode("utf-8", "replace")[-500:],
            }
            break
        # 先排空（把后台线程已交接的字节搬进容器），再判是否结束 ——
        # 顺序反了会在「子进程刚退出、后台线程还有缓冲」时提前 break 丢掉尾部输出。
        # ⚠️ 管道字节已被后台线程搬走：这里**绝不能**再直接 `进程.stdout.read()`
        # （那是第二个读者，只会拿到空串，把正常输出判成「非法 JSON」）。
        for 收集, 容器 in 收集器:
            片段, _结束, 首次超限 = 收集.取()
            容器.extend(片段)
            if 首次超限:
                进程组终止(进程)
                结果 = {"成功": 假, "错误码": "输出超限",
                        "错误信息": f"{'stdout' if 容器 is 输出 else 'stderr'} 超过 {输出上限} 字节"}
                break
        if 结果 is not None:
            break
        if 进程.poll() is not None and all(收集.已结束() for 收集, _容器 in 收集器):
            # 进程已退出且两条管道都 EOF/排空 → 再取一次尾部字节后收口
            for 收集, 容器 in 收集器:
                片段, _结束, _首次超限 = 收集.取()
                容器.extend(片段)
            break
        for 收集, _容器 in 收集器:
            收集.等(0.5)
    if 结果 is not None:
        结果.setdefault("耗时秒", round(time.monotonic() - 开始, 3))
        return 结果
    退出码 = 进程.returncode
    文本 = 输出.decode("utf-8", "replace")
    错误文本 = 错误输出.decode("utf-8", "replace")
    if 退出码 != 0:
        return {
            "成功": 假,
            "错误码": "脚本非零退出",
            "错误信息": f"退出码 {退出码}",
            "标准错误": 错误文本[-2000:],
            "耗时秒": round(time.monotonic() - 开始, 3),
        }
    try:
        解析结果 = json.loads(文本.strip() or "{}")
    except json.JSONDecodeError:
        return {
            "成功": 假,
            "错误码": "输出格式错误",
            "错误信息": "脚本 stdout 不是合法 JSON",
            "标准输出": 文本[-2000:],
            "耗时秒": round(time.monotonic() - 开始, 3),
        }
    if isinstance(解析结果, dict):
        解析结果.setdefault("耗时秒", round(time.monotonic() - 开始, 3))
        解析结果["成功"] = 真
        return 解析结果
    return {"成功": 真, "结果": 解析结果, "耗时秒": round(time.monotonic() - 开始, 3)}


# ── 对外三个能力 ──────────────────────────────────────────────────

def 校验技能包(技能根目录: str = None, 技能标识或路径: str = None) -> 结果:
    """能力 技能库.技能包.校验技能包：结构校验 + 契约可读性。"""
    根 = Path(技能根目录 or "").resolve()
    标识 = (技能标识或路径 or "").strip()
    if not 技能根目录 or not 标识:
        return 结果.失败("参数不合法", "技能根目录 与 技能标识或路径 必填", 来源=来源标识)
    if not 根.is_dir():
        return 结果.失败("目录不存在", f"技能根目录不存在: {根}", 来源=来源标识)
    try:
        技能目录 = 解析技能包(根, 标识)
        来源 = "索引"
    except ValueError:
        候选 = (根 / 标识).resolve()
        if 候选.is_dir() and (根 in 候选.parents or 候选 == 根):
            技能目录, 来源 = 候选, "路径"
        else:
            return 结果.失败("技能未找到", f"既不在索引中，也不是根目录下的合法子目录: {标识}", 来源=来源标识)
    缺失 = 校验技能包结构(技能目录)
    契约错误 = ""
    try:
        json.loads((技能目录 / "契约.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as 错误:
        契约错误 = str(错误)
    通过 = not 缺失 and not 契约错误
    值 = {"通过": 通过, "技能目录": str(技能目录), "来源": 来源, "缺失": 缺失}
    if 契约错误:
        值["契约错误"] = 契约错误
    return 结果.成功结果(值)


def 运行技能包(
    技能根目录: str = None,
    能力标识: str = None,
    参数: dict | None = None,
    超时秒: int = 默认超时秒,
    输出上限: int = 默认输出上限,
    环境变量: dict | None = None,
    禁止导入前缀: list | None = None,
    项目根目录: str | None = None,
    可调能力白名单: list | None = None,
    权限等级: int | None = None,
) -> 结果:
    """能力 技能库.受控执行.运行技能包：结构校验 → 定位入口 → 导入审计 → 受控运行。

    `可调能力白名单`（可选，默认空）：空 = 技能脚本只能纯标准库，行为与历史版本完全一致；
    非空 = 把合成模块 `技能底座能力` 注入子进程并放行其导入，技能脚本经它走唯一网关
    HTTP 调用白名单内的底座能力；白名单外一律拒绝（不降级），第三方/进程派生/项目模块
    导入一并不放开。

    `权限等级`（可选，默认 None=自动）：第 9 条 5 项「相对安全、用户自选」的落地——
    1=纯标准库（给了白名单也不注入凭证，用户主动收紧）、2=白名单能力（要求白名单非空）、
    None=自动（白名单非空→2、空→1，与历史版本行为完全一致）。**这是相对安全，不是绝对边界**：
    白名单只是静态导入审计，运行期脚本仍持有网关凭证；要更强隔离请在私有部署侧自行加系统级沙箱。
    """
    if not 技能根目录 or not 能力标识:
        return 结果.失败("参数不合法", "技能根目录 与 能力标识 必填", 来源=来源标识)
    白名单, 白名单问题 = 校验可调能力白名单(可调能力白名单)
    if 白名单问题:
        return 结果.失败("参数不合法", 白名单问题, 来源=来源标识)
    生效等级, 等级问题 = 判定权限等级(权限等级, 白名单)
    if 等级问题:
        return 结果.失败("参数不合法", 等级问题, 来源=来源标识)
    允许注入能力 = 生效等级 == 权限等级_白名单能力 and bool(白名单)
    根 = Path(技能根目录).resolve()
    if not 根.is_dir():
        return 结果.失败("目录不存在", f"技能根目录不存在: {根}", 来源=来源标识)
    try:
        技能目录 = 解析技能包(根, 能力标识)
    except ValueError as 错误:
        return 结果.失败("技能未找到", str(错误), 来源=来源标识)
    缺失 = 校验技能包结构(技能目录)
    if 缺失:
        return 结果.失败("结构不完整", f"技能包结构缺失: {缺失}", 来源=来源标识, 详情={"缺失": 缺失})
    try:
        工作流 = json.loads((技能目录 / "工作流.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as 错误:
        return 结果.失败("工作流无效", str(错误), 来源=来源标识)
    入口脚本名 = str(工作流.get("入口脚本") or "").strip()
    if not 入口脚本名:
        return 结果.失败("缺少入口脚本", "工作流.json 未声明 入口脚本", 来源=来源标识)
    try:
        脚本路径 = 解析入口脚本(技能目录, 入口脚本名)
    except ValueError as 错误:
        return 结果.失败("脚本路径逃逸", str(错误), 来源=来源标识)
    try:
        源码 = 脚本路径.read_text(encoding="utf-8")
    except OSError as 错误:
        return 结果.失败("脚本读取失败", str(错误), 来源=来源标识)
    违规 = 审计脚本源码(
        源码,
        tuple(禁止导入前缀 or ()),
        frozenset({合成模块名}) if 允许注入能力 else frozenset(),
    )
    if 违规:
        return 结果.失败("脚本审计未通过", "脚本未通过导入审计", 来源=来源标识, 详情={"违规": 违规})
    注入物: 能力注入 | None = None
    if 允许注入能力:
        凭证 = (os.environ.get(网关凭证环境变量) or "").strip()
        if not 凭证:
            return 结果.失败(
                "能力调用凭证缺失",
                f"可调能力白名单非空时必须经唯一网关调用，环境变量 {网关凭证环境变量} 未设置",
                来源=来源标识,
                详情={"可调能力白名单": list(白名单), "凭证环境变量": 网关凭证环境变量},
            )
        try:
            注入物 = 创建能力注入(白名单, 凭证, 超时秒)
        except OSError as 错误:
            return 结果.失败("启动失败", f"合成模块注入失败: {错误}", 来源=来源标识)
    try:
        运行结果 = 运行受控脚本(
            脚本路径,
            参数,
            技能根目录=Path(项目根目录).resolve() if 项目根目录 else 根,
            超时秒=超时秒,
            输出上限=输出上限,
            环境变量=环境变量,
            能力注入=注入物,
        )
    finally:
        if 注入物 is not None:
            注入物.清理()
    if not 运行结果.get("成功"):
        return 结果.失败(
            运行结果.get("错误码") or "脚本执行失败",
            运行结果.get("错误信息") or "",
            来源=来源标识,
            详情={k: v for k, v in 运行结果.items() if k not in ("成功", "错误码", "错误信息")},
        )
    返回数据 = {k: v for k, v in 运行结果.items() if k != "成功"}
    返回数据["权限等级"] = 生效等级
    返回数据["权限等级说明"] = 权限等级说明[生效等级]
    return 结果.成功结果(返回数据)


def 扫描技能包(技能根目录: str = None) -> 结果:
    """能力 技能库.技能索引.扫描技能包：扫描索引与目录，返回技能清单与结构问题。"""
    if not 技能根目录:
        return 结果.失败("参数不合法", "技能根目录 必填", 来源=来源标识)
    根 = Path(技能根目录).resolve()
    if not 根.is_dir():
        return 结果.失败("目录不存在", f"技能根目录不存在: {根}", 来源=来源标识)
    列表: list[dict] = []
    try:
        索引 = json.loads((根 / "索引.json").read_text(encoding="utf-8"))
        登记项 = [项 for 项 in (索引.get("能力列表") or []) if isinstance(项, dict)]
    except (OSError, json.JSONDecodeError):
        登记项 = []
    for 项 in 登记项:
        标识 = str(项.get("能力标识") or "").strip()
        相对 = str(项.get("路径") or "").strip()
        if not 标识 or not 相对:
            continue
        目录 = (根 / 相对).resolve()
        try:
            目录.relative_to(根)
            在范围内 = 真
        except ValueError:
            在范围内 = 假
        缺失 = 校验技能包结构(目录) if (在范围内 and 目录.is_dir()) else ["技能目录不存在或路径逃逸"]
        列表.append({
            "能力标识": 标识,
            "路径": 相对,
            "完整": not 缺失,
            "缺失": 缺失,
        })
    return 结果.成功结果({"数量": len(列表), "技能列表": 列表})


# ── 索引构建（迁移自 V3 技能包校验器：读取契约 / 从契约派生索引 / 发现技能包目录） ──

def 读取技能契约(技能目录: Path) -> dict:
    """读技能包的 契约.json；缺失或损坏返回空字典。"""
    路径 = Path(技能目录) / "契约.json"
    if not 路径.is_file():
        return {}
    try:
        数据 = json.loads(路径.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return 数据 if isinstance(数据, dict) else {}


def 从契约派生索引条目(契约: dict) -> dict:
    """从 契约.json 派生索引条目：参数事实唯一源始终是契约，不复制第二套。"""
    return {
        "能力标识": 契约.get("能力标识", ""),
        "名称": 契约.get("名称", ""),
        "分类": 契约.get("分类", ""),
        "版本": 契约.get("版本", ""),
        "执行入口": 契约.get("执行入口", "脚本执行器"),
        "路径": 契约.get("路径", ""),
    }


def 生成技能索引(技能根目录: str = None, 写回索引: bool = 真) -> 结果:
    """能力 技能库.技能索引.生成索引：扫描全部技能包，从契约派生索引并（可选）写回。"""
    if not 技能根目录:
        return 结果.失败("参数不合法", "技能根目录 必填", 来源=来源标识)
    根 = Path(技能根目录).resolve()
    if not 根.is_dir():
        return 结果.失败("目录不存在", f"技能根目录不存在: {根}", 来源=来源标识)
    条目列表: list[dict] = []
    跳过: list[dict] = []
    for 契约路径 in sorted(根.rglob("契约.json")):
        技能目录 = 契约路径.parent.resolve()
        try:
            技能目录.relative_to(根)
        except ValueError:
            跳过.append({"路径": str(技能目录), "原因": "路径逃逸"})
            continue
        契约 = 读取技能契约(技能目录)
        if not 契约.get("能力标识"):
            跳过.append({"路径": str(技能目录.relative_to(根)), "原因": "契约缺少能力标识"})
            continue
        缺失 = 校验技能包结构(技能目录)
        if 缺失:
            跳过.append({"路径": str(技能目录.relative_to(根)), "原因": f"结构缺失: {缺失}"})
            continue
        条目 = 从契约派生索引条目(契约)
        条目["路径"] = str(技能目录.relative_to(根))
        条目列表.append(条目)
    重复 = sorted({e["能力标识"] for e in 条目列表 if [x["能力标识"] for x in 条目列表].count(e["能力标识"]) > 1})
    结果值 = {"数量": len(条目列表), "能力列表": 条目列表, "跳过": 跳过, "重复标识": 重复}
    if 写回索引:
        索引路径 = 根 / "索引.json"
        try:
            原索引 = json.loads(索引路径.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            原索引 = {}
        新索引 = dict(原索引)
        新索引["能力列表"] = 条目列表
        try:
            索引路径.write_text(json.dumps(新索引, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            结果值["已写回"] = str(索引路径)
        except OSError as 错误:
            结果值["写回失败"] = str(错误)
    return 结果.成功结果(结果值)
