"""资源回收确认原子能力实现（不对外暴露，只经包级中文入口调用）。

职责（华哥口径）：资源启动时登记 → 绑定句柄 → 句柄失效时核查所有资源
是否已回收（PID/端口/SQLite/临时文件），没回收的补回收一趟（幂等）。
只做资源登记/核查/回收，不做业务逻辑；所有回收动作带检查（先查再收）。
"""

from __future__ import annotations

import os
import signal
import threading
import time

from 公共契约.基础类型.结果类型 import 结果

锁 = threading.Lock()
资源登记表: dict[str, dict] = {}   # 登记id → 资源信息
句柄绑定表: dict[str, list[str]] = {}  # 句柄 → [登记id]
回收记录表: dict[str, list[dict]] = {}  # 句柄 → 回收记录


def _登记id生成() -> str:
    return f"资{int(time.time() * 1000)}-{len(资源登记表) + 1}"


def _检查进程存活(pid: int) -> bool:
    """检查 PID 是否存活（排除 zombie：/proc 状态检查在 macOS 用 ps）。"""
    if not isinstance(pid, int) or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except Exception:
        return False
    # os.kill(pid,0) 对 zombie 也返回真，用 ps 确认状态不是 Z
    try:
        import subprocess
        r = subprocess.run(["ps", "-o", "state=", "-p", str(pid)], capture_output=True, text=True, timeout=3)
        状态 = r.stdout.strip()
        if 状态 and 状态[0] in ("Z", "X"):
            return False  # zombie/死进程，视为已回收
    except Exception:
        pass
    return True


def _回收进程(pid: int) -> str:
    """回收进程：先 SIGTERM，等 1 秒，再 SIGKILL（进程树）。"""
    if not _检查进程存活(pid):
        return "进程已不存在（无需回收）"
    try:
        os.killpg(pid, signal.SIGTERM) if _进程组存在(pid) else os.kill(pid, signal.SIGTERM)
    except Exception:
        pass
    time.sleep(1)
    try:
        if _检查进程存活(pid):
            os.killpg(pid, signal.SIGKILL) if _进程组存在(pid) else os.kill(pid, signal.SIGKILL)
    except Exception:
        pass
    return "已终止进程（含进程组）" if not _检查进程存活(pid) else "进程仍存活（回收失败）"


def _进程组存在(pid: int) -> bool:
    """判断是否进程组长（有进程组可 killpg）。"""
    try:
        return os.getpgid(pid) == pid
    except Exception:
        return False


def _检查端口(端口: int) -> bool:
    """检查端口是否被监听（粗糙探测）。"""
    if not isinstance(端口, int) or 端口 <= 0:
        return False
    try:
        import socket
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(1)
            return s.connect_ex(("127.0.0.1", 端口)) == 0
    except Exception:
        return False


def _回收端口(端口: int) -> str:
    """回收端口：找到占用进程并杀（谨慎：只回收登记过的端口）。"""
    if not _检查端口(端口):
        return "端口已释放（无需回收）"
    try:
        import subprocess
        r = subprocess.run(["lsof", "-nP", "-iTCP:%d" % 端口, "-sTCP:LISTEN", "-t"],
                           capture_output=True, text=True, timeout=5)
        for pid_str in r.stdout.strip().split():
            try:
                pid = int(pid_str)
                os.kill(pid, signal.SIGKILL)
            except Exception:
                pass
        return f"端口 {端口} 占用进程已清理"
    except Exception as 错误:
        return f"端口 {端口} 回收异常: {错误}"


