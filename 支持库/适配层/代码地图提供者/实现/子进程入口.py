"""代码地图提供者 · 子进程入口：调 codegraph 外部命令建/查任意项目的索引。

协议：stdin 读一行 JSON ``{"操作": ..., "参数": {...}}``，stdout 写一行 JSON。
一次性子进程；异常一律转 JSON 错误返回，不把栈打给调用方。
**传项目根目录即可**——支持任意项目，不写死本仓。
"""

from __future__ import annotations

import os
import shutil
import sqlite3
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

# 仓库根自举：本文件是被 提供者.py 以 `sys.executable` 起的**独立子进程入口**，
# 必须能自己在 sys.path 上找到正式根 —— 不能依赖父进程的 PYTHONPATH / cwd
# （2026-09-19 实测：不注入 PYTHONPATH 时 `from 公共契约…` 直接 ModuleNotFoundError，
# 子进程退码 1，被上层误报成「提供者崩溃」，真实原因被掩盖）。
# 同目录族先例：MLXWhisper提供者/转写支持库 的子进程入口都写了同一段自举。
系统根 = Path(__file__).resolve().parents[4]
导入根 = 系统根.parent if 系统根.name == "平台客户端" else 系统根
if str(导入根) not in sys.path:
    sys.path.insert(0, str(导入根))

from 公共契约.基础类型.逻辑类型 import 真, 假
from 公共契约.运行时.数据库URI import 只读库URI实参

可执行名 = "codegraph"
兜底目录 = ("/usr/local/bin", "/opt/homebrew/bin")  # ★ node 常在 /usr/local/bin，不在 homebrew
重建方式表 = {"同步": "sync", "全量": "index"}
计数表名 = ("nodes", "files", "edges")  # 代码常量，非用户输入，不构成注入面

能力操作表 = ("代码地图提供者.查询项目地图状态", "代码地图提供者.重建项目地图索引",
            "代码地图提供者.检查提供者")


def _环境() -> dict:
    """拼 PATH：兜底目录前置，确保能连带找到 node。"""
    环境 = dict(os.environ)
    环境["PATH"] = ":".join(兜底目录) + ":" + 环境.get("PATH", "")
    return 环境


def _找可执行() -> str:
    """定位 codegraph：PATH 优先，再兜底 npm-global 与常见目录。"""
    命中 = shutil.which(可执行名)
    if 命中:
        return 命中
    候选 = [Path.home() / ".npm-global" / "bin" / 可执行名]
    候选 += [Path(目录) / 可执行名 for 目录 in 兜底目录]
    for 路径 in 候选:
        if 路径.is_file():
            return str(路径)
    return ""


def _库路径(项目根: Path) -> Path:
    return 项目根 / ".codegraph" / "codegraph.db"


def _计数(库路径: Path) -> dict:
    """只读统计地图规模；走唯一构造口径转义（含中文/`#`/`?` 路径），不建 side 文件。"""
    if not 库路径.is_file():
        return {"存在": False, "文件数": 0, "节点数": 0, "边数": 0}
    计数 = {}
    try:
        连接 = sqlite3.connect(只读库URI实参(库路径),
                              uri=True, timeout=5.0)
        try:
            for 表 in 计数表名:
                计数[表] = 连接.execute(f"SELECT COUNT(*) FROM {表}").fetchone()[0]
        finally:
            连接.close()
    except sqlite3.Error as 错误:
        return {"存在": True, "读取失败": str(错误)}
    return {"存在": True, "文件数": 计数["files"], "节点数": 计数["nodes"], "边数": 计数["edges"]}


def _取项目根(参数: dict) -> tuple[Path | None, dict | None]:
    """校验并返回 (项目根 Path, None)；不合法时返回 (None, 错误字典)。"""
    文本 = str(参数.get("项目根目录") or "").strip()
    if not 文本:
        return None, {"成功": 假, "错误码": "参数不合法", "错误说明": "缺少必填参数 项目根目录"}
    项目根 = Path(文本).expanduser()
    if not 项目根.is_dir():
        return None, {"成功": 假, "错误码": "参数不合法",
                      "错误说明": f"项目根目录不存在或不是目录: {项目根}"}
    return 项目根, None


def 检查提供者(参数: dict) -> dict:
    """真实版本探针；缺失即 提供者不可用，不伪装成功。"""
    可执行 = _找可执行()
    if not 可执行:
        return {"成功": 假, "错误码": "提供者不可用",
                "错误说明": f"未找到 {可执行名} 外部命令（已查 PATH 与 {'、'.join(兜底目录)}）"}
    try:
        探针 = subprocess.run([可执行, "--version"], capture_output=True, text=True,
                             timeout=30, env=_环境())
    except subprocess.TimeoutExpired:
        return {"成功": 假, "错误码": "超时", "错误说明": "版本探针超过 30 秒"}
    文本 = (探针.stdout or 探针.stderr or "").strip()
    return {"成功": 真, "值": {"可执行路径": 可执行, "版本": 文本.splitlines()[0] if 文本 else "",
                                "退出码": 探针.returncode}}


