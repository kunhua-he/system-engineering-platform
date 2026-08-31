"""公共句柄契约与唯一状态机实现。

状态机统一维护句柄全生命周期：创建 → 有效 → 失效（超时/释放/回收/过期）。
资源生命周期（华哥口径）：资源登记绑定到句柄 → 状态机失效时统一监控回收
（PID/端口/连接/临时文件），不旁路拼接独立回收能力。
"""
from __future__ import annotations
import time
import secrets
import threading
import os
import signal
from dataclasses import dataclass, field
from typing import Any

句柄类型_读取 = "读取句柄"
句柄类型_修改事务 = "修改事务句柄"
句柄类型_资源 = "资源句柄"
句柄类型_任务 = "任务句柄"
句柄类型_会话 = "会话句柄"
状态_已创建 = "已创建"
状态_有效 = "有效"
状态_已失效 = "已失效"
失效原因_过期 = "过期"
失效原因_回收 = "回收"
失效原因_释放 = "释放"
失效原因_超时 = "超时"
句柄位数 = 6


def 是合法句柄id(句柄id: str | int) -> bool:
    """公共对外句柄格式：固定六位数字字符串（兼容历史整数调用）。"""
    if isinstance(句柄id, str):
        return len(句柄id) == 句柄位数 and 句柄id.isascii() and 句柄id.isdecimal()
    return isinstance(句柄id, int) and not isinstance(句柄id, bool) and 1 <= 句柄id <= 999999


def 生成句柄id() -> int:
    """生成 1 到 999999 的整数句柄；资源表负责校验活动句柄冲突。"""
    return secrets.randbelow(999999) + 1

@dataclass
class 句柄:
    句柄id: int = 0
    句柄类型: str = 句柄类型_资源
    资源id: str = ""
    项目id: str = ""
    所有者: str = ""
    状态: str = 状态_已创建
    创建时间: str = ""
    失效时间: str = ""
    失效原因: str = ""
    版本: str = ""
    元数据: dict[str, Any] = field(default_factory=dict)
    绑定资源: list[dict[str, Any]] = field(default_factory=list)   # 句柄绑定的资源清单

    def 转字典(self) -> dict[str, Any]:
        return {"句柄id": self.句柄id, "句柄类型": self.句柄类型, "资源id": self.资源id,
                "项目id": self.项目id, "所有者": self.所有者, "状态": self.状态,
                "创建时间": self.创建时间, "失效时间": self.失效时间,
                "失效原因": self.失效原因, "版本": self.版本,
                "绑定资源数": len(self.绑定资源)}