def 登记资源(句柄: str = None, 资源类型: str = None, PID: int = None,
             端口: int = None, 资源路径: str = None, 清理函数名: str = None) -> 结果:
    """登记资源并绑定到句柄。资源类型：进程/端口/SQLite连接/临时文件。"""
    if not isinstance(句柄, str) or not 句柄.strip():
        return 结果.失败("参数不合法", "句柄必须是非空字符串", 来源="资源回收确认")
    if 资源类型 not in ("进程", "端口", "SQLite连接", "临时文件"):
        return 结果.失败("参数不合法", f"资源类型必须是 进程/端口/SQLite连接/临时文件: {资源类型}", 来源="资源回收确认")
    登记id = _登记id生成()
    with 锁:
        资源登记表[登记id] = {
            "登记id": 登记id, "句柄": 句柄, "资源类型": 资源类型,
            "PID": PID if isinstance(PID, int) else None,
            "端口": 端口 if isinstance(端口, int) else None,
            "资源路径": 资源路径, "清理函数名": 清理函数名,
            "登记时间": time.strftime("%Y-%m-%d %H:%M:%S"), "已回收": False,
        }
        句柄绑定表.setdefault(句柄, []).append(登记id)
    return 结果.成功结果({"登记id": 登记id, "句柄": 句柄, "资源类型": 资源类型, "已绑定": True})


def _核查单个资源(资源: dict) -> tuple[bool, str]:
    """核查单个资源：存活→回收；不存活→标记已回收（幂等）。返回 (已回收, 说明)。"""
    类型 = 资源["资源类型"]
    说明 = ""
    try:
        if 类型 == "进程":
            pid = 资源["PID"]
            if pid and _检查进程存活(pid):
                说明 = _回收进程(pid)
            else:
                说明 = "进程本就不存在（无泄露）"
        elif 类型 == "端口":
            端口 = 资源["端口"]
            说明 = _回收端口(端口)
        elif 类型 == "SQLite连接":
            路径 = 资源["资源路径"]
            # 连接对象不跨进程序列化，由拥有方在清理函数里 close；这里只登记说明
            说明 = f"SQLite连接 {路径} 需拥有方清理（清理函数: {资源['清理函数名'] or '无'}）"
        elif 类型 == "临时文件":
            路径 = 资源["资源路径"]
            if 路径 and os.path.isfile(路径):
                try:
                    os.remove(路径)
                    说明 = f"临时文件 {路径} 已删除"
                except Exception as 错误:
                    说明 = f"临时文件删除失败: {错误}"
            else:
                说明 = "临时文件本就不存在（无泄露）"
    except Exception as 错误:
        说明 = f"回收异常: {错误}"
    已回收 = "无泄露" in 说明 or "已删除" in 说明 or "已释放" in 说明 or "已清理" in 说明 or "已终止" in 说明
    return 已回收, 说明


def 核查回收(句柄: str = None) -> 结果:
    """句柄失效时核查所有绑定资源，未回收的补回收一趟（幂等）。"""
    if not isinstance(句柄, str) or not 句柄.strip():
        return 结果.失败("参数不合法", "句柄必须是非空字符串", 来源="资源回收确认")
    with 锁:
        登记ids = list(句柄绑定表.get(句柄, []))
        回收清单 = []
        已回收数 = 0
        for 登记id in 登记ids:
            资源 = 资源登记表.get(登记id)
            if 资源 is None or 资源.get("已回收"):
                回收清单.append({"登记id": 登记id, "已回收": True, "说明": "已在先前回收（幂等）"})
                已回收数 += 1
                continue
            已回收, 说明 = _核查单个资源(资源)
            资源["已回收"] = True
            回收清单.append({"登记id": 登记id, "资源类型": 资源["资源类型"], "已回收": 已回收, "说明": 说明})
            已回收数 += 1 if 已回收 else 0
        回收记录表[句柄] = 回收清单
    return 结果.成功结果({
        "句柄": 句柄, "回收清单": 回收清单,
        "已回收数": 已回收数, "资源总数": len(登记ids),
    })


def 查询资源(句柄: str = None) -> 结果:
    """查询句柄绑定的资源（审计）。"""
    if not isinstance(句柄, str) or not 句柄.strip():
        return 结果.失败("参数不合法", "句柄必须是非空字符串", 来源="资源回收确认")
    with 锁:
        登记ids = 句柄绑定表.get(句柄, [])
        资源清单 = [资源登记表.get(i) for i in 登记ids if 资源登记表.get(i)]
    return 结果.成功结果({"句柄": 句柄, "资源数": len(资源清单), "资源清单": 资源清单})
