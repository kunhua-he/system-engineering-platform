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
- 超时与进程组回收：start_new_session 独立进程组，超时 killpg 连孙进程一并回收。
- 输出上限：stdout 超限立即终止并返回 输出超限。
- 环境变量白名单：只透传白名单内变量；调用方传白名单外变量直接拒绝。
- 路径范围校验：技能目录、入口脚本、工作目录必须位于技能根目录内。
- 资源预算：RLIMIT_CPU / RLIMIT_FSIZE。
- 导入审计（AST）：禁止 shell=True、eval/exec/compile、__import__/importlib 动态加载、
  subprocess/os 命令执行、第三方库；调用方可用「禁止导入前缀」追加项目级禁入项。
"""

from __future__ import annotations

import ast
import contextlib
import json
import os
import resource
import select
import signal
import subprocess
import sys
import time
from pathlib import Path

from 公共契约.基础类型.结果类型 import 结果

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


# ── 环境与资源 ────────────────────────────────────────────────────

def 构造白名单环境(技能根目录: Path, 调用方环境: dict | None = None) -> dict:
    """只透传白名单内环境变量；调用方传入白名单外变量时抛 ValueError。"""
    环境 = {键: 值 for 键, 值 in os.environ.items() if 键 in 环境变量白名单}
    环境["PYTHONPATH"] = str(技能根目录)
    环境["PYTHONUTF8"] = "1"
    环境["PYTHONDONTWRITEBYTECODE"] = "1"
    for 键, 值 in (调用方环境 or {}).items():
        if 键 not in 环境变量白名单:
            raise ValueError(f"非法环境变量（不在白名单）: {键}")
        环境[键] = str(值)
    return 环境


def 设置资源预算(预算: dict):
    """构造 preexec_fn：在子进程内施加 CPU 与文件大小资源上限。"""

    def 应用() -> None:
        try:
            cpu = int(预算.get("CPU秒", 默认超时秒))
            resource.setrlimit(resource.RLIMIT_CPU, (cpu, cpu))
            大小 = int(预算.get("文件大小", 默认脚本大小上限))
            resource.setrlimit(resource.RLIMIT_FSIZE, (大小, 大小))
        except (ValueError, OSError, AttributeError):
            pass

    return 应用


def 进程组终止(进程: subprocess.Popen) -> None:
    """向进程组发 SIGKILL 并等待回收；子进程与孙进程一并清理。"""
    with contextlib.suppress(ProcessLookupError, PermissionError, AttributeError):
        os.killpg(进程.pid, signal.SIGKILL)
    try:
        进程.wait(timeout=5)
    except subprocess.TimeoutExpired:
        进程.kill()
        with contextlib.suppress(subprocess.TimeoutExpired):
            进程.wait(timeout=5)


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


def _审计导入(模块名: str, 禁止导入前缀: tuple[str, ...]) -> list[str]:
    """审计单个导入：标准库放行，硬禁止与调用方禁入前缀一律拦截，其余（第三方/项目模块）拦截。"""
    顶层 = (模块名 or "").split(".")[0]
    违规: list[str] = []
    if 顶层 in 硬禁止导入模块:
        违规.append(f"禁止导入模块: {模块名}")
    elif any(模块名 == 前缀 or 模块名.startswith(前缀 + ".") for 前缀 in 禁止导入前缀):
        违规.append(f"禁止导入项目模块: {模块名}")
    elif 顶层 and 顶层 not in 标准库模块集合:
        违规.append(f"禁止导入非标准库模块: {模块名}")
    return 违规


def 审计脚本源码(脚本源码: str, 禁止导入前缀: tuple[str, ...] = ()) -> list[str]:
    """静态审计技能脚本：返回违规说明列表（空列表 = 通过）。"""
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
                    违规.extend(_审计导入(项.name, 禁止导入前缀))
            elif 模块名:
                违规.extend(_审计导入(模块名, 禁止导入前缀))
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
                    if 关键字.arg == "shell" and isinstance(关键字.value, ast.Constant) and 关键字.value.value is True:
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
) -> dict:
    """受控运行单个脚本，返回 {"成功": bool, ...}；违规输入一律 fail-closed。"""
    脚本路径 = Path(脚本路径).resolve()
    根 = Path(技能根目录).resolve()
    if 脚本路径 != 根 and 根 not in 脚本路径.parents:
        return {"成功": False, "错误码": "脚本路径逃逸", "错误信息": f"脚本不在技能根目录内: {脚本路径}"}
    try:
        环境 = 构造白名单环境(根, 环境变量)
    except ValueError as 错误:
        return {"成功": False, "错误码": "非法环境变量", "错误信息": str(错误)}
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
            start_new_session=True,
            preexec_fn=设置资源预算(预算),
        )
    except OSError as 错误:
        return {"成功": False, "错误码": "启动失败", "错误信息": str(错误)}
    开始 = time.monotonic()
    输出 = bytearray()
    错误输出 = bytearray()
    try:
        进程.stdin.write(json.dumps({"参数": 参数 or {}}, ensure_ascii=False).encode("utf-8"))
        进程.stdin.close()
    except (BrokenPipeError, OSError):
        pass
    结果: dict | None = None
    while True:
        if 进程.poll() is not None:
            for 管道, 容器 in ((进程.stdout, 输出), (进程.stderr, 错误输出)):
                try:
                    块 = 管道.read()
                except Exception:
                    块 = b""
                容器.extend(块 or b"")
            break
        if time.monotonic() - 开始 > 超时秒:
            进程组终止(进程)
            结果 = {
                "成功": False,
                "错误码": "超时",
                "错误信息": f"脚本执行超过 {超时秒} 秒",
                "标准错误": 错误输出.decode("utf-8", "replace")[-500:],
            }
            break
        try:
            可读, _, _ = select.select([进程.stdout, 进程.stderr], [], [], 0.5)
        except ValueError:
            可读 = []
        for 管道 in 可读:
            try:
                块 = os.read(管道.fileno(), 65536)
            except OSError:
                块 = b""
            if 管道 is 进程.stdout:
                输出.extend(块)
                if len(输出) > 输出上限:
                    进程组终止(进程)
                    结果 = {"成功": False, "错误码": "输出超限", "错误信息": f"stdout 超过 {输出上限} 字节"}
                    break
            else:
                错误输出.extend(块)
        if 结果 is not None:
            break
    if 结果 is not None:
        结果.setdefault("耗时秒", round(time.monotonic() - 开始, 3))
        return 结果
    退出码 = 进程.returncode
    文本 = 输出.decode("utf-8", "replace")
    错误文本 = 错误输出.decode("utf-8", "replace")
    if 退出码 != 0:
        return {
            "成功": False,
            "错误码": "脚本非零退出",
            "错误信息": f"退出码 {退出码}",
            "标准错误": 错误文本[-2000:],
            "耗时秒": round(time.monotonic() - 开始, 3),
        }
    try:
        解析结果 = json.loads(文本.strip() or "{}")
    except json.JSONDecodeError:
        return {
            "成功": False,
            "错误码": "输出格式错误",
            "错误信息": "脚本 stdout 不是合法 JSON",
            "标准输出": 文本[-2000:],
            "耗时秒": round(time.monotonic() - 开始, 3),
        }
    if isinstance(解析结果, dict):
        解析结果.setdefault("耗时秒", round(time.monotonic() - 开始, 3))
        解析结果["成功"] = True
        return 解析结果
    return {"成功": True, "结果": 解析结果, "耗时秒": round(time.monotonic() - 开始, 3)}


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
) -> 结果:
    """能力 技能库.受控执行.运行技能包：结构校验 → 定位入口 → 导入审计 → 受控运行。"""
    if not 技能根目录 or not 能力标识:
        return 结果.失败("参数不合法", "技能根目录 与 能力标识 必填", 来源=来源标识)
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
    违规 = 审计脚本源码(源码, tuple(禁止导入前缀 or ()))
    if 违规:
        return 结果.失败("脚本审计未通过", "脚本未通过导入审计", 来源=来源标识, 详情={"违规": 违规})
    运行结果 = 运行受控脚本(
        脚本路径,
        参数,
        技能根目录=Path(项目根目录).resolve() if 项目根目录 else 根,
        超时秒=超时秒,
        输出上限=输出上限,
        环境变量=环境变量,
    )
    if not 运行结果.get("成功"):
        return 结果.失败(
            运行结果.get("错误码") or "脚本执行失败",
            运行结果.get("错误信息") or "",
            来源=来源标识,
            详情={k: v for k, v in 运行结果.items() if k not in ("成功", "错误码", "错误信息")},
        )
    return 结果.成功结果({k: v for k, v in 运行结果.items() if k != "成功"})


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
            在范围内 = True
        except ValueError:
            在范围内 = False
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


def 生成技能索引(技能根目录: str = None, 写回索引: bool = True) -> 结果:
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
