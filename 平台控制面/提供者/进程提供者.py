"""本地进程 Provider：有界进程池、独立行协议、stderr 消费与可核对关闭。"""
from __future__ import annotations

import json
import hashlib
import os
import subprocess
import threading
import time
import uuid
from collections import OrderedDict, deque
from typing import Any

from 公共契约.运行时.资源键表 import 取成员索引
from 公共契约.基础类型.逻辑类型 import 真, 假
from 公共契约.运行时 import 平台适配, 进程终止

状态_已创建, 状态_运行中, 状态_故障, 状态_已停止 = "已创建", "运行中", "故障", "已停止"
最大重启次数, 最大允许池大小, stderr日志上限, 响应表上限 = 2, 16, 200, 1024
信号_终止, 信号_强杀 = "终止", "强杀"


#: 判定收口层信封是否**真的发出了信号**：逻辑唯一实现在 `进程终止.信号已发出`。
#: 本名仅在本文件内被 `_发信号` 使用（该用法已改成收口层唯一入口），保留导入名是为了
#: 不把「已发出信号」这一判据再写第二遍 —— 不是第二份实现，也不是兼容壳。
_收口已发出信号 = 进程终止.信号已发出


class _进程成员:
    """一个 Provider 进程成员；独占管道、写锁、读取线程和 stderr 线程。"""

    def __init__(self, 所有者: "本地进程提供者", 索引: int) -> None:
        self.所有者, self.索引 = 所有者, 索引
        self.进程: subprocess.Popen | None = None
        self.响应表: dict[str, dict] = {}
        self.响应条件 = threading.Condition()
        self.写锁 = threading.Lock()
        self.读取线程: threading.Thread | None = None
        self.stderr线程: threading.Thread | None = None
        self.stderr日志 = deque(maxlen=stderr日志上限)
        self.退出已记录pid: set[int] = set()

    def _读取循环(self, 进程: subprocess.Popen) -> None:
        try:
            if 进程.stdout is None:
                return
            for 行 in 进程.stdout:
                try:
                    响应 = json.loads(行)
                except json.JSONDecodeError:
                    continue
                请求id = str(响应.get("请求id", ""))
                if not 请求id:
                    continue
                with self.响应条件:
                    if len(self.响应表) >= 响应表上限:
                        self.响应表.pop(next(iter(self.响应表)))
                    self.响应表[请求id] = 响应
                    self.响应条件.notify_all()
        except (ValueError, OSError):
            pass
        finally:
            with self.响应条件:
                self.响应条件.notify_all()

    def _stderr循环(self, 进程: subprocess.Popen) -> None:
        if 进程.stderr is None:
            return
        try:
            描述符 = 进程.stderr.fileno()
            while True:
                块 = os.read(描述符, 4096)
                if not 块:
                    break
                self.stderr日志.append(块.decode("utf-8", "replace"))
        except (OSError, ValueError):
            pass

    def 启动(self) -> dict[str, Any]:
        if self.进程 is not None and self.进程.poll() is None:
            return {"成功": 真, "消息": "已在运行"}
        try:
            进程 = subprocess.Popen(
                self.所有者.命令表, cwd=self.所有者.工作目录,
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, encoding="utf-8", bufsize=1, **平台适配.子进程组启动标志())
        except OSError as 错误:
            return {"成功": 假, "错误码": "启动失败", "消息": str(错误)}
        self.进程 = 进程
        self.响应表.clear()
        self.读取线程 = threading.Thread(
            target=self._读取循环, args=(进程,),
            name=f"Provider-stdout-{进程.pid}", daemon=True)
        self.stderr线程 = threading.Thread(
            target=self._stderr循环, args=(进程,),
            name=f"Provider-stderr-{进程.pid}", daemon=True)
        self.读取线程.start()
        self.stderr线程.start()
        self.所有者._记证据("启动", 成员=self.索引, pid=进程.pid, 工作目录=self.所有者.工作目录)
        响应 = self.发送({"请求id": uuid.uuid4().hex[:12], "类型": "健康"}, self.所有者.启动超时秒)
        if 响应 is None:
            self.关闭()
            return {"成功": 假, "错误码": "启动失败", "消息": "健康握手失败"}
        return {"成功": 真, "消息": f"启动成功（pid {进程.pid}）"}

    def 发送(self, 请求: dict, 超时秒: float) -> dict | None:
        进程 = self.进程
        if 进程 is None or 进程.poll() is not None or 进程.stdin is None:
            return None
        请求id = str(请求["请求id"])
        try:
            # 锁只保护一个成员的一次完整写行；等待响应不持锁。不同成员完全独立。
            with self.写锁:
                进程.stdin.write(json.dumps(请求, ensure_ascii=False) + "\n")
                进程.stdin.flush()
        except (BrokenPipeError, OSError, ValueError):
            return None
        截止 = time.monotonic() + max(0.01, 超时秒)
        with self.响应条件:
            while 请求id not in self.响应表:
                if 进程.poll() is not None:
                    break
                剩余 = 截止 - time.monotonic()
                if 剩余 <= 0:
                    break
                self.响应条件.wait(剩余)
            响应 = self.响应表.pop(请求id, None)
        if 响应 is not None and str(响应.get("请求id")) != 请求id:
            return None
        return 响应

    def 记录退出(self) -> dict[str, Any] | None:
        进程 = self.进程
        if 进程 is None or 进程.poll() is None:
            return None
        if 进程.pid not in self.退出已记录pid:
            self.退出已记录pid.add(进程.pid)
            self.所有者._记证据(
                "退出", 成员=self.索引, pid=进程.pid, 退出码=进程.returncode,
                信号=-进程.returncode if 进程.returncode < 0 else None)
        return {"退出码": 进程.returncode,
                "信号": -进程.returncode if 进程.returncode < 0 else None}

    def _进程组存活(self) -> bool:
        """成员进程组是否仍存活（组长已回收但同组子孙仍在也算存活）。

        判据与实现唯一在 `公共契约/运行时/进程终止.进程组存活`：句柄未回收 → 真；句柄已回收
        → `按组号探活(组长pid)`（组号 == 组长 pid 由 `子进程组启动标志()` 保证）。本方法只把
        `self.进程` 递过去，不持有任何组判定 —— 平台差异全在收口层（`os.killpg` 有无、
        Windows 无组概念），**本调用点不做任何平台判断**（测试中心/第一批维修/
        测试_Provider进程.py::test_P0_14_组长正常退出也必须回收同组子进程）。
        """
        return 进程终止.进程组存活(self.进程)

    def _等待进程组退出(self, 超时秒: float) -> bool:
        """按整组口径等退出（组长已回收但同组子孙仍在 ⇒ 未收敛）。

        逻辑唯一在 `公共契约/运行时/进程终止.等待进程组退出`。
        """
        return 进程终止.等待进程组退出(self.进程, 超时秒)

    def _发信号(self, 信号名: str) -> None:
        """向成员进程组发信号：两次都走跨平台收口，调用点不做任何平台判断。

        逻辑唯一在 `公共契约/运行时/进程终止.发进程组信号`：按组长身份整组发信号 →
        组长已被 `Popen` 回收时按组号补发（`按组号终止`，组长已回收仍可用）→ 两发都没发出
        且手上有句柄时退化为句柄信号。「不向自己所在的组发信号」的安全闸也在收口层内
        （本进程组号由 `进程组号()` 取，非 POSIX 平台如实回 `None`）；保住
        「组长退出不等于组已收敛」（测试中心/第一批维修/测试_Provider进程.py::test_P0_14）。
        """
        进程终止.发进程组信号(self.进程, 信号名)

    def _关闭管道线程(self) -> None:
        进程 = self.进程
        if 进程 is not None:
            for 管道 in (进程.stdin, 进程.stdout, 进程.stderr):
                if 管道 is not None and not 管道.closed:
                    try:
                        管道.close()
                    except (OSError, ValueError):
                        pass
        for 线程 in (self.读取线程, self.stderr线程):
            if 线程 is not None and 线程 is not threading.current_thread():
                线程.join(timeout=1.0)

    def 核对资源收敛(self) -> list[str]:
        未收敛: list[str] = []
        进程 = self.进程
        if 进程 is not None and self._进程组存活():
            未收敛.append(f"进程组仍存活:{进程.pid}")
        if 进程 is not None:
            for 名称, 管道 in (("stdin", 进程.stdin), ("stdout", 进程.stdout), ("stderr", 进程.stderr)):
                if 管道 is not None and not 管道.closed:
                    未收敛.append(f"管道未关闭:{名称}")
        for 名称, 线程 in (("stdout", self.读取线程), ("stderr", self.stderr线程)):
            if 线程 is not None and 线程.is_alive():
                未收敛.append(f"{名称}线程仍存活:{线程.name}")
        return 未收敛

    def 关闭(self) -> dict[str, Any]:
        进程 = self.进程
        已使用SIGKILL = 假
        if self._进程组存活():
            if 进程 is not None and 进程.poll() is None:
                self.发送({"请求id": uuid.uuid4().hex[:12], "类型": "关闭"}, self.所有者.调用超时秒)
                try:
                    进程.wait(timeout=self.所有者.调用超时秒)
                except subprocess.TimeoutExpired:
                    pass
            if self._进程组存活():
                self._发信号(信号_终止)
                self._等待进程组退出(min(max(self.所有者.调用超时秒, 0.05), 1.0))
            if self._进程组存活():
                已使用SIGKILL = 真
                self._发信号(信号_强杀)
                self._等待进程组退出(2.0)
        退出证据 = self.记录退出()
        self._关闭管道线程()
        未收敛 = self.核对资源收敛()
        return {
            "成功": not 未收敛, "错误码": "" if not 未收敛 else "资源未收敛",
            "错误说明": "成员资源已收敛" if not 未收敛 else f"成员资源未收敛: {'；'.join(未收敛)}",
            "可重试": bool(未收敛), "未收敛": 未收敛,
            "已使用SIGKILL": 已使用SIGKILL, "退出证据": 退出证据,
        }


