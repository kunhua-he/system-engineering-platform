"""代码地图提供者 主进程管理器：子进程协议 + 稳定错误码（骨架占位）。"""
from __future__ import annotations
import json, os, subprocess, sys
from pathlib import Path

系统根 = "/Users/hekunhua/Documents/Agent/PHP/系统工程平台"
if 系统根 not in sys.path:
    sys.path.insert(0, 系统根)
from 公共契约.基础类型.结果类型 import 结果
from 公共契约.运行时.有界IO import 受限通信
from 公共契约.运行时 import 平台适配, 进程终止

包目录 = Path(__file__).resolve().parent.parent
子进程入口路径 = 包目录 / "实现" / "子进程入口.py"
可重试错误码 = ("超时", "提供者崩溃", "提供者不可用")


def _失败(错误码: str, 消息: str) -> 结果:
    return 结果.失败(错误码, 消息, 来源="代码地图提供者", 可重试=错误码 in 可重试错误码)


def _终止进程组(进程, 宽限秒: float = 1.0) -> None:
    """超时/异常时回收整个进程组（终止 → 宽限 → 强杀 → 复查）。

    唯一实现是 公共契约.运行时.进程终止.强制结束子进程；本模板不生成任何
    平台判断，进程组启动标志与整组回收都由 公共契约.运行时 收口。
    """
    进程终止.强制结束子进程(进程, 宽限秒=宽限秒, 等待秒=宽限秒)


def 执行任务(操作: str, 参数: dict, 超时秒: float = 60.0) -> 结果:
    """启动一次性骨架子进程执行任务；超时/崩溃/不可用逐类映射稳定错误码。"""
    try:
        进程 = subprocess.Popen([sys.executable, str(子进程入口路径)], stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                **平台适配.子进程组启动标志(), env=dict(os.environ))
    except OSError as 错误:
        return _失败("提供者不可用", f"无法启动子进程: {错误}")
    try:
        输出, _, 已超时, 已超限 = 受限通信(
            进程,
            输入=(json.dumps({"操作": 操作, "参数": 参数}, ensure_ascii=False) + "\n").encode(),
            超时秒=超时秒,
            终止回调=lambda: _终止进程组(进程),
        )
        if 已超时:
            return _失败("超时", f"执行超过 {超时秒} 秒")
        if 已超限:
            return _失败("超出限制", "子进程输出超过上限")
    except OSError as 错误:
        return _失败("提供者不可用", f"子进程通信失败: {错误}")
    if 进程.returncode:
        return _失败("提供者崩溃", f"子进程异常退出（退出码 {进程.returncode}）")
    try:
        响应 = json.loads(输出.decode("utf-8", errors="replace"))
    except json.JSONDecodeError:
        return _失败("提供者崩溃", "子进程返回无效响应")
    if not 响应.get("成功"):
        return _失败(str(响应.get("错误码") or "提供者崩溃"), str(响应.get("错误说明") or "执行失败"))
    return 结果.成功结果(响应.get("值"))


def 检查提供者(超时秒=30):
    """检查 codegraph 外部命令是否可用（真实版本探针）；缺失 → 提供者不可用"""
    return 执行任务("代码地图提供者.检查提供者", {}, 超时秒=超时秒)

def 查询项目地图状态(项目根目录, 超时秒=120):
    """只读查询某项目的代码地图索引状态：是否存在、文件/节点/边数量、索引时间、待同步变更数（不做任何写入）"""
    if 项目根目录 is None:
        return _失败("参数不合法", "缺少必填参数")
    return 执行任务("代码地图提供者.查询项目地图状态", {"项目根目录": 项目根目录}, 超时秒=超时秒)

def 重建项目地图索引(项目根目录, 重建方式='同步', 超时秒=1800):
    """对指定项目重建/同步代码地图索引（传项目根目录即可）：先探针提供者，再执行索引，返回同步前后的节点/文件数量与耗时，供调用方核实是否真的刷新"""
    if 项目根目录 is None:
        return _失败("参数不合法", "缺少必填参数")
    return 执行任务("代码地图提供者.重建项目地图索引", {"项目根目录": 项目根目录, "重建方式": 重建方式}, 超时秒=超时秒)

