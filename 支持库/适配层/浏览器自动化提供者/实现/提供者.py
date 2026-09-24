"""浏览器自动化受管 Provider：只负责外部 CLI/CDP 边界。"""

from __future__ import annotations

import ast
import contextlib
import json
import os
import shutil
import subprocess
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any

from 公共契约.基础类型.逻辑类型 import 真
from 公共契约.运行时 import 平台适配, 进程终止
from 支持库.适配层.浏览器自动化提供者.实现.执行器 import 有界执行


class 浏览器自动化提供者:
    """Browser Use CLI 外部适配器；不把第三方库导入底座主进程。"""

    def __init__(self, 命令: list[str] | None = None, 工作根: str = "") -> None:
        self.命令 = 命令 or self._发现命令()
        self.工作根 = Path(工作根 or tempfile.gettempdir()) / "底座浏览器会话"
        self.工作根.mkdir(parents=True, exist_ok=True)
        self.会话目录表: dict[str, Path] = {}
        self.会话进程表: dict[str, tuple[subprocess.Popen, int]] = {}

    @staticmethod
    def _搜索可执行(名称: str) -> str | None:
        候选 = [
            shutil.which(名称),
            str(Path.home() / ".local" / "bin" / 名称),
            str(Path.home() / ".hermes" / "bin" / 名称),
        ]
        return next((路径 for 路径 in 候选 if 路径 and Path(路径).is_file()), None)

    @classmethod
    def _发现命令(cls) -> list[str]:
        浏览器 = cls._搜索可执行("browser-use")
        if 浏览器:
            return [浏览器]
        uvx = cls._搜索可执行("uvx")
        return [uvx, "browser-use"] if uvx else []

    def 检查可用(self) -> dict[str, Any]:
        if not self.命令:
            return {"成功": False, "错误码": "提供者不可用", "错误说明": "browser-use/uvx 未安装"}
        return {"成功": True, "值": {"命令": self.命令}}

    @staticmethod
    def _发现浏览器() -> str | None:
        候选 = [
            os.environ.get("浏览器可执行路径", ""),
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "/Applications/Chromium.app/Contents/MacOS/Chromium",
        ]
        return next((路径 for 路径 in 候选 if 路径 and Path(路径).is_file()), None)

    def _启动浏览器(self, 会话名: str, 目录: Path, 超时秒: int,
                    视口宽: int = 0, 视口高: int = 0) -> tuple[subprocess.Popen, int] | None:
        浏览器 = self._发现浏览器()
        if not 浏览器:
            return None
        参数 = [
            浏览器, f"--user-data-dir={目录}", "--remote-debugging-port=0",
            "--headless=new", "--no-first-run", "--no-default-browser-check",
            "--disable-background-networking", "--disable-component-update",
            "--disable-default-apps", "--disable-sync", "--no-startup-window",
        ]
        # 视口（可选）：由调用方指定宽高，不传则用浏览器默认
        if isinstance(视口宽, int) and isinstance(视口高, int) and 视口宽 > 0 and 视口高 > 0:
            参数.append(f"--window-size={视口宽},{视口高}")
        try:
            进程 = subprocess.Popen(
                参数, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, **平台适配.子进程组启动标志(),
            )
        except OSError:
            return None
        端口文件 = 目录 / "DevToolsActivePort"
        截止 = time.monotonic() + max(1, min(int(超时秒), 30))
        while time.monotonic() < 截止:
            try:
                端口 = int(端口文件.read_text(encoding="utf-8").splitlines()[0])
                self.会话进程表[会话名] = (进程, 端口)
                return 进程, 端口
            except (OSError, ValueError, IndexError):
                if 进程.poll() is not None:
                    break
                time.sleep(0.1)
        self._回收进程(进程)
        return None

    @staticmethod
    @staticmethod
    def _回收进程(进程: subprocess.Popen) -> None:
        """回收子进程（终止→宽限→强杀→复查）：跨平台，终止失败不阻塞上层。

        原「POSIX 进程组强杀 / 非 POSIX terminate()」的平台分叉已删除——平台差异
        收口在 公共契约.运行时.进程终止，本处不判断平台。
        """
        if 进程.poll() is not None:
            return
        with contextlib.suppress(Exception):
            进程终止.强制结束子进程(进程, 宽限秒=2.0, 等待秒=2.0)

    def _会话环境(self, 会话名: str) -> dict[str, str]:
        环境 = dict(os.environ)
        受管路径 = [
            str(Path.home() / ".local" / "bin"),
            str(Path.home() / ".hermes" / "bin"),
            "/opt/homebrew/bin",
        ]
        现有路径 = 环境.get("PATH", "").split(os.pathsep)
        环境["PATH"] = os.pathsep.join(dict.fromkeys(受管路径 + 现有路径))
        环境["BU_NAME"] = 会话名
        if 会话名 in self.会话进程表:
            环境["BU_CDP_URL"] = f"http://127.0.0.1:{self.会话进程表[会话名][1]}"
        目录 = self.会话目录表.get(会话名)
        if 目录:
            环境["BH_AGENT_WORKSPACE"] = str(目录)
        return 环境

    def _执行代码(self, 代码: str, 会话名: str, 超时秒: float) -> dict[str, Any]:
        return 有界执行(self.命令, 代码, 环境=self._会话环境(会话名), 超时秒=超时秒)

    def 执行(self, 代码: str, *, 会话名: str = "", 超时秒: float = 30.0) -> dict[str, Any]:
        """受限执行入口，主要用于 Provider 自身连通性和超时回归。"""
        return self._执行代码(代码, 会话名, 超时秒)

    @staticmethod
    def _读取对象(输出: str) -> dict[str, Any]:
        for 行 in reversed((输出 or "").splitlines()):
            try:
                值 = ast.literal_eval(行.strip())
                if isinstance(值, dict):
                    return 值
            except (SyntaxError, ValueError):
                continue
        return {}

    def 建立连接(self, *, 超时秒: int = 30, 视口宽: int = 0, 视口高: int = 0) -> dict[str, Any]:
        可用 = self.检查可用()
        if not 可用["成功"]:
            return 可用
        会话名 = f"dizuo-browser-{uuid.uuid4().hex[:12]}"
        目录 = Path(tempfile.mkdtemp(prefix="会话-", dir=self.工作根))
        self.会话目录表[会话名] = 目录
        if "browser-use" in self.命令:
            if self._启动浏览器(会话名, 目录, 超时秒, 视口宽, 视口高) is None:
                self.会话目录表.pop(会话名, None)
                平台适配.清只读后删除树(目录, 忽略失败=真)
                return {"成功": False, "错误码": "提供者不可用", "错误说明": "独立Chromium未能启动或暴露CDP端口"}
        结果 = self._执行代码(
            '# 底座受管浏览器创建会话\nensure_real_tab()\nprint(page_info())',
            会话名, 超时秒)
        if not 结果["成功"]:
            self._关闭命名守护进程(会话名, 5)
            进程记录 = self.会话进程表.pop(会话名, None)
            if 进程记录:
                self._回收进程(进程记录[0])
            平台适配.清只读后删除树(目录, 忽略失败=真)
            self.会话目录表.pop(会话名, None)
            return 结果
        return {"成功": True, "值": {"会话名": 会话名, "页面": self._读取对象(结果["输出"])}}

    def 导航(self, *, 会话名: str, 地址: str, 超时秒: int = 30) -> dict[str, Any]:
        代码 = (
            "# 底座受管浏览器导航页面\n"
            f"goto_url({json.dumps(地址, ensure_ascii=False)})\n"
            "wait_for_load()\nprint(page_info())"
        )
        结果 = self._执行代码(代码, 会话名, 超时秒)
        return {"成功": True, "值": self._读取对象(结果["输出"])} if 结果["成功"] else 结果

    def 读取(self, *, 会话名: str, 内容类型: str = "文本", 最大长度: int = 20000) -> dict[str, Any]:
        if 内容类型 == "HTML":
            表达式 = f"document.documentElement ? document.documentElement.outerHTML.slice(0, {最大长度}) : ''"
        elif 内容类型 == "链接":
            # 可见链接清单：只取 href 与文本，不碰 cookie / localStorage
            表达式 = (
                "JSON.stringify(Array.from(document.querySelectorAll('a[href]'))"
                ".map(function(el){return {text:(el.textContent||'').trim().slice(0,200),"
                "href:el.getAttribute('href'),可见:el.offsetParent!==null}})"
                ".filter(function(l){return l.href&&l.text}).slice(0,100))"
            )
        else:
            表达式 = f"document.body ? document.body.innerText.slice(0, {最大长度}) : ''"
        代码 = (
            "# 底座受管浏览器读取页面\n"
            f"信息=page_info()\n内容=js({json.dumps(表达式)})\n"
            "print({'地址':信息.get('url',''),'标题':信息.get('title',''),'内容':内容})"
        )
        结果 = self._执行代码(代码, 会话名, 30)
        return {"成功": True, "值": self._读取对象(结果["输出"])} if 结果["成功"] else 结果

    def 操作(self, *, 会话名: str, 操作: str, 选择器: str = "", 文本: str = "", 超时秒: int = 30) -> dict[str, Any]:
        选择器代码 = json.dumps(选择器, ensure_ascii=False)
        文本代码 = json.dumps(文本, ensure_ascii=False)
        if 操作 == "点击":
            表达式 = f"document.querySelector({选择器代码})?.click()"
            动作 = f"js({json.dumps(表达式)})"
        elif 操作 == "填写":
            动作 = f"fill_input({选择器代码}, {文本代码})"
        elif 操作 == "按键":
            表达式 = f"document.activeElement?.dispatchEvent(new KeyboardEvent('keydown',{{key:{文本代码},bubbles:true}}))"
            动作 = f"js({json.dumps(表达式)})"
        elif 操作 == "等待":
            动作 = f"wait({max(0.01, min(float(文本 or 0.5), 30.0))})"
        else:
            return {"成功": False, "错误码": "操作不允许", "错误说明": f"不支持页面操作：{操作}"}
        代码 = f"# 底座受管浏览器页面操作\n{动作}\nprint(page_info())"
        结果 = self._执行代码(代码, 会话名, 超时秒)
        return {"成功": True, "值": self._读取对象(结果["输出"])} if 结果["成功"] else 结果

    def 截图(self, *, 会话名: str, 格式: str = "png", 超时秒: int = 30) -> dict[str, Any]:
        代码 = "# 底座受管浏览器获取截图\n路径=capture_screenshot()\nprint({'路径':路径})"
        结果 = self._执行代码(代码, 会话名, 超时秒)
        if not 结果["成功"]:
            return 结果
        值 = self._读取对象(结果["输出"])
        路径 = str(值.get("路径", ""))
        源文件 = Path(路径)
        目录 = self.会话目录表.get(会话名)
        if not 路径 or not 源文件.is_file() or 目录 is None:
            return {"成功": False, "错误码": "截图失败", "错误说明": "Provider未返回有效截图文件"}
        私有文件 = 目录 / f"截图-{uuid.uuid4().hex[:12]}.{格式}"
        try:
            shutil.copy2(源文件, 私有文件)
        except OSError as 错误:
            return {"成功": False, "错误码": "截图失败", "错误说明": f"截图私有化失败：{错误}"}
        return {"成功": True, "值": {"路径": str(私有文件), "字节数": 私有文件.stat().st_size, "格式": 格式}}

    def _关闭命名守护进程(self, 会话名: str, 超时秒: int) -> dict[str, Any]:
        配置根 = Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config")))
        运行根 = 配置根 / "browser-harness" / "runtime"
        pid文件 = 运行根 / f"bu-{会话名}.pid"
        if not pid文件.is_file():
            return {"成功": True, "值": {"状态": "守护进程不存在"}}
        try:
            记录 = json.loads(pid文件.read_text(encoding="utf-8"))
            if isinstance(记录, dict):
                pid = int(记录.get("pid", 0))
            elif isinstance(记录, int):
                pid = 记录
            else:
                return {"成功": False, "错误码": "资源未收敛", "错误说明": "PID文件格式不受支持"}
            if pid <= 0:
                return {"成功": False, "错误码": "资源未收敛", "错误说明": "PID文件未提供有效PID"}
            命令 = subprocess.check_output(
                ["ps", "-p", str(pid), "-o", "command="],
                text=True, timeout=3,
            ).strip()
            if not 命令:
                for 后缀 in (".pid", ".sock", ".spawnlock"):
                    with contextlib.suppress(OSError):
                        (运行根 / f"bu-{会话名}{后缀}").unlink()
                return {"成功": True, "值": {"状态": "守护进程已不存在且状态已清理", "PID": pid}}
            if "browser_harness.daemon" not in 命令:
                return {"成功": False, "错误码": "资源未收敛", "错误说明": "PID文件指向的进程不是Browser Harness守护进程"}
            预算秒 = float(max(1, min(int(超时秒), 15)))
            # 终止→宽限→强杀→复查的升级顺序由 公共契约.运行时.进程终止 一处持有；
            # 复查口径是**整组**（组长已回收但同组子孙仍在 ⇒ 未收敛），比改前的
            # 「单进程 进程存活」更严：守护进程若自建独立进程组，其同组子孙一并覆盖。
            已收敛 = 进程终止.结束并留痕(
                pid, 位置="浏览器自动化提供者.关闭命名守护进程",
                宽限秒=预算秒, 等待秒=预算秒)
            if not 已收敛:
                return {"成功": False, "错误码": "资源未收敛",
                        "错误说明": f"守护进程 {pid} 仍未收敛（含同组子孙）"}
            for 后缀 in (".pid", ".sock", ".spawnlock"):
                with contextlib.suppress(OSError):
                    (运行根 / f"bu-{会话名}{后缀}").unlink()
            return {"成功": True, "值": {"状态": "守护进程已回收", "PID": pid}}
        except (OSError, ValueError, KeyError, subprocess.SubprocessError) as 错误:
            return {"成功": False, "错误码": "资源未收敛", "错误说明": str(错误)}

    def 关闭会话(self, *, 会话名: str, 超时秒: int = 30) -> dict[str, Any]:
        agent = self._搜索可执行("agent-browser")
        npx = self._搜索可执行("npx")
        命令 = [agent, "--session", 会话名, "close"] if agent else ([npx, "--prefer-offline", "-y", "agent-browser", "--session", 会话名, "close"] if npx else [])
        if not 命令:
            return {"成功": False, "错误码": "提供者不可用", "错误说明": "agent-browser/npx 未安装"}
        环境 = self._会话环境(会话名)
        结果 = 有界执行(命令, 环境=环境, 超时秒=超时秒, 输出上限=65536)
        守护结果 = self._关闭命名守护进程(会话名, 超时秒)
        进程记录 = self.会话进程表.pop(会话名, None)
        if 进程记录:
            self._回收进程(进程记录[0])
        目录 = self.会话目录表.pop(会话名, None)
        if 目录:
            平台适配.清只读后删除树(目录, 忽略失败=真)
        if not 守护结果["成功"]:
            return 守护结果
        return {"成功": True, "值": {"状态": "已关闭"}} if 结果["成功"] else 结果
