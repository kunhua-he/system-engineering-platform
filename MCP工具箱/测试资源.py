"""测试临时资源登记与安全清理。只清理登记且位于受控临时根内的资源。

支持资源类型：文件、目录、子进程（终止进程组防残留）、端口（终止占用进程并验证释放）、
线程（验证已结束）、句柄（验证已关闭）。清理失败不抛异常，返回失败表并保留证据到
临时根目录/清理失败.json；提供证据目录时额外写入
工程缓存/清理失败证据/{work_id}.json（与测试中心独立模块验证语义对齐）；成功=False 时调用方必须感知。

安全边界（S2）：
- 临时根必须位于 工程缓存/ 下（MCP 工具入口固定 工程缓存/测试临时/，不接受调用者任意参数）；
- 子进程/端口登记时校验 pid 归属：只允许本进程派生集合内的 pid
  （父进程链可达当前进程或已注入 _已启动子进程pid集合），防止登记任意第三方进程；
- 清理前复核 pid 仍属于本进程派生集合，否则拒绝清理（防清单伪造）。
"""

from __future__ import annotations

import json
import os
import shutil
import signal
import socket
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any

# 线程对象与句柄对象无法写入清单 JSON，登记时按资源路径登记到进程内注册表，
# 清理时取出对象验证真实状态（线程是否结束、句柄是否关闭）。
_对象注册表: dict[str, Any] = {}

# 本进程已启动子进程 pid 集合：登记入口主动注入或登记时按父进程链自动登记；
# 清理前复核 pid 必须仍属于该集合（进程内防伪造）。
_已启动子进程pid集合: set[int] = set()

_工程缓存名 = "工程缓存"


def 登记已启动子进程(pid: int) -> None:
    """派生方启动子进程后主动注入 pid（登记入口信任集合内的 pid）。"""
    try:
        _已启动子进程pid集合.add(int(pid))
    except (TypeError, ValueError):
        raise ValueError(f"pid 必须是整数: {pid!r}")


def _校验临时根(临时根目录: Path) -> Path:
    """临时根必须位于某个 工程缓存/ 目录之下（测试临时/、验证运行/、任务工作区/ 等）。

    以路径链中的 工程缓存 目录为锚点：允许任意项目根的 工程缓存/ 子目录，
    但不允许把 工程缓存 本身或 工程缓存 之外 的路径作为临时根。
    """
    根 = Path(临时根目录).resolve()
    候选 = 根
    while True:
        if 候选.name == _工程缓存名:
            if 根 == 候选:
                raise ValueError(f"临时根不能是 工程缓存 本身: {根}")
            return 根
        候选 = 候选.parent
        if 候选 == 候选.parent:
            break
    raise ValueError(f"临时根必须位于 工程缓存/ 下: {根}")


def _父进程id(pid: int) -> int | None:
    """查询 pid 的父进程 pid；查不到返回 None。"""
    try:
        进程 = subprocess.run(
            ["ps", "-o", "ppid=", "-p", str(pid)],
            capture_output=True, text=True, timeout=5,
        )
        if 进程.returncode == 0 and 进程.stdout.strip().isdigit():
            return int(进程.stdout.strip())
    except (OSError, subprocess.TimeoutExpired, ValueError):
        pass
    return None


def _是当前进程后代(pid: int) -> bool:
    """pid 的父进程链中是否包含当前进程（本网关/本进程直接或间接派生）。"""
    已见: set[int] = set()
    while pid and pid not in 已见 and len(已见) < 64:
        已见.add(pid)
        if pid == os.getpid():
            return True
        pid = _父进程id(pid)
    return False


def _校验进程归属(pid: int, 资源类型: str) -> int:
    """子进程/端口登记：pid 必须属于本进程派生集合，否则拒绝登记。"""
    pid = int(pid)
    if pid in _已启动子进程pid集合:
        return pid
    if pid == os.getpid() or _是当前进程后代(pid):
        _已启动子进程pid集合.add(pid)
        return pid
    raise ValueError(
        f"拒绝登记 {资源类型}: pid {pid} 不是本进程已启动的子进程"
    )


def _复核清理归属(pid: int, 标识: str) -> None:
    """清理前复核：pid 仍属于本进程派生集合，否则拒绝（防清单伪造）。"""
    if pid in _已启动子进程pid集合:
        return
    if pid == os.getpid() or _是当前进程后代(pid):
        _已启动子进程pid集合.add(pid)
        return
    raise OSError(f"拒绝清理 {标识}: pid {pid} 不属于本进程派生集合")