class 句柄体系:
    def __init__(self) -> None:
        self.句柄表: dict[int, 句柄] = {}
        self.回收证据表: list[dict[str, Any]] = []
        self._锁 = threading.Lock()

    def 创建句柄(self, *, 句柄类型: str, 资源id: str, 项目id: str = "", 所有者: str = "", 版本: str = "") -> 句柄:
        with self._锁:
            for _ in range(100):
                句柄id = 生成句柄id()
                if 句柄id not in self.句柄表:
                    对象 = 句柄(句柄id, 句柄类型, 资源id, 项目id, 所有者, 状态_有效,
                                time.strftime("%Y-%m-%d %H:%M:%S"), 版本=版本)
                    self.句柄表[句柄id] = 对象
                    return 对象
        raise RuntimeError("六位句柄已耗尽")

    def 恢复句柄(self, 对象: 句柄) -> 句柄:
        """从权威账本恢复句柄；禁止覆盖本进程已存在的不同对象。"""
        if not 是合法句柄id(对象.句柄id):
            raise ValueError("恢复句柄id不合法")
        if 对象.状态 not in (状态_已创建, 状态_有效, 状态_已失效):
            raise ValueError("恢复句柄状态不合法")
        with self._锁:
            已有 = self.句柄表.get(对象.句柄id)
            if 已有 is not None:
                if 已有.资源id != 对象.资源id or 已有.项目id != 对象.项目id or 已有.所有者 != 对象.所有者:
                    raise RuntimeError("句柄账本与内存对象冲突")
                return 已有
            self.句柄表[对象.句柄id] = 对象
            return 对象

    def 校验(self, 句柄id: int, *, 项目id: str = "", 所有者: str = "") -> tuple[bool, str]:
        对象 = self.句柄表.get(句柄id)
        if 对象 is None: return False, f"句柄不存在: {句柄id}"
        if 对象.状态 != 状态_有效: return False, f"句柄已失效（{对象.失效原因}），不能自动复活"
        if 项目id and 对象.项目id and 对象.项目id != 项目id: return False, f"跨项目复用被拒绝: 句柄属 {对象.项目id}，请求 {项目id}"
        if 所有者 and 对象.所有者 and 对象.所有者 != 所有者: return False, f"跨所有者复用被拒绝: 句柄属 {对象.所有者}，请求 {所有者}"
        return True, "句柄有效"

    # ── 资源登记（状态机内置，华哥口径）────────────────

    def 登记资源(self, 句柄id: int, *, 资源类型: str, PID: int = None, 端口: int = None,
                 资源路径: str = None, 清理函数: Any = None) -> tuple[bool, str]:
        """把资源绑定到句柄，由状态机统一监控/回收。资源类型：进程/端口/连接/临时文件。"""
        with self._锁:
            对象 = self.句柄表.get(句柄id)
            if 对象 is None: return False, f"句柄不存在: {句柄id}"
            if 对象.状态 != 状态_有效: return False, f"句柄已失效，不能登记资源: {句柄id}"
            对象.绑定资源.append({
                "资源类型": 资源类型, "PID": PID, "端口": 端口, "资源路径": 资源路径,
                "清理函数": 清理函数, "已回收": False, "回收说明": "",
            })
            return True, "资源已绑定句柄"

    def 查询资源(self, 句柄id: int) -> list[dict[str, Any]]:
        """查询句柄绑定的资源（审计）。"""
        with self._锁:
            对象 = self.句柄表.get(句柄id)
            if 对象 is None: return []
            return [{"资源类型": r["资源类型"], "PID": r["PID"], "端口": r["端口"],
                     "资源路径": r["资源路径"], "已回收": r["已回收"], "回收说明": r["回收说明"]}
                    for r in 对象.绑定资源]

    def _检查进程存活(self, pid: int) -> bool:
        """检查 PID 是否存活（排除 zombie）。"""
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
        try:
            import subprocess
            r = subprocess.run(["ps", "-o", "state=", "-p", str(pid)], capture_output=True, text=True, timeout=3)
            if r.stdout.strip() and r.stdout.strip()[0] in ("Z", "X"):
                return False
        except Exception:
            pass
        return True

    def _回收单个资源(self, 资源: dict) -> tuple[bool, str]:
        """核查单个资源：存活→回收；否则标记已回收（幂等）。"""
        类型 = 资源["资源类型"]
        说明 = ""
        try:
            if 类型 == "进程":
                pid = 资源["PID"]
                if pid and self._检查进程存活(pid):
                    try:
                        os.killpg(pid, signal.SIGTERM) if os.getpgid(pid) == pid else os.kill(pid, signal.SIGTERM)
                    except Exception:
                        pass
                    time.sleep(1)
                    try:
                        if self._检查进程存活(pid):
                            os.killpg(pid, signal.SIGKILL) if os.getpgid(pid) == pid else os.kill(pid, signal.SIGKILL)
                    except Exception:
                        pass
                    说明 = "已终止进程（含进程组）" if not self._检查进程存活(pid) else "进程仍存活（回收失败）"
                else:
                    # 进程不在（含 zombie 已死）→ 补杀一次确保回收干净
                    try:
                        os.kill(pid, signal.SIGKILL) if isinstance(pid, int) else None
                    except Exception:
                        pass
                    说明 = "进程已不存在（无泄露）"
            elif 类型 == "端口":
                端口 = 资源["端口"]
                if not isinstance(端口, int) or 端口 <= 0:
                    说明 = "无端口"
                else:
                    import socket
                    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                        s.settimeout(1)
                        占用 = s.connect_ex(("127.0.0.1", 端口)) == 0
                    if 占用:
                        import subprocess
                        r = subprocess.run(["lsof", "-nP", "-iTCP:%d" % 端口, "-sTCP:LISTEN", "-t"],
                                           capture_output=True, text=True, timeout=5)
                        for pid_str in r.stdout.strip().split():
                            try: os.kill(int(pid_str), signal.SIGKILL)
                            except Exception: pass
                        说明 = f"端口 {端口} 占用进程已清理"
                    else:
                        说明 = "端口已释放（无泄露）"
            elif 类型 == "临时文件":
                路径 = 资源["资源路径"]
                if 路径 and os.path.isfile(路径):
                    try:
                        os.remove(路径); 说明 = f"临时文件 {路径} 已删除"
                    except Exception as 错误:
                        说明 = f"临时文件删除失败: {错误}"
                else:
                    说明 = "临时文件本就不存在（无泄露）"
            else:
                # 连接等资源：由清理函数回收
                清理函数 = 资源["清理函数"]
                if callable(清理函数):
                    清理函数(); 说明 = "已调用清理函数回收"
                else:
                    说明 = f"连接资源需清理函数回收（无）"
        except Exception as 错误:
            说明 = f"回收异常: {错误}"
        已回收 = ("无泄露" in 说明 or "已删除" in 说明 or "已释放" in 说明
                  or "已清理" in 说明 or "已终止" in 说明 or "已调用清理函数" in 说明)
        return 已回收, 说明

    def 核查回收(self, 句柄id: int) -> dict[str, Any]:
        """句柄失效时核查所有绑定资源，未回收的补回收一趟（幂等）。状态机统一维护。"""
        with self._锁:
            对象 = self.句柄表.get(句柄id)
            if 对象 is None:
                return {"句柄": 句柄id, "已回收数": 0, "资源总数": 0, "回收清单": []}
            回收清单 = []
            已回收数 = 0
            for 资源 in 对象.绑定资源:
                if 资源["已回收"]:
                    回收清单.append({"资源类型": 资源["资源类型"], "已回收": True, "说明": "已在先前回收（幂等）"})
                    已回收数 += 1
                    continue
                已回收, 说明 = self._回收单个资源(资源)
                # 只有确认清理成功才进入终态；失败必须保留待回收状态，
                # 让后续有界重试或诊断流程仍能再次执行清理。
                资源["已回收"] = 已回收
                资源["回收说明"] = 说明
                回收清单.append({"资源类型": 资源["资源类型"], "已回收": 已回收, "说明": 说明})
                已回收数 += 1 if 已回收 else 0
            return {"句柄": 句柄id, "已回收数": 已回收数, "资源总数": len(对象.绑定资源), "回收清单": 回收清单}

    def 失效(self, 句柄id: int, 原因: str) -> tuple[bool, str]:
        对象 = self.句柄表.get(句柄id)
        if 对象 is None: return False, f"句柄不存在: {句柄id}"
        if 对象.状态 == 状态_已失效: return True, "句柄已失效（幂等）"
        原状态, 原失效时间, 原失效原因 = 对象.状态, 对象.失效时间, 对象.失效原因
        对象.状态 = 状态_已失效; 对象.失效时间 = time.strftime("%Y-%m-%d %H:%M:%S"); 对象.失效原因 = 原因
        # 失效即统一核查绑定资源；资源未全部回收时恢复有效状态，保留绑定记录供重试。
        try:
            回收结果 = self.核查回收(句柄id)
        except Exception as 错误:
            对象.状态, 对象.失效时间, 对象.失效原因 = 原状态, 原失效时间, 原失效原因
            return False, f"句柄未失效且资源回收异常: {type(错误).__name__}"
        if 回收结果["已回收数"] != 回收结果["资源总数"]:
            对象.状态, 对象.失效时间, 对象.失效原因 = 原状态, 原失效时间, 原失效原因
            return False, f"资源未收敛（{回收结果['已回收数']}/{回收结果['资源总数']}）"
        self.回收证据表.append({"句柄id": 句柄id, "资源id": 对象.资源id, "类型": 对象.句柄类型, "失效原因": 原因, "时间": 对象.失效时间, "版本": 对象.版本})
        return True, f"句柄已失效（{原因}）"

    def 查询回收证据(self, *, 资源id: str = "") -> list[dict[str, Any]]:
        return [x for x in self.回收证据表 if not 资源id or x["资源id"] == 资源id]

    def 活跃句柄数(self) -> int:
        return sum(x.状态 == 状态_有效 for x in self.句柄表.values())

    def 状态快照(self) -> dict[str, Any]:
        return {"句柄总数": len(self.句柄表), "活跃句柄数": self.活跃句柄数(), "回收证据数": len(self.回收证据表)}

__all__ = ["句柄", "句柄体系", "是合法句柄id", "生成句柄id", "句柄位数", "句柄类型_读取", "句柄类型_修改事务", "句柄类型_资源", "句柄类型_任务", "句柄类型_会话", "状态_已创建", "状态_有效", "状态_已失效", "失效原因_过期", "失效原因_回收", "失效原因_释放", "失效原因_超时"]