def 查询项目地图状态(参数: dict) -> dict:
    """只读：地图是否存在、规模、索引时间、待同步变更（codegraph status）。"""
    项目根, 错误 = _取项目根(参数)
    if 错误:
        return 错误
    库路径 = _库路径(项目根)
    规模 = _计数(库路径)
    索引时间 = ""
    if 库路径.is_file():
        索引时间 = datetime.fromtimestamp(库路径.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
    待同步, 状态输出 = "", ""
    可执行 = _找可执行()
    if 可执行 and 库路径.is_file():
        try:
            状态 = subprocess.run([可执行, "status", "."], cwd=str(项目根), capture_output=True,
                                 text=True, timeout=float(参数.get("超时秒") or 120), env=_环境())
            状态输出 = (状态.stdout or 状态.stderr or "").strip()[-600:]
            段 = 状态输出.split("Pending Changes:", 1)
            待同步 = 段[1].strip()[:200] if len(段) > 1 else ""
        except subprocess.TimeoutExpired:
            状态输出 = "（status 超时）"
    return {"成功": 真, "值": {"项目根目录": str(项目根), "地图路径": str(库路径),
                                "索引时间": 索引时间, **规模,
                                "待同步变更": 待同步, "状态输出": 状态输出}}


def 重建项目地图索引(参数: dict) -> dict:
    """对指定项目重建/同步索引，返回前后规模对比，供调用方核实是否真刷新。"""
    项目根, 错误 = _取项目根(参数)
    if 错误:
        return 错误
    重建方式 = str(参数.get("重建方式") or "同步").strip()
    if 重建方式 not in 重建方式表:
        return {"成功": 假, "错误码": "参数不合法",
                "错误说明": f"重建方式 只能是 {' / '.join(重建方式表)}，实际 {重建方式!r}"}
    可执行 = _找可执行()
    if not 可执行:
        return {"成功": 假, "错误码": "提供者不可用", "错误说明": f"未找到 {可执行名} 外部命令"}
    库路径 = _库路径(项目根)
    之前 = _计数(库路径)
    子命令 = 重建方式表[重建方式]
    开始 = time.monotonic()
    try:
        执行 = subprocess.run([可执行, 子命令, "."], cwd=str(项目根), capture_output=True, text=True,
                             timeout=float(参数.get("超时秒") or 1800), env=_环境())
    except subprocess.TimeoutExpired:
        return {"成功": 假, "错误码": "超时",
                "错误说明": f"codegraph {子命令} 超过 {参数.get('超时秒') or 1800} 秒"}
    耗时秒 = round(time.monotonic() - 开始, 2)
    if 执行.returncode != 0:
        尾巴 = (执行.stderr or 执行.stdout or "").strip()[-500:]
        return {"成功": 假, "错误码": "执行失败",
                "错误说明": f"codegraph {子命令} 退出码 {执行.returncode}: {尾巴}"}
    之后 = _计数(库路径)
    return {"成功": 真, "值": {"项目根目录": str(项目根), "重建方式": 重建方式, "子命令": 子命令,
                                "耗时秒": 耗时秒, "之前规模": 之前, "之后规模": 之后,
                                "是否刷新": 之前 != 之后,
                                "输出": (执行.stdout or "").strip()[-800:]},
            "之前规模": 之前, "之后规模": 之后}


_操作实现表 = {
    "代码地图提供者.检查提供者": 检查提供者,
    "代码地图提供者.查询项目地图状态": 查询项目地图状态,
    "代码地图提供者.重建项目地图索引": 重建项目地图索引,
}


from 公共契约.运行时 import 子进程协议  # noqa: E402 - 单发协议唯一实现（平台根已在上方自举入 sys.path）


def _收参数(函数):
    """本腿实现函数收「参数」子字典；协议处理函数收整条请求，故逐条包一层。"""

    def 处理(请求: dict):
        return 函数(请求.get("参数") or {})

    return 处理


def _前置() -> str | None:
    """禁用库开关：置 1 即整条腿不可用（回 提供者不可用）。"""
    if os.environ.get("代码地图提供者_禁用库") == "1":
        return "代码地图提供者 被禁用"
    return None


def 主循环() -> int:
    """单发协议主循环；四类收口与信封组装唯一实现在 公共契约/运行时/子进程协议。"""
    return 子进程协议.单发主循环(
        {名: _收参数(函数) for 名, 函数 in _操作实现表.items()},
        入口名="代码地图提供者",
        前置=_前置,
        崩溃错误码="执行失败",
        崩溃说明前缀="",
        测试超时环境变量="代码地图提供者_测试超时",
    )


if __name__ == "__main__":
    主循环()
    sys.stdout.flush()
    os._exit(0)