def 登记资源(清单路径: Path, *, 资源路径: str, 临时根目录: Path,
             资源类型: str = "文件", 保留: bool = False,
             附加信息: Any = None, work_id: str | None = None) -> dict[str, Any]:
    """登记一条测试临时资源。

    资源路径：文件/目录为真实路径；子进程为"子进程:<pid>"；端口为"端口:<端口号>"；
    线程为"线程:<标识>"；句柄为"句柄:<描述>"。
    附加信息：子进程传 {"pid": 整数}；端口传 {"端口": 整数, "占用pid": 整数}；
    线程传线程对象；句柄传句柄对象。
    work_id：可选登记维度，写入记录后关闭工作区可按维度定位与清理。

    S2 安全边界：临时根必须位于 工程缓存/ 下；子进程/端口 pid 必须是
    本进程派生集合内的 pid（父进程链可达当前进程或已注入），否则拒绝登记。
    """
    根 = _校验临时根(临时根目录)
    目标 = Path(资源路径).resolve()
    if 资源类型 in ("文件", "目录") and not str(目标).startswith(f"{根}{os.sep}"):
        raise ValueError("只能登记临时根目录内的资源")
    if 资源类型 == "子进程":
        pid = _推导pid(附加信息, 目标)
        _校验进程归属(pid, "子进程")
    elif 资源类型 == "端口":
        占用pid = _端口占用pid(附加信息, 目标)
        if 占用pid is not None:
            _校验进程归属(占用pid, "端口")
    标识 = _推导标识(资源类型, 目标, 附加信息)
    记录: dict[str, Any] = {"路径": str(目标), "类型": 资源类型,
                            "保留": bool(保留), "标识": 标识}
    if work_id:
        记录["work_id"] = str(work_id)
    if 资源类型 == "端口" and isinstance(附加信息, dict) and 附加信息.get("占用pid") is not None:
        记录["占用pid"] = int(附加信息["占用pid"])
    if 附加信息 is not None and 资源类型 in ("线程", "句柄"):
        _对象注册表[str(目标)] = 附加信息
    清单路径.parent.mkdir(parents=True, exist_ok=True)
    with 清单路径.open("a", encoding="utf-8") as 文件:
        文件.write(json.dumps(记录, ensure_ascii=False) + "\n")
    return {"成功": True, **记录}


def 清理资源(清单路径: Path, *, 临时根目录: Path,
             证据目录: Path | None = None, work_id: str | None = None) -> dict[str, Any]:
    """清理清单中已登记的资源；单项失败不抛异常，收集到失败表并保留证据。

    证据目录：提供时，失败证据额外写入 证据目录/{work_id or "未开工"}.json
    （统一结构：运行id/时间/路径/失败原因/资源列表，与测试中心独立模块验证语义对齐）。

    返回 {"成功": bool, "清理数": int, "保留数": int, "失败表": [...], "证据路径": str}；
    失败表项为 {"路径/标识": str, "类型": str, "原因": str}。
    """
    根 = _校验临时根(临时根目录)
    清理数 = 0
    保留数 = 0
    失败表: list[dict[str, str]] = []
    if 清单路径.is_file():
        for 行 in 清单路径.read_text(encoding="utf-8").splitlines():
            try:
                记录 = json.loads(行)
            except json.JSONDecodeError:
                continue
            类型 = str(记录.get("类型", "文件"))
            if 记录.get("保留"):
                保留数 += 1
                continue
            try:
                清理单项(记录, 根)
                清理数 += 1
            except (OSError, ValueError) as 错误:
                失败表.append({
                    "路径/标识": str(记录.get("路径", "")),
                    "类型": 类型,
                    "原因": f"{type(错误).__name__}: {错误}",
                })
        清单路径.unlink(missing_ok=True)
    证据路径 = ""
    if 失败表:
        try:
            _写临时根清理失败证据(根, 失败表)
        except OSError as 错误:
            失败表.append({"路径/标识": str(根 / "清理失败.json"), "类型": "证据",
                         "原因": f"写入清理失败证据失败：{type(错误).__name__}: {错误}"})
        if 证据目录 is not None:
            try:
                证据路径 = str(写清理失败证据(
                    证据目录.resolve(), work_id or "未开工", 根, 失败表,
                ))
            except OSError as 错误:
                失败表.append({
                    "路径/标识": str(证据目录.resolve() / f"{work_id or '未开工'}.json"),
                    "类型": "证据",
                    "原因": f"写入统一清理失败证据失败：{type(错误).__name__}: {错误}",
                })
        return {"成功": False, "清理数": 清理数, "保留数": 保留数,
                "失败表": 失败表, "证据路径": 证据路径}
    return {"成功": True, "清理数": 清理数, "保留数": 保留数,
            "失败表": 失败表, "证据路径": 证据路径}


