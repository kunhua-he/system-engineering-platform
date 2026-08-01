"""本地进程真实提供者：真实 subprocess 独立进程 + JSON 行协议。

独立进程组（start_new_session）、stdin/stdout 每行一个 JSON 请求/响应、
中文契约 启动(工作目录)/调用(请求JSON, 超时秒)/关闭()/状态()、
崩溃自动重启（有界 2 次，证据记录）、退出证据（退出码/信号/时间）。"""
import json
import os
import signal
import subprocess
import threading
import time
import uuid

状态_已创建, 状态_运行中, 状态_故障, 状态_已停止, 最大重启次数 = "已创建", "运行中", "故障", "已停止", 2


class 本地进程提供者:
    def __init__(self, 命令表, *, 工作目录=None, 启动超时秒=5.0, 调用超时秒=3.0):
        self.命令表 = list(命令表)
        self.工作目录 = str(工作目录) if 工作目录 else None
        self.启动超时秒, self.调用超时秒 = 启动超时秒, 调用超时秒
        self.运行状态, self.进程, self.重启次数 = 状态_已创建, None, 0
        self.证据列表, self.响应表, self.响应条件 = [], {}, threading.Condition()

    def _记证据(self, 类型, **字段):
        self.证据列表.append(dict(类型=类型, 时间=time.strftime("%Y-%m-%d %H:%M:%S"), **字段))

    def _读取循环(self, 进程):
        try:
            for 行 in 进程.stdout:
                try:
                    响应 = json.loads(行)
                except json.JSONDecodeError:
                    continue
                with self.响应条件:
                    self.响应表[响应.get("请求id", "")] = 响应
                    self.响应条件.notify_all()
        except (ValueError, OSError):
            pass
        with self.响应条件: self.响应条件.notify_all()

    def _发送(self, 请求, 超时秒):
        进程 = self.进程
        if 进程 is None or 进程.poll() is not None:
            return None
        try:
            进程.stdin.write(json.dumps(请求, ensure_ascii=False) + "\n")
            进程.stdin.flush()
        except (BrokenPipeError, OSError, ValueError):
            return None
        请求id, 截止 = 请求["请求id"], time.monotonic() + 超时秒
        with self.响应条件:
            while 请求id not in self.响应表 and time.monotonic() < 截止:
                self.响应条件.wait(截止 - time.monotonic())
            return self.响应表.pop(请求id, None)

    def _退出证据(self):
        进程 = self.进程
        if 进程 is None:
            return None
        退出码 = 进程.poll()
        if 退出码 is None:
            return None
        self._记证据("退出", pid=进程.pid, 退出码=退出码, 信号=-退出码 if 退出码 < 0 else None)
        self.运行状态 = 状态_故障
        return {"退出码": 退出码, "信号": -退出码 if 退出码 < 0 else None}

    def _杀进程组(self, 信号值):
        进程 = self.进程
        if 进程 is None or 进程.poll() is not None:
            return
        try:
            os.killpg(进程.pid, 信号值)
        except OSError:
            进程.kill()
        try:
            进程.wait(timeout=2)
        except subprocess.TimeoutExpired:
            pass

    def _清理管道(self):
        if self.进程 is not None:
            for 管道 in (self.进程.stdin, self.进程.stdout, self.进程.stderr):
                try:
                    管道.close()
                except (OSError, ValueError):
                    pass

    def _重启(self):
        if self.重启次数 >= 最大重启次数:
            return False
        self.重启次数 += 1
        self._记证据("重启", 次数=self.重启次数)
        return bool(self.启动().get("成功"))

    def 启动(self, 工作目录=None):
        """启动(工作目录)：真实拉起独立进程组，健康握手成功后返回。"""
        if self.运行状态 == 状态_运行中 and self.进程 is not None and self.进程.poll() is None:
            return {"成功": True, "消息": "已在运行"}
        目录 = str(工作目录) if 工作目录 else self.工作目录
        try:
            进程 = subprocess.Popen(self.命令表, cwd=目录, stdin=subprocess.PIPE,
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                    text=True, encoding="utf-8", bufsize=1, start_new_session=True)
        except OSError as 错误:
            self.运行状态 = 状态_故障
            self._记证据("启动失败", 错误=str(错误))
            return {"成功": False, "错误码": "启动失败", "消息": str(错误)}
        self.进程, self.工作目录, self.运行状态 = 进程, 目录, 状态_运行中
        self._记证据("启动", pid=进程.pid, 工作目录=目录)
        threading.Thread(target=self._读取循环, args=(进程,), daemon=True).start()
        响应 = self._发送({"请求id": uuid.uuid4().hex[:12], "类型": "健康"}, self.启动超时秒)
        if 响应 is None:
            证据 = self._退出证据()
            if 证据 is None:
                self._杀进程组(signal.SIGKILL); self._记证据("启动超时", 超时秒=self.启动超时秒)
            return {"成功": False, "错误码": "启动失败", "消息": f"健康握手失败（{证据}）"}
        return {"成功": True, "消息": f"启动成功（pid {进程.pid}）"}

    def 调用(self, 请求, 超时秒=None):
        """调用(请求JSON, 超时秒)：真实写行读响应；崩溃自动重启后重试一次。"""
        if self.进程 is None or self.运行状态 == 状态_已停止:
            return {"成功": False, "错误码": "未启动" if self.进程 is None else "已关闭",
                    "错误说明": "请先调用 启动()" if self.进程 is None else "提供者已关闭，请先重新 启动()"}
        超时 = 超时秒 if 超时秒 is not None else self.调用超时秒
        完整请求 = dict(请求)
        完整请求["请求id"] = 请求.get("请求id") or uuid.uuid4().hex[:12]
        for _ in range(最大重启次数 + 1):
            响应 = self._发送(完整请求, 超时)
            if 响应 is not None:
                return 响应
            证据 = self._退出证据()
            if 证据 is None:
                return {"成功": False, "错误码": "超时", "错误说明": f"调用超过 {超时} 秒无响应"}
            if not self._重启():
                return {"成功": False, "错误码": "崩溃", "证据": list(self.证据列表),
                        "错误说明": f"崩溃且自动重启已达上限（{self.重启次数}/{最大重启次数}），退出证据 {证据}"}

    def 关闭(self):
        """关闭()：发送关闭请求优雅退出；超时按进程组强杀；幂等。"""
        进程 = self.进程
        if 进程 is not None and 进程.poll() is None:
            self._发送({"请求id": uuid.uuid4().hex[:12], "类型": "关闭"}, self.调用超时秒)
            for 信号值 in (signal.SIGTERM, signal.SIGKILL):
                try:
                    进程.wait(timeout=self.调用超时秒 if 信号值 == signal.SIGTERM else 2)
                    break
                except subprocess.TimeoutExpired:
                    self._杀进程组(信号值)
        证据 = self._退出证据()
        self.运行状态 = 状态_已停止
        self._清理管道()
        return {"成功": True, "消息": f"已关闭（退出证据 {证据}）"}

    def 状态(self):
        """状态()：运行状态/pid/重启次数/最近退出证据/证据清单。"""
        退出证据 = next((证据 for 证据 in reversed(self.证据列表) if 证据["类型"] == "退出"), None)
        return {"状态": self.运行状态, "pid": self.进程.pid if self.进程 else None,
                "重启次数": self.重启次数, "退出证据": 退出证据,
                "证据列表": list(self.证据列表), "工作目录": self.工作目录}