class 本地进程提供者:
    """有界 Provider 进程池；资源键稳定分配，池成员通信和日志完全隔离。"""

    def __init__(self, 命令表, *, 工作目录=None, 启动超时秒=5.0, 调用超时秒=3.0,
                 池大小: int = 1, 最大资源键数: int = 4096):
        if not 1 <= int(池大小) <= 最大允许池大小:
            raise ValueError(f"池大小必须在 1..{最大允许池大小} 之间")
        if 最大资源键数 < 池大小:
            raise ValueError("最大资源键数不得小于池大小")
        self.命令表 = list(命令表)
        self.工作目录 = str(工作目录) if 工作目录 else None
        self.启动超时秒, self.调用超时秒 = float(启动超时秒), float(调用超时秒)
        self.池大小, self.最大资源键数 = int(池大小), int(最大资源键数)
        self.运行状态, self.重启次数 = 状态_已创建, 0
        self.证据列表: list[dict[str, Any]] = []
        self.成员表 = [_进程成员(self, 索引) for 索引 in range(self.池大小)]
        # 资源键 → 成员索引的**有界 LRU** 映射（字典保序 + 命中/插入即移到队尾）。
        # 键只作等价绑定用（索引本身由 sha256(键) % 池大小 纯函数决定），故淘汰键**不需要**
        # 释放任何池内资源——池成员数与池的关闭语义都不由该表持有（成员生命周期由 关闭() 负责）。
        # 淘汰只丢「缓存行」，被淘汰的键下次进来按同一哈希重新绑定到同一成员，行为等价、无泄漏。
        self.资源分配: OrderedDict[str, int] = OrderedDict()
        self._分配锁 = threading.Lock()
        self.关闭账本: list[dict[str, Any]] = []

    @property
    def 进程(self):
        return self.成员表[0].进程 if self.成员表 else None

    def _记证据(self, 类型, **字段):
        self.证据列表.append(dict(类型=类型, 时间=time.strftime("%Y-%m-%d %H:%M:%S"), **字段))

    def _分配成员(self, 资源键: str) -> _进程成员 | None:
        """按资源键分配池成员（**有界 LRU**：满表淘汰最久未用，永不拒绝新键）。

        键 → 成员索引的语义**已收口到 `公共契约/运行时/资源键表.py`**（本文件与
        `运行核心/加载器/提供者隔离/独立进程.提供者进程池` 曾是两份同构实现 —— 哲学 1.2
        不允许同一件事两套实现）。本方法只负责「持锁 + 取索引 + 查成员表」。
        """
        with self._分配锁:
            索引 = 取成员索引(self.资源分配, self._分配锁, 资源键,
                           池大小=self.池大小, 最大资源键数=self.最大资源键数)
            return self.成员表[索引]

    def 启动(self, 工作目录=None):
        if 工作目录:
            self.工作目录 = str(工作目录)
        if self.运行状态 == 状态_运行中 and all(
                成员.进程 is not None and 成员.进程.poll() is None for 成员 in self.成员表):
            return {"成功": 真, "消息": "已在运行"}
        已启动: list[_进程成员] = []
        for 成员 in self.成员表:
            结果 = 成员.启动()
            if not 结果["成功"]:
                for 已有成员 in 已启动:
                    已有成员.关闭()
                self.运行状态 = 状态_故障
                self._记证据("启动失败", 成员=成员.索引, 错误=结果.get("消息", ""))
                return 结果
            已启动.append(成员)
        self.运行状态 = 状态_运行中
        return {"成功": 真, "消息": f"启动成功（{self.池大小} 个池成员）"}

    def _重启成员(self, 成员: _进程成员) -> bool:
        if self.重启次数 >= 最大重启次数:
            return 假
        self.重启次数 += 1
        self._记证据("重启", 成员=成员.索引, 次数=self.重启次数)
        成员._关闭管道线程()
        return bool(成员.启动().get("成功"))

    def 调用(self, 请求, 超时秒=None):
        if self.运行状态 == 状态_已停止:
            return {"成功": 假, "错误码": "已关闭", "错误说明": "提供者已关闭，请先重新 启动()"}
        if not any(成员.进程 is not None for 成员 in self.成员表):
            return {"成功": 假, "错误码": "未启动", "错误说明": "请先调用 启动()"}
        完整请求 = dict(请求)
        完整请求["请求id"] = 请求.get("请求id") or uuid.uuid4().hex[:12]
        键 = str(请求.get("资源键") or "默认")
        成员 = self._分配成员(键)
        if 成员 is None:
            return {"成功": 假, "错误码": "资源繁忙", "错误说明": "Provider资源键表已满", "可重试": 真}
        超时 = float(超时秒 if 超时秒 is not None else self.调用超时秒)
        for _ in range(最大重启次数 + 1):
            响应 = 成员.发送(完整请求, 超时)
            if 响应 is not None:
                return 响应
            退出证据 = 成员.记录退出()
            if 退出证据 is None:
                return {"成功": 假, "错误码": "超时", "错误说明": f"调用超过 {超时} 秒无响应"}
            self.运行状态 = 状态_故障
            if not self._重启成员(成员):
                return {"成功": 假, "错误码": "崩溃", "证据": list(self.证据列表),
                        "错误说明": f"崩溃且自动重启已达上限（{self.重启次数}/{最大重启次数}），退出证据 {退出证据}"}
            self.运行状态 = 状态_运行中
        return {"成功": 假, "错误码": "崩溃", "错误说明": "Provider不可恢复"}

    def _核对资源收敛(self) -> list[str]:
        未收敛: list[str] = []
        for 成员 in self.成员表:
            未收敛.extend(f"成员{成员.索引 + 1}:{问题}" for 问题 in 成员.核对资源收敛())
        return 未收敛

    def 关闭(self):
        成员结果 = [成员.关闭() for 成员 in self.成员表]
        未收敛 = self._核对资源收敛()
        成功 = not 未收敛 and all(结果["成功"] for 结果 in 成员结果)
        if not 成功 and not 未收敛:
            未收敛 = [结果["错误说明"] for 结果 in 成员结果 if not 结果["成功"]]
        self.运行状态 = 状态_已停止 if 成功 else 状态_故障
        结果 = {
            "成功": 成功, "错误码": "" if 成功 else "资源未收敛",
            "错误说明": "Provider进程池资源已收敛" if 成功 else f"Provider进程池资源未收敛: {'；'.join(未收敛)}",
            "消息": "已关闭" if 成功 else "关闭失败，账本已保留供重试",
            "可重试": not 成功, "未收敛": 未收敛,
            "已使用SIGKILL": any(项.get("已使用SIGKILL", 假) for 项 in 成员结果),
            "成员结果": 成员结果,
        }
        self.关闭账本.append(dict(结果, 时间=time.time()))
        return 结果

    def 重试关闭(self):
        return self.关闭()

    def 状态(self):
        成员状态 = [{
            "成员": 成员.索引, "pid": 成员.进程.pid if 成员.进程 else None,
            "运行中": bool(成员.进程 is not None and 成员.进程.poll() is None),
            "stderr日志": list(成员.stderr日志),
            "读取线程存活": bool(成员.读取线程 and 成员.读取线程.is_alive()),
            "stderr线程存活": bool(成员.stderr线程 and 成员.stderr线程.is_alive()),
        } for 成员 in self.成员表]
        退出证据 = next((证据 for 证据 in reversed(self.证据列表) if 证据["类型"] == "退出"), None)
        return {
            "状态": self.运行状态, "pid": self.进程.pid if self.进程 else None,
            "pid表": [项["pid"] for 项 in 成员状态 if 项["pid"] is not None],
            "池大小": self.池大小, "成员表": 成员状态,
            "资源分配": dict(self.资源分配), "重启次数": self.重启次数,
            "退出证据": 退出证据, "证据列表": list(self.证据列表),
            "工作目录": self.工作目录, "关闭账本": list(self.关闭账本),
        }