def 清理单项(记录: dict[str, Any], 根: Path) -> None:
    """按登记类型清理单项资源；失败抛 OSError/ValueError 由调用方捕获。"""
    类型 = str(记录.get("类型", "文件"))
    目标 = Path(记录["路径"]).resolve()
    标识 = str(记录.get("标识", ""))
    if 类型 in ("文件", "目录"):
        if not str(目标).startswith(f"{根}{os.sep}"):
            return  # 越界记录跳过，保持安全边界
        if 目标.is_dir():
            shutil.rmtree(目标, ignore_errors=False)
        else:
            目标.unlink(missing_ok=True)
        return
    if 类型 == "子进程":
        if not 标识:
            raise OSError("子进程登记缺少 pid 标识")
        _复核清理归属(int(标识), f"子进程:{标识}")
        _终止子进程组(int(标识))
        return
    if 类型 == "端口":
        if not 标识:
            raise OSError("端口登记缺少端口号标识")
        _释放端口(int(标识), 记录)
        return
    if 类型 == "线程":
        _验证线程已结束(目标, 标识)
        return
    if 类型 == "句柄":
        _验证句柄已关闭(目标, 标识)
        return
    raise ValueError(f"未知资源类型：{类型}")


def _推导标识(资源类型: str, 目标: Path, 附加信息: Any) -> str:
    """从资源路径或附加信息推导标识（pid/端口号/线程名/句柄描述）。"""
    if 资源类型 == "子进程":
        if isinstance(附加信息, dict) and 附加信息.get("pid") is not None:
            return str(附加信息["pid"])
        return _冒号后(目标.name)
    if 资源类型 == "端口":
        if isinstance(附加信息, dict) and 附加信息.get("端口") is not None:
            return str(附加信息["端口"])
        return _冒号后(目标.name)
    if 资源类型 == "线程":
        if isinstance(附加信息, threading.Thread):
            return str(附加信息.name)
        return _冒号后(目标.name)
    if 资源类型 == "句柄":
        return _冒号后(目标.name)
    return ""


def _冒号后(名称: str) -> str:
    """取"前缀:值"形式名称中冒号后的值。"""
    return 名称.rsplit(":", 1)[-1] if ":" in 名称 else 名称


def _终止子进程组(pid: int) -> None:
    """终止进程组防残留：先探测进程，再 killpg 整组终止。"""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return  # 进程已退出，无需清理
    except PermissionError as 错误:
        raise OSError(f"无权限探测进程 {pid}：{错误}") from 错误
    try:
        os.killpg(os.getpgid(pid), signal.SIGKILL)
    except ProcessLookupError:
        return  # 进程组已不存在，进程已退出
    except PermissionError as 错误:
        raise OSError(f"无权限终止进程组 {pid}：{错误}") from 错误
    # 等待内核完成终止；僵尸回收由父进程负责（Popen.wait/poll 等）
    time.sleep(0.1)


def _释放端口(端口号: int, 记录: dict[str, Any]) -> None:
    """终止占用进程（仅限本进程派生集合内，且非本进程自身）并验证端口已释放。"""
    占用pid = 记录.get("占用pid")
    if 占用pid is not None and int(占用pid) != os.getpid():
        _复核清理归属(int(占用pid), f"端口:{端口号} 占用进程")
        _终止占用进程(int(占用pid))
    _验证端口已释放(端口号)


def _推导pid(附加信息: Any, 目标: Path) -> int:
    """子进程登记：从附加信息或 子进程:<pid> 路径推导 pid。"""
    if isinstance(附加信息, dict) and 附加信息.get("pid") is not None:
        return int(附加信息["pid"])
    return int(_冒号后(目标.name))


def _端口占用pid(附加信息: Any, 目标: Path) -> int | None:
    """端口登记：从附加信息或 端口:<端口号> 路径推导占用 pid（可能无）。"""
    if isinstance(附加信息, dict) and 附加信息.get("占用pid") is not None:
        return int(附加信息["占用pid"])
    端口号 = int(_冒号后(目标.name))
    try:
        for 行 in subprocess.run(
            ["lsof", "-ti", f"TCP:{端口号}"], capture_output=True,
            text=True, timeout=5,
        ).stdout.splitlines():
            if 行.strip().isdigit():
                return int(行.strip())
    except (OSError, subprocess.TimeoutExpired, ValueError):
        pass
    return None


def _终止占用进程(pid: int) -> None:
    """先温和终止，短暂等待后强制终止，防残留。"""
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    except PermissionError as 错误:
        raise OSError(f"无权限终止进程 {pid}：{错误}") from 错误
    for _ in range(10):
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return
        time.sleep(0.05)
    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


def 终止进程防残留(pid: int) -> None:
    """公开入口：先温和终止、等待后强制终止单个进程，防残留；进程已退出视为成功。"""
    _终止占用进程(pid)


def _验证端口已释放(端口号: int) -> None:
    """尝试绑定端口验证已释放；仍被占用抛 OSError。"""
    探针 = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        探针.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        探针.bind(("127.0.0.1", 端口号))
    except OSError as 错误:
        raise OSError(f"端口 {端口号} 仍被占用：{错误}") from 错误
    finally:
        探针.close()


def _验证线程已结束(目标: Path, 标识: str) -> None:
    """线程登记后清理时验证线程真实结束。"""
    线程对象 = _对象注册表.get(str(目标))
    if not isinstance(线程对象, threading.Thread):
        raise OSError(f"无线程对象可供验证：{标识}")
    if 线程对象.is_alive():
        raise OSError(f"线程仍存活：{标识}")
    _对象注册表.pop(str(目标), None)


def _验证句柄已关闭(目标: Path, 标识: str) -> None:
    """句柄登记后清理时验证句柄真实关闭。"""
    句柄对象 = _对象注册表.get(str(目标))
    if 句柄对象 is None:
        raise OSError(f"无句柄对象可供验证：{标识}")
    if not _句柄已关闭(句柄对象):
        raise OSError(f"句柄未关闭：{标识}")
    _对象注册表.pop(str(目标), None)


def _句柄已关闭(句柄对象: Any) -> bool:
    关闭标记 = getattr(句柄对象, "closed", None)
    if isinstance(关闭标记, bool):
        return 关闭标记
    try:
        句柄对象.fileno()
    except OSError:
        return True
    return False


def _写临时根清理失败证据(根: Path, 失败表: list[dict[str, str]]) -> None:
    """把失败证据写入 临时根目录/清理失败.json，已有证据追加不覆盖。"""
    证据路径 = 根 / "清理失败.json"
    已有失败: list[dict[str, Any]] = []
    if 证据路径.is_file():
        try:
            已有内容 = json.loads(证据路径.read_text(encoding="utf-8"))
            已有失败 = list(已有内容.get("失败", []))
        except (json.JSONDecodeError, OSError):
            已有失败 = []
    时间戳 = datetime.now().isoformat()
    新条目 = [{"路径": 项.get("路径/标识", ""), "类型": 项.get("类型", ""),
               "原因": 项.get("原因", ""), "时间": 时间戳} for 项 in 失败表]
    证据路径.write_text(
        json.dumps({"失败": 已有失败 + 新条目}, ensure_ascii=False, indent=2),
        encoding="utf-8")


def 写清理失败证据(
    证据目录: Path, 运行id: str, 根: Path, 失败表: list[dict[str, str]],
) -> Path:
    """写入统一清理失败证据：证据目录/{运行id}.json（原子写，覆盖不追加）。

    结构化字段：运行id/时间/路径/失败原因/资源列表，与测试中心独立模块验证语义对齐，供关闭工作区等场景复用。
    """
    证据目录.mkdir(parents=True, exist_ok=True)
    证据 = {
        "运行id": 运行id,
        "时间": time.strftime("%Y-%m-%d %H:%M:%S"),
        "路径": str(根),
        "失败原因": f"资源清理失败，共 {len(失败表)} 项",
        "资源列表": [
            {"路径": 项.get("路径/标识", ""), "类型": 项.get("类型", ""),
             "原因": 项.get("原因", "")} for 项 in 失败表
        ],
    }
    证据路径 = 证据目录 / f"{运行id}.json"
    临时路径 = 证据路径.with_suffix(".json.tmp")
    临时路径.write_text(json.dumps(证据, ensure_ascii=False, indent=2), encoding="utf-8")
    临时路径.replace(证据路径)
    return 证据路径
